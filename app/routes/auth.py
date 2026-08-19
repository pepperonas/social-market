"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Authentication Routes
Purpose: User authentication with security features
"""

import re
from datetime import datetime
from urllib.parse import urlparse

from flask import Blueprint, render_template, redirect, url_for, flash, request, session, current_app
from flask_login import login_user, logout_user, login_required, current_user
from sqlalchemy import text

from app import db, limiter
from app.models.user import User
from app.services.password_service import get_password_service

auth_bp = Blueprint('auth', __name__)

# How long a half-finished 2FA login stays valid
PENDING_2FA_TIMEOUT_SECONDS = 300


def _clear_pending_2fa():
    """Drop all pending-2FA state from the session."""
    session.pop('pending_2fa_user_id', None)
    session.pop('pending_2fa_remember', None)
    session.pop('pending_2fa_started', None)


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("20 per minute")
def login():
    """
    User login with security features:
    - Rate limiting (20 req/min)
    - Account lockout after failed attempts
    - 2FA support
    - Audit logging
    - IP tracking
    """
    if current_user.is_authenticated:
        return redirect(url_for('marketplace.index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        remember = request.form.get('remember', False)

        # Input validation
        if not username or not password:
            flash('Username and password are required', 'error')
            return render_template('auth/login.html')

        # Find user
        user = User.query.filter_by(username=username).first()

        # Get client IP
        client_ip = request.remote_addr

        if user:
            # Check if account is locked
            if user.is_account_locked():
                # Log failed attempt
                _log_auth_event(username, user.id, 'login_failed_locked', client_ip)

                flash('Account is temporarily locked due to multiple failed login attempts', 'error')
                return render_template('auth/login.html')

            # Verify password
            if user.check_password(password):
                # Check if account is active.
                # This MUST come before the 2FA branch: a deactivated account with
                # 2FA enabled would otherwise be handed to verify_2fa and log in,
                # bypassing deactivation entirely.
                if not user.is_active:
                    _log_auth_event(username, user.id, 'login_failed_inactive', client_ip)
                    flash('Account is not active', 'error')
                    return render_template('auth/login.html')

                # Check if 2FA is enabled
                if user.two_factor_enabled:
                    # Store user ID in session for 2FA verification
                    session['pending_2fa_user_id'] = str(user.id)
                    session['pending_2fa_remember'] = remember
                    session['pending_2fa_started'] = datetime.utcnow().timestamp()
                    return redirect(url_for('auth.verify_2fa'))

                # Successful login
                login_user(user, remember=remember)
                user.record_successful_login(client_ip)

                # Commit database changes
                db.session.commit()

                # Mark session as modified to ensure it's saved
                session.modified = True

                # Log successful login
                _log_auth_event(username, user.id, 'login_success', client_ip, session.get('session_id'))

                # Redirect to next page or dashboard (with open redirect prevention)
                next_page = request.args.get('next')
                if next_page and _is_safe_url(next_page):
                    return redirect(next_page)

                if user.is_vendor():
                    return redirect(url_for('vendor.dashboard'))
                elif user.is_admin():
                    return redirect(url_for('admin.dashboard'))
                else:
                    return redirect(url_for('marketplace.index'))
            else:
                # Failed login - record attempt
                user.record_failed_login(client_ip)
                _log_auth_event(username, user.id, 'login_failed_password', client_ip,
                               failure_reason='Invalid password')
        else:
            # User not found
            _log_auth_event(username, None, 'login_failed_user_not_found', client_ip,
                           failure_reason='User not found')

        flash('Invalid username or password', 'error')

    return render_template('auth/login.html')


@auth_bp.route('/verify-2fa', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def verify_2fa():
    """
    2FA verification (TOTP)
    """
    # Check if user is pending 2FA verification
    pending_user_id = session.get('pending_2fa_user_id')
    if not pending_user_id:
        return redirect(url_for('auth.login'))

    user = User.query.get(pending_user_id)
    if not user:
        session.pop('pending_2fa_user_id', None)
        return redirect(url_for('auth.login'))

    # Re-check on every step: the pending state lives in the session and the
    # account may have been deactivated or locked since the password was entered.
    if not user.is_active or user.is_account_locked():
        _clear_pending_2fa()
        _log_auth_event(user.username, user.id, 'login_failed_inactive', request.remote_addr)
        flash('Account is not active', 'error')
        return redirect(url_for('auth.login'))

    # Pending 2FA must not stay valid indefinitely
    started = session.get('pending_2fa_started')
    if started and (datetime.utcnow().timestamp() - started) > PENDING_2FA_TIMEOUT_SECONDS:
        _clear_pending_2fa()
        flash('Two-factor verification timed out. Please log in again.', 'error')
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        token = request.form.get('token', '').strip()

        if not token:
            flash('2FA token is required', 'error')
            return render_template('auth/verify_2fa.html')

        # Verify TOTP token
        if user.verify_totp(token):
            # Successful 2FA
            remember = session.get('pending_2fa_remember', False)
            login_user(user, remember=remember)
            user.record_successful_login(request.remote_addr)

            # Log successful login
            _log_auth_event(user.username, user.id, '2fa_success', request.remote_addr,
                           session.get('session_id'))

            # Clean up session
            _clear_pending_2fa()

            flash('Login successful', 'success')

            # Redirect based on role
            if user.is_vendor():
                return redirect(url_for('vendor.dashboard'))
            elif user.is_admin():
                return redirect(url_for('admin.dashboard'))
            else:
                return redirect(url_for('marketplace.index'))
        else:
            # Failed 2FA
            _log_auth_event(user.username, user.id, '2fa_failed', request.remote_addr,
                           failure_reason='Invalid token')
            flash('Invalid 2FA token', 'error')

    return render_template('auth/verify_2fa.html')


@auth_bp.route('/logout')
@login_required
def logout():
    """User logout"""
    # Log logout
    _log_auth_event(current_user.username, current_user.id, 'logout',
                   request.remote_addr, session.get('session_id'))

    logout_user()
    session.clear()
    flash('You have been logged out', 'info')
    return redirect(url_for('marketplace.index'))


@auth_bp.route('/register', methods=['GET', 'POST'])
@limiter.limit("10 per hour")
def register():
    """
    User registration with security features:
    - Rate limiting (1 req/hour per IP)
    - Password policy enforcement
    - Email verification (optional)
    - Terms acceptance
    """
    if current_user.is_authenticated:
        return redirect(url_for('marketplace.index'))

    if not current_app.config.get('ENABLE_REGISTRATION', True):
        flash('Registration is currently disabled', 'error')
        return redirect(url_for('marketplace.index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        password_confirm = request.form.get('password_confirm', '')
        role = request.form.get('role', 'buyer')
        # Coerce to a real bool: the raw form value is the string 'on', and the
        # column is Boolean -- SQLAlchemy rejects it with "Not a boolean value".
        # This never surfaced because the field-name mismatch above rejected
        # every submission before it could reach the INSERT.
        terms_accepted = request.form.get('terms_accepted') is not None

        # Validate role before echoing it back into the form
        if role not in ['buyer', 'vendor']:
            role = 'buyer'

        # Everything the user typed, so a rejected submission does not wipe the
        # form. Passwords are deliberately NOT echoed: re-rendering them would
        # put the plaintext into the HTML, the browser's back/forward cache and
        # any DOM an XSS could read. Retyping a password is a small cost; the
        # rest of the form is not.
        form_values = {
            'username': username,
            'email': email,
            'role': role,
            'terms_accepted': bool(terms_accepted),
        }

        # Collect ALL problems rather than returning on the first one, so the
        # user fixes the form once instead of playing whack-a-mole.
        errors = {}

        if not username:
            errors['username'] = 'Please choose a username.'
        elif len(username) < 3:
            errors['username'] = 'Username must be at least 3 characters.'
        elif not re.fullmatch(r'[A-Za-z0-9._-]{3,50}', username):
            errors['username'] = 'Use only letters, digits, dot, underscore or hyphen.'

        if not email:
            errors['email'] = 'Please enter an email address.'
        elif not re.fullmatch(r'[^@\s]+@[^@\s]+\.[A-Za-z]{2,}', email):
            errors['email'] = 'That does not look like an email address.'

        if not password:
            errors['password'] = 'Please choose a password.'
        else:
            violations = get_password_service().validate_policy(password)
            if violations:
                errors['password'] = ' '.join(v + '.' for v in violations)

        if password and password != password_confirm:
            errors['password_confirm'] = 'The two passwords do not match.'

        if current_app.config.get('REQUIRE_TERMS_ACCEPTANCE') and not terms_accepted:
            errors['terms_accepted'] = 'Please accept the terms to continue.'

        if role == 'vendor' and not current_app.config.get('ENABLE_VENDOR_REGISTRATION', True):
            errors['role'] = 'Vendor registration is currently disabled.'

        # Uniqueness last: no point querying if the input is malformed anyway.
        # NOTE (blue team): telling the user which of the two is taken is user
        # enumeration. It is kept because a registration form cannot avoid
        # leaking username availability anyway, and hiding it would only make
        # the form worse without making the leak go away. Rate limiting
        # (10/hour) is what actually bounds enumeration here.
        if not errors.get('username') and User.query.filter_by(username=username).first():
            errors['username'] = 'That username is already taken.'

        if not errors.get('email') and User.query.filter_by(email=email).first():
            errors['email'] = 'An account with that email already exists.'

        if errors:
            return render_template(
                'auth/register.html', errors=errors, form=form_values
            ), 400

        try:
            # Create user
            user = User(
                username=username,
                email=email,
                role=role,
                terms_accepted=terms_accepted,
                terms_version=current_app.config.get('TERMS_VERSION', '1.0')
            )

            # Set password (validates against policy)
            user.set_password(password)

            db.session.add(user)
            db.session.commit()

            # Log registration
            _log_auth_event(username, user.id, 'user_registered', request.remote_addr)

            flash('Registration successful! Please log in.', 'success')
            return redirect(url_for('auth.login'))

        except ValueError as e:
            # Password policy violation (server side is authoritative)
            return render_template(
                'auth/register.html',
                errors={'password': str(e)},
                form=form_values
            ), 400
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'Registration error: {e}')
            flash('An error occurred during registration. Please try again.', 'error')
            # Pass BOTH: the template branches on `errors`, and an undefined
            # name is a hard error under the strict Jinja used in tests.
            return render_template('auth/register.html', form=form_values, errors={}), 500

    return render_template('auth/register.html', form={}, errors={})


@auth_bp.route('/suggest-passphrase')
@limiter.limit("30 per minute")
def suggest_passphrase():
    """
    Suggest wordlist passphrases with an honest entropy figure.

    Generated server-side with `secrets`: the browser's Math.random() is not a
    CSPRNG, and a suggestion a user might actually keep must not come from a
    predictable source.
    """
    from app.services.passphrase_service import get_passphrase_service
    from flask import jsonify

    service = get_passphrase_service()
    try:
        words = int(request.args.get('words', 6))
    except (TypeError, ValueError):
        words = 6

    suggestions = service.generate_many(3, word_count=words)
    for item in suggestions:
        item['crack_time'] = service.crack_time_estimate(item['entropy_bits'])

    return jsonify({
        'suggestions': suggestions,
        'wordlist': 'BIP-39 English',
        'bits_per_word': round(service.bits_per_word(), 2),
        'note': ('Entropy counts the random words only, not the added digit/symbol. '
                 'Crack time assumes a fast hash at 1e12 guesses/s; against this '
                 "app's Argon2id it is vastly longer."),
    })


@auth_bp.route('/profile')
@login_required
def profile():
    """User profile"""
    return render_template('auth/profile.html', user=current_user)


@auth_bp.route('/profile/edit', methods=['GET', 'POST'])
@login_required
def edit_profile():
    """Edit user profile"""
    if request.method == 'POST':
        display_name = request.form.get('display_name', '').strip()
        bio = request.form.get('bio', '').strip()

        current_user.display_name = display_name
        current_user.bio = bio

        if current_user.is_vendor():
            vendor_description = request.form.get('vendor_description', '').strip()
            current_user.vendor_description = vendor_description

        db.session.commit()
        flash('Profile updated successfully', 'success')
        return redirect(url_for('auth.profile'))

    return render_template('auth/edit_profile.html')


@auth_bp.route('/profile/pgp', methods=['GET', 'POST'])
@login_required
def pgp_settings():
    """PGP key management"""
    if request.method == 'POST':
        pgp_public_key = request.form.get('pgp_public_key', '').strip()

        if not pgp_public_key:
            flash('PGP public key is required', 'error')
            return render_template('auth/pgp_settings.html')

        try:
            current_user.set_pgp_key(pgp_public_key)
            flash('PGP public key updated successfully', 'success')
            return redirect(url_for('auth.profile'))
        except ValueError as e:
            flash(str(e), 'error')

    return render_template('auth/pgp_settings.html')


@auth_bp.route('/profile/2fa/enable', methods=['GET', 'POST'])
@login_required
def enable_2fa():
    """Enable 2FA"""
    if current_user.two_factor_enabled:
        flash('2FA is already enabled', 'info')
        return redirect(url_for('auth.profile'))

    if request.method == 'POST':
        token = request.form.get('token', '').strip()

        if not token:
            flash('Verification code is required', 'error')
            return render_template('auth/enable_2fa.html')

        # Only now, after the user proved they hold the secret, is 2FA switched on
        if current_user.confirm_two_factor(token):
            flash('2FA enabled successfully', 'success')
            _log_auth_event(current_user.username, current_user.id, '2fa_enabled',
                           request.remote_addr)
            return redirect(url_for('auth.profile'))
        else:
            flash('Invalid verification code', 'error')

    # Generate QR code. This only provisions a secret -- it does not enable 2FA.
    provisioning_uri = current_user.begin_two_factor_setup()

    # Generate QR code for display
    import qrcode
    import io
    import base64

    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(provisioning_uri)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    qr_code_base64 = base64.b64encode(buf.getvalue()).decode()

    return render_template('auth/enable_2fa.html',
                          qr_code=qr_code_base64,
                          secret=current_user.two_factor_secret)


@auth_bp.route('/profile/2fa/disable', methods=['POST'])
@login_required
def disable_2fa():
    """Disable 2FA"""
    password = request.form.get('password', '')

    if not password:
        flash('Password is required to disable 2FA', 'error')
        return redirect(url_for('auth.profile'))

    if not current_user.check_password(password):
        flash('Invalid password', 'error')
        return redirect(url_for('auth.profile'))

    current_user.disable_two_factor()
    _log_auth_event(current_user.username, current_user.id, '2fa_disabled',
                   request.remote_addr)

    flash('2FA disabled successfully', 'success')
    return redirect(url_for('auth.profile'))


# =============================================================================
# PGP Key Management Routes
# =============================================================================

@auth_bp.route('/pgp-keys', methods=['GET'])
@login_required
def pgp_keys():
    """PGP key management page"""
    return render_template('auth/pgp_keys.html')


@auth_bp.route('/generate-pgp-key', methods=['POST'])
@login_required
@limiter.limit("3 per hour")  # Rate limit: 3 key generations per hour
def generate_pgp_key():
    """
    Generate RSA-4096 PGP keypair

    Security features:
    - RSA-4096 bit keys (industry standard for high security)
    - Strong passphrase validation (minimum 12 characters)
    - Rate limiting (3 generations per hour)
    - Secure key generation with python-gnupg
    - Keys not stored on server (user must download)
    """
    from app.services.pgp_service import PGPService

    try:
        # Get form data
        key_name = request.form.get('key_name', '').strip()
        key_email = request.form.get('key_email', '').strip()
        passphrase = request.form.get('passphrase', '')
        passphrase_confirm = request.form.get('passphrase_confirm', '')
        key_length = int(request.form.get('key_length', 4096))
        expire_years = request.form.get('expire_years', '0')

        # Validation
        if not key_name or len(key_name) < 3:
            flash('Name must be at least 3 characters', 'danger')
            return redirect(url_for('auth.pgp_keys'))

        if not key_email or '@' not in key_email:
            flash('Valid email address required', 'danger')
            return redirect(url_for('auth.pgp_keys'))

        if passphrase != passphrase_confirm:
            flash('Passphrases do not match', 'danger')
            return redirect(url_for('auth.pgp_keys'))

        # Validate passphrase strength
        pgp_service = PGPService()
        passphrase_check = pgp_service.validate_passphrase_strength(passphrase)

        if not passphrase_check['valid']:
            flash(f"Passphrase is too weak: {', '.join(passphrase_check['feedback'])}", 'danger')
            return redirect(url_for('auth.pgp_keys'))

        # Validate key length
        if key_length not in [2048, 3072, 4096]:
            flash('Invalid key length. Choose 2048, 3072, or 4096 bits', 'danger')
            return redirect(url_for('auth.pgp_keys'))

        # Convert expiration years to format
        expire_date = '0'  # Never expire
        if expire_years and expire_years != '0':
            expire_date = f'{expire_years}y'

        # Generate keypair
        current_app.logger.info(f'Generating RSA-{key_length} keypair for user {current_user.username}')

        result = pgp_service.generate_keypair(
            name=key_name,
            email=key_email,
            passphrase=passphrase,
            key_length=key_length,
            expire_date=expire_date,
            comment=f'Generated by Social Market for {current_user.username}'
        )

        if not result['success']:
            flash(f"Key generation failed: {result.get('error', 'Unknown error')}", 'danger')
            return redirect(url_for('auth.pgp_keys'))

        # Log key generation event (general auth log)
        _log_auth_event(
            current_user.username,
            current_user.id,
            'pgp_key_generated',
            request.remote_addr
        )

        # Log PGP-specific audit event
        from app.services.audit_service import log_pgp_key_event
        log_pgp_key_event(
            user_id=current_user.id,
            action='pgp_key_generated',
            key_fingerprint=result['fingerprint'],
            created_by='user',
            source='generated',
            metadata={
                'username': current_user.username,
                'email': key_email,
                'key_length': str(key_length),
                'algorithm': 'RSA',
                'expire_date': expire_date
            }
        )

        current_app.logger.info(f'Successfully generated keypair for {current_user.username}: {result["fingerprint"]}')

        # Return keys as downloadable JSON (not stored on server!)
        response_data = {
            'success': True,
            'public_key': result['public_key'],
            'private_key': result['private_key'],
            'fingerprint': result['fingerprint'],
            'keyid': result['keyid'],
            'key_length': result['key_length'],
            'created_at': result['created_at'],
            'warning': 'Save these keys securely! They will not be shown again.'
        }

        # For web UI, store temporarily in session (will be cleared after download)
        session['generated_keys'] = response_data
        session.modified = True

        flash(f'Successfully generated RSA-{key_length} keypair! Download your keys now.', 'success')
        return redirect(url_for('auth.download_keys'))

    except ValueError as e:
        flash(f'Invalid input: {str(e)}', 'danger')
        return redirect(url_for('auth.pgp_keys'))
    except Exception as e:
        current_app.logger.error(f'Key generation error: {str(e)}')
        flash('An error occurred during key generation. Please try again.', 'danger')
        return redirect(url_for('auth.pgp_keys'))


@auth_bp.route('/download-keys', methods=['GET'])
@login_required
def download_keys():
    """Display generated keys for download"""
    generated_keys = session.get('generated_keys')

    if not generated_keys:
        flash('No keys available for download', 'warning')
        return redirect(url_for('auth.pgp_keys'))

    return render_template('auth/download_keys.html', keys=generated_keys)


@auth_bp.route('/download-key/<key_type>', methods=['GET'])
@login_required
def download_key_file(key_type):
    """Download key as file"""
    from flask import make_response

    generated_keys = session.get('generated_keys')

    if not generated_keys:
        flash('No keys available for download', 'warning')
        return redirect(url_for('auth.pgp_keys'))

    if key_type not in ['public', 'private', 'both']:
        flash('Invalid key type', 'danger')
        return redirect(url_for('auth.download_keys'))

    # Prepare file content
    if key_type == 'public':
        content = generated_keys['public_key']
        filename = f'public_key_{generated_keys["keyid"]}.asc'
        mime_type = 'application/pgp-keys'
    elif key_type == 'private':
        content = generated_keys['private_key']
        filename = f'private_key_{generated_keys["keyid"]}.asc'
        mime_type = 'application/pgp-keys'
    else:  # both
        content = f"{generated_keys['public_key']}\n\n{generated_keys['private_key']}"
        filename = f'keypair_{generated_keys["keyid"]}.asc'
        mime_type = 'application/pgp-keys'

    # Create response
    response = make_response(content)
    response.headers['Content-Type'] = mime_type
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'

    return response


@auth_bp.route('/clear-generated-keys', methods=['POST'])
@login_required
def clear_generated_keys():
    """Clear generated keys from session"""
    if 'generated_keys' in session:
        del session['generated_keys']
        session.modified = True
        flash('Generated keys cleared from session', 'info')

    return redirect(url_for('auth.pgp_keys'))


@auth_bp.route('/validate-passphrase', methods=['POST'])
@login_required
def validate_passphrase():
    """AJAX endpoint to validate passphrase strength"""
    from flask import jsonify
    from app.services.pgp_service import PGPService

    passphrase = request.json.get('passphrase', '')

    pgp_service = PGPService()
    result = pgp_service.validate_passphrase_strength(passphrase)

    return jsonify(result)


# =============================================================================
# Helper Functions
# =============================================================================

def _is_safe_url(target):
    """
    Validate redirect URL to prevent open redirect attacks.

    Only allows relative URLs on the same host.

    Args:
        target: URL to validate

    Returns:
        bool: True if URL is safe to redirect to
    """
    if not target:
        return False

    # Browsers normalise backslashes to forward slashes, so "/\\evil.com" and
    # "/\evil.com" leave the site even though urlparse reports no netloc.
    if '\\' in target:
        return False

    parsed = urlparse(target)

    # Allow only relative paths (no scheme/netloc) or same-host URLs
    if parsed.netloc:
        host = urlparse(request.host_url)
        return parsed.scheme in ('http', 'https') and parsed.netloc == host.netloc

    # A relative target must be rooted at a single slash; "//evil.com" is
    # protocol-relative and would also leave the site.
    return target.startswith('/') and not target.startswith('//')


def _log_auth_event(username, user_id, action, ip_address, session_id=None, failure_reason=None):
    """
    Log authentication event to database

    Args:
        username: Username
        user_id: User ID (if known)
        action: Action type
        ip_address: Client IP address
        session_id: Session ID (optional)
        failure_reason: Failure reason (optional)
    """
    try:
        db.session.execute(
            text(
                "SELECT log_auth_event(:username, :user_id, :action, :ip_address, "
                ":user_agent, :session_id, :failure_reason, NULL)"
            ),
            {
                'username': username,
                'user_id': user_id,
                'action': action,
                'ip_address': ip_address,
                'user_agent': request.headers.get('User-Agent', ''),
                'session_id': session_id,
                'failure_reason': failure_reason
            }
        )
        db.session.commit()
    except Exception as e:
        current_app.logger.error(f'Failed to log auth event: {e}')
        db.session.rollback()
