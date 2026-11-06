"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Account Security Routes
Purpose: Password management, session control, GDPR compliance
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app, session
from flask_login import login_required, current_user, login_user, logout_user
import json
import uuid

from app import db, limiter
from app.services.audit_service import log_auth_event, log_security_event
from app.routes.auth import reauth_allowed, reauth_failed, reauth_refused
from app.timeutil import utcnow

account_bp = Blueprint('account', __name__)


# =============================================================================
# Password Management
# =============================================================================

@account_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
@limiter.limit("5 per hour", methods=['POST'])
def change_password():
    """
    Change user password with security validation

    Security features:
    - Current password verification
    - Rate limiting
    - Audit logging
    - Session invalidation option
    """
    if request.method == 'POST':
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        if not reauth_allowed():
            return reauth_refused(url_for('account.change_password'))

        # Validate current password -- counts towards the lockout (see reauth_failed)
        if not current_user.check_password(current_password):
            return reauth_failed('Current password is incorrect',
                                 url_for('account.change_password'))

        # Validate new passwords match
        if new_password != confirm_password:
            flash('New passwords do not match', 'danger')
            return render_template('account/change_password.html')

        # The policy is enforced by set_password() (PasswordService.validate_policy).
        # This route used to re-implement it with a different special-character
        # set, so the same password could pass registration and fail here.
        try:
            # Update password. This also ends every existing session and
            # remember-me cookie of the user (User.end_all_sessions).
            current_user.set_password(new_password)
            db.session.commit()
            _keep_this_browser_logged_in()

            # Log successful change
            log_auth_event(
                current_user.username,
                current_user.id,
                'password_changed',
                request.remote_addr
            )

            log_security_event(
                'password_changed',
                'info',
                f'User {current_user.username} changed their password',
                current_user.id,
                request.remote_addr
            )

            flash('Password changed successfully. All other sessions have been signed out.', 'success')
            return redirect(url_for('account.security_settings'))

        except ValueError as e:
            flash(str(e), 'danger')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'Password change error: {e}')
            flash('Error changing password', 'danger')

    return render_template('account/change_password.html')


# =============================================================================
# Security Settings
# =============================================================================

@account_bp.route('/security')
@login_required
def security_settings():
    """
    Security settings overview
    - 2FA status
    - Recent login activity
    - Active sessions
    - Password age
    """

    # Get recent auth events
    recent_logins = []
    try:
        from sqlalchemy import text
        result = db.session.execute(
            text("""
                SELECT timestamp, action, ip_address, user_agent
                FROM auth_log
                WHERE user_id = :user_id
                ORDER BY timestamp DESC
                LIMIT 10
            """),
            {'user_id': current_user.id}
        )
        recent_logins = result.fetchall()
    except Exception as e:
        current_app.logger.error(f'Failed to fetch login history: {e}')

    # Calculate password age
    password_age_days = None
    if current_user.updated_at:
        password_age = utcnow() - current_user.updated_at
        password_age_days = password_age.days

    return render_template('account/security.html',
                         recent_logins=recent_logins,
                         password_age_days=password_age_days)


@account_bp.route('/sessions')
@login_required
def active_sessions():
    """View and manage active sessions"""
    # In production, this would query Redis for active sessions
    # For training, we show a placeholder
    sessions_data = []

    try:
        from sqlalchemy import text
        result = db.session.execute(
            text("""
                SELECT session_id, timestamp, ip_address, user_agent
                FROM auth_log
                WHERE user_id = :user_id AND action = 'login_success'
                ORDER BY timestamp DESC
                LIMIT 20
            """),
            {'user_id': current_user.id}
        )
        sessions_data = result.fetchall()
    except Exception as e:
        current_app.logger.error(f'Failed to fetch sessions: {e}')

    return render_template('account/sessions.html', sessions=sessions_data)


@account_bp.route('/sessions/terminate-all', methods=['POST'])
@login_required
def terminate_all_sessions():
    """Terminate all other sessions"""
    try:
        current_user.end_all_sessions()
        db.session.commit()
        _keep_this_browser_logged_in()

        log_security_event(
            'sessions_terminated',
            'info',
            f'User {current_user.username} terminated all other sessions',
            current_user.id,
            request.remote_addr
        )

        flash('All other sessions have been terminated', 'success')
    except Exception as e:
        current_app.logger.error(f'Error terminating sessions: {e}')
        flash('Error terminating sessions', 'danger')

    return redirect(url_for('account.security_settings'))


