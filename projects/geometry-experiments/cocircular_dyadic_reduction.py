#!/usr/bin/env python3
"""Independent exact audit of the dyadic parabolic-to-circle reduction.

This program uses only the Python standard library and imports no other
project code. It verifies finite instances; the accompanying written proof
must discharge the unbounded statements and the cited source hardness.
Run normally (never with -O). --full expands the residual-graph audit.
"""

from __future__ import annotations

import argparse
from fractions import Fraction as F
from itertools import permutations
from math import lcm
from random import Random

if not __debug__:
    raise RuntimeError("Assertions must be enabled; do not use -O or -OO.")


def determinant(a, b):
    return a[0]*b[1]-a[1]*b[0]


def kernel(x, y):
    return x*y*(y-x)


def cycle_count(s):
    seen = set()
    count = 0
    for start in range(len(s)):
        if start in seen:
            continue
        count += 1
        current = start
        while current not in seen:
            seen.add(current)
            current = s[current]
    return count


def partitions(k):
    """Canonical restricted-growth encodings, independently enumerated."""
    if k == 0:
        yield ()
        return
    def extend(prefix):
        if len(prefix) == k:
            yield tuple(prefix)
            return
        for label in range(max(prefix)+2):
            yield from extend(prefix+[label])
    yield from extend([0])


def partition_permutation(labels):
    k = len(labels)
    sigma = [-1]*k
    for block in range(max(labels)+1):
        vertices = [i for i in range(k) if labels[i] == block]
        for i, j in zip(vertices, vertices[1:]+vertices[:1]):
            sigma[i] = j
    assert sorted(sigma) == list(range(k))
    return tuple(sigma)


def permutation_partition(sigma):
    labels = [-1]*len(sigma)
    next_label = 0
    for i in range(len(sigma)):
        if labels[i] >= 0:
            continue
        j = i
        while labels[j] < 0:
            labels[j] = next_label
            j = sigma[j]
        next_label += 1
    return tuple(labels)


def partition_spine_yes(labels):
    """Exhaust all sets of disjoint adjacent-label edges and test a tree."""
    k = len(labels)
    m = max(labels)+1
    for mask in range(1 << (k-1)):
        if mask.bit_count() != m-1:
            continue
        parent = list(range(m))
        used = set()
        valid = True
        def find(v):
            while parent[v] != v:
                v = parent[v]
            return v
        for i in range(k-1):
            if not mask & (1 << i):
                continue
            if i in used or i+1 in used:
                valid = False
                break
            used.update((i, i+1))
            a, b = find(labels[i]), find(labels[i+1])
            if a == b:
                valid = False
                break
            parent[a] = b
        if valid and len({find(v) for v in range(m)}) == 1:
            return True
    return False


def construct(sigma):
    """Construct directly from path lengths, without a FIFO implementation."""
    k = len(sigma)
    assert k >= 2 and sorted(sigma) == list(range(k))
    n = k*(k+5)//2
    gap = 100*k*k
    anchor_bound = 2**(k+1)
    offset_bound = 2**k*gap*k
    anchor = (100*n*(offset_bound+1)*(anchor_bound+1)**2
              + k**4+1)
    heights = [k+1-sigma[i] for i in range(k)]
    nodes = []
    for i in range(k):
        for level in range(heights[i]+1):
            if level == 0:
                coordinate, leading, offset = i, 0, i
            elif level == 1:
                coordinate, leading, offset = anchor+i, 1, i
            else:
                factor = 2**(level-2)
                coordinate = factor*(2*anchor+gap*i)
                leading, offset = 2*factor, factor*gap*i
            nodes.append((coordinate, i, level, leading, offset))
    nodes.sort()
    assert len(nodes) == n
    xs = tuple(v[0] for v in nodes)
    assert all(a < b for a, b in zip(xs, xs[1:]))
    index = {(i, level): j for j, (_, i, level, _, _) in enumerate(nodes)}
    assert all(index[i, 0] == i and index[i, 1] == k+i for i in range(k))
    phi = [-1]*n
    for row, (_, i, level, leading, offset) in enumerate(nodes):
        assert xs[row] == anchor*leading+offset
        assert 0 <= leading <= anchor_bound and 0 <= offset <= offset_bound
        if level < heights[i]:
            phi[row] = index[i, level+1]
        else:
            phi[row] = index[sigma[i], 0]
    assert sorted(phi) == list(range(n))
    assert cycle_count(phi) == cycle_count(sigma)
    peaks = [index[i, heights[i]] for i in range(k)]
    peaks.sort()
    assert [phi[p] for p in peaks] == list(reversed(range(k)))
    for i in range(k):
        j = phi[i]
        while j >= k:
            j = phi[j]
        assert j == sigma[i]
    w = tuple(tuple(kernel(x, y) for y in xs) for x in xs)
    baseline = sum(w[i][phi[i]] for i in range(n))
    threshold = baseline-2*anchor*(cycle_count(sigma)-1)
    return {"k": k, "n": n, "gap": gap, "anchor": anchor,
            "anchor_bound": anchor_bound, "offset_bound": offset_bound,
            "xs": xs, "nodes": tuple(nodes), "phi": tuple(phi), "w": w,
            "baseline": baseline, "threshold": threshold}


