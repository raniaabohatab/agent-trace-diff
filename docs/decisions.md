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
