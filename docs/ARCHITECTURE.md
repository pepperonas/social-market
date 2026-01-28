# Social Market - Architecture Documentation

**EDUCATIONAL SECURITY TRAINING ENVIRONMENT**

## Overview

This document describes the architecture of the secure marketplace training environment. This is an educational platform designed to demonstrate security best practices in web application development.

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Internet (Tor Network)                   │
└────────────────────────┬────────────────────────────────────┘
                         │
                    ┌────▼────┐
                    │   Tor   │ (Hidden Service v3)
                    │ Service │ Port: 9050
                    └────┬────┘
                         │
                    ┌────▼────┐
                    │  Nginx  │ (Reverse Proxy + TLS 1.3)
                    │         │ Port: 80/443
                    │ • Rate Limiting
                    │ • Security Headers
                    │ • DDoS Protection
                    └────┬────┘
                         │
              ┌──────────┴──────────┐
              │                     │
         ┌────▼────┐           ┌────▼────┐
         │  Flask  │           │ Celery  │
         │   App   │───────────│ Workers │
         │         │           │         │
         │ • Auth  │           │ • Escrow│
         │ • API   │           │ • Tasks │
         │ • Routes│           └────┬────┘
         └────┬────┘                │
              │                     │
     ┌────────┴────────┬───────────┘
     │                 │
