"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Celery entry point for docker-compose:

    celery -A celery_worker.celery worker
    celery -A celery_worker.celery beat

It used to be `celery -A app.celery`: the bare Celery() instance from
app/__init__.py, with no app, no tasks and no schedule. Workers started, beat
started, and nothing was ever executed.
"""

from app import celery as _celery, create_app
from app.tasks import init_celery

flask_app = create_app()
celery = init_celery(flask_app, _celery)
