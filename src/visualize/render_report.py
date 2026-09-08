"""Render one DiffResult + its source AgentRun into a standalone HTML report.

Self-contained on purpose: the template has its CSS inlined, so the output
file works with no internet connection and no build step. See
docs/decisions.md, 2026-06-17, for why static HTML over a live app.
"""
import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from src.diff.classify import DivergenceEvent
from src.diff.diff_result import DiffResult
from src.schema import AgentRun

TEMPLATE_DIR = Path(__file__).resolve().parent
NORMALIZED_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "normalized"
DIFFS_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "diffs"
REPORTS_DIR = Path(__file__).resolve().parent.parent.parent / "reports"

_env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))

_HARD_KINDS = {"skipped_step", "unexpected_step", "wrong_tool"}


def _describe_event(event: DivergenceEvent) -> str:
    if event.kind == "skipped_step":
        return f"Agent skipped the planned '{event.planned_tool}' step (step {event.index})."
    if event.kind == "unexpected_step":
        return f"Agent called '{event.actual_tool}', which wasn't in the plan, at step {event.index}."
    if event.kind == "wrong_tool":
        return (
            f"Agent planned to call '{event.planned_tool}' but called "
            f"'{event.actual_tool}' instead, at step {event.index}."
        )
    # args_changed, only reachable here via a direct call with no hard events.
    return f"Agent called '{event.actual_tool}' as planned, but with unexpected arguments, at step {event.index}."


def summarize(divergence_events: list[DivergenceEvent]) -> str:
    """Generate a one-line plain-English explanation from classify.py's
    structured output. Template-string logic keyed on `kind` and position,
    no LLM call, deterministic given the same events."""
    hard = [e for e in divergence_events if e.kind in _HARD_KINDS]
    soft = [e for e in divergence_events if e.kind not in _HARD_KINDS]

    if not hard:
        if soft:
            plural = "s" if len(soft) != 1 else ""
            return (
                "Agent followed its plan exactly (tool-for-tool), though "
                f"{len(soft)} step{plural} had arguments that don't obviously "
                "match the plan's stated reason."
            )
        return "Agent followed its plan exactly, no divergence detected."

    sentence = _describe_event(hard[0])
    remaining = len(hard) - 1
    if remaining > 0:
        plural = "s" if remaining != 1 else ""
        sentence += f" ({remaining} more divergence{plural} after this point.)"
    return sentence


_ROW_CLASS_BY_EVENT_KIND = {
    "wrong_tool": "row-substitute",
    "args_changed": "row-args-changed",
}


_LONG_OUTPUT_THRESHOLD = 150  # chars, above which the output collapses into a <details>

# final_status describes whether the run itself completed, not whether it
# followed its plan. Displaying it as "success" next to "Followed plan: no"
# reads as a contradiction, since the run can complete fine while still
# diverging. Relabeled to describe the run, not the outcome.
_RUN_STATUS_LABEL = {
    "success": "completed",
    "failure": "errored",
    "unknown": "unknown",
}


def _pair_actions_with_observations(run: AgentRun) -> list[tuple]:
    """A single AIMessage can request several parallel tool calls, which
    appends multiple "action" steps in a row before their "observation"
    steps arrive. We used to assume the Nth action's output was always the
    Nth observation, in order. That held for small batches but a real
    15-parallel-call trace showed observations can complete out of order,
    so the tool name we captured at request time is the only thing that
    still lines up correctly by tool_call_id. Traces generated after Week 7
    carry tool_call_id on both sides and get paired by that id. Traces from
    before that field existed fall back to the old positional pairing, with
    the same tool-name mismatch guard as before. See docs/decisions.md,
    2026-07-21.
    """
    action_steps = [s for s in run.steps if s.step_type == "action"]
    observation_steps = [s for s in run.steps if s.step_type == "observation"]
    observations_by_call_id = {
        s.tool_call_id: s for s in observation_steps if s.tool_call_id is not None
    }

    paired = []
    for i, action in enumerate(action_steps):
        if action.tool_call_id is not None and action.tool_call_id in observations_by_call_id:
            observation = observations_by_call_id[action.tool_call_id]
        else:
            observation = observation_steps[i] if i < len(observation_steps) else None
            if observation is not None and observation.actual_tool != action.actual_tool:
                # Positional fallback broke for this run, degrade gracefully
                # instead of mis-attributing one tool's output to another.
                observation = None
        paired.append((action, observation))
    return paired


