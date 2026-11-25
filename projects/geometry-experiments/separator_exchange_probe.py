#!/usr/bin/env python3
"""Combinatorial search for small exchange certificates of separator failures."""

from __future__ import annotations

import argparse
import itertools
import math
import random


def local_ccw(order: tuple[int, ...]) -> bool:
    n = len(order)
    steps = tuple((order[(i + 1) % n] - order[i]) % n for i in range(n))
    return all(steps[i - 1] + steps[i] < n for i in range(n))


def block_separator(order: tuple[int, ...]) -> int | None:
    n = len(order)
    successor = [0] * n
    for i, vertex in enumerate(order):
        successor[vertex] = order[(i + 1) % n]
    for cut in range(n):
        rotated = tuple((successor[(i + cut) % n] - cut) % n for i in range(n))
        peaks = {i for i, target in enumerate(rotated) if target < i}
        valleys = {rotated[i] for i in peaks}
        k = len(peaks)
        if valleys == set(range(k)) and peaks == set(range(n - k, n)):
            return cut
    return None


def weight(a: int, b: int, angles: tuple[float, ...]) -> float:
    return math.sin(angles[b] - angles[a])


def best_three_shift(order: tuple[int, ...], angles: tuple[float, ...]) -> tuple[float, tuple[int, ...]]:
    n = len(order)
    edges = tuple((order[i], order[(i + 1) % n]) for i in range(n))
    best = -math.inf
    witness: tuple[int, ...] = ()
    for positions in itertools.combinations(range(n), 3):
        selected = tuple(edges[i] for i in positions)
        gain = sum(weight(selected[i][0], selected[(i + 1) % 3][1], angles)
                   - weight(selected[i][0], selected[i][1], angles)
                   for i in range(3))
        if gain > best:
            best, witness = gain, positions
    return best, witness


def angle_samples(n: int, count: int, seed: int) -> list[tuple[float, ...]]:
    rng = random.Random(seed)
    result = [tuple(2 * math.pi * i / n for i in range(n))]
    for _ in range(count - 1):
        gaps = [rng.expovariate(1) for _ in range(n)]
        scale = 2 * math.pi / sum(gaps)
        angles = [0.0]
        for gap in gaps[:-1]:
            angles.append(angles[-1] + scale * gap)
        result.append(tuple(angles))
    return result


def search(n: int, samples: int, seed: int) -> None:
    checked = 0
    geometries = angle_samples(n, samples, seed)
    for tail in itertools.permutations(range(1, n)):
        order = (0,) + tail
        if not local_ccw(order) or block_separator(order) is not None:
            continue
        checked += 1
        for sample, angles in enumerate(geometries):
            gain, positions = best_three_shift(order, angles)
            if gain <= 1e-11:
                print({"status": "NO_3_SHIFT", "n": n, "order": order,
                       "sample": sample, "angles": angles, "best_gain": gain,
                       "positions": positions})
                return
    print({"status": "PASS", "n": n, "violating_local_tours": checked,
           "angle_samples": samples, "seed": seed})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=8)
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--seed", type=int, default=839201)
    args = parser.parse_args()
    search(args.n, args.samples, args.seed)
