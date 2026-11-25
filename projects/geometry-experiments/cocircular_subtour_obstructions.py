#!/usr/bin/env python3
"""Exact obstructions to subtour-LP algorithms for cocircular area tours.

The four examples successively preserve fixed integer winding, the usual
local-CCW inequalities, and a common strict kernel. The last has twelve
integer points on a radius-5 circle, Hamiltonian optimum 288, and a feasible
fractional value 289 at the globally optimal winding 3.

All geometry, LP constraints, objectives, and dynamic programming use exact
arithmetic. This is a finite certificate, not a proof of general NP-hardness.
No external packages or project imports are used.
"""

from fractions import Fraction as F
from itertools import permutations
from math import lcm


SIX = ((-5, 0), (-4, -3), (0, -5), (3, -4), (3, 4), (0, 5))
SEVEN_FIXED = ((-1, 0), (F(-15, 17), F(-8, 17)),
               (F(-4, 5), F(-3, 5)), (F(-5, 13), F(-12, 13)),
               (F(3, 5), F(4, 5)), (F(-9, 41), F(40, 41)),
               (F(-3, 5), F(4, 5)))
SEVEN_LOCAL = ((-1, 0), (F(-15, 17), F(-8, 17)),
               (F(-4, 5), F(-3, 5)), (F(-33, 65), F(-56, 65)),
               (F(4, 5), F(3, 5)), (0, 1), (F(-3, 5), F(4, 5)))
TWELVE = ((-5, 0), (-4, -3), (-3, -4), (0, -5),
          (3, -4), (4, -3), (5, 0), (4, 3),
          (3, 4), (0, 5), (-3, 4), (-4, 3))


def det(a, b):
    return a[0]*b[1] - a[1]*b[0]


def winding(order):
    return sum(order[(i+1) % len(order)] < order[i] for i in range(len(order)))


def integer_matrix(points):
    rational = tuple(tuple(F(det(a, b)) for b in points) for a in points)
    denominator = lcm(*(v.denominator for row in rational for v in row))
    return denominator, tuple(tuple(int(v*denominator) for v in row)
                              for row in rational)


def held_karp(w):
    """Independent exact maximum-cycle DP, fixing vertex 0."""
    n = len(w)
    states = {(1, 0): 0}
    predecessor = {}
    for mask in range(1, 1 << n, 2):
        for last in range(n):
            if (mask, last) not in states:
                continue
            value = states[mask, last]
            for nxt in range(1, n):
                if mask & (1 << nxt):
                    continue
                target = mask | (1 << nxt), nxt
                candidate = value + w[last][nxt]
                if target not in states or candidate > states[target]:
                    states[target] = candidate
                    predecessor[target] = last
    full = (1 << n)-1
    optimum, last = max((states[full, j]+w[j][0], j)
                        for j in range(1, n))
    reverse = []
    mask = full
    while last:
        reverse.append(last)
        old_last = last
        last = predecessor[mask, last]
        mask ^= 1 << old_last
    order = (0,) + tuple(reversed(reverse))
    assert len(order) == n and len(set(order)) == n
    assert sum(w[order[i]][order[(i+1) % n]] for i in range(n)) == optimum
    return optimum, order


def verify_instance(name, points, y, divisor, expected_optimum,
                    expected_fractional, expected_winding=None,
                    require_local=False, require_kernel=False):
    """The LP vector is x=y/divisor, with integer-valued y."""
    n = len(points)
    assert len(set(points)) == n
    radius_squared = sum(v*v for v in points[0])
    assert all(sum(v*v for v in p) == radius_squared for p in points)
    # For cocircular points, positive orientation of every i<j<k triple
    # certifies the supplied counterclockwise circular order.
    for i in range(n):
        for j in range(i+1, n):
            for k in range(j+1, n):
                a = tuple(points[j][h]-points[i][h] for h in (0, 1))
                b = tuple(points[k][h]-points[i][h] for h in (0, 1))
                assert det(a, b) > 0
    scale, w = integer_matrix(points)
    assert all(i != j and 0 < v <= divisor for (i, j), v in y.items())
    assert all(sum(v for (i, j), v in y.items() if i == q) == divisor
               for q in range(n))
    assert all(sum(v for (i, j), v in y.items() if j == q) == divisor
               for q in range(n))
    fractional_winding = F(sum(v for (i, j), v in y.items() if j < i), divisor)
    if expected_winding is not None:
        assert fractional_winding == expected_winding
    for mask in range(1, (1 << n)-1):
        outgoing = sum(v for (i, j), v in y.items()
                       if mask & (1 << i) and not mask & (1 << j))
        assert outgoing >= divisor, (name, mask, outgoing)
    if require_local:
        for i in range(n):
            for j in range(n):
                for k in range(n):
                    if len({i, j, k}) == 3 and (j-i) % n + (k-j) % n >= n:
                        assert y.get((i, j), 0)+y.get((j, k), 0) <= divisor
    if require_kernel:
        assert all(w[i][j] > 0 for i, j in y)
    fractional = F(sum(v*w[i][j] for (i, j), v in y.items()), divisor*scale)
    best, order = held_karp(w)
    optimum = F(best, scale)
    assert optimum == expected_optimum
    assert fractional == expected_fractional and fractional > optimum
    if expected_winding is not None:
        assert winding(order) == expected_winding
    if n <= 7:
        best_by_winding = {}
        count = 0
        for tail in permutations(range(1, n)):
            tour = (0,) + tail
            value = sum(w[tour[i]][tour[(i+1) % n]] for i in range(n))
            k = winding(tour)
            best_by_winding[k] = max(value, best_by_winding.get(k, value))
            count += 1
        assert max(best_by_winding.values()) == best
        assert count == (120 if n == 6 else 720)
    print(name, "PASS:", "tour", optimum, "fractional", fractional,
          "gap", fractional-optimum, "fractional winding", fractional_winding)
    print("  optimal tour:", order)
    return w


