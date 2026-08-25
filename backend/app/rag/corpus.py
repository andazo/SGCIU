from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pypdf import PdfReader
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.ai.embeddings import EmbeddingProvider, get_legal_embedding_provider
from app.config import Settings, get_settings
from app.models import LegalChunk, LegalDocument
from app.schemas import (
    LegalCorpusDocumentStatus,
    LegalCorpusStatus,
    LegalIndexingResult,
)

ARTICLE_HEADING_PATTERN = re.compile(
    r"(?im)^(?:art[ií]culo|art\.)\s*(?:n[.º°o]\s*)?(\d+(?:\s*(?:bis|ter))?)"
)
SECTION_PATTERN = re.compile(
    r"(?im)^(?P<section>(?:T[IÍ]TULO|CAP[IÍ]TULO|SECCI[OÓ]N)\s+[^\n]{1,160})$"
)
LEGAL_INDEX_VERSION = "legal-index-v1"

SOURCE_PROFILES: dict[str, dict[str, object]] = {
    "national_legislation": {
        "legal_force": "binding",
        "authority_scope": "general_national",
        "allowed_classifications": ["legal_obligation"],
    },
    "executive_regulation": {
        "legal_force": "binding",
        "authority_scope": "general_national",
        "allowed_classifications": ["legal_obligation"],
    },
    "municipal_enabling_law": {
        "legal_force": "binding",
        "authority_scope": "municipal_national",
        "allowed_classifications": ["legal_obligation", "municipal_authority"],
    },
    "municipal_regulation": {
        "legal_force": "binding",
        "authority_scope": "municipal_flores",
        "allowed_classifications": ["legal_obligation", "municipal_authority"],
    },
    "national_police_regulation": {
        "legal_force": "binding",
        "authority_scope": "national_police_only",
        "allowed_classifications": ["legal_obligation"],
    },
    "operational_protocol": {
        "legal_force": "operational_guidance",
        "authority_scope": "issuing_institution_only",
        "allowed_classifications": ["recommended_procedure"],
    },
}


class ManifestDocument(BaseModel):
    model_config = ConfigDict(extra="allow")

    key: str
    title: str
    short_title: str
    filename: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    authority: str
    document_type: str
    source_category: Literal[
        "national_legislation",
        "executive_regulation",
        "municipal_enabling_law",
        "municipal_regulation",
        "national_police_regulation",
        "operational_protocol",
    ]
    priority: int = Field(default=3, ge=1, le=5)
    notes: str | None = None
    source_url: str | None = None

    def source_profile(self) -> dict[str, object]:
        try:
            return SOURCE_PROFILES[self.source_category]
        except KeyError as exc:
            raise ValueError(
                f"Categoría jurídica no soportada: {self.source_category}"
            ) from exc


class CorpusManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    corpus_id: str
    version: str
    jurisdiction: str
    language: str
    description: str
    citation_policy: str
    known_gaps: list[str] = Field(default_factory=list)
    documents: list[ManifestDocument]


@dataclass(frozen=True, slots=True)
class ExtractedPage:
    page_number: int
    printed_page_label: str | None
    text: str


@dataclass(frozen=True, slots=True)
class ChunkDraft:
    chunk_index: int
    page_number: int
    printed_page_label: str | None
    section_path: str | None
    article_references: tuple[str, ...]
    content: str
    estimated_tokens: int


def estimate_tokens(text: str) -> int:
    """Conservative tokenizer-independent estimate suitable for chunk boundaries."""
    return max(1, math.ceil(len(text) / 4))


def load_manifest(corpus_path: Path) -> CorpusManifest:
    manifest_path = corpus_path / "manifest.json"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"No se pudo leer el manifiesto legal: {manifest_path}") from exc
    manifest = CorpusManifest.model_validate(payload)
    keys = [document.key for document in manifest.documents]
    if len(keys) != len(set(keys)):
        raise RuntimeError("El manifiesto legal contiene claves de documento duplicadas.")
    for document in manifest.documents:
        document.source_profile()
    return manifest