def exact_hamiltonian(w):
    """Exact Held--Karp, with integer arithmetic and witness reconstruction."""
    n = len(w)
    table = {(1, 0): 0}
    previous = {}
    for mask in range(1, 1 << n, 2):
        for last in range(n):
            key = mask, last
            if key not in table:
                continue
            value = table[key]
            for nxt in range(1, n):
                if mask & (1 << nxt):
                    continue
                destination = mask | (1 << nxt), nxt
                candidate = value+w[last][nxt]
                if destination not in table or candidate > table[destination]:
                    table[destination] = candidate
                    previous[destination] = last
    full = (1 << n)-1
    value, last = max((table[full, j]+w[j][0], j) for j in range(1, n))
    mask = full
    reverse = []
    while last:
        reverse.append(last)
        old = last
        last = previous[mask, last]
        mask ^= 1 << old
    tour = (0,)+tuple(reversed(reverse))
    assert len(tour) == n and len(set(tour)) == n
    assert sum(w[tour[i]][tour[(i+1) % n]] for i in range(n)) == value
    return value, tour


def residual_audit(instance):
    """Certify all exchange cycles and the cheapest cycle using an auxiliary row."""
    w, phi = instance["w"], instance["phi"]
    k, n = instance["k"], instance["n"]
    edge = [[w[i][phi[i]]-w[i][phi[j]] for j in range(n)] for i in range(n)]
    distance = [row[:] for row in edge]
    for middle in range(n):
        via = distance[middle]
        for i in range(n):
            prefix = distance[i][middle]
            row = distance[i]
            for j in range(n):
                candidate = prefix+via[j]
                if candidate < row[j]:
                    row[j] = candidate
    assert all(distance[i][i] == 0 for i in range(n)), "Negative exchange cycle"
    auxiliary_gap = min(edge[i][j]+distance[j][i]
                        for i in range(k, n) for j in range(n) if i != j)
    assert auxiliary_gap > 2*instance["anchor"]*(k-1), auxiliary_gap
    # Adjacent transpositions of initial rows have the exact intended cost.
    for i in range(k-1):
        assert edge[i][i+1]+edge[i+1][i] == 2*instance["anchor"]
    return auxiliary_gap


def initial_matching_audit(instance, sigma):
    k, n = instance["k"], instance["n"]
    a, w, phi = instance["anchor"], instance["w"], instance["phi"]
    found = False
    for tau in permutations(range(k)):
        changed = list(phi)
        for i in range(k):
            changed[i] = phi[tau[i]]
        displacement = sum(i*(i-tau[i]) for i in range(k))
        residual = sum(i*i*tau[i]-i*tau[i]*tau[i] for i in range(k))
        loss = instance["baseline"]-sum(w[i][changed[i]] for i in range(n))
        assert loss == 2*a*displacement+residual
        assert abs(residual) < k**4
        induced = tuple(sigma[tau[i]] for i in range(k))
        assert (cycle_count(changed) == 1) == (cycle_count(induced) == 1)
        if cycle_count(changed) == 1 and loss <= 2*a*(cycle_count(sigma)-1):
            found = True
    assert found == partition_spine_yes(permutation_partition(sigma))


