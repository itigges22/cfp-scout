"""Scout FastAPI service.

Serves the JSON API at /api/v1/* and the built React SPA at /.
APScheduler runs in-process via the FastAPI lifespan (wired in step 13).
"""

__version__ = "0.1.0"
