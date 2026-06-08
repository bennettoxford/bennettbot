import sqlite3
from contextlib import closing

import pytest

from bennettbot import scheduler, settings
from bennettbot.connection import get_connection

from .assertions import (
    assert_job_matches,
    assert_no_running_job,
    assert_running_job,
    assert_suppression_matches,
)
from .time_helpers import T0, TS, T


# Make sure all tests run when datetime.now() returning T0
pytestmark = pytest.mark.freeze_time(T0)


def test_schedule_job_with_no_jobs_already_scheduled():
    assert_no_running_job(
        scheduler.schedule_job("good_job", {"k": "v"}, "channel", TS, 0)
    )

    jj = scheduler.get_jobs_of_type("good_job")
    assert len(jj) == 1
    assert_job_matches(jj[0], "good_job", {"k": "v"}, "channel", T(0), None)


def test_schedule_job_with_no_jobs_of_same_type_already_scheduled():
    assert_no_running_job(
        scheduler.schedule_job("odd_job", {"k": "v"}, "channel", TS, 0)
    )

    assert_no_running_job(
        scheduler.schedule_job("good_job", {"k": "v"}, "channel", TS, 0)
    )

    jj = scheduler.get_jobs_of_type("good_job")
    assert len(jj) == 1
    assert_job_matches(jj[0], "good_job", {"k": "v"}, "channel", T(0), None)


def test_schedule_job_with_same_type_and_args_scheduled_overwrites():
    assert_no_running_job(
        scheduler.schedule_job("good_job", {"k": "v"}, "channel", TS, 0)
    )
    assert_no_running_job(
        scheduler.schedule_job("good_job", {"k": "v"}, "channel1", TS, 10)
    )

    jj = scheduler.get_jobs_of_type("good_job")
    assert len(jj) == 1
    assert_job_matches(jj[0], "good_job", {"k": "v"}, "channel1", T(10), None)


def test_schedule_job_with_same_type_different_args_scheduled_coexists():
    assert_no_running_job(
        scheduler.schedule_job("good_job", {"k": "v"}, "channel", TS, 0)
    )
    assert_no_running_job(
        scheduler.schedule_job("good_job", {"k": "w"}, "channel1", TS, 10)
    )

    jj = scheduler.get_jobs_of_type("good_job")
    assert len(jj) == 2
    assert_job_matches(jj[0], "good_job", {"k": "v"}, "channel", T(0), None)
    assert_job_matches(jj[1], "good_job", {"k": "w"}, "channel1", T(10), None)


def test_schedule_job_args_match_ignores_dict_key_order():
    assert_no_running_job(
        scheduler.schedule_job("good_job", {"a": 1, "b": 2}, "channel", TS, 0)
    )
    assert_no_running_job(
        scheduler.schedule_job("good_job", {"b": 2, "a": 1}, "channel1", TS, 10)
    )

    jj = scheduler.get_jobs_of_type("good_job")
    assert len(jj) == 1
    assert_job_matches(jj[0], "good_job", {"a": 1, "b": 2}, "channel1", T(10), None)


def test_schedule_job_with_job_of_same_type_running(freezer):
    assert_no_running_job(
        scheduler.schedule_job("good_job", {"k": "v"}, "channel", TS, 0)
    )
    freezer.move_to(T(5))
    scheduler.reserve_job()

    assert_running_job(
        scheduler.schedule_job("good_job", {"k": "w"}, "channel1", TS, 5)
    )

    jj = scheduler.get_jobs_of_type("good_job")
    assert len(jj) == 2
    assert_job_matches(jj[0], "good_job", {"k": "v"}, "channel", T(0), T(5))
    assert_job_matches(jj[1], "good_job", {"k": "w"}, "channel1", T(10), None)


def test_schedule_job_with_job_of_different_type_running(freezer):
    assert_no_running_job(
        scheduler.schedule_job("good_job", {"k": "v"}, "channel", TS, 0)
    )

    freezer.move_to(T(5))
    scheduler.reserve_job()

    jj = scheduler.get_jobs_of_type("good_job")
    assert len(jj) == 1

    assert_no_running_job(
        scheduler.schedule_job("odd_job", {"k": "v"}, "channel", TS, 0)
    )


def test_schedule_job_with_job_of_same_type_running_and_another_scheduled(freezer):
    scheduler.schedule_job("good_job", {"k": "v"}, "channel", TS, 0)
    freezer.move_to(T(5))
    scheduler.reserve_job()
    assert_running_job(
        scheduler.schedule_job("good_job", {"k": "w"}, "channel1", TS, 5)
    )

    assert_running_job(
        scheduler.schedule_job("good_job", ["args2"], "channel2", TS, 15)
    )
    jj = scheduler.get_jobs_of_type("good_job")
    assert len(jj) == 3
    assert_job_matches(jj[0], "good_job", {"k": "v"}, "channel", T(0), T(5))
    assert_job_matches(jj[1], "good_job", {"k": "w"}, "channel1", T(10), None)
    assert_job_matches(jj[2], "good_job", ["args2"], "channel2", T(20), None)


