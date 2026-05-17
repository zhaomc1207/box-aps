"""Command line interface for BOX APS preprocessing and MILP solving."""

from __future__ import annotations

from pathlib import Path
import argparse
import json
import logging
import sys
import traceback

import pandas as pd

from .data import PreprocessConfig, build_processed_data, load_processed_data
from .export import ExportConfig, build_export_artifacts, write_export_tables
from .model import ModelConfig, build_gurobi_model, extract_solution
from .second_stage import run_second_stage


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        logging.exception("BOX APS MILP run failed")
        print(f"ERROR: {exc}", file=sys.stderr)
        if logging.getLogger().isEnabledFor(logging.DEBUG):
            traceback.print_exc()
        return 1


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="BOX APS MILP data preprocessing and Gurobi model runner")
    parser.add_argument("--log-file", default=None, help="Write application logs to this file.")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    sub = parser.add_subparsers(dest="command", required=True)

    prep = sub.add_parser("preprocess", help="Read the BOX APS Excel input and export normalized model tables.")
    prep.add_argument("--input", required=True, help="Input xlsx, e.g. BOX-APS脱敏数据-2.xlsx")
    prep.add_argument("--output", required=True, help="Directory for processed CSV/metadata files")
    _add_preprocess_args(prep)

    solve = sub.add_parser("solve", help="Build and solve the Gurobi MILP.")
    solve.add_argument("--input", help="Input xlsx. If supplied, preprocessing is run first.")
    solve.add_argument("--processed", help="Existing processed data directory from preprocess command.")
    solve.add_argument("--output", default="outputs/solution.csv", help="Output CSV path for positive schedule quantities")
    _add_preprocess_args(solve)
    solve.add_argument("--time-limit", type=float, default=None)
    solve.add_argument("--mip-gap", type=float, default=None)
    solve.add_argument("--threads", type=int, default=None)
    solve.add_argument("--gurobi-log-file", default=None, help="Write Gurobi optimizer log to this file.")
    solve.add_argument("--summary", default=None, help="Write a machine-readable run summary JSON.")
    solve.add_argument("--no-strict-locks", action="store_true", help="Do not force FIX/adjust inherited locks.")
    solve.add_argument("--no-eliminate-locks", action="store_true", help="Keep FIX/adjust locks inside the MILP instead of subtracting them from capacity.")
    solve.add_argument(
        "--use-activation-binaries",
        dest="use_activation_binaries",
        action="store_true",
        help="Create z[d,l,t] binaries and one-line-per-slot constraints (default: on).",
    )
    solve.add_argument(
        "--no-activation-binaries",
        dest="use_activation_binaries",
        action="store_false",
        help="Disable z[d,l,t] binaries (lighter model, no per-slot activation).",
    )
    solve.set_defaults(use_activation_binaries=True)
    solve.add_argument("--no-prefer-complete-demands", action="store_true", help="Do not add the qtymax secondary objective that prefers fully completed demands.")
    solve.add_argument(
        "--fai-repair-iterations",
        type=int,
        default=1,
        help="Run this many post-solve FAI repair iterations by pruning violating rest-demand candidates (default: 1).",
    )
    solve.add_argument(
        "--enforce-fai-with-big-m",
        dest="enforce_fai_with_big_m",
        action="store_true",
        help="Use Big-M FAI precedence constraints (default: on). Requires --use-activation-binaries.",
    )
    solve.add_argument(
        "--no-enforce-fai-with-big-m",
        dest="enforce_fai_with_big_m",
        action="store_false",
        help="Disable Big-M FAI; use window-pruning + optional fai-repair only (lighter).",
    )
    solve.set_defaults(enforce_fai_with_big_m=True)
    solve.add_argument("--completion-upper", action="store_true", help="Add exact e_d upper-bound constraints. This can be very large on full data.")
    solve.add_argument("--no-completion-upper", action="store_true", help=argparse.SUPPRESS)
    # v7_2: delivery KPI buffers and urgent-flag boost (rule 13).
    solve.add_argument("--ots-buffer-days", type=int, default=2, help="Schedule must complete this many days before OTS to count as on-time (rule 13.1, v7_2 default: 2).")
    solve.add_argument("--fpsd-buffer-days", type=int, default=2, help="Schedule must complete this many days before FPSD to count as on-time (rule 13.2, v7_2 default: 2).")
    solve.add_argument("--ship2-buffer-days", type=int, default=2, help="Schedule must complete this many days before ship_day_two to count as on-time (rule 13.4 alignment, v7_2 default: 2).")
    solve.add_argument("--urgent-priority-boost", type=float, default=1.0, help="Multiplicative boost on priority_weight when om_urgent=1 (rule 13.3, v7_2 default: 1.0 → 2x weight).")
    solve.add_argument("--no-mr-exempt-ots", action="store_true", help="Do NOT exempt MR-day-limited demands from the OTS metric (rule 13.1 'MR Day限制的订单除外').")
    solve.add_argument("--no-mr-exempt-fpsd", action="store_true", help="Do NOT exempt MR-day-limited demands from the FPSD metric.")
    solve.add_argument("--no-mr-exempt-ship2", action="store_true", help="Do NOT exempt MR-day-limited demands from the ship_day_two metric.")

    export = sub.add_parser("export-outputs", help="Map a solution CSV into BOX APS output table CSV layouts.")
    export.add_argument("--solution", required=True, help="Solution CSV generated by the solve command.")
    export.add_argument("--processed", required=True, help="Processed data directory used by the solution.")
    export.add_argument("--output-dir", required=True, help="Directory for output-table CSV files.")
    export.add_argument("--source-input", default=None, help="Original BOX APS input xlsx, used to enrich optional output fields.")
    export.add_argument("--run-version", default=None)
    export.add_argument("--schedule-version", default=None)
    export.add_argument("--sub-schedule-version", default=None)
    export.add_argument("--schedule-line-version", type=int, default=1)
    export.add_argument("--biz-type", default="")
    export.add_argument("--plant", default="")
    export.add_argument("--create-time", default=None, help="Override create_time, e.g. '2026-03-10 08:00:00'.")

    run_all = sub.add_parser("run-all", help="Run preprocessing, main MILP, second stage, and output-table export.")
    run_all.add_argument("--input", required=True, help="Input xlsx, e.g. BOX-APS脱敏数据-2.xlsx")
    run_all.add_argument("--processed", required=True, help="Directory for processed CSV/metadata files")
    run_all.add_argument("--solution", required=True, help="Output CSV path for the second-stage schedule solution")
    run_all.add_argument("--summary", default=None, help="Write a machine-readable run summary JSON.")
    run_all.add_argument("--output-dir", required=True, help="Directory for output-table CSV files.")
    run_all.add_argument("--source-input", default=None, help="Original BOX APS input xlsx, used to enrich optional output fields. Defaults to --input.")
    run_all.add_argument("--run-version", default=None)
    run_all.add_argument("--schedule-line-version", type=int, default=1)
    run_all.add_argument("--biz-type", default="")
    run_all.add_argument("--plant", default="")
    run_all.add_argument("--create-time", default=None, help="Override create_time, e.g. '2026-03-10 08:00:00'.")
    _add_preprocess_args(run_all)
    run_all.add_argument("--time-limit", type=float, default=None)
    run_all.add_argument("--mip-gap", type=float, default=None)
    run_all.add_argument("--threads", type=int, default=None)
    run_all.add_argument("--gurobi-log-file", default=None, help="Write Gurobi optimizer log to this file.")
    run_all.add_argument("--no-strict-locks", action="store_true", help="Do not force FIX/adjust inherited locks.")
    run_all.add_argument("--no-eliminate-locks", action="store_true", help="Keep FIX/adjust locks inside the MILP instead of subtracting them from capacity.")
    run_all.add_argument("--use-activation-binaries", dest="use_activation_binaries", action="store_true")
    run_all.add_argument("--no-activation-binaries", dest="use_activation_binaries", action="store_false")
    run_all.set_defaults(use_activation_binaries=True)
    run_all.add_argument("--no-prefer-complete-demands", action="store_true")
    run_all.add_argument(
        "--fai-repair-iterations",
        type=int,
        default=1,
        help="Post-solve FAI repair iterations (default: 1).",
    )
    run_all.add_argument(
        "--enforce-fai-with-big-m",
        dest="enforce_fai_with_big_m",
        action="store_true",
        help="Big-M FAI precedence in MILP (default: on). Requires activation binaries.",
    )
    run_all.add_argument(
        "--no-enforce-fai-with-big-m",
        dest="enforce_fai_with_big_m",
        action="store_false",
        help="Disable Big-M FAI; use pruning + fai-repair only.",
    )
    run_all.set_defaults(enforce_fai_with_big_m=True)
    run_all.add_argument("--completion-upper", action="store_true")
    run_all.add_argument("--no-completion-upper", action="store_true", help=argparse.SUPPRESS)
    run_all.add_argument("--ots-buffer-days", type=int, default=2)
    run_all.add_argument("--fpsd-buffer-days", type=int, default=2)
    run_all.add_argument("--ship2-buffer-days", type=int, default=2)
    run_all.add_argument("--urgent-priority-boost", type=float, default=1.0)
    run_all.add_argument("--no-mr-exempt-ots", action="store_true")
    run_all.add_argument("--no-mr-exempt-fpsd", action="store_true")
    run_all.add_argument("--no-mr-exempt-ship2", action="store_true")

    args = parser.parse_args(argv)
    _configure_logging(args.log_file, args.log_level)
    logging.info("command=%s", args.command)

    if args.command == "preprocess":
        data = build_processed_data(args.input, _preprocess_config_from_args(args))
        data.save(args.output)
        _print_summary(data)
        logging.info("preprocess output=%s counts=%s", Path(args.output).resolve(), data.metadata.get("counts", {}))
        return 0

    if args.command == "solve":
        if args.input:
            data = build_processed_data(args.input, _preprocess_config_from_args(args))
        elif args.processed:
            data = load_processed_data(args.processed)
        else:
            parser.error("solve requires either --input or --processed")
        _print_summary(data)
        model, solution, summary = _solve_pipeline(data, args)
        _write_lock_diagnostics(model, Path(args.summary).resolve().parent if args.summary else Path(args.output).resolve().parent)
        if args.summary:
            _write_json(args.summary, summary)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        solution.to_csv(output, index=False, encoding="utf-8-sig")
        print(f"solution_rows={len(solution)}")
        print(f"solution={output.resolve()}")
        runtime_issues = summary.get("runtime_issues") or []
        if runtime_issues:
            print(f"runtime_issues: {len(runtime_issues)}")
            for issue in runtime_issues[:10]:
                print(f"  [{issue.get('level')}] {issue.get('where')}: {issue.get('message')}")
        logging.info("solution=%s rows=%s status=%s", output.resolve(), len(solution), summary.get("status"))
        return 0

    if args.command == "export-outputs":
        artifacts = build_export_artifacts(
            solution_csv=args.solution,
            processed_dir=args.processed,
            source_input_xlsx=args.source_input,
            config=ExportConfig(
                run_version=args.run_version,
                schedule_version=args.schedule_version,
                sub_schedule_version=args.sub_schedule_version,
                schedule_line_version=args.schedule_line_version,
                biz_type=args.biz_type,
                plant=args.plant,
                create_time=args.create_time,
            ),
        )
        paths = write_export_tables(artifacts, args.output_dir)
        for name, path in paths.items():
            print(f"{name}={path.resolve()}")
        logging.info("exported output tables=%s", {k: str(v.resolve()) for k, v in paths.items()})
        return 0

    if args.command == "run-all":
        data = build_processed_data(args.input, _preprocess_config_from_args(args))
        data.save(args.processed)
        _print_summary(data)
        logging.info("run-all preprocess output=%s counts=%s", Path(args.processed).resolve(), data.metadata.get("counts", {}))

        model, solution, summary = _solve_pipeline(data, args)
        _write_lock_diagnostics(model, Path(args.processed).resolve())
        solution_path = Path(args.solution)
        solution_path.parent.mkdir(parents=True, exist_ok=True)
        solution.to_csv(solution_path, index=False, encoding="utf-8-sig")

        artifacts = build_export_artifacts(
            solution_csv=solution_path,
            processed_dir=args.processed,
            source_input_xlsx=args.source_input or args.input,
            config=ExportConfig(
                run_version=args.run_version,
                schedule_version=args.schedule_version,
                sub_schedule_version=args.sub_schedule_version,
                schedule_line_version=args.schedule_line_version,
                biz_type=args.biz_type,
                plant=args.plant,
                create_time=args.create_time,
            ),
        )
        export_paths = write_export_tables(artifacts, args.output_dir)
        summary["exports"] = {name: str(path.resolve()) for name, path in export_paths.items()}
        summary["output_metrics"] = artifacts.summary
        if args.summary:
            _write_json(args.summary, summary)
        print(f"solution_rows={len(solution)}")
        print(f"solution={solution_path.resolve()}")
        for name, path in export_paths.items():
            print(f"{name}={path.resolve()}")
        runtime_issues = summary.get("runtime_issues") or []
        if runtime_issues:
            print(f"runtime_issues: {len(runtime_issues)}")
            for issue in runtime_issues[:10]:
                print(f"  [{issue.get('level')}] {issue.get('where')}: {issue.get('message')}")
        return 0

    return 2


