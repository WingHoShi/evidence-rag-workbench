from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator
from uuid import uuid4


SCHEMA = """
CREATE TABLE IF NOT EXISTS knowledge_bases (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    knowledge_base_id TEXT NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS document_versions (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    knowledge_base_id TEXT NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    original_filename TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    status TEXT NOT NULL,
    error_message TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(document_id, version_number),
    UNIQUE(knowledge_base_id, sha256)
);

CREATE TABLE IF NOT EXISTS document_tasks (
    id TEXT PRIMARY KEY,
    document_version_id TEXT NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_sessions (
    id TEXT PRIMARY KEY,
    knowledge_base_id TEXT NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    title TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS citation_snapshots (
    id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL REFERENCES chat_messages(id) ON DELETE CASCADE,
    document_version_id TEXT REFERENCES document_versions(id) ON DELETE SET NULL,
    chunk_id TEXT,
    label TEXT NOT NULL,
    locator TEXT,
    quoted_text TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_documents_knowledge_base ON documents(knowledge_base_id);
CREATE INDEX IF NOT EXISTS idx_versions_document ON document_versions(document_id, version_number);
CREATE INDEX IF NOT EXISTS idx_tasks_version ON document_tasks(document_version_id, created_at);
"""


def now() -> str:
    return datetime.now(UTC).isoformat()


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            connection.executescript(SCHEMA)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def table_names(self) -> set[str]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        return {row["name"] for row in rows}

    def create_knowledge_base(self, name: str) -> dict:
        knowledge_base_id = str(uuid4())
        created_at = now()
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO knowledge_bases (id, name, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (knowledge_base_id, name, created_at, created_at),
            )
        return {"id": knowledge_base_id, "name": name, "document_count": 0}

    def list_knowledge_bases(self) -> list[dict]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT kb.id, kb.name, COUNT(d.id) AS document_count
                FROM knowledge_bases AS kb
                LEFT JOIN documents AS d ON d.knowledge_base_id = kb.id
                GROUP BY kb.id
                ORDER BY kb.created_at
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def knowledge_base_exists(self, knowledge_base_id: str) -> bool:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT 1 FROM knowledge_bases WHERE id = ?", (knowledge_base_id,)
            ).fetchone()
        return row is not None

    def total_size(self, knowledge_base_id: str) -> int:
        with self.connection() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(SUM(v.size_bytes), 0) AS total_size
                FROM document_versions AS v
                WHERE v.knowledge_base_id = ?
                """,
                (knowledge_base_id,),
            ).fetchone()
        return int(row["total_size"])

    def duplicate_hash_exists(self, knowledge_base_id: str, sha256: str) -> bool:
        with self.connection() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM document_versions
                WHERE knowledge_base_id = ? AND sha256 = ?
                """,
                (knowledge_base_id, sha256),
            ).fetchone()
        return row is not None

    def create_document(
        self,
        *,
        knowledge_base_id: str,
        original_filename: str,
        storage_path: str,
        sha256: str,
        size_bytes: int,
    ) -> dict:
        document_id = str(uuid4())
        version_id = str(uuid4())
        task_id = str(uuid4())
        created_at = now()
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO documents (id, knowledge_base_id, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (document_id, knowledge_base_id, created_at, created_at),
            )
            connection.execute(
                """
                INSERT INTO document_versions (
                    id, document_id, knowledge_base_id, version_number,
                    original_filename, storage_path, sha256, size_bytes, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, 1, ?, ?, ?, ?, 'queued', ?, ?)
                """,
                (
                    version_id,
                    document_id,
                    knowledge_base_id,
                    original_filename,
                    storage_path,
                    sha256,
                    size_bytes,
                    created_at,
                    created_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO document_tasks (
                    id, document_version_id, kind, status, attempt, created_at, updated_at
                ) VALUES (?, ?, 'parse', 'queued', 0, ?, ?)
                """,
                (task_id, version_id, created_at, created_at),
            )
        return self.get_document(knowledge_base_id, document_id) or {}

    def get_document(self, knowledge_base_id: str, document_id: str) -> dict | None:
        with self.connection() as connection:
            row = connection.execute(
                """
                SELECT
                    d.id, v.id AS version_id, v.original_filename, v.storage_path,
                    v.sha256, v.size_bytes, v.status, v.retry_count,
                    v.created_at, v.updated_at,
                    t.id AS task_id, t.kind AS task_kind, t.status AS task_status,
                    t.attempt AS task_attempt, t.error_message AS task_error_message
                FROM documents AS d
                JOIN document_versions AS v ON v.document_id = d.id
                LEFT JOIN document_tasks AS t ON t.id = (
                    SELECT id FROM document_tasks
                    WHERE document_version_id = v.id
                    ORDER BY created_at DESC, rowid DESC LIMIT 1
                )
                WHERE d.id = ? AND d.knowledge_base_id = ?
                ORDER BY v.version_number DESC
                LIMIT 1
                """,
                (document_id, knowledge_base_id),
            ).fetchone()
        return self._document_from_row(row) if row else None

    def list_documents(self, knowledge_base_id: str) -> list[dict]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT d.id, v.id AS version_id, v.original_filename, v.storage_path,
                    v.sha256, v.size_bytes, v.status, v.retry_count,
                    v.created_at, v.updated_at,
                    t.id AS task_id, t.kind AS task_kind, t.status AS task_status,
                    t.attempt AS task_attempt, t.error_message AS task_error_message
                FROM documents AS d
                JOIN document_versions AS v ON v.document_id = d.id
                LEFT JOIN document_tasks AS t ON t.id = (
                    SELECT id FROM document_tasks
                    WHERE document_version_id = v.id
                    ORDER BY created_at DESC, rowid DESC LIMIT 1
                )
                WHERE d.knowledge_base_id = ?
                ORDER BY d.created_at
                """,
                (knowledge_base_id,),
            ).fetchall()
        return [self._document_from_row(row) for row in rows]

    def list_tasks(self, knowledge_base_id: str, document_id: str) -> list[dict] | None:
        document = self.get_document(knowledge_base_id, document_id)
        if not document:
            return None
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT t.id, t.kind, t.status, t.attempt, t.error_message,
                    t.created_at, t.updated_at
                FROM document_tasks AS t
                JOIN document_versions AS v ON v.id = t.document_version_id
                WHERE v.document_id = ? AND v.knowledge_base_id = ?
                ORDER BY t.created_at, t.rowid
                """,
                (document_id, knowledge_base_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_latest_task_failed(self, document_id: str, error_message: str) -> bool:
        updated_at = now()
        with self.connection() as connection:
            version = connection.execute(
                """
                SELECT id FROM document_versions
                WHERE document_id = ? ORDER BY version_number DESC LIMIT 1
                """,
                (document_id,),
            ).fetchone()
            if version is None:
                return False
            task = connection.execute(
                """
                SELECT id FROM document_tasks
                WHERE document_version_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1
                """,
                (version["id"],),
            ).fetchone()
            connection.execute(
                """
                UPDATE document_versions
                SET status = 'failed', error_message = ?, updated_at = ?
                WHERE id = ?
                """,
                (error_message, updated_at, version["id"]),
            )
            if task:
                connection.execute(
                    """
                    UPDATE document_tasks
                    SET status = 'failed', error_message = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (error_message, updated_at, task["id"]),
                )
        return True

    def retry_document(self, knowledge_base_id: str, document_id: str) -> dict | None:
        updated_at = now()
        with self.connection() as connection:
            version = connection.execute(
                """
                SELECT v.* FROM document_versions AS v
                JOIN documents AS d ON d.id = v.document_id
                WHERE d.id = ? AND d.knowledge_base_id = ?
                ORDER BY v.version_number DESC LIMIT 1
                """,
                (document_id, knowledge_base_id),
            ).fetchone()
            if version is None:
                return None
            if version["status"] != "failed":
                return {"status": "not_failed"}
            retry_count = int(version["retry_count"]) + 1
            connection.execute(
                """
                UPDATE document_versions
                SET status = 'queued', error_message = NULL, retry_count = ?, updated_at = ?
                WHERE id = ?
                """,
                (retry_count, updated_at, version["id"]),
            )
            connection.execute(
                """
                INSERT INTO document_tasks (
                    id, document_version_id, kind, status, attempt, created_at, updated_at
                ) VALUES (?, ?, 'parse', 'queued', ?, ?, ?)
                """,
                (str(uuid4()), version["id"], retry_count, updated_at, updated_at),
            )
        return self.get_document(knowledge_base_id, document_id)

    def delete_document(self, knowledge_base_id: str, document_id: str) -> dict | None:
        document = self.get_document(knowledge_base_id, document_id)
        if not document:
            return None
        with self.connection() as connection:
            connection.execute(
                "DELETE FROM documents WHERE id = ? AND knowledge_base_id = ?",
                (document_id, knowledge_base_id),
            )
        return document

    def delete_knowledge_base(self, knowledge_base_id: str) -> bool:
        with self.connection() as connection:
            result = connection.execute(
                "DELETE FROM knowledge_bases WHERE id = ?", (knowledge_base_id,)
            )
        return result.rowcount == 1

    @staticmethod
    def _document_from_row(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "version_id": row["version_id"],
            "original_filename": row["original_filename"],
            "size_bytes": row["size_bytes"],
            "sha256": row["sha256"],
            "status": row["status"],
            "retry_count": row["retry_count"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "task": {
                "id": row["task_id"],
                "kind": row["task_kind"],
                "status": row["task_status"],
                "attempt": row["task_attempt"],
                "error_message": row["task_error_message"],
            },
        }
