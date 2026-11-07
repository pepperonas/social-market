"""EDUCATIONAL SECURITY TRAINING ENVIRONMENT

Round 3, step 7: HTTP workflows for the previously thinly covered account,
notification and message routes. Assert persisted effects and isolation, not
merely that an endpoint can be called. Crypto is stubbed only at the service
boundary; real GPG packet validation remains in test_admin_and_messaging.py.
"""

import uuid
from unittest.mock import Mock

import pytest

from app import db
from app.models.message import Message, MessageThread
from app.models.notification import Notification
from app.models.product import Product, ProductCategory
from tests.conftest import reload_user


def signed_in(app, user):
    client = app.test_client()
    with client.session_transaction() as session:
        session['_user_id'] = user.get_id()
    return client


def fresh(model, ident):
    db.session.expire_all()
    return db.session.get(model, ident)


@pytest.fixture
def notes(sample_user, sample_vendor):
    created = []

    def make(user=sample_user, title=None, **kwargs):
        note = Notification.create(user.id, 'system', title or uuid.uuid4().hex,
                                   'workflow notification', **kwargs)
        created.append(note.id)
        return note

    yield make
    for ident in created:
        note = db.session.get(Notification, ident)
        if note:
            db.session.delete(note)
    db.session.commit()


class TestNotificationWorkflows:
    def test_lists_filter_read_state_and_other_users(self, auth_client, notes, sample_vendor):
        """The unread tab must render actual rows, without leaking another user's alerts."""
        unread = notes(title='own-unread-workflow')
        read = notes(title='own-read-workflow')
        read.mark_as_read()
        notes(sample_vendor, title='foreign-workflow')
        body = auth_client.get('/notifications/').data
        assert unread.title.encode() in body and read.title.encode() in body
        assert b'foreign-workflow' not in body
        response = auth_client.get('/notifications/unread')
        assert response.status_code == 200
        assert unread.title.encode() in response.data
        assert read.title.encode() not in response.data
        assert b'foreign-workflow' not in response.data

    def test_api_recent_is_unread_own_and_limited(self, auth_client, notes, sample_vendor):
        own = [notes() for _ in range(7)]
        read = notes()
        read.mark_as_read()
        foreign = notes(sample_vendor)
        assert auth_client.get('/notifications/api/count').json == {'count': 7}
        data = auth_client.get('/notifications/api/recent').json
        assert data['count'] == 5
        ids = {row['id'] for row in data['notifications']}
        assert ids <= {str(n.id) for n in own}
        assert str(read.id) not in ids and str(foreign.id) not in ids

    @pytest.mark.parametrize('api', [False, True])
    def test_mark_read_checks_owner_and_persists(self, auth_client, notes, sample_vendor, api):
        own, foreign = notes(), notes(sample_vendor)
        prefix = '/notifications/api/mark-read' if api else '/notifications/mark-read'
        response = auth_client.post(f'{prefix}/{foreign.id}')
        assert response.status_code == (404 if api else 302)
        assert fresh(Notification, foreign.id).is_read is False
        response = auth_client.post(f'{prefix}/{own.id}')
        assert response.status_code == (200 if api else 302)
        assert fresh(Notification, own.id).is_read is True
        assert fresh(Notification, own.id).read_at is not None

    def test_action_redirect_and_bulk_read_are_scoped(self, auth_client, notes, sample_vendor):
        action = notes(action_url='/account/security')
        own, foreign = notes(), notes(sample_vendor)
        response = auth_client.post(f'/notifications/mark-read/{action.id}')
        assert response.location == '/account/security'
        assert auth_client.post('/notifications/mark-all-read').status_code == 302
        assert fresh(Notification, own.id).is_read is True
        assert fresh(Notification, foreign.id).is_read is False

    def test_delete_only_removes_owned_notification(self, auth_client, notes, sample_vendor):
        own, foreign = notes(), notes(sample_vendor)
        own_id, foreign_id = own.id, foreign.id
        assert auth_client.post(f'/notifications/delete/{foreign_id}').status_code == 302
        assert fresh(Notification, foreign_id) is not None
        assert auth_client.post(f'/notifications/delete/{own_id}').status_code == 302
        assert fresh(Notification, own_id) is None


@pytest.fixture
def conversation(sample_user, sample_vendor):
    thread = MessageThread.find_or_create_thread(sample_user.id, sample_vendor.id, subject='workflow-thread')
    incoming = Message(thread_id=thread.id, sender_id=sample_vendor.id,
                       recipient_id=sample_user.id, content_encrypted=b'ciphertext-incoming')
    outgoing = Message(thread_id=thread.id, sender_id=sample_user.id,
                       recipient_id=sample_vendor.id, content_encrypted=b'ciphertext-outgoing')
    db.session.add_all([incoming, outgoing])
    db.session.commit()
    ids = thread.id, incoming.id, outgoing.id
    yield ids
    thread = db.session.get(MessageThread, ids[0])
    if thread:
        db.session.delete(thread)
    db.session.commit()


