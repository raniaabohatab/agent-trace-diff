"""Run a simple tool-using LangChain agent and print its steps to console.

Day 1 draft: no trace capture yet (that's Week 1 Day 3-4). This just proves
the agent runs end-to-end with deterministic, canned tools so runs are
repeatable while building the ingestion pipeline.
"""
import argparse
import os

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.tools import tool
from langchain_anthropic import ChatAnthropic

load_dotenv()

MODEL_NAME = "claude-haiku-4-5"


@tool
def calculator(expression: str) -> str:
    """Evaluate a basic arithmetic expression, e.g. '12 * 4 + 1'."""
    try:
        # Restricted eval: digits, operators, parens, whitespace only.
        allowed = set("0123456789+-*/(). ")
        if not set(expression) <= allowed:
            return f"Error: expression contains disallowed characters: {expression}"
        return str(eval(expression, {"__builtins__": {}}, {}))
    except Exception as e:
        return f"Error evaluating expression: {e}"


@tool
def search(query: str) -> str:
    """Search the web for information about a topic. Returns canned results for testing."""
    canned = {
        "weather": "Canned result: it is sunny and 72F today.",
        "capital of france": "Canned result: the capital of France is Paris.",
    }
    for key, value in canned.items():
        if key in query.lower():
            return value
    return f"Canned result: no specific data found for '{query}'. Try a more common query."


@tool
def read_file(filename: str) -> str:
    """Read the contents of a named file. Returns canned contents for testing."""
    canned_files = {
        "notes.txt": "Meeting notes: discuss Q3 roadmap, budget review, hiring plan.",
        "config.json": '{"env": "test", "debug": true}',
    }
    if filename in canned_files:
        return canned_files[filename]
    return f"Error: file '{filename}' not found. Available files: {list(canned_files.keys())}"


TOOLS = [calculator, search, read_file]


def build_agent():
    model = ChatAnthropic(model=MODEL_NAME)
    return create_agent(model, tools=TOOLS)


def run_task(task: str) -> None:
    agent = build_agent()
    print(f"=== Running task: {task} ===\n")
    for step in agent.stream(
        {"messages": [{"role": "user", "content": task}]},
        stream_mode="updates",
    ):
        for node_name, node_output in step.items():
            print(f"--- step: {node_name} ---")
            for message in node_output.get("messages", []):
                message.pretty_print()
            print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run a single agent task and print its steps.")
    parser.add_argument("--task", required=True, help="The task/prompt to give the agent.")
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY not set (check .env)")

    run_task(args.task)
