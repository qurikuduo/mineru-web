# -*- coding: utf-8 -*-
"""MinerU Web Console: FastAPI app."""
import logging
import os
from typing import List, Optional

from fastapi import (Depends, FastAPI, File, Form, HTTPException, UploadFile)
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from . import auth
from .auth import get_current_user
from .config import Config, make_token
from .db import DB
from .logging_setup import setup_logging
from .task_manager import TaskManager
from .version import VERSION

log = setup_logging()
config = Config()
auth.init_config(config)
database = DB()
manager = TaskManager(config, database)

app = FastAPI(title="MinerU Web Console", version=VERSION)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


@app.on_event("startup")
def _startup():
    manager.start()
    log.info("MinerU Web Console started, data_dir=%s, mineru=%s",
             os.environ.get("MINERU_WEB_DATA_DIR", "/data"),
             config.get("mineru_base_url"))


@app.on_event("shutdown")
def _shutdown():
    manager.stop()


# ---- health (no auth) ----
@app.get("/api/health")
def health():
    return {"status": "ok", "mineru_base_url": config.get("mineru_base_url"), "version": VERSION}


# ---- auth ----
@app.post("/api/login")
def login(payload: dict):
    username = payload.get("username", "")
    password = payload.get("password", "")
    if not config.verify_login(username, password):
        raise HTTPException(401, "用户名或密码错误")
    token = make_token(username, config.secret())
    return {"token": token, "username": username}


@app.get("/api/me")
def me(username: str = Depends(get_current_user)):
    return {"username": username}


# ---- config ----
@app.get("/api/config")
def get_config(username: str = Depends(get_current_user)):
    return config.public()


@app.put("/api/config")
def put_config(payload: dict, username: str = Depends(get_current_user)):
    if "mineru_base_url" in payload:
        config.set_mineru_url(payload["mineru_base_url"])
    if "defaults" in payload and isinstance(payload["defaults"], dict):
        config.set_defaults(payload["defaults"])
    if "password" in payload and payload["password"]:
        new_user = payload.get("username") or username
        config.set_password(new_user, payload["password"])
    return config.public()


@app.post("/api/config/test")
def test_config(payload: dict, username: str = Depends(get_current_user)):
    from .mineru_client import MinerUClient
    url = payload.get("mineru_base_url") or config.get("mineru_base_url")
    try:
        data = MinerUClient(url).health()
        return {"ok": True, "version": data.get("version"), "url": url}
    except Exception as e:
        return {"ok": False, "error": str(e), "url": url}


# ---- tasks ----
@app.post("/api/tasks")
async def create_task(
    files: List[UploadFile] = File(...),
    tier: Optional[str] = Form(None),
    ocr_mode: Optional[str] = Form(None),
    output_formats: Optional[str] = Form(None),
    username: str = Depends(get_current_user),
):
    if not files:
        raise HTTPException(400, "没有上传文件")
    if tier:
        config.set_defaults({"tier": tier})
    if ocr_mode:
        config.set_defaults({"ocr_mode": ocr_mode})
    if output_formats:
        config.set_defaults({"output_formats": [f.strip() for f in output_formats.split(",") if f.strip()]})

    payload = []
    for f in files:
        data = await f.read()
        payload.append((f.filename or "file", data))

    try:
        task_id = manager.create_task(payload)
    except Exception as e:
        raise HTTPException(500, f"创建任务失败: {e}")
    return manager.database.get_task(task_id)


@app.get("/api/tasks")
def list_tasks(username: str = Depends(get_current_user)):
    tasks = manager.database.list_tasks()
    for t in tasks:
        t["files"] = manager.database.get_files(t["id"])
    return tasks


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str, username: str = Depends(get_current_user)):
    t = manager.database.get_task(task_id)
    if not t:
        raise HTTPException(404, "任务不存在")
    return t


@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: str, username: str = Depends(get_current_user)):
    manager.database.delete_task(task_id)
    import shutil
    shutil.rmtree(manager.result_dir(task_id), ignore_errors=True)
    return {"ok": True}


@app.get("/api/tasks/{task_id}/download")
def download_task(task_id: str, username: str = Depends(get_current_user)):
    t = manager.database.get_task(task_id)
    if not t:
        raise HTTPException(404, "任务不存在")
    if t["status"] not in ("completed", "partial"):
        raise HTTPException(409, "任务尚未完成，无法下载")
    buf = manager.build_download_zip(task_id)
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{task_id}.zip"'},
    )


@app.get("/api/tasks/{task_id}/files/{file_name}/download")
def download_file(task_id: str, file_name: str, username: str = Depends(get_current_user)):
    buf = manager.build_file_download_zip(task_id, file_name)
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{file_name}.zip"'},
    )


# ---- static frontend (must be last) ----
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
