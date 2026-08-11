"""Minimaler Python-Client fuer die Claude Code Remote API.

Nutzung:
    export GATEWAY_TOKEN=...            # dein API-Bearer
    export BASE_URL=http://localhost:8000
    python examples/client.py oneshot "Antworte nur mit: OK"
    python examples/client.py session "Lege hello.txt mit Inhalt hallo an."
"""

from __future__ import annotations

import json
import os
import sys

import httpx

BASE = os.environ.get("BASE_URL", "http://localhost:8000")
TOKEN = os.environ["GATEWAY_TOKEN"]
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def _print_sse(response: httpx.Response) -> None:
    event = None
    for line in response.iter_lines():
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data = json.loads(line[5:].strip())
            if event == "assistant":
                for block in data.get("content", []):
                    if block.get("type") == "text":
                        print(block["text"], end="", flush=True)
                    elif block.get("type") == "tool_use":
                        print(f"\n[tool_use {block['name']}] {json.dumps(block['input'])[:200]}")
            elif event == "result":
                print(f"\n[result] turns={data.get('num_turns')} cost=${data.get('total_cost_usd')}")


def oneshot(prompt: str) -> None:
    with httpx.Client(timeout=None) as c:
        with c.stream("POST", f"{BASE}/v1/oneshot",
                      headers=HEADERS, json={"prompt": prompt, "stream": True}) as r:
            r.raise_for_status()
            _print_sse(r)


def session(prompt: str) -> None:
    with httpx.Client(timeout=None) as c:
        sid = c.post(f"{BASE}/v1/sessions", headers=HEADERS,
                     json={"permission_mode": "acceptEdits"}).json()["session_id"]
        print(f"session: {sid}")
        with c.stream("POST", f"{BASE}/v1/sessions/{sid}/messages",
                      headers=HEADERS, json={"prompt": prompt}) as r:
            r.raise_for_status()
            _print_sse(r)


if __name__ == "__main__":
    mode, text = sys.argv[1], sys.argv[2]
    {"oneshot": oneshot, "session": session}[mode](text)
