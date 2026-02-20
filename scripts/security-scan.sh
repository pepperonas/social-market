#!/bin/bash
# EDUCATIONAL SECURITY TRAINING ENVIRONMENT
# Security scanning script
# Purpose: Automated dependency vulnerability scanning

set -euo pipefail

echo "=========================================="
echo "Security Scan - Social Market"
echo "=========================================="
echo ""

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$(dirname "$SCRIPT_DIR")/app"

# 1. Dependency vulnerability scan with pip-audit
echo "[1/3] Running pip-audit (dependency vulnerabilities)..."
echo "---"
if command -v pip-audit &> /dev/null; then
    pip-audit -r "$APP_DIR/requirements.txt" --desc || true
else
    echo "SKIP: pip-audit not installed. Install with: pip install pip-audit"
fi
echo ""

# 2. Static security analysis with bandit (if available)
echo "[2/3] Running bandit (Python security linter)..."
echo "---"
if command -v bandit &> /dev/null; then
    bandit -r "$APP_DIR" -ll --skip B101 -f screen || true
else
    echo "SKIP: bandit not installed. Install with: pip install bandit"
fi
echo ""

# 3. Check for known insecure configurations
echo "[3/3] Checking configuration security..."
echo "---"

# Check for debug mode
if grep -q "DEBUG.*=.*True" "$APP_DIR/config.py" 2>/dev/null; then
    echo "WARNING: DEBUG mode may be enabled in config.py"
fi

# Check for default secrets
ENV_FILE="$(dirname "$APP_DIR")/.env"
if [ -f "$ENV_FILE" ]; then
    if grep -q "change-me\|dev-key\|dev-pepper\|ChangeMe" "$ENV_FILE" 2>/dev/null; then
        echo "WARNING: Default/insecure values detected in .env file"
    fi
fi

echo ""
echo "=========================================="
echo "Security scan complete"
echo "=========================================="
