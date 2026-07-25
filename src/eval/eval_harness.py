"""Measure how well align()/classify() detect divergence against hand-labeled
ground truth. This script only measures, it does not modify align.py or
classify.py to chase a better number. That's explicitly Week 6's job, done
as a separate, deliberate iteration step with its own before/after
comparison.

Metrics are reported per source_category, plus a "primary" aggregate that
excludes external_no_plan cases. Those cases are structurally guaranteed to
produce first_divergence_index==0 (no plan exists to diverge from, see
docs/decisions.md, 2026-06-29 and 2026-07-02). Folding them into a single
blended accuracy number would inflate it with cases the algorithm cannot
get wrong by construction, which is exactly the kind of thing this project's
"honest measurement" discipline exists to catch.
"""
import argparse
import json
from pathlib import Path

from src.diff.run_diff import diff_run
from src.schema import AgentRun

EVAL_SET_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "eval" / "eval_set.jsonl"
NORMALIZED_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "normalized"

PRIMARY_CATEGORIES = {"self_constructed_failure", "clean_control"}


def load_eval_set(path: Path = EVAL_SET_PATH) -> list[dict]:
    with open(path, "r") as f:
        return [json.loads(line) for line in f if line.strip()]


def _outcome(predicted: int | None, ground_truth: int | None) -> str:
    """Classify one case's result against the four categories this project cares about."""
    if predicted == ground_truth:
        return "exact_match"
    if ground_truth is None:
        # Algorithm flagged a divergence on a case that shouldn't have one.
        return "false_positive"
    if predicted is None:
        # A real divergence existed and the algorithm reported none.
        return "miss"
    if abs(predicted - ground_truth) <= 1:
        return "within_tolerance"
    return "miss"


def _empty_stats() -> dict:
    return {"count": 0, "exact_match": 0, "within_tolerance": 0, "false_positive": 0, "miss": 0}


def _accumulate(stats: dict, outcome: str) -> None:
    stats["count"] += 1
    stats[outcome] += 1


def _finalize_stats(stats: dict) -> dict:
    count = stats["count"]
    if count == 0:
        return {**stats, "accuracy_exact": None, "accuracy_tolerance_1": None}
    correct_exact = stats["exact_match"]
    correct_tolerance_1 = stats["exact_match"] + stats["within_tolerance"]
    return {
        **stats,
        "accuracy_exact": correct_exact / count,
        "accuracy_tolerance_1": correct_tolerance_1 / count,
    }


def run_eval(eval_set_path: Path = EVAL_SET_PATH, normalized_dir: Path = NORMALIZED_DATA_DIR) -> dict:
    cases = load_eval_set(eval_set_path)

    by_category: dict[str, dict] = {}
    primary = _empty_stats()
    clean_only = _empty_stats()  # for false-positive rate specifically
    per_case_results = []

    for case in cases:
        run_id = case["run_id"]
        category = case["source_category"]
        ground_truth = case["ground_truth_divergence_step"]

        run_path = normalized_dir / f"{run_id}.jsonl"
        run = AgentRun.model_validate(json.loads(run_path.read_text()))
        diff = diff_run(run)
        predicted = diff.first_divergence_index

        outcome = _outcome(predicted, ground_truth)

        by_category.setdefault(category, _empty_stats())
        _accumulate(by_category[category], outcome)

        if category in PRIMARY_CATEGORIES:
            _accumulate(primary, outcome)
        if category == "clean_control":
            _accumulate(clean_only, outcome)

        per_case_results.append(
            {
                "run_id": run_id,
                "source_category": category,
                "task_description": case.get("task_description"),
                "predicted_first_divergence_index": predicted,
                "ground_truth_divergence_step": ground_truth,
                "outcome": outcome,
            }
        )

    clean_finalized = _finalize_stats(clean_only)
    false_positive_rate = (
        clean_finalized["false_positive"] / clean_finalized["count"] if clean_finalized["count"] else None
    )

    return {
        "total_cases": len(cases),
        "by_category": {cat: _finalize_stats(s) for cat, s in by_category.items()},
        "primary": _finalize_stats(primary),
        "primary_false_positive_rate": false_positive_rate,
        "per_case_results": per_case_results,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the evaluation harness against data/eval/eval_set.jsonl.")
    parser.add_argument("--eval-set", type=Path, default=EVAL_SET_PATH)
    args = parser.parse_args()

    results = run_eval(eval_set_path=args.eval_set)

    print(f"Total cases: {results['total_cases']}\n")
    for category, stats in results["by_category"].items():
        print(f"[{category}] n={stats['count']}")
        print(f"  exact_match={stats['exact_match']}  within_tolerance={stats['within_tolerance']}  "
              f"false_positive={stats['false_positive']}  miss={stats['miss']}")
        if stats["accuracy_exact"] is not None:
            print(f"  accuracy_exact={stats['accuracy_exact']:.3f}  accuracy_tolerance_1={stats['accuracy_tolerance_1']:.3f}")
        print()

    p = results["primary"]
    print(f"PRIMARY (self_constructed_failure + clean_control), n={p['count']}")
    print(f"  accuracy_exact={p['accuracy_exact']:.3f}  accuracy_tolerance_1={p['accuracy_tolerance_1']:.3f}")
    if results["primary_false_positive_rate"] is not None:
        print(f"  false_positive_rate (on clean_control)={results['primary_false_positive_rate']:.3f}")
