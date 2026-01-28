# Security Documentation

**EDUCATIONAL SECURITY TRAINING ENVIRONMENT**

This document describes the security controls and threat model of the secure marketplace training environment.

## Security Controls

### 1. Network Security

#### Tor Hidden Service
- **Control**: Network anonymity through Tor
- **Implementation**: v3 onion service
- **Benefit**: IP address anonymity, resistance to traffic analysis

#### Network Isolation
- **Control**: Docker network segregation
- **Implementation**: Separate networks (frontend, backend, isolated)
- **Benefit**: Limited lateral movement in case of compromise

#### TLS Encryption
- **Control**: Transport layer encryption
- **Implementation**: TLS 1.3 only, modern cipher suites
- **Benefit**: Confidentiality and integrity of data in transit

### 2. Application Security

#### Authentication
- **Control**: Multi-factor authentication
- **Implementation**:
  - Bcrypt password hashing (12 rounds)
  - TOTP 2FA support
  - Account lockout after 5 failed attempts
- **Benefit**: Strong authentication, resistance to brute force

#### Session Management
- **Control**: Secure session handling
- **Implementation**:
  - Redis-backed sessions
  - HTTPOnly, Secure, SameSite cookies
  - Session timeout after 1 hour
  - Session invalidation on logout
- **Benefit**: Resistance to session hijacking

#### Input Validation
- **Control**: Comprehensive input sanitization
- **Implementation**:
  - SQLAlchemy ORM (parameterized queries)
  - Werkzeug input sanitization
  - Bleach HTML sanitization
  - File upload validation
- **Benefit**: Prevention of injection attacks

#### CSRF Protection
- **Control**: Cross-Site Request Forgery prevention
- **Implementation**:
  - Token-based CSRF (Flask-WTF)
  - SameSite cookie attribute
  - Double-submit cookie pattern
- **Benefit**: Prevention of CSRF attacks

#### XSS Prevention
- **Control**: Cross-Site Scripting mitigation
- **Implementation**:
  - Strict Content Security Policy
  - Template auto-escaping (Jinja2)
  - No JavaScript execution (Tor compatibility)
- **Benefit**: Prevention of XSS attacks

#### Rate Limiting
- **Control**: Request throttling
- **Implementation**:
  - General: 10 req/sec
  - Login: 1 req/min
  - Registration: 1 req/hour
  - Redis-backed counters
- **Benefit**: DDoS protection, brute force prevention

### 3. Data Security

#### Database Encryption
- **Control**: Field-level encryption
- **Implementation**:
  - pgcrypto extension
  - AES-256 encryption
  - Encrypted fields: messages, addresses
- **Benefit**: Data confidentiality at rest

#### Password Security
- **Control**: Strong password hashing
- **Implementation**:
  - Bcrypt algorithm
  - Cost factor: 12
  - Password policy enforcement
- **Benefit**: Resistance to password cracking

#### PGP Encryption
- **Control**: End-to-end encrypted messaging
- **Implementation**:
  - GPG/PGP public key encryption
  - Message encryption with recipient's key
  - Client-side decryption
- **Benefit**: Message confidentiality

#### Data Minimization
- **Control**: Limited data collection
- **Implementation**:
  - Optional profile fields
  - Message auto-deletion (30 days)
  - Secure deletion functions
- **Benefit**: Reduced attack surface

### 4. Access Control

#### Role-Based Access Control
- **Control**: RBAC for authorization
- **Implementation**:
  - Roles: buyer, vendor, admin
  - Route decorators for access control
  - Database row-level security
- **Benefit**: Principle of least privilege

#### Database Access Control
- **Control**: Limited database permissions
- **Implementation**:
  - Separate app user (no DELETE, DROP)
  - Read-only audit user
  - Connection pooling
- **Benefit**: Limited damage from SQL injection

### 5. Monitoring & Detection

#### Audit Logging
- **Control**: Comprehensive audit trail
- **Implementation**:
  - All DB changes logged
  - Authentication events logged
  - Admin actions logged
  - Timestamp and user tracking
- **Benefit**: Forensics and accountability

#### Security Event Logging
- **Control**: Security-specific event tracking
- **Implementation**:
  - Failed login attempts
  - Rate limit violations
  - Suspicious activities
  - Severity classification
- **Benefit**: Threat detection

#### File Integrity Monitoring
- **Control**: Detect file modifications
- **Implementation**:
  - SHA256 baseline hashing
  - Periodic integrity checks
  - Automated alerting
- **Benefit**: Malware/tampering detection

#### Health Monitoring
- **Control**: Service availability monitoring
- **Implementation**:
  - Service health checks
  - Disk usage monitoring
  - Failed login tracking
  - Automated alerting
- **Benefit**: Availability assurance

### 6. Infrastructure Security

#### Docker Security
- **Control**: Container isolation
- **Implementation**:
  - Non-root containers
  - Read-only file systems (where possible)
  - Resource limits
  - Security-opt flags
- **Benefit**: Containment of breaches

