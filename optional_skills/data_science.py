"""Data Science Skills — EDA, feature analysis, and visualization."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["eda", "feature_analysis", "data_quality_report"]


def eda(
    data_path: str | Path,
    max_rows: int = 10000,
    **kwargs: Any,
) -> dict[str, Any]:
    """Perform exploratory data analysis on a CSV or Parquet file.

    Args:
        data_path: Path to the data file (CSV or Parquet).
        max_rows: Maximum rows to sample for analysis.

    Returns:
        A dict with 'stats' (summary stats), 'columns', 'types', 'missing', 'summary'.
    """
    p = Path(data_path)
    if not p.exists():
        return {"error": f"File not found: {data_path}"}

    try:
        import pandas as pd
    except ImportError:
        return {"error": "pandas not installed — run: pip install pandas"}

    try:
        if p.suffix.lower() == ".parquet":
            df = pd.read_parquet(p)
        else:
            df = pd.read_csv(p, nrows=max_rows)
    except Exception as exc:
        return {"error": f"Failed to read file: {exc}"}

    stats = {}
    try:
        stats["num_rows"] = len(df)
        stats["num_cols"] = len(df.columns)
        stats["num_cells"] = int(df.size)
        stats["memory_mb"] = round(df.memory_usage(deep=True).sum() / 1024 / 1024, 2)
    except Exception:
        pass

    columns: list[dict[str, Any]] = []
    for col in df.columns:
        dtype = str(df[col].dtype)
        missing = int(df[col].isna().sum())
        missing_pct = round(missing / len(df) * 100, 1) if len(df) > 0 else 0

        col_info: dict[str, Any] = {
            "name": col,
            "dtype": dtype,
            "missing_count": missing,
            "missing_pct": missing_pct,
        }

        if pd.api.types.is_numeric_dtype(df[col]):
            try:
                col_info["mean"] = round(float(df[col].mean()), 4)
                col_info["std"] = round(float(df[col].std()), 4)
                col_info["min"] = round(float(df[col].min()), 4)
                col_info["max"] = round(float(df[col].max()), 4)
            except Exception:
                pass
        else:
            col_info["unique_count"] = int(df[col].nunique())
            col_info["top_values"] = (
                df[col].value_counts().head(3).to_dict()
            )

        columns.append(col_info)

    summary = (
        f"Dataset: {stats.get('num_rows', '?')} rows × "
        f"{stats.get('num_cols', '?')} cols, "
        f"{stats.get('memory_mb', '?')} MB"
    )

    return {
        "stats": stats,
        "columns": columns,
        "summary": summary,
    }


def feature_analysis(
    data_path: str | Path,
    target_col: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Analyze features for a machine learning dataset.

    Args:
        data_path: Path to a CSV or Parquet file.
        target_col: Target column name for correlation analysis.

    Returns:
        A dict with 'features' (per-feature analysis) and 'correlations'.
    """
    p = Path(data_path)
    if not p.exists():
        return {"error": f"File not found: {data_path}"}

    try:
        import pandas as pd
    except ImportError:
        return {"error": "pandas not installed"}

    try:
        df = pd.read_csv(p)
    except Exception as exc:
        return {"error": f"Failed to read file: {exc}"}

    features: list[dict[str, Any]] = []
    for col in df.columns:
        dtype = str(df[col].dtype)
        numeric = pd.api.types.is_numeric_dtype(df[col])

        feature_info: dict[str, Any] = {
            "name": col,
            "dtype": dtype,
            "is_numeric": numeric,
            "missing_pct": round(df[col].isna().mean() * 100, 2),
            "cardinality": int(df[col].nunique()),
        }

        if numeric:
            try:
                corr = 0.0
                if target_col and target_col in df.columns and pd.api.types.is_numeric_dtype(df[target_col]):
                    corr = round(float(df[col].corr(df[target_col])), 4)
                    feature_info["target_correlation"] = corr
            except Exception:
                pass

        features.append(feature_info)

    return {"features": features, "summary": f"{len(features)} features analyzed"}


def data_quality_report(
    data_path: str | Path,
    **kwargs: Any,
) -> dict[str, Any]:
    """Generate a comprehensive data quality report.

    Args:
        data_path: Path to a CSV or Parquet file.

    Returns:
        A dict with 'issues', 'scores', and 'summary'.
    """
    p = Path(data_path)
    if not p.exists():
        return {"error": f"File not found: {data_path}"}

    try:
        import pandas as pd
    except ImportError:
        return {"error": "pandas not installed"}

    try:
        df = pd.read_csv(p)
    except Exception as exc:
        return {"error": f"Failed to read file: {exc}"}

    issues: list[dict[str, Any]] = []
    scores: dict[str, Any] = {}

    total_cells = int(df.size)
    total_missing = int(df.isna().sum().sum())
    completeness = round((total_cells - total_missing) / total_cells * 100, 2) if total_cells > 0 else 100
    scores["completeness"] = completeness

    if completeness < 80:
        issues.append({
            "severity": "high",
            "check": "completeness",
            "description": f"Only {completeness}% of cells have values",
        })

    for col in df.columns:
        if df[col].isna().mean() > 0.5:
            issues.append({
                "severity": "medium",
                "check": "column_missing",
                "column": col,
                "description": f"{col} has {round(df[col].isna().mean()*100,1)}% missing values",
            })

    duplicate_rows = int(df.duplicated().sum())
    dup_pct = round(duplicate_rows / len(df) * 100, 2) if len(df) > 0 else 0
    scores["duplicate_pct"] = dup_pct

    if duplicate_rows > 0:
        issues.append({
            "severity": "medium",
            "check": "duplicates",
            "description": f"{duplicate_rows} duplicate rows ({dup_pct}%)",
        })

    return {
        "issues": issues,
        "scores": scores,
        "summary": f"Completeness: {completeness}%, Duplicates: {dup_pct}%, {len(issues)} issue(s)",
    }
