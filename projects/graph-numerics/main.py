import argparse
import csv
import json
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import mpmath as mp

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib-cache")

try:
    # Matplotlib is used only for clean report-quality plots.
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    MATPLOTLIB_AVAILABLE = True
except Exception:
    plt = None
    MATPLOTLIB_AVAILABLE = False

Point = Tuple[int, int]
MPMatrix = List[List[mp.mpf]]
MP_ZERO = mp.mpf("0")
MP_ONE = mp.mpf("1")


@dataclass
class PrecisionConfig:
    precision_dps: int
    guard_digits: int
    output_digits: int
    adaptive_rounds: int
    refine_log_jump: mp.mpf
    near_singular_log10_spread: mp.mpf
    relative_singularity_tol: Optional[mp.mpf]
    max_samples_per_curve: int


def default_input_path() -> Path:
    return Path(__file__).resolve().parent.parent / "Tram" / "tram_handoff" / "tram_output.json"


def default_output_path() -> Path:
    return Path(__file__).resolve().parent / "sudais_handoff"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="High-precision Student 2 pipeline for Graph Theory 484: steps (4)-(6).",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=default_input_path(),
        help="Path to Tram's Stage 1 handoff JSON.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=default_output_path(),
        help="Directory where Sudais handoff files and plots will be written.",
    )
    parser.add_argument(
        "--set-ids",
        nargs="*",
        default=[],
        help="Optional list of set IDs to process, such as S01 S02.",
    )
    parser.add_argument(
        "--q-values",
        nargs="+",
        default=["1", "1.5", "2", "2.5", "3"],
        help="One or more q values for the l_q metric.",
    )
    parser.add_argument(
        "--p-start",
        default="0",
        help="Starting p value for curve sampling.",
    )
    parser.add_argument(
        "--p-end",
        default="4",
        help="Ending p value for curve sampling.",
    )
    parser.add_argument(
        "--p-count",
        type=int,
        default=61,
        help="Number of base-grid p values before adaptive refinement.",
    )
    parser.add_argument(
        "--precision-dps",
        type=int,
        default=80,
        help="Working decimal precision used by mpmath.",
    )
    parser.add_argument(
        "--guard-digits",
        type=int,
        default=20,
        help="Extra safety digits reserved when deciding if a pivot is numerically zero.",
    )
    parser.add_argument(
        "--adaptive-rounds",
        type=int,
        default=4,
        help="Number of midpoint-refinement rounds for difficult curve regions.",
    )
    parser.add_argument(
        "--refine-log-jump",
        default="1.25",
        help="Refine intervals when transformed endpoint values differ by more than this amount.",
    )
    parser.add_argument(
        "--near-singular-log10-spread",
        default="18",
        help="Mark samples as near-singular when pivot spread exceeds this log10 threshold.",
    )
    parser.add_argument(
        "--singularity-tol",
        default=None,
        help="Optional relative pivot tolerance override, for example 1e-50.",
    )
    parser.add_argument(
        "--max-samples-per-curve",
        type=int,
        default=401,
        help="Safety cap on the total number of adaptive samples for one curve.",
    )
    parser.add_argument(
        "--output-digits",
        type=int,
        default=30,
        help="Number of significant digits written to CSV files.",
    )
    return parser.parse_args()


def mpf_from_value(value: Any) -> mp.mpf:
    return mp.mpf(str(value))


def q_display(q_value: mp.mpf) -> str:
    text = mp.nstr(q_value, 12)
    if "e" not in text and "E" not in text and "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def q_path_label(q_value: mp.mpf) -> str:
    return f"q_{q_display(q_value).replace('-', 'm').replace('.', 'p')}"


def point_label(point: Point) -> str:
    return f"({point[0]},{point[1]})"


def mpf_to_str(value: Optional[mp.mpf], digits: int) -> str:
    if value is None:
        return ""
    if value == 0:
        return "0"
    return mp.nstr(value, n=digits)


def mpf_to_float(value: Optional[mp.mpf]) -> float:
    if value is None:
        return float("nan")
    if not mp.isfinite(value):
        return math.copysign(float("inf"), float(mp.sign(value)))
    try:
        return float(value)
    except (OverflowError, ValueError):
        return math.copysign(float("inf"), float(mp.sign(value)))


