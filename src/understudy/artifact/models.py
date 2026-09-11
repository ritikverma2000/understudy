from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MatchCount(StrictModel):
    min: int = Field(ge=0)
    max: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_range(self) -> "MatchCount":
        if self.min > self.max:
            raise ValueError("min cannot be greater than max")
        return self

MatchMode = Literal["exact", "contains"]


class AccessibilityStrategy(StrictModel):
    id: str
    kind: Literal["accessibility"]
    role: str
    name: str
    match: MatchMode


class TextStrategy(StrictModel):
    id: str
    kind: Literal["text"]
    value: str | None = None
    value_from: str | None = None
    match: MatchMode
    within_css: str | None = None

    @model_validator(mode="after")
    def require_one_value_source(self) -> "TextStrategy":
        supplied = [self.value is not None, self.value_from is not None]
        if sum(supplied) != 1:
            raise ValueError(
                "text strategy requires exactly one of value or value_from"
            )
        return self


class AttributeStrategy(StrictModel):
    id: str
    kind: Literal["attribute"]
    attribute: str
    value: str | None = None
    value_template: str | None = None

    @model_validator(mode="after")
    def require_one_attribute_value(self) -> "AttributeStrategy":
        supplied = [
            self.value is not None,
            self.value_template is not None,
        ]
        if sum(supplied) != 1:
            raise ValueError(
                "attribute strategy requires exactly one of "
                "value or value_template"
            )
        return self


class CssStrategy(StrictModel):
    id: str
    kind: Literal["css"]
    value: str

class ColumnValueRowMatch(StrictModel):
    kind: Literal["column_value"]
    column_header: str
    equals: str | None = None
    equals_from: str | None = None

    @model_validator(mode="after")
    def require_one_expected_value(self) -> "ColumnValueRowMatch":
        supplied = [
            self.equals is not None,
            self.equals_from is not None,
        ]
        if sum(supplied) != 1:
            raise ValueError(
                "column_value requires exactly one of "
                "equals or equals_from"
            )
        return self


class RowLabelMatch(StrictModel):
    kind: Literal["row_label"]
    label: str
    match: MatchMode


RowMatch = Annotated[
    Union[
        ColumnValueRowMatch,
        RowLabelMatch,
    ],
    Field(discriminator="kind"),
]

class DescendantSelect(StrictModel):
    kind: Literal["descendant"]
    role: str
    name: str
    match: MatchMode


class CellSelect(StrictModel):
    kind: Literal["cell"]
    column_header: str


TableSelect = Annotated[
    Union[
        DescendantSelect,
        CellSelect,
    ],
    Field(discriminator="kind"),
]


class TableRelationStrategy(StrictModel):
    id: str
    kind: Literal["table_relation"]
    table_anchor: str
    row_match: RowMatch
    select: TableSelect

LocatorStrategy = Annotated[
    Union[
        AccessibilityStrategy,
        TextStrategy,
        AttributeStrategy,
        CssStrategy,
        TableRelationStrategy,
    ],
    Field(discriminator="kind"),
]

class DriftPolicy(StrictModel):
    primary_strategy_id: str
    fallback_resolution: Literal["mark_degraded"]
    no_resolution: Literal["fail", "condition_not_present"]


class Target(StrictModel):
    context_ref: str
    role_in_flow: Literal["actionable", "detectable"]
    expected_matches: MatchCount
    strategies: list[LocatorStrategy] = Field(min_length=1)
    drift_policy: DriftPolicy
    rationale: str | None = None

FrameLocatorStrategy = Annotated[
    Union[
        AttributeStrategy,
        CssStrategy,
    ],
    Field(discriminator="kind"),
]


class SurfaceContext(StrictModel):
    kind: Literal["web_frame"]
    expected_matches: MatchCount
    strategies: list[FrameLocatorStrategy] = Field(min_length=1)
    rationale: str | None = None

class VisibleCondition(StrictModel):
    kind: Literal["visible"]
    target_ref: str


class NotVisibleCondition(StrictModel):
    kind: Literal["not_visible"]
    target_ref: str


class EnabledCondition(StrictModel):
    kind: Literal["enabled"]
    target_ref: str


class ElementValueEqualsCondition(StrictModel):
    kind: Literal["element_value_equals"]
    target_ref: str
    source: Literal["value", "text"]
    value_from: str
    log_policy: Literal["allow", "redact"]


