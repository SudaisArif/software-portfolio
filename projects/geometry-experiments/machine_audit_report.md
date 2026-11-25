# Independent machine audit of `proof.tex`

**Run date:** 3 September 2026  
**Arithmetic:** exact Python integers and `fractions.Fraction`  
**Checker:** `experiments/machine_proof_audit.py`

## Result

No counterexample or failed proof obligation was found. The full independent
command was:

```sh
python3 -m py_compile experiments/machine_proof_audit.py
python3 experiments/machine_proof_audit.py --full
```

It returned:

```text
{'audit': 'coefficient-wise polynomial identities',
 'penalty_permutations': 153, 'matching_triples': 216,
 'positivity_certificate':
 'gap=n^3*((7600*n-12)*(n^3+1)^2-1)>0 for every integer n>=2',
 'status': 'PASS'}
{'audit': 'uniform anchor perturbation error', 'corner_cases': 144,
 'maximum_MH_coefficient': 2,
 'maximum_H_squared_coefficient': 2,
 'claimed_bound': '4*M*H+2*H^2', 'status': 'PASS'}
{'audit': 'balanced cyclic colour words', 'n_max': 5, 'words': 793182,
 'maximum_nonpattern_q': {1: -1, 2: 1, 3: 2, 4: 3, 5: 4},
 'status': 'PASS'}
{'audit': 'three-matching composition and Hamiltonicity', 'n_max': 5,
 'matching_triples': 1742049, 'status': 'PASS'}
{'audit': 'independent normalized source reduction',
 'partition_n_max': 7, 'partitions': 1155,
 'candidate_cycles': 657151, 'displacement_n_max': 9,
 'displacement_permutations': 409113, 'status': 'PASS'}
{'audit': 'independent raw determinant tours', 'n_max': 3,
 'instances': 40, 'tours': 1452000,
 'minimum_nonpattern_margin_below_C0_minus_n_cubed':
 {2: 12859437, 3: 631466312}, 'status': 'PASS'}
{'audit': 'independent Held-Karp, canonical factor pairs', 'n_max': 5,
 'instances': 152, 'status': 'PASS'}
```

## Obligations checked

The checker is deliberately independent of `area_tour.py`,
`three_cluster_reduction.py`, and `final_red_team_audit.py`.

1. A sparse-polynomial implementation compares coefficients, rather than
   evaluating at selected numbers, for the three determinant formulas and the
   translation potential. It checks both squared-displacement identities for
   all 153 permutations through size five, the complete generic
   alternating-tour equation for all 216 matching triples at size three, and
   the polynomial factorizations behind the scale and source inequalities.
2. The perturbation expression is checked at every anchor pair and every
   vertex of its deviation box. Multi-affinity then justifies the full-box
   bound. The actual coefficient maximum is smaller than the manuscript's
   intentionally loose bound.
3. Every balanced cyclic color word through five copies of each color is
   enumerated. The circulation equalities and the characterization `q=n` iff
   the word is cyclically `ABCABC...` hold in every case.
4. Every triple of interclass bijections through size five is converted into
   a three-layer successor permutation. Its cycle count always equals that of
   `gamma o beta o alpha`, verifying the composition and Hamiltonicity
   convention.
5. The Sarvanov-style source construction is rebuilt without project imports.
   All set partitions through seven and every candidate Hamiltonian cycle are
   checked against the partition-graph condition. The corrected baseline,
   the objective/displacement identity, and the cycle-count lower bound all
   agree exactly.
6. The geometric points are independently reconstructed and optimized using
   raw integer determinants. All factor-permutation pairs through size three
   and every possible allowed threshold are checked. A separately written
   exact Held--Karp program checks all canonical factor pairs through size
   five. Point distinctness and positive-coordinate translation are also
   checked.

## What this does not certify

This is not a kernel-checked formalization. The checker deliberately has no
dependency on Lean, Coq, Isabelle, Z3, Sage, SymPy, or Hypothesis, and no
proof-assistant formalization was performed. The unbounded claims still depend
on the short general arguments in `proof.tex`; exhaustive testing can only
falsify them on bounded domains. The checker also cannot establish:

- the externally cited NP-completeness theorem for PARTITION GRAPH SPANNING
  TREE;
- the correctness of bibliographic scans or the claim that no earlier paper
  contains the same result;
- novelty, priority, or acceptance by peer review.

Accordingly, the accurate conclusion is that the manuscript survived an
independent exact machine audit with broad bounded coverage and explicit
symbolic coefficient checks. It should not be described as formally verified
until the complete argument and its source theorem have been encoded in a
proof assistant and checked by that assistant's trusted kernel.
