# Agent E: independent structural experiments

This branch did not inspect or test the proposed reduction.  All integer and
rational computations below use exact arithmetic.  Statements are labeled as
proved, finite exhaustive, or heuristic evidence.

## Reproduction

Quick check:

```sh
python3 experiments/branch_e_structural_search.py
```

The fuller run used for this note:

```sh
python3 experiments/branch_e_structural_search.py \
  --grid --identity-trials 10000 --oracle-trials 40 --regular-max 20 \
  --general-samples 80 --circle-samples 50
```

The exact brute-force and Held--Karp oracles agreed on 280 seeded integer
instances, 40 for every `n=2,...,8`.  Ten thousand exact rational trials passed
the exchange, Plucker, translation, reversal, and linear-map identities.

## Exact small counterexamples

### A properly self-intersecting optimum is already possible at five points

Take

```text
P = ((0,0), (1,2), (1,3), (2,1), (3,1)).
```

The 24 tours with vertex 0 fixed have weight histogram

```text
7:1, 6:3, 5:3, 4:2, 2:1, 1:2,
-1:2, -2:1, -4:2, -5:3, -6:3, -7:1.
```

The unique maximum is `W=7` at `(0,4,1,3,2)`.  Edges `(4,1)` and
`(3,2)` cross properly.  The best simple tour has weight 6.  The set is in
general position.

This example plus the four-point argument below proves (not merely suggests)
that five is the minimum number of points for which every optimum can be
properly self-intersecting.

### Hull order need not be preserved

For

```text
P = ((0,0), (0,5), (1,1), (4,2), (5,1)),
```

the unique optimum is `W=23` at `(0,3,2,4,1)`; the best simple value is 22.
The counterclockwise hull order is `(0,4,3,1)`, while deleting the one interior
point from the optimum gives `(0,3,4,1)`, neither that order nor its reverse.

### Six small integer points on one circle beat the hull boundary

The following points are all on `x^2+y^2=25`, are in strict convex position,
and contain no antipodal pair:

```text
P = ((-4,-3), (-3,-4), (4,-3), (5,0), (0,5), (-3,4)).
```

Their counterclockwise boundary tour has `W=112`.  Two tours have `W=124`:

```text
(0,2,4,1,3,5), edge determinants (24,20,15,20,20,25)
(0,3,5,1,2,4), edge determinants (15,20,24,25,20,20).
```

Each has five proper crossing pairs and every edge determinant is positive.
Since a simple polygon through convex-position points lies in their convex hull,
the exhibited strict inequality `124>112` proves that every optimum is
self-intersecting.  Brute force additionally finds that exactly these two tours
are optimal.

A related six-point radius-5 instance

```text
((-4,-3), (-3,-4), (0,-5), (3,-4), (5,0), (4,3))
```

has a unique optimum `W=74` at `(0,2,4,1,3,5)`, with edge determinants
`(20,25,-20,24,25,0)`.  The best tour whose individual determinants are all
nonnegative has value 72.  Thus even on a centered circle, forbidding a
negative edge can discard the optimum.  (This second instance has one
antipodal pair.)

### Directed cyclic 2-opt has strict suboptimal local maxima

Use all reversals of a cyclic contiguous block of lengths `2,...,n-2`, including
wrap-around blocks; complementary reversals cannot be identified because this
objective is asymmetric.  For

```text
P = ((0,0), (0,1), (1,0), (1,2), (2,1)),
```

tour `(0,4,1,2,3)` has value 3.  Its ten neighbors have values

```text
-2,-2,-1,-1,-1,1,1,1,2,2,
```

but the global optimum `(0,2,4,3,1)` has value 5.  Hence a natural directed
2-opt local-search/sorting argument fails at `n=5`.

## A proved theorem for equally spaced points

Let the vertices of the regular `n`-gon be indexed modulo `n`.  An edge of
increment `k` has weight `sin(2*pi*k/n)`.

**Theorem (proved).**

* If `4` does not divide `n`, choose the integer `k` closest to `n/4` that
  maximizes the sine.  This `k` is coprime to `n`, the constant-step tour is
  Hamiltonian, and

  ```text
  OPT(n) = n sin(2*pi*k/n).
  ```

* If `n=4m`, then

  ```text
  OPT(4m) = 2m+2 + 2(m-1) cos(pi/(2m)).
  ```

  For `m>=2`, every optimum has `m-1` increments `m-1`, `2m+2` increments
  `m`, and `m-1` increments `m+1`.

Proof of the first case: the selected increment individually maximizes every
edge.  It is coprime because, according as `n` is `1,2,3 mod 4`, the closest
choice is `m`, one of `m,m+1` (the odd one), or `m+1`; the elementary gcds are
one.  Thus a constant-step Hamiltonian cycle attains the sum of all per-edge
upper bounds.

