#!/usr/bin/env python3
"""Reproducible structural experiments for determinant-weight tours.

This file is deliberately independent of reduction/gadget code.  Integer and
rational experiments are exact.  The regular-polygon Held--Karp check uses
floating-point trigonometric coordinates and only checks the proved formula.
"""

from __future__ import annotations

import argparse
import math
import random
from collections import Counter
from fractions import Fraction
from itertools import combinations, permutations

from area_tour import brute_force, held_karp, tour_weight


def orient(a, b, c):
    return ((b[0] - a[0]) * (c[1] - a[1])
            - (b[1] - a[1]) * (c[0] - a[0]))


def general_position(points):
    return (len(set(points)) == len(points)
            and all(orient(a, b, c) != 0
                    for a, b, c in combinations(points, 3)))


def proper_crossings(points, tour):
    result = []
    n = len(tour)
    for i in range(n):
        a, b = tour[i], tour[(i + 1) % n]
        for j in range(i + 1, n):
            c, d = tour[j], tour[(j + 1) % n]
            if len({a, b, c, d}) < 4:
                continue
            if (orient(points[a], points[b], points[c])
                    * orient(points[a], points[b], points[d]) < 0
                    and orient(points[c], points[d], points[a])
                    * orient(points[c], points[d], points[b]) < 0):
                result.append(((a, b), (c, d)))
    return tuple(result)


def edge_determinants(points, tour):
    return tuple(
        points[i][0] * points[j][1] - points[i][1] * points[j][0]
        for i, j in zip(tour, tour[1:] + tour[:1])
    )


def all_rows(points):
    rows = []
    for tail in permutations(range(1, len(points))):
        tour = (0,) + tail
        rows.append((tour_weight(points, tour), tour,
                     edge_determinants(points, tour),
                     proper_crossings(points, tour)))
    return sorted(rows, reverse=True)


def hull_indices(points):
    tagged = sorted((point, i) for i, point in enumerate(points))
    lower = []
    for item in tagged:
        while (len(lower) >= 2
               and orient(lower[-2][0], lower[-1][0], item[0]) <= 0):
            lower.pop()
        lower.append(item)
    upper = []
    for item in reversed(tagged):
        while (len(upper) >= 2
               and orient(upper[-2][0], upper[-1][0], item[0]) <= 0):
            upper.pop()
        upper.append(item)
    return tuple(i for _, i in lower[:-1] + upper[:-1])


def canonical_rotation(tour):
    k = tour.index(0)
    return tour[k:] + tour[:k]


def cyclic_segment_reversal_neighbors(tour):
    """All directed 2-opt reversals of either cyclic segment.

    In asymmetric weights the two complementary reversals are not equivalent,
    so wrap-around blocks must be retained.
    """
    n = len(tour)
    result = set()
    for start in range(n):
        for length in range(2, n - 1):
            positions = tuple((start + k) % n for k in range(length))
            neighbor = list(tour)
            values = [tour[i] for i in positions][::-1]
            for position, value in zip(positions, values):
                neighbor[position] = value
            result.add(canonical_rotation(tuple(neighbor)))
    result.discard(tour)
    return result


