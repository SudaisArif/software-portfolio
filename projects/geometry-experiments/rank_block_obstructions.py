#!/usr/bin/env python3
"""Exact obstructions to simple all-winding cocircular decompositions.

The points use the rational unit-circle parametrization q(t).  The checks
show (i) that optimizing the increasing path cover and the descending
connector matching independently can create subtours, and (ii) that an
optimal tour need not induce either a monotone connector matching or a
cyclic-shift path-endpoint permutation at any rank-block cut.
"""

from __future__ import annotations

from fractions import Fraction as F
from itertools import permutations


Point = tuple[F, F]


def point(t: F) -> Point:
    denominator = 1 + t * t
    return ((1 - t * t) / denominator, 2 * t / denominator)


def det(a: Point, b: Point) -> F:
    return a[0] * b[1] - a[1] * b[0]


def weight(points: tuple[Point, ...], order: tuple[int, ...]) -> F:
    return sum(
        det(points[order[i]], points[order[(i + 1) % len(order)]])
        for i in range(len(order))
    )


def all_rooted_tours(n: int):
    for tail in permutations(range(1, n)):
        yield (0,) + tail


def successor(order: tuple[int, ...]) -> tuple[int, ...]:
    result = [0] * len(order)
    for i, vertex in enumerate(order):
        result[vertex] = order[(i + 1) % len(order)]
    return tuple(result)


def cycles(successor_map: tuple[int, ...]) -> tuple[tuple[int, ...], ...]:
    seen: set[int] = set()
    result: list[tuple[int, ...]] = []
    for start in range(len(successor_map)):
        if start in seen:
            continue
        cycle: list[int] = []
        vertex = start
        while vertex not in seen:
            seen.add(vertex)
            cycle.append(vertex)
            vertex = successor_map[vertex]
        result.append(tuple(cycle))
    return tuple(result)


def held_karp_top_two(points: tuple[Point, ...]):
    """Return the two best rooted tours, using exact arithmetic."""
    n = len(points)
    arc = tuple(tuple(det(points[i], points[j]) for j in range(n)) for i in range(n))
    states: dict[tuple[int, int], list[tuple[F, tuple[int, ...]]]] = {
        (1, 0): [(F(0), (0,))]
    }
    for mask in range(1, 1 << n, 2):
        for last in range(n):
            for value, order in states.get((mask, last), ()):
                for following in range(1, n):
                    if mask & (1 << following):
                        continue
                    key = (mask | (1 << following), following)
                    candidates = states.setdefault(key, [])
                    candidates.append((value + arc[last][following], order + (following,)))
                    candidates.sort(key=lambda item: item[0], reverse=True)
                    del candidates[2:]
    full = (1 << n) - 1
    answers = [
        (value + arc[last][0], order)
        for last in range(1, n)
        for value, order in states[(full, last)]
    ]
    answers.sort(key=lambda item: item[0], reverse=True)
    return answers[:2]


def best_increasing_cover(points: tuple[Point, ...], k: int):
    """Best matching 0..n-k-1 -> k..n-1 using only increasing arcs."""
    n = len(points)
    sources = tuple(range(n - k))
    targets = tuple(range(k, n))
    states: dict[int, tuple[F, tuple[int, ...]]] = {0: (F(0), ())}
    for source in sources:
        following_states: dict[int, tuple[F, tuple[int, ...]]] = {}
        for mask, (value, matching) in states.items():
            for rank, target in enumerate(targets):
                if mask & (1 << rank) or source >= target:
                    continue
                key = mask | (1 << rank)
                candidate = (value + det(points[source], points[target]), matching + (target,))
                if key not in following_states or candidate[0] > following_states[key][0]:
                    following_states[key] = candidate
        states = following_states
    return states[(1 << (n - k)) - 1]


def best_connectors(points: tuple[Point, ...], k: int):
    n = len(points)
    peaks = range(n - k, n)
    return max(
        (
            sum(det(points[peak], points[target]) for peak, target in zip(peaks, matching)),
            matching,
        )
        for matching in permutations(range(k))
    )


