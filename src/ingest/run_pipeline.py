"""Scan data/raw/, run each file through whichever registered parser claims
it, and write the normalized AgentRun to data/normalized/{run_id}.jsonl.

One bad file should never take down the whole batch — anything that doesn't
parse gets logged to data/normalized/_unparsed.log with a reason instead of
raising. There's only one parser today, but the loop is written as if there
could be several, since that's the point of the TraceParser abstraction.
"""
from pathlib import Path

from src.ingest.base import TraceParser
from src.ingest.langchain_parser import LangChainTraceParser

RAW_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "raw"
NORMALIZED_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "normalized"

PARSERS: list[TraceParser] = [LangChainTraceParser()]


def run_pipeline() -> None:
    NORMALIZED_DATA_DIR.mkdir(parents=True, exist_ok=True)
    unparsed_log_path = NORMALIZED_DATA_DIR / "_unparsed.log"

    raw_files = sorted(p for p in RAW_DATA_DIR.iterdir() if p.is_file() and not p.name.startswith("."))

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

        out_path = NORMALIZED_DATA_DIR / f"{run.run_id}.jsonl"
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


if __name__ == "__main__":
    run_pipeline()