For `n=4m`, write each modular edge increment as `k_i=m+delta_i`, where
`1-m <= delta_i <= 3m-1`, and put `h=pi/(2m)`.  Its weight is
`cos(h delta_i)`.  The lifted partial sums of the `delta_i`, reduced modulo
`m`, visit all `m` residue classes.  Their final sum is a multiple of `4m`.
If it is nonzero, their total variation is at least `4m`; if it is zero, a
closed integer walk representing all `m` residues has range at least `m-1`
and total variation at least `2(m-1)`.  Therefore

```text
sum_i |delta_i| >= 2(m-1).
```

For every allowed integer `delta`,

```text
1-cos(h delta) >= |delta| (1-cos h).
```

For `|delta|<=m`, split the integral of `sin(t)` into intervals of length `h`
and use monotonicity on `[0,pi/2]`.  For `m<=|delta|<=3m-1`, the left side is
at least one; `1-cos h <= h^2/2` proves the bound for `m>=4`, and `m=1,2,3`
are direct checks.  Summing gives the stated upper bound.

For attainment, start with the step-`m` permutation, which has `m` directed
4-cycles.  For `r=1,...,m-1`, at alternating levels swap the two successors of
adjacent residue classes `r-1,r`.  Each swap merges two current cycles and
replaces two step-`m` edges by increments `m-1,m+1`.  The path of `m-1` swaps
therefore yields one Hamiltonian cycle with the stated counts.  Strictness in
the one-edge inequality gives the count characterization.

Consequences: the boundary tour is optimal for regular `n<=6`; the first
regular polygon whose optimum must cross is the heptagon (constant step 2).
The conjecture that an optimal regular tour is always a constant-step star
first fails at `n=8`, where

```text
OPT(8)=6+sqrt(2), increments {1:1, 2:6, 3:1},
```

whereas the best Hamiltonian constant-step tour has value `4 sqrt(2)`.
Held--Karp numerically matched the theorem for every `n=3,...,20`; this check is
experimental corroboration, not part of the proof.

## Exchange identities and their limitation

The following are exact algebraic identities (proved by bilinearity, and also
tested on 10,000 seeded rational quadruples):

```text
det(a,d)+det(c,b)-det(a,b)-det(c,d) = det(a-c,d-b),

w_ab w_cd - w_ac w_bd + w_ad w_bc = 0.
```

The first identity compares swapping the successors in arcs `a->b,c->d` to
`a->d,c->b`.  In a single Hamiltonian cycle, however, that successor swap
splits the cycle into two cycles (and conversely merges two distinct cycles).
It is therefore useful for cycle-cover patching but is not itself a feasible
Hamiltonian uncrossing operation.  A true segment reversal also negates every
internal directed edge, so its change cannot be read from the endpoints alone.

For completeness, a proper crossing in a four-point tour can never be optimal.
Translate its crossing to the origin and write the crossing arcs as
`a->b,c->d`, with `b=-lambda*a`, `d=-mu*c`, `lambda,mu>0`.  If
`K=det(a,c)`, the crossing tour (up to rotation/orientation) has absolute weight

```text
|mu-lambda| |K|,
```

while one orientation of the alternative tour `(a,c,b,d)` has weight

```text
(1+lambda)(1+mu) |K|,
```

which is strictly larger.  This supplies the lower-bound half of the exact
five-point minimum above.

## Seeded frequency data (heuristic only)

For 80 general-position integer samples per size in `[-25,25]^2`, seed
`20260903`, the Held--Karp witness was crossing in

```text
n=4: 0/80; n=5: 7/80; n=6: 54/80; n=7: 77/80;
n=8: 80/80; n=9: 80/80; n=10: 80/80.
```

For 50 rational unit-circle samples per size, using
`((1-t^2)/(1+t^2),2t/(1+t^2))` and seed `20260904`, the exact optimum exceeded
the boundary value in

```text
n=4: 0/50; n=5: 0/50; n=6: 12/50; n=7: 25/50;
n=8: 45/50; n=9: 48/50; n=10: 50/50.
```

An additional exact search over every five-element subset of a fixed pool of
16 small rational circle parameters (4,368 subsets), plus 100,000 seeded random
rational five-point circle instances, found no boundary counterexample at
`n=5`.  This is evidence, not a universal proof, that six may be the minimum in
strict convex/cocircular position.

The exhaustive grid audit is a finite statement: among all general-position
subsets of `{0,1,2,3}^2`, there were 1,278 four-point sets and no crossing
optimum; among 1,668 five-point sets, 12 had at least one crossing optimum and
four had only crossing optima.
