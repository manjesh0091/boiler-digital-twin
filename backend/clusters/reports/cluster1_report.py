"""
clusters/reports/cluster1_report.py — Cluster 1 standalone validation report.

Trains Cluster 1's baseline on the first 20% of each calendar month
(monthly-stratified — see shared/chronological_split.py) only, then runs
the validator across the remaining ~80% — genuinely unseen data the
baseline never saw (see clusters/cluster_baseline.py's docstring for the
full split / STEADY-filter / quality-filter methodology). Writes both a
Markdown report (cluster1_report.md) and a native Word document
(cluster1_report.docx, via markdown_to_docx.py) — the .docx is generated
programmatically every run, not a manual "Save As Word" step.

Standalone by design: does not import server.py, does not touch the
frontend, does not require the webapp running. Only reads the raw CSV
(via shared/raw_loader.py) and Cluster 1's own config/baseline/validator
modules.

Usage:
    python -m clusters.reports.cluster1_report
    (run from backend/, so the shared/engine/clusters packages resolve)
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from clusters.cluster_baseline import Cluster1Baseline
from clusters.cluster_features import build_cluster_view
from clusters.cluster_validator import validate_dataframe
from clusters.reports.markdown_to_docx import write_docx
from shared.feature_extraction import load_config
from shared.raw_loader import load_raw

OUT_PATH = Path(__file__).parent / "cluster1_report.md"
DOCX_OUT_PATH = Path(__file__).parent / "cluster1_report.docx"
CLUSTER_CONFIG_PATH = Path(__file__).parent.parent / "cluster_config.yaml"

STATUS_ORDER = ["consistent", "outlier", "ambiguous", "unknown"]

# Summary stats from the report's PRE-FIX run (full 91,767-row dataset used
# for both training AND scoring -- data leakage; no chronological split, no
# STEADY-only training filter beyond what cluster_baseline.py already did,
# no stale/spike/known-bad-timestamp exclusion). Kept only for the
# before/after comparison in section 1 -- not recomputed each run.
BEFORE_FIX_SUMMARY = {
    "steam_flow_ab_balance_status": {"consistent": 91763, "outlier": 3, "ambiguous": 1},
    "water_steam_balance_status": {"consistent": 86719, "outlier": 7, "ambiguous": 5041},
    "air_vs_load_envelope_status": {"consistent": 74297, "outlier": 2460, "unknown": 15010},
    "sa_ab_balance_status": {"consistent": 72692, "outlier": 4293, "unknown": 14782},
    "ta_ab_balance_status": {"consistent": 88439, "outlier": 3100, "unknown": 228},
}
BEFORE_FIX_TOTAL = 91767

# Summary stats from the intermediate run: leakage fixed (chronological
# split + STEADY filter + quality filter), but still a single
# first-20%-of-the-YEAR block (2024-01-18 -> 2024-03-27) rather than
# monthly stratification. Kept only to demonstrate, quantitatively, that
# switching to a monthly-stratified split resolves the seasonal-drift
# problem that split exposed -- not recomputed each run.
SINGLE_CUTOFF_SPLIT_SUMMARY = {
    "air_vs_load_envelope_status": {"consistent": 33947, "outlier": 26933, "unknown": 10817},
    "sa_ab_balance_status": {"consistent": 50969, "outlier": 9911, "unknown": 10817},
}
SINGLE_CUTOFF_SPLIT_TOTAL = 71697


# --------------------------------------------------------------------------
# pipeline
# --------------------------------------------------------------------------

def run_pipeline():
    raw = load_raw()
    cluster_config = load_config(CLUSTER_CONFIG_PATH)
    full_view = build_cluster_view(raw, cluster_config)
    baseline = Cluster1Baseline(raw_df=raw, cluster_config=cluster_config)
    results = validate_dataframe(baseline.test_view, baseline, cluster_config)
    return raw, full_view, baseline, results, cluster_config


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _status_table(results: pd.DataFrame, status_col: str) -> str:
    counts = results[status_col].value_counts()
    total = len(results)
    lines = ["| status | rows | % |", "|---|---:|---:|"]
    for status in STATUS_ORDER:
        n = int(counts.get(status, 0))
        if n == 0 and status not in counts.index:
            continue
        lines.append(f"| {status} | {n:,} | {n / total * 100:.2f}% |")
    return "\n".join(lines)


def _frozen_streaks(view: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    rows = []
    for c in columns:
        s = view[c]
        same_as_prev = (s == s.shift(1)) & s.notna()
        streak = same_as_prev.groupby((~same_as_prev).cumsum()).cumsum()
        max_streak = int(streak.max()) if len(streak) else 0
        end_ts = view.loc[streak.idxmax(), "Timestamp"] if max_streak > 0 else None
        start_ts = view.loc[streak.idxmax() - max_streak + 1, "Timestamp"] if max_streak > 0 else None
        rows.append({"column": c, "max_streak_rows": max_streak, "max_streak_minutes": max_streak * 5,
                      "start": start_ts, "end": end_ts})
    return pd.DataFrame(rows)


def _nan_gap_periods(view: pd.DataFrame, column: str) -> pd.DataFrame:
    nan_mask = view[column].isna()
    if not nan_mask.any():
        return pd.DataFrame(columns=["first", "last", "n_rows"])
    blocks = (nan_mask != nan_mask.shift()).cumsum()[nan_mask]
    grp = view.loc[nan_mask].groupby(blocks)
    summary = grp.agg(first=("Timestamp", "first"), last=("Timestamp", "last"), n_rows=("Timestamp", "size"))
    return summary.sort_values("n_rows", ascending=False).reset_index(drop=True)


# --------------------------------------------------------------------------
# report sections
# --------------------------------------------------------------------------

def section_header(raw: pd.DataFrame) -> str:
    return f"""# Cluster 1 — Load-Flow Mass Balance — Validation Report

Generated by `clusters/reports/cluster1_report.py`. Standalone analysis — does
not touch `server.py`, `engine/`, or the frontend; the webapp does not need
to be running to reproduce this.