def mpf_key(value: mp.mpf, digits: int) -> str:
    return mp.nstr(value, n=digits)


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def parse_points(raw_points: Sequence[Sequence[int]]) -> List[Point]:
    return [(int(x), int(y)) for x, y in raw_points]


def linspace_mp(start: mp.mpf, end: mp.mpf, count: int) -> List[mp.mpf]:
    if count <= 0:
        raise ValueError("p-count must be positive.")
    if count == 1:
        return [start]
    step = (end - start) / (count - 1)
    return [start + step * index for index in range(count)]


def build_distance_and_log_matrices(points: Sequence[Point], q_value: mp.mpf) -> Tuple[MPMatrix, List[List[Optional[mp.mpf]]]]:
    # We build D_{S,q} only once per set and q, then reuse the log-distances for every p.
    distance_matrix: MPMatrix = []
    log_distance_matrix: List[List[Optional[mp.mpf]]] = []
    inverse_q = MP_ONE / q_value

    for point_i in points:
        distance_row: List[mp.mpf] = []
        log_row: List[Optional[mp.mpf]] = []
        for point_j in points:
            dx = abs(point_i[0] - point_j[0])
            dy = abs(point_i[1] - point_j[1])
            if dx == 0 and dy == 0:
                distance_row.append(MP_ZERO)
                log_row.append(None)
                continue

            dx_mp = mp.mpf(dx)
            dy_mp = mp.mpf(dy)
            distance = mp.power(mp.power(dx_mp, q_value) + mp.power(dy_mp, q_value), inverse_q)
            distance_row.append(distance)
            log_row.append(mp.log(distance))
        distance_matrix.append(distance_row)
        log_distance_matrix.append(log_row)

    return distance_matrix, log_distance_matrix


def build_p_distance_matrix(log_distance_matrix: List[List[Optional[mp.mpf]]], p_value: mp.mpf) -> MPMatrix:
    # The diagonal stays zero. When p = 0, every off-diagonal distance becomes 1.
    matrix: MPMatrix = []
    for row_index, row_logs in enumerate(log_distance_matrix):
        powered_row: List[mp.mpf] = []
        for col_index, log_distance in enumerate(row_logs):
            if row_index == col_index or log_distance is None:
                powered_row.append(MP_ZERO)
            elif p_value == 0:
                powered_row.append(MP_ONE)
            else:
                powered_row.append(mp.exp(p_value * log_distance))
        matrix.append(powered_row)
    return matrix


def matrix_max_abs(matrix: MPMatrix) -> mp.mpf:
    return max((mp.fabs(entry) for row in matrix for entry in row), default=MP_ONE)


def relative_singularity_tol(config: PrecisionConfig) -> mp.mpf:
    if config.relative_singularity_tol is not None:
        return config.relative_singularity_tol
    effective_digits = max(10, config.precision_dps - config.guard_digits)
    return mp.power(10, -effective_digits)


def absolute_singularity_threshold(matrix: MPMatrix, config: PrecisionConfig) -> mp.mpf:
    return relative_singularity_tol(config) * max(MP_ONE, matrix_max_abs(matrix))


def lu_decompose_mp(matrix: MPMatrix, zero_threshold: mp.mpf) -> Optional[Dict[str, Any]]:
    n = len(matrix)
    lu = [row[:] for row in matrix]
    permutation = list(range(n))
    row_swap_sign = 1
    max_abs_entry = max(MP_ONE, matrix_max_abs(matrix))
    min_abs_pivot: Optional[mp.mpf] = None

    for pivot_col in range(n):
        pivot_row = max(range(pivot_col, n), key=lambda row_index: mp.fabs(lu[row_index][pivot_col]))
        pivot_value = lu[pivot_row][pivot_col]
        pivot_abs = mp.fabs(pivot_value)
        if pivot_abs <= zero_threshold:
            return None

        if min_abs_pivot is None or pivot_abs < min_abs_pivot:
            min_abs_pivot = pivot_abs

        if pivot_row != pivot_col:
            lu[pivot_col], lu[pivot_row] = lu[pivot_row], lu[pivot_col]
            permutation[pivot_col], permutation[pivot_row] = permutation[pivot_row], permutation[pivot_col]
            row_swap_sign *= -1

        for row_index in range(pivot_col + 1, n):
            lu[row_index][pivot_col] /= lu[pivot_col][pivot_col]
            multiplier = lu[row_index][pivot_col]
            for col_index in range(pivot_col + 1, n):
                lu[row_index][col_index] -= multiplier * lu[pivot_col][col_index]

    pivot_spread = mp.log10(max_abs_entry / max(min_abs_pivot, mp.mpf("1e-300"))) if min_abs_pivot else mp.inf
    return {
        "lu": lu,
        "permutation": permutation,
        "row_swap_sign": row_swap_sign,
        "max_abs_entry": max_abs_entry,
        "min_abs_pivot": min_abs_pivot or MP_ZERO,
        "pivot_log10_spread": pivot_spread,
    }