┌────▼────┐      ┌────▼────┐
│PostgreSQL│     │  Redis  │
│         │      │         │
│ • pgcrypto│    │ • Sessions│
│ • RLS    │     │ • Cache │
│ • Audit  │     │ • Queues│
└──────────┘     └─────────┘
```

## Components

### 1. Tor Hidden Service
- **Purpose**: Network-level anonymity
- **Technology**: Tor v3 onion service
- **Security**: Isolated Docker network

### 2. Nginx Reverse Proxy
- **Purpose**: TLS termination, rate limiting, load balancing
- **Security Features**:
  - TLS 1.3 only
  - Security headers (CSP, HSTS, X-Frame-Options)
  - Multi-tier rate limiting
  - DDoS protection

### 3. Flask Application
- **Purpose**: Business logic and API
- **Security Features**:
  - CSRF protection
  - Input validation
  - Session security
  - 2FA support
  - PGP encryption

### 4. PostgreSQL Database
- **Purpose**: Data persistence
- **Security Features**:
  - pgcrypto extension for encryption
  - Row-level security (RLS)
  - Audit logging
  - Least privilege access

### 5. Redis
- **Purpose**: Session storage, caching, job queues
- **Security**: Password-protected, isolated network

### 6. Celery Workers
- **Purpose**: Background task processing
- **Tasks**:
  - Escrow processing
  - Auto-finalization
  - Message cleanup
  - Monitoring tasks

### 7. Monitoring Service
- **Purpose**: Security monitoring and alerting
- **Features**:
  - File integrity monitoring
  - Service health checks
  - Security event detection
  - Disk usage monitoring

## Security Architecture

### Defense-in-Depth Layers

1. **Network Layer**
   - Tor hidden service
   - Docker network isolation
   - Firewall rules (via Docker)

2. **Transport Layer**
   - TLS 1.3 encryption
   - Perfect forward secrecy
   - Certificate pinning (optional)

3. **Application Layer**
   - CSRF protection
   - XSS prevention (CSP)
   - SQL injection prevention (ORM)
   - Rate limiting
   - Session security

4. **Data Layer**
   - Field-level encryption (pgcrypto)
   - PGP message encryption
   - Bcrypt password hashing
   - Audit logging

5. **Monitoring Layer**
   - File integrity monitoring
   - Security event logging
   - Failed login detection
   - Anomaly detection

## Data Flow

### User Authentication
```
1. User → Nginx (rate limit check)
2. Nginx → Flask (forward request)
3. Flask → PostgreSQL (verify credentials)
4. PostgreSQL → Flask (user data)
5. Flask → Redis (create session)
6. Flask → PostgreSQL (log auth event)
7. Flask → Nginx → User (session cookie)
```

### Product Purchase
```
1. Buyer places order
2. Flask creates Order (PENDING status)
3. Flask creates Escrow (mock wallet)
4. Buyer "funds" escrow
5. Escrow status → FUNDED
6. Order status → PAID
7. Vendor ships product
8. Order status → SHIPPED
9. Buyer confirms delivery
10. Order status → DELIVERED
11. Auto-finalize after N days
12. Order status → COMPLETED
13. Escrow releases funds to vendor
```

### PGP Message Encryption
```
1. Sender composes message
2. Flask retrieves recipient's public key
3. Message encrypted with recipient's PGP key
4. Encrypted message stored in database
5. Recipient retrieves encrypted message
6. Client-side decryption with private key
```

## Database Schema

### Core Tables
- `users` - User accounts with security features
- `products` - Product listings
- `orders` - Order management
- `escrows` - Escrow transactions (mock)
- `messages` - PGP-encrypted messages

### Security Tables
- `audit_log` - General audit trail
- `auth_log` - Authentication events
- `security_events` - Security alerts
- `rate_limit_log` - Rate limiting attempts
- `admin_actions` - Admin accountability

## API Endpoints

### Authentication
- `POST /auth/login` - User login
- `POST /auth/logout` - User logout
- `POST /auth/register` - User registration
- `POST /auth/verify-2fa` - 2FA verification

### Marketplace
- `GET /` - Homepage
- `GET /search` - Product search
- `GET /product/<id>` - Product details
- `GET /category/<id>` - Category browse

### Vendor
- `GET /vendor/dashboard` - Vendor dashboard
- `GET /vendor/products` - Product management
- `GET /vendor/orders` - Order management

### Buyer
- `GET /buyer/orders` - Order history
- `POST /buyer/order/<id>/confirm` - Confirm delivery

### Admin
- `GET /admin/dashboard` - Admin overview
- `GET /admin/users` - User management
- `GET /admin/security` - Security monitoring

### Messages
- `GET /messages` - Message inbox
- `GET /messages/thread/<id>` - Message thread
- `POST /messages/send` - Send message

## Deployment

### Docker Compose Services
- `postgres` - PostgreSQL database
- `redis` - Redis cache/sessions
- `app` - Flask application
- `celery` - Background workers
- `celery-beat` - Scheduled tasks
- `nginx` - Reverse proxy
- `tor` - Hidden service
- `monitor` - Security monitoring

### Volumes
- `postgres_data` - Database persistence
- `redis_data` - Redis persistence
- `tor_data` - Tor keys
- `uploads` - User uploads
- `backups` - Encrypted backups
- `logs` - Application logs

### Networks
- `frontend` - Public-facing (Nginx ↔ App)
- `backend` - Internal (App ↔ DB/Redis)
- `isolated` - Tor only (no external)

## Security Monitoring

### File Integrity Monitoring
- SHA256 hashing of critical files
- Baseline creation and comparison
- Automated change detection
- Alert on modifications

### Security Events
- Failed login tracking
- Rate limit violations
- Suspicious activity detection
- Admin action logging

### Health Checks
- Service availability
- Database connectivity
- Disk usage
- Tor connectivity

## Backup Strategy

### Backup Process
1. PostgreSQL dump
2. Critical files archive
3. GPG encryption (AES256)
4. Retention: 7 days
5. Automated cleanup

### Restore Process
1. Decrypt backup with GPG
2. Extract tarball
3. Restore database
4. Verify integrity

## Educational Value

This architecture demonstrates:
- ✅ Defense-in-depth security
- ✅ Zero-trust principles
- ✅ Encryption at rest and in transit
- ✅ Comprehensive audit logging
- ✅ Rate limiting and DDoS protection
- ✅ Secure session management
- ✅ File integrity monitoring
- ✅ Network isolation (Tor)
- ✅ Least privilege access
- ✅ Automated monitoring

## Limitations

**This is a training environment:**
- Mock cryptocurrency escrow (not real blockchain)
- Local deployment only
- Not production-ready
- For educational purposes only

## Next Steps

1. Complete templates for UI
2. Add comprehensive unit tests
3. Implement additional features
4. Create training scenarios
5. Develop CTF-style challenges

---

**© 2026 Social Market - Educational Use Only**
