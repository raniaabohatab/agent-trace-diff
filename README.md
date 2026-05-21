# agent-trace-diff

Captures an AI agent's full execution trace, diffs the planned sequence of actions
against what was actually executed, and flags the exact step where they diverge.

**Status:** Week 1 in progress — framework selection and first working agent script done.
Trace schema, ingestion pipeline, diff algorithm, and evaluation harness are not built yet.

## Setup

```bash
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file with `ANTHROPIC_API_KEY=<your key>` (never committed — see `.gitignore`).

## Usage so far

```bash
python -m src.generate_traces --task "What is 23 * 17, and what is the capital of France?"
```

Run as a module (`-m`), not `python src/generate_traces.py` — the script imports
`src.schema`, which needs the repo root on `sys.path`; `-m` gives you that, a direct
script invocation doesn't.

Runs a 3-tool (calculator, search, read_file) LangChain agent on `claude-haiku-4-5`,
prints each step to the console, and writes the full captured trace to
`data/raw/{run_id}.jsonl`. Tools return deterministic, canned data — no real external
APIs — so runs are repeatable while the schema and pipeline are being built.
