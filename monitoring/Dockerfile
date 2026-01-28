# EDUCATIONAL SECURITY TRAINING ENVIRONMENT
# Monitoring Service Dockerfile

FROM python:3.11-slim-bookworm

LABEL maintainer="celox.io"
LABEL description="Secure Marketplace Training Environment - Monitoring"
LABEL purpose="Educational security research and training"

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy monitoring scripts
COPY . .

# Security: Create monitoring user
RUN useradd -r -s /bin/false monitoring && \
    chown -R monitoring:monitoring /app

USER monitoring

CMD ["python", "/app/monitoring/security_monitor.py"]
