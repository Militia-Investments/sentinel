FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY sentinel/ ./sentinel/

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash sentinel
USER sentinel

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import sentinel; print('ok')" || exit 1

# Run the worker
CMD ["python", "-m", "sentinel.worker.main"]
