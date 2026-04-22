"""
Determinism tracking system for the medical data ingestion pipeline.

Captures full execution fingerprints and enables comparison between runs.
Architecture:
  - SQLite DB (data/determinism.db): documents, executions, stage_records tables
  - Content-addressable storage (data/artifacts/): large intermediate outputs
"""

import hashlib
import json
import platform
import sqlite3
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "data" / "determinism.db"
ARTIFACTS_DIR = PROJECT_ROOT / "data" / "artifacts"


def document_uuid(filename: str) -> str:
    """Generate deterministic UUID from filename using SHA256."""
    sha = hashlib.sha256(filename.encode()).hexdigest()
    return str(uuid.UUID(sha[:32]))


def execution_uuid() -> str:
    """Generate random UUID for this pipeline execution."""
    return str(uuid.uuid4())


def _get_git_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=PROJECT_ROOT
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def _get_pip_freeze_hash() -> str:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "freeze"],
            capture_output=True, text=True
        )
        return hashlib.sha256(result.stdout.encode()).hexdigest()
    except Exception:
        return "unknown"


def capture_environment(hyperparameters: Dict = None) -> Dict[str, Any]:
    """Capture full environment fingerprint."""
    import multiprocessing

    env: Dict[str, Any] = {
        "os": platform.platform(),
        "python_version": sys.version,
        "pip_freeze_hash": _get_pip_freeze_hash(),
        "git_sha": _get_git_sha(),
        "cpu_count": multiprocessing.cpu_count(),
        "timestamp": datetime.utcnow().isoformat(),
    }

    try:
        import torch
        env["cuda_available"] = torch.cuda.is_available()
        env["mps_available"] = (
            torch.backends.mps.is_available()
            if hasattr(torch.backends, "mps")
            else False
        )
    except ImportError:
        env["cuda_available"] = False
        env["mps_available"] = False

    if hyperparameters:
        env["hyperparameters"] = hyperparameters

    return env


class DeterminismTracker:
    """Manages determinism tracking for pipeline executions."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS documents (
                    doc_uuid    TEXT PRIMARY KEY,
                    filename    TEXT NOT NULL,
                    created_at  TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS executions (
                    exec_uuid    TEXT PRIMARY KEY,
                    doc_uuid     TEXT NOT NULL,
                    status       TEXT NOT NULL DEFAULT 'running',
                    environment  TEXT NOT NULL,
                    started_at   TEXT NOT NULL,
                    completed_at TEXT,
                    FOREIGN KEY (doc_uuid) REFERENCES documents(doc_uuid)
                );

                CREATE TABLE IF NOT EXISTS stage_records (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    exec_uuid    TEXT NOT NULL,
                    stage        TEXT NOT NULL,
                    output_hash  TEXT,
                    artifact_path TEXT,
                    fingerprint  TEXT NOT NULL,
                    recorded_at  TEXT NOT NULL,
                    FOREIGN KEY (exec_uuid) REFERENCES executions(exec_uuid)
                );
            """)

    def register_document(self, filename: str) -> str:
        """Register a document (idempotent) and return its deterministic UUID."""
        doc_id = document_uuid(filename)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO documents (doc_uuid, filename, created_at) VALUES (?, ?, ?)",
                (doc_id, filename, datetime.utcnow().isoformat()),
            )
        return doc_id

    def start_execution(self, doc_uuid: str, hyperparameters: Dict = None) -> str:
        """Start a new execution and return its UUID."""
        exec_id = execution_uuid()
        env = capture_environment(hyperparameters=hyperparameters)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO executions (exec_uuid, doc_uuid, status, environment, started_at) "
                "VALUES (?, ?, 'running', ?, ?)",
                (exec_id, doc_uuid, json.dumps(env), datetime.utcnow().isoformat()),
            )
        return exec_id

    def record_stage(
        self,
        exec_uuid: str,
        stage: str,
        output_data: Any,
        fingerprint: Dict = None,
        artifact_ext: str = "json",
    ) -> str:
        """Record a stage output with its SHA-256 hash; store artifact content-addressably."""
        if isinstance(output_data, bytes):
            raw = output_data
        elif isinstance(output_data, str):
            raw = output_data.encode()
        else:
            raw = json.dumps(output_data, sort_keys=True).encode()

        output_hash = hashlib.sha256(raw).hexdigest()
        artifact_path = self._store_artifact(stage, output_hash, raw, artifact_ext)

        fp = dict(fingerprint or {})
        fp["output_hash"] = output_hash

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO stage_records "
                "(exec_uuid, stage, output_hash, artifact_path, fingerprint, recorded_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    exec_uuid, stage, output_hash,
                    str(artifact_path), json.dumps(fp),
                    datetime.utcnow().isoformat(),
                ),
            )
        return output_hash

    def _store_artifact(self, stage: str, full_hash: str, data: bytes, ext: str) -> Path:
        """Store artifact in content-addressable layout: artifacts/{stage}/{hash[:2]}/{hash}.{ext}"""
        stage_dir = ARTIFACTS_DIR / stage / full_hash[:2]
        stage_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = stage_dir / f"{full_hash}.{ext}"
        if not artifact_path.exists():
            artifact_path.write_bytes(data)
        return artifact_path

    def complete_execution(self, exec_uuid: str, status: str = "completed"):
        """Mark an execution as complete (or failed)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE executions SET status = ?, completed_at = ? WHERE exec_uuid = ?",
                (status, datetime.utcnow().isoformat(), exec_uuid),
            )

    # ── Query helpers ──────────────────────────────────────────────────────────

    def list_documents(self):
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute(
                "SELECT doc_uuid, filename, created_at FROM documents ORDER BY created_at"
            ).fetchall()

    def list_executions(self, doc_uuid: str):
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute(
                "SELECT exec_uuid, started_at, status FROM executions "
                "WHERE doc_uuid = ? ORDER BY started_at",
                (doc_uuid,),
            ).fetchall()

    def get_stage_records(self, exec_uuid: str):
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute(
                "SELECT stage, output_hash, fingerprint FROM stage_records "
                "WHERE exec_uuid = ? ORDER BY recorded_at",
                (exec_uuid,),
            ).fetchall()

    def get_environment(self, exec_uuid: str) -> Dict:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT environment FROM executions WHERE exec_uuid = ?",
                (exec_uuid,),
            ).fetchone()
            return json.loads(row[0]) if row else {}