def lu_determinant_mp(factorization: Dict[str, Any]) -> Tuple[mp.mpf, int, Optional[mp.mpf]]:
    sign = factorization["row_swap_sign"]
    log10_abs_det = MP_ZERO
    for row_index in range(len(factorization["lu"])):
        diagonal_value = factorization["lu"][row_index][row_index]
        if diagonal_value == 0:
            return MP_ZERO, 0, None
        if diagonal_value < 0:
            sign *= -1
        log10_abs_det += mp.log10(mp.fabs(diagonal_value))

    determinant = mp.mpf(sign) * mp.power(10, log10_abs_det)
    return determinant, sign, log10_abs_det


def lu_solve_mp(factorization: Dict[str, Any], rhs: Sequence[mp.mpf]) -> List[mp.mpf]:
    lu = factorization["lu"]
    permutation = factorization["permutation"]
    n = len(lu)

    # The LU decomposition records row swaps, so we apply the same permutation to the rhs.
    permuted_rhs = [rhs[permutation[row_index]] for row_index in range(n)]

    forward_solution = [MP_ZERO] * n
    for row_index in range(n):
        total = permuted_rhs[row_index]
        for col_index in range(row_index):
            total -= lu[row_index][col_index] * forward_solution[col_index]
        forward_solution[row_index] = total

    backward_solution = [MP_ZERO] * n
    for row_index in range(n - 1, -1, -1):
        total = forward_solution[row_index]
        for col_index in range(row_index + 1, n):
            total -= lu[row_index][col_index] * backward_solution[col_index]
        backward_solution[row_index] = total / lu[row_index][row_index]

    return backward_solution


def residual_inf_norm(matrix: MPMatrix, solution: Sequence[mp.mpf], rhs: Sequence[mp.mpf]) -> mp.mpf:
    residuals: List[mp.mpf] = []
    for row, rhs_entry in zip(matrix, rhs):
        product = mp.fsum(row[col_index] * solution[col_index] for col_index in range(len(solution)))
        residuals.append(mp.fabs(product - rhs_entry))
    return max(residuals, default=MP_ZERO)


def evaluate_curve_point(
    log_distance_matrix: List[List[Optional[mp.mpf]]],
    p_value: mp.mpf,
    config: PrecisionConfig,
) -> Dict[str, Any]:
    # Each p-sample is evaluated with guard digits so the singularity checks are stricter.
    with mp.workdps(config.precision_dps + config.guard_digits):
        p_distance_matrix = build_p_distance_matrix(log_distance_matrix, p_value)
        singularity_threshold = absolute_singularity_threshold(p_distance_matrix, config)
        factorization = lu_decompose_mp(p_distance_matrix, singularity_threshold)

        if factorization is None:
            return {
                "p": p_value,
                "determinant": MP_ZERO,
                "determinant_sign": 0,
                "log10_abs_determinant": None,
                "inverse_sum": None,
                "inverse_defined": False,
                "log10_abs_inverse_sum": None,
                "numerical_status": "singular",
                "pivot_log10_spread": None,
                "min_abs_pivot": MP_ZERO,
                "max_abs_entry": matrix_max_abs(p_distance_matrix),
                "residual_inf_norm": None,
                "singularity_threshold": singularity_threshold,
            }

        determinant, determinant_sign, log10_abs_determinant = lu_determinant_mp(factorization)
        rhs = [MP_ONE] * len(p_distance_matrix)
        solution = lu_solve_mp(factorization, rhs)
        inverse_sum = mp.fsum(solution)
        residual = residual_inf_norm(p_distance_matrix, solution, rhs)
        log10_abs_inverse_sum = None if inverse_sum == 0 else mp.log10(mp.fabs(inverse_sum))
        numerical_status = (
            "near_singular"
            if factorization["pivot_log10_spread"] >= config.near_singular_log10_spread
            else "stable"
        )

        return {
            "p": p_value,
            "determinant": determinant,
            "determinant_sign": determinant_sign,
            "log10_abs_determinant": log10_abs_determinant,
            "inverse_sum": inverse_sum,
            "inverse_defined": True,
            "log10_abs_inverse_sum": log10_abs_inverse_sum,
            "numerical_status": numerical_status,
            "pivot_log10_spread": factorization["pivot_log10_spread"],
            "min_abs_pivot": factorization["min_abs_pivot"],
            "max_abs_entry": factorization["max_abs_entry"],
            "residual_inf_norm": residual,
            "singularity_threshold": singularity_threshold,
        }


