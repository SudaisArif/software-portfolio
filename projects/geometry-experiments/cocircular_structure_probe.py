#!/usr/bin/env python3
"""Exact search for structure in optimal determinant tours on one circle.

This is a conjecture-finding program, not part of the proof audit. It tests
whether an optimal successor s admits a shift R_d such that R_{-d} composed
with s acts as one cyclic rotation on each circular-interval block.
"""

from __future__ import annotations

import argparse
from fractions import Fraction
from itertools import permutations
from math import gcd
from random import Random
from typing import Iterable, Sequence

from area_tour import held_karp, tour_weight


Point = tuple[Fraction, Fraction]


def circle_point(parameter: Fraction) -> Point:
    denominator = 1 + parameter * parameter
    return (
        (1 - parameter * parameter) / denominator,
        2 * parameter / denominator,
    )


def successor(order: Sequence[int]) -> tuple[int, ...]:
    result = [0] * len(order)
    for index, vertex in enumerate(order):
        result[vertex] = order[(index + 1) % len(order)]
    return tuple(result)


def permutation_cycles(permutation: Sequence[int]) -> tuple[tuple[int, ...], ...]:
    seen: set[int] = set()
    result: list[tuple[int, ...]] = []
    for start in range(len(permutation)):
        if start in seen:
            continue
        cycle: list[int] = []
        vertex = start
        while vertex not in seen:
            seen.add(vertex)
            cycle.append(vertex)
            vertex = permutation[vertex]
        result.append(tuple(cycle))
    return tuple(result)


def circular_interval_order(vertices: set[int], n: int) -> tuple[int, ...] | None:
    """Return the ambient order of a circular interval, if it is one."""
    if not vertices:
        return None
    if len(vertices) == n:
        return tuple(range(n))
    starts = [vertex for vertex in vertices if (vertex - 1) % n not in vertices]
    if len(starts) != 1:
        return None
    start = starts[0]
    order = tuple((start + offset) % n for offset in range(len(vertices)))
    return order if set(order) == vertices else None


def is_rotation_on_order(
    permutation: Sequence[int], order: Sequence[int]
) -> bool:
    position = {vertex: index for index, vertex in enumerate(order)}
    length = len(order)
    if length == 1:
        return permutation[order[0]] == order[0]
    step = (position[permutation[order[0]]] - position[order[0]]) % length
    if gcd(step, length) != 1:
        return False
    return all(
        permutation[vertex] == order[(position[vertex] + step) % length]
        for vertex in order
    )


def interval_rotation_witness(
    tour_successor: Sequence[int],
) -> tuple[int, tuple[tuple[int, ...], ...]] | None:
    """Find d for which the shifted successor is blockwise rotational."""
    n = len(tour_successor)
    for shift in range(n):
        residual = tuple((image - shift) % n for image in tour_successor)
        blocks: list[tuple[int, ...]] = []
        valid = True
        for cycle in permutation_cycles(residual):
            ambient_order = circular_interval_order(set(cycle), n)
            if ambient_order is None or not is_rotation_on_order(
                residual, ambient_order
            ):
                valid = False
                break
            blocks.append(ambient_order)
        if valid:
            return shift, tuple(blocks)
    return None


def all_optimal_tours(points: Sequence[Point]) -> Iterable[tuple[int, ...]]:
    """Small-instance tie-safe oracle, with vertex zero fixed first."""
    optimum, _ = held_karp(points)
    for tail in permutations(range(1, len(points))):
        order = (0,) + tail
        if tour_weight(points, order) == optimum:
            yield order


def exact_random_search(
    n_min: int, n_max: int, trials: int, seed: int, tie_safe_n: int
) -> None:
    random = Random(seed)
    total = 0
    for n in range(n_min, n_max + 1):
        for trial in range(trials):
            # q(t) is counterclockwise as t increases. Varying the denominator
            # and using a wide range produces clustered and uneven exact inputs.
            denominator = random.randint(1, 97)
            population = range(-12 * n * n, 12 * n * n + 1)
            parameters = tuple(
                Fraction(value, denominator)
                for value in sorted(random.sample(population, n))
            )
            points = tuple(circle_point(parameter) for parameter in parameters)
            optimum, order = held_karp(points)
            candidate_orders = (
                tuple(all_optimal_tours(points)) if n <= tie_safe_n else (order,)
            )
            witnesses = [
                (candidate, interval_rotation_witness(successor(candidate)))
                for candidate in candidate_orders
            ]
            if not any(witness is not None for _, witness in witnesses):
                print(
                    {
                        "status": "COUNTEREXAMPLE",
                        "n": n,
                        "trial": trial,
                        "parameters": parameters,
                        "optimum": optimum,
                        "optimal_orders": candidate_orders,
                        "successors": tuple(successor(x) for x in candidate_orders),
                    }
                )
                return
            total += 1
        print({"n": n, "trials_passed": trials})
    print({"status": "PASS", "instances": total, "seed": seed})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-min", type=int, default=5)
    parser.add_argument("--n-max", type=int, default=10)
    parser.add_argument("--trials", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20260904)
    parser.add_argument(
        "--tie-safe-n",
        type=int,
        default=8,
        help="enumerate all optimal tours through this size",
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    exact_random_search(
        arguments.n_min,
        arguments.n_max,
        arguments.trials,
        arguments.seed,
        arguments.tie_safe_n,
    )
