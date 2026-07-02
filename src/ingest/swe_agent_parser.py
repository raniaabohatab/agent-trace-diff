"""Concrete TraceParser for real external agent trajectories from the
nebius/SWE-agent-trajectories dataset (SWE-agent attempting real GitHub
issues from SWE-bench). Not AgentBench — see docs/decisions.md, 2026-06-29,
for why: AgentBench's public repo has task specs and Docker configs, not
recorded transcripts; getting real traces out of it means running their
whole harness, a much bigger lift than adapting an existing dataset.

SWE-agent is ReAct-style with no upfront plan (same as the project's own
Week 1 legacy traces) — planned_steps is always empty here, deliberately,
not a parsing gap. See docs/decisions.md, 2026-06-29, for what that means
for how these cases are scored in Week 5's evaluation.
"""
import json
import logging
import re

from src.ingest.base import TraceParser
from src.schema import AgentRun, Step

logger = logging.getLogger(__name__)

_COMMAND_RE = re.compile(r"```\s*\n(.*?)\n```", re.DOTALL)
_DISCUSSION_RE = re.compile(r"DISCUSSION\s*\n(.*?)(?:\n\s*COMMAND|\Z)", re.DOTALL)


def _extract_command_and_thought(text: str) -> tuple[str | None, str | None]:
    """SWE-agent's ACI format is consistently 'DISCUSSION\\n<reasoning>\\n\\nCOMMAND\\n```\\n<cmd>\\n```'."""
    if not text:
        return None, None
    command_match = _COMMAND_RE.search(text)
    command = command_match.group(1).strip() if command_match else None
    discussion_match = _DISCUSSION_RE.search(text)
    thought = discussion_match.group(1).strip() if discussion_match else text.strip()
    return command, thought


def _tool_name_from_command(command: str) -> str:
    """First whitespace-separated token of the command as the 'tool name'
    (e.g. 'find_file "x.py" lexicon' -> 'find_file', 'ls -F' -> 'ls').
    SWE-agent's ACI verbs (open, edit, search_dir, find_file, submit, ...)
    plus raw bash both work fine with this — it's just "the command word.\""""
    return command.split()[0] if command.strip() else "unknown"


class SWEAgentTraceParser(TraceParser):
    def can_parse(self, raw_path: str) -> bool:
        try:
            with open(raw_path, "r") as f:
                line = f.readline().strip()
            if not line:
                return False
            data = json.loads(line)
            return isinstance(data, dict) and data.get("framework") == "swe_agent_bench"
        except (OSError, json.JSONDecodeError):
            return False

    def parse(self, raw_path: str) -> AgentRun:
        try:
            with open(raw_path, "r") as f:
                line = f.readline().strip()
        except OSError as e:
            raise ValueError(f"Could not read {raw_path}: {e}") from e

        if not line:
            raise ValueError(f"{raw_path} is empty")

        try:
            data = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"{raw_path} is not valid JSON: {e}") from e

        required = ["run_id", "instance_id", "model_name", "target_resolved", "trajectory"]
        missing = [k for k in required if k not in data]
        if missing:
            raise ValueError(f"{raw_path} is missing required field(s): {missing}")

        trajectory = data["trajectory"]
        if not isinstance(trajectory, list) or not trajectory:
            raise ValueError(f"{raw_path} has an empty or malformed trajectory")

        task_description = f"SWE-bench issue: {data['instance_id']}"
        for entry in trajectory:
            if entry.get("role") == "user" and entry.get("text"):
                # First user turn is the issue statement -- use it (trimmed) as
                # a more useful task_description than the bare instance_id.
                issue_text = entry["text"].split("ISSUE:", 1)[-1].strip()
                task_description = issue_text[:200]
                break

        steps: list[Step] = []
        step_index = 0
        pending_tool_for_observation = None
        for entry in trajectory:
            role = entry.get("role")
            text = entry.get("text")
            if role == "system":
                continue
            if role == "ai":
                command, thought = _extract_command_and_thought(text)
                if command:
                    tool = _tool_name_from_command(command)
                    steps.append(
                        Step(
                            step_index=step_index,
                            step_type="action",
                            actual_tool=tool,
                            tool_input={"command": command},
                            raw_thought=thought,
                            timestamp=entry.get("cutoff_date") or "1970-01-01T00:00:00Z",
                        )
                    )
                    pending_tool_for_observation = tool
                else:
                    # No command block -- treat as a final answer (e.g. the
                    # agent's closing summary after `submit`).
                    steps.append(
                        Step(
                            step_index=step_index,
                            step_type="final_answer",
                            raw_thought=thought,
                            timestamp=entry.get("cutoff_date") or "1970-01-01T00:00:00Z",
                        )
                    )
                    pending_tool_for_observation = None
                step_index += 1
            elif role == "user" and pending_tool_for_observation is not None:
                # This is the observation for the action step we just added
                # (the first "user" turn, the issue statement, has no
                # preceding action and is skipped by the None check).
                steps.append(
                    Step(
                        step_index=step_index,
                        step_type="observation",
                        actual_tool=pending_tool_for_observation,
                        tool_output=text,
                        timestamp=entry.get("cutoff_date") or "1970-01-01T00:00:00Z",
                    )
                )
                pending_tool_for_observation = None
                step_index += 1

        return AgentRun(
            run_id=data["run_id"],
            task_description=task_description,
            framework="swe_agent_bench",
            model_name=data["model_name"],
            steps=steps,
            planned_steps=[],  # ReAct-style, no upfront plan -- see module docstring
            plan_was_attempted=False,
            final_status="failure" if not data["target_resolved"] else "success",
            ground_truth_divergence_step=None,  # hand-labeled in Week 5 Day 4
        )
