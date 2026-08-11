# Claude Code Remote API

Run **Claude Code inside a container and drive it over HTTP.** A small FastAPI
wrapper exposes a lean API with **two interfaces**:

- **One-shot** (`/v1/oneshot`) — a stateless single prompt.
- **Sessions** (`/v1/sessions/...`) — persistent, agentic, multi-turn work on a
  workspace (Claude can read/write files, run bash, etc.), streamed over SSE.

Authentication uses **your Claude Code subscription** (an OAuth token), **not** a
pay-per-token API key.

> 🇩🇪 Deutsche Version: [README.de.md](README.de.md)

> ⚠️ **Personal use.** Anthropic does not permit offering claude.ai login / your
> subscription's rate limits as a service to third parties. Run this for
> yourself, not as a multi-user/public service.

---

## 1. Authentication (create a subscription token)

Once, **locally** (a browser is needed):

```bash
claude setup-token
```

This prints a long-lived (~1 year) OAuth token. Copy it — it is not stored
anywhere automatically. Re-run when it expires.

Do **not** set `ANTHROPIC_API_KEY`: if present it takes precedence and you'd be
billed per token instead of using your subscription. (The server even strips it
on startup and warns.)

---

## 2. Configuration

```bash
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(32))"   # -> GATEWAY_TOKEN
```

Set in `.env`:
- `GATEWAY_TOKEN` — the bearer token clients must send.
- `CLAUDE_CODE_OAUTH_TOKEN` — the token from `claude setup-token`.

---

## 3. Run

**Docker (quickest — builds locally + optional Caddy for TLS):**
```bash
docker compose up --build -d
```

**Prebuilt image behind your own reverse proxy:**
```bash
docker compose -f deploy/compose.yml up -d      # pulls ghcr.io/alphagrid-cc/claude_api
```

**Without Docker (local dev):**
```bash
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
export $(grep -v '^#' .env | xargs)
./.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Verify subscription auth works end-to-end:
```bash
bash scripts/smoke_auth.sh
```

See [deploy/README.md](deploy/README.md) for self-hosting behind a reverse proxy.

---

## 4. API

All `/v1` routes require `Authorization: Bearer <GATEWAY_TOKEN>`.

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Liveness (no auth) |
| POST | `/v1/oneshot` | Single prompt (JSON or SSE) |
| POST | `/v1/sessions` | Create a session (optional `git_repo`) |
| GET | `/v1/sessions` | List sessions |
| GET | `/v1/sessions/{id}` | Session status |
| POST | `/v1/sessions/{id}/messages` | Send a turn → **SSE stream** |
| POST | `/v1/sessions/{id}/interrupt` | Abort the running turn |
| DELETE | `/v1/sessions/{id}?remove_workspace=true` | Close a session |

### One-shot (JSON)
```bash
curl -s http://localhost:8000/v1/oneshot \
  -H "Authorization: Bearer $GATEWAY_TOKEN" -H "Content-Type: application/json" \
  -d '{"prompt":"Reply with just: OK"}'
```

### Session (clone a repo, then work agentically)
```bash
SID=$(curl -s http://localhost:8000/v1/sessions \
  -H "Authorization: Bearer $GATEWAY_TOKEN" -H "Content-Type: application/json" \
  -d '{"workspace":"projectA","permission_mode":"acceptEdits"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['session_id'])")

curl -N http://localhost:8000/v1/sessions/$SID/messages \
  -H "Authorization: Bearer $GATEWAY_TOKEN" -H "Content-Type: application/json" \
  -d '{"prompt":"Create hello.txt containing \"hi\"."}'
```

SSE `event:` types: `system`, `assistant` (text/thinking/tool_use), `user`
(tool results), `result` (final, incl. `usage` / `total_cost_usd`), `error`.
A Python client example is in [examples/client.py](examples/client.py).

### Request parameters (excerpt)
- `permission_mode`: `default` | `acceptEdits` | `plan` | `bypassPermissions` | `dontAsk` | `auto`
- `allowed_tools` / `disallowed_tools`: e.g. `["Read","Bash"]`
- `model`, `system_prompt`, `max_turns`, `workspace`, `git_repo`, `git_ref`

---

## 5. Security

- The agent can **write files and run bash** inside its workspace. Run the
  container isolated (non-root, dedicated volume) and consider an egress firewall.
- Expose a public endpoint only behind **HTTPS + a strong `GATEWAY_TOKEN`**;
  an additional access layer (IP allowlist / access proxy) is recommended.
- Secrets are runtime env only (`.env`) — never baked into the image or committed.

## 6. Architecture

```
Client ──HTTPS──▶ reverse proxy ──▶ FastAPI gateway ──▶ SessionManager
                                          │                 │ (one ClaudeSDKClient per session)
                                          ▼                 ▼
                                     Runner (options) ─▶ Claude Agent SDK ─▶ Claude Code CLI
                                                            auth: CLAUDE_CODE_OAUTH_TOKEN (env)
```

Modules: `app/main.py` (routes/SSE), `app/auth.py` (bearer), `app/config.py`
(settings), `app/models.py` (schemas), `app/runner.py` (options + one-shot),
`app/sessions.py` (session manager), `app/streaming.py` (message → SSE).

## License

[MIT](LICENSE)
