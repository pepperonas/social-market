# EDUCATIONAL SECURITY TRAINING ENVIRONMENT

⚠️ **IMPORTANT LEGAL NOTICE** ⚠️

This is a **LOCAL, ISOLATED** training environment for IT security education, architecture study, and defensive security research.

## Purpose

- ✅ Understanding secure system architecture and hardening
- ✅ Learning defense-in-depth security principles
- ✅ Studying encryption, authentication, and access control
- ✅ Training for security professionals and law enforcement
- ✅ Educational demonstration of security best practices

## NOT FOR

- ❌ Production use or public deployment
- ❌ Illegal activities of any kind
- ❌ Processing real transactions or sensitive data
- ❌ Internet-facing deployment without proper authorization

## Legal Context

**Social Market**
- Authorized security education material
- For defensive security purposes only
- Complies with security research best practices

---

## Overview

This project implements a fully-featured, security-hardened marketplace platform that demonstrates:

- **Defense-in-Depth Architecture** - Multiple layers of security controls
- **Zero-Trust Security Model** - Verify everything, trust nothing
- **Argon2id Password Hashing** - Memory-hard, GPU-resistant with pepper
- **RSA-4096 PGP Key Generation** - Web-based keypair generation
- **Encryption at Rest & in Transit** - pgcrypto, TLS 1.3, PGP messaging
- **Secure Session Management** - Redis-backed, HTTPOnly cookies
- **Rate Limiting & DDoS Protection** - Multi-tier rate limiting
- **Input Validation & Injection Prevention** - Parameterized queries, sanitization
- **Audit Logging & Monitoring** - Complete audit trail
- **Network Isolation** - Tor hidden service support
- **File Integrity Monitoring** - AIDE-style hash verification
- **Secure Backup Strategies** - GPG-encrypted backups

## Technology Stack

### Backend
- Python 3.11 + Flask (lightweight, security-focused)
- PostgreSQL 15 with pgcrypto extension
- Redis for session management
- Celery for async task processing

### Security & Crypto
- **Argon2id** for password hashing (Winner of Password Hashing Competition)
  - Memory-hard: 64 MB per hash (GPU/ASIC resistant)
  - Time-cost: 3 iterations (~0.2-0.5s per hash)
  - Pepper: Secret server-side salt for additional security
- **RSA-4096 PGP** key generation (OpenPGP standard)
- **pgcrypto** for database field encryption
- **python-gnupg** for PGP messaging
- **cryptography** library for Python crypto operations

### Infrastructure
- Docker Compose for all services
- Nginx reverse proxy with TLS 1.3
- Tor hidden service (v3 onions)
- Fail2Ban for rate limiting

## Quick Start

### Prerequisites

- Docker & Docker Compose
- At least 4GB RAM
- 10GB disk space

### Setup

1. **Clone and configure environment:**
   ```bash
   cd secure-marketplace
   cp .env.example .env
   # Edit .env with secure random values
   ```

2. **Generate secure secrets:**
   ```bash
   python3 -c "import secrets; print(secrets.token_hex(32))"  # For SECRET_KEY
   python3 -c "import secrets; print(secrets.token_hex(32))"  # For DB_ENCRYPTION_KEY
   python3 -c "import secrets; print(secrets.token_hex(32))"  # For PASSWORD_PEPPER
   ```

   Update `.env` with generated values

3. **Build and start services:**
   ```bash
   docker-compose up -d
   ```

4. **Initialize database:**
   ```bash
   docker-compose exec app flask db upgrade
   docker-compose exec app flask init-db
   ```

5. **Access the application:**
   - HTTP: http://localhost:8080
   - Tor: Check logs for .onion address
     ```bash
     docker-compose logs tor | grep "hostname"
     ```

### Default Admin Account

**Username:** `admin`
**Password:** `ChangeMe123!` (⚠️ Change immediately!)

Access admin panel at: http://localhost:8080/admin

## Architecture

```
Internet (Tor)
     ↓
  Tor Hidden Service (isolated network)
     ↓
  Nginx (TLS 1.3, Security Headers, Rate Limiting)
     ↓
  Flask App (Gunicorn workers)
     ↓
  ├─→ PostgreSQL (pgcrypto, RLS, audit logs)
  ├─→ Redis (sessions, cache, rate limit counters)
  └─→ Celery (escrow processing, monitoring tasks)
```

## Security Features

