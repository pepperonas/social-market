"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Messages Routes - PGP-Encrypted Messaging
Purpose: Secure communication between users with mandatory encryption
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from sqlalchemy import or_, and_
import uuid

from app import db, limiter
from app.models.message import Message, MessageThread
from app.models.user import User
from app.services.pgp_service import PGPService

messages_bp = Blueprint('messages', __name__)


@messages_bp.route('/')
@login_required
def inbox():
    """
    Message inbox - show all threads for current user

    Returns threads where user is participant_1 or participant_2
    Supports Admin, Vendor, and Buyer communications
    """
    # Get all threads where user is a participant
    threads = MessageThread.query.filter(
        or_(
            MessageThread.participant_1_id == current_user.id,
            MessageThread.participant_2_id == current_user.id
        )
    ).order_by(MessageThread.last_message_at.desc()).all()

    # Calculate unread counts for each thread
    threads_data = []
    for thread in threads:
        other_participant = thread.get_participant(current_user.id)
        unread_count = thread.get_unread_count(current_user.id)

        threads_data.append({
            'thread': thread,
            'participant': other_participant,
            'unread_count': unread_count,
            'last_message': thread.messages.first() if thread.messages.count() > 0 else None
        })

    return render_template('messages/inbox.html', threads=threads_data)


@messages_bp.route('/thread/<uuid:thread_id>')
@login_required
def thread(thread_id):
    """
    View message thread with decryption support

    Security:
    - Only participants can view thread
    - Messages are decrypted client-side (user provides private key)
    - No plaintext messages in database
    """
    thread = MessageThread.query.get_or_404(thread_id)

    # Verify user is participant
    if not thread.is_participant(current_user.id):
        flash('You do not have access to this thread', 'danger')
        return redirect(url_for('messages.inbox'))

    # Get other participant
    other_participant = thread.get_participant(current_user.id)

    # Get all messages in thread (encrypted)
    messages = thread.messages.filter(
        or_(
            and_(Message.sender_id == current_user.id, Message.is_deleted_by_sender == False),
            and_(Message.recipient_id == current_user.id, Message.is_deleted_by_recipient == False)
        )
    ).order_by(Message.created_at.asc()).all()

    # Mark messages as read
    thread.mark_all_read(current_user.id)

    return render_template('messages/thread.html',
                         thread=thread,
                         other_participant=other_participant,
                         messages=messages)