#### Secrets Management
- **Control**: Secure secret storage
- **Implementation**:
  - Environment variables
  - Docker secrets (optional)
  - No hardcoded secrets
- **Benefit**: Secrets protection

#### Backup Security
- **Control**: Encrypted backups
- **Implementation**:
  - GPG encryption (AES256)
  - Automated retention (7 days)
  - Secure deletion of temps
- **Benefit**: Data recovery with confidentiality

## Threat Model

### Assets
1. User credentials
2. Personal information (PII)
3. Messages (encrypted)
4. Transaction data
5. Application availability

### Threats

#### T1: Brute Force Attacks
- **Attack**: Automated password guessing
- **Mitigation**:
  - Rate limiting (1 req/min for login)
  - Account lockout after 5 attempts
  - CAPTCHA (optional)
- **Risk**: LOW

#### T2: SQL Injection
- **Attack**: Malicious SQL in user input
- **Mitigation**:
  - SQLAlchemy ORM (parameterized queries)
  - Input validation
  - Least privilege DB user
- **Risk**: LOW

#### T3: Cross-Site Scripting (XSS)
- **Attack**: Injecting malicious scripts
- **Mitigation**:
  - Strict Content Security Policy
  - Template auto-escaping
  - No JavaScript execution
- **Risk**: LOW

#### T4: Cross-Site Request Forgery (CSRF)
- **Attack**: Unauthorized actions via victim's session
- **Mitigation**:
  - CSRF tokens
  - SameSite cookies
  - Referrer validation
- **Risk**: LOW

#### T5: Session Hijacking
- **Attack**: Stealing or predicting session tokens
- **Mitigation**:
  - Secure, HTTPOnly, SameSite cookies
  - Session timeout
  - Session regeneration
  - TLS encryption
- **Risk**: LOW

#### T6: Denial of Service (DoS)
- **Attack**: Overwhelming system resources
- **Mitigation**:
  - Multi-tier rate limiting
  - Connection limits
  - Resource limits (Docker)
- **Risk**: MEDIUM (inherent in any web service)

#### T7: Man-in-the-Middle (MITM)
- **Attack**: Intercepting network traffic
- **Mitigation**:
  - TLS 1.3 encryption
  - Tor hidden service
  - HSTS header
- **Risk**: LOW

#### T8: Malware/Backdoors
- **Attack**: Malicious code insertion
- **Mitigation**:
  - File integrity monitoring
  - Code reviews (educational)
  - Read-only containers
- **Risk**: LOW

#### T9: Insider Threats
- **Attack**: Malicious admin/developer
- **Mitigation**:
  - Audit logging
  - Admin action tracking
  - Principle of least privilege
- **Risk**: MEDIUM (training environment)

#### T10: Data Exfiltration
- **Attack**: Unauthorized data export
- **Mitigation**:
  - Field-level encryption
  - Access controls
  - Audit logging
  - Network isolation
- **Risk**: MEDIUM

## Security Best Practices

### For Developers
1. Never hardcode secrets
2. Use parameterized queries
3. Validate all inputs
4. Implement least privilege
5. Log security events
6. Keep dependencies updated
7. Review code for vulnerabilities
8. Test security controls

### For Operators
1. Change default credentials
2. Enable 2FA for admins
3. Monitor security logs
4. Keep backups encrypted
5. Patch regularly
6. Limit network exposure
7. Use strong passwords
8. Implement network segmentation

### For Users
1. Use strong passwords
2. Enable 2FA
3. Verify PGP fingerprints
4. Don't reuse passwords
5. Log out after use
6. Monitor account activity
7. Report suspicious behavior

## Compliance

### Data Protection
- Data minimization
- User consent
- Right to deletion (GDPR)
- Data encryption
- Audit trails

### Security Standards
- OWASP Top 10 mitigation
- CIS Docker Benchmark
- NIST Cybersecurity Framework (reference)

## Incident Response

### Detection
1. Monitor security logs
2. File integrity alerts
3. Failed login spikes
4. Anomaly detection

### Response
1. Isolate affected systems
2. Preserve logs and evidence
3. Patch vulnerabilities
4. Notify affected users (if applicable)
5. Post-incident review

### Recovery
1. Restore from backups
2. Verify integrity
3. Reset compromised credentials
4. Document lessons learned

## Security Testing

### Recommended Tests
1. **Penetration Testing**
   - SQL injection attempts
   - XSS payloads
   - CSRF attacks
   - Authentication bypass

2. **Vulnerability Scanning**
   - Dependency scanning (pip-audit)
   - Container scanning
   - Port scanning

3. **Code Review**
   - Manual security review
   - Static analysis (bandit)
   - Secrets detection

4. **Stress Testing**
   - Rate limit effectiveness
   - DoS resilience
   - Resource exhaustion

## Limitations

This is an **educational training environment**:
- Not production-ready
- Mock escrow system
- Local deployment only
- Simplified threat model
- For training purposes only

## Reporting Security Issues

For this training environment:
- Create an issue in the repository
- Document the vulnerability
- Suggest remediation
- No real user data at risk

---

**© 2026 Social Market - Educational Use Only**
