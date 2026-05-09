from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field, model_validator


class EvalTurnSpec(BaseModel):
    role: str
    content: str


class EvalSetupSpec(BaseModel):
    session_history_fixture: str = "none"
    memory_fixture: str = "none"
    automation_fixture: str = "none"


class EvalFinalTextExpectations(BaseModel):
    contains_all: list[str] = Field(default_factory=list)
    contains_any: list[str] = Field(default_factory=list)
    forbid_all: list[str] = Field(default_factory=list)


class EvalToolCallRule(BaseModel):
    tool_name: str
    min_calls: int = 0
    max_calls: int = 1

    @model_validator(mode="after")
    def validate_call_range(self) -> "EvalToolCallRule":
        if self.min_calls > self.max_calls:
            raise ValueError("min_calls must be <= max_calls")
        return self


class EvalToolCallExpectations(BaseModel):
    required_calls: list[EvalToolCallRule] = Field(default_factory=list)
    forbidden_calls: list[str] = Field(default_factory=list)


class EvalEfficiencyExpectations(BaseModel):
    max_llm_requests: int | None = None
    max_tool_calls: int | None = None


class EvalContextExpectations(BaseModel):
    expect_compaction: bool | None = None
    expect_preserved_tail_user_turns: int | None = None


class EvalDiagnosticsExpectations(BaseModel):
    expect_provider_ref: str | None = None
    expect_final_provider_ref: str | None = None


class EvalExpectations(BaseModel):
    final_text: EvalFinalTextExpectations = Field(default_factory=EvalFinalTextExpectations)
    tool_path: EvalToolCallExpectations = Field(default_factory=EvalToolCallExpectations)
    efficiency: EvalEfficiencyExpectations = Field(default_factory=EvalEfficiencyExpectations)
    context: EvalContextExpectations = Field(default_factory=EvalContextExpectations)
    diagnostics: EvalDiagnosticsExpectations = Field(default_factory=EvalDiagnosticsExpectations)


class EvalWeights(BaseModel):
    outcome: int = 0
    tool_path: int = 0
    efficiency: int = 0
    context: int = 0

    def total(self) -> int:
        return self.outcome + self.tool_path + self.efficiency + self.context

    @model_validator(mode="after")
    def validate_total(self) -> "EvalWeights":
        if self.total() != 100:
            raise ValueError("weights must sum to 100")
        return self


class EvalComponentScore(BaseModel):
    key: str
    label: str
    weight: int
    ratio: float
    score: float
    passed: bool
    details: object | None = None


class EvalComponentComparison(BaseModel):
    key: str
    label: str | None = None
    current_score: float | None = None
    baseline_score: float | None = None
    delta: float = 0.0
    current_passed: bool | None = None
    baseline_passed: bool | None = None


class EvalComponentSummary(BaseModel):
    key: str
    label: str
    current_score: float | None = None
    baseline_score: float | None = None
    delta: float = 0.0
    case_count: int = 0


class EvalStabilityStats(BaseModel):
    sample_size: int = 0
    mean: float | None = None
    min: float | None = None
    max: float | None = None
    range: float | None = None
    stddev: float | None = None


class EvalStabilityComponentSummary(BaseModel):
    key: str
    label: str
    score: EvalStabilityStats = Field(default_factory=EvalStabilityStats)
    unstable: bool = False


class EvalStabilityCaseSummary(BaseModel):
    case_id: str
    run_count: int = 0
    status_values: list[str] = Field(default_factory=list)
    pass_rate: float = 0.0
    score: EvalStabilityStats = Field(default_factory=EvalStabilityStats)
    token_total: EvalStabilityStats = Field(default_factory=EvalStabilityStats)
    failover_rate: float = 0.0
    anchor_signal_count: int = 0
    anchor_strength: str = "weak"
    unstable: bool = False
    unstable_reasons: list[str] = Field(default_factory=list)
    components: list[EvalStabilityComponentSummary] = Field(default_factory=list)


class EvalRunStabilitySummary(BaseModel):
    suite_id: str
    profile_name: str
    eval_mode: str
    window_size: int
    sample_size: int = 0
    history_eval_run_ids: list[str] = Field(default_factory=list)
    total_score: EvalStabilityStats = Field(default_factory=EvalStabilityStats)
    pass_rate: EvalStabilityStats = Field(default_factory=EvalStabilityStats)
    token_total: EvalStabilityStats = Field(default_factory=EvalStabilityStats)
    failover_rate: float = 0.0
    unstable_case_count: int = 0
    unstable_component_count: int = 0
    cases: list[EvalStabilityCaseSummary] = Field(default_factory=list)
    components: list[EvalStabilityComponentSummary] = Field(default_factory=list)