def signed_log10_plus_one(value: Optional[mp.mpf]) -> Optional[mp.mpf]:
    if value is None:
        return None
    if value == 0:
        return MP_ZERO
    return mp.sign(value) * mp.log10(1 + mp.fabs(value))


def row_sign(value: Optional[mp.mpf]) -> int:
    if value is None:
        return 0
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def interval_needs_refinement(
    left_row: Dict[str, Any],
    right_row: Dict[str, Any],
    min_step: mp.mpf,
    config: PrecisionConfig,
) -> bool:
    interval_width = right_row["p"] - left_row["p"]
    if interval_width <= min_step:
        return False

    # We always refine across visible singular transitions and sign changes.
    if left_row["inverse_defined"] != right_row["inverse_defined"]:
        return True
    if left_row["determinant_sign"] != right_row["determinant_sign"]:
        return True
    if left_row["inverse_defined"] and right_row["inverse_defined"]:
        if row_sign(left_row["inverse_sum"]) != row_sign(right_row["inverse_sum"]):
            return True

    # Near-singular samples deserve more attention because they are the most unstable.
    if left_row["numerical_status"] != "stable" or right_row["numerical_status"] != "stable":
        return True

    left_det_value = signed_log10_plus_one(left_row["determinant"])
    right_det_value = signed_log10_plus_one(right_row["determinant"])
    if left_det_value is not None and right_det_value is not None:
        if mp.fabs(right_det_value - left_det_value) > config.refine_log_jump:
            return True

    left_inv_value = signed_log10_plus_one(left_row["inverse_sum"])
    right_inv_value = signed_log10_plus_one(right_row["inverse_sum"])
    if left_inv_value is not None and right_inv_value is not None:
        if mp.fabs(right_inv_value - left_inv_value) > config.refine_log_jump:
            return True

    return False


def evaluate_curve(
    log_distance_matrix: List[List[Optional[mp.mpf]]],
    p_start: mp.mpf,
    p_end: mp.mpf,
    base_count: int,
    config: PrecisionConfig,
) -> List[Dict[str, Any]]:
    sample_rows: Dict[str, Dict[str, Any]] = {}
    base_grid = linspace_mp(p_start, p_end, base_count)
    key_digits = config.precision_dps + config.guard_digits + 10

    for p_value in base_grid:
        sample_rows[mpf_key(p_value, key_digits)] = evaluate_curve_point(log_distance_matrix, p_value, config)

    if base_count == 1:
        return list(sample_rows.values())

    min_step = (p_end - p_start) / ((base_count - 1) * (2 ** config.adaptive_rounds))

    for _ in range(config.adaptive_rounds):
        ordered_rows = sorted(sample_rows.values(), key=lambda row: row["p"])
        new_points: List[mp.mpf] = []
        queued_keys = set()

        for left_row, right_row in zip(ordered_rows, ordered_rows[1:]):
            if len(sample_rows) + len(new_points) >= config.max_samples_per_curve:
                break
            if not interval_needs_refinement(left_row, right_row, min_step, config):
                continue

            midpoint = (left_row["p"] + right_row["p"]) / 2
            midpoint_key = mpf_key(midpoint, key_digits)
            if midpoint_key in sample_rows or midpoint_key in queued_keys:
                continue
            queued_keys.add(midpoint_key)
            new_points.append(midpoint)

        if not new_points:
            break

        for p_value in new_points:
            sample_rows[mpf_key(p_value, key_digits)] = evaluate_curve_point(log_distance_matrix, p_value, config)

    return sorted(sample_rows.values(), key=lambda row: row["p"])


