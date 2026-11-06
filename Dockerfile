# Multi-Agent Autonomous Software Engineering System
# Production Container Image — Non-Root Hardened

FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PORT=8501 \
    HOME=/home/appuser

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create unprivileged system user and group (UID/GID 10001)
RUN groupadd --gid 10001 appgroup && \
    useradd --uid 10001 --gid appgroup --shell /bin/bash --create-home appuser

# Copy requirements and install python dependencies
COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy source code and configurations
COPY . .

# Ensure runtime directories exist with restricted permissions
RUN mkdir -p /app/sandbox_workspace/runs /app/sandbox_workspace/sample_repo /home/appuser/.streamlit && \
    chown -R appuser:appgroup /app/sandbox_workspace /home/appuser && \
    chmod -R 775 /app/sandbox_workspace /home/appuser

# Switch to dedicated unprivileged user for all subsequent execution
USER appuser

# Expose Streamlit default port
EXPOSE 8501

# Health check probe executing as appuser
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

# Launch Streamlit dashboard as appuser
ENTRYPOINT ["streamlit", "run", "dashboard/app.py", "--server.port=8501", "--server.address=0.0.0.0"]
