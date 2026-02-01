"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Notifications Routes
Purpose: User notification management
"""

from flask import Blueprint, render_template, redirect, url_for, flash, jsonify, request
from flask_login import login_required, current_user

from app import db
from app.models.notification import Notification

notifications_bp = Blueprint('notifications', __name__)


@notifications_bp.route('/')
@login_required
def index():
    """View all notifications"""
    page = request.args.get('page', 1, type=int)
    
    # Get all notifications (paginated)
    notifications = Notification.query.filter_by(
        user_id=current_user.id
    ).order_by(Notification.created_at.desc()).paginate(
        page=page, per_page=20, error_out=False
    )
    
    # Get unread count
    unread_count = Notification.get_unread_count(current_user.id)
    
    return render_template('notifications/index.html',
                         notifications=notifications,
                         unread_count=unread_count)


@notifications_bp.route('/unread')
@login_required
def unread():
    """View unread notifications only"""
    notifications = Notification.get_recent(current_user.id, limit=50, include_read=False)
    unread_count = len(notifications)
    
    return render_template('notifications/index.html',
                         notifications={'items': notifications, 'pages': 1, 'page': 1},
                         unread_count=unread_count,
                         filter='unread')


@notifications_bp.route('/mark-read/<uuid:notification_id>', methods=['POST'])
@login_required
def mark_read(notification_id):
    """Mark single notification as read"""
    notification = Notification.query.get_or_404(notification_id)
    
    # Verify ownership
    if str(notification.user_id) != str(current_user.id):
        flash('Notification not found', 'danger')
        return redirect(url_for('notifications.index'))
    
    notification.mark_as_read()
    
    # If has action URL, redirect there
    if notification.action_url:
        return redirect(notification.action_url)
    
    return redirect(url_for('notifications.index'))


@notifications_bp.route('/mark-all-read', methods=['POST'])
@login_required
def mark_all_read():
    """Mark all notifications as read"""
    Notification.mark_all_read(current_user.id)
    flash('All notifications marked as read', 'success')
    return redirect(url_for('notifications.index'))


@notifications_bp.route('/delete/<uuid:notification_id>', methods=['POST'])
@login_required
def delete(notification_id):
    """Delete single notification"""
    notification = Notification.query.get_or_404(notification_id)
    
    # Verify ownership
    if str(notification.user_id) != str(current_user.id):
        flash('Notification not found', 'danger')
        return redirect(url_for('notifications.index'))
    
    try:
        db.session.delete(notification)
        db.session.commit()
        flash('Notification deleted', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Error deleting notification', 'danger')
    
    return redirect(url_for('notifications.index'))


# =============================================================================
# API Endpoints
# =============================================================================

@notifications_bp.route('/api/count')
@login_required
def api_count():
    """Get unread notification count (AJAX)"""
    count = Notification.get_unread_count(current_user.id)
    return jsonify({'count': count})


@notifications_bp.route('/api/recent')
@login_required
def api_recent():
    """Get recent notifications (AJAX)"""
    notifications = Notification.get_recent(current_user.id, limit=5, include_read=False)
    return jsonify({
        'count': len(notifications),
        'notifications': [n.to_dict() for n in notifications]
    })


@notifications_bp.route('/api/mark-read/<uuid:notification_id>', methods=['POST'])
@login_required
def api_mark_read(notification_id):
    """Mark notification as read (AJAX)"""
    notification = Notification.query.get_or_404(notification_id)
    
    if str(notification.user_id) != str(current_user.id):
        return jsonify({'success': False, 'error': 'Not found'}), 404
    
    notification.mark_as_read()
    return jsonify({'success': True})
