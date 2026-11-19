# -*- coding: utf-8 -*-
"""Single source of truth for the application version.

Bump this on every release; it is surfaced in /api/health, the FastAPI
metadata, the web UI, and used for the Docker/Harbor image tag.
"""

VERSION = "1.1.0"
