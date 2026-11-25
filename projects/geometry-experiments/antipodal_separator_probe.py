#!/usr/bin/env python3
"""Search exact cocircular optima for an antipodal descent separator."""

from __future__ import annotations

import argparse
import math
from fractions import Fraction as F
from random import Random

from area_tour import held_karp


def point(t: F) -> tuple[F, F]:
    d = 1 + t * t
    return ((1 - t * t) / d, 2 * t / d)


def antipodal_separator(points: tuple[tuple[F, F], ...], order: tuple[int, ...]) -> float | None:
    """Return a cut c for which no tour edge crosses both c and c+pi."""
    angles = tuple(math.atan2(float(y), float(x)) % (2 * math.pi) for x, y in points)
    events = sorted({a for a in angles} | {(a + math.pi) % (2 * math.pi) for a in angles})
    candidates = []
    for i, left in enumerate(events):
        right = events[(i + 1) % len(events)]
        if i + 1 == len(events):
            right += 2 * math.pi
        candidates.append(((left + right) / 2) % (2 * math.pi))
    for cut in candidates:
        shifted = tuple((a - cut) % (2 * math.pi) for a in angles)
        good = True
        for i, source in enumerate(order):
            target = order[(i + 1) % len(order)]
            if shifted[source] > shifted[target]:
                if not (shifted[target] < math.pi < shifted[source]):
                    good = False
                    break
        if good:
            return cut
    return None


def parameters_for(random: Random, n: int, mode: str) -> tuple[F, ...]:
    if mode == "linear":
        denominator = random.randint(1, 211)
        numerators = sorted(random.sample(range(-80 * n * n, 80 * n * n + 1), n))
        return tuple(F(value, denominator) for value in numerators)
    if mode == "uniform-angle":
        angles = sorted(random.random() * 2 * math.pi - math.pi for _ in range(n))
        return tuple(F.from_float(math.tan(angle / 2)).limit_denominator(100_000)
                     for angle in angles)
    if mode == "regular-perturb":
        offset = random.random() * 2 * math.pi
        angles = sorted(((offset + 2 * math.pi * i / n
                          + random.uniform(-0.12, 0.12) / n + math.pi)
                         % (2 * math.pi)) - math.pi for i in range(n))
        return tuple(F.from_float(math.tan(angle / 2)).limit_denominator(100_000)
                     for angle in angles)
    raise ValueError(mode)


def search(n_min: int, n_max: int, trials: int, seed: int, mode: str) -> None:
    random = Random(seed)
    checked = 0
    for n in range(n_min, n_max + 1):
        for trial in range(trials):
            parameters = parameters_for(random, n, mode)
            points = tuple(point(t) for t in parameters)
            optimum, order = held_karp(points)
            witness = antipodal_separator(points, order)
            if witness is None:
                print({"status": "COUNTEREXAMPLE", "n": n, "trial": trial,
                       "parameters": parameters, "optimum": optimum, "order": order})
                return
            checked += 1
        print({"n": n, "passed": trials})
    print({"status": "PASS", "instances": checked, "seed": seed, "mode": mode})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-min", type=int, default=5)
    parser.add_argument("--n-max", type=int, default=12)
    parser.add_argument("--trials", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20260904)
    parser.add_argument("--mode", choices=("linear", "uniform-angle", "regular-perturb"),
                        default="linear")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    search(args.n_min, args.n_max, args.trials, args.seed, args.mode)
