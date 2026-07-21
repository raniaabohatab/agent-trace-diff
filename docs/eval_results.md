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

## Week 6 rerun (2026-07-11), after the repeated tool tie breaking fix

Same command, same `eval_set.jsonl`, run again after fixing the bug described above
in `align.py`. Here is the honest result: nothing moved.

| Category | n | Exact match | Within ±1 | False positive | Miss | Accuracy (exact) | Accuracy (±1) |
|---|---|---|---|---|---|---|---|
| self_constructed_failure | 21 | 21 | 0 | 0 | 0 | 1.000 | 1.000 |
| external_no_plan | 18 | 18 | 0 | 0 | 0 | 1.000 | 1.000 |
| clean_control | 10 | 10 | 0 | 0 | 0 | 1.000 | 1.000 |

Primary accuracy is still 1.000 exact and 1.000 within one step, and the false
positive rate on clean controls is still 0.000. Every number here is identical to
the Week 5 run.

That is not a mistake and it is not a wasted week. The fix was real. Two traces in
the full 71 trace corpus changed, `036aca4a` and `c2750ec6`, and both now pair the
plan with the correct occurrence of a repeated tool. Neither trace happens to be one
of the 49 cases in `eval_set.jsonl`, so this particular eval set was never able to
see the bug, and it was never going to see the fix either. That is a real limit of
the current eval set, not a limit of the fix. Week 7 adds cases with a tool called
several times in a row specifically so a future run of this harness can actually
measure something like this instead of missing it entirely.

The honest one line summary for this week: found a real bug, fixed it, confirmed the
fix on the traces that exposed it, and the current eval set is not built to detect
either the bug or the fix. All three of those things are true at once, and the
project is better for knowing it.

## Week 7 rerun (2026-07-20), at 77 cases instead of 49

Same command, the expanded eval set from Week 7, which specifically fills gaps the
Week 6 set had: multi step plans for the self constructed injectors instead of just
one step ones, a combined injector that produces two real hard divergences in one
run instead of always exactly one, longer plans, 8 more external cases from 8 new
GitHub issues, and 3 more clean controls with longer plans.

| Category | n | Exact match | Accuracy (exact) |
|---|---|---|---|
| self_constructed_failure | 38 | 38 | 1.000 |
| external_no_plan | 26 | 26 | 1.000 |
| clean_control | 13 | 13 | 1.000 |

Primary accuracy is still 1.000 exact, now on n=51 instead of n=31. Still 100 percent,
and this time that is a somewhat stronger claim than Week 5 or Week 6's, not a
weaker one. The new cases specifically target things the algorithm had never been
tested against: a run with two real divergences instead of one, and a run that gets
the first step wrong but correctly matches every step after it, the recovers after a
mistake case Week 7 Day 1 identified as missing. The algorithm handles both
correctly, which is a real result at this scale, not a coincidence carried over from
easier cases, since these specific cases did not exist before this week.

The same honest limits from the Week 5 and Week 6 write ups still apply and are not
solved by adding more cases built the same way. self constructed cases still share
the same alignment assumptions as the code being tested, and external cases are still
trivially guaranteed by the algorithm's own definition. A bigger number of cases
built the same way is more evidence within that scope, not evidence outside it. The
`first_divergence_index` metric still cannot see the repeated tool tie breaking bug's
effect on pairing, because that bug never touches which position is reported first,
only which occurrence gets blamed.
