"""Scout — the API package.

One process serves the JSON API under /api/v1 and the built React UI at /.
Start reading at ``app/main.py`` (what gets served) and ``app/lifespan.py``
(what happens at boot). Background work lives in ``app/tasks/``, driven by
``app/scheduler.py``.
"""

__version__ = "0.1.0"
