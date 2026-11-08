"""
Review round 3 (2026-11), step 4: background jobs.

app/tasks.py set `celery = None` and then decorated every task with
`@celery.task` -- AttributeError on import. Nothing imported the module, the
docker-compose worker loaded an empty Celery instance, and the beat schedule
was never applied. On the live server no worker ran at all. So none of it ever
executed: escrow auto-finalisation, deletion of expired messages, the
failed-login scan. Message.expires_at was a promise kept by nobody.

The jobs now live in app/jobs.py as plain functions with one entry point,
`flask run-job NAME`, which systemd timers call on the server and a thin
Celery wrapper (app/tasks.py) calls under docker-compose.
"""

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def product(app, sample_vendor):
    from app import db
    from app.models.product import Product, ProductCategory

    suffix = uuid.uuid4().hex[:8]
    category = ProductCategory(id=uuid.uuid4(), name=f'J {suffix}', slug=f'j-{suffix}')
    db.session.add(category)
    db.session.flush()
    item = Product(id=uuid.uuid4(), vendor_id=sample_vendor.id, category_id=category.id,
                   title=f'Job item {suffix}', description='for the job tests',
                   price=Decimal('10.00'), quantity=10, is_active=True, is_approved=True)
    db.session.add(item)
    db.session.commit()
    return item


@pytest.fixture
def place_order(app, sample_user, sample_vendor, product):
    """An order placed the way the app does it: stock reserved, escrow created."""
    from app import db
    from app.models.order import Order
    from app.services.escrow_service import EscrowService
    from app.timeutil import utcnow

    def make(age=timedelta(0), quantity=2):
        assert product.reserve_stock(quantity)
        order = Order(id=uuid.uuid4(), buyer_id=sample_user.id, vendor_id=sample_vendor.id,
                      product_id=product.id, quantity=quantity, unit_price=product.price,
                      created_at=utcnow() - age)
        db.session.add(order)
        db.session.flush()
        EscrowService.create_escrow_for_order(order)
        db.session.commit()
        return order

    return make


def run(app, *names):
    return app.test_cli_runner().invoke(args=['run-job', *names])


def fresh(model, ident):
    from app import db

    # expunge, not expire: an object the job deleted would otherwise raise
    # ObjectDeletedError instead of coming back as None.
    db.session.expunge_all()
    return db.session.get(model, ident)


# =============================================================================
# The Celery wrapper can be imported at all
# =============================================================================

class TestCeleryWrapper:
    def test_tasks_module_imports(self):
        """It raised AttributeError: 'NoneType' object has no attribute 'task'."""
        import importlib

        import app.tasks
        importlib.reload(app.tasks)

    def test_every_job_is_a_registered_task_on_the_schedule(self, app):
        from celery import Celery

        from app.jobs import JOBS
        from app.tasks import init_celery

        celery = init_celery(app, Celery('test'))
        scheduled = {entry['task'] for entry in celery.conf.beat_schedule.values()}

        assert scheduled == {f'jobs.{name}' for name in JOBS}
        assert scheduled <= set(celery.tasks)

    def test_a_task_runs_its_job_inside_the_app(self, app, monkeypatch):
        from celery import Celery

        from app import jobs
        from app.tasks import init_celery

        seen = []
        monkeypatch.setitem(jobs.JOBS, 'purge-expired-notifications',
                            jobs.Job(lambda: seen.append('ran') or {'deleted': 0}, 'daily', 'x'))
        celery = init_celery(app, Celery('test'))

        celery.tasks['jobs.purge-expired-notifications'].run()

        assert seen == ['ran']


# =============================================================================
# One CLI entry point, failing loudly
# =============================================================================

class TestRunJobCommand:
    def test_unknown_job_fails(self, app):
        result = run(app, 'no-such-job')

        assert result.exit_code != 0

    def test_a_failing_job_fails_the_command(self, app, monkeypatch):
        """
        A systemd timer only notices a broken job through the exit code. The
        old tasks swallowed every exception into {'success': False}.
        """
        from app import jobs

        def boom():
            raise RuntimeError('database gone')
        monkeypatch.setitem(jobs.JOBS, 'purge-expired-messages', jobs.Job(boom, 'daily', 'x'))

        result = run(app, 'purge-expired-messages', 'purge-expired-notifications')

        assert result.exit_code != 0
        assert 'purge-expired-notifications' in result.output, 'later jobs still run'


# =============================================================================
# The jobs themselves
# =============================================================================

class TestAutoFinalize:
    def test_due_delivered_order_is_completed(self, app, place_order):
        from app import db
        from app.models.order import Order
        from app.services.escrow_service import EscrowService
        from app.timeutil import utcnow

        order = place_order()
        EscrowService.pay_order(order)
        order.transition_to('shipped')
        order.transition_to('delivered')
        order.auto_finalize_at = utcnow() - timedelta(minutes=1)
        db.session.commit()

        assert run(app, 'auto-finalize-orders').exit_code == 0

        order = fresh(Order, order.id)
        assert order.status == 'completed'
        assert order.escrow.status == 'released'


