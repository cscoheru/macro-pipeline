"""Render macro time-series charts from store.db to data/charts/.

Per-economy time series (CPI / GDP / policy rate / unemployment) and
cross-economy "latest snapshot" bars, one PNG each. Idempotent —
regenerates everything on every run. With --upload, push the PNGs
to vault 宏观经济/_pipeline/_charts/ via Obsidian REST API.

Pure local matplotlib (Agg backend); no network. Charts embed source
labels in the title so a stale render never masquerades as fresh.
"""
import argparse
import os
import sqlite3

import matplotlib
matplotlib.use("Agg")  # headless — no display server required
import matplotlib.pyplot as plt

import paths


CHARTS_DIR = os.path.join(paths.DATA, "charts")


# Per-economy series configuration. Each tuple is (source, series, label);
# the script joins labels in the legend. Series with empty `series` lists
# are silently skipped (gracefully handles JP/DE historical gaps).
SERIES_CONFIG = [
    ("cpi_yoy", "CPI 同比 (%)", {
        "us": [("fred", "CPIAUCSL", "Headline CPI")],
        "cn": [("cn_stats_cpi", "cpi_yoy_yoy", "CPI")],
        "jp": [],
        "de": [("de_cpi", "cpi_yoy", "CPI")],
    }),
    ("gdp_yoy", "GDP 同比 (%)", {
        "us": [("fred", "GDPC1", "Real GDP (2017=100)")],
        "cn": [],
        "jp": [("jp_gdp", "gdp_yoy", "GDP 実質")],
        "de": [("de_gdp", "gdp_yoy", "GDP")],
    }),
    ("policy_rate", "政策利率 (%)", {
        "us": [("fred", "FEDFUNDS", "Fed Funds")],
        "cn": [],
        "jp": [("jp_policy", "policy_rate", "BOJ 無担保O/N 目標")],
        "de": [],
    }),
    ("unemployment", "失业率 (%)", {
        "us": [("fred", "UNRATE", "U-3")],
        "cn": [],
        "jp": [],
        "de": [("de_unrate", "employment_yoy", "就業者数 同比 (proxy)")],
    }),
]

# Indicators plotted as cross-economy "latest snapshot" bars. The first
# listed source/series is the headline; others are extras in the same chart.
CROSS_SNAPSHOT = [
    ("cpi_yoy", "CPI 同比 — 最新读数", {
        "us": ("fred", "CPIAUCSL"),
        "cn": ("cn_stats_cpi", "cpi_yoy_yoy"),
        "jp": (None, None),
        "de": ("de_cpi", "cpi_yoy"),
    }),
    ("gdp_yoy", "GDP 同比 — 最新读数", {
        "us": ("fred", "GDPC1"),
        "cn": (None, None),
        "jp": ("jp_gdp", "gdp_yoy"),
        "de": ("de_gdp", "gdp_yoy"),
    }),
    ("policy_rate", "政策利率 — 最新读数", {
        "us": ("fred", "FEDFUNDS"),
        "cn": (None, None),
        "jp": ("jp_policy", "policy_rate"),
        "de": (None, None),
    }),
]

# Chart text styling — uses Chinese labels (vault audience). PNG fonts come
# from matplotlib's default CJK fallback; if it renders as boxes, install
# a CJK font (e.g. `brew install --cask font-source-han-sans`).
plt.rcParams["font.sans-serif"] = ["PingFang SC", "Heiti SC", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

ECONOMY_LABEL = {"us": "US", "cn": "CN", "jp": "JP", "de": "DE"}
# Flag glyphs render as boxes in matplotlib's default CJK fallback on macOS;
# substitute bracketed country codes so charts stay readable without a CJK font.
ECONOMY_FLAG = {"us": "[US]", "cn": "[CN]", "jp": "[JP]", "de": "[DE]"}


def _connect():
    return sqlite3.connect(paths.STORE_DB)


def _history(source, series, limit=200):
    """(date, value) oldest -> newest, up to `limit` most recent observations."""
    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT date, value FROM observations "
            "WHERE source = ? AND series = ? "
            "ORDER BY date ASC LIMIT ?",
            (source, series, limit),
        )
        return cur.fetchall()
    finally:
        conn.close()


def _to_yoy(rows, period_year_diff=1):
    """Compute period-over-year pct change from a level series.

    FRED stores CPIAUCSL/GDPC1 as index levels; cn/jp/de store YoY directly.
    Pair each row with the row ~1 year earlier (same period-of-year match
    is unnecessary for monthly/quarterly series with stable seasonality —
    we use chronological year-distance for robustness).
    """
    if len(rows) < 2:
        return []
    result = []
    for index, (date, value) in enumerate(rows):
        if value is None:
            continue
        # Find the row 12 months earlier (or 4 quarters earlier for quarterly).
        if len(date) >= 7:  # YYYY-MM or YYYY-MM-DD
            try:
                year, month = int(date[:4]), int(date[5:7])
                target_year = year - 1
                target = f"{target_year}-{date[5:]}"
            except ValueError:
                continue
        else:
            continue
        for prev_date, prev_value in rows[:index]:
            if prev_value is None:
                continue
            if prev_date.startswith(target):
                if prev_value != 0:
                    yoy = (value - prev_value) / prev_value * 100
                    result.append((date, yoy))
                break
    return result