class OutputMatchesCondition(StrictModel):
    kind: Literal["output_matches"]
    output: str
    type: Literal["integer", "string"]
    equals: str | int | float | bool | None = None


class RuntimeBindingPresentCondition(StrictModel):
    kind: Literal["runtime_binding_present"]
    binding: str


class AllCondition(StrictModel):
    kind: Literal["all"]
    conditions: list["Condition"] = Field(min_length=1)


Condition = Annotated[
    Union[
        VisibleCondition,
        NotVisibleCondition,
        EnabledCondition,
        ElementValueEqualsCondition,
        OutputMatchesCondition,
        RuntimeBindingPresentCondition,
        AllCondition,
    ],
    Field(discriminator="kind"),
]


AllCondition.model_rebuild(
    _types_namespace={"Condition": Condition}
)

class NavigateAction(StrictModel):
    type: Literal["navigate"]
    route_ref: str


class EnterTextAction(StrictModel):
    type: Literal["enter_text"]
    target_ref: str
    value_from: str


class ActivateAction(StrictModel):
    type: Literal["activate"]
    target_ref: str


class MoneyParser(StrictModel):
    kind: Literal["money"]
    locale: str
    expected_currency: str
    amount_output: str
    currency_output: str


class ReadAction(StrictModel):
    type: Literal["read"]
    target_ref: str
    parser: MoneyParser


class PressKeyAction(StrictModel):
    type: Literal["press_key"]
    key: str
    target_ref: str | None = None


Action = Annotated[
    Union[
        NavigateAction,
        EnterTextAction,
        ActivateAction,
        ReadAction,
        PressKeyAction,
    ],
    Field(discriminator="type"),
]


RiskClass = Literal[
    "safe_read",
    "safe_reversible",
    "irreversible",
]

NonNegativeMilliseconds = Annotated[
    int,
    Field(ge=0),
]

class RetryPolicy(StrictModel):
    max_attempts: int = Field(ge=1)
    idempotent: bool
    retry_action: bool
    retry_on: list[str]
    backoff_ms: list[NonNegativeMilliseconds] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def prevent_unsafe_action_retry(self) -> "RetryPolicy":
        if self.retry_action and not self.idempotent:
            raise ValueError(
                "retry_action cannot be true for a "
                "non-idempotent action"
            )
        return self


class Step(StrictModel):
    id: str
    intent: str
    action: Action
    risk: RiskClass
    precondition: Condition
    postcondition: Condition
    runtime_condition_check: Literal["during_wait"] | None = None
    timeout_ms: int = Field(gt=0)
    retry: RetryPolicy

class CapabilityMetadata(StrictModel):
    id: str
    name: str
    description: str
    version: str
    approval_state: Literal["draft", "approved", "deprecated"]
    risk_class: RiskClass


class RuntimeBindingDefinition(StrictModel):
    type: Literal["url"]
    required: bool


class RouteDefinition(StrictModel):
    pattern: str
    usage: Literal["entry_point", "expected_navigation"]


class EntryPoint(StrictModel):
    route_ref: str


class ApplicationTarget(StrictModel):
    surface_kind: Literal["web"]
    app_family: str
    compatible_app_versions: list[str] = Field(min_length=1)
    runtime_bindings: dict[str, RuntimeBindingDefinition]
    routes: dict[str, RouteDefinition]
    entry_point: EntryPoint


Sensitivity = Literal[
    "public",
    "pii",
    "financial",
    "secret",
]


LogPolicy = Literal["allow", "redact"]


class InputDefinition(StrictModel):
    type: Literal["string"]
    description: str
    required: bool
    pattern: str
    sensitivity: Sensitivity
    log_policy: LogPolicy


class OutputDefinition(StrictModel):
    type: Literal["integer", "string"]
    description: str
    required: bool
    enum: list[str] | None = None
    sensitivity: Sensitivity
    persistence: Literal["return_only"]
    log_policy: LogPolicy

CheckPhase = Literal[
    "during_wait",
    "after_step",
]


class InterventionDefinition(StrictModel):
    reason: str
    control_transfer: Literal["same_live_session"]
    resume_condition: Condition


class FailureDefinition(StrictModel):
    category: str
    retryable: bool
    capture_evidence: list[
        Literal["screenshot", "dom_snapshot"]
    ]


class BusinessOutcomeResult(StrictModel):
    status: Literal["business_outcome"]
    message: str


