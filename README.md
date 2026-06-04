# agent-trace-diff

Captures an AI agent's full execution trace, diffs the planned sequence of actions
against what was actually executed, and flags the exact step where they diverge.

**Status:** Trace generation and the ingestion pipeline are working end-to-end. The
diff algorithm (comparing planned vs. actual tool-call sequences) and the evaluation
harness (precision/recall against a hand-labeled divergence set) are not built yet.

## Setup

```bash
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file with `ANTHROPIC_API_KEY=<your key>` (never committed — see `.gitignore`).

## Usage

**1. Generate a trace** — runs a 3-tool (calculator, search, read_file) LangChain
agent on `claude-haiku-4-5`, prints each step to the console, and writes the full
captured trace to `data/raw/{run_id}.jsonl`:

```bash
python -m src.generate_traces --task "What is 23 * 17, and what is the capital of France?"
```

Tools return deterministic, canned data — no real external APIs — so runs are
repeatable. `data/raw/` currently has 14 traces generated from 10 varied task prompts
(clean single/multi-tool successes plus a few deliberately-not-clean cases: an
unmatched search query, a file the read_file tool doesn't have, a divide-by-zero).

**2. Normalize the corpus** — validates every file in `data/raw/` against the trace
schema and writes the result to `data/normalized/{run_id}.jsonl`. A file that fails to
parse is logged to `data/normalized/_unparsed.log` with a reason instead of stopping
the batch:

```bash
python -m src.ingest.run_pipeline
```

Run as a module (`-m`) in both cases, not as a direct script path — both files import
`src.schema`/`src.ingest.*`, which need the repo root on `sys.path`; `-m` gives you
that, a direct script invocation doesn't.

## Tests

```bash
python -m pytest tests/
```

9 tests: 3 on the trace schema (valid parse, missing-required-field validation error,
JSON round-trip), 6 on ingestion (parser success/failure/forward-compatibility paths,
`can_parse` rejecting malformed input, and the pipeline producing the exact expected
normalized count against a fixture directory).

## Project layout

```
src/
  schema.py            # Step / AgentRun pydantic models
  generate_traces.py   # runs the agent, captures the trace, writes data/raw/
  ingest/
    base.py             # abstract TraceParser interface
    langchain_parser.py # concrete parser for the format generate_traces.py writes
    run_pipeline.py     # data/raw/ -> data/normalized/, with per-file failure handling
  diff/                 # not built yet (Week 3)
data/
  raw/                  # untouched agent traces, one file per run
  normalized/            # schema-validated output of the ingestion pipeline
docs/
  decisions.md           # dated log of non-obvious choices, with reasoning
```

See `docs/decisions.md` for the reasoning behind specific choices (schema design,
LangChain API surface, parser error handling, test design).
