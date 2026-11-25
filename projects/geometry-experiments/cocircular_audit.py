#!/usr/bin/env python3
"""Exact checks for the cocircular results stated in proof.tex.

All computations in this file use fractions or integers.  The script is a
finite audit of the examples and of the fixed-descent dynamic program; the
general statements still require their written proofs.
"""

from __future__ import annotations

from fractions import Fraction
from functools import cmp_to_key
from itertools import combinations, permutations
from math import prod


F = Fraction
Point = tuple[Fraction, Fraction]


def circle_point(t: Fraction) -> Point:
    denominator = 1 + t * t
    return ((1 - t * t) / denominator, 2 * t / denominator)


def tangent_circle_point(t: Fraction) -> Point:
    """A rational parametrization of the circle through the origin."""

    denominator = 1 + t * t
    return (1 / denominator, t / denominator)


def det(a: Point, b: Point) -> Fraction:
    return a[0] * b[1] - a[1] * b[0]


def rotate_quarter(a: Point) -> Point:
    return (-a[1], a[0])


def squared_distance(a: Point, b: Point) -> Fraction:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def orientation(a: Point, b: Point, c: Point) -> Fraction:
    return det((b[0] - a[0], b[1] - a[1]), (c[0] - a[0], c[1] - a[1]))


def is_locally_counterclockwise(
    points: tuple[Point, ...], order: tuple[int, ...]
) -> bool:
    n = len(order)
    return all(
        orientation(
            points[order[i]],
            points[order[(i + 1) % n]],
            points[order[(i + 2) % n]],
        )
        > 0
        for i in range(n)
    )


def order_weight(points: tuple[Point, ...], order: tuple[int, ...]) -> Fraction:
    return sum(
        det(points[order[i]], points[order[(i + 1) % len(order)]])
        for i in range(len(order))
    )


def successor_weight(points: tuple[Point, ...], successor: tuple[int, ...]) -> Fraction:
    return sum(det(points[i], points[successor[i]]) for i in range(len(points)))


def parabolic_weight(parameters: tuple[int, ...], order: tuple[int, ...]) -> int:
    """Twice the signed area for the points (x,x^2)."""

    return sum(
        parameters[order[i]]
        * parameters[order[(i + 1) % len(order)]]
        * (parameters[order[(i + 1) % len(order)]] - parameters[order[i]])
        for i in range(len(order))
    )


def successor_cycles(successor: tuple[int, ...]) -> tuple[tuple[int, ...], ...]:
    seen: set[int] = set()
    cycles: list[tuple[int, ...]] = []
    for start in range(len(successor)):
        if start in seen:
            continue
        cycle: list[int] = []
        vertex = start
        while vertex not in seen:
            seen.add(vertex)
            cycle.append(vertex)
            vertex = successor[vertex]
        cycles.append(tuple(cycle))
    return tuple(cycles)


def all_rooted_tours(n: int):
    for tail in permutations(range(1, n)):
        yield (0,) + tail


def descents(order: tuple[int, ...]) -> int:
    return sum(order[i] > order[(i + 1) % len(order)] for i in range(len(order)))


def successor_wraps(successor: tuple[int, ...]) -> int:
    return sum(successor[i] < i for i in range(len(successor)))


