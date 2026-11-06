"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Celery wrapper around app/jobs.py (docker-compose deployment)

This module used to define the jobs itself, as `@celery.task` functions under a
module-level `celery = None` -- which raised AttributeError on import. Nothing
imported it, so nothing noticed, and not one of the tasks ever ran.

Now it only registers the plain functions from app/jobs.py as Celery tasks and
builds the beat schedule from the same registry, so the two deployments cannot
drift apart. The live server does not use Celery at all; it runs the same jobs
through `flask run-job` from systemd timers (deploy/systemd/).

Entry point for the worker and beat: celery_worker.py at the repository root.
"""

from celery.schedules import crontab

from app.jobs import JOBS

SCHEDULES = {
    'hourly': crontab(minute=7),
    'daily': crontab(hour=3, minute=17),
}


def init_celery(app, celery):
    """Register every job as task `jobs.<name>`, run inside `app`, and schedule it."""
    celery.conf.update(
        broker_url=app.config.get('CELERY_BROKER_URL'),
        result_backend=app.config.get('CELERY_RESULT_BACKEND'),
    )

    for name in JOBS:
        celery.task(name=f'jobs.{name}')(_task_for(app, name))

    celery.conf.beat_schedule = {
        name: {'task': f'jobs.{name}', 'schedule': SCHEDULES[job.schedule]}
        for name, job in JOBS.items()
    }
    return celery


def _task_for(app, name):
    """
    A named function per job (Celery builds its task signature from the
    function, a lambda is refused). The job is looked up at call time, so the
    task always runs what the registry says -- and a test can substitute one.
    """
    def task():
        with app.app_context():
            return JOBS[name].func()
    task.__name__ = name.replace('-', '_')
    task.__qualname__ = task.__name__
    return task