class TestMessageWorkflows:
    def test_read_and_two_party_delete(self, app, auth_client, sample_vendor, conversation):
        """Opening a thread reads incoming messages; deletion affects each participant separately."""
        thread_id, incoming_id, outgoing_id = conversation
        response = auth_client.get(f'/messages/thread/{thread_id}')
        assert response.status_code == 200
        assert b'workflow-thread' in response.data
        assert fresh(Message, incoming_id).is_read is True
        assert fresh(Message, outgoing_id).is_read is False
        assert auth_client.post(f'/messages/delete/{incoming_id}').status_code == 302
        message = fresh(Message, incoming_id)
        assert message.is_deleted_by_recipient is True
        assert message.is_deleted_by_sender is False
        vendor = signed_in(app, sample_vendor)
        assert vendor.post(f'/messages/delete/{incoming_id}').status_code == 302
        assert fresh(Message, incoming_id) is None

    def test_outsider_cannot_read_send_delete_or_decrypt(self, app, sample_admin, conversation):
        thread_id, incoming_id, _ = conversation
        outsider = signed_in(app, sample_admin)
        assert outsider.get(f'/messages/thread/{thread_id}').location.endswith('/messages/')
        assert outsider.post(f'/messages/send/{thread_id}', data={'message': 'x'}).location.endswith('/messages/')
        assert outsider.post(f'/messages/delete/{incoming_id}').location.endswith('/messages/')
        response = outsider.post('/messages/decrypt', json={'message_id': str(incoming_id), 'private_key': 'key'})
        assert response.status_code == 403
        message = fresh(Message, incoming_id)
        assert not message.is_read and not message.is_deleted_by_sender and not message.is_deleted_by_recipient
        assert Message.query.filter_by(thread_id=thread_id).count() == 2

    @pytest.mark.parametrize('success', [True, False])
    def test_decryption_result_and_service_inputs(self, auth_client, conversation, monkeypatch, success):
        _, incoming_id, _ = conversation
        service = Mock()
        service.decrypt_message.return_value = (success, 'decrypted-result' if success else 'wrong passphrase')
        monkeypatch.setattr('app.routes.messages.PGPService', Mock(return_value=service))
        response = auth_client.post('/messages/decrypt', json={
            'message_id': str(incoming_id), 'private_key': 'private-key', 'passphrase': 'secret'})
        assert response.status_code == (200 if success else 400)
        assert response.json['success'] is success
        if success:
            assert response.json['decrypted_message'] == 'decrypted-result'
        else:
            assert 'wrong passphrase' in response.json['error']
        service.decrypt_message.assert_called_once_with(
            encrypted_message='ciphertext-incoming', private_key='private-key', passphrase='secret')

    def test_reply_encrypts_and_notifies_recipient(self, auth_client, sample_vendor, conversation, monkeypatch):
        thread_id, _, _ = conversation
        vendor = reload_user(sample_vendor.id)
        vendor.pgp_public_key = 'recipient-public-key'
        db.session.commit()
        service = Mock()
        service.encrypt_message.return_value = (True, 'encrypted-reply')
        monkeypatch.setattr('app.routes.messages.PGPService', Mock(return_value=service))
        response = auth_client.post(f'/messages/send/{thread_id}', data={'message': 'private reply'})
        assert response.location.endswith(f'/messages/thread/{thread_id}')
        message = Message.query.filter_by(thread_id=thread_id, content_encrypted=b'encrypted-reply').one()
        assert message.recipient_id == vendor.id and message.is_encrypted
        service.encrypt_message.assert_called_once_with(message='private reply', recipient_public_key='recipient-public-key')
        note = Notification.query.filter_by(user_id=vendor.id, related_id=thread_id).one()
        assert note.action_url.endswith(f'/messages/thread/{thread_id}')
        db.session.delete(note)
        db.session.commit()

    @pytest.mark.parametrize('content', ['', 'x' * 10001])
    def test_empty_or_oversize_reply_creates_nothing(
        self, auth_client, sample_vendor, conversation, content, monkeypatch
    ):
        thread_id, _, _ = conversation
        vendor = reload_user(sample_vendor.id)
        vendor.pgp_public_key = 'recipient-key'
        db.session.commit()
        service = Mock()
        service.encrypt_message.return_value = (True, 'encrypted-invalid-reply')
        monkeypatch.setattr('app.routes.messages.PGPService', Mock(return_value=service))
        response = auth_client.post(f'/messages/send/{thread_id}', data={'message': content})
        assert response.status_code == 302
        assert Message.query.filter_by(thread_id=thread_id).count() == 2

    def test_admin_directory_excludes_self_and_inactive(self, admin_client, sample_admin, sample_user, sample_vendor):
        vendor = reload_user(sample_vendor.id)
        vendor.is_active = False
        db.session.commit()
        response = admin_client.get('/messages/admin/users')
        assert response.status_code == 200
        assert sample_user.username.encode() in response.data
        assert vendor.username.encode() not in response.data
        # The admin name occurs in the navigation, so check the actual recipient link.
        assert f'/messages/new/{sample_admin.id}'.encode() not in response.data


