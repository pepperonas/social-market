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

# Initialize extensions
db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
session = Session()
csrf = CSRFProtect()
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["10 per second"],
    # No credentials in source. Real URL (incl. password) comes from RATELIMIT_STORAGE_URL.
    storage_uri=os.getenv('RATELIMIT_STORAGE_URL', 'redis://redis:6379/1')
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

    # Override with environment-specific config.
    # NOTE: config.py exports a ``config`` dict; there is no module attribute
    # named e.g. ``testing``, so from_object('app.config.testing') would fail --
    # which meant create_app('testing') raised and no named config ever applied.
    #
    # Gunicorn calls the factory as ``create_app()``, so the environment selects
    # the config. This is opt-in via APP_CONFIG rather than reusing FLASK_ENV:
    # ProductionConfig additionally sets WTF_CSRF_SSL_STRICT, which needs HTTPS
    # end to end and would break form posts on the plain-HTTP training setup.
    if config_name is None:
        config_name = os.environ.get('APP_CONFIG')

    if config_name:
        from app.config import config as config_map
        if config_name not in config_map:
            raise ValueError(
                f'Unknown config name {config_name!r}. '
                f'Available: {", ".join(sorted(config_map))}'
            )
        app.config.from_object(config_map[config_name])

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

    # Favicon route (redirect .ico requests to SVG)
    @app.route('/favicon.ico')
    def favicon():
        """Serve favicon"""
        from flask import send_from_directory
        import os
        return send_from_directory(
            os.path.join(app.root_path, 'static'),
            'favicon.svg',
            mimetype='image/svg+xml'
        )

    return app


def initialize_extensions(app):
    """Initialize Flask extensions"""

    # Database
    db.init_app(app)
    migrate.init_app(app, db)

    # Session management - configure Redis connection
    import redis as redis_lib
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
    from app.routes.cart import cart_bp
    from app.routes.account import account_bp
    from app.routes.notifications import notifications_bp

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(marketplace_bp, url_prefix='/')
    app.register_blueprint(vendor_bp, url_prefix='/vendor')
    app.register_blueprint(buyer_bp, url_prefix='/buyer')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(messages_bp, url_prefix='/messages')
    app.register_blueprint(cart_bp, url_prefix='/cart')
    app.register_blueprint(account_bp, url_prefix='/account')
    app.register_blueprint(notifications_bp, url_prefix='/notifications')


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

    if app.debug or app.config.get('TESTING'):
        return

    formatter = logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
    )

    # File handler (directory created by Dockerfile). Outside the container the
    # path does not exist -- fall back to stderr instead of failing app startup.
    log_path = app.config.get('LOG_FILE', '/var/log/marketplace/app.log')
    try:
        from logging.handlers import RotatingFileHandler
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        handler = RotatingFileHandler(log_path, maxBytes=10240000, backupCount=10)
    except OSError as exc:
        handler = logging.StreamHandler()
        app.logger.warning('File logging unavailable (%s); logging to stderr', exc)

    handler.setFormatter(formatter)
    handler.setLevel(logging.INFO)
    app.logger.addHandler(handler)

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
        'form-action': "'self'",
        'report-uri': '/admin/csp-report-uri'
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

    # Store request ID in Flask g for logging/audit correlation
    from flask import g, request as flask_request

    @app.before_request
    def set_request_id():
        g.request_id = flask_request.environ.get('HTTP_X_REQUEST_ID', '')

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