# =============================================================================
# Login Alerts & Notifications
# =============================================================================

@account_bp.route('/alerts')
@login_required
def login_alerts():
    """View login alerts and suspicious activity"""
    alerts = []

    try:
        from sqlalchemy import text
        result = db.session.execute(
            text("""
                SELECT timestamp, action, ip_address, user_agent, failure_reason
                FROM auth_log
                WHERE user_id = :user_id
                AND action LIKE 'login_failed%'
                ORDER BY timestamp DESC
                LIMIT 50
            """),
            {'user_id': current_user.id}
        )
        alerts = result.fetchall()
    except Exception as e:
        current_app.logger.error(f'Failed to fetch alerts: {e}')

    return render_template('account/alerts.html', alerts=alerts)


# =============================================================================
# GDPR Compliance
# =============================================================================

@account_bp.route('/privacy')
@login_required
def privacy_settings():
    """Privacy settings and data management"""
    return render_template('account/privacy.html')


@account_bp.route('/export-data', methods=['POST'])
@login_required
@limiter.limit("1 per day")
def export_data():
    """
    Export all user data (GDPR Right to Data Portability)

    Exports:
    - Profile information
    - Orders
    - Messages (encrypted)
    - Products (if vendor)
    - Activity logs
    """
    from flask import make_response

    try:
        data = {
            'export_date': utcnow().isoformat(),
            'user_id': str(current_user.id),
            'profile': {
                'username': current_user.username,
                'email': current_user.email,
                'display_name': current_user.display_name,
                'bio': current_user.bio,
                'role': current_user.role,
                'created_at': current_user.created_at.isoformat(),
                'two_factor_enabled': current_user.two_factor_enabled,
                'pgp_fingerprint': current_user.pgp_fingerprint
            },
            'orders': [],
            'products': [],
            'messages': []
        }

        # Export orders
        from app.models.order import Order
        orders = Order.query.filter(
            db.or_(Order.buyer_id == current_user.id, Order.vendor_id == current_user.id)
        ).all()

        for order in orders:
            data['orders'].append({
                'id': str(order.id),
                'role': 'buyer' if str(order.buyer_id) == str(current_user.id) else 'vendor',
                'status': order.status,
                'total_price': str(order.total_price),
                'created_at': order.created_at.isoformat()
            })

        # Export products if vendor
        if current_user.is_vendor():
            from app.models.product import Product
            products = Product.query.filter_by(vendor_id=current_user.id).all()
            for product in products:
                data['products'].append({
                    'id': str(product.id),
                    'title': product.title,
                    'description': product.description,
                    'price': str(product.price),
                    'created_at': product.created_at.isoformat()
                })

        # Export messages (encrypted content only - for privacy)
        from app.models.message import Message
        messages = Message.query.filter(
            db.or_(Message.sender_id == current_user.id, Message.recipient_id == current_user.id)
        ).all()

        for msg in messages:
            data['messages'].append({
                'id': str(msg.id),
                'direction': 'sent' if str(msg.sender_id) == str(current_user.id) else 'received',
                'is_encrypted': msg.is_encrypted,
                'created_at': msg.created_at.isoformat()
            })

        # Log export event
        log_security_event(
            'data_exported',
            'info',
            f'User {current_user.username} exported their data',
            current_user.id,
            request.remote_addr
        )

        # Return as downloadable JSON
        response = make_response(json.dumps(data, indent=2))
        response.headers['Content-Type'] = 'application/json'
        response.headers['Content-Disposition'] = f'attachment; filename=data_export_{current_user.username}_{utcnow().strftime("%Y%m%d")}.json'

        return response

    except Exception as e:
        current_app.logger.error(f'Data export error: {e}')
        flash('Error exporting data', 'danger')
        return redirect(url_for('account.privacy_settings'))


