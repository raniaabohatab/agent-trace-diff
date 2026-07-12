"""Shared lexical overlap heuristic. Used by classify.py for the
args_changed signal and by align.py's tie breaking (Week 6 Day 3). It is a
plain word overlap check, not semantic understanding, and both callers
treat it as a soft, known crude signal on purpose.
"""
import re

STOPWORDS = {
    "the", "a", "an", "to", "of", "for", "and", "in", "on", "at", "is", "this",
    "that", "it", "need", "needs", "with", "from", "into", "its", "will", "be",
    "determine", "find", "get", "use", "using", "then", "want", "would", "should",
}


def tokenize(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2 and w not in STOPWORDS}


def shares_a_word(text_a: str, text_b: str) -> bool:
    """True if the two texts share at least one meaningful word. Also true
    when either side has no meaningful tokens at all, since there is
    nothing to disagree with in that case."""
    tokens_a = tokenize(text_a)
    tokens_b = tokenize(text_b)
    if not tokens_a or not tokens_b:
        return True
    return not tokens_a.isdisjoint(tokens_b)
