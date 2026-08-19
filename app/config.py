"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Application Configuration
Purpose: Centralized configuration management
"""

import os
import tempfile
from datetime import timedelta


class Config:
    """Base configuration class"""

    # =============================================================================
    # Application Settings
    # =============================================================================
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-key-change-me-in-production'
    DEBUG = os.environ.get('DEBUG', 'false').lower() == 'true'

    # =============================================================================
    # Database Configuration
    # =============================================================================
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'postgresql://marketplace:password@postgres:5432/marketplace'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = os.environ.get('SQLALCHEMY_ECHO', 'false').lower() == 'true'
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': int(os.environ.get('SQLALCHEMY_POOL_SIZE', 10)),
        'pool_recycle': int(os.environ.get('SQLALCHEMY_POOL_RECYCLE', 3600)),
        'pool_pre_ping': True,
        'max_overflow': int(os.environ.get('SQLALCHEMY_MAX_OVERFLOW', 20)),
        'connect_args': {
            'sslmode': os.environ.get('DB_SSLMODE', 'prefer'),
        },
    }

    # Database encryption key
    DB_ENCRYPTION_KEY = os.environ.get('DB_ENCRYPTION_KEY') or 'dev-encryption-key'

    # =============================================================================
    # Session Configuration
    # =============================================================================
    SESSION_TYPE = 'redis'
    SESSION_PERMANENT = True
    SESSION_USE_SIGNER = True
    SESSION_KEY_PREFIX = 'marketplace:'
    SESSION_REDIS = None  # Set in __init__ from REDIS_URL
    SESSION_SERIALIZATION_FORMAT = 'json'  # Use JSON serialization to avoid bytes issues
    SESSION_ID_FIELD = 'sid'

    # Session cookie settings (security)
    SESSION_COOKIE_NAME = 'marketplace_session'
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', 'true').lower() == 'true'
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = timedelta(seconds=int(os.environ.get('PERMANENT_SESSION_LIFETIME', 3600)))

    # =============================================================================
    # Redis Configuration
    # =============================================================================
    REDIS_URL = os.environ.get('REDIS_URL') or 'redis://redis:6379/0'

    # =============================================================================
    # Celery Configuration
    # =============================================================================
    CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL') or 'redis://redis:6379/2'
    CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND') or 'redis://redis:6379/3'
    CELERY_TASK_SERIALIZER = 'json'
    CELERY_RESULT_SERIALIZER = 'json'
    CELERY_ACCEPT_CONTENT = ['json']
    CELERY_TIMEZONE = 'UTC'
    CELERY_ENABLE_UTC = True

    # =============================================================================
    # Security Configuration
    # =============================================================================

    # CSRF Protection
    WTF_CSRF_ENABLED = os.environ.get('WTF_CSRF_ENABLED', 'true').lower() == 'true'
    WTF_CSRF_TIME_LIMIT = int(os.environ.get('WTF_CSRF_TIME_LIMIT', 3600))
    WTF_CSRF_SSL_STRICT = False  # Set to True in production with HTTPS

    # Password Policy
    PASSWORD_MIN_LENGTH = int(os.environ.get('PASSWORD_MIN_LENGTH', 12))
    PASSWORD_REQUIRE_UPPERCASE = os.environ.get('PASSWORD_REQUIRE_UPPERCASE', 'true').lower() == 'true'
    PASSWORD_REQUIRE_LOWERCASE = os.environ.get('PASSWORD_REQUIRE_LOWERCASE', 'true').lower() == 'true'
    PASSWORD_REQUIRE_DIGITS = os.environ.get('PASSWORD_REQUIRE_DIGITS', 'true').lower() == 'true'
    PASSWORD_REQUIRE_SPECIAL = os.environ.get('PASSWORD_REQUIRE_SPECIAL', 'true').lower() == 'true'

    # Password Hashing - Argon2id with Pepper
    # Pepper: Secret server-side value added to passwords before hashing
    # CRITICAL: Generate with: python3 -c "import secrets; print(secrets.token_hex(32))"
    # Store securely in environment, never commit to git
    PASSWORD_PEPPER = os.environ.get('PASSWORD_PEPPER') or 'dev-pepper-CHANGE-ME-IN-PRODUCTION'

    # Bcrypt rounds (legacy, kept for migration compatibility)
    BCRYPT_LOG_ROUNDS = int(os.environ.get('BCRYPT_LOG_ROUNDS', 12))

    # Failed login attempts
    MAX_FAILED_LOGIN_ATTEMPTS = int(os.environ.get('MAX_FAILED_LOGIN_ATTEMPTS', 5))
    ACCOUNT_LOCKOUT_DURATION = int(os.environ.get('ACCOUNT_LOCKOUT_DURATION', 900))  # 15 minutes

    # =============================================================================
    # Rate Limiting
    # =============================================================================
    RATELIMIT_ENABLED = os.environ.get('RATELIMIT_ENABLED', 'true').lower() == 'true'
    RATELIMIT_STORAGE_URL = os.environ.get('RATELIMIT_STORAGE_URL') or 'redis://redis:6379/1'

    # Default rate limits
    RATELIMIT_DEFAULT = os.environ.get('RATELIMIT_DEFAULT', '10 per second')
    RATELIMIT_LOGIN = os.environ.get('RATELIMIT_LOGIN', '1 per minute')
    RATELIMIT_REGISTER = os.environ.get('RATELIMIT_REGISTER', '1 per hour')
    RATELIMIT_API = os.environ.get('RATELIMIT_API', '100 per minute')

    # =============================================================================
    # Reverse proxy
    # =============================================================================
    # Number of trusted proxy hops in front of the app. 0 disables X-Forwarded-*
    # handling entirely, which is the safe default: a client can set those
    # headers itself, so trusting them without a known hop count allows source
    # IP spoofing. Set to 1 when running behind exactly one nginx.
    TRUSTED_PROXY_COUNT = int(os.environ.get('TRUSTED_PROXY_COUNT', 0))

    # Public base URL, used for the Canonical field in security.txt
    APP_URL = os.environ.get('APP_URL', 'http://localhost:8080')

    # =============================================================================
    # Logging
    # =============================================================================
    # Documented in .env.example but previously never read -- the path was
    # hard-coded in setup_logging().
    LOG_FILE = os.environ.get('LOG_FILE', '/var/log/marketplace/app.log')

    # =============================================================================
    # File Upload Configuration
    # =============================================================================
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 5 * 1024 * 1024))  # 5MB
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', '/app/uploads')
    ALLOWED_EXTENSIONS = set(os.environ.get('ALLOWED_EXTENSIONS', 'png,jpg,jpeg,gif').split(','))
    MAX_IMAGE_SIZE = int(os.environ.get('MAX_IMAGE_SIZE', 2 * 1024 * 1024))  # 2MB

    # =============================================================================
    # Escrow Configuration
    # =============================================================================
    ESCROW_AUTO_RELEASE_DAYS = int(os.environ.get('ESCROW_AUTO_RELEASE_DAYS', 14))
    ESCROW_COMMISSION_PERCENT = float(os.environ.get('ESCROW_COMMISSION_PERCENT', 3.0))
    ESCROW_DISPUTE_WINDOW_DAYS = int(os.environ.get('ESCROW_DISPUTE_WINDOW_DAYS', 7))

    # =============================================================================
    # Messaging Configuration
    # =============================================================================
    MESSAGE_RETENTION_DAYS = int(os.environ.get('MESSAGE_RETENTION_DAYS', 30))
    MESSAGE_MAX_LENGTH = int(os.environ.get('MESSAGE_MAX_LENGTH', 5000))
    REQUIRE_PGP_ENCRYPTION = os.environ.get('REQUIRE_PGP_ENCRYPTION', 'true').lower() == 'true'

    # =============================================================================
    # Application URLs
    # =============================================================================
    APP_URL = os.environ.get('APP_URL', 'http://localhost:8080')
    ONION_URL = os.environ.get('ONION_URL', '')

    # =============================================================================
    # Monitoring Configuration
    # =============================================================================
    FIM_ENABLED = os.environ.get('FIM_ENABLED', 'true').lower() == 'true'
    FIM_CHECK_INTERVAL = int(os.environ.get('FIM_CHECK_INTERVAL', 3600))
    FIM_BASELINE_PATH = os.environ.get('FIM_BASELINE_PATH', '/app/monitoring/baseline.json')

    MONITOR_ENABLED = os.environ.get('MONITOR_ENABLED', 'true').lower() == 'true'
    MONITOR_CHECK_INTERVAL = int(os.environ.get('MONITOR_CHECK_INTERVAL', 300))

    # =============================================================================
    # Audit Logging
    # =============================================================================
    AUDIT_LOG_ENABLED = os.environ.get('AUDIT_LOG_ENABLED', 'true').lower() == 'true'
    AUDIT_LOG_RETENTION_DAYS = int(os.environ.get('AUDIT_LOG_RETENTION_DAYS', 365))

    # =============================================================================
    # Backup Configuration
    # =============================================================================
    BACKUP_ENABLED = os.environ.get('BACKUP_ENABLED', 'true').lower() == 'true'
    BACKUP_INTERVAL = int(os.environ.get('BACKUP_INTERVAL', 86400))  # 24 hours
    BACKUP_RETENTION_DAYS = int(os.environ.get('BACKUP_RETENTION_DAYS', 7))
    BACKUP_ENCRYPTION_PASSPHRASE = os.environ.get('BACKUP_ENCRYPTION_PASSPHRASE', 'change-me')
    BACKUP_PATH = os.environ.get('BACKUP_PATH', '/backups')

    # =============================================================================
    # Email Configuration (for alerts)
    # =============================================================================
    MAIL_ENABLED = os.environ.get('MAIL_ENABLED', 'false').lower() == 'true'
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'localhost')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'true').lower() == 'true'
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME', '')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD', '')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER', 'noreply@marketplace.local')

    # =============================================================================
    # Feature Flags
    # =============================================================================
    ENABLE_REGISTRATION = os.environ.get('ENABLE_REGISTRATION', 'true').lower() == 'true'
    ENABLE_VENDOR_REGISTRATION = os.environ.get('ENABLE_VENDOR_REGISTRATION', 'true').lower() == 'true'
    ENABLE_2FA = os.environ.get('ENABLE_2FA', 'true').lower() == 'true'
    ENABLE_PGP_MESSAGING = os.environ.get('ENABLE_PGP_MESSAGING', 'true').lower() == 'true'
    ENABLE_ESCROW = os.environ.get('ENABLE_ESCROW', 'true').lower() == 'true'
    ENABLE_REVIEWS = os.environ.get('ENABLE_REVIEWS', 'true').lower() == 'true'

    # =============================================================================
    # Legal / Compliance
    # =============================================================================
    TERMS_VERSION = os.environ.get('TERMS_VERSION', '1.0')
    PRIVACY_VERSION = os.environ.get('PRIVACY_VERSION', '1.0')
    REQUIRE_TERMS_ACCEPTANCE = os.environ.get('REQUIRE_TERMS_ACCEPTANCE', 'true').lower() == 'true'
    DATA_RETENTION_DAYS = int(os.environ.get('DATA_RETENTION_DAYS', 365))

    # =============================================================================
    # Admin Configuration
    # =============================================================================
    ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'admin@localhost')
    ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'ChangeMe123!')

    # Dead Man's Switch
    DEADMAN_ENABLED = os.environ.get('DEADMAN_ENABLED', 'false').lower() == 'true'
    DEADMAN_CHECKIN_INTERVAL = int(os.environ.get('DEADMAN_CHECKIN_INTERVAL', 86400))
    DEADMAN_GRACE_PERIOD = int(os.environ.get('DEADMAN_GRACE_PERIOD', 172800))

    # =============================================================================
    # Tor Configuration
    # =============================================================================
    TOR_ENABLED = os.environ.get('TOR_ENABLED', 'true').lower() == 'true'
    TOR_SOCKS_PORT = int(os.environ.get('TOR_SOCKS_PORT', 9050))
    TOR_CONTROL_PORT = int(os.environ.get('TOR_CONTROL_PORT', 9051))


class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True
    SQLALCHEMY_ECHO = True


class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False
    SESSION_COOKIE_SECURE = True
    WTF_CSRF_SSL_STRICT = True


class TestingConfig(Config):
    """Testing configuration"""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = os.environ.get('TEST_DATABASE_URL', 'sqlite:///:memory:')
    # The base config sets PostgreSQL-only pool options (pool_size, max_overflow,
    # connect_args.sslmode). SQLite's StaticPool rejects them, so reset them here.
    SQLALCHEMY_ENGINE_OPTIONS = {}
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False
    # Tests must not need a Redis server.
    SESSION_TYPE = 'filesystem'
    RATELIMIT_STORAGE_URL = 'memory://'
    # The default is the container path /app/uploads, which does not exist (and
    # is not writable) outside Docker.
    UPLOAD_FOLDER = os.environ.get(
        'TEST_UPLOAD_FOLDER',
        os.path.join(tempfile.gettempdir(), 'socialmarket-test-uploads'),
    )


# Configuration dictionary
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': Config
}