def write_distance_matrix_csv(path: Path, points: Sequence[Point], matrix: MPMatrix, output_digits: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = ["point"] + [point_label(point) for point in points]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        for point, row in zip(points, matrix):
            writer.writerow([point_label(point)] + [mpf_to_str(value, output_digits) for value in row])


def write_curve_csv(path: Path, curve_rows: Sequence[Dict[str, Any]], output_digits: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "p",
                "determinant",
                "inverse_sum",
                "inverse_defined",
                "determinant_sign",
                "log10_abs_determinant",
                "log10_abs_inverse_sum",
                "numerical_status",
                "pivot_log10_spread",
                "min_abs_pivot",
                "max_abs_entry",
                "residual_inf_norm",
                "singularity_threshold",
            ]
        )
        for row in curve_rows:
            writer.writerow(
                [
                    mpf_to_str(row["p"], output_digits),
                    mpf_to_str(row["determinant"], output_digits),
                    mpf_to_str(row["inverse_sum"], output_digits),
                    "true" if row["inverse_defined"] else "false",
                    row["determinant_sign"],
                    mpf_to_str(row["log10_abs_determinant"], output_digits),
                    mpf_to_str(row["log10_abs_inverse_sum"], output_digits),
                    row["numerical_status"],
                    mpf_to_str(row["pivot_log10_spread"], output_digits),
                    mpf_to_str(row["min_abs_pivot"], output_digits),
                    mpf_to_str(row["max_abs_entry"], output_digits),
                    mpf_to_str(row["residual_inf_norm"], output_digits),
                    mpf_to_str(row["singularity_threshold"], output_digits),
                ]
            )


def transformed_plot_values(curve_rows: Sequence[Dict[str, Any]], field_name: str) -> List[float]:
    plot_values: List[float] = []
    for row in curve_rows:
        transformed = signed_log10_plus_one(row[field_name])
        plot_values.append(mpf_to_float(transformed))
    return plot_values


def finite_nonzero_abs_values(values: Sequence[float]) -> List[float]:
    magnitudes = [abs(value) for value in values if math.isfinite(value) and value != 0.0]
    magnitudes.sort()
    return magnitudes


def choose_plot_margin(values: Sequence[float]) -> Tuple[float, float]:
    finite_values = [value for value in values if math.isfinite(value)]
    if not finite_values:
        return -1.0, 1.0
    lower = min(finite_values)
    upper = max(finite_values)
    if lower == upper:
        return lower - 1.0, upper + 1.0
    margin = 0.08 * (upper - lower)
    return lower - margin, upper + margin