def _build_rows(run: AgentRun, diff: DiffResult) -> list[dict]:
    events_by_index = {e.index: e for e in diff.divergence_events}
    action_observation_pairs = _pair_actions_with_observations(run)

    rows = []
    for i, pair in enumerate(diff.aligned_pairs):
        op = pair["op"]
        event = events_by_index.get(i)

        planned = run.planned_steps[pair["planned_index"]] if pair["planned_index"] is not None else None
        actual, observation = (
            action_observation_pairs[pair["actual_index"]] if pair["actual_index"] is not None else (None, None)
        )
        actual_output = str(observation.tool_output) if observation and observation.tool_output is not None else None
        # Every tool in this project reports a failure by returning a string
        # that starts with "Error", there's no separate is_error field on
        # Step. A result line needs to look different from a real success,
        # green on "Error: division by zero" reads as the call succeeded.
        actual_output_is_error = bool(actual_output) and actual_output.startswith("Error")

        if op == "match":
            row_class = _ROW_CLASS_BY_EVENT_KIND.get(event.kind, "row-match") if event else "row-match"
        elif op == "substitute":
            row_class = "row-substitute"
        else:  # insert or delete
            row_class = "row-missing"

        rows.append(
            {
                "planned_tool": planned.tool if planned else None,
                "planned_reason": planned.reason if planned else None,
                "actual_tool": actual.actual_tool if actual else None,
                "actual_input": actual.tool_input if actual else None,
                "actual_output": actual_output,
                "actual_output_is_long": bool(actual_output) and len(actual_output) > _LONG_OUTPUT_THRESHOLD,
                "actual_output_is_error": actual_output_is_error,
                "row_class": row_class,
                "is_first_divergence": diff.first_divergence_index == i,
                "event_detail": event.detail if event else None,
            }
        )
    return rows


def render_report(run: AgentRun, diff: DiffResult) -> str:
    template = _env.get_template("template.html")
    hard_count = sum(1 for e in diff.divergence_events if e.kind in _HARD_KINDS)

    if not run.plan_was_attempted:
        # No upfront plan exists for this run at all, either a legacy Week 1
        # trace (predates the Plan-and-Execute change) or a ReAct-style
        # external trace (e.g. SWE-agent, which reasons and acts one step at
        # a time with no upfront plan by design). Either way, every executed
        # step aligns as "unexpected" against an empty plan, which is
        # technically correct but reads as "the agent went off-script" when
        # the real story is "there was no plan to compare against." See
        # docs/decisions.md, 2026-06-11 and 2026-07-01. Deliberately NOT `not
        # run.planned_steps`, a run where a plan was genuinely attempted and
        # came back empty (and execution also made zero tool calls) is a real,
        # correct exact match, not a missing plan. See 2026-06-23.
        summary_text = (
            "No upfront plan exists for this run (either a legacy pre-Plan-and-"
            "Execute trace, or a framework that doesn't plan upfront), so there's "
            "nothing to compare execution against."
        )
    else:
        summary_text = summarize(diff.divergence_events)

    return template.render(
        run_id=run.run_id,
        task_description=run.task_description,
        final_status=run.final_status,
        run_status_label=_RUN_STATUS_LABEL.get(run.final_status, run.final_status),
        divergence_count=hard_count,
        summary_text=summary_text,
        plan_followed_exactly=diff.plan_followed_exactly,
        rows=_build_rows(run, diff),
    )


def render_and_save(run: AgentRun, diff: DiffResult, reports_dir: Path = REPORTS_DIR) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    html = render_report(run, diff)
    path = reports_dir / f"{run.run_id}.html"
    path.write_text(html)
    return path


def load_run_and_diff(
    run_id: str, normalized_dir: Path = NORMALIZED_DATA_DIR, diffs_dir: Path = DIFFS_DATA_DIR
) -> tuple[AgentRun, DiffResult]:
    run = AgentRun.model_validate(json.loads((normalized_dir / f"{run_id}.jsonl").read_text()))
    diff = DiffResult.model_validate(json.loads((diffs_dir / f"{run_id}.jsonl").read_text()))
    return run, diff


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Render one DiffResult into a standalone HTML report.")
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()

    loaded_run, loaded_diff = load_run_and_diff(args.run_id)
    out_path = render_and_save(loaded_run, loaded_diff)
    print(f"Wrote {out_path}")
