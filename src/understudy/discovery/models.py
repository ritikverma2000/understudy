from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field


TargetRef = Literal[
    "member_id_input",
    "search_control",
    "member_result_link",
    "savings_balance_cell",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ControlSnapshot(StrictModel):
    id: str
    role: str
    name: str
    context: str


class Observation(StrictModel):
    url: str
    title: str
    controls: list[ControlSnapshot]


class TypeTextDecision(StrictModel):
    type: Literal["type_text"]
    control_id: str
    target_ref: Literal["member_id_input"]
    input_name: Literal["member_id"]
    decision_summary: str


class ActivateDecision(StrictModel):
    type: Literal["activate"]
    control_id: str
    target_ref: Literal["search_control", "member_result_link"]
    decision_summary: str


class ReadDecision(StrictModel):
    type: Literal["read"]
    control_id: str
    target_ref: Literal["savings_balance_cell"]
    decision_summary: str


class FinishDecision(StrictModel):
    type: Literal["finish"]
    decision_summary: str


class EscalateDecision(StrictModel):
    type: Literal["escalate"]
    decision_summary: str


Decision = Annotated[
    Union[
        TypeTextDecision,
        ActivateDecision,
        ReadDecision,
        FinishDecision,
        EscalateDecision,
    ],
    Field(discriminator="type"),
]


class DecisionEnvelope(StrictModel):
    decision: Decision


class TraceEvent(StrictModel):
    index: int
    action: str
    target_ref: str | None
    control_role: str | None
    control_name: str | None
    decision_summary: str
