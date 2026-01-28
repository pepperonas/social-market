#!/bin/bash
# EDUCATIONAL SECURITY TRAINING ENVIRONMENT
# Entrypoint script to fix permissions and start application

set -e

# Fix log directory permissions (volume is mounted as root)
if [ -d "/var/log/marketplace" ]; then
    chown -R marketplace:marketplace /var/log/marketplace 2>/dev/null || true
fi

# Fix uploads directory permissions
if [ -d "/app/uploads" ]; then
    chown -R marketplace:marketplace /app/uploads 2>/dev/null || true
fi

# If running as root, switch to marketplace user for the actual command
if [ "$(id -u)" = "0" ]; then
    # Execute the command as marketplace user
    exec gosu marketplace "$@"
else
    # Already running as marketplace user
    exec "$@"
fi