def rotate_successor(successor_map: tuple[int, ...], cut: int) -> tuple[int, ...]:
    n = len(successor_map)
    return tuple((successor_map[(i + cut) % n] - cut) % n for i in range(n))


def rank_block_data(successor_map: tuple[int, ...]):
    """List (cut,k,descent map,path endpoint map) for all rank-block cuts."""
    n = len(successor_map)
    answer = []
    for cut in range(n):
        rotated = rotate_successor(successor_map, cut)
        peaks = tuple(i for i, target in enumerate(rotated) if i > target)
        valleys = tuple(rotated[i] for i in peaks)
        k = len(peaks)
        if sorted(valleys) != list(range(k)):
            continue
        if sorted(peaks) != list(range(n - k, n)):
            continue
        descent_map = tuple(rotated[n - k + i] for i in range(k))
        endpoint_map = []
        for valley in range(k):
            vertex = valley
            while vertex < n - k:
                vertex = rotated[vertex]
            endpoint_map.append(vertex - (n - k))
        answer.append((cut, k, descent_map, tuple(endpoint_map)))
    return tuple(answer)


def check_independent_optimization_failure() -> None:
    parameters = tuple(F(x) for x in (-5, -4, -3, -2, -1, 0, 1, 2))
    points = tuple(point(t) for t in parameters)
    optimum, runner_up = held_karp_top_two(points)
    assert optimum == (F(5494, 1105), (0, 3, 5, 7, 1, 2, 4, 6))
    assert runner_up[0] == F(5438, 1105)

    inside_value, inside = best_increasing_cover(points, 2)
    connector_value, connectors = best_connectors(points, 2)
    assert (inside_value, inside) == (F(3392, 1105), (2, 3, 4, 5, 6, 7))
    assert (connector_value, connectors) == (F(2112, 1105), (0, 1))
    combined = inside + connectors
    assert cycles(combined) == ((0, 2, 4, 6), (1, 3, 5, 7))
    assert inside_value + connector_value == F(5504, 1105)
    assert inside_value + connector_value - optimum[0] == F(2, 221)


def check_monotone_shift_failure() -> None:
    parameters = tuple(F(x) for x in (-8, -7, -6, -5, -4, -3, -2, -1, 3, 4, 5, 6))
    points = tuple(point(t) for t in parameters)
    optimum, runner_up = held_karp_top_two(points)
    assert optimum == (
        F(332052, 204425),
        (0, 4, 10, 2, 5, 7, 8, 11, 1, 3, 6, 9),
    )
    assert runner_up[0] == F(61408166, 37818625)

    data = rank_block_data(successor(optimum[1]))
    assert data == (
        (0, 3, (0, 2, 1), (1, 0, 2)),
        (3, 3, (1, 0, 2), (0, 2, 1)),
    )
    identity = (0, 1, 2)
    reversal = (2, 1, 0)
    shifts = {(0, 1, 2), (1, 2, 0), (2, 0, 1)}
    assert all(descents not in (identity, reversal) for _, _, descents, _ in data)
    assert all(endpoints not in shifts for _, _, _, endpoints in data)

    for cut, k, _, _ in data:
        rotated_points = points[cut:] + points[:cut]
        inside_value, inside = best_increasing_cover(rotated_points, k)
        connector_value, connectors = best_connectors(rotated_points, k)
        assert inside == (3, 4, 5, 6, 10, 7, 9, 8, 11) if cut == 0 else (
            inside == (3, 7, 4, 6, 5, 8, 9, 10, 11)
        )
        assert connectors == identity
        combined = inside + connectors
        assert len(cycles(combined)) == 3
        assert inside_value + connector_value == F(159957498, 98328425)


def main() -> None:
    check_independent_optimization_failure()
    check_monotone_shift_failure()
    print("PASS: independent rank-block assignments can create subtours")
    print("PASS: monotone-connector/cyclic-shift endpoint conjecture fails exactly")


if __name__ == "__main__":
    main()
