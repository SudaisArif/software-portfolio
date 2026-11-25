#!/usr/bin/env python3
"""Search for a valley/peak separator in optimal cocircular tours.

This is conjecture-finding code.  It uses exact rational circle points and
the exact Held--Karp oracle from area_tour.py.
"""

from __future__ import annotations

import argparse
from fractions import Fraction as F
from random import Random

from area_tour import held_karp


def point(t: F) -> tuple[F, F]:
    denominator = 1 + t * t
    return ((1 - t * t) / denominator, 2 * t / denominator)


def successor(order: tuple[int, ...]) -> tuple[int, ...]:
    result = [0] * len(order)
    for i, vertex in enumerate(order):
        result[vertex] = order[(i + 1) % len(order)]
    return tuple(result)


def separator(successor_map: tuple[int, ...]) -> tuple[int, int] | None:
    """Return two circular cuts separating valleys from peaks, if any."""
    n = len(successor_map)
    for cut in range(n):
        valleys: list[int] = []
        peaks: list[int] = []
        for old_source, old_target in enumerate(successor_map):
            source = (old_source - cut) % n
            target = (old_target - cut) % n
            if source > target:
                peaks.append(source)
                valleys.append(target)
        assert valleys and len(valleys) == len(peaks)
        if max(valleys) < min(peaks):
            return cut, max(valleys) + 1
    return None


def local_ccw(order: tuple[int, ...]) -> bool:
    n = len(order)
    for i in range(n):
        a, b, c = order[i - 1], order[i], order[(i + 1) % n]
        if (b - a) % n + (c - b) % n >= n:
            return False
    return True


def search(n_min: int, n_max: int, trials: int, seed: int) -> None:
    random = Random(seed)
    checked = 0
    for n in range(n_min, n_max + 1):
        for trial in range(trials):
            denominator = random.randint(1, 211)
            population = range(-50 * n * n, 50 * n * n + 1)
            numerators = sorted(random.sample(population, n))
            parameters = tuple(F(value, denominator) for value in numerators)
            points = tuple(point(t) for t in parameters)
            optimum, order = held_karp(points)
            witness = separator(successor(order))
            assert local_ccw(order)
            if witness is None:
                print({
                    "status": "COUNTEREXAMPLE",
                    "n": n,
                    "trial": trial,
                    "parameters": parameters,
                    "optimum": optimum,
                    "order": order,
                })
                return
            checked += 1
        print({"n": n, "passed": trials})
    print({"status": "PASS", "instances": checked, "seed": seed})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-min", type=int, default=5)
    parser.add_argument("--n-max", type=int, default=12)
    parser.add_argument("--trials", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20260904)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    search(args.n_min, args.n_max, args.trials, args.seed)
