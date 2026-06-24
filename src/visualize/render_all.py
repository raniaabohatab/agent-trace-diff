"""Batch-render every DiffResult in data/diffs/ into a standalone HTML
report. Same per-file resilience pattern as Week 2's run_pipeline.py and
Week 3's run_diff.py --all.
"""
from pathlib import Path

from src.visualize.render_report import (
    DIFFS_DATA_DIR,
    NORMALIZED_DATA_DIR,
    REPORTS_DIR,
    load_run_and_diff,
    render_and_save,
)


def render_all(
    diffs_dir: Path = DIFFS_DATA_DIR,
    normalized_dir: Path = NORMALIZED_DATA_DIR,
    reports_dir: Path = REPORTS_DIR,
) -> dict:
    diff_files = sorted(diffs_dir.glob("*.jsonl"))
    succeeded, failed = 0, 0

    for path in diff_files:
        run_id = path.stem
        try:
            run, diff = load_run_and_diff(run_id, normalized_dir=normalized_dir, diffs_dir=diffs_dir)
            render_and_save(run, diff, reports_dir=reports_dir)
            succeeded += 1
        except Exception as exc:  # noqa: BLE001 - one bad report shouldn't abort the batch
            print(f"[fail] {run_id}: {exc}")
            failed += 1

    total = len(diff_files)
    print(f"\n{total} diffs processed, {succeeded} rendered, {failed} failed")
    return {"total": total, "succeeded": succeeded, "failed": failed}


if __name__ == "__main__":
    render_all()
