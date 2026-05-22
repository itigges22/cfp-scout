"""Digest services (plan 24).

Today: CFP-closing digest. Future digests (weekly status, anomalies) plug
in here as siblings.
"""

from app.services.digest.cfp import build_cfp_digest

__all__ = ["build_cfp_digest"]
