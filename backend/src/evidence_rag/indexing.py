from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid5

import pymupdf
from docx import Document
from modelscope import snapshot_download
from qdrant_client.http import models as qmodels
from sentence_transformers import SentenceTransformer

from evidence_rag.lifecycle import DocumentLifecycleService, LifecycleError
from evidence_rag.settings import Settings
from evidence_rag.vector_store import VectorIndex, create_qdrant_client


@dataclass(frozen=True)
class ParsedSection:
    text: str
    heading: str | None
    locator: str


@dataclass(frozen=True)
class DocumentChunk:
    text: str
    heading: str | None
    locator: str
    index: int


class DocumentParseError(ValueError):
    pass


class EmbeddingEngine(Protocol):
    model_name: str
    dimension: int

    def embed_passages(self, texts: list[str]) -> list[list[float]]: ...

    def embed_queries(self, texts: list[str]) -> list[list[float]]: ...


class DocumentParser:
    def parse(self, path: Path) -> list[ParsedSection]:
        suffix = path.suffix.lower()
        if suffix in {".md", ".markdown"}:
            return self._parse_markdown(path)
        if suffix == ".txt":
            return self._parse_text(path)
        if suffix == ".docx":
            return self._parse_docx(path)
        if suffix == ".pdf":
            return self._parse_pdf(path)
        raise DocumentParseError("不支持该文件类型")

    def _parse_markdown(self, path: Path) -> list[ParsedSection]:
        sections: list[ParsedSection] = []
        heading: str | None = None
        buffer: list[str] = []

        def flush() -> None:
            text = "\n".join(buffer).strip()
            if text:
                locator = f"heading: {heading}" if heading else "document start"
                sections.append(ParsedSection(text=text, heading=heading, locator=locator))
            buffer.clear()

        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            match = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
            if match:
                flush()
                heading = match.group(1)
            else:
                buffer.append(line)
        flush()
        return self._require_text(sections)

    def _parse_text(self, path: Path) -> list[ParsedSection]:
        source = path.read_text(encoding="utf-8", errors="replace")
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", source) if part.strip()]
        sections = [
            ParsedSection(text=paragraph, heading=None, locator=f"paragraph {index}")
            for index, paragraph in enumerate(paragraphs, start=1)
        ]
        return self._require_text(sections)

    def _parse_docx(self, path: Path) -> list[ParsedSection]:
        document = Document(path)
        sections: list[ParsedSection] = []
        heading: str | None = None
        for index, paragraph in enumerate(document.paragraphs, start=1):
            text = paragraph.text.strip()
            if not text:
                continue
            if paragraph.style.name.startswith("Heading"):
                heading = text
                continue
            sections.append(
                ParsedSection(text=text, heading=heading, locator=f"paragraph {index}")
            )
        return self._require_text(sections)

    def _parse_pdf(self, path: Path) -> list[ParsedSection]:
        sections: list[ParsedSection] = []
        with pymupdf.open(path) as document:
            for page_number, page in enumerate(document, start=1):
                text = page.get_text("text").strip()
                if text:
                    sections.append(
                        ParsedSection(text=text, heading=None, locator=f"page {page_number}")
                    )
        if not sections:
            raise DocumentParseError("PDF 不包含可复制文本，暂不支持 OCR 或扫描件")
        return sections

    @staticmethod
    def _require_text(sections: list[ParsedSection]) -> list[ParsedSection]:
        if not sections:
            raise DocumentParseError("文档不包含可提取文本")
        return sections


def chunk_sections(
    sections: list[ParsedSection],
    *,
    chunk_size: int = 900,
    overlap: int = 160,
) -> list[DocumentChunk]:
    if chunk_size <= overlap:
        raise ValueError("chunk_size 必须大于 overlap")
    chunks: list[DocumentChunk] = []
    for section in sections:
        prefix = f"{section.heading}\n\n" if section.heading else ""
        text = f"{prefix}{section.text}".strip()
        start = 0
        while start < len(text):
            end = min(start + chunk_size, len(text))
            if end < len(text):
                boundary = max(text.rfind("\n", start, end), text.rfind(" ", start, end))
                if boundary > start + chunk_size // 2:
                    end = boundary
            piece = text[start:end].strip()
            if piece:
                chunks.append(
                    DocumentChunk(
                        text=piece,
                        heading=section.heading,
                        locator=section.locator,
                        index=len(chunks),
                    )
                )
            if end >= len(text):
                break
            start = max(end - overlap, start + 1)
    if not chunks:
        raise DocumentParseError("文档切分后没有可索引内容")
    return chunks


