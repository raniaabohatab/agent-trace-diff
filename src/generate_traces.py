"""Run a tool-using LangChain agent Plan-and-Execute style: one upfront LLM
call produces an ordered plan of intended tool calls, then the agent
executes the task normally (free to deviate from its own plan), and both
the plan and the actual execution are captured into data/raw/{run_id}.jsonl.

Streaming (not callbacks) is the capture mechanism: agent.stream(...,
stream_mode="updates") already yields structured per-node output (AIMessage /
ToolMessage) for the LangGraph-based create_agent, so building Steps directly
from that stream is simpler and more reliable than a BaseCallbackHandler.
See docs/decisions.md.
"""
import argparse
import json
import os
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.tools import tool
from langchain_anthropic import ChatAnthropic

from src.schema import AgentRun, PlannedStep, Step

load_dotenv()

MODEL_NAME = "claude-haiku-4-5"
FRAMEWORK = "langchain"
RAW_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"


@tool
def calculator(expression: str) -> str:
    """Evaluate a basic arithmetic expression, e.g. '12 * 4 + 1'."""
    try:
        allowed = set("0123456789+-*/(). ")
        if not set(expression) <= allowed:
            return f"Error: expression contains disallowed characters: {expression}"
        return str(eval(expression, {"__builtins__": {}}, {}))
    except Exception as e:  # noqa: BLE001, any eval failure should become an error string, not a crash
        return f"Error evaluating expression: {e}"


@tool
def search(query: str) -> str:
    """Search the web for information about a topic. Returns canned results for testing."""
    canned = {
        "weather": "Canned result: it is sunny and 72F today.",
        "capital of france": "Canned result: the capital of France is Paris.",
    }
    for key, value in canned.items():
        if key in query.lower():
            return value
    return f"Canned result: no specific data found for '{query}'. Try a more common query."


@tool
def read_file(filename: str) -> str:
    """Read the contents of a named file. Returns canned contents for testing."""
    canned_files = {
        "notes.txt": "Meeting notes: discuss Q3 roadmap, budget review, hiring plan.",
        "config.json": '{"env": "test", "debug": true}',
    }
    if filename in canned_files:
        return canned_files[filename]
    return f"Error: file '{filename}' not found. Available files: {list(canned_files.keys())}"


TOOLS = [calculator, search, read_file]


