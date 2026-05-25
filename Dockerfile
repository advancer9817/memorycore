FROM python:3.11-slim

WORKDIR /app

# Install core deps first for layer caching
COPY pyproject.toml requirements.txt ./
RUN pip install --no-cache-dir mcp==1.27.1

# Optional: vector support
ARG INSTALL_VECTOR=false
RUN if [ "$INSTALL_VECTOR" = "true" ]; then \
      pip install --no-cache-dir "qdrant-client>=1.18.0,<2.0"; \
    fi

COPY local_memory_mcp/ ./local_memory_mcp/

# Data directory — mount a volume here to persist memory.sqlite3
RUN mkdir -p /data
ENV LOCAL_MEMORY_DB=/data/memory.sqlite3

EXPOSE 8318

CMD ["python", "-m", "local_memory_mcp", "serve", "--host", "0.0.0.0", "--port", "8318"]