@messages_bp.route('/new/<uuid:recipient_id>', methods=['GET', 'POST'])
@login_required
@limiter.limit("10 per hour")
def new_thread(recipient_id):
    """
    Start new message thread or send message to existing thread

    Security Features:
    - Mandatory PGP encryption (no plaintext allowed)
    - Two modes:
      1. Auto-encrypt: System encrypts with recipient's public key
      2. Manual: User provides pre-encrypted message
    - Rate limited to prevent spam
    """
    # Get recipient
    recipient = User.query.get_or_404(recipient_id)

    # Prevent self-messaging
    if str(recipient_id) == str(current_user.id):
        flash('You cannot send messages to yourself', 'warning')
        return redirect(url_for('messages.inbox'))

    # Check if recipient has PGP key (required for auto-encryption)
    has_recipient_key = recipient.pgp_public_key is not None

    if request.method == 'POST':
        message_content = request.form.get('message', '').strip()
        encryption_mode = request.form.get('encryption_mode', 'auto')  # 'auto' or 'manual'
        subject = request.form.get('subject', '').strip()

        # Validation
        if not message_content:
            flash('Message cannot be empty', 'danger')
            return redirect(url_for('messages.new_thread', recipient_id=recipient_id))

        if len(message_content) > 10000:
            flash('Message is too long (max 10,000 characters)', 'danger')
            return redirect(url_for('messages.new_thread', recipient_id=recipient_id))

        try:
            # Find or create thread
            thread = MessageThread.find_or_create_thread(
                participant_1_id=current_user.id,
                participant_2_id=recipient_id,
                subject=subject if subject else None
            )

            # Create message
            message = Message(
                id=uuid.uuid4(),
                thread_id=thread.id,
                sender_id=current_user.id,
                recipient_id=recipient_id
            )

            # Encrypt message based on mode
            if encryption_mode == 'auto':
                # Auto-encryption mode: System encrypts with recipient's public key
                if not has_recipient_key:
                    flash('Recipient does not have a PGP public key. Cannot auto-encrypt.', 'danger')
                    return redirect(url_for('messages.new_thread', recipient_id=recipient_id))

                # Validate message is plaintext (not already encrypted)
                if message_content.startswith('-----BEGIN PGP MESSAGE-----'):
                    flash('Message appears to be already encrypted. Use manual mode for pre-encrypted messages.', 'warning')
                    return redirect(url_for('messages.new_thread', recipient_id=recipient_id))

                # Encrypt with PGP service
                pgp_service = PGPService(use_temp_home=True)
                success, result = pgp_service.encrypt_message(
                    message=message_content,
                    recipient_public_key=recipient.pgp_public_key
                )

                if not success:
                    flash(f'Encryption failed: {result}', 'danger')
                    return redirect(url_for('messages.new_thread', recipient_id=recipient_id))

                # Store encrypted message
                message.content_encrypted = result.encode('utf-8')
                message.is_encrypted = True

            elif encryption_mode == 'manual':
                # Manual mode: User provides pre-encrypted message
                # Validate it's actually encrypted
                if not message_content.startswith('-----BEGIN PGP MESSAGE-----'):
                    flash('Manual mode requires PGP-encrypted message (must start with -----BEGIN PGP MESSAGE-----)', 'danger')
                    return redirect(url_for('messages.new_thread', recipient_id=recipient_id))

                if not message_content.rstrip().endswith('-----END PGP MESSAGE-----'):
                    flash('Invalid PGP message format (must end with -----END PGP MESSAGE-----)', 'danger')
                    return redirect(url_for('messages.new_thread', recipient_id=recipient_id))

                # Store pre-encrypted message
                message.content_encrypted = message_content.encode('utf-8')
                message.is_encrypted = True

            else:
                flash('Invalid encryption mode', 'danger')
                return redirect(url_for('messages.new_thread', recipient_id=recipient_id))

            # CRITICAL: Verify message is encrypted before saving
            if not message.is_encrypted:
                raise ValueError('SECURITY: Attempted to send unencrypted message')

            # Verify encrypted content exists
            if not message.content_encrypted:
                raise ValueError('SECURITY: No encrypted content')

            # Save message
            db.session.add(message)
            db.session.commit()

            flash('Message sent successfully (encrypted)', 'success')
            return redirect(url_for('messages.thread', thread_id=thread.id))

        except Exception as e:
            db.session.rollback()
            flash(f'Error sending message: {str(e)}', 'danger')
            return redirect(url_for('messages.new_thread', recipient_id=recipient_id))

    return render_template('messages/new_thread.html',
                         recipient=recipient,
                         has_recipient_key=has_recipient_key)