def test_schedule_job_with_running_and_pending_same_args_updates_pending(freezer):
    scheduler.schedule_job("good_job", {"k": "v"}, "channel", TS, 0)
    freezer.move_to(T(5))
    scheduler.reserve_job()
    assert_running_job(
        scheduler.schedule_job("good_job", {"k": "w"}, "channel1", TS, 5)
    )

    assert_running_job(
        scheduler.schedule_job("good_job", {"k": "w"}, "channel2", TS, 15)
    )
    jj = scheduler.get_jobs_of_type("good_job")
    assert len(jj) == 2
    assert_job_matches(jj[0], "good_job", {"k": "v"}, "channel", T(0), T(5))
    assert_job_matches(jj[1], "good_job", {"k": "w"}, "channel2", T(20), None)


def test_schedule_job_with_same_args_running_and_pending_updates_pending(freezer):
    scheduler.schedule_job("good_job", {"k": "v"}, "channel", TS, 0)
    freezer.move_to(T(5))
    scheduler.reserve_job()
    assert_running_job(
        scheduler.schedule_job("good_job", {"k": "v"}, "channel1", TS, 5)
    )

    assert_running_job(
        scheduler.schedule_job("good_job", {"k": "v"}, "channel2", TS, 15)
    )
    jj = scheduler.get_jobs_of_type("good_job")
    assert len(jj) == 2
    assert_job_matches(jj[0], "good_job", {"k": "v"}, "channel", T(0), T(5))
    assert_job_matches(jj[1], "good_job", {"k": "v"}, "channel2", T(20), None)


def test_cancel_job_with_no_jobs_of_same_type_scheduled():
    scheduler.schedule_job("odd_job", {"k": "v"}, "channel", TS, 0)

    scheduler.cancel_job("good_job")

    jj = scheduler.get_jobs_of_type("odd_job")
    assert len(jj) == 1


def test_cancel_job_with_job_scheduled():
    scheduler.schedule_job("good_job", {"k": "v"}, "channel", TS, 0)

    scheduler.cancel_job("good_job")

    jj = scheduler.get_jobs_of_type("good_job")
    assert len(jj) == 0


def test_cancel_job_with_job_running(freezer):
    scheduler.schedule_job("good_job", {"k": "v"}, "channel", TS, 0)
    freezer.move_to(T(5))
    scheduler.reserve_job()

    scheduler.cancel_job("good_job")

    jj = scheduler.get_jobs_of_type("good_job")
    assert len(jj) == 1


def test_cancel_job_with_job_running_and_another_scheduled(freezer):
    scheduler.schedule_job("good_job", {"k": "v"}, "channel", TS, 0)
    freezer.move_to(T(5))
    scheduler.reserve_job()
    scheduler.schedule_job("good_job", {"k": "v"}, "channel", TS, 0)

    scheduler.cancel_job("good_job")

    jj = scheduler.get_jobs_of_type("good_job")
    assert len(jj) == 1


def test_schedule_suppression():
    scheduler.schedule_suppression("good_job", T(5), T(15))
    scheduler.schedule_suppression("odd_job", T(10), T(20))
    scheduler.schedule_suppression("good_job", T(20), T(30))

    ss = scheduler.get_suppressions()
    assert len(ss) == 3
    assert_suppression_matches(ss[0], "good_job", T(5), T(15))
    assert_suppression_matches(ss[1], "odd_job", T(10), T(20))
    assert_suppression_matches(ss[2], "good_job", T(20), T(30))


def test_cancel_suppressions():
    scheduler.schedule_suppression("good_job", T(5), T(15))
    scheduler.schedule_suppression("odd_job", T(10), T(20))
    scheduler.schedule_suppression("good_job", T(20), T(30))

    scheduler.cancel_suppressions("good_job")

    ss = scheduler.get_suppressions()
    assert len(ss) == 1
    assert_suppression_matches(ss[0], "odd_job", T(10), T(20))


def test_remove_expired_suppressions(freezer):
    scheduler.schedule_suppression("good_job", T(5), T(15))
    scheduler.schedule_suppression("odd_job", T(10), T(20))
    scheduler.schedule_suppression("good_job", T(20), T(30))
    freezer.move_to(T(17))

    scheduler.remove_expired_suppressions()

    ss = scheduler.get_suppressions()
    assert len(ss) == 2
    assert_suppression_matches(ss[0], "odd_job", T(10), T(20))
    assert_suppression_matches(ss[1], "good_job", T(20), T(30))