def build_agent():
    model = ChatAnthropic(model=MODEL_NAME)
    return create_agent(model, tools=TOOLS)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _extract_text(content) -> str:
    """AIMessage.content is either a plain string or a list of content blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return "\n".join(p for p in parts if p)
    return ""


def _parse_plan_json(text: str) -> list[dict]:
    """Extract a JSON array from a model response that may be wrapped in
    markdown code fences or preceded by stray text."""
    fenced = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else text
    bracket_match = re.search(r"\[.*\]", candidate, re.DOTALL)
    if bracket_match:
        candidate = bracket_match.group(0)
    parsed = json.loads(candidate)
    if not isinstance(parsed, list):
        raise ValueError("expected a JSON array")
    return parsed


def make_plan(task: str, verbose: bool = True) -> list[PlannedStep]:
    """One upfront LLM call: ask for an ordered list of intended tool calls
    before any execution happens. This is a separate call from execution,
    the model is not in an agent loop here, just asked to plan.

    Never raises: a plan that fails to parse is a soft failure (empty plan,
    logged to stdout), not a reason to abandon the whole trace. This
    project needs the execution trace even when the plan came back malformed.
    """
    model = ChatAnthropic(model=MODEL_NAME)
    tool_descriptions = "\n".join(f"- {t.name}: {t.description}" for t in TOOLS)
    prompt = (
        f"You are about to complete this task: {task}\n\n"
        f"Available tools:\n{tool_descriptions}\n\n"
        "Before doing anything, output your intended plan as a JSON array of "
        "the tool calls you expect to make, in order. Each item must have "
        '"tool" (the tool name) and "reason" (why you expect to need it). '
        "If you don't expect to need any tools, output an empty array [].\n\n"
        "Output ONLY the JSON array, nothing else. Example:\n"
        '[{"tool": "search", "reason": "need current info about X"}, '
        '{"tool": "calculator", "reason": "need to compute Y"}]'
    )
    try:
        response = model.invoke(prompt)
        text = _extract_text(response.content)
        if verbose:
            print(f"--- plan ---\n{text}\n")
        raw_steps = _parse_plan_json(text)
        return [
            PlannedStep(step_index=i, tool=s["tool"], reason=s["reason"])
            for i, s in enumerate(raw_steps)
        ]
    except Exception as exc:  # noqa: BLE001, a bad plan should not abort the whole trace
        if verbose:
            print(f"--- plan generation failed, using empty plan: {exc} ---\n")
        return []


def _format_plan_for_execution(planned_steps: list[PlannedStep]) -> str:
    if not planned_steps:
        return ""
    lines = "\n".join(f"{s.step_index + 1}. {s.tool}: {s.reason}" for s in planned_steps)
    return (
        "\n\nYou previously planned to take these steps:\n"
        f"{lines}\n\n"
        "Follow this plan, but adapt if a step turns out to be unnecessary, "
        "wrong, or if you discover a better approach as you go."
    )


def run_and_capture(task: str, verbose: bool = True) -> AgentRun:
    """Plan the task, then run the agent on it, capturing every step into
    the trace schema.

    Handles mid-run errors by setting final_status="failure" and keeping
    whatever steps were captured before the error. Partial runs are still
    useful data, not discarded.
    """
    planned_steps = make_plan(task, verbose=verbose)
    execution_prompt = task + _format_plan_for_execution(planned_steps)

    agent = build_agent()
    steps: list[Step] = []
    final_status = "success"

    def add_step(**kwargs) -> None:
        steps.append(Step(step_index=len(steps), timestamp=_now(), **kwargs))

    try:
        for chunk in agent.stream(
            {"messages": [{"role": "user", "content": execution_prompt}]},
            stream_mode="updates",
        ):
            for node_output in chunk.values():
                for message in node_output.get("messages", []):
                    if verbose:
                        message.pretty_print()

                    msg_type = type(message).__name__
                    if msg_type == "AIMessage":
                        tool_calls = getattr(message, "tool_calls", None) or []
                        thought = _extract_text(message.content) or None
                        if tool_calls:
                            for call in tool_calls:
                                add_step(
                                    step_type="action",
                                    actual_tool=call["name"],
                                    tool_input=call["args"],
                                    raw_thought=thought,
                                    tool_call_id=call.get("id"),
                                )
                        else:
                            add_step(step_type="final_answer", raw_thought=thought)
                    elif msg_type == "ToolMessage":
                        add_step(
                            step_type="observation",
                            actual_tool=getattr(message, "name", None),
                            tool_output=message.content,
                            tool_call_id=getattr(message, "tool_call_id", None),
                        )
    except Exception as exc:  # noqa: BLE001 - deliberately broad: capture partial trace on any failure
        final_status = "failure"
        add_step(step_type="observation", raw_thought=f"Run errored: {exc}")

    return AgentRun(
        run_id=str(uuid.uuid4()),
        task_description=task,
        framework=FRAMEWORK,
        model_name=MODEL_NAME,
        steps=steps,
        planned_steps=planned_steps,
        plan_was_attempted=True,
        final_status=final_status,
    )


ALL_TOOL_NAMES = [t.name for t in TOOLS]


class InjectionPreconditionError(ValueError):
    """Raised when a run isn't shaped right for a given injection (e.g. no
    clean match at the position being corrupted). The caller should generate
    a different base run rather than treat this as a real failure."""


def inject_wrong_tool(run: AgentRun) -> AgentRun:
    """Swap the first planned step's tool for one that differs from what was
    actually executed there, forcing a deterministic SUBSTITUTE divergence
    at position 0. Ground truth is known exactly because we caused it.
    Requires the run's first planned step to have cleanly matched execution.
    """
    action_steps = [s for s in run.steps if s.step_type == "action"]
    if not run.planned_steps or not action_steps:
        raise InjectionPreconditionError("wrong_tool needs at least one planned step and one executed action")
    real_tool = action_steps[0].actual_tool
    if run.planned_steps[0].tool != real_tool:
        raise InjectionPreconditionError("wrong_tool needs the first step to already be a clean match")

    fake_tool = next(t for t in ALL_TOOL_NAMES if t != real_tool)
    new_planned = list(run.planned_steps)
    new_planned[0] = PlannedStep(step_index=0, tool=fake_tool, reason=new_planned[0].reason)

    return run.model_copy(
        update={
            "planned_steps": new_planned,
            "injected_failure": "wrong_tool",
            "ground_truth_divergence_step": 0,
        }
    )


def inject_skip_step(run: AgentRun) -> AgentRun:
    """Remove the last planned step's actual execution (its action step and
    matching observation), simulating the agent skipping a step it planned.
    Forces a deterministic DELETE (skipped_step) divergence. Requires the
    run to have cleanly executed every planned step, one tool call each.
    """
    if len(run.planned_steps) < 2:
        raise InjectionPreconditionError("skip_step needs at least 2 planned steps")

    action_steps = [s for s in run.steps if s.step_type == "action"]
    observation_steps = [s for s in run.steps if s.step_type == "observation"]
    planned_tools = [p.tool for p in run.planned_steps]
    actual_tools = [s.actual_tool for s in action_steps]
    if planned_tools != actual_tools or len(observation_steps) != len(action_steps):
        raise InjectionPreconditionError("skip_step needs a fully clean 1:1 planned/executed run")

    skip_idx = len(run.planned_steps) - 1
    action_to_remove = action_steps[skip_idx]
    observation_to_remove = observation_steps[skip_idx]

    kept_steps = [s for s in run.steps if s is not action_to_remove and s is not observation_to_remove]
    renumbered_steps = [s.model_copy(update={"step_index": i}) for i, s in enumerate(kept_steps)]

    return run.model_copy(
        update={
            "steps": renumbered_steps,
            "injected_failure": "skip_step",
            "ground_truth_divergence_step": skip_idx,
        }
    )


def inject_corrupt_args(run: AgentRun) -> AgentRun:
    """Replace the first executed action's arguments with values clearly
    unrelated to the plan's stated reason. The tool called is still the
    planned one (align() sees a clean MATCH), but classify()'s lexical-
    overlap check should flag args_changed. This is a soft signal, so
    ground_truth_divergence_step stays None: there is no hard divergence to
    find, and correctly NOT flagging one is exactly what's being tested.
    Requires the first step to already be a clean match.
    """
    action_steps = [s for s in run.steps if s.step_type == "action"]
    if not run.planned_steps or not action_steps or action_steps[0].actual_tool != run.planned_steps[0].tool:
        raise InjectionPreconditionError("corrupt_args needs the first step to already be a clean match")

    original_input = action_steps[0].tool_input or {}
    corrupted_input = {k: "zzz_corrupted_unrelated_value_9981" for k in original_input} or {
        "zzz_corrupted_key": "zzz_corrupted_unrelated_value_9981"
    }
    new_steps = [
        s.model_copy(update={"tool_input": corrupted_input}) if s is action_steps[0] else s for s in run.steps
    ]

    return run.model_copy(
        update={
            "steps": new_steps,
            "injected_failure": "corrupt_args",
            "ground_truth_divergence_step": None,
        }
    )


def inject_wrong_tool_and_skip_step(run: AgentRun) -> AgentRun:
    """Compose two injections on the same run, a wrong tool at the start and
    a skipped step near the end, so the run ends up with two real hard
    divergences instead of one. Week 5's injectors only ever produced runs
    with exactly one, which was a real gap in eval coverage found in
    Week 7 Day 1.

    Order matters: skip_step needs a fully clean planned/actual match to
    even run, so it goes first, while the run is still clean. wrong_tool
    only touches position 0 and doesn't care that skip_step already
    shortened the actual sequence, so it goes second. ground_truth_
    divergence_step stays 0, the earlier of the two, since that's what
    first_divergence_index is defined to report.
    """
    skipped = inject_skip_step(run)
    both = inject_wrong_tool(skipped)
    return both.model_copy(update={"injected_failure": "wrong_tool+skip_step"})


INJECTORS = {
    "wrong_tool": inject_wrong_tool,
    "skip_step": inject_skip_step,
    "corrupt_args": inject_corrupt_args,
    "wrong_tool+skip_step": inject_wrong_tool_and_skip_step,
}


def save_run(run: AgentRun) -> Path:
    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DATA_DIR / f"{run.run_id}.jsonl"
    with open(path, "w") as f:
        f.write(run.model_dump_json())
        f.write("\n")
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run a single agent task, capture its trace, and write it to data/raw/."
    )
    parser.add_argument("--task", required=True, help="The task/prompt to give the agent.")
    parser.add_argument(
        "--inject-failure",
        choices=sorted(INJECTORS.keys()),
        help=(
            "Deliberately corrupt the captured run to force a known divergence "
            "(auto-populates ground_truth_divergence_step). Fails clearly if this "
            "task's run isn't shaped right for the chosen injection (e.g. no clean "
            "match to corrupt), try a different --task."
        ),
    )
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY not set (check .env)")

    print(f"=== Running task: {args.task} ===\n")
    run = run_and_capture(args.task)

    if args.inject_failure:
        try:
            run = INJECTORS[args.inject_failure](run)
        except InjectionPreconditionError as e:
            raise SystemExit(f"Cannot inject '{args.inject_failure}' into this run: {e}")

    out_path = save_run(run)
    print(f"\n=== Wrote trace ({run.final_status}, {len(run.steps)} steps) to {out_path} ===")
