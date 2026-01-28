"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Admin Routes - Placeholder
Purpose: Admin dashboard and moderation
"""

from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user
from functools import wraps
from app import db

admin_bp = Blueprint('admin', __name__)


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin():
            flash('Admin access required', 'error')
            return redirect(url_for('marketplace.index'))
        return f(*args, **kwargs)
    return decorated_function


@admin_bp.route('/dashboard')
@login_required
@admin_required
def dashboard():
    """Admin dashboard"""
    from app.models.user import User
    from app.models.product import Product
    from app.models.order import Order

    stats = {
        'total_users': User.query.count(),
        'total_products': Product.query.count(),
        'total_orders': Order.query.count(),
        'total_transactions': Order.query.filter(Order.status.in_(['completed', 'paid'])).count()
    }

    return render_template('admin/dashboard.html', stats=stats)


@admin_bp.route('/users')
@login_required
@admin_required
def users():
    """User management"""
    from app.models.user import User
    from flask import request

    # Get filter parameters
    role = request.args.get('role', '')
    search = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)

    # Build query
    query = User.query

    if role:
        query = query.filter_by(role=role)

    if search:
        query = query.filter(
            db.or_(
                User.username.ilike(f'%{search}%'),
                User.email.ilike(f'%{search}%')
            )
        )

    # Paginate results
    users_pagination = query.order_by(User.created_at.desc()).paginate(
        page=page,
        per_page=20,
        error_out=False
    )

    return render_template('admin/users.html', users=users_pagination, search=search, role=role)


@admin_bp.route('/security')
@login_required
@admin_required
def security():
    """Security dashboard"""
    from app.models.user import User
    from datetime import datetime, timedelta

    # Security statistics for template
    recent_time = datetime.utcnow() - timedelta(hours=1)

    stats = {
        'failed_logins': User.query.filter(User.failed_login_attempts > 0).count(),
        'rate_limit_hits': 0,  # TODO: Implement rate limit tracking
        'security_events': User.query.filter(User.account_locked_until.isnot(None)).count(),
        'active_sessions': User.query.filter(User.last_login > recent_time).count(),
        'locked_accounts': User.query.filter(User.account_locked_until.isnot(None)).count(),
        'users_without_2fa': User.query.filter_by(two_factor_enabled=False, role='admin').count(),
        'total_admins': User.query.filter_by(role='admin').count(),
        'total_vendors': User.query.filter_by(role='vendor').count(),
        'total_buyers': User.query.filter_by(role='buyer').count()
    }

    # System health checks
    health = {
        'database': True,  # TODO: Implement actual DB check
        'redis': True,  # TODO: Implement actual Redis check
        'celery': True,  # TODO: Implement actual Celery check
        'disk_usage': 50  # TODO: Implement actual disk usage check
    }

    return render_template('admin/security.html', stats=stats, health=health)


@admin_bp.route('/audit-logs')
@login_required
@admin_required
def audit_logs():
    """Audit logs viewer"""
    # TODO: Implement audit log viewing
    # For now, redirect to security page
    return redirect(url_for('admin.security'))


@admin_bp.route('/system-health')
@login_required
@admin_required
def system_health():
    """System health monitoring"""
    # TODO: Implement system health checks
    # For now, redirect to security page
    return redirect(url_for('admin.security'))


@admin_bp.route('/user/<uuid:user_id>')
@login_required
@admin_required
def user_detail(user_id):
    """View user details"""
    from app.models.user import User
    from app.models.product import Product
    from app.models.order import Order

    user = User.query.get_or_404(user_id)

    # Get user statistics
    stats = {}
    if user.is_vendor():
        stats['products'] = Product.query.filter_by(vendor_id=user.id).count()
        stats['orders'] = Order.query.filter_by(vendor_id=user.id).count()
    else:
        stats['orders'] = Order.query.filter_by(buyer_id=user.id).count()

    return render_template('admin/user_detail.html', user=user, stats=stats)


@admin_bp.route('/user/<uuid:user_id>/deactivate', methods=['POST'])
@login_required
@admin_required
def deactivate_user(user_id):
    """Deactivate user account"""
    from app.models.user import User
    user = User.query.get_or_404(user_id)
    user.is_active = False
    db.session.commit()
    flash(f'User {user.username} deactivated', 'success')
    return redirect(url_for('admin.users'))


@admin_bp.route('/user/<uuid:user_id>/activate', methods=['POST'])
@login_required
@admin_required
def activate_user(user_id):
    """Activate user account"""
    from app.models.user import User
    user = User.query.get_or_404(user_id)
    user.is_active = True
    db.session.commit()
    flash(f'User {user.username} activated', 'success')
    return redirect(url_for('admin.users'))
