from pydantic import BaseModel


class DeliveryState(BaseModel):
    delivered: bool
    event_type: str
    run_id: str
    trace_id: str
    reason: str = ""


def finalize_delivery(
    validation_ok: bool,
    review_passed: bool,
    run_id: str,
    trace_id: str = "trace_delivery",
) -> DeliveryState:
    if not validation_ok:
        return DeliveryState(
            delivered=False,
            event_type="error",
            run_id=run_id,
            trace_id=trace_id,
            reason="validation_failed",
        )
    if not review_passed:
        return DeliveryState(
            delivered=False,
            event_type="error",
            run_id=run_id,
            trace_id=trace_id,
            reason="review_not_passed",
        )
    return DeliveryState(
        delivered=True,
        event_type="final",
        run_id=run_id,
        trace_id=trace_id,
        reason="ok",
    )
