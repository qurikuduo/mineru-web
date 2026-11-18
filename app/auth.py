# -*- coding: utf-8 -*-
"""HTTP auth: bearer-token dependency."""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from .config import Config, verify_token

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> str:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    username = verify_token(credentials.credentials, _config().secret())
    if not username:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    return username


_config_instance = None


def init_config(config: Config):
    global _config_instance
    _config_instance = config


def _config() -> Config:
    return _config_instance
