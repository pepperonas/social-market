# EDUCATIONAL SECURITY TRAINING ENVIRONMENT
# Tor Hidden Service Dockerfile

FROM alpine:3.19

LABEL maintainer="celox.io"
LABEL description="Secure Marketplace Training Environment - Tor Hidden Service"
LABEL purpose="Educational security research and training"

# Install Tor
RUN apk add --no-cache \
    tor \
    torsocks \
    curl

# Create directories (tor user already exists from package)
RUN mkdir -p /var/lib/tor/hidden_service && \
    chown -R tor:tor /var/lib/tor && \
    chmod 700 /var/lib/tor/hidden_service

# Security: Set proper permissions
RUN chmod 600 /etc/tor/torrc 2>/dev/null || true

# Health check
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -sx socks5h://localhost:9050 https://check.torproject.org/ || exit 1

# Expose SOCKS proxy port
EXPOSE 9050

# Expose control port (optional, for monitoring)
EXPOSE 9051

# Run as tor user
USER tor

# Start Tor
CMD ["tor", "-f", "/etc/tor/torrc"]