def _document_metadata(manifest: CorpusManifest, item: ManifestDocument) -> dict[str, object]:
    return {
        "corpus_id": manifest.corpus_id,
        "language": manifest.language,
        "notes": item.notes,
        "source_url": item.source_url,
        "citation_policy": manifest.citation_policy,
        "indexer_version": LEGAL_INDEX_VERSION,
        "source_category": item.source_category,
        **item.source_profile(),
    }


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _normalize_page_text(text: str) -> str:
    value = unicodedata.normalize("NFKC", text or "")
    value = value.replace("\u00ad", "")
    value = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", value)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in value.splitlines()]
    return "\n".join(lines).strip()


def _repeated_margin_lines(pages: list[str]) -> set[str]:
    if len(pages) < 4:
        return set()
    candidates: Counter[str] = Counter()
    for page in pages:
        lines = [line for line in page.splitlines() if line]
        for line in [*lines[:4], *lines[-4:]]:
            if 3 <= len(line) <= 140:
                candidates[line] += 1
    threshold = max(3, math.ceil(len(pages) * 0.3))
    return {line for line, count in candidates.items() if count >= threshold}


def extract_pdf_pages(path: Path) -> list[ExtractedPage]:
    try:
        reader = PdfReader(path, strict=False)
    except Exception as exc:
        raise RuntimeError(f"No se pudo abrir el PDF {path.name}.") from exc
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:
            raise RuntimeError(f"El PDF {path.name} está cifrado.") from exc
    raw_pages = [_normalize_page_text(page.extract_text() or "") for page in reader.pages]
    repeated = _repeated_margin_lines(raw_pages)
    labels = getattr(reader, "page_labels", None) or []
    extracted: list[ExtractedPage] = []
    for index, raw in enumerate(raw_pages):
        cleaned_lines = [line for line in raw.splitlines() if line not in repeated]
        cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(cleaned_lines)).strip()
        label = str(labels[index]) if index < len(labels) else None
        extracted.append(
            ExtractedPage(
                page_number=index + 1,
                printed_page_label=label if label and label != str(index + 1) else None,
                text=cleaned,
            )
        )
    return extracted


