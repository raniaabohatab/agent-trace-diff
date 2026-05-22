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
