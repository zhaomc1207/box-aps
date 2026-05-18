"""Data preparation for the BOX APS MILP model.

The transformation follows ``业务规则到MILP数学约束映射表_v6.md``:

* demand-level aggregation by ``demand_id``;
* master PN enrichment for model/program/color/texture;
* sparse ``(demand, line, slot)`` eligibility from UPH/calendar/MR/rules;
* FIX and inherited schedule locks;
* external inherited schedule capacity occupation;
* priority-group matching and FAI first/rest arcs.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import logging
from pathlib import Path
from typing import Any, Iterable
import json
import math
import time

import pandas as pd


logger = logging.getLogger(__name__)


REQUIRED_SHEETS = [
    "aps_schedule_master_pn_input",
    "aps_schedule_demand_base_input",
    "aps_schedule_demand_fai_input",
    "aps_schedule_demand_fix_input",
    "aps_schedule_line_input",
    "aps_schedule_line_calendar",
    "aps_schedule_off_time_input",
    "aps_schedule_uph_input",
    "aps_change_time_input",
    "aps_schedule_limit_setting",
    "aps_schedule_order_ruler",
    "aps_schedule_order_qty",
    "aps_schedule_priority",
    "aps_adjust_schedule_input",
]


# v7_2: optional sheets covering rule 7 (产能预留) and rule 6 (班次预留产能)
# auxiliary inputs. Missing sheets degrade gracefully.
OPTIONAL_SHEETS = [
    "aps_schedule_reserver_input",
    "aps_schedule_demand_reserve_input",
    "aps_merge_priority_setting",
    "aps_schedule_merge_priority_setting",
    "aps_schedule_cycle_merge_setting",
]


TABLE_FILES = {
    "raw_demands": "raw_demands.csv",
    "demands": "demands.csv",
    "merge_map": "merge_map.csv",
    "cycle_merge_map": "cycle_merge_map.csv",
    "lines": "lines.csv",
    "slots": "slots.csv",
    "line_slots": "line_slots.csv",
    "triples": "triples.csv",
    "fixed_locks": "fixed_locks.csv",
    "adjust_locks": "adjust_locks.csv",
    "fai_arcs": "fai_arcs.csv",
    "priority": "priority.csv",
    "change_min": "change_min.csv",
    "order_keys": "order_keys.csv",
    "issues": "issues.csv",
}


@dataclass(slots=True)
class PreprocessConfig:
    """Options controlling data transformation.

    ``horizon_days`` and ``max_demands`` are useful for development runs. Leave
    them as ``None`` for the full instance.
    """

    schedule_version: str | None = None
    sub_schedule_version: str | None = None
    start_date: str | None = None
    horizon_days: int | None = None
    max_demands: int | None = None
    calendar_require_demand_flag: bool = False
    fai_lead_time_unit: str = "hours"
    include_locked_triples: bool = True
    default_kpi_mode: str = "qtymax"
    # v7_1: relax candidate pruning to trade more solver time for tighter solutions.
    due_buffer_days: int | None = 3
    # v7.6: KPI-specific timely buffers. When unset, fall back to due_buffer_days
    # to preserve backward compatibility with historical preprocessing behavior.
    ots_buffer_days: int | None = None
    fpsd_buffer_days: int | None = None
    ship2_buffer_days: int | None = None
    ots_ext_days: int = 3
    fpsd_ext_days: int = 3
    ship2_ext_days: int = 3
    max_lines_per_demand_day: int | None = 5
    max_slots_per_demand: int | None = 60
    bucket_after_days: int | None = 5
    # v7.6: slot-level FAI capacity reservation B_{lt}^{fai}. Disabled by
    # default to preserve backward compatibility with historical runs.
    enable_fai_slot_buffer: bool = False
    # v7.6 strategy switch: "strict" applies slot buffer to all eligible slots,
    # while "lock_friendly" skips slots that already carry lock rows.
    fai_buffer_policy: str = "lock_friendly"
    # Optional upper cap (minutes) for per-(line, slot) reservation.
    fai_buffer_cap_minutes: float | None = None


@dataclass(slots=True)
class ProcessedData:
    config: PreprocessConfig
    metadata: dict[str, Any]
    demands: pd.DataFrame
    lines: pd.DataFrame
    slots: pd.DataFrame
    line_slots: pd.DataFrame
    triples: pd.DataFrame
    fixed_locks: pd.DataFrame
    adjust_locks: pd.DataFrame
    fai_arcs: pd.DataFrame
    priority: pd.DataFrame
    change_min: pd.DataFrame
    order_keys: pd.DataFrame
    raw_demands: pd.DataFrame = field(default_factory=pd.DataFrame)
    merge_map: pd.DataFrame = field(default_factory=pd.DataFrame)
    cycle_merge_map: pd.DataFrame = field(default_factory=pd.DataFrame)
    issues: pd.DataFrame = field(default_factory=pd.DataFrame)

    def save(self, output_dir: str | Path) -> None:
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        meta = {
            "config": asdict(self.config),
            "metadata": self.metadata,
            "tables": TABLE_FILES,
        }
        (output / "metadata.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        for attr, filename in TABLE_FILES.items():
            getattr(self, attr).to_csv(output / filename, index=False, encoding="utf-8-sig")


def load_processed_data(input_dir: str | Path) -> ProcessedData:
    input_path = Path(input_dir)
    meta = json.loads((input_path / "metadata.json").read_text(encoding="utf-8"))
    config = PreprocessConfig(**meta["config"])
    tables = {}
    for attr, filename in TABLE_FILES.items():
        path = input_path / filename
        tables[attr] = pd.read_csv(path, dtype=str, keep_default_na=False) if path.exists() else pd.DataFrame()
    tables["raw_demands"] = _restore_numeric(tables["raw_demands"], ["qty", "priority_rank", "priority_weight", "total_index"])
    tables["demands"] = _restore_numeric(tables["demands"], ["qty", "priority_rank", "priority_weight"])
    tables["merge_map"] = _restore_numeric(tables["merge_map"], ["raw_qty", "member_rank", "merge_applied"])
    tables["cycle_merge_map"] = _restore_numeric(tables["cycle_merge_map"], ["member_rank", "merge_applied"])
    for col in ["mr_day_dt", "ots_date_dt", "fpsd_dt", "ship_day_two_dt", "reference_date"]:
        if col in tables["raw_demands"].columns:
            tables["raw_demands"][col] = pd.to_datetime(tables["raw_demands"][col], errors="coerce")
    for col in ["mr_day_dt", "ots_date_dt", "fpsd_dt", "ship_day_two_dt", "reference_date"]:
        if col in tables["demands"].columns:
            tables["demands"][col] = pd.to_datetime(tables["demands"][col], errors="coerce")
    tables["slots"] = _restore_numeric(tables["slots"], ["slot_rank", "start_hour", "end_hour"])
    for col in ["day", "shift_start_time", "shift_end_time"]:
        if col in tables["slots"].columns:
            tables["slots"][col] = pd.to_datetime(tables["slots"][col], errors="coerce")
    tables["line_slots"] = _restore_numeric(
        tables["line_slots"],
        [
            "cap_hours",
            "down_hours",
            "reserved_hours",
            "occupied_hours",
            "avail_hours",
            "fai_buffer_hours",
            "fai_buffer_minutes",
            "slot_rank",
            "non_merge_flag",
            "fix_type",
            "allow_calendar",
        ],
    )
    for col in ["day", "shift_start_time", "shift_end_time"]:
        if col in tables["line_slots"].columns:
            tables["line_slots"][col] = pd.to_datetime(tables["line_slots"][col], errors="coerce")
    tables["triples"] = _restore_numeric(
        tables["triples"],
        [
            "uph",
            "elig",
            "slot_rank",
            "is_ots_timely",
            "is_fpsd_timely",
            "is_ship2_timely",
            "is_ots_extended",
            "is_fpsd_extended",
            "is_ship2_extended",
            "keep_by_timely",
            "keep_by_extended",
        ],
    )
    tables["fai_arcs"] = _restore_numeric(tables["fai_arcs"], ["lead_hours"])
    tables["change_min"] = _restore_numeric(tables["change_min"], ["ct_min_hours"])
    return ProcessedData(config=config, metadata=meta["metadata"], **tables)


def build_processed_data(input_xlsx: str | Path, config: PreprocessConfig | None = None) -> ProcessedData:
    t0 = time.perf_counter()
    logger.info("preprocess:start input=%s", Path(input_xlsx).resolve())
    config = config or PreprocessConfig()
    sheets = read_input_workbook(input_xlsx)
    logger.info("preprocess:read_workbook sheets=%s", len(sheets))
    sheets = _filter_versions(sheets, config)
    issues: list[dict[str, Any]] = []

    preliminary_line_slots, preliminary_slots = _build_slots_and_line_slots(sheets, config)
    start_ts, end_ts = _resolve_horizon(preliminary_slots, config)
    logger.info(
        "preprocess:horizon start=%s end=%s prelim_slots=%s prelim_line_slots=%s",
        start_ts,
        end_ts,
        len(preliminary_slots),
        len(preliminary_line_slots),
    )
    sheets = _filter_horizon(sheets, start_ts, end_ts)
    line_slots, slots = _build_slots_and_line_slots(sheets, config)
    lines = _build_lines(sheets, line_slots)
    logger.info("preprocess:calendar lines=%s slots=%s line_slots=%s", len(lines), len(slots), len(line_slots))

    raw_demands = _build_demands(sheets, slots, config, issues)
    merge_excluded = _merge_excluded_demand_ids(sheets, raw_demands)
    demands, merge_map, cycle_merge_map, merge_trace = _apply_merge_priority(sheets, raw_demands, merge_excluded, issues)
    logger.info(
        "preprocess:demands raw=%s merged=%s merge_map=%s excluded=%s",
        len(raw_demands),
        len(demands),
        len(merge_map),
        len(merge_excluded),
    )
    uph = _normalize_uph(sheets.get("aps_schedule_uph_input", pd.DataFrame()))
    line_slots = _apply_downtime(line_slots, sheets.get("aps_schedule_off_time_input", pd.DataFrame()))
    # v7_2: rule 7 capacity reservation. Reads optional aps_schedule_reserver_input and
    # subtracts the reserved time from each affected (line, slot) avail_hours.
    line_slots = _apply_reservations(
        line_slots,
        sheets.get("aps_schedule_reserver_input", pd.DataFrame()),
        issues,
    )

    fixed_locks = _build_fixed_locks(sheets, demands, slots, config, issues)
    adjust_locks, external_adjust = _split_adjust_schedule(sheets, demands, slots, issues)
    occupied = _build_external_occupation(external_adjust, uph, issues)
    line_slots = _apply_external_occupation(line_slots, occupied)
    logger.info(
        "preprocess:locks fixed=%s adjust=%s external_adjust=%s external_occupied_slots=%s",
        len(fixed_locks),
        len(adjust_locks),
        len(external_adjust),
        len(occupied),
    )

    triples = _build_sparse_triples(
        demands=demands,
        lines=lines,
        slots=slots,
        line_slots=line_slots,
        uph=uph,
        order_qty=sheets.get("aps_schedule_order_qty", pd.DataFrame()),
        limit_rules=sheets.get("aps_schedule_limit_setting", pd.DataFrame()),
        fixed_locks=fixed_locks,
        adjust_locks=adjust_locks,
        config=config,
        issues=issues,
    )
    priority, kpi_mode = _build_priority(sheets, demands, slots, config, issues)
    demands = demands.merge(priority[["demand_id", "priority_rank", "priority_weight"]], on="demand_id", how="left")
    demands["priority_rank"] = demands["priority_rank"].fillna(priority["priority_rank"].max() + 1 if len(priority) else 99)
    demands["priority_weight"] = demands["priority_weight"].fillna(1.0)
    raw_demands = _propagate_priority_to_raw_demands(raw_demands, merge_map, demands)

    fai_arcs = _build_fai_arcs(sheets, demands, config, issues)
    change_min = _build_change_min(sheets, lines, demands)
    order_keys = _build_order_keys(sheets)

    raw_triples = int(len(triples))
    triples = _prune_sparse_triples(triples, demands, slots, config, issues)
    pruned_triples = int(len(triples))

    (
        triples,
        line_slots,
        slots,
        fixed_locks,
        adjust_locks,
    ) = _apply_day_buckets(triples, line_slots, slots, fixed_locks, adjust_locks, config)
    # v7.6: optional FAI slot-level capacity reservation attached to line_slots.
    line_slots = _apply_fai_slot_buffer(
        line_slots=line_slots,
        triples=triples,
        fai_arcs=fai_arcs,
        fixed_locks=fixed_locks,
        adjust_locks=adjust_locks,
        config=config,
    )
    bucketed_triples = int(len(triples))
    logger.info(
        "preprocess:triples raw=%s pruned=%s bucketed=%s",
        raw_triples,
        pruned_triples,
        bucketed_triples,
    )
    merge_applied_series = (
        pd.to_numeric(merge_map["merge_applied"], errors="coerce").fillna(0).astype(int)
        if len(merge_map) and "merge_applied" in merge_map.columns
        else pd.Series(dtype=int)
    )
    merge_applied_raw = int(merge_applied_series.sum()) if len(merge_applied_series) else 0
    merge_group_count = (
        int(merge_map.loc[merge_applied_series > 0, "merged_demand_id"].nunique())
        if len(merge_applied_series)
        else 0
    )

    metadata = {
        "input_xlsx": str(Path(input_xlsx).resolve()),
        "schedule_version": config.schedule_version,
        "sub_schedule_version": config.sub_schedule_version,
        "start": start_ts.isoformat() if pd.notna(start_ts) else None,
        "end": end_ts.isoformat() if pd.notna(end_ts) else None,
        "kpi_mode": kpi_mode,
        "merge_settings": {
            "candidate_raw_demands": int(len(raw_demands)),
            "merged_demands": int(len(demands)),
            "merge_applied_raw_demands": merge_applied_raw,
            "merge_groups": merge_group_count,
        },
        "priority_settings": {
            "schedule_priority_sheet": "aps_schedule_priority",
            "schedule_priority_active": bool(not sheets.get("aps_schedule_priority", pd.DataFrame()).empty),
            "merge_priority_sheet": str(merge_trace.get("merge_source_table", "none")),
            "merge_priority_loaded": bool(str(merge_trace.get("merge_source_table", "none")) != "none"),
            "merge_priority_applied": bool(merge_applied_raw > 0),
            "cycle_merge_enabled": bool(merge_trace.get("cycle_merge_enabled", False)),
            "cycle_merge_source_table": str(merge_trace.get("cycle_merge_source_table", "none")),
            "cycle_merge_hit_rules": int(merge_trace.get("cycle_merge_hit_rules", 0)),
            "merge_execution_order": str(merge_trace.get("merge_execution_order", "priority_then_cycle")),
        },
        "kpi_settings": {
            "ots_ext_days": int(config.ots_ext_days),
            "fpsd_ext_days": int(config.fpsd_ext_days),
            "ship2_ext_days": int(config.ship2_ext_days),
            "due_buffer_days_legacy": None if config.due_buffer_days is None else int(config.due_buffer_days),
            "kpi_cutoff_policy": "end_of_day",
            "enable_fai_slot_buffer": bool(config.enable_fai_slot_buffer),
            "fai_buffer_policy": str(config.fai_buffer_policy),
            "fai_buffer_cap_minutes": (
                None if config.fai_buffer_cap_minutes is None else float(config.fai_buffer_cap_minutes)
            ),
        },
        "counts": {
            "raw_demands": int(len(raw_demands)),
            "demands": int(len(demands)),
            "lines": int(len(lines)),
            "slots": int(len(slots)),
            "line_slots": int(len(line_slots)),
            "triples": int(len(triples)),
            "raw_triples": raw_triples,
            "pruned_triples": pruned_triples,
            "bucketed_triples": bucketed_triples,
            "fixed_locks": int(len(fixed_locks)),
            "adjust_locks": int(len(adjust_locks)),
            "fai_arcs": int(len(fai_arcs)),
            "fai_buffered_line_slots": int(
                pd.to_numeric(line_slots.get("fai_buffer_hours", 0.0), errors="coerce").fillna(0.0).gt(0).sum()
            ),
        },
    }

    out = ProcessedData(
        config=config,
        metadata=metadata,
        raw_demands=raw_demands,
        demands=demands,
        merge_map=merge_map,
        cycle_merge_map=cycle_merge_map,
        lines=lines,
        slots=slots,
        line_slots=line_slots,
        triples=triples,
        fixed_locks=fixed_locks,
        adjust_locks=adjust_locks,
        fai_arcs=fai_arcs,
        priority=priority,
        change_min=change_min,
        order_keys=order_keys,
        issues=pd.DataFrame(issues),
    )
    logger.info("preprocess:done elapsed_sec=%.3f issues=%s", time.perf_counter() - t0, len(out.issues))
    return out


def read_input_workbook(input_xlsx: str | Path) -> dict[str, pd.DataFrame]:
    path = Path(input_xlsx)
    xl = pd.ExcelFile(path)
    sheets: dict[str, pd.DataFrame] = {}
    missing = [s for s in REQUIRED_SHEETS if s not in xl.sheet_names]
    if missing:
        raise ValueError(f"Missing required sheets: {', '.join(missing)}")
    for sheet in REQUIRED_SHEETS:
        sheets[sheet] = _clean_frame(pd.read_excel(path, sheet_name=sheet))
    for sheet in OPTIONAL_SHEETS:
        if sheet in xl.sheet_names:
            sheets[sheet] = _clean_frame(pd.read_excel(path, sheet_name=sheet))
        else:
            sheets[sheet] = pd.DataFrame()
    return sheets


def _clean_frame(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    df = df.loc[:, ~df.columns.str.match(r"^Unnamed")]
    for col in df.columns:
        if pd.api.types.is_object_dtype(df[col]) or pd.api.types.is_string_dtype(df[col]):
            df[col] = df[col].map(_clean_cell)
    return df


def _clean_cell(value: Any) -> Any:
    if value is None:
        return pd.NA
    try:
        if pd.isna(value):
            return pd.NA
    except TypeError:
        pass
    if isinstance(value, str):
        value = value.strip()
        return pd.NA if value == "" else value
    return value


def _restore_numeric(df: pd.DataFrame, cols: Iterable[str]) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    for col in cols:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def _filter_versions(sheets: dict[str, pd.DataFrame], config: PreprocessConfig) -> dict[str, pd.DataFrame]:
    demand_base = sheets["aps_schedule_demand_base_input"]
    if config.schedule_version is None and "schedule_version" in demand_base.columns:
        versions = demand_base["schedule_version"].dropna()
        if len(versions):
            config.schedule_version = str(versions.mode().iloc[0])
    if config.sub_schedule_version is None:
        # Do not infer this by default: adjust_schedule commonly belongs to a
        # later sub-version while still being the inherited schedule for this run.
        pass

    filtered: dict[str, pd.DataFrame] = {}
    for name, df in sheets.items():
        out = df.copy()
        if config.schedule_version and "schedule_version" in out.columns:
            out = out[out["schedule_version"].astype(str) == config.schedule_version]
        if config.schedule_version and name == "aps_adjust_schedule_input" and "run_version" in out.columns:
            out = out[out["run_version"].astype(str) == config.schedule_version]
        if config.sub_schedule_version and "sub_schedule_version" in out.columns:
            out = out[out["sub_schedule_version"].astype(str) == config.sub_schedule_version]
        filtered[name] = out.reset_index(drop=True)
    return filtered


def _to_id(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _fast_to_datetime_cleaned(series: pd.Series) -> pd.Series:
    """Fast datetime parse for large string columns.

    Keeps existing semantics:
    - empty string -> NaT
    - invalid text -> NaT
    - still supports mixed formats via fallback
    """
    cleaned = series.fillna("").astype(str).str.strip()
    masked = cleaned.where(cleaned.ne(""))

    # Fast path: common BOX date format (YYYY-MM-DD)
    parsed = pd.to_datetime(masked, format="%Y-%m-%d", errors="coerce")

    # Fallback path: only parse rows not handled by fast path
    need_fallback = masked.notna() & parsed.isna()
    if need_fallback.any():
        parsed.loc[need_fallback] = pd.to_datetime(masked.loc[need_fallback], errors="coerce")

    return parsed


def _safe_datetime(series: pd.Series) -> pd.Series:
    text = series.astype("string").str.strip()
    text = text.mask(text.str.startswith("9999", na=False))
    return _fast_to_datetime_cleaned(text)


def _safe_numeric(series: pd.Series, default: float = 0.0) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(default)


def _truthy(value: Any) -> bool:
    if value is None or pd.isna(value):
        return False
    if isinstance(value, str):
        return value.strip().upper() in {"1", "Y", "YES", "TRUE", "T", "X"}
    return bool(value)


def _urgent_flag(value: Any) -> bool:
    """Treat business urgent markers (URGENT / Y / 1 / X / ...) as truthy.

    `aps_schedule_demand_base_input.om_urgent` in BOX data uses the literal
    text "URGENT" rather than a boolean character, so the standard `_truthy`
    helper would miss it. We extend the rule to accept any non-empty token
    that is not an explicit negation (0/N/NO/FALSE/F).
    """
    if value is None or pd.isna(value):
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().upper()
    if text in {"", "0", "N", "NO", "FALSE", "F"}:
        return False
    return True


def _resolve_horizon(slots: pd.DataFrame, config: PreprocessConfig) -> tuple[pd.Timestamp, pd.Timestamp]:
    if slots.empty:
        return pd.NaT, pd.NaT
    start = pd.to_datetime(config.start_date) if config.start_date else slots["shift_start_time"].min()
    if config.horizon_days:
        end = start + pd.Timedelta(days=config.horizon_days)
    else:
        end = slots["shift_end_time"].max()
    return start, end


def _filter_horizon(
    sheets: dict[str, pd.DataFrame],
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
) -> dict[str, pd.DataFrame]:
    if pd.isna(start_ts) or pd.isna(end_ts):
        return sheets
    result = dict(sheets)
    if "aps_schedule_line_calendar" in result:
        cal = result["aps_schedule_line_calendar"]
        if "shift_start_time" in cal.columns:
            shift_start = _safe_datetime(cal["shift_start_time"])
            result["aps_schedule_line_calendar"] = cal[(shift_start >= start_ts) & (shift_start < end_ts)].reset_index(drop=True)
    if "aps_schedule_off_time_input" in result:
        off = result["aps_schedule_off_time_input"]
        if "start_time" in off.columns:
            off_start = _safe_datetime(off["start_time"])
            result["aps_schedule_off_time_input"] = off[(off_start >= start_ts) & (off_start < end_ts)].reset_index(drop=True)

    day_min = start_ts.normalize()
    day_max_exclusive = end_ts.normalize()
    if end_ts > day_max_exclusive:
        day_max_exclusive = day_max_exclusive + pd.Timedelta(days=1)
    for name, day_col in [
        ("aps_schedule_uph_input", "day"),
        ("aps_schedule_demand_fix_input", "fix_day"),
        ("aps_adjust_schedule_input", "schedule_day"),
    ]:
        df = result.get(name)
        if df is None or df.empty or day_col not in df.columns:
            continue
        day = _safe_datetime(df[day_col]).dt.normalize()
        result[name] = df[(day >= day_min) & (day < day_max_exclusive)].reset_index(drop=True)
    return result


def _slot_id(day: Any, shift_seq: Any) -> str:
    day_ts = pd.to_datetime(day, errors="coerce")
    day_text = day_ts.strftime("%Y-%m-%d") if pd.notna(day_ts) else str(day).strip()
    shift = int(float(shift_seq)) if pd.notna(shift_seq) and str(shift_seq).strip() != "" else 0
    return f"{day_text}|{shift}"


def _build_slots_and_line_slots(
    sheets: dict[str, pd.DataFrame],
    config: PreprocessConfig,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    cal = sheets["aps_schedule_line_calendar"].copy()
    cal["line_id"] = cal["line_id"].map(_to_id)
    cal["shift_seq"] = _safe_numeric(cal["shift_seq"]).astype(int)
    cal["day_dt"] = _safe_datetime(cal["day"]).dt.normalize()
    cal["shift_start_time"] = _safe_datetime(cal["shift_start_time"])
    cal["shift_end_time"] = _safe_datetime(cal["shift_end_time"])
    cal["slot_id"] = [_slot_id(d, s) for d, s in zip(cal["day_dt"], cal["shift_seq"])]
    cal["cap_hours"] = (cal["shift_end_time"] - cal["shift_start_time"]).dt.total_seconds() / 3600.0
    cal["cap_hours"] = cal["cap_hours"].clip(lower=0)
    cal["shift_status"] = cal.get("shift_status", pd.Series(index=cal.index, dtype="object")).astype("string").str.upper()
    allow = cal["shift_status"].eq("ON")
    # Field doc: demand_flag=1 means "Normal orders cannot be scheduled here".
    # The previous semantics required the flag to be truthy to allow scheduling
    # which inverted the catalog meaning. v7_2 corrects this so the option,
    # when enabled, hides slots flagged as 1 (i.e., non-Normal-only blocks).
    if config.calendar_require_demand_flag and "demand_flag" in cal.columns:
        allow &= ~cal["demand_flag"].map(_truthy)
    cal["allow_calendar"] = allow.astype(int)
    # v7_2: surface calendar metadata (non_merge_flag / fix_type) to downstream
    # second stage so 班次产能预留 / 班次FIX can be respected. They do not change
    # capacity directly but inform the local sequencer.
    if "non_merge_flag" in cal.columns:
        cal["non_merge_flag"] = _safe_numeric(cal["non_merge_flag"]).astype(int)
    else:
        cal["non_merge_flag"] = 0
    if "fix_type" in cal.columns:
        cal["fix_type"] = _safe_numeric(cal["fix_type"]).astype(int)
    else:
        cal["fix_type"] = 0

    line_slots = cal[
        [
            "line_id",
            "slot_id",
            "day_dt",
            "shift_seq",
            "shift_start_time",
            "shift_end_time",
            "cap_hours",
            "allow_calendar",
            "non_merge_flag",
            "fix_type",
        ]
    ].drop_duplicates(["line_id", "slot_id"])
    line_slots = line_slots.rename(columns={"day_dt": "day"})

    slots = (
        line_slots.groupby("slot_id", as_index=False)
        .agg(
            day=("day", "first"),
            shift_seq=("shift_seq", "first"),
            shift_start_time=("shift_start_time", "min"),
            shift_end_time=("shift_end_time", "max"),
        )
        .sort_values(["shift_start_time", "slot_id"])
        .reset_index(drop=True)
    )
    start0 = slots["shift_start_time"].min()
    slots["slot_rank"] = range(len(slots))
    slots["start_hour"] = (slots["shift_start_time"] - start0).dt.total_seconds() / 3600.0
    slots["end_hour"] = (slots["shift_end_time"] - start0).dt.total_seconds() / 3600.0
    line_slots = line_slots.merge(slots[["slot_id", "slot_rank", "start_hour", "end_hour"]], on="slot_id", how="left")
    line_slots["down_hours"] = 0.0
    line_slots["reserved_hours"] = 0.0
    line_slots["occupied_hours"] = 0.0
    line_slots["avail_hours"] = line_slots["cap_hours"].fillna(0.0)
    return line_slots.reset_index(drop=True), slots.reset_index(drop=True)


def _build_lines(sheets: dict[str, pd.DataFrame], line_slots: pd.DataFrame) -> pd.DataFrame:
    lines = sheets["aps_schedule_line_input"].copy()
    lines["line_id"] = lines["line_id"].map(_to_id)
    if "line_type" not in lines.columns:
        lines["line_type"] = ""
    if "line" not in lines.columns:
        lines["line"] = lines["line_id"]
    if "pu" not in lines.columns:
        lines["pu"] = ""
    lines = lines.drop_duplicates("line_id")
    lines["line_type"] = lines["line_type"].fillna("").astype(str)
    lines["open_type"] = lines.get("open_type", "").fillna("").astype(str)
    lines["cell_flag"] = (
        lines["line_type"].str.lower().str.contains("cell", na=False) | lines["open_type"].str.contains("小线", na=False)
    ).astype(int)
    line_ids = set(line_slots["line_id"].astype(str))
    lines = lines[lines["line_id"].isin(line_ids)]
    return lines[["line_id", "line", "line_type", "open_type", "pu", "pu_site", "cell_flag"]].reset_index(drop=True)


def _build_demands(
    sheets: dict[str, pd.DataFrame],
    slots: pd.DataFrame,
    config: PreprocessConfig,
    issues: list[dict[str, Any]],
) -> pd.DataFrame:
    base = sheets["aps_schedule_demand_base_input"].copy()
    base["demand_id"] = base["demand_id"].map(_to_id)
    base["qty"] = _safe_numeric(base["qty"]).astype(int)
    base = base[base["demand_id"] != ""]

    master = sheets["aps_schedule_master_pn_input"].copy()
    if "pn" in master.columns:
        master["pn"] = master["pn"].astype("string").str.strip()
        master_cols = [c for c in ["pn", "model", "program", "texture", "color", "series"] if c in master.columns]
        master = master[master_cols].dropna(subset=["pn"]).drop_duplicates("pn")
        base = base.merge(master, on="pn", how="left", suffixes=("", "_master"))

    for col in ["model", "program", "texture", "color", "series"]:
        if col not in base.columns:
            base[col] = pd.NA
        master_col = f"{col}_master"
        if master_col in base.columns:
            base[col] = base[col].combine_first(base[master_col])

    agg: dict[str, Any] = {
        "qty": "max",
        "pn": "first",
        "mcode": "first",
        "model": "first",
        "program": "first",
        "texture": "first",
        "color": "first",
        "series": "first",
        "demand_type": "first",
        "mr_day": "first",
        "ots_date": "first",
        "fpsd": "first",
        "ship_day_two": "first",
        "pre_lock": "max",
        "fix_flag": "max",
        "fast_ship": "max",
        "cust_svc": "max",
        "om_urgent": "first",
        "ord_qty": "max",
        "line_qty": "max",
        "total_index": "min",
        "pu_site": "first",
        "plant": "first",
        "mo": "first",
        "lot": "first",
        "kb": "first",
        "cover_assy": "first",
        "log_up_assy": "first",
        "pcba": "first",
        "thermal": "first",
        "material_sections": "first",
        "material_type": "first",
        "eop": "first",
        "country": "first",
        "priority_code": "first",
    }
    for col in list(agg):
        if col not in base.columns:
            base[col] = pd.NA
    grouped = base.groupby("demand_id", as_index=False).agg(agg)
    duplicate_count = int(len(base) - len(grouped))
    if duplicate_count:
        issues.append({"level": "info", "where": "demands", "message": f"Aggregated {duplicate_count} duplicate demand rows by demand_id."})

    grouped["qty"] = _safe_numeric(grouped["qty"]).astype(int)
    grouped = grouped[grouped["qty"] > 0]
    for col in ["pre_lock", "fix_flag", "fast_ship", "cust_svc"]:
        grouped[col] = grouped[col].map(_truthy).astype(int)
    # om_urgent in the source data uses the literal "URGENT"; treat any non-empty
    # text token (URGENT / Y / 1 / X / TRUE / T) as a positive urgent flag.
    grouped["urgent"] = grouped["om_urgent"].map(_urgent_flag).astype(int)
    for col in ["mr_day", "ots_date", "fpsd", "ship_day_two"]:
        grouped[f"{col}_dt"] = _safe_datetime(grouped[col])

    grouped["mcode"] = grouped["mcode"].fillna("").astype(str)
    grouped["model"] = grouped["model"].fillna("").astype(str)
    missing_model = int(grouped["model"].eq("").sum())
    if missing_model:
        issues.append({"level": "warning", "where": "demands", "message": f"{missing_model} demands have no model after PN enrichment."})

    ref_date = slots["shift_start_time"].min().normalize() if len(slots) else pd.Timestamp.today().normalize()
    grouped["reference_date"] = ref_date
    grouped = grouped.sort_values(["total_index", "demand_id"], na_position="last").reset_index(drop=True)
    if config.max_demands is not None:
        grouped = grouped.head(config.max_demands).copy()
    return grouped.reset_index(drop=True)


MERGE_STAGE_FIELD_MAP: dict[str, list[str]] = {
    "pn属性合并": ["model", "program", "texture", "series"],
    "mtm属性合并": ["model", "program", "texture", "series"],
    "demand属性合并": [
        "demand_type",
        "priority_code",
        "status",
        "pre_lock",
        "pre_plan",
        "fast_ship",
        "cust_svc",
        "om_urgent",
        "mr_day",
        "ots_date",
        "fpsd",
        "ship_day_two",
    ],
    "颜色材料项合并": [
        "color",
        "kb",
        "cover_assy",
        "log_up_assy",
        "pcba",
        "thermal",
        "material_sections",
        "material_type",
        "country",
    ],
    "pn合并": ["pn"],
    "mtm合并": ["pn"],
}


def _merge_excluded_demand_ids(sheets: dict[str, pd.DataFrame], raw_demands: pd.DataFrame) -> set[str]:
    excluded: set[str] = set()
    if raw_demands.empty:
        return excluded
    demand_ids = set(raw_demands["demand_id"].astype(str))

    if "lot" in raw_demands.columns:
        lot_mask = raw_demands["lot"].fillna("").astype(str).str.strip().ne("")
        excluded.update(raw_demands.loc[lot_mask, "demand_id"].astype(str))

    fix = sheets.get("aps_schedule_demand_fix_input", pd.DataFrame())
    if not fix.empty and "demand_id" in fix.columns:
        excluded.update(fix["demand_id"].map(_to_id))

    adjust = sheets.get("aps_adjust_schedule_input", pd.DataFrame())
    if not adjust.empty and "demand_id" in adjust.columns:
        inside = adjust["demand_id"].map(_to_id)
        excluded.update(d for d in inside if d in demand_ids)

    fai = sheets.get("aps_schedule_demand_fai_input", pd.DataFrame())
    if not fai.empty and "demand_id" in fai.columns:
        excluded.update(fai["demand_id"].map(_to_id))

    return {str(d) for d in excluded if str(d)}


def _apply_merge_priority(
    sheets: dict[str, pd.DataFrame],
    raw_demands: pd.DataFrame,
    excluded_ids: set[str],
    issues: list[dict[str, Any]],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    if raw_demands.empty:
        empty_map = pd.DataFrame(
            columns=[
                "raw_demand_id",
                "merged_demand_id",
                "merge_applied",
                "member_rank",
                "raw_qty",
                "merge_source_table",
                "merge_key_snapshot",
                "merge_type",
            ]
        )
        empty_cycle = pd.DataFrame(
            columns=[
                "raw_demand_id",
                "merged_demand_id",
                "member_rank",
                "cycle_merge_rule_id",
                "cycle_merge_key_snapshot",
                "cycle_merge_source_table",
                "merge_type",
            ]
        )
        return raw_demands.copy(), empty_map, empty_cycle, {"merge_source_table": "none", "cycle_merge_source_table": "none", "cycle_merge_enabled": False, "cycle_merge_hit_rules": 0, "merge_execution_order": "priority_then_cycle"}

    demands = raw_demands.copy()
    demands["demand_id"] = demands["demand_id"].astype(str)
    demands["_merged_demand_id"] = demands["demand_id"]
    demands["_merge_key_snapshot"] = ""
    demands["_merge_type"] = "none"
    demands["_cycle_merge_rule_id"] = ""
    demands["_cycle_merge_key_snapshot"] = ""

    source_table = "none"
    rules = pd.DataFrame()
    new_rules = sheets.get("aps_schedule_merge_priority_setting", pd.DataFrame())
    old_rules = sheets.get("aps_merge_priority_setting", pd.DataFrame())
    if isinstance(new_rules, pd.DataFrame) and not new_rules.empty:
        rules = new_rules.copy()
        source_table = "aps_schedule_merge_priority_setting"
    elif isinstance(old_rules, pd.DataFrame) and not old_rules.empty:
        rules = old_rules.copy()
        source_table = "aps_merge_priority_setting"

    if rules.empty:
        demands, cycle_trace = _apply_cycle_merge(sheets, demands, excluded_ids, issues)
        merge_map = _build_merge_map(
            demands,
            merge_source_table=source_table,
            merge_key_snapshot_col="_merge_key_snapshot",
            merge_type_col="_merge_type",
        )
        cycle_map = _build_cycle_merge_map(demands, cycle_trace.get("cycle_merge_source_table", "none"))
        merged_demands = _aggregate_merged_demands(demands, merge_map, issues)
        trace = {
            "merge_source_table": source_table,
            "cycle_merge_source_table": cycle_trace.get("cycle_merge_source_table", "none"),
            "cycle_merge_enabled": bool(cycle_trace.get("cycle_merge_enabled", False)),
            "cycle_merge_hit_rules": int(cycle_trace.get("cycle_merge_hit_rules", 0)),
            "merge_execution_order": "priority_then_cycle",
        }
        return merged_demands, merge_map, cycle_map, trace

    for col in ["mcode", "plant", "priority_desc"]:
        if col not in rules.columns:
            rules[col] = pd.NA
        rules[col] = rules[col].fillna("").astype(str).str.strip()
    rules["priority"] = _safe_numeric(rules.get("priority", 0)).astype(int)
    rules = rules.sort_values(["mcode", "plant", "priority", "code"]).reset_index(drop=True)

    eligible = ~demands["demand_id"].isin(excluded_ids)
    if "mcode" not in demands.columns:
        demands["mcode"] = ""
    if "plant" not in demands.columns:
        demands["plant"] = ""

    for (mcode, plant), group_rules in rules.groupby(["mcode", "plant"], dropna=False):
        stage_fields = _merge_stage_fields(group_rules, issues)
        if not stage_fields:
            continue
        mask = eligible & demands["mcode"].fillna("").astype(str).eq(str(mcode).strip())
        if str(plant).strip():
            mask &= demands["plant"].fillna("").astype(str).eq(str(plant).strip())
        candidates = demands[mask].copy()
        if len(candidates) <= 1:
            continue
        key_fields = [field for field in stage_fields if field in candidates.columns]
        if not key_fields:
            continue
        keys = candidates.apply(lambda row: _merge_key(row, key_fields), axis=1)
        grouped_indices: dict[tuple[str, ...], list[int]] = {}
        for idx, key in zip(candidates.index.tolist(), keys.tolist()):
            grouped_indices.setdefault(key, []).append(idx)
        for key, indices in grouped_indices.items():
            if len(indices) <= 1:
                continue
            merged_id = _make_merged_demand_id(candidates.loc[indices, "demand_id"].astype(str).tolist(), str(mcode).strip())
            demands.loc[indices, "_merged_demand_id"] = merged_id
            demands.loc[indices, "_merge_key_snapshot"] = "|".join(
                f"{field}={value}" for field, value in zip(key_fields, key)
            )
            demands.loc[indices, "_merge_type"] = "priority_merge"

    demands, cycle_trace = _apply_cycle_merge(sheets, demands, excluded_ids, issues)
    merge_map = _build_merge_map(
        demands,
        merge_source_table=source_table,
        merge_key_snapshot_col="_merge_key_snapshot",
        merge_type_col="_merge_type",
    )
    cycle_map = _build_cycle_merge_map(demands, cycle_trace.get("cycle_merge_source_table", "none"))
    merged_demands = _aggregate_merged_demands(demands, merge_map, issues)
    trace = {
        "merge_source_table": source_table,
        "cycle_merge_source_table": cycle_trace.get("cycle_merge_source_table", "none"),
        "cycle_merge_enabled": bool(cycle_trace.get("cycle_merge_enabled", False)),
        "cycle_merge_hit_rules": int(cycle_trace.get("cycle_merge_hit_rules", 0)),
        "merge_execution_order": "priority_then_cycle",
    }
    return merged_demands, merge_map, cycle_map, trace


def _merge_stage_fields(rules: pd.DataFrame, issues: list[dict[str, Any]]) -> list[str]:
    ordered_fields: list[str] = []
    unknown_desc: list[str] = []
    for desc in rules["priority_desc"].fillna("").astype(str).str.strip().tolist():
        fields = MERGE_STAGE_FIELD_MAP.get(desc.lower(), None)
        if fields is None:
            fields = MERGE_STAGE_FIELD_MAP.get(desc, None)
        if fields is None:
            unknown_desc.append(desc)
            continue
        for field in fields:
            if field not in ordered_fields:
                ordered_fields.append(field)
    if unknown_desc:
        issues.append(
            {
                "level": "warning",
                "where": "merge_priority",
                "message": f"Unsupported merge priority_desc values ignored: {sorted(set(unknown_desc))}",
            }
        )
    return ordered_fields


def _merge_key(row: pd.Series, fields: list[str]) -> tuple[str, ...]:
    values = []
    for field in fields:
        value = row.get(field, pd.NA)
        if pd.isna(value):
            values.append("")
        else:
            values.append(str(value).strip())
    return tuple(values)


def _make_merged_demand_id(raw_ids: list[str], mcode: str) -> str:
    digest = hashlib.md5("|".join(sorted(raw_ids)).encode("utf-8")).hexdigest()[:16]
    prefix = mcode or "GEN"
    return f"MRG::{prefix}::{digest}"


def _apply_cycle_merge(
    sheets: dict[str, pd.DataFrame],
    demands_with_assignment: pd.DataFrame,
    excluded_ids: set[str],
    issues: list[dict[str, Any]],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    rules = sheets.get("aps_schedule_cycle_merge_setting", pd.DataFrame())
    if rules is None or rules.empty:
        return demands_with_assignment, {"cycle_merge_enabled": False, "cycle_merge_source_table": "none", "cycle_merge_hit_rules": 0}

    out = demands_with_assignment.copy()
    for col in ["mcode", "plant", "_merge_type", "_cycle_merge_rule_id", "_cycle_merge_key_snapshot"]:
        if col not in out.columns:
            out[col] = ""
    out["mcode"] = out["mcode"].fillna("").astype(str).str.strip()
    out["plant"] = out.get("plant", "").fillna("").astype(str).str.strip()

    rules = rules.copy()
    for col in ["rule_id", "mcode", "plant", "merge_fields", "priority_desc", "code"]:
        if col not in rules.columns:
            rules[col] = ""
        rules[col] = rules[col].fillna("").astype(str).str.strip()
    rules["priority"] = _safe_numeric(rules.get("priority", 0)).astype(int)
    rules = rules.sort_values(["mcode", "plant", "priority", "code", "rule_id"]).reset_index(drop=True)

    hit_rules = 0
    for rule in rules.itertuples(index=False):
        rule_id = str(getattr(rule, "rule_id", "") or "")
        mcode = str(getattr(rule, "mcode", "") or "")
        plant = str(getattr(rule, "plant", "") or "")
        merge_fields_text = str(getattr(rule, "merge_fields", "") or "")
        if merge_fields_text:
            stage_fields = [f.strip() for f in merge_fields_text.split(",") if f.strip()]
        else:
            one_rule = pd.DataFrame([{"priority_desc": str(getattr(rule, "priority_desc", "") or "")}])
            stage_fields = _merge_stage_fields(one_rule, issues)
        if not stage_fields:
            continue

        mask = ~out["demand_id"].astype(str).isin(excluded_ids)
        mask &= out["demand_id"].astype(str).eq(out["_merged_demand_id"].astype(str))
        if mcode:
            mask &= out["mcode"].astype(str).eq(mcode)
        if plant:
            mask &= out["plant"].astype(str).eq(plant)
        candidates = out[mask].copy()
        if len(candidates) <= 1:
            continue

        key_fields = [field for field in stage_fields if field in candidates.columns]
        if not key_fields:
            continue
        keys = candidates.apply(lambda row: _merge_key(row, key_fields), axis=1)
        grouped_indices: dict[tuple[str, ...], list[int]] = {}
        for idx, key in zip(candidates.index.tolist(), keys.tolist()):
            grouped_indices.setdefault(key, []).append(idx)

        rule_hit = False
        for key, indices in grouped_indices.items():
            if len(indices) <= 1:
                continue
            merged_id = _make_merged_demand_id(candidates.loc[indices, "demand_id"].astype(str).tolist(), mcode)
            out.loc[indices, "_merged_demand_id"] = merged_id
            out.loc[indices, "_merge_type"] = "cycle_merge"
            out.loc[indices, "_cycle_merge_rule_id"] = rule_id
            out.loc[indices, "_cycle_merge_key_snapshot"] = "|".join(
                f"{field}={value}" for field, value in zip(key_fields, key)
            )
            if out.loc[indices, "_merge_key_snapshot"].fillna("").astype(str).str.strip().eq("").all():
                out.loc[indices, "_merge_key_snapshot"] = out.loc[indices, "_cycle_merge_key_snapshot"]
            rule_hit = True
        if rule_hit:
            hit_rules += 1

    return out, {
        "cycle_merge_enabled": True,
        "cycle_merge_source_table": "aps_schedule_cycle_merge_setting",
        "cycle_merge_hit_rules": int(hit_rules),
    }


def _build_cycle_merge_map(demands_with_assignment: pd.DataFrame, source_table: str) -> pd.DataFrame:
    if demands_with_assignment.empty:
        return pd.DataFrame(
            columns=[
                "raw_demand_id",
                "merged_demand_id",
                "member_rank",
                "cycle_merge_rule_id",
                "cycle_merge_key_snapshot",
                "cycle_merge_source_table",
                "merge_type",
            ]
        )
    out = demands_with_assignment.copy()
    out["raw_demand_id"] = out["demand_id"].astype(str)
    out["merged_demand_id"] = out["_merged_demand_id"].astype(str)
    out["merge_type"] = out.get("_merge_type", "none").fillna("none").astype(str)
    out["cycle_merge_rule_id"] = out.get("_cycle_merge_rule_id", "").fillna("").astype(str)
    out["cycle_merge_key_snapshot"] = out.get("_cycle_merge_key_snapshot", "").fillna("").astype(str)
    out["cycle_merge_source_table"] = str(source_table or "none")
    out["_member_rank"] = pd.to_numeric(out.get("total_index", pd.NA), errors="coerce").fillna(10**9).astype(int)
    out = out.sort_values(["merged_demand_id", "_member_rank", "raw_demand_id"]).reset_index(drop=True)
    out["member_rank"] = out.groupby("merged_demand_id").cumcount() + 1
    return out[
        [
            "raw_demand_id",
            "merged_demand_id",
            "member_rank",
            "cycle_merge_rule_id",
            "cycle_merge_key_snapshot",
            "cycle_merge_source_table",
            "merge_type",
        ]
    ]


def _build_merge_map(
    demands_with_assignment: pd.DataFrame,
    merge_source_table: str = "none",
    merge_key_snapshot_col: str = "_merge_key_snapshot",
    merge_type_col: str = "_merge_type",
) -> pd.DataFrame:
    base = demands_with_assignment.copy()
    base["raw_demand_id"] = base["demand_id"].astype(str)
    base["merged_demand_id"] = base["_merged_demand_id"].astype(str)
    base["raw_qty"] = _safe_numeric(base.get("qty", 0)).astype(int)
    if merge_key_snapshot_col in base.columns:
        base["merge_key_snapshot"] = base[merge_key_snapshot_col].fillna("").astype(str)
    else:
        base["merge_key_snapshot"] = ""
    if merge_type_col in base.columns:
        base["merge_type"] = base[merge_type_col].fillna("none").astype(str)
    else:
        base["merge_type"] = "none"
    base["merge_source_table"] = str(merge_source_table or "none")
    base["_member_rank"] = (
        pd.to_numeric(base.get("total_index", pd.NA), errors="coerce")
        .fillna(10**9)
        .astype(int)
    )
    base = base.sort_values(["merged_demand_id", "_member_rank", "raw_demand_id"]).reset_index(drop=True)
    base["member_rank"] = base.groupby("merged_demand_id").cumcount() + 1
    group_size = base.groupby("merged_demand_id")["raw_demand_id"].transform("size")
    base["merge_applied"] = (group_size > 1).astype(int)
    return base[
        [
            "raw_demand_id",
            "merged_demand_id",
            "merge_applied",
            "member_rank",
            "raw_qty",
            "merge_source_table",
            "merge_key_snapshot",
            "merge_type",
        ]
    ]


def _aggregate_merged_demands(raw_demands: pd.DataFrame, merge_map: pd.DataFrame, issues: list[dict[str, Any]]) -> pd.DataFrame:
    left = raw_demands.copy()
    left = left.drop(columns=["_merged_demand_id"], errors="ignore")
    joined = left.merge(
        merge_map.rename(columns={"raw_demand_id": "demand_id", "merged_demand_id": "_merged_demand_id"}),
        on="demand_id",
        how="left",
    )
    joined["_merged_demand_id"] = joined["_merged_demand_id"].fillna(joined["demand_id"].astype(str))
    rows: list[dict[str, Any]] = []
    for merged_id, group in joined.groupby("_merged_demand_id", sort=False):
        group = group.sort_values(["member_rank", "demand_id"], na_position="last").reset_index(drop=True)
        first = group.iloc[0]
        row: dict[str, Any] = {"demand_id": str(merged_id)}
        mixed_fields: list[str] = []
        for col in group.columns:
            if col.startswith("_") or col in {
                "demand_id",
                "merge_applied",
                "member_rank",
                "raw_qty",
                "merge_source_table",
                "merge_key_snapshot",
                "merge_type",
            }:
                continue
            if col == "qty":
                row[col] = int(pd.to_numeric(group[col], errors="coerce").fillna(0).sum())
            elif col in {"pre_lock", "fast_ship", "cust_svc", "ord_qty", "line_qty"}:
                row[col] = int(pd.to_numeric(group[col], errors="coerce").fillna(0).max())
            elif col == "total_index":
                row[col] = int(pd.to_numeric(group[col], errors="coerce").fillna(10**9).min())
            elif col == "mr_day":
                row[col] = _strict_date_pick(group[col], prefer="latest")
            elif col in {"ots_date", "fpsd", "ship_day_two"}:
                row[col] = _strict_date_pick(group[col], prefer="earliest")
            elif col == "mr_day_dt":
                row[col] = _strict_datetime_pick(group[col], prefer="latest")
            elif col in {"ots_date_dt", "fpsd_dt", "ship_day_two_dt"}:
                row[col] = _strict_datetime_pick(group[col], prefer="earliest")
            elif col == "om_urgent":
                row[col] = _truthy_text_pick(group[col])
            elif col == "urgent":
                row[col] = int(pd.to_numeric(group[col], errors="coerce").fillna(0).max())
            elif col == "mo":
                row[col] = _stable_single_or_blank(group[col])
            elif col in {"priority_rank"}:
                row[col] = int(pd.to_numeric(group[col], errors="coerce").fillna(10**9).min())
            elif col in {"priority_weight"}:
                row[col] = float(pd.to_numeric(group[col], errors="coerce").fillna(0).max())
            else:
                consensus, is_mixed = _consensus_or_mixed(group[col])
                row[col] = consensus
                if is_mixed:
                    mixed_fields.append(col)
        row["raw_demand_count"] = int(len(group))
        row["member_demand_ids"] = "|".join(group["demand_id"].astype(str).tolist())
        row["merge_mixed_fields"] = "|".join(sorted(set(mixed_fields)))
        if mixed_fields:
            issues.append(
                {
                    "level": "info",
                    "where": "merge_aggregate",
                    "message": f"Merged demand {merged_id} has mixed values in fields: {sorted(set(mixed_fields))}",
                }
            )
        rows.append(row)
    out = pd.DataFrame(rows)
    for col in ["pre_lock", "fast_ship", "cust_svc", "ord_qty", "line_qty", "raw_demand_count"]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0).astype(int)
    out = out.sort_values(["total_index", "demand_id"], na_position="last").reset_index(drop=True)
    return out


def _strict_date_pick(values: pd.Series, prefer: str) -> Any:
    cleaned = values.fillna("").astype(str).str.strip()
    parsed = _fast_to_datetime_cleaned(cleaned).dropna()
    if parsed.empty:
        return pd.NA
    target = parsed.max() if prefer == "latest" else parsed.min()
    return pd.Timestamp(target).strftime("%Y-%m-%d")


def _strict_datetime_pick(values: pd.Series, prefer: str) -> Any:
    parsed = pd.to_datetime(values, errors="coerce").dropna()
    if parsed.empty:
        return pd.NaT
    return parsed.max() if prefer == "latest" else parsed.min()


def _truthy_text_pick(values: pd.Series) -> Any:
    non_empty = [str(v).strip() for v in values.fillna("").astype(str) if str(v).strip()]
    if not non_empty:
        return pd.NA
    for value in non_empty:
        if _urgent_flag(value):
            return value
    return non_empty[0]


def _stable_single_or_blank(values: pd.Series) -> Any:
    distinct = sorted({str(v).strip() for v in values.fillna("").astype(str) if str(v).strip()})
    if len(distinct) == 1:
        return distinct[0]
    return pd.NA


def _consensus_or_mixed(values: pd.Series) -> tuple[Any, bool]:
    cleaned = values.fillna("").astype(str).str.strip()
    non_empty = [v for v in cleaned.tolist() if v != ""]
    if not non_empty:
        return pd.NA, False
    distinct = sorted(set(non_empty))
    if len(distinct) == 1:
        return distinct[0], False
    # keep deterministic representative while surfacing mixed state
    return non_empty[0], True


def _propagate_priority_to_raw_demands(raw_demands: pd.DataFrame, merge_map: pd.DataFrame, demands: pd.DataFrame) -> pd.DataFrame:
    if raw_demands.empty:
        return raw_demands.copy()
    if merge_map.empty or demands.empty:
        out = raw_demands.copy()
        if "priority_rank" not in out.columns:
            out["priority_rank"] = pd.NA
        if "priority_weight" not in out.columns:
            out["priority_weight"] = pd.NA
        return out
    merged_priority = demands[["demand_id", "priority_rank", "priority_weight"]].rename(columns={"demand_id": "merged_demand_id"})
    out = raw_demands.copy().merge(
        merge_map[["raw_demand_id", "merged_demand_id"]],
        left_on="demand_id",
        right_on="raw_demand_id",
        how="left",
    )
    out["merged_demand_id"] = out["merged_demand_id"].fillna(out["demand_id"].astype(str))
    out = out.drop(columns=["priority_rank", "priority_weight"], errors="ignore")
    out = out.merge(merged_priority, on="merged_demand_id", how="left")
    return out.drop(columns=["raw_demand_id", "merged_demand_id"], errors="ignore")


def _normalize_uph(uph: pd.DataFrame) -> pd.DataFrame:
    if uph.empty:
        return uph
    out = uph.copy()
    out["line_id"] = out["line_id"].map(_to_id)
    out["slot_id"] = [_slot_id(d, s) for d, s in zip(_safe_datetime(out["day"]).dt.normalize(), out["shift_seq"])]
    out["model"] = out["model"].fillna("").astype(str).str.strip()
    out["mcode"] = out["mcode"].fillna("").astype(str).str.strip()
    out["uph"] = _safe_numeric(out["uph_qty"])
    out["priority"] = _safe_numeric(out.get("priority", 9999), 9999)
    out["transform_priority"] = _safe_numeric(out.get("transform_priority", 9999), 9999)
    out["fast_ship_specific"] = out.get("fast_ship_flag", "").map(_truthy).astype(int)
    out["cust_svc_specific"] = out.get("cust_svc", "").map(_truthy).astype(int)
    out["mat_type"] = out.get("mat_type", "").fillna("").astype(str).str.strip()
    out = out[out["uph"] > 0]
    return out[
        [
            "line_id",
            "slot_id",
            "model",
            "mcode",
            "uph",
            "priority",
            "transform_priority",
            "fast_ship_specific",
            "cust_svc_specific",
            "mat_type",
        ]
    ].reset_index(drop=True)


def _apply_downtime(line_slots: pd.DataFrame, off_time: pd.DataFrame) -> pd.DataFrame:
    out = line_slots.copy()
    if off_time.empty:
        return _recalc_avail(out)
    off = off_time.copy()
    off["line_id"] = off["line_id"].map(_to_id)
    off["slot_id"] = [_slot_id(d, s) for d, s in zip(_safe_datetime(off["day"]).dt.normalize(), off["shift_seq"])]
    start = _safe_datetime(off["start_time"])
    end = _safe_datetime(off["end_time"])
    off["down_hours"] = ((end - start).dt.total_seconds() / 3600.0).clip(lower=0).fillna(0.0)
    down = off.groupby(["line_id", "slot_id"], as_index=False)["down_hours"].sum()
    out = out.drop(columns=["down_hours"], errors="ignore").merge(down, on=["line_id", "slot_id"], how="left")
    out["down_hours"] = out["down_hours"].fillna(0.0)
    return _recalc_avail(out)


def _apply_reservations(
    line_slots: pd.DataFrame,
    reserver: pd.DataFrame,
    issues: list[dict[str, Any]],
) -> pd.DataFrame:
    """Apply rule 7 (产能预留): subtract reserved windows from line-slot avail.

    The optional ``aps_schedule_reserver_input`` sheet defines explicit
    capacity reservation windows by line/day/shift, with ``reserved_start_time``
    and ``reserved_end_time`` (clock times). Each row reduces ``avail_hours`` of
    the matching (line, slot) by the overlap with that shift.
    """
    out = line_slots.copy()
    if reserver is None or reserver.empty:
        return _recalc_avail(out)
    res = reserver.copy()
    if "line_id" not in res.columns:
        return _recalc_avail(out)
    res["line_id"] = res["line_id"].map(_to_id)
    if "shift_seq" not in res.columns:
        res["shift_seq"] = 0
    if "reserved_day" not in res.columns:
        return _recalc_avail(out)
    res["slot_id"] = [
        _slot_id(d, s) for d, s in zip(_safe_datetime(res["reserved_day"]).dt.normalize(), res["shift_seq"])
    ]
    # Times may be stored as datetime, time-of-day strings, or HH:MM:SS strings.
    start_text = res.get("reserved_start_time", pd.Series("", index=res.index)).astype("string")
    end_text = res.get("reserved_end_time", pd.Series("", index=res.index)).astype("string")
    start_combined = pd.to_datetime(
        _safe_datetime(res["reserved_day"]).dt.strftime("%Y-%m-%d") + " " + start_text.fillna(""),
        errors="coerce",
    )
    end_combined = pd.to_datetime(
        _safe_datetime(res["reserved_day"]).dt.strftime("%Y-%m-%d") + " " + end_text.fillna(""),
        errors="coerce",
    )
    fallback_start = _safe_datetime(start_text)
    fallback_end = _safe_datetime(end_text)
    res["start_dt"] = start_combined.where(start_combined.notna(), fallback_start)
    res["end_dt"] = end_combined.where(end_combined.notna(), fallback_end)
    if not (res["start_dt"].notna() & res["end_dt"].notna()).any():
        issues.append(
            {
                "level": "warning",
                "where": "reserver",
                "message": "aps_schedule_reserver_input rows had no parseable start/end times; ignored.",
            }
        )
        return _recalc_avail(out)

    keys = res[["line_id", "slot_id", "start_dt", "end_dt"]].copy()
    overlap_target = out[["line_id", "slot_id", "shift_start_time", "shift_end_time"]].copy()
    overlap_target["shift_start_time"] = pd.to_datetime(overlap_target["shift_start_time"], errors="coerce")
    overlap_target["shift_end_time"] = pd.to_datetime(overlap_target["shift_end_time"], errors="coerce")
    merged = keys.merge(overlap_target, on=["line_id", "slot_id"], how="inner")
    if merged.empty:
        issues.append(
            {
                "level": "info",
                "where": "reserver",
                "message": f"{len(res)} reservation rows did not match any open line-slot.",
            }
        )
        return _recalc_avail(out)
    overlap_start = merged[["start_dt", "shift_start_time"]].max(axis=1)
    overlap_end = merged[["end_dt", "shift_end_time"]].min(axis=1)
    overlap_hours = ((overlap_end - overlap_start).dt.total_seconds() / 3600.0).clip(lower=0.0).fillna(0.0)
    merged["reserved_hours"] = overlap_hours
    summed = merged.groupby(["line_id", "slot_id"], as_index=False)["reserved_hours"].sum()
    out = out.drop(columns=["reserved_hours"], errors="ignore").merge(
        summed, on=["line_id", "slot_id"], how="left"
    )
    out["reserved_hours"] = out["reserved_hours"].fillna(0.0)
    return _recalc_avail(out)


def _build_fixed_locks(
    sheets: dict[str, pd.DataFrame],
    demands: pd.DataFrame,
    slots: pd.DataFrame,
    config: PreprocessConfig,
    issues: list[dict[str, Any]],
) -> pd.DataFrame:
    fix = sheets["aps_schedule_demand_fix_input"].copy()
    if fix.empty:
        return pd.DataFrame(columns=["lock_id", "source_row_id", "demand_id", "line_id", "slot_id", "shift_date", "shift", "seq", "lock_qty"])
    demand_qty = demands.set_index("demand_id")["qty"].to_dict()
    fix["demand_id"] = fix["demand_id"].map(_to_id)
    fix = fix[fix["demand_id"].isin(demand_qty)]
    fix["source_row_id"] = ["fix_row_" + str(i + 1) for i in range(len(fix))]
    if "id" in fix.columns:
        fix["lock_id"] = fix["id"].map(_to_id)
    elif "fix_id" in fix.columns:
        fix["lock_id"] = fix["fix_id"].map(_to_id)
    else:
        fix["lock_id"] = ""
    fix["line_id"] = fix["fix_line_id"].map(_to_id)
    fix["shift_date"] = pd.to_datetime(fix["fix_day"], errors="coerce").dt.strftime("%Y-%m-%d").fillna("")
    fix["shift"] = _safe_numeric(fix.get("fix_shift", 0)).astype(int).astype(str)
    fix["slot_id"] = [_slot_id(d, s) for d, s in zip(fix["fix_day"], fix["fix_shift"])]
    fix["seq"] = _safe_numeric(fix.get("fix_seq", 0)).astype(int)
    fix["fix_qty"] = _safe_numeric(fix.get("fix_qty", 0)).astype(float)
    fix["lock_qty"] = fix["fix_qty"].astype(float)
    mismatch = fix[(fix["fix_qty"] > 0) & (fix["fix_qty"] != fix["demand_id"].map(demand_qty).astype(float))]
    if len(mismatch):
        issues.append({"level": "info", "where": "fix", "message": f"{len(mismatch)} FIX rows have fix_qty different from demand qty; lock uses fix_qty as quantity lock."})
    non_positive = int((fix["lock_qty"] <= 0).sum())
    if non_positive:
        issues.append({"level": "warning", "where": "fix", "message": f"{non_positive} FIX rows have non-positive fix_qty and were dropped."})
    fix = fix[fix["lock_qty"] > 0].copy()
    return fix.sort_values(["demand_id", "seq", "source_row_id"])[
        ["lock_id", "source_row_id", "demand_id", "line_id", "slot_id", "shift_date", "shift", "seq", "lock_qty"]
    ].reset_index(drop=True)


def _split_adjust_schedule(
    sheets: dict[str, pd.DataFrame],
    demands: pd.DataFrame,
    slots: pd.DataFrame,
    issues: list[dict[str, Any]],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    adj = sheets["aps_adjust_schedule_input"].copy()
    if adj.empty:
        empty_lock = pd.DataFrame(columns=["lock_id", "source_row_id", "demand_id", "line_id", "slot_id", "shift_date", "shift", "seq", "lock_qty"])
        return empty_lock, adj
    demand_qty = demands.set_index("demand_id")["qty"].to_dict()
    adj["demand_id"] = adj["demand_id"].map(_to_id)
    adj["source_row_id"] = ["adjust_row_" + str(i + 1) for i in range(len(adj))]
    if "id" in adj.columns:
        adj["lock_id"] = adj["id"].map(_to_id)
    elif "adjust_id" in adj.columns:
        adj["lock_id"] = adj["adjust_id"].map(_to_id)
    else:
        adj["lock_id"] = ""
    adj["line_id"] = adj["line_id"].map(_to_id)
    adj["shift_date"] = pd.to_datetime(adj["schedule_day"], errors="coerce").dt.strftime("%Y-%m-%d").fillna("")
    adj["shift"] = _safe_numeric(adj.get("shift_seq", 0)).astype(int).astype(str)
    adj["slot_id"] = [_slot_id(d, s) for d, s in zip(adj["schedule_day"], adj["shift_seq"])]
    adj["seq"] = _safe_numeric(adj.get("schedule_seq", 0)).astype(int)
    adj["schedule_qty"] = _safe_numeric(adj.get("schedule_qty", 0)).astype(float)

    inside = adj[adj["demand_id"].isin(demand_qty)].copy()
    outside = adj[~adj["demand_id"].isin(demand_qty)].copy()
    inside["lock_qty"] = inside["schedule_qty"].astype(float)
    mismatch = inside[(inside["schedule_qty"] > 0) & (inside["schedule_qty"] != inside["demand_id"].map(demand_qty).astype(float))]
    if len(mismatch):
        issues.append({"level": "info", "where": "adjust", "message": f"{len(mismatch)} inherited rows have schedule_qty different from demand qty; lock uses schedule_qty as quantity lock."})
    non_positive = int((inside["lock_qty"] <= 0).sum())
    if non_positive:
        issues.append({"level": "warning", "where": "adjust", "message": f"{non_positive} inherited rows have non-positive schedule_qty and were dropped."})
    inside = inside[inside["lock_qty"] > 0].copy()
    lock = inside.sort_values(["demand_id", "seq", "source_row_id"])[
        ["lock_id", "source_row_id", "demand_id", "line_id", "slot_id", "shift_date", "shift", "seq", "lock_qty"]
    ].reset_index(drop=True)
    return lock, outside.reset_index(drop=True)


def _lookup_uph(
    uph: pd.DataFrame,
    demand: pd.Series | dict[str, Any],
    line_id: str,
    slot_id: str,
    allow_generic_for_special: bool = True,
) -> float:
    if uph.empty:
        return math.nan
    model = str(demand.get("model", "") or "")
    mcode = str(demand.get("mcode", "") or "")
    subset = uph[(uph["line_id"] == str(line_id)) & (uph["slot_id"] == str(slot_id)) & (uph["model"] == model)]
    if mcode:
        exact = subset[(subset["mcode"] == mcode) | (subset["mcode"] == "") | (subset["mcode"] == "*")]
        if not exact.empty:
            subset = exact
    if subset.empty:
        return math.nan
    fast = int(demand.get("fast_ship", 0) or 0)
    cust = int(demand.get("cust_svc", 0) or 0)
    if not fast:
        subset = subset[subset["fast_ship_specific"] == 0]
    elif not allow_generic_for_special:
        subset = subset[subset["fast_ship_specific"] == 1]
    if not cust:
        subset = subset[subset["cust_svc_specific"] == 0]
    elif not allow_generic_for_special:
        subset = subset[subset["cust_svc_specific"] == 1]
    mat_type = str(demand.get("material_type", "") or "")
    if mat_type:
        subset = subset[(subset["mat_type"] == "") | (subset["mat_type"] == "*") | (subset["mat_type"] == mat_type)]
    if subset.empty:
        return math.nan
    subset = subset.assign(
        score=(subset["fast_ship_specific"] == fast).astype(int)
        + (subset["cust_svc_specific"] == cust).astype(int)
        + (subset["mcode"] == mcode).astype(int)
    )
    best = subset.sort_values(["score", "priority", "transform_priority", "uph"], ascending=[False, True, True, False]).iloc[0]
    return float(best["uph"])


def _build_external_occupation(
    external_adjust: pd.DataFrame,
    uph: pd.DataFrame,
    issues: list[dict[str, Any]],
) -> pd.DataFrame:
    if external_adjust.empty:
        return pd.DataFrame(columns=["line_id", "slot_id", "occupied_hours"])
    rows = []
    missing = 0
    for _, row in external_adjust.iterrows():
        demand_like = {
            "model": row.get("model", ""),
            "mcode": row.get("mcode", ""),
            "fast_ship": 0,
            "cust_svc": 0,
            "material_type": "",
        }
        matched_uph = _lookup_uph(uph, demand_like, row["line_id"], row["slot_id"])
        if not matched_uph or math.isnan(matched_uph):
            missing += 1
            continue
        rows.append(
            {
                "line_id": row["line_id"],
                "slot_id": row["slot_id"],
                "occupied_hours": float(row["schedule_qty"]) / matched_uph,
            }
        )
    if missing:
        issues.append({"level": "warning", "where": "adjust_external", "message": f"{missing} external inherited rows could not match UPH and were not counted in occupied capacity."})
    if not rows:
        return pd.DataFrame(columns=["line_id", "slot_id", "occupied_hours"])
    return pd.DataFrame(rows).groupby(["line_id", "slot_id"], as_index=False)["occupied_hours"].sum()


def _apply_external_occupation(line_slots: pd.DataFrame, occupied: pd.DataFrame) -> pd.DataFrame:
    out = line_slots.drop(columns=["occupied_hours"], errors="ignore")
    if occupied.empty:
        out["occupied_hours"] = 0.0
    else:
        out = out.merge(occupied, on=["line_id", "slot_id"], how="left")
        out["occupied_hours"] = out["occupied_hours"].fillna(0.0)
    return _recalc_avail(out)


def _recalc_avail(line_slots: pd.DataFrame) -> pd.DataFrame:
    out = line_slots.copy()
    for col in ["cap_hours", "down_hours", "reserved_hours", "occupied_hours"]:
        if col not in out.columns:
            out[col] = 0.0
        out[col] = _safe_numeric(out[col])
    out["avail_hours"] = out["cap_hours"] - out["down_hours"] - out["reserved_hours"] - out["occupied_hours"]
    return out


def _build_sparse_triples(
    demands: pd.DataFrame,
    lines: pd.DataFrame,
    slots: pd.DataFrame,
    line_slots: pd.DataFrame,
    uph: pd.DataFrame,
    order_qty: pd.DataFrame,
    limit_rules: pd.DataFrame,
    fixed_locks: pd.DataFrame,
    adjust_locks: pd.DataFrame,
    config: PreprocessConfig,
    issues: list[dict[str, Any]],
) -> pd.DataFrame:
    allowed_line_slots = line_slots[line_slots["allow_calendar"].astype(int) == 1][
        ["line_id", "slot_id", "slot_rank", "start_hour", "shift_start_time"]
    ]
    uph_allowed = uph.merge(allowed_line_slots, on=["line_id", "slot_id"], how="inner")
    exact_mcode_keys = {
        (row.line_id, row.slot_id, row.model, row.mcode)
        for row in uph_allowed[["line_id", "slot_id", "model", "mcode"]].itertuples(index=False)
        if str(row.mcode).strip() not in {"", "*"}
    }
    demands_by_model = {model: df for model, df in demands.groupby("model", dropna=False)}
    rows: list[tuple[Any, ...]] = []
    demand_cols = ["demand_id", "mcode", "fast_ship", "cust_svc", "material_type", "mr_day_dt", "qty", "model"]

    for uph_row in uph_allowed.itertuples(index=False):
        model = getattr(uph_row, "model")
        if model not in demands_by_model:
            continue
        candidates = demands_by_model[model][demand_cols]
        uph_mcode = str(getattr(uph_row, "mcode") or "")
        if uph_mcode and uph_mcode != "*":
            exact_mask = candidates["mcode"].astype(str).map(
                lambda d_mcode: (getattr(uph_row, "line_id"), getattr(uph_row, "slot_id"), model, d_mcode) in exact_mcode_keys
            )
            candidates = candidates[
                candidates["mcode"].astype(str).eq(uph_mcode)
                | candidates["mcode"].isna()
                | candidates["mcode"].astype(str).eq("")
                | ~exact_mask
            ]
        if int(getattr(uph_row, "fast_ship_specific")) == 1:
            candidates = candidates[candidates["fast_ship"].astype(int) == 1]
        if int(getattr(uph_row, "cust_svc_specific")) == 1:
            candidates = candidates[candidates["cust_svc"].astype(int) == 1]
        mat_type = getattr(uph_row, "mat_type")
        if mat_type and mat_type != "*":
            candidates = candidates[candidates["material_type"].fillna("").astype(str).isin(["", mat_type])]
        if candidates.empty:
            continue
        for d in candidates.itertuples(index=False):
            rows.append(
                (
                    d.demand_id,
                    getattr(uph_row, "line_id"),
                    getattr(uph_row, "slot_id"),
                    float(getattr(uph_row, "uph")),
                    int(getattr(uph_row, "slot_rank")),
                    float(getattr(uph_row, "start_hour")),
                    getattr(uph_row, "shift_start_time"),
                    int(getattr(uph_row, "fast_ship_specific")) + int(getattr(uph_row, "cust_svc_specific")),
                    float(getattr(uph_row, "priority")),
                    float(getattr(uph_row, "transform_priority")),
                )
            )

    if rows:
        triples = pd.DataFrame(
            rows,
            columns=[
                "demand_id",
                "line_id",
                "slot_id",
                "uph",
                "slot_rank",
                "start_hour",
                "shift_start_time",
                "specificity",
                "uph_priority",
                "transform_priority",
            ],
        )
        triples = (
            triples.sort_values(
                ["specificity", "uph_priority", "transform_priority", "uph"],
                ascending=[False, True, True, False],
            )
            .drop_duplicates(["demand_id", "line_id", "slot_id"])
            .reset_index(drop=True)
        )
    else:
        triples = pd.DataFrame(columns=["demand_id", "line_id", "slot_id", "uph", "slot_rank", "start_hour", "shift_start_time"])

    triples = _apply_mr_rule(triples, demands)
    triples = _apply_order_qty_rule(triples, demands, order_qty)
    triples = _apply_limit_rules(triples, demands, lines, slots, limit_rules)
    triples["elig"] = (
        triples["allow_mr"].astype(int)
        * triples["allow_qty"].astype(int)
        * triples["allow_limit"].astype(int)
    )
    triples = triples[triples["elig"] == 1].copy()

    if config.include_locked_triples:
        triples = _ensure_locked_triples(triples, fixed_locks, adjust_locks, demands, uph, line_slots, issues)

    triples = triples[["demand_id", "line_id", "slot_id", "uph", "slot_rank", "elig"]].drop_duplicates(
        ["demand_id", "line_id", "slot_id"]
    )
    return triples.reset_index(drop=True)


def _apply_mr_rule(triples: pd.DataFrame, demands: pd.DataFrame) -> pd.DataFrame:
    if triples.empty:
        triples["allow_mr"] = []
        return triples
    demand_mr = demands[["demand_id", "mr_day_dt"]]
    out = triples.merge(demand_mr, on="demand_id", how="left")
    out["shift_start_time"] = pd.to_datetime(out["shift_start_time"], errors="coerce")
    out["allow_mr"] = out["mr_day_dt"].isna() | (out["shift_start_time"] >= out["mr_day_dt"])
    # The source sample uses 9999-12-31 sentinels heavily; those become NaT above.
    return out.drop(columns=["mr_day_dt"])


def _apply_order_qty_rule(triples: pd.DataFrame, demands: pd.DataFrame, order_qty: pd.DataFrame) -> pd.DataFrame:
    out = triples.copy()
    out["allow_qty"] = 1
    if out.empty or order_qty.empty:
        return out
    tmp = out.merge(demands[["demand_id", "qty", "model"]], on="demand_id", how="left")
    rules = order_qty.copy()
    rules["line_id"] = rules["line_id"].map(_to_id)
    rules["model"] = rules["model"].fillna("*").astype(str).str.strip()
    rules["flag_type"] = _safe_numeric(rules["flag_type"]).astype(int)
    rules["small_qty"] = _safe_numeric(rules["small_qty"]).astype(int)
    allowed = pd.Series(True, index=tmp.index)
    for _, rule in rules.iterrows():
        mask = tmp["line_id"].eq(rule["line_id"])
        if rule["model"] != "*":
            mask &= tmp["model"].astype(str).eq(rule["model"])
        small = tmp["qty"] <= int(rule["small_qty"])
        if int(rule["flag_type"]) == 1:
            allowed &= ~mask | small
        elif int(rule["flag_type"]) == 3:
            allowed &= ~mask | ~small
    out["allow_qty"] = allowed.astype(int).values
    return out


def _apply_limit_rules(
    triples: pd.DataFrame,
    demands: pd.DataFrame,
    lines: pd.DataFrame,
    slots: pd.DataFrame,
    limit_rules: pd.DataFrame,
) -> pd.DataFrame:
    out = triples.copy()
    out["allow_limit"] = 1
    if out.empty or limit_rules.empty:
        return out
    rules = limit_rules.copy()
    rules["group_id"] = rules["group_id"].map(_to_id)
    rules["type"] = _safe_numeric(rules["type"]).astype(int)
    rules["condition_key"] = rules["condition_key"].fillna("").astype(str)
    rules["condition_value"] = rules["condition_value"].fillna("").astype(str)
    dem = demands.set_index("demand_id")
    line_map = lines.set_index("line_id").to_dict("index")
    slot_map = slots.set_index("slot_id").to_dict("index")
    allowed = pd.Series(True, index=out.index)
    for _, group in rules.groupby("group_id"):
        demand_conditions = group[group["type"] == 1]
        restrictions = group[group["type"] != 1]
        if demand_conditions.empty or restrictions.empty:
            continue
        matched_demands = [d for d, row in dem.iterrows() if _row_matches_conditions(row, demand_conditions)]
        if not matched_demands:
            continue
        mask = out["demand_id"].isin(matched_demands)
        if not mask.any():
            continue
        restrict_ok = []
        for row in out[mask].itertuples():
            ok = True
            line = line_map.get(row.line_id, {})
            slot = slot_map.get(row.slot_id, {})
            for _, r in restrictions.iterrows():
                ok = ok and _restriction_allows(r["condition_key"], r["condition_value"], line, slot)
            restrict_ok.append(ok)
        allowed.loc[mask] &= pd.Series(restrict_ok, index=out[mask].index)
    out["allow_limit"] = allowed.astype(int)
    return out


def _row_matches_conditions(row: pd.Series, conditions: pd.DataFrame) -> bool:
    for _, cond in conditions.iterrows():
        key = str(cond["condition_key"]).strip()
        value = str(cond["condition_value"]).strip()
        if key.lower() == "model":
            actual = str(row.get("model", ""))
        else:
            actual = str(row.get(key, ""))
        if value not in {"", "*"} and actual != value:
            return False
    return True


def _restriction_allows(key: str, value: str, line: dict[str, Any], slot: dict[str, Any]) -> bool:
    key_norm = str(key).strip().lower()
    value_norm = str(value).strip()
    if key_norm in {"shift", "shift_seq"}:
        return str(int(slot.get("shift_seq", -1))) == value_norm
    if key_norm in {"line", "line_id", "limitline"}:
        return value_norm in {str(line.get("line_id", "")), str(line.get("line", ""))}
    if key_norm == "status":
        return value_norm.upper() in {"", "ON", "1", "TRUE", "X"}
    return True


def _ensure_locked_triples(
    triples: pd.DataFrame,
    fixed_locks: pd.DataFrame,
    adjust_locks: pd.DataFrame,
    demands: pd.DataFrame,
    uph: pd.DataFrame,
    line_slots: pd.DataFrame,
    issues: list[dict[str, Any]],
) -> pd.DataFrame:
    locks = pd.concat([fixed_locks, adjust_locks], ignore_index=True)
    if locks.empty:
        return triples
    existing = set(zip(triples["demand_id"], triples["line_id"], triples["slot_id"]))
    demand_map = demands.set_index("demand_id").to_dict("index")
    allowed_line_slots = line_slots[line_slots["allow_calendar"].astype(int) == 1]
    line_slot_allowed = set(zip(allowed_line_slots["line_id"], allowed_line_slots["slot_id"]))
    add_rows = []
    for row in locks.itertuples(index=False):
        key = (row.demand_id, row.line_id, row.slot_id)
        if key in existing:
            continue
        demand = demand_map.get(row.demand_id)
        if demand is None:
            continue
        matched_uph = _lookup_uph(uph, demand, row.line_id, row.slot_id)
        elig = int((row.line_id, row.slot_id) in line_slot_allowed and matched_uph and not math.isnan(matched_uph))
        if not elig:
            issues.append({"level": "warning", "where": "locks", "message": f"Locked triple {key} is not eligible by UPH/calendar and will make strict model infeasible."})
        add_rows.append(
            {
                "demand_id": row.demand_id,
                "line_id": row.line_id,
                "slot_id": row.slot_id,
                "uph": matched_uph if matched_uph and not math.isnan(matched_uph) else 0.0,
                "slot_rank": 0,
                "elig": elig,
            }
        )
    if not add_rows:
        return triples
    added = pd.DataFrame(add_rows)
    slot_rank = line_slots[["line_id", "slot_id", "slot_rank"]].drop_duplicates()
    added = added.drop(columns=["slot_rank"]).merge(slot_rank, on=["line_id", "slot_id"], how="left")
    added["slot_rank"] = _safe_numeric(added["slot_rank"]).astype(int)
    base = triples.copy()
    if "elig" not in base.columns:
        base["elig"] = 1
    return pd.concat([base, added], ignore_index=True)


def _prune_sparse_triples(
    triples: pd.DataFrame,
    demands: pd.DataFrame,
    slots: pd.DataFrame,
    config: PreprocessConfig,
    issues: list[dict[str, Any]],
) -> pd.DataFrame:
    """Keep only the most useful sparse columns before the MILP is built."""

    if triples.empty:
        return triples
    out = triples.copy()
    missing_slot_cols = [col for col in ["shift_start_time", "shift_end_time", "start_hour"] if col not in out.columns]
    if missing_slot_cols:
        out = out.merge(
            slots[["slot_id", "shift_start_time", "shift_end_time", "start_hour"]],
            on="slot_id",
            how="left",
        )
    out["shift_start_time"] = pd.to_datetime(out["shift_start_time"], errors="coerce")
    out["shift_end_time"] = pd.to_datetime(out["shift_end_time"], errors="coerce")
    out = out.merge(
        demands[
            [
                "demand_id",
                "mr_day_dt",
                "ots_date_dt",
                "fpsd_dt",
                "ship_day_two_dt",
            ]
        ],
        on="demand_id",
        how="left",
    )
    for col in ["mr_day_dt", "ots_date_dt", "fpsd_dt", "ship_day_two_dt"]:
        out[col] = pd.to_datetime(out[col], errors="coerce")
    base_candidates = out.copy()

    due_buffer = int(config.due_buffer_days or 0)
    ots_buffer = int(config.ots_buffer_days if config.ots_buffer_days is not None else due_buffer)
    fpsd_buffer = int(config.fpsd_buffer_days if config.fpsd_buffer_days is not None else due_buffer)
    ship2_buffer = int(config.ship2_buffer_days if config.ship2_buffer_days is not None else due_buffer)
    eod = pd.Timedelta(hours=23, minutes=59, seconds=59)
    # Vectorized KPI cutoffs: EndOfDay(due +/- days)
    out["_ots_timely_cutoff"] = out["ots_date_dt"].dt.normalize() + pd.to_timedelta(-ots_buffer, unit="D") + eod
    out["_fpsd_timely_cutoff"] = out["fpsd_dt"].dt.normalize() + pd.to_timedelta(-fpsd_buffer, unit="D") + eod
    out["_ship2_timely_cutoff"] = out["ship_day_two_dt"].dt.normalize() + pd.to_timedelta(-ship2_buffer, unit="D") + eod
    out["_ots_ext_cutoff"] = out["ots_date_dt"].dt.normalize() + pd.to_timedelta(int(config.ots_ext_days), unit="D") + eod
    out["_fpsd_ext_cutoff"] = out["fpsd_dt"].dt.normalize() + pd.to_timedelta(int(config.fpsd_ext_days), unit="D") + eod
    out["_ship2_ext_cutoff"] = out["ship_day_two_dt"].dt.normalize() + pd.to_timedelta(int(config.ship2_ext_days), unit="D") + eod

    # v7.6 consistency: main MILP treats slot completion at shift_end_time.
    # Candidate timely/extended flags must use the same end-time semantics.
    out["is_ots_timely"] = (
        out["ots_date_dt"].isna()
        | out["shift_end_time"].isna()
        | (out["shift_end_time"] <= out["_ots_timely_cutoff"])
    ).astype(int)
    out["is_fpsd_timely"] = (
        out["fpsd_dt"].isna()
        | out["shift_end_time"].isna()
        | (out["shift_end_time"] <= out["_fpsd_timely_cutoff"])
    ).astype(int)
    out["is_ship2_timely"] = (
        out["ship_day_two_dt"].isna()
        | out["shift_end_time"].isna()
        | (out["shift_end_time"] <= out["_ship2_timely_cutoff"])
    ).astype(int)
    out["is_ots_extended"] = (
        out["ots_date_dt"].isna()
        | out["shift_end_time"].isna()
        | (out["shift_end_time"] <= out["_ots_ext_cutoff"])
    ).astype(int)
    out["is_fpsd_extended"] = (
        out["fpsd_dt"].isna()
        | out["shift_end_time"].isna()
        | (out["shift_end_time"] <= out["_fpsd_ext_cutoff"])
    ).astype(int)
    out["is_ship2_extended"] = (
        out["ship_day_two_dt"].isna()
        | out["shift_end_time"].isna()
        | (out["shift_end_time"] <= out["_ship2_ext_cutoff"])
    ).astype(int)
    out["keep_by_timely"] = (
        (out["is_ots_timely"] > 0) | (out["is_fpsd_timely"] > 0) | (out["is_ship2_timely"] > 0)
    ).astype(int)
    out["keep_by_extended"] = (
        (out["is_ots_extended"] > 0) | (out["is_fpsd_extended"] > 0) | (out["is_ship2_extended"] > 0)
    ).astype(int)
    keep_kpi = (out["keep_by_timely"] > 0) | (out["keep_by_extended"] > 0)
    out = out[keep_kpi].copy()
    # Vectorized reason tagging (avoid slow axis=1 apply on multi-million rows).
    out["kept_by_reason"] = "fallback"
    out.loc[out["keep_by_extended"] > 0, "kept_by_reason"] = "extended"
    out.loc[out["keep_by_timely"] > 0, "kept_by_reason"] = "timely"

    if config.max_lines_per_demand_day is not None and config.max_lines_per_demand_day > 0 and len(out):
        out["_day"] = out["shift_start_time"].dt.normalize()
        line_score = (
            out.groupby(["demand_id", "_day", "line_id"], as_index=False)
            .agg(
                best_uph=("uph", "max"),
                first_slot=("slot_rank", "min"),
                best_specificity=("specificity", "max") if "specificity" in out.columns else ("uph", "size"),
                best_priority=("uph_priority", "min") if "uph_priority" in out.columns else ("uph", "size"),
            )
            .sort_values(
                ["demand_id", "_day", "best_specificity", "best_priority", "best_uph", "first_slot"],
                ascending=[True, True, False, True, False, True],
            )
        )
        line_score["_line_rank"] = line_score.groupby(["demand_id", "_day"]).cumcount() + 1
        keep_lines = line_score[
            line_score["_line_rank"] <= int(config.max_lines_per_demand_day)
        ][["demand_id", "_day", "line_id"]]
        out = out.merge(keep_lines, on=["demand_id", "_day", "line_id"], how="inner")

    if config.max_slots_per_demand is not None and config.max_slots_per_demand > 0 and len(out):
        out["_due_min"] = out[["ots_date_dt", "fpsd_dt", "ship_day_two_dt"]].min(axis=1)
        out["_on_time"] = out["_due_min"].isna() | (out["shift_start_time"] <= out["_due_min"] + pd.Timedelta(days=1))
        sort_cols = ["demand_id", "_on_time", "slot_rank", "uph"]
        out = out.sort_values(sort_cols, ascending=[True, False, True, False])
        out["_slot_keep_rank"] = out.groupby("demand_id").cumcount() + 1
        out = out[out["_slot_keep_rank"] <= int(config.max_slots_per_demand)].copy()

    missing_demands = set(base_candidates["demand_id"].astype(str)) - set(out["demand_id"].astype(str))
    if missing_demands:
        fallback_limit = int(config.max_slots_per_demand or 30)
        fallback = base_candidates[base_candidates["demand_id"].astype(str).isin(missing_demands)].copy()
        fallback = fallback.sort_values(["demand_id", "slot_rank", "uph"], ascending=[True, True, False])
        fallback["_slot_keep_rank"] = fallback.groupby("demand_id").cumcount() + 1
        fallback = fallback[fallback["_slot_keep_rank"] <= fallback_limit]
        # fallback rows are retained for anti-empty safety and must keep trace flags.
        for col in [
            "is_ots_timely",
            "is_fpsd_timely",
            "is_ship2_timely",
            "is_ots_extended",
            "is_fpsd_extended",
            "is_ship2_extended",
            "keep_by_timely",
            "keep_by_extended",
        ]:
            if col not in fallback.columns:
                fallback[col] = 0
        fallback["kept_by_reason"] = "fallback"
        out = pd.concat([out, fallback], ignore_index=True)

    drop_cols = [
        "mr_day_dt",
        "ots_date_dt",
        "fpsd_dt",
        "ship_day_two_dt",
        "_day",
        "_due_min",
        "_on_time",
        "_slot_keep_rank",
        "_ots_timely_cutoff",
        "_fpsd_timely_cutoff",
        "_ship2_timely_cutoff",
        "_ots_ext_cutoff",
        "_fpsd_ext_cutoff",
        "_ship2_ext_cutoff",
    ]
    out = out.drop(columns=drop_cols, errors="ignore")
    out = out.drop_duplicates(["demand_id", "line_id", "slot_id"]).reset_index(drop=True)
    removed = int(len(triples) - len(out))
    if removed > 0:
        issues.append({"level": "info", "where": "triples", "message": f"Pruned {removed} sparse demand-line-slot candidates before MILP build."})
    return out


def _apply_day_buckets(
    triples: pd.DataFrame,
    line_slots: pd.DataFrame,
    slots: pd.DataFrame,
    fixed_locks: pd.DataFrame,
    adjust_locks: pd.DataFrame,
    config: PreprocessConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Collapse far-future shifts into line-day buckets."""

    if config.bucket_after_days is None or config.bucket_after_days < 0 or slots.empty:
        return triples, line_slots, slots, fixed_locks, adjust_locks

    start = pd.to_datetime(slots["shift_start_time"], errors="coerce").min()
    if pd.isna(start):
        return triples, line_slots, slots, fixed_locks, adjust_locks
    cutoff = start + pd.Timedelta(days=int(config.bucket_after_days))
    slot_info = slots[["slot_id", "day", "shift_start_time", "shift_end_time"]].copy()
    slot_info["shift_start_time"] = pd.to_datetime(slot_info["shift_start_time"], errors="coerce")
    slot_info["shift_end_time"] = pd.to_datetime(slot_info["shift_end_time"], errors="coerce")
    slot_info["bucket_slot_id"] = slot_info.apply(
        lambda row: _bucket_slot_id(row["day"]) if pd.notna(row["shift_start_time"]) and row["shift_start_time"] >= cutoff else row["slot_id"],
        axis=1,
    )
    slot_map = slot_info.set_index("slot_id")["bucket_slot_id"].to_dict()

    new_line_slots = line_slots.copy()
    new_line_slots["slot_id"] = new_line_slots["slot_id"].map(lambda s: slot_map.get(s, s))
    sum_cols = ["cap_hours", "down_hours", "reserved_hours", "occupied_hours", "avail_hours"]
    for col in sum_cols:
        if col not in new_line_slots.columns:
            new_line_slots[col] = 0.0
        new_line_slots[col] = _safe_numeric(new_line_slots[col])
    aggregations: dict[str, tuple[str, str]] = {
        "day": ("day", "first"),
        "shift_seq": ("shift_seq", "first"),
        "shift_start_time": ("shift_start_time", "min"),
        "shift_end_time": ("shift_end_time", "max"),
        "cap_hours": ("cap_hours", "sum"),
        "down_hours": ("down_hours", "sum"),
        "reserved_hours": ("reserved_hours", "sum"),
        "occupied_hours": ("occupied_hours", "sum"),
        "avail_hours": ("avail_hours", "sum"),
        "allow_calendar": ("allow_calendar", "max"),
    }
    if "non_merge_flag" in new_line_slots.columns:
        aggregations["non_merge_flag"] = ("non_merge_flag", "max")
    if "fix_type" in new_line_slots.columns:
        aggregations["fix_type"] = ("fix_type", "max")
    new_line_slots = (
        new_line_slots.groupby(["line_id", "slot_id"], as_index=False)
        .agg(**aggregations)
        .sort_values(["shift_start_time", "line_id", "slot_id"])
        .reset_index(drop=True)
    )

    new_slots = (
        new_line_slots.groupby("slot_id", as_index=False)
        .agg(
            day=("day", "first"),
            shift_seq=("shift_seq", "first"),
            shift_start_time=("shift_start_time", "min"),
            shift_end_time=("shift_end_time", "max"),
        )
        .sort_values(["shift_start_time", "slot_id"])
        .reset_index(drop=True)
    )
    new_slots["slot_rank"] = range(len(new_slots))
    start0 = new_slots["shift_start_time"].min()
    new_slots["start_hour"] = (new_slots["shift_start_time"] - start0).dt.total_seconds() / 3600.0
    new_slots["end_hour"] = (new_slots["shift_end_time"] - start0).dt.total_seconds() / 3600.0
    new_line_slots = new_line_slots.drop(columns=["slot_rank", "start_hour", "end_hour"], errors="ignore").merge(
        new_slots[["slot_id", "slot_rank", "start_hour", "end_hour"]],
        on="slot_id",
        how="left",
    )

    new_triples = triples.copy()
    if not new_triples.empty:
        new_triples["slot_id"] = new_triples["slot_id"].map(lambda s: slot_map.get(s, s))
        new_triples = new_triples.merge(new_slots[["slot_id", "slot_rank", "start_hour", "shift_start_time"]], on="slot_id", how="left", suffixes=("", "_bucket"))
        for col in ["slot_rank", "start_hour", "shift_start_time"]:
            bucket_col = f"{col}_bucket"
            if bucket_col in new_triples.columns:
                new_triples[col] = new_triples[bucket_col].combine_first(new_triples[col])
        grouped = new_triples.groupby(["demand_id", "line_id", "slot_id"], as_index=False)
        out_rows: list[dict[str, Any]] = []
        for _, grp in grouped:
            best = grp.sort_values(["uph"], ascending=[False]).iloc[0].to_dict()
            for col in [
                "is_ots_timely",
                "is_fpsd_timely",
                "is_ship2_timely",
                "is_ots_extended",
                "is_fpsd_extended",
                "is_ship2_extended",
                "keep_by_timely",
                "keep_by_extended",
            ]:
                if col in grp.columns:
                    best[col] = int(pd.to_numeric(grp[col], errors="coerce").fillna(0).max())
            if "kept_by_reason" in grp.columns:
                reasons = [str(v).strip() for v in grp["kept_by_reason"].fillna("").astype(str).tolist() if str(v).strip()]
                best["kept_by_reason"] = "|".join(sorted(set(reasons))) if reasons else ""
            out_rows.append(best)
        new_triples = pd.DataFrame(out_rows)
        new_triples = (
            new_triples.drop(columns=[c for c in new_triples.columns if c.endswith("_bucket")], errors="ignore")
            .sort_values(["demand_id", "line_id", "slot_id"])
            .drop_duplicates(["demand_id", "line_id", "slot_id"])
            .reset_index(drop=True)
        )

    new_fixed = _bucket_locks(fixed_locks, slot_map)
    new_adjust = _bucket_locks(adjust_locks, slot_map)
    return new_triples, new_line_slots, new_slots, new_fixed, new_adjust


def _bucket_slot_id(day: Any) -> str:
    day_ts = pd.to_datetime(day, errors="coerce")
    day_text = day_ts.strftime("%Y-%m-%d") if pd.notna(day_ts) else str(day).strip()
    return f"{day_text}|DAY"


def _bucket_locks(locks: pd.DataFrame, slot_map: dict[str, str]) -> pd.DataFrame:
    if locks.empty:
        return locks
    out = locks.copy()
    out["slot_id"] = out["slot_id"].map(lambda s: slot_map.get(s, s))
    return out


def _end_of_day_with_days(value: Any, day_delta: int) -> pd.Timestamp:
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return pd.NaT
    day = pd.Timestamp(ts).normalize() + pd.Timedelta(days=int(day_delta))
    return day + pd.Timedelta(hours=23, minutes=59, seconds=59)


def _kpi_kept_reason(row: pd.Series) -> str:
    if int(row.get("keep_by_timely", 0) or 0) > 0:
        return "timely"
    if int(row.get("keep_by_extended", 0) or 0) > 0:
        return "extended"
    return "fallback"


def _apply_fai_slot_buffer(
    line_slots: pd.DataFrame,
    triples: pd.DataFrame,
    fai_arcs: pd.DataFrame,
    fixed_locks: pd.DataFrame,
    adjust_locks: pd.DataFrame,
    config: PreprocessConfig,
) -> pd.DataFrame:
    """Compute optional v7.6 B_{lt}^{fai} and attach to line_slots.

    Rule: for each (line, slot), for each FAI group that has at least one
    first-candidate and one rest-candidate on this slot, reserve this group's
    max lead_hours on this slot; sum across groups.

    Backward compatibility: when disabled, both columns are zero.
    Lock-friendly policy: do not apply FAI buffer on slots that already carry
    FIX/adjust locks, to reduce strict-lock infeasibility risk.
    """
    out = line_slots.copy()
    out["fai_buffer_hours"] = 0.0
    out["fai_buffer_minutes"] = 0.0
    if not bool(config.enable_fai_slot_buffer):
        return out
    if out.empty or triples.empty or fai_arcs.empty:
        return out

    tri = triples[["demand_id", "line_id", "slot_id"]].copy()
    for col in ["demand_id", "line_id", "slot_id"]:
        tri[col] = tri[col].astype(str)
    present = tri.drop_duplicates(["demand_id", "line_id", "slot_id"])

    arcs = fai_arcs.copy()
    for col in ["group_id", "first_demand_id", "rest_demand_id"]:
        arcs[col] = arcs[col].astype(str)
    arcs["lead_hours"] = pd.to_numeric(arcs["lead_hours"], errors="coerce").fillna(0.0).clip(lower=0.0)
    if arcs.empty:
        return out

    first_present = present.rename(columns={"demand_id": "first_demand_id"})[
        ["first_demand_id", "line_id", "slot_id"]
    ].copy()
    rest_present = present.rename(columns={"demand_id": "rest_demand_id"})[
        ["rest_demand_id", "line_id", "slot_id"]
    ].copy()

    hits = (
        arcs.merge(first_present, on="first_demand_id", how="inner")
        .merge(rest_present, on=["rest_demand_id", "line_id", "slot_id"], how="inner")
    )
    if hits.empty:
        return out

    group_slot = (
        hits.groupby(["group_id", "line_id", "slot_id"], as_index=False)["lead_hours"]
        .max()
        .rename(columns={"lead_hours": "group_slot_fai_hours"})
    )
    slot_buffer = (
        group_slot.groupby(["line_id", "slot_id"], as_index=False)["group_slot_fai_hours"]
        .sum()
        .rename(columns={"group_slot_fai_hours": "fai_buffer_hours"})
    )

    policy = str(getattr(config, "fai_buffer_policy", "lock_friendly") or "lock_friendly").strip().lower()
    if policy not in {"strict", "lock_friendly"}:
        logger.warning("preprocess:fai_slot_buffer unknown policy=%s, fallback=lock_friendly", policy)
        policy = "lock_friendly"

    if policy == "lock_friendly":
        lock_slots = set()
        for frame in [fixed_locks, adjust_locks]:
            if frame is None or frame.empty:
                continue
            lock_slots.update(
                (
                    str(r.line_id),
                    str(r.slot_id),
                )
                for r in frame[["line_id", "slot_id"]].dropna().itertuples(index=False)
            )
        if lock_slots:
            before = len(slot_buffer)
            slot_buffer = slot_buffer[
                ~slot_buffer.apply(lambda r: (str(r["line_id"]), str(r["slot_id"])) in lock_slots, axis=1)
            ].copy()
            logger.info(
                "preprocess:fai_slot_buffer policy=%s filtered_slots=%s kept_slots=%s",
                policy,
                before - len(slot_buffer),
                len(slot_buffer),
            )
    else:
        logger.info("preprocess:fai_slot_buffer policy=%s applies buffer on all eligible slots", policy)

    if config.fai_buffer_cap_minutes is not None:
        cap_hours = max(float(config.fai_buffer_cap_minutes), 0.0) / 60.0
        slot_buffer["fai_buffer_hours"] = slot_buffer["fai_buffer_hours"].clip(upper=cap_hours)

    slot_buffer["fai_buffer_minutes"] = slot_buffer["fai_buffer_hours"] * 60.0
    out = out.merge(slot_buffer, on=["line_id", "slot_id"], how="left", suffixes=("", "_calc"))
    out["fai_buffer_hours"] = pd.to_numeric(
        out.get("fai_buffer_hours_calc", out["fai_buffer_hours"]), errors="coerce"
    ).fillna(out["fai_buffer_hours"])
    out["fai_buffer_minutes"] = pd.to_numeric(
        out.get("fai_buffer_minutes_calc", out["fai_buffer_minutes"]), errors="coerce"
    ).fillna(out["fai_buffer_minutes"])
    out = out.drop(columns=["fai_buffer_hours_calc", "fai_buffer_minutes_calc"], errors="ignore")

    nonzero = out[pd.to_numeric(out["fai_buffer_hours"], errors="coerce").fillna(0.0) > 0.0][
        ["line_id", "slot_id", "fai_buffer_hours", "fai_buffer_minutes"]
    ]
    if len(nonzero):
        logger.info(
            "preprocess:fai_slot_buffer enabled=%s policy=%s nonzero_slots=%s sample=%s",
            bool(config.enable_fai_slot_buffer),
            policy,
            len(nonzero),
            nonzero.head(5).to_dict(orient="records"),
        )
    else:
        logger.info(
            "preprocess:fai_slot_buffer enabled=%s policy=%s nonzero_slots=0",
            bool(config.enable_fai_slot_buffer),
            policy,
        )
    return out


def _build_priority(
    sheets: dict[str, pd.DataFrame],
    demands: pd.DataFrame,
    slots: pd.DataFrame,
    config: PreprocessConfig,
    issues: list[dict[str, Any]],
) -> tuple[pd.DataFrame, str]:
    rules = sheets["aps_schedule_priority"].copy()
    if rules.empty:
        out = demands[["demand_id"]].copy()
        out["priority_rank"] = 99
        out["priority_weight"] = 1.0
        return out, config.default_kpi_mode
    rules["priority"] = _safe_numeric(rules["priority"]).astype(int)
    rules["priority_group"] = rules["priority_group"].map(_to_id)
    rules["condition_key"] = rules["condition_key"].fillna("").astype(str)
    rules["condition_value"] = rules["condition_value"].fillna("").astype(str)
    rules["condition_type"] = _safe_numeric(rules["condition_type"]).astype(int)
    kpis = sorted({str(k).strip() for k in rules.get("kpi", pd.Series(dtype=str)).dropna() if str(k).strip()})
    if len(kpis) > 1:
        issues.append({"level": "warning", "where": "priority", "message": f"Multiple non-empty KPI modes found: {kpis}; using {kpis[0]}."})
    kpi_mode = kpis[0] if kpis else config.default_kpi_mode
    ref_date = slots["shift_start_time"].min().normalize() if len(slots) else pd.Timestamp.today().normalize()

    group_rows = []
    for group_id, group in rules.groupby("priority_group"):
        group_priority = int(group["priority"].min())
        for demand in demands.itertuples(index=False):
            if _priority_group_hits(demand, group, ref_date):
                group_rows.append({"demand_id": demand.demand_id, "priority_group": group_id, "priority_rank": group_priority})
    if group_rows:
        hits = pd.DataFrame(group_rows)
        rank = hits.groupby("demand_id", as_index=False)["priority_rank"].min()
    else:
        rank = pd.DataFrame(columns=["demand_id", "priority_rank"])
    max_priority = int(rules["priority"].max()) + 1
    out = demands[["demand_id"]].merge(rank, on="demand_id", how="left")
    out["priority_rank"] = out["priority_rank"].fillna(max_priority).astype(int)
    out["priority_weight"] = (max_priority - out["priority_rank"] + 1).clip(lower=1).astype(float)
    return out, kpi_mode


def _priority_group_hits(demand: Any, group: pd.DataFrame, ref_date: pd.Timestamp) -> bool:
    for _, rule in group.iterrows():
        if not _priority_condition_hits(demand, rule, ref_date):
            return False
    return True


def _priority_condition_hits(demand: Any, rule: pd.Series, ref_date: pd.Timestamp) -> bool:
    key = str(rule["condition_key"]).strip()
    key_norm = key.lower()
    ctype = int(rule["condition_type"])
    value = str(rule["condition_value"]).strip()
    if key_norm == "rolling mo":
        actual = str(getattr(demand, "demand_type", "")).upper()
        return actual == "ROLLING_MO"
    if key_norm == "others":
        actual = str(getattr(demand, "demand_type", "")).upper()
        desc = str(rule.get("second_priority_desc", "")).upper()
        if "OPEN" in desc:
            return actual == "OPEN_MO"
        return actual not in {"ROLLING_MO", "OPEN_MO"}
    if key_norm in {"pre_lock", "fast_ship", "cust_svc"}:
        return bool(int(getattr(demand, key_norm, 0) or 0))
    if key_norm in {"ots_date", "fpsd", "ship_day_two"}:
        dt = getattr(demand, f"{key_norm}_dt", pd.NaT)
        dt_parsed = pd.to_datetime(dt, errors="coerce")
        if pd.isna(dt_parsed):
            return False
        ref_ts = pd.to_datetime(ref_date, errors="coerce")
        if pd.isna(ref_ts):
            raise ValueError(f"Invalid ref_date for priority evaluation: {ref_date!r}")
        try:
            offset = int(float(value))
        except ValueError:
            return False
        days = (pd.Timestamp(dt_parsed).normalize() - pd.Timestamp(ref_ts).normalize()).days
        if ctype == 3:
            return days == offset
        if ctype == 2:
            return days >= offset
        if ctype == 5:
            return days <= offset
        return days == offset
    raw_actual = getattr(demand, key, "")
    actual = "" if pd.isna(raw_actual) else str(raw_actual)
    if value in {"", "*", "X"}:
        return _truthy(actual) if value == "X" else True
    return actual == value


def _build_fai_arcs(
    sheets: dict[str, pd.DataFrame],
    demands: pd.DataFrame,
    config: PreprocessConfig,
    issues: list[dict[str, Any]],
) -> pd.DataFrame:
    fai = sheets["aps_schedule_demand_fai_input"].copy()
    if fai.empty:
        return pd.DataFrame(columns=["group_id", "first_demand_id", "rest_demand_id", "lead_hours"])
    demand_ids = set(demands["demand_id"])
    fai["demand_id"] = fai["demand_id"].map(_to_id)
    fai = fai[fai["demand_id"].isin(demand_ids)]
    fai["group_id"] = fai["group_id"].map(_to_id)
    fai["group_first"] = fai["group_first"].map(_truthy).astype(int)
    fai["lead_time"] = _safe_numeric(fai["lead_time"])
    rows = []
    for group_id, group in fai.groupby("group_id"):
        first_rows = group[group["group_first"] == 1]
        rest_rows = group[group["group_first"] != 1]
        if first_rows.empty or rest_rows.empty:
            continue
        first = first_rows.iloc[0]
        lead_hours = _lead_to_hours(first["lead_time"], config.fai_lead_time_unit)
        for rest in rest_rows["demand_id"]:
            rows.append(
                {
                    "group_id": group_id,
                    "first_demand_id": first["demand_id"],
                    "rest_demand_id": rest,
                    "lead_hours": lead_hours,
                }
            )
        if len(first_rows) > 1:
            issues.append({"level": "warning", "where": "fai", "message": f"FAI group {group_id} has multiple first rows; using the first one."})
    return pd.DataFrame(rows, columns=["group_id", "first_demand_id", "rest_demand_id", "lead_hours"])


def _lead_to_hours(value: float, unit: str) -> float:
    unit = unit.lower()
    if unit.startswith("min"):
        return float(value) / 60.0
    if unit.startswith("day"):
        return float(value) * 24.0
    return float(value)


def _build_change_min(sheets: dict[str, pd.DataFrame], lines: pd.DataFrame, demands: pd.DataFrame) -> pd.DataFrame:
    change = sheets["aps_change_time_input"].copy()
    if change.empty:
        return pd.DataFrame({"line_id": lines["line_id"], "ct_min_hours": 0.0})
    change["mcode"] = change["mcode"].fillna("").astype(str).str.strip()
    change["pu"] = change.get("pu", "").fillna("").astype(str).str.strip()
    change["change_time"] = _safe_numeric(change["change_time"])
    demand_mcodes = set(demands["mcode"].dropna().astype(str))
    rows = []
    for line in lines.itertuples(index=False):
        pu = str(getattr(line, "pu", "") or "")
        subset = change[change["mcode"].isin(demand_mcodes)]
        if pu:
            specific = subset[(subset["pu"] == pu) | (subset["pu"] == "") | (subset["pu"] == "*")]
            if not specific.empty:
                subset = specific
        minutes = float(subset["change_time"].min()) if not subset.empty else 0.0
        rows.append({"line_id": line.line_id, "ct_min_hours": minutes / 60.0})
    return pd.DataFrame(rows)


def _build_order_keys(sheets: dict[str, pd.DataFrame]) -> pd.DataFrame:
    ruler = sheets["aps_schedule_order_ruler"].copy()
    if ruler.empty:
        return pd.DataFrame(columns=["line_id", "mcode", "model", "priority", "condition_key"])
    ruler["line_id"] = ruler["line_id"].map(_to_id)
    ruler["priority"] = _safe_numeric(ruler["priority"]).astype(int)
    return ruler[["line_id", "mcode", "model", "priority", "condition_key"]].sort_values(
        ["line_id", "priority"]
    ).reset_index(drop=True)
