import pytest
from pydantic import ValidationError

from src.schema import AgentRun, Step


def make_valid_run() -> AgentRun:
    return AgentRun(
        run_id="a1b2c3d4-0000-0000-0000-000000000000",
        task_description="What is 23 * 17?",
        framework="langchain",
        model_name="claude-haiku-4-5",
        steps=[
            Step(
                step_index=0,
                step_type="action",
                actual_tool="calculator",
                tool_input={"expression": "23 * 17"},
                raw_thought="I'll use the calculator tool.",
                timestamp="2026-05-18T21:00:00Z",
            ),
            Step(
                step_index=1,
                step_type="observation",
                actual_tool="calculator",
                tool_output="391",
                timestamp="2026-05-18T21:00:01Z",
            ),
            Step(
                step_index=2,
                step_type="final_answer",
                raw_thought="23 * 17 = 391",
                timestamp="2026-05-18T21:00:02Z",
            ),
        ],
        final_status="success",
    )


def test_valid_agent_run_parses_correctly():
    run = make_valid_run()
    assert run.run_id == "a1b2c3d4-0000-0000-0000-000000000000"
    assert run.framework == "langchain"
    assert len(run.steps) == 3
    assert run.steps[0].actual_tool == "calculator"
    assert run.steps[1].tool_output == "391"
    assert run.ground_truth_divergence_step is None  # not filled in until Week 5


def test_step_missing_required_field_raises_validation_error():
    with pytest.raises(ValidationError):
        # missing step_type and timestamp
        Step(step_index=0)


def test_agent_run_round_trip_json_preserves_all_fields():
    run = make_valid_run()
    serialized = run.model_dump_json()
    restored = AgentRun.model_validate_json(serialized)
    assert restored == run
    assert restored.model_dump() == run.model_dump()