def write_curve_plot_files(
    plot_base: Path,
    curve_rows: Sequence[Dict[str, Any]],
    q_value: mp.mpf,
    set_id: str,
    has_bridge: bool,
) -> Dict[str, Optional[str]]:
    if not MATPLOTLIB_AVAILABLE:
        return {"png": None, "pdf": None, "svg": None}

    plot_base.parent.mkdir(parents=True, exist_ok=True)
    p_values = [mpf_to_float(row["p"]) for row in curve_rows]
    det_values = transformed_plot_values(curve_rows, "determinant")
    inv_values = [
        float("nan") if not row["inverse_defined"] else mpf_to_float(signed_log10_plus_one(row["inverse_sum"]))
        for row in curve_rows
    ]
    undefined_g_p_values = [mpf_to_float(row["p"]) for row in curve_rows if not row["inverse_defined"]]
    near_singular_p_values = [mpf_to_float(row["p"]) for row in curve_rows if row["numerical_status"] == "near_singular"]
    status_label = "bridge case" if has_bridge else "no-bridge case"

    figure, axes = plt.subplots(2, 1, figsize=(11.0, 8.0), sharex=True, constrained_layout=True)

    for axis in axes:
        axis.grid(True, which="major", color="#d9e2ec", linewidth=0.9, alpha=0.9)
        axis.grid(True, which="minor", color="#edf2f7", linewidth=0.6, alpha=0.9)
        axis.axvline(mpf_to_float(q_value), color="#0f172a", linestyle="--", linewidth=1.3)
        axis.set_xlim(min(p_values), max(p_values))

    det_lower, det_upper = choose_plot_margin(det_values)
    inv_lower, inv_upper = choose_plot_margin(inv_values)

    axes[0].plot(
        p_values,
        det_values,
        color="#b91c1c",
        linewidth=1.9,
        marker="o",
        markersize=2.6,
    )
    axes[0].set_ylabel(r"$\mathrm{sgn}(f(p))\,\log_{10}(1+|f(p)|)$")
    axes[0].set_ylim(det_lower, det_upper)

    axes[1].plot(
        p_values,
        inv_values,
        color="#1d4ed8",
        linewidth=1.9,
        marker="o",
        markersize=2.6,
        label=r"$g(p)$",
    )
    axes[1].set_ylabel(r"$\mathrm{sgn}(g(p))\,\log_{10}(1+|g(p)|)$")
    axes[1].set_xlabel(r"$p$")
    axes[1].set_ylim(inv_lower, inv_upper)

    if undefined_g_p_values:
        axes[1].scatter(
            undefined_g_p_values,
            [inv_lower + 0.05 * (inv_upper - inv_lower)] * len(undefined_g_p_values),
            color="#475569",
            marker="x",
            s=26,
            linewidths=1.0,
            label=r"$g(p)$ undefined",
            zorder=6,
        )

    if near_singular_p_values:
        axes[0].scatter(
            near_singular_p_values,
            [det_lower + 0.06 * (det_upper - det_lower)] * len(near_singular_p_values),
            color="#c2410c",
            marker="D",
            s=18,
            alpha=0.8,
            label="near singular",
            zorder=6,
        )
        axes[1].scatter(
            near_singular_p_values,
            [inv_lower + 0.12 * (inv_upper - inv_lower)] * len(near_singular_p_values),
            color="#c2410c",
            marker="D",
            s=18,
            alpha=0.8,
            label="near singular",
            zorder=6,
        )

    axes[0].legend(
        handles=[
            plt.Line2D([], [], color="#b91c1c", linewidth=1.9, marker="o", markersize=3, label=r"$f(p)$"),
            plt.Line2D([], [], color="#0f172a", linewidth=1.3, linestyle="--", label=r"$p=q$"),
            plt.Line2D([], [], color="#c2410c", marker="D", linestyle="", markersize=5, label="near singular"),
        ],
        loc="best",
        frameon=True,
        facecolor="white",
    )
    axes[1].legend(loc="best", frameon=True, facecolor="white")

    figure.suptitle(
        f"Set {set_id}, q = {q_display(q_value)} ({status_label})",
        fontsize=15,
        fontweight="bold",
    )
    figure.text(
        0.5,
        0.01,
        "Adaptive high-precision sampling. The dashed line marks p = q. "
        "Gaps and x-markers show where D_{S,q,p} is singular, so g(p) is not defined.",
        ha="center",
        fontsize=10,
        color="#334155",
    )

    png_path = plot_base.with_suffix(".png")
    pdf_path = plot_base.with_suffix(".pdf")
    svg_path = plot_base.with_suffix(".svg")
    figure.savefig(png_path, dpi=240, bbox_inches="tight")
    figure.savefig(pdf_path, bbox_inches="tight")
    figure.savefig(svg_path, bbox_inches="tight")
    plt.close(figure)

    return {
        "png": str(png_path),
        "pdf": str(pdf_path),
        "svg": str(svg_path),
    }


def summarize_curve_rows(curve_rows: Sequence[Dict[str, Any]], output_digits: int) -> Dict[str, Any]:
    min_abs_det_row = min(curve_rows, key=lambda row: mp.fabs(row["determinant"]))
    max_pivot_spread = max(
        (row["pivot_log10_spread"] for row in curve_rows if row["pivot_log10_spread"] is not None),
        default=None,
    )
    return {
        "num_samples": len(curve_rows),
        "undefined_g_samples": sum(1 for row in curve_rows if not row["inverse_defined"]),
        "near_singular_samples": sum(1 for row in curve_rows if row["numerical_status"] == "near_singular"),
        "min_abs_det": mpf_to_str(mp.fabs(min_abs_det_row["determinant"]), output_digits),
        "min_abs_det_log10": mpf_to_str(min_abs_det_row["log10_abs_determinant"], output_digits),
        "p_at_min_abs_det": mpf_to_str(min_abs_det_row["p"], output_digits),
        "max_pivot_log10_spread": mpf_to_str(max_pivot_spread, output_digits),
    }


