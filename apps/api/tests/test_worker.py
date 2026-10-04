import pytest

from app.worker import celery_app, heartbeat, ping


def test_ping_task_runs() -> None:
    assert ping.apply().get() == "pong"


def test_heartbeat_returns_utc_timestamp() -> None:
    assert heartbeat.apply().get().endswith("+00:00")


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
