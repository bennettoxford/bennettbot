import pytest

from ebmbot import scheduler

from .assertions import assert_job_matches, assert_suppression_matches
from .time_helpers import T0, TS, T

# Make sure all tests run when datetime.now() returning T0
pytestmark = pytest.mark.freeze_time(T0)


def test_schedule_job_with_no_jobs_already_scheduled():
    scheduler.schedule_job("good_job", {"k": "v"}, "channel", TS, 0)

    jj = scheduler.get_jobs_of_type("good_job")
    assert len(jj) == 1
    assert_job_matches(jj[0], "good_job", {"k": "v"}, "channel", T(0), None)


def test_schedule_job_with_no_jobs_of_same_type_already_scheduled():
    scheduler.schedule_job("odd_job", {"k": "v"}, "channel", TS, 0)

    scheduler.schedule_job("good_job", {"k": "v"}, "channel", TS, 0)

    jj = scheduler.get_jobs_of_type("good_job")
    assert len(jj) == 1
    assert_job_matches(jj[0], "good_job", {"k": "v"}, "channel", T(0), None)


def test_schedule_job_with_job_of_same_type_scheduled():
    scheduler.schedule_job("good_job", {"k": "v"}, "channel", TS, 0)

    scheduler.schedule_job("good_job", {"k": "w"}, "channel1", TS, 10)

    jj = scheduler.get_jobs_of_type("good_job")
    assert len(jj) == 1
    assert_job_matches(jj[0], "good_job", {"k": "w"}, "channel1", T(10), None)


def test_schedule_job_with_job_of_same_type_running(freezer):
    scheduler.schedule_job("good_job", {"k": "v"}, "channel", TS, 0)
    freezer.move_to(T(5))
    scheduler.reserve_job()

    scheduler.schedule_job("good_job", {"k": "w"}, "channel1", TS, 5)

    jj = scheduler.get_jobs_of_type("good_job")
    assert len(jj) == 2
    assert_job_matches(jj[0], "good_job", {"k": "v"}, "channel", T(0), T(5))
    assert_job_matches(jj[1], "good_job", {"k": "w"}, "channel1", T(10), None)


def test_schedule_job_with_job_of_same_type_running_and_another_scheduled(freezer):
    scheduler.schedule_job("good_job", {"k": "v"}, "channel", TS, 0)
    freezer.move_to(T(5))
    scheduler.reserve_job()
    scheduler.schedule_job("good_job", {"k": "w"}, "channel1", TS, 5)

    scheduler.schedule_job("good_job", ["args2"], "channel2", TS, 15)

    jj = scheduler.get_jobs_of_type("good_job")
    assert len(jj) == 2
    assert_job_matches(jj[0], "good_job", {"k": "v"}, "channel", T(0), T(5))
    assert_job_matches(jj[1], "good_job", ["args2"], "channel2", T(20), None)


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
