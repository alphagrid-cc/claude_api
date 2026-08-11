"""Bearer-Auth fuer die eigene API (constant-time Vergleich)."""

from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, status

from .config import settings


def _extract_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip()


async def require_bearer(authorization: str | None = Header(default=None)) -> None:
    """FastAPI-Dependency: prueft Authorization: Bearer <GATEWAY_TOKEN>."""
    if not settings.gateway_token:
        # Fail closed: ohne konfigurierten Token ist die API gesperrt.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Server nicht konfiguriert: GATEWAY_TOKEN fehlt.",
        )

    token = _extract_bearer(authorization)
    if token is None or not secrets.compare_digest(token, settings.gateway_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ungueltiger oder fehlender Bearer-Token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
