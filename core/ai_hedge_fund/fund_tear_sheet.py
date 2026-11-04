# -*- coding: utf-8 -*-
"""
Lumina AI Hedge Fund: Institutional Performance Tear Sheet Engine (pyfolio Inspired)
Generates Wall Street grade performance and risk analytics from trading execution logs.
Produces monthly return heatmaps, underwater drawdown plots, and rolling Sharpe metrics.
"""

import os
import sys
import json
import time
import math
from typing import Dict, Any, List, Optional
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")  # Non-interactive headless backend
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from core.ai_hedge_fund.broker_client import PaperTradingEngine


def _fmt(value, spec: str, suffix: str = "") -> str:
    """Format a KPI or 'n/a' when it could not be computed from recorded data."""
    if value is None:
        return "n/a (insufficient data)"
    return format(value, spec) + suffix


class FundTearSheet:
    """
    Institutional Performance & Risk Tear Sheet Generator (pyfolio architecture).
    Evaluates real trading journey health and exports publication-ready graphics for note.com.
    """

    OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "outputs")
    TEAR_SHEET_PNG = os.path.join(OUTPUT_DIR, "lumina_performance_tearsheet.png")

    @classmethod
    def generate_tear_sheet(cls, broker: Optional[PaperTradingEngine] = None, save_image: bool = True) -> Dict[str, Any]:
        """
        Calculates comprehensive fund metrics and renders the institutional tear sheet chart.
        """
        if not broker:
            broker = PaperTradingEngine()

        positions = broker.get_positions()
        summary = broker.get_portfolio_summary()
        history = getattr(broker, "get_trade_history", lambda: [])()

        # If trade history is empty or short, build simulated real series based on summary
        initial_cash = 100000.0  # $100,000 base
        total_value = float(summary.get("total_portfolio_value_usd", initial_cash))
        realized_pnl = float(summary.get("total_realized_pnl_usd", 0.0))
        unrealized_pnl = float(summary.get("total_unrealized_pnl_usd", 0.0))

        # Build trade-level return series
        trades = []
        if hasattr(broker, "get_closed_positions"):
            trades = broker.get_closed_positions()

        # Compile Key Fund KPIs — all computed from recorded data (audit P0 F8: upstream
        # hard-coded Sharpe 1.94 / Sortino 2.85 / MaxDD -3.8% / win-rate 66.7%). None = not enough data.
        win_trades = [t for t in trades if float(t.get("realized_pnl", 0)) > 0]
        loss_trades = [t for t in trades if float(t.get("realized_pnl", 0)) <= 0]
        total_trades = len(trades)
        win_rate = (len(win_trades) / total_trades * 100.0) if total_trades > 0 else None
        total_gain = sum([float(t.get("realized_pnl", 0)) for t in win_trades])
        total_loss = abs(sum([float(t.get("realized_pnl", 0)) for t in loss_trades]))
        profit_factor = round(total_gain / total_loss, 2) if total_loss > 0 else None
        total_return_pct = round(((total_value - initial_cash) / initial_cash) * 100.0, 2)

        curve = cls._equity_series(broker)
        risk = cls.compute_risk_kpis(curve)

        kpis = {
            "initial_capital_usd": initial_cash,
            "total_portfolio_value_usd": round(total_value, 2),
            "total_net_pnl_usd": round(realized_pnl + unrealized_pnl, 2),
            "cumulative_return_pct": total_return_pct,
            **risk,
            "win_rate_pct": round(win_rate, 1) if win_rate is not None else None,
            "profit_factor": profit_factor,
            "total_trades_count": total_trades,
            "equity_points": len(curve),
            "source": "PaperTradingEngine SQLite (equity_snapshots, closed positions)",
            "as_of": time.strftime("%Y-%m-%d"),
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "_equity_curve": curve,
        }

        if save_image:
            try:
                cls._render_matplotlib_tearsheet(kpis)
            except Exception as e:
                print(f"[FundTearSheet] Image rendering warning: {e}")

        kpis.pop("_equity_curve", None)
        return kpis

    @staticmethod
    def _equity_series(broker) -> List[Any]:
        """[(timestamp, equity_jpy)] from recorded snapshots; never synthesised."""
        try:
            rows = broker.get_equity_curve(limit=5000)
        except Exception:
            return []
        out = []
        for r in rows:
            ts = r.get("snapshot_time") or r.get("created_at") or r.get("timestamp") or r.get("snapshot_id")
            val = r.get("total_equity_jpy")
            if val is not None:
                out.append((ts, float(val)))
        return out

    @staticmethod
    def compute_risk_kpis(curve: List[Any], periods_per_year: int = 252) -> Dict[str, Any]:
        """Deterministic risk KPIs from an equity series; None when < 20 observations."""
        empty = {"annualized_volatility_pct": None, "sharpe_ratio": None, "sortino_ratio": None,
                 "calmar_ratio": None, "max_drawdown_pct": None}
        vals = np.array([v for _, v in curve], dtype=float)
        if len(vals) < 20 or np.any(vals <= 0):
            return empty
        rets = vals[1:] / vals[:-1] - 1.0
        vol = float(rets.std(ddof=1) * np.sqrt(periods_per_year))
        mean_ann = float(rets.mean() * periods_per_year)
        downside = rets[rets < 0]
        dd = vals / np.maximum.accumulate(vals) - 1.0
        max_dd = float(dd.min())
        return {
            "annualized_volatility_pct": round(vol * 100.0, 2),
            "sharpe_ratio": round(mean_ann / vol, 2) if vol > 0 else None,
            "sortino_ratio": round(mean_ann / float(downside.std(ddof=1) * np.sqrt(periods_per_year)), 2) if len(downside) > 1 and downside.std(ddof=1) > 0 else None,
            "calmar_ratio": round(mean_ann / abs(max_dd), 2) if max_dd < 0 else None,
            "max_drawdown_pct": round(max_dd * 100.0, 2),
        }

    @classmethod
    def _render_matplotlib_tearsheet(cls, kpis: Dict[str, Any]):
        """Render high-resolution 3-panel tear sheet chart (Dark Cyberpunk Theme)"""
        os.makedirs(cls.OUTPUT_DIR, exist_ok=True)

        fig = plt.figure(figsize=(12, 8), dpi=150)
        fig.patch.set_facecolor("#030712")  # Deep cyber dark

        # Grid setup: 2 rows (Top: Cumulative Return & Underwater Drawdown, Bottom: Monthly Table / KPIs)
        gs = fig.add_gridspec(2, 2, height_ratios=[1.2, 1.0], hspace=0.35, wspace=0.25)

        # 1. Panel 1: Cumulative Equity Curve (Simulated Chronological Curve)
        ax1 = fig.add_subplot(gs[0, :])
        ax1.set_facecolor("#0b0f19")
        
        curve = kpis.get("_equity_curve") or []
        if len(curve) >= 2:
            dates = list(range(len(curve)))
            equity_curve = np.array([v for _, v in curve], dtype=float)
        else:
            dates, equity_curve = [0, 1], np.array([np.nan, np.nan])
            ax1.text(0.5, 0.5, "No recorded equity snapshots yet", color="#94a3b8", ha="center", transform=ax1.transAxes)
        ax1.plot(dates, equity_curve, color="#00f0ff", linewidth=2.2, label="Recorded equity (JPY, equity_snapshots)")
        ax1.fill_between(dates, np.nanmin(equity_curve) if np.isfinite(equity_curve).any() else 0.0, equity_curve, color="#00f0ff", alpha=0.12)
        ax1.set_title("LUMINA CAPITAL — CUMULATIVE PORTFOLIO EQUITY (NAV)", color="#f8fafc", fontsize=12, fontweight="bold", pad=10)
        ax1.tick_params(colors="#94a3b8", labelsize=9)
        ax1.yaxis.set_major_formatter("¥{x:,.0f}")
        for spine in ax1.spines.values():
            spine.set_color("#1e293b")
        ax1.grid(True, color="#1e293b", linestyle=":", alpha=0.6)
        ax1.legend(loc="upper left", facecolor="#0b0f19", edgecolor="#1e293b", labelcolor="#f8fafc", fontsize=9)

        # 2. Panel 2: Underwater Drawdown Plot
        ax2 = fig.add_subplot(gs[1, 0])
        ax2.set_facecolor("#0b0f19")

        peaks = np.maximum.accumulate(equity_curve)
        drawdown = (equity_curve - peaks) / peaks * 100.0

        ax2.plot(dates, drawdown, color="#ff0055", linewidth=1.8, label="Underwater DD (%)")
        ax2.fill_between(dates, 0, drawdown, color="#ff0055", alpha=0.25)
        ax2.set_title("UNDERWATER DRAWDOWN PROFILE (MAX DD %)", color="#f8fafc", fontsize=10, fontweight="bold", pad=10)
        ax2.tick_params(colors="#94a3b8", labelsize=8)
        ax2.yaxis.set_major_formatter("{x:.1f}%")
        for spine in ax2.spines.values():
            spine.set_color("#1e293b")
        ax2.grid(True, color="#1e293b", linestyle=":", alpha=0.6)
        ax2.legend(loc="lower left", facecolor="#0b0f19", edgecolor="#1e293b", labelcolor="#f8fafc", fontsize=8)

        # 3. Panel 3: Key Performance Diagnostic Table (KPIs)
        ax3 = fig.add_subplot(gs[1, 1])
        ax3.set_facecolor("#0b0f19")
        ax3.axis("off")

        kpi_rows = [
            ["Cumulative Return", _fmt(kpis.get("cumulative_return_pct"), "+.2f", "%")],
            ["Annualized Volatility", _fmt(kpis.get("annualized_volatility_pct"), ".1f", "%")],
            ["Sharpe Ratio", _fmt(kpis.get("sharpe_ratio"), ".2f", "")],
            ["Sortino Ratio", _fmt(kpis.get("sortino_ratio"), ".2f", "")],
            ["Calmar Ratio", _fmt(kpis.get("calmar_ratio"), ".2f", "")],
            ["Max Drawdown", _fmt(kpis.get("max_drawdown_pct"), ".1f", "%")],
            ["Win Rate", _fmt(kpis.get("win_rate_pct"), ".1f", "%")],
            ["Profit Factor", _fmt(kpis.get("profit_factor"), ".2f", "")],
            ["CRO Veto Enforced", "YES (Strict)"]
        ]

        table = ax3.table(
            cellText=kpi_rows,
            colLabels=["Diagnostic Metric", "Fund Score"],
            loc="center",
            cellLoc="left"
        )
        table.auto_set_font_size(False)
        table.set_fontsize(9)
        table.scale(1.0, 1.4)

        for (row, col), cell in table.get_celld().items():
            cell.set_edgecolor("#1e293b")
            if row == 0:
                cell.set_facecolor("#0f172a")
                cell.set_text_props(color="#38bdf8", fontweight="bold")
            else:
                cell.set_facecolor("#0b0f19")
                cell.set_text_props(color="#f8fafc" if col == 1 else "#94a3b8")

        plt.savefig(cls.TEAR_SHEET_PNG, bbox_inches="tight", facecolor=fig.get_facecolor(), edgecolor="none")
        plt.close(fig)
        print(f"[FundTearSheet] Institutional Tear Sheet exported to: {cls.TEAR_SHEET_PNG}")
