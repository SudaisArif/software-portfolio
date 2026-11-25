#!/usr/bin/env python3
"""Search for no-five-star failures in the quarter-turn reduction."""

from fractions import Fraction as F
from itertools import combinations, permutations
from random import Random


def point(t):
    d = 1 + t*t
    return ((1-t*t)/d, 2*t/d)


def det(a, b):
    return a[0]*b[1] - a[1]*b[0]


def half(p):
    return 0 if p[1] > 0 or (p[1] == 0 and p[0] >= 0) else 1


def angular_order(points):
    from functools import cmp_to_key
    def cmp(a, b):
        ha, hb = half(points[a]), half(points[b])
        if ha != hb:
            return -1 if ha < hb else 1
        d = det(points[a], points[b])
        return -1 if d > 0 else (1 if d < 0 else 0)
    return tuple(sorted(range(len(points)), key=cmp_to_key(cmp)))


def five_star(rank_tour):
    """Return a five-star witness or None."""
    n = len(rank_tour)
    pos = [0]*n
    for i, rank in enumerate(rank_tour):
        pos[rank] = i
    for subset in combinations(range(n), 5):
        base = subset[0]
        encountered = tuple(sorted(subset, key=lambda x: (pos[x]-pos[base]) % n))
        if encountered == (subset[0], subset[2], subset[4], subset[1], subset[3]):
            return subset, encountered
        if encountered == (subset[0], subset[3], subset[1], subset[4], subset[2]):
            return subset, encountered
    return None


def alternating_rank_tour(params, order):
    blue = tuple(point(t) for t in params)
    red = tuple((-p[1], p[0]) for p in blue)
    vertices = blue + red
    if len(set(vertices)) < len(vertices):
        return None
    boundary = angular_order(vertices)
    rank = {v:i for i,v in enumerate(boundary)}
    sequence = tuple(x for i in order for x in (i, len(params)+i))
    return tuple(rank[v] for v in sequence)


def weight(params, order):
    p = tuple(point(t) for t in params)
    return sum(det(p[order[i]], p[order[(i+1) % len(order)]]) for i in range(len(order)))


def search():
    rng = Random(12987)
    for n in range(5, 10):
        universe = list(range(-18, 19))
        for trial in range(5000):
            ints = tuple(sorted(rng.sample(universe, n)))
            params = tuple(F(x, 5) for x in ints)
            candidates = []
            best = None
            for tail in permutations(range(1, n)):
                order = (0,) + tail
                w = weight(params, order)
                if best is None or w > best:
                    best, candidates = w, [order]
                elif w == best:
                    candidates.append(order)
            witnesses = []
            valid = True
            for order in candidates:
                ranks = alternating_rank_tour(params, order)
                if ranks is None:
                    valid = False
                    break
                witness = five_star(ranks)
                if witness is None:
                    valid = False
                    break
                witnesses.append((order, ranks, witness))
            if valid:
                print('FOUND', n, ints, best, len(candidates))
                for item in witnesses[:4]: print(item)
                return
        print('done n', n)


if __name__ == '__main__':
    search()
