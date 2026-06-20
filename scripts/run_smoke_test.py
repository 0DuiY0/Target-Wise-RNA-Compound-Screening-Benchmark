"""Run the synthetic clean-clone smoke test."""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score


MODEL_SCORES = {
    "rnasmol": "rnasmol_score",
    "ligand_only": "ligand_only_score",
}


def parse_args() -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=repo_root / "examples" / "smoke_test",
        help="Smoke-test fixture directory or CSV file.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=repo_root / "reports" / "smoke_test",
        help="Output directory.",
    )
    parser.add_argument("--min-candidates", type=int, default=5)
    parser.add_argument("--focal-model", default="rnasmol")
    parser.add_argument("--baseline-model", default="ligand_only")
    return parser.parse_args()


def input_csv(path: Path) -> Path:
    return path / "smoke_pairs.csv" if path.is_dir() else path


def manifest_path(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def validate_input(df: pd.DataFrame, path: Path) -> None:
    required = {
        "dataset",
        "candidate_pool_id",
        "target_id",
        "compound_id",
        "smiles",
        "label",
        *MODEL_SCORES.values(),
    }
    missing = sorted(required.difference(df.columns))
    if missing:
        raise KeyError(f"{path} is missing required columns: {missing}")


def expected_first_hit_rank(labels: np.ndarray, scores: np.ndarray) -> float:
    order = np.argsort(-scores, kind="mergesort")
    labels = labels[order]
    scores = scores[order]
    seen = 0
    for score in np.unique(scores)[::-1]:
        mask = scores == score
        group_size = int(mask.sum())
        positives = int(labels[mask].sum())
        if positives > 0:
            return float(seen + (group_size + 1) / (positives + 1))
        seen += group_size
    return float("nan")


def expected_hits_at_k(labels: np.ndarray, scores: np.ndarray, k: int) -> tuple[float, float]:
    order = np.argsort(-scores, kind="mergesort")
    labels = labels[order]
    scores = scores[order]
    selected = 0
    expected_hits = 0.0
    prob_no_hit = 1.0

    for score in np.unique(scores)[::-1]:
        mask = scores == score
        group_labels = labels[mask]
        group_size = int(len(group_labels))
        positives = int(group_labels.sum())
        if selected + group_size <= k:
            expected_hits += positives
            if positives > 0:
                prob_no_hit = 0.0
            selected += group_size
            continue

        remaining = k - selected
        if remaining <= 0:
            break
        expected_hits += positives * remaining / group_size
        if positives > 0 and prob_no_hit > 0:
            negatives = group_size - positives
            if negatives >= remaining:
                prob_no_hit *= math.comb(negatives, remaining) / math.comb(group_size, remaining)
            else:
                prob_no_hit = 0.0
        selected = k
        break

    return float(expected_hits), float(1.0 - prob_no_hit)


def compute_pool_metrics(group: pd.DataFrame, score_col: str) -> dict[str, float]:
    labels = group["label"].to_numpy(dtype=int)
    scores = group[score_col].to_numpy(dtype=float)
    n_candidates = int(len(group))
    n_positive = int(labels.sum())
    n_negative = int(n_candidates - n_positive)
    positive_rate = float(n_positive / n_candidates) if n_candidates else float("nan")

    if n_positive > 0 and n_negative > 0:
        auc = float(roc_auc_score(labels, scores))
        aupr = float(average_precision_score(labels, scores))
    else:
        auc = float("nan")
        aupr = float("nan")

    first_hit = expected_first_hit_rank(labels, scores)
    k_ef5 = max(1, int(math.ceil(0.05 * n_candidates)))
    hits_ef5, top1_prob = expected_hits_at_k(labels, scores, k_ef5)
    ef5 = float(hits_ef5 / (k_ef5 * positive_rate)) if positive_rate > 0 else float("nan")
    mrr = float(1.0 / first_hit) if first_hit and not math.isnan(first_hit) else float("nan")

    return {
        "n_candidates": n_candidates,
        "n_positive": n_positive,
        "n_negative": n_negative,
        "positive_rate": positive_rate,
        "auc": auc,
        "aupr": aupr,
        "first_hit_rank": first_hit,
        "mrr": mrr,
        "ef5": ef5,
        "top1_hit_probability": top1_prob,
    }


def build_target_metrics(df: pd.DataFrame, min_candidates: int) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for (dataset, pool_id), group in df.groupby(["dataset", "candidate_pool_id"], sort=True):
        for model, score_col in MODEL_SCORES.items():
            metrics = compute_pool_metrics(group, score_col)
            eligible = (
                metrics["n_candidates"] >= min_candidates
                and metrics["n_positive"] >= 1
                and metrics["n_negative"] >= 1
            )
            rows.append(
                {
                    "dataset": dataset,
                    "candidate_pool_id": pool_id,
                    "model": model,
                    "score_col": score_col,
                    "eligible": bool(eligible),
                    **metrics,
                }
            )
    return pd.DataFrame(rows)


def build_model_summary(target_metrics: pd.DataFrame) -> pd.DataFrame:
    rows = []
    eligible = target_metrics[target_metrics["eligible"]].copy()
    for model, group in eligible.groupby("model", sort=True):
        rows.append(
            {
                "model": model,
                "n_target_pools": int(group["candidate_pool_id"].nunique()),
                "mean_auc": float(group["auc"].mean()),
                "mean_aupr": float(group["aupr"].mean()),
                "mean_ef5": float(group["ef5"].mean()),
                "mean_mrr": float(group["mrr"].mean()),
                "mean_first_hit_rank": float(group["first_hit_rank"].mean()),
                "mean_top1_hit_probability": float(group["top1_hit_probability"].mean()),
            }
        )
    return pd.DataFrame(rows)


def build_pairwise_deltas(target_metrics: pd.DataFrame, focal_model: str, baseline_model: str) -> pd.DataFrame:
    eligible = target_metrics[target_metrics["eligible"]].copy()
    focal = eligible[eligible["model"] == focal_model]
    baseline = eligible[eligible["model"] == baseline_model]
    paired = focal.merge(
        baseline,
        on=["dataset", "candidate_pool_id"],
        suffixes=("_focal", "_baseline"),
    )
    metric_specs = {
        "auc": True,
        "aupr": True,
        "ef5": True,
        "mrr": True,
        "top1_hit_probability": True,
        "first_hit_rank": False,
    }
    rows = []
    for metric, higher_is_better in metric_specs.items():
        focal_col = f"{metric}_focal"
        baseline_col = f"{metric}_baseline"
        values = paired[focal_col] - paired[baseline_col]
        improvement = values if higher_is_better else paired[baseline_col] - paired[focal_col]
        rows.append(
            {
                "focal_model": focal_model,
                "baseline_model": baseline_model,
                "metric": metric,
                "higher_is_better": bool(higher_is_better),
                "n_pools": int(len(paired)),
                "mean_focal": float(paired[focal_col].mean()),
                "mean_baseline": float(paired[baseline_col].mean()),
                "mean_improvement_delta": float(improvement.mean()),
                "pct_pools_improved": float((improvement > 0).mean()),
                "pct_pools_tied": float(np.isclose(improvement, 0.0).mean()),
            }
        )
    return pd.DataFrame(rows)


def plot_smoke(summary: pd.DataFrame, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 3.0))
    colors = {"rnasmol": "#7A5AA6", "ligand_only": "#C77C2C"}
    for ax, metric, title in [
        (axes[0], "mean_ef5", "Mean EF5"),
        (axes[1], "mean_first_hit_rank", "Mean first-hit rank"),
    ]:
        data = summary.sort_values("model")
        ax.bar(data["model"], data[metric], color=[colors.get(model, "#6F7782") for model in data["model"]])
        ax.set_title(title)
        ax.grid(axis="y", alpha=0.25)
    axes[1].invert_yaxis()
    fig.suptitle("Smoke-test target-wise metrics")
    fig.tight_layout()
    path = output_dir / "smoke_figure.pdf"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def main() -> None:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    output_dir = args.output.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    csv_path = input_csv(args.input)
    df = pd.read_csv(csv_path)
    validate_input(df, csv_path)
    df["label"] = pd.to_numeric(df["label"], errors="raise").astype(int)

    target_metrics = build_target_metrics(df, args.min_candidates)
    summary = build_model_summary(target_metrics)
    deltas = build_pairwise_deltas(target_metrics, args.focal_model, args.baseline_model)

    target_path = output_dir / "target_level_metrics.csv"
    summary_path = output_dir / "model_summary_metrics.csv"
    delta_path = output_dir / "pairwise_delta_summary.csv"
    manifest_file = output_dir / "smoke_test_manifest.json"
    target_metrics.to_csv(target_path, index=False)
    summary.to_csv(summary_path, index=False)
    deltas.to_csv(delta_path, index=False)
    figure_path = plot_smoke(summary, output_dir)

    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_csv": manifest_path(csv_path, repo_root),
        "min_candidates": args.min_candidates,
        "models": MODEL_SCORES,
        "outputs": {
            "target_level_metrics": manifest_path(target_path, repo_root),
            "model_summary_metrics": manifest_path(summary_path, repo_root),
            "pairwise_delta_summary": manifest_path(delta_path, repo_root),
            "smoke_figure": manifest_path(figure_path, repo_root),
        },
        "notes": [
            "Synthetic fixture only; no upstream data are redistributed.",
            "first_hit_rank uses expected random tie-breaking within the first positive tie group.",
            "EF5 uses expected hits when the top-k boundary cuts through a tied score group.",
        ],
    }
    manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


    print(f"wrote {target_path}")
    print(f"wrote {summary_path}")
    print(f"wrote {delta_path}")
    print(f"wrote {figure_path}")
    print(f"wrote {manifest_file}")


if __name__ == "__main__":
    main()
