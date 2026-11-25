# Sudais's Handoff (Steps 4-6)

This folder contains **Student 2's work** for the 484 final project. It is designed to pick up directly from Tram's Stage 1 handoff and produce everything needed for:

1. Step (4): build the distance matrix `D_{S,q}`,
2. Step (5): build the sampled `p`-distance matrices `D_{S,q,p}`,
3. Step (6): evaluate and plot
   - `f(p) = det(D_{S,q,p})`
   - `g(p) = sum(D_{S,q,p}^{-1})` when the matrix is invertible.

The current version of the pipeline uses:

- high-precision arithmetic with `mpmath`,
- adaptive refinement in difficult `p`-intervals,
- cleaner plots that are more reliable near singular behavior.

## What This Code Uses

- Input comes from Tram's JSON handoff:
  - `../Tram/tram_handoff/tram_output.json`
- The code preserves Tram's:
  - `set_id`
  - point ordering
  - bridge / no-bridge labels

That makes it easy for Student 3 to line up this output with the Stage 1 data.

## Files In This Folder

- `main.py`
  - The full Student 2 pipeline.
- `README.md`
  - This explanation and run guide.
- `sudais_handoff/`
  - Created after running the code.
  - Contains JSON, CSV tables, and plot files.
- `student2_report.tex`
  - A short LaTeX writeup for this stage.

## Output Structure

After running `main.py`, the code writes:

- `sudais_handoff/sudais_output.json`
  - Main handoff bundle for Student 3.
- `sudais_handoff/curve_summary.csv`
  - One summary row per `(set, q)` analysis.
- `sudais_handoff/tables/<set_id>/...`
  - Distance matrices and sampled curve tables.
- `sudais_handoff/plots/<set_id>/...`
  - `PNG`, `PDF`, and `SVG` plots for `f(p)` and `g(p)`.

For each set `S` and each chosen `q`, the code produces:

- one CSV file for `D_{S,q}`,
- one CSV file with adaptively sampled values of `p`, `f(p)`, `g(p)`, and numerical diagnostics,
- one plot bundle showing both curves in `PNG`, `PDF`, and `SVG`.

## Default Parameters

By default, the script samples:

- `q` values:
  - `1 1.5 2 2.5 3`
- `p` values:
  - from `0.0` to `4.0`
  - with a base grid of `61` points
  - plus `4` adaptive refinement rounds where the curves are hardest to resolve

It also uses:

- `80` decimal digits of working precision,
- a very small relative singularity threshold,
- extra diagnostics in the curve CSV files to flag singular or difficult regions.

This gives Student 3 a starting point below, at, and above `q = 2`.

## Important Numerical Note

The code computes `g(p)` using a linear solve rather than explicitly forming the full inverse matrix. This is mathematically equivalent for the needed quantity because:

- `sum(D^{-1}) = 1^T D^{-1} 1`

and it is usually more numerically stable than building the inverse entry-by-entry.

Also:

- the diagonal of `D_{S,q,p}` is kept at `0`,
- when `p = 0`, every off-diagonal entry is set to `1`.

That matches the intended distance-power behavior for distinct points.

Because the code now uses arbitrary precision and adaptive sampling, the output should be much less sensitive to the kind of plotting noise that can appear with ordinary double-precision fixed-grid sampling.

## Plot Note

The newer plot style is meant to be easier to read in a report:

- the dashed vertical line marks `p = q`,
- the lower panel leaves visible gaps where `g(p)` is undefined,
- those gaps happen when `D_{S,q,p}` is singular, so the inverse does not exist at that sampled `p`.
- the plotted y-values use a signed `log10(1 + |value|)` transform so very large magnitudes stay readable.

## How To Run It

From the project root:

```bash
python3 Sudais/main.py
```

This uses the default Tram input file and writes output into:

```text
Sudais/sudais_handoff/
```

## How To Run With Custom q Values

Example:

```bash
python3 Sudais/main.py --q-values 1 2 2.5 3.5
```

## How To Run With A Different p Grid

Example:

```bash
python3 Sudais/main.py --p-start 0 --p-end 5 --p-count 81 --adaptive-rounds 5
```

## How To Run One Set For Checking

Example:

```bash
python3 Sudais/main.py --set-ids S01 --q-values 2
```

## Step-By-Step Workflow

1. Make sure Tram's handoff file exists at:
   - `Tram/tram_handoff/tram_output.json`
2. Run:
   - `python3 Sudais/main.py`
3. Open the generated folder:
   - `Sudais/sudais_handoff/`
4. Check:
   - `sudais_output.json` for the main handoff bundle,
   - `curve_summary.csv` for the quick summary,
   - `plots/` for the graph files,
   - `tables/` for the raw numeric outputs,
   - `student2_report.tex` for the writeup.
5. Share `Sudais/sudais_handoff/` with Student 3.

## What Student 3 Receives

Student 3 can use this handoff in two ways:

1. Read the already-sampled `f(p)` and `g(p)` data from the curve CSV files.
2. Re-run `main.py` with more adaptive rounds, a different base grid, or additional `q` values to refine root estimates for:
   - `P_{S,q} = min { p > 0 : f(p) = 0 or g(p) = 0 }`

## Summary Of My Completed Part

I completed the Stage 2 tasks:

- built `D_{S,q}`,
- built sampled `D_{S,q,p}`,
- evaluated `f(p)` and `g(p)`,
- generated graph files for those curves,
- packaged the results in a clean handoff format for the next student.

## Portfolio distribution
This folder contains my Stage 2 source only. The preceding teammate JSON handoff is not bundled; supply it with the input option shown in `python3 main.py --help`.
