"""Train a representation-matched ligand-only RNAsmol probe.

This probe keeps the RNAsmol ligand GCN architecture and classifier input
dimension, but replaces the target-specific RNA encoder output with a learned
global null RNA vector. It is intended as a quick go/no-go experiment before a
full multi-seed ablation.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from sklearn.metrics import average_precision_score, roc_auc_score
from torch_geometric.loader import DataLoader


DEFAULT_DATASETS = ["robin_netperturbation"]


def parse_args() -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo_root", type=Path, default=repo_root)
    parser.add_argument("--rnasmol_root", type=Path, default=repo_root / "RNAsmol")
    parser.add_argument("--datasets", nargs="+", default=DEFAULT_DATASETS)
    parser.add_argument(
        "--full_predictions_csv",
        type=Path,
        default=repo_root / "reports" / "rnasmol_model_predictions" / "rnasmol_saved_model_predictions.csv",
    )
    parser.add_argument(
        "--output_dir",
        type=Path,
        default=repo_root / "reports" / "rnasmol_ligand_only_probe" / "training_probe",
    )
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--batch_size", type=int, default=2048)
    parser.add_argument("--num_workers", type=int, default=0)
    parser.add_argument("--lr", type=float, default=5e-5)
    parser.add_argument("--seed", type=int, default=20260620)
    parser.add_argument("--device", default=None)
    return parser.parse_args()


def stable_hash(text: object, length: int = 16) -> str:
    value = "" if pd.isna(text) else str(text)
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:length]


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


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
    from model import GCNNet  # type: ignore

    return GNNDataset, GCNNet


class RNAsmolLigandOnlyProbe(nn.Module):
    def __init__(self, GCNNet, filter_num: int = 32, out_dim: int = 2):
        super().__init__()
        self.ligand_encoder = GCNNet(num_features_xd=87, output_dim=filter_num * 3, dropout=0.5)
        self.null_rna = nn.Parameter(torch.zeros(1, 96))
        nn.init.normal_(self.null_rna, mean=0.0, std=0.02)
        self.classifier = nn.Sequential(
            nn.Linear(filter_num * 3 * 2, 1024),
            nn.ReLU(),
            nn.Dropout(0.5),
            nn.Linear(1024, 1024),
            nn.ReLU(),
            nn.Dropout(0.5),
            nn.Linear(1024, 256),
            nn.ReLU(),
            nn.Dropout(0.5),
            nn.Linear(256, out_dim),
        )

    def forward(self, data):
        ligand_x = self.ligand_encoder(data)
        protein_x = self.null_rna.expand(ligand_x.size(0), -1)
        logits = self.classifier(torch.cat([protein_x, ligand_x], dim=-1))
        return ligand_x, protein_x, None, logits


def safe_auc(y_true: np.ndarray, probs: np.ndarray) -> float:
    if np.unique(y_true).size != 2:
        return float("nan")
    return float(roc_auc_score(y_true, probs))


def safe_aupr(y_true: np.ndarray, probs: np.ndarray) -> float:
    if np.unique(y_true).size != 2:
        return float("nan")
    return float(average_precision_score(y_true, probs))


def evaluate(model, loader, criterion, device: torch.device) -> dict[str, object]:
    model.eval()
    losses = []
    probs = []
    logits_pos = []
    labels = []
    with torch.no_grad():
        for batch in loader:
            batch.y = batch.y.long()
            batch = batch.to(device)
            _, _, _, logits = model(batch)
            loss = criterion(logits, batch.y)
            prob = F.softmax(logits, dim=-1)[:, 1]
            losses.append(float(loss.item()) * int(batch.y.numel()))
            probs.append(prob.detach().cpu().numpy())
            logits_pos.append(logits[:, 1].detach().cpu().numpy())
            labels.append(batch.y.detach().cpu().numpy())
    y = np.concatenate(labels).astype(int)
    p = np.concatenate(probs).astype(float)
    lp = np.concatenate(logits_pos).astype(float)
    return {
        "loss": float(np.sum(losses) / max(len(y), 1)),
        "auc": safe_auc(y, p),
        "aupr": safe_aupr(y, p),
        "labels": y,
        "probs": p,
        "logits_pos": lp,
    }


def train_dataset(
    *,
    repo_root: Path,
    rnasmol_root: Path,
    dataset_name: str,
    full_predictions: pd.DataFrame,
    output_dir: Path,
    device: torch.device,
    epochs: int,
    batch_size: int,
    num_workers: int,
    lr: float,
    seed: int,
    GNNDataset,
    GCNNet,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    dataset_root = rnasmol_root / "rnasmol" / "data" / dataset_name
    raw_test_path = dataset_root / "raw" / "data_test.csv"
    raw = pd.read_csv(raw_test_path).rename(
        columns={
            "compound_iso_smiles": "smiles",
            "target_sequence": "rna_sequence",
            "affinity": "label",
        }
    )
    raw["label"] = pd.to_numeric(raw["label"], errors="coerce").astype(int)

    train_set = GNNDataset(str(dataset_root.resolve()), types="train")
    val_set = GNNDataset(str(dataset_root.resolve()), types="val")
    test_set = GNNDataset(str(dataset_root.resolve()), types="test")
    train_loader = DataLoader(train_set, batch_size=batch_size, shuffle=True, num_workers=num_workers)
    val_loader = DataLoader(val_set, batch_size=batch_size, shuffle=False, num_workers=num_workers)
    test_loader = DataLoader(test_set, batch_size=batch_size, shuffle=False, num_workers=num_workers)

    model = RNAsmolLigandOnlyProbe(GCNNet).to(device)
    optimizer = optim.Adam(model.parameters(), lr=lr)
    criterion = nn.CrossEntropyLoss()

    best_state = copy.deepcopy(model.state_dict())
    best_val_aupr = -float("inf")
    best_epoch = -1
    logs = []
    started = time.perf_counter()
    for epoch in range(epochs):
        model.train()
        train_loss_sum = 0.0
        n_train = 0
        for batch in train_loader:
            batch.y = batch.y.long()
            batch = batch.to(device)
            _, _, _, logits = model(batch)
            loss = criterion(logits, batch.y)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            train_loss_sum += float(loss.item()) * int(batch.y.numel())
            n_train += int(batch.y.numel())

        val = evaluate(model, val_loader, criterion, device)
        test = evaluate(model, test_loader, criterion, device)
        train_loss = train_loss_sum / max(n_train, 1)
        logs.append(
            {
                "dataset": dataset_name,
                "epoch": epoch,
                "train_loss": train_loss,
                "val_loss": val["loss"],
                "val_auc": val["auc"],
                "val_aupr": val["aupr"],
                "test_loss": test["loss"],
                "test_auc": test["auc"],
                "test_aupr": test["aupr"],
            }
        )
        if float(val["aupr"]) > best_val_aupr:
            best_val_aupr = float(val["aupr"])
            best_epoch = epoch
            best_state = copy.deepcopy(model.state_dict())

    model.load_state_dict(best_state)
    test = evaluate(model, test_loader, criterion, device)

    out = raw.copy().reset_index(drop=True)
    out["benchmark_family"] = "RNAsmol"
    out["dataset"] = dataset_name
    out["dataset_kind"] = "robin_perturbation"
    out["split"] = "test"
    out["original_row_index"] = out.index.astype(int)
    out["target_id"] = "rna_" + out["rna_sequence"].map(stable_hash)
    out["compound_id"] = "cmp_" + out["smiles"].map(stable_hash)
    out["candidate_pool_id"] = out["dataset"] + ":" + out["split"] + ":" + out["target_id"]
    out["rnasmol_ligand_only_probe_probability"] = test["probs"]
    out["rnasmol_ligand_only_probe_logit_positive"] = test["logits_pos"]

    full_cols = ["dataset", "original_row_index", "rnasmol_probability"]
    full = full_predictions.loc[full_predictions["dataset"] == dataset_name, full_cols].copy()
    out = out.merge(full, on=["dataset", "original_row_index"], how="left", validate="one_to_one")
    if out["rnasmol_probability"].isna().any():
        raise ValueError(f"{dataset_name}: missing full RNAsmol predictions after merge")

    log_frame = pd.DataFrame(logs)
    summary = {
        "dataset": dataset_name,
        "seed": seed,
        "epochs": epochs,
        "best_epoch_by_val_aupr": int(best_epoch),
        "best_val_aupr": best_val_aupr,
        "final_best_test_auc": test["auc"],
        "final_best_test_aupr": test["aupr"],
        "n_train": int(len(train_set)),
        "n_val": int(len(val_set)),
        "n_test": int(len(test_set)),
        "runtime_seconds": float(time.perf_counter() - started),
    }
    return out, log_frame, summary


def main() -> None:
    args = parse_args()
    set_seed(args.seed)
    repo_root = args.repo_root.resolve()
    rnasmol_root = args.rnasmol_root.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    patch_torch_load_for_local_pyg_objects()
    GNNDataset, GCNNet = load_rnasmol_modules(rnasmol_root)
    device = resolve_device(args.device)
    full_predictions = pd.read_csv(args.full_predictions_csv)

    frames = []
    logs = []
    summaries = []
    for dataset_name in args.datasets:
        frame, log, summary = train_dataset(
            repo_root=repo_root,
            rnasmol_root=rnasmol_root,
            dataset_name=dataset_name,
            full_predictions=full_predictions,
            output_dir=output_dir,
            device=device,
            epochs=args.epochs,
            batch_size=args.batch_size,
            num_workers=args.num_workers,
            lr=args.lr,
            seed=args.seed,
            GNNDataset=GNNDataset,
            GCNNet=GCNNet,
        )
        frames.append(frame)
        logs.append(log)
        summaries.append(summary)

    predictions = pd.concat(frames, ignore_index=True)
    training_log = pd.concat(logs, ignore_index=True)
    predictions_path = output_dir / "rnasmol_ligand_only_training_probe_predictions.csv"
    training_log_path = output_dir / "rnasmol_ligand_only_training_probe_log.csv"
    manifest_path = output_dir / "rnasmol_ligand_only_training_probe_manifest.json"
    predictions.to_csv(predictions_path, index=False)
    training_log.to_csv(training_log_path, index=False)
    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(repo_root),
        "rnasmol_root": str(rnasmol_root),
        "full_predictions_csv": str(args.full_predictions_csv.resolve()),
        "device": str(device),
        "seed": args.seed,
        "epochs": args.epochs,
        "batch_size": args.batch_size,
        "lr": args.lr,
        "datasets": args.datasets,
        "outputs": {
            "predictions": str(predictions_path),
            "training_log": str(training_log_path),
        },
        "dataset_summaries": summaries,
        "notes": [
            "This is a 1-seed probe unless multiple seeds are run separately.",
            "The model keeps the RNAsmol ligand GCN architecture and classifier dimensions.",
            "Target-specific RNA input is replaced by a learned global null RNA vector.",
            "Best epoch is selected by validation AUPR.",
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"wrote {predictions_path}")
    print(f"wrote {training_log_path}")
    print(f"wrote {manifest_path}")
    print(pd.DataFrame(summaries).to_string(index=False))


if __name__ == "__main__":
    main()
