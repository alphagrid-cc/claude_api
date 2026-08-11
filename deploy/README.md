# Deployment (self-hosting)

Der Dienst bindet bewusst nur auf `127.0.0.1` — setze einen **eigenen Reverse-Proxy**
davor, der TLS terminiert (nginx, Caddy, Traefik …).

## Schritte (generisch)

1. **Image:** wird per CI gebaut und nach GHCR gepusht (`ghcr.io/alphagrid-cc/claude_api`) — oder du baust selbst mit `docker compose up --build` (siehe Root-`docker-compose.yml`).
2. **Config:** lege eine `.env` neben `deploy/compose.yml` (siehe `.env.example`):
   - `GATEWAY_TOKEN` — Bearer für die API
   - `CLAUDE_CODE_OAUTH_TOKEN` — aus `claude setup-token`
   - **kein** `ANTHROPIC_API_KEY` (sonst Abrechnung per Token statt Abo)
3. **Start:**
   ```bash
   docker compose -f deploy/compose.yml up -d
   ```
4. **Reverse-Proxy:** leite deine Domain auf `http://127.0.0.1:8091`. Für die
   SSE-/Streaming-Endpoints Buffering **aus** und lange Read-Timeouts setzen.
5. **Updates (pull-based):** ein Scheduler zieht periodisch das neue Image:
   ```bash
   docker compose -f deploy/compose.yml pull && docker compose -f deploy/compose.yml up -d
   ```

## Sicherheit
- Endpoint immer hinter **HTTPS + starkem `GATEWAY_TOKEN`**; zusätzlich ein Zugriffsschutz (IP-Allowlist / Access-Proxy) empfohlen, da der Agent Bash/Dateien ausführen kann.
- Container läuft non-root; `/workspaces` isoliert; Ressourcen-Caps in der Compose.
- Secrets nur als Runtime-Env (`.env`), niemals ins Image oder ins Repo.
