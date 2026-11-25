# Independent audit of the direct dyadic cocircular reduction

Audited artifact: [cocircular_proof.tex](../cocircular_proof.tex),
the mathematical argument read on 7 September 2026. The audit follows the complete
reduction, not merely its numerical experiments.

## Finding

I found no mathematical defect in the current source reduction, macro
isolation, micro correction, source decoding, or rational-circle transfer.
The construction proves ordinary NP-hardness. Its coordinates have
polynomial bit length but exponential magnitude; strong NP-hardness is not
established by this construction. The only external hardness dependency is
the stated Gilmore--Lawler--Shmoys partition-graph spanning-tree theorem;
the root agent verified its definition and Lemma 12 against the indexed
[primary report](https://www2.eecs.berkeley.edu/Pubs/TechRpts/1984/CSD-84-208.pdf),
printed pages 39--40. This source inspection was separate from my proof audit.

## Source and composition

The heights `h_i=k+1-sigma(i)` are exactly `2,...,k+1`. Minimum height two
is sufficient: every level-one row still has a level-two successor, which
is the count fact required by the macro proof. There are
`N=sum_i(h_i+1)=k(k+5)/2` vertices.

The baseline path beginning at initial label i ends at initial label
sigma(i). Changing only its first image to the first vertex of path tau(i)
therefore induces `sigma(tau(i))`, not `tau(sigma(i))`. Hamiltonicity is
exactly the one-cycle condition for `sigma composed with tau`.

The initial-block loss is exactly

    2 A d(tau) - S(tau),
    d(tau) = sum_i i(i-tau(i)),
    S(tau) = sum_i i*tau(i)*(tau(i)-i).

The bound `|S|<k^4<A` is valid for labels `0,...,k-1`. Thus this loss is
nonnegative for every tau. If the induced permutation is one cycle,
`d>=k-c(tau)>=m-1`; threshold feasibility excludes `d>=m` because `A>k^4`.
Equality forces precisely `m-1` disjoint adjacent transpositions, and the
usual cycle-merging induction gives the partition spanning tree. Their S
contributions cancel pairwise. Both YES and NO implications use the same
composition convention correctly. The case m=1 also works: the baseline is
already one cycle and the threshold is its weight.

## Macro isolation

The declared bounds `Q=2^(k+1)` and `H=2^k G k` safely exceed the actual
anchor coefficient and offset maxima. `A>H` bounds every actual coordinate
by `(Q+1)A`. The identity

    K(x,y)=y^3/4-y(x-y/2)^2

gives each anchor column's maximum exactly. For target A, row anchors zero
and A tie; the tie is resolved by counts, since the k target columns at 2A
use all k source rows at A. All other positive target anchors uniquely
require their half-anchor source. At levels two and above, distinct terminal
heights make the next level's count smaller by exactly one.

Every forbidden macro arc loses at least `2A^3`. The per-edge perturbation
bound is valid over the whole segment joining anchor and actual coordinates,
because both partial derivatives have absolute value at most
`3(Q+1)^2 A^2`. The assignment error bound E satisfies `E<0.06A^3`, so
baseline-versus-candidate loss is greater than `A^3>2A(k-1)` for every
forbidden macro pattern. This bound is uniform over all permutations.

The earlier macro-lemma wording issue has been resolved: its explicit
one-sided condition is `B_0-W(s)<=2A(k-1)`. The proof establishes that
statement, not merely an absolute-distance condition.

## Auxiliary correction

The level-one inversion formula is correct. Its bracket is positive with
the stated constants. In fact it is at least 2A, since distinct target
indices satisfy `j+j'>=1`, source indices satisfy `i+i'<=2k-3`, and
`G>=2k`. Hence the manuscript's more conservative gain bound AG is safe.

At a higher level, the map f goes from prescribed nonpeaks onto all rows
except the actual peak q. Therefore `sum Delta=p-q` is exact even when the
matching contains cycles or has several moved rows. Restoring all doubled
images and moving the same valley image from q to p preserves bijectivity
globally and does not change initial images. Different levels can be
corrected independently.

The gain formula

    sum_u [2 x_u Delta_u^2 + v(v-p-q) Delta_u]

is exact. The estimates `x_u>=2cA`, `p,q<3cA`, `0<=v<k`, and every nonzero
Delta being a multiple of cG yield the asserted lower bound. In particular
`(4c^2AG-6cAk)>=2cAG` follows from `(2c-1)G>=3k`.

The last level needs no doubled-edge correction because it has one row.
Once all other levels have been corrected, there remains exactly the
prescribed peak at each distinct height. Sorting peak images into reverse
order is strictly improving whenever needed; the peak gap is greater than
A and the sum factor is greater than 4A-2k. The reverse order is exactly
the prescribed sigma map, by the chosen height formula. This also covers
the important case where only peak-to-valley images were originally wrong.

The corrected assignment has only an initial tau change and thus has
nonnegative loss from the baseline. Any original auxiliary error required
a correction of gain at least AG, giving original loss at least
`AG>2A(k-1)`. This proves isolation without assuming Hamiltonicity of any
intermediate corrected assignment. That relaxation is legitimate and is
essential to the argument.

## Circle transfer and complexity

The revised transfer uses an exact translated identity. Write

    q(x)=((1-epsilon^2 x^2)/(1+epsilon^2 x^2),
          2 epsilon x/(1+epsilon^2 x^2)).

Then

    det(q(x)-(1,0), q(y)-(1,0))
      =4 epsilon^3 K(x,y)/[(1+epsilon^2 x^2)(1+epsilon^2 y^2)].

Translation leaves every tour sum unchanged. For `0<=x,y<=B`,
`|K(x,y)|<=B^3`. The inequality
`0<=1-1/((1+a)(1+b))<=a+b` for nonnegative a,b therefore bounds
the normalized per-edge error by `2 epsilon^2 B^5`. With
`epsilon=1/(8 N B^3)` and `B>=1`, the normalized total error is at most

    2 N epsilon^2 B^5 = 1/(32 N B) < 1/2.

This identity avoids a Taylor expansion entirely. The independent checker
also retains the earlier exact Taylor-remainder check as an additional test.

Thus the half-integer threshold shift preserves YES and NO exactly. No
floating-point claim is needed. Finite rational parameters give distinct
unit-circle points. Their numerators and denominators, and the threshold,
have polynomial bit length. The original parabolic weights and threshold
are integers, which is the needed unit-gap assumption.

The bit-size statements correctly distinguish binary encoding from
polynomial magnitude. Rational determinant summation supplies NP
membership. The construction also lies on a small arc, although the theorem
does not need that additional restriction.

## Independent exact checks

[cocircular_redteam_identity_audit.py](cocircular_redteam_identity_audit.py)
uses only Python standard-library fractions and permutations. It imports no
project reduction code and has no temporary-directory dependency. Run from
the repository root with assertions enabled:

```sh
python3 experiments/cocircular_redteam_identity_audit.py
```

Its fresh persisted-file run passed:

* 30,228 exact higher-level correction cases, checking the gain identity and
  the lower bound, including different actual/prescribed peaks;
* 5,912 initial permutations through size seven, checking the exact source
  loss identity, correction bound, and nonnegativity;
* 2,299 exact translated-circle identities and Taylor-remainder checks for
  all integer pairs in boxes with B=1,...,11, including negative parameters;
* 649 normalized per-edge error bounds for the nonnegative pairs in those
  same boxes, and 11 sharp normalized total-error bounds.

The correction cases use k=2,...,6, G=100k^2, A=100,000,000,
c in {1,2,4}, and source labels {0,2,...,2(k-1)}. For each combination,
the checker considers every prescribed peak, every actual peak, every
bijection of the remaining row sets, and valley values 0 and k-1.
The initial-block cases include every permutation for k=2,...,7 with
A=k^4+1. The circle cases use N=7 and epsilon=1/(8NB^3); their bounds
cover every ordered pair of integers x,y in [-B,B] for each listed B.
The sharper translated-error test uses the subset x,y in [0,B], as in
the construction. The fresh run returned:

```text
PASS: micro correction identity and gap on 30228 exact assignments
PASS: initial-block loss formula and nonnegativity for 5912 permutations
PASS: exact translated-circle identity and Taylor bound on 2299 integer pairs
PASS: normalized circle error on 649 nonnegative pairs and 11 total gap bounds
```

The all-size arguments above are written proofs. These finite checks are
independent algebraic falsification tests, not proof-assistant certification.
The checker refuses to run under `-O` or `-OO`, since those disable its
assertions. Neither this audit nor its successful tests constitute external
peer review or establish literature priority.

## Historical obstruction and current status

Earlier broad patching-barrier prose concerned the interpretation in which
full-spine adjacent patches are uniformly cheap. The new reduction does not
contradict the nested-hull observation: only initial-block adjacent patches
are cheap, while auxiliary patches exceed the threshold. This distinction
has now been qualified in the project status notes. Earlier unsuccessful
approaches remain part of the research history, not obstructions to the
direct dyadic construction audited here.
