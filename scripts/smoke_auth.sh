#!/usr/bin/env bash
# Smoke-Test: bestaetigt, dass Claude Code ueber das ABO (OAuth-Token) laeuft,
# nicht ueber einen API-Key.
#
# Voraussetzung: CLAUDE_CODE_OAUTH_TOKEN ist gesetzt (aus `claude setup-token`).
set -euo pipefail

if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
  echo "WARN: ANTHROPIC_API_KEY ist gesetzt -> haette Vorrang (Token-Abrechnung)."
  echo "      Fuer Abo-Betrieb bitte unsetzen:  unset ANTHROPIC_API_KEY"
fi

if [[ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]]; then
  echo "FEHLER: CLAUDE_CODE_OAUTH_TOKEN ist nicht gesetzt."
  echo "  1) Lokal einmalig:   claude setup-token"
  echo "  2) Token exportieren: export CLAUDE_CODE_OAUTH_TOKEN=<token>"
  exit 1
fi

# Python aus dem venv nutzen (dort ist claude-agent-sdk installiert), sonst system.
PY="python3"
for cand in "$(dirname "$0")/../.venv/bin/python" "./.venv/bin/python"; do
  if [[ -x "$cand" ]]; then PY="$cand"; break; fi
done
echo "(nutze Python: $PY)"

echo "== 1) CLI headless (nutzt den OAuth-Token direkt) =="
claude -p "Antworte nur mit: OK" --output-format json | "$PY" -c 'import sys,json; d=json.load(sys.stdin); print("result:", d.get("result")); print("session_id:", d.get("session_id"))'

echo
echo "== 2) Python Agent SDK (bestaetigt SDK nutzt denselben Token) =="
"$PY" - <<'PY'
import anyio
from claude_agent_sdk import query, ClaudeAgentOptions

async def main():
    async for msg in query(prompt="Antworte nur mit: OK", options=ClaudeAgentOptions(max_turns=1)):
        print(type(msg).__name__, getattr(msg, "result", ""))

anyio.run(main)
PY

echo
echo "OK: Wenn beide Schritte ohne API-Key funktioniert haben, laeuft alles ueber dein Abo."
