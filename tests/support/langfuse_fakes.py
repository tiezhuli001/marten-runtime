from __future__ import annotations


class FakeLangfuseClient:
    def __init__(self) -> None:
        self.traces: list[dict] = []
        self.generations: list[dict] = []
        self.tool_spans: list[dict] = []
        self.finalizations: list[dict] = []

    def create_trace(self, payload: dict) -> dict:
        self.traces.append(payload)
        trace_id = str(payload.get("trace_id") or "lf-generated")
        return {"trace_id": trace_id, "url": f"https://langfuse.example/trace/{trace_id}"}

    def record_generation(self, payload: dict) -> None:
        self.generations.append(payload)

    def record_tool_span(self, payload: dict) -> None:
        self.tool_spans.append(payload)

    def finalize_trace(self, payload: dict) -> None:
        self.finalizations.append(payload)

    def flush(self) -> None:
        pass

    def shutdown(self) -> None:
        pass


class ThrowingLangfuseClient:
    def __init__(self, *, throw_on_close: bool = False) -> None:
        self.throw_on_close = throw_on_close

    def create_trace(self, payload: dict) -> dict:
        del payload
        raise RuntimeError("langfuse create boom")

    def record_generation(self, payload: dict) -> None:
        del payload
        raise RuntimeError("langfuse generation boom")

    def record_tool_span(self, payload: dict) -> None:
        del payload
        raise RuntimeError("langfuse tool boom")

    def finalize_trace(self, payload: dict) -> None:
        del payload
        raise RuntimeError("langfuse finalize boom")

    def flush(self) -> None:
        if self.throw_on_close:
            raise RuntimeError("langfuse flush boom")

    def shutdown(self) -> None:
        if self.throw_on_close:
            raise RuntimeError("langfuse shutdown boom")