def fixed_descent_dp(points: tuple[Point, ...], k: int) -> Fraction | None:
    """Maximum tour weight with exactly k descents in the given point order.

    A state is ``(last_1, first_2, last_2, ..., first_k, last_k)``.  The first
    increasing path starts at vertex 0.  A pair ``(-1, -1)`` denotes an empty
    path.  The processed prefix endpoint is the largest current last vertex.
    """

    n = len(points)
    if not 1 <= k < n:
        return None

    initial = (0,) + (-1, -1) * (k - 1)
    table: dict[tuple[int, ...], Fraction] = {initial: F(0)}

    for vertex in range(1, n):
        next_table: dict[tuple[int, ...], Fraction] = {}
        for state, value in table.items():
            # Append to P_1.
            previous = state[0]
            new_state = (vertex,) + state[1:]
            candidate = value + det(points[previous], points[vertex])
            if candidate > next_table.get(new_state, candidate - 1):
                next_table[new_state] = candidate

            # Start or append to P_2,...,P_k.
            for path in range(1, k):
                offset = 1 + 2 * (path - 1)
                first, last = state[offset], state[offset + 1]
                data = list(state)
                if first == -1:
                    data[offset] = data[offset + 1] = vertex
                    candidate = value
                else:
                    data[offset + 1] = vertex
                    candidate = value + det(points[last], points[vertex])
                new_state = tuple(data)
                if candidate > next_table.get(new_state, candidate - 1):
                    next_table[new_state] = candidate
        table = next_table

    optimum: Fraction | None = None
    for state, internal_weight in table.items():
        endpoints = [(0, state[0])]
        valid = True
        for path in range(1, k):
            offset = 1 + 2 * (path - 1)
            first, last = state[offset], state[offset + 1]
            if first == -1:
                valid = False
                break
            endpoints.append((first, last))
        if not valid:
            continue

        connector_weight = F(0)
        for path in range(k - 1):
            last = endpoints[path][1]
            next_first = endpoints[path + 1][0]
            if last <= next_first:
                valid = False
                break
            connector_weight += det(points[last], points[next_first])
        if not valid or endpoints[-1][1] <= 0:
            continue
        connector_weight += det(points[endpoints[-1][1]], points[0])
        candidate = internal_weight + connector_weight
        if optimum is None or candidate > optimum:
            optimum = candidate
    return optimum


def check_rational_parametrization() -> None:
    parameters = tuple(F(i, 3) for i in range(-7, 8))
    points = tuple(circle_point(t) for t in parameters)
    for t, point in zip(parameters, points):
        assert point[0] * point[0] + point[1] * point[1] == 1
    for i, s in enumerate(parameters):
        for j, t in enumerate(parameters):
            expected = 2 * (t - s) * (1 + s * t) / (
                (1 + s * s) * (1 + t * t)
            )
            assert det(points[i], points[j]) == expected


def check_matching_identity_and_quadrangle_failure() -> None:
    parameters = (F(-2), F(-1), F(-1, 2))
    points = tuple(circle_point(t) for t in parameters)
    rotated = tuple(rotate_quarter(point) for point in points)

    for i, point in enumerate(points):
        for j, target in enumerate(points):
            assert det(point, target) == 1 - squared_distance(rotated[i], target) / 2

    for order in all_rooted_tours(len(points)):
        successor = [0] * len(points)
        for i, vertex in enumerate(order):
            successor[vertex] = order[(i + 1) % len(order)]
        fixed = sum(squared_distance(points[i], rotated[i]) for i in range(len(points)))
        variable = sum(
            squared_distance(rotated[i], points[successor[i]])
            for i in range(len(points))
        )
        assert fixed + variable == 4 * len(points) - 2 * order_weight(points, order)

    left = squared_distance(points[0], rotated[1]) + squared_distance(
        points[2], rotated[0]
    )
    right = squared_distance(points[0], rotated[0]) + squared_distance(
        points[2], rotated[1]
    )
    assert left == F(82, 25)
    assert right == F(14, 5)
    assert left > right


def check_crossing_beats_boundary() -> None:
    integer_points = (
        (-4, -3),
        (-3, -4),
        (4, -3),
        (5, 0),
        (0, 5),
        (-3, 4),
    )
    points = tuple((F(x), F(y)) for x, y in integer_points)
    assert all(x * x + y * y == 25 for x, y in points)
    boundary = (0, 1, 2, 3, 4, 5)
    crossing = (0, 2, 4, 1, 3, 5)
    assert order_weight(points, boundary) == 112
    assert order_weight(points, crossing) == 124
    optimum = max(order_weight(points, order) for order in all_rooted_tours(6))
    assert optimum == 124


