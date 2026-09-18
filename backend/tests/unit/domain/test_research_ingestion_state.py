"""Ingestion state machine contract.

Spec 7.2 and 19: only the documented forward path plus retry/cancel edges exist,
only the current attempt holding an unexpired lease can advance state, and a late
result from a superseded attempt must not touch the job at all.
"""

from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError
from sector_pulse.domain.research_library.ingestion import (
    INGESTION_TRANSITIONS,
    IngestionLeaseLost,
    IngestionStatus,
    InvalidIngestionTransition,
    acquire_ingestion_lease,
    is_terminal,
    transition_ingestion,
)
from sector_pulse.domain.research_library.models import IngestionJob

from backend.tests.research_library_support import NOW, job_payload

LEASE_SECONDS = 300


def leased_job(status: IngestionStatus = IngestionStatus.RECEIVED) -> IngestionJob:
    job = IngestionJob.model_validate(job_payload(status=status.value))
    return acquire_ingestion_lease(job, now=NOW, worker_id="worker-1", lease_seconds=LEASE_SECONDS)


def advance_to(target: IngestionStatus, *, worker_id: str = "worker-1", attempt: int = 1):
    """Walk the documented forward path until `target` is reached."""
    job = leased_job()
    now = NOW
    for status in (
        IngestionStatus.VALIDATING,
        IngestionStatus.PARSING,
        IngestionStatus.NORMALIZING,
        IngestionStatus.CHUNKING,
        IngestionStatus.EMBEDDING,
        IngestionStatus.INDEXING,
        IngestionStatus.VERIFYING,
        IngestionStatus.PUBLISHED,
    ):
        now += timedelta(seconds=1)
        job = transition_ingestion(job, status, now, worker_id, attempt)
        if status is target:
            return job
    raise AssertionError(f"unreachable target: {target}")


def test_ingestion_cannot_publish_before_verification():
    job = leased_job()
    with pytest.raises(InvalidIngestionTransition):
        transition_ingestion(job, IngestionStatus.PUBLISHED, NOW, "worker-1", 1)


def test_forward_path_reaches_published_one_stage_at_a_time():
    job = advance_to(IngestionStatus.PUBLISHED)
    assert job.status is IngestionStatus.PUBLISHED
    assert job.attempt_id == 1


def test_transition_returns_a_new_job_and_leaves_the_original_untouched():
    job = leased_job()
    moved = transition_ingestion(job, IngestionStatus.VALIDATING, NOW, "worker-1", 1)
    assert moved.status is IngestionStatus.VALIDATING
    assert job.status is IngestionStatus.RECEIVED


def test_skipping_a_stage_is_rejected():
    job = leased_job()
    with pytest.raises(InvalidIngestionTransition):
        transition_ingestion(job, IngestionStatus.CHUNKING, NOW, "worker-1", 1)


@pytest.mark.parametrize(
    "terminal",
    [IngestionStatus.PUBLISHED, IngestionStatus.PERMANENT_FAILED, IngestionStatus.CANCELLED],
)
def test_terminal_states_have_no_outgoing_transition(terminal):
    assert INGESTION_TRANSITIONS[terminal] == frozenset()
    assert is_terminal(terminal) is True


@pytest.mark.parametrize(
    "stage",
    [
        IngestionStatus.VALIDATING,
        IngestionStatus.PARSING,
        IngestionStatus.NORMALIZING,
        IngestionStatus.CHUNKING,
        IngestionStatus.EMBEDDING,
        IngestionStatus.INDEXING,
        IngestionStatus.VERIFYING,
    ],
)
def test_every_pipeline_stage_reports_retryable_failure(stage):
    assert IngestionStatus.RETRYABLE_FAILED in INGESTION_TRANSITIONS[stage]


def test_retryable_failure_can_resume_at_a_pipeline_stage():
    job = advance_to(IngestionStatus.PARSING)
    failed = transition_ingestion(
        job,
        IngestionStatus.RETRYABLE_FAILED,
        NOW + timedelta(seconds=2),
        "worker-1",
        1,
        reason="pdf worker timed out",
    )
    assert failed.status is IngestionStatus.RETRYABLE_FAILED
    assert failed.failure_reason == "pdf worker timed out"
    resumed = transition_ingestion(
        failed,
        IngestionStatus.PARSING,
        NOW + timedelta(seconds=3),
        "worker-1",
        1,
    )
    assert resumed.status is IngestionStatus.PARSING


