# Claude Code Remote API

Betreibe **Claude Code in einem Container** und steuere ihn **von außen per HTTP**.
Der Container stellt eine eigene, schlanke API bereit mit **zwei Interfaces**:

- **One-shot** (`/v1/oneshot`) — zustandsloser Einzel-Prompt.
- **Sessions** (`/v1/sessions/...`) — persistente, agentische Multi-Turn-Arbeit auf einem Workspace (Claude darf Dateien lesen/schreiben, Bash ausführen usw.).

Authentifizierung läuft über **dein Claude-Code-Abo** (OAuth-Token), **nicht** über einen pay-per-token API-Key.

> ⚠️ **Nur für den Eigengebrauch.** Anthropic erlaubt es nicht, claude.ai-Login/Abo-Ratenlimits als Dienst für Dritte anzubieten. Betreibe das nicht als Multi-User-/öffentlichen Dienst.

---

## 1. Anmeldung (Abo-Token erzeugen)

Einmalig **lokal** (Browser nötig):

```bash
claude setup-token
```

Das gibt einen **~1 Jahr gültigen OAuth-Token** aus. Kopiere ihn — er wird nirgends automatisch gespeichert. Nach Ablauf erneut ausführen.

Wichtig: Setze **keinen** `ANTHROPIC_API_KEY`. Wäre er gesetzt, hätte er Vorrang → Abrechnung per Token statt über dein Abo. Der Server entfernt ihn beim Start sogar bewusst aus der Umgebung und warnt.

---

## 2. Konfiguration

```bash
cp .env.example .env
# GATEWAY_TOKEN erzeugen:
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

In `.env` eintragen:
- `GATEWAY_TOKEN` — dein eigener Bearer-Token (Clients müssen ihn senden).
- `CLAUDE_CODE_OAUTH_TOKEN` — der Token aus `claude setup-token`.

---

## 3. Lokal starten (ohne Docker)

```bash
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
export $(grep -v '^#' .env | xargs)   # .env laden
./.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Smoke-Test der Abo-Auth:

```bash
bash scripts/smoke_auth.sh
```

---

## 4. Mit Docker / Compose starten

```bash
docker compose up --build -d
```

- `api` (intern, Port 8000) hinter **Caddy** (HTTPS, automatisches Zertifikat).
- Domain in `Caddyfile` eintragen. Für rein privaten Betrieb (Tailscale/VPN) kann Caddy entfallen — dann bei `api` `ports: ["127.0.0.1:8000:8000"]` setzen.
- Workspaces liegen im benannten Volume `workspaces` (überleben Neustarts).

---

## 5. API

Alle `/v1`-Routen erfordern den Header `Authorization: Bearer <GATEWAY_TOKEN>`.

| Methode | Pfad | Zweck |
|--------|------|-------|
| GET | `/health` | Liveness (ohne Auth) |
| POST | `/v1/oneshot` | Einzel-Prompt (JSON oder SSE) |
| POST | `/v1/sessions` | Session anlegen (optional `git_repo`) |
| GET | `/v1/sessions` | Sessions auflisten |
| GET | `/v1/sessions/{id}` | Session-Status |
| POST | `/v1/sessions/{id}/messages` | Turn senden → **SSE-Stream** |
| POST | `/v1/sessions/{id}/interrupt` | laufenden Turn abbrechen |
| DELETE | `/v1/sessions/{id}?remove_workspace=true` | Session schließen |

### One-shot (JSON)

```bash
curl -s http://localhost:8000/v1/oneshot \
  -H "Authorization: Bearer $GATEWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Antworte nur mit: OK"}'
```

### One-shot (Streaming, SSE)

```bash
curl -N http://localhost:8000/v1/oneshot \
  -H "Authorization: Bearer $GATEWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Erklaere kurz Rekursion","stream":true}'
```

### Session: Repo klonen, dann agentisch arbeiten

```bash
# 1) Session anlegen (optional Repo klonen)
SID=$(curl -s http://localhost:8000/v1/sessions \
  -H "Authorization: Bearer $GATEWAY_TOKEN" -H "Content-Type: application/json" \
  -d '{"workspace":"projektA","permission_mode":"acceptEdits"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['session_id'])")

# 2) Turn senden (SSE-Stream)
curl -N http://localhost:8000/v1/sessions/$SID/messages \
  -H "Authorization: Bearer $GATEWAY_TOKEN" -H "Content-Type: application/json" \
  -d '{"prompt":"Lege eine Datei hello.txt mit Inhalt \"hallo\" an."}'

# 3) Folge-Turn (Kontext bleibt erhalten)
curl -N http://localhost:8000/v1/sessions/$SID/messages \
  -H "Authorization: Bearer $GATEWAY_TOKEN" -H "Content-Type: application/json" \
  -d '{"prompt":"Was steht in der Datei, die du eben angelegt hast?"}'
```

### SSE-Event-Typen

`event:`-Namen im Stream: `system`, `assistant` (Text/Thinking/Tool-Use), `user` (Tool-Ergebnisse), `result` (Abschluss inkl. `usage`, `total_cost_usd`), `stream` (Partials, falls aktiviert), `rate_limit`.

Ein Python-Client-Beispiel liegt in [`examples/client.py`](examples/client.py).

---

## 6. Request-Parameter (Auszug)

- `permission_mode`: `default` | `acceptEdits` | `plan` | `bypassPermissions` | `dontAsk` | `auto`
- `allowed_tools` / `disallowed_tools`: Tool-Allow-/Blocklist (z.B. `["Read","Bash"]`)
- `model`: optionales Modell (leer = Claude-Code-Default)
- `system_prompt`, `max_turns`, `workspace`, `git_repo`, `git_ref`

---

## 7. Sicherheit

- Der Agent darf im Workspace **frei Dateien schreiben und Bash ausführen**. Betreibe den Container isoliert (non-root, eigenes Volume), erwäge eine Egress-Firewall.
- Öffentlicher Endpoint nur hinter **HTTPS + starkem `GATEWAY_TOKEN`**.
- `permission_mode` konservativ wählen; `bypassPermissions` nur bewusst einsetzen.
- Secrets niemals ins Image bauen und niemals loggen.

## 8. Architektur

```
Client ──HTTPS──▶ Caddy ──▶ FastAPI-Gateway ──▶ SessionManager
                                    │                 │  (ClaudeSDKClient pro Session)
                                    ▼                 ▼
                              Runner (build_options) ─▶ Claude Agent SDK ─▶ Claude Code CLI
                                                          Auth: CLAUDE_CODE_OAUTH_TOKEN (env)
```

Module: `app/main.py` (Routen/SSE), `app/auth.py` (Bearer), `app/config.py` (Settings),
`app/models.py` (Schemas), `app/runner.py` (Options + One-shot), `app/sessions.py`
(SessionManager), `app/streaming.py` (Message→SSE).
