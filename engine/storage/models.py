"""
SQLAlchemy models for the CorpusMind storage layer (§7.3).

A project contains text corpora (and, in Phase 4, image sets). A corpus
contains documents. A document is parsed into tokens with lemma/POS/morph/
dependency annotations (CoNLL-U-compatible). Every corpus is versioned —
re-running the pipeline with an upgraded tagger creates a new annotation
version rather than silently overwriting the old one (§4.8).
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _uuid() -> str:
    return uuid.uuid4().hex[:16]


class Base(DeclarativeBase):
    """Declarative base for all CorpusMind models."""


# --------------------------------------------------------------------------- #
# Projects & corpora
# --------------------------------------------------------------------------- #


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    language: Mapped[str] = mapped_column(String(8), default="en")  # ISO 639-1
    visibility: Mapped[str] = mapped_column(String(16), default="private")  # private | public
    metadata_schema: Mapped[dict] = mapped_column(JSON, default=dict)  # user-definable
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    corpora: Mapped[list[Corpus]] = relationship(back_populates="project", cascade="all, delete-orphan")


class Corpus(Base):
    __tablename__ = "corpora"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    language: Mapped[str] = mapped_column(String(8), default="en")
    # The pipeline recipe: tokenizer/tagger/parser + versions (§8.1)
    pipeline_recipe: Mapped[dict] = mapped_column(JSON, default=dict)
    # Aggregate stats cache (token count, type count, etc.) — recomputed on ingestion
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    project: Mapped[Project] = relationship(back_populates="corpora")
    documents: Mapped[list[Document]] = relationship(back_populates="corpus", cascade="all, delete-orphan")
    annotation_versions: Mapped[list[AnnotationVersion]] = relationship(back_populates="corpus", cascade="all, delete-orphan")


class Document(Base):
    """A source file ingested into a corpus. Stores the cleaned text;
    token-level annotations live in the AnnotationVersion / Token tables."""
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=_uuid)
    corpus_id: Mapped[str] = mapped_column(ForeignKey("corpora.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    format: Mapped[str] = mapped_column(String(16), default="txt")  # txt|docx|pdf|html|xml|csv
    encoding: Mapped[str] = mapped_column(String(16), default="utf-8")
    detected_language: Mapped[str | None] = mapped_column(String(8), nullable=True)
    raw_size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    cleaned_text: Mapped[str] = mapped_column(Text, default="")
    # User-definable metadata (genre, year, author, register, discipline, etc.)
    # NB: 'metadata' is reserved by SQLAlchemy's Declarative API, so we use 'meta'.
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    corpus: Mapped[Corpus] = relationship(back_populates="documents")


class AnnotationVersion(Base):
    """A versioned annotation pass over a corpus (§4.8 reproducibility).

    Re-running the pipeline with an upgraded tagger creates a new row here
    rather than overwriting the old one. The active version is the one with
    the highest `created_at` for a given corpus.
    """
    __tablename__ = "annotation_versions"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=_uuid)
    corpus_id: Mapped[str] = mapped_column(ForeignKey("corpora.id", ondelete="CASCADE"), index=True)
    version_label: Mapped[str] = mapped_column(String(64), default="v1")
    # The exact spaCy/Stanza/etc. model name + version used
    model_name: Mapped[str] = mapped_column(String(128), default="spacy:en_core_web_sm")
    model_version: Mapped[str] = mapped_column(String(64), default="")
    tokenizer: Mapped[str] = mapped_column(String(64), default="spacy-default")
    tagger: Mapped[str] = mapped_column(String(64), default="spacy-default")
    parser: Mapped[str] = mapped_column(String(64), default="spacy-default")
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    type_count: Mapped[int] = mapped_column(Integer, default=0)
    sentence_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    corpus: Mapped[Corpus] = relationship(back_populates="annotation_versions")
    tokens: Mapped[list[Token]] = relationship(back_populates="version", cascade="all, delete-orphan")


class Token(Base):
    """A single token with its annotations. CoNLL-U-compatible schema."""
    __tablename__ = "tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("annotation_versions.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    sentence_idx: Mapped[int] = mapped_column(Integer, default=0, index=True)  # sentence number within document
    token_idx: Mapped[int] = mapped_column(Integer, default=0)  # token number within sentence
    text: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    lemma: Mapped[str] = mapped_column(String(255), default="", index=True)
    pos: Mapped[str] = mapped_column(String(32), default="", index=True)        # UPOS
    pos_fine: Mapped[str] = mapped_column(String(32), default="")               # XPOS
    morph: Mapped[str] = mapped_column(String(255), default="")                 # Feats
    dep_head: Mapped[int] = mapped_column(Integer, default=0)                   # 0 = root
    dep_rel: Mapped[str] = mapped_column(String(32), default="")                # UD relation
    is_punct: Mapped[bool] = mapped_column(default=False)
    is_stop: Mapped[bool] = mapped_column(default=False)

    version: Mapped[AnnotationVersion] = relationship(back_populates="tokens")

    __table_args__ = (
        Index("ix_tokens_version_text", "version_id", "text"),
        Index("ix_tokens_version_lemma", "version_id", "lemma"),
        Index("ix_tokens_version_pos", "version_id", "pos"),
        Index("ix_tokens_version_doc_sent", "version_id", "document_id", "sentence_idx", "token_idx"),
    )


# --------------------------------------------------------------------------- #
# Conversations (AI Assistant audit trail — §11)
# --------------------------------------------------------------------------- #


class Conversation(Base):
    """Persisted conversation. Phase 0 had these in-memory; Phase 1 persists."""
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=_uuid)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(32), default="ollama")
    model: Mapped[str] = mapped_column(String(128), default="")
    framework: Mapped[str | None] = mapped_column(String(64), nullable=True)  # active framework lens
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    turns: Mapped[list[ConversationTurn]] = relationship(back_populates="conversation", cascade="all, delete-orphan", order_by="ConversationTurn.idx")


class ConversationTurn(Base):
    """One turn in a conversation. Carries the load-bearing `grounded` flag
    plus the evidence IDs the assistant cited (§11.1)."""
    __tablename__ = "conversation_turns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    idx: Mapped[int] = mapped_column(Integer, default=0)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant | system | tool
    content: Mapped[str] = mapped_column(Text, default="")
    grounded: Mapped[bool] = mapped_column(default=False)
    tool_calls: Mapped[list] = mapped_column(JSON, default=list)
    evidence: Mapped[list] = mapped_column(JSON, default=list)  # [{kind, ref, snippet}]
    elapsed_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    conversation: Mapped[Conversation] = relationship(back_populates="turns")


# --------------------------------------------------------------------------- #
# Images (Phase 4 — Suite B Vision)
# --------------------------------------------------------------------------- #


class ImageSet(Base):
    """A set of images within a corpus (Phase 4)."""
    __tablename__ = "image_sets"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=_uuid)
    corpus_id: Mapped[str] = mapped_column(ForeignKey("corpora.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    images: Mapped[list[Image]] = relationship(back_populates="image_set", cascade="all, delete-orphan")


class Image(Base):
    """An ingested image with its analysis results."""
    __tablename__ = "images"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=_uuid)
    image_set_id: Mapped[str] = mapped_column(ForeignKey("image_sets.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    format: Mapped[str] = mapped_column(String(16), default="jpg")
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    # The raw image bytes are stored on disk (data_dir/images/{id}.{ext}),
    # not in the DB — keeps the DB lean.
    storage_path: Mapped[str] = mapped_column(String(1024), default="")
    # Cached analysis results (colour, composition, OCR, visual grammar)
    analysis: Mapped[dict] = mapped_column(JSON, default=dict)
    # Optional co-occurring text (caption, alt-text, article body)
    caption: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    image_set: Mapped[ImageSet] = relationship(back_populates="images")
