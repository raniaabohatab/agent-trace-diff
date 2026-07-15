# Decisions Log

## 2026-05-18

- **Optional fields need explicit `= None` defaults in Pydantic v2.** The spec's
  `Step`/`AgentRun` code block writes `Optional[str]` with no default — in Pydantic v1
  that implicitly meant "defaults to None", but Pydantic v2 removed that implicit
  behavior: `Optional[str]` with no default is a *required* field that merely accepts
  `None` as a value. Added explicit `= None` to every field that should actually be
  optional (`planned_tool`, `actual_tool`, `tool_input`, `tool_output`, `raw_thought`),
  keeping `step_index`, `step_type`, and `timestamp` genuinely required so the
  "missing required field raises ValidationError" test has something real to check.

- **`planned_tool` will stay unused for now, per the spec's own fallback plan.**
  LangChain's tool-calling loop doesn't expose a separate "planned tool" distinct from
  the tool it actually calls — a model turn just contains `tool_use` blocks, which
  directly become `actual_tool` on `action` steps. `raw_thought` (the model's leading
  text before/around a tool call) is what gets captured instead. Week 3's diff
  algorithm will need to infer "planned" from `raw_thought` text rather than compare
  it directly against `actual_tool` — this was anticipated in the spec itself, not a
  gap I'm discovering later.

## 2026-05-20

- **Trace capture uses `agent.stream(..., stream_mode="updates")`, not a
  `BaseCallbackHandler`.** The spec's Day 3-4 plan assumes callback hooks
  (`on_agent_action`, `on_tool_start`, etc.) from the old `AgentExecutor` API. The
  LangGraph-based `create_agent` doesn't fire those the same way, but its `stream()`
  already yields exactly the structured data needed (`AIMessage`s with `tool_calls`,
  `ToolMessage`s with `.name`/`.content`) keyed by graph node — building `Step`s
  directly from that stream is less code and no less reliable than a callback handler
  would be. Verified the message shapes (`tool_calls` is `[{"name", "args", "id",
  "type"}]`, `ToolMessage.name`/`.content`) against a live run before writing the
  capture logic, rather than assuming from memory.

- **`python -m src.generate_traces`, not `python src/generate_traces.py`.** The script
  does `from src.schema import ...`, which needs the repo root on `sys.path`. Running
  the file directly puts `src/` itself on `sys.path[0]` (not the repo root), so the
  import fails; running as a module (`-m`) does not have that problem. Chose this over
  a `sys.path.insert()` hack at the top of the script to keep the import style
  consistent with `tests/`, which already imports `from src.schema import ...`.

- **Partial runs are kept, not discarded, on error.** `run_and_capture` wraps the
  streaming loop in `try/except`; on any exception it sets `final_status="failure"`,
  appends one observation step noting the error, and still returns/saves whatever
  steps were captured before the failure — per the spec, partial failure traces are
  useful data for later evaluation, not something to throw away.

## 2026-05-21

