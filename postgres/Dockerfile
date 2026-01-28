# EDUCATIONAL SECURITY TRAINING ENVIRONMENT
# PostgreSQL with pgcrypto Dockerfile

FROM postgres:15-alpine

LABEL maintainer="celox.io"
LABEL description="Secure Marketplace Training Environment - Database"
LABEL purpose="Educational security research and training"

# Install additional extensions
RUN apk add --no-cache postgresql-contrib

# Security: Harden PostgreSQL configuration
RUN echo "# Security hardening" >> /var/lib/postgresql/data/postgresql.conf && \
    echo "ssl = on" >> /var/lib/postgresql/data/postgresql.conf && \
    echo "password_encryption = scram-sha-256" >> /var/lib/postgresql/data/postgresql.conf && \
    echo "log_connections = on" >> /var/lib/postgresql/data/postgresql.conf && \
    echo "log_disconnections = on" >> /var/lib/postgresql/data/postgresql.conf && \
    echo "log_duration = on" >> /var/lib/postgresql/data/postgresql.conf

# Health check
HEALTHCHECK --interval=10s --timeout=5s --retries=5 \
    CMD pg_isready -U ${POSTGRES_USER} || exit 1
