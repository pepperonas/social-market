"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Routes Package
Purpose: Flask blueprints for application routing
"""

from app.routes.auth import auth_bp
from app.routes.marketplace import marketplace_bp
from app.routes.vendor import vendor_bp
from app.routes.buyer import buyer_bp
from app.routes.admin import admin_bp
from app.routes.messages import messages_bp
from app.routes.cart import cart_bp
from app.routes.account import account_bp
from app.routes.notifications import notifications_bp

__all__ = [
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
