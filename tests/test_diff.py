"""Diff algorithm tests against small, hand-constructed cases with a known
correct answer — deliberately separate from real messy agent data (that's
Week 3 Day 6). Every expected AlignOp / DivergenceEvent / first_divergence_index
here was worked out by hand, not just asserted against whatever the code
happened to produce.
"""
from src.diff.align import AlignOp, align
from src.diff.classify import classify, first_divergence_index
from src.diff.diff_result import serialize_aligned_pairs
from src.diff.run_diff import diff_run
from src.schema import AgentRun, PlannedStep, Step


def make_run(planned_tools: list[str], actual_tools: list[str], tool_inputs: list[dict] | None = None) -> AgentRun:
    """Build a minimal synthetic AgentRun for diff-algorithm testing.

    tool_inputs (one dict per actual step, default {}) lets tests control
    the args_changed heuristic; an empty dict never triggers it, so plain
    alignment tests aren't accidentally polluted by the soft signal.
    """
    tool_inputs = tool_inputs or [{} for _ in actual_tools]
    planned_steps = [
        PlannedStep(step_index=i, tool=tool, reason="test reason") for i, tool in enumerate(planned_tools)
    ]
    steps = [
        Step(
            step_index=i,
            step_type="action",
            actual_tool=tool,
            tool_input=tool_inputs[i],
            timestamp="2026-06-12T00:00:00Z",
        )
        for i, tool in enumerate(actual_tools)
    ]
    return AgentRun(
        run_id=f"test-{'-'.join(planned_tools) or 'none'}-{'-'.join(actual_tools) or 'none'}",
        task_description="synthetic test run",
        framework="langchain",
        model_name="test-model",
        steps=steps,
        planned_steps=planned_steps,
        final_status="success",
    )


def diff_of(planned_tools, actual_tools, tool_inputs=None):
    run = make_run(planned_tools, actual_tools, tool_inputs)
    aligned = align(planned_tools, actual_tools)
    events = classify(aligned, run)
    return aligned, events


def test_exact_match():
    aligned, events = diff_of(["search", "calc"], ["search", "calc"])
    assert [p.op for p in aligned] == [AlignOp.MATCH, AlignOp.MATCH]
    assert events == []
    assert first_divergence_index(events) is None


def test_single_insertion():
    aligned, events = diff_of(["search", "calc"], ["search", "file_read", "calc"])
    ops = [(p.op, p.planned_index, p.actual_index) for p in aligned]
    assert ops == [
        (AlignOp.MATCH, 0, 0),
        (AlignOp.INSERT, None, 1),
        (AlignOp.MATCH, 1, 2),
    ]
    assert len(events) == 1
    assert events[0].kind == "unexpected_step"
    assert events[0].actual_tool == "file_read"
    assert first_divergence_index(events) == 1


def test_single_deletion():
    aligned, events = diff_of(["search", "calc", "submit"], ["search", "submit"])
    ops = [(p.op, p.planned_index, p.actual_index) for p in aligned]
    assert ops == [
        (AlignOp.MATCH, 0, 0),
        (AlignOp.DELETE, 1, None),
        (AlignOp.MATCH, 2, 1),
    ]
    assert len(events) == 1
    assert events[0].kind == "skipped_step"
    assert events[0].planned_tool == "calc"
    assert first_divergence_index(events) == 1


def test_substitution():
    aligned, events = diff_of(["search"], ["calc"])
    assert [p.op for p in aligned] == [AlignOp.SUBSTITUTE]
    assert len(events) == 1
    assert events[0].kind == "wrong_tool"
    assert events[0].planned_tool == "search"
    assert events[0].actual_tool == "calc"
    assert first_divergence_index(events) == 0


def test_no_planned_steps_edge_case():
    # Agent had no plan at all (e.g. a legacy pre-Plan-and-Execute trace) but
    # still executed a step. Should not crash, should classify as unexpected.
    aligned, events = diff_of([], ["search"])
    assert [p.op for p in aligned] == [AlignOp.INSERT]
    assert len(events) == 1
    assert events[0].kind == "unexpected_step"
    assert first_divergence_index(events) == 0


def test_empty_actual_steps_edge_case():
    # Agent produced a plan but crashed/stopped before executing anything.
    aligned, events = diff_of(["search"], [])
    assert [p.op for p in aligned] == [AlignOp.DELETE]
    assert len(events) == 1
    assert events[0].kind == "skipped_step"
    assert first_divergence_index(events) == 0


def test_both_empty_sequences():
    aligned, events = diff_of([], [])
    assert aligned == []
    assert events == []
    assert first_divergence_index(events) is None


def test_repeated_consecutive_tool_matches_cleanly():
    # Classic off-by-one alignment trap: identical tools back-to-back must
    # not get misaligned as a spurious insert+delete pair.
    aligned, events = diff_of(["read_file", "read_file"], ["read_file", "read_file"])
    ops = [(p.op, p.planned_index, p.actual_index) for p in aligned]
    assert ops == [
        (AlignOp.MATCH, 0, 0),
        (AlignOp.MATCH, 1, 1),
    ]
    assert events == []