**Source:** `data/raw/boiler9_cleaned_2024.csv` — {len(raw):,} rows, full 2024,
5-minute sampling interval, Hindalco Boiler-9 (CFBC, Unit 4).
"""


def section_methodology(baseline: Cluster1Baseline) -> str:
    si = baseline.split_info
    parts = ["## 1. Methodology — Chronological Train/Test Split & Training-Data Hygiene\n"]
    parts.append(
        "Everything in this report downstream of this section is scored "
        "**only on the test window** — data the baseline never saw. This "
        "fixes a data-leakage bug in the previous version of this report, "
        "which trained the baseline on the full dataset and then scored "
        "that same dataset against it, so every real deviation was already "
        "partly baked into what the baseline considered \"normal.\"\n"
    )
    parts.append("### 1.1 Monthly-stratified split\n")
    parts.append(
        f"Split independently WITHIN each calendar month: the first 20% of "
        f"each month's own observed timestamp span trains the baseline, the "
        f"remaining ~80% is test. This supersedes an earlier version that "
        f"used a single first-20%-of-the-year block (2024-01-18 through "
        f"2024-03-27) — that trained a baseline that never saw a single row "
        f"from June through December, and a genuine seasonal drift in "
        f"several relationships (see §3's investigation) then showed up as "
        f"an inflated outlier rate across the back half of the year, "
        f"reflecting training-window non-representativeness rather than "
        f"real faults. Stratifying by month fixes that while still "
        f"respecting chronological order (never trains on a row using "
        f"information from later in that same month) and real sampling "
        f"gaps ({si['n_gaps_in_full_dataset']} in the full dataset, "
        f"including a full missing month, 2024-06-01 through 2024-06-30 — "
        f"June contributes 0 rows to either split).\n\n"
        f"- **Train:** {si['n_train']:,} rows ({si['train_frac_actual']*100:.1f}% of the dataset)\n"
        f"- **Test:** {si['n_test']:,} rows ({(1 - si['train_frac_actual'])*100:.1f}% of the dataset) "
        f"— **unseen data**, used for every status table and worked example "
        f"in the sections below (§3 onward).\n"
    )
    lines = ["\n| month | total rows | train rows | test rows |", "|---|---:|---:|---:|"]
    for m in si["month_breakdown"]:
        lines.append(f"| {m['month']} | {m['n_rows']:,} | {m['n_train']:,} | {m['n_test']:,} |")
    parts.append("\n".join(lines))
    parts.append(
        "\n(2024-06 is absent — zero rows that month, per the missing-month "
        "gap noted above.)\n"
    )
    parts.append("### 1.2 STEADY-only filtering (within the train window)\n")
    modes_str = ', '.join(f'{k}={v:,}' for k, v in sorted(baseline.train_mode_counts.items(), key=lambda kv: -kv[1]))
    parts.append(
        f"Of the {si['n_train']:,} training-window rows, "
        f"{baseline.n_train_steady:,} ({baseline.n_train_steady / si['n_train'] * 100:.1f}%) "
        f"are classified `STEADY` by `engine/mode_classifier.py` (imported "
        f"directly, not reimplemented). Mode breakdown in the training "
        f"window: {modes_str}. No `STARTUP`/`SHUTDOWN` rows exist anywhere "
        f"in this dataset (consistent with Module 1's own finding), so in "
        f"practice this step only excludes `LOW_LOAD` rows here — applied "
        f"unconditionally regardless, so it stays correct if that ever "
        f"changes. Only the STEADY rows above feed into §1.3.\n"
    )
    parts.append("### 1.3 Data-quality filtering (on top of the STEADY filter)\n")
    parts.append(
        "Even a STEADY-labeled row can carry a brief frozen sensor reading "
        "or an implausible spike that doesn't last long enough to flip the "
        "mode classifier's state — every one of Punarbasu's 9 cluster notes "
        "calls this out separately from operating-state classification. "
        "Three checks, combined per metric column (`shared/data_quality.py`):\n\n"
        "1. **Frozen/stale streaks** — 12+ consecutive identical readings "
        "(60 min). Higher than the live dashboard's 3-row/15-min alerting "
        "threshold: investigating real data showed the live threshold "
        "over-triggers on Module 1's `STACK_TEMPERATURE`/`FEGT` (whole-degree "
        "instrument resolution causes ordinary slow drift to repeat 3+ "
        "times) — raised uniformly for training-exclusion purposes only; "
        "the live per-tick detector is unchanged.\n"
        "2. **Statistically implausible spikes** — >6 rolling-window "
        "standard deviations from a short (5-row) centered rolling median.\n"
        "3. **Known-bad timestamps** — specific rows with positive evidence "
        "of a genuine fault, found via this cluster's own Steam Flow-A/B "
        "tiebreak (§5): `2024-02-11 13:30`, `2024-02-11 14:00` (both fall "
        "inside the training window). The related ambiguous row at "
        "`2024-10-04 11:40` is deliberately NOT excluded — no positive "
        "evidence it's bad, only that the tiebreak couldn't tell.\n"
    )
    lines = ["\n| metric column | rows excluded (stale/spike/known-bad) | of n STEADY training rows |", "|---|---:|---:|"]
    for col, n in baseline.excluded_counts.items():
        lines.append(f"| `{col}` | {n:,} | {baseline.n_train_steady:,} |")
    parts.append("\n".join(lines))
    parts.append(
        "\nAll six metric columns show **0 additional exclusions**: the two "
        "known-bad 2024-02-11 timestamps are already absent from the STEADY "
        "training set (both independently classified `LOW_LOAD` — the same "
        "sensor glitch that corrupted Steam Flow also dragged `UNIT_LOAD` "
        "down, so §1.2's STEADY filter removed them before the quality "
        "filter even ran), and none of Cluster 1's derived ratio/sum "
        "columns exhibit the whole-number quantization that caused "
        "Module 1's stack_temp/fegt over-triggering. The known-bad list is "
        "kept as an explicit, auditable safety net regardless — it would "
        "matter if a future dataset's glitch didn't happen to coincide with "
        "a mode-classifier exclusion.\n"
    )
    return "\n".join(parts) + "\n"


def _monthly_drift_table(view: pd.DataFrame, column: str, load_low: float = 100.0, load_high: float = 110.0) -> str:
    v = view.copy()
    v["_month"] = pd.to_datetime(v["Timestamp"]).dt.to_period("M")
    sub = v[(v["LOAD"] >= load_low) & (v["LOAD"] < load_high)]
    grp = sub.groupby("_month")[column].agg(["mean", "std", "count"])
    lines = ["| month | mean | std | n |", "|---|---:|---:|---:|"]
    for month, row in grp.iterrows():
        lines.append(f"| {month} | {row['mean']:.2f} | {row['std']:.2f} | {int(row['count']):,} |")
    return "\n".join(lines)


def section_parameters_tolerances(cluster_config: dict, baseline: Cluster1Baseline) -> str:
    """Reference table: for each relationship, what feeds it, what's
    checked, what tolerance/band governs consistent-vs-outlier, and where
    that number came from (doc-specified / learned from STEADY historical
    data / a user-configurable default) — built directly from
    cluster_config.yaml + the trained baseline, not hand-typed, so it can't
    drift out of sync with the actual running config.
    """
    rel = cluster_config["relationships"]
    parts = ["## 2. Parameters & Tolerances\n"]
    parts.append(
        "Every check below is defined in `clusters/cluster_config.yaml`. "
        "\"Source\" distinguishes three kinds of number: a value the "
        "technical note specifies explicitly, a value learned from this "
        "run's STEADY training data (and therefore specific to this "
        "dataset/split), or a user-configurable default this project chose "
        "because the doc doesn't give a number — all three are legitimate, "
        "but only the first is non-negotiable.\n"
    )

    def band_desc(metric_column: str, band_width_std: float, unit: str, signed: bool = True) -> str:
        g = baseline._global.get(metric_column)
        if not g:
            return f"mean ± {band_width_std:.1f}×std per load bin (no learned stats available)"
        mean_str = f"{g.mean:+.2f}{unit}" if signed else f"{g.mean:.2f}{unit}"
        return f"mean ± {band_width_std:.1f}×std per load bin — e.g. all-STEADY: {mean_str} ± {g.std:.2f}{unit}"

    rows = [
        {
            "name": "Steam Flow A/B Balance",
            "members": "Steam Flow-A, Steam Flow-B (+ Feedwater Flow for the tiebreak)",
            "check": "|A − B| / avg(A, B) × 100 vs. flat tolerance; if exceeded, correlate each side against Feedwater Flow",
            "tolerance": f"{rel['steam_flow_ab_balance']['tolerance_pct']:.1f}% flat tolerance; tiebreak ambiguous margin {rel['steam_flow_ab_balance']['tiebreak_ambiguous_margin_pct']:.1f} percentage points",
            "source": (
                f"**Doc-specified** ({rel['steam_flow_ab_balance']['tolerance_pct']:.0f}%, "
                f"\"acceptable variation 3% (Example User Input)\", "
                f"{rel['steam_flow_ab_balance']['doc_ref']}) for the tolerance. "
                "Ambiguous margin is a **user-configurable default** "
                "(`cluster_config.yaml: relationships.steam_flow_ab_balance."
                "tiebreak_ambiguous_margin_pct`) — not specified in the doc."
            ),
        },
        {
            "name": "Water-Steam Balance",
            "members": "Feedwater Flow, resolved Total Main Steam Flow (+ Load for the tiebreak)",
            "check": "(Feedwater − Total Steam) / Total Steam × 100 vs. learned band; if exceeded, correlate both sides against Load",
            "tolerance": band_desc("WATER_STEAM_BALANCE_DEV_PCT", rel["water_steam_balance"]["band_width_std"], "%"),
            "source": (
                "**Learned from STEADY historical training data** (§4) — the "
                "doc gives no numeric tolerance for this check, only the "
                "formula. `band_width_std="
                f"{rel['water_steam_balance']['band_width_std']:.1f}` is a "
                "**user-configurable default** (`cluster_config.yaml: "
                "relationships.water_steam_balance.band_width_std`). "
                "Ambiguous margin: same default as Steam A/B "
                f"({rel['water_steam_balance']['tiebreak_ambiguous_margin_pct']:.1f}pp, "
                "also user-configurable)."
            ),
        },
        {
            "name": "Total Combustion Air vs. Load",
            "members": "Total PA Flow, Total SA Flow, Total TA Flow, Load",
            "check": "Total PA + Total SA + Total TA vs. learned load-dependent envelope",
            "tolerance": band_desc("TOTAL_COMBUSTION_AIR", rel["air_vs_load_envelope"]["band_width_std"], " TPH", signed=False),
            "source": (
                "**Learned from STEADY historical training data** (§7) — the "
                "doc specifies the load-dependent-envelope APPROACH but no "
                f"numeric width. `band_width_std={rel['air_vs_load_envelope']['band_width_std']:.1f}` "
                "is a **user-configurable default** (`cluster_config.yaml: "
                "relationships.air_vs_load_envelope.band_width_std`). No "
                "tiebreak — the doc defers root-cause diagnosis to a "
                "different cluster."
            ),
        },
        {
            "name": "Secondary Air A/B Balance",
            "members": "SA Flow-A, SA Flow-B",
            "check": "(SA-A − SA-B) / avg(SA-A, SA-B) × 100 vs. learned band",
            "tolerance": band_desc("SA_SIDE_DEV_PCT", rel["sa_ab_balance"]["band_width_std"], "%"),
            "source": (
                "**Learned from STEADY historical training data** (§8) — doc "
                "gives the formula (Table 7) but explicitly no number "
                "(\"a perfectly equal split should not be assumed\"). "
                f"`band_width_std={rel['sa_ab_balance']['band_width_std']:.1f}` is a "
                "**user-configurable default** (`cluster_config.yaml: "
                "relationships.sa_ab_balance.band_width_std`). No tiebreak "
                "specified in the doc."
            ),
        },
        {
            "name": "Tertiary Air A/B Balance",
            "members": "TA Flow-A, TA Flow-B",
            "check": "(TA-A − TA-B) / avg(TA-A, TA-B) × 100 vs. learned band",
            "tolerance": band_desc("TA_SIDE_DEV_PCT", rel["ta_ab_balance"]["band_width_std"], "%"),
            "source": (
                "**Learned from STEADY historical training data** (§8) — "
                "same doc formula pattern extended to TA by analogy (not "
                "explicit in the doc). "
                f"`band_width_std={rel['ta_ab_balance']['band_width_std']:.1f}` is a "
                "**user-configurable default** (`cluster_config.yaml: "
                "relationships.ta_ab_balance.band_width_std`). No tiebreak "
                "specified in the doc."
            ),
        },
    ]

    for r in rows:
        parts.append(f"### {r['name']}\n")
        parts.append(f"- **Members:** {r['members']}")
        parts.append(f"- **Check performed:** {r['check']}")
        parts.append(f"- **Tolerance/range used:** {r['tolerance']}")
        parts.append(f"- **Source:** {r['source']}")
        parts.append("")

    return "\n".join(parts)


def section_summary(results: pd.DataFrame, full_view: pd.DataFrame) -> str:
    rel_names = [
        ("steam_flow_ab_balance_status", "Steam Flow A/B Balance"),
        ("water_steam_balance_status", "Water-Steam Balance"),
        ("air_vs_load_envelope_status", "Total Combustion Air vs. Load"),
        ("sa_ab_balance_status", "Secondary Air A/B Balance"),
        ("ta_ab_balance_status", "Tertiary Air A/B Balance"),
    ]
    parts = ["## 3. Summary — status by relationship, before vs. after the fix\n"]
    parts.append(
        f"**After (this run):** test window only, {len(results):,} unseen "
        f"rows, baseline trained on the separate 20% training window. "
        f"**Before (prior report version):** full {BEFORE_FIX_TOTAL:,}-row "
        f"dataset used for both training and scoring (leakage), no "
        f"STEADY-training-window restriction beyond the original always-full-"
        f"dataset STEADY filter, no stale/spike/known-bad exclusion. Shifts "
        f"here are expected and correct — this is what testing on genuinely "
        f"unseen data with a cleaner baseline is supposed to look like, not "
        f"a regression.\n"
    )
    for col, label in rel_names:
        before = BEFORE_FIX_SUMMARY[col]
        after_counts = results[col].value_counts()
        parts.append(f"### {label}\n")
        lines = ["| status | before (full-dataset, leaked) | after (test-window, fixed) |", "|---|---:|---:|"]
        for status in STATUS_ORDER:
            b = before.get(status, 0)
            a = int(after_counts.get(status, 0))
            if b == 0 and a == 0:
                continue
            b_pct = b / BEFORE_FIX_TOTAL * 100
            a_pct = a / len(results) * 100
            lines.append(f"| {status} | {b:,} ({b_pct:.2f}%) | {a:,} ({a_pct:.2f}%) |")
        parts.append("\n".join(lines))
        parts.append("")

    parts.append(
        "### Seasonal drift: why an earlier version of this split inflated Air Envelope / SA Balance outliers, and how monthly stratification fixes it\n"
    )
    parts.append(
        "An intermediate version of this fix (single first-20%-of-the-year "
        "block, 2024-01-18 -> 2024-03-27) showed Total Combustion Air's "
        "outlier rate rise to 37.57% and Secondary Air balance to 13.82% — "
        "both far above the original (leaked) baseline's 2.68% / 4.68%. "
        "Investigating why (same load band, 100-110% MCR, across the year) "
        "found a genuine, sustained seasonal shift the Jan-Mar-only "
        "training window had no way to know about:\n"
    )
    parts.append(_monthly_drift_table(full_view, "TOTAL_COMBUSTION_AIR"))
    parts.append(
        "\nMean Total Combustion Air at this load band rises from "
        "~250 TPH in Jan-May to ~263-269 TPH from July onward — a "
        "15-19 TPH shift, several times the training window's own std "
        "(ambient/seasonal effect, a coal-quality or combustion-tuning "
        "change, or an instrument recalibration — this data alone can't "
        "distinguish which). Secondary Air side-balance showed the same "
        "pattern, smaller in scale:\n"
    )
    parts.append(_monthly_drift_table(full_view, "SA_SIDE_DEV_PCT"))
    parts.append(
        "\n**Switching to the monthly-stratified split (§1.1) — every month "
        "contributes its own first-20% training slice, instead of only "
        "Jan-Mar — resolves this:**\n"
    )
    lines = ["\n| relationship | leaked (original) | single-cutoff split | monthly-stratified split (this run) |", "|---|---:|---:|---:|"]
    for col, single_label in [("air_vs_load_envelope_status", "Total Combustion Air"), ("sa_ab_balance_status", "SA Balance")]:
        leaked_outlier = BEFORE_FIX_SUMMARY[col]["outlier"] / BEFORE_FIX_TOTAL * 100
        single_outlier = SINGLE_CUTOFF_SPLIT_SUMMARY[col]["outlier"] / SINGLE_CUTOFF_SPLIT_TOTAL * 100
        final_outlier = int(results[col].value_counts().get("outlier", 0)) / len(results) * 100
        lines.append(f"| {single_label} outlier rate | {leaked_outlier:.2f}% | {single_outlier:.2f}% | {final_outlier:.2f}% |")
    parts.append("\n".join(lines))
    parts.append(
        "\nBoth relationships' outlier rates land back close to the "
        "original leaked-baseline numbers — expected, since a "
        "representative (all-months) training set should recover roughly "
        "the same \"normal\" the leaked baseline saw, minus actual leakage "
        "and now with a genuinely held-out test set. The remaining small "
        "differences are the STEADY/quality filtering and finite-sample "
        "noise doing real work, not a residual seasonal-drift artifact.\n"
        "\nBy contrast, Water-Steam Balance Deviation stayed within "
        "~5.3-6.0% all year at this load band (see §4's table) under EVERY "
        "split tried — confirming that relationship is genuinely stable "
        "year-round and was never sensitive to which months trained the "
        "baseline.\n"
    )

    parts.append(
        "### Tertiary Air Balance is a DIFFERENT story: a real event the "
        "single-cutoff split had accidentally trained away\n"
    )
    parts.append(
        "TA Balance's outlier rate did NOT settle back near the original "
        "leaked baseline like Air/SA did — it rose further, from 3.38% "
        "(leaked) and 0.00% (single-cutoff split) to 11.78% here. This "
        "isn't a representativeness problem; it's the validator correctly "
        "catching a real, sustained event that the single-cutoff split's "
        "baseline had absorbed into \"normal\" by accident. Investigating: "
        "Total Tertiary Air dropped sharply for about 18 days while Load "
        "stayed in its normal range throughout — a genuine operational "
        "event, not noise:\n"
    )
    ta_periods = [
        ("before, Feb 1 – Feb 8 08:00", "2024-02-01", "2024-02-08 08:00"),
        ("stage 1, Feb 8 12:00 – Feb 12 08:00", "2024-02-08 12:00", "2024-02-12 08:00"),
        ("stage 2, Feb 12 12:00 – Feb 26 12:00", "2024-02-12 12:00", "2024-02-26 12:00"),
        ("after, Feb 26 16:00 – Feb 29", "2024-02-26 16:00", "2024-03-01"),
    ]
    ta_ts = pd.to_datetime(full_view["Timestamp"])
    lines = ["| period | n rows | Total Tertiary Air (mean TPH) | Load (mean %) |", "|---|---:|---:|---:|"]
    for label, start, end in ta_periods:
        mask = (ta_ts >= start) & (ta_ts < end)
        sub = full_view.loc[mask]
        lines.append(f"| {label} | {len(sub):,} | {sub['TOTAL_TERTIARY_AIR'].mean():.1f} | {sub['LOAD'].mean():.1f} |")
    full_year_mean = full_view["TOTAL_TERTIARY_AIR"].mean()
    lines.append(f"| **full-year average (reference)** | {len(full_view):,} | **{full_year_mean:.1f}** | — |")
    parts.append("\n".join(lines))
    parts.append(
        "\nTotal Tertiary Air fell from a normal ~61 TPH to ~11 TPH "
        "(an ~82% drop) for 4 days, partially recovered to ~29 TPH for the "
        "next ~14 days, then returned to ~51 TPH — while Load stayed "
        "essentially flat (~91-103%) the entire time. The A/B split ALSO "
        "genuinely widened during the deepest-drop stage — the A/B ratio "
        "moved from a normal ~1.007 to ~1.138 (TA_SIDE_DEV_PCT mean 12.8%, "
        "vs. 0.7% normal) in the first 4 days, then partly narrowed back "
        "to ~1.021 (2.1%) as total flow partially recovered. So this isn't "
        "purely a ratio-denominator artifact of the total dropping — the "
        "two air paths genuinely stopped tracking each other as closely "
        "during the event, on top of the large total-flow drop. Full event "
        "detail in §9.5.\n"
        "\n**Why the splits disagree:** the single-cutoff training window "
        "(2024-01-18 -> 2024-03-27) fully contained this Feb 8-26 event, "
        "so that baseline learned the event's depressed TA-balance "
        "readings as part of \"normal\" — widening its band enough to "
        "mask the event (and everything resembling it) almost entirely "
        "(0.00% outlier). The monthly-stratified split's February training "
        "slice is only Feb 1 - Feb 6.8 (first 20% of February), which ends "
        "BEFORE the event starts (Feb 8) — so this baseline never learned "
        "the event as normal, and correctly flags it in the test window. "
        "This is the split method working as intended, not a regression.\n"
    )
    return "\n".join(parts)


def section_water_steam_bias(baseline: Cluster1Baseline, view: pd.DataFrame) -> str:
    """Dedicated section: Feedwater Flow reads systematically higher than
    Total Steam Flow at every load band, all year. This is the learned
    baseline itself (not a fault-detection outcome) — the single most
    actionable finding for a plant engineer to review, so it gets its own
    section rather than a footnote."""
    parts = ["## 4. Feedwater Flow vs. Total Steam Flow — Systematic Bias\n"]
    parts.append(
        "**Finding: Feedwater Flow reads 5-7% higher than Total Main Steam "
        "Flow at steady state, consistently across every load band, all "
        "year. This is not a fault flagged by the validator — it IS the "
        "learned normal baseline — but it's a real, persistent, plant-wide "
        "offset that a plant engineer should be able to explain.**\n"
    )
    parts.append(
        "Doc Table 4: `Water-Steam Balance Deviation (%) = (Feedwater Flow - "
        "Total Main Steam Flow) / Total Main Steam Flow * 100`. STEADY-state "
        "distribution, learned per load bin by `cluster_baseline.py`:\n"
    )
    stats = baseline._by_bin.get("WATER_STEAM_BALANCE_DEV_PCT", {})
    lines = ["| load band (% MCR) | n (STEADY rows) | mean deviation | std dev |", "|---|---:|---:|---:|"]
    thin_bins = []
    for interval, s in sorted(stats.items(), key=lambda kv: kv[0].left):
        flag = " *" if s.n < baseline.min_samples else ""
        if flag:
            thin_bins.append((interval, s))
        lines.append(f"| [{interval.left:.0f}, {interval.right:.0f}){flag} | {s.n:,} | {s.mean:+.2f}% | {s.std:.2f}% |")
    g = baseline._global.get("WATER_STEAM_BALANCE_DEV_PCT")
    if g:
        lines.append(f"| **all STEADY rows** | **{g.n:,}** | **{g.mean:+.2f}%** | **{g.std:.2f}%** |")
    parts.append("\n".join(lines))
    if thin_bins:
        bin_desc = ", ".join(f"[{i.left:.0f},{i.right:.0f})" for i, s in thin_bins)
        n_desc = ", ".join(f"n={s.n}" for i, s in thin_bins)
        parts.append(
            f"\n\\* {bin_desc} ({n_desc}) — below `min_samples` "
            f"({baseline.min_samples}), too thin to trust on its own. "
            f"`stats_for()` automatically falls back to the \"all STEADY "
            f"rows\" global stats for any row landing in this bin (see "
            f"`engine/baseline.py`/`clusters/cluster_baseline.py`'s "
            f"sparse-bin-fallback rule) — the table shows the raw bin "
            f"statistic for transparency, but it is NOT what's actually "
            f"used to score a row at this load. This plant runs at "
            f"110-120% MCR rarely enough that the monthly-stratified "
            f"training slice catches only a handful of samples there; "
            f"revisit once more high-load historian data is available.\n"
        )

    dev = view["WATER_STEAM_BALANCE_DEV_PCT"].replace([np.inf, -np.inf], np.nan).dropna()
    pct = dev.quantile([0.05, 0.25, 0.5, 0.75, 0.95])
    parts.append(
        f"\nAcross all {len(dev):,} TEST WINDOW rows with valid data (unseen "
        f"data, not used to train the baseline above): 5th pct "
        f"{pct[0.05]:+.2f}%, 25th {pct[0.25]:+.2f}%, median {pct[0.5]:+.2f}%, "
        f"75th {pct[0.75]:+.2f}%, 95th {pct[0.95]:+.2f}%. The offset holds "
        "across the whole distribution, not just the mean, AND holds on "
        "data the baseline never saw — this isn't a few outlier rows "
        "pulling an average, and it isn't an artifact of training on the "
        "same data being described."
    )
    parts.append(
        "\n**Why this matters:** the bias is one-directional (feedwater "
        "always reads higher, never lower, at every load) and its "
        "magnitude *shrinks* as load rises (6.5% at 80-90% MCR down to "
        "3.3% at 110-120% MCR) — a random instrument noise problem "
        "wouldn't behave this consistently. Plausible explanations, in "
        "order of what the available data can and can't confirm:\n"
        "- **Missing spray-water term** — doc Table 3's formula is "
        "`Total Main Steam Flow = Feedwater Flow + Steam Flow Error`, "
        "where the error term is `f(Feedwater Flow, Spray Flow)`. This "
        "dataset has no usable Spray Flow tag (see §9), so the balance "
        "here omits it entirely — but spray water *adds* mass into the "
        "steam side, which would push Total Steam higher (i.e. shrink "
        "this gap or flip its sign), not explain why Feedwater is "
        "consistently the *larger* number. This alone likely does not "
        "explain the direction of the offset.\n"
        "- **Blowdown** (continuous or intermittent drum blowdown draws "
        "water out of the loop after the feedwater meter but before it "
        "becomes measured steam) — consistent with the observed direction "
        "and would explain a load-independent-ish base draw that's a "
        "shrinking *percentage* of a rising steam flow, matching the "
        "load-band trend above.\n"
        "- **Meter calibration offset** on one or both flow elements — "
        "cannot be distinguished from blowdown using this data alone.\n"
        "\nNone of these can be confirmed from the historian data alone. "
        "**Recommend the plant engineer confirm actual blowdown practice "
        "and the last calibration date for the feedwater and steam flow "
        "elements before this offset is accepted as \"normal.\"**"
    )
    return "\n".join(parts) + "\n"


def section_steam_ab_tiebreak(results: pd.DataFrame) -> str:
    parts = ["## 5. Steam Flow A/B Tiebreaker — worked examples\n"]
    parts.append(
        "Doc: *\"In case of Eq 1 Correlate both readings acceptable "
        "variation 3% ... In case two readings differ Correlate with Feed "
        "Flow.\"* When A and B disagree beyond 3%, each candidate is "
        "plugged in as Total Steam Flow and compared against the learned "
        "water-steam-balance band; whichever lands closer is trusted. If "
        "neither is clearly closer, the relationship is marked "
        "`ambiguous` rather than guessed.\n"
        "\n**What downstream code uses as Total Steam Flow when the "
        "tiebreak is ambiguous:** the plain `(Steam Flow-A + Steam Flow-B) "
        "/ 2` average — the SAME value used when A and B already agree, "
        "not a guess at which side is right. Marking a row `ambiguous` "
        "means \"no basis to prefer one side,\" so §6's water-steam-balance "
        "check downstream doesn't invent a preference either; it uses the "
        "same combination it would use for a consistent row. That row's "
        "own status in §6 still reflects whatever residual this average "
        "produces — the ambiguity isn't hidden from a reader inspecting "
        "the row, just not resolved into a single \"correct\" side. See "
        "`clusters/cluster_validator.py`'s `validate_row()`.\n"
        "\nNote: under the monthly-stratified split (§1), which of the "
        "dataset's four known A/B-disagreement rows land in train vs. test "
        "depends on where each falls within ITS OWN month's first-20% "
        "slice — this shifts from run to run as the split method changes, "
        "not evidence of more or fewer real faults existing. This run: the "
        "two 2024-02-11 events fall in February's test portion (scored "
        "below); the 2024-10-04 11:35 outlier and 11:40 ambiguous case both "
        "fall inside October's training slice (excluded from training via "
        "`KNOWN_BAD_TIMESTAMPS` and the STEADY filter respectively, not "
        "scored here).\n"
    )

    outliers = results[results["steam_flow_ab_balance_status"] == "outlier"]
    row_word_o = "row" if len(outliers) == 1 else "rows"
    parts.append(f"### Outliers resolved: {len(outliers)} {row_word_o}\n")
    parts.append(
        "Genuine sensor-fault events, not noise: the losing side's implied "
        "deviation from Feedwater Flow is in the hundreds of percent, "
        "meaning that meter briefly reported a value far below its true "
        "flow (i.e. it was the wrong one, not a marginal call).\n"
    )
    for _, r in outliers.iterrows():
        d = r["steam_flow_ab_balance_detail"]
        parts.append(
            f"- **{r['Timestamp']}** — A/B disagreement {d['ab_diff_pct']:.1f}%. "
            f"Steam-A implied {d['dev_a_vs_fw_pct']:+.1f}% vs. Feedwater, "
            f"Steam-B implied {d['dev_b_vs_fw_pct']:+.1f}% vs. Feedwater "
            f"(normal band: {d['wsb_baseline_mean_pct']:.1f}% ± "
            f"{d['wsb_baseline_std_pct']:.1f}%). "
            f"**Trusted: Steam Flow-{d['trusted_side']}, flagged: "
            f"Steam Flow-{d['flagged_side']}.**"
        )

    ambiguous = results[results["steam_flow_ab_balance_status"] == "ambiguous"]
    row_word = "row" if len(ambiguous) == 1 else "rows"
    parts.append(f"\n### Ambiguous cases (tiebreak declined to guess): {len(ambiguous)} {row_word}\n")
    if ambiguous.empty:
        parts.append(
            "None in this test window — the dataset's one A/B-ambiguous "
            "event (2024-10-04 11:40, 3.6% disagreement, both sides "
            "similarly far from the normal band) falls inside October's "
            "training slice under the monthly-stratified split, so it "
            "isn't scored here. See §6 for a water-steam-balance ambiguous "
            "example instead, which demonstrates the same \"decline to "
            "guess\" behavior for the other tiebreak.\n"
        )
    for _, r in ambiguous.iterrows():
        d = r["steam_flow_ab_balance_detail"]
        parts.append(
            f"- **{r['Timestamp']}** — A/B disagreement {d['ab_diff_pct']:.1f}% "
            f"(just over the 3% tolerance). Steam-A implied "
            f"{d['dev_a_vs_fw_pct']:+.1f}% vs. Feedwater, Steam-B implied "
            f"{d['dev_b_vs_fw_pct']:+.1f}% — both similarly far from the "
            f"normal band, so neither reading is more trustworthy than the "
            f"other. Correctly left unresolved rather than picking one."
        )
    return "\n".join(parts) + "\n"


def section_water_steam_tiebreak(results: pd.DataFrame) -> str:
    parts = ["## 6. Water-Steam Balance Tiebreak (vs. Load) — worked examples\n"]
    parts.append(
        "Doc para 21: *\"In case Steam Flow and Feed Flow are not matching "
        "both values should be correlated with Load. The value matching "
        "with load should be considered and other will be corrected.\"* "
        "When the resolved balance falls outside its learned band, both "
        "Total Steam Flow and Feedwater Flow are compared against what "
        "Load's own baseline predicts for each; whichever is closer is "
        "trusted.\n"
    )

    outliers = results[results["water_steam_balance_status"] == "outlier"]
    parts.append(f"### Outliers resolved: {len(outliers)} rows\n")
    for _, r in outliers.iterrows():
        d = r["water_steam_balance_detail"]
        parts.append(
            f"- **{r['Timestamp']}** — balance deviation {d['deviation_pct']:+.1f}% "
            f"(band {d['baseline_mean_pct']:.1f}% ± {d['baseline_std_pct']:.1f}%). "
            f"Steam Flow is {d['steam_dev_from_load_pct']:.1f}% off Load's "
            f"expectation; Feedwater Flow is {d['fw_dev_from_load_pct']:.1f}% "
            f"off. **Trusted: {d['trusted']}, flagged for correction: "
            f"{d['flagged_for_correction']}.**"
        )

    ambiguous = results[results["water_steam_balance_status"] == "ambiguous"].copy()
    ambiguous["_spread"] = ambiguous["water_steam_balance_detail"].apply(
        lambda d: abs(d.get("steam_dev_from_load_pct", np.nan) - d.get("fw_dev_from_load_pct", np.nan))
    )
    parts.append(f"\n### Ambiguous cases: {len(ambiguous)} rows ({len(ambiguous) / len(results) * 100:.2f}% of all rows)\n")
    parts.append(
        "Example with the two candidates' deviation-from-load close "
        "together (~5 percentage points apart) — a real but modest, "
        "everyday imbalance where neither Steam Flow nor Feedwater Flow "
        "stands out as clearly wrong relative to Load, so the tiebreak "
        "correctly declines to blame one over the other:\n"
    )
    if not ambiguous.empty:
        target = ambiguous.iloc[(ambiguous["_spread"] - 5.0).abs().argsort().iloc[0]]
        d = target["water_steam_balance_detail"]
        parts.append(
            f"- **{target['Timestamp']}** — balance deviation "
            f"{d['deviation_pct']:+.1f}% (band {d['baseline_mean_pct']:.1f}% "
            f"± {d['baseline_std_pct']:.1f}%). Steam Flow is "
            f"{d['steam_dev_from_load_pct']:.1f}% off Load's expectation; "
            f"Feedwater Flow is {d['fw_dev_from_load_pct']:.1f}% off — a "
            f"{target['_spread']:.1f} percentage-point spread, under the "
            f"15pp ambiguity margin. **Left ambiguous** rather than "
            f"arbitrarily trusting the marginally-closer one."
        )
    return "\n".join(parts) + "\n"


def section_air_envelope(view: pd.DataFrame, results: pd.DataFrame) -> str:
    parts = ["## 7. Total Combustion Air vs. Load Envelope\n"]
    parts.append(_status_table(results, "air_vs_load_envelope_status"))

    air_nan = view["TOTAL_COMBUSTION_AIR"].isna()
    pa_nan = view["TOTAL_PA_FLOW"].isna()
    sa_nan = view["TOTAL_SECONDARY_AIR"].isna()
    ta_nan = view["TOTAL_TERTIARY_AIR"].isna()
    union = pa_nan | sa_nan | ta_nan
    exact_match = bool((air_nan == union).all())

    parts.append(
        f"\n**`unknown` rows are fully explained by upstream sensor gaps, "
        f"not a new issue.** `Total Combustion Air = Total PA + Total SA + "
        f"Total TA` is NaN in exactly {int(air_nan.sum()):,} rows, which "
        f"matches the union of PA/SA/TA component NaNs "
        f"({int(union.sum()):,} rows) {'exactly' if exact_match else '— MISMATCH, see below'}. "
        f"Breakdown: PA NaN alone contributes "
        f"{int((pa_nan & ~sa_nan & ~ta_nan).sum()):,}, SA (total) NaN alone "
        f"{int((sa_nan & ~pa_nan & ~ta_nan).sum()):,}, TA (total) NaN alone "
        f"{int((ta_nan & ~pa_nan & ~sa_nan).sum()):,}, with "
        f"{int((sa_nan & ta_nan).sum()):,} rows where SA and TA are both "
        f"NaN simultaneously. See §9 for the underlying SA/TA sensor gap "
        f"periods."
    )
    return "\n".join(parts) + "\n"


def section_ab_side_balance(results: pd.DataFrame) -> str:
    parts = ["## 8. Secondary/Tertiary Air A/B Side Balance\n"]
    parts.append(
        "Doc: *\"A perfectly equal split should not be assumed ... Trend "
        "movement is often more informative than the absolute difference.\"* "
        "No numeric tolerance or tiebreak is specified for air-side balance "
        "in the doc, so this uses the STEADY-state learned band (mean ± 2 "
        "std, per load bin) rather than a flat guessed percentage — a ~4-5% "
        "outlier rate is the expected base rate for a roughly-normal "
        "distribution at a 2-sigma band, not necessarily abnormal plant "
        "behavior. No reconciliation is attempted (none is specified) — "
        "these are flagged for the trend-based follow-up the doc "
        "describes, not resolved here.\n"
    )
    parts.append("### Secondary Air (SA-A vs. SA-B)\n")
    parts.append(_status_table(results, "sa_ab_balance_status"))
    parts.append("\n### Tertiary Air (TA-A vs. TA-B)\n")
    parts.append(_status_table(results, "ta_ab_balance_status"))
    return "\n".join(parts) + "\n"


def section_data_quality(raw: pd.DataFrame, view: pd.DataFrame) -> str:
    parts = ["## 9. Real-data findings — surfaced as-is\n"]
    parts.append(
        "Scope note: this section describes the FULL year (train + test "
        "combined) — these are historian data-quality observations, not "
        "validator status results, so the train/test split doesn't apply "
        "to them.\n"
    )

    parts.append("### 9.1 Spray Water Flow — no usable tag\n")
    parts.append(
        "No real tag for spray water flow to the superheater exists in "
        "this historian export. Candidate proxy tags `CV-116 FB` / "
        "`CV-121 FB` exist but Module 1's config already rejected them as "
        "an unverified proxy (\"CV-116/121 FB proxy mapping unclear, do "
        "not use\"). Same call kept here — the water-steam balance in §4 "
        "runs without a spray term.\n"
    )

    parts.append("### 9.2 Simultaneous frozen-value stretch, 2024-08-30\n")
    streaks = _frozen_streaks(view, [
        "STEAM_FLOW_A", "STEAM_FLOW_B", "FEEDWATER_FLOW", "TOTAL_PA_FLOW",
        "SA_FLOW_A", "SA_FLOW_B", "TA_FLOW_A", "TA_FLOW_B",
    ])
    lines = ["| column | longest frozen streak | window ends |", "|---|---:|---|"]
    for _, r in streaks.iterrows():
        if r["max_streak_rows"] == 0:
            lines.append(f"| {r['column']} | 0 | — |")
        else:
            lines.append(f"| {r['column']} | {int(r['max_streak_rows'])} rows (~{int(r['max_streak_minutes'])} min) | {r['end']} |")
    parts.append("\n".join(lines))
    parts.append(
        "\nSteam Flow-A, Steam Flow-B and Feedwater Flow are all frozen at "
        "identical values simultaneously for roughly an hour ending "
        "2024-08-30 16:20 (values like `153.000000` / `154.000000` / "
        "`164.753571` repeating exactly across ~12-13 consecutive 5-minute "
        "rows), with a second ~30-minute frozen stretch around 17:20-17:50 "
        "on the same day. All three key process variables freezing at "
        "once, at suspiciously round numbers, points to a historian/"
        "logging outage on that date rather than three independent sensor "
        "faults — worth confirming against plant maintenance logs for "
        "2024-08-30 rather than trusting that window's readings.\n"
    )

    parts.append("### 9.3 Secondary/Tertiary Air sensor gap periods\n")
    sa_gaps = _nan_gap_periods(view, "TOTAL_SECONDARY_AIR")
    ta_gaps = _nan_gap_periods(view, "TOTAL_TERTIARY_AIR")
    parts.append(
        f"Secondary Air: {len(sa_gaps)} distinct NaN gap periods, "
        f"{int(sa_gaps['n_rows'].sum()):,} rows total "
        f"({int(sa_gaps['n_rows'].sum()) / len(view) * 100:.1f}% of the year). "
        f"The 5 largest gaps account for "
        f"{int(sa_gaps['n_rows'].head(5).sum()):,} of those rows — this is "
        f"dominated by a handful of sustained multi-day outages, not "
        f"scattered single-row dropouts:\n"
    )
    lines = ["| start | end | rows | approx. duration |", "|---|---|---:|---|"]
    for _, r in sa_gaps.head(5).iterrows():
        days = r["n_rows"] * 5 / 60 / 24
        lines.append(f"| {r['first']} | {r['last']} | {int(r['n_rows']):,} | ~{days:.1f} days |")
    parts.append("\n".join(lines))
    parts.append(
        f"\nTertiary Air: {len(ta_gaps)} distinct gap period(s), "
        f"{int(ta_gaps['n_rows'].sum()):,} rows total — "
        + (
            "concentrated entirely on the first day of the dataset "
            f"({ta_gaps.iloc[0]['first']} to {ta_gaps.iloc[0]['last']}, "
            f"{int(ta_gaps.iloc[0]['n_rows'])} rows), i.e. instrumentation "
            "coming online at the very start of the historian export, not "
            "an ongoing issue."
            if not ta_gaps.empty else "none found."
        )
    )

    parts.append("\n### 9.4 Total PA Flow: derivation cross-check\n")
    pa_a = raw[["PA FLOW TO HGG -A (1)", "PA FLOW TO HGG -A (2)"]].mean(axis=1)
    pa_b = raw[["PA FLOW TO HGG -B (1)", "PA FLOW TO HGG -B (2)"]].mean(axis=1)
    computed_total = pa_a + pa_b
    raw_total_tag = raw["TOTAL PA FLOW"]
    diff = (computed_total - raw_total_tag).abs()
    parts.append(
        f"A raw `TOTAL PA FLOW` tag exists in the historian CSV separately "
        f"from the 4 header sub-tags this report derives PA from (same "
        f"derivation as Module 1's `PRIMARY_AIR_FLOW`). Cross-checked: max "
        f"abs difference {diff.max():.3f} TPH, mean {diff.mean():.4f} TPH "
        f"— negligible (rounding), confirms the derivation is correct and "
        f"consistent with the plant's own computed total."
    )

    parts.append("\n### 9.5 Sustained Tertiary Air flow reduction, 2024-02-08 to 2024-02-26\n")
    ta_ts = pd.to_datetime(view["Timestamp"])
    ta_periods = [
        ("before, Feb 1 – Feb 8 08:00", "2024-02-01", "2024-02-08 08:00"),
        ("stage 1, Feb 8 12:00 – Feb 12 08:00", "2024-02-08 12:00", "2024-02-12 08:00"),
        ("stage 2, Feb 12 12:00 – Feb 26 12:00", "2024-02-12 12:00", "2024-02-26 12:00"),
        ("after, Feb 26 16:00 – Feb 29", "2024-02-26 16:00", "2024-03-01"),
    ]
    lines = ["| period | n rows | TA-A mean | TA-B mean | Total TA mean | A/B ratio | Load mean |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for label, start, end in ta_periods:
        mask = (ta_ts >= start) & (ta_ts < end)
        sub = view.loc[mask]
        ratio = (sub["TA_FLOW_A"] / sub["TA_FLOW_B"]).mean()
        lines.append(
            f"| {label} | {len(sub):,} | {sub['TA_FLOW_A'].mean():.1f} | "
            f"{sub['TA_FLOW_B'].mean():.1f} | {sub['TOTAL_TERTIARY_AIR'].mean():.1f} | "
            f"{ratio:.3f} | {sub['LOAD'].mean():.1f}% |"
        )
    parts.append("\n".join(lines))
    parts.append(
        "\nFor about 18 days, Total Tertiary Air ran far below its normal "
        "level (full-year average ~51 TPH) while Load stayed in its "
        "ordinary operating range throughout — this is not a load-driven "
        "change. Two distinct stages: a severe drop (~11 TPH, ~82% below "
        "normal) for the first 4 days, with the A/B split also genuinely "
        "widening (ratio 1.14 vs. a normal ~1.01); then a partial recovery "
        "(~29 TPH, still ~43% below normal) for the remaining ~14 days, "
        "with the A/B split mostly (not fully) narrowing back. Both TA "
        "channels move together throughout — this rules out a single "
        "frozen/failed transmitter (which would hold one channel constant "
        "while the other kept varying normally) — pointing instead toward "
        "a genuine equipment or operating-mode event affecting both "
        "tertiary-air paths at once (e.g. TA damper/fan maintenance, or a "
        "deliberate air-distribution change with more load carried by PA/SA "
        "instead). This data alone can't confirm the cause — flagged for "
        "the plant engineer to check maintenance/operations logs for "
        "2024-02-08 through 2024-02-26. This is also the event discussed "
        "in §3's split-method comparison: it happened to fall entirely "
        "inside the single-cutoff split's training window, which caused "
        "that baseline to (incorrectly) learn it as normal."
    )
    return "\n".join(parts) + "\n"


def section_limitations() -> str:
    return """## 10. Known limitations — not implemented in this phase

