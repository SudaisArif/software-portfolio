#!/usr/bin/env python3
"""Independent, exact audit of the proof obligations in ``proof.md``.

This file intentionally does not import the project's other experiment code.
It provides four different kinds of checks:

* coefficient-wise polynomial identity checks using a tiny sparse-polynomial
  implementation (no SymPy or other third-party package is required);
* exhaustive enumeration of all balanced three-colour cyclic words through a
  requested size;
* exhaustive checks of the normalized Sarvanov/PPTSP source reduction on set
  partitions and permutations; and
* raw determinant optimization of the geometric construction on small inputs.

These checks are a bounded falsification aid.  The general quantifiers in the
NP-hardness proof are discharged by the written arguments, not by this file.
All computations below are exact integer or rational computations.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from fractions import Fraction
from itertools import combinations, permutations, product
from math import factorial


# ---------------------------------------------------------------------------
# Minimal exact sparse-polynomial arithmetic


class Poly:
    """A multivariate polynomial over Q.

    A monomial is represented by a sorted tuple containing one copy of a
    variable name for each unit of exponent.  The implementation is deliberately
    small enough to audit visually.
    """

    def __init__(self, terms=None):
        cleaned = {}
        for monomial, coefficient in (terms or {}).items():
            coefficient = Fraction(coefficient)
            monomial = tuple(sorted(monomial))
            if coefficient:
                cleaned[monomial] = cleaned.get(monomial, Fraction(0)) + coefficient
        self.terms = {m: c for m, c in cleaned.items() if c}

    @staticmethod
    def constant(value):
        return Poly({(): Fraction(value)}) if value else Poly()

    @staticmethod
    def variable(name):
        return Poly({(name,): Fraction(1)})

    @staticmethod
    def coerce(value):
        return value if isinstance(value, Poly) else Poly.constant(value)

    def __add__(self, other):
        other = Poly.coerce(other)
        terms = dict(self.terms)
        for monomial, coefficient in other.terms.items():
            terms[monomial] = terms.get(monomial, Fraction(0)) + coefficient
        return Poly(terms)

    __radd__ = __add__

    def __neg__(self):
        return Poly({m: -c for m, c in self.terms.items()})

    def __sub__(self, other):
        return self + (-Poly.coerce(other))

    def __rsub__(self, other):
        return Poly.coerce(other) - self

    def __mul__(self, other):
        other = Poly.coerce(other)
        terms = defaultdict(Fraction)
        for left_monomial, left_coefficient in self.terms.items():
            for right_monomial, right_coefficient in other.terms.items():
                monomial = tuple(sorted(left_monomial + right_monomial))
                terms[monomial] += left_coefficient * right_coefficient
        return Poly(terms)

    __rmul__ = __mul__

    def __pow__(self, exponent):
        if not isinstance(exponent, int) or exponent < 0:
            raise ValueError("only nonnegative integral powers are supported")
        value = Poly.constant(1)
        base = self
        while exponent:
            if exponent & 1:
                value = value * base
            base = base * base
            exponent //= 2
        return value

    def __eq__(self, other):
        return self.terms == Poly.coerce(other).terms

    def __repr__(self):
        return f"Poly({self.terms!r})"


def symbols(*names):
    return tuple(Poly.variable(name) for name in names)


def determinant(left, right):
    return left[0] * right[1] - left[1] * right[0]


def assert_identity(left, right, label):
    difference = Poly.coerce(left) - Poly.coerce(right)
    assert not difference.terms, (label, difference)


def polynomial_identity_audit():
    """Coefficient-check every algebraic identity used by the gadget."""

    L, M, u_i, v_i, v_j, r_i, r_j = symbols(
        "L", "M", "u_i", "v_i", "v_j", "r_i", "r_j"
    )
    A_i = (L * r_i, 0)
    A_j = (L * r_j, 0)
    B_i = (M - u_i, L * r_i)
    B_j = (M - Poly.variable("u_j"), L * r_j)
    C_i = (0, M + v_i)
    C_j = (0, M + v_j)

    assert_identity(
        determinant(A_i, B_j), L**2 * r_i * r_j, "A-to-B determinant"
    )
    assert_identity(
        determinant(B_i, C_j),
        M**2 + M * v_j - M * u_i - u_i * v_j,
        "B-to-C determinant",
    )
    assert_identity(
        determinant(C_i, A_j), -L * (M + v_i) * r_j,
        "C-to-A determinant",
    )

    x_i, y_i, x_j, y_j, t_x, t_y = symbols(
        "x_i", "y_i", "x_j", "y_j", "t_x", "t_y"
    )
    p_i, p_j, t = (x_i, y_i), (x_j, y_j), (t_x, t_y)
    assert_identity(
        determinant((x_i + t_x, y_i + t_y), (x_j + t_x, y_j + t_y)),
        determinant(p_i, p_j) + determinant(t, p_j) - determinant(t, p_i),
        "translation adds a telescoping potential",
    )

    # Verify both displacement identities coefficient-wise for every
    # permutation through size five.  Gamma's identity includes r=N-v.
    penalty_cases = 0
    for size in range(1, 6):
        rs = symbols(*(f"r{k}" for k in range(size)))
        vs = symbols(*(f"v{k}" for k in range(size)))
        N = Poly.variable("N")
        for permutation in permutations(range(size)):
            alpha_left = sum(r * r for r in rs) - sum(
                rs[i] * rs[permutation[i]] for i in range(size)
            )
            alpha_right = Fraction(1, 2) * sum(
                (rs[i] - rs[permutation[i]]) ** 2 for i in range(size)
            )
            assert_identity(alpha_left, alpha_right, "alpha penalty")

            gamma_left = sum(
                vs[i] * (N - vs[permutation[i]]) for i in range(size)
            ) - sum(vs[i] * (N - vs[i]) for i in range(size))
            gamma_right = Fraction(1, 2) * sum(
                (vs[i] - vs[permutation[i]]) ** 2 for i in range(size)
            )
            assert_identity(gamma_left, gamma_right, "gamma penalty")
            penalty_cases += 1

    # Check the complete alternating-tour formula with generic factor entries
    # for every triple of matchings at size three.  This catches index and
    # composition mistakes that isolated edge checks could miss.
    size = 3
    us = symbols(*(f"U{k}" for k in range(size)))
    vs = symbols(*(f"V{k}" for k in range(size)))
    rs = symbols(*(f"R{k}" for k in range(size)))
    generic_points = {
        "A": [(L * rs[i], 0) for i in range(size)],
        "B": [(M - us[i], L * rs[i]) for i in range(size)],
        "C": [(0, M + vs[i]) for i in range(size)],
    }
    C0 = (
        size * M**2
        + M * (sum(vs) - sum(us))
        - M * L * sum(rs)
        + L**2 * sum(r * r for r in rs)
        - L * sum(vs[i] * rs[i] for i in range(size))
    )
    matching_cases = 0
    for alpha, beta, gamma in product(permutations(range(size)), repeat=3):
        raw = sum(
            determinant(generic_points["A"][i], generic_points["B"][alpha[i]])
            + determinant(generic_points["B"][i], generic_points["C"][beta[i]])
            + determinant(generic_points["C"][i], generic_points["A"][gamma[i]])
            for i in range(size)
        )
        delta_alpha = sum(r * r for r in rs) - sum(
            rs[i] * rs[alpha[i]] for i in range(size)
        )
        delta_gamma = sum(vs[i] * rs[gamma[i]] for i in range(size)) - sum(
            vs[i] * rs[i] for i in range(size)
        )
        objective = sum(us[i] * vs[beta[i]] for i in range(size))
        expected = C0 - L**2 * delta_alpha - L * delta_gamma - objective
        assert_identity(raw, expected, "complete alternating-tour formula")
        matching_cases += 1

    # Verify the scale expansion in (18), first with H independent and then
    # with H=n(n^3+1).  Positivity has the explicit certificate recorded below.
    n, H = symbols("n", "H")
    scale_M = 100 * n * H
    E = 12 * n * scale_M * H + 6 * n * H**2
    gap = scale_M**2 - 2 * E - n**3
    assert_identity(
        gap, (7600 * n**2 - 12 * n) * H**2 - n**3,
        "scale expansion with independent H",
    )
    instantiated_H = n * (n**3 + 1)
    assert_identity(
        (7600 * n**2 - 12 * n) * instantiated_H**2 - n**3,
        n**3 * ((7600 * n - 12) * (n**3 + 1) ** 2 - 1),
        "positive-gap factorization",
    )
    assert_identity(
        6 * n**3 - (n * (n + 1) * (n + 2) + 6 * n - 6),
        (n - 1) * (5 * n**2 + 2 * n - 6),
        "source threshold is at most n cubed",
    )

    result = {
        "audit": "coefficient-wise polynomial identities",
        "penalty_permutations": penalty_cases,
        "matching_triples": matching_cases,
        "positivity_certificate": (
            "gap=n^3*((7600*n-12)*(n^3+1)^2-1)>0 for every integer n>=2"
        ),
        "status": "PASS",
    }
    print(result)
    return result


def perturbation_bound_audit():
    """Check the per-edge anchor perturbation bound at box vertices.

    After dividing coordinates by H, each error at a corner of the deviation
    box is ``a*(M/H)+b``.  A multi-affine function attains both its maximum
    and minimum over a box at vertices, so coefficient bounds at the 144
    anchor-pair/corner cases establish the bound for the entire box.
    """

    # Anchor coordinates are represented as (coefficient of R, constant).
    anchors = (((0, 0), (0, 0)), ((1, 0), (0, 0)), ((0, 0), (1, 0)))

    def affine_add(left, right):
        return left[0] + right[0], left[1] + right[1]

    def affine_sub(left, right):
        return left[0] - right[0], left[1] - right[1]

    def affine_times_integer(value, integer):
        return value[0] * integer, value[1] * integer

    coefficients = []
    for left_anchor, right_anchor in product(anchors, repeat=2):
        for dx, dy, ex, ey in product((-1, 1), repeat=4):
            # det(U, e) + det(d, V) + det(d, e)
            first = affine_sub(
                affine_times_integer(left_anchor[0], ey),
                affine_times_integer(left_anchor[1], ex),
            )
            second = affine_sub(
                affine_times_integer(right_anchor[1], dx),
                affine_times_integer(right_anchor[0], dy),
            )
            third = (0, dx * ey - dy * ex)
            coefficient = affine_add(affine_add(first, second), third)
            assert abs(coefficient[0]) <= 4
            assert abs(coefficient[1]) <= 2
            coefficients.append(coefficient)

    result = {
        "audit": "uniform anchor perturbation error",
        "corner_cases": len(coefficients),
        "maximum_MH_coefficient": max(abs(a) for a, _ in coefficients),
        "maximum_H_squared_coefficient": max(abs(b) for _, b in coefficients),
        "claimed_bound": "4*M*H+2*H^2",
        "status": "PASS",
    }
    print(result)
    return result


# ---------------------------------------------------------------------------
# Three-colour forcing


def balanced_words(size):
    """Yield all words with exactly ``size`` copies of A, B, and C."""

    counts = [size, size, size]
    word = []

    def visit():
        if len(word) == 3 * size:
            yield tuple(word)
            return
        for color in range(3):
            if counts[color]:
                counts[color] -= 1
                word.append(color)
                yield from visit()
                word.pop()
                counts[color] += 1

    yield from visit()


def transition_counts(word):
    counts = [[0] * 3 for _ in range(3)]
    for left, right in zip(word, word[1:] + word[:1]):
        counts[left][right] += 1
    return counts


def is_abc_cycle(word):
    return all(word[(i + 1) % len(word)] == (word[i] + 1) % 3 for i in range(len(word)))


def color_word_audit(n_max):
    checked = 0
    max_nonpattern = {}
    for n in range(1, n_max + 1):
        nonpattern_q = None
        for word in balanced_words(n):
            counts = transition_counts(word)
            q_bc = counts[1][2] - counts[2][1]
            q_ab = counts[0][1] - counts[1][0]
            q_ca = counts[2][0] - counts[0][2]
            assert q_bc == q_ab == q_ca
            assert q_bc <= n
            assert (q_bc == n) == is_abc_cycle(word)
            if not is_abc_cycle(word):
                nonpattern_q = q_bc if nonpattern_q is None else max(nonpattern_q, q_bc)
            checked += 1
        max_nonpattern[n] = nonpattern_q
        if n >= 2:
            assert nonpattern_q == n - 1
    result = {
        "audit": "balanced cyclic colour words",
        "n_max": n_max,
        "words": checked,
        "maximum_nonpattern_q": max_nonpattern,
        "status": "PASS",
    }
    print(result)
    return result


def matching_composition_audit(n_max):
    """Verify the three-layer cycle/composition correspondence exhaustively."""

    cases = 0
    for n in range(1, n_max + 1):
        permutation_list = tuple(permutations(range(n)))
        for alpha, beta, gamma in product(permutation_list, repeat=3):
            full_successor = [None] * (3 * n)
            for i in range(n):
                full_successor[i] = n + alpha[i]
                full_successor[n + i] = 2 * n + beta[i]
                full_successor[2 * n + i] = gamma[i]
            composed = tuple(gamma[beta[alpha[i]]] for i in range(n))
            assert cycle_count(full_successor) == cycle_count(composed)
            assert (cycle_count(full_successor) == 1) == (cycle_count(composed) == 1)
            cases += 1
    result = {
        "audit": "three-matching composition and Hamiltonicity",
        "n_max": n_max,
        "matching_triples": cases,
        "status": "PASS",
    }
    print(result)
    return result


# ---------------------------------------------------------------------------
# Independent source-problem checker


def set_partitions(size):
    """Restricted-growth encodings of all set partitions."""

    if size == 0:
        yield ()
        return
    labels = [0] * size

    def visit(position, largest):
        if position == size:
            yield tuple(labels)
            return
        for label in range(largest + 2):
            labels[position] = label
            yield from visit(position + 1, max(largest, label))

    yield from visit(1, 0)


def partition_cycle(labels):
    successor = [None] * len(labels)
    for label in range(max(labels) + 1):
        block = [i for i, value in enumerate(labels) if value == label]
        for i, j in zip(block, block[1:] + block[:1]):
            successor[i] = j
    return tuple(successor)


def is_connected_block_tree(labels, chosen_edges):
    block_count = max(labels) + 1
    if len(chosen_edges) != block_count - 1:
        return False
    parent = list(range(block_count))

    def find(vertex):
        while parent[vertex] != vertex:
            parent[vertex] = parent[parent[vertex]]
            vertex = parent[vertex]
        return vertex

    for edge in chosen_edges:
        left, right = labels[edge], labels[edge + 1]
        left_root, right_root = find(left), find(right)
        if left_root == right_root:
            return False
        parent[left_root] = right_root
    return len({find(vertex) for vertex in range(block_count)}) == 1


def has_partition_graph_tree(labels):
    needed = max(labels)
    for edge_set in combinations(range(len(labels) - 1), needed):
        used_vertices = set()
        disjoint = True
        for edge in edge_set:
            endpoints = {edge, edge + 1}
            if used_vertices & endpoints:
                disjoint = False
                break
            used_vertices |= endpoints
        if disjoint and is_connected_block_tree(labels, edge_set):
            return True
    return False


def one_cycle_successors(size):
    if size == 1:
        yield (0,)
        return
    for tail in permutations(range(1, size)):
        order = (0,) + tail
        successor = [None] * size
        for left, right in zip(order, order[1:] + order[:1]):
            successor[left] = right
        yield tuple(successor)


def cycle_count(permutation):
    seen = set()
    count = 0
    for start in range(len(permutation)):
        if start in seen:
            continue
        count += 1
        current = start
        while current not in seen:
            seen.add(current)
            current = permutation[current]
    return count


def adjacent_transposition_product(permutation):
    for i, image in enumerate(permutation):
        if image == i:
            continue
        if abs(i - image) != 1 or permutation[image] != i:
            return False
    return True


def source_reduction_audit(partition_n_max, displacement_n_max):
    displacement_cases = 0
    for n in range(1, displacement_n_max + 1):
        for tau in permutations(range(n)):
            d = sum((i - tau[i]) ** 2 for i in range(n)) // 2
            lower = n - cycle_count(tau)
            assert d >= lower
            assert (d == lower) == adjacent_transposition_product(tau)
            displacement_cases += 1

    partitions_checked = 0
    candidate_cycles = 0
    for n in range(1, partition_n_max + 1):
        u = tuple(range(1, n + 1))
        baseline = n * (n + 1) * (n + 2) // 6
        cycles = tuple(one_cycle_successors(n))
        for labels in set_partitions(n):
            sigma = partition_cycle(labels)
            inverse_sigma = [None] * n
            for i, image in enumerate(sigma):
                inverse_sigma[image] = i
            v = [None] * n
            for i in range(n):
                v[sigma[i]] = n - i
            threshold = baseline + max(labels)
            objective_values = []
            for beta in cycles:
                objective = sum(u[i] * v[beta[i]] for i in range(n))
                tau = tuple(inverse_sigma[beta[i]] for i in range(n))
                displacement = sum((i - tau[i]) ** 2 for i in range(n)) // 2
                assert objective == baseline + displacement
                assert n - cycle_count(tau) >= max(labels)
                objective_values.append(objective)
            optimum = min(objective_values)
            assert (optimum <= threshold) == has_partition_graph_tree(labels), (
                n, labels, tuple(v), threshold, optimum
            )
            assert threshold <= n**3
            partitions_checked += 1
            candidate_cycles += len(cycles)

    result = {
        "audit": "independent normalized source reduction",
        "partition_n_max": partition_n_max,
        "partitions": partitions_checked,
        "candidate_cycles": candidate_cycles,
        "displacement_n_max": displacement_n_max,
        "displacement_permutations": displacement_cases,
        "status": "PASS",
    }
    print(result)
    return result


# ---------------------------------------------------------------------------
# Independent raw determinant checker


def numeric_det(left, right):
    return left[0] * right[1] - left[1] * right[0]


def construct_numeric(u, v):
    n = len(u)
    L = n**3 + 1
    H = n * L
    M = 100 * n * H
    r = tuple(n + 1 - value for value in v)
    points = (
        tuple((L * r[i], 0) for i in range(n))
        + tuple((M - u[i], L * r[i]) for i in range(n))
        + tuple((0, M + v[i]) for i in range(n))
    )
    C0 = (
        n * M**2
        + M * (sum(v) - sum(u))
        - M * L * sum(r)
        + L**2 * sum(value**2 for value in r)
        - L * sum(v[i] * r[i] for i in range(n))
    )
    return points, C0, (L, H, M, r)


def tour_value(points, tour):
    return sum(numeric_det(points[i], points[j]) for i, j in zip(tour, tour[1:] + tour[:1]))


def colors_are_abc(tour, n):
    colors = tuple(vertex // n for vertex in tour)
    return is_abc_cycle(colors)


def decode_matchings(tour, n):
    if not colors_are_abc(tour, n):
        return None
    start = next(i for i, vertex in enumerate(tour) if vertex // n == 0)
    order = tour[start:] + tour[:start]
    alpha = [None] * n
    beta = [None] * n
    gamma = [None] * n
    for position in range(0, 3 * n, 3):
        a, b, c = order[position:position + 3]
        next_a = order[(position + 3) % (3 * n)]
        alpha[a] = b - n
        beta[b - n] = c - 2 * n
        gamma[c - 2 * n] = next_a
    return tuple(alpha), tuple(beta), tuple(gamma)


def product_optimum_numeric(u, v):
    return min(
        sum(u[i] * v[successor[i]] for i in range(len(u)))
        for successor in one_cycle_successors(len(u))
    )


def raw_reduction_audit(n_max):
    instances = 0
    tours_checked = 0
    weakest_nonpattern_margin = {}
    for n in range(2, n_max + 1):
        minimum_margin = None
        for u in permutations(range(1, n + 1)):
            for v in permutations(range(1, n + 1)):
                points, C0, scales = construct_numeric(u, v)
                L, H, M, r = scales
                assert H == n * L and M == 100 * n * H
                assert all(1 <= value <= n for value in r)
                assert len(points) == len(set(points))
                translated = tuple((x + 1, y + 1) for x, y in points)
                assert all(x > 0 and y > 0 for x, y in translated)
                source_optimum = product_optimum_numeric(u, v)
                best = None
                best_nonpattern = None
                best_bad_matching = None
                for tail in permutations(range(1, 3 * n)):
                    tour = (0,) + tail
                    value = tour_value(points, tour)
                    best = value if best is None else max(best, value)
                    decoded = decode_matchings(tour, n)
                    if decoded is None:
                        best_nonpattern = value if best_nonpattern is None else max(best_nonpattern, value)
                    else:
                        alpha, _, gamma = decoded
                        identity = tuple(range(n))
                        if alpha != identity or gamma != identity:
                            best_bad_matching = (
                                value if best_bad_matching is None
                                else max(best_bad_matching, value)
                            )
                    tours_checked += 1
                assert best == C0 - source_optimum, (n, u, v, best, C0 - source_optimum)
                # Checking every allowed threshold verifies the decision
                # equivalence, not merely the optimum identity.
                for K in range(n**3 + 1):
                    assert (best >= C0 - K) == (source_optimum <= K)
                if best_nonpattern is not None:
                    assert best_nonpattern < C0 - n**3
                    margin = C0 - n**3 - best_nonpattern
                    minimum_margin = margin if minimum_margin is None else min(minimum_margin, margin)
                if best_bad_matching is not None:
                    assert best_bad_matching < C0 - n**3
                instances += 1
        weakest_nonpattern_margin[n] = minimum_margin
    result = {
        "audit": "independent raw determinant tours",
        "n_max": n_max,
        "instances": instances,
        "tours": tours_checked,
        "minimum_nonpattern_margin_below_C0_minus_n_cubed": weakest_nonpattern_margin,
        "status": "PASS",
    }
    print(result)
    return result


def held_karp_maximum(points):
    """Independent exact maximum Hamiltonian-cycle dynamic program."""

    size = len(points)
    weights = [[numeric_det(points[i], points[j]) for j in range(size)] for i in range(size)]
    states = {(1, 0): 0}
    for mask_size in range(1, size):
        next_states = {}
        for (mask, last), value in states.items():
            if mask.bit_count() != mask_size:
                continue
            for vertex in range(1, size):
                bit = 1 << vertex
                if mask & bit:
                    continue
                key = (mask | bit, vertex)
                candidate = value + weights[last][vertex]
                if key not in next_states or candidate > next_states[key]:
                    next_states[key] = candidate
        # All current states have the same cardinality; only the next layer is
        # needed.  This is also an implementation independent of area_tour.py.
        states = next_states
    full_mask = (1 << size) - 1
    return max(value + weights[last][0] for (mask, last), value in states.items() if mask == full_mask)


def canonical_dynamic_program_audit(n_max):
    instances = 0
    for n in range(2, n_max + 1):
        u = tuple(range(1, n + 1))
        for v in permutations(range(1, n + 1)):
            points, C0, _ = construct_numeric(u, v)
            actual = held_karp_maximum(points)
            predicted = C0 - product_optimum_numeric(u, v)
            assert actual == predicted, (n, v, actual, predicted)
            instances += 1
    result = {
        "audit": "independent Held-Karp, canonical factor pairs",
        "n_max": n_max,
        "instances": instances,
        "status": "PASS",
    }
    print(result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="run the slower exhaustive bounds")
    parser.add_argument("--color-max", type=int)
    parser.add_argument("--partition-max", type=int)
    parser.add_argument("--displacement-max", type=int)
    parser.add_argument("--raw-max", type=int)
    parser.add_argument("--dp-max", type=int)
    parser.add_argument("--composition-max", type=int)
    args = parser.parse_args()

    color_max = args.color_max or (5 if args.full else 4)
    partition_max = args.partition_max or (7 if args.full else 6)
    displacement_max = args.displacement_max or (9 if args.full else 8)
    raw_max = args.raw_max or 3
    dp_max = args.dp_max or (5 if args.full else 4)
    composition_max = args.composition_max or (5 if args.full else 4)

    polynomial_identity_audit()
    perturbation_bound_audit()
    color_word_audit(color_max)
    matching_composition_audit(composition_max)
    source_reduction_audit(partition_max, displacement_max)
    raw_reduction_audit(raw_max)
    canonical_dynamic_program_audit(dp_max)


if __name__ == "__main__":
    main()
