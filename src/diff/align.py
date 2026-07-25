"""Global sequence alignment between planned tool calls and actual tool
calls, via the same dynamic-programming family as Needleman-Wunsch / classic
edit distance.

Cost function is uniform: match=0, substitute=1, insert=1, delete=1. A
smarter cost function (e.g. penalizing substitutions less than insertions
when tool names are semantically similar) is a known possible improvement,
deliberately deferred. See docs/decisions.md, 2026-06-09.

The minimum cost itself is never in question. What can be ambiguous is
which occurrence of a repeated tool the backtrack pairs up when more than
one path reaches that same minimum cost. optional planned_context and
actual_context args break that kind of tie using the same word overlap
heuristic classify.py uses for args_changed. See docs/decisions.md, Week 6
Day 3, for the real case this fixes.
"""
from dataclasses import dataclass
from enum import Enum

from src.diff.text_utils import shares_a_word


class AlignOp(str, Enum):
    MATCH = "match"  # same tool at this position
    SUBSTITUTE = "substitute"  # different tool where one was expected
    INSERT = "insert"  # actual step with no corresponding planned step
    DELETE = "delete"  # planned step never executed


@dataclass
class AlignedPair:
    planned_index: int | None
    actual_index: int | None
    op: AlignOp


def align(
    planned_tools: list[str],
    actual_tools: list[str],
    planned_context: list[str] | None = None,
    actual_context: list[str] | None = None,
) -> list[AlignedPair]:
    """
    Global alignment via dynamic programming.
    Cost function: match=0, substitute=1, insert=1, delete=1.
    Returns the minimum-cost edit script as a list of AlignedPair, in order.

    planned_context and actual_context are optional, same length as the
    matching tool list (a plan's stated reason, an executed call's stringified
    arguments). They never change the minimum cost. They only break ties when
    a diagonal match and an insert or delete reach that same cost, which only
    comes up when a tool name repeats. Omit them and the function behaves
    exactly as before, always preferring the diagonal on a tie.
    """
    n, m = len(planned_tools), len(actual_tools)

    # dp[i][j] = min cost to align planned[0:i] with actual[0:j]
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = i  # i deletes: none of the first i planned steps were executed
    for j in range(1, m + 1):
        dp[0][j] = j  # j inserts: all of the first j actual steps are unplanned

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            sub_cost = 0 if planned_tools[i - 1] == actual_tools[j - 1] else 1
            dp[i][j] = min(
                dp[i - 1][j - 1] + sub_cost,  # match or substitute
                dp[i - 1][j] + 1,  # delete planned[i-1]
                dp[i][j - 1] + 1,  # insert actual[j-1]
            )

    def context_supports_match(i: int, j: int) -> bool:
        """True if planned_context[i-1] and actual_context[j-1] share a word,
        or no context was given at all (the old, unconditional behavior)."""
        if planned_context is None or actual_context is None:
            return True
        return shares_a_word(planned_context[i - 1], actual_context[j - 1])

    # Backtrack from (n, m) to (0, 0), then reverse to get chronological order.
    pairs: list[AlignedPair] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0:
            sub_cost = 0 if planned_tools[i - 1] == actual_tools[j - 1] else 1
            diagonal_reaches_min = dp[i][j] == dp[i - 1][j - 1] + sub_cost
            if diagonal_reaches_min:
                delete_ties = i > 0 and dp[i][j] == dp[i - 1][j] + 1
                insert_ties = j > 0 and dp[i][j] == dp[i][j - 1] + 1
                # Only a same-tool match can be ambiguous this way (a
                # substitute is never tied with skipping both sides at once).
                # If there's a tied alternative and this specific pairing
                # doesn't hold up on context, take the alternative instead
                # and leave this match for a different occurrence to claim.
                if sub_cost == 0 and (delete_ties or insert_ties) and not context_supports_match(i, j):
                    if insert_ties:
                        pairs.append(AlignedPair(planned_index=None, actual_index=j - 1, op=AlignOp.INSERT))
                        j -= 1
                        continue
                    pairs.append(AlignedPair(planned_index=i - 1, actual_index=None, op=AlignOp.DELETE))
                    i -= 1
                    continue
                op = AlignOp.MATCH if sub_cost == 0 else AlignOp.SUBSTITUTE
                pairs.append(AlignedPair(planned_index=i - 1, actual_index=j - 1, op=op))
                i, j = i - 1, j - 1
                continue
        if i > 0 and dp[i][j] == dp[i - 1][j] + 1:
            pairs.append(AlignedPair(planned_index=i - 1, actual_index=None, op=AlignOp.DELETE))
            i -= 1
            continue
        # j > 0 must hold here (i == 0 or the delete branch above didn't match)
        pairs.append(AlignedPair(planned_index=None, actual_index=j - 1, op=AlignOp.INSERT))
        j -= 1

    pairs.reverse()
    return pairs
