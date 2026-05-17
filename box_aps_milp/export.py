"""Export solved schedules into BOX APS output table layouts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from .data import ProcessedData, load_processed_data


ADJUST_OUTPUT_COLUMNS = [
    "id",
    "run_version",
    "schedule_version",
    "sub_schedule_version",
    "schedule_line_version",
    "mcode",
    "demand_id",
    "schedule_qty",
    "line_id",
    "schedule_seq",
    "schedule_day",
    "shift_seq",
    "reserved_id",
]

CHANGE_LINE_COLUMNS = [
    "id",
    "schedule_version",
    "sub_schedule_version",
    "line_id",
    "day",
    "shift_seq",
    "times",
    "raw_times",
    "effective_times",
    "locked_changeovers",
    "row_count",
    "distinct_models",
    "locked_rows",
    "fix_rows",
    "adjust_rows",
    "milp_rows",
]

SCHEDULE_RESULT_COLUMNS = [
    "id",
    "schedule_version",
    "sub_schedule_version",
    "schedule_line_version",
    "pu",
    "pu_site",
    "plant",
    "biz_type",
    "schedule_line",
    "schedule_line_id",
    "schedule_start_time",
    "schedule_end_time",
    "schedule_seq",
    "time_block_type",
    "demand_id",
    "schedule_cut_no",
    "schedule_cut_qty",
    "shift",
    "shift_seq",
    "schedule_day",
    "effective_flag",
    "schedule_problem_type",
    "schedule_status",
    "uph_qty",
    "reserver_id",
    "manual_flag",
    "create_time",
]

DEMAND_COVERAGE_COLUMNS = [
    "id",
    "schedule_version",
    "sub_schedule_version",
    "demand_id",
    "pn",
    "mcode",
    "model",
    "demand_qty",
    "scheduled_qty",
    "remaining_qty",
    "coverage_status",
    "scheduled_rows",
    "scheduled_lines",
    "scheduled_slots",
    "source_flags",
    "priority_rank",
    "priority_weight",
]

RUNTIME_LOG_COLUMNS = [
    "id",
    "run_version",
    "schedule_version",
    "sub_schedule_version",
    "schedule_line_version",
    "mcode",
    "demand_id",
    "line",
    "model",
    "series",
    "program",
    "schedule_qty",
    "date",
    "shift",
    "shift_seq",
    "reserver_id",
    "schedule_seq",
    "fix_shift",
    "mo",
    "lot",
    "texture",
    "color",
    "kb",
    "cover_assy",
    "log_up_assy",
    "pcba",
    "thermal",
    "material_sections",
    "created_by",
    "created_time",
    "updated_by",
    "updated_time",
]


@dataclass(slots=True)
class ExportConfig:
    run_version: str | None = None
    schedule_version: str | None = None
    sub_schedule_version: str | None = None
    schedule_line_version: int = 1
    biz_type: str = ""
    plant: str = ""
    create_time: str | None = None


@dataclass(slots=True)
class ExportArtifacts:
    tables: dict[str, pd.DataFrame]
    summary: dict[str, Any]


def build_export_artifacts(
    solution_csv: str | Path,
    processed_dir: str | Path,
    config: ExportConfig | None = None,
    source_input_xlsx: str | Path | None = None,
) -> ExportArtifacts:
    """Prepare BOX APS output tables and observability metrics."""

    config = config or ExportConfig()
    data = load_processed_data(processed_dir)
    solution = pd.read_csv(solution_csv, dtype=str, keep_default_na=False)
    enriched = _enrich_solution(solution, data, config, source_input_xlsx)

    adjust_output = _build_adjust_output(enriched)
    change_line = _build_change_line(enriched, config)
    schedule_result = _build_schedule_result(enriched)
    demand_coverage = _build_demand_coverage(data, enriched, config)
    runtime_log = _build_runtime_log(enriched)

    tables = {
        "aps_adjust_schedule_output": adjust_output,
        "aps_schedule_change_line": change_line,
        "aps_schedule_result": schedule_result,
        "aps_demand_coverage_output": demand_coverage,
        "aps_schedule_runtime_log": runtime_log,
    }
    summary = {
        "coverage": _summarize_demand_coverage(demand_coverage),
        "changeovers": _summarize_change_line(change_line),
    }
    return ExportArtifacts(tables=tables, summary=summary)


def write_export_tables(artifacts: ExportArtifacts, output_dir: str | Path) -> dict[str, Path]:
    """Write prepared export tables to CSV files."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for name, frame in artifacts.tables.items():
        path = output / f"{name}.csv"
        frame.to_csv(path, index=False, encoding="utf-8-sig")
        paths[name] = path
    return paths


