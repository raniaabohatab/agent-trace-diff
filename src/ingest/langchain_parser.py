"""Concrete TraceParser for the JSONL format src/generate_traces.py writes.

We control both the writer (generate_traces.py) and this reader, so in
principle this is just deserialize + validate. Treated with the same
robustness a stranger's malformed file would need anyway, because Week 3+
pulling in outside failure traces (AgentBench, SWE-bench) will need it.
"""
import json
import logging

from pydantic import ValidationError

from src.ingest.base import TraceParser
from src.schema import AgentRun

logger = logging.getLogger(__name__)

_KNOWN_FIELDS = set(AgentRun.model_fields.keys())


def _read_first_line(raw_path: str) -> str:
    with open(raw_path, "r") as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                return stripped
    return ""


class LangChainTraceParser(TraceParser):
    def can_parse(self, raw_path: str) -> bool:
        try:
            line = _read_first_line(raw_path)
            if not line:
                return False
            data = json.loads(line)
            return isinstance(data, dict) and data.get("framework") == "langchain"
        except (OSError, json.JSONDecodeError):
            return False

    def parse(self, raw_path: str) -> AgentRun:
        try:
            line = _read_first_line(raw_path)
        except OSError as e:
            raise ValueError(f"Could not read {raw_path}: {e}") from e

        if not line:
            raise ValueError(f"{raw_path} is empty")

        try:
            data = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"{raw_path} is not valid JSON: {e}") from e

        if not isinstance(data, dict):
            raise ValueError(f"{raw_path} does not contain a JSON object at the top level")

        extra_fields = set(data.keys()) - _KNOWN_FIELDS
        if extra_fields:
            logger.warning(
                "%s has unrecognized field(s) %s — ignoring them (forward compatibility)",
                raw_path,
                sorted(extra_fields),
            )

        try:
            return AgentRun.model_validate(data)
        except ValidationError as e:
            problems = "; ".join(
                f"field '{'.'.join(str(p) for p in err['loc'])}': {err['msg']}" for err in e.errors()
            )
            raise ValueError(f"{raw_path} failed schema validation — {problems}") from e
