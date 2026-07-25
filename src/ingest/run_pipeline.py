"""Scan data/raw/, run each file through whichever registered parser claims
it, and write the normalized AgentRun to data/normalized/{run_id}.jsonl.

One bad file should never take down the whole batch. Anything that doesn't
parse gets logged to data/normalized/_unparsed.log with a reason instead of
raising. Two parsers now (LangChain-generated traces, and external
SWE-agent-derived traces). This is exactly the payoff Week 2's abstract
TraceParser interface was built for: a second format is a new parser class,
not a rewrite of this loop. See docs/decisions.md, 2026-07-01.
"""
from pathlib import Path

from src.ingest.base import TraceParser
from src.ingest.langchain_parser import LangChainTraceParser
from src.ingest.swe_agent_parser import SWEAgentTraceParser

RAW_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "raw"
NORMALIZED_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "normalized"

PARSERS: list[TraceParser] = [LangChainTraceParser(), SWEAgentTraceParser()]


def run_pipeline(raw_dir: Path = RAW_DATA_DIR, normalized_dir: Path = NORMALIZED_DATA_DIR) -> dict[str, int]:
    normalized_dir.mkdir(parents=True, exist_ok=True)
    unparsed_log_path = normalized_dir / "_unparsed.log"

    raw_files = sorted(p for p in raw_dir.iterdir() if p.is_file() and not p.name.startswith("."))

    succeeded = 0
    failed = 0
    unparsed_lines: list[str] = []

    for raw_path in raw_files:
        raw_path_str = str(raw_path)
        matched_parser = None
        for parser in PARSERS:
            if parser.can_parse(raw_path_str):
                matched_parser = parser
                break

        if matched_parser is None:
            reason = "no registered parser matched this file"
            unparsed_lines.append(f"{raw_path.name}: {reason}")
            print(f"[skip] {raw_path.name}: {reason}")
            failed += 1
            continue

        try:
            run = matched_parser.parse(raw_path_str)
        except ValueError as e:
            unparsed_lines.append(f"{raw_path.name}: {e}")
            print(f"[fail] {raw_path.name}: {e}")
            failed += 1
            continue

        out_path = normalized_dir / f"{run.run_id}.jsonl"
        with open(out_path, "w") as f:
            f.write(run.model_dump_json())
            f.write("\n")
        succeeded += 1

    if unparsed_lines:
        with open(unparsed_log_path, "w") as f:
            f.write("\n".join(unparsed_lines) + "\n")
    elif unparsed_log_path.exists():
        unparsed_log_path.unlink()

    total = len(raw_files)
    print(f"\n{total} files processed, {succeeded} succeeded, {failed} failed")
    if failed:
        print(f"See {unparsed_log_path} for reasons")

    return {"total": total, "succeeded": succeeded, "failed": failed}


if __name__ == "__main__":
    run_pipeline()
