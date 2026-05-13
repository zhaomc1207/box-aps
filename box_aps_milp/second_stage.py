"""Second-stage sequencing and validation for BOX APS schedules.

The main MILP decides line/slot quantities. This module turns those quantities
into executable within-slot sequences and reports rules that are not fully
encoded in the global MILP, such as FAI timing, demand split, and local
changeover/continuity checks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from .data import ProcessedData


@dataclass(slots=True)
class SecondStageResult:
    solution: pd.DataFrame
    report: dict[str, Any]


def run_second_stage(solution: pd.DataFrame, data: ProcessedData) -> SecondStageResult:
    """Sequence each non-empty line-slot and validate second-stage rules."""

    if solution.empty:
        return SecondStageResult(solution=solution.copy(), report={"issues": [], "counts": {}})

    sequenced = _sequence_line_slots(solution, data)
    issues: list[dict[str, Any]] = []
    counts: dict[str, Any] = {}

    split_count = _check_same_demand_same_slot_split(sequenced, issues)
    fai_count = _check_fai_precedence(sequenced, data, issues)
    capacity_count = _check_capacity(sequenced, data, issues)
    changeover_counts = _summarize_changeovers(sequenced, issues)

    counts.update(
        {
            "same_demand_same_slot_split_count": split_count,
            "fai_violation_count": fai_count,
            "capacity_violation_slot_count": capacity_count,
            **changeover_counts,
        }
    )
    report = {"issues": issues, "counts": counts}
    return SecondStageResult(solution=sequenced, report=report)


def _sequence_line_slots(solution: pd.DataFrame, data: ProcessedData) -> pd.DataFrame:
    out = solution.copy()
    for col in ["demand_id", "line_id", "slot_id"]:
        out[col] = out[col].astype(str)

    out["_schedule_qty_num"] = pd.to_numeric(out.get("schedule_qty", 0), errors="coerce").fillna(0.0)
    out["_shift_start"] = pd.to_datetime(out.get("shift_start_time"), errors="coerce")

    sort_cols = _sort_columns_from_demands(data)
    demand_extra_cols = ["kb", "log_up_assy", "cover_assy", "pcba", "program", "color"]
    demand_extra_cols = [c for c in demand_extra_cols if c in data.demands.columns and c not in out.columns]
    if demand_extra_cols:
        demand_cols = ["demand_id", *demand_extra_cols]
        out = out.merge(data.demands[demand_cols], on="demand_id", how="left")

    fixed = data.fixed_locks.assign(_lock_source="fix") if len(data.fixed_locks) else pd.DataFrame()
    adjust = data.adjust_locks.assign(_lock_source="adjust") if len(data.adjust_locks) else pd.DataFrame()
    locks = pd.concat([fixed, adjust], ignore_index=True) if len(fixed) or len(adjust) else pd.DataFrame()
    if len(locks):
        locks = locks[["demand_id", "line_id", "slot_id", "seq", "_lock_source"]].copy()
        for col in ["demand_id", "line_id", "slot_id"]:
            locks[col] = locks[col].astype(str)
        out = out.drop(columns=["seq", "_lock_source"], errors="ignore").merge(
            locks,
            on=["demand_id", "line_id", "slot_id"],
            how="left",
        )
    else:
        out["seq"] = pd.NA
        out["_lock_source"] = pd.NA

    source_rank = {"fix": 0, "adjust": 1, "milp": 2}
    out["_source_rank"] = out.get("source", "").map(source_rank).fillna(9).astype(int)
    out["_locked_first"] = out["seq"].notna().astype(int)
    out["_seq_sort"] = pd.to_numeric(out["seq"], errors="coerce").fillna(10**9)

    for col in ["lot", "mo", "model", *sort_cols, "demand_id"]:
        if col not in out.columns:
            out[col] = ""
        out[col] = out[col].fillna("").astype(str)

    # v7_2: rule 14.2 forbids same-shift A-B-A model interleaving and rule 14.1
    # asks to minimise model changeovers. We therefore sort by model BEFORE lot
    # / mo so identical models cluster within a shift even when lots differ.
    # Lot and mo continuity remain as secondary grouping keys, followed by the
    # configured order_ruler material keys (rule 14.4 PO 物料排序).
    sort_by = [
        "line_id",
        "slot_id",
        "_locked_first",
        "_source_rank",
        "_seq_sort",
        "model",
        "lot",
        "mo",
        *sort_cols,
        "demand_id",
    ]
    ascending = [True, True, False, True, True] + [True] * (len(sort_by) - 5)
    out = out.sort_values(sort_by, ascending=ascending, kind="mergesort").reset_index(drop=True)
    out["sequence"] = out.groupby(["line_id", "slot_id"]).cumcount() + 1

    drop_cols = [
        "_schedule_qty_num",
        "_shift_start",
        "_source_rank",
        "_locked_first",
        "_seq_sort",
        "_lock_source",
    ]
    return out.drop(columns=drop_cols, errors="ignore")


def _sort_columns_from_demands(data: ProcessedData) -> list[str]:
    defaults = ["kb", "log_up_assy", "cover_assy", "pcba"]
    if data.order_keys.empty or "condition_key" not in data.order_keys.columns:
        return [c for c in defaults if c in data.demands.columns]
    keys = (
        data.order_keys.sort_values(["line_id", "priority"])["condition_key"]
        .dropna()
        .astype(str)
        .str.strip()
        .tolist()
    )
    normalized = []
    aliases = {"logup": "log_up_assy", "log_up": "log_up_assy"}
    for key in keys:
        col = aliases.get(key.lower(), key)
        if col in data.demands.columns and col not in normalized:
            normalized.append(col)
    return normalized or [c for c in defaults if c in data.demands.columns]


def _check_same_demand_same_slot_split(solution: pd.DataFrame, issues: list[dict[str, Any]]) -> int:
    grouped = solution.groupby(["demand_id", "slot_id"])["line_id"].nunique()
    split = grouped[grouped > 1]
    if len(split):
        sample = ", ".join(f"{d}|{s}" for (d, s) in list(split.index)[:5])
        issues.append(
            {
                "level": "warning",
                "where": "second_stage_split",
                "message": f"{len(split)} (demand, slot) pairs are split across multiple lines; sample={sample}",
            }
        )
    return int(len(split))


def _check_fai_precedence(solution: pd.DataFrame, data: ProcessedData, issues: list[dict[str, Any]]) -> int:
    if data.fai_arcs.empty:
        return 0
    sol = solution.copy()
    sol["shift_start_time"] = pd.to_datetime(sol["shift_start_time"], errors="coerce")
    sol["shift_end_time"] = pd.to_datetime(sol["shift_end_time"], errors="coerce")
    finish = sol.dropna(subset=["shift_end_time"]).groupby("demand_id")["shift_end_time"].max()
    start = sol.dropna(subset=["shift_start_time"]).groupby("demand_id")["shift_start_time"].min()

    violations = []
    for arc in data.fai_arcs.itertuples(index=False):
        first_d = str(arc.first_demand_id)
        rest_d = str(arc.rest_demand_id)
        if first_d not in finish.index or rest_d not in start.index:
            continue
        required = pd.Timestamp(finish.loc[first_d]) + pd.Timedelta(hours=float(arc.lead_hours))
        actual = pd.Timestamp(start.loc[rest_d])
        if actual + pd.Timedelta(seconds=1) < required:
            violations.append((arc.group_id, first_d, rest_d, required, actual))
    if violations:
        sample = "; ".join(
            f"group={g} first={f} rest={r} required>={req.isoformat()} actual={act.isoformat()}"
            for g, f, r, req, act in violations[:3]
        )
        issues.append(
            {
                "level": "warning",
                "where": "second_stage_fai",
                "message": f"{len(violations)} FAI precedence violations remain after second stage; sample={sample}",
            }
        )
    return int(len(violations))


def _check_capacity(solution: pd.DataFrame, data: ProcessedData, issues: list[dict[str, Any]]) -> int:
    """Sanity check capacity feasibility of the merged (MILP + locked) solution.

    The locked schedule is booked using a fallback UPH (see model._build_locked_schedule)
    while the post-solve lookup uses ``data.triples`` UPH, which can differ when the
    locked (demand, line, slot) was pruned out of the candidate triples table. Here
    we rebuild the *physical* shift capacity by adding back the locked occupation
    that was already subtracted from ``avail_hours``, and we compute lock usage with
    a multi-source UPH (solution row's own UPH if present, then triples, then a
    (demand, line) fallback) so the units stay consistent with what the model used.
    """
    if data.line_slots.empty:
        return 0
    triples = data.triples.copy() if not data.triples.empty else pd.DataFrame()
    if not triples.empty:
        triples["uph"] = pd.to_numeric(triples["uph"], errors="coerce").fillna(0.0)
        uph_triples = triples.set_index(["demand_id", "line_id", "slot_id"])["uph"].to_dict()
        # Fallback by (demand, line) for locked rows whose exact slot was pruned.
        uph_demand_line = (
            triples.groupby(["demand_id", "line_id"])["uph"].max().to_dict()
        )
    else:
        uph_triples, uph_demand_line = {}, {}
    if "uph" in solution.columns:
        sol_uph_series = pd.to_numeric(solution["uph"], errors="coerce").fillna(0.0)
        solution_uph = {
            (str(d), str(l), str(s)): float(u)
            for d, l, s, u in zip(
                solution["demand_id"], solution["line_id"], solution["slot_id"], sol_uph_series
            )
        }
    else:
        solution_uph = {}

    line_slots = data.line_slots.assign(
        avail_hours=pd.to_numeric(data.line_slots["avail_hours"], errors="coerce").fillna(0.0)
    )
    avail = line_slots.set_index(["line_id", "slot_id"])["avail_hours"].to_dict()

    # Determine locked rows so we can rebuild physical capacity.
    locks_frames: list[pd.DataFrame] = []
    if len(data.fixed_locks):
        locks_frames.append(data.fixed_locks)
    if len(data.adjust_locks):
        locks_frames.append(data.adjust_locks)
    locked_keys: set[tuple[str, str, str]] = set()
    if locks_frames:
        all_locks = pd.concat(locks_frames, ignore_index=True)
        locked_keys = {
            (str(r.demand_id), str(r.line_id), str(r.slot_id))
            for r in all_locks.itertuples(index=False)
        }

    usage: dict[tuple[str, str], float] = {}
    locked_added_back: dict[tuple[str, str], float] = {}
    for row in solution.itertuples(index=False):
        key = (str(row.demand_id), str(row.line_id), str(row.slot_id))
        qty = float(getattr(row, "schedule_qty", 0.0) or 0.0)
        if qty <= 0:
            continue
        # Prefer the UPH value already attached to the solution row (export
        # path) since that matches the unit used to compute occupied hours.
        row_uph = solution_uph.get(key, 0.0)
        if row_uph <= 0:
            row_uph = float(uph_triples.get(key, 0.0) or 0.0)
        if row_uph <= 0 and key in locked_keys:
            row_uph = float(uph_demand_line.get((key[0], key[1]), 0.0) or 0.0)
        if row_uph <= 0:
            continue
        used = qty / row_uph
        usage[(key[1], key[2])] = usage.get((key[1], key[2]), 0.0) + used
        if key in locked_keys:
            locked_added_back[(key[1], key[2])] = locked_added_back.get((key[1], key[2]), 0.0) + used

    violations = []
    for ls, used in usage.items():
        cap_residual = float(avail.get(ls, 0.0) or 0.0)
        physical_cap = cap_residual + locked_added_back.get(ls, 0.0)
        if used > physical_cap + 1e-3:
            violations.append((ls, used, physical_cap))
    if violations:
        sample = "; ".join(f"line={l} slot={s} used={u:.3f} avail={a:.3f}" for (l, s), u, a in violations[:5])
        issues.append(
            {
                "level": "error",
                "where": "second_stage_capacity",
                "message": f"{len(violations)} line-slots exceed available capacity; sample={sample}",
            }
        )
    return int(len(violations))


def _summarize_changeovers(solution: pd.DataFrame, issues: list[dict[str, Any]]) -> dict[str, int]:
    if "model" not in solution.columns:
        return {
            "model_changeover_count": 0,
            "raw_model_changeover_count": 0,
            "locked_model_changeover_count": 0,
        }
    raw_changeovers = 0
    effective_changeovers = 0
    locked_changeovers = 0
    for _, group in solution.sort_values(["line_id", "slot_id", "sequence"]).groupby(["line_id", "slot_id"]):
        raw_changeovers += _count_model_changeovers(group)
        if "source" in group.columns:
            effective_changeovers += _count_model_changeovers(group[group["source"].astype(str) == "milp"])
            locked_changeovers += _count_model_changeovers(group[group["source"].astype(str) != "milp"])
        else:
            effective_changeovers += _count_model_changeovers(group)
    issues.append(
        {
            "level": "info",
            "where": "second_stage_changeover",
            "message": (
                "Local sequencing changeovers "
                f"(effective={effective_changeovers}, raw={raw_changeovers}, locked={locked_changeovers})."
            ),
        }
    )
    return {
        "model_changeover_count": int(effective_changeovers),
        "raw_model_changeover_count": int(raw_changeovers),
        "locked_model_changeover_count": int(locked_changeovers),
    }


def _count_model_changeovers(frame: pd.DataFrame) -> int:
    if frame.empty or "model" not in frame.columns:
        return 0
    models = [str(m).strip() for m in frame["model"].fillna("").astype(str) if str(m).strip()]
    return sum(1 for prev, cur in zip(models, models[1:]) if prev != cur)
