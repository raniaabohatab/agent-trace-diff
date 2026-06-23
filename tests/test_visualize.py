"""summarize() is the first thing anyone reads in a demo — test it against
every divergence type the classifier produces, asserting the exact expected
sentence, not just "does it return something."
"""
from src.diff.classify import DivergenceEvent
from src.visualize.render_report import summarize


def test_summarize_no_events():
    assert summarize([]) == "Agent followed its plan exactly — no divergence detected."


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


def test_summarize_ignores_soft_args_changed_when_counting_and_ordering_hard_divergences():
    # An args_changed event sitting before a hard divergence must not be
    # picked as "the first divergence" and must not count toward the
    # "N more" tally.
    events = [
        DivergenceEvent(index=0, kind="args_changed", planned_tool="a", actual_tool="a", detail="soft"),
        DivergenceEvent(index=1, kind="skipped_step", planned_tool="submit", actual_tool=None, detail="hard"),
    ]
    assert summarize(events) == "Agent skipped the planned 'submit' step (step 1)."