def check_negative_edge_is_necessary() -> None:
    parameters = (F(-3), F(-2), F(-1), F(-1, 3), F(3, 2), F(2))
    points = tuple(circle_point(t) for t in parameters)
    optimum = None
    best_nonnegative = None
    optimum_orders: list[tuple[int, ...]] = []
    for order in all_rooted_tours(6):
        edge_weights = tuple(
            det(points[order[i]], points[order[(i + 1) % 6]]) for i in range(6)
        )
        weight = sum(edge_weights)
        if optimum is None or weight > optimum:
            optimum = weight
            optimum_orders = [order]
        elif weight == optimum:
            optimum_orders.append(order)
        if all(weight >= 0 for weight in edge_weights):
            if best_nonnegative is None or sum(edge_weights) > best_nonnegative:
                best_nonnegative = sum(edge_weights)
    assert optimum == F(1182, 325)
    assert optimum_orders == [(0, 2, 5, 1, 3, 4)]
    assert best_nonnegative == F(1116, 325)
    assert any(
        det(points[optimum_orders[0][i]], points[optimum_orders[0][(i + 1) % 6]])
        < 0
        for i in range(6)
    )


def check_assignment_patching_failure() -> None:
    parameters = (F(-3), F(-2), F(-2, 3), F(0), F(1), F(2))
    points = tuple(circle_point(t) for t in parameters)
    n = len(points)

    assignments: list[tuple[Fraction, tuple[int, ...]]] = []
    for successor in permutations(range(n)):
        assignments.append((successor_weight(points, successor), successor))
    assignment_value = max(value for value, _ in assignments)
    assignment_optimizers = [s for value, s in assignments if value == assignment_value]
    assignment = (2, 3, 4, 5, 0, 1)
    assert assignment_value == F(1532, 325)
    assert assignment_optimizers == [assignment]
    assert successor_cycles(assignment) == ((0, 2, 4), (1, 3, 5))

    first_cycle, second_cycle = successor_cycles(assignment)
    merged_values = []
    for a in first_cycle:
        for b in second_cycle:
            merged = list(assignment)
            merged[a], merged[b] = merged[b], merged[a]
            merged = tuple(merged)
            assert len(successor_cycles(merged)) == 1
            merged_values.append(successor_weight(points, merged))
    assert max(merged_values) == F(296, 65)

    tour_values = [(order_weight(points, order), order) for order in all_rooted_tours(n)]
    optimum = max(value for value, _ in tour_values)
    optimizers = [order for value, order in tour_values if value == optimum]
    assert optimum == F(1516, 325)
    assert optimizers == [(0, 1, 2, 3, 4, 5)]
    assert optimum > max(merged_values)


def check_assignment_is_not_always_a_shift() -> None:
    parameters = tuple(map(F, (-5, -4, -3, -2, -1, 2, 3)))
    points = tuple(circle_point(t) for t in parameters)
    n = len(points)
    assignments = [
        (successor_weight(points, successor), successor)
        for successor in permutations(range(n))
    ]
    optimum = max(value for value, _ in assignments)
    optimizers = [successor for value, successor in assignments if value == optimum]
    claimed = (2, 3, 4, 6, 5, 0, 1)
    assert optimum == F(1928, 1105)
    assert optimizers == [claimed]
    assert successor_cycles(claimed) == ((0, 2, 4, 5), (1, 3, 6))

    shifts = tuple(
        tuple((i + step) % n for i in range(n)) for step in range(n)
    )
    best_shift = max(successor_weight(points, successor) for successor in shifts)
    assert best_shift == F(9224, 5525)
    assert optimum - best_shift == F(32, 425)

    # A compact exact dual certificate for uniqueness.  Every A_i+B_j
    # dominates c_ij.  Equality edges have only the claimed perfect matching.
    dual_rows = (
        F(-3112, 5525),
        F(-279, 425),
        F(-4, 5),
        F(-1),
        F(-16, 25),
        F(151, 425),
        F(1368, 5525),
    )
    dual_columns = (
        F(3392, 5525),
        F(3637, 5525),
        F(344, 425),
        F(27, 25),
        F(8, 5),
        F(1, 25),
        F(0),
    )
    equality_edges = []
    for i in range(n):
        row = []
        for j in range(n):
            slack = dual_rows[i] + dual_columns[j] - det(points[i], points[j])
            assert slack >= 0
            if slack == 0:
                row.append(j)
        equality_edges.append(tuple(row))
    assert sum(dual_rows) + sum(dual_columns) == optimum
    assert equality_edges == [
        (1, 2),
        (2, 3),
        (3, 4),
        (4, 5, 6),
        (5,),
        (0,),
        (0, 1),
    ]