- **A/B side-balance trend analysis** — the doc notes "trend movement is
  often more informative than the absolute difference" for SA/TA A/B
  balance. This report only evaluates each row's instantaneous deviation
  against a load-binned band; no rolling-trend detection is implemented.
- **Water-steam balance tiebreak margin (15 percentage points), all
  `band_width_std` values, the 20% train fraction, and the training-only
  stale threshold (12 rows) are user-configurable defaults or judgment
  calls**, not numbers specified in the doc (only the 3% Steam Flow-A/B
  tolerance is an explicit doc value) — see `clusters/cluster_config.yaml`
  and `shared/data_quality.py` for all tunable fields and their rationale.
- **Training-window mode classification can hiccup across small sampling
  gaps** — `engine/mode_classifier.py`'s rolling slope features compute a
  diff() across whatever rows are adjacent within a month's training slice;
  2 small real gaps (50/100 min, both in January's slice) exist inside the
  actual training data and could in principle produce a spurious slope
  reading for the 1-2 rows adjacent to each. Not separately verified in
  this report. (Month-to-month boundaries in the concatenated training set
  also look like large gaps if diffed naively — those are a training-set
  construction artifact, not real data gaps, and mode_classifier.py is
  never run across that boundary.)
- **A learned band from finite training data will always flag some
  fraction of even in-control test data by construction** (a 2-sigma band
  flags ~4-5% on a well-behaved normal distribution) — most of Air
  Envelope/SA/TA Balance's outlier rates in this report are close to that
  base rate, but TA Balance's 11.78% is NOT just base rate — see §3 and
  §9.5 for the real ~18-day Tertiary Air event driving it.
- **Not wired into `server.py` or the frontend** — by design, per this
  phase's scope. This report is the standalone deliverable.
"""


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main():
    raw, full_view, baseline, results, cluster_config = run_pipeline()
    test_view = baseline.test_view

    sections = [
        section_header(raw),
        section_methodology(baseline),
        section_parameters_tolerances(cluster_config, baseline),
        section_summary(results, full_view),
        section_water_steam_bias(baseline, test_view),
        section_steam_ab_tiebreak(results),
        section_water_steam_tiebreak(results),
        section_air_envelope(test_view, results),
        section_ab_side_balance(results),
        section_data_quality(raw, full_view),
        section_limitations(),
    ]
    report = "\n".join(sections)
    OUT_PATH.write_text(report, encoding="utf-8")
    print(f"Wrote {OUT_PATH} ({len(report):,} chars)")

    write_docx(report, DOCX_OUT_PATH, title="Cluster 1 — Load-Flow Mass Balance — Validation Report")
    print(f"Wrote {DOCX_OUT_PATH}")


if __name__ == "__main__":
    main()
