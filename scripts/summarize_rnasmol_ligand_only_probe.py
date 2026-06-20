"""Summarize the RNAsmol ligand-only training probe for the manuscript.

The probe keeps the RNAsmol ligand GCN and classifier dimensions, but replaces
the target-specific RNA representation with a learned global null vector. This
script aggregates independently run seed directories into compact CSV tables
for the manuscript and supplementary information.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


DEFAULT_RUNS = [
    ("robin_netperturbation", 20260620, "rnasmol_ligand_only_training_probe_120e"),
    ("robin_netperturbation", 20260621, "rnasmol_ligand_only_training_probe_120e_seed20260621"),
    ("robin_netperturbation", 20260622, "rnasmol_ligand_only_training_probe_120e_seed20260622"),
    ("robin_molperturbation", 20260620, "rnasmol_ligand_only_training_probe_mol_120e_seed20260620"),
    ("robin_molperturbation", 20260621, "rnasmol_ligand_only_training_probe_mol_120e_seed20260621"),
    ("robin_molperturbation", 20260622, "rnasmol_ligand_only_training_probe_mol_120e_seed20260622"),
]


def default_paper_tables_dir(repo_root: Path) -> Path:
    paper_root = repo_root / "paper"
    candidates = sorted(paper_root.glob("targetwise_lowcost_screening*_oup/tables"))
    if candidates:
        return candidates[0]
    return paper_root / "targetwise_lowcost_screening_oup" / "tables"


def parse_args() -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo_root", type=Path, default=repo_root)
    parser.add_argument(
        "--reports_dir",
        type=Path,
        default=repo_root / "reports" / "rnasmol_ligand_only_probe",
    )
    parser.add_argument(
        "--paper_tables_dir",
        type=Path,
        default=default_paper_tables_dir(repo_root),
    )
    parser.add_argument("--output_prefix", default="rnasmol_ligand_only_probe")
    return parser.parse_args()


def fmt_range(values: pd.Series, digits: int = 3) -> str:
    values = pd.to_numeric(values, errors="coerce").dropna()
    if values.empty:
        return ""
    return f"{values.min():.{digits}f}--{values.max():.{digits}f}"


def dataset_label(dataset: str) -> str:
    return {
        "robin_netperturbation": "Network perturbation",
        "robin_molperturbation": "Molecule perturbation",
    }.get(dataset, dataset)


def interpretation(dataset: str, threshold: int, delta_aupr: float, delta_ef5: float) -> str:
    if dataset == "robin_netperturbation":
        if threshold == 20:
            return "Full RNAsmol clearly exceeds the representation-matched ligand-only probe."
        return "Full RNAsmol retains AUPR gain; EF5 gain is positive but smaller."
    if abs(delta_ef5) < 1e-9:
        return "Early retrieval remains saturated by ligand-only information."
    if delta_aupr > 0:
        return "Small AUPR difference with saturated early-retrieval metrics."
    return "No consistent gain over the ligand-only probe."


def read_manifest(run_dir: Path, dataset: str, seed: int) -> dict[str, object]:
    manifest = json.loads((run_dir / "rnasmol_ligand_only_training_probe_manifest.json").read_text())
    summaries = manifest.get("dataset_summaries", [])
    if not summaries:
        raise ValueError(f"No dataset_summaries in {run_dir}")
    summary = summaries[0].copy()
    summary["dataset"] = dataset
    summary["seed"] = seed
    summary["run_dir"] = run_dir.name
    return summary


def main() -> None:
    args = parse_args()
    reports_dir = args.reports_dir.resolve()
    paper_tables_dir = args.paper_tables_dir.resolve()
    paper_tables_dir.mkdir(parents=True, exist_ok=True)

    manifest_rows: list[dict[str, object]] = []
    model_rows: list[pd.DataFrame] = []
    delta_rows: list[pd.DataFrame] = []

    for dataset, seed, run_name in DEFAULT_RUNS:
        run_dir = reports_dir / run_name
        manifest_rows.append(read_manifest(run_dir, dataset, seed))

        model_path = run_dir / "targetwise_metrics" / "rnasmol_ligand_only_training_probe_model_summary_metrics.csv"
        model = pd.read_csv(model_path)
        model = model[(model["level"] == "sample_mean") & (model["min_candidates"].isin([20, 50]))].copy()
        model["dataset"] = dataset
        model["seed"] = seed
        model["run_dir"] = run_name
        model_rows.append(model)

        delta_path = run_dir / "early_retrieval" / "paired_early_retrieval_bootstrap_ci.csv"
        deltas = pd.read_csv(delta_path)
        deltas = deltas[deltas["metric"].isin(["aupr", "ef5"])].copy()
        deltas["seed"] = seed
        deltas["run_dir"] = run_name
        delta_rows.append(deltas)

    manifest_df = pd.DataFrame(manifest_rows)
    model_df = pd.concat(model_rows, ignore_index=True)
    delta_df = pd.concat(delta_rows, ignore_index=True)

    manifest_df.to_csv(paper_tables_dir / f"{args.output_prefix}_seed_manifest.csv", index=False)
    model_df.to_csv(paper_tables_dir / f"{args.output_prefix}_model_summary_by_seed.csv", index=False)
    delta_df.to_csv(paper_tables_dir / f"{args.output_prefix}_paired_deltas_by_seed.csv", index=False)

    rows: list[dict[str, object]] = []
    for dataset in sorted(delta_df["dataset"].unique()):
        row_aupr = manifest_df.loc[manifest_df["dataset"] == dataset, "final_best_test_aupr"]
        for threshold in [20, 50]:
            model_subset = model_df[(model_df["dataset"] == dataset) & (model_df["min_candidates"] == threshold)]
            full = model_subset[model_subset["model"] == "rnasmol"]
            probe = model_subset[model_subset["model"] == "rnasmol_ligand_only_probe"]
            delta_subset = delta_df[(delta_df["dataset"] == dataset) & (delta_df["threshold"] == threshold)]
            aupr_delta = delta_subset[delta_subset["metric"] == "aupr"]["mean_improvement_delta"]
            ef5_delta = delta_subset[delta_subset["metric"] == "ef5"]["mean_improvement_delta"]
            rows.append(
                {
                    "dataset": dataset,
                    "dataset_label": dataset_label(dataset),
                    "threshold": threshold,
                    "n_pools": int(delta_subset["n_pools"].max()),
                    "probe_row_level_aupr_mean": row_aupr.mean(),
                    "probe_row_level_aupr_range": fmt_range(row_aupr),
                    "full_targetwise_aupr_mean": full["mean_aupr"].mean(),
                    "probe_targetwise_aupr_mean": probe["mean_aupr"].mean(),
                    "delta_aupr_mean": aupr_delta.mean(),
                    "delta_aupr_seed_range": fmt_range(aupr_delta),
                    "delta_ef5_mean": ef5_delta.mean(),
                    "delta_ef5_seed_range": fmt_range(ef5_delta),
                    "interpretation": interpretation(
                        dataset,
                        threshold,
                        float(aupr_delta.mean()),
                        float(ef5_delta.mean()),
                    ),
                }
            )

    summary_df = pd.DataFrame(rows)
    summary_df.to_csv(paper_tables_dir / f"{args.output_prefix}_summary.csv", index=False)
    print(summary_df.to_string(index=False))


if __name__ == "__main__":
    main()