def check_cut_path_obstruction() -> None:
    parameters = tuple(map(F, (-4, -3, 1, 2, 3)))
    points = tuple(tangent_circle_point(t) for t in parameters)
    origin = (F(0), F(0))
    assert all((x - F(1, 2)) ** 2 + y * y == F(1, 4) for x, y in points)

    def path_weight(order: tuple[int, ...]) -> Fraction:
        return sum(
            det(points[order[i]], points[order[i + 1]])
            for i in range(len(order) - 1)
        )

    def turns(order: tuple[int, ...]) -> int:
        signs = tuple(
            1 if order[i] < order[i + 1] else -1
            for i in range(len(order) - 1)
        )
        return sum(signs[i] != signs[i + 1] for i in range(len(signs) - 1))

    def interval_prefixes(order: tuple[int, ...]) -> bool:
        for size in range(1, len(order) + 1):
            prefix = order[:size]
            if max(prefix) - min(prefix) + 1 != size:
                return False
        return True

    paths = tuple(permutations(range(len(points))))
    values = tuple((path_weight(order), order) for order in paths)
    optimum = max(value for value, _ in values)
    optimizers = tuple(order for value, order in values if value == optimum)
    assert optimum == F(28, 85)
    assert optimizers == ((1, 2, 4, 0, 3),)

    restricted_families = (
        lambda order: turns(order) <= 1,
        lambda order: order[0] in (0, 4) or order[-1] in (0, 4),
        interval_prefixes,
    )
    for predicate in restricted_families:
        restricted = max(path_weight(order) for order in paths if predicate(order))
        assert restricted == F(277, 850)
        assert optimum - restricted == F(3, 850)

    # Adding the origin closes every path without changing its weight.
    closed = (5,) + optimizers[0]
    all_points = points + (origin,)
    assert order_weight(all_points, closed) == optimum

    def cost(i: int, j: int) -> Fraction:
        s, t = parameters[i], parameters[j]
        return (t - s) / ((1 + s * s) * (1 + t * t))

    first_minor = cost(0, 2) + cost(1, 3) - cost(0, 3) - cost(1, 2)
    second_minor = cost(0, 3) + cost(2, 4) - cost(0, 4) - cost(2, 3)
    assert first_minor == F(-2, 85)
    assert second_minor == F(1, 34)


def check_no_monge_or_demidenko_order() -> None:
    # Three noncollinear points already prevent independent row and column
    # permutations from making a determinant matrix Monge or anti-Monge.
    points3 = tuple(circle_point(t) for t in (F(-1), F(0), F(1)))
    matrix3 = tuple(tuple(det(a, b) for b in points3) for a in points3)

    def is_monge(
        matrix: tuple[tuple[Fraction, ...], ...],
        row_order: tuple[int, ...],
        column_order: tuple[int, ...],
        sign: int,
    ) -> bool:
        n = len(matrix)
        for i in range(n):
            for k in range(i + 1, n):
                for j in range(n):
                    for ell in range(j + 1, n):
                        cross = (
                            matrix[row_order[i]][column_order[j]]
                            + matrix[row_order[k]][column_order[ell]]
                            - matrix[row_order[i]][column_order[ell]]
                            - matrix[row_order[k]][column_order[j]]
                        )
                        if sign * cross > 0:
                            return False
        return True

    orders3 = tuple(permutations(range(3)))
    assert not any(
        is_monge(matrix3, rows, columns, sign)
        for rows in orders3
        for columns in orders3
        for sign in (-1, 1)
    )

    # For five points, no simultaneous city order satisfies the asymmetric
    # Demidenko inequalities, for either sign of the objective.
    points5 = tuple(circle_point(F(t)) for t in (-2, -1, 0, 1, 2))
    original = tuple(tuple(det(a, b) for b in points5) for a in points5)

    def is_demidenko(matrix: tuple[tuple[Fraction, ...], ...]) -> bool:
        n = len(matrix)
        for j in range(1, n - 2):
            jp = j + 1
            for i in range(j):
                for ell in range(j + 2, n):
                    if (
                        matrix[i][j] + matrix[j][jp] + matrix[jp][ell]
                        > matrix[i][jp] + matrix[jp][j] + matrix[j][ell]
                    ):
                        return False
                    if (
                        matrix[j][i] + matrix[jp][j] + matrix[ell][jp]
                        > matrix[jp][i] + matrix[j][jp] + matrix[ell][j]
                    ):
                        return False
                    if matrix[i][j] + matrix[ell][jp] > matrix[i][jp] + matrix[ell][j]:
                        return False
                    if matrix[j][i] + matrix[jp][ell] > matrix[jp][i] + matrix[j][ell]:
                        return False
        return True

    for sign in (-1, 1):
        for order in permutations(range(5)):
            reordered = tuple(
                tuple(sign * original[order[i]][order[j]] for j in range(5))
                for i in range(5)
            )
            assert not is_demidenko(reordered)


