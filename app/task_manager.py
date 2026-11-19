# -*- coding: utf-8 -*-
"""Task lifecycle: create MinerU task, upload files, poll, download + extract results."""
import io
import os
import re
import threading
import time
import uuid
import zipfile

from . import db
from .config import Config
from .mineru_client import MinerUClient, MinerUError

RESULTS_DIR = os.path.join(os.environ.get("MINERU_WEB_DATA_DIR", "/data"), "results")

TERMINAL = {"completed", "partial", "failed", "canceled"}
FILE_TERMINAL = {"completed", "failed", "canceled"}

_SAFE_RE = re.compile(r"[^A-Za-z0-9一-鿿._\-()（） ]+")


def _safe_name(name):
    name = name.replace("\\", "/").split("/")[-1]
    name = _SAFE_RE.sub("_", name).strip()
    return name or "file"


class TaskManager:
    def __init__(self, config: Config, database: db.DB):
        self.config = config
        self.database = database
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _client(self):
        return MinerUClient(self.config.get("mineru_base_url", ""))

    # ---- creation ----
    def create_task(self, files):
        """files: list of (original_name, bytes)."""
        task_id = uuid.uuid4().hex[:16]
        tier = self.config.get("defaults", {}).get("tier", "flash")
        ocr_mode = self.config.get("defaults", {}).get("ocr_mode", "auto")
        output_formats = self.config.get("defaults", {}).get("output_formats", ["default"])
        output_formats = output_formats or ["default"]

        meta = [{"file_name": _safe_name(n), "bytes": len(b)} for n, b in files]
        if not meta:
            raise ValueError("no files")

        client = self._client()
        resp = client.create_task(tier, ocr_mode, output_formats, meta)
        mineru_task_id = resp["task_id"]
        mineru_files = {f["file_name"]: f for f in resp.get("files", [])}

        # store locally
        self.database.create_task(
            task_id, mineru_task_id, tier, ocr_mode, output_formats,
            [{"file_name": m["file_name"], "file_id": mineru_files.get(m["file_name"], {}).get("file_id"),
              "size": m["bytes"]}
             for m in meta],
        )

        # upload each file
        for (orig, data), m in zip(files, meta):
            name = m["file_name"]
            mf = mineru_files.get(name)
            if not mf or not mf.get("upload"):
                self.database.update_file(task_id, name, status="failed",
                                          error="no upload link from MinerU")
                continue
            try:
                client.upload_file(mf["upload"], data)
                self.database.update_file(task_id, name, status="pending")
            except Exception as e:
                self.database.update_file(task_id, name, status="failed", error=str(e))

        self.database.update_task(task_id, status="running", started_at=db._now())
        status = self.database.refresh_progress(task_id)
        if status in TERMINAL:
            self.database.update_task(task_id, finished_at=db._now())
        return task_id

    # ---- polling ----
    def _poll_loop(self):
        while not self._stop.is_set():
            try:
                for t in self.database.list_tasks():
                    if t["status"] in TERMINAL:
                        continue
                    self._poll_one(t["id"])
            except Exception:
                pass
            self._stop.wait(3)

    def _poll_one(self, task_id):
        t = self.database.get_task(task_id)
        if not t or not t.get("mineru_task_id"):
            return
        client = self._client()
        try:
            detail = client.get_task(t["mineru_task_id"])
        except Exception as e:
            self.database.update_task(task_id, status="failed", error=f"MinerU unreachable: {e}")
            return

        for mf in detail.get("files", []):
            name = mf.get("file_name")
            status = mf.get("status")
            updates = {"status": status, "file_id": mf.get("file_id"),
                       "result_url": mf.get("result_url")}
            if mf.get("error"):
                updates["error"] = str(mf["error"])
            self.database.update_file(task_id, name, **updates)

            if status == "completed" and mf.get("result_url"):
                self._maybe_download(task_id, name, mf["result_url"])

        status = self.database.refresh_progress(task_id)
        if status in TERMINAL:
            self.database.update_task(task_id, finished_at=db._now())
            if detail.get("error"):
                self.database.update_task(task_id, error=str(detail["error"]))

    def _maybe_download(self, task_id, file_name, result_url):
        existing = self.database.get_files(task_id)
        for f in existing:
            if f["file_name"] == file_name and f.get("result_path"):
                return  # already downloaded
        try:
            content = self._client().download(result_url)
            dest_dir = os.path.join(RESULTS_DIR, task_id, _safe_name(file_name))
            os.makedirs(dest_dir, exist_ok=True)
            self._extract(content, dest_dir)
            self.database.update_file(task_id, file_name, result_path=dest_dir)
        except Exception as e:
            self.database.update_file(task_id, file_name, error=f"download failed: {e}")

    @staticmethod
    def _extract(content, dest_dir):
        if content[:2] == b"PK":
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                z.extractall(dest_dir)
        else:
            with open(os.path.join(dest_dir, "result.bin"), "wb") as f:
                f.write(content)

    # ---- results ----
    def result_dir(self, task_id):
        return os.path.join(RESULTS_DIR, task_id)

    def build_download_zip(self, task_id):
        base = self.result_dir(task_id)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            if os.path.isdir(base):
                for root, dirs, files in os.walk(base):
                    for f in files:
                        full = os.path.join(root, f)
                        arc = os.path.relpath(full, base)
                        z.write(full, arc)
        buf.seek(0)
        return buf

    def build_file_download_zip(self, task_id, file_name):
        base = os.path.join(self.result_dir(task_id), _safe_name(file_name))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            if os.path.isdir(base):
                for root, dirs, files in os.walk(base):
                    for f in files:
                        full = os.path.join(root, f)
                        arc = os.path.relpath(full, base)
                        z.write(full, arc)
        buf.seek(0)
        return buf