### Application Security
- **Argon2id Password Hashing:**
  - Memory-hard algorithm (64 MB per hash)
  - GPU/ASIC attack resistance
  - Pepper + salt protection
  - Automatic migration from legacy hashes
  - OWASP & NIST compliant
- **PGP Key Generation:**
  - RSA-4096 keypair generation
  - Web-based key creation
  - OpenPGP standard compatible
  - Strong passphrase validation
  - No server-side key storage
- **Security Headers:** CSP, HSTS, X-Frame-Options, etc.
- **Rate Limiting:** Multi-tier (general, login, registration, PGP: 3/hour)
- **CSRF Protection:** Token-based for all state-changing operations
- **Input Validation:** SQLAlchemy ORM, Werkzeug sanitization
- **Session Security:** HTTPOnly, Secure, SameSite cookies

### Database Security
- **Least Privilege:** App user has minimal permissions
- **Row-Level Security:** Users can only access their own data
- **Field Encryption:** Sensitive data encrypted with pgcrypto
- **Audit Logging:** All DB changes logged with timestamps

### Network Security
- **TLS 1.3 Only:** Modern cipher suites
- **Tor Hidden Service:** Network anonymity layer
- **Rate Limiting:** Nginx + Redis-backed counters
- **DDoS Protection:** Connection limits, request throttling

### Monitoring & Detection
- **File Integrity Monitoring:** SHA256 hash verification
- **Security Monitoring:** Service health, failed logins, disk usage
- **Audit Logs:** Complete trail of all actions
- **Alerting:** Automated alerts for security events

## Core Features

### User Management
- **Multi-role system:** Vendor/Buyer/Admin with distinct permissions
- **Argon2id password hashing:**
  - Memory-hard algorithm (64 MB per hash)
  - Pepper + salt protection
  - GPU/ASIC attack resistance
  - Automatic migration from legacy hashes
- **RSA-4096 PGP key generation:**
  - Web-based keypair creation
  - 2048/3072/4096-bit options
  - Strong passphrase validation
  - No server-side storage
  - OpenPGP standard compatible
- **2FA via TOTP:** Time-based one-time passwords
- **Account security:**
  - Failed login attempt tracking
  - Account lockout (5 attempts, 15 min)
  - Session management with Redis

### Marketplace
- Product listings (legal categories only: Books, Art, Digital Goods, Services)
- Search functionality with SQL injection protection
- Rating/review system
- Vendor analytics dashboard

### Escrow System
- Multi-signature wallet simulation (educational mock)
- Order states: pending → paid → shipped → completed → released
- Dispute handling
- Auto-release mechanism
- Commission calculation (3%)

### Messaging System
- **Mandatory PGP encryption:** All messages MUST be encrypted (no plaintext allowed)
- **Two encryption modes:**
  - Auto-encrypt: System encrypts with recipient's public key
  - Manual: User provides pre-encrypted PGP message
- **Flexible communication:**
  - Admin ↔ All users (support/moderation)
  - Vendor ↔ Buyers (customer service)
  - Users ↔ Admin (support requests)
- **Zero-knowledge architecture:** Messages stored encrypted, server cannot decrypt
- **Message threading:** Organized conversations per participant pair
- **Auto-deletion:** Messages expire after 30 days (OPSEC)
- **Soft delete:** Per-user deletion, permanent only when both delete
- **Rate limiting:** 10 new threads/hour, 20 replies/hour
- **AJAX decryption:** User provides private key to decrypt in browser
- See `docs/MESSAGING.md` for complete documentation

### Admin Dashboard
- User management
- Transaction monitoring
- Security alerts dashboard
- System health checks
- Audit log viewer

## Backup & Recovery

Automated encrypted backups:

```bash
# Run backup manually
docker-compose exec app python /app/scripts/backup.sh

# Restore from backup
docker-compose exec app python /app/scripts/restore.sh backup_20250127_120000.tar.gz.gpg
```

Backups are:
- Encrypted with GPG (AES256)
- Stored in `/backups` volume
- Retained for 7 days
- Include database dump + critical files

## Monitoring

### File Integrity Monitoring

```bash
# Create baseline
docker-compose exec app python /app/monitoring/file_integrity_monitor.py --baseline

# Check for changes
docker-compose exec app python /app/monitoring/file_integrity_monitor.py --check
```

### Security Monitoring

```bash
# View security status
docker-compose exec app python /app/monitoring/security_monitor.py --status

# View recent alerts
docker-compose exec app python /app/monitoring/security_monitor.py --alerts
```

### Logs

