"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Admin Routes - Placeholder
Purpose: Admin dashboard and moderation
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
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
    """
    Audit logs viewer with filtering
    - Auth events
    - Security events
    - Admin actions
    - Transaction events
    """
    from flask import request
    from sqlalchemy import text
    
    log_type = request.args.get('type', 'auth')
    page = request.args.get('page', 1, type=int)
    per_page = 50
    offset = (page - 1) * per_page
    
    logs = []
    total_count = 0
    
    try:
        if log_type == 'auth':
            # Auth logs
            result = db.session.execute(
                text("""
                    SELECT id, username, user_id, action, ip_address, user_agent, 
                           failure_reason, timestamp
                    FROM auth_log 
                    ORDER BY timestamp DESC
                    LIMIT :limit OFFSET :offset
                """),
                {'limit': per_page, 'offset': offset}
            )
            logs = result.fetchall()
            
            count_result = db.session.execute(text("SELECT COUNT(*) FROM auth_log"))
            total_count = count_result.scalar()
            
        elif log_type == 'security':
            # Security events
            result = db.session.execute(
                text("""
                    SELECT id, event_type, severity, source, user_id, ip_address, 
                           description, timestamp
                    FROM security_events 
                    ORDER BY timestamp DESC
                    LIMIT :limit OFFSET :offset
                """),
                {'limit': per_page, 'offset': offset}
            )
            logs = result.fetchall()
            
            count_result = db.session.execute(text("SELECT COUNT(*) FROM security_events"))
            total_count = count_result.scalar()
            
        elif log_type == 'admin':
            # Admin actions
            result = db.session.execute(
                text("""
                    SELECT id, admin_user_id, action, target_type, target_id, 
                           reason, ip_address, timestamp
                    FROM admin_actions 
                    ORDER BY timestamp DESC
                    LIMIT :limit OFFSET :offset
                """),
                {'limit': per_page, 'offset': offset}
            )
            logs = result.fetchall()
            
            count_result = db.session.execute(text("SELECT COUNT(*) FROM admin_actions"))
            total_count = count_result.scalar()
            
        elif log_type == 'audit':
            # General audit log
            result = db.session.execute(
                text("""
                    SELECT id, user_id, action, table_name, record_id, 
                           status, severity, timestamp
                    FROM audit_log 
                    ORDER BY timestamp DESC
                    LIMIT :limit OFFSET :offset
                """),
                {'limit': per_page, 'offset': offset}
            )
            logs = result.fetchall()
            
            count_result = db.session.execute(text("SELECT COUNT(*) FROM audit_log"))
            total_count = count_result.scalar()
            
    except Exception as e:
        flash(f'Error loading logs: {str(e)}', 'danger')
    
    total_pages = (total_count + per_page - 1) // per_page
    
    return render_template('admin/audit_logs.html', 
                         logs=logs, 
                         log_type=log_type,
                         page=page,
                         total_pages=total_pages,
                         total_count=total_count)


@admin_bp.route('/system-health')
@login_required
@admin_required
def system_health():
    """
    System health monitoring dashboard
    - Database connectivity
    - Redis status
    - Disk usage
    - Memory usage
    - Service uptime
    """
    import os
    import psutil
    from datetime import datetime
    
    health = {
        'database': {'status': 'unknown', 'latency': 0},
        'redis': {'status': 'unknown', 'latency': 0},
        'disk': {'status': 'unknown', 'usage': 0, 'free': 0},
        'memory': {'status': 'unknown', 'usage': 0, 'available': 0},
        'celery': {'status': 'unknown'},
        'tor': {'status': 'unknown'}
    }
    
    # Check Database
    try:
        from sqlalchemy import text
        import time
        
        start = time.time()
        db.session.execute(text("SELECT 1"))
        latency = (time.time() - start) * 1000
        
        health['database'] = {
            'status': 'healthy' if latency < 100 else 'degraded',
            'latency': round(latency, 2)
        }
    except Exception as e:
        health['database'] = {'status': 'unhealthy', 'error': str(e)}
    
    # Check Redis
    try:
        import redis
        import time
        
        r = redis.from_url(current_app.config['REDIS_URL'])
        start = time.time()
        r.ping()
        latency = (time.time() - start) * 1000
        
        health['redis'] = {
            'status': 'healthy' if latency < 50 else 'degraded',
            'latency': round(latency, 2)
        }
    except Exception as e:
        health['redis'] = {'status': 'unhealthy', 'error': str(e)}
    
    # Check Disk
    try:
        disk = psutil.disk_usage('/')
        usage_percent = disk.percent
        free_gb = disk.free / (1024 ** 3)
        
        status = 'healthy'
        if usage_percent > 90:
            status = 'critical'
        elif usage_percent > 80:
            status = 'warning'
        
        health['disk'] = {
            'status': status,
            'usage': usage_percent,
            'free': round(free_gb, 2)
        }
    except Exception as e:
        health['disk'] = {'status': 'unknown', 'error': str(e)}
    
    # Check Memory
    try:
        memory = psutil.virtual_memory()
        usage_percent = memory.percent
        available_gb = memory.available / (1024 ** 3)
        
        status = 'healthy'
        if usage_percent > 90:
            status = 'critical'
        elif usage_percent > 80:
            status = 'warning'
        
        health['memory'] = {
            'status': status,
            'usage': usage_percent,
            'available': round(available_gb, 2)
        }
    except Exception as e:
        health['memory'] = {'status': 'unknown', 'error': str(e)}
    
    # Overall health score
    healthy_count = sum(1 for k, v in health.items() if v.get('status') == 'healthy')
    total_checks = len(health)
    health_score = (healthy_count / total_checks) * 100
    
    return render_template('admin/system_health.html', 
                         health=health, 
                         health_score=health_score,
                         timestamp=datetime.utcnow())


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
