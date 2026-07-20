"""
General-language NLP pipeline (§8.1).

Wraps spaCy (the default) so the rest of the engine doesn't care which
backend produced the annotations. Phase 3 will add a Stanza backend and an
Arabic-specific backend (CAMeL Tools / SinaTools); they'll all conform to
the same `Pipeline` interface and emit the same CoNLL-U-compatible token
rows that storage/models.Token expects.
"""
from __future__ import annotations

import functools
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

from app.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ParsedToken:
    """One token with its annotations — produced by a pipeline, consumed by storage."""
    text: str
    lemma: str
    pos: str          # UPOS
    pos_fine: str     # XPOS
    morph: str        # UD features, "Feature=Value|Feature2=Value2"
    dep_head: int     # 1-indexed; 0 = root
    dep_rel: str      # UD relation
    is_punct: bool
    is_stop: bool


@dataclass(frozen=True, slots=True)
class ParsedSentence:
    tokens: list[ParsedToken]


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    sentences: list[ParsedSentence]

    @property
    def token_count(self) -> int:
        return sum(len(s.tokens) for s in self.sentences)

    @property
    def type_count(self) -> int:
        return len({t.text for s in self.sentences for t in s.tokens})


@dataclass(frozen=True, slots=True)
class PipelineInfo:
    """Reproducibility info — pinned to a corpus version (§4.8)."""
    backend: str       # "spacy" | "stanza" | "camel" | ...
    model_name: str    # e.g. "en_core_web_sm"
    model_version: str
    spacy_version: str
    language: str


class Pipeline(Protocol):
    def info(self) -> PipelineInfo: ...
    def parse(self, text: str) -> Iterator[ParsedSentence]: ...
    def parse_document(self, text: str) -> ParsedDocument: ...


# --------------------------------------------------------------------------- #
# spaCy implementation
# --------------------------------------------------------------------------- #


