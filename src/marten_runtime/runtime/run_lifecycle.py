from dataclasses import dataclass

from marten_runtime.observability.langfuse import LangfuseObserver
from marten_runtime.runtime.history import InMemoryRunHistory
from marten_runtime.runtime.provider_flow import ProviderFailoverState, set_history_failover_state
from marten_runtime.runtime.request_flow import cumulative_usage_payload
from marten_runtime.runtime.run_outcome_flow import elapsed_ms


@dataclass
class RunLifecycleFinalizer:
    history: InMemoryRunHistory
    langfuse_observer: LangfuseObserver
    trace_handle: object
    run_id: str
    run_started_at: float
    provider_state: ProviderFailoverState
    request_kind: str
    agent_id: str
    channel_id: str | None
    observation_policy: str = "standard"

    def _finalize_common(
        self,
        *,
        status: str,
        final_provider_ref: str | None,
        llm_request_count: int,
        final_text: str | None = None,
        error_code: str | None = None,
    ) -> None:
        set_history_failover_state(
            self.history,
            run_id=self.run_id,
            state=self.provider_state,
            final_provider_ref=final_provider_ref,
        )
        run_record = self.history.get(self.run_id)
        self.history.set_external_observability_refs(
            self.run_id,
            langfuse_trace_id=getattr(self.trace_handle, "trace_id", None),
            langfuse_url=getattr(self.trace_handle, "url", None),
        )
        kwargs: dict[str, object] = {
            "status": status,
            "usage": cumulative_usage_payload(run_record),
            "total_ms": elapsed_ms(self.run_started_at),
            "metadata": {
                "llm_request_count": llm_request_count,
                "request_kind": self.request_kind,
                "agent_id": self.agent_id,
                "channel_id": self.channel_id,
            },
        }
        if final_text is not None:
            kwargs["final_text"] = final_text
        if error_code is not None:
            kwargs["error_code"] = error_code
        self.langfuse_observer.finalize_run(
            self.trace_handle,
            observation_policy=self.observation_policy,
            **kwargs,
        )

    def finalize_success(
        self,
        *,
        final_text: str,
        final_provider_ref: str | None,
        llm_request_count: int,
    ) -> None:
        self._finalize_common(
            status="succeeded",
            final_text=final_text,
            final_provider_ref=final_provider_ref,
            llm_request_count=llm_request_count,
        )

    def finalize_error(
        self,
        *,
        error_code: str,
        final_provider_ref: str | None,
        llm_request_count: int,
    ) -> None:
        self._finalize_common(
            status="failed",
            error_code=error_code,
            final_provider_ref=final_provider_ref,
            llm_request_count=llm_request_count,
        )
