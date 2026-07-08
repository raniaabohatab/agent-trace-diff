# Evaluation Results

Run: `python -m src.eval.eval_harness`, against `data/eval/eval_set.jsonl` (49 cases),
2026-07-07. These are the actual numbers from that run — nothing rounded, averaged
away, or excluded. `align.py`/`classify.py` were not modified to produce this result;
per the Week 5 spec, tuning against these numbers is explicitly Week 6's job, done
separately.

## Raw numbers

| Category | n | Exact match | Within ±1 | False positive | Miss | Accuracy (exact) | Accuracy (±1) |
|---|---|---|---|---|---|---|---|
| `self_constructed_failure` | 21 | 21 | 0 | 0 | 0 | 1.000 | 1.000 |
| `external_no_plan` | 18 | 18 | 0 | 0 | 0 | 1.000 | 1.000 |
| `clean_control` | 10 | 10 | 0 | 0 | 0 | 1.000 | 1.000 |
| **Total** | **49** | **49** | 0 | 0 | 0 | **1.000** | **1.000** |

**Primary metric** (`self_constructed_failure` + `clean_control`, excluding
`external_no_plan` — see below for why): **n=31, accuracy_exact = 1.000,
accuracy_tolerance_1 = 1.000, false_positive_rate (on clean_control) = 0.000.**

Breakdown of `self_constructed_failure` by injection type, checked specifically for
a per-type pattern: `wrong_tool` 7/7, `skip_step` 7/7, `corrupt_args` 7/7. No
difference between injection types — each is detected correctly every time.

## What this 100% actually means — and doesn't

A perfect score across every category is the real result of this run, not a rounded
or cherry-picked one. But reporting it without context would overstate what it shows,
and the honest version of this section is more useful than the number alone.

**`external_no_plan` (18/18) is not a meaningful accuracy signal at all.** These are
real external SWE-agent trajectories, but they're ReAct-style with no upfront plan
(`planned_steps = []`), so `first_divergence_index` is trivially 0 for every one of
them by the algorithm's own definition — there's no plan for execution to diverge
from, so the very first action always aligns as unplanned. Scoring 18/18 here just
confirms the algorithm behaves predictably on that structural edge case applied to
real, messy, external data — it says nothing about whether the algorithm can find a
meaningful divergence point in a trace that never had a plan to begin with. This is
exactly why it's excluded from the primary metric (decided 2026-06-29, before any of
these numbers existed) rather than blended in as if it were an equally strong result.

**`self_constructed_failure` (21/21) is a real result, but a narrower one than it
first looks.** These cases are constructed by directly manipulating the same
`planned_steps`/`actual_tool` sequences `align()` reads (Week 5 Day 2) — swapping a
tool name, removing a step, corrupting arguments — and the alignment algorithm being
tested is the same one already covered by 12 hand-verified synthetic tests (Week 3
Day 5) and validated against 32 real traces by hand (Week 3 Day 6). So 21/21 here is
closer to confirming "the well-tested Week 3 algorithm still runs correctly at this
larger scale" than it is an independent test of judgment on ambiguous real-world
cases. It's not a meaningless result — it's a genuine regression check — but it
shouldn't be read as "the algorithm has been proven correct on hard cases."

**`clean_control` (10/10) is close to true by construction.** These 10 were selected
specifically because they already have an exact `planned_steps == actual_tools`
match (verified programmatically before inclusion, Week 5 Day 4) — the algorithm
would have to have a real bug to get these wrong.

## The real, harder evidence isn't in this table

The eval set, by design, doesn't currently contain a case that would produce a
`miss` — that's worth stating plainly rather than leaving implicit. The most
concrete, real limitation found in this project so far doesn't show up here at all:
**Week 3 Day 6 found a real, confirmed case where the algorithm pairs the *wrong*
occurrence of a repeated tool** (`036aca4a`: a plan reasoning about "45 divided by 9"
got paired against the actual `100 / 0` call, with the real `45 / 9` call flagged as
unexpected instead — evidence was the plan's own reason text naming the values in
the *other* call). That's a genuine bug in the fine-grained alignment. But
`first_divergence_index` — the only thing this harness scores — was still correct in
that case (`0`, both predicted and by inspection), because the bug affects *which*
occurrence gets blamed, not *whether* a divergence is detected or *where* it starts.
**This is a real, useful finding about the eval methodology itself**: a metric can
read as perfect while a known, documented bug still exists, because the metric and
the bug operate at different levels of granularity. Anyone asking "so the algorithm
is bug-free?" should get this section as the answer, not the 100% alone.

## What would actually stress-test this

A harder, more informative eval set would need cases that are independent of the
alignment code being tested — e.g., hand-authored traces with repeated tools and a
known-correct pairing (testing the exact limitation above), or held-out real traces
scored by someone other than the person who built the algorithm. Both are reasonable
Week 6+ extensions; neither exists in this eval set today, and pretending otherwise
would be exactly the kind of inflated number this project's Week 5 discipline is
built to avoid.

See `data/eval/labeling_notes.md` for how every hand-labeled ground truth value was
determined, and `docs/decisions.md` (2026-06-29 through 2026-07-06) for the full
reasoning behind the eval set's design.