def export_solution_tables(
    solution_csv: str | Path,
    processed_dir: str | Path,
    output_dir: str | Path,
    config: ExportConfig | None = None,
    source_input_xlsx: str | Path | None = None,
) -> dict[str, Path]:
    """Write BOX APS output-table CSVs and return their paths."""

    artifacts = build_export_artifacts(
        solution_csv=solution_csv,
        processed_dir=processed_dir,
        config=config,
        source_input_xlsx=source_input_xlsx,
    )
    return write_export_tables(artifacts, output_dir)


def _enrich_solution(
    solution: pd.DataFrame,
    data: ProcessedData,
    config: ExportConfig,
    source_input_xlsx: str | Path | None,
) -> pd.DataFrame:
    out = solution.copy()
    for col in ["demand_id", "line_id", "slot_id"]:
        if col in out.columns:
            out[col] = out[col].astype(str)

    versions = _resolve_versions(data, config)
    for key, value in versions.items():
        out[key] = value

    out["schedule_line_version"] = int(config.schedule_line_version)
    out["biz_type"] = config.biz_type
    out["create_time"] = config.create_time or pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    out["schedule_qty"] = pd.to_numeric(out["schedule_qty"], errors="coerce").fillna(0).round().astype(int)
    out["sequence"] = pd.to_numeric(out.get("sequence", 0), errors="coerce").fillna(0).astype(int)
    out["seq"] = pd.to_numeric(out.get("seq", pd.NA), errors="coerce")
    if "uph" in out.columns:
        out["uph"] = pd.to_numeric(out["uph"], errors="coerce").fillna(0.0)

    demand_source = data.raw_demands if len(data.raw_demands) else data.demands
    demand_cols = [
        "demand_id",
        "pn",
        "mcode",
        "model",
        "program",
        "series",
        "texture",
        "color",
        "mo",
        "lot",
        "kb",
        "cover_assy",
        "log_up_assy",
        "pcba",
        "material_type",
        "country",
    ]
    demand_cols = [c for c in demand_cols if c in demand_source.columns]
    out = out.drop(columns=[c for c in demand_cols if c != "demand_id" and c in out.columns], errors="ignore")
    out = out.merge(demand_source[demand_cols], on="demand_id", how="left", suffixes=("", "_demand"))

    line_cols = [c for c in ["line_id", "line", "pu", "pu_site"] if c in data.lines.columns]
    out = out.drop(columns=[c for c in ["line", "pu", "pu_site"] if c in out.columns], errors="ignore")
    out = out.merge(data.lines[line_cols], on="line_id", how="left")

    uph = data.triples[["demand_id", "line_id", "slot_id", "uph"]].copy() if len(data.triples) else pd.DataFrame()
    if len(uph):
        for col in ["demand_id", "line_id", "slot_id"]:
            uph[col] = uph[col].astype(str)
        out = out.merge(
            uph.drop_duplicates(["demand_id", "line_id", "slot_id"]).rename(columns={"uph": "uph_lookup"}),
            on=["demand_id", "line_id", "slot_id"],
            how="left",
        )
        if "uph" in out.columns:
            out["uph"] = pd.to_numeric(out["uph"], errors="coerce").fillna(0.0)
            out["uph_lookup"] = pd.to_numeric(out.get("uph_lookup", 0.0), errors="coerce").fillna(0.0)
            out["uph"] = out["uph"].where(out["uph"] > 0, out["uph_lookup"])
            out = out.drop(columns=["uph_lookup"], errors="ignore")
        else:
            out = out.rename(columns={"uph_lookup": "uph"})
    if "uph" not in out.columns:
        out["uph"] = pd.NA
    out["uph"] = pd.to_numeric(out["uph"], errors="coerce").fillna(0.0)

    extra = _load_source_extras(source_input_xlsx)
    if len(extra["demands"]):
        out = out.merge(extra["demands"], on="demand_id", how="left", suffixes=("", "_src"))
        for col in ["plant", "thermal", "material_sections"]:
            out[col] = _coalesce_text_column(out, col, f"{col}_src")
        for col in ["texture", "color", "kb", "cover_assy", "log_up_assy", "pcba", "program", "series"]:
            if f"{col}_src" in out.columns:
                out[col] = _coalesce_text_column(out, col, f"{col}_src")
    else:
        for col in ["plant", "thermal", "material_sections"]:
            if col not in out.columns:
                out[col] = ""

    if len(extra["calendar"]):
        out["schedule_day_key"] = pd.to_datetime(out["day"], errors="coerce").dt.strftime("%Y-%m-%d")
        cal = extra["calendar"].copy()
        cal["schedule_day_key"] = pd.to_datetime(cal["schedule_day"], errors="coerce").dt.strftime("%Y-%m-%d")
        out = out.merge(
            cal[["line_id", "schedule_day_key", "shift_seq", "shift", "fix_shift"]],
            on=["line_id", "schedule_day_key", "shift_seq"],
            how="left",
        )
    else:
        out["shift"] = ""
        out["fix_shift"] = 0

    if config.plant:
        out["plant"] = config.plant
    for col in ["shift", "fix_shift", "plant", "thermal", "material_sections"]:
        if col not in out.columns:
            out[col] = ""
    out["fix_shift"] = pd.to_numeric(out["fix_shift"], errors="coerce").fillna(0).astype(int)
    out["shift"] = out["shift"].where(out["shift"].astype(str).ne(""), out["shift_seq"].astype(str))
    out["schedule_day"] = pd.to_datetime(out["day"], errors="coerce").dt.strftime("%Y-%m-%d")
    out["schedule_seq"] = out["sequence"].where(out["sequence"] > 0, out["seq"]).fillna(0).astype(int)
    # v7.6: second_stage may already provide timeline columns with FAI waits.
    # Keep backward compatibility by falling back to legacy assignment when
    # those columns are absent.
    has_second_stage_timeline = {
        "schedule_start_time_calc",
        "schedule_end_time_calc",
    }.issubset(set(out.columns))
    if not has_second_stage_timeline:
        out = _assign_schedule_times(out)
    return _empty_to_blank(out)


