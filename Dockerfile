FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# System deps (curl needed for the Claude CLI installer)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps first (cached layer — rebuilds only when requirements change),
# then Chromium + its system libraries in the same layer cleanup pass.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/* /root/.cache

# Non-root user; owns app data and the shared browser install
RUN useradd --create-home --uid 1000 harvey \
    && mkdir -p /app/data \
    && chown -R harvey:harvey /app /ms-playwright

# Copy project (config/prompts are typically bind-mounted over these at runtime)
COPY --chown=harvey:harvey harvey/ harvey/
COPY --chown=harvey:harvey prompts/ prompts/
COPY --chown=harvey:harvey skills/ skills/
COPY --chown=harvey:harvey workspaces/ workspaces/
COPY --chown=harvey:harvey data/ data/
COPY --chown=harvey:harvey harvey.yaml .

USER harvey
ENV PATH="/home/harvey/.local/bin:${PATH}"

# Claude Code CLI, installed as the runtime user so ~/.local/bin is correct.
# `|| true` keeps the build working offline; the CLI is required at runtime.
RUN curl -fsSL https://claude.ai/install.sh | sh || true

# Expose Jarvis Web Dashboard port
EXPOSE 5555

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5555/api/harvey/status')" || exit 1

CMD ["python", "-m", "harvey.cli", "dashboard", "--host", "0.0.0.0", "--port", "5555"]