def test_multiple_divergences_in_one_run():
    # Two fully-unrelated tool names at each position: the minimum-cost
    # alignment is two substitutions (cost 2), strictly cheaper than
    # deleting both and inserting both (cost 4) -- hand-verifiable.
    aligned, events = diff_of(["alpha", "beta"], ["gamma", "delta"])
    assert [p.op for p in aligned] == [AlignOp.SUBSTITUTE, AlignOp.SUBSTITUTE]
    assert len(events) == 2
    assert all(e.kind == "wrong_tool" for e in events)
    assert first_divergence_index(events) == 0


def test_args_changed_soft_signal_does_not_count_as_hard_divergence():
    # Tool matches the plan, but the arguments share no words with the
    # plan's stated reason -> args_changed should fire, but it must NOT be
    # picked up by first_divergence_index (it's explicitly a soft signal).
    aligned, events = diff_of(
        ["calculator"],
        ["calculator"],
        tool_inputs=[{"expression": "completely unrelated string"}],
    )
    assert [p.op for p in aligned] == [AlignOp.MATCH]
    assert len(events) == 1
    assert events[0].kind == "args_changed"
    assert first_divergence_index(events) is None  # soft signal, not a hard divergence


def test_args_changed_not_triggered_when_words_overlap():
    run = make_run(
        ["calculator"],
        ["calculator"],
        tool_inputs=[{"expression": "15 * 200 / 100"}],
    )
    # Give the plan a reason that shares a word ("total") with... nothing in the
    # expression, but shares "compute"/"percent"-adjacent wording deliberately.
    run.planned_steps[0] = PlannedStep(step_index=0, tool="calculator", reason="need to compute 200 total")
    aligned = align(["calculator"], ["calculator"])
    events = classify(aligned, run)
    assert events == []  # "200" appears in both -> tokens overlap, no args_changed


def test_diff_run_end_to_end_wiring():
    run = make_run(["search", "calc"], ["search", "file_read", "calc"])
    result = diff_run(run)
    assert result.run_id == run.run_id
    assert result.first_divergence_index == 1
    assert result.plan_followed_exactly is False
    assert len(result.divergence_events) == 1
    assert result.aligned_pairs == serialize_aligned_pairs(align(["search", "calc"], ["search", "file_read", "calc"]))


def test_align_without_context_keeps_old_tie_breaking_behavior():
    # No context given, so a repeated tool ties toward the diagonal first,
    # same as before Week 6. This locks in the old behavior for every
    # caller that doesn't pass context.
    aligned = align(["calculator"], ["calculator", "calculator"])
    ops = [(p.op, p.planned_index, p.actual_index) for p in aligned]
    assert ops == [
        (AlignOp.INSERT, None, 0),
        (AlignOp.MATCH, 0, 1),
    ]


def test_align_with_context_breaks_repeated_tool_tie_correctly():
    # This is the real case from Week 3 Day 6 (run 036aca4a), reproduced as a
    # hand constructed test: a plan step whose reason names a value that only
    # shows up in the FIRST of two identical tool calls. Without context, the
    # backtrack pairs the plan with the second call instead (see the test
    # above). With context, it correctly pairs the plan with the first call
    # and flags the second as unexpected.
    planned_tools = ["calculator"]
    actual_tools = ["calculator", "calculator"]
    planned_context = ["need to compute 45 divided by 9"]
    actual_context = ["45 / 9", "100 / 0"]

    aligned = align(planned_tools, actual_tools, planned_context=planned_context, actual_context=actual_context)
    ops = [(p.op, p.planned_index, p.actual_index) for p in aligned]
    assert ops == [
        (AlignOp.MATCH, 0, 0),
        (AlignOp.INSERT, None, 1),
    ]


def test_align_with_context_falls_back_to_diagonal_when_both_sides_relate():
    # If context doesn't clearly rule out the diagonal pairing, keep the old
    # diagonal-first behavior rather than guessing.
    aligned = align(
        ["calculator"],
        ["calculator", "calculator"],
        planned_context=["compute the total"],
        actual_context=["10 total", "20 total"],
    )
    ops = [(p.op, p.planned_index, p.actual_index) for p in aligned]
    assert ops == [
        (AlignOp.INSERT, None, 0),
        (AlignOp.MATCH, 0, 1),
    ]


def test_diff_run_uses_context_for_repeated_tool_pairing():
    # Same scenario as test_align_with_context_breaks_repeated_tool_tie_correctly,
    # but through the real diff_run() wiring, confirming run_diff.py actually
    # passes context through rather than just align() supporting it in theory.
    run = make_run(
        ["calculator"],
        ["calculator", "calculator"],
        tool_inputs=[{"expression": "45 / 9"}, {"expression": "100 / 0"}],
    )
    run.planned_steps[0] = PlannedStep(step_index=0, tool="calculator", reason="need to compute 45 divided by 9")

    result = diff_run(run)

    assert result.aligned_pairs[0] == {"planned_index": 0, "actual_index": 0, "op": AlignOp.MATCH}
    assert result.aligned_pairs[1] == {"planned_index": None, "actual_index": 1, "op": AlignOp.INSERT}
    assert result.first_divergence_index == 1