def _build_adjust_output(enriched: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=enriched.index)
    out["id"] = range(1, len(enriched) + 1)
    out["run_version"] = enriched["run_version"]
    out["schedule_version"] = enriched["schedule_version"]
    out["sub_schedule_version"] = enriched["sub_schedule_version"]
    out["schedule_line_version"] = enriched["schedule_line_version"]
    out["mcode"] = enriched.get("mcode", "")
    out["demand_id"] = enriched["demand_id"]
    out["schedule_qty"] = enriched["schedule_qty"]
    out["line_id"] = enriched["line_id"]
    out["schedule_seq"] = enriched["schedule_seq"]
    out["schedule_day"] = enriched["schedule_day"]
    out["shift_seq"] = enriched["shift_seq"]
    out["reserved_id"] = ""
    return out[ADJUST_OUTPUT_COLUMNS]


def _build_change_line(enriched: pd.DataFrame, config: ExportConfig) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    ordered = enriched.sort_values(["line_id", "schedule_day", "shift_seq", "schedule_seq", "demand_id"])
    for (line_id, day, shift_seq), group in ordered.groupby(["line_id", "schedule_day", "shift_seq"], dropna=False):
        source = group["source"].astype(str) if "source" in group.columns else pd.Series("", index=group.index)
        raw_times = _count_model_changeovers(group)
        milp_group = group[source == "milp"].copy()
        locked_group = group[source != "milp"].copy()
        effective_times = _count_model_changeovers(milp_group)
        locked_changeovers = _count_model_changeovers(locked_group)
        rows.append(
            {
                "id": len(rows) + 1,
                "schedule_version": group["schedule_version"].iloc[0],
                "sub_schedule_version": group["sub_schedule_version"].iloc[0],
                "line_id": line_id,
                "day": day,
                "shift_seq": shift_seq,
                # Default to solver-owned changeovers so inherited lock churn does
                # not dominate the public KPI.
                "times": effective_times,
                "raw_times": raw_times,
                "effective_times": effective_times,
                "locked_changeovers": locked_changeovers,
                "row_count": int(len(group)),
                "distinct_models": int(group["model"].fillna("").astype(str).str.strip().replace("", pd.NA).dropna().nunique()),
                "locked_rows": int(len(locked_group)),
                "fix_rows": int((source == "fix").sum()),
                "adjust_rows": int((source == "adjust").sum()),
                "milp_rows": int((source == "milp").sum()),
            }
        )
    return pd.DataFrame(rows, columns=CHANGE_LINE_COLUMNS)


