#!/usr/bin/env python3
"""Test Sarvanov's product-matrix reduction after antisymmetrization.

The source problem used in the classic product-TSP proof is PARTITION GRAPH
SPANNING TREE.  This script enumerates small set partitions, verifies the stated
product-TSP threshold, and records what happens when c_ij=a_i*b_j is replaced by
c_ij-c_ji=det((a_i,b_i),(a_j,b_j)).
"""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations, permutations, product

from area_tour import brute_force, tour_weight


def canonical_partitions(n: int):
    """Yield restricted-growth strings encoding every partition of [n]."""
    if n == 0:
        yield ()
        return
    for tail in product(range(n), repeat=n - 1):
        labels = (0,) + tail
        max_seen = 0
        valid = True
        for label in labels[1:]:
            if label > max_seen + 1:
                valid = False
                break
            max_seen = max(max_seen, label)
        if valid:
            yield labels


def quotient_connected(labels, chosen_edges):
    blocks = set(labels)
    graph = {block: set() for block in blocks}
    for i, j in chosen_edges:
        u, v = labels[i], labels[j]
        if u != v:
            graph[u].add(v)
            graph[v].add(u)
    seen = set()
    stack = [next(iter(blocks))]
    while stack:
        u = stack.pop()
        if u in seen:
            continue
        seen.add(u)
        stack.extend(graph[u] - seen)
    return seen == blocks


def has_good_matching(labels):
    """Definition from Lawler et al.'s presentation of Sarvanov's reduction."""
    n = len(labels)
    m = max(labels) + 1
    spine = [(i, i + 1) for i in range(n - 1) if labels[i] != labels[i + 1]]
    for chosen in combinations(spine, m - 1):
        endpoints = [v for edge in chosen for v in edge]
        if len(set(endpoints)) != len(endpoints):
            continue
        if quotient_connected(labels, chosen):
            return True, chosen
    return False, None


def cycle_permutation(labels):
    blocks = defaultdict(list)
    for i, label in enumerate(labels):
        blocks[label].append(i)
    phi = [None] * len(labels)
    for block in blocks.values():
        for i, vertex in enumerate(block):
            phi[vertex] = block[(i + 1) % len(block)]
    return tuple(phi)


def construction(labels):
    n = len(labels)
    phi = cycle_permutation(labels)
    a = [n - i for i in range(n)]
    b = [None] * n
    # b_{phi(i)}=i+1 gives the reverse-sorted minimum assignment phi.
    for i in range(n):
        b[phi[i]] = i + 1
    return tuple(zip(a, b)), phi


def product_cost(points, tour):
    return sum(points[i][0] * points[j][1]
               for i, j in zip(tour, tour[1:] + tour[:1]))


def brute_product(points):
    best = None
    arg = None
    for tail in permutations(range(1, len(points))):
        tour = (0,) + tail
        value = product_cost(points, tour)
        if best is None or value < best:
            best, arg = value, tour
    return best, arg


def audit(n_max=8):
    first_product_failure = None
    by_n = {}
    skew_counterexample = None
    for n in range(2, n_max + 1):
        groups = defaultdict(list)
        count = 0
        for labels in canonical_partitions(n):
            m = max(labels) + 1
            if m == 1:
                continue
            count += 1
            source_yes, witness = has_good_matching(labels)
            points, phi = construction(labels)
            product_opt, product_tour = brute_product(points)
            base = sum((i + 1) * (n - i) for i in range(n))
            threshold = base + m - 1
            product_equiv = (product_opt <= threshold) == source_yes
            if not product_equiv and first_product_failure is None:
                first_product_failure = {
                    "labels": labels,
                    "source_yes": source_yes,
                    "product_opt": product_opt,
                    "threshold": threshold,
                    "tour": product_tour,
                }

            skew_opt, skew_tour = brute_force(points)
            groups[source_yes].append(skew_opt)
            # The naively inherited threshold cannot work: product cost and its
            # transpose have different, instance-dependent contributions.
            if skew_counterexample is None:
                reverse_product = product_cost(points, tuple(reversed(skew_tour)))
                if skew_opt != product_cost(points, skew_tour) - reverse_product:
                    raise AssertionError("antisymmetrization identity failed")
        by_n[n] = {
            "partitions": count,
            "yes_skew_values": sorted(set(groups[True])),
            "no_skew_values": sorted(set(groups[False])),
            "separable_by_value": (
                not groups[False]
                or not groups[True]
                or max(groups[False]) < min(groups[True])
                or max(groups[True]) < min(groups[False])
            ),
        }
        if groups[True] and groups[False] and not by_n[n]["separable_by_value"]:
            skew_counterexample = skew_counterexample or {
                "n": n,
                "yes_range": (min(groups[True]), max(groups[True])),
                "no_range": (min(groups[False]), max(groups[False])),
            }
    print({"product_reduction_failure": first_product_failure})
    print({"first_skew_overlap": skew_counterexample})
    for n, summary in by_n.items():
        print(n, summary)


if __name__ == "__main__":
    audit()
