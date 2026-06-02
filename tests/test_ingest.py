import json

import pytest

from src.ingest.langchain_parser import LangChainTraceParser
from src.ingest.run_pipeline import run_pipeline
from src.schema import AgentRun

VALID_RUN = {
    "run_id": "11111111-1111-1111-1111-111111111111",
    "task_description": "What is 2 + 2?",
    "framework": "langchain",
    "model_name": "claude-haiku-4-5",
    "steps": [
        {
            "step_index": 0,
            "step_type": "action",
            "actual_tool": "calculator",
            "tool_input": {"expression": "2 + 2"},
            "timestamp": "2026-06-01T12:00:00Z",
        },
        {
            "step_index": 1,
            "step_type": "observation",
            "actual_tool": "calculator",
            "tool_output": "4",
            "timestamp": "2026-06-01T12:00:01Z",
        },
    ],
    "final_status": "success",
}


def write_jsonl(path, data: dict) -> str:
    path.write_text(json.dumps(data) + "\n")
    return str(path)


def test_parsing_well_formed_trace_produces_matching_agent_run(tmp_path):
    raw_path = write_jsonl(tmp_path / "good.jsonl", VALID_RUN)

    run = LangChainTraceParser().parse(raw_path)

    assert isinstance(run, AgentRun)
    assert run.run_id == VALID_RUN["run_id"]
    assert run.task_description == VALID_RUN["task_description"]
    assert run.framework == "langchain"
    assert run.final_status == "success"
    assert len(run.steps) == 2
    assert run.steps[0].actual_tool == "calculator"
    assert run.steps[1].tool_output == "4"


def test_parsing_missing_required_field_raises_value_error(tmp_path):
    broken = {k: v for k, v in VALID_RUN.items() if k != "task_description"}
    raw_path = write_jsonl(tmp_path / "missing_field.jsonl", broken)

    with pytest.raises(ValueError, match="task_description"):
        LangChainTraceParser().parse(raw_path)


def test_parsing_extra_unknown_fields_succeeds(tmp_path, caplog):
    with_extra = {**VALID_RUN, "some_future_field": "not in the schema yet"}
    raw_path = write_jsonl(tmp_path / "extra_field.jsonl", with_extra)

    with caplog.at_level("WARNING"):
        run = LangChainTraceParser().parse(raw_path)

    assert run.run_id == VALID_RUN["run_id"]
    assert "some_future_field" in caplog.text


def test_can_parse_rejects_non_langchain_format(tmp_path):
    openai_style = {"framework": "openai", "run_id": "x"}
    raw_path = write_jsonl(tmp_path / "openai.jsonl", openai_style)

    assert LangChainTraceParser().can_parse(raw_path) is False


def test_can_parse_rejects_garbage_file(tmp_path):
    raw_path = tmp_path / "garbage.txt"
    raw_path.write_text("this is not json at all {{{")

    assert LangChainTraceParser().can_parse(str(raw_path)) is False


def test_pipeline_produces_expected_normalized_count(tmp_path):
    raw_dir = tmp_path / "raw"
    normalized_dir = tmp_path / "normalized"
    raw_dir.mkdir()

    # 2 valid LangChain traces, 1 malformed LangChain trace, 1 non-LangChain file.
    write_jsonl(raw_dir / "run1.jsonl", {**VALID_RUN, "run_id": "aaaaaaaa-0000-0000-0000-000000000000"})
    write_jsonl(raw_dir / "run2.jsonl", {**VALID_RUN, "run_id": "bbbbbbbb-0000-0000-0000-000000000000"})
    write_jsonl(raw_dir / "broken.jsonl", {"framework": "langchain", "run_id": "only-this"})
    write_jsonl(raw_dir / "other_framework.jsonl", {"framework": "openai", "run_id": "z"})

    summary = run_pipeline(raw_dir=raw_dir, normalized_dir=normalized_dir)

    assert summary == {"total": 4, "succeeded": 2, "failed": 2}
    normalized_files = sorted(p.name for p in normalized_dir.glob("*.jsonl"))
    assert normalized_files == [
        "aaaaaaaa-0000-0000-0000-000000000000.jsonl",
        "bbbbbbbb-0000-0000-0000-000000000000.jsonl",
    ]

    unparsed_log = (normalized_dir / "_unparsed.log").read_text()
    assert "broken.jsonl" in unparsed_log
    assert "other_framework.jsonl" in unparsed_log