def test_reserve_job_with_no_jobs_scheduled():
    assert not scheduler.reserve_job()


def test_reserve_job_with_no_jobs_due_to_run():
    scheduler.schedule_job("good_job", {"k": "v"}, "channel", TS, 5)

    assert not scheduler.reserve_job()


def test_reserve_job_with_one_job_due_to_run(freezer):
    scheduler.schedule_job("good_job", {"k": "v"}, "channel", TS, 5)
    freezer.move_to(T(10))

    job_id = scheduler.reserve_job()
    job = scheduler.get_job(job_id)
    assert_job_matches(job, "good_job", {"k": "v"}, "channel", T(5), T(10))


def test_reserve_job_with_two_jobs_due_to_run(freezer):
    scheduler.schedule_job("good_job", {"k": "v"}, "channel", TS, 5)
    scheduler.schedule_job("odd_job", {"k": "v"}, "channel", TS, 6)
    freezer.move_to(T(10))

    job_id = scheduler.reserve_job()
    job = scheduler.get_job(job_id)
    assert_job_matches(job, "good_job", {"k": "v"}, "channel", T(5), T(10))

    job_id = scheduler.reserve_job()
    job = scheduler.get_job(job_id)
    assert_job_matches(job, "odd_job", {"k": "v"}, "channel", T(6), T(10))


def test_reserve_job_with_job_running(freezer):
    scheduler.schedule_job("good_job", {"k": "v"}, "channel", TS, 5)
    freezer.move_to(T(10))
    scheduler.reserve_job()
    scheduler.schedule_job("good_job", {"k": "w"}, "channel1", TS, 5)
    freezer.move_to(T(20))

    assert not scheduler.reserve_job()


def test_reserve_job_with_another_job_running(freezer):
    scheduler.schedule_job("good_job", {"k": "v"}, "channel", TS, 5)
    freezer.move_to(T(10))
    scheduler.reserve_job()
    scheduler.schedule_job("odd_job", {"k": "w"}, "channel1", TS, 5)
    freezer.move_to(T(20))

    job_id = scheduler.reserve_job()
    job = scheduler.get_job(job_id)
    assert_job_matches(job, "odd_job", {"k": "w"}, "channel1", T(15), T(20))


def test_reserve_job_with_suppression_in_progress(freezer):
    scheduler.schedule_job("good_job", {"k": "v"}, "channel", TS, 5)
    scheduler.schedule_suppression("good_job", T(10), T(20))
    freezer.move_to(T(15))

    assert not scheduler.reserve_job()


def test_reserve_job_with_suppression_in_progress_for_another_job_type(freezer):
    scheduler.schedule_job("good_job", {"k": "v"}, "channel", TS, 5)
    scheduler.schedule_suppression("odd_job", T(10), T(20))
    freezer.move_to(T(15))

    job_id = scheduler.reserve_job()
    job = scheduler.get_job(job_id)
    assert_job_matches(job, "good_job", {"k": "v"}, "channel", T(5), T(15))


def test_reserve_job_with_suppression_in_future(freezer):
    scheduler.schedule_suppression("good_job", T(15), T(20))
    scheduler.schedule_job("good_job", {"k": "v"}, "channel", TS, 5)
    freezer.move_to(T(10))

    job_id = scheduler.reserve_job()
    job = scheduler.get_job(job_id)
    assert_job_matches(job, "good_job", {"k": "v"}, "channel", T(5), T(10))


def test_mark_job_done(freezer):
    scheduler.schedule_job("good_job", {"k": "v"}, "channel", TS, 0)
    freezer.move_to(T(10))
    job_id = scheduler.reserve_job()

    scheduler.mark_job_done(job_id)

    assert not scheduler.get_jobs()


def test_get_connection_adds_message_ts_to_legacy_table():
    """Pre-message_ts job tables should be migrated on connection."""
    with closing(sqlite3.connect(settings.DB_PATH)) as conn:
        conn.execute(
            """
            CREATE TABLE job (
                id INTEGER PRIMARY KEY,
                type TEXT NOT NULL,
                args TEXT,
                channel TEXT,
                thread_ts TEXT,
                start_after DATETIME,
                started_at DATETIME,
                is_im BOOLEAN
            )
            """
        )
        conn.commit()
    with closing(get_connection()) as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(job)")}
    assert "message_ts" in columns


def test_schedule_job_with_message_ts():
    scheduler.schedule_job("good_job", {"k": "v"}, "channel", TS, 0, message_ts="42.42")
    jobs = scheduler.get_jobs_of_type("good_job")
    assert jobs[0]["message_ts"] == "42.42"
