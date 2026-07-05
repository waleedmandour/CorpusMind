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
from dataclasses import dataclass
from typing import Iterator, Protocol

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
        self._nlp = spacy.load(self._model_name)
        # Sentencizer is built into most models, but add it defensively for
        # blank/minimal models.
        if "senter" not in self._nlp.pipe_names and "sentencizer" not in self._nlp.pipe_names:
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
        # Use nlp.pipe with as_tuples=False for a single doc.
        # Disable pipes we don't need to keep throughput high.
        for doc in self._nlp.pipe([text], disable=[]):
            for sent in doc.sents:
                tokens: list[ParsedToken] = []
                for i, tok in enumerate(sent, start=1):
                    head_idx = tok.head.i - sent.start + 1 if tok.head is not tok else 0
                    tokens.append(ParsedToken(
                        text=tok.text,
                        lemma=tok.lemma_ or tok.text.lower(),
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
def get_pipeline(backend: str = "spacy", language: str = "en", model_name: str | None = None) -> "Pipeline":
    """Return a cached pipeline instance.

    Defaults: spaCy + en_core_web_sm. Phase 3 will branch on language == 'ar'
    and load the Arabic backend (CAMeL Tools / SinaTools).
    """
    if backend == "spacy":
        if model_name is None:
            model_name = "en_core_web_sm" if language == "en" else f"{language}_core_web_sm"
        return SpaCyPipeline(model_name=model_name, language=language)
    raise ValueError(f"Unknown NLP backend: {backend}")