def exact_scaled_assignment(
    numerators: tuple[int, ...], denominator: int
) -> tuple[tuple[int, ...], tuple[tuple[int, ...], ...]]:
    """Return an exact optimum and its equality graph for rational q(t)."""

    n = len(numerators)
    squares = tuple(denominator * denominator + x * x for x in numerators)
    scale = prod(squares)
    weights = tuple(
        tuple(
            2
            * denominator
            * (numerators[j] - numerators[i])
            * (denominator * denominator + numerators[i] * numerators[j])
            * (scale // squares[i] // squares[j])
            for j in range(n)
        )
        for i in range(n)
    )

    largest = max(abs(value) for row in weights for value in row)
    infinity = 1 << (largest.bit_length() + 10)
    row_potential = [0] * (n + 1)
    column_potential = [0] * (n + 1)
    matched_row = [0] * (n + 1)
    predecessor = [0] * (n + 1)
    for row in range(1, n + 1):
        matched_row[0] = row
        column = 0
        minimum = [infinity] * (n + 1)
        used = [False] * (n + 1)
        while True:
            used[column] = True
            active_row = matched_row[column]
            delta = infinity
            next_column = 0
            for candidate in range(1, n + 1):
                if used[candidate]:
                    continue
                reduced = (
                    -weights[active_row - 1][candidate - 1]
                    - row_potential[active_row]
                    - column_potential[candidate]
                )
                if reduced < minimum[candidate]:
                    minimum[candidate] = reduced
                    predecessor[candidate] = column
                if minimum[candidate] < delta:
                    delta = minimum[candidate]
                    next_column = candidate
            for candidate in range(n + 1):
                if used[candidate]:
                    row_potential[matched_row[candidate]] += delta
                    column_potential[candidate] -= delta
                else:
                    minimum[candidate] -= delta
            column = next_column
            if matched_row[column] == 0:
                break
        while True:
            previous = predecessor[column]
            matched_row[column] = matched_row[previous]
            column = previous
            if column == 0:
                break

    successor = [0] * n
    for column in range(1, n + 1):
        successor[matched_row[column] - 1] = column - 1
    dual_rows = tuple(-value for value in row_potential[1:])
    dual_columns = tuple(-value for value in column_potential[1:])
    equality = tuple(
        tuple(
            j
            for j in range(n)
            if dual_rows[i] + dual_columns[j] == weights[i][j]
        )
        for i in range(n)
    )
    assert all(
        dual_rows[i] + dual_columns[j] >= weights[i][j]
        for i in range(n)
        for j in range(n)
    )
    assert sum(weights[i][successor[i]] for i in range(n)) == (
        sum(dual_rows) + sum(dual_columns)
    )

    counts = {0: 1}
    for row in range(n):
        next_counts: dict[int, int] = {}
        for mask, count in counts.items():
            for column in equality[row]:
                if mask & (1 << column):
                    continue
                new_mask = mask | (1 << column)
                next_counts[new_mask] = min(2, next_counts.get(new_mask, 0) + count)
        counts = next_counts
    assert counts[(1 << n) - 1] == 1
    return tuple(successor), equality


def check_assignment_patch_graph_can_be_complex() -> None:
    numerators = (
        -87,
        -59,
        -10,
        -9,
        -1,
        1,
        5,
        9,
        15,
        17,
        19,
        22,
        34,
        38,
        39,
        56,
        57,
        58,
        70,
        87,
    )
    successor, _ = exact_scaled_assignment(numerators, 50)
    assert successor == (
        3,
        4,
        7,
        8,
        9,
        10,
        11,
        12,
        13,
        14,
        15,
        16,
        17,
        18,
        19,
        6,
        5,
        2,
        0,
        1,
    )
    cycles = successor_cycles(successor)
    assert cycles == (
        (0, 3, 8, 13, 18),
        (1, 4, 9, 14, 19),
        (2, 7, 12, 17),
        (5, 10, 15, 6, 11, 16),
    )
    component = {vertex: index for index, cycle in enumerate(cycles) for vertex in cycle}
    patch_edges = {
        tuple(sorted((component[i], component[i + 1])))
        for i in range(len(successor) - 1)
        if component[i] != component[i + 1]
    }
    assert patch_edges == {(0, 1), (0, 2), (1, 2), (1, 3), (2, 3)}
    degrees = tuple(
        sum(vertex in edge for edge in patch_edges) for vertex in range(len(cycles))
    )
    assert degrees == (2, 3, 3, 2)
    # This is K_4 minus one edge.  Its two triangles share an edge, so it is
    # not even a cactus, and in particular is no path, cycle, star, or tree.


def check_fixed_wrap_assignment_patching_failure() -> None:
    parameters = tuple(map(F, (-5, -2, -1, 0, 1, 3)))
    points = tuple(circle_point(t) for t in parameters)
    n = len(points)
    candidates = [
        (successor_weight(points, successor), successor)
        for successor in permutations(range(n))
        if successor_wraps(successor) == 2
    ]
    optimum = max(value for value, _ in candidates)
    optimizers = [successor for value, successor in candidates if value == optimum]
    assignment = (2, 3, 4, 5, 0, 1)
    assert optimum == F(276, 65)
    assert optimizers == [assignment]
    first, second = successor_cycles(assignment)
    assert (first, second) == ((0, 2, 4), (1, 3, 5))

    one_swap = []
    for a in first:
        for b in second:
            merged = list(assignment)
            merged[a], merged[b] = merged[b], merged[a]
            merged = tuple(merged)
            assert len(successor_cycles(merged)) == 1
            if successor_wraps(merged) == 2:
                one_swap.append(successor_weight(points, merged))
    assert max(one_swap) == F(50, 13)

    tours = [
        (value, successor)
        for value, successor in candidates
        if len(successor_cycles(successor)) == 1
    ]
    best_tour = max(tours)
    assert best_tour == (F(274, 65), (2, 0, 3, 4, 5, 1))
    assert best_tour[0] - max(one_swap) == F(24, 65)


def check_wrap_values_are_not_concave() -> None:
    parameters = tuple(map(F, (-15, -12, -9, -8, 15, 17)))
    points = tuple(circle_point(t) for t in parameters)
    best: dict[int, Fraction] = {}
    for successor in permutations(range(len(points))):
        k = successor_wraps(successor)
        value = successor_weight(points, successor)
        best[k] = max(best.get(k, value), value)
    concavity_slack = 2 * best[3] - best[2] - best[4]
    assert concavity_slack == -F(3118202, 4934260825)


def angular_order(points: tuple[Point, ...]) -> tuple[int, ...]:
    def half(point: Point) -> int:
        x, y = point
        return 0 if y > 0 or (y == 0 and x >= 0) else 1

    def compare(i: int, j: int) -> int:
        if half(points[i]) != half(points[j]):
            return -1 if half(points[i]) < half(points[j]) else 1
        cross = det(points[i], points[j])
        if cross:
            return -1 if cross > 0 else 1
        assert points[i] == points[j]
        return 0

    return tuple(sorted(range(len(points)), key=cmp_to_key(compare)))


def five_point_star(order: tuple[int, ...]):
    position = {vertex: index for index, vertex in enumerate(order)}
    for subset in combinations(range(len(order)), 5):
        first = subset[0]
        encountered = tuple(
            sorted(subset, key=lambda x: (position[x] - position[first]) % len(order))
        )
        star_one = (subset[0], subset[2], subset[4], subset[1], subset[3])
        star_two = (subset[0], subset[3], subset[1], subset[4], subset[2])
        if encountered in (star_one, star_two):
            return subset, encountered
    return None


def check_fixed_matching_optimum_need_not_be_g_pyramidal() -> None:
    parameters = tuple(map(F, (-4, -3, -2, -1, 1)))
    blue = tuple(circle_point(t) for t in parameters)
    red = tuple(rotate_quarter(point) for point in blue)
    vertices = blue + red
    assert len(set(vertices)) == 10

    values = [(order_weight(blue, order), order) for order in all_rooted_tours(5)]
    optimum = max(value for value, _ in values)
    optimizers = [order for value, order in values if value == optimum]
    assert optimum == F(814, 425)
    assert optimizers == [(0, 1, 2, 3, 4)]
    assert max(value for value, _ in values if value < optimum) == F(776, 425)

    boundary = angular_order(vertices)
    assert boundary == (8, 4, 9, 0, 1, 2, 3, 5, 6, 7)
    rank = {vertex: index for index, vertex in enumerate(boundary)}
    alternating = tuple(
        rank[vertex]
        for i in optimizers[0]
        for vertex in (i, 5 + i)
    )
    assert alternating == (3, 7, 4, 8, 5, 9, 6, 0, 1, 2)
    assert five_point_star(alternating) == (
        (0, 4, 5, 7, 8),
        (0, 7, 4, 8, 5),
    )


def check_fixed_descent_dp() -> None:
    parameter_sets = (
        (F(-3), F(-2), F(-1), F(0), F(1)),
        (F(-3), F(-2), F(-2, 3), F(0), F(1), F(2)),
        (F(-5, 2), F(-4, 3), F(-1, 2), F(1, 5), F(4, 5), F(7, 4), F(3)),
    )
    for parameters in parameter_sets:
        points = tuple(circle_point(t) for t in parameters)
        brute: dict[int, Fraction] = {}
        tour_values: list[tuple[Fraction, tuple[int, ...]]] = []
        for order in all_rooted_tours(len(points)):
            k = descents(order)
            weight = order_weight(points, order)
            tour_values.append((weight, order))
            brute[k] = max(brute.get(k, weight), weight)
        for k in range(1, len(points)):
            assert fixed_descent_dp(points, k) == brute.get(k)
        optimum = max(weight for weight, _ in tour_values)
        assert all(
            is_locally_counterclockwise(points, order)
            for weight, order in tour_values
            if weight == optimum
        )


def parabolic_turns(order: tuple[int, ...]) -> tuple[tuple[int, ...], tuple[int, ...]]:
    valleys: list[int] = []
    peaks: list[int] = []
    for i, value in enumerate(order):
        previous = order[i - 1]
        following = order[(i + 1) % len(order)]
        if previous > value < following:
            valleys.append(value)
        if previous < value > following:
            peaks.append(value)
    return tuple(valleys), tuple(peaks)


def parabolic_circulation_weight(
    parameters: tuple[int, ...], order: tuple[int, ...]
) -> int:
    gaps = tuple(parameters[i + 1] - parameters[i] for i in range(len(parameters) - 1))
    edges = tuple(zip(order, order[1:] + order[:1]))
    answer = 0
    for a in range(len(gaps)):
        for b in range(a + 1, len(gaps)):
            q = sum(i > b and j <= a for i, j in edges)
            q -= sum(i <= a and j > b for i, j in edges)
            coefficient = gaps[a] * gaps[b] * (
                parameters[b]
                + parameters[b + 1]
                - parameters[a]
                - parameters[a + 1]
            )
            answer += coefficient * q
    return answer


def check_parabolic_structure() -> None:
    parameter_sets = (
        (-4, -3, -1, 2, 8),
        (-8, -5, -4, 1, 3, 9),
        (-13, -10, -6, 5, 10, 13, 14),
    )
    for parameters in parameter_sets:
        weighted_orders = []
        for order in all_rooted_tours(len(parameters)):
            weight = parabolic_weight(parameters, order)
            assert weight == parabolic_circulation_weight(parameters, order)
            weighted_orders.append((weight, order))
        optimum = max(weight for weight, _ in weighted_orders)
        for weight, order in weighted_orders:
            if weight != optimum:
                continue
            points = tuple((F(x), F(x * x)) for x in parameters)
            assert is_locally_counterclockwise(points, order)
            valleys, peaks = parabolic_turns(order)
            assert valleys and peaks and max(valleys) < min(peaks)

    # A direct finite audit of the exchange used in the separation proof.
    parameters = tuple(range(8))
    points = tuple((F(x), F(x * x)) for x in parameters)
    for order in all_rooted_tours(len(parameters)):
        if not is_locally_counterclockwise(points, order):
            continue
        valleys, peaks = parabolic_turns(order)
        valley = max(valleys)
        peak = min(peaks)
        if valley <= peak:
            continue
        swapped = list(order)
        i, j = swapped.index(valley), swapped.index(peak)
        swapped[i], swapped[j] = swapped[j], swapped[i]
        assert parabolic_weight(parameters, tuple(swapped)) > parabolic_weight(parameters, order)

    # The best Hamiltonian tour need not be a one-swap patch of the best assignment.
    parameters = (-6, -4, -1, 2, 3, 4, 10)
    assignments = []
    for successor in permutations(range(len(parameters))):
        value = sum(
            parameters[i]
            * parameters[successor[i]]
            * (parameters[successor[i]] - parameters[i])
            for i in range(len(parameters))
        )
        assignments.append((value, successor))
    assignment_value = max(value for value, _ in assignments)
    assignment_optimizers = [s for value, s in assignments if value == assignment_value]
    assignment = (2, 3, 4, 5, 6, 1, 0)
    assert assignment_value == 1284
    assert assignment_optimizers == [assignment]
    assert successor_cycles(assignment) == ((0, 2, 4, 6), (1, 3, 5))

    tour_values = [
        (parabolic_weight(parameters, order), order)
        for order in all_rooted_tours(len(parameters))
    ]
    tour_optimum = max(value for value, _ in tour_values)
    tour_optimizers = [order for value, order in tour_values if value == tour_optimum]
    assert tour_optimum == 1272
    assert tour_optimizers == [tuple(range(len(parameters)))]

    first_cycle, second_cycle = successor_cycles(assignment)
    patched_values = []
    for i in first_cycle:
        for j in second_cycle:
            merged = list(assignment)
            merged[i], merged[j] = merged[j], merged[i]
            merged_value = next(value for value, s in assignments if s == tuple(merged))
            patched_values.append(merged_value)
            assert len(successor_cycles(tuple(merged))) == 1
    assert max(patched_values) == 1270 < tour_optimum


def main() -> None:
    check_rational_parametrization()
    check_matching_identity_and_quadrangle_failure()
    check_crossing_beats_boundary()
    check_negative_edge_is_necessary()
    check_assignment_patching_failure()
    check_assignment_is_not_always_a_shift()
    check_cut_path_obstruction()
    check_no_monge_or_demidenko_order()
    check_assignment_patch_graph_can_be_complex()
    check_fixed_wrap_assignment_patching_failure()
    check_wrap_values_are_not_concave()
    check_fixed_matching_optimum_need_not_be_g_pyramidal()
    check_fixed_descent_dp()
    check_parabolic_structure()
    print("PASS: exact cocircular parametrization and examples")
    print("PASS: assignment, path-DP, Monge, patching, and g-pyramidal obstructions")
    print("PASS: fixed-descent dynamic program matches exhaustive tours through n=7")
    print("PASS: exact parabolic circulation, separation, and patch obstruction")


if __name__ == "__main__":
    main()