class SpaCyPipeline:
    """Wraps a spaCy Language object.

    Loads the model lazily on first use so the engine starts fast even when
    a project hasn't been opened yet. spaCy models are heavy (~50 MB).
    """

    def __init__(self, model_name: str = "en_core_web_sm", language: str = "en") -> None:
        self._model_name = model_name
        self._language = language
        self._nlp = None
        self._info: PipelineInfo | None = None

    def _load(self) -> None:
        if self._nlp is not None:
            return
        import spacy
        log.info("spacy_loading", model=self._model_name)

        # PyInstaller FIX: spacy.load("en_core_web_sm") uses spaCy's
        # data-path resolution which can fail in frozen environments.
        # Try multiple strategies in order:
        #   1. spacy.load(model_name) — standard, works in dev
        #   2. import the model package + spacy.load(package_path)
        #   3. Search sys.path for the model package dir
        #   4. spacy.blank(lang) with tokenizer only — degraded fallback

        nlp = None

        # Strategy 1: standard spaCy load
        try:
            nlp = spacy.load(self._model_name)
        except OSError:
            log.info("spacy_strategy1_failed", model=self._model_name)

        # Strategy 2: import the package + load from its directory
        if nlp is None:
            try:
                import importlib
                mod = importlib.import_module(self._model_name)
                if hasattr(mod, "__path__"):
                    model_path = list(mod.__path__)[0]
                    log.info("spacy_strategy2_import", model_path=model_path)
                    nlp = spacy.load(model_path)
            except (ImportError, OSError, Exception) as e:
                log.info("spacy_strategy2_failed", error=str(e))

        # Strategy 3: search for the model in common paths (PyInstaller _internal)
        if nlp is None:
            try:
                import os
                import sys
                # In PyInstaller, the _internal dir is where packages live
                for search_dir in sys.path + [os.path.join(os.path.dirname(sys.executable), "_internal")]:
                    model_dir = os.path.join(search_dir, self._model_name)
                    if os.path.isdir(model_dir):
                        meta_path = os.path.join(model_dir, "meta.json")
                        if os.path.exists(meta_path):
                            log.info("spacy_strategy3_found", model_dir=model_dir)
                            nlp = spacy.load(model_dir)
                            break
            except Exception as e:
                log.info("spacy_strategy3_failed", error=str(e))

        # Strategy 4: degraded fallback — blank model with tokenizer only
        if nlp is None:
            log.warning(
                "spacy_model_not_found_fallback_blank",
                model=self._model_name,
                hint="Using spacy.blank() — tokenization only, no POS/lemma/parse. "
                     "The full model was not bundled correctly in PyInstaller.",
            )
            nlp = spacy.blank(self._language)
            # Add a sentencizer so we at least get sentence boundaries
            if "sentencizer" not in nlp.pipe_names:
                nlp.add_pipe("sentencizer")

        self._nlp = nlp

        # Sentencizer is built into most models, but add it defensively for
        # blank/minimal models. Also check for "parser" since the parser
        # provides sentence boundaries too.
        has_sent_pipe = any(
            p in self._nlp.pipe_names
            for p in ("senter", "sentencizer", "parser")
        )
        if not has_sent_pipe:
            self._nlp.add_pipe("sentencizer")
        spacy_version = spacy.__version__
        model_meta = self._nlp.meta
        self._info = PipelineInfo(
            backend="spacy",
            model_name=self._model_name,
            model_version=model_meta.get("version", ""),
            spacy_version=spacy_version,
            language=self._language,
        )
        log.info("spacy_loaded", model=self._model_name, version=self._info.model_version, spacy=spacy_version)

    def info(self) -> PipelineInfo:
        self._load()
        assert self._info is not None
        return self._info

    def parse(self, text: str) -> Iterator[ParsedSentence]:
        self._load()
        assert self._nlp is not None
        # Disable pipes we don't need to keep throughput high.
        # NER, entity_linker, entity_ruler, spancat, textcat are not used by
        # CorpusMind's token storage model — disabling them gives ~25-40% speedup.
        # We keep: tokenizer, tagger, morphologizer, lemmatizer, parser, attribute_ruler
        # (attribute_ruler is needed by the rule-based lemmatizer for POS assignment).
        disable = [
            name for name in self._nlp.pipe_names
            if name in {"ner", "entity_linker", "entity_ruler", "spancat", "textcat"}
        ]
        for doc in self._nlp.pipe([text], disable=disable):
            for sent in doc.sents:
                tokens: list[ParsedToken] = []
                for _i, tok in enumerate(sent, start=1):
                    head_idx = tok.head.i - sent.start + 1 if tok.head is not tok else 0
                    # Preserve surface form when lemmatizer produces nothing
                    # (e.g., punctuation, unknown words). Don't silently lowercase.
                    lemma = tok.lemma_ if tok.lemma_ else tok.text
                    tokens.append(ParsedToken(
                        text=tok.text,
                        lemma=lemma,
                        pos=tok.pos_ or "X",
                        pos_fine=tok.tag_ or "",
                        morph=str(tok.morph) if tok.morph else "",
                        dep_head=head_idx,
                        dep_rel=tok.dep_ or "dep",
                        is_punct=tok.is_punct,
                        is_stop=tok.is_stop,
                    ))
                yield ParsedSentence(tokens=tokens)

    def parse_document(self, text: str) -> ParsedDocument:
        return ParsedDocument(sentences=list(self.parse(text)))


# --------------------------------------------------------------------------- #
# Registry: maps (backend, language) → a constructed pipeline
# --------------------------------------------------------------------------- #


@functools.lru_cache(maxsize=8)
def get_pipeline(backend: str = "spacy", language: str = "en", model_name: str | None = None) -> Pipeline:
    """Return a cached pipeline instance.

    For Arabic (language == 'ar'), this delegates to the CAMeL Tools
    pipeline (nlp/arabic/pipeline.py) which provides proper Arabic
    morphology, POS, lemma, and root extraction.

    For other languages, it uses spaCy with the correct model naming
    convention: most languages use `_core_news_sm` (not `_core_web_sm`).
    Only English and Chinese use `_core_web_sm`.

    Raises ValueError with an actionable message if the language has
    no available spaCy model.
    """
    # Arabic: delegate to the CAMeL Tools pipeline
    if language == "ar" and backend == "spacy":
        try:
            from nlp.arabic.pipeline import ArabicPipeline
            return ArabicPipeline()
        except ImportError as exc:
            raise ValueError(
                "Arabic NLP requires CAMeL Tools. Install with: "
                "pip install camel-tools && camel_data -i morphology-db-msa-r13"
            ) from exc

    if backend == "spacy":
        if model_name is None:
            # English and Chinese use _core_web_sm; everything else uses _core_news_sm
            if language == "en":
                model_name = "en_core_web_sm"
            elif language == "zh":
                model_name = "zh_core_web_sm"
            else:
                model_name = f"{language}_core_news_sm"
        return SpaCyPipeline(model_name=model_name, language=language)
    raise ValueError(f"Unknown NLP backend: {backend}")