def _build_schedule_result(enriched: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=enriched.index)
    out["id"] = range(1, len(enriched) + 1)
    out["schedule_version"] = enriched["schedule_version"]
    out["sub_schedule_version"] = enriched["sub_schedule_version"]
    out["schedule_line_version"] = enriched["schedule_line_version"]
    out["pu"] = enriched.get("pu", "")
    out["pu_site"] = enriched.get("pu_site", "")
    out["plant"] = enriched.get("plant", "")
    out["biz_type"] = enriched.get("biz_type", "")
    out["schedule_line"] = enriched.get("line", "")
    out["schedule_line_id"] = enriched["line_id"]
    out["schedule_start_time"] = enriched["schedule_start_time_calc"]
    out["schedule_end_time"] = enriched["schedule_end_time_calc"]
    out["schedule_seq"] = enriched["schedule_seq"]
    out["time_block_type"] = enriched["source"].map(lambda s: 5 if str(s) == "fix" else 2)
    out["demand_id"] = enriched["demand_id"]
    out["schedule_cut_no"] = range(1, len(enriched) + 1)
    out["schedule_cut_qty"] = enriched["schedule_qty"]
    out["shift"] = enriched.get("shift", "")
    out["shift_seq"] = enriched["shift_seq"]
    out["schedule_day"] = enriched["schedule_day"]
    out["effective_flag"] = 1
    out["schedule_problem_type"] = enriched.apply(lambda r: 1 if str(r.get("source", "")) == "fix" and float(r.get("uph", 0) or 0) <= 0 else "", axis=1)
    out["schedule_status"] = ""
    out["uph_qty"] = enriched["uph"].round().astype(int)
    out["reserver_id"] = ""
    out["manual_flag"] = 0
    out["create_time"] = enriched["create_time"]
    return out[SCHEDULE_RESULT_COLUMNS]


def _build_demand_coverage(data: ProcessedData, enriched: pd.DataFrame, config: ExportConfig) -> pd.DataFrame:
    versions = _resolve_versions(data, config)
    demands = data.raw_demands.copy() if len(data.raw_demands) else data.demands.copy()
    for col in ["demand_id", "pn", "mcode", "model"]:
        if col not in demands.columns:
            demands[col] = ""
    demand_base = demands[["demand_id", "pn", "mcode", "model", "qty", "priority_rank", "priority_weight"]].copy()
    demand_base["qty"] = pd.to_numeric(demand_base["qty"], errors="coerce").fillna(0).round().astype(int)

    scheduled = enriched.copy()
    if scheduled.empty:
        grouped = pd.DataFrame(
            columns=[
                "demand_id",
                "scheduled_qty",
                "scheduled_rows",
                "scheduled_lines",
                "scheduled_slots",
                "source_flags",
            ]
        )
    else:
        scheduled["schedule_qty"] = pd.to_numeric(scheduled["schedule_qty"], errors="coerce").fillna(0)
        grouped = (
            scheduled.groupby("demand_id", as_index=False)
            .agg(
                scheduled_qty=("schedule_qty", "sum"),
                scheduled_rows=("schedule_qty", "size"),
                scheduled_lines=("line_id", pd.Series.nunique),
                scheduled_slots=("slot_id", pd.Series.nunique),
                source_flags=("source", lambda s: "|".join(sorted({str(v) for v in s if str(v)}))),
            )
        )
        grouped["scheduled_qty"] = grouped["scheduled_qty"].round().astype(int)

    out = demand_base.merge(grouped, on="demand_id", how="left")
    out["scheduled_qty"] = pd.to_numeric(out["scheduled_qty"], errors="coerce").fillna(0).astype(int)
    out["scheduled_rows"] = pd.to_numeric(out["scheduled_rows"], errors="coerce").fillna(0).astype(int)
    out["scheduled_lines"] = pd.to_numeric(out["scheduled_lines"], errors="coerce").fillna(0).astype(int)
    out["scheduled_slots"] = pd.to_numeric(out["scheduled_slots"], errors="coerce").fillna(0).astype(int)
    out["source_flags"] = out["source_flags"].fillna("").astype(str)
    out["remaining_qty"] = (out["qty"] - out["scheduled_qty"]).clip(lower=0).astype(int)
    out["coverage_status"] = "unscheduled"
    out.loc[out["scheduled_qty"] > out["qty"], "coverage_status"] = "overscheduled"
    out.loc[(out["scheduled_qty"] > 0) & (out["scheduled_qty"] < out["qty"]), "coverage_status"] = "partially_scheduled"
    out.loc[out["scheduled_qty"] == out["qty"], "coverage_status"] = "fully_scheduled"
    out["id"] = range(1, len(out) + 1)
    out["schedule_version"] = versions["schedule_version"]
    out["sub_schedule_version"] = versions["sub_schedule_version"]
    out = out.rename(columns={"qty": "demand_qty"})
    return out[DEMAND_COVERAGE_COLUMNS]


