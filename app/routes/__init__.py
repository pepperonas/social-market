"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Routes Package
Purpose: Flask blueprints for application routing
"""

from flask import current_app, flash


def flash_internal_error(what):
    """
    Report an unexpected error: full detail to the log, a generic message to the page.

    Many handlers did `flash(f'Error {what}: {str(e)}')`. For an unexpected
    exception that text is the database's own message -- SQL fragments,
    constraint and column names, sometimes values -- shown to whoever triggered
    it. Expected, user-facing errors are raised as ValueError with a message
    written for the user and are still shown as they are.

    Call it from inside the `except` block (it logs the active exception).
    """
    current_app.logger.exception('Unexpected error while %s', what)
    flash(f'Something went wrong while {what}. Nothing was changed -- please try again.',
          'danger')


from app.routes.auth import auth_bp  # noqa: E402
from app.routes.marketplace import marketplace_bp  # noqa: E402
from app.routes.vendor import vendor_bp  # noqa: E402
from app.routes.buyer import buyer_bp  # noqa: E402
from app.routes.admin import admin_bp  # noqa: E402
from app.routes.messages import messages_bp  # noqa: E402
from app.routes.cart import cart_bp  # noqa: E402
from app.routes.account import account_bp  # noqa: E402
from app.routes.notifications import notifications_bp  # noqa: E402

__all__ = [
    'flash_internal_error',
    'auth_bp',
    'marketplace_bp',
    'vendor_bp',
    'buyer_bp',
    'admin_bp',
    'messages_bp',
    'cart_bp',
    'account_bp',
    'notifications_bp',
]
