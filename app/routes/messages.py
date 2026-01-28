"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Messages Routes - Placeholder
Purpose: PGP-encrypted messaging
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

messages_bp = Blueprint('messages', __name__)


@messages_bp.route('/')
@login_required
def inbox():
    """Message inbox"""
    return render_template('messages/inbox.html')


@messages_bp.route('/thread/<uuid:thread_id>')
@login_required
def thread(thread_id):
    """Message thread"""
    return render_template('messages/thread.html')


@messages_bp.route('/new/<uuid:recipient_id>', methods=['GET', 'POST'])
@login_required
def new_thread(recipient_id):
    """Start new message thread"""
    from app.models.user import User

    # Get recipient
    recipient = User.query.get_or_404(recipient_id)

    # Check if user is not messaging themselves
    if recipient_id == current_user.id:
        flash('You cannot send messages to yourself', 'warning')
        return redirect(url_for('messages.inbox'))

    if request.method == 'POST':
        # TODO: Implement message sending
        flash('Message functionality coming soon', 'info')
        return redirect(url_for('messages.inbox'))

    return render_template('messages/new_thread.html', recipient=recipient)
