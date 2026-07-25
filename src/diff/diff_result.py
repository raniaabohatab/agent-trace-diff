"""Output schema for one run's diff: aligned pairs, classified divergence
events, and the single most important number Week 5's evaluation measures
against ground truth, first_divergence_index.
"""
from dataclasses import asdict

from pydantic import BaseModel

from src.diff.align import AlignedPair
from src.diff.classify import DivergenceEvent


class DiffResult(BaseModel):
    run_id: str
    aligned_pairs: list[dict]  # serialized AlignedPair list
    divergence_events: list[DivergenceEvent]
    first_divergence_index: int | None
    plan_followed_exactly: bool  # True if divergence_events (hard ones) is empty


def serialize_aligned_pairs(pairs: list[AlignedPair]) -> list[dict]:
    """AlignOp is a (str, Enum) subclass, so it serializes to its plain string
    value automatically when the resulting dict later goes through pydantic's
    model_dump_json(), no manual enum handling needed here."""
    return [asdict(p) for p in pairs]