def exact_examples():
    general = ((0, 0), (1, 2), (1, 3), (2, 1), (3, 1))
    rows = all_rows(general)
    simple = max(row for row in rows if not row[3])
    assert rows[0][0] == 7 and rows[0][1] == (0, 4, 1, 3, 2)
    assert simple[0] == 6 and len([r for r in rows if r[0] == 7]) == 1
    print({
        "example": "five-point unique crossing optimum",
        "points": general,
        "global": rows[0],
        "simple_best": simple,
        "weight_histogram": sorted(Counter(r[0] for r in rows).items(),
                                   reverse=True),
    })

    hull_order = ((0, 0), (0, 5), (1, 1), (4, 2), (5, 1))
    rows = all_rows(hull_order)
    hull = hull_indices(hull_order)
    induced = tuple(i for i in rows[0][1] if i in hull)
    assert rows[0][0] == 23 and rows[0][1] == (0, 3, 2, 4, 1)
    assert hull == (0, 4, 3, 1) and induced == (0, 3, 4, 1)
    print({
        "example": "hull order is not preserved",
        "points": hull_order,
        "hull_ccw": hull,
        "global": rows[0],
        "induced_hull_order": induced,
    })

    circle = ((-4, -3), (-3, -4), (4, -3), (5, 0), (0, 5), (-3, 4))
    rows = all_rows(circle)
    boundary = (0, 1, 2, 3, 4, 5)
    assert all(x * x + y * y == 25 for x, y in circle)
    assert not any(circle[i] == (-circle[j][0], -circle[j][1])
                   for i, j in combinations(range(6), 2))
    assert rows[0][0] == 124 and tour_weight(circle, boundary) == 112
    assert len([r for r in rows if r[0] == 124]) == 2
    assert all(min(r[2]) > 0 for r in rows if r[0] == 124)
    print({
        "example": "non-antipodal integer cocircular crossing optima",
        "points": circle,
        "boundary": (tour_weight(circle, boundary), boundary),
        "global_optima": [r for r in rows if r[0] == rows[0][0]],
    })

    negative = ((-4, -3), (-3, -4), (0, -5), (3, -4), (5, 0), (4, 3))
    rows = all_rows(negative)
    nonnegative = max(row for row in rows if min(row[2]) >= 0)
    assert rows[0][0] == 74 and len([r for r in rows if r[0] == 74]) == 1
    assert min(rows[0][2]) == -20 and nonnegative[0] == 72
    print({
        "example": "cocircular optimum requires a negative edge",
        "points": negative,
        "global": rows[0],
        "best_all_edges_nonnegative": nonnegative,
    })

    local_points = ((0, 0), (0, 1), (1, 0), (1, 2), (2, 1))
    local = (0, 4, 1, 2, 3)
    neighbors = cyclic_segment_reversal_neighbors(local)
    local_value = tour_weight(local_points, local)
    neighbor_rows = sorted((tour_weight(local_points, t), t) for t in neighbors)
    global_value, global_tour = brute_force(local_points)
    assert local_value == 3 and global_value == 5
    assert len(neighbors) == 10 and max(v for v, _ in neighbor_rows) == 2
    print({
        "example": "strict suboptimal cyclic-2-opt local maximum",
        "points": local_points,
        "local": (local_value, local),
        "neighbors": neighbor_rows,
        "global": (global_value, global_tour),
    })


def grid_audit():
    universe = tuple((x, y) for x in range(4) for y in range(4))
    for n in (4, 5):
        counts = Counter()
        first_all = None
        for points in combinations(universe, n):
            if not general_position(points):
                continue
            counts["general_position_sets"] += 1
            rows = all_rows(points)
            optimum = rows[0][0]
            optima = [row for row in rows if row[0] == optimum]
            flags = [bool(row[3]) for row in optima]
            counts["some_crossing_optimum"] += any(flags)
            counts["only_crossing_optima"] += all(flags)
            if all(flags) and first_all is None:
                first_all = (points, optima)
        print({"audit": "all subsets of {0,1,2,3}^2",
               "n": n, **counts, "first_all_crossing": first_all})


def identity_audit(trials):
    rng = random.Random(190733)

    def point():
        return (Fraction(rng.randrange(-30, 31), rng.randrange(1, 10)),
                Fraction(rng.randrange(-30, 31), rng.randrange(1, 10)))

    def det(a, b):
        return a[0] * b[1] - a[1] * b[0]

    def add(a, b):
        return a[0] + b[0], a[1] + b[1]

    def sub(a, b):
        return a[0] - b[0], a[1] - b[1]

    for _ in range(trials):
        a, b, c, d = point(), point(), point(), point()
        exchange = det(a, d) + det(c, b) - det(a, b) - det(c, d)
        assert exchange == det(sub(a, c), sub(d, b))
        assert (det(a, b) * det(c, d) - det(a, c) * det(b, d)
                + det(a, d) * det(b, c) == 0)

        n = rng.randrange(3, 10)
        points = [point() for __ in range(n)]
        translation = point()
        translated = [add(p, translation) for p in points]
        tour = tuple(range(n))
        assert tour_weight(points, tour) == tour_weight(translated, tour)
        assert tour_weight(points, tuple(reversed(tour))) == -tour_weight(points, tour)
        matrix = tuple(Fraction(rng.randrange(-8, 9)) for __ in range(4))
        transformed = [(matrix[0] * x + matrix[1] * y,
                        matrix[2] * x + matrix[3] * y) for x, y in points]
        determinant = matrix[0] * matrix[3] - matrix[1] * matrix[2]
        assert tour_weight(transformed, tour) == determinant * tour_weight(points, tour)
    print({"audit": "exact exchange/Plucker/invariance identities",
           "seed": 190733, "trials": trials, "status": "PASS"})