def test_resuming_a_retryable_failure_clears_the_previous_failure_reason():
    """回到流水线里的任务不再处于失败状态，因此不该继续带着上一次的失败原因。

    这条断言看着像吹毛求疵，其实是一条会漏掉的约束：`IngestionJob` 自己就拒绝"非失败状态
    带着 failure_reason"，但 `transition_ingestion` 用 `model_copy` 造新任务，而 Pydantic
    的 `model_copy` **不跑校验器**。于是不合法的任务在这里被安静地造出来，一路走到数据库才
    被 CHECK 顶回来——而那时它已经被翻译成"写入输给了并发者"，重试也就永远停在原地。
    """
    job = advance_to(IngestionStatus.PARSING)
    failed = transition_ingestion(
        job,
        IngestionStatus.RETRYABLE_FAILED,
        NOW + timedelta(seconds=2),
        "worker-1",
        1,
        reason="pdf worker timed out",
    )

    resumed = transition_ingestion(
        failed,
        IngestionStatus.PARSING,
        NOW + timedelta(seconds=3),
        "worker-1",
        1,
    )

    assert resumed.failure_reason is None
    # 重新校验一次：`model_copy` 不会替我们做这件事，而数据库会。
    assert IngestionJob.model_validate(resumed.model_dump()) == resumed


def test_cancelling_a_failed_job_also_clears_the_failure_reason():
    """取消不是失败状态，所以同一个理由也成立。"""
    job = advance_to(IngestionStatus.PARSING)
    failed = transition_ingestion(
        job,
        IngestionStatus.RETRYABLE_FAILED,
        NOW + timedelta(seconds=2),
        "worker-1",
        1,
        reason="pdf worker timed out",
    )

    cancelled = transition_ingestion(
        failed, IngestionStatus.CANCELLED, NOW + timedelta(seconds=3), "worker-1", 1
    )

    assert cancelled.failure_reason is None
    assert IngestionJob.model_validate(cancelled.model_dump()) == cancelled


def test_a_permanent_failure_keeps_the_reason_it_was_given():
    """两个失败状态之间迁移时，原因换成新的那一个，而不是被清掉。"""
    job = advance_to(IngestionStatus.PARSING)
    failed = transition_ingestion(
        job,
        IngestionStatus.RETRYABLE_FAILED,
        NOW + timedelta(seconds=2),
        "worker-1",
        1,
        reason="pdf worker timed out",
    )

    permanent = transition_ingestion(
        failed,
        IngestionStatus.PERMANENT_FAILED,
        NOW + timedelta(seconds=3),
        "worker-1",
        1,
        reason="no attempt left after 3",
    )

    assert permanent.failure_reason == "no attempt left after 3"


def test_failure_transition_must_state_a_reason():
    job = advance_to(IngestionStatus.PARSING)
    with pytest.raises(ValueError, match="failure reason"):
        transition_ingestion(
            job, IngestionStatus.RETRYABLE_FAILED, NOW + timedelta(seconds=2), "worker-1", 1
        )


def test_retryable_failure_can_become_permanent_when_attempts_are_exhausted():
    job = advance_to(IngestionStatus.PARSING)
    failed = transition_ingestion(
        job,
        IngestionStatus.RETRYABLE_FAILED,
        NOW + timedelta(seconds=2),
        "worker-1",
        1,
        reason="pdf worker timed out",
    )
    terminal = transition_ingestion(
        failed,
        IngestionStatus.PERMANENT_FAILED,
        NOW + timedelta(seconds=3),
        "worker-1",
        1,
        reason="attempt budget exhausted",
    )
    assert terminal.status is IngestionStatus.PERMANENT_FAILED
    assert terminal.worker_id is None
    assert terminal.lease_expires_at is None


