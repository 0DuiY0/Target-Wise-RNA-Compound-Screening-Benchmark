"""Probe whether saved RNAsmol checkpoints use target-specific RNA context.

This is a lightweight inference-time probe, not a retrained ligand-only
ablation. It keeps the saved RNAsmol ligand graph encoder and classifier fixed,
then compares full test-set predictions with predictions made after replacing
the RNA target tensor by a constant training RNA, a shuffled test RNA, or all
padding tokens.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
from torch_geometric.loader import DataLoader


DEFAULT_DATASET_MODELS = {
    "robin_netperturbation": "robin_bothaug_netperturbation.pt",
    "robin_molperturbation": "robin_bothaug_molperturbation.pt",
}

VARIANT_SCORE_COLS = {
    "full": "rnasmol_probability",
    "constant_train_rna": "rnasmol_constant_rna_probability",
    "shuffled_test_rna": "rnasmol_shuffled_rna_probability",
    "zero_rna": "rnasmol_zero_rna_probability",
}


def parse_args() -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo_root", type=Path, default=repo_root)
    parser.add_argument("--rnasmol_root", type=Path, default=repo_root / "RNAsmol")
    parser.add_argument(
        "--datasets",
        nargs="+",
        default=["robin_netperturbation", "robin_molperturbation"],
        choices=sorted(DEFAULT_DATASET_MODELS),
    )
    parser.add_argument(
        "--output_dir",
        type=Path,
        default=repo_root / "reports" / "rnasmol_rna_context_probe",
    )
    parser.add_argument("--batch_size", type=int, default=256)
    parser.add_argument("--num_workers", type=int, default=0)
    parser.add_argument("--seed", type=int, default=20260620)
    parser.add_argument("--device", default=None)
    return parser.parse_args()


def stable_hash(text: object, length: int = 16) -> str:
    value = "" if pd.isna(text) else str(text)
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:length]


def resolve_device(device_arg: str | None) -> torch.device:
    if device_arg:
        return torch.device(device_arg)
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def patch_torch_load_for_local_pyg_objects() -> None:
    real_load = torch.load

    def compat_load(*args, **kwargs):
        kwargs.setdefault("weights_only", False)
        return real_load(*args, **kwargs)

    torch.load = compat_load  # type: ignore[assignment]


def load_rnasmol_modules(rnasmol_root: Path):
    module_dir = rnasmol_root / "rnasmol"
    sys.path.insert(0, str(module_dir.resolve()))
    from dataset import GNNDataset  # type: ignore
    from model import MCNN_GCN  # type: ignore
    from utils import load_model_dict  # type: ignore

    return GNNDataset, MCNN_GCN, load_model_dict


def relpath(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def stack_targets(dataset) -> torch.Tensor:
    return torch.cat([dataset[i].target.clone() for i in range(len(dataset))], dim=0).long()


def predict_variant(
    *,
    model,
    test_set,
    device: torch.device,
    batch_size: int,
    num_workers: int,
    variant: str,
    constant_target: torch.Tensor,
    shuffled_targets: torch.Tensor,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    loader = DataLoader(test_set, batch_size=batch_size, shuffle=False, num_workers=num_workers)
    probs: list[np.ndarray] = []
    logits_pos: list[np.ndarray] = []
    labels: list[np.ndarray] = []
    offset = 0

    model.eval()
    with torch.no_grad():
        for batch in loader:
            batch.y = batch.y.long()
            n_batch = int(batch.y.numel())
            if variant == "constant_train_rna":
                batch.target = constant_target.repeat(n_batch, 1)
            elif variant == "shuffled_test_rna":
                batch.target = shuffled_targets[offset : offset + n_batch].clone()
            elif variant == "zero_rna":
                batch.target = torch.zeros_like(batch.target)
            elif variant != "full":
                raise ValueError(f"Unknown variant: {variant}")

            batch = batch.to(device)
            _, _, _, logits = model(batch)
            prob = F.softmax(logits, dim=-1)[:, 1]
            probs.append(prob.detach().cpu().numpy())
            logits_pos.append(logits[:, 1].detach().cpu().numpy())
            labels.append(batch.y.detach().cpu().numpy())
            offset += n_batch

    return np.concatenate(probs), np.concatenate(logits_pos), np.concatenate(labels).astype(int)


def row_correlations(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    full = frame[VARIANT_SCORE_COLS["full"]].astype(float)
    for variant, score_col in VARIANT_SCORE_COLS.items():
        if variant == "full":
            continue
        score = frame[score_col].astype(float)
        rows.append(
            {
                "dataset": frame["dataset"].iloc[0],
                "variant": variant,
                "score_col": score_col,
                "pearson_vs_full": float(full.corr(score, method="pearson")),
                "spearman_vs_full": float(full.corr(score, method="spearman")),
                "mean_abs_delta_vs_full": float((full - score).abs().mean()),
                "max_abs_delta_vs_full": float((full - score).abs().max()),
            }
        )
    return pd.DataFrame(rows)


def predict_dataset(
    *,
    repo_root: Path,
    rnasmol_root: Path,
    dataset_name: str,
    model_filename: str,
    device: torch.device,
    batch_size: int,
    num_workers: int,
    seed: int,
    GNNDataset,
    MCNN_GCN,
    load_model_dict,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    dataset_root = rnasmol_root / "rnasmol" / "data" / dataset_name
    raw_test_path = dataset_root / "raw" / "data_test.csv"
    model_path = rnasmol_root / "saved_model" / model_filename
    if not raw_test_path.exists():
        raise FileNotFoundError(raw_test_path)
    if not model_path.exists():
        raise FileNotFoundError(model_path)

    raw = pd.read_csv(raw_test_path).rename(
        columns={
            "compound_iso_smiles": "smiles",
            "target_sequence": "rna_sequence",
            "affinity": "label",
        }
    )
    raw["label"] = pd.to_numeric(raw["label"], errors="coerce").astype(int)

    train_set = GNNDataset(str(dataset_root.resolve()), types="train")
    test_set = GNNDataset(str(dataset_root.resolve()), types="test")
    if len(test_set) != len(raw):
        raise ValueError(f"{dataset_name}: raw rows {len(raw)} != processed rows {len(test_set)}")

    constant_target = train_set[0].target.clone().long()
    test_targets = stack_targets(test_set)
    rng = np.random.default_rng(seed + stable_int(dataset_name))
    shuffled_targets = test_targets[torch.as_tensor(rng.permutation(len(test_targets)), dtype=torch.long)]

    model = MCNN_GCN(3, 25 + 1, embedding_size=96, filter_num=32, out_dim=2, ban_heads=2).to(device)
    load_model_dict(model, str(model_path.resolve()), map_location=device)

    out = raw.copy().reset_index(drop=True)
    out["benchmark_family"] = "RNAsmol"
    out["dataset"] = dataset_name
    out["dataset_kind"] = "robin_perturbation"
    out["split"] = "test"
    out["source_path"] = relpath(raw_test_path, repo_root)
    out["original_row_index"] = out.index.astype(int)
    out["target_id"] = "rna_" + out["rna_sequence"].map(stable_hash)
    out["compound_id"] = "cmp_" + out["smiles"].map(stable_hash)
    out["candidate_pool_id"] = out["dataset"] + ":" + out["split"] + ":" + out["target_id"]
    out["rnasmol_model_name"] = model_filename
    out["rnasmol_model_path"] = relpath(model_path, repo_root)

    label_match_by_variant = {}
    for variant, score_col in VARIANT_SCORE_COLS.items():
        prob, logit_pos, processed_label = predict_variant(
            model=model,
            test_set=test_set,
            device=device,
            batch_size=batch_size,
            num_workers=num_workers,
            variant=variant,
            constant_target=constant_target,
            shuffled_targets=shuffled_targets,
        )
        out[score_col] = prob
        out[score_col.replace("_probability", "_logit_positive")] = logit_pos
        label_match_by_variant[variant] = bool(np.array_equal(out["label"].to_numpy(dtype=int), processed_label))

    correlations = row_correlations(out)
    manifest_row = {
        "dataset": dataset_name,
        "model_path": str(model_path.resolve()),
        "n_rows": int(len(out)),
        "n_targets": int(out["target_id"].nunique()),
        "n_compounds": int(out["compound_id"].nunique()),
        "positives": int(out["label"].sum()),
        "negatives": int(len(out) - out["label"].sum()),
        "constant_target_source": "first training row target tensor",
        "shuffled_target_source": "test target tensors shuffled within dataset",
        "label_match_by_variant": label_match_by_variant,
    }
    return out, correlations, manifest_row


def stable_int(text: str) -> int:
    return int(hashlib.sha1(text.encode("utf-8")).hexdigest()[:8], 16)


def main() -> None:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    rnasmol_root = args.rnasmol_root.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    patch_torch_load_for_local_pyg_objects()
    GNNDataset, MCNN_GCN, load_model_dict = load_rnasmol_modules(rnasmol_root)
    device = resolve_device(args.device)

    frames = []
    correlations = []
    manifest_rows = []
    for dataset_name in args.datasets:
        frame, corr, row = predict_dataset(
            repo_root=repo_root,
            rnasmol_root=rnasmol_root,
            dataset_name=dataset_name,
            model_filename=DEFAULT_DATASET_MODELS[dataset_name],
            device=device,
            batch_size=args.batch_size,
            num_workers=args.num_workers,
            seed=args.seed,
            GNNDataset=GNNDataset,
            MCNN_GCN=MCNN_GCN,
            load_model_dict=load_model_dict,
        )
        frames.append(frame)
        correlations.append(corr)
        manifest_rows.append(row)

    predictions = pd.concat(frames, ignore_index=True)
    correlation_table = pd.concat(correlations, ignore_index=True)
    predictions_path = output_dir / "rnasmol_rna_context_probe_predictions.csv"
    correlations_path = output_dir / "rnasmol_rna_context_probe_row_correlations.csv"
    manifest_path = output_dir / "rnasmol_rna_context_probe_manifest.json"
    predictions.to_csv(predictions_path, index=False)
    correlation_table.to_csv(correlations_path, index=False)
    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(repo_root),
        "rnasmol_root": str(rnasmol_root),
        "device": str(device),
        "seed": args.seed,
        "datasets": args.datasets,
        "variant_score_cols": VARIANT_SCORE_COLS,
        "outputs": {
            "predictions": str(predictions_path),
            "row_correlations": str(correlations_path),
        },
        "dataset_summaries": manifest_rows,
        "notes": [
            "This is an inference-time RNA-context perturbation probe, not a retrained ligand-only RNAsmol ablation.",
            "The full saved checkpoint is kept fixed for all variants.",
            "constant_train_rna repeats the first training target tensor for every test compound.",
            "shuffled_test_rna permutes test target tensors within each dataset with a fixed seed.",
            "zero_rna replaces the RNA target tensor with padding-token zeros and should be interpreted as an OOD stress check.",
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"wrote {predictions_path}")
    print(f"wrote {correlations_path}")
    print(f"wrote {manifest_path}")
    print(correlation_table.to_string(index=False))


if __name__ == "__main__":
    main()
