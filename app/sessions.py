"""Session-Management fuer stateful/agentische Nutzung.

Pro Session:
- ein persistenter `ClaudeSDKClient` (bleibt ueber mehrere Turns verbunden)
- ein Workspace-Verzeichnis (unterhalb WORKSPACES_DIR)
- ein `asyncio.Lock` (ein Turn zur Zeit je Session)
- TTL-basierte Aufraeumung inaktiver Sessions
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import shutil
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from claude_agent_sdk import ClaudeSDKClient, ResultMessage

from .config import settings
from .models import CreateSessionRequest, SessionInfo
from .runner import build_options
from .streaming import serialize_message

logger = logging.getLogger("claude_api.sessions")


class SessionError(Exception):
    """Fachliche Fehler des SessionManagers (Mapping auf HTTP in main.py)."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def _safe_workspace(name: str | None) -> Path:
    """Loest einen Workspace-Pfad sicher innerhalb WORKSPACES_DIR auf."""
    base = settings.resolved_workspaces_dir()
    if not name:
        name = "ws-" + secrets.token_hex(6)
    # Nur einfache Namen zulassen; kein Path-Traversal.
    candidate = (base / name).resolve()
    if candidate != base and base not in candidate.parents:
        raise SessionError(400, "Ungueltiger workspace-Name.")
    candidate.mkdir(parents=True, exist_ok=True)
    return candidate


async def _git_clone(repo: str, ref: str | None, dest: Path) -> None:
    args = ["git", "clone", "--depth", "1"]
    if ref:
        args += ["--branch", ref]
    args += [repo, str(dest)]
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise SessionError(400, f"git clone fehlgeschlagen: {stderr.decode(errors='replace')[:500]}")


@dataclass
class Session:
    id: str
    workspace: Path
    client: ClaudeSDKClient
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    status: str = "idle"  # idle | busy | closed
    num_messages: int = 0
    claude_session_id: str | None = None

    def info(self) -> SessionInfo:
        return SessionInfo(
            session_id=self.id,
            workspace=str(self.workspace),
            status=self.status,  # type: ignore[arg-type]
            created_at=self.created_at,
            last_active=self.last_active,
            num_messages=self.num_messages,
            claude_session_id=self.claude_session_id,
        )


class SessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._cleanup_task: asyncio.Task[None] | None = None

    # ---- Lifecycle ----------------------------------------------------
    def start(self) -> None:
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def shutdown(self) -> None:
        if self._cleanup_task:
            self._cleanup_task.cancel()
        for sess in list(self._sessions.values()):
            await self._close(sess, remove_workspace=False)
        self._sessions.clear()

    # ---- CRUD ---------------------------------------------------------
    async def create(self, req: CreateSessionRequest) -> Session:
        if len(self._sessions) >= settings.max_sessions:
            raise SessionError(429, "Maximale Anzahl gleichzeitiger Sessions erreicht.")

        workspace = _safe_workspace(req.workspace)
        if req.git_repo:
            # Nur in leeren Workspace klonen.
            if any(workspace.iterdir()):
                raise SessionError(400, "Workspace ist nicht leer; git_repo abgelehnt.")
            await _git_clone(req.git_repo, req.git_ref, workspace)

        options = build_options(
            cwd=workspace,
            allowed_tools=req.allowed_tools,
            disallowed_tools=req.disallowed_tools,
            permission_mode=req.permission_mode,
            model=req.model,
            effort=req.effort,
            system_prompt=req.system_prompt,
            max_turns=req.max_turns,
        )
        client = ClaudeSDKClient(options=options)
        try:
            await client.connect()
        except Exception as exc:  # z.B. fehlende Auth / managed settings
            logger.error("connect() fehlgeschlagen: %s", exc)
            raise SessionError(502, f"Verbindung zu Claude Code fehlgeschlagen: {exc}") from exc

        session_id = "sess-" + secrets.token_hex(8)
        session = Session(id=session_id, workspace=workspace, client=client)
        self._sessions[session_id] = session
        logger.info("Session %s erstellt (workspace=%s)", session_id, workspace)
        return session

    def get(self, session_id: str) -> Session:
        sess = self._sessions.get(session_id)
        if sess is None:
            raise SessionError(404, "Session nicht gefunden.")
        return sess

    def list(self) -> list[SessionInfo]:
        return [s.info() for s in self._sessions.values()]

    async def send(self, session_id: str, prompt: str) -> AsyncIterator[dict[str, Any]]:
        """Sendet einen Turn und streamt die Events bis zur ResultMessage."""
        sess = self.get(session_id)
        if sess.lock.locked():
            raise SessionError(409, "Session verarbeitet bereits einen Turn.")

        async with sess.lock:
            sess.status = "busy"
            sess.last_active = time.time()
            sess.num_messages += 1
            try:
                await sess.client.query(prompt)
                async for msg in sess.client.receive_response():
                    if isinstance(msg, ResultMessage) and msg.session_id:
                        sess.claude_session_id = msg.session_id
                    event = serialize_message(msg)
                    if event is not None:
                        yield event
            finally:
                sess.status = "idle"
                sess.last_active = time.time()

    async def interrupt(self, session_id: str) -> None:
        sess = self.get(session_id)
        await sess.client.interrupt()

    async def delete(self, session_id: str, remove_workspace: bool = False) -> None:
        sess = self._sessions.pop(session_id, None)
        if sess is None:
            raise SessionError(404, "Session nicht gefunden.")
        await self._close(sess, remove_workspace=remove_workspace)

    # ---- intern -------------------------------------------------------
    async def _close(self, sess: Session, remove_workspace: bool) -> None:
        sess.status = "closed"
        try:
            await sess.client.disconnect()
        except Exception as exc:  # pragma: no cover - best effort
            logger.warning("disconnect fehlgeschlagen (%s): %s", sess.id, exc)
        if remove_workspace:
            shutil.rmtree(sess.workspace, ignore_errors=True)

    async def _cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(60)
            now = time.time()
            ttl = settings.session_ttl_seconds
            stale = [
                s
                for s in self._sessions.values()
                if s.status == "idle" and (now - s.last_active) > ttl
            ]
            for sess in stale:
                logger.info("Session %s laeuft ab (idle > %ss)", sess.id, ttl)
                self._sessions.pop(sess.id, None)
                await self._close(sess, remove_workspace=False)
