"""Version 1 of the Scout JSON API — the package that holds every router.

WHAT THIS DOES
    Nothing on its own. Each sibling module in this package builds one
    FastAPI ``APIRouter``; ``app/main.py`` imports them all from here and
    registers each with ``include_router``.

HOW IT CONNECTS
    Called by   app/main.py (imports every module in this package by name)
    Routes      everything here is served under the /api/v1 URL prefix
"""
