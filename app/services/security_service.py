"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Security Service
Purpose: IP blocking, canary tokens, threat detection
"""

import hashlib
import secrets
import json
from datetime import datetime, timedelta
from flask import request, current_app
from sqlalchemy import text
from app import db


class SecurityService:
    """
    Advanced security features:
    - IP blocking (automatic and manual)
    - Canary tokens for intrusion detection
    - Threat scoring
    - Honeypot fields
    """
    
    # ==========================================================================
    # IP Blocking
    # ==========================================================================
    
    @staticmethod
    def block_ip(ip_address, reason, duration_hours=24, blocked_by='system'):
        """
        Block an IP address
        
        Args:
            ip_address: IP to block
            reason: Reason for blocking
            duration_hours: Block duration in hours (0 = permanent)
            blocked_by: Who initiated the block (system, admin username)
        """
        try:
            expires_at = None
            if duration_hours > 0:
                expires_at = datetime.utcnow() + timedelta(hours=duration_hours)
            
            db.session.execute(
                text("""
                    INSERT INTO blocked_ips (ip_address, reason, blocked_by, expires_at, created_at)
                    VALUES (:ip, :reason, :blocked_by, :expires_at, NOW())
                    ON CONFLICT (ip_address) DO UPDATE SET
                        reason = EXCLUDED.reason,
                        blocked_by = EXCLUDED.blocked_by,
                        expires_at = EXCLUDED.expires_at,
                        updated_at = NOW()
                """),
                {
                    'ip': ip_address,
                    'reason': reason,
                    'blocked_by': blocked_by,
                    'expires_at': expires_at
                }
            )
            db.session.commit()
            
            current_app.logger.warning(f'IP blocked: {ip_address} - {reason}')
            return True
            
        except Exception as e:
            current_app.logger.error(f'Failed to block IP: {e}')
            db.session.rollback()
            return False
    
    @staticmethod
    def unblock_ip(ip_address):
        """Remove IP from blocklist"""
        try:
            db.session.execute(
                text("DELETE FROM blocked_ips WHERE ip_address = :ip"),
                {'ip': ip_address}
            )
            db.session.commit()
            current_app.logger.info(f'IP unblocked: {ip_address}')
            return True
        except Exception as e:
            current_app.logger.error(f'Failed to unblock IP: {e}')
            return False
    
    @staticmethod
    def is_ip_blocked(ip_address):
        """
        Check if IP is blocked
        
        Returns:
            tuple: (is_blocked, reason) or (False, None)
        """
        try:
            result = db.session.execute(
                text("""
                    SELECT reason, expires_at FROM blocked_ips 
                    WHERE ip_address = :ip 
                    AND (expires_at IS NULL OR expires_at > NOW())
                """),
                {'ip': ip_address}
            )
            row = result.fetchone()
            
            if row:
                return True, row.reason
            return False, None
            
        except Exception as e:
            current_app.logger.error(f'Error checking blocked IP: {e}')
            return False, None
    
    @staticmethod
    def get_blocked_ips():
        """Get all currently blocked IPs"""
        try:
            result = db.session.execute(
                text("""
                    SELECT ip_address, reason, blocked_by, expires_at, created_at
                    FROM blocked_ips 
                    WHERE expires_at IS NULL OR expires_at > NOW()
                    ORDER BY created_at DESC
                """)
            )
            return result.fetchall()
        except Exception as e:
            current_app.logger.error(f'Error fetching blocked IPs: {e}')
            return []
    
    @staticmethod
    def auto_block_check(ip_address):
        """
        Check if IP should be automatically blocked based on behavior
        
        Triggers:
        - Too many failed logins (>10 in 1 hour)
        - Too many rate limit hits (>50 in 1 hour)
        - Suspicious patterns
        """
        try:
            # Check failed logins
            result = db.session.execute(
                text("""
                    SELECT COUNT(*) FROM auth_log 
                    WHERE ip_address = :ip 
                    AND action LIKE 'login_failed%'
                    AND timestamp > NOW() - INTERVAL '1 hour'
                """),
                {'ip': ip_address}
            )
            failed_logins = result.scalar()
            
            if failed_logins > 10:
                SecurityService.block_ip(
                    ip_address, 
                    f'Automatic block: {failed_logins} failed logins in 1 hour',
                    duration_hours=24,
                    blocked_by='auto_security'
                )
                return True
            
            return False
            
        except Exception as e:
            current_app.logger.error(f'Auto-block check error: {e}')
            return False
    
    # ==========================================================================
    # Canary Tokens
    # ==========================================================================
    
    @staticmethod
    def create_canary_token(token_type, description, alert_email=None):
        """
        Create a canary token for intrusion detection
        
        Token types:
        - url: Triggers on access
        - username: Triggers on login attempt
        - file: Triggers on file access
        - api_key: Triggers on API usage
        
        Args:
            token_type: Type of canary
            description: What this canary protects
            alert_email: Email for alerts (optional)
            
        Returns:
            dict: Token details
        """
        try:
            token_value = secrets.token_urlsafe(32)
            token_hash = hashlib.sha256(token_value.encode()).hexdigest()
            
            db.session.execute(
                text("""
                    INSERT INTO canary_tokens 
                    (token_hash, token_type, description, alert_email, created_at, is_active)
                    VALUES (:hash, :type, :desc, :email, NOW(), true)
                """),
                {
                    'hash': token_hash,
                    'type': token_type,
                    'desc': description,
                    'email': alert_email
                }
            )
            db.session.commit()
            
            return {
                'token': token_value,
                'type': token_type,
                'description': description,
                'hash': token_hash[:16] + '...'  # Partial hash for reference
            }
            
        except Exception as e:
            current_app.logger.error(f'Failed to create canary: {e}')
            db.session.rollback()
            return None
    
    @staticmethod
    def trigger_canary(token_value):
        """
        Check and trigger a canary token
        
        Returns:
            bool: True if canary was triggered
        """
        try:
            token_hash = hashlib.sha256(token_value.encode()).hexdigest()
            
            result = db.session.execute(
                text("""
                    SELECT id, token_type, description, alert_email 
                    FROM canary_tokens 
                    WHERE token_hash = :hash AND is_active = true
                """),
                {'hash': token_hash}
            )
            canary = result.fetchone()
            
            if canary:
                # Log the trigger
                db.session.execute(
                    text("""
                        INSERT INTO canary_triggers 
                        (canary_id, ip_address, user_agent, triggered_at, metadata)
                        VALUES (:canary_id, :ip, :ua, NOW(), :meta)
                    """),
                    {
                        'canary_id': canary.id,
                        'ip': request.remote_addr if request else 'unknown',
                        'ua': request.headers.get('User-Agent', '') if request else 'unknown',
                        'meta': json.dumps({
                            'type': canary.token_type,
                            'description': canary.description
                        })
                    }
                )
                
                # Update trigger count
                db.session.execute(
                    text("""
                        UPDATE canary_tokens 
                        SET trigger_count = trigger_count + 1,
                            last_triggered_at = NOW()
                        WHERE id = :id
                    """),
                    {'id': canary.id}
                )
                
                db.session.commit()
                
                # Log security event
                from app.services.audit_service import log_security_event
                log_security_event(
                    'canary_triggered',
                    'critical',
                    f'Canary token triggered: {canary.description}',
                    ip_address=request.remote_addr if request else None
                )
                
                current_app.logger.critical(
                    f'CANARY TRIGGERED! Type: {canary.token_type}, '
                    f'Description: {canary.description}'
                )
                
                return True
            
            return False
            
        except Exception as e:
            current_app.logger.error(f'Canary trigger error: {e}')
            return False
    
    @staticmethod
    def get_canary_alerts(hours=24):
        """Get recent canary alerts"""
        try:
            result = db.session.execute(
                text("""
                    SELECT ct.id, ct.token_type, ct.description, 
                           tr.ip_address, tr.user_agent, tr.triggered_at
                    FROM canary_tokens ct
                    JOIN canary_triggers tr ON ct.id = tr.canary_id
                    WHERE tr.triggered_at > NOW() - INTERVAL ':hours hours'
                    ORDER BY tr.triggered_at DESC
                """),
                {'hours': hours}
            )
            return result.fetchall()
        except Exception as e:
            current_app.logger.error(f'Error fetching canary alerts: {e}')
            return []
    
    # ==========================================================================
    # Threat Scoring
    # ==========================================================================
    
    @staticmethod
    def calculate_threat_score(ip_address):
        """
        Calculate threat score for an IP address
        
        Factors:
        - Failed login attempts
        - Rate limit violations
        - Suspicious user agents
        - Known bad IP ranges
        
        Returns:
            int: Score 0-100 (higher = more suspicious)
        """
        score = 0
        
        try:
            # Failed logins (max 30 points)
            result = db.session.execute(
                text("""
                    SELECT COUNT(*) FROM auth_log 
                    WHERE ip_address = :ip 
                    AND action LIKE 'login_failed%'
                    AND timestamp > NOW() - INTERVAL '24 hours'
                """),
                {'ip': ip_address}
            )
            failed_logins = result.scalar()
            score += min(failed_logins * 3, 30)
            
            # Security events (max 30 points)
            result = db.session.execute(
                text("""
                    SELECT COUNT(*) FROM security_events 
                    WHERE ip_address = :ip 
                    AND timestamp > NOW() - INTERVAL '24 hours'
                """),
                {'ip': ip_address}
            )
            security_events = result.scalar()
            score += min(security_events * 5, 30)
            
            # Check user agent (suspicious patterns)
            if request:
                ua = request.headers.get('User-Agent', '').lower()
                suspicious_patterns = ['curl', 'wget', 'python', 'scanner', 'bot']
                for pattern in suspicious_patterns:
                    if pattern in ua:
                        score += 10
                        break
            
            # Check if IP was previously blocked
            result = db.session.execute(
                text("SELECT COUNT(*) FROM blocked_ips WHERE ip_address = :ip"),
                {'ip': ip_address}
            )
            if result.scalar() > 0:
                score += 20
            
        except Exception as e:
            current_app.logger.error(f'Threat score calculation error: {e}')
        
        return min(score, 100)
    
    # ==========================================================================
    # Honeypot Fields
    # ==========================================================================
    
    @staticmethod
    def check_honeypot(form_data, honeypot_fields=['hp_email', 'hp_website', 'hp_phone']):
        """
        Check if honeypot fields were filled (bot detection)
        
        Args:
            form_data: Form submission data
            honeypot_fields: List of honeypot field names
            
        Returns:
            bool: True if honeypot triggered (likely bot)
        """
        for field in honeypot_fields:
            if field in form_data and form_data[field]:
                # Log bot detection
                from app.services.audit_service import log_security_event
                log_security_event(
                    'honeypot_triggered',
                    'medium',
                    f'Honeypot field filled: {field}',
                    ip_address=request.remote_addr if request else None
                )
                return True
        return False


# Database tables for security features
SECURITY_TABLES_SQL = """
-- Blocked IPs table
CREATE TABLE IF NOT EXISTS blocked_ips (
    id SERIAL PRIMARY KEY,
    ip_address INET NOT NULL UNIQUE,
    reason TEXT NOT NULL,
    blocked_by VARCHAR(100) DEFAULT 'system',
    expires_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_blocked_ips_expires ON blocked_ips(expires_at);

-- Canary tokens table
CREATE TABLE IF NOT EXISTS canary_tokens (
    id SERIAL PRIMARY KEY,
    token_hash VARCHAR(64) NOT NULL UNIQUE,
    token_type VARCHAR(50) NOT NULL,
    description TEXT,
    alert_email VARCHAR(255),
    trigger_count INTEGER DEFAULT 0,
    last_triggered_at TIMESTAMP,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Canary triggers table
CREATE TABLE IF NOT EXISTS canary_triggers (
    id SERIAL PRIMARY KEY,
    canary_id INTEGER REFERENCES canary_tokens(id),
    ip_address INET,
    user_agent TEXT,
    triggered_at TIMESTAMP DEFAULT NOW(),
    metadata JSONB
);

CREATE INDEX IF NOT EXISTS idx_canary_triggers_time ON canary_triggers(triggered_at);
"""


def get_security_service():
    """Get security service singleton"""
    return SecurityService()
