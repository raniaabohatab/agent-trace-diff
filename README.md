# agent-trace-diff

Captures an AI agent's full execution trace, diffs the planned sequence of actions
against what was actually executed, and flags the exact step where they diverge.

**Status:** Trace generation, the ingestion pipeline, and the diff algorithm are
working end-to-end. Visualization (Week 4) and the evaluation harness (Week 5) are
not built yet.

## Setup

```bash
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file with `ANTHROPIC_API_KEY=<your key>` (never committed — see `.gitignore`).

## Usage

**1. Generate a trace** — the agent first makes one upfront LLM call to produce a
plan (an ordered list of tool calls it intends to make), then executes the task with
a normal 3-tool (calculator, search, read_file) LangChain agent on `claude-haiku-4-5`,
free to deviate from its own plan as it goes. Both the plan and the actual execution
are captured to `data/raw/{run_id}.jsonl`:

```bash
python -m src.generate_traces --task "What is 23 * 17, and what is the capital of France?"
```

Tools return deterministic, canned data — no real external APIs — so runs are
repeatable. `data/raw/` currently has 32 traces: 14 from the original ReAct-style
agent (no upfront plan — `planned_steps` is an empty list for these, a real,
deliberately-handled edge case, not missing data) plus 18 Plan-and-Execute traces,
including several with genuine plan/execution divergence.

**2. Normalize the corpus** — validates every file in `data/raw/` against the trace
schema and writes the result to `data/normalized/{run_id}.jsonl`. A file that fails to
parse is logged to `data/normalized/_unparsed.log` with a reason instead of stopping
the batch:

```bash
python -m src.ingest.run_pipeline
```

**3. Diff plan vs. actual** — aligns each normalized run's planned tool calls against
its actual ones and classifies the differences, writing a `DiffResult` to
`data/diffs/{run_id}.jsonl`:

```bash
python -m src.diff.run_diff --all
```

Run everything as a module (`-m`), not as a direct script path — these files import
`src.schema`/`src.ingest.*`/`src.diff.*`, which need the repo root on `sys.path`;
`-m` gives you that, a direct script invocation doesn't.

## How the diff algorithm works

Each agent run produces two sequences of tool names: the **planned** sequence (from
the upfront plan) and the **actual** sequence (the tools genuinely invoked during
execution). The diff algorithm's job is to line these two sequences up and say
exactly where — and how — they stop matching.

The alignment step (`src/diff/align.py`) treats this as a classic sequence-alignment
problem, the same dynamic-programming family Needleman-Wunsch and Myers diff belong
to: find the cheapest way to transform the planned sequence into the actual sequence
using three edit operations — substitute one tool for another, insert an unplanned
tool call, or delete a planned call that never happened — plus free matches where the
two sequences already agree. The output is an ordered list of aligned pairs, each
tagged `match`, `substitute`, `insert`, or `delete`.

The classification step (`src/diff/classify.py`) turns that alignment into
human-readable divergence events. A `delete` becomes a **skipped step** (the agent
planned to call a tool and never did); an `insert` becomes an **unexpected step** (the
agent called a tool it never planned to); a `substitute` becomes **wrong tool** (it
called something other than what it planned at that point). These three are "hard"
divergences. A softer fourth signal, **args changed**, flags a `match` where the tool
name is right but its arguments don't obviously relate to the plan's stated reason for
that step — this is deliberately excluded from counting as a hard divergence, since it's
a much weaker, lexical-overlap-based signal rather than a structural one. The single
most important output of the whole pipeline is `first_divergence_index`: the position
of the first hard divergence, or `None` if the run followed its plan exactly. Week 5's
evaluation measures how well this number matches hand-labeled ground truth.

A known limitation, found by manually checking real traces rather than assumed: when
the same tool appears more than once on both sides, the alignment can tie between
multiple equally-cheap pairings, and the specific pairing chosen is decided by
backtrack order alone, blind to the actual arguments involved — in one observed case
this visibly paired the plan against the wrong one of two identical-tool calls. It
doesn't affect `first_divergence_index` in any case checked so far, only the
fine-grained pairing detail. See `docs/decisions.md` (2026-06-15) for the specifics.

## Tests

```bash
python -m pytest tests/
```

21 tests: 3 on the trace schema, 6 on ingestion, and 12 on the diff algorithm —
hand-constructed cases (exact match, single insert/delete/substitute, empty-plan and
empty-execution edge cases, repeated-consecutive-tool, multiple divergences in one
run, and the args-changed soft-signal behavior) with manually-verified expected
answers, kept separate from real messy agent data.

## Project layout

```
src/
  schema.py            # Step / PlannedStep / AgentRun pydantic models
  generate_traces.py   # plans + runs the agent, captures the trace, writes data/raw/
  ingest/
    base.py             # abstract TraceParser interface
    langchain_parser.py # concrete parser for the format generate_traces.py writes
    run_pipeline.py     # data/raw/ -> data/normalized/, with per-file failure handling
  diff/
    align.py            # planned-vs-actual sequence alignment (DP / edit distance)
    classify.py          # alignment -> human-readable divergence events
    diff_result.py       # DiffResult output schema
    run_diff.py           # data/normalized/ -> data/diffs/, with per-run failure handling
data/
  raw/                  # untouched agent traces, one file per run
  normalized/            # schema-validated output of the ingestion pipeline
  diffs/                 # DiffResult output of the diff pipeline
docs/
  decisions.md           # dated log of non-obvious choices, with reasoning
```

See `docs/decisions.md` for the reasoning behind specific choices (schema design,
LangChain API surface, parser error handling, alignment cost function, test design,
and the repeated-tool tie-breaking limitation above).
