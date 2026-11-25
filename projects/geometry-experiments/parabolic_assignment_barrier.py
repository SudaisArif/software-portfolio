#!/usr/bin/env python3
"""Exact audit of the parabolic assignment-patching barrier.

For K(x,y)=x*y*(y-x), the script checks the structural claims used to
exclude a direct Sarvanov/assignment-patching reduction on a narrow arc:

* every maximum assignment has no cycles of length one or two;
* its excedance images increase and its deficiency images decrease;
* every nontrivial cycle maps its maximum element to its minimum element;
* the hull intervals of its cycles form one inclusion chain; and
* alternating left/right boundary edges give a vertex-disjoint tree that
  patches those cycles.

The enumeration is exact.  It is a falsification audit, not a replacement
for the unbounded proofs in the accompanying note.
"""

from __future__ import annotations

import argparse
from itertools import permutations
from random import Random


def kernel(x: int, y: int) -> int:
    return x * y * (y - x)


def assignment_weight(parameters: tuple[int, ...], successor: tuple[int, ...]) -> int:
    return sum(kernel(parameters[i], parameters[successor[i]]) for i in range(len(parameters)))


def cycles(successor: tuple[int, ...]) -> tuple[tuple[int, ...], ...]:
    unseen = set(range(len(successor)))
    answer: list[tuple[int, ...]] = []
    while unseen:
        first = min(unseen)
        cycle: list[int] = []
        current = first
        while current in unseen:
            unseen.remove(current)
            cycle.append(current)
            current = successor[current]
        assert current == first
        answer.append(tuple(cycle))
    return tuple(answer)


def structural_checks(successor: tuple[int, ...]) -> None:
    components = cycles(successor)
    assert all(len(component) >= 3 for component in components)

    excedances = [i for i, image in enumerate(successor) if image > i]
    deficiencies = [i for i, image in enumerate(successor) if image < i]
    assert all(successor[i] < successor[j] for i, j in zip(excedances, excedances[1:]))
    assert all(successor[i] > successor[j] for i, j in zip(deficiencies, deficiencies[1:]))

    intervals = []
    for component in components:
        left, right = min(component), max(component)
        assert successor[right] == left
        intervals.append((left, right, frozenset(component)))

    intervals.sort(key=lambda item: item[1] - item[0])
    for inner, outer in zip(intervals, intervals[1:]):
        assert outer[0] < inner[0] and inner[1] < outer[1]

    # Patch every nonouter component to an outer component.  At successive
    # depths use opposite sides; equal-side edges are separated by the
    # boundary of the intervening interval.
    owner = {}
    for block, (_, _, component) in enumerate(intervals):
        for vertex in component:
            owner[vertex] = block
    selected: list[tuple[int, int]] = []
    quotient_edges: list[tuple[int, int]] = []
    for depth, (left, right, _) in enumerate(intervals[:-1]):
        edge = (left - 1, left) if depth % 2 == 0 else (right, right + 1)
        assert edge[0] >= 0 and edge[1] < len(successor)
        assert owner[edge[0]] != owner[edge[1]]
        selected.append(edge)
        quotient_edges.append((owner[edge[0]], owner[edge[1]]))
    used_endpoints = [endpoint for edge in selected for endpoint in edge]
    assert len(used_endpoints) == len(set(used_endpoints))

    parent = list(range(len(intervals)))

    def root(vertex: int) -> int:
        while parent[vertex] != vertex:
            parent[vertex] = parent[parent[vertex]]
            vertex = parent[vertex]
        return vertex

    for a, b in quotient_edges:
        a, b = root(a), root(b)
        assert a != b
        parent[a] = b
    assert len({root(i) for i in range(len(intervals))}) == 1


def audit_parameter_set(parameters: tuple[int, ...]) -> int:
    assert tuple(sorted(parameters)) == parameters
    best: int | None = None
    optimizers: list[tuple[int, ...]] = []
    for successor in permutations(range(len(parameters))):
        value = assignment_weight(parameters, successor)
        if best is None or value > best:
            best = value
            optimizers = [successor]
        elif value == best:
            optimizers.append(successor)
    for successor in optimizers:
        structural_checks(successor)
    return len(optimizers)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()

    deterministic = (
        (-6, -4, -1, 2, 3, 4, 10),
        (-13, -10, -6, 5, 10, 13, 14),
        (-9, -8, -4, -1, 0, 2, 7, 11),
    )
    checked = 0
    optimizer_count = 0
    for parameters in deterministic:
        optimizer_count += audit_parameter_set(parameters)
        checked += 1

    random = Random(20260904)
    largest = 9 if args.full else 8
    samples = 20 if args.full else 5
    for n in range(3, largest + 1):
        for _ in range(samples):
            parameters = tuple(sorted(random.sample(range(-40, 41), n)))
            optimizer_count += audit_parameter_set(parameters)
            checked += 1

    print(
        "PASS: parabolic assignment barrier; "
        f"{checked} parameter sets, {optimizer_count} exact maximizing covers"
    )


if __name__ == "__main__":
    main()