def _split_long_text(text: str, target_tokens: int, overlap_tokens: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(words):
        end = start
        while end < len(words):
            candidate = " ".join(words[start : end + 1])
            if end > start and estimate_tokens(candidate) > target_tokens:
                break
            end += 1
        if end == start:
            end += 1
        chunk = " ".join(words[start:end]).strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(words):
            break
        overlap_start = end
        while overlap_start > start:
            candidate = " ".join(words[overlap_start - 1 : end])
            if estimate_tokens(candidate) > overlap_tokens:
                break
            overlap_start -= 1
        start = overlap_start if overlap_start < end else end
    return chunks


def _article_references(text: str, inherited: str | None) -> tuple[str, ...]:
    references = [
        f"Artículo {match.group(1).strip()}" for match in ARTICLE_HEADING_PATTERN.finditer(text)
    ]
    if inherited and not references:
        references.append(inherited)
    return tuple(dict.fromkeys(references))


def chunk_pages(
    pages: list[ExtractedPage],
    *,
    target_tokens: int,
    overlap_tokens: int,
) -> list[ChunkDraft]:
    """Creates article-aware chunks that never cross a physical PDF page."""
    drafts: list[ChunkDraft] = []
    active_article: str | None = None
    active_section: str | None = None
    for page in pages:
        if len(page.text) < 40:
            continue
        section_matches = list(SECTION_PATTERN.finditer(page.text))
        if section_matches:
            active_section = section_matches[-1].group("section").strip()
        article_matches = list(ARTICLE_HEADING_PATTERN.finditer(page.text))
        boundaries = [match.start() for match in article_matches]
        segments: list[str] = []
        if boundaries:
            if boundaries[0] > 0:
                segments.append(page.text[: boundaries[0]])
            for position, start in enumerate(boundaries):
                end = boundaries[position + 1] if position + 1 < len(boundaries) else len(page.text)
                segments.append(page.text[start:end])
        else:
            segments = [page.text]
        for segment in segments:
            segment = segment.strip()
            if len(segment) < 40:
                continue
            found_articles = _article_references(segment, active_article)
            explicit_articles = [
                f"Artículo {match.group(1).strip()}"
                for match in ARTICLE_HEADING_PATTERN.finditer(segment)
            ]
            if explicit_articles:
                active_article = explicit_articles[-1]
            for content in _split_long_text(segment, target_tokens, overlap_tokens):
                drafts.append(
                    ChunkDraft(
                        chunk_index=len(drafts),
                        page_number=page.page_number,
                        printed_page_label=page.printed_page_label,
                        section_path=active_section,
                        article_references=found_articles,
                        content=content,
                        estimated_tokens=estimate_tokens(content),
                    )
                )
    return drafts


class LegalCorpusIndexer:
    def __init__(
        self,
        db: Session,
        settings: Settings | None = None,
        embedding_provider: EmbeddingProvider | None = None,
    ):
        self.db = db
        self.settings = settings or get_settings()
        self.embedding_provider = embedding_provider
        self.corpus_path = self.settings.legal_rag_corpus_path

    def _provider(self) -> EmbeddingProvider:
        if self.embedding_provider is None:
            self.embedding_provider = get_legal_embedding_provider(self.settings)
        return self.embedding_provider

    def index_all(
        self,
        *,
        force: bool = False,
        progress: Callable[[int, int, str, str], None] | None = None,
    ) -> LegalIndexingResult:
        manifest = load_manifest(self.corpus_path)
        self.db.scalar(select(func.count(LegalDocument.id)))
        indexed = skipped = failed = embeddings_created = 0
        failures: list[str] = []
        total = len(manifest.documents)
        manifest_keys = {item.key for item in manifest.documents}
        for position, item in enumerate(manifest.documents, start=1):
            try:
                created = self._index_document(manifest, item, force=force)
                if created is None:
                    skipped += 1
                    status = "sin cambios"
                else:
                    indexed += 1
                    embeddings_created += created
                    status = f"{created} embeddings"
                if progress:
                    progress(position, total, item.key, status)
            except Exception as exc:
                self.db.rollback()
                failed += 1
                message = f"{item.key}: {type(exc).__name__}: {exc}"
                failures.append(message)
                if progress:
                    progress(position, total, item.key, "falló")
        inactive = self.db.scalars(
            select(LegalDocument).where(LegalDocument.document_key.not_in(manifest_keys))
        )
        for document in inactive:
            document.status = "inactive"
        self.db.commit()
        return LegalIndexingResult(
            corpus_version=manifest.version,
            documents_found=total,
            documents_indexed=indexed,
            documents_skipped=skipped,
            documents_failed=failed,
            embeddings_created=embeddings_created,
            failures=failures,
        )

    def _index_document(
        self,
        manifest: CorpusManifest,
        item: ManifestDocument,
        *,
        force: bool,
    ) -> int | None:
        pdf_path = self.corpus_path / "pdfs" / item.filename
        if not pdf_path.is_file():
            raise RuntimeError(f"No existe {pdf_path}.")
        actual_sha = file_sha256(pdf_path)
        if actual_sha != item.sha256:
            raise RuntimeError("El checksum no coincide con el manifiesto; no se indexó el PDF.")
        document = self.db.scalar(
            select(LegalDocument).where(LegalDocument.document_key == item.key)
        )
        existing_chunks = 0
        if document is not None:
            existing_chunks = self.db.scalar(
                select(func.count(LegalChunk.id)).where(LegalChunk.document_id == document.id)
            ) or 0
        if (
            not force
            and document is not None
            and document.source_sha256 == actual_sha
            and (document.document_metadata or {}).get("indexer_version")
            == LEGAL_INDEX_VERSION
            and existing_chunks > 0
            and self.db.scalar(
                select(func.count(LegalChunk.id)).where(
                    LegalChunk.document_id == document.id,
                    LegalChunk.embedding_model == self._provider().model_name,
                )
            )
            == existing_chunks
        ):
            document.title = item.title
            document.short_title = item.short_title
            document.source_filename = item.filename
            document.authority = item.authority
            document.jurisdiction = manifest.jurisdiction
            document.document_type = item.document_type
            document.corpus_version = manifest.version
            document.priority = item.priority
            document.status = "active"
            document.document_metadata = _document_metadata(manifest, item)
            self.db.execute(
                update(LegalChunk)
                .where(LegalChunk.document_id == document.id)
                .values(corpus_version=manifest.version)
            )
            self.db.flush()
            return None
        pages = extract_pdf_pages(pdf_path)
        drafts = chunk_pages(
            pages,
            target_tokens=self.settings.legal_rag_chunk_tokens,
            overlap_tokens=min(
                self.settings.legal_rag_chunk_overlap_tokens,
                self.settings.legal_rag_chunk_tokens // 2,
            ),
        )
        if not drafts:
            raise RuntimeError("El PDF no produjo texto suficiente para indexar.")
        if document is None:
            document = LegalDocument(document_key=item.key)
            self.db.add(document)
        else:
            self.db.execute(delete(LegalChunk).where(LegalChunk.document_id == document.id))
        document.title = item.title
        document.short_title = item.short_title
        document.source_filename = item.filename
        document.source_sha256 = actual_sha
        document.authority = item.authority
        document.jurisdiction = manifest.jurisdiction
        document.document_type = item.document_type
        document.corpus_version = manifest.version
        document.page_count = len(pages)
        document.priority = item.priority
        document.status = "active"
        document.document_metadata = _document_metadata(manifest, item)
        self.db.flush()
        vectors: list[list[float]] = []
        provider = self._provider()
        batch_size = 64
        for start in range(0, len(drafts), batch_size):
            batch = drafts[start : start + batch_size]
            embedding_inputs = [
                "\n".join(
                    part
                    for part in (
                        f"Documento: {item.title}.",
                        f"Sección: {draft.section_path}." if draft.section_path else None,
                        (
                            f"Referencia: {', '.join(draft.article_references)}."
                            if draft.article_references
                            else None
                        ),
                        draft.content,
                    )
                    if part
                )
                for draft in batch
            ]
            vectors.extend(provider.embed_many(embedding_inputs))
        if len(vectors) != len(drafts):
            raise RuntimeError("OpenAI devolvió una cantidad inesperada de embeddings.")
        for draft, vector in zip(drafts, vectors, strict=True):
            self.db.add(
                LegalChunk(
                    document=document,
                    chunk_index=draft.chunk_index,
                    page_number=draft.page_number,
                    printed_page_label=draft.printed_page_label,
                    section_path=draft.section_path,
                    article_references=list(draft.article_references),
                    content=draft.content,
                    content_hash=hashlib.sha256(draft.content.encode("utf-8")).hexdigest(),
                    estimated_tokens=draft.estimated_tokens,
                    embedding=vector,
                    embedding_model=provider.model_name,
                    corpus_version=manifest.version,
                    chunk_metadata={
                        "physical_pdf_page": draft.page_number,
                        "indexer_version": LEGAL_INDEX_VERSION,
                    },
                )
            )
        self.db.commit()
        return len(drafts)

    def status(self) -> LegalCorpusStatus:
        manifest = load_manifest(self.corpus_path)
        documents = list(
            self.db.scalars(
                select(LegalDocument)
                .where(LegalDocument.status == "active")
                .order_by(LegalDocument.priority, LegalDocument.document_key)
            )
        )
        statuses: list[LegalCorpusDocumentStatus] = []
        indexed_embeddings = 0
        for document in documents:
            count = self.db.scalar(
                select(func.count(LegalChunk.id)).where(LegalChunk.document_id == document.id)
            ) or 0
            indexed_embeddings += count
            statuses.append(
                LegalCorpusDocumentStatus(
                    document_key=document.document_key,
                    title=document.title,
                    page_count=document.page_count,
                    embeddings=count,
                    status=document.status,
                    source_sha256=document.source_sha256,
                )
            )
        return LegalCorpusStatus(
            corpus_version=manifest.version,
            documents_in_manifest=len(manifest.documents),
            indexed_documents=len(documents),
            indexed_embeddings=indexed_embeddings,
            known_gaps=manifest.known_gaps,
            documents=statuses,
        )
