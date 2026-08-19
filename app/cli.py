"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Flask CLI Commands
Purpose: Management commands for initialization and maintenance
"""

import click
from flask import current_app
from app import db
from app.models.user import User
from app.models.product import ProductCategory
import secrets


@click.command('init-db')
def init_db():
    """Initialize database with default data"""
    click.echo('Initializing database...')

    # Create tables
    db.create_all()
    click.echo('✓ Tables created')

    # Create default categories (LEGAL ONLY)
    categories = [
        {'name': 'Books', 'slug': 'books', 'description': 'Educational books and publications'},
        {'name': 'Art', 'slug': 'art', 'description': 'Digital and physical artwork'},
        {'name': 'Digital Goods', 'slug': 'digital-goods', 'description': 'Software, courses, ebooks'},
        {'name': 'Services', 'slug': 'services', 'description': 'Professional services'},
    ]

    for cat_data in categories:
        if not ProductCategory.query.filter_by(slug=cat_data['slug']).first():
            category = ProductCategory(**cat_data)
            db.session.add(category)
            click.echo(f'✓ Created category: {cat_data["name"]}')

    db.session.commit()
    click.echo('✓ Database initialized successfully')


@click.command('init-admin')
def init_admin():
    """Create default admin user"""
    click.echo('Creating admin user...')

    # Check if admin exists
    admin = User.query.filter_by(username='admin').first()
    if admin:
        click.echo('! Admin user already exists')
        return

    # Get credentials from config or use defaults
    admin_username = current_app.config.get('ADMIN_USERNAME', 'admin')
    admin_password = current_app.config.get('ADMIN_PASSWORD', 'ChangeMe123!')
    admin_email = current_app.config.get('ADMIN_EMAIL', 'admin@localhost')

    # Create admin user
    admin = User(
        username=admin_username,
        email=admin_email,
        role='admin',
        is_active=True,
        is_verified=True,
        terms_accepted=True
    )

    admin.set_password(admin_password)

    db.session.add(admin)
    db.session.commit()

    click.echo('✓ Admin user created')
    click.echo(f'  Username: {admin_username}')
    click.echo(f'  Password: {admin_password}')
    click.echo('  ⚠️  CHANGE PASSWORD IMMEDIATELY!')


@click.command('create-user')
@click.option('--username', prompt=True)
@click.option('--email', prompt=True)
@click.option('--password', prompt=True, hide_input=True, confirmation_prompt=True)
@click.option('--role', type=click.Choice(['buyer', 'vendor', 'admin']), default='buyer')
def create_user(username, email, password, role):
    """Create a new user"""
    # Check if user exists
    if User.query.filter_by(username=username).first():
        click.echo(f'✗ User {username} already exists')
        return

    if User.query.filter_by(email=email).first():
        click.echo(f'✗ Email {email} already registered')
        return

    # Create user
    user = User(
        username=username,
        email=email,
        role=role,
        is_active=True,
        is_verified=True,
        terms_accepted=True
    )

    try:
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        click.echo(f'✓ User {username} created successfully')
    except ValueError as e:
        click.echo(f'✗ Error: {e}')


@click.command('reset-password')
@click.option('--username', prompt=True)
@click.option('--password', prompt=True, hide_input=True, confirmation_prompt=True)
def reset_password(username, password):
    """Reset user password"""
    user = User.query.filter_by(username=username).first()

    if not user:
        click.echo(f'✗ User {username} not found')
        return

    try:
        user.set_password(password)
        user.failed_login_attempts = 0
        user.account_locked_until = None
        db.session.commit()
        click.echo(f'✓ Password reset for {username}')
    except ValueError as e:
        click.echo(f'✗ Error: {e}')


@click.command('generate-secret')
@click.option('--length', default=32, help='Secret length in bytes')
def generate_secret(length):
    """Generate secure random secret"""
    secret = secrets.token_hex(length)
    click.echo(f'Generated secret ({length} bytes):')
    click.echo(secret)


@click.command('cleanup-old-data')
@click.option('--days', default=30, help='Delete data older than N days')
@click.option('--dry-run', is_flag=True, help='Show what would be deleted')
def cleanup_old_data(days, dry_run):
    """Clean up old messages and rate limit logs"""
    from datetime import datetime
    from app.models.message import Message

    # Count expired messages
    expired_messages = Message.query.filter(
        Message.expires_at < datetime.utcnow()
    ).count()

    if dry_run:
        click.echo(f'Would delete {expired_messages} expired messages')
    else:
        Message.query.filter(Message.expires_at < datetime.utcnow()).delete()
        db.session.commit()
        click.echo(f'✓ Deleted {expired_messages} expired messages')


# Demo personas: each account is also a teaching example.
# Jinja escapes on render, so these are plain text here.
VENDOR_PERSONAS = [
    ('salt_n_peppa', 'Salt & Peppa',
     'Sells hashing supplies. Insists that salt goes in the database and pepper stays in the environment.'),
    ('zero_cool', 'Zero Cool',
     'Retired 1995 teen hacker, now selling perfectly legal courseware. Hack the planet, responsibly.'),
    ('null_bytes', 'Null Bytes',
     'Terminates everything early. Ask about the buffer overflow discount.'),
    ('entropy_ella', 'Entropy Ella',
     'Rolls actual dice. Refuses to sell anything generated by Math.random().'),
    ('rubber_ducky', 'Rubber Ducky',
     'Debugging consultant. Listens patiently while you explain the bug and solve it yourself.'),
]

BUYER_PERSONAS = [
    ('clicky_mcclickface', 'Clicky McClickface',
     'Has never met a link he would not click. The security team knows him by first name.'),
    ('bob_from_accounting', 'Bob from Accounting',
     'Receives 40 invoices a day. Three of them are real. Please be gentle.'),
    ('password_pete', 'Password Pete',
     'Uses the same password everywhere. It is his cat\'s name and the year he got her.'),
    ('sudo_susan', 'Sudo Susan',
     'Believes any problem can be solved by running the command again with sudo. Often right.'),
    ('two_factor_tina', 'Two-Factor Tina',
     'Has 2FA on everything, including the microwave. The one you want in your org.'),
    ('phishy_phil', 'Phishy Phil',
     'Once wired money to a Nigerian prince. Now runs the awareness training.'),
    ('cache_money', 'Cache Money',
     'Never invalidates anything. Still seeing prices from last Tuesday.'),
    ('patch_tuesday', 'Patch Tuesday',
     'Reboots religiously once a month. Has strong opinions about maintenance windows.'),
    ('cookie_monster', 'Cookie Monster',
     'Accepts all cookies. ALL of them. Om nom nom SameSite=None.'),
    ('admin_admin', 'Admin Admin',
     'Left the default credentials on the router. Named the WiFi "FBI Surveillance Van".'),
]


def _attach_cover(product, category_name=None):
    """
    Draw a cover for a seeded product and register it as its primary image.

    Generated rather than downloaded: no third-party media in the repository,
    no licences to track, and -- unlike a stock photo -- no EXIF to leak. The
    upload path still strips metadata; that is a separate control, exercised by
    image_service.py.
    """
    import os

    from flask import current_app

    from app.models.product import ProductImage
    from app.services.cover_service import cover_filename, render_cover

    folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'products')
    os.makedirs(folder, exist_ok=True)

    filename = cover_filename(product.title)
    path = os.path.join(folder, filename)

    if not os.path.exists(path):
        with open(path, 'wb') as handle:
            handle.write(render_cover(product.title, category_name))

    if ProductImage.query.filter_by(product_id=product.id, filename=filename).first():
        return

    db.session.add(ProductImage(
        product_id=product.id,
        filename=filename,
        filepath=path,
        file_size=os.path.getsize(path),
        mime_type='image/png',
        metadata_stripped=True,  # nothing was ever embedded; we drew it
        is_primary=True,
        display_order=0,
    ))


@click.command('seed-data')
@click.option('--products', default=20, help='Number of products to create')
def seed_data(products):
    """Seed database with test data"""
    from faker import Faker
    from app.models.product import Product
    fake = Faker()

    click.echo('🌱 Seeding database with test data...')

    # Get or create categories
    categories = ProductCategory.query.all()
    if not categories:
        click.echo('⚠️  No categories found. Run init-db first.')
        return

    click.echo(f'Found {len(categories)} categories')

    # Create vendor users
    vendors = []
    for username, display_name, bio in VENDOR_PERSONAS:
        existing = User.query.filter_by(username=username).first()
        if not existing:
            vendor = User(
                username=username,
                display_name=display_name,
                vendor_description=bio,
                email=f'{username}@example.com',
                role='vendor',
                is_active=True,
                is_verified=True,
                is_vendor_approved=True,  # Auto-approve for testing
                terms_accepted=True
            )
            vendor.set_password('Password123!')
            db.session.add(vendor)
            vendors.append(vendor)
        else:
            vendors.append(existing)

    db.session.commit()
    click.echo(f'✅ Created {len([v for v in vendors if v.id])} vendor accounts')

    # Create buyer users
    buyers = []
    for username, display_name, bio in BUYER_PERSONAS:
        existing = User.query.filter_by(username=username).first()
        if not existing:
            buyer = User(
                username=username,
                display_name=display_name,
                bio=bio,
                email=f'{username}@example.com',
                role='buyer',
                is_active=True,
                is_verified=True,
                terms_accepted=True
            )
            buyer.set_password('Password123!')
            db.session.add(buyer)
            buyers.append(buyer)
        else:
            buyers.append(existing)

    db.session.commit()
    click.echo(f'✅ Created {len([b for b in buyers if b.id])} buyer accounts')

    # Reload vendors after commit
    vendors = User.query.filter_by(role='vendor').all()

    # Create products
    product_titles = [
        'Python Programming Guide', 'JavaScript Essentials', 'Web Development Course',
        'Digital Marketing Ebook', 'Photography Presets Pack', 'UI/UX Design Template',
        'SEO Tools Bundle', 'Social Media Graphics', 'Business Plan Template',
        'Cryptocurrency Guide', 'Fitness Training Program', 'Cooking Recipe Collection',
        'Music Production Pack', 'Video Editing Presets', 'Graphic Design Assets',
        'WordPress Theme', 'Mobile App Template', 'Data Science Tutorial',
        'Machine Learning Course', 'Cybersecurity Handbook'
    ]

    category_names = {str(c.id): c.name for c in categories}

    created_products = 0
    for i in range(products):
        title = f"{product_titles[i % len(product_titles)]} #{i+1}"

        product = Product(
            vendor_id=fake.random_element(vendors).id,
            category_id=fake.random_element(categories).id,
            title=title,
            description=fake.text(max_nb_chars=500),
            price=fake.random_int(min=5, max=200),
            quantity=fake.random_int(min=5, max=100),
            is_digital=fake.boolean(chance_of_getting_true=50),
            is_active=True,
            is_approved=True,
            tags=','.join(fake.words(nb=3)),
            search_vector=title.lower(),
            views=fake.random_int(min=0, max=1000),
            sales=fake.random_int(min=0, max=50)
        )
        db.session.add(product)
        db.session.flush()  # need the id for the image row
        _attach_cover(product, category_names.get(str(product.category_id)))
        created_products += 1

    db.session.commit()
    click.echo(f'✅ Created {created_products} products (with generated covers)')

    click.echo('✨ Database seeding completed!')
    click.echo('\n📝 Test Accounts:')
    click.echo('   Admin: admin / ChangeMe123!')
    click.echo('   Vendors: ' + ', '.join(u for u, _, _ in VENDOR_PERSONAS) + ' / Password123!')
    click.echo('   Buyers:  ' + ', '.join(u for u, _, _ in BUYER_PERSONAS) + ' / Password123!')


@click.command('backup-now')
def backup_now():
    """Trigger immediate backup"""
    import subprocess

    click.echo('Starting backup...')
    result = subprocess.run(['/app/scripts/backup.sh'], capture_output=True, text=True)

    if result.returncode == 0:
        click.echo('✓ Backup completed successfully')
        click.echo(result.stdout)
    else:
        click.echo('✗ Backup failed')
        click.echo(result.stderr)


@click.command('generate-pgp-keys')
@click.option('--username', prompt=True, help='Username to generate keys for')
@click.option('--passphrase', prompt=True, hide_input=True, confirmation_prompt=True, help='Passphrase to protect private key')
@click.option('--save-private', is_flag=True, help='Save private key to file (INSECURE - for testing only)')
def generate_pgp_keys(username, passphrase, save_private):
    """Generate PGP key pair for a user"""
    from app.services.pgp_service import PGPService
    from app.services.audit_service import log_pgp_key_event
    from datetime import datetime

    # Get user
    user = User.query.filter_by(username=username).first()
    if not user:
        click.echo(f'✗ User {username} not found')
        return

    # Check if user already has key
    is_update = False
    if user.pgp_public_key:
        click.echo(f'⚠️  User {username} already has a PGP key')
        overwrite = click.confirm('Overwrite existing key?')
        if not overwrite:
            return
        is_update = True

    click.echo(f'🔐 Generating PGP key pair for {username}...')

    # Generate keys
    pgp_service = PGPService(use_temp_home=True)
    result = pgp_service.generate_keypair(
        name=username,
        email=user.email,
        passphrase=passphrase
    )

    if not result['success']:
        click.echo(f'✗ Key generation failed: {result.get("error", "Unknown error")}')
        return

    public_key = result['public_key']
    private_key = result['private_key']
    fingerprint = result.get('fingerprint', 'N/A')

    # Save public key to database with timestamps
    user.pgp_public_key = public_key
    user.pgp_fingerprint = fingerprint
    user.pgp_key_created_by = 'cli'
    user.pgp_key_source = 'generated'

    if not is_update:
        user.pgp_key_created_at = datetime.utcnow()
    else:
        user.pgp_key_updated_at = datetime.utcnow()

    db.session.commit()

    # Log audit event
    action = 'pgp_key_updated' if is_update else 'pgp_key_generated'
    log_pgp_key_event(
        user_id=user.id,
        action=action,
        key_fingerprint=fingerprint,
        created_by='cli',
        source='generated',
        metadata={
            'username': username,
            'email': user.email,
            'key_length': '4096',
            'algorithm': 'RSA'
        }
    )

    click.echo('✅ PGP keys generated successfully!')
    click.echo('✓ Public key saved to database')
    click.echo(f'✓ Key fingerprint: {fingerprint}')
    click.echo('✓ Audit log created')

    # Display public key
    click.echo('\n📋 Public Key:')
    click.echo('─' * 80)
    click.echo(public_key)
    click.echo('─' * 80)

    # Save private key to file if requested
    if save_private:
        filename = f'{username}_private_key.asc'
        with open(filename, 'w') as f:
            f.write(private_key)
        click.echo(f'\n⚠️  Private key saved to: {filename}')
        click.echo('⚠️  SECURITY WARNING: Delete this file after copying to secure storage!')
    else:
        click.echo('\n🔐 Private Key (SAVE THIS SECURELY - will not be shown again):')
        click.echo('─' * 80)
        click.echo(private_key)
        click.echo('─' * 80)
        click.echo('\n⚠️  Copy this private key to a secure location NOW!')
        click.echo('⚠️  Recommended: USB stick, password manager, or hardware key')
        click.echo('⚠️  DO NOT store in cloud, email, or unencrypted locations')


@click.command('upload-pgp-key')
@click.option('--username', prompt=True, help='Username to upload key for')
@click.option('--key-file', prompt=True, help='Path to public key file')
def upload_pgp_key(username, key_file):
    """Upload existing PGP public key for a user"""
    from app.services.pgp_service import PGPService
    from app.services.audit_service import log_pgp_key_event
    from datetime import datetime

    # Get user
    user = User.query.filter_by(username=username).first()
    if not user:
        click.echo(f'✗ User {username} not found')
        return

    # Check if user already has key
    is_update = False
    if user.pgp_public_key:
        click.echo(f'⚠️  User {username} already has a PGP key')
        overwrite = click.confirm('Overwrite existing key?')
        if not overwrite:
            return
        is_update = True

    # Read key file
    try:
        with open(key_file, 'r') as f:
            public_key = f.read()
    except FileNotFoundError:
        click.echo(f'✗ Key file not found: {key_file}')
        return
    except Exception as e:
        click.echo(f'✗ Error reading key file: {e}')
        return

    # Validate key format
    if not public_key.startswith('-----BEGIN PGP PUBLIC KEY BLOCK-----'):
        click.echo('✗ Invalid PGP public key format')
        return

    # Extract fingerprint using PGP service
    pgp_service = PGPService(use_temp_home=True)
    fingerprint = None
    try:
        # Import key temporarily to get fingerprint
        import_result = pgp_service.gpg.import_keys(public_key)
        if import_result.count > 0:
            fingerprint = import_result.fingerprints[0]
    except Exception as e:
        click.echo(f'⚠️  Could not extract fingerprint: {e}')

    # Save to database with timestamps
    user.pgp_public_key = public_key
    user.pgp_fingerprint = fingerprint
    user.pgp_key_created_by = 'cli'
    user.pgp_key_source = 'uploaded'

    if not is_update:
        user.pgp_key_created_at = datetime.utcnow()
    else:
        user.pgp_key_updated_at = datetime.utcnow()

    db.session.commit()

    # Log audit event
    action = 'pgp_key_updated' if is_update else 'pgp_key_uploaded'
    log_pgp_key_event(
        user_id=user.id,
        action=action,
        key_fingerprint=fingerprint,
        created_by='cli',
        source='uploaded',
        metadata={
            'username': username,
            'email': user.email,
            'key_file': key_file
        }
    )

    click.echo(f'✅ PGP public key uploaded for {username}')
    click.echo('✓ Key saved to database')
    if fingerprint:
        click.echo(f'✓ Key fingerprint: {fingerprint}')
    click.echo('✓ Audit log created')


@click.command('show-pgp-audit')
@click.option('--username', help='Filter by username (optional)')
@click.option('--limit', default=50, help='Number of entries to show')
def show_pgp_audit(username, limit):
    """Show PGP key audit log"""
    from sqlalchemy import text

    click.echo('🔍 PGP Key Audit Log')
    click.echo('=' * 100)

    try:
        # Build query
        if username:
            # Get user ID
            user = User.query.filter_by(username=username).first()
            if not user:
                click.echo(f'✗ User {username} not found')
                return

            query = text("""
                SELECT
                    al.timestamp,
                    u.username,
                    al.action,
                    al.new_values->>'fingerprint' as fingerprint,
                    al.new_values->>'source' as source,
                    al.new_values->>'created_by' as created_by,
                    al.status,
                    al.ip_address
                FROM audit_log al
                JOIN users u ON al.user_id = u.id
                WHERE al.action LIKE 'pgp_key%'
                  AND al.user_id = :user_id
                ORDER BY al.timestamp DESC
                LIMIT :limit
            """)
            result = db.session.execute(query, {'user_id': user.id, 'limit': limit})
        else:
            query = text("""
                SELECT
                    al.timestamp,
                    u.username,
                    al.action,
                    al.new_values->>'fingerprint' as fingerprint,
                    al.new_values->>'source' as source,
                    al.new_values->>'created_by' as created_by,
                    al.status,
                    al.ip_address
                FROM audit_log al
                JOIN users u ON al.user_id = u.id
                WHERE al.action LIKE 'pgp_key%'
                ORDER BY al.timestamp DESC
                LIMIT :limit
            """)
            result = db.session.execute(query, {'limit': limit})

        rows = result.fetchall()

        if not rows:
            click.echo('No PGP key audit entries found.')
            return

        click.echo(f'\nFound {len(rows)} audit entries:\n')

        for row in rows:
            timestamp = row[0].strftime('%Y-%m-%d %H:%M:%S')
            username = row[1]
            action = row[2]
            fingerprint = row[3] or 'N/A'
            source = row[4] or 'N/A'
            created_by = row[5] or 'N/A'
            status = row[6]
            ip_address = row[7] or 'N/A'

            # Color code by action
            if 'generated' in action:
                icon = '🔐'
            elif 'uploaded' in action:
                icon = '📤'
            elif 'updated' in action:
                icon = '🔄'
            elif 'deleted' in action:
                icon = '🗑️'
            else:
                icon = '📝'

            click.echo(f'{icon} {timestamp} | {username:15} | {action:20}')
            click.echo(f'   Fingerprint: {fingerprint[:16]}...')
            click.echo(f'   Source: {source:12} | Created by: {created_by:8} | IP: {ip_address}')
            click.echo(f'   Status: {status}')
            click.echo('-' * 100)

    except Exception as e:
        click.echo(f'✗ Error reading audit log: {e}')


@click.command('security-check')
def security_check():
    """Run security checks"""
    click.echo('Running security checks...')

    # Check for users without 2FA
    users_no_2fa = User.query.filter_by(
        two_factor_enabled=False,
        role='admin'
    ).count()

    if users_no_2fa > 0:
        click.echo(f'⚠️  {users_no_2fa} admin users without 2FA')
    else:
        click.echo('✓ All admin users have 2FA enabled')

    # Check for default passwords (can't really check, but warn)
    click.echo('⚠️  Ensure default passwords have been changed')

    # Check encryption key
    if current_app.config['DB_ENCRYPTION_KEY'] == 'dev-encryption-key':
        click.echo('⚠️  Using default encryption key - change immediately!')
    else:
        click.echo('✓ Custom encryption key configured')

    # Check secret key
    if current_app.config['SECRET_KEY'] == 'dev-key-change-me-in-production':
        click.echo('⚠️  Using default secret key - change immediately!')
    else:
        click.echo('✓ Custom secret key configured')


def register_commands(app):
    """Register all CLI commands"""
    app.cli.add_command(init_db)
    app.cli.add_command(init_admin)
    app.cli.add_command(create_user)
    app.cli.add_command(reset_password)
    app.cli.add_command(generate_secret)
    app.cli.add_command(cleanup_old_data)
    app.cli.add_command(seed_data)
    app.cli.add_command(backup_now)
    app.cli.add_command(security_check)
    app.cli.add_command(generate_pgp_keys)
    app.cli.add_command(upload_pgp_key)
    app.cli.add_command(show_pgp_audit)