@messages_bp.route('/send/<uuid:thread_id>', methods=['POST'])
@login_required
@limiter.limit("20 per hour")
def send_message(thread_id):
    """
    Send message in existing thread

    Same security as new_thread - mandatory encryption
    """
    thread = MessageThread.query.get_or_404(thread_id)

    # Verify user is participant
    if not thread.is_participant(current_user.id):
        flash('You do not have access to this thread', 'danger')
        return redirect(url_for('messages.inbox'))

    # Get recipient (other participant)
    recipient = thread.get_participant(current_user.id)

    message_content = request.form.get('message', '').strip()
    encryption_mode = request.form.get('encryption_mode', 'auto')

    # Validation
    if not message_content:
        flash('Message cannot be empty', 'danger')
        return redirect(url_for('messages.thread', thread_id=thread_id))

    if len(message_content) > 10000:
        flash('Message is too long (max 10,000 characters)', 'danger')
        return redirect(url_for('messages.thread', thread_id=thread_id))

    try:
        # Create message
        message = Message(
            id=uuid.uuid4(),
            thread_id=thread.id,
            sender_id=current_user.id,
            recipient_id=recipient.id
        )

        # Encrypt message based on mode
        if encryption_mode == 'auto':
            # Auto-encryption mode
            if not recipient.pgp_public_key:
                flash('Recipient does not have a PGP public key. Cannot auto-encrypt.', 'danger')
                return redirect(url_for('messages.thread', thread_id=thread_id))

            # Validate not already encrypted
            if message_content.startswith('-----BEGIN PGP MESSAGE-----'):
                flash('Message appears to be already encrypted. Use manual mode.', 'warning')
                return redirect(url_for('messages.thread', thread_id=thread_id))

            # Encrypt
            pgp_service = PGPService(use_temp_home=True)
            success, result = pgp_service.encrypt_message(
                message=message_content,
                recipient_public_key=recipient.pgp_public_key
            )

            if not success:
                flash(f'Encryption failed: {result}', 'danger')
                return redirect(url_for('messages.thread', thread_id=thread_id))

            message.content_encrypted = result.encode('utf-8')
            message.is_encrypted = True

        elif encryption_mode == 'manual':
            # Manual mode: Validate PGP format
            if not message_content.startswith('-----BEGIN PGP MESSAGE-----'):
                flash('Manual mode requires PGP-encrypted message', 'danger')
                return redirect(url_for('messages.thread', thread_id=thread_id))

            if not message_content.rstrip().endswith('-----END PGP MESSAGE-----'):
                flash('Invalid PGP message format', 'danger')
                return redirect(url_for('messages.thread', thread_id=thread_id))

            message.content_encrypted = message_content.encode('utf-8')
            message.is_encrypted = True

        else:
            flash('Invalid encryption mode', 'danger')
            return redirect(url_for('messages.thread', thread_id=thread_id))

        # CRITICAL: Verify encryption before saving
        if not message.is_encrypted or not message.content_encrypted:
            raise ValueError('SECURITY: Attempted to send unencrypted message')

        # Save message
        db.session.add(message)
        db.session.commit()

        flash('Message sent successfully (encrypted)', 'success')
        return redirect(url_for('messages.thread', thread_id=thread_id))

    except Exception as e:
        db.session.rollback()
        flash(f'Error sending message: {str(e)}', 'danger')
        return redirect(url_for('messages.thread', thread_id=thread_id))


@messages_bp.route('/decrypt', methods=['POST'])
@login_required
def decrypt_message():
    """
    AJAX endpoint to decrypt message client-side

    Security:
    - User must provide their private key and passphrase
    - Decryption happens server-side but key is not stored
    - Only recipient can decrypt
    """
    message_id = request.json.get('message_id')
    private_key = request.json.get('private_key')
    passphrase = request.json.get('passphrase', '')

    if not message_id or not private_key:
        return jsonify({'success': False, 'error': 'Missing required fields'}), 400

    # Get message
    message = Message.query.get_or_404(message_id)

    # Verify user is recipient
    if str(message.recipient_id) != str(current_user.id):
        return jsonify({'success': False, 'error': 'You are not the recipient'}), 403

    # Decrypt message
    try:
        pgp_service = PGPService(use_temp_home=True)
        encrypted_content = message.content_encrypted.decode('utf-8')

        success, result = pgp_service.decrypt_message(
            encrypted_message=encrypted_content,
            private_key=private_key,
            passphrase=passphrase
        )

        if not success:
            return jsonify({'success': False, 'error': f'Decryption failed: {result}'}), 400

        return jsonify({'success': True, 'decrypted_message': result})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@messages_bp.route('/delete/<uuid:message_id>', methods=['POST'])
@login_required
def delete_message(message_id):
    """
    Delete message for current user

    Security:
    - Only sender or recipient can delete
    - Deletion is per-user (soft delete)
    - Message deleted from DB only when both users delete
    """
    message = Message.query.get_or_404(message_id)

    # Verify user has access
    if not (str(message.sender_id) == str(current_user.id) or
            str(message.recipient_id) == str(current_user.id)):
        flash('You do not have access to this message', 'danger')
        return redirect(url_for('messages.inbox'))

    try:
        thread_id = message.thread_id
        message.delete_for_user(current_user.id)

        flash('Message deleted', 'success')
        return redirect(url_for('messages.thread', thread_id=thread_id))

    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting message: {str(e)}', 'danger')
        return redirect(url_for('messages.inbox'))


@messages_bp.route('/admin/users', methods=['GET'])
@login_required
def admin_user_list():
    """
    Admin endpoint: List all users for messaging

    Security:
    - Only admins can access
    - Shows all users to enable admin support
    """
    if current_user.role != 'admin':
        flash('Access denied', 'danger')
        return redirect(url_for('messages.inbox'))

    # Get all users except current admin
    users = User.query.filter(
        User.id != current_user.id,
        User.is_active == True
    ).order_by(User.username).all()

    return render_template('messages/admin_users.html', users=users)