class MultilingualE5EmbeddingEngine:
    dimension = 384
    required_model_files = [
        "config.json",
        "model.safetensors",
        "modules.json",
        "sentence_bert_config.json",
        "sentencepiece.bpe.model",
        "special_tokens_map.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "1_Pooling/config.json",
    ]

    def __init__(self, settings: Settings) -> None:
        self.model_name = settings.embedding_model
        self.model_dir = settings.embedding_model_dir
        self.batch_size = settings.embedding_batch_size
        self._model: SentenceTransformer | None = None

    @staticmethod
    def prefix_passage(text: str) -> str:
        return f"passage: {text}"

    @staticmethod
    def prefix_query(text: str) -> str:
        return f"query: {text}"

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return self._encode([self.prefix_passage(text) for text in texts])

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        return self._encode([self.prefix_query(text) for text in texts])

    def _encode(self, texts: list[str]) -> list[list[float]]:
        model = self._get_model()
        vectors = model.encode(
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
            batch_size=self.batch_size,
        )
        return [vector.tolist() for vector in vectors]

    def _get_model(self) -> SentenceTransformer:
        if self._model is None:
            model_path = self._ensure_model_path()
            self._model = SentenceTransformer(str(model_path), device="cpu")
            dimension = self._model.get_sentence_embedding_dimension()
            if dimension != self.dimension:
                raise RuntimeError(f"Embedding 维度应为 {self.dimension}，实际为 {dimension}")
        return self._model

    def _ensure_model_path(self) -> Path:
        if (self.model_dir / "model.safetensors").exists():
            return self.model_dir
        self.model_dir.parent.mkdir(parents=True, exist_ok=True)
        downloaded_path = snapshot_download(
            self.model_name,
            local_dir=str(self.model_dir),
            allow_patterns=self.required_model_files,
        )
        return Path(downloaded_path)


