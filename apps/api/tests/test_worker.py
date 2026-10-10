import pytest

from app.worker import celery_app, heartbeat, ping


def test_ping_task_runs() -> None:
    assert ping.apply().get() == "pong"


@pytest.mark.integration
def test_heartbeat_is_recorded_for_the_ops_checks() -> None:
    import redis

    from app.modules.ops.checks import HEARTBEAT_KEY
    from app.worker import settings

    beat = heartbeat.apply().get()
    assert beat.endswith("+00:00")
    client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        assert client.get(HEARTBEAT_KEY) == beat
    finally:
        client.close()


def test_worker_refuses_pickle() -> None:
    assert celery_app.conf.accept_content == ["json"]
    assert celery_app.conf.task_serializer == "json"


def test_beat_schedule_tasks_are_registered() -> None:
    for entry in celery_app.conf.beat_schedule.values():
        assert entry["task"] in celery_app.tasks


@pytest.mark.integration
def test_broker_reachable() -> None:
    with celery_app.connection_for_write() as conn:
        conn.ensure_connection(max_retries=1)