class RecoveryDefinition(StrictModel):
    kind: Literal["wait_until_hidden"]
    target_ref: str
    timeout_ms: int = Field(gt=0)
    max_attempts: int = Field(ge=1)
    on_exhausted: str


class InterventionRuntimeCondition(StrictModel):
    code: str
    classification: Literal["intervention_required"]
    priority: int = Field(ge=0)
    check_phases: list[CheckPhase] = Field(min_length=1)
    detect: Condition
    terminal: Literal[False]
    intervention: InterventionDefinition


class HardFailureRuntimeCondition(StrictModel):
    code: str
    classification: Literal["hard_failure"]
    priority: int = Field(ge=0)
    check_phases: list[CheckPhase] = Field(min_length=1)
    detect: Condition
    terminal: Literal[True]
    failure: FailureDefinition


class BusinessOutcomeRuntimeCondition(StrictModel):
    code: str
    classification: Literal["business_outcome"]
    priority: int = Field(ge=0)
    check_phases: list[CheckPhase] = Field(min_length=1)
    detect: Condition
    terminal: Literal[True]
    result: BusinessOutcomeResult


class RecoverableRuntimeCondition(StrictModel):
    code: str
    classification: Literal["recoverable"]
    priority: int = Field(ge=0)
    check_phases: list[CheckPhase] = Field(min_length=1)
    detect: Condition
    terminal: Literal[False]
    recovery: RecoveryDefinition


RuntimeCondition = Annotated[
    Union[
        InterventionRuntimeCondition,
        HardFailureRuntimeCondition,
        BusinessOutcomeRuntimeCondition,
        RecoverableRuntimeCondition,
    ],
    Field(discriminator="classification"),
]

class SuccessCheckpoint(StrictModel):
    description: str
    condition: Condition


class RiskPolicy(StrictModel):
    allowed_without_confirmation: list[RiskClass]
    require_human_confirmation: list[RiskClass]


class ModelActionConstraints(StrictModel):
    allow_model_supplied_selectors: bool
    allow_model_supplied_urls: bool
    allow_model_supplied_code: bool
    treat_surface_content_as_untrusted: bool
    surface_content_may_not_modify_policy: bool


class DataHandlingPolicy(StrictModel):
    persist_raw_inputs: bool
    persist_raw_outputs: bool
    persist_credentials: bool
    persist_tokens: bool
    persist_raw_model_transcript: bool
    redact_sensitive_logs: bool
    redact_sensitive_evidence: bool


AllowedActionType = Literal[
    "navigate",
    "enter_text",
    "activate",
    "read",
    "press_key",
]


class PolicyRequirements(StrictModel):
    runtime_policy_relation: Literal["intersection_only"]
    allowed_origins: list[str] = Field(min_length=1)
    allowed_route_refs: list[str] = Field(min_length=1)
    allowed_action_types: list[AllowedActionType] = Field(
        min_length=1
    )
    maximum_steps: int = Field(gt=0)
    maximum_runtime_ms: int = Field(gt=0)
    risk: RiskPolicy
    model_action_constraints: ModelActionConstraints
    data_handling: DataHandlingPolicy


class Provenance(StrictModel):
    source: Literal[
        "hand_authored_test_fixture",
        "discovery_generated",
    ]
    authorship: Literal[
        "human_designed",
        "model_discovered",
    ]
    discovery_run_id: str | None
    recorded_at: str | None
    contains_runtime_values: bool
    notes: str

def condition_target_refs(
    condition: Condition,
) -> set[str]:
    if isinstance(condition, AllCondition):
        references: set[str] = set()

        for child in condition.conditions:
            references.update(condition_target_refs(child))

        return references

    target_ref = getattr(condition, "target_ref", None)

    if target_ref is None:
        return set()

    return {target_ref}

