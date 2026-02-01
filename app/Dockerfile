# EDUCATIONAL SECURITY TRAINING ENVIRONMENT
# Flask Application Dockerfile

FROM python:3.11-slim-bookworm

LABEL maintainer="celox.io"
LABEL description="Secure Marketplace Training Environment - Application"
LABEL purpose="Educational security research and training"

# Security: Run as non-root user
RUN groupadd -r marketplace && useradd -r -g marketplace marketplace

# Install system dependencies including gosu for entrypoint
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    libpq-dev \
    gnupg \
    curl \
    gosu \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# Set working directory to root
WORKDIR /

# Copy requirements and install Python dependencies
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /tmp/requirements.txt && \
    rm /tmp/requirements.txt

# Copy application code to /app directory
COPY . /app

# Copy entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Create necessary directories
RUN mkdir -p /app/uploads /var/log/marketplace && \
    chown -R marketplace:marketplace /app /var/log/marketplace

# Note: We start as root to fix volume permissions, then switch to marketplace user in entrypoint
# USER marketplace is set in entrypoint.sh

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV FLASK_APP=app
ENV FLASK_ENV=production

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1

# Expose port (internal only, proxied by nginx)
EXPOSE 5000

# Entrypoint to fix permissions
ENTRYPOINT ["/entrypoint.sh"]

# Default command (overridden in docker-compose for celery)
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "4", "app:create_app()"]
