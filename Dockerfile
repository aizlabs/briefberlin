FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        git \
        build-essential \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Copy dependency files and README (required by pyproject.toml)
COPY pyproject.toml uv.lock README.md ./

# Install Python dependencies using uv
# This includes the SpaCy model from the direct dependency
RUN uv sync --frozen

# Copy application code
COPY scripts/ ./scripts/
COPY config/ ./config/

# Run as non-root user
# Note: Create user before creating directories so they get correct ownership
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app

USER appuser

# Create output directories as appuser
# These will be overridden by volume mounts in docker-compose, but ensure
# the container can write to these locations in standalone mode
RUN mkdir -p /app/output/_posts /app/output/logs /app/output/metrics /app/logs

# Default command runs test discovery
# Use uv run to ensure virtual environment is activated
CMD ["uv", "run", "python", "scripts/test_discovery.py"]
