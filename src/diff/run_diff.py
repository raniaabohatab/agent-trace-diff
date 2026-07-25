"""CLI entry point: take normalized AgentRuns from data/normalized/, run
align() + classify() on each, and write DiffResult objects to data/diffs/.

Same per-file resilience pattern as Week 2's run_pipeline.py. One run that
fails to diff (e.g. malformed planned_steps) is logged and skipped, not a
reason to abort the whole batch.
"""
import argparse
import json
from pathlib import Path

from src.diff.align import align
from src.diff.classify import classify
from src.diff.classify import first_divergence_index as compute_first_divergence_index
from src.diff.diff_result import DiffResult, serialize_aligned_pairs
from src.schema import AgentRun

NORMALIZED_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "normalized"
DIFFS_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "diffs"


def diff_run(run: AgentRun) -> DiffResult:
    planned_tools = [s.tool for s in run.planned_steps]
    action_steps = [s for s in run.steps if s.step_type == "action"]
    actual_tools = [s.actual_tool for s in action_steps]

    planned_context = [s.reason for s in run.planned_steps]
    actual_context = [" ".join(str(v) for v in (s.tool_input or {}).values()) for s in action_steps]

    aligned = align(planned_tools, actual_tools, planned_context=planned_context, actual_context=actual_context)
    events = classify(aligned, run)
    fdi = compute_first_divergence_index(events)

    return DiffResult(
        run_id=run.run_id,
        aligned_pairs=serialize_aligned_pairs(aligned),
        divergence_events=events,
        first_divergence_index=fdi,
        plan_followed_exactly=(fdi is None),
    )


def save_diff(result: DiffResult, diffs_dir: Path = DIFFS_DATA_DIR) -> Path:
    diffs_dir.mkdir(parents=True, exist_ok=True)
    path = diffs_dir / f"{result.run_id}.jsonl"
    with open(path, "w") as f:
        f.write(result.model_dump_json())
        f.write("\n")
    return path


def run_diff_all(normalized_dir: Path = NORMALIZED_DATA_DIR, diffs_dir: Path = DIFFS_DATA_DIR) -> dict:
    normalized_files = sorted(normalized_dir.glob("*.jsonl"))
    succeeded, failed = 0, 0

    for path in normalized_files:
        try:
            data = json.loads(path.read_text())
            run = AgentRun.model_validate(data)
            result = diff_run(run)
            save_diff(result, diffs_dir=diffs_dir)
            succeeded += 1
        except Exception as exc:  # noqa: BLE001 - one bad run shouldn't abort the batch
            print(f"[fail] {path.name}: {exc}")
            failed += 1

    total = len(normalized_files)
    print(f"\n{total} normalized runs processed, {succeeded} diffed, {failed} failed")
    return {"total": total, "succeeded": succeeded, "failed": failed}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compute plan-vs-actual diffs for normalized agent runs.")
    parser.add_argument("--all", action="store_true", help="Process every run in data/normalized/.")
    parser.add_argument("--run-id", help="Process a single run by ID (reads data/normalized/{run_id}.jsonl).")
    args = parser.parse_args()

    if args.all:
        run_diff_all()
    elif args.run_id:
        run_path = NORMALIZED_DATA_DIR / f"{args.run_id}.jsonl"
        agent_run = AgentRun.model_validate(json.loads(run_path.read_text()))
        diff_result = diff_run(agent_run)
        out_path = save_diff(diff_result)
        print(f"Wrote {out_path}")
    else:
        parser.error("Provide --all or --run-id")
