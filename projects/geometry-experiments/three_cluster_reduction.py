#!/usr/bin/env python3
"""Exact tests for the three-cluster reduction from PRODUCT-TSP.

For a PRODUCT-TSP instance with u and v permutations of 1..n, construct
three point classes A, B, C.  The predicted identity is

    max_AREA W = C0 - min_PRODUCT_TSP sum_i u_i v_{sigma(i)},

where sigma ranges over single n-cycles.  The scale choices are intentionally
much larger than necessary so the proof can use transparent global bounds.
"""

from __future__ import annotations

import argparse
import random
from itertools import permutations

from area_tour import held_karp, tour_weight


def is_single_cycle(successor):
    n = len(successor)
    seen = set()
    i = 0
    while i not in seen:
        seen.add(i)
        i = successor[i]
    return i == 0 and len(seen) == n


def product_optimum(u, v):
    n = len(u)
    best = None
    witness = None
    # A cyclic permutation is represented as a tour, then converted to its
    # successor map.  Fixing vertex 0 removes rotation duplicates.
    for tail in permutations(range(1, n)):
        tour = (0,) + tail
        successor = [None] * n
        for i, j in zip(tour, tour[1:] + tour[:1]):
            successor[i] = j
        value = sum(u[i] * v[successor[i]] for i in range(n))
        if best is None or value < best:
            best = value
            witness = tuple(successor)
    return best, witness


def construct(u, v):
    n = len(u)
    assert sorted(u) == list(range(1, n + 1))
    assert sorted(v) == list(range(1, n + 1))
    L = n**3 + 1
    H = L * n
    M = 100 * n * H
    r = [n + 1 - value for value in v]

    points = []
    colors = []
    labels = []
    for i in range(n):
        points.append((L * r[i], 0))
        colors.append("A")
        labels.append(i)
    for i in range(n):
        points.append((M - u[i], L * r[i]))
        colors.append("B")
        labels.append(i)
    for i in range(n):
        points.append((0, M + v[i]))
        colors.append("C")
        labels.append(i)

    C0 = (
        n * M * M
        + M * (sum(v) - sum(u))
        - M * L * sum(r)
        + L * L * sum(value * value for value in r)
        - L * sum(v[i] * r[i] for i in range(n))
    )
    return points, colors, labels, C0, {"L": L, "H": H, "M": M, "r": r}


def decode_exact_pattern(tour, colors, labels):
    """Return (alpha,beta,gamma) if the cyclic colors are ABC, else None."""
    n3 = len(tour)
    start = next((k for k, vertex in enumerate(tour) if colors[vertex] == "A"), None)
    if start is None:
        return None
    rotated = tour[start:] + tour[:start]
    if any(colors[rotated[k]] != "ABC"[k % 3] for k in range(n3)):
        return None
    n = n3 // 3
    alpha = [None] * n
    beta = [None] * n
    gamma = [None] * n
    for k in range(0, n3, 3):
        a, b, c = rotated[k:k + 3]
        alpha[labels[a]] = labels[b]
        beta[labels[b]] = labels[c]
        gamma[labels[c]] = labels[rotated[(k + 3) % n3]]
    return tuple(alpha), tuple(beta), tuple(gamma)


def one_test(u, v, verbose=False):
    source_opt, source_successor = product_optimum(u, v)
    points, colors, labels, C0, scales = construct(u, v)
    area_opt, area_tour = held_karp(points)
    decoded = decode_exact_pattern(area_tour, colors, labels)
    predicted = C0 - source_opt
    result = {
        "n": len(u),
        "u": tuple(u),
        "v": tuple(v),
        "source_opt": source_opt,
        "source_successor": source_successor,
        "area_opt": area_opt,
        "predicted": predicted,
        "identity_holds": area_opt == predicted,
        "decoded": decoded,
        "tour": area_tour,
        "scales": scales,
    }
    if decoded is not None:
        alpha, beta, gamma = decoded
        result["forcing_holds"] = (
            alpha == tuple(range(len(u)))
            and gamma == tuple(range(len(u)))
            and is_single_cycle(beta)
        )
    else:
        result["forcing_holds"] = False
    if verbose or not result["identity_holds"] or not result["forcing_holds"]:
        print(result)
    assert tour_weight(points, area_tour) == area_opt
    return result


def audit(n_max=4, samples=20, seed=20260903):
    rng = random.Random(seed)
    tested = 0
    for n in range(2, n_max + 1):
        if n <= 3:
            instances = [
                (u, v)
                for u in permutations(range(1, n + 1))
                for v in permutations(range(1, n + 1))
            ]
        else:
            instances = []
            for _ in range(samples):
                u = list(range(1, n + 1))
                v = list(range(1, n + 1))
                rng.shuffle(u)
                rng.shuffle(v)
                instances.append((tuple(u), tuple(v)))
        for u, v in instances:
            result = one_test(u, v)
            tested += 1
            if not result["identity_holds"] or not result["forcing_holds"]:
                print("COUNTEREXAMPLE", result)
                return False
    print({"tested": tested, "status": "all exact identities verified"})
    return True


def canonical_exhaustive(n):
    """Test every instance up to simultaneous relabeling at one size.

    Since u is a permutation, relabeling source indices can put it in the order
    (1,...,n); the correspondingly relabeled v remains an arbitrary
    permutation.  These n! cases therefore represent every (u,v) pair up to a
    label symmetry respected by the construction.
    """
    u = tuple(range(1, n + 1))
    tested = 0
    for v in permutations(range(1, n + 1)):
        result = one_test(u, v)
        tested += 1
        if not result["identity_holds"] or not result["forcing_holds"]:
            print("COUNTEREXAMPLE", result)
            return False
    print({
        "n": n,
        "tested": tested,
        "scope": "all factor pairs up to simultaneous relabeling",
        "status": "all exact identities verified",
    })
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-max", type=int, default=4)
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument(
        "--canonical-exhaustive", type=int,
        help="instead test all n! instances at this size up to relabeling",
    )
    args = parser.parse_args()
    if args.canonical_exhaustive is not None:
        ok = canonical_exhaustive(args.canonical_exhaustive)
    else:
        ok = audit(args.n_max, args.samples)
    raise SystemExit(0 if ok else 1)
