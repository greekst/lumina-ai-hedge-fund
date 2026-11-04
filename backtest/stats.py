# -*- coding: utf-8 -*-
"""backtest/stats.py — deterministic inference helpers (seeded; no wall-clock, no global RNG)."""

from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

import numpy as np

SEED = 20261104
Z80 = 2.8016  # z(0.975) + z(0.80)


def iid_ci(x: np.ndarray, n_boot: int = 2000, seed: int = SEED) -> Dict[str, Optional[float]]:
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) < 2:
        return {"lo": None, "hi": None, "se": None}
    rng = np.random.default_rng(seed)
    means = rng.choice(x, size=(n_boot, len(x)), replace=True).mean(axis=1)
    return {"lo": float(np.percentile(means, 2.5)), "hi": float(np.percentile(means, 97.5)), "se": float(means.std(ddof=1))}


def cluster_ci(x: np.ndarray, clusters: Sequence[Any], n_boot: int = 2000, seed: int = SEED) -> Dict[str, Optional[float]]:
    """Cluster (block) bootstrap of the pooled mean: resample whole clusters with replacement.
    Events in the same calendar month share market moves and overlapping return windows, so
    treating them as independent understates the uncertainty."""
    x = np.asarray(x, dtype=float)
    g = np.asarray(list(clusters))
    ok = np.isfinite(x)
    x, g = x[ok], g[ok]
    labels = sorted(set(g.tolist()))
    if len(labels) < 2:
        return {"lo": None, "hi": None, "se": None, "n_clusters": len(labels)}
    sums = np.array([x[g == c].sum() for c in labels])
    cnts = np.array([(g == c).sum() for c in labels], dtype=float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(labels), size=(n_boot, len(labels)))
    means = sums[idx].sum(axis=1) / cnts[idx].sum(axis=1)
    return {"lo": float(np.percentile(means, 2.5)), "hi": float(np.percentile(means, 97.5)),
            "se": float(means.std(ddof=1)), "n_clusters": len(labels)}


def describe(x: np.ndarray, clusters: Optional[Sequence[Any]] = None) -> Dict[str, Any]:
    """Mean, n, iid and (optional) cluster bootstrap CIs, and the minimum detectable effect
    (80% power, 5% two-sided) implied by the cluster SE when available, else the iid SE."""
    x = np.asarray(x, dtype=float)
    fin = x[np.isfinite(x)]
    out: Dict[str, Any] = {"n": int(len(fin)), "mean": float(fin.mean()) if len(fin) else None}
    out["iid"] = iid_ci(x)
    if clusters is not None:
        out["cluster"] = cluster_ci(x, clusters)
    se = (out.get("cluster") or {}).get("se") or out["iid"]["se"]
    out["mde80"] = float(Z80 * se) if se else None
    return out


def cluster_diff(y: np.ndarray, group: np.ndarray, clusters: Sequence[Any], n_boot: int = 2000,
                 seed: int = SEED) -> Dict[str, Optional[float]]:
    """mean(y | group) - mean(y | ~group), with a month-clustered bootstrap CI and MDE.
    Used as 'selection skill': do events a strategy goes long on outperform the ones it skips?
    Unlike the strategy's own return, this is not inflated by how OFTEN it is long."""
    y = np.asarray(y, dtype=float)
    gm = np.asarray(group, dtype=bool)
    g = np.asarray(list(clusters))
    ok = np.isfinite(y)
    y, gm, g = y[ok], gm[ok], g[ok]
    out: Dict[str, Optional[float]] = {"n_in": int(gm.sum()), "n_out": int((~gm).sum()), "mean": None,
                                       "lo": None, "hi": None, "se": None, "mde80": None}
    if gm.sum() < 2 or (~gm).sum() < 2:
        return out
    out["mean"] = float(y[gm].mean() - y[~gm].mean())
    labels = sorted(set(g.tolist()))
    s1 = np.array([y[(g == c) & gm].sum() for c in labels]); n1 = np.array([((g == c) & gm).sum() for c in labels], float)
    s0 = np.array([y[(g == c) & ~gm].sum() for c in labels]); n0 = np.array([((g == c) & ~gm).sum() for c in labels], float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(labels), size=(n_boot, len(labels)))
    with np.errstate(invalid="ignore", divide="ignore"):
        d = s1[idx].sum(1) / n1[idx].sum(1) - s0[idx].sum(1) / n0[idx].sum(1)
    d = d[np.isfinite(d)]
    out.update(lo=float(np.percentile(d, 2.5)), hi=float(np.percentile(d, 97.5)), se=float(d.std(ddof=1)))
    out["mde80"] = float(Z80 * out["se"])
    return out
