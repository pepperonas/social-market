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

    click.echo(f'✓ Admin user created')
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
    from datetime import datetime, timedelta
    from app.models.message import Message

    cutoff_date = datetime.utcnow() - timedelta(days=days)

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
    for i in range(5):
        username = f'vendor{i+1}'
        existing = User.query.filter_by(username=username).first()
        if not existing:
            vendor = User(
                username=username,
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
    for i in range(10):
        username = f'buyer{i+1}'
        existing = User.query.filter_by(username=username).first()
        if not existing:
            buyer = User(
                username=username,
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
        created_products += 1

    db.session.commit()
    click.echo(f'✅ Created {created_products} products')

    click.echo('✨ Database seeding completed!')
    click.echo('\n📝 Test Accounts:')
    click.echo('   Admin: admin / ChangeMe123!')
    click.echo('   Vendors: vendor1-5 / Password123!')
    click.echo('   Buyers: buyer1-10 / Password123!')


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