def verify_six_upper_bound(w):
    rows = (26, 23, 13, 24, 24, 31)
    columns = (-6, -11, -3, 2, 0, -9)
    even = {0, 2, 4}
    assert sum(rows)+sum(columns) == 114
    for i in range(6):
        for j in range(6):
            if i == j:
                continue
            slack = rows[i]+columns[j]+2*(i in even and j in even)-w[i][j]
            if (j-i) % 6 in (1, 2):
                assert slack == 0
            else:
                assert slack >= 4
    # Thus W<=114+2*x(E,E)<=118 for the LP. For a tour, positive slack
    # gives W<=114+4-4=114. A zero-slack tour uses only +1/+2; its indegree
    # equations force one common step. Only the +1 choice is Hamiltonian.


def verify_twelve_upper_bound(w):
    """Check all finite arithmetic in the accompanying phase proof."""
    assert all(v <= 25 for row in w for v in row)
    increments = {(0, 1): 1, (1, 0): 1, (0, 2): 0,
                  (2, 0): 2, (1, 2): 1, (2, 1): 1}
    for i in range(12):
        for j in range(12):
            if i == j:
                continue
            a, b = i % 3, j % 3
            loss = 25-w[i][j]
            if a == b:
                assert loss == 0 if (j-i) % 12 == 3 else loss >= 25
            else:
                minimum = 5 if 0 in (a, b) else 1
                assert loss >= minimum
                if loss == minimum:
                    assert (j//3-i//3) % 4 == increments[a, b]
                else:
                    assert loss >= (10 if 0 in (a, b) else 18)
    assert (9+increments[0, 1]+increments[1, 2]+increments[2, 0]) % 4 != 0
    assert (9+increments[0, 2]+increments[2, 1]+increments[1, 0]) % 4 != 0
    # A Hamiltonian cycle of loss<12 must use exactly one quotient 3-cycle,
    # with interclass losses 5,5,1; all nine remaining edges have loss zero.
    # The two possible quotient orientations above have inconsistent total
    # phase modulo four. Therefore every Hamiltonian cycle loses at least12.
    witness = (0, 3, 6, 9, 11, 2, 5, 7, 10, 1, 4, 8)
    assert sum(w[witness[i]][witness[(i+1) % 12]] for i in range(12)) == 288
    assert winding(witness) == 3


def main():
    y6 = {(i, (i+1) % 6): 1 for i in range(6)}
    y6.update({(i, (i+2) % 6): 2 for i in range(6)})
    w6 = verify_instance("Subtour LP", SIX, y6, 3, F(114), F(118),
                         require_local=True, require_kernel=True)
    verify_six_upper_bound(w6)
    yf = {(0, 2): 2, (1, 3): 2, (3, 4): 2,
          (2, 1): 1, (2, 5): 1, (4, 5): 1, (4, 6): 1,
          (5, 0): 1, (5, 6): 1, (6, 0): 1, (6, 1): 1}
    verify_instance("Fixed winding", SEVEN_FIXED, yf, 2,
                    F(764214, 226525), F(768907, 226525), expected_winding=2)
    yl = {(0, 2): 2, (0, 3): 1, (1, 2): 1, (1, 3): 2,
          (2, 1): 1, (2, 5): 2, (3, 4): 3, (4, 5): 1,
          (4, 6): 2, (5, 0): 2, (5, 6): 1, (6, 0): 1, (6, 1): 2}
    verify_instance("Fixed winding plus local CCW", SEVEN_LOCAL, yl, 3,
                    F(796, 221), F(11972, 3315), expected_winding=2,
                    require_local=True)
    y12 = {(i, (i+3) % 12): 6 for i in range(12)}
    y12.update({(i, (i+2) % 12): 1 for i in range(12)})
    y12.update({(i, (i+4) % 12): 1 for i in range(12)})
    w12 = verify_instance("Fixed winding plus common kernel", TWELVE, y12, 8,
                          F(288), F(289), expected_winding=3,
                          require_local=True, require_kernel=True)
    verify_twelve_upper_bound(w12)
    print("PASS: all four exact certificates and both arithmetic upper bounds.")


if __name__ == "__main__":
    main()