def circle_instance(instance):
    """Clear rational circle denominators exactly; return integer circle data."""
    xs, n = instance["xs"], instance["n"]
    bound = max(xs)
    epsilon_denominator = 8*n*bound**3
    denominators = tuple(epsilon_denominator**2+x*x for x in xs)
    radius = lcm(*denominators)
    points = tuple(((epsilon_denominator**2-x*x)*(radius//d),
                    2*epsilon_denominator*x*(radius//d))
                   for x, d in zip(xs, denominators))
    assert len(set(points)) == n
    assert all(x*x+y*y == radius*radius for x, y in points)
    w = tuple(tuple(determinant(p, q) for q in points) for p in points)
    target = F(2*(2*instance["threshold"]-1)*radius**2,
               epsilon_denominator**3)
    integer_threshold = -((-target.numerator)//target.denominator)
    assert F(integer_threshold-1) < target <= integer_threshold
    # Exact normalized error estimate from translation by (-1,0):
    # W_circle/(4 epsilon^3) = sum K/(1+epsilon^2 x^2)(1+epsilon^2 y^2).
    error = F(2*n*bound**5, epsilon_denominator**2)
    assert error < F(1, 2)
    # Also check the more generous bound quoted in the accompanying proof.
    assert F(40*n*bound**5, epsilon_denominator**2) < 2
    return points, w, integer_threshold, radius, epsilon_denominator, error


def full_small_audit(sigma, circle=True):
    instance = construct(sigma)
    source_yes = partition_spine_yes(permutation_partition(sigma))
    residual_audit(instance)
    initial_matching_audit(instance, sigma)
    para_value, para_tour = exact_hamiltonian(instance["w"])
    assert (para_value >= instance["threshold"]) == source_yes
    if circle:
        points, w, threshold, radius, q, error = circle_instance(instance)
        circle_value, circle_tour = exact_hamiltonian(w)
        assert (circle_value >= threshold) == source_yes
        # Check the error estimate on both independently optimized witnesses.
        for tour in (para_tour, circle_tour):
            para_weight = sum(instance["w"][tour[i]][tour[(i+1) % len(tour)]]
                              for i in range(len(tour)))
            circle_weight = sum(w[tour[i]][tour[(i+1) % len(tour)]]
                                for i in range(len(tour)))
            normalized = F(circle_weight*q**3, 4*radius**2)
            assert abs(normalized-para_weight) <= error
        # The returned integer coordinates are themselves exactly cocircular.
        assert all(p[0]*p[0]+p[1]*p[1] == radius**2 for p in points)
    return source_yes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true",
                        help="Expand all-permutation and sampled residual-cycle checks.")
    args = parser.parse_args()
    counts = {"small_yes": 0, "small_no": 0, "residual_instances": 0}
    # Every permutation at k=2,3: arbitrary initial cycle orders as well as
    # every possible source partition. N=7 and12 permits full exact tour DPs.
    for k in (2, 3):
        for sigma in permutations(range(k)):
            yes = full_small_audit(sigma)
            counts["small_yes" if yes else "small_no"] += 1
        print("PASS: all parabolic and circle instances for source size", k, flush=True)
    # Independently enumerate partitions and test the source equivalence.
    partition_count = 0
    for k in range(2, 7 if args.full else 5):
        for labels in partitions(k):
            sigma = partition_permutation(labels)
            instance = construct(sigma)
            initial_matching_audit(instance, sigma)
            assert permutation_partition(sigma) == labels
            partition_count += 1
    print("PASS: source partition and initial-matching identities:", partition_count, flush=True)
    rng = Random(2026090723)
    maximum_k = 9 if args.full else 6
    for k in range(2, maximum_k+1):
        if k <= (5 if args.full else 4):
            cases = list(permutations(range(k)))
        else:
            cases = [tuple(rng.sample(range(k), k))
                     for _ in range(30 if args.full else 8)]
        minimum_ratio = None
        for sigma in cases:
            instance = construct(sigma)
            gap = residual_audit(instance)
            ratio = F(gap, 2*instance["anchor"])
            minimum_ratio = ratio if minimum_ratio is None else min(minimum_ratio, ratio)
            counts["residual_instances"] += 1
        print("PASS: all-exchange-cycle certificate k =", k, "cases =", len(cases),
              "minimum auxiliary gap/(2A) =", minimum_ratio, flush=True)
    assert counts["small_yes"] > 0 and counts["small_no"] > 0
    print("PASS: independent dyadic reduction audit", counts, flush=True)


if __name__ == "__main__":
    main()

