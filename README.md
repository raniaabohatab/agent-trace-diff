# agent-trace-diff

A tool that watches an AI agent work and tells you where it went off script.

Before an agent starts a task it writes a plan, then does the task, and sometimes it follows that plan and sometimes it doesn't. This captures both sides, lines them up, and shows the step where they stop matching. It's a `git diff`, but for what an agent said it would do versus what it did.

## Setup

```bash
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Then create a `.env` file in the project folder with your Anthropic key in
it, like this:

```
ANTHROPIC_API_KEY=your-key-here
```

That file is gitignored, so it never gets committed.

## How to use it

Everything runs as a Python module, so use `-m` in every command below, not
a plain file path.

**Step 1: give it a task and let the agent run.**

```bash
python -m src.generate_traces --task "What is 23 * 17, and what is the capital of France?"
```

You'll see the agent plan, then work through the task live in your
terminal. When it's done, it prints the run's ID and saves the full trace to
`data/raw/`. Copy that ID, you'll need it in a minute.

**Step 2: process the trace.** Three commands, run in order, each one
turning the trace into the next thing it needs to become:

```bash
python -m src.ingest.run_pipeline      # validates the trace
python -m src.diff.run_diff --all      # compares plan vs. what actually happened
python -m src.visualize.render_all     # turns it into a readable report
```

**Step 3: open the report.**

```bash
open reports/<the_id_from_step_1>.html
```

It's a plain HTML file, opens in any browser, no server needed. You'll see
the plan on the left, what actually happened on the right, color coded:
green means it matched, red marks the first place it didn't.


## What you're looking at in the report

- **Green rows**: the agent did exactly what it planned.
- **Yellow rows**: it called the right tool, but with arguments that don't
  obviously match its own stated reason for that step.
- **Red rows**: it called a different tool than planned.
- **Gray dashed rows**: something with nothing to match on the other side,
  either it skipped a planned step, or it did something it never planned.

Here's an example built with the project's own failure injection tool (the
same one used to build the eval set), on a real eight step run across five
different tools: get the time in two cities, convert some units, search the
web, read a file, do some arithmetic. Step one is forced red, a different
tool than the one actually called. Everything in the middle matched its plan
exactly. The last step is forced gray, planned but never executed:

![Example diff report](docs/example_report.png)

## A couple of other things you can do

**Break a run on purpose**, useful for building test data:

```bash
python -m src.generate_traces --task "..." --inject-failure wrong_tool
```

**Check how accurate the tool is**, against a set of 77 hand
checked cases:

```bash
python -m src.eval.eval_harness
```

**Run the test suite:**

```bash
python -m pytest tests/
```

## How it actually figures out where things diverge

Every run boils down to two lists of tool names: what was planned, and what
really happened. The tool lines these up using the same kind of algorithm
`git diff` uses under the hood, find the cheapest way to turn one list into
the other, and whatever changes had to be made along the way are exactly
the divergences worth flagging.

That's really the whole trick. If you want the deeper detail, the full
writeup of how the algorithm works, the real bugs found while building it,
and the evaluation methodology and its honest limits all live in
`docs/decisions.md` and `docs/eval_results.md`.

## Project layout

```
src/
  generate_traces.py    # runs the agent, captures the trace
  schema.py              # the data model everything else builds on
  ingest/                # turns raw traces into a validated format
  diff/                  # the alignment algorithm and its output
  eval/                  # scores the tool against hand labeled cases
  visualize/             # builds the HTML reports
data/
  raw/, normalized/, diffs/    # a trace at each stage of the pipeline
  eval/                        # the 77 case hand labeled test set
reports/                 # the HTML report for every run
docs/
  decisions.md            # why everything was built the way it was
  eval_results.md         # the full evaluation writeup
```
