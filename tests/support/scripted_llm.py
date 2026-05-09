from __future__ import annotations

from marten_runtime.runtime.direct_rendering import render_direct_tool_text
from marten_runtime.runtime.llm_client import LLMReply, _normalize_reply_contract_metadata
from marten_runtime.runtime.usage_models import ProviderCallAttempt, ProviderCallDiagnostics
from tests.support.finalization_contracts import contracted_final_reply


class FailingLLMClient:
    provider_name = "failing"
    model_name = "failing-local"

    def complete(self, request):  # noqa: ANN001
        raise RuntimeError("provider_transport_error:connection reset")


class FirstSuccessThenFailingLLMClient:
    provider_name = "scripted"
    model_name = "scripted-local"

    def __init__(self, first_reply: LLMReply) -> None:
        self._first_reply = first_reply
        self._calls = 0

    def complete(self, request):  # noqa: ANN001
        self._calls += 1
        if self._calls == 1:
            return self._first_reply
        raise RuntimeError("provider_transport_error:connection reset")


class BrokenInternalLLMClient:
    provider_name = "broken"
    model_name = "broken-local"

    def complete(self, request):  # noqa: ANN001
        raise ValueError("boom")


class AuthFailingLLMClient:
    provider_name = "auth-failing"
    model_name = "auth-failing-local"

    def complete(self, request):  # noqa: ANN001
        raise RuntimeError("provider_http_error:401:unauthorized")


class OverloadedLLMClient:
    provider_name = "overloaded"
    model_name = "overloaded-local"

    def complete(self, request):  # noqa: ANN001
        raise RuntimeError(
            'provider_http_error:529:{"type":"error","error":{"type":"overloaded_error","message":"当前服务繁忙","http_code":"529"}}'
        )


class BrokenToolLLMClient:
    provider_name = "scripted"
    model_name = "scripted-local"

    def complete(self, request):  # noqa: ANN001
        return LLMReply(tool_name="broken_tool", tool_payload={"value": "x"})


class FirstSuccessThenDisallowedToolLLMClient:
    provider_name = "scripted"
    model_name = "scripted-local"

    def __init__(self, first_reply: LLMReply) -> None:
        self._first_reply = first_reply
        self._calls = 0

    def complete(self, request):  # noqa: ANN001
        self._calls += 1
        if self._calls == 1:
            return self._first_reply
        return LLMReply(tool_name="time", tool_payload={"timezone": "UTC"})


class ObservedLLMClient:
    provider_name = "observed"
    model_name = "observed-local"

    def __init__(self) -> None:
        self.last_call_diagnostics = ProviderCallDiagnostics(
            request_kind="interactive",
            timeout_seconds=20,
            max_attempts=2,
            completed=True,
            final_error_code=None,
            attempts=[
                ProviderCallAttempt(
                    attempt=1,
                    elapsed_ms=123,
                    ok=True,
                    error_code=None,
                    error_detail=None,
                    retryable=False,
                )
            ],
        )

    def complete(self, request):  # noqa: ANN001
        return contracted_final_reply("ok")


class PromptTooLongThenSuccessLLMClient:
    provider_name = "scripted"
    model_name = "scripted-local"

    def __init__(self) -> None:
        self.requests = []
        self._calls = 0

    def complete(self, request):  # noqa: ANN001
        self.requests.append(request)
        self._calls += 1
        if self._calls == 1:
            raise RuntimeError("provider_http_error:400:prompt too long")
        return _normalize_reply_contract_metadata(request, contracted_final_reply("recovered"))


class ConcurrentInterleavingLLMClient:
    provider_name = "scripted"
    model_name = "scripted-local"

    def complete(self, request):  # noqa: ANN001
        if request.message == "first":
            if request.tool_result is None:
                return LLMReply(tool_name="time", tool_payload={})
            return contracted_final_reply(
                str(
                    render_direct_tool_text(
                        "time",
                        request.tool_result,
                        tool_payload={"timezone": request.tool_result.get("timezone")},
                    )
                    or ""
                )
            )
        return contracted_final_reply("done-second")
