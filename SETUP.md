# Quick Setup Guide

**EDUCATIONAL SECURITY TRAINING ENVIRONMENT**

This is a step-by-step guide to get the secure marketplace training environment running.

## Prerequisites

- Docker 20.10+
- Docker Compose 2.0+
- At least 4GB RAM
- 10GB disk space
- Python 3.11+ (for local development)

## Quick Start

### 1. Clone and Configure

```bash
cd secure-marketplace

# Copy environment template
cp .env.example .env

# Generate secure secrets
python3 -c "import secrets; print('SECRET_KEY=' + secrets.token_hex(32))" >> .env
python3 -c "import secrets; print('DB_ENCRYPTION_KEY=' + secrets.token_hex(32))" >> .env
```

### 2. Edit .env File

Open `.env` and configure:
- Change all `CHANGE_ME` values
- Set secure passwords for PostgreSQL, Redis
- Configure backup encryption passphrase

### 3. Build and Start Services

```bash
# Build containers
docker-compose build

# Start all services
docker-compose up -d

# Check status
docker-compose ps
```

### 4. Initialize Database

```bash
# Wait for PostgreSQL to be ready (10-15 seconds)
sleep 15

# Create database tables
docker-compose exec app flask db upgrade

# Create initial admin user (optional)
docker-compose exec app flask init-admin
```

### 5. Verify Installation

```bash
# Check application health
curl http://localhost:8080/health

# View logs
docker-compose logs -f app

# Check Tor hidden service address
docker-compose exec tor cat /var/lib/tor/hidden_service/hostname
```

## Accessing the Application

### HTTP Access
- URL: http://localhost:8080
- Admin: http://localhost:8080/admin (login required)

### Tor Access
```bash
# Get .onion address
ONION=$(docker-compose exec tor cat /var/lib/tor/hidden_service/hostname)
echo "Tor address: $ONION"

# Access via Tor Browser or SOCKS proxy
curl --socks5-hostname localhost:9050 http://$ONION
```

## Default Credentials

**Admin Account:**
- Username: `admin`
- Password: `ChangeMe123!`

⚠️ **CHANGE IMMEDIATELY AFTER FIRST LOGIN**

## Common Tasks

### View Logs
```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f app
docker-compose logs -f nginx
docker-compose logs -f postgres
```

### Restart Services
```bash
# Restart all
docker-compose restart

# Restart specific service
docker-compose restart app
```

### Stop Services
```bash
docker-compose down
```

### Database Access
```bash
# PostgreSQL shell
docker-compose exec postgres psql -U marketplace

# View audit logs
docker-compose exec postgres psql -U marketplace -c "SELECT * FROM auth_log LIMIT 10;"
```

### Redis CLI
```bash
docker-compose exec redis redis-cli
AUTH <your_redis_password>
KEYS marketplace:*
```

### Create Backup
```bash
docker-compose exec app /app/scripts/backup.sh
```

### Restore Backup
```bash
docker-compose exec app /app/scripts/restore.sh /backups/backup_YYYYMMDD_HHMMSS.tar.gz.gpg
```

### File Integrity Monitoring
```bash
# Create baseline
docker-compose exec monitor python /app/monitoring/file_integrity_monitor.py --baseline

# Check integrity
docker-compose exec monitor python /app/monitoring/file_integrity_monitor.py --check
```

### Security Monitoring
```bash
# Run security check
docker-compose exec monitor python /app/monitoring/security_monitor.py --once

# View security alerts
docker-compose exec app cat /var/log/marketplace/security_alerts.log
```

## Development Mode

### Run Flask App Locally
```bash
cd app

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set environment
export FLASK_APP=app
export FLASK_ENV=development
export DATABASE_URL=postgresql://marketplace:password@localhost:5432/marketplace

# Run development server
flask run
```

### Database Migrations
```bash
# Create migration
docker-compose exec app flask db migrate -m "Description"

# Apply migration
docker-compose exec app flask db upgrade

# Rollback
docker-compose exec app flask db downgrade
```

## Troubleshooting

### Services Won't Start
```bash
# Check Docker status
docker ps

# Check logs for errors
docker-compose logs

# Verify ports not in use
sudo lsof -i :8080,5432,6379,9050
```

### Database Connection Errors
```bash
# Check PostgreSQL is ready
docker-compose exec postgres pg_isready

# Check credentials in .env
cat .env | grep POSTGRES

# Reset database (⚠️ destroys data)
docker-compose down -v
docker-compose up -d postgres
sleep 10
docker-compose exec app flask db upgrade
```

### Tor Not Working
```bash
# Check Tor logs
docker-compose logs tor

# Verify hostname file
docker-compose exec tor cat /var/lib/tor/hidden_service/hostname

# Restart Tor
docker-compose restart tor
```

### High CPU/Memory Usage
```bash
# Check resource usage
docker stats

# Adjust resource limits in docker-compose.yml
# Restart services after changes
```

## Security Checklist

Before using the environment:

- [ ] Change default admin password
- [ ] Generate new SECRET_KEY and DB_ENCRYPTION_KEY
- [ ] Set secure passwords for PostgreSQL and Redis
- [ ] Configure backup encryption passphrase
- [ ] Review and customize rate limits
- [ ] Enable file integrity monitoring
- [ ] Test backup and restore process
- [ ] Review audit log retention policy
- [ ] Verify all services start correctly
- [ ] Run security header checks

## Testing

### Security Headers
```bash
curl -I http://localhost:8080 | grep -E "X-Frame|CSP|HSTS"
```

### Rate Limiting
```bash
# Should see 429 responses
for i in {1..20}; do
  curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8080/
done
```

### Database Encryption
```bash
docker-compose exec postgres psql -U marketplace -d marketplace -c \
  "SELECT pgp_sym_encrypt('test', current_setting('app.encryption_key'));"
```

## Stopping and Cleanup

### Stop Services
```bash
docker-compose down
```

### Remove All Data (⚠️ IRREVERSIBLE)
```bash
docker-compose down -v
```

### Remove Images
```bash
docker-compose down --rmi all
```

## Getting Help

- Check logs: `docker-compose logs`
- Review documentation: `docs/`
- Check security settings: `docs/SECURITY.md`
- Verify architecture: `docs/ARCHITECTURE.md`

## Next Steps

1. Explore the application
2. Review security features
3. Test authentication and 2FA
4. Try the escrow system
5. Send encrypted messages
6. Monitor security events
7. Create backups
8. Study the codebase

---

**Remember:** This is an educational training environment. Always use for authorized security training only.

**© 2026 Social Market - Educational Use Only**