class TestExpireUnpaidOrders:
    """
    New with step 3: a placed order now holds its stock. An order that is never
    paid must not hold it for ever -- otherwise one abandoned checkout takes a
    product off the market.
    """

    def test_old_unpaid_order_is_cancelled_and_stock_returns(self, app, place_order, product):
        from app.models.order import Order
        from app.models.product import Product

        hours = app.config['ORDER_PAYMENT_TIMEOUT_HOURS']
        old_id = place_order(age=timedelta(hours=hours + 1), quantity=3).id
        product_id = product.id
        assert fresh(Product, product_id).quantity == 7

        assert run(app, 'expire-unpaid-orders').exit_code == 0

        assert fresh(Order, old_id).status == 'cancelled'
        assert fresh(Product, product_id).quantity == 10

    def test_recent_unpaid_order_is_left_alone(self, app, place_order):
        from app.models.order import Order

        recent = place_order(age=timedelta(minutes=5))

        run(app, 'expire-unpaid-orders')

        assert fresh(Order, recent.id).status == 'pending'

    def test_paid_order_is_never_expired(self, app, place_order):
        from app import db
        from app.models.order import Order
        from app.services.escrow_service import EscrowService

        hours = app.config['ORDER_PAYMENT_TIMEOUT_HOURS']
        order = place_order(age=timedelta(hours=hours + 1))
        EscrowService.pay_order(order)
        db.session.commit()

        run(app, 'expire-unpaid-orders')

        assert fresh(Order, order.id).status == 'paid'


class TestPurges:
    def _thread(self, sample_user, sample_vendor):
        from app import db
        from app.models.message import MessageThread

        thread = MessageThread(id=uuid.uuid4(), participant_1_id=sample_user.id,
                               participant_2_id=sample_vendor.id)
        db.session.add(thread)
        db.session.flush()
        return thread

    def test_expired_messages_are_deleted(self, app, sample_user, sample_vendor):
        from app import db
        from app.models.message import Message
        from app.timeutil import utcnow

        thread = self._thread(sample_user, sample_vendor)
        old = Message(id=uuid.uuid4(), thread_id=thread.id, sender_id=sample_user.id,
                      recipient_id=sample_vendor.id, content_encrypted=b'x',
                      expires_at=utcnow() - timedelta(days=1))
        new = Message(id=uuid.uuid4(), thread_id=thread.id, sender_id=sample_user.id,
                      recipient_id=sample_vendor.id, content_encrypted=b'y',
                      expires_at=utcnow() + timedelta(days=1))
        db.session.add_all([old, new])
        db.session.commit()
        old_id, new_id = old.id, new.id

        assert run(app, 'purge-expired-messages').exit_code == 0

        assert fresh(Message, old_id) is None
        assert fresh(Message, new_id) is not None

    def test_expired_notifications_are_deleted(self, app, sample_user):
        from app import db
        from app.models.notification import Notification
        from app.timeutil import utcnow

        old = Notification(id=uuid.uuid4(), user_id=sample_user.id, notification_type='t',
                           title='old', message='m', expires_at=utcnow() - timedelta(days=1))
        db.session.add(old)
        db.session.commit()
        old_id = old.id

        assert run(app, 'purge-expired-notifications').exit_code == 0

        assert fresh(Notification, old_id) is None


class TestSecurityScan:
    """
    The scan looked for action = 'login_failed'. The app writes
    'login_failed_password', 'login_failed_locked', '2fa_failed', ... -- the
    query could never match anything. It also used a PostgreSQL-only INTERVAL
    literal; the cutoff is now computed in Python and bound.
    """

    def test_burst_of_failed_logins_from_one_ip_is_reported(self, app):
        from sqlalchemy import text

        from app import db
        from app.jobs import security_scan
        from tests.conftest import aware_utcnow

        ip = f'203.0.113.{uuid.uuid4().int % 250}'
        for action in ['login_failed_password'] * 8 + ['2fa_failed'] * 2 + ['reauth_failed'] * 2:
            db.session.execute(text(
                "INSERT INTO auth_log (timestamp, username, action, ip_address) "
                "VALUES (:ts, 'x', :action, :ip)"), {'ts': aware_utcnow(), 'action': action, 'ip': ip})
        db.session.commit()

        result = security_scan()

        assert ip in result['suspicious_ips']

    def test_successful_logins_are_not_counted(self, app):
        from sqlalchemy import text

        from app import db
        from app.jobs import security_scan
        from tests.conftest import aware_utcnow

        ip = f'198.51.100.{uuid.uuid4().int % 250}'
        for _ in range(20):
            db.session.execute(text(
                "INSERT INTO auth_log (timestamp, username, action, ip_address) "
                "VALUES (:ts, 'x', 'login_success', :ip)"), {'ts': aware_utcnow(), 'ip': ip})
        db.session.commit()

        assert ip not in security_scan()['suspicious_ips']


class TestSystemdUnitsMatchTheRegistry:
    """The server runs the jobs from deploy/systemd/. A job missing there never runs."""

    def _units(self):
        import pathlib
        import re

        found = {}
        for unit in pathlib.Path('deploy/systemd').glob('socialmarket-jobs-*.service'):
            line = re.search(r'^ExecStart=.*run-job (.+)$', unit.read_text(), re.M)
            kind = unit.stem.rsplit('-', 1)[-1]
            found[kind] = line.group(1).split()
        return found

    def test_every_job_runs_on_its_schedule(self):
        from app.jobs import JOBS

        units = self._units()
        for name, job in JOBS.items():
            assert name in units.get(job.schedule, []), f'{name} is not in the {job.schedule} unit'

    def test_units_name_only_existing_jobs(self):
        from app.jobs import JOBS

        for names in self._units().values():
            assert set(names) <= set(JOBS)

    def test_every_job_service_has_a_timer(self):
        import pathlib

        for unit in pathlib.Path('deploy/systemd').glob('socialmarket-jobs-*.service'):
            assert unit.with_suffix('.timer').exists(), unit.name
