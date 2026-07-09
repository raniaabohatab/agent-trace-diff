# Labeling Notes

Justification for every hand-labeled (non-auto-generated) `ground_truth_divergence_step`
value in `eval_set.jsonl`. Self-constructed injected-failure cases (Week 5 Day 2) are
**not** here — their ground truth is auto-populated at generation time by construction
(the injector sets it directly, verified 21/21 against the algorithm's own output on
2026-06-30) and doesn't need separate justification.

## External cases (18, from `nebius/SWE-agent-trajectories`)

**Every external case gets `ground_truth_divergence_step = 0`.** This is not a
per-case judgment call — it follows mechanically from a fact confirmed by actually
reading all 18 trajectories: SWE-agent is ReAct-style and never produces an upfront
plan (`planned_steps = []`, `plan_was_attempted = false`, for every single one). Given
this project's specific definition of divergence — the first point where actual
execution departs from *the plan* — a run with no plan at all trivially diverges at
its very first action, by the algorithm's own stated semantics, not by an
interpretation I'm imposing after the fact. I confirmed this structural fact for
every case (checked that `plan_was_attempted=false` and at least one real action
exists) rather than assuming it applied uniformly just because it held for the first
few.

**This is a different, narrower claim than "where did the agent's problem-solving
actually go wrong," and I want to be explicit about that distinction** rather than
let the number imply more than it means. `ground_truth_divergence_step=0` here tests
whether the pipeline handles a real, structurally different external format correctly
and predictably (a robustness/edge-case check) — it does **not** test whether the
algorithm can identify the point in a 10-20 step trajectory where the agent's actual
reasoning went astray. That's a different, harder problem (something closer to
step-quality judgment or outcome attribution) that this project's plan-vs-actual
alignment isn't designed to answer, and Week 6's honest-reporting discipline is
better served by saying so directly than by letting a clean "0" look like a richer
result than it is.

### What I actually found reading these (real analysis, not scored — supplementary)

Reading all 18 end to end surfaced genuine patterns worth recording, even though none
of it feeds `ground_truth_divergence_step`:

- **`TheFriendlyCoder__pyjen-113`** (`97ba3057`) — the agent's first real edit attempt
  (step 8-10) claims success, then immediately admits at step 12 "the previous edit
  commands didn't quite work as expected," and needs a second retry at step 14 for an
  indentation mistake before finally converging by step 16-18. The trajectory reaches
  `submit`, reads as confident throughout, and still has `target=False` (the benchmark's
  real test suite says the fix wasn't actually correct/complete). If I were hand-labeling
  "where did this go wrong" in the richer sense, I'd say step 8 — not step 0.

- **`casbin__pycasbin-53`** (`55be4e7f`, `ca180b61`) — the underlying GitHub issue itself
  is vague ("bring pycasbin in track with casbin-core... implement missing features,"
  no specific bug or scope named). The agent's approach (search the local repo, then
  try `curl`-ing casbin's docs/GitHub page when nothing local matched) is a reasonable
  strategy given a genuinely underspecified task, not an obvious agent mistake. This is
  a case where the *task* looks poorly scoped for a single-PR fix, which matters for
  interpreting `target=False` honestly — an unresolved issue isn't always evidence the
  agent reasoned badly.

- **`auth0__auth0-python-477`** (`de3b977d`) — by contrast, a clean, well-scoped issue
  (add specific missing API endpoints) with an agent trajectory that reads as
  genuinely competent: locates the right file methodically (`ls` → `open` →
  `branding.py`), then adds three endpoint methods one at a time, each edit landing
  cleanly. If this one still shows `target=False`, the likely story is a narrower
  correctness gap (wrong parameter name, missed edge case) rather than an approach
  failure — worth knowing when reading Week 6's results, since not every "unresolved"
  case looks alike.

- **`asottile__pyupgrade-142`** (`490a703b`, `5783479c`) — a real self-caught mistake:
  step 10 tries to navigate to a line number before opening the file, and the agent's
  own next turn says so plainly ("It seems I forgot to open the file before trying to
  navigate"). Recovers immediately and proceeds normally. A concrete example of an
  agent's actual execution — as opposed to a plan — containing its own visible error
  and correction, which this project's diff algorithm has no way to see at all
  (it only compares tool-call sequences, not the reasoning between them).

- **`asottile__pyupgrade-147`** (`c5814d40`, model `swe-agent-llama-8b`, the weaker
  model in this dataset) — this is the case that surfaced the parser bug described in
  `docs/decisions.md` (2026-07-02): its second turn quotes a `% pyupgrade ...` command
  from the GitHub issue text inside its own fenced-code reasoning, then states the real
  command in a second, later fence. Confirmed against the actual tool output that
  followed (a traceback matching the second command, not the first) before fixing the
  extraction logic — not assumed.

## Day 7 re-review (2026-07-08)

Re-read `eval_set.jsonl` end to end a second time, specifically looking for labeling
errors now that the harness had run — including checking whether the algorithm's
100% agreement might mean *my* labels were wrong in a way that happened to match a
consistent bug rather than the algorithm being right. Structural checks: no duplicate
`run_id`s, category/ground-truth consistency holds for all 49 entries (every
`clean_control` has `null`, every `external_no_plan` has `0`), no truncated or
suspiciously short `task_description` values. Spot-read all 18 external
`task_description` extracts again — all genuine, readable GitHub issue excerpts, no
parsing corruption. Found no corrections to make. Re-ran the harness after this
review to confirm nothing had drifted: identical 49/49 results.

## Clean control cases (10, from the Week 3/4 corpus)

No hand-labeling needed — `ground_truth_divergence_step = None` for all 10, because
each was already verified, mechanically and independently of any label I might assign,
to have `planned_steps == [actual tools executed]` (an exact tool-for-tool match) via
the same programmatic check used throughout Weeks 3-4. Selected for variety: single-tool
matches, multi-tool chains, and the two genuine "planned zero tools, executed zero
tools" cases (`9b335d47`, `9eae1430`) that motivated the `plan_was_attempted` field
fix on 2026-06-23.