class CapabilityArtifact(StrictModel):
    schema_version: Literal["1.0.0"]
    capability: CapabilityMetadata
    target: ApplicationTarget

    surface_contexts: dict[str, SurfaceContext] = Field(
        min_length=1
    )

    inputs: dict[str, InputDefinition] = Field(
        min_length=1
    )

    outputs: dict[str, OutputDefinition] = Field(
        min_length=1
    )

    targets: dict[str, Target] = Field(
        min_length=1
    )

    runtime_conditions: list[RuntimeCondition]
    steps: list[Step] = Field(min_length=1)
    success_checkpoint: SuccessCheckpoint
    policy_requirements: PolicyRequirements
    provenance: Provenance

    @model_validator(mode="after")
    def validate_contract_references(
        self,
    ) -> "CapabilityArtifact":
        target_ids = set(self.targets)
        context_ids = set(self.surface_contexts)
        route_ids = set(self.target.routes)
        output_ids = set(self.outputs)

        # Step IDs must be unique.
        step_ids = [step.id for step in self.steps]

        if len(step_ids) != len(set(step_ids)):
            raise ValueError("step IDs must be unique")

        # Runtime-condition codes must be unique.
        condition_codes = [
            condition.code
            for condition in self.runtime_conditions
        ]

        if len(condition_codes) != len(set(condition_codes)):
            raise ValueError(
                "runtime-condition codes must be unique"
            )

        # Entry point must reference a declared route.
        entry_route = self.target.entry_point.route_ref

        if entry_route not in route_ids:
            raise ValueError(
                f"entry point references unknown route "
                f"{entry_route!r}"
            )

        # Every policy route must exist in the route catalog.
        unknown_policy_routes = (
            set(self.policy_requirements.allowed_route_refs)
            - route_ids
        )

        if unknown_policy_routes:
            raise ValueError(
                "policy references unknown routes: "
                f"{sorted(unknown_policy_routes)}"
            )

        # Validate target contexts and locator strategies.
        for target_id, target in self.targets.items():
            if target.context_ref not in context_ids:
                raise ValueError(
                    f"target {target_id!r} references unknown "
                    f"context {target.context_ref!r}"
                )

            strategy_ids = [
                strategy.id
                for strategy in target.strategies
            ]

            if len(strategy_ids) != len(set(strategy_ids)):
                raise ValueError(
                    f"target {target_id!r} contains duplicate "
                    "locator strategy IDs"
                )

            primary = (
                target.drift_policy.primary_strategy_id
            )

            if primary not in strategy_ids:
                raise ValueError(
                    f"target {target_id!r} references unknown "
                    f"primary strategy {primary!r}"
                )

        def require_known_targets(
            references: set[str],
            location: str,
        ) -> None:
            unknown = references - target_ids

            if unknown:
                raise ValueError(
                    f"{location} references unknown targets: "
                    f"{sorted(unknown)}"
                )

        # Validate every step.
        for step in self.steps:
            action = step.action

            if isinstance(action, NavigateAction):
                if action.route_ref not in route_ids:
                    raise ValueError(
                        f"step {step.id!r} references unknown "
                        f"route {action.route_ref!r}"
                    )

            action_target = getattr(
                action,
                "target_ref",
                None,
            )

            if action_target is not None:
                require_known_targets(
                    {action_target},
                    f"step {step.id!r} action",
                )

            require_known_targets(
                condition_target_refs(step.precondition),
                f"step {step.id!r} precondition",
            )

            require_known_targets(
                condition_target_refs(step.postcondition),
                f"step {step.id!r} postcondition",
            )

            if isinstance(action, ReadAction):
                parser_outputs = {
                    action.parser.amount_output,
                    action.parser.currency_output,
                }

                undeclared_outputs = (
                    parser_outputs - output_ids
                )

                if undeclared_outputs:
                    raise ValueError(
                        f"step {step.id!r} writes undeclared "
                        f"outputs: {sorted(undeclared_outputs)}"
                    )

        # Validate the final checkpoint.
        require_known_targets(
            condition_target_refs(
                self.success_checkpoint.condition
            ),
            "success checkpoint",
        )

        # Validate runtime-condition references.
        for runtime_condition in self.runtime_conditions:
            require_known_targets(
                condition_target_refs(
                    runtime_condition.detect
                ),
                f"runtime condition "
                f"{runtime_condition.code!r}",
            )

            if isinstance(
                runtime_condition,
                InterventionRuntimeCondition,
            ):
                require_known_targets(
                    condition_target_refs(
                        runtime_condition
                        .intervention
                        .resume_condition
                    ),
                    f"runtime condition "
                    f"{runtime_condition.code!r} "
                    "resume condition",
                )

            if isinstance(
                runtime_condition,
                RecoverableRuntimeCondition,
            ):
                require_known_targets(
                    {
                        runtime_condition
                        .recovery
                        .target_ref
                    },
                    f"runtime condition "
                    f"{runtime_condition.code!r} recovery",
                )

        return self