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
    sequenced = _assign_timeline_with_fai_wait(sequenced, data)
    issues: list[dict[str, Any]] = []
    counts: dict[str, Any] = {}

    fai_sort_conflict_count = _check_fai_lock_seq_conflicts(sequenced, data, issues)
    split_count = _check_same_demand_same_slot_split(sequenced, issues)
    fai_count = _check_fai_precedence(sequenced, data, issues)
    capacity_count = _check_capacity(sequenced, data, issues)
    changeover_counts = _summarize_changeovers(sequenced, issues)

    counts.update(
        {
            "same_demand_same_slot_split_count": split_count,
            "fai_sort_conflict_count": fai_sort_conflict_count,
            "fai_violation_count": fai_count,
            "capacity_violation_slot_count": capacity_count,
            "time_overrun_row_count": int(
                pd.to_numeric(sequenced.get("time_overrun_flag", 0), errors="coerce").fillna(0).astype(int).sum()
            ),
            "fai_wait_minutes_total": float(
                pd.to_numeric(sequenced.get("fai_wait_minutes", 0.0), errors="coerce").fillna(0.0).sum()
            ),
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
    fai_rank_map, fai_role_map = _build_fai_sort_maps(data)
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
    out["_fai_rank"] = out["demand_id"].map(lambda d: int(fai_rank_map.get(str(d), 1))).astype(int)
    out["_fai_role"] = out["demand_id"].map(lambda d: str(fai_role_map.get(str(d), "")))

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
        "_fai_rank",
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
        "_fai_rank",
        "_fai_role",
        "_lock_source",
    ]
    return out.drop(columns=drop_cols, errors="ignore")


def _build_fai_sort_maps(data: ProcessedData) -> tuple[dict[str, int], dict[str, str]]:
    """Build demand-level FAI sorting rank (first=0, rest=2, other=1)."""
    rank: dict[str, int] = {}
    role: dict[str, str] = {}
    if data.fai_arcs.empty:
        return rank, role
    for arc in data.fai_arcs.itertuples(index=False):
        first_d = str(arc.first_demand_id)
        rest_d = str(arc.rest_demand_id)
        rank[first_d] = min(rank.get(first_d, 1), 0)
        role[first_d] = "first"
        rank[rest_d] = max(rank.get(rest_d, 1), 2)
        role[rest_d] = role.get(rest_d, "rest")
    return rank, role


def _check_fai_lock_seq_conflicts(solution: pd.DataFrame, data: ProcessedData, issues: list[dict[str, Any]]) -> int:
    """Report conflicts where lock seq implies rest-before-first inside same slot."""
    if data.fai_arcs.empty or solution.empty:
        return 0
    sol = solution.copy()
    sol["demand_id"] = sol["demand_id"].astype(str)
    sol["line_id"] = sol["line_id"].astype(str)
    sol["slot_id"] = sol["slot_id"].astype(str)
    sol["sequence"] = pd.to_numeric(sol.get("sequence", 0), errors="coerce").fillna(0).astype(int)
    pos = sol.set_index(["line_id", "slot_id", "demand_id"])["sequence"].to_dict()

    conflicts: list[tuple[str, str, str, str, str, int, int]] = []
    for arc in data.fai_arcs.itertuples(index=False):
        first_d = str(arc.first_demand_id)
        rest_d = str(arc.rest_demand_id)
        first_rows = sol[sol["demand_id"] == first_d][["line_id", "slot_id"]].drop_duplicates()
        rest_rows = sol[sol["demand_id"] == rest_d][["line_id", "slot_id"]].drop_duplicates()
        if first_rows.empty or rest_rows.empty:
            continue
        overlap = first_rows.merge(rest_rows, on=["line_id", "slot_id"], how="inner")
        for row in overlap.itertuples(index=False):
            key_first = (str(row.line_id), str(row.slot_id), first_d)
            key_rest = (str(row.line_id), str(row.slot_id), rest_d)
            seq_first = int(pos.get(key_first, 0))
            seq_rest = int(pos.get(key_rest, 0))
            if seq_first > 0 and seq_rest > 0 and seq_rest < seq_first:
                conflicts.append((str(getattr(arc, "group_id", "")), first_d, rest_d, str(row.line_id), str(row.slot_id), seq_first, seq_rest))
    if conflicts:
        sample = "; ".join(
            f"group={g} line={l} slot={s} first={f}@{sf} rest={r}@{sr}"
            for g, f, r, l, s, sf, sr in conflicts[:5]
        )
        issues.append(
            {
                "level": "warning",
                "where": "second_stage_fai_sort_conflict",
                "message": f"{len(conflicts)} FAI same-slot order conflicts (lock/seq precedence kept); sample={sample}",
            }
        )
    return int(len(conflicts))


def _assign_timeline_with_fai_wait(solution: pd.DataFrame, data: ProcessedData) -> pd.DataFrame:
    """v7.6 lightweight timeline with minute-level FAI wait insertion.

    This does not change quantity/line/slot assignment. It only computes
    start/end timestamps per row after sequencing.
    """
    out = solution.copy()
    if out.empty:
        out["schedule_start_time_calc"] = ""
        out["schedule_end_time_calc"] = ""
        out["fai_wait_minutes"] = 0.0
        out["time_overrun_flag"] = 0
        return out

    out["shift_start_time"] = pd.to_datetime(out.get("shift_start_time"), errors="coerce")
    out["shift_end_time"] = pd.to_datetime(out.get("shift_end_time"), errors="coerce")
    out["schedule_qty"] = pd.to_numeric(out.get("schedule_qty", 0), errors="coerce").fillna(0.0)
    out["uph"] = pd.to_numeric(out.get("uph", 0), errors="coerce").fillna(0.0)
    out["sequence"] = pd.to_numeric(out.get("sequence", 0), errors="coerce").fillna(0).astype(int)
    out["demand_id"] = out["demand_id"].astype(str)
    out["line_id"] = out["line_id"].astype(str)
    out["slot_id"] = out["slot_id"].astype(str)

    # rest_demand -> list[(first_demand, lead_hours)]
    incoming: dict[str, list[tuple[str, float]]] = {}
    if not data.fai_arcs.empty:
        for arc in data.fai_arcs.itertuples(index=False):
            rest = str(arc.rest_demand_id)
            first = str(arc.first_demand_id)
            lead = float(getattr(arc, "lead_hours", 0.0) or 0.0)
            incoming.setdefault(rest, []).append((first, lead))

    ordered = out.sort_values(
        ["shift_start_time", "line_id", "slot_id", "sequence", "demand_id"],
        kind="mergesort",
    ).copy()
    finish_by_demand: dict[str, pd.Timestamp] = {}
    starts: list[pd.Timestamp | pd.NaT] = []
    ends: list[pd.Timestamp | pd.NaT] = []
    waits: list[float] = []
    overruns: list[int] = []

    for _, group in ordered.groupby(["line_id", "slot_id"], sort=False):
        cursor = pd.to_datetime(group["shift_start_time"].iloc[0], errors="coerce")
        slot_end = pd.to_datetime(group["shift_end_time"].iloc[0], errors="coerce")
        for row in group.itertuples(index=False):
            base_start = cursor
            demand_id = str(row.demand_id)
            start = base_start
            wait_minutes = 0.0
            if demand_id in incoming and pd.notna(base_start):
                required_times: list[pd.Timestamp] = []
                for first_d, lead_h in incoming[demand_id]:
                    finish_first = finish_by_demand.get(first_d)
                    if finish_first is not None:
                        required_times.append(pd.Timestamp(finish_first) + pd.Timedelta(hours=float(lead_h)))
                if required_times:
                    required = max(required_times)
                    if pd.Timestamp(base_start) < required:
                        start = required
                        wait_minutes = max((required - pd.Timestamp(base_start)).total_seconds() / 60.0, 0.0)

            uph = float(getattr(row, "uph", 0.0) or 0.0)
            qty = float(getattr(row, "schedule_qty", 0.0) or 0.0)
            duration = pd.Timedelta(hours=qty / uph) if uph > 0 and qty > 0 else pd.Timedelta(0)
            end = start + duration if pd.notna(start) else pd.NaT
            overrun = int(pd.notna(slot_end) and pd.notna(end) and end > slot_end + pd.Timedelta(seconds=1))

            starts.append(start)
            ends.append(end)
            waits.append(wait_minutes)
            overruns.append(overrun)

            if pd.notna(end):
                cursor = end
                prev_finish = finish_by_demand.get(demand_id)
                if prev_finish is None or pd.Timestamp(end) > pd.Timestamp(prev_finish):
                    finish_by_demand[demand_id] = pd.Timestamp(end)

    ordered["schedule_start_time_calc"] = [_format_datetime(ts) for ts in starts]
    ordered["schedule_end_time_calc"] = [_format_datetime(ts) for ts in ends]
    ordered["fai_wait_minutes"] = waits
    ordered["time_overrun_flag"] = overruns
    return ordered.sort_index()


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
    start_col = "schedule_start_time_calc" if "schedule_start_time_calc" in sol.columns else "shift_start_time"
    end_col = "schedule_end_time_calc" if "schedule_end_time_calc" in sol.columns else "shift_end_time"
    sol[start_col] = pd.to_datetime(sol[start_col], errors="coerce")
    sol[end_col] = pd.to_datetime(sol[end_col], errors="coerce")
    finish = sol.dropna(subset=[end_col]).groupby("demand_id")[end_col].max()
    start = sol.dropna(subset=[start_col]).groupby("demand_id")[start_col].min()

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


def _format_datetime(value: Any) -> str:
    if pd.isna(value):
        return ""
    return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M:%S")