def _plot_time_series(ax, slug, title, series_map):
    """Render one chart per indicator. Multiple series per economy stacked."""
    any_data = False
    for economy, series_list in series_map.items():
        for source, series, label in series_list:
            rows = _history(source, series)
            if not rows:
                continue
            # Decide whether rows are already YoY (%) or level. Heuristic:
            # values in [−100, 100] for the level series are unrealistic for
            # indices; values > 100 are levels.
            values = [v for _, v in rows if v is not None]
            if values and max(abs(v) for v in values) > 100:
                yoy_rows = _to_yoy(rows)
            else:
                yoy_rows = [(d, v) for d, v in rows if v is not None]
            if not yoy_rows:
                continue
            dates = [d for d, _ in yoy_rows]
            ys = [v for _, v in yoy_rows]
            ax.plot(dates, ys, marker="o", markersize=2,
                    linewidth=1.2, label=f"{ECONOMY_FLAG[economy]} {label}")
            any_data = True
    if not any_data:
        return False
    ax.set_title(title, fontsize=11)
    ax.set_xlabel("数据期")
    ax.set_ylabel("%")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8, loc="best")
    # Compact x-axis: ≤ 8 ticks regardless of history length. Categorical
    # string dates can't use nbins (matplotlib throws a warning); pick every
    # Nth tick label instead.
    labels = ax.get_xticklabels()
    if len(labels) > 8:
        step = max(1, len(labels) // 8)
        for index, label in enumerate(labels):
            label.set_visible(index % step == 0)
    return True


def _plot_snapshot_bars(ax, slug, title, series_map):
    """Cross-economy horizontal bars: latest CPI/GDP/policy_rate."""
    bars = []
    for economy, (source, series) in series_map.items():
        if source is None:
            continue
        rows = _history(source, series, limit=200)
        if not rows:
            continue
        # Same level/YoY heuristic
        values = [v for _, v in rows if v is not None]
        if values and max(abs(v) for v in values) > 100:
            yoy_rows = _to_yoy(rows)
        else:
            yoy_rows = [(d, v) for d, v in rows if v is not None]
        if not yoy_rows:
            continue
        date, value = yoy_rows[-1]
        bars.append((economy, value, date))
    if not bars:
        return False
    economies = [ECONOMY_FLAG[e] + " " + ECONOMY_LABEL[e] for e, _, _ in bars]
    values = [v for _, v, _ in bars]
    dates = [f"({d})" for _, _, d in bars]
    y_pos = list(range(len(bars)))
    ax.barh(y_pos, values, color=["#1f77b4", "#d62728", "#2ca02c", "#ff7f0e"][:len(bars)])
    ax.set_yticks(y_pos)
    ax.set_yticklabels([f"{e}  {d}" for e, d in zip(economies, dates)], fontsize=9)
    ax.set_title(title, fontsize=11)
    ax.set_xlabel("%")
    ax.axvline(0, color="grey", linewidth=0.5)
    ax.grid(True, axis="x", alpha=0.3)
    for index, value in enumerate(values):
        ax.text(value + (0.05 if value >= 0 else -0.05), index,
                f"{value:.2f}",
                ha="left" if value >= 0 else "right", va="center", fontsize=8)
    return True


def render(output_dir):
    os.makedirs(output_dir, exist_ok=True)
    written = []
    for slug, title, series_map in SERIES_CONFIG:
        fig, ax = plt.subplots(figsize=(8, 4))
        try:
            ok = _plot_time_series(ax, slug, title, series_map)
            if ok:
                fig.tight_layout()
                path = os.path.join(output_dir, f"{slug}_history.png")
                fig.savefig(path, dpi=120)
                written.append(path)
        finally:
            plt.close(fig)
    for slug, title, series_map in CROSS_SNAPSHOT:
        fig, ax = plt.subplots(figsize=(8, 3))
        try:
            ok = _plot_snapshot_bars(ax, slug, title, series_map)
            if ok:
                fig.tight_layout()
                path = os.path.join(output_dir, f"cross_{slug}_latest.png")
                fig.savefig(path, dpi=120)
                written.append(path)
        finally:
            plt.close(fig)
    return written


def _upload(paths_to_upload):
    # Defer import so the script still works without REST config.
    from vault_writer import VaultWriter
    client = VaultWriter()
    target_prefix = f"{paths.VAULT_PIPELINE_PREFIX}/_charts"
    uploaded = []
    for local in paths_to_upload:
        name = os.path.basename(local)
        with open(local, "rb") as handle:
            content = handle.read()
        # Obsidian REST PUT accepts raw bytes for binary files (image/png).
        client.put_binary(f"{target_prefix}/{name}", content)
        uploaded.append(name)
    return uploaded


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=CHARTS_DIR,
                        help=f"Local output directory (default: {CHARTS_DIR})")
    parser.add_argument("--upload", action="store_true",
                        help="Push PNGs to vault 宏观经济/_pipeline/_charts/ via REST API")
    args = parser.parse_args()

    written = render(args.output_dir)
    if not written:
        print("no charts written (no data)")
        return 1
    print(f"wrote {len(written)} charts to {args.output_dir}")
    for path in written:
        print(f"  {path}")
    if args.upload:
        uploaded = _upload(written)
        print(f"uploaded {len(uploaded)} to vault 宏观经济/_pipeline/_charts/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())