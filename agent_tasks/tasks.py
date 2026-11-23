"""Celery tasks. They run on their own queue (`browser`): the default worker
has one slot and carries money work."""
from celery import shared_task


@shared_task(name='agent_tasks.step', ignore_result=True, soft_time_limit=170, time_limit=178)
def step(task_id, turn=None):
    from . import runner
    runner.run_step(task_id, turn)


@shared_task(name='agent_tasks.sweep', ignore_result=True, soft_time_limit=100, time_limit=110)
def sweep():
    from . import service
    service.sweep()
