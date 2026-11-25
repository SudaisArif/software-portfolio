#!/usr/bin/env python3
"""Exact utilities for determinant-weight Hamiltonian tours.

All arithmetic is integer or Fraction arithmetic.  A cyclic tour is represented by
a tuple of point indices; fixing index 0 first removes rotational duplicates, but
we deliberately retain both orientations because reversing a tour negates its
weight.
"""

from __future__ import annotations

from fractions import Fraction
from itertools import permutations
from typing import Iterable, Sequence, TypeAlias

Scalar: TypeAlias = int | Fraction
Point: TypeAlias = tuple[Scalar, Scalar]


def det(p: Point, q: Point) -> Scalar:
    return p[0] * q[1] - p[1] * q[0]


def tour_weight(points: Sequence[Point], tour: Sequence[int]) -> Scalar:
    return sum(
        (det(points[tour[i]], points[tour[(i + 1) % len(tour)]])
         for i in range(len(tour))),
        start=0,
    )


def brute_force(points: Sequence[Point]) -> tuple[Scalar, tuple[int, ...]]:
    """Return the exact maximum and one maximizing tour.

    Runtime is O((n-1)! n); intended only as a small-instance oracle.
    """
    n = len(points)
    if n == 0:
        return 0, ()
    best_value: Scalar | None = None
    best_tour: tuple[int, ...] | None = None
    for tail in permutations(range(1, n)):
        tour = (0,) + tail
        value = tour_weight(points, tour)
        if best_value is None or value > best_value:
            best_value = value
            best_tour = tour
    assert best_value is not None and best_tour is not None
    return best_value, best_tour


def held_karp(points: Sequence[Point]) -> tuple[Scalar, tuple[int, ...]]:
    """Exact O(n^2 2^n) maximum-tour DP, with vertex 0 fixed as start."""
    n = len(points)
    if n == 0:
        return 0, ()
    if n == 1:
        return 0, (0,)

    # State (mask, j): best path 0 -> ... -> j using exactly mask, where mask
    # indexes vertices 1..n-1.  Values also store the predecessor for recovery.
    dp: dict[tuple[int, int], Scalar] = {}
    parent: dict[tuple[int, int], int] = {}
    for j in range(1, n):
        mask = 1 << (j - 1)
        dp[(mask, j)] = det(points[0], points[j])
        parent[(mask, j)] = 0

    full = (1 << (n - 1)) - 1
    for size in range(2, n):
        for mask in range(1, full + 1):
            if mask.bit_count() != size:
                continue
            for j in range(1, n):
                bit = 1 << (j - 1)
                if not mask & bit:
                    continue
                prev_mask = mask ^ bit
                candidates = (
                    (dp[(prev_mask, k)] + det(points[k], points[j]), k)
                    for k in range(1, n)
                    if prev_mask & (1 << (k - 1))
                )
                value, pred = max(candidates, key=lambda pair: pair[0])
                dp[(mask, j)] = value
                parent[(mask, j)] = pred

    best_value, last = max(
        ((dp[(full, j)] + det(points[j], points[0]), j)
         for j in range(1, n)),
        key=lambda pair: pair[0],
    )
    reverse_tail: list[int] = []
    mask = full
    j = last
    while j != 0:
        reverse_tail.append(j)
        pred = parent[(mask, j)]
        mask ^= 1 << (j - 1)
        j = pred
    tour = (0,) + tuple(reversed(reverse_tail))
    assert tour_weight(points, tour) == best_value
    return best_value, tour


def all_tour_values(points: Sequence[Point]) -> Iterable[tuple[Scalar, tuple[int, ...]]]:
    if not points:
        yield 0, ()
        return
    for tail in permutations(range(1, len(points))):
        tour = (0,) + tail
        yield tour_weight(points, tour), tour


if __name__ == "__main__":
    sample = [(0, 0), (2, 0), (2, 1), (0, 1), (1, 3)]
    brute = brute_force(sample)
    dynamic = held_karp(sample)
    assert brute[0] == dynamic[0]
    print({"points": sample, "optimum": brute[0], "tour": brute[1]})
