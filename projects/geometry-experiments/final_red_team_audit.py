#!/usr/bin/env python3
"""Reproduce the final adversarial audits of the AREA-TOUR proof.

The reduction audit enumerates raw determinant tours and only afterwards asks
whether a tour has the intended color/matching form.  The source audit checks
the normalized Sarvanov construction directly on set partitions.  All
arithmetic is integral.
"""

from __future__ import annotations

import argparse
from itertools import permutations

from area_tour import tour_weight
from product_partition_test import (
    canonical_partitions,
    cycle_permutation,
    has_good_matching,
)
from three_cluster_reduction import (
    construct,
    decode_exact_pattern,
    product_optimum,
)


def cycle_count(permutation):
    seen = set()
    count = 0
    for start in range(len(permutation)):
        if start in seen:
            continue
        count += 1
        vertex = start
        while vertex not in seen:
            seen.add(vertex)
            vertex = permutation[vertex]
    return count


def is_adjacent_transposition_product(permutation):
    for i, j in enumerate(permutation):
        if j == i:
            continue
        if abs(i - j) != 1 or permutation[j] != i:
            return False
    return True


def displacement_audit(n_max):
    checked = 0
    for n in range(1, n_max + 1):
        for tau in permutations(range(n)):
            d2 = sum((i - tau[i]) ** 2 for i in range(n))
            assert d2 % 2 == 0
            d = d2 // 2
            lower = n - cycle_count(tau)
            assert d >= lower
            assert (d == lower) == is_adjacent_transposition_product(tau)
            checked += 1
    result = {
        "audit": "displacement inequality and equality classification",
        "n_max": n_max,
        "permutations": checked,
        "status": "PASS",
    }
    print(result)
    return result


def normalized_source(labels):
    n = len(labels)
    sigma = cycle_permutation(labels)
    u = tuple(range(1, n + 1))
    v = [None] * n
    for i in range(n):
        v[sigma[i]] = n - i
    m = max(labels) + 1
    baseline = n * (n + 1) * (n + 2) // 6
    return u, tuple(v), baseline + m - 1


def source_audit(n_max):
    partitions = 0
    cycle_objectives = 0
    for n in range(1, n_max + 1):
        for labels in canonical_partitions(n):
            source_yes, _ = has_good_matching(labels)
            u, v, threshold = normalized_source(labels)
            optimum, _ = product_optimum(u, v)
            cycle_objectives += 1 if n == 1 else _factorial(n - 1)
            assert (optimum <= threshold) == source_yes, {
                "labels": labels,
                "source_yes": source_yes,
                "u": u,
                "v": v,
                "threshold": threshold,
                "optimum": optimum,
            }
            partitions += 1
    result = {
        "audit": "normalized Sarvanov source",
        "n_max": n_max,
        "partitions": partitions,
        "cycle_objectives": cycle_objectives,
        "status": "PASS",
    }
    print(result)
    return result


def _factorial(n):
    value = 1
    for k in range(2, n + 1):
        value *= k
    return value


def reduction_raw_audit(n_max):
    instances = 0
    tour_evaluations = 0
    margins = {}
    for n in range(1, n_max + 1):
        minimum_margin = None
        for u in permutations(range(1, n + 1)):
            for v in permutations(range(1, n + 1)):
                product_value, _ = product_optimum(u, v)
                points, colors, labels, c0, _ = construct(u, v)
                best = None
                best_nonpattern = None
                best_bad_matching = None
                for tail in permutations(range(1, 3 * n)):
                    tour = (0,) + tail
                    value = tour_weight(points, tour)
                    best = value if best is None else max(best, value)
                    decoded = decode_exact_pattern(tour, colors, labels)
                    if decoded is None:
                        best_nonpattern = (
                            value if best_nonpattern is None
                            else max(best_nonpattern, value)
                        )
                    else:
                        alpha, _, gamma = decoded
                        identity = tuple(range(n))
                        if alpha != identity or gamma != identity:
                            best_bad_matching = (
                                value if best_bad_matching is None
                                else max(best_bad_matching, value)
                            )
                    tour_evaluations += 1

                assert best == c0 - product_value, {
                    "n": n, "u": u, "v": v, "best": best,
                    "prediction": c0 - product_value,
                }
                weakest_threshold = c0 - n**3
                if best_nonpattern is not None:
                    assert best_nonpattern < weakest_threshold
                    margin = weakest_threshold - best_nonpattern
                    minimum_margin = (
                        margin if minimum_margin is None
                        else min(minimum_margin, margin)
                    )
                if best_bad_matching is not None:
                    assert best_bad_matching < weakest_threshold
                instances += 1
        margins[n] = minimum_margin

    result = {
        "audit": "raw determinant reduction enumeration",
        "n_max": n_max,
        "instances": instances,
        "tour_evaluations": tour_evaluations,
        "minimum_nonpattern_margins": margins,
        "status": "PASS",
    }
    print(result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--full", action="store_true",
        help="reproduce all reported counts (roughly two million enumerations)",
    )
    parser.add_argument("--reduction-max", type=int)
    parser.add_argument("--source-max", type=int)
    parser.add_argument("--displacement-max", type=int)
    args = parser.parse_args()

    reduction_max = args.reduction_max or (3 if args.full else 2)
    source_max = args.source_max or (7 if args.full else 6)
    displacement_max = args.displacement_max or (8 if args.full else 7)

    reduction_raw_audit(reduction_max)
    source_audit(source_max)
    displacement_audit(displacement_max)


if __name__ == "__main__":
    main()
