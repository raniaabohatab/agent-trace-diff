"""Trace data model.

A single agent run is one AgentRun containing an ordered list of Steps.
Plan/action/observation steps are interleaved within one run — we are not
treating "planned" and "actual" as two separate agent runs to diff against
each other. See docs/decisions.md for why.
"""
from typing import Any, Optional

from pydantic import BaseModel


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
    final_status: str  # "success" | "failure" | "unknown"
    ground_truth_divergence_step: Optional[int] = None  # filled in manually in Week 5, leave None for now