@account_bp.route('/delete-account', methods=['GET', 'POST'])
@login_required
@limiter.limit("3 per hour", methods=['POST'])
def delete_account():
    """
    Delete user account (GDPR Right to Erasure)

    Process:
    1. Verify password
    2. Soft delete user data
    3. Anonymize remaining records
    4. Log deletion
    5. Logout
    """
    if request.method == 'POST':
        password = request.form.get('password', '')
        confirmation = request.form.get('confirmation', '')

        if not reauth_allowed():
            return reauth_refused(url_for('account.delete_account'))

        # Verify password, and with 2FA on a current code: the password alone
        # must not be enough to destroy the account. Failures count towards the
        # lockout (see reauth_failed).
        if not current_user.check_password(password) or (
                current_user.two_factor_enabled and
                not current_user.verify_totp(request.form.get('token', '').strip())):
            return reauth_failed('Password or code incorrect',
                                 url_for('account.delete_account'))

        # Verify confirmation phrase
        if confirmation != f'DELETE {current_user.username}':
            flash('Please type the confirmation phrase exactly', 'danger')
            return render_template('account/delete_account.html')

        try:
            user_id = current_user.id
            username = current_user.username

            # Log deletion before anonymizing
            log_security_event(
                'account_deleted',
                'high',
                f'User account deleted: {username}',
                user_id,
                request.remote_addr
            )

            # Anonymize user data
            current_user.username = f'deleted_user_{uuid.uuid4().hex[:8]}'
            current_user.email = f'deleted_{uuid.uuid4().hex[:8]}@deleted.local'
            current_user.password_hash = 'DELETED'
            current_user.display_name = 'Deleted User'
            current_user.bio = None
            current_user.pgp_public_key = None
            current_user.pgp_fingerprint = None
            current_user.two_factor_secret = None
            current_user.two_factor_enabled = False
            current_user.is_active = False
            current_user.end_all_sessions()

            # Clear sensitive fields
            current_user.last_login_ip = None

            db.session.commit()

            # Logout user
            logout_user()
            session.clear()

            flash('Your account has been deleted. All personal data has been removed.', 'info')
            return redirect(url_for('marketplace.index'))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'Account deletion error: {e}')
            flash('Error deleting account', 'danger')

    return render_template('account/delete_account.html')


# =============================================================================
# API Endpoints
# =============================================================================

@account_bp.route('/api/check-password-strength', methods=['POST'])
@login_required
def check_password_strength():
    """AJAX endpoint to check password strength"""
    password = request.json.get('password', '')

    strength = {
        'score': 0,
        'feedback': [],
        'strong_enough': False
    }

    if len(password) >= 12:
        strength['score'] += 25
    else:
        strength['feedback'].append(f'Add {12 - len(password)} more characters')

    if any(c.isupper() for c in password):
        strength['score'] += 20
    else:
        strength['feedback'].append('Add uppercase letters')

    if any(c.islower() for c in password):
        strength['score'] += 20
    else:
        strength['feedback'].append('Add lowercase letters')

    if any(c.isdigit() for c in password):
        strength['score'] += 15
    else:
        strength['feedback'].append('Add numbers')

    if any(c in '!@#$%^&*()_+-=[]{}|;:,.<>?' for c in password):
        strength['score'] += 20
    else:
        strength['feedback'].append('Add special characters')

    strength['strong_enough'] = strength['score'] >= 80

    return jsonify(strength)


# =============================================================================
# Internal Helpers
# =============================================================================

def _keep_this_browser_logged_in():
    """
    After end_all_sessions(), log the current browser back in.

    Raising session_version invalidates every identifier issued so far -- this
    browser's included. login_user() stores the new one; regenerate() moves the
    session to a fresh id, so the old id is gone from the store as well. A
    remember-me cookie the browser already had is reissued, not dropped.

    This replaces _invalidate_other_sessions(), which scanned Redis for session
    keys and deleted those belonging to the user. It could not reach a
    remember-me cookie (that lives in the browser, not in Redis), swallowed
    every error, and only ran when an unchecked-by-default box was ticked.
    """
    had_remember = current_app.config['REMEMBER_COOKIE_NAME'] in request.cookies
    login_user(current_user._get_current_object(), remember=had_remember)
    current_app.session_interface.regenerate(session)
