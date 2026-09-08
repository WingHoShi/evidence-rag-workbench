from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from evidence_rag.database import Database
from evidence_rag.settings import Settings
from evidence_rag.vector_store import NoopVectorIndex, VectorIndex


SUPPORTED_SUFFIXES = {".md", ".markdown", ".txt", ".docx", ".pdf"}
CHUNK_SIZE = 1024 * 1024


class LifecycleError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


class DocumentLifecycleService:
    """管理上传副本、SQLite 元数据和文档任务状态。"""

    def __init__(self, settings: Settings, vector_index: VectorIndex | None = None) -> None:
        self.settings = settings
        self.database = Database(settings.database_path)
        self.vector_index = vector_index or NoopVectorIndex()
        self.upload_root = settings.data_dir / "uploads"
        self.staging_root = self.upload_root / ".staging"
        self.staging_root.mkdir(parents=True, exist_ok=True)

    def create_knowledge_base(self, name: str) -> dict:
        cleaned_name = name.strip()
        if not cleaned_name:
            raise LifecycleError(422, "知识库名称不能为空")
        if len(cleaned_name) > 80:
            raise LifecycleError(422, "知识库名称不能超过 80 个字符")
        try:
            return self.database.create_knowledge_base(cleaned_name)
        except Exception as error:
            if "UNIQUE constraint failed" in str(error):
                raise LifecycleError(409, "已存在同名知识库") from error
            raise

    def list_knowledge_bases(self) -> list[dict]:
        return self.database.list_knowledge_bases()

    async def upload_document(self, knowledge_base_id: str, upload: UploadFile) -> dict:
        self._require_knowledge_base(knowledge_base_id)
        filename = Path(upload.filename or "").name
        suffix = Path(filename).suffix.lower()
        if not filename or suffix not in SUPPORTED_SUFFIXES:
            raise LifecycleError(422, "仅支持 Markdown、TXT、DOCX 和可复制文本 PDF 文件")

        staging_path = self.staging_root / f"{uuid4()}.part"
        size_bytes = 0
        digest = hashlib.sha256()
        try:
            with staging_path.open("xb") as destination:
                while chunk := await upload.read(CHUNK_SIZE):
                    size_bytes += len(chunk)
                    if size_bytes > self.settings.max_file_bytes:
                        raise LifecycleError(
                            413,
                            f"单文件不能超过 {self.settings.max_file_bytes} 字节",
                        )
                    digest.update(chunk)
                    destination.write(chunk)

            sha256 = digest.hexdigest()
            if self.database.duplicate_hash_exists(knowledge_base_id, sha256):
                raise LifecycleError(409, "该知识库已存在内容相同的文件")
            if self.database.total_size(knowledge_base_id) + size_bytes > self.settings.max_knowledge_base_bytes:
                raise LifecycleError(
                    413,
                    f"单知识库不能超过 {self.settings.max_knowledge_base_bytes} 字节",
                )

            document_id = str(uuid4())
            version_id = str(uuid4())
            relative_path = Path("uploads") / knowledge_base_id / document_id / f"{version_id}{suffix}"
            final_path = self.settings.data_dir / relative_path
            final_path.parent.mkdir(parents=True, exist_ok=True)
            staging_path.replace(final_path)
            try:
                document = self.database.create_document(
                    knowledge_base_id=knowledge_base_id,
                    original_filename=filename,
                    storage_path=relative_path.as_posix(),
                    sha256=sha256,
                    size_bytes=size_bytes,
                )
            except Exception:
                self._remove_owned_file(final_path)
                raise
            if not document:
                raise RuntimeError("文档元数据创建失败")
            return document
        except LifecycleError:
            self._remove_owned_file(staging_path)
            raise
        finally:
            await upload.close()

    def list_documents(self, knowledge_base_id: str) -> list[dict]:
        self._require_knowledge_base(knowledge_base_id)
        return self.database.list_documents(knowledge_base_id)

    def list_tasks(self, knowledge_base_id: str, document_id: str) -> list[dict]:
        tasks = self.database.list_tasks(knowledge_base_id, document_id)
        if tasks is None:
            raise LifecycleError(404, "文档不存在或不属于该知识库")
        return tasks

    def delete_document(self, knowledge_base_id: str, document_id: str) -> None:
        document = self.database.get_document(knowledge_base_id, document_id)
        if document is None:
            raise LifecycleError(404, "文档不存在或不属于该知识库")
        self.vector_index.delete_document_vectors(knowledge_base_id, document["version_id"])
        self._remove_owned_file(self.storage_path_for(document_id))
        self.database.delete_document(knowledge_base_id, document_id)

    def retry_document(self, knowledge_base_id: str, document_id: str) -> dict:
        document = self.database.retry_document(knowledge_base_id, document_id)
        if document is None:
            raise LifecycleError(404, "文档不存在或不属于该知识库")
        if document.get("status") == "not_failed":
            raise LifecycleError(409, "仅失败的文档可以重试")
        return document

    def mark_latest_task_failed(self, document_id: str, error_message: str) -> None:
        if not self.database.mark_latest_task_failed(document_id, error_message):
            raise LifecycleError(404, "文档不存在")

    def delete_knowledge_base(self, knowledge_base_id: str) -> None:
        self._require_knowledge_base(knowledge_base_id)
        documents = self.database.list_documents(knowledge_base_id)
        self.vector_index.delete_knowledge_base_vectors(knowledge_base_id)
        for document in documents:
            self._remove_owned_file(self.storage_path_for(document["id"]))
        self.database.delete_knowledge_base(knowledge_base_id)

    def storage_path_for(self, document_id: str) -> Path:
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT v.storage_path FROM document_versions AS v
                WHERE v.document_id = ? ORDER BY v.version_number DESC LIMIT 1
                """,
                (document_id,),
            ).fetchone()
        if row is None:
            raise LifecycleError(404, "文档不存在")
        return self.settings.data_dir / row["storage_path"]

    def _require_knowledge_base(self, knowledge_base_id: str) -> None:
        if not self.database.knowledge_base_exists(knowledge_base_id):
            raise LifecycleError(404, "知识库不存在")

    def _remove_owned_file(self, path: Path) -> None:
        root = self.upload_root.resolve()
        resolved_path = path.resolve()
        if not resolved_path.is_relative_to(root):
            raise RuntimeError("拒绝删除项目上传目录之外的文件")
        if resolved_path.exists():
            resolved_path.unlink()
        if resolved_path.is_relative_to(self.staging_root.resolve()):
            return
        parent = resolved_path.parent
        while parent != root:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
