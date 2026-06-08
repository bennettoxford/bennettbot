import json
from contextlib import closing
from datetime import UTC, datetime, timedelta

from .connection import get_connection
from .logger import log_call


@log_call
def schedule_job(
    type_, args, channel, thread_ts, delay_seconds, is_im=False, message_ts=None
):
    """Schedule job to be run.

    Only one job with a given (type, args) combination may be scheduled.  If
    a matching job is already scheduled but isn't running yet and another job
    with the same (type, args) is scheduled, the record of the first job is
    updated.

    Jobs with the same type but different args are treated as independent and
    coexist in the queue.  The dispatcher still only runs one job per type at
    a time (see reserve_job), so they execute serially.

    `message_ts` is the timestamp of the Slack message that triggered the job,
    so the dispatcher can react to it on completion. May be None for
    automated/scheduled jobs that have no originating message.

    Returns a boolean indicating whether an existing job was already running.
    """

    start_after = _now() + timedelta(seconds=delay_seconds)
    args = json.dumps(args, sort_keys=True)

    sql = """
    SELECT id, args, started_at IS NOT NULL AS has_started
    FROM job
    WHERE type = ?
    ORDER BY has_started
    """

    with closing(get_connection()) as conn:
        with conn:
            same_type_jobs = list(conn.execute(sql, [type_]))

        # Do we have a running job of the same type (irrespective of args)?
        existing_job_type_running = any(j["has_started"] for j in same_type_jobs)
        # Find matching jobs including args
        matching_jobs = [j for j in same_type_jobs if j["args"] == args]

        match len(matching_jobs):
            case 0:
                _create_job(
                    conn,
                    type_,
                    args,
                    channel,
                    thread_ts,
                    message_ts,
                    start_after,
                    is_im,
                )
            case 1:
                job = matching_jobs[0]
                if job["has_started"]:
                    _create_job(
                        conn,
                        type_,
                        args,
                        channel,
                        thread_ts,
                        message_ts,
                        start_after,
                        is_im,
                    )
                else:
                    _update_job(
                        conn,
                        job["id"],
                        args,
                        channel,
                        thread_ts,
                        message_ts,
                        start_after,
                    )
            case 2:
                # We order by has_started ASC, and we can only have one matching job running
                # Update the not-running job (always the first one) with the current requested job
                # sanity check
                assert not matching_jobs[0]["has_started"]
                assert matching_jobs[1]["has_started"]
                _update_job(
                    conn,
                    matching_jobs[0]["id"],
                    args,
                    channel,
                    thread_ts,
                    message_ts,
                    start_after,
                )
            case _:  # pragma: no cover
                assert False

    return existing_job_type_running


def _create_job(conn, type_, args, channel, thread_ts, message_ts, start_after, is_im):
    with conn:
        conn.execute(
            "INSERT INTO job (type, args, channel, thread_ts, message_ts, start_after, is_im) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [type_, args, channel, thread_ts, message_ts, start_after, is_im],
        )


def _update_job(conn, id_, args, channel, thread_ts, message_ts, start_after):
    with conn:
        conn.execute(
            "UPDATE job SET args = ?, channel = ?, thread_ts = ?, message_ts = ?, start_after = ? WHERE id = ?",
            [args, channel, thread_ts, message_ts, start_after, id_],
        )


@log_call
def cancel_job(type_):
    """Cancel scheduled job of given type."""

    with closing(get_connection()) as conn:
        with conn:
            conn.execute(
                "DELETE FROM job WHERE type = ? AND started_at IS NULL", [type_]
            )


@log_call
def schedule_suppression(job_type, start_at, end_at):
    """Schedule suppression for jobs of given type."""

    with closing(get_connection()) as conn:
        with conn:
            conn.execute(
                "INSERT INTO suppression (job_type, start_at, end_at) VALUES (?, ?, ?)",
                [job_type, start_at, end_at],
            )


@log_call
def cancel_suppressions(job_type):
    """Cancel suppressions for jobs of given type."""

    with closing(get_connection()) as conn:
        with conn:
            conn.execute("DELETE FROM suppression WHERE job_type = ?", [job_type])


# @log_call
def remove_expired_suppressions():
    """Remove expired suppressions.

    This is not logged because it is called every second by the dispatcher.
    """

    with closing(get_connection()) as conn:
        with conn:
            conn.execute("DELETE FROM suppression WHERE end_at < ?", [_now()])


# @log_call
def reserve_job():
    """Reserve a job and return its id.

    The first job where:

        * there is not a running job of the same type
        * there is no active suppression

    is reserved.  This updates the started_at column on the database record.

    This is not logged because it is called every second by the dispatcher.
    """

    sql = """
    WITH running_job_types AS (
        SELECT type
        FROM job
        WHERE started_at IS NOT NULL
    ),

    suppressed_job_types AS (
        SELECT job_type
        FROM suppression
        WHERE start_at < ?
    )

    SELECT id
    FROM job
    WHERE
          type NOT IN (SELECT * FROM suppressed_job_types)
      AND type NOT IN (SELECT * FROM running_job_types)
      AND started_at IS NULL
      AND start_after <= ?
    ORDER BY start_after
    LIMIT 1
    """

    now = _now()
    with closing(get_connection()) as conn:
        with conn:
            results = list(conn.execute(sql, [now, now]))

        if not results:
            return None

        job_id = results[0]["id"]
        with conn:
            conn.execute("UPDATE job SET started_at = ? WHERE id = ?", [now, job_id])
    return job_id


@log_call
def mark_job_done(job_id):
    """Remove job from job table."""

    with closing(get_connection()) as conn:
        with conn:
            conn.execute("DELETE FROM job WHERE id = ?", [job_id])


@log_call
def get_job(job_id):
    """Retrieve job from job table."""

    with closing(get_connection()) as conn:
        with conn:
            job = list(conn.execute("SELECT * FROM job WHERE id = ?", [job_id]))[0]
    _convert_job_args_from_json(job)
    return job


@log_call
def get_jobs():
    """Retrieve all jobs from job table."""

    with closing(get_connection()) as conn:
        with conn:
            jobs = list(conn.execute("SELECT * FROM job ORDER BY id"))
    for job in jobs:
        _convert_job_args_from_json(job)
    return jobs


@log_call
def get_jobs_of_type(type_):
    """Retrieve all jobs of given type from job table."""

    with closing(get_connection()) as conn:
        with conn:
            jobs = list(
                conn.execute("SELECT * FROM job WHERE type = ? ORDER BY id", [type_])
            )
    for job in jobs:
        _convert_job_args_from_json(job)
    return jobs


@log_call
def get_suppressions():
    """Retrieve all suppressions from job table."""

    with closing(get_connection()) as conn:
        with conn:
            suppressions = list(conn.execute("SELECT * FROM suppression ORDER BY id"))
        return suppressions


def _now():
    return datetime.now(UTC)


def _convert_job_args_from_json(job):
    job["args"] = json.loads(job["args"])