class EvalCaseSpec(BaseModel):
    case_id: str
    suite_id: str
    family: str
    grader_id: str | None = None
    enabled: bool = True
    required: bool = True
    description: str
    agent_id: str
    profile_name: str
    tags: list[str] = Field(default_factory=list)
    turns: list[EvalTurnSpec]
    setup: EvalSetupSpec = Field(default_factory=EvalSetupSpec)
    expectations: EvalExpectations = Field(default_factory=EvalExpectations)
    weights: EvalWeights | None = None
    component_weights: dict[str, int] = Field(default_factory=dict)
    gate_components: list[str] = Field(default_factory=list)
    grader_case: dict[str, object] = Field(default_factory=dict)
    source_path: str | None = None
    resolved_fixtures: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_scoring_contract(self) -> "EvalCaseSpec":
        has_legacy_weights = self.weights is not None
        has_component_weights = bool(self.component_weights)
        if not has_legacy_weights and not has_component_weights:
            raise ValueError("case must define weights or component_weights")
        if has_component_weights and sum(self.component_weights.values()) != 100:
            raise ValueError("component_weights must sum to 100")
        unknown_gate_components = [
            key for key in self.gate_components if key not in self.component_weights
        ]
        if unknown_gate_components:
            raise ValueError(
                f"gate_components must exist in component_weights: {unknown_gate_components}"
            )
        return self


class EvalSuiteSpec(BaseModel):
    suite_id: str
    grader_id: str | None = None
    description: str
    default_mode: str
    scripted_supported: bool
    required_dependencies: list[str] = Field(default_factory=list)
    baseline_policy: str
    case_files: list[str] = Field(default_factory=list)
    cases: list[EvalCaseSpec] = Field(default_factory=list)
    suite_fingerprint: str = ""
    source_path: str | None = None

    @model_validator(mode="after")
    def validate_mode(self) -> "EvalSuiteSpec":
        if self.default_mode not in {"live", "scripted"}:
            raise ValueError("default_mode must be live or scripted")
        return self


class EvalCaseResult(BaseModel):
    eval_run_id: str
    case_id: str
    family: str
    status: str
    total_score: float
    outcome_score: float
    tool_path_score: float
    efficiency_score: float
    context_score: float
    llm_request_count: int = 0
    tool_calls_count: int = 0
    duration_ms: int = 0
    run_id: str | None = None
    trace_id: str | None = None
    langfuse_url: str | None = None
    final_text: str = ""
    diagnostics_json: dict[str, object] = Field(default_factory=dict)
    score_breakdown_json: dict[str, object] = Field(default_factory=dict)
    artifact_path: str | None = None
    blocked_reason: str | None = None


class EvalCaseObservation(BaseModel):
    case_id: str
    family: str
    final_text: str = ""
    llm_request_count: int = 0
    tool_calls_count: int = 0
    duration_ms: int = 0
    run_id: str | None = None
    trace_id: str | None = None
    langfuse_url: str | None = None
    tool_calls: list[dict[str, object]] = Field(default_factory=list)
    diagnostics_json: dict[str, object] = Field(default_factory=dict)
    blocked_reason: str | None = None
    error_code: str | None = None


class EvalCaseComparison(BaseModel):
    case_id: str
    current_status: str | None = None
    baseline_status: str | None = None
    current_total_score: float | None = None
    baseline_total_score: float | None = None
    total_score_delta: float = 0.0
    change_kind: str = "unchanged"
    components: list[EvalComponentComparison] = Field(default_factory=list)


class EvalRunComparison(BaseModel):
    baseline_eval_run_id: str
    baseline_source: str
    total_score_delta: float = 0.0
    pass_rate_delta: float = 0.0
    regressions: list[EvalCaseComparison] = Field(default_factory=list)
    improvements: list[EvalCaseComparison] = Field(default_factory=list)
    cases: list[EvalCaseComparison] = Field(default_factory=list)
    component_summary: list[EvalComponentSummary] = Field(default_factory=list)


class EvalRunSummary(BaseModel):
    eval_run_id: str
    suite_id: str
    git_branch: str
    git_sha: str
    git_dirty: bool
    eval_mode: str
    agent_id: str
    profile_name: str
    provider_ref: str | None = None
    model_name: str | None = None
    config_fingerprint: str
    suite_fingerprint: str
    baseline_eval_run_id: str | None = None
    total_score: float = 0.0
    pass_rate: float = 0.0
    status: str
    artifact_root: str
    component_summary: list[EvalComponentSummary] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None

    @model_validator(mode="after")
    def validate_mode(self) -> "EvalRunSummary":
        if self.eval_mode not in {"live", "scripted"}:
            raise ValueError("eval_mode must be live or scripted")
        return self