```bash
# Application logs
docker-compose logs -f app

# Nginx access/error logs
docker-compose logs -f nginx

# PostgreSQL logs
docker-compose logs -f postgres

# Tor logs
docker-compose logs -f tor
```

## Testing

### Security Headers
```bash
curl -I http://localhost:8080 | grep -E "X-Frame|CSP|HSTS"
```

### Rate Limiting
```bash
# Should see 429 responses after limit exceeded
for i in {1..20}; do curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8080/; done
```

### Database Encryption
```bash
docker-compose exec postgres psql -U marketplace -d marketplace -c \
  "SELECT pgp_sym_encrypt('test message', current_setting('app.encryption_key'));"
```

### Tor Connectivity
```bash
# Get .onion address
ONION=$(docker-compose exec tor cat /var/lib/tor/hidden_service/hostname)

# Test via Tor
curl --socks5-hostname localhost:9050 http://$ONION
```

## Development

### Run tests
```bash
docker-compose exec app pytest
```

### Access PostgreSQL
```bash
docker-compose exec postgres psql -U marketplace
```

### Access Redis CLI
```bash
docker-compose exec redis redis-cli
```

### Rebuild after code changes
```bash
docker-compose down
docker-compose up -d --build
```

## Training Scenarios

See `docs/TRAINING-GUIDE.md` for:
- Security audit exercises
- Penetration testing scenarios (authorized only)
- Incident response drills
- Code review challenges
- Configuration hardening tasks

## Documentation

### Core Documentation
- `docs/ARCHITECTURE.md` - Detailed system architecture
- `docs/SECURITY.md` - Security controls and threat model
- `SETUP.md` - Comprehensive setup guide

### Security Features
- **`docs/PASSWORD_SECURITY.md`** - Argon2id password hashing with pepper
  - Algorithm explanation
  - Security comparison vs other algorithms
  - Best practices for pepper management
  - Migration strategy
  - Threat model and attack defenses
  - Performance considerations
  - Compliance (OWASP, NIST, PCI-DSS, GDPR)

- **`docs/PGP_KEYS.md`** - RSA-4096 PGP key generation
  - Web-based key generation guide
  - Security features and best practices
  - Import instructions for various clients
  - Use cases (email, files, signatures)
  - Troubleshooting

- **`docs/MESSAGING.md`** - Encrypted messaging system
  - Mandatory PGP encryption architecture
  - Auto-encrypt vs manual modes
  - Communication matrix (who can message whom)
  - Zero-knowledge design
  - Database schema and API endpoints
  - Security best practices and troubleshooting

### User Guides
- `LOGIN_CREDENTIALS.md` - Default accounts and access information

## Troubleshooting

### Services won't start
```bash
# Check logs
docker-compose logs

# Verify ports not in use
sudo lsof -i :8080,5432,6379,9050
```

### Database connection errors
```bash
# Verify PostgreSQL is ready
docker-compose exec postgres pg_isready

# Check credentials in .env
```

### Tor hidden service not working
```bash
# Check Tor logs
docker-compose logs tor

# Verify hostname file exists
docker-compose exec tor cat /var/lib/tor/hidden_service/hostname
```

## Security Hardening Checklist

Before deployment (even locally):

- [ ] Change default admin password
- [ ] Generate new SECRET_KEY and DB_ENCRYPTION_KEY
- [ ] Review and customize rate limits
- [ ] Configure backup encryption passphrase
- [ ] Enable file integrity monitoring
- [ ] Review audit log retention policy
- [ ] Test emergency shutdown procedure
- [ ] Verify all services start correctly
- [ ] Run security header checks
- [ ] Test rate limiting effectiveness

## Emergency Procedures

### Shutdown all services
```bash
docker-compose down
```

### Emergency data wipe (IRREVERSIBLE)
```bash
docker-compose down -v  # Removes all volumes/data
```

### Dead Man's Switch
The system includes an optional dead man's switch that will:
1. Stop all services
2. Drop all databases
3. Delete encryption keys
4. Send encrypted alert

Configure in `scripts/dead-mans-switch.py`

## Contributing

This is an educational project. Contributions should:
- Maintain educational focus
- Enhance security features
- Include documentation
- Follow defensive security principles

## License

This project is for educational purposes only. See LICENSE file for details.

## Contact

For questions about this training environment:
- Email: security-training@cloudcommand.example
- Purpose: IT security education and training inquiries only

---

**Remember:** This is a training environment. All security features should be understood, tested, and adapted for any real-world use case. Never deploy training environments to production.

**© 2026 Social Market - Educational Use Only**