def _build_runtime_log(enriched: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=enriched.index)
    out["id"] = range(1, len(enriched) + 1)
    out["run_version"] = enriched["run_version"]
    out["schedule_version"] = enriched["schedule_version"]
    out["sub_schedule_version"] = enriched["sub_schedule_version"]
    out["schedule_line_version"] = enriched["schedule_line_version"]
    out["mcode"] = enriched.get("mcode", "")
    out["demand_id"] = enriched["demand_id"]
    # BOX 输出表字段名为 line，口径对应线体ID。
    out["line"] = enriched["line_id"]
    out["model"] = enriched.get("model", "")
    out["series"] = enriched.get("series", "")
    out["program"] = enriched.get("program", "")
    out["schedule_qty"] = enriched["schedule_qty"]
    out["date"] = enriched["schedule_day"]
    out["shift"] = enriched.get("shift", "")
    out["shift_seq"] = enriched["shift_seq"]
    out["reserver_id"] = ""
    out["schedule_seq"] = enriched["schedule_seq"]
    out["fix_shift"] = pd.to_numeric(enriched.get("fix_shift", 0), errors="coerce").fillna(0).astype(int)
    out["mo"] = enriched.get("mo", "")
    out["lot"] = enriched.get("lot", "")
    out["texture"] = enriched.get("texture", "")
    out["color"] = enriched.get("color", "")
    out["kb"] = enriched.get("kb", "")
    out["cover_assy"] = enriched.get("cover_assy", "")
    out["log_up_assy"] = enriched.get("log_up_assy", "")
    out["pcba"] = enriched.get("pcba", "")
    out["thermal"] = enriched.get("thermal", "")
    out["material_sections"] = enriched.get("material_sections", "")
    out["created_by"] = ""
    out["created_time"] = enriched["create_time"]
    out["updated_by"] = ""
    out["updated_time"] = enriched["create_time"]
    return out[RUNTIME_LOG_COLUMNS]


def _assign_schedule_times(enriched: pd.DataFrame) -> pd.DataFrame:
    out = enriched.sort_values(["line_id", "slot_id", "schedule_seq", "demand_id"]).copy()
    starts: list[str] = []
    ends: list[str] = []
    for _, group in out.groupby(["line_id", "slot_id"], sort=False):
        cursor = pd.to_datetime(group["shift_start_time"].iloc[0], errors="coerce")
        slot_end = pd.to_datetime(group["shift_end_time"].iloc[0], errors="coerce")
        for row in group.itertuples(index=False):
            start = cursor
            uph = float(getattr(row, "uph", 0.0) or 0.0)
            qty = float(getattr(row, "schedule_qty", 0.0) or 0.0)
            duration = pd.Timedelta(hours=qty / uph) if uph > 0 else pd.Timedelta(0)
            end = start + duration if pd.notna(start) else pd.NaT
            if pd.notna(slot_end) and pd.notna(end) and end > slot_end:
                end = slot_end
            starts.append(_format_datetime(start))
            ends.append(_format_datetime(end))
            cursor = end if pd.notna(end) else cursor
    out["schedule_start_time_calc"] = starts
    out["schedule_end_time_calc"] = ends
    return out.sort_index()


def _resolve_versions(data: ProcessedData, config: ExportConfig) -> dict[str, str]:
    schedule_version = config.schedule_version or data.metadata.get("schedule_version") or data.config.schedule_version or ""
    sub_schedule_version = config.sub_schedule_version or data.config.sub_schedule_version or ""
    run_version = config.run_version or schedule_version
    return {
        "run_version": str(run_version),
        "schedule_version": str(schedule_version),
        "sub_schedule_version": str(sub_schedule_version),
    }