def oracle_audit(trials_per_n):
    rng = random.Random(20260903)
    checked = 0
    for n in range(2, 9):
        for _ in range(trials_per_n):
            points = tuple((rng.randrange(-9, 10), rng.randrange(-9, 10))
                           for __ in range(n))
            assert brute_force(points)[0] == held_karp(points)[0]
            checked += 1
    print({"audit": "brute force versus Held--Karp",
           "seed": 20260903, "instances": checked, "status": "PASS"})


def regular_constructed_tour(n):
    if n % 4:
        best_step = max((k for k in range(1, n) if math.gcd(k, n) == 1),
                        key=lambda k: math.sin(2 * math.pi * k / n))
        return tuple((j * best_step) % n for j in range(n))

    m = n // 4
    successor = [(v + m) % n for v in range(n)]
    for r in range(1, m):
        level = r % 2
        u = r - 1 + level * m
        v = r + level * m
        successor[u], successor[v] = successor[v], successor[u]
    tour = [0]
    while successor[tour[-1]] != 0:
        tour.append(successor[tour[-1]])
    assert len(tour) == n
    return tuple(tour)


def regular_formula(n):
    if n % 4:
        step = regular_constructed_tour(n)[1]
        return n * math.sin(2 * math.pi * step / n)
    m = n // 4
    return 2 * m + 2 + 2 * (m - 1) * math.cos(math.pi / (2 * m))


def regular_audit(n_max):
    for n in range(3, n_max + 1):
        points = tuple((math.cos(2 * math.pi * j / n),
                        math.sin(2 * math.pi * j / n)) for j in range(n))
        optimum, dp_tour = held_karp(points)
        constructed = regular_constructed_tour(n)
        prediction = regular_formula(n)
        assert abs(optimum - prediction) < 1e-8
        assert abs(tour_weight(points, constructed) - prediction) < 1e-8
        increments = tuple((constructed[(i + 1) % n] - constructed[i]) % n
                           for i in range(n))
        print({
            "regular_n": n,
            "held_karp": round(float(optimum), 12),
            "formula": round(prediction, 12),
            "constructed_tour": constructed,
            "increment_counts": dict(sorted(Counter(increments).items())),
            "proper_crossings": len(proper_crossings(points, constructed)),
            "dp_witness": dp_tour,
        })


def random_audit(general_samples, circle_samples):
    rng = random.Random(20260903)
    for n in range(4, 11):
        crossing = total_crossings = 0
        for _ in range(general_samples):
            while True:
                points = tuple((rng.randrange(-25, 26), rng.randrange(-25, 26))
                               for __ in range(n))
                if general_position(points):
                    break
            _, tour = held_karp(points)
            number = len(proper_crossings(points, tour))
            crossing += number > 0
            total_crossings += number
        print({"random_family": "general integer [-25,25]^2 GP",
               "seed": 20260903, "n": n, "samples": general_samples,
               "returned_opt_crossing": crossing,
               "mean_crossings": round(total_crossings / general_samples, 3)})

    def circle_point(t):
        return ((1 - t * t) / (1 + t * t), 2 * t / (1 + t * t))

    rng = random.Random(20260904)
    for n in range(4, 11):
        above = crossing = 0
        gap = Fraction(0)
        for _ in range(circle_samples):
            parameters = set()
            while len(parameters) < n:
                parameters.add(Fraction(rng.randrange(-40, 41),
                                        rng.randrange(1, 13)))
            points = tuple(circle_point(t) for t in sorted(parameters))
            optimum, tour = held_karp(points)
            boundary = tour_weight(points, tuple(range(n)))
            above += optimum > boundary
            crossing += bool(proper_crossings(points, tour))
            gap += optimum - boundary
        print({"random_family": "rational unit circle t=num/den",
               "seed": 20260904, "n": n, "samples": circle_samples,
               "opt_above_boundary": above,
               "returned_opt_crossing": crossing,
               "mean_gap": round(float(gap / circle_samples), 6)})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--grid", action="store_true")
    parser.add_argument("--identity-trials", type=int, default=1000)
    parser.add_argument("--oracle-trials", type=int, default=10)
    parser.add_argument("--regular-max", type=int, default=12)
    parser.add_argument("--general-samples", type=int, default=0)
    parser.add_argument("--circle-samples", type=int, default=0)
    args = parser.parse_args()
    exact_examples()
    identity_audit(args.identity_trials)
    oracle_audit(args.oracle_trials)
    if args.grid:
        grid_audit()
    if args.regular_max:
        regular_audit(args.regular_max)
    if args.general_samples or args.circle_samples:
        if not args.general_samples or not args.circle_samples:
            parser.error("set both --general-samples and --circle-samples")
        random_audit(args.general_samples, args.circle_samples)


if __name__ == "__main__":
    main()
