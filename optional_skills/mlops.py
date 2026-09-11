"""MLOps Skills — model monitoring, drift detection, and training diagnostics."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["model_drift_check", "training_diagnostics", "model_registry_info"]


def model_drift_check(
    reference_data: str | Path,
    current_data: str | Path,
    threshold: float = 0.05,
    **kwargs: Any,
) -> dict[str, Any]:
    """Detect data drift between a reference and current dataset."""
    try:
        import pandas as pd  # noqa: F401
    except ImportError:
        return {"error": "pandas not installed"}

    ref_path = Path(reference_data)
    cur_path = Path(current_data)

    if not ref_path.exists() or not cur_path.exists():
        return {"error": "One or both data files not found"}

    try:
        ref_df = pd.read_csv(ref_path)
        cur_df = pd.read_csv(cur_path)
    except Exception as exc:
        return {"error": f"Failed to read files: {exc}"}

    common_cols = [c for c in ref_df.columns if c in cur_df.columns]
    drifted: list[dict[str, Any]] = []
    drift_scores: list[dict[str, Any]] = []

    for col in common_cols:
        if not pd.api.types.is_numeric_dtype(ref_df[col]):
            continue

        ref_mean = float(ref_df[col].mean())
        cur_mean = float(cur_df[col].mean())

        if ref_mean == 0:
            ref_mean = 1e-9
        drift_pct = abs(cur_mean - ref_mean) / abs(ref_mean)

        entry: dict[str, Any] = {
            "feature": col,
            "ref_mean": round(ref_mean, 4),
            "cur_mean": round(cur_mean, 4),
            "drift_pct": round(drift_pct * 100, 2),
        }
        drift_scores.append(entry)

        if drift_pct > threshold:
            entry["drifted"] = True
            drifted.append(entry)
        else:
            entry["drifted"] = False

    summary = f"{len(drifted)} feature(s) drifted (threshold={threshold * 100}%)"

    return {
        "drifted_features": drifted,
        "drift_scores": drift_scores,
        "summary": summary,
    }


def training_diagnostics(
    log_path: str | Path | None = None,
    log_content: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Diagnose training log files for common ML issues."""
    content = ""
    if log_content:
        content = log_content
    elif log_path:
        p = Path(log_path)
        if p.exists():
            content = p.read_text(encoding="utf-8")
        else:
            return {"issues": [], "metrics": {}, "summary": f"File not found: {log_path}"}

    import re

    loss_vals: list[float] = []
    acc_vals: list[float] = []
    lr_vals: list[float] = []
    issues: list[dict[str, Any]] = []

    for line in content.splitlines():
        loss_m = re.search(r"loss[:=\s]+([0-9.]+)", line, re.IGNORECASE)
        if loss_m:
            loss_vals.append(float(loss_m.group(1)))
        acc_m = re.search(r"(?:acc|accuracy)[:=\s]+([0-9.]+)", line, re.IGNORECASE)
        if acc_m:
            acc_vals.append(float(acc_m.group(1)))
        lr_m = re.search(r"(?:lr|learning_rate)[:=\s]+([0-9.e-]+)", line, re.IGNORECASE)
        if lr_m:
            lr_vals.append(float(lr_m.group(1)))

    if len(loss_vals) >= 2:
        if loss_vals[-1] > loss_vals[0]:
            issues.append({
                "severity": "high",
                "check": "loss_increasing",
                "description": f"Loss increased from {loss_vals[0]:.4f} to {loss_vals[-1]:.4f}",
            })
        elif loss_vals[-1] < loss_vals[0] * 0.01:
            issues.append({
                "severity": "medium",
                "check": "loss_plateau",
                "description": "Loss dropped very rapidly — possible overfitting",
            })

    if len(loss_vals) >= 10:
        recent_std = _std(loss_vals[-10:])
        if recent_std > 0.5:
            issues.append({
                "severity": "medium",
                "check": "loss_unstable",
                "description": f"Loss is unstable in last 10 steps (std={recent_std:.4f})",
            })

    if not lr_vals and "learning rate" in content.lower():
        issues.append({
            "severity": "low",
            "check": "lr_not_found",
            "description": "Could not parse learning rate from log",
        })

    metrics: dict[str, Any] = {
        "final_loss": loss_vals[-1] if loss_vals else None,
        "initial_loss": loss_vals[0] if loss_vals else None,
        "loss_steps": len(loss_vals),
        "final_acc": acc_vals[-1] if acc_vals else None,
        "acc_steps": len(acc_vals),
        "lr_values": lr_vals[-3:] if lr_vals else [],
    }

    summary = (
        f"{len(loss_vals)} loss step(s), "
        f"final={metrics['final_loss']}, "
        f"{len(issues)} issue(s)"
    )

    return {"issues": issues, "metrics": metrics, "summary": summary}


def _std(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean_val = sum(values) / n
    variance = sum((x - mean_val) ** 2 for x in values) / (n - 1)
    return variance ** 0.5


def model_registry_info(
    registry_path: str | Path | None = None,
    model_name: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Query a local model registry directory."""
    if registry_path is None:
        return {"models": [], "summary": "No registry_path provided"}

    p = Path(registry_path)
    if not p.is_dir():
        return {"models": [], "summary": f"Registry path not found: {registry_path}"}

    models: list[dict[str, Any]] = []

    for model_dir in sorted(p.iterdir()):
        if not model_dir.is_dir():
            continue
        if model_name and model_name.lower() not in model_dir.name.lower():
            continue

        info: dict[str, Any] = {
            "name": model_dir.name,
            "path": str(model_dir),
        }

        for ext in ("*.pt", "*.pth", "*.safetensors", "*.onnx", "*.h5"):
            for weight_file in model_dir.glob(ext):
                info["weights_file"] = str(weight_file)
                try:
                    info["size_mb"] = round(weight_file.stat().st_size / 1024 / 1024, 2)
                except OSError:
                    pass
                break

        for meta in ("metadata.json", "model_card.md", "config.json"):
            if (model_dir / meta).exists():
                key = "has_" + meta.replace(".", "_").replace("-", "_")
                info[key] = True

        models.append(info)

    return {
        "models": models,
        "summary": f"{len(models)} model(s) found in {registry_path}",
    }
