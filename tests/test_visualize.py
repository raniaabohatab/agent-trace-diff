"""summarize() is the first thing anyone reads in a demo, test it against
every divergence type the classifier produces, asserting the exact expected
sentence, not just "does it return something."
"""
from src.diff.classify import DivergenceEvent
from src.diff.run_diff import diff_run
from src.schema import AgentRun, PlannedStep, Step
from src.visualize.render_report import _build_rows, _pair_actions_with_observations, render_report, summarize


def _action(step_index, tool, call_id):
    return Step(
        step_index=step_index,
        step_type="action",
        actual_tool=tool,
        tool_input={},
        timestamp="2026-07-21T00:00:00Z",
        tool_call_id=call_id,
    )


def _observation(step_index, tool, output, call_id):
    return Step(
        step_index=step_index,
        step_type="observation",
        actual_tool=tool,
        tool_output=output,
        timestamp="2026-07-21T00:00:00Z",
        tool_call_id=call_id,
    )


def test_summarize_no_events():
    assert summarize([]) == "Agent followed its plan exactly, no divergence detected."


def test_summarize_skipped_step():
    events = [
        DivergenceEvent(
            index=2,
            kind="skipped_step",
            planned_tool="verify",
            actual_tool=None,
            detail="Planned to call 'verify' (double check output) but never did.",
        )
    ]
    assert summarize(events) == "Agent skipped the planned 'verify' step (step 2)."


def test_summarize_unexpected_step():
    events = [
        DivergenceEvent(
            index=1,
            kind="unexpected_step",
            planned_tool=None,
            actual_tool="search",
            detail="Called 'search' with no corresponding planned step.",
        )
    ]
    assert summarize(events) == "Agent called 'search', which wasn't in the plan, at step 1."


def test_summarize_wrong_tool():
    events = [
        DivergenceEvent(
            index=0,
            kind="wrong_tool",
            planned_tool="calculator",
            actual_tool="search",
            detail="Planned to call 'calculator' but called 'search' instead.",
        )
    ]
    assert summarize(events) == "Agent planned to call 'calculator' but called 'search' instead, at step 0."


def test_summarize_args_changed_only_is_distinct_from_no_divergence():
    events = [
        DivergenceEvent(
            index=0,
            kind="args_changed",
            planned_tool="calculator",
            actual_tool="calculator",
            detail="Called 'calculator' as planned, but its arguments don't obviously relate to the stated reason.",
        )
    ]
    assert summarize(events) == (
        "Agent followed its plan exactly (tool-for-tool), though 1 step had arguments "
        "that don't obviously match the plan's stated reason."
    )


def test_summarize_args_changed_only_plural():
    events = [
        DivergenceEvent(index=0, kind="args_changed", planned_tool="a", actual_tool="a", detail="d1"),
        DivergenceEvent(index=1, kind="args_changed", planned_tool="b", actual_tool="b", detail="d2"),
    ]
    assert summarize(events) == (
        "Agent followed its plan exactly (tool-for-tool), though 2 steps had arguments "
        "that don't obviously match the plan's stated reason."
    )


def test_summarize_multiple_hard_divergences_appends_count():
    events = [
        DivergenceEvent(index=0, kind="wrong_tool", planned_tool="search", actual_tool="calc", detail="d1"),
        DivergenceEvent(index=1, kind="skipped_step", planned_tool="submit", actual_tool=None, detail="d2"),
    ]
    assert summarize(events) == (
        "Agent planned to call 'search' but called 'calc' instead, at step 0. "
        "(1 more divergence after this point.)"
    )


def test_summarize_three_hard_divergences_plural_count():
    events = [
        DivergenceEvent(index=0, kind="wrong_tool", planned_tool="search", actual_tool="calc", detail="d1"),
        DivergenceEvent(index=1, kind="skipped_step", planned_tool="submit", actual_tool=None, detail="d2"),
        DivergenceEvent(index=2, kind="unexpected_step", planned_tool=None, actual_tool="notify", detail="d3"),
    ]
    assert summarize(events) == (
        "Agent planned to call 'search' but called 'calc' instead, at step 0. "
        "(2 more divergences after this point.)"
    )


