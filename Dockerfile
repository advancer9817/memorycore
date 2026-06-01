FROM python:3.11-slim

WORKDIR /app

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONUNBUFFERED=1

# Install from the checked-in source so package metadata and optional extras
# stay in sync with pyproject.toml.
COPY pyproject.toml README.md ./
COPY local_memory_mcp/ ./local_memory_mcp/

ARG INSTALL_EXTRAS=all
RUN if [ "$INSTALL_EXTRAS" = "none" ]; then \
      pip install -e .; \
    else \
      pip install -e ".[${INSTALL_EXTRAS}]"; \
    fi

# Data directory — mount a volume here to persist memory.sqlite3
RUN mkdir -p /data
ENV LOCAL_MEMORY_DB=/data/memory.sqlite3 \
    LOCAL_MEMORY_CONFIG=/data/config.yaml \
    QDRANT_URL=http://qdrant:6333 \
    QDRANT_COLLECTION=agent_memory \
    LOCAL_MEMORY_EMBEDDING_PROVIDER=hashing \
    LOCAL_MEMORY_FRONTEND_TOKEN=change-me

EXPOSE 8318

CMD ["python", "-m", "local_memory_mcp", "serve", "--host", "0.0.0.0", "--port", "8318"]