class TestAccountWorkflows:
    def test_vendor_export_is_scoped_and_downloadable(self, vendor_client, sample_user, sample_vendor, conversation):
        """Portability must export the caller's metadata, never password/TOTP secrets or unrelated products."""
        category = ProductCategory(name='Export category', slug=uuid.uuid4().hex)
        db.session.add(category)
        db.session.flush()
        own = Product(category_id=category.id, vendor_id=sample_vendor.id, title='own-export-product', description='own',
                      price=12, quantity=3)
        foreign = Product(category_id=category.id, vendor_id=sample_user.id, title='foreign-export-product', description='other',
                          price=13, quantity=1)
        db.session.add_all([own, foreign])
        db.session.commit()
        try:
            response = vendor_client.post('/account/export-data')
            assert response.status_code == 200
            assert response.mimetype == 'application/json'
            assert response.headers['Content-Disposition'].startswith('attachment; filename=data_export_')
            data = response.json
            assert data['user_id'] == str(sample_vendor.id)
            assert data['profile']['username'] == sample_vendor.username
            assert {p['id'] for p in data['products']} == {str(own.id)}
            assert {m['id'] for m in data['messages']} == {str(ident) for ident in conversation[1:]}
            assert {m['direction'] for m in data['messages']} == {'sent', 'received'}
            assert not {'password_hash', 'two_factor_secret', 'password_pepper'} & data['profile'].keys()
            assert b'ciphertext-incoming' not in response.data
        finally:
            db.session.delete(own)
            db.session.delete(foreign)
            db.session.delete(category)
            db.session.commit()

    @pytest.mark.parametrize('password,score,strong', [('', 0, False), ('LongPassword123!', 100, True)])
    def test_strength_feedback(self, auth_client, password, score, strong):
        data = auth_client.post('/account/api/check-password-strength', json={'password': password}).json
        assert data['score'] == score and data['strong_enough'] is strong
        assert bool(data['feedback']) is not strong

    def test_delete_requires_exact_confirmation_then_anonymizes(self, auth_client, sample_user):
        """Deletion requires explicit confirmation and must remove secrets and the usable session."""
        ident, username, email = sample_user.id, sample_user.username, sample_user.email
        response = auth_client.post('/account/delete-account', data={
            'password': 'TestPassword123!', 'confirmation': 'DELETE'})
        assert response.status_code == 200
        assert reload_user(ident).is_active is True
        response = auth_client.post('/account/delete-account', data={
            'password': 'TestPassword123!', 'confirmation': f'DELETE {username}'})
        assert response.status_code == 302
        user = reload_user(ident)
        assert user.is_active is False
        assert user.username != username and user.email != email
        assert user.password_hash == 'DELETED'
        assert user.pgp_public_key is None and user.two_factor_secret is None
        assert auth_client.get('/account/privacy').status_code == 302

    def test_audit_pages_show_only_own_matching_events(self, auth_client, sample_user, sample_vendor):
        """Session and alert history must filter both the owner and event type."""
        from sqlalchemy import text

        rows = [
            (sample_user.id, 'login_success', 'own-session-agent'),
            (sample_user.id, 'login_failed_password', 'own-failed-agent'),
            (sample_vendor.id, 'login_success', 'foreign-session-agent'),
            (sample_vendor.id, 'login_failed_password', 'foreign-failed-agent'),
        ]
        for user_id, action, agent in rows:
            db.session.execute(text(
                "INSERT INTO auth_log (user_id, username, action, user_agent, failure_reason, session_id) "
                "VALUES (:uid, 'workflow', :action, :agent, :agent, :agent)"),
                {'uid': str(user_id), 'action': action, 'agent': agent})
        db.session.commit()
        try:
            sessions = auth_client.get('/account/sessions')
            alerts = auth_client.get('/account/alerts')
            security = auth_client.get('/account/security')
            assert security.status_code == 200
            assert b'own-session-agent' in security.data and b'own-failed-agent' in security.data
            assert b'foreign-session-agent' not in security.data
            assert sessions.status_code == alerts.status_code == 200
            assert b'own-session-agent' in sessions.data
            assert b'own-failed-agent' not in sessions.data
            assert b'own-failed-agent' in alerts.data
            assert b'own-session-agent' not in alerts.data
            assert b'foreign-session-agent' not in sessions.data
            assert b'foreign-failed-agent' not in alerts.data
        finally:
            db.session.execute(text("DELETE FROM auth_log WHERE username = 'workflow'"))
            db.session.commit()

    @pytest.mark.parametrize('path', ['security', 'sessions', 'alerts'])
    def test_audit_read_failure_rolls_back_before_rendering(self, auth_client, monkeypatch, path):
        """PostgreSQL leaves a failed transaction unusable until rollback; SQLite alone cannot prove this."""
        execute = db.session.execute
        rollback = Mock(wraps=db.session.rollback)

        def fail_history(statement, *args, **kwargs):
            if 'FROM auth_log' in str(statement):
                raise RuntimeError('simulated audit read failure')
            return execute(statement, *args, **kwargs)

        monkeypatch.setattr(db.session, 'execute', fail_history)
        monkeypatch.setattr(db.session, 'rollback', rollback)
        assert auth_client.get(f'/account/{path}').status_code == 200
        rollback.assert_called_once_with()
