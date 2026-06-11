"""Turn a raw alignment into human-readable divergence events.

args_changed detection (MATCH pairs where the executed tool's arguments
don't obviously relate to the plan's stated reason) uses a plain lexical
overlap heuristic, not an LLM call — see docs/decisions.md, 2026-06-10, for
why that's a known-crude signal deliberately kept simple.
"""
import re

from pydantic import BaseModel

from src.diff.align import AlignedPair, AlignOp
from src.schema import AgentRun

_STOPWORDS = {
    "the", "a", "an", "to", "of", "for", "and", "in", "on", "at", "is", "this",
    "that", "it", "need", "needs", "with", "from", "into", "its", "will", "be",
    "determine", "find", "get", "use", "using", "then", "want", "would", "should",
}


class DivergenceEvent(BaseModel):
    index: int  # position in the alignment
    kind: str  # "skipped_step" | "unexpected_step" | "wrong_tool" | "args_changed"
    planned_tool: str | None = None
    actual_tool: str | None = None
    detail: str  # human-readable one-line explanation


def _tokenize(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2 and w not in _STOPWORDS}


def _args_look_unrelated_to_reason(tool_input: dict | None, reason: str) -> bool:
    """Crude lexical-overlap heuristic: if none of the tool call's argument
    values share a word with the plan's stated reason, flag it. False
    negatives and false positives are both expected — this is a soft signal
    (args_changed is explicitly excluded from "hard" divergences), not a
    claim of semantic understanding.
    """
    if not tool_input:
        return False
    input_tokens = _tokenize(" ".join(str(v) for v in tool_input.values()))
    reason_tokens = _tokenize(reason)
    if not input_tokens or not reason_tokens:
        return False
    return input_tokens.isdisjoint(reason_tokens)


def classify(aligned: list[AlignedPair], run: AgentRun) -> list[DivergenceEvent]:
    """
    Walk the alignment and produce divergence events:
    - AlignOp.DELETE  -> "skipped_step" (planned but never executed)
    - AlignOp.INSERT  -> "unexpected_step" (executed but not planned)
    - AlignOp.SUBSTITUTE -> "wrong_tool" (different tool than planned)
    - AlignOp.MATCH but tool_input differs meaningfully from the plan's stated reason
      -> "args_changed" (softer signal — flag but don't count as a hard divergence)
    """
    action_steps = [s for s in run.steps if s.step_type == "action"]
    events: list[DivergenceEvent] = []

    for i, pair in enumerate(aligned):
        if pair.op == AlignOp.DELETE:
            planned = run.planned_steps[pair.planned_index]
            events.append(
                DivergenceEvent(
                    index=i,
                    kind="skipped_step",
                    planned_tool=planned.tool,
                    actual_tool=None,
                    detail=f"Planned to call '{planned.tool}' ({planned.reason}) but never did.",
                )
            )
        elif pair.op == AlignOp.INSERT:
            actual_step = action_steps[pair.actual_index]
            events.append(
                DivergenceEvent(
                    index=i,
                    kind="unexpected_step",
                    planned_tool=None,
                    actual_tool=actual_step.actual_tool,
                    detail=f"Called '{actual_step.actual_tool}' with no corresponding planned step.",
                )
            )
        elif pair.op == AlignOp.SUBSTITUTE:
            planned = run.planned_steps[pair.planned_index]
            actual_step = action_steps[pair.actual_index]
            events.append(
                DivergenceEvent(
                    index=i,
                    kind="wrong_tool",
                    planned_tool=planned.tool,
                    actual_tool=actual_step.actual_tool,
                    detail=(
                        f"Planned to call '{planned.tool}' but called "
                        f"'{actual_step.actual_tool}' instead."
                    ),
                )
            )
        else:  # AlignOp.MATCH
            planned = run.planned_steps[pair.planned_index]
            actual_step = action_steps[pair.actual_index]
            if _args_look_unrelated_to_reason(actual_step.tool_input, planned.reason):
                events.append(
                    DivergenceEvent(
                        index=i,
                        kind="args_changed",
                        planned_tool=planned.tool,
                        actual_tool=actual_step.actual_tool,
                        detail=(
                            f"Called '{actual_step.actual_tool}' as planned, but its arguments "
                            f"don't obviously relate to the stated reason ('{planned.reason}')."
                        ),
                    )
                )

    return events


_HARD_KINDS = {"skipped_step", "unexpected_step", "wrong_tool"}


def first_divergence_index(events: list[DivergenceEvent]) -> int | None:
    """Return the index of the first hard divergence (skipped_step, unexpected_step, wrong_tool),
    excluding args_changed. Return None if the run matches its plan exactly."""
    for event in events:
        if event.kind in _HARD_KINDS:
            return event.index
    return None
