# -*- coding: utf-8 -*-
"""Thin client for the MinerU 4.x API."""
import requests

TIMEOUT = (10, 120)


class MinerUError(Exception):
    def __init__(self, message, code="mineru_error"):
        super().__init__(message)
        self.code = code
        self.message = message


class MinerUClient:
    def __init__(self, base_url: str):
        self.base_url = (base_url or "").strip().rstrip("/")

    def _url(self, path):
        return f"{self.base_url}{path}"

    def health(self):
        r = requests.get(self._url("/v1/health"), timeout=(5, 15))
        r.raise_for_status()
        return r.json()

    def create_task(self, tier, ocr_mode, output_formats, files):
        """files: list of {"file_name": str, "bytes": int}"""
        body = {
            "tier": tier,
            "ocr_mode": ocr_mode,
            "output_formats": output_formats,
            "files": [{"file_name": f["file_name"], "bytes": f["bytes"], "url": None} for f in files],
        }
        r = requests.post(self._url("/v1/tasks"), json=body, timeout=TIMEOUT)
        if r.status_code >= 400:
            raise MinerUError(_fmt_http(r), code="create_task_failed")
        return r.json()

    def upload_file(self, upload, data):
        url = upload["url"]
        headers = dict(upload.get("headers") or {})
        headers["Content-Type"] = "application/octet-stream"
        r = requests.put(url, data=data, headers=headers, timeout=(10, 600))
        if r.status_code >= 400:
            raise MinerUError(_fmt_http(r), code="upload_failed")
        return r.json()

    def get_task(self, task_id):
        r = requests.get(self._url(f"/v1/tasks/{task_id}"), timeout=TIMEOUT)
        if r.status_code >= 400:
            raise MinerUError(_fmt_http(r), code="get_task_failed")
        return r.json()

    def download(self, url):
        r = requests.get(url, timeout=(10, 600))
        if r.status_code >= 400:
            raise MinerUError(_fmt_http(r), code="download_failed")
        return r.content


def _fmt_http(r):
    try:
        body = r.json()
        err = body.get("error") or body.get("detail")
        if isinstance(err, dict):
            msg = err.get("message") or json_dumps(err)
        elif isinstance(err, list):
            msg = "; ".join(e.get("msg", str(e)) for e in err)
        else:
            msg = str(err)
        return f"{r.status_code}: {msg}"
    except Exception:
        return f"{r.status_code}: {r.text[:300]}"


def json_dumps(o):
    import json
    return json.dumps(o, ensure_ascii=False)