def write_summary_csv(path: Path, summary_rows: Sequence[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "set_id",
                "q",
                "has_bridge",
                "distance_matrix_file",
                "curve_file",
                "plot_file",
                "plot_pdf_file",
                "plot_svg_file",
                "num_samples",
                "undefined_g_samples",
                "near_singular_samples",
                "min_abs_det",
                "min_abs_det_log10",
                "p_at_min_abs_det",
                "max_pivot_log10_spread",
            ]
        )
        for row in summary_rows:
            writer.writerow(
                [
                    row["set_id"],
                    row["q"],
                    "true" if row["has_bridge"] else "false",
                    row["distance_matrix_file"],
                    row["curve_file"],
                    row["plot_file"],
                    row["plot_pdf_file"],
                    row["plot_svg_file"],
                    row["num_samples"],
                    row["undefined_g_samples"],
                    row["near_singular_samples"],
                    row["min_abs_det"],
                    row["min_abs_det_log10"],
                    row["p_at_min_abs_det"],
                    row["max_pivot_log10_spread"],
                ]
            )


def build_manifest(
    tram_manifest: Dict[str, Any],
    q_values: Sequence[mp.mpf],
    args: argparse.Namespace,
    config: PrecisionConfig,
    input_path: Path,
    num_sets: int,
) -> Dict[str, Any]:
    return {
        "project": tram_manifest.get("project", "Graph Theory 484 Final Project"),
        "student_role": "Sudais",
        "completed_steps": [4, 5, 6],
        "source_student_role": tram_manifest.get("student_role", "Tram"),
        "source_input_file": str(input_path),
        "q_values": [q_display(value) for value in q_values],
        "sampling_strategy": {
            "p_start": str(args.p_start),
            "p_end": str(args.p_end),
            "base_grid_count": args.p_count,
            "adaptive_rounds": config.adaptive_rounds,
            "refine_log_jump": mpf_to_str(config.refine_log_jump, config.output_digits),
            "max_samples_per_curve": config.max_samples_per_curve,
        },
        "precision": {
            "precision_dps": config.precision_dps,
            "guard_digits": config.guard_digits,
            "relative_singularity_tol": mpf_to_str(relative_singularity_tol(config), config.output_digits),
            "near_singular_log10_spread": mpf_to_str(
                config.near_singular_log10_spread,
                config.output_digits,
            ),
        },
        "source_num_sets": tram_manifest.get("num_sets"),
        "processed_num_sets": num_sets,
        "bridge_summary": tram_manifest.get("bridge_summary"),
        "plot_formats": ["png", "pdf", "svg"] if MATPLOTLIB_AVAILABLE else [],
        "schema_version": "2.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def analyze_set(
    set_record: Dict[str, Any],
    q_values: Sequence[mp.mpf],
    p_start: mp.mpf,
    p_end: mp.mpf,
    base_p_count: int,
    output_dir: Path,
    config: PrecisionConfig,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    set_id = set_record["set_id"]
    points = parse_points(set_record["points"])

    analysis_entries: List[Dict[str, Any]] = []
    summary_rows: List[Dict[str, Any]] = []

    for q_value in q_values:
        q_label = q_path_label(q_value)
        distance_matrix, log_distance_matrix = build_distance_and_log_matrices(points, q_value)
        curve_rows = evaluate_curve(log_distance_matrix, p_start, p_end, base_p_count, config)
        curve_summary = summarize_curve_rows(curve_rows, config.output_digits)

        distance_matrix_file = output_dir / "tables" / set_id / f"{q_label}_distance_matrix.csv"
        curve_file = output_dir / "tables" / set_id / f"{q_label}_curve_values.csv"
        plot_base = output_dir / "plots" / set_id / f"{q_label}_fg_plot"

        write_distance_matrix_csv(distance_matrix_file, points, distance_matrix, config.output_digits)
        write_curve_csv(curve_file, curve_rows, config.output_digits)
        plot_files = write_curve_plot_files(plot_base, curve_rows, q_value, set_id, bool(set_record["has_bridge"]))
        primary_plot_file = plot_files["png"] or plot_files["svg"] or ""
        plot_pdf_file = plot_files["pdf"] or ""
        plot_svg_file = plot_files["svg"] or ""

        analysis_entry = {
            "q": q_display(q_value),
            "q_label": q_label,
            "distance_matrix_file": str(distance_matrix_file),
            "curve_file": str(curve_file),
            "plot_file": primary_plot_file,
            "plot_pdf_file": plot_pdf_file,
            "plot_svg_file": plot_svg_file,
            "curve_summary": curve_summary,
        }
        analysis_entries.append(analysis_entry)

        summary_rows.append(
            {
                "set_id": set_id,
                "q": q_display(q_value),
                "has_bridge": bool(set_record["has_bridge"]),
                "distance_matrix_file": str(distance_matrix_file),
                "curve_file": str(curve_file),
                "plot_file": primary_plot_file,
                "plot_pdf_file": plot_pdf_file,
                "plot_svg_file": plot_svg_file,
                **curve_summary,
            }
        )

    set_output = {
        "set_id": set_record["set_id"],
        "points": set_record["points"],
        "n": set_record["n"],
        "x_values": set_record["x_values"],
        "y_values": set_record["y_values"],
        "has_bridge": set_record["has_bridge"],
        "bridge_edges": set_record["bridge_edges"],
        "analyses": analysis_entries,
    }
    return set_output, summary_rows


def main() -> None:
    args = parse_args()
    mp.mp.dps = args.precision_dps

    config = PrecisionConfig(
        precision_dps=args.precision_dps,
        guard_digits=args.guard_digits,
        output_digits=args.output_digits,
        adaptive_rounds=args.adaptive_rounds,
        refine_log_jump=mpf_from_value(args.refine_log_jump),
        near_singular_log10_spread=mpf_from_value(args.near_singular_log10_spread),
        relative_singularity_tol=None if args.singularity_tol is None else mpf_from_value(args.singularity_tol),
        max_samples_per_curve=args.max_samples_per_curve,
    )

    tram_payload = load_json(args.input)
    requested_set_ids = set(args.set_ids)
    selected_sets = [
        set_record
        for set_record in tram_payload["sets"]
        if not requested_set_ids or set_record["set_id"] in requested_set_ids
    ]
    if requested_set_ids and not selected_sets:
        raise ValueError(f"No matching set IDs found for {sorted(requested_set_ids)}")

    q_values = [mpf_from_value(value) for value in args.q_values]
    p_start = mpf_from_value(args.p_start)
    p_end = mpf_from_value(args.p_end)

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    analyzed_sets: List[Dict[str, Any]] = []
    summary_rows: List[Dict[str, Any]] = []

    for set_record in selected_sets:
        set_output, set_summary_rows = analyze_set(
            set_record=set_record,
            q_values=q_values,
            p_start=p_start,
            p_end=p_end,
            base_p_count=args.p_count,
            output_dir=output_dir,
            config=config,
        )
        analyzed_sets.append(set_output)
        summary_rows.extend(set_summary_rows)

    handoff_payload = {
        "manifest": build_manifest(
            tram_manifest=tram_payload["manifest"],
            q_values=q_values,
            args=args,
            config=config,
            input_path=args.input,
            num_sets=len(analyzed_sets),
        ),
        "source_manifest": tram_payload["manifest"],
        "sets": analyzed_sets,
    }

    write_json(output_dir / "sudais_output.json", handoff_payload)
    write_summary_csv(output_dir / "curve_summary.csv", summary_rows)

    print(f"Analyzed {len(analyzed_sets)} sets from {args.input}")
    print(f"q values: {', '.join(q_display(value) for value in q_values)}")
    print(
        "sampling: "
        f"base grid {args.p_count} points on [{args.p_start}, {args.p_end}] "
        f"with {config.adaptive_rounds} adaptive rounds"
    )
    print(
        "precision: "
        f"{config.precision_dps} dps with relative singularity tolerance "
        f"{mpf_to_str(relative_singularity_tol(config), config.output_digits)}"
    )
    print(f"Wrote handoff JSON: {output_dir / 'sudais_output.json'}")
    print(f"Wrote summary CSV: {output_dir / 'curve_summary.csv'}")
    print(f"Wrote tables under: {output_dir / 'tables'}")
    print(f"Wrote plots under: {output_dir / 'plots'}")


if __name__ == "__main__":
    main()
