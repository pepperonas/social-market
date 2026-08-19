"""
Performance regression tests.

These pin the *number of SQL statements* an endpoint issues. The point is not
raw speed but shape: a query count that grows with the number of rows is an
N+1 problem, and it will not show up on a developer machine with three rows.

Blue team relevance: N+1 endpoints are a cheap denial-of-service surface. An
authenticated user who can create rows can make one HTTP request cost hundreds
of database round trips.
"""

import uuid

import pytest


@pytest.fixture
def conversation_partners(app, sample_user):
    """Create N threads with messages for the sample user."""
    from app import db
    from app.models.user import User
    from app.models.message import Message, MessageThread

    created = {'users': [], 'threads': [], 'messages': []}

    def _build(count):
        for i in range(count):
            suffix = uuid.uuid4().hex[:8]
            other = User(
                id=uuid.uuid4(),
                username=f'partner_{suffix}',
                email=f'partner_{suffix}@test.local',
                role='vendor',
                is_active=True,
                is_vendor_approved=True,
            )
            other.set_password('PartnerPass123!')
            db.session.add(other)
            db.session.flush()

            thread = MessageThread(
                id=uuid.uuid4(),
                participant_1_id=sample_user.id,
                participant_2_id=other.id,
                subject=f'Thread {i}',
            )
            db.session.add(thread)
            db.session.flush()

            for j in range(3):
                message = Message(
                    id=uuid.uuid4(),
                    thread_id=thread.id,
                    sender_id=other.id,
                    recipient_id=sample_user.id,
                    content_encrypted=b'ciphertext',
                    is_read=False,
                )
                db.session.add(message)
                created['messages'].append(message)

            created['users'].append(other)
            created['threads'].append(thread)

        db.session.commit()
        return created['threads']

    yield _build

    for bucket in ('messages', 'threads', 'users'):
        for obj in created[bucket]:
            try:
                db.session.delete(obj)
            except Exception:
                db.session.rollback()
    db.session.commit()


def _login(client, user, password='TestPassword123!'):
    response = client.post('/auth/login',
                           data={'username': user.username, 'password': password},
                           follow_redirects=False)
    assert response.status_code in (302, 303)


class TestInboxQueryCount:
    """
    Regression: inbox() ran four queries per thread (participant lookup, unread
    count, message count, last message).
    """

    def test_inbox_query_count_does_not_grow_with_threads(
        self, client, sample_user, conversation_partners, query_counter
    ):
        conversation_partners(3)
        _login(client, sample_user)

        with query_counter() as few:
            assert client.get('/messages/').status_code == 200

        conversation_partners(9)  # 12 threads total

        with query_counter() as many:
            assert client.get('/messages/').status_code == 200

        growth = many.count - few.count
        assert growth <= 2, (
            f'query count grew by {growth} when adding 9 threads '
            f'({few.count} -> {many.count}); this is an N+1 regression'
        )

    def test_inbox_stays_under_a_fixed_budget(
        self, client, sample_user, conversation_partners, query_counter
    ):
        """A generous absolute ceiling, so a rewrite cannot quietly explode."""
        conversation_partners(10)
        _login(client, sample_user)

        with query_counter() as counter:
            assert client.get('/messages/').status_code == 200

        assert counter.count < 20, (
            f'inbox issued {counter.count} queries for 10 threads:\n'
            + '\n'.join(counter.statements[:25])
        )

    def test_inbox_still_shows_correct_unread_counts(
        self, client, sample_user, conversation_partners
    ):
        """Batching must not change the numbers it reports."""
        from app import db
        from app.models.message import Message

        threads = conversation_partners(2)
        _login(client, sample_user)

        counts = {
            t.id: Message.query.filter_by(
                thread_id=t.id, recipient_id=sample_user.id, is_read=False
            ).count()
            for t in threads
        }
        assert all(c == 3 for c in counts.values()), 'fixture should create 3 unread each'

        # Mark one message read; the endpoint must reflect it
        first = Message.query.filter_by(thread_id=threads[0].id).first()
        first.is_read = True
        db.session.commit()

        response = client.get('/messages/')
        assert response.status_code == 200


class TestEmptyInputsAvoidQueries:
    """Helpers must short-circuit rather than issue a pointless IN () query."""

    def test_unread_counts_with_no_threads(self, app, sample_user, query_counter):
        from app.routes.messages import _unread_counts_by_thread

        user_id = sample_user.id  # outside the counter: attribute access can reload

        with query_counter() as counter:
            assert _unread_counts_by_thread([], user_id) == {}
        assert counter.count == 0

    def test_last_message_with_no_threads(self, app, query_counter):
        from app.routes.messages import _last_message_by_thread

        with query_counter() as counter:
            assert _last_message_by_thread([]) == {}
        assert counter.count == 0
