"""Abstract parser interface for turning raw, framework-specific trace files
into validated AgentRun objects.

An abstract base class instead of a single function: Week 3+ and any future
framework support (raw OpenAI function-calling logs, etc.) need a stable
contract, and this lets the pipeline gain a new parser without touching
existing code (open/closed principle).
"""
from abc import ABC, abstractmethod

from src.schema import AgentRun


class TraceParser(ABC):
    @abstractmethod
    def can_parse(self, raw_path: str) -> bool:
        """Return True if this parser can handle the file at raw_path."""
        ...

    @abstractmethod
    def parse(self, raw_path: str) -> AgentRun:
        """Parse the raw file into a validated AgentRun. Raise ValueError on malformed input."""
        ...
