from datetime import datetime, timezone

from marten_runtime.execution.models import JobRecord


def recover_expired_leases(items: list[JobRecord], now_ts: int) -> list[str]:
    recovered: list[str] = []
    for item in items:
        if item.state == "running" and item.lease_expires_at and item.lease_expires_at < now_ts:
            item.state = "queued"
            item.attempt += 1
            item.updated_at = datetime.now(timezone.utc)
            recovered.append(item.job_id)
    return recovered
