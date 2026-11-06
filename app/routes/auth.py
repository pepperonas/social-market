"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Authentication Routes
Purpose: User authentication with security features
"""

import re
from urllib.parse import urlparse

from flask import Blueprint, render_template, redirect, url_for, flash, request, session, current_app
from flask_login import login_user, logout_user, login_required, current_user
from sqlalchemy import text

from app import db, limiter
from app.models.user import User
from app.services.password_service import get_password_service
from app.timeutil import utcnow

auth_bp = Blueprint('auth', __name__)

# How long a half-finished 2FA login stays valid
PENDING_2FA_TIMEOUT_SECONDS = 300


_DUMMY_HASH = None

# One message for every failed login -- unknown user, wrong password, locked
# account -- so the response never tells which of them it was. The lockout is
# mentioned in general terms, for everybody, so a locked-out owner is not left
# guessing.
GENERIC_LOGIN_FAILURE = ('Invalid username or password. After repeated failed attempts, '
                         'sign-in is paused for a while.')


def burn_password_check(password):
    """
    Spend the same Argon2 work as a real password check, for a user that does
    not exist.

    Without it, "unknown username" returned in a few milliseconds while "wrong
    password" paid for an Argon2id verification -- a difference a stopwatch can
    read across the network, which turns the login form into a way to test
    whether an account exists. The result is ignored on purpose.
    """
    global _DUMMY_HASH
    service = get_password_service()
    if _DUMMY_HASH is None:
        import secrets
        _DUMMY_HASH = service.hash_password(secrets.token_urlsafe(16))
    service.verify_password(password, _DUMMY_HASH)


def _start_authenticated_session(user, remember=False):
    """
    Log the user in on a fresh session id.

    login_user() keeps whatever session id the browser arrived with. Anyone who
    managed to plant that id beforehand (a shared machine, a cookie set by a
    sibling subdomain) would share the authenticated session afterwards:
    session fixation. regenerate() moves the data to a new id and deletes the old
    one in the store.
    """
    login_user(user, remember=remember)
    current_app.session_interface.regenerate(session)


def reauth_failed(message, back_to):
    """
    A logged-in user failed to confirm their password or 2FA code.

    These forms (turn off 2FA, change password, delete account) re-check secrets
    for someone who already holds a session -- which is exactly the position of
    someone who stole one. Without counting, the form was a password and code
    guessing machine behind the login, outside the lockout. Failures now count
    towards the same lockout as the login; once locked, the session ends.
    """
    user = current_user._get_current_object()
    user.record_failed_login(request.remote_addr)
    _log_auth_event(user.username, user.id, 'reauth_failed', request.remote_addr,
                    failure_reason=message)
    if user.is_account_locked():
        return reauth_locked()
    flash(message, 'error')
    return redirect(back_to)


def reauth_locked():
    """
    End EVERY session of a user whose re-authentication tripped the lockout.

    The first version only logged out the session that made the attempt.
    Someone guessing with a stolen session can hold several, or a remember-me
    cookie, and simply continue in the next one. Bumping session_version
    revokes all of them at once.

    Deliberately not done for a lock caused at the *login form*: anybody can
    trip that with five wrong guesses at a username, and ending the owner's
    sessions everywhere would hand them a denial-of-service button. Here the
    attempts came from inside an authenticated session -- that session is the
    suspect.
    """
    user = current_user._get_current_object()
    user.end_all_sessions()
    db.session.commit()
    logout_user()
    session.clear()
    flash(GENERIC_LOGIN_FAILURE, 'error')
    return redirect(url_for('auth.login'))


def reauth_allowed():
    """
    False while the account is locked -- check BEFORE verifying any secret.

    record_failed_login() counts, but a check that runs anyway still answers.
    Without this gate a correct guess made during the lock would succeed,
    exactly the oracle the login form had to be cured of.
    """
    return not current_user.is_account_locked()


def reauth_refused(back_to):
    """
    The account is already locked: refuse, change nothing, revoke nothing.

    The first version answered with reauth_locked(), i.e. ended every session.
    But a lock can come from the LOGIN form, where anybody can produce one with
    five wrong guesses at a username. The owner then opened "change password"
    and was logged out everywhere -- the denial-of-service button that
    reauth_locked() was explicitly meant not to be. Revoking all sessions stays
    reserved for a lock this session tripped itself (reauth_failed).
    """
    flash('Sign-in is paused after repeated failed attempts. Try again later.', 'error')
    return redirect(back_to)


def _clear_pending_2fa():
    """Drop all pending-2FA state from the session."""
    session.pop('pending_2fa_user_id', None)
    session.pop('pending_2fa_remember', None)
    session.pop('pending_2fa_started', None)
    session.pop('pending_2fa_next', None)


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
        # Case-insensitive, matching registration (see register()).
        user = User.query.filter(db.func.lower(User.username) == username.lower()).first()

        # Get client IP
        client_ip = request.remote_addr

        if user:
            # While locked, the password is not checked at all, and the answer is
            # the same generic message as for any failure.
            #
            # The lock message used to come first and named the lock outright,
            # which confirmed that the username exists. The first fix moved it
            # behind the password check and showed it only for a correct
            # password -- which turned it into a password oracle: attempts made
            # during the lock are not counted, so an attacker could keep guessing
            # through the lockout and be told which guess was right. A lock that
            # still answers "correct" protects nothing.
            if user.is_account_locked():
                burn_password_check(password)  # same Argon2 cost as a real check
                _log_auth_event(username, user.id, 'login_failed_locked', client_ip)
                flash(GENERIC_LOGIN_FAILURE, 'error')
                return render_template('auth/login.html')

            password_ok = user.check_password(password)

            # Verify password
            if password_ok:
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
                    # Carry `next` across the 2FA step; it used to be dropped there.
                    next_page = request.args.get('next')
                    if next_page and _is_safe_url(next_page):
                        session['pending_2fa_next'] = next_page
                    session['pending_2fa_started'] = utcnow().timestamp()
                    return redirect(url_for('auth.verify_2fa'))

                # Successful login
                _start_authenticated_session(user, remember=remember)
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
            # User not found -- still pay for a hash check (see burn_password_check)
            burn_password_check(password)
            _log_auth_event(username, None, 'login_failed_user_not_found', client_ip,
                           failure_reason='User not found')

        flash(GENERIC_LOGIN_FAILURE, 'error')

    return render_template('auth/login.html')


@auth_bp.route('/verify-2fa', methods=['GET', 'POST'])
@limiter.limit("5 per minute", methods=['POST'])
def verify_2fa():
    """
    2FA verification (TOTP)
    """
    # Check if user is pending 2FA verification
    pending_user_id = session.get('pending_2fa_user_id')
    if not pending_user_id:
        return redirect(url_for('auth.login'))

    user = db.session.get(User, pending_user_id)
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
    if started and (utcnow().timestamp() - started) > PENDING_2FA_TIMEOUT_SECONDS:
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
            next_page = session.get('pending_2fa_next')  # read before the cleanup below
            _start_authenticated_session(user, remember=remember)
            user.record_successful_login(request.remote_addr)

            # Log successful login
            _log_auth_event(user.username, user.id, '2fa_success', request.remote_addr,
                           session.get('session_id'))

            # Clean up session
            _clear_pending_2fa()

            flash('Login successful', 'success')

            if next_page and _is_safe_url(next_page):
                return redirect(next_page)

            # Redirect based on role
            if user.is_vendor():
                return redirect(url_for('vendor.dashboard'))
            elif user.is_admin():
                return redirect(url_for('admin.dashboard'))
            else:
                return redirect(url_for('marketplace.index'))
        else:
            # Failed 2FA. Counts towards the same lockout as a wrong password:
            # the password is already known at this point, so the code is the
            # only thing left to guess, and a per-IP rate limit alone does not
            # stop an attacker who spreads the attempts over many addresses.
            user.record_failed_login(request.remote_addr)
            _log_auth_event(user.username, user.id, '2fa_failed', request.remote_addr,
                           failure_reason='Invalid token')
            if user.is_account_locked():
                _clear_pending_2fa()
                flash(GENERIC_LOGIN_FAILURE, 'error')
                return redirect(url_for('auth.login'))
            flash('Invalid 2FA token', 'error')

    return render_template('auth/verify_2fa.html')


@auth_bp.route('/logout', methods=['POST'])
def logout():
    """
    Log out -- POST only, CSRF-protected.

    It was a GET link. Any page on any site could log a visitor out with an
    <img src=".../auth/logout"> (SameSite=Lax still sends cookies on top-level
    GET navigations, and an image needs none of that for the request to land).
    It also required login, so the "Cancel" link on the 2FA page -- where the
    user is not logged in yet -- bounced to the login page with the half-done
    2FA state still in the session. Logging out now always clears the session.
    """
    if current_user.is_authenticated:
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
        # Compared case-insensitively. "Admin" could be registered next to
        # "admin" -- a ready-made impersonation in every message thread and
        # order list -- and "Bob@x" next to "bob@x".
        if not errors.get('username') and User.query.filter(
                db.func.lower(User.username) == username.lower()).first():
            errors['username'] = 'That username is already taken.'

        if not errors.get('email') and User.query.filter(
                db.func.lower(User.email) == email.lower()).first():
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


# display_name is VARCHAR(100); the two text fields are TEXT and get a sane cap.
PROFILE_LIMITS = {'display_name': 100, 'bio': 2000, 'vendor_description': 5000}


@auth_bp.route('/profile/edit', methods=['GET', 'POST'])
@login_required
def edit_profile():
    """Edit user profile"""
    # The template used to post email and password fields instead of these, so
    # every save blanked display name and bio and reported success. The field
    # names are now pinned against the template in tests.
    if request.method == 'POST':
        display_name = request.form.get('display_name', '').strip()
        bio = request.form.get('bio', '').strip()
        vendor_description = request.form.get('vendor_description', '').strip()

        errors = []
        if len(display_name) > PROFILE_LIMITS['display_name']:
            errors.append(f"Display name: at most {PROFILE_LIMITS['display_name']} characters")
        if len(bio) > PROFILE_LIMITS['bio']:
            errors.append(f"Bio: at most {PROFILE_LIMITS['bio']} characters")
        if len(vendor_description) > PROFILE_LIMITS['vendor_description']:
            errors.append(f"Shop description: at most {PROFILE_LIMITS['vendor_description']} characters")
        if errors:
            for message in errors:
                flash(message, 'error')
            return render_template('auth/edit_profile.html', limits=PROFILE_LIMITS)

        current_user.display_name = display_name or None
        current_user.bio = bio or None

        if current_user.is_vendor():
            current_user.vendor_description = vendor_description or None

        db.session.commit()
        flash('Profile updated successfully', 'success')
        return redirect(url_for('auth.profile'))

    return render_template('auth/edit_profile.html', limits=PROFILE_LIMITS)


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
    # A data URI, not bare base64: <img src="iVBOR..."> is a relative URL to a
    # file that does not exist, and the QR code never appeared. (The CSP already
    # allows img-src data:.)
    qr_code_uri = 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()

    return render_template('auth/enable_2fa.html',
                          qr_code=qr_code_uri,
                          secret=current_user.two_factor_secret)


@auth_bp.route('/profile/2fa/disable', methods=['POST'])
@login_required
@limiter.limit("5 per hour", methods=['POST'])
def disable_2fa():
    """Disable 2FA"""
    password = request.form.get('password', '')

    if not reauth_allowed():
        return reauth_refused(url_for('account.security_settings'))

    if not password:
        flash('Password is required to disable 2FA', 'error')
        return redirect(url_for('auth.profile'))

    # Password alone is exactly the single factor that 2FA exists to back up.
    # Someone who has only the password must not be able to remove the second one.
    if not current_user.check_password(password) or \
            not current_user.verify_totp(request.form.get('token', '').strip()):
        return reauth_failed(
            'Password or code incorrect', url_for('account.security_settings'))

    current_user.disable_two_factor()
    _log_auth_event(current_user.username, current_user.id, '2fa_disabled',
                   request.remote_addr)

    flash('2FA disabled successfully', 'success')
    return redirect(url_for('account.security_settings'))


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

    if key_type in ('private', 'both') and 'private_key' not in generated_keys:
        flash('The private key was already downloaded and removed from the server', 'warning')
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

    # The private key leaves the server with this download. Until now it stayed
    # in the (Redis-backed) session until the session expired, while the page
    # promised it was "not stored on the server". Keep only the public half.
    if key_type in ('private', 'both'):
        remaining = {k: v for k, v in generated_keys.items() if k != 'private_key'}
        session['generated_keys'] = remaining
        session.modified = True

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