def test_pair_actions_with_observations_uses_tool_call_id_when_out_of_order():
    # Reproduces the real bug found in Week 7: 3 parallel calculator calls
    # requested in order (a, b, c) but their observations come back
    # scrambled (b, c, a). Positional pairing would attribute b's output to
    # a, c's output to b, and a's output to c. Pairing by tool_call_id must
    # get every one right regardless of arrival order.
    run = AgentRun(
        run_id="test",
        task_description="add three pairs of numbers",
        framework="langchain",
        model_name="claude-haiku-4-5",
        final_status="success",
        steps=[
            _action(0, "calculator", "call_a"),
            _action(1, "calculator", "call_b"),
            _action(2, "calculator", "call_c"),
            _observation(3, "calculator", "4", "call_b"),
            _observation(4, "calculator", "6", "call_c"),
            _observation(5, "calculator", "2", "call_a"),
        ],
    )
    pairs = _pair_actions_with_observations(run)
    assert [obs.tool_output for _, obs in pairs] == ["2", "4", "6"]


def test_pair_actions_with_observations_falls_back_to_position_without_call_id():
    # Traces generated before Week 7 have tool_call_id = None on every step.
    # They must still pair by position, exactly like before this fix.
    run = AgentRun(
        run_id="test",
        task_description="add two pairs of numbers",
        framework="langchain",
        model_name="claude-haiku-4-5",
        final_status="success",
        steps=[
            _action(0, "calculator", None),
            _action(1, "calculator", None),
            _observation(2, "calculator", "2", None),
            _observation(3, "calculator", "4", None),
        ],
    )
    pairs = _pair_actions_with_observations(run)
    assert [obs.tool_output for _, obs in pairs] == ["2", "4"]


def test_pair_actions_with_observations_mismatched_tool_name_degrades_gracefully():
    # Legacy positional fallback: if the Nth action and Nth observation
    # don't even agree on tool name, drop the observation instead of
    # showing the wrong tool's output.
    run = AgentRun(
        run_id="test",
        task_description="do two different things",
        framework="langchain",
        model_name="claude-haiku-4-5",
        final_status="success",
        steps=[
            _action(0, "calculator", None),
            _action(1, "search", None),
            _observation(2, "search", "results", None),
            _observation(3, "calculator", "42", None),
        ],
    )
    pairs = _pair_actions_with_observations(run)
    assert [obs.tool_output if obs else None for _, obs in pairs] == [None, None]


def test_build_rows_flags_error_output_separately_from_success_output():
    # Real bug: a tool call that errors ("Error: ...") was rendered with the
    # exact same green success styling as a real result, so a divide by zero
    # looked like it succeeded. actual_output_is_error is the signal the
    # template branches on to fix that.
    run = AgentRun(
        run_id="test",
        task_description="divide by zero then add two numbers",
        framework="langchain",
        model_name="claude-haiku-4-5",
        final_status="success",
        planned_steps=[
            PlannedStep(step_index=0, tool="calculator", reason="divide by zero"),
            PlannedStep(step_index=1, tool="calculator", reason="add two numbers"),
        ],
        plan_was_attempted=True,
        steps=[
            _action(0, "calculator", "call_a"),
            _observation(1, "calculator", "Error evaluating expression: division by zero", "call_a"),
            _action(2, "calculator", "call_b"),
            _observation(3, "calculator", "7", "call_b"),
        ],
    )
    diff = diff_run(run)
    rows = _build_rows(run, diff)
    assert [r["actual_output_is_error"] for r in rows] == [True, False]


def test_render_report_relabels_status_so_it_does_not_contradict_followed_plan():
    # "Status: success" next to "Followed plan: no" reads as a contradiction,
    # since a run can complete fine while still diverging from its plan.
    # The label and the displayed text both changed to describe the run
    # itself, not the outcome.
    run = AgentRun(
        run_id="test",
        task_description="do one thing",
        framework="langchain",
        model_name="claude-haiku-4-5",
        final_status="success",
        planned_steps=[PlannedStep(step_index=0, tool="calculator", reason="need to add")],
        plan_was_attempted=True,
        steps=[_action(0, "search", "call_a"), _observation(0, "search", "result", "call_a")],
    )
    diff = diff_run(run)
    html = render_report(run, diff)
    assert ">Run<" in html
    assert ">completed<" in html
    assert ">success<" not in html


def test_summarize_ignores_soft_args_changed_when_counting_and_ordering_hard_divergences():
    # An args_changed event sitting before a hard divergence must not be
    # picked as "the first divergence" and must not count toward the
    # "N more" tally.
    events = [
        DivergenceEvent(index=0, kind="args_changed", planned_tool="a", actual_tool="a", detail="soft"),
        DivergenceEvent(index=1, kind="skipped_step", planned_tool="submit", actual_tool=None, detail="hard"),
    ]
    assert summarize(events) == "Agent skipped the planned 'submit' step (step 1)."
