# Pas d'Ollama ici (voir integration.docker.yaml) — embeddings via Jina/Gemini,
# vision via Groq, génération via le provider cloud configuré (llm.provider
# dans app/chat/plugin.yaml). Ollama reste le repli local pour le dev uniquement.
FROM python:3.14-slim

# build-essential : certaines dépendances compilent des extensions natives
# (cryptography, onnxruntime...). openssl : génération des clés JWT au
# premier démarrage (voir docker-entrypoint.sh). curl : healthcheck.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    openssl \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Couche dépendances séparée du code applicatif : un changement de code seul
# ne réinvalide pas `uv sync`, le rebuild reste rapide.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY . .
RUN uv sync --frozen --no-dev

RUN chmod +x docker-entrypoint.sh

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    XCORE_CONFIG_PATH=integration.docker.yaml

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["./docker-entrypoint.sh"]

# Service par défaut : l'API. Le worker Celery (RAG/rappels) est un service
# Dokploy SÉPARÉ pointant sur cette même image, avec ce CMD écrasé — voir le
# README déployé à côté de ce Dockerfile pour la commande exacte.
CMD ["/app/docker-start.sh"]