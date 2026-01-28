# EDUCATIONAL SECURITY TRAINING ENVIRONMENT
# Nginx Reverse Proxy Dockerfile

FROM nginx:1.25-alpine

LABEL maintainer="celox.io"
LABEL description="Secure Marketplace Training Environment - Reverse Proxy"
LABEL purpose="Educational security research and training"

# Install additional tools
RUN apk add --no-cache \
    certbot \
    certbot-nginx \
    openssl

# Remove default configuration
RUN rm /etc/nginx/conf.d/default.conf

# Security: Create nginx user if doesn't exist
RUN addgroup -g 101 -S nginx 2>/dev/null || true && \
    adduser -S -D -H -u 101 -h /var/cache/nginx -s /sbin/nologin -G nginx -g nginx nginx 2>/dev/null || true

# Create directories for logs and cache
RUN mkdir -p /var/log/nginx /var/cache/nginx && \
    chown -R nginx:nginx /var/log/nginx /var/cache/nginx

# Security hardening
RUN chmod -R 755 /etc/nginx && \
    chmod 644 /etc/nginx/nginx.conf 2>/dev/null || true

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD wget --quiet --tries=1 --spider http://localhost/health || exit 1

# Expose ports
EXPOSE 80 443

# Note: Running as root is standard for nginx in Docker
# Nginx handles privilege dropping for worker processes via nginx.conf
CMD ["nginx", "-g", "daemon off;"]
