"""FastAPI-Gateway: schlanke API vor Claude Code (One-shot + Sessions)."""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager

import claude_agent_sdk
from claude_agent_sdk import ResultMessage
from fastapi import Depends, FastAPI, Request, status
from fastapi.responses import JSONResponse, StreamingResponse

from . import __version__
from .auth import require_bearer
from .config import settings
from .models import (
    CreateSessionRequest,
    CreateSessionResponse,
    MessageRequest,
    OneShotRequest,
    OneShotResponse,
    SessionInfo,
)
from .runner import build_options, oneshot_stream
from .sessions import SessionError, SessionManager, _safe_workspace
from .streaming import error_event, serialize_message, sse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("claude_api")

manager = SessionManager()

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Abo erzwingen: ANTHROPIC_API_KEY haette Vorrang -> entfernen + warnen.
    if os.environ.pop("ANTHROPIC_API_KEY", None):
        logger.warning(
            "ANTHROPIC_API_KEY war gesetzt und wurde ignoriert, um den Abo-Betrieb "
            "(CLAUDE_CODE_OAUTH_TOKEN) zu erzwingen."
        )
    if not os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        logger.warning(
            "CLAUDE_CODE_OAUTH_TOKEN ist nicht gesetzt - Claude-Aufrufe werden fehlschlagen. "
            "Lokal einmalig `claude setup-token` ausfuehren und den Token setzen."
        )
    if not settings.gateway_token:
        logger.warning("GATEWAY_TOKEN ist nicht gesetzt - die API ist gesperrt (503).")
    manager.start()
    logger.info("Claude Code Remote API v%s gestartet.", __version__)
    try:
        yield
    finally:
        await manager.shutdown()


app = FastAPI(title="Claude Code Remote API", version=__version__, lifespan=lifespan)


# ---- Rate-Limit (einfaches Sliding-Window je Client-IP) -----------------
_hits: dict[str, deque[float]] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    if request.url.path.startswith("/v1") and settings.rate_limit_per_minute > 0:
        ip = _client_ip(request)
        now = time.time()
        bucket = _hits[ip]
        while bucket and now - bucket[0] > 60:
            bucket.popleft()
        if len(bucket) >= settings.rate_limit_per_minute:
            return JSONResponse({"detail": "Rate limit ueberschritten."}, status_code=429)
        bucket.append(now)
    return await call_next(request)


@app.exception_handler(SessionError)
async def session_error_handler(request: Request, exc: SessionError):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


# ---- Health -------------------------------------------------------------
def _versions() -> dict[str, str | None]:
    """Laufende SDK-/CLI-Versionen (fuers Monitoring auf veraltete Images)."""
    cli: str | None = None
    if not settings.claude_cli_path:  # sonst laeuft eine fremde Binary
        try:
            from claude_agent_sdk._cli_version import __cli_version__ as cli
        except ImportError:  # privates Modul, kann sich aendern
            pass
    return {"claude_agent_sdk": claude_agent_sdk.__version__, "claude_code_cli": cli}


VERSIONS = _versions()


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": __version__,
        "auth_configured": bool(settings.gateway_token),
        "oauth_token_present": bool(os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")),
        "active_sessions": len(manager.list()),
        "versions": VERSIONS,
    }


# ---- One-shot -----------------------------------------------------------
@app.post("/v1/oneshot", dependencies=[Depends(require_bearer)])
async def oneshot(req: OneShotRequest):
    cwd = _safe_workspace(req.workspace or "_oneshot")
    options = build_options(
        cwd=cwd,
        allowed_tools=req.allowed_tools,
        disallowed_tools=req.disallowed_tools,
        permission_mode=req.permission_mode,
        model=req.model,
        effort=req.effort,
        system_prompt=req.system_prompt,
        max_turns=req.max_turns,
    )

    if req.stream:
        async def gen():
            try:
                async for msg in oneshot_stream(req.prompt, options):
                    event = serialize_message(msg)
                    if event is not None:
                        yield sse(event)
            except Exception as exc:  # SDK meldet Fehler teils als bare Exception
                logger.error("Agent-Fehler (oneshot stream): %s", exc)
                yield sse(error_event(str(exc)))

        return StreamingResponse(gen(), media_type="text/event-stream", headers=SSE_HEADERS)

    result: ResultMessage | None = None
    try:
        async for msg in oneshot_stream(req.prompt, options):
            if isinstance(msg, ResultMessage):
                result = msg
    except Exception as exc:  # SDK meldet Fehler teils als bare Exception
        logger.error("Agent-Fehler (oneshot): %s", exc)
        return JSONResponse({"detail": f"Agent-Fehler: {exc}"}, status_code=502)
    if result is None:
        return JSONResponse({"detail": "Kein Ergebnis vom Agenten erhalten."}, status_code=502)
    return OneShotResponse(
        result=result.result or "",
        session_id=result.session_id,
        is_error=result.is_error,
        num_turns=result.num_turns,
        duration_ms=result.duration_ms,
        total_cost_usd=result.total_cost_usd,
        usage=result.usage,
    )


# ---- Sessions -----------------------------------------------------------
@app.post("/v1/sessions", dependencies=[Depends(require_bearer)])
async def create_session(req: CreateSessionRequest) -> CreateSessionResponse:
    sess = await manager.create(req)
    return CreateSessionResponse(session_id=sess.id, workspace=str(sess.workspace))


@app.get("/v1/sessions", dependencies=[Depends(require_bearer)])
async def list_sessions() -> list[SessionInfo]:
    return manager.list()


@app.get("/v1/sessions/{session_id}", dependencies=[Depends(require_bearer)])
async def get_session(session_id: str) -> SessionInfo:
    return manager.get(session_id).info()


@app.post("/v1/sessions/{session_id}/messages", dependencies=[Depends(require_bearer)])
async def send_message(session_id: str, req: MessageRequest):
    # Vorab pruefen, damit 404/409 als sauberer HTTP-Status statt im Stream landen.
    sess = manager.get(session_id)
    if sess.lock.locked():
        raise SessionError(409, "Session verarbeitet bereits einen Turn.")

    async def gen():
        try:
            async for event in manager.send(session_id, req.prompt):
                yield sse(event)
        except Exception as exc:  # SDK meldet Fehler teils als bare Exception
            logger.error("Agent-Fehler (session %s): %s", session_id, exc)
            yield sse(error_event(str(exc)))

    return StreamingResponse(gen(), media_type="text/event-stream", headers=SSE_HEADERS)


@app.post(
    "/v1/sessions/{session_id}/interrupt",
    dependencies=[Depends(require_bearer)],
    status_code=status.HTTP_202_ACCEPTED,
)
async def interrupt_session(session_id: str):
    await manager.interrupt(session_id)
    return {"status": "interrupted"}


@app.delete("/v1/sessions/{session_id}", dependencies=[Depends(require_bearer)])
async def delete_session(session_id: str, remove_workspace: bool = False):
    await manager.delete(session_id, remove_workspace=remove_workspace)
    return {"status": "deleted"}
