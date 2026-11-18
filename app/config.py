# -*- coding: utf-8 -*-
"""Persistent configuration (MinerU address, auth credentials, defaults).

Config lives in a JSON file under a mounted volume so it survives container
restarts. Auth password is stored only as a PBKDF2 hash.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time

DATA_DIR = os.environ.get("MINERU_WEB_DATA_DIR", "/data")
CONFIG_DIR = os.path.join(DATA_DIR, "config")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

PBKDF2_ITERATIONS = 200_000

DEFAULT_CONFIG = {
    "mineru_base_url": os.environ.get("MINERU_WEB_BASE_URL", "http://172.171.16.221:28001"),
    "auth": {
        "username": os.environ.get("MINERU_WEB_USERNAME", "admin"),
        "password_hash": None,
        "password_salt": None,
    },
    "secret": None,
    "defaults": {
        "tier": "flash",
        "ocr_mode": "auto",
        "output_formats": ["default"],
    },
}


def _hash_password(password: str, salt: bytes = None):
    if salt is None:
        salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return base64.b64encode(dk).decode("ascii"), base64.b64encode(salt).decode("ascii")


def _verify_password(password: str, hash_b64: str, salt_b64: str) -> bool:
    try:
        salt = base64.b64decode(salt_b64.encode("ascii"))
        expected = base64.b64decode(hash_b64.encode("ascii"))
    except Exception:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return hmac.compare_digest(dk, expected)


class Config:
    """Thread-safe config store backed by a JSON file."""

    def __init__(self):
        self._lock = threading.RLock()
        self.data = self._load()

    def _load(self):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
            except Exception:
                loaded = {}
            cfg = json.loads(json.dumps(DEFAULT_CONFIG))
            self._deep_update(cfg, loaded)
        else:
            cfg = json.loads(json.dumps(DEFAULT_CONFIG))
        # Ensure secret + password exist on first run.
        if not cfg.get("secret"):
            cfg["secret"] = secrets.token_hex(32)
        pw_hash = cfg["auth"].get("password_hash")
        pw_salt = cfg["auth"].get("password_salt")
        if not pw_hash or not pw_salt:
            env_pw = os.environ.get("MINERU_WEB_PASSWORD")
            if env_pw:
                pw = env_pw
            else:
                pw = cfg["auth"]["username"] or "admin"
                pw = "admin123"  # sane default for an internal tool
            cfg["auth"]["password_hash"], cfg["auth"]["password_salt"] = _hash_password(pw)
        self._save(cfg)
        return cfg

    @staticmethod
    def _deep_update(base, extra):
        for k, v in extra.items():
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                Config._deep_update(base[k], v)
            else:
                base[k] = v

    def _save(self, cfg):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CONFIG_PATH)

    def get(self, key, default=None):
        with self._lock:
            return self.data.get(key, default)

    def public(self):
        """Config safe to expose to the (authenticated) client."""
        with self._lock:
            return {
                "mineru_base_url": self.data.get("mineru_base_url"),
                "username": self.data.get("auth", {}).get("username"),
                "defaults": self.data.get("defaults", {}),
            }

    def set_mineru_url(self, url: str):
        url = (url or "").strip().rstrip("/")
        with self._lock:
            self.data["mineru_base_url"] = url
            self._save(self.data)
        return url

    def set_defaults(self, defaults: dict):
        with self._lock:
            cur = self.data.setdefault("defaults", {})
            for k in ("tier", "ocr_mode", "output_formats"):
                if k in defaults:
                    cur[k] = defaults[k]
            self._save(self.data)
        return cur

    def verify_login(self, username: str, password: str) -> bool:
        with self._lock:
            a = self.data.get("auth", {})
            if username != a.get("username"):
                return False
            return _verify_password(password, a.get("password_hash"), a.get("password_salt"))

    def secret(self):
        with self._lock:
            return self.data["secret"]

    def set_password(self, username: str, password: str):
        h, s = _hash_password(password)
        with self._lock:
            self.data["auth"]["username"] = username
            self.data["auth"]["password_hash"] = h
            self.data["auth"]["password_salt"] = s
            self._save(self.data)


def make_token(username: str, secret: str, ttl: int = 7 * 24 * 3600) -> str:
    payload = {"u": username, "exp": int(time.time()) + ttl}
    body = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii").rstrip("=")
    sig = hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def verify_token(token: str, secret: str):
    try:
        body, sig = token.split(".", 1)
    except ValueError:
        return None
    expected = hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except Exception:
        return None
    if payload.get("exp", 0) < time.time():
        return None
    return payload.get("u")
