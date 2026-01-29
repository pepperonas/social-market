"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Flask Application Factory
Purpose: Secure marketplace training application
"""

import os
import logging
from flask import Flask, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_session import Session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman
from flask_wtf.csrf import CSRFProtect
from celery import Celery
import redis

# Initialize extensions
db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
session = Session()
csrf = CSRFProtect()
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["10 per second"],
    storage_uri=os.getenv('RATELIMIT_STORAGE_URL', 'redis://:***REMOVED-REDIS-PASSWORD***@redis:6379/1')
)
celery = Celery()


def create_app(config_name=None):
    """
    Application factory pattern for creating Flask app instance

    Args:
        config_name: Configuration environment (development, production, etc.)

    Returns:
        Flask application instance
    """
    app = Flask(__name__)

    # Load configuration
    from app.config import Config
    app.config.from_object(Config)

    # Override with instance config if exists
    if config_name:
        app.config.from_object(f'app.config.{config_name}')

    # Initialize extensions
    initialize_extensions(app)

    # Register blueprints
    register_blueprints(app)

    # Register error handlers
    register_error_handlers(app)

    # Setup logging
    setup_logging(app)

    # Register shell context
    register_shell_context(app)

    # Security middleware
    setup_security(app)

    # Health check endpoint
    @app.route('/health')
    def health_check():
        """Health check endpoint for monitoring"""
        return jsonify({
            'status': 'healthy',
            'environment': 'training',
            'disclaimer': 'Educational security training environment only'
        }), 200

    return app


def initialize_extensions(app):
    """Initialize Flask extensions"""

    # Database
    db.init_app(app)
    migrate.init_app(app, db)

    # Session management - configure Redis connection
    import redis as redis_lib
    import secrets
    app.config['SESSION_REDIS'] = redis_lib.from_url(app.config['REDIS_URL'])
    session.init_app(app)

    # Monkey-patch the session interface to generate string session IDs
    # Flask-Session 0.8.0 already returns strings, but we keep this for compatibility
    # (actually not needed anymore with Flask-Session 0.8.0, but keeping for safety)

    # Authentication
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.session_protection = 'strong'

    # CSRF protection
    csrf.init_app(app)

    # Rate limiting
    limiter.init_app(app)

    # Celery
    celery.conf.update(app.config)

    # User loader for Flask-Login
    from app.models.user import User
    from uuid import UUID

    @login_manager.user_loader
    def load_user(user_id):
        try:
            # Convert string to UUID if necessary
            if isinstance(user_id, str):
                user_id = UUID(user_id)
            return User.query.get(user_id)
        except (ValueError, AttributeError):
            return None


def register_blueprints(app):
    """Register Flask blueprints"""

    from app.routes.auth import auth_bp
    from app.routes.marketplace import marketplace_bp
    from app.routes.vendor import vendor_bp
    from app.routes.buyer import buyer_bp
    from app.routes.admin import admin_bp
    from app.routes.messages import messages_bp

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(marketplace_bp, url_prefix='/')
    app.register_blueprint(vendor_bp, url_prefix='/vendor')
    app.register_blueprint(buyer_bp, url_prefix='/buyer')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(messages_bp, url_prefix='/messages')


def register_error_handlers(app):
    """Register error handlers"""

    @app.errorhandler(400)
    def bad_request(error):
        return jsonify({'error': 'Bad request'}), 400

    @app.errorhandler(401)
    def unauthorized(error):
        return jsonify({'error': 'Unauthorized'}), 401

    @app.errorhandler(403)
    def forbidden(error):
        return jsonify({'error': 'Forbidden'}), 403

    @app.errorhandler(404)
    def not_found(error):
        return jsonify({'error': 'Not found'}), 404

    @app.errorhandler(429)
    def rate_limit_exceeded(error):
        return jsonify({
            'error': 'Rate limit exceeded',
            'message': 'Too many requests. Please try again later.'
        }), 429

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        app.logger.error(f'Internal error: {error}')
        return jsonify({'error': 'Internal server error'}), 500


def setup_logging(app):
    """Setup application logging"""

    if not app.debug:
        # File handler (directory created by Dockerfile)
        from logging.handlers import RotatingFileHandler
        file_handler = RotatingFileHandler(
            '/var/log/marketplace/app.log',
            maxBytes=10240000,
            backupCount=10
        )
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
        ))
        file_handler.setLevel(logging.INFO)
        app.logger.addHandler(file_handler)

        app.logger.setLevel(logging.INFO)
        app.logger.info('Marketplace training environment startup')


def register_shell_context(app):
    """Register shell context for flask shell command"""

    @app.shell_context_processor
    def make_shell_context():
        from app.models.user import User
        from app.models.product import Product
        from app.models.order import Order
        from app.models.escrow import Escrow
        from app.models.message import Message

        return {
            'db': db,
            'User': User,
            'Product': Product,
            'Order': Order,
            'Escrow': Escrow,
            'Message': Message
        }


def setup_security(app):
    """Setup security middleware and headers"""

    # Security headers (Talisman)
    # Use nonce-based CSP for inline scripts
    csp = {
        'default-src': "'self'",
        'script-src': "'self'",  # Allow scripts from same origin + nonce
        'style-src': ["'self'", "'unsafe-inline'", "https://cdn.jsdelivr.net"],  # Allow Bootstrap CDN for training
        'img-src': ["'self'", "data:"],
        'font-src': "'self'",
        'connect-src': "'self'",
        'frame-ancestors': "'none'",
        'base-uri': "'self'",
        'form-action': "'self'"
    }

    Talisman(
        app,
        force_https=False,  # Set to True in production with HTTPS
        strict_transport_security=True,
        strict_transport_security_max_age=31536000,
        content_security_policy=csp,
        content_security_policy_nonce_in=['script-src'],  # Use nonce for scripts
        referrer_policy='no-referrer',
        feature_policy={
            'geolocation': "'none'",
            'microphone': "'none'",
            'camera': "'none'"
        }
    )

    # Request ID middleware
    from app.middleware.security_headers import SecurityHeadersMiddleware
    app.wsgi_app = SecurityHeadersMiddleware(app.wsgi_app)

    # Register CLI commands
    from app.cli import register_commands
    register_commands(app)


# =============================================================================
# Disclaimer Notice
# =============================================================================

print("""
================================================================================
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
================================================================================
This is a LOCAL, ISOLATED training environment for IT security education.

Purpose: Understanding secure system architecture and hardening
NOT FOR: Production use, illegal activities, or public deployment

Legal Notice: For authorized security training only
Social Market
================================================================================
""")
