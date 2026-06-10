"""Global sequence alignment between planned tool calls and actual tool
calls, via the same dynamic-programming family as Needleman-Wunsch / classic
edit distance.

Cost function is uniform: match=0, substitute=1, insert=1, delete=1. A
smarter cost function (e.g. penalizing substitutions less than insertions
when tool names are semantically similar) is a known possible improvement,
deliberately deferred — see docs/decisions.md, 2026-06-09.
"""
from dataclasses import dataclass
from enum import Enum


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


def align(planned_tools: list[str], actual_tools: list[str]) -> list[AlignedPair]:
    """
    Global alignment via dynamic programming.
    Cost function: match=0, substitute=1, insert=1, delete=1.
    Returns the minimum-cost edit script as a list of AlignedPair, in order.
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

    # Backtrack from (n, m) to (0, 0), then reverse to get chronological order.
    pairs: list[AlignedPair] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0:
            sub_cost = 0 if planned_tools[i - 1] == actual_tools[j - 1] else 1
            if dp[i][j] == dp[i - 1][j - 1] + sub_cost:
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
