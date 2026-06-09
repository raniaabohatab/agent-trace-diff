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
from datetime import datetime, timezone
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
    except Exception as e:
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
    return datetime.now(timezone.utc).isoformat()


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
    before any execution happens. This is a separate call from execution —
    the model is not in an agent loop here, just asked to plan.

    Never raises: a plan that fails to parse is a soft failure (empty plan,
    logged to stdout), not a reason to abandon the whole trace — this
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
    except Exception as exc:  # noqa: BLE001 - a bad plan shouldn't abort the whole trace
        if verbose:
            print(f"--- plan generation failed, using empty plan: {exc} ---\n")
        return []


def _format_plan_for_execution(planned_steps: list[PlannedStep]) -> str:
    if not planned_steps:
        return ""
    lines = "\n".join(f"{s.step_index + 1}. {s.tool} — {s.reason}" for s in planned_steps)
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
    whatever steps were captured before the error — partial runs are still
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
            for _node_name, node_output in chunk.items():
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
                                )
                        else:
                            add_step(step_type="final_answer", raw_thought=thought)
                    elif msg_type == "ToolMessage":
                        add_step(
                            step_type="observation",
                            actual_tool=getattr(message, "name", None),
                            tool_output=message.content,
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
        final_status=final_status,
    )


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
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY not set (check .env)")

    print(f"=== Running task: {args.task} ===\n")
    run = run_and_capture(args.task)
    out_path = save_run(run)
    print(f"\n=== Wrote trace ({run.final_status}, {len(run.steps)} steps) to {out_path} ===")