def _load_source_extras(source_input_xlsx: str | Path | None) -> dict[str, pd.DataFrame]:
    empty = {"demands": pd.DataFrame(), "calendar": pd.DataFrame()}
    if source_input_xlsx is None:
        return empty
    path = Path(source_input_xlsx)
    if not path.exists():
        return empty
    demands = _read_source_sheet(path, "aps_schedule_demand_base_input")
    calendar = _read_source_sheet(path, "aps_schedule_line_calendar")
    demand_cols = [
        "demand_id",
        "plant",
        "thermal",
        "material_sections",
        "texture",
        "color",
        "kb",
        "cover_assy",
        "log_up_assy",
        "pcba",
        "program",
        "series",
    ]
    if len(demands):
        demands = demands[[c for c in demand_cols if c in demands.columns]].drop_duplicates("demand_id")
        demands["demand_id"] = demands["demand_id"].astype(str)
    if len(calendar):
        for col in ["line_id", "shift_seq"]:
            calendar[col] = calendar[col].astype(str)
        calendar["fix_type"] = pd.to_numeric(calendar.get("fix_type", 0), errors="coerce").fillna(0).astype(int)
        calendar["non_merge_flag"] = pd.to_numeric(calendar.get("non_merge_flag", 0), errors="coerce").fillna(0).astype(int)
        calendar["fix_shift"] = ((calendar["fix_type"] == 0) & (calendar["non_merge_flag"] == 0)).astype(int)
        if "shift" not in calendar.columns:
            calendar["shift"] = calendar["shift_seq"]
        calendar = calendar.rename(columns={"day": "schedule_day"})
        calendar = calendar[["line_id", "schedule_day", "shift_seq", "shift", "fix_shift"]].drop_duplicates(
            ["line_id", "schedule_day", "shift_seq"]
        )
    return {"demands": demands, "calendar": calendar}


def _read_source_sheet(path: Path, sheet_name: str) -> pd.DataFrame:
    try:
        df = pd.read_excel(path, sheet_name=sheet_name, dtype=str, keep_default_na=False)
    except ValueError:
        return pd.DataFrame()
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].map(lambda v: str(v).strip() if v is not None else "")
    return df


def _format_datetime(value: Any) -> str:
    if pd.isna(value):
        return ""
    return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M:%S")


def _empty_to_blank(df: pd.DataFrame) -> pd.DataFrame:
    return df.fillna("").replace({"nan": "", "NaT": "", "<NA>": ""})


def _coalesce_text_column(df: pd.DataFrame, primary: str, fallback: str) -> pd.Series:
    left = df[primary] if primary in df.columns else pd.Series("", index=df.index)
    right = df[fallback] if fallback in df.columns else pd.Series("", index=df.index)
    return left.where(left.astype(str).ne(""), right)


def _count_model_changeovers(frame: pd.DataFrame) -> int:
    if frame.empty or "model" not in frame.columns:
        return 0
    models = [str(m).strip() for m in frame["model"].fillna("").astype(str) if str(m).strip()]
    return sum(1 for prev, cur in zip(models, models[1:]) if prev != cur)


def _summarize_demand_coverage(frame: pd.DataFrame) -> dict[str, int]:
    if frame.empty:
        return {
            "total_demands": 0,
            "scheduled_demands": 0,
            "fully_scheduled_demands": 0,
            "partially_scheduled_demands": 0,
            "unscheduled_demands": 0,
            "overscheduled_demands": 0,
        }
    status = frame["coverage_status"].fillna("").astype(str)
    return {
        "total_demands": int(len(frame)),
        "scheduled_demands": int((frame["scheduled_qty"] > 0).sum()),
        "fully_scheduled_demands": int((status == "fully_scheduled").sum()),
        "partially_scheduled_demands": int((status == "partially_scheduled").sum()),
        "unscheduled_demands": int((status == "unscheduled").sum()),
        "overscheduled_demands": int((status == "overscheduled").sum()),
    }


def _summarize_change_line(frame: pd.DataFrame) -> dict[str, int]:
    if frame.empty:
        return {
            "line_shift_groups": 0,
            "raw_changeovers": 0,
            "effective_changeovers": 0,
            "locked_changeovers": 0,
        }
    return {
        "line_shift_groups": int(len(frame)),
        "raw_changeovers": int(pd.to_numeric(frame["raw_times"], errors="coerce").fillna(0).sum()),
        "effective_changeovers": int(pd.to_numeric(frame["effective_times"], errors="coerce").fillna(0).sum()),
        "locked_changeovers": int(pd.to_numeric(frame["locked_changeovers"], errors="coerce").fillna(0).sum()),
    }