def _configure_logging(log_file: str | None, log_level: str) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(path, encoding="utf-8"))
    logging.basicConfig(
        level=getattr(logging, log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=handlers,
        force=True,
    )


def _add_preprocess_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--schedule-version", default=None)
    parser.add_argument("--sub-schedule-version", default=None)
    parser.add_argument("--start-date", default=None, help="YYYY-MM-DD or datetime. Defaults to first calendar shift.")
    parser.add_argument("--horizon-days", type=int, default=None, help="Limit calendar horizon for development runs.")
    parser.add_argument("--max-demands", type=int, default=None, help="Take the first N demand_id after demand-level aggregation.")
    parser.add_argument(
        "--fai-lead-time-unit",
        choices=["minutes", "hours", "days"],
        default="minutes",
        help="Unit for aps_schedule_demand_fai_input.lead_time.",
    )
    parser.add_argument("--calendar-require-demand-flag", action="store_true")
    parser.add_argument("--due-buffer-days", type=int, default=3, help="Keep demand candidates through earliest due date plus this many days (v7_1 default: 3).")
    parser.add_argument("--ots-ext-days", type=int, default=3, help="OTS extension window days for KPI candidate retention (v7.5).")
    parser.add_argument("--fpsd-ext-days", type=int, default=3, help="FPSD extension window days for KPI candidate retention (v7.5).")
    parser.add_argument("--ship2-ext-days", type=int, default=3, help="ship_day_two extension window days for KPI candidate retention (v7.5).")
    parser.add_argument("--max-lines-per-demand-day", type=int, default=5, help="Keep at most this many candidate lines per demand per day (v7_1 default: 5).")
    parser.add_argument("--max-slots-per-demand", type=int, default=60, help="Keep at most this many candidate line-slot columns per demand (v7_1 default: 60).")
    parser.add_argument("--bucket-after-days", type=int, default=5, help="Collapse shifts after this many days into line-day buckets (v7_1 default: 5).")
    parser.add_argument(
        "--enable-fai-slot-buffer",
        action="store_true",
        help="Enable v7.6 slot-level FAI capacity reservation B_{lt}^{fai} in preprocessing.",
    )
    parser.add_argument(
        "--fai-buffer-cap-minutes",
        type=float,
        default=None,
        help="Optional upper cap (minutes) for per-(line,slot) FAI buffer.",
    )


def _preprocess_config_from_args(args: argparse.Namespace) -> PreprocessConfig:
    return PreprocessConfig(
        schedule_version=args.schedule_version,
        sub_schedule_version=args.sub_schedule_version,
        start_date=args.start_date,
        horizon_days=args.horizon_days,
        max_demands=args.max_demands,
        calendar_require_demand_flag=args.calendar_require_demand_flag,
        fai_lead_time_unit=args.fai_lead_time_unit,
        due_buffer_days=args.due_buffer_days,
        ots_ext_days=args.ots_ext_days,
        fpsd_ext_days=args.fpsd_ext_days,
        ship2_ext_days=args.ship2_ext_days,
        max_lines_per_demand_day=args.max_lines_per_demand_day,
        max_slots_per_demand=args.max_slots_per_demand,
        bucket_after_days=args.bucket_after_days,
        enable_fai_slot_buffer=getattr(args, "enable_fai_slot_buffer", False),
        fai_buffer_cap_minutes=getattr(args, "fai_buffer_cap_minutes", None),
    )


def _print_summary(data) -> None:
    print("metadata:")
    for key, value in data.metadata.get("counts", {}).items():
        print(f"  {key}: {value}")
    print(f"  kpi_mode: {data.metadata.get('kpi_mode')}")
    if len(data.issues):
        print(f"issues: {len(data.issues)}")
        for row in data.issues.head(10).itertuples(index=False):
            print(f"  [{row.level}] {row.where}: {row.message}")


def _model_config_from_args(args: argparse.Namespace) -> ModelConfig:
    return ModelConfig(
        time_limit=args.time_limit,
        mip_gap=args.mip_gap,
        threads=args.threads,
        gurobi_log_file=args.gurobi_log_file,
        strict_locks=not args.no_strict_locks,
        enforce_completion_upper=args.completion_upper and not args.no_completion_upper,
        eliminate_locks=not args.no_eliminate_locks,
        use_activation_binaries=args.use_activation_binaries,
        prefer_complete_demands=not args.no_prefer_complete_demands,
        enforce_fai_with_big_m=args.enforce_fai_with_big_m,
        ots_buffer_days=getattr(args, "ots_buffer_days", 2),
        fpsd_buffer_days=getattr(args, "fpsd_buffer_days", 2),
        ship2_buffer_days=getattr(args, "ship2_buffer_days", 2),
        urgent_priority_boost=getattr(args, "urgent_priority_boost", 1.0),
        exempt_mr_limited_from_ots=not getattr(args, "no_mr_exempt_ots", False),
        exempt_mr_limited_from_fpsd=not getattr(args, "no_mr_exempt_fpsd", False),
        exempt_mr_limited_from_ship2=not getattr(args, "no_mr_exempt_ship2", False),
    )


def _solve_pipeline(data, args: argparse.Namespace):
    model_config = _model_config_from_args(args)
    model, solution, summary = _solve_with_optional_fai_repair(data, model_config, max(args.fai_repair_iterations, 0))
    second_stage = run_second_stage(solution, data)
    summary["second_stage"] = second_stage.report
    return model, second_stage.solution, summary


def _write_lock_diagnostics(model, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    lock_balance = getattr(model, "_aps_lock_balance", None)
    if isinstance(lock_balance, pd.DataFrame) and len(lock_balance):
        lock_balance.to_csv(output_dir / "lock_balance.csv", index=False, encoding="utf-8-sig")
    lock_details = getattr(model, "_aps_lock_details", None)
    if isinstance(lock_details, pd.DataFrame) and len(lock_details):
        lock_details.to_csv(output_dir / "lock_details.csv", index=False, encoding="utf-8-sig")


def _solve_with_optional_fai_repair(data, model_config: ModelConfig, fai_repair_iterations: int):
    """Solve once, then optionally prune FAI-violating rest candidates and re-solve.

    This keeps the default model fast (no global FAI Big-M), but turns the
    previous post-solve FAI warning into a concrete second-pass repair.
    """

    repair_history: list[dict] = []
    max_iterations = 0 if model_config.enforce_fai_with_big_m else fai_repair_iterations
    model = None
    solution = None

    for iteration in range(max_iterations + 1):
        model = build_gurobi_model(data, model_config)
        model.optimize()
        solution = extract_solution(model, data)
        thresholds, violation_count = _fai_repair_thresholds(solution, data)
        if iteration >= max_iterations or not thresholds:
            break
        removed = _apply_fai_repair_thresholds(data, thresholds)
        repair_history.append(
            {
                "iteration": iteration + 1,
                "fai_violations_before_repair": int(violation_count),
                "rest_demands_repaired": int(len(thresholds)),
                "triples_removed": int(removed),
            }
        )
        logging.info(
            "fai repair iteration=%s violations=%s rest_demands=%s triples_removed=%s",
            iteration + 1,
            violation_count,
            len(thresholds),
            removed,
        )
        if removed == 0:
            break

    if model is None or solution is None:  # pragma: no cover - defensive
        raise RuntimeError("Solver did not run.")
    if repair_history:
        runtime_issues = getattr(model, "_aps_runtime_issues", []) or []
        for repair in repair_history:
            runtime_issues.append(
                {
                    "level": "info",
                    "where": "fai_repair",
                    "message": (
                        f"Iteration {repair['iteration']} pruned {repair['triples_removed']} triples "
                        f"for {repair['rest_demands_repaired']} rest demands after "
                        f"{repair['fai_violations_before_repair']} FAI violations."
                    ),
                }
            )
        model._aps_runtime_issues = runtime_issues
        model._aps_fai_repair_history = repair_history
    summary = _solver_summary(model, data)
    if repair_history:
        summary["fai_repair_history"] = repair_history
    return model, solution, summary


def _fai_repair_thresholds(solution: pd.DataFrame, data) -> tuple[dict[str, pd.Timestamp], int]:
    if solution.empty or data.fai_arcs.empty:
        return {}, 0
    sol = solution.copy()
    sol["shift_start_time"] = pd.to_datetime(sol["shift_start_time"], errors="coerce")
    sol["shift_end_time"] = pd.to_datetime(sol["shift_end_time"], errors="coerce")
    finish = sol.dropna(subset=["shift_end_time"]).groupby("demand_id")["shift_end_time"].max()
    start = sol.dropna(subset=["shift_start_time"]).groupby("demand_id")["shift_start_time"].min()

    thresholds: dict[str, pd.Timestamp] = {}
    violation_count = 0
    for arc in data.fai_arcs.itertuples(index=False):
        first_d = str(arc.first_demand_id)
        rest_d = str(arc.rest_demand_id)
        if first_d not in finish.index or rest_d not in start.index:
            continue
        required = pd.Timestamp(finish.loc[first_d]) + pd.Timedelta(hours=float(arc.lead_hours))
        if pd.Timestamp(start.loc[rest_d]) + pd.Timedelta(seconds=1) < required:
            violation_count += 1
            thresholds[rest_d] = max(thresholds.get(rest_d, pd.Timestamp.min), required)
    return thresholds, violation_count


def _apply_fai_repair_thresholds(data, thresholds: dict[str, pd.Timestamp]) -> int:
    if not thresholds or data.triples.empty:
        return 0
    triples = data.triples.copy()
    if "slot_id" not in triples.columns or "demand_id" not in triples.columns:
        logging.warning("FAI repair skipped because triples is missing required columns.")
        return 0
    slot_start = _slot_shift_start_map(data.slots)
    if slot_start:
        triples["_repair_shift_start_time"] = triples["slot_id"].astype(str).map(slot_start)
    elif "shift_start_time" in triples.columns:
        triples["_repair_shift_start_time"] = pd.to_datetime(triples["shift_start_time"], errors="coerce")
    else:
        logging.warning("FAI repair skipped because shift_start_time cannot be resolved from slots or triples.")
        return 0
    threshold_series = triples["demand_id"].astype(str).map(thresholds)
    keep = (
        threshold_series.isna()
        | triples["_repair_shift_start_time"].isna()
        | (triples["_repair_shift_start_time"] >= threshold_series)
    )
    repaired = triples[keep].drop(columns=["_repair_shift_start_time"], errors="ignore").reset_index(drop=True)
    removed = int(len(data.triples) - len(repaired))
    if removed > 0:
        data.triples = repaired
        counts = data.metadata.setdefault("counts", {})
        counts["triples"] = int(len(repaired))
        counts["fai_repair_removed_triples"] = int(counts.get("fai_repair_removed_triples", 0)) + removed
    return removed


def _slot_shift_start_map(slots: pd.DataFrame) -> dict[str, pd.Timestamp]:
    if slots.empty or "slot_id" not in slots.columns or "shift_start_time" not in slots.columns:
        return {}
    slot_start = slots[["slot_id", "shift_start_time"]].copy()
    slot_start["shift_start_time"] = pd.to_datetime(slot_start["shift_start_time"], errors="coerce")
    slot_start = slot_start.dropna(subset=["shift_start_time"]).drop_duplicates("slot_id")
    return slot_start.assign(slot_id=slot_start["slot_id"].astype(str)).set_index("slot_id")["shift_start_time"].to_dict()


def _solver_summary(model, data) -> dict:
    summary = {
        "status": int(model.Status),
        "runtime_seconds": float(getattr(model, "Runtime", 0.0)),
        "solution_count": int(getattr(model, "SolCount", 0)),
        "counts": data.metadata.get("counts", {}),
        "kpi_mode": data.metadata.get("kpi_mode"),
        "priority_settings": data.metadata.get("priority_settings", {}),
    }
    if summary["solution_count"] > 0:
        summary["objective_value"] = float(model.ObjVal)
        summary["mip_gap"] = float(getattr(model, "MIPGap", 0.0))
    runtime_issues = getattr(model, "_aps_runtime_issues", []) or []
    if runtime_issues:
        summary["runtime_issues"] = list(runtime_issues)
    lock_overview = getattr(model, "_aps_lock_overview", None)
    if isinstance(lock_overview, dict):
        summary["lock_overview"] = dict(lock_overview)
    return summary


def _write_json(path: str, payload: dict) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
