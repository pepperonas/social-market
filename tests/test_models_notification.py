"""Unit tests for the Notification model (per-user isolation, expiry, counts)."""

from datetime import datetime, timedelta

import pytest


@pytest.fixture
def notify(app, sample_user):
    from app import db
    from app.models.notification import Notification

    created = []

    def _make(user=None, title='Title', read=False, **over):
        note = Notification.create(
            user_id=(user or sample_user).id,
            notification_type='system',
            title=title,
            message='body',
            **over
        )
        if read:
            note.mark_as_read()
        created.append(note)
        return note

    yield _make

    for note in created:
        try:
            db.session.delete(note)
            db.session.commit()
        except Exception:
            db.session.rollback()


class TestCreation:
    def test_created_unread(self, notify):
        assert notify().is_read is False

    def test_expiry_default_is_set(self, notify):
        note = notify()
        assert note.expires_at is not None
        assert note.expires_at > datetime.utcnow()

    def test_zero_days_means_no_expiry(self, notify):
        assert notify(expires_days=0).expires_at is None

    def test_is_expired_false_when_fresh(self, notify):
        assert notify().is_expired() is False

    def test_is_expired_true_when_past(self, app, notify):
        from app import db

        note = notify()
        note.expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.session.commit()

        assert note.is_expired() is True


class TestReadState:
    def test_mark_as_read(self, notify):
        note = notify()
        note.mark_as_read()
        assert note.is_read is True

    def test_unread_count(self, notify, sample_user):
        from app.models.notification import Notification

        before = Notification.get_unread_count(sample_user.id)
        notify()
        notify()
        notify(read=True)

        assert Notification.get_unread_count(sample_user.id) == before + 2

    def test_mark_all_read(self, notify, sample_user):
        from app.models.notification import Notification

        notify()
        notify()
        Notification.mark_all_read(sample_user.id)

        assert Notification.get_unread_count(sample_user.id) == 0


class TestUserIsolation:
    """A notification must never be visible or countable for another user."""

    def test_count_is_per_user(self, notify, sample_user, sample_vendor):
        from app.models.notification import Notification

        vendor_before = Notification.get_unread_count(sample_vendor.id)
        notify(user=sample_user)

        assert Notification.get_unread_count(sample_vendor.id) == vendor_before

    def test_mark_all_read_does_not_touch_other_users(self, notify, sample_user, sample_vendor):
        from app.models.notification import Notification

        notify(user=sample_vendor)
        vendor_unread = Notification.get_unread_count(sample_vendor.id)
        assert vendor_unread >= 1

        Notification.mark_all_read(sample_user.id)

        assert Notification.get_unread_count(sample_vendor.id) == vendor_unread

    def test_get_recent_only_returns_own(self, notify, sample_user, sample_vendor):
        from app.models.notification import Notification

        notify(user=sample_user, title='mine')
        notify(user=sample_vendor, title='theirs')

        titles = [n.title for n in Notification.get_recent(sample_user.id, limit=50)]
        assert 'theirs' not in titles
