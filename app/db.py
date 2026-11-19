# -*- coding: utf-8 -*-
"""SQLite-backed task registry. Single file, mounted to host."""
import json
import os
import sqlite3
import threading

DATA_DIR = os.environ.get("MINERU_WEB_DATA_DIR", "/data")
DB_PATH = os.path.join(DATA_DIR, "tasks.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    mineru_task_id TEXT,
    status TEXT NOT NULL DEFAULT 'uploading',
    tier TEXT,
    ocr_mode TEXT,
    output_formats TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    error TEXT,
    total_files INTEGER DEFAULT 0,
    completed_files INTEGER DEFAULT 0,
    failed_files INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS task_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    file_name TEXT NOT NULL,
    file_id TEXT,
    status TEXT NOT NULL DEFAULT 'waiting-file',
    error TEXT,
    result_url TEXT,
    result_path TEXT,
    size INTEGER,
    FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_task_files_task ON task_files(task_id);
"""


class DB:
    def __init__(self):
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._migrate()

    def _execute(self, sql, params=()):
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def _query(self, sql, params=()):
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def _migrate(self):
        cols = {r["name"] for r in self._query("PRAGMA table_info(task_files)")}
        if "size" not in cols:
            self._execute("ALTER TABLE task_files ADD COLUMN size INTEGER")

    # ---- tasks ----
    def create_task(self, task_id, mineru_task_id, tier, ocr_mode, output_formats, files):
        now = _now()
        self._execute(
            "INSERT INTO tasks (id, mineru_task_id, status, tier, ocr_mode, output_formats, "
            "created_at, total_files) VALUES (?,?,?,?,?,?,?,?)",
            (task_id, mineru_task_id, "uploading", tier, ocr_mode,
             json.dumps(output_formats), now, len(files)),
        )
        for f in files:
            self._execute(
                "INSERT INTO task_files (task_id, file_name, file_id, status, size) VALUES (?,?,?,?,?)",
                (task_id, f["file_name"], f.get("file_id"), "waiting-file", f.get("size")),
            )

    def list_tasks(self):
        rows = self._query("SELECT * FROM tasks ORDER BY created_at DESC")
        return [dict(r) for r in rows]

    def get_task(self, task_id):
        rows = self._query("SELECT * FROM tasks WHERE id=?", (task_id,))
        if not rows:
            return None
        t = dict(rows[0])
        t["files"] = self.get_files(task_id)
        return t

    def get_files(self, task_id):
        rows = self._query(
            "SELECT * FROM task_files WHERE task_id=? ORDER BY id", (task_id,))
        return [dict(r) for r in rows]

    def update_task(self, task_id, **fields):
        if not fields:
            return
        keys = list(fields.keys())
        sql = "UPDATE tasks SET " + ", ".join(f"{k}=?" for k in keys) + " WHERE id=?"
        self._execute(sql, [fields[k] for k in keys] + [task_id])

    def update_file(self, task_id, file_name, **fields):
        if not fields:
            return
        keys = list(fields.keys())
        sql = ("UPDATE task_files SET " + ", ".join(f"{k}=?" for k in keys)
               + " WHERE task_id=? AND file_name=?")
        self._execute(sql, [fields[k] for k in keys] + [task_id, file_name])

    def refresh_progress(self, task_id):
        rows = self._query(
            "SELECT status FROM task_files WHERE task_id=?", (task_id,))
        total = len(rows)
        completed = sum(1 for r in rows if r["status"] == "completed")
        failed = sum(1 for r in rows if r["status"] == "failed")
        canceled = sum(1 for r in rows if r["status"] == "canceled")
        status = "uploading"
        if total and completed + failed + canceled == total:
            if failed and not completed:
                status = "failed"
            elif failed:
                status = "partial"
            elif canceled == total:
                status = "canceled"
            else:
                status = "completed"
        elif any(r["status"] in ("running", "pending") for r in rows):
            status = "running"
        self.update_task(task_id, status=status,
                         completed_files=completed, failed_files=failed)
        return status

    def delete_task(self, task_id):
        self._execute("DELETE FROM tasks WHERE id=?", (task_id,))


def _now():
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).astimezone(
        datetime.timezone(datetime.timedelta(hours=8))).isoformat(timespec="seconds")
