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
        # data resolution which looks for the model in spaCy's data path.
        # In a PyInstaller frozen environment, this path resolution can fail
        # with "[E050] Can't find model 'en_core_web_sm'". The fix is to
        # import the model package directly and pass the loaded module to
        # spacy.load() — this bypasses the data-path resolution entirely.
        try:
            self._nlp = spacy.load(self._model_name)
        except OSError:
            # Fallback: import the model package directly and use its path.
            # This works in PyInstaller bundles where the model is collected
            # as a package but spaCy's data-path resolution doesn't find it.
            log.info("spacy_fallback_import", model=self._model_name)
            try:
                model_module = __import__(self._model_name)
                model_path = model_module.__file__
                if model_path:
                    import os
                    model_dir = os.path.dirname(model_path)
                    self._nlp = spacy.load(model_dir)
                else:
                    raise
            except (ImportError, OSError) as e2:
                log.error("spacy_load_failed", model=self._model_name,
                          error=str(e2),
                          hint="The spaCy model is not installed. In development, run: "
                               "python -m spacy download en_core_web_sm")
                raise ValueError(
                    f"spaCy model '{self._model_name}' could not be loaded. "
                    f"In development, install it with: "
                    f"python -m spacy download {self._model_name}"
                ) from e2

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
