"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
How DB_ENCRYPTION_KEY reaches encrypt_data()/decrypt_data() (plan 2026-11, C1).

The pgcrypto functions read app.encryption_key from the session. The key is
passed in the connection's startup options -- not in a SET or set_config()
statement, which log_statement, auto_explain and pg_stat_activity would keep.
These checks pin that route; tests/test_postgres.py checks that it works.
"""

import pytest


@pytest.mark.parametrize('raw, escaped', [
    ('plain', 'plain'),
    ('with space', 'with\\ space'),
    ('back\\slash', 'back\\\\slash'),
    ('tab\tand\nnewline', 'tab\\\tand\\\nnewline'),
])
def test_option_value_escaping(raw, escaped):
    from app import _libpq_option_value
    assert _libpq_option_value(raw) == escaped


def _apply(uri, key='k3y with space', engine_options=None):
    from flask import Flask

    from app import _pass_db_encryption_key
    app = Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI=uri, DB_ENCRYPTION_KEY=key)
    if engine_options is not None:
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = engine_options
    _pass_db_encryption_key(app)
    return app.config.get('SQLALCHEMY_ENGINE_OPTIONS')


def test_postgres_connections_get_the_key_as_startup_option():
    options = _apply('postgresql://u:p@h/db')
    assert options['connect_args']['options'] == '-c app.encryption_key=k3y\\ with\\ space'


def test_existing_connect_args_are_kept():
    options = _apply('postgresql://u:p@h/db', key='k', engine_options={
        'pool_size': 3, 'connect_args': {'sslmode': 'prefer', 'options': '-c statement_timeout=5s'}})
    assert options['pool_size'] == 3
    assert options['connect_args']['sslmode'] == 'prefer'
    assert options['connect_args']['options'] == '-c statement_timeout=5s -c app.encryption_key=k'


def test_the_shared_config_dict_is_not_mutated():
    shared = {'connect_args': {'sslmode': 'prefer'}}
    _apply('postgresql://u:p@h/db', key='k', engine_options=shared)
    assert shared == {'connect_args': {'sslmode': 'prefer'}}


def test_sqlite_is_left_alone():
    assert _apply('sqlite:///:memory:', engine_options={}) == {}


def _code_strings_and_calls():
    """String literals and called names in app/__init__.py -- docstrings excluded."""
    import ast
    import inspect

    import app as app_module
    tree = ast.parse(inspect.getsource(app_module))
    docstrings = {id(node.body[0].value) for node in ast.walk(tree)
                  if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef))
                  and node.body and isinstance(node.body[0], ast.Expr)
                  and isinstance(node.body[0].value, ast.Constant)}
    strings = [n.value for n in ast.walk(tree)
               if isinstance(n, ast.Constant) and isinstance(n.value, str)
               and id(n) not in docstrings]
    return strings


def test_no_connect_listener_sends_the_key_as_sql():
    """The rejected alternative: SET/set_config in a 'connect' event."""
    strings = _code_strings_and_calls()
    assert not any('set_config' in s or 'SET app.' in s for s in strings)
    assert 'connect' not in strings