- **Generated 14 raw traces from 10 task prompts** (3 run twice for variation across
  the model's non-determinism), landing inside the spec's 12-15 target. Deliberately
  included tasks designed to *not* cleanly succeed: a search query with no canned
  match, a read of a file that isn't in the canned set, and a divide-by-zero.

- **Spot-checking 3 traces by eye surfaced real, useful behavior, not just schema
  bugs** (the point of the spot-check, per the spec):
  - `Calculate 5 divided by 0` produced a **1-step trace with no tool call at all** —
    the model answered from its own math knowledge instead of invoking the
    calculator. Worth keeping in mind for Week 3: "didn't call the tool it was
    expected to" is itself a kind of divergence, not just "called the wrong tool."
  - `15 percent of 200` got rewritten to the tool-safe expression `15 * 200 / 100`
    rather than sent as `15% * 200` — the calculator tool's character allowlist
    (`0-9+-*/(). `) doesn't include `%`, and the model worked around that on its own
    without being told to.
  - The Mars-colonies search (no canned match) produced a clean fallback: the model
    read the "no specific data found" observation and answered from its own
    knowledge rather than stalling or hallucinating a fabricated result.

## 2026-05-26

- **`TraceParser` is an ABC, not a plain function.** A single `parse_trace(path)`
  function would work for the one parser we have today, but Week 3+ and any future
  framework support (raw OpenAI function-calling logs, AgentBench/SWE-bench imports)
  need a stable contract to add a new parser against without touching the pipeline
  runner. `can_parse`/`parse` as two separate abstract methods (rather than one method
  that raises if it can't handle the file) lets the pipeline runner try several
  parsers per file cheaply, without relying on exceptions for control flow.

## 2026-05-28

- **Forward-compatible field handling via a manual key-diff before validation,
  not `model_config = ConfigDict(extra="forbid")`.** Pydantic v2's default is
  already "ignore extra fields silently" — that alone satisfies "don't fail," but the
  spec also wants a visible warning when it happens. Diffing `data.keys()` against
  `AgentRun.model_fields.keys()` before validation, logging anything unexpected, then
  letting `model_validate` do its normal (extra-ignoring) thing gets both: a warning
  for visibility, and validation logic that doesn't have to duplicate what pydantic
  already does.

- **`can_parse` swallows errors and returns `False`; `parse` raises informative
  `ValueError`s.** These have different jobs — `can_parse` is a cheap probe the
  pipeline runner calls on every file against every registered parser, so it must
  never throw (a bad file should just mean "no match found," not crash the batch).
  `parse` is only called after a match, so it's fine — better, per the spec — for it
  to fail loudly with the file path and exact field(s) involved.

- **Verified against the real 14-trace corpus before writing a single test.** All 14
  raw files parse successfully with `can_parse` correctly true for each, plus quick
  manual checks that a non-LangChain file is rejected, an extra field warns without
  failing, and a missing required field raises a `ValueError` naming the file and the
  missing fields. Wanted this working against real data first — Week 2 Day 5's actual
  test suite formalizes these same checks, it doesn't discover them for the first time.

## 2026-05-29

- **`_unparsed.log` is deleted when there's nothing to report, not left stale.**
  A pipeline that always writes the file (even empty) leaves a confusing artifact
  after a clean run; one that never checks leaves last run's failures looking current
  after a fix. Wrote it only when `unparsed_lines` is non-empty and delete it if it
  exists from a prior run, so its mere presence is a meaningful signal.

- **Confirmed resilience by hand before trusting it**: dropped a garbage non-JSON
  file into `data/raw/` and reran — it was cleanly logged to `_unparsed.log`
  ("no registered parser matched this file") and the other 14 real traces still
  processed and normalized correctly. This is the actual behavior the spec's
  "one bad file should never take down the pipeline" requirement is about, not just
  something asserted in a docstring.

## 2026-06-01

- **`run_pipeline()` takes optional `raw_dir`/`normalized_dir` args instead of only
  ever reading the real `data/raw/`.** Defaults still point at the real project
  directories, so `python -m src.ingest.run_pipeline` behaves exactly as before. But
  the "full pipeline produces expected count" test needs a *fixed* known input to
  assert an exact count against — pointing it at the real `data/raw/` would make the
  test's expected count drift every time the corpus grows, which is exactly the kind
  of test that looks broken later for no code reason. Testing against a small
  tmp_path fixture (2 good, 1 malformed, 1 wrong-framework) is a stronger check of the
  actual routing logic than the real corpus would be anyway.

- **6 ingest tests, not just the 5 the spec listed** — added a "can_parse rejects a
  file that isn't even valid JSON" case (`garbage.txt`) alongside the spec's 5,
  since `can_parse` swallowing `json.JSONDecodeError` (vs. just "wrong framework
  value") was a real code path that needed its own coverage.

## 2026-06-03

- **Full integration pass: clean rerun from scratch, byte-for-byte diff on 3
  raw→normalized pairs.** Deleted `data/normalized/` entirely and reran the pipeline
  against the full 14-file raw corpus: 14/14 succeeded, no `_unparsed.log` produced.
  Then diffed 3 raw files (chosen for variety — a 5-step multi-tool run, the 1-step
  no-tool-call divide-by-zero run, and a 5-step multi-file-read run) against their
  normalized counterparts as parsed dicts: all three were exact matches. Nothing is
  silently dropped or reshaped in the raw → parse → validate → normalize path, which
  is exactly what Week 2's "no data corrupted in translation" check is for — and
  worth confirming explicitly rather than assuming it from the code, since parse/
  validate/re-serialize is precisely the kind of round trip that silently drops a
  field if a bug is introduced later.

## 2026-06-08

- **Plan-and-Execute, not pure ReAct.** Week 1's agent thinks and acts one step at a
  time with no upfront plan, which means there's no clean "planned sequence" to diff
  against "actual sequence" — the core thing this project needs. Added one upfront
  LLM call (`make_plan()`) that asks the model to output an ordered JSON plan of
  intended tool calls before any execution happens, completely separate from the
  agent's actual execution loop.

- **The plan is fed back into the execution prompt, not left as an independent,
  disconnected sample.** The spec's Day 1 text says to "proceed with normal
  step-by-step execution as before," which could be read as two fully independent
  LLM calls about the same task. I fed the generated plan into the execution prompt
  instead (`_format_plan_for_execution`, appended to the task message: "you
  previously planned X, follow it but adapt if needed") so that when execution
  deviates from the plan, it's a genuine adaptation the model is making against a
  plan it was told to follow — not just two uncorrelated samples that happen to
  differ. This produces more meaningful divergence data for the diff algorithm to
  be tested against. Confirmed it actually working end-to-end on a live run before
  generating the rest of the batch: one task's plan said `["calculator"]` and its
  actual execution was `["calculator", "search"]` — a real, observed insertion.

- **`planned_steps` defaults to an empty list, not a required field.** This keeps
  all 14 of the real Week 1 traces (generated before this change, no upfront plan)
  loading correctly through the exact same schema and pipeline — an empty plan
  against a non-empty actual sequence becomes a legitimate edge case the alignment
  algorithm has to handle (and Week 3 Day 5's test plan already calls for exactly
  this case), rather than a breaking schema migration that forces discarding or
  regenerating the existing corpus. Verified: all 20 raw traces (14 old + 6 new)
  normalize cleanly through the unmodified Week 2 pipeline, and all 9 existing tests
  pass unchanged.

- **A plan that fails to parse produces an empty plan, not a failed run.** `make_plan()`
  never raises — a malformed JSON response from the planning call is a soft failure
  (logged, empty `planned_steps`), because the execution trace is still valuable data
  even when the upfront plan came back unusable. Didn't hit this in practice across
  6 real runs, but the failure mode is real (free-form JSON extraction from an LLM
  response, not a schema-validated tool call) and shouldn't be able to take down
  trace capture.

## 2026-06-09

- **Uniform cost (match=0, substitute=1, insert=1, delete=1), not a weighted cost
  function.** A smarter cost function — e.g. penalizing a substitution less than an
  insertion+deletion pair when two tool names are semantically similar (`search` vs.
  `web_search`) — is a real, known possible improvement. Deliberately deferred: with
  only 3 tool names in the current corpus there's no semantic-similarity signal to
  exploit yet, and starting simple keeps the alignment easy to reason about and debug
  before adding a dimension of complexity that would need its own justification and
  tests. Recorded here explicitly so it reads as a deferred decision, not an
  oversight, if it comes up later.

- **`AlignedPair` is a plain `@dataclass`, not a pydantic `BaseModel`.** Nothing about
  alignment output needs pydantic's validation — it's produced by `align()` itself,
  never parsed from untrusted external input the way `AgentRun` is. A dataclass gives
  free `__eq__`/`__repr__` (useful for the Day 5 tests, which assert exact
  `AlignedPair` equality) without the validation overhead pydantic is for.

- **Sanity-checked the DP core by hand against 8 cases (exact match, insert, delete,
  substitute, empty-planned, empty-actual, repeated-consecutive-tool, and a mixed
  case) before moving on to `classify.py`.** Not a replacement for Day 5's real test
  suite — just confirming the backtracking logic is sound before building more code
  on top of it. All 8 produced the expected minimum-cost alignment on inspection,
  including the repeated-tool case, which is the classic off-by-one trap for this
  kind of DP backtrack.

## 2026-06-10

- **`args_changed` detection uses a plain lexical word-overlap heuristic, not an LLM
  call.** The only signal available is the plan's free-text `reason` string versus
  the executed step's `tool_input` dict — there's no structured "planned arguments"
  to diff numerically. Tokenize both (lowercased, stopwords stripped, words >2 chars),
  flag `args_changed` when the two token sets are fully disjoint. This is a known-crude
  signal — a reason like "compute the total" and args `{"expression": "15 * 200 / 100"}`
  share zero words but are clearly related — which is exactly why the spec treats
  `args_changed` as soft (excluded from `first_divergence_index`, never a hard
  divergence). Same category of deferred-precision decision as Day 2's uniform
  alignment cost: simple and honest about its limits now, a candidate for a real
  semantic-similarity check later if it turns out to matter.

- **`DivergenceEvent` is a pydantic `BaseModel`, unlike `AlignedPair`.** `AlignedPair`
  is purely internal to `align()`/`classify()` and never leaves this module in
  serialized form. `DivergenceEvent` does — Day 4's `DiffResult` holds a typed
  `list[DivergenceEvent]` and gets written to `data/diffs/{run_id}.jsonl`, so it needs
  the same validate-and-serialize behavior as every other schema type in this project.

- **Verified against all 5 real Plan-and-Execute traces with non-empty plans**: the
  4 that matched their plan exactly produced zero divergence events (including zero
  false positives from the `args_changed` heuristic), and the one genuine divergence
  (`planned=[calculator]`, `actual=[calculator, search]`) correctly classified as a
  single `unexpected_step` at index 1, with `first_divergence_index == 1`.

## 2026-06-11

- **`run_diff_all` catches per-run exceptions and keeps going**, same resilience
  pattern as Week 2's `run_pipeline.py` — one run that fails to diff shouldn't abort
  the batch. Ran cleanly against all 20 normalized runs (0 failures) on the first try,
  so this hasn't been exercised by a real failure yet, but the shape matches the
  project's established pattern rather than introducing a new one.

- **Known interpretive caveat, found while spot-checking output, not something to
  quietly special-case:** for the 14 legacy Week 1 traces (empty `planned_steps`,
  predating the Plan-and-Execute change), every executed step aligns as `INSERT` and
  gets classified `unexpected_step` — technically correct (there's nothing to match
  against an empty sequence), but semantically it means "no plan exists for this
  trace," not "the agent deviated from its plan." `plan_followed_exactly: false` on a
  legacy trace should be read as "not applicable," not "divergence detected." This
  matters concretely for Week 5: legacy no-plan traces should not be silently folded
  into the evaluation set as genuine divergence-detection ground truth — noting it
  now so Week 5 Day 1's sourcing strategy accounts for it rather than discovering it
  as a labeling bug later.

## 2026-06-12

- **12 synthetic test cases, not the spec's minimum 8-10** — added two beyond the
  required list: an explicit "args_changed fires but is excluded from
  `first_divergence_index`" case (the soft-vs-hard distinction is the single most
  important nuance in `classify.py`'s contract, and it deserves its own test rather
  than being incidentally covered), and a full `diff_run()` end-to-end wiring test
  (align → classify → `DiffResult` assembly), since Day 4's wiring code had no direct
  test coverage yet — everything up to now only exercised `align()`/`classify()`
  individually or against real data by hand.

- **Every expected value in `test_diff.py` was derived by hand before running the
  test, not back-filled from whatever the code produced.** For the "multiple
  divergences" case specifically: `planned=["alpha","beta"]`, `actual=["gamma",
  "delta"]` — worked out that the minimum-cost alignment must be two substitutions
  (cost 2: 1+1) rather than delete-both-insert-both (cost 4: 1+1+1+1) before writing
  the assertion, so the test is checking the algorithm against a known-correct
  answer, not against its own output.

## 2026-06-15

- **Expanded the real corpus to 32 traces** (14 legacy + 6 from Day 1 + 12 new,
  deliberately chosen to provoke real divergence: conditional tasks whose plan can't
  know the branch outcome in advance, tasks needing more tool calls than planned,
  a "don't use tools" instruction against a plan that expected one). `run_pipeline.py`
  and `run_diff.py --all` both processed all 32 with zero failures.

- **Real, genuine limitation found and confirmed with hard evidence — documented,
  not silently patched, per this week's explicit instruction on ambiguity vs. bug.**
  When the same tool appears more than once in both the plan and the actual
  execution, the DP can have multiple equal-cost valid alignments, and which specific
  occurrence gets paired with which is decided by backtrack order alone — `align()`
  only ever looks at tool *names*, never at `tool_input` or the plan's `reason` text.
  Two real examples surfaced this by hand:
  - `036aca4a...` — plan: `[calculator]`, reason *"need to compute 45 divided by 9"*.
    Actual: `[calculator(45/9), calculator(100/0)]`. The algorithm paired the plan
    against the **second** call (`100/0`) and flagged the **first** (`45/9` — the one
    the reason literally names) as `unexpected_step`. Backwards, by inspection.
  - `c2750ec6...` — plan: `[calculator, search]`. Actual: `[calculator, search("year
    63 AD historical events significance"), search("63 AD Roman history")]` — the
    agent retried its search with a refined query after an empty result. Here there's
    no clearly "right" answer at all (both searches genuinely serve the one planned
    intent), which is the kind of ambiguity the spec anticipated as legitimate rather
    than fixable.
  - **Both are the same underlying gap**: alignment is tool-name-only, per Day 2's
    "uniform cost, no semantic signal" decision — this is that decision's limitation
    showing up in practice, not a new one. A natural fix exists (when a DP tie
    involves repeated occurrences of the same tool, break it using the same
    `tool_input`/`reason` lexical-overlap check `classify.py` already computes for
    `args_changed`) but isn't implemented now — that would mean `align()` needing
    `AgentRun` context it currently doesn't take, a real interface change, not a
    one-line patch, and Day 2 already scoped richer signal as deferred work.
  - **Mitigating and worth stating plainly: `first_divergence_index` — the number
    Week 5 actually evaluates — was correct in both cases** (`1` and, when checked
    against a similar pattern, unaffected). The ambiguity is confined to *which*
    same-tool occurrence gets blamed in the fine-grained `aligned_pairs`/event detail,
    not to whether a divergence gets detected or where it first occurs.

- **Sanity-checked 2 of the clean-match cases too** (a 3-tool sequential chain and a
  2x-`read_file`-with-different-filenames case) — both correctly show as exact
  matches at the tool-name level, which is the alignment's actual scope; per-argument
  correctness within a match is `args_changed`'s job, not `align()`'s.

## 2026-06-17

- **Static HTML report generator, not a live web server or SPA.** Zero-dependency to
  view (open the file, no server to run), trivially shareable (attach to an email,
  embed in a portfolio page), and works with no internet connection since everything
  — CSS included — is inlined into one file per report. This is a deliberate scope
  decision, not a shortcut taken to skip building a frontend: the time saved not
  standing up a server goes toward making the report itself genuinely legible, which
  is the actual goal (see Week 4's stated 30-second legibility bar).

- **Report layout, designed before writing any code:**
  - **Summary header** above everything: task description, final status, count of
    hard divergence events, and a one-line plain-English summary generated
    programmatically from `classify.py`'s output (Week 4 Day 3's `summarize()` — no
    LLM call, template logic keyed on `kind` and position).
  - **Two columns below the header**: planned steps on the left, actual steps on the
    right, connected by the alignment — each `AlignedPair` becomes one horizontal row
    spanning both columns, so a `match` shows the same tool on both sides at the same
    row, an `insert` shows an empty left cell, a `delete` shows an empty right cell.
  - **Color coding per row**, keyed to `AlignOp`/`DivergenceEvent.kind`: green
    background = match (with no `args_changed` event), yellow = match with
    `args_changed`, red = substitute (`wrong_tool`), gray with a dashed border =
    insert or delete (nothing on the other side to compare against).
  - **The first hard divergence gets a distinct marker** — a red left border on its
    row — so it's the first thing a viewer's eye lands on, matching
    `first_divergence_index` being the single most important number in the whole
    pipeline.

## 2026-06-19

- **`summarize()` stays a pure function of `divergence_events` alone** (no `AgentRun`
  or `DiffResult` argument) — it takes the same input `classify.py` already produces,
  which keeps Day 4's planned unit tests (exact string assertions per divergence
  `kind`) simple and independent of report-rendering concerns. Describes the first
  *hard* divergence in one sentence, then appends a parenthetical count if there are
  more; `args_changed`-only runs get a distinct "followed its plan, but arguments
  looked off" sentence rather than being silently folded into "no divergence."

- **Legacy no-plan traces get a distinct summary sentence, not `summarize()`'s
  normal output.** Rendering a real report for one of the 14 pre-Plan-and-Execute
  traces surfaced exactly the interpretive trap flagged on 2026-06-11: `summarize()`
  would say "Agent called 'read_file', which wasn't in the plan" — accurate per the
  alignment math, but misleading to a reader, who'd take that as "the agent went
  off-script" rather than "there was no plan at all for this trace." Fixed at the
  `render_report()` level (check `run.planned_steps` before calling `summarize()`)
  rather than inside `summarize()` itself, so `summarize()` stays a pure function of
  divergence events — this is a report-legibility fix, not an algorithm fix, and
  belongs in the layer that owns "what does a human reading this need to know."

- **Verified 3 real reports render as well-formed HTML** (checked via Python's
  `html.parser` — no unclosed/mismatched tags) and read correctly: a genuine
  divergence case shows the right summary and marks the right row as first-divergence,
  a clean-match case shows "followed its plan exactly," and the legacy no-plan case
  now shows the corrected message above.

## 2026-06-22

- **9 exact-string tests for `summarize()`, not the spec's minimum 3-4** — one per
  divergence kind (`skipped_step`, `unexpected_step`, `wrong_tool`), plus the
  args_changed-only sentence (singular and plural), the multi-divergence count
  suffix (singular "1 more divergence" vs. plural "2 more divergences" — a classic
  off-by-one for hand-written pluralization), and a case specifically checking that a
  soft `args_changed` event sitting *before* a hard divergence in the list doesn't get
  picked as "the first divergence" or counted in the "N more" tally. Asserting exact
  strings (not just "returns non-empty" or "contains the tool name") is deliberate —
  this function's whole job is to read naturally, and a test that only checks
  presence of a substring wouldn't catch an awkward or misleading sentence.

## 2026-06-23

- **`render_all.py`, same per-file resilience pattern as every batch script in this
  project.** Ran cleanly against all 32 diffs on the first try.

- **Readability review (9 reports, read as a stranger seeing them for the first
  time) surfaced two real bugs, not just "looks fine":**
  - **Real bug, found by comparing files, not by reading one in isolation**: two
    Day 6 stress-batch traces (`9b335d47`, `9eae1430`) genuinely planned an empty
    tool sequence *and* executed zero tools — a correct, deliberate exact match, not
    a missing plan. But `render_report.py`'s `if not run.planned_steps` check (from
    2026-06-19) couldn't tell that apart from a true legacy no-plan trace, since both
    produce the same empty-list shape. Fixed properly: added `plan_was_attempted:
    bool = False` to `AgentRun` (schema.py), set `True` unconditionally in
    `generate_traces.py` now that `make_plan()` always runs, and backfilled the 18
    already-generated raw files that genuinely went through planning (identified
    precisely — not guessed — by checking which raw JSON files literally contain a
    `planned_steps` key at all, since the 14 true-legacy files predate the field
    existing in the schema). Considered relying on pydantic's `model_fields_set`
    instead of a new field — rejected because `run_pipeline.py`'s
    `model_dump_json()` re-serializes every field regardless of whether it was
    explicitly set, so that distinction is already lost by the time a report reads
    from `data/normalized/`, not something to recover after the fact.
  - **Empty-state gap**: a run with zero aligned rows (the case above) rendered the
    diff section as a blank block under the "Planned / Actual" headers — reads as a
    broken or incomplete report to a first-time viewer, not "there's nothing to show
    because everything matched trivially." Added an explicit `.empty-state` message
    in the template for `{% if not rows %}`.
  - Re-verified after both fixes: the genuine empty-plan match now correctly reads
    "Agent followed its plan exactly," the true legacy case still correctly reads
    "no plan captured," and the empty-rows case shows an explanatory message instead
    of a blank area. All 30 tests still pass; `render_all.py` re-run clean.

## 2026-06-24

- **Added tool outputs to the report — a real gap, not originally in the Day 2-3
  build.** The report showed planned reasons and actual arguments but never what a
  tool actually *returned*, which matters: rendering `036aca4a`'s report with outputs
  now visibly shows the second `calculator` call returned `"Error evaluating
  expression: division by zero"` — context a reader needs and the report was
  silently missing.

- **Pairing an action step with its observation isn't always "next step in the
  list."** A single AIMessage can request multiple parallel tool calls, which
  appends several "action" steps in a row before their "observation" steps arrive
  (also in a row) — confirmed on a real 2-parallel-call trace (`807835da`):
  `action(calc), action(search), observation(calc), observation(search)`, not
  alternating. Fixed by pairing the Nth action-step with the Nth observation-step by
  position within each filtered list (ToolMessages return in the same order their
  tool_calls were requested), with a same-tool-name sanity check per pair that
  degrades to "no output shown" rather than mis-attributing one tool's output to a
  different tool's row if that assumption ever breaks.

- **Collapsible `<details>` for long outputs (>150 chars), inline for short ones.**
  The real corpus's longest tool output is only 111 characters — canned test data is
  naturally short — so no real report actually exercises the collapsing path.
  Verified it directly with a synthetic 200-character output instead of trusting
  that a code path nothing in the corpus reaches actually works.

## 2026-06-29

- **Two-source eval set: self-constructed injected failures + one external benchmark**,
  not either alone — a single-source eval set is fairly criticized as unrepresentative
  (self-constructed cases only prove the algorithm works on failures shaped like the
  ones I imagined; external cases only prove it on someone else's data, with no clean
  ground truth). Both together are stronger than either.

- **AgentBench investigated first (as the spec suggested) and rejected — for a
  real, checked reason, not assumed.** Pulled its actual repo structure via the GitHub
  API: `data/<env>/` holds task *specifications* (descriptions, setup scripts, grading
  criteria) and Docker environment definitions, not recorded agent transcripts.
  Getting real failure traces out of it means running their full harness — Docker,
  their `src/` framework, live model calls — against those task specs myself, which is
  a different and much larger undertaking than "adapt a subset of pre-existing
  traces." The spec explicitly permits falling back to an alternative when a benchmark
  format is awkward to work with; this is that case, not a shortcut.

- **`SWE-bench/experiments` checked next — also rejected**, for the same underlying
  reason: it publishes aggregate *results* (resolved/unresolved counts, patch stats),
  not per-step tool-call trajectories.

- **Landed on `nebius/SWE-agent-trajectories` (Hugging Face)** — a public dataset of
  ~80K real recorded SWE-agent trajectories attempting to resolve actual GitHub
  issues, each with `instance_id`, `model_name`, `target` (bool: whether the issue was
  actually resolved), and a full step-by-step `trajectory` (alternating `ai`/`user`
  roles — the agent's reasoning + a fenced bash command, then the real command output).
  Fetched via Hugging Face's public `datasets-server` "rows" API (no full-parquet
  download needed) and confirmed the shape against real sample rows before committing
  to it. Filtered to `target: False` (genuinely unresolved — real failures, not
  synthetic ones) and trajectory length ≤ 20 steps (keeps hand-labeling tractable):
  57 candidates spanning 13 distinct GitHub issues, comfortably above the 15-20 target.

- **A real architectural finding, worked out before writing any adapter code, that
  changes how the eval set and harness need to be built:** SWE-agent is ReAct-style —
  reason, then act, one step at a time — with no explicit upfront plan, same as my own
  14 legacy Week 1 traces. My diff algorithm is fundamentally a *plan-vs-actual*
  comparison; with `planned_steps=[]`, the very first executed step always aligns as
  `INSERT` (nothing to match against an empty plan), so `first_divergence_index` is
  **trivially 0** for every no-plan trace with at least one action — not a discovery
  about that specific trace, a structural fact about the algorithm applied to empty
  plans. If I fold these into the headline accuracy number as ordinary cases, they
  inflate it for free: the algorithm literally cannot get them wrong. **Decision:**
  every eval case gets a `source_category` — `self_constructed_failure` (has a real
  plan, genuinely tests divergence detection), `external_no_plan` (SWE-agent cases;
  tests the no-plan edge case and cross-benchmark pipeline extensibility on real messy
  data, reported separately, not blended into headline accuracy), or `clean_control`
  (negative controls, Day 4). This is exactly the kind of thing this week is for
  catching before it quietly makes the eventual numbers look better than they are.

## 2026-06-30

- **Injection is post-processing on a genuine, unperturbed run, not a corrupted
  prompt fed into execution.** Considered corrupting the plan text *before* feeding
  it into the execution prompt (closer to the spec's literal "swap... before
  execution" phrasing) — rejected because that makes the actual execution's behavior
  unpredictable (the model might partially comply with a wrong plan in ways that
  aren't the specific divergence being tested), which defeats the point of having
  *exact* auto-populated ground truth. Instead: run the task completely normally,
  capture a genuine clean plan+execution, and only then corrupt the stored record
  (`inject_wrong_tool` swaps `planned_steps[0].tool`, `inject_skip_step` removes the
  last action+observation `Step` pair, `inject_corrupt_args` replaces the first
  action's `tool_input` values) — the real execution is untouched, so the divergence
  is exactly and only what I put there.

- **Each injector raises `InjectionPreconditionError` (caught, not fatal) when the
  base run isn't shaped right** — e.g. `wrong_tool`/`corrupt_args` need the first
  step to already be a clean match, `skip_step` needs ≥2 planned steps that all
  executed cleanly with none already diverging. Real and expected: of the tasks tried
  in the batch script, several were skipped this way before landing on ones that
  worked (e.g. a task whose plan came back empty, or one where the model didn't plan
  a step it ended up not needing). Precondition failures are a normal control-flow
  path here, not a bug — the CLI (`--inject-failure`) surfaces the same error clearly
  and tells the user to try a different `--task` rather than silently doing nothing.

- **`corrupt_args`'s `ground_truth_divergence_step` is `None`, deliberately** — not
  a placeholder for "not yet labeled." `args_changed` is a soft signal excluded from
  `first_divergence_index` by `classify.py`'s own definition (Week 3), so the correct
  behavior for a `corrupt_args`-injected run genuinely is "report no hard divergence
  despite the corrupted arguments" — these cases test that the algorithm does NOT
  over-fire, which is exactly as important as testing that it correctly detects real
  divergences.

- **Generated 21 injected-failure runs** (7 per type — the batch script's 18 plus 3
  from validating each injector manually before batch-generating), landing above the
  15-20 target. **Verified all 21 programmatically, not just a spot-check of a few**:
  ran every one through `align()`/`classify()` via `diff_run()` and compared
  `first_divergence_index` against the auto-populated `ground_truth_divergence_step`
  — 21/21 exact matches. (Spot-checked 2 by hand first, per the spec's explicit ask,
  before trusting the full programmatic check.) This isn't Week 5's real evaluation —
  these are cases I built to have a known-correct answer by construction, so a
  mismatch here would mean a bug in the injector or the algorithm, not a genuine
  measurement of detection accuracy on hard cases. The actual `eval_harness.py`
  measurement comes Day 5-6, against the full mixed eval set.

## 2026-07-01

- **`SWEAgentTraceParser`, not `agentbench_parser.py`** — file named for what it
  actually parses (`nebius/SWE-agent-trajectories`), per the Day 1 sourcing decision.

- **Staged external raw files carry an explicit `run_id` key, matching
  `LangChainTraceParser`'s convention** — considered deriving `run_id` from the
  filename instead (simpler at first glance, since the staging script already
  generates the filename), but that makes the file's identity depend on where it
  happens to live rather than what's inside it, unlike every other raw file in this
  project. Fixed before ever running the pipeline against it, not after finding a bug.

- **Tool name extraction is "first word of the command"** (`ls -F` → `ls`,
  `find_file "x.py" lexicon` → `find_file`), not a fixed enum — SWE-agent's ACI verbs
  (`open`, `edit`, `search_dir`, `find_file`, `submit`, plain bash) all fall out of
  this naturally, matched against the format's own consistent `DISCUSSION\n<reasoning>
  \n\nCOMMAND\n\`\`\`\n<command>\n\`\`\`` structure (confirmed by reading several real
  trajectory steps before writing the regex, not guessed).

- **Registered a second parser in `run_pipeline.py` with a one-line change to the
  `PARSERS` list — no other pipeline code touched.** This is the actual payoff of
  Week 2's abstract `TraceParser` interface being worth building: a structurally very
  different data source (nested JSON trajectory objects vs. this project's own flat
  JSONL) becomes a new parser class, not a rewrite. Ran cleanly against all 71 raw
  files (53 existing + 18 new external) on the first try — 0 failures.

- **All 18 external cases produced `first_divergence_index == 0`, exactly as the
  Day 1 architectural analysis predicted** — verified programmatically, not just
  assumed the earlier reasoning still held. Confirms `planned_steps=[]` really does
  mean "trivially diverges at 0" in practice, on real messy external data, not just
  in the abstract.

- **Fixed a small but real accuracy issue found while spot-checking a rendered
  external report**: the no-plan message said "a pre-Plan-and-Execute trace," which
  is only true for the legacy Week 1 cases — an external SWE-agent trace isn't
  "pre-" anything of mine, it's a different framework that never plans upfront by
  design. Reworded to cover both cases honestly.

## 2026-07-02

- **Found a real parser bug while doing the actual hand-labeling reading, not before
  it** — exactly the kind of thing "actually read each one" (the spec's explicit
  instruction) is for. `SWEAgentTraceParser`'s command extraction originally took the
  *first* fenced code block in each "ai" turn. Reading `asottile__pyupgrade-147`
  (`c5814d40`) closely surfaced a case where the agent's reasoning quotes the GitHub
  issue's own example command in one fenced block, then states the real new command
  in a second, later block — grabbing the first block produced a bogus "tool name" of
  literally `Let's` (a fragment of English prose). Confirmed the real fix by checking
  which block's content matched the traceback shown in the following observation step
  — the second (last) block, not the first. Switched to taking the *last* fenced block.
  Also found, checking this across all 18 trajectories rather than just the one case
  that surfaced it: a rarer opposite pattern (one weaker-model turn emitting several
  real edit attempts in a row, of which only the first was actually executed —
  confirmed by exactly one observation following, not several). "Last block" is
  correct for the common case and a known-imperfect heuristic for that rarer one;
  documented in the parser's own module docstring rather than fixed further, since
  it affects only 4 of ~180 "ai" turns across the whole external set and the two
  patterns don't have a shared rule that would fix both.

- **Ground truth for external cases is `0` for all 18, and that's a mechanical fact,
  not a per-case judgment call** — worked out carefully in `data/eval/labeling_notes.md`
  because conflating it with "did I judge this case correctly" would be dishonest.
  This project's diff algorithm answers one specific question (does execution match
  *the plan*); with no plan, the answer is trivially "diverges immediately," by the
  algorithm's own definition, for every such case. Explicitly recorded that this is a
  narrower claim than "where did the agent's approach actually go wrong" — a real,
  harder question I still engaged with in `labeling_notes.md` as supplementary,
  unscored analysis (e.g. `TheFriendlyCoder__pyjen-113`'s agent claims success at step
  10, admits the fix didn't work at step 12, needs a second retry, and still ends up
  `target=False` after reaching `submit` — a genuinely interesting real failure mode
  this project's algorithm has no way to see, since it only compares tool-call
  sequences, not reasoning quality).

- **10 clean controls selected from the existing corpus, not freshly generated** —
  verified programmatically (an `assert` in the assembly script, not eyeballed) that
  each really does have `planned_steps == [executed tools]` before including it.
  Picked for variety across tool-count (3 zero-tool, 3 single-tool, 2 two-tool, 2
  three-tool), including the two genuine empty-plan-matches-empty-execution cases
  that motivated the `plan_was_attempted` field fix on 2026-06-23.

- **`data/eval/eval_set.jsonl` assembled: 49 total** (21 self-constructed + 18
  external + 10 clean), above the spec's ~25-30 target for the failure-case portion.
  Deliberate, not scope creep: this is real, already-validated data sitting in the
  corpus, and discarding good real data to hit a smaller round number would trade
  away statistical value for no real reason — "extra real data is never wasted," per
  the Week 1 closing notes, applies here too.

## 2026-07-06

- **Four outcome categories, not just right/wrong**: `exact_match`,
  `within_tolerance` (predicted within 1 step of ground truth), `false_positive`
  (flagged a divergence on a case that shouldn't have one), `miss` (a real
  divergence existed and the algorithm either reported none or reported one more
  than 1 step away). Collapsing these into a single accuracy number would hide the
  difference between "close but not exact" and "confidently wrong," which matters
  for the honest failure-mode discussion Day 6 needs to write.

- **`primary` metric excludes `external_no_plan`, per the Day 1 decision, implemented
  in code now rather than left as a promise** — `PRIMARY_CATEGORIES = {"self_constructed_
  failure", "clean_control"}`. Reported per-category numbers still include
  `external_no_plan` in the printed breakdown (nothing hidden), just not folded into
  the headline `primary` figure it would trivially inflate.

- **A first run against the full 49-case set scored 100% in every category — noted
  here now, addressed honestly in Day 6's write-up rather than treated as "done."**
  Before writing up results, worth being explicit that a perfect score on this
  particular eval set is expected, not a strong claim about general-purpose
  divergence detection: `self_constructed_failure` cases are injected by directly
  manipulating the same `planned_steps`/`actual_tool` sequences `align()` reads, so
  scoring well there is close to "does the already-extensively-tested Week 3
  algorithm still run correctly," not an independent judgment test; `clean_control`
  cases were selected specifically for already being exact matches. Flagging this now
  so Day 6 doesn't just report "100%!" without the context that makes the number
  mean what it actually means — the real, harder evidence about the algorithm's
  actual capabilities and limits is the qualitative findings already on record (the
  repeated-tool tie-breaking bug from Week 3 Day 6, the external cases' supplementary
  analysis in `labeling_notes.md`), not a single blended percentage.

## 2026-07-07

- **Ran the harness against the real 49-case set and wrote up the actual result —
  100% across every category — in `docs/eval_results.md`, with as much space given to
  what the number doesn't show as to the number itself.** The honest version of "the
  eval passed" here isn't "the algorithm is proven correct," it's "this eval set,
  built the way it was built, can't currently produce anything other than a high
  score" — `external_no_plan` is trivially guaranteed by the algorithm's own
  definition, `self_constructed_failure` shares its underlying assumptions with the
  code being tested, `clean_control` was selected for already matching. Said this
  plainly rather than let a clean 100% imply more than it does.

- **Explicitly connected the eval result back to the one real bug this project has
  found** (Week 3 Day 6's repeated-tool tie-breaking issue) to make a genuinely useful
  methodological point: that bug doesn't produce a `miss` under this harness, because
  `first_divergence_index` — the only thing scored — was unaffected by it. A clean eval
  score and a known, documented bug coexist here, and burying that would make the
  100% read as a stronger claim than the data supports. This is the kind of finding
  Week 5's "measure honestly" discipline is specifically for.

## 2026-07-08

- **Final Week 5 re-review: genuinely re-read `eval_set.jsonl` end to end, found
  nothing to correct — recorded as a real (clean) outcome, not skipped because there
  were no algorithm disagreements to chase.** With 0 misses from Day 6, there was no
  "the algorithm disagrees with my label" signal to investigate the way the spec's
  framing assumes — so the check instead was structural and re-readthrough-based:
  duplicate `run_id`s, category/ground-truth consistency, and a second read of all 18
  external `task_description` extracts for corruption or truncation. Re-ran the
  harness afterward to confirm nothing had drifted (identical 49/49). Week 5 is done:
  49-case real eval set, honestly measured, honestly written up, with the actual
  Week 3 limitation connected explicitly to what the metric does and doesn't cover.

## Week 6 Day 1: prioritizing what to fix

The eval harness scored zero misses across all 49 cases in Week 5. That means there
is no accuracy based failure pattern to sort by frequency the way the spec describes,
because nothing actually failed on the metric the harness measures. I am not going to
invent misses that do not exist just to have more material.

There is still a real, honest target. The one confirmed bug this project has found is
the repeated tool tie breaking issue from Week 3 Day 6. It does not show up as a miss
because it affects which occurrence of a repeated tool gets paired with the plan, not
whether a divergence is detected or where it starts. That is exactly why it survived
the eval harness undetected. It is still a real correctness bug in the fine grained
alignment output, and it will matter more once Week 7 grows the eval set, since Week 7
explicitly wants cases where the same tool gets called several times in a row.
Fixing this now is the right call even though it will not move this week's numbers,
because the current metric cannot see the problem at all.

Prioritized list for the week: one item, the repeated tool tie breaking bug in
`align.py`.

## Week 6 Day 2: hypothesis

The bug happens when the same tool name appears more than once in both the plan and
the actual execution. The dynamic programming alignment finds the correct minimum
cost, but when two different paths reach that same minimum cost, the backtrack always
prefers the diagonal match first, with no check on whether that specific pairing
actually makes sense. In the confirmed case, the plan's stated reason names a value
that only shows up in the first occurrence of the repeated tool, but the algorithm
paired the plan with the second occurrence instead and flagged the first one as
unexpected.

The fix is to give the backtrack a tie breaker. When a diagonal match and an insert
or delete both reach the same cost, and the tool names already match, check whether
the plan's reason text shares any words with the executed tool's arguments. If it
does not, skip this pairing in favor of the alternative, so a different occurrence
gets a chance to match instead. This reuses the same word overlap check `classify.py`
already computes for `args_changed`, so it is not new machinery, just applied one
step earlier, during alignment instead of after it.

## Week 6 Day 3: implementing the fix

Pulled the word overlap tokenizer out of `classify.py` into a shared
`text_utils.py` so `align.py` could reuse it without a circular import.
`align()` now takes two optional arguments, `planned_context` and
`actual_context`. When neither is given it behaves exactly as before, always
preferring the diagonal on a tie. When both are given, the backtrack checks
for a tie between the diagonal and an insert or delete, and if the tool
names already match but the context does not share a word, it takes the
tied alternative instead and leaves this pairing open for a different
occurrence to claim.

`run_diff.py` now passes the plan's reason text and the executed call's
stringified arguments as that context, so the fix is live in the real
pipeline, not just available in theory.

Tested against the actual case that found the bug, run `036aca4a` from
Week 3 Day 6. Before the fix, the plan paired with the second calculator
call and the first one got flagged as unexpected. After the fix, the plan
correctly pairs with the first call, the one its own reason text names, and
the second call is what gets flagged. Added four new tests locking this in:
one confirming the old no context behavior is unchanged, one reproducing
the real bug as a hand built case, one confirming the fix backs off when
context does not clearly rule out the diagonal, and one confirming
`run_diff.py` actually wires the context through end to end. All 34 tests
pass, no regressions.

Regenerated diffs and reports for the full 71 trace corpus. Exactly two
files changed, `036aca4a` and `c2750ec6`, the two cases already flagged in
Week 3 Day 6 as showing this problem. `c2750ec6` improved too, and I had
not specifically targeted it. Its plan said it needed to find the
historical significance of a year, and the agent searched twice, once with
a query that shares those exact words and once with a shorter, less
related retry. The fix now pairs the plan with the first search, the one
that actually matches the stated reason, instead of the second. Nothing
else in the corpus moved.

## Week 6 Day 5: no second pattern this week

The spec's Day 5 asks for a second improvement round if there is a second item on
Day 1's prioritized list. Mine only had one item, because that was the only real bug
this project had actually found. Forcing a second fix here would mean picking one of
a few known, already documented soft spots, the crude word overlap heuristic in
`args_changed`, the uniform cost function in `align.py`, the rare multi block command
ambiguity in the SWE agent parser, and treating it as broken when nothing has
actually shown it to be. Every one of those was already looked at and deliberately
left alone with a clear reason on record. Changing one now, with no new evidence,
would be tuning against a number I want to see move rather than a problem I have
actually found, which is the exact thing this project's rules are built to prevent.

Not doing a second round this week is the honest call, not a shortcut.

## Week 6 Day 6: regression check

Deleted `data/normalized`, `data/diffs`, and `reports`, then rebuilt everything from
scratch: ingestion, diffing, rendering, the eval harness, and the full test suite.
34 tests pass, the eval numbers match Day 4's rerun exactly, and the rebuilt output
is byte for byte identical to what was already committed. Nothing broke.

## 2026-08-11

- **Framework: LangChain.** Most widely used agent framework, verbose/callback-based
  logging exposes step-by-step execution, and its thought → action → observation
  structure maps directly onto the planned-vs-actual comparison this project needs.

- **Model: `claude-haiku-4-5`.** This project only needs a tool-calling loop over 2-3
  deterministic tools for ~15 short test runs — Haiku is fast, cheap (~$1/$5 per MTok),
  and more than capable for that; no reason to pay Sonnet/Opus rates for trace generation.

- **LangChain 1.3.x is a different API than the one the spec assumes.** `pip install
  langchain` pulled in LangChain 1.3.14, whose recommended agent-construction path is
  `langchain.agents.create_agent` (LangGraph-based) — the old `AgentExecutor` /
  `initialize_agent` / `verbose=True` API from the LangChain 0.x docs the spec was
  written against no longer exists as the primary path. Confirmed the actual API by
  inspecting the installed package rather than assuming from memory, per the "pin the
  version, don't debug against a moving target" guidance in the spec's closing notes.
  Pinned exact versions in `requirements.txt`.

- **Console visibility via `agent.stream(..., stream_mode="updates")` + `pretty_print()`**
  instead of `verbose=True`/`StdOutCallbackHandler` — those don't apply to the
  LangGraph-based `create_agent`. This is the 1.x-native equivalent for Day 1's "see
  step-by-step output in console" requirement, and it previews the shape Week 1 Day 3-4's
  trace-capture code will consume (stream steps keyed by node name, each carrying
  `messages`).

- **Tools are fully deterministic/canned** (calculator does real arithmetic locally;
  search and read_file return fixed canned strings) — no real external APIs, so every
  run is repeatable while building the schema and ingestion pipeline, per Day 1 spec.
