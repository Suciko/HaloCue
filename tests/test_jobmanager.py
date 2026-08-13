# -*- coding: utf-8 -*-
import sys
import time
from pathlib import Path
from urllib.error import HTTPError

HERE = Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import pytest
from jobs import JobManager
from llm import InsufficientQuotaError


def test_jobmanager_submit_and_get():
    jm = JobManager()

    def sample_task(job):
        job.update_progress(50, "处理中...")
        return {"foo": "bar"}

    job_id = jm.submit(sample_task, label="测试任务")
    assert job_id.startswith("job-") or "-" in job_id

    # 等待完成
    for _ in range(20):
        info = jm.get(job_id)
        if info["state"] in ("succeeded", "failed"):
            break
        time.sleep(0.05)

    info = jm.get(job_id)
    assert info["state"] == "succeeded"
    assert info["result"] == {"foo": "bar"}
    assert info["progress"] == 50


def test_jobmanager_cooperative_cancel():
    jm = JobManager()

    def cancelable_task(job):
        for i in range(10):
            if job.is_cancel_requested():
                job.mark_cancelled()
                return
            time.sleep(0.05)

    job_id = jm.submit(cancelable_task, label="可取消任务")
    time.sleep(0.02)
    cancelled_info = jm.cancel(job_id)
    assert cancelled_info["cancel_requested"] is True

    for _ in range(20):
        info = jm.get(job_id)
        if info["state"] in ("cancelled", "succeeded", "failed"):
            break
        time.sleep(0.05)

    info = jm.get(job_id)
    assert info["state"] == "cancelled"


def test_jobmanager_cleanup():
    jm = JobManager(ttl_seconds=1)

    def quick_task(job):
        return "done"

    job_id = jm.submit(quick_task, label="快任务")
    time.sleep(0.1)

    info = jm.get(job_id)
    assert info["state"] == "succeeded"

    # 等待超过 TTL
    time.sleep(1.1)
    jm.clean_stale_jobs()
    assert jm.get(job_id) is None


def test_job_activity_is_snapshot_and_does_not_pollute_progress_detail():
    jm = JobManager()

    def sample_task(job):
        job.update_progress(25, "正在标注第 1/4 个场景块")
        job.update_activity({
            "state": "receiving",
            "model": "deepseek-v4-flash",
            "received_chars": 2048,
            "elapsed_ms": 7300,
            "untrusted_field": "drop me",
        })
        return {"ok": True}

    job_id = jm.submit(sample_task, label="活动测试")
    for _ in range(20):
        info = jm.get(job_id)
        if info["state"] in ("succeeded", "failed"):
            break
        time.sleep(0.05)

    info = jm.get(job_id)
    assert info["detail"] == "正在标注第 1/4 个场景块"
    assert info["activity"] == {
        "state": "receiving",
        "model": "deepseek-v4-flash",
        "received_chars": 2048,
        "elapsed_ms": 7300,
    }


def test_job_failure_exposes_stable_model_error_metadata_from_cause_chain():
    jm = JobManager()

    def failing_task(_job):
        try:
            try:
                raise HTTPError("https://example.invalid", 403, "Forbidden", {}, None)
            except HTTPError as http_error:
                raise InsufficientQuotaError(
                    "quota-model 接口返回 HTTP 403: 用户额度不足",
                    model="quota-model", http_status=403,
                ) from http_error
        except InsufficientQuotaError as exc:
            raise RuntimeError(f"模型调用失败: {exc}") from exc

    job_id = jm.submit(failing_task, label="额度失败")
    for _ in range(20):
        info = jm.get(job_id)
        if info["state"] == "failed":
            break
        time.sleep(0.05)

    assert info["error_code"] == "insufficient_quota"
    assert info["error_detail"] == {
        "model": "quota-model", "retryable": False, "http_status": 403,
    }


def test_jobmanager_marks_system_exit_as_failed_instead_of_leaving_it_running():
    jm = JobManager()

    job_id = jm.submit(lambda _job: (_ for _ in ()).throw(SystemExit("missing AA path")))
    for _ in range(20):
        info = jm.get(job_id)
        if info["state"] == "failed":
            break
        time.sleep(0.05)

    assert info["state"] == "failed"
    assert "missing AA path" in info["error"]