class QdrantChunkIndex(VectorIndex):
    def __init__(self, settings: Settings, collection_name: str = "evidence_rag_chunks") -> None:
        self.settings = settings
        self._client = None
        self.collection_name = collection_name

    @property
    def client(self):
        if self._client is None:
            self._client = create_qdrant_client(self.settings)
        return self._client

    def upsert_chunks(
        self,
        *,
        knowledge_base_id: str,
        document_id: str,
        version_id: str,
        original_filename: str,
        chunks: list[DocumentChunk],
        vectors: list[list[float]],
        dimension: int,
    ) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("切分结果与向量数量不一致")
        self._ensure_collection(dimension)
        points = [
            qmodels.PointStruct(
                id=str(uuid5(UUID(version_id), str(chunk.index))),
                vector=vector,
                payload={
                    "knowledge_base_id": knowledge_base_id,
                    "document_id": document_id,
                    "document_version_id": version_id,
                    "original_filename": original_filename,
                    "heading": chunk.heading,
                    "locator": chunk.locator,
                    "chunk_index": chunk.index,
                    "text": chunk.text,
                },
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        self.client.upsert(self.collection_name, points=points, wait=True)

    def search(self, knowledge_base_id: str, query_vector: list[float], limit: int = 5) -> list[dict]:
        if not self.client.collection_exists(self.collection_name):
            return []
        response = self.client.query_points(
            self.collection_name,
            query=query_vector,
            query_filter=self._filter("knowledge_base_id", knowledge_base_id),
            limit=limit,
            with_payload=True,
        )
        return [
            {**dict(point.payload or {}), "score": point.score}
            for point in response.points
        ]

    def delete_document_vectors(self, knowledge_base_id: str, version_id: str) -> None:
        if self.client.collection_exists(self.collection_name):
            self.client.delete(
                self.collection_name,
                points_selector=self._filter("document_version_id", version_id),
                wait=True,
            )

    def delete_knowledge_base_vectors(self, knowledge_base_id: str) -> None:
        if self.client.collection_exists(self.collection_name):
            self.client.delete(
                self.collection_name,
                points_selector=self._filter("knowledge_base_id", knowledge_base_id),
                wait=True,
            )

    def _ensure_collection(self, dimension: int) -> None:
        if not self.client.collection_exists(self.collection_name):
            self.client.create_collection(
                self.collection_name,
                vectors_config=qmodels.VectorParams(size=dimension, distance=qmodels.Distance.COSINE),
            )
            return
        info = self.client.get_collection(self.collection_name)
        vector_params = info.config.params.vectors
        existing_dimension = vector_params.size if isinstance(vector_params, qmodels.VectorParams) else None
        if existing_dimension != dimension:
            raise RuntimeError("Qdrant collection 向量维度不匹配，请重建本地索引")

    @staticmethod
    def _filter(key: str, value: str) -> qmodels.Filter:
        return qmodels.Filter(
            must=[qmodels.FieldCondition(key=key, match=qmodels.MatchValue(value=value))]
        )


class DocumentIndexingService:
    def __init__(
        self,
        lifecycle: DocumentLifecycleService,
        index: QdrantChunkIndex | VectorIndex,
        embedding_engine: EmbeddingEngine,
    ) -> None:
        self.lifecycle = lifecycle
        self.index = index
        self.embedding_engine = embedding_engine
        self.parser = DocumentParser()

    def index_document(self, knowledge_base_id: str, document_id: str) -> dict:
        self.lifecycle._require_knowledge_base(knowledge_base_id)
        state = self.lifecycle.database.get_index_state(knowledge_base_id)
        if state and state["status"] == "ready" and state["embedding_model"] != self.embedding_engine.model_name:
            raise LifecycleError(409, "Embedding 模型已变更，请先重建索引")
        document = self.lifecycle.database.start_indexing(knowledge_base_id, document_id)
        if document is None:
            raise LifecycleError(404, "文档不存在或不属于该知识库")
        if document.get("status") == "not_queued":
            raise LifecycleError(409, "仅排队中的文档可以索引")
        try:
            self.lifecycle.database.upsert_index_state(
                knowledge_base_id,
                self.embedding_engine.model_name,
                self.embedding_engine.dimension,
                "indexing",
            )
            sections = self.parser.parse(self.lifecycle.storage_path_for(document_id))
            chunks = chunk_sections(sections)
            vectors = self.embedding_engine.embed_passages([chunk.text for chunk in chunks])
            if not hasattr(self.index, "upsert_chunks"):
                raise RuntimeError("当前向量索引不支持写入")
            self.index.upsert_chunks(
                knowledge_base_id=knowledge_base_id,
                document_id=document_id,
                version_id=document["version_id"],
                original_filename=document["original_filename"],
                chunks=chunks,
                vectors=vectors,
                dimension=self.embedding_engine.dimension,
            )
            completed = self.lifecycle.database.complete_indexing(knowledge_base_id, document_id)
            self.lifecycle.database.upsert_index_state(
                knowledge_base_id,
                self.embedding_engine.model_name,
                self.embedding_engine.dimension,
                "ready",
                indexed=True,
            )
            return completed or {}
        except DocumentParseError as error:
            self._fail(knowledge_base_id, document_id, str(error))
            raise LifecycleError(422, str(error)) from error
        except LifecycleError:
            raise
        except Exception as error:
            self._fail(knowledge_base_id, document_id, "索引任务失败")
            raise LifecycleError(500, "索引任务失败，请查看本地日志后重试") from error

    def rebuild_knowledge_base(self, knowledge_base_id: str) -> dict:
        self.lifecycle._require_knowledge_base(knowledge_base_id)
        if not hasattr(self.index, "delete_knowledge_base_vectors"):
            raise LifecycleError(500, "当前向量索引不支持重建")
        self.index.delete_knowledge_base_vectors(knowledge_base_id)
        self.lifecycle.database.upsert_index_state(
            knowledge_base_id,
            self.embedding_engine.model_name,
            self.embedding_engine.dimension,
            "rebuilding",
        )
        documents = self.lifecycle.database.reset_knowledge_base_for_rebuild(knowledge_base_id)
        for document in documents:
            self.index_document(knowledge_base_id, document["id"])
        return self.index_status(knowledge_base_id)

    def index_status(self, knowledge_base_id: str) -> dict:
        self.lifecycle._require_knowledge_base(knowledge_base_id)
        return self.lifecycle.database.get_index_state(knowledge_base_id) or {
            "knowledge_base_id": knowledge_base_id,
            "embedding_model": self.embedding_engine.model_name,
            "vector_dimension": self.embedding_engine.dimension,
            "status": "not_indexed",
            "last_indexed_at": None,
            "updated_at": None,
        }

    def search(self, knowledge_base_id: str, query: str, limit: int = 5) -> list[dict]:
        self.lifecycle._require_knowledge_base(knowledge_base_id)
        if not hasattr(self.index, "search"):
            raise LifecycleError(500, "当前向量索引不支持检索")
        vector = self.embedding_engine.embed_queries([query])[0]
        return self.index.search(knowledge_base_id, vector, limit)

    def _fail(self, knowledge_base_id: str, document_id: str, message: str) -> None:
        self.lifecycle.database.fail_indexing(knowledge_base_id, document_id, message)
        self.lifecycle.database.upsert_index_state(
            knowledge_base_id,
            self.embedding_engine.model_name,
            self.embedding_engine.dimension,
            "failed",
        )
