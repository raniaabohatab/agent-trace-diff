"""Trace data model.

A single agent run is one AgentRun containing an ordered list of Steps.
Plan/action/observation steps are interleaved within one run — we are not
treating "planned" and "actual" as two separate agent runs to diff against
each other. See docs/decisions.md for why.

planned_steps (Week 3) is the upfront plan the diff algorithm aligns actual
execution against. It defaults to an empty list rather than being required,
so the Week 1 ReAct-style traces already in data/raw/ (generated before the
Plan-and-Execute change) keep loading correctly — an empty plan against a
non-empty actual sequence is a real, deliberately-handled edge case for the
alignment algorithm, not a schema break. See docs/decisions.md, 2026-06-08.
"""
from typing import Any, Optional

from pydantic import BaseModel, Field


class PlannedStep(BaseModel):
    step_index: int
    tool: str
    reason: str


class Step(BaseModel):
    step_index: int  # 0-indexed order in the run
    step_type: str  # "plan" | "action" | "observation" | "final_answer"
    planned_tool: Optional[str] = None  # tool name the agent said it would call, if step_type == "plan"
    actual_tool: Optional[str] = None  # tool name actually invoked, if step_type == "action"
    tool_input: Optional[dict] = None  # arguments passed to the tool
    tool_output: Optional[Any] = None  # raw output/observation returned
    raw_thought: Optional[str] = None  # the agent's reasoning text for this step, if captured
    timestamp: str  # ISO 8601


class AgentRun(BaseModel):
    run_id: str  # UUID, generate with uuid.uuid4()
    task_description: str  # the prompt/goal given to the agent
    framework: str  # "langchain" for now, always
    model_name: str  # e.g. "gpt-4o", "claude-sonnet-4"
    steps: list[Step]
    planned_steps: list[PlannedStep] = Field(default_factory=list)  # upfront plan, Week 3+
    plan_was_attempted: bool = False  # True iff make_plan() actually ran, even if it returned []
    final_status: str  # "success" | "failure" | "unknown"
    ground_truth_divergence_step: Optional[int] = None  # filled in manually in Week 5, leave None for now
