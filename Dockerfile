# Claude Code Remote API — Container
# Node (fuer die Claude Code CLI) + Python (fuer den FastAPI-Wrapper).
FROM node:22-bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-venv python3-pip git ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# Claude Code CLI (wird vom Agent SDK genutzt)
RUN npm install -g @anthropic-ai/claude-code

# non-root user (noetig, falls permission_mode=bypassPermissions genutzt wird)
RUN useradd -m -u 1001 appuser

# Python-venv (umgeht PEP 668 auf Debian)
ENV VENV=/opt/venv
RUN python3 -m venv "$VENV"
ENV PATH="$VENV/bin:$PATH"

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

RUN mkdir -p /workspaces && chown -R appuser:appuser /workspaces /app
USER appuser

ENV WORKSPACES_DIR=/workspaces \
    HOST=0.0.0.0 \
    PORT=8000 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# Healthcheck ohne Auth
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