def test_stale_attempt_cannot_advance_the_job():
    job = leased_job()
    with pytest.raises(IngestionLeaseLost, match="attempt"):
        transition_ingestion(job, IngestionStatus.VALIDATING, NOW, "worker-1", 2)


def test_a_different_worker_cannot_advance_a_leased_job():
    job = leased_job()
    with pytest.raises(IngestionLeaseLost, match="worker"):
        transition_ingestion(job, IngestionStatus.VALIDATING, NOW, "worker-2", 1)


def test_expired_lease_cannot_advance_the_job():
    job = leased_job()
    after_expiry = NOW + timedelta(seconds=LEASE_SECONDS + 1)
    with pytest.raises(IngestionLeaseLost, match="lease"):
        transition_ingestion(job, IngestionStatus.VALIDATING, after_expiry, "worker-1", 1)


def test_expired_lease_allows_takeover_with_a_new_attempt():
    job = advance_to(IngestionStatus.PARSING)
    after_expiry = NOW + timedelta(seconds=LEASE_SECONDS + 5)
    taken_over = acquire_ingestion_lease(
        job, now=after_expiry, worker_id="worker-2", lease_seconds=LEASE_SECONDS
    )
    assert taken_over.attempt_id == job.attempt_id + 1
    assert taken_over.worker_id == "worker-2"

    late = transition_ingestion(
        taken_over, IngestionStatus.NORMALIZING, after_expiry, "worker-2", taken_over.attempt_id
    )
    assert late.status is IngestionStatus.NORMALIZING
    with pytest.raises(IngestionLeaseLost):
        transition_ingestion(taken_over, IngestionStatus.NORMALIZING, after_expiry, "worker-1", 1)


def test_live_lease_cannot_be_taken_over():
    job = leased_job()
    with pytest.raises(IngestionLeaseLost, match="lease"):
        acquire_ingestion_lease(
            job, now=NOW + timedelta(seconds=10), worker_id="worker-2", lease_seconds=LEASE_SECONDS
        )


def test_terminal_job_cannot_be_leased_again():
    job = advance_to(IngestionStatus.PUBLISHED)
    with pytest.raises(InvalidIngestionTransition):
        acquire_ingestion_lease(
            job,
            now=NOW + timedelta(seconds=LEASE_SECONDS + 60),
            worker_id="worker-3",
            lease_seconds=LEASE_SECONDS,
        )


def test_cancellation_needs_no_lease_because_a_user_requests_it():
    job = leased_job()
    cancelled = transition_ingestion(job, IngestionStatus.CANCELLED, NOW, "user_1", 0)
    assert cancelled.status is IngestionStatus.CANCELLED


def test_cancelled_job_cannot_resume():
    job = transition_ingestion(leased_job(), IngestionStatus.CANCELLED, NOW, "user_1", 0)
    with pytest.raises(InvalidIngestionTransition):
        transition_ingestion(job, IngestionStatus.VALIDATING, NOW, "worker-1", 1)


def test_transition_rejects_naive_now():
    job = leased_job()
    with pytest.raises(ValidationError):
        transition_ingestion(
            job, IngestionStatus.VALIDATING, datetime(2026, 9, 18, 2, 0), "worker-1", 1
        )


def test_job_rejects_a_lease_without_an_owner():
    with pytest.raises(ValidationError, match="lease"):
        IngestionJob.model_validate(
            job_payload(worker_id=None, lease_expires_at=NOW.isoformat(), attempt_id=1)
        )


def test_job_rejects_a_failure_reason_on_a_running_status():
    with pytest.raises(ValidationError, match="failure_reason"):
        IngestionJob.model_validate(job_payload(status="PARSING", failure_reason="boom"))


def test_received_job_has_no_attempt_yet():
    job = IngestionJob.model_validate(job_payload())
    assert job.attempt_id == 0
    assert job.worker_id is None
    assert job.lease_expires_at is None


@pytest.mark.parametrize("status", ["RETRYABLE_FAILED", "PERMANENT_FAILED"])
def test_failed_job_must_state_why(status):
    with pytest.raises(ValidationError, match="failure_reason"):
        IngestionJob.model_validate(job_payload(status=status))
