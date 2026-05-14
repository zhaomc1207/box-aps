"""Gurobi model construction for the BOX APS main MILP."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from .data import ProcessedData


@dataclass(slots=True)
class ModelConfig:
    omega_ots: float = 1.0
    omega_fpsd: float = 1.0
    omega_ship2: float = 1.0
    omega_unscheduled: float = 100.0
    line_preference_cost: float = 0.0
    non_cell_penalty_for_small_or_special: float = 1.0
    big_m: float | None = None
    time_limit: float | None = None
    mip_gap: float | None = None
    threads: int | None = None
    gurobi_log_file: str | None = None
    strict_locks: bool = True
    enforce_completion_upper: bool = False
    eliminate_locks: bool = True
    # v7_1: keep z[d,l,b] optional; full activation binaries made full-data
    # solutions harder without improving the observed business result.
    use_activation_binaries: bool = True
    prefer_complete_demands: bool = True
    enforce_fai_with_big_m: bool = True
    # v7_2: align the OTS/FPSD/ship_day_two delivery metric with the business
    # rule "OTS - schedule_date >= 2 days". A positive value means the schedule
    # must complete that many days BEFORE the due date to count as on-time.
    ots_buffer_days: int = 2
    fpsd_buffer_days: int = 2
    ship2_buffer_days: int = 2
    # v7_2: orders whose MR date is too close to the due date cannot logically
    # satisfy the buffer. Flag them as exempt so the metric is not over-pessimistic.
    exempt_mr_limited_from_ots: bool = True
    exempt_mr_limited_from_fpsd: bool = True
    exempt_mr_limited_from_ship2: bool = True
    # v7_2: rule 13.3 "Urgent Order priority". Multiplicative boost applied to
    # priority_weight when om_urgent is truthy. Default keeps urgent demands at
    # twice the configured weight.
    urgent_priority_boost: float = 1.0


def build_gurobi_model(data: ProcessedData, config: ModelConfig | None = None):
    """Build the main MILP model.

    The function imports ``gurobipy`` lazily, so preprocessing can run on
    machines without a Gurobi installation.
    """

    config = config or ModelConfig()
    try:
        import gurobipy as gp
        from gurobipy import GRB
    except ImportError as exc:
        raise RuntimeError(
            "gurobipy is not installed in this Python environment. "
            "Install Gurobi/gurobipy to build and solve the MILP; preprocessing can still be run."
        ) from exc

    demands = data.demands.copy()
    lines = data.lines.copy()
    slots = data.slots.copy()
    line_slots = data.line_slots.copy()
    triples = data.triples.copy()
    runtime_issues: list[dict[str, Any]] = []

    if triples.empty:
        raise ValueError("No eligible (demand, line, slot) triples were generated.")

    lock_details, lock_balance, lock_overview, lock_issues = _prepare_lock_diagnostics(
        demands=demands,
        fixed_locks=data.fixed_locks,
        adjust_locks=data.adjust_locks,
    )
    runtime_issues.extend(lock_issues)
    if config.strict_locks:
        _assert_lock_balance_feasible(lock_balance)
    locked_schedule = pd.DataFrame()
    if config.strict_locks and config.eliminate_locks:
        lock_active = lock_details[lock_details["active_lock_flag"].astype(int) == 1].copy() if len(lock_details) else pd.DataFrame()
        locked_schedule = _build_locked_schedule(data, triples, lock_active)
        if len(locked_schedule):
            _log_lock_uph_fallbacks(locked_schedule, runtime_issues)
            line_slots = _subtract_locked_capacity(line_slots, locked_schedule)
            demands = _apply_remaining_qty(demands, lock_balance)
            remaining_demands = set(demands["demand_id"].astype(str))
            triples = triples[triples["demand_id"].astype(str).isin(remaining_demands)].copy()
            data_fai_arcs = data.fai_arcs[
                data.fai_arcs["rest_demand_id"].astype(str).isin(remaining_demands)
            ].copy()
        else:
            data_fai_arcs = data.fai_arcs.copy()
    else:
        data_fai_arcs = data.fai_arcs.copy()

    if len(data_fai_arcs) and not config.enforce_fai_with_big_m:
        triples = _prune_fai_rest_candidates(triples, data_fai_arcs, slots, locked_schedule)

    demand_ids = demands["demand_id"].astype(str).tolist()
    triple_keys = [tuple(row) for row in triples[["demand_id", "line_id", "slot_id"]].astype(str).itertuples(index=False, name=None)]
    line_slot_keys = [tuple(row) for row in line_slots[["line_id", "slot_id"]].astype(str).itertuples(index=False, name=None)]

    demand_qty = demands.set_index("demand_id")["qty"].astype(float).to_dict()
    base_priority_weight = demands.set_index("demand_id")["priority_weight"].astype(float).to_dict()
    # v7_2: rule 13.3 "Urgent Order priority". Multiplicative boost on top of
    # the base priority weight; default boost=1.0 doubles weight when urgent.
    urgent_flag = (
        demands.set_index("demand_id").get("urgent", pd.Series(0, index=demands["demand_id"]))
        .astype(int)
        .to_dict()
    )
    priority_weight = {
        d: base_priority_weight[d] * (1.0 + float(config.urgent_priority_boost) * urgent_flag.get(d, 0))
        for d in base_priority_weight
    }
    slot_start = slots.set_index("slot_id")["start_hour"].astype(float).to_dict()
    slot_end = slots.set_index("slot_id")["end_hour"].astype(float).to_dict()
    slot_rank = slots.set_index("slot_id")["slot_rank"].astype(int).to_dict()
    avail = line_slots.set_index(["line_id", "slot_id"])["avail_hours"].astype(float).to_dict()
    uph = triples.set_index(["demand_id", "line_id", "slot_id"])["uph"].astype(float).to_dict()
    elig = triples.set_index(["demand_id", "line_id", "slot_id"])["elig"].astype(int).to_dict()
    line_cell = lines.set_index("line_id")["cell_flag"].astype(int).to_dict()
    ct_min = data.change_min.set_index("line_id")["ct_min_hours"].astype(float).to_dict() if len(data.change_min) else {}
    demand_special = (
        demands.assign(_special=demands.get("fast_ship", 0).astype(int) | demands.get("cust_svc", 0).astype(int))
        .set_index("demand_id")["_special"]
        .astype(int)
        .to_dict()
    )
    line_cost = {
        key: config.line_preference_cost
        + config.non_cell_penalty_for_small_or_special
        * int(demand_special.get(key[0], 0))
        * (1 - int(line_cell.get(key[1], 0)))
        for key in triple_keys
    }

    triples_by_d = _group_keys(triple_keys, 0)
    triples_by_line_slot = _group_keys(triple_keys, (1, 2))
    triples_by_d_slot = _group_keys(triple_keys, (0, 2))
    models_by_line_slot, triples_by_line_slot_model = _build_model_groups(triples, demands)
    max_end = max(slot_end.values()) if slot_end else 0.0
    big_m = config.big_m if config.big_m is not None else max(max_end + 24.0, 24.0)
    kpi_mode = data.metadata.get("kpi_mode", "qtymax")

    model = gp.Model("box_aps_main_milp")
    if config.time_limit is not None:
        model.Params.TimeLimit = config.time_limit
    if config.mip_gap is not None:
        model.Params.MIPGap = config.mip_gap
    if config.threads is not None:
        model.Params.Threads = config.threads
    if config.gurobi_log_file:
        model.Params.LogFile = config.gurobi_log_file

    x = model.addVars(triple_keys, vtype=GRB.INTEGER, lb=0.0, name="x")
    z = model.addVars(triple_keys, vtype=GRB.BINARY, name="z") if config.use_activation_binaries else {}
    needs_completion_flag = kpi_mode == "ordermax" or config.prefer_complete_demands
    u = model.addVars(demand_ids, vtype=GRB.BINARY, name="u") if needs_completion_flag else {}
    c = model.addVars(demand_ids, vtype=GRB.INTEGER, lb=0.0, name="c")
    miss_ots = model.addVars(demand_ids, vtype=GRB.CONTINUOUS, lb=0.0, name="miss_ots")
    miss_fpsd = model.addVars(demand_ids, vtype=GRB.CONTINUOUS, lb=0.0, name="miss_fpsd")
    miss_ship2 = model.addVars(demand_ids, vtype=GRB.CONTINUOUS, lb=0.0, name="miss_ship2")
    h = model.addVars(line_slot_keys, vtype=GRB.INTEGER, lb=0.0, name="h")
    setup = model.addVars(line_slot_keys, vtype=GRB.CONTINUOUS, lb=0.0, name="setup")
    g_keys = sorted(models_by_line_slot)
    g = model.addVars(g_keys, vtype=GRB.BINARY, name="g")

    # 8.1 demand balance
    for d in demand_ids:
        model.addConstr(gp.quicksum(x[key] for key in triples_by_d.get(d, [])) + c[d] == demand_qty[d], name=f"demand_balance[{d}]")

    # 8.2 activation linkage and 8.6 sparse feasibility
    for key in triple_keys:
        d = key[0]
        if config.use_activation_binaries:
            model.addConstr(x[key] <= demand_qty[d] * z[key], name=f"activate_ub[{_key_name(key)}]")
            model.addConstr(x[key] >= z[key], name=f"activate_lb[{_key_name(key)}]")
        model.addConstr(x[key] <= demand_qty[d] * int(elig.get(key, 0)), name=f"elig[{_key_name(key)}]")

    # 8.3 full completion flag. In qtymax mode v7_1 still creates this
    # lightweight demand-level binary so the solver prefers complete demands
    # after it has optimized delivered/unscheduled quantity.
    if needs_completion_flag:
        for d in demand_ids:
            scheduled = gp.quicksum(x[key] for key in triples_by_d.get(d, []))
            q = demand_qty[d]
            model.addConstr(scheduled >= q * u[d], name=f"complete_lb[{d}]")
            if q >= 1:
                model.addConstr(scheduled <= q - (1 - u[d]), name=f"complete_ub[{d}]")

    # 8.4 same demand and same slot can use at most one line.
    if config.use_activation_binaries:
        for (d, slot), keys in triples_by_d_slot.items():
            model.addConstr(gp.quicksum(z[key] for key in keys) <= 1, name=f"one_line_per_slot[{d}|{slot}]")

    # 8.5 line/shift capacity.
    for key in line_slot_keys:
        lhs = gp.quicksum(x[t] / uph[t] for t in triples_by_line_slot.get(key, []) if uph.get(t, 0.0) > 0)
        model.addConstr(lhs + setup[key] <= float(avail.get(key, 0.0)), name=f"capacity[{_key_name(key)}]")

    # 8.8 delivery miss quantities.
    due_sets = _build_due_sets(
        data,
        ots_buffer_days=config.ots_buffer_days,
        fpsd_buffer_days=config.fpsd_buffer_days,
        ship2_buffer_days=config.ship2_buffer_days,
    )
    for d in demand_ids:
        keys = triples_by_d.get(d, [])
        model.addConstr(
            miss_ots[d] >= demand_qty[d] - gp.quicksum(x[key] for key in keys if key[2] in due_sets["ots"].get(d, set())),
            name=f"miss_ots[{d}]",
        )
        model.addConstr(
            miss_fpsd[d] >= demand_qty[d] - gp.quicksum(x[key] for key in keys if key[2] in due_sets["fpsd"].get(d, set())),
            name=f"miss_fpsd[{d}]",
        )
        model.addConstr(
            miss_ship2[d] >= demand_qty[d] - gp.quicksum(x[key] for key in keys if key[2] in due_sets["ship2"].get(d, set())),
            name=f"miss_ship2[{d}]",
        )

    if config.strict_locks and not config.eliminate_locks:
        lock_active = lock_details[lock_details["active_lock_flag"].astype(int) == 1].copy() if len(lock_details) else pd.DataFrame()
        _add_lock_constraints(model, x, triples_by_d, lock_active, "locks")

    # 8.11 FAI first/rest precedence.
    if config.enforce_fai_with_big_m and config.use_activation_binaries:
        e = model.addVars(demand_ids, vtype=GRB.CONTINUOUS, lb=0.0, name="e")
        for d in demand_ids:
            for key in sorted(triples_by_d.get(d, []), key=lambda k: slot_rank[k[2]]):
                model.addConstr(e[d] >= float(slot_end[key[2]]) - big_m * (1 - z[key]), name=f"completion_lb[{_key_name(key)}]")
        for arc in data_fai_arcs.itertuples(index=False):
            first_d = str(arc.first_demand_id)
            rest_d = str(arc.rest_demand_id)
            if first_d not in demand_qty or rest_d not in demand_qty:
                continue
            for key in triples_by_d.get(rest_d, []):
                model.addConstr(
                    float(slot_start[key[2]]) + big_m * (1 - z[key]) >= e[first_d] + float(arc.lead_hours),
                    name=f"fai[{arc.group_id}|{first_d}|{_key_name(key)}]",
                )
    else:
        e = {}

    # 8.12 model appearance linkage.
    for g_key in g_keys:
        line_id, model_name, slot_id = g_key
        keys = triples_by_line_slot_model.get(g_key, [])
        if not keys:
            continue
        if config.use_activation_binaries:
            model.addConstr(gp.quicksum(z[key] for key in keys) <= len(keys) * g[g_key], name=f"model_on_ub[{_key_name(g_key)}]")
            model.addConstr(g[g_key] <= gp.quicksum(z[key] for key in keys), name=f"model_on_lb[{_key_name(g_key)}]")
        else:
            total_qty = sum(float(demand_qty.get(key[0], 0.0)) for key in keys)
            model.addConstr(gp.quicksum(x[key] for key in keys) <= max(total_qty, 1.0) * g[g_key], name=f"model_on_ub[{_key_name(g_key)}]")
            model.addConstr(g[g_key] <= gp.quicksum(x[key] for key in keys), name=f"model_on_lb[{_key_name(g_key)}]")

    # 8.13 and 8.14 rough changeover lower bound.
    for line_id, slot_id in line_slot_keys:
        present_models = [model_name for l, model_name, s in g_keys if l == line_id and s == slot_id]
        model.addConstr(h[(line_id, slot_id)] >= gp.quicksum(g[(line_id, m, slot_id)] for m in present_models) - 1, name=f"change_count_lb[{line_id}|{slot_id}]")
        model.addConstr(setup[(line_id, slot_id)] >= float(ct_min.get(line_id, 0.0)) * h[(line_id, slot_id)], name=f"setup_lb[{line_id}|{slot_id}]")

    kappa_ots = _date_kappa(
        demands,
        "ots_date_dt",
        buffer_days=config.ots_buffer_days,
        exempt_mr_limited=config.exempt_mr_limited_from_ots,
    )
    kappa_fpsd = _date_kappa(
        demands,
        "fpsd_dt",
        buffer_days=config.fpsd_buffer_days,
        exempt_mr_limited=config.exempt_mr_limited_from_fpsd,
    )
    kappa_ship2 = _date_kappa(
        demands,
        "ship_day_two_dt",
        buffer_days=config.ship2_buffer_days,
        exempt_mr_limited=config.exempt_mr_limited_from_ship2,
    )
    obj1 = gp.quicksum(
        priority_weight[d]
        * (
            config.omega_ots * kappa_ots.get(d, 0) * miss_ots[d]
            + config.omega_fpsd * kappa_fpsd.get(d, 0) * miss_fpsd[d]
            + config.omega_ship2 * kappa_ship2.get(d, 0) * miss_ship2[d]
            + config.omega_unscheduled * c[d]
        )
        for d in demand_ids
    )
    obj2 = gp.quicksum(c[d] for d in demand_ids) if kpi_mode == "qtymax" else -gp.quicksum(u[d] for d in demand_ids)
    obj_complete = -gp.quicksum(u[d] for d in demand_ids) if config.prefer_complete_demands and kpi_mode == "qtymax" else None
    obj3 = gp.quicksum(line_cost[key] * x[key] for key in triple_keys)
    obj4 = gp.quicksum(setup[key] for key in line_slot_keys) + gp.quicksum(g[key] for key in g_keys)

    model.ModelSense = GRB.MINIMIZE
    model.setObjectiveN(obj1, index=0, priority=5, name="delivery_priority")
    model.setObjectiveN(obj2, index=1, priority=4, name="kpi_mode")
    if obj_complete is not None:
        model.setObjectiveN(obj_complete, index=2, priority=3, name="complete_demands")
        model.setObjectiveN(obj3, index=3, priority=2, name="line_cell_preference")
        model.setObjectiveN(obj4, index=4, priority=1, name="rough_efficiency")
    else:
        model.setObjectiveN(obj3, index=2, priority=2, name="line_cell_preference")
        model.setObjectiveN(obj4, index=3, priority=1, name="rough_efficiency")

    model._aps_data = data
    model._aps_vars = {
        "x": x,
        "z": z,
        "u": u,
        "c": c,
        "e": e,
        "miss_ots": miss_ots,
        "miss_fpsd": miss_fpsd,
        "miss_ship2": miss_ship2,
        "g": g,
        "h": h,
        "setup": setup,
    }
    lock_balance_out = lock_balance.copy()
    lock_balance_out["over_locked_flag"] = (
        pd.to_numeric(lock_balance_out["locked_qty_total"], errors="coerce").fillna(0.0)
        > pd.to_numeric(lock_balance_out["original_qty"], errors="coerce").fillna(0.0) + 1e-6
    ).astype(int)
    lock_details_out = lock_details.copy()
    if len(lock_details_out):
        occ = {}
        if len(locked_schedule):
            occ = locked_schedule.set_index(["demand_id", "line_id", "slot_id", "source", "seq"])["occupied_hours"].astype(float).to_dict()
        lock_details_out["occupied_hours"] = [
            float(occ.get((str(r.demand_id), str(r.line_id), str(r.slot_id), str(r.source), int(r.seq)), 0.0))
            for r in lock_details_out.itertuples(index=False)
        ]
        lock_details_out = lock_details_out.merge(
            lock_balance_out[["demand_id", "original_qty", "locked_qty_total", "remaining_qty"]],
            on="demand_id",
            how="left",
        )
    model._aps_locked_schedule = locked_schedule
    model._aps_lock_balance = lock_balance_out
    model._aps_lock_details = lock_details_out
    model._aps_lock_overview = lock_overview
    model._aps_data_fai_arcs = data_fai_arcs
    model._aps_runtime_issues = runtime_issues
    model._aps_config = config
    return model


def extract_solution(model, data: ProcessedData | None = None, min_qty: float = 1e-6) -> pd.DataFrame:
    """Extract positive schedule quantities from a solved model."""

    try:
        from gurobipy import GRB
    except ImportError as exc:
        raise RuntimeError("gurobipy is required to extract a Gurobi solution.") from exc

    data = data or getattr(model, "_aps_data", None)
    if data is None:
        raise ValueError("ProcessedData was not attached to the model.")
    if model.Status not in {GRB.OPTIMAL, GRB.SUBOPTIMAL, GRB.TIME_LIMIT, GRB.INTERRUPTED}:
        raise ValueError(f"Model has no extractable incumbent solution; status={model.Status}.")

    x = model._aps_vars["x"]
    triples_uph = data.triples.set_index(["demand_id", "line_id", "slot_id"])["uph"].astype(float).to_dict() if len(data.triples) else {}
    rows = []
    for key, var in x.items():
        if var.X > min_qty:
            d, line_id, slot_id = key
            rows.append(
                {
                    "demand_id": d,
                    "line_id": line_id,
                    "slot_id": slot_id,
                    "schedule_qty": var.X,
                    "source": "milp",
                    "uph": float(triples_uph.get((str(d), str(line_id), str(slot_id)), 0.0) or 0.0),
                }
            )
    locked_schedule = getattr(model, "_aps_locked_schedule", pd.DataFrame())
    if isinstance(locked_schedule, pd.DataFrame) and len(locked_schedule):
        for row in locked_schedule.itertuples(index=False):
            rows.append(
                {
                    "demand_id": str(row.demand_id),
                    "line_id": str(row.line_id),
                    "slot_id": str(row.slot_id),
                    "schedule_qty": float(row.schedule_qty),
                    "source": str(row.source),
                    "uph": float(getattr(row, "uph", 0.0) or 0.0),
                }
            )
    if not rows:
        return pd.DataFrame(columns=["demand_id", "line_id", "slot_id", "schedule_qty", "source", "uph"])
    result = pd.DataFrame(rows)
    result = result.merge(data.slots[["slot_id", "day", "shift_seq", "shift_start_time", "shift_end_time"]], on="slot_id", how="left")
    result = result.merge(data.lines[["line_id", "line"]], on="line_id", how="left")
    result = _expand_merged_solution_rows(result, data)
    demand_lookup = data.raw_demands if len(data.raw_demands) else data.demands
    result = result.merge(
        demand_lookup[[c for c in ["demand_id", "pn", "model", "mcode", "qty", "priority_rank", "mo", "lot"] if c in demand_lookup.columns]],
        on="demand_id",
        how="left",
    )
    result = _sequence_solution_rows(result, data)
    final = result.sort_values(["shift_start_time", "line", "sequence", "demand_id"]).reset_index(drop=True)

    # v7_1: post-solve consistency and FAI checks (observability only).
    runtime_issues = getattr(model, "_aps_runtime_issues", [])
    _post_solve_consistency_checks(final, model, data, runtime_issues)
    _post_solve_fai_check(final, model, data, runtime_issues)
    model._aps_runtime_issues = runtime_issues
    return final


def _expand_merged_solution_rows(result: pd.DataFrame, data: ProcessedData) -> pd.DataFrame:
    if result.empty or data.merge_map.empty:
        return result
    merge_map = data.merge_map.copy()
    if not {"raw_demand_id", "merged_demand_id", "merge_applied", "member_rank", "raw_qty"}.issubset(merge_map.columns):
        return result

    merge_map["merge_applied"] = pd.to_numeric(merge_map["merge_applied"], errors="coerce").fillna(0).astype(int)
    merge_map["member_rank"] = pd.to_numeric(merge_map["member_rank"], errors="coerce").fillna(0).astype(int)
    merge_map["raw_qty"] = pd.to_numeric(merge_map["raw_qty"], errors="coerce").fillna(0.0)
    applied = merge_map[merge_map["merge_applied"] > 0].copy()
    if applied.empty:
        return result

    member_groups = {
        merged_id: group.sort_values(["member_rank", "raw_demand_id"]).reset_index(drop=True)
        for merged_id, group in applied.groupby("merged_demand_id", sort=False)
    }

    out_rows: list[dict[str, Any]] = []
    sortable = result.copy()
    sortable["_sort_shift_start"] = pd.to_datetime(sortable.get("shift_start_time"), errors="coerce")
    sortable["_sort_schedule_qty"] = pd.to_numeric(sortable.get("schedule_qty", 0), errors="coerce").fillna(0.0)
    sortable["_row_order"] = range(len(sortable))

    for demand_id, group in sortable.groupby("demand_id", sort=False):
        members = member_groups.get(str(demand_id))
        if members is None:
            out_rows.extend(group.drop(columns=["_sort_shift_start", "_sort_schedule_qty", "_row_order"], errors="ignore").to_dict("records"))
            continue

        member_state = [
            {
                "raw_demand_id": str(row.raw_demand_id),
                "remaining_qty": float(row.raw_qty),
            }
            for row in members.itertuples(index=False)
        ]
        member_idx = 0
        ordered_group = group.sort_values(["_sort_shift_start", "line_id", "slot_id", "_row_order"])
        for row in ordered_group.to_dict("records"):
            qty_left = float(row.get("schedule_qty", 0.0) or 0.0)
            while qty_left > 1e-6 and member_idx < len(member_state):
                member = member_state[member_idx]
                alloc = min(qty_left, member["remaining_qty"])
                if alloc <= 1e-6:
                    member_idx += 1
                    continue
                new_row = dict(row)
                new_row["merged_demand_id"] = str(demand_id)
                new_row["demand_id"] = member["raw_demand_id"]
                new_row["schedule_qty"] = alloc
                out_rows.append(new_row)
                qty_left -= alloc
                member["remaining_qty"] -= alloc
                if member["remaining_qty"] <= 1e-6:
                    member_idx += 1
            if qty_left > 1e-6 and member_state:
                fallback = dict(row)
                fallback["merged_demand_id"] = str(demand_id)
                fallback["demand_id"] = member_state[-1]["raw_demand_id"]
                fallback["schedule_qty"] = qty_left
                out_rows.append(fallback)

    expanded = pd.DataFrame(out_rows)
    return expanded.drop(columns=["_sort_shift_start", "_sort_schedule_qty", "_row_order"], errors="ignore")


def _build_locked_schedule(data: ProcessedData, triples: pd.DataFrame, lock_rows: pd.DataFrame | None = None) -> pd.DataFrame:
    if lock_rows is None:
        locks = []
        for source, frame in [("fix", data.fixed_locks), ("adjust", data.adjust_locks)]:
            if frame.empty:
                continue
            tmp = frame.copy()
            tmp["source"] = source
            locks.append(tmp)
        lock_rows = pd.concat(locks, ignore_index=True) if locks else pd.DataFrame()
    if lock_rows is None or lock_rows.empty:
        return pd.DataFrame(columns=["demand_id", "line_id", "slot_id", "schedule_qty", "uph", "occupied_hours", "source", "seq"])
    source_rank = {"fix": 0, "adjust": 1}
    lock_rows = lock_rows.copy()
    lock_rows["_source_rank"] = lock_rows.get("source", pd.Series("", index=lock_rows.index)).map(source_rank).fillna(9)
    lock_rows = lock_rows.sort_values(["demand_id", "_source_rank", "seq"])
    triples_uph = triples.set_index(["demand_id", "line_id", "slot_id"])["uph"].astype(float).to_dict()
    # v7_1: build multi-level UPH fallbacks so locked occupation is rarely zero.
    uph_by_demand_line, uph_by_demand = _build_lock_uph_fallbacks(triples)
    demand_model = data.demands.set_index("demand_id")["model"].astype(str).to_dict() if len(data.demands) else {}
    rows = []
    for row in lock_rows.itertuples(index=False):
        key = (str(row.demand_id), str(row.line_id), str(row.slot_id))
        qty = float(getattr(row, "lock_qty", 0.0) or 0.0)
        if qty <= 0.0:
            continue
        matched_uph = float(triples_uph.get(key, 0.0) or 0.0)
        uph_source = "exact"
        if matched_uph <= 0.0:
            fallback = uph_by_demand_line.get((key[0], key[1]), 0.0)
            if fallback > 0.0:
                matched_uph = float(fallback)
                uph_source = "demand_line"
        if matched_uph <= 0.0:
            fallback = uph_by_demand.get(key[0], 0.0)
            if fallback > 0.0:
                matched_uph = float(fallback)
                uph_source = "demand"
        if matched_uph <= 0.0:
            # No fallback worked. Fall back to v7 behaviour but flag aggressively.
            uph_source = "missing"
        occupied_hours = qty / matched_uph if matched_uph > 0.0 else 0.0
        rows.append(
            {
                "demand_id": key[0],
                "line_id": key[1],
                "slot_id": key[2],
                "schedule_qty": qty,
                "uph": matched_uph,
                "occupied_hours": occupied_hours,
                "source": str(row.source),
                "seq": int(getattr(row, "seq", 0) or 0),
                "uph_source": uph_source,
                "model": demand_model.get(key[0], ""),
                "lock_id": str(getattr(row, "lock_id", "") or ""),
                "source_row_id": str(getattr(row, "source_row_id", "") or ""),
            }
        )
    return pd.DataFrame(
        rows,
        columns=[
            "demand_id",
            "line_id",
            "slot_id",
            "schedule_qty",
            "uph",
            "occupied_hours",
            "source",
            "seq",
            "uph_source",
            "model",
            "lock_id",
            "source_row_id",
        ],
    )


def _build_lock_uph_fallbacks(triples: pd.DataFrame) -> tuple[dict[tuple[str, str], float], dict[str, float]]:
    """Build (demand, line) and (demand) -> best UPH fallback maps.

    Used when a locked (demand, line, slot) is not present in the pruned triples
    table so that occupied capacity is still estimated from a reasonable UPH
    rather than defaulting to zero.
    """
    if triples.empty:
        return {}, {}
    if "uph" not in triples.columns:
        return {}, {}
    by_demand_line_series = (
        triples.assign(uph=pd.to_numeric(triples["uph"], errors="coerce").fillna(0.0))
        .groupby(["demand_id", "line_id"])["uph"]
        .max()
    )
    by_demand_line = {
        (str(d), str(l)): float(v)
        for (d, l), v in by_demand_line_series.items()
        if float(v) > 0.0
    }
    by_demand_series = (
        triples.assign(uph=pd.to_numeric(triples["uph"], errors="coerce").fillna(0.0))
        .groupby("demand_id")["uph"]
        .max()
    )
    by_demand = {str(d): float(v) for d, v in by_demand_series.items() if float(v) > 0.0}
    return by_demand_line, by_demand


def _subtract_locked_capacity(line_slots: pd.DataFrame, locked_schedule: pd.DataFrame) -> pd.DataFrame:
    if locked_schedule.empty:
        return line_slots
    occupied = locked_schedule.groupby(["line_id", "slot_id"], as_index=False)["occupied_hours"].sum()
    out = line_slots.copy()
    out = out.merge(occupied.rename(columns={"occupied_hours": "_locked_hours"}), on=["line_id", "slot_id"], how="left")
    out["_locked_hours"] = out["_locked_hours"].fillna(0.0)
    out["occupied_hours"] = out.get("occupied_hours", 0.0).astype(float) + out["_locked_hours"]
    out["avail_hours"] = (out["avail_hours"].astype(float) - out["_locked_hours"]).clip(lower=0.0)
    return out.drop(columns=["_locked_hours"])


def _prune_fai_rest_candidates(
    triples: pd.DataFrame,
    fai_arcs: pd.DataFrame,
    slots: pd.DataFrame,
    locked_schedule: pd.DataFrame,
) -> pd.DataFrame:
    if triples.empty or fai_arcs.empty:
        return triples
    slot_start = slots.set_index("slot_id")["start_hour"].astype(float).to_dict()
    slot_end = slots.set_index("slot_id")["end_hour"].astype(float).to_dict()
    first_finish: dict[str, float] = {}
    if len(locked_schedule):
        for row in locked_schedule.itertuples(index=False):
            end = slot_end.get(str(row.slot_id))
            if end is not None:
                first_finish[str(row.demand_id)] = min(float(end), first_finish.get(str(row.demand_id), float("inf")))
    for first_d, group in triples.groupby("demand_id"):
        ends = [float(slot_end[s]) for s in group["slot_id"].astype(str) if s in slot_end]
        if ends:
            first_finish[str(first_d)] = min(min(ends), first_finish.get(str(first_d), float("inf")))
    thresholds: dict[str, float] = {}
    for arc in fai_arcs.itertuples(index=False):
        finish = first_finish.get(str(arc.first_demand_id))
        if finish is None:
            continue
        rest = str(arc.rest_demand_id)
        threshold = finish + float(arc.lead_hours)
        thresholds[rest] = max(thresholds.get(rest, 0.0), threshold)
    if not thresholds:
        return triples
    out = triples.copy()
    out["_slot_start"] = out["slot_id"].astype(str).map(slot_start)
    rest_threshold = out["demand_id"].astype(str).map(thresholds)
    keep = rest_threshold.isna() | out["_slot_start"].isna() | (out["_slot_start"] >= rest_threshold)
    return out[keep].drop(columns=["_slot_start"]).reset_index(drop=True)


def _sequence_solution_rows(result: pd.DataFrame, data: ProcessedData) -> pd.DataFrame:
    """Local line-slot sequencing heuristic for reporting and downstream repair."""

    if result.empty:
        result["sequence"] = []
        return result
    out = result.copy()
    fixed = data.fixed_locks.assign(_lock_source="fix") if len(data.fixed_locks) else pd.DataFrame()
    adjust = data.adjust_locks.assign(_lock_source="adjust") if len(data.adjust_locks) else pd.DataFrame()
    locks = pd.concat([fixed, adjust], ignore_index=True) if len(fixed) or len(adjust) else pd.DataFrame()
    if len(locks):
        locks = locks[["demand_id", "line_id", "slot_id", "seq", "_lock_source"]]
        out = out.merge(locks, on=["demand_id", "line_id", "slot_id"], how="left")
    else:
        out["seq"] = pd.NA
        out["_lock_source"] = pd.NA
    sort_cols = ["line_id", "slot_id", "_locked_first", "_seq_sort", "lot", "mo", "model", "demand_id"]
    out["_locked_first"] = out["seq"].notna().astype(int)
    out["_seq_sort"] = pd.to_numeric(out["seq"], errors="coerce").fillna(10**9)
    for col in ["lot", "mo", "model"]:
        if col not in out.columns:
            out[col] = ""
    out = out.sort_values(sort_cols, ascending=[True, True, False, True, True, True, True, True])
    out["sequence"] = out.groupby(["line_id", "slot_id"]).cumcount() + 1
    return out.drop(columns=["_locked_first", "_seq_sort", "_lock_source"], errors="ignore")


def _group_keys(keys: list[tuple[str, str, str]], index: int | tuple[int, ...]) -> dict[Any, list[tuple[str, str, str]]]:
    grouped: dict[Any, list[tuple[str, str, str]]] = {}
    for key in keys:
        group_key = key[index] if isinstance(index, int) else tuple(key[i] for i in index)
        grouped.setdefault(group_key, []).append(key)
    return grouped


def _build_model_groups(triples: pd.DataFrame, demands: pd.DataFrame):
    demand_model = demands.set_index("demand_id")["model"].astype(str).to_dict()
    models_by_line_slot: set[tuple[str, str, str]] = set()
    triples_by_group: dict[tuple[str, str, str], list[tuple[str, str, str]]] = {}
    for row in triples[["demand_id", "line_id", "slot_id"]].astype(str).itertuples(index=False):
        model_name = demand_model.get(row.demand_id, "")
        key = (row.line_id, model_name, row.slot_id)
        triple = (row.demand_id, row.line_id, row.slot_id)
        models_by_line_slot.add(key)
        triples_by_group.setdefault(key, []).append(triple)
    return models_by_line_slot, triples_by_group


def _build_due_sets(
    data: ProcessedData,
    ots_buffer_days: int = 2,
    fpsd_buffer_days: int = 2,
    ship2_buffer_days: int = 2,
) -> dict[str, dict[str, set[str]]]:
    """Slots that count as "on-time" per delivery KPI.

    The business rule (BOX-智能排产约束规则.xlsx, rule 13.1/13.2/13.4) requires
    `due_date - schedule_date >= buffer_days`. We therefore consider a candidate
    slot on-time only when its shift completes at least ``buffer_days`` calendar
    days before the due date. The slot end is compared against the START of
    ``due_date - buffer_days``.
    """
    slots = data.slots.copy()
    slots["shift_end_time"] = pd.to_datetime(slots["shift_end_time"], errors="coerce")
    slot_end = slots.set_index("slot_id")["shift_end_time"].to_dict()
    buffers = {"ots": int(ots_buffer_days), "fpsd": int(fpsd_buffer_days), "ship2": int(ship2_buffer_days)}
    cols = {"ots": "ots_date_dt", "fpsd": "fpsd_dt", "ship2": "ship_day_two_dt"}
    result: dict[str, dict[str, set[str]]] = {"ots": {}, "fpsd": {}, "ship2": {}}
    for d in data.demands.itertuples(index=False):
        for name, attr in cols.items():
            due = getattr(d, attr, pd.NaT)
            if pd.isna(due):
                # No due date -> all slots eligible (KPI not gated).
                result[name][d.demand_id] = set(slot_end)
                continue
            buffer_days = buffers[name]
            cutoff = pd.Timestamp(due).normalize() - pd.Timedelta(days=int(buffer_days))
            result[name][d.demand_id] = {
                slot for slot, end in slot_end.items() if pd.notna(end) and end <= cutoff
            }
    return result


def _date_kappa(
    demands: pd.DataFrame,
    col: str,
    buffer_days: int = 0,
    exempt_mr_limited: bool = False,
) -> dict[str, int]:
    """KPI participation flag for each demand.

    A demand contributes to a delivery KPI only when:
    1. It has the corresponding due date set, and
    2. Its MR date does not force a schedule that necessarily violates the
       ``due_date - buffer_days`` rule (rule 13.1/13.2 "MR Day限制的订单除外").
    """
    out: dict[str, int] = {}
    needed = ["demand_id", col]
    if exempt_mr_limited and "mr_day_dt" in demands.columns:
        needed.append("mr_day_dt")
    available = [c for c in needed if c in demands.columns]
    for row in demands[available].itertuples(index=False):
        due = getattr(row, col, pd.NaT)
        if pd.isna(due):
            out[row.demand_id] = 0
            continue
        if exempt_mr_limited and hasattr(row, "mr_day_dt"):
            mr = getattr(row, "mr_day_dt", pd.NaT)
            if pd.notna(mr):
                cutoff = pd.Timestamp(due).normalize() - pd.Timedelta(days=int(buffer_days))
                if pd.Timestamp(mr).normalize() > cutoff:
                    out[row.demand_id] = 0
                    continue
        out[row.demand_id] = 1
    return out


def _add_lock_constraints(model, x, triples_by_d, locks: pd.DataFrame, label: str) -> None:
    if locks.empty:
        return
    for row in locks.itertuples(index=False):
        target = (str(row.demand_id), str(row.line_id), str(row.slot_id))
        if target not in triples_by_d.get(str(row.demand_id), []):
            continue
        lock_qty = float(getattr(row, "lock_qty", 0.0) or 0.0)
        if lock_qty <= 0.0:
            continue
        model.addConstr(x[target] >= lock_qty, name=f"{label}_lb[{_key_name(target)}]")


def _prepare_lock_diagnostics(
    demands: pd.DataFrame,
    fixed_locks: pd.DataFrame,
    adjust_locks: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, float], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    demand_qty = demands.set_index("demand_id")["qty"].astype(float).to_dict() if len(demands) else {}
    frames: list[pd.DataFrame] = []
    for source, frame in [("fix", fixed_locks), ("adjust", adjust_locks)]:
        if frame.empty:
            continue
        tmp = frame.copy()
        for col in ["lock_id", "source_row_id", "shift_date", "shift", "seq"]:
            if col not in tmp.columns:
                tmp[col] = ""
        tmp["source"] = source
        for col in ["demand_id", "line_id", "slot_id", "lock_id", "source_row_id", "shift_date", "shift"]:
            if col in tmp.columns:
                tmp[col] = tmp[col].fillna("").astype(str).str.strip()
        tmp["seq"] = pd.to_numeric(tmp["seq"], errors="coerce").fillna(10**9).astype(int)
        tmp["lock_qty"] = pd.to_numeric(tmp.get("lock_qty", 0), errors="coerce").fillna(0.0)
        tmp = tmp[tmp["lock_qty"] > 0].copy()
        if tmp.empty:
            continue
        biz_key = tmp["lock_id"].where(tmp["lock_id"].ne(""), tmp["source_row_id"])
        tmp["dedup_key"] = (
            tmp["demand_id"]
            + "|"
            + tmp["line_id"]
            + "|"
            + tmp["slot_id"]
            + "|"
            + tmp["shift_date"]
            + "|"
            + tmp["shift"]
            + "|"
            + tmp["lock_qty"].map(lambda v: f"{float(v):.6f}")
            + "|"
            + biz_key.fillna("").astype(str)
            + "|"
            + tmp["source"]
        )
        tmp["cross_source_key"] = (
            tmp["demand_id"]
            + "|"
            + tmp["line_id"]
            + "|"
            + tmp["slot_id"]
            + "|"
            + tmp["shift_date"]
            + "|"
            + tmp["shift"]
            + "|"
            + tmp["lock_qty"].map(lambda v: f"{float(v):.6f}")
        )
        frames.append(
            tmp[
                [
                    "source",
                    "lock_id",
                    "source_row_id",
                    "demand_id",
                    "line_id",
                    "slot_id",
                    "shift_date",
                    "shift",
                    "seq",
                    "lock_qty",
                    "dedup_key",
                    "cross_source_key",
                ]
            ]
        )
    if not frames:
        empty_details = pd.DataFrame(
            columns=[
                "source",
                "lock_id",
                "source_row_id",
                "demand_id",
                "line_id",
                "slot_id",
                "shift_date",
                "shift",
                "seq",
                "lock_qty",
                "dedup_key",
                "duplicate_flag",
                "issue_type",
                "active_lock_flag",
            ]
        )
        empty_balance = pd.DataFrame(columns=["demand_id", "original_qty", "locked_qty_total", "remaining_qty"])
        overview = {
            "fixed_locks": int(len(fixed_locks)),
            "adjust_locks": int(len(adjust_locks)),
            "duplicated_lock_rows": 0,
            "over_locked_demands": 0,
            "fully_locked_demands": 0,
            "partially_locked_demands": 0,
            "remaining_qty_total": 0.0,
        }
        return empty_details, empty_balance, overview, issues

    details = pd.concat(frames, ignore_index=True)
    details["_source_rank"] = details["source"].map({"fix": 0, "adjust": 1}).fillna(9).astype(int)
    details = details.sort_values(["demand_id", "cross_source_key", "_source_rank", "seq", "source_row_id"]).reset_index(drop=True)
    details["duplicate_flag"] = 0
    details["issue_type"] = ""
    details["active_lock_flag"] = 1

    seen_strict: dict[str, int] = {}
    for idx, row in details.iterrows():
        key = str(row["dedup_key"])
        if key in seen_strict:
            details.loc[idx, "duplicate_flag"] = 1
            details.loc[idx, "issue_type"] = "same_source_exact_duplicate"
            details.loc[idx, "active_lock_flag"] = 0
        else:
            seen_strict[key] = idx

    # cross-source duplicate heuristic (same demand/line/slot/qty) -> keep FIX first.
    seen_cross: dict[str, int] = {}
    for idx, row in details.iterrows():
        if int(details.loc[idx, "active_lock_flag"]) == 0:
            continue
        key = str(row["cross_source_key"])
        prev = seen_cross.get(key)
        if prev is None:
            seen_cross[key] = idx
            continue
        prev_qty = float(details.loc[prev, "lock_qty"])
        cur_qty = float(row["lock_qty"])
        if abs(prev_qty - cur_qty) <= 1e-9:
            details.loc[idx, "duplicate_flag"] = 1
            details.loc[idx, "issue_type"] = "cross_source_same_position_qty_duplicate"
            details.loc[idx, "active_lock_flag"] = 0
        else:
            if not str(details.loc[prev, "issue_type"]):
                details.loc[prev, "issue_type"] = "same_position_different_qty_needs_review"
            details.loc[idx, "issue_type"] = "same_position_different_qty_needs_review"
            issues.append(
                {
                    "level": "warning",
                    "where": "locks",
                    "message": (
                        "Lock rows share demand/line/slot but have different lock_qty; both kept. "
                        f"demand={row['demand_id']} line={row['line_id']} slot={row['slot_id']}"
                    ),
                }
            )

    active = details[details["active_lock_flag"].astype(int) == 1].copy()
    by_demand = active.groupby("demand_id", as_index=False)["lock_qty"].sum().rename(columns={"lock_qty": "locked_qty_total"})
    lock_balance = pd.DataFrame({"demand_id": list(demand_qty.keys()), "original_qty": list(demand_qty.values())})
    lock_balance = lock_balance.merge(by_demand, on="demand_id", how="left")
    lock_balance["locked_qty_total"] = pd.to_numeric(lock_balance["locked_qty_total"], errors="coerce").fillna(0.0)
    lock_balance["remaining_qty"] = lock_balance["original_qty"] - lock_balance["locked_qty_total"]

    over = int((lock_balance["locked_qty_total"] > lock_balance["original_qty"] + 1e-6).sum())
    fully = int((lock_balance["remaining_qty"].abs() <= 1e-6).sum())
    partial = int(((lock_balance["locked_qty_total"] > 1e-6) & (lock_balance["remaining_qty"] > 1e-6)).sum())
    duplicated = int((details["duplicate_flag"].astype(int) > 0).sum())
    overview = {
        "fixed_locks": int(len(fixed_locks)),
        "adjust_locks": int(len(adjust_locks)),
        "duplicated_lock_rows": duplicated,
        "over_locked_demands": over,
        "fully_locked_demands": fully,
        "partially_locked_demands": partial,
        "remaining_qty_total": float(lock_balance["remaining_qty"].clip(lower=0).sum()),
    }
    if duplicated > 0:
        issues.append(
            {
                "level": "warning",
                "where": "locks",
                "message": f"Detected and deactivated {duplicated} duplicate lock rows.",
            }
        )
    return details.drop(columns=["_source_rank", "cross_source_key"], errors="ignore"), lock_balance, overview, issues


def _assert_lock_balance_feasible(lock_balance: pd.DataFrame) -> None:
    if lock_balance.empty:
        return
    over = lock_balance[lock_balance["locked_qty_total"] > lock_balance["original_qty"] + 1e-6]
    if len(over):
        sample = "; ".join(
            f"demand={r.demand_id} original={r.original_qty} locked={r.locked_qty_total}"
            for r in over.head(10).itertuples(index=False)
        )
        raise ValueError(f"Lock quantity exceeds demand quantity: {sample}")


def _apply_remaining_qty(demands: pd.DataFrame, lock_balance: pd.DataFrame) -> pd.DataFrame:
    if demands.empty or lock_balance.empty:
        return demands.copy()
    out = demands.copy()
    out = out.merge(lock_balance[["demand_id", "locked_qty_total", "remaining_qty"]], on="demand_id", how="left")
    out["remaining_qty"] = pd.to_numeric(out["remaining_qty"], errors="coerce").fillna(out["qty"])
    out["qty"] = out["remaining_qty"].clip(lower=0.0)
    out = out[out["qty"] > 1e-6].copy()
    out["qty"] = out["qty"].round().astype(int)
    return out.drop(columns=["locked_qty_total", "remaining_qty"], errors="ignore")


def _line_cost(key: tuple[str, str, str], demands: pd.DataFrame, line_cell: dict[str, int], config: ModelConfig) -> float:
    d, line_id, _ = key
    row = demands.loc[demands["demand_id"] == d].iloc[0]
    is_special = int(row.get("fast_ship", 0) or 0) or int(row.get("cust_svc", 0) or 0)
    return config.line_preference_cost + config.non_cell_penalty_for_small_or_special * is_special * (1 - int(line_cell.get(line_id, 0)))


def _log_lock_uph_fallbacks(locked_schedule: pd.DataFrame, runtime_issues: list[dict[str, Any]]) -> None:
    """Emit issues when locked rows could not match an exact UPH (v7_1)."""
    if locked_schedule.empty or "uph_source" not in locked_schedule.columns:
        return
    source_counts = locked_schedule["uph_source"].value_counts().to_dict()
    if source_counts.get("demand_line", 0):
        runtime_issues.append(
            {
                "level": "warning",
                "where": "locks_uph",
                "message": (
                    f"{int(source_counts['demand_line'])} locked rows used (demand, line) fallback UPH; "
                    "occupied capacity may be approximate."
                ),
            }
        )
    if source_counts.get("demand", 0):
        runtime_issues.append(
            {
                "level": "warning",
                "where": "locks_uph",
                "message": (
                    f"{int(source_counts['demand'])} locked rows used demand-level best UPH fallback; "
                    "occupied capacity is a coarse estimate."
                ),
            }
        )
    missing = locked_schedule[locked_schedule["uph_source"] == "missing"]
    if len(missing):
        runtime_issues.append(
            {
                "level": "error",
                "where": "locks_uph",
                "message": (
                    f"{int(len(missing))} locked rows have no UPH match in any fallback; "
                    "occupied capacity treated as 0 and remaining capacity may be overestimated."
                ),
            }
        )


def _post_solve_consistency_checks(
    result: pd.DataFrame,
    model,
    data: ProcessedData,
    runtime_issues: list[dict[str, Any]],
) -> None:
    """v7_1: verify lock retention, one-line-per-bucket and capacity feasibility."""
    if result.empty:
        return

    locks_frames = []
    if len(data.fixed_locks):
        locks_frames.append(data.fixed_locks.assign(_lock_source="fix"))
    if len(data.adjust_locks):
        locks_frames.append(data.adjust_locks.assign(_lock_source="adjust"))
    if locks_frames:
        all_locks = pd.concat(locks_frames, ignore_index=True)
        scheduled = result.set_index(["demand_id", "line_id", "slot_id"])["schedule_qty"].to_dict()
        missing_locks = []
        for row in all_locks.itertuples(index=False):
            key = (str(row.demand_id), str(row.line_id), str(row.slot_id))
            qty = float(getattr(row, "lock_qty", 0.0) or 0.0)
            actual = float(scheduled.get(key, 0.0) or 0.0)
            if qty > 0.0 and actual + 1e-6 < qty:
                missing_locks.append(
                    f"demand={key[0]} line={key[1]} slot={key[2]} expected>={qty} actual={actual}"
                )
        if missing_locks:
            runtime_issues.append(
                {
                    "level": "error",
                    "where": "consistency_locks",
                    "message": "Locked schedule rows not preserved in solution: " + "; ".join(missing_locks[:5]),
                }
            )

    grouped = (
        result.assign(_d=result["demand_id"].astype(str), _slot=result["slot_id"].astype(str))
        .groupby(["_d", "_slot"])["line_id"]
        .nunique()
    )
    multi_line = grouped[grouped > 1]
    if len(multi_line):
        sample = ", ".join(f"{d}|{s}" for (d, s) in list(multi_line.index)[:5])
        runtime_issues.append(
            {
                "level": "warning",
                "where": "consistency_one_line",
                "message": (
                    f"{int(len(multi_line))} (demand, slot) pairs use more than one line in solution; "
                    f"sample={sample}"
                ),
            }
        )

    triples_uph = data.triples.set_index(["demand_id", "line_id", "slot_id"])["uph"].astype(float).to_dict()
    line_slots = data.line_slots.copy()
    # v7_2: avail is post-lock-subtraction; rebuild the "physical" avail by
    # adding back the lock occupation that was already booked, then compare
    # the entire solution against it. This avoids the unit mismatch between
    # the lock-side fallback UPH (used to subtract occupation) and the post-
    # solve UPH lookup (which can return a different value).
    avail = line_slots.set_index(["line_id", "slot_id"])["avail_hours"].astype(float).to_dict()
    locked_schedule = getattr(model, "_aps_locked_schedule", pd.DataFrame())
    locked_keys: set[tuple[str, str, str]] = set()
    locked_uph: dict[tuple[str, str, str], float] = {}
    locked_occupied: dict[tuple[str, str], float] = {}
    if isinstance(locked_schedule, pd.DataFrame) and len(locked_schedule):
        for r in locked_schedule.itertuples(index=False):
            key = (str(r.demand_id), str(r.line_id), str(r.slot_id))
            locked_keys.add(key)
            locked_uph[key] = float(getattr(r, "uph", 0.0) or 0.0)
            occ = float(getattr(r, "occupied_hours", 0.0) or 0.0)
            locked_occupied[(key[1], key[2])] = locked_occupied.get((key[1], key[2]), 0.0) + occ
    setup_vars = model._aps_vars.get("setup", {}) if hasattr(model, "_aps_vars") else {}

    capacity_violations: list[str] = []
    by_ls: dict[tuple[str, str], float] = {}
    for row in result.itertuples(index=False):
        key = (str(row.demand_id), str(row.line_id), str(row.slot_id))
        qty = float(row.schedule_qty)
        # Prefer the lock-side UPH for locked rows so the units match the
        # locked occupation that was subtracted from avail upstream.
        if key in locked_keys and locked_uph.get(key, 0.0) > 0:
            uph = locked_uph[key]
        else:
            uph = float(getattr(row, "uph", 0.0) or 0.0)
            if uph <= 0.0:
                uph = float(triples_uph.get(key, 0.0) or 0.0)
        if uph <= 0.0:
            continue
        by_ls[(key[1], key[2])] = by_ls.get((key[1], key[2]), 0.0) + qty / uph
    for (line_id, slot_id), used in by_ls.items():
        setup_used = 0.0
        var = setup_vars.get((line_id, slot_id))
        try:
            if var is not None:
                setup_used = float(var.X)
        except Exception:
            setup_used = 0.0
        cap = float(avail.get((line_id, slot_id), 0.0) or 0.0)
        # Add back lock occupation so we compare against the *physical* shift
        # capacity rather than the post-subtraction residual.
        physical_cap = cap + float(locked_occupied.get((line_id, slot_id), 0.0))
        if used + setup_used > physical_cap + 1e-3:
            capacity_violations.append(
                f"line={line_id} slot={slot_id} used={used:.3f} setup={setup_used:.3f} avail={physical_cap:.3f}"
            )
    if capacity_violations:
        runtime_issues.append(
            {
                "level": "error",
                "where": "consistency_capacity",
                "message": "Capacity exceeded in solution: " + "; ".join(capacity_violations[:5]),
            }
        )


def _post_solve_fai_check(
    result: pd.DataFrame,
    model,
    data: ProcessedData,
    runtime_issues: list[dict[str, Any]],
) -> None:
    """v7_1: verify FAI rest demand actually starts after first finish + lead."""
    arcs = getattr(model, "_aps_data_fai_arcs", data.fai_arcs)
    if arcs is None or arcs.empty or result.empty:
        return
    config = getattr(model, "_aps_config", None)
    if config is not None and getattr(config, "enforce_fai_with_big_m", False):
        return  # Hard constraint already enforced by Big-M.
    res = result.copy()
    res["shift_start_time"] = pd.to_datetime(res["shift_start_time"], errors="coerce")
    res["shift_end_time"] = pd.to_datetime(res["shift_end_time"], errors="coerce")
    finish_by_demand = (
        res.dropna(subset=["shift_end_time"]).groupby("demand_id")["shift_end_time"].max().to_dict()
    )
    start_by_demand = (
        res.dropna(subset=["shift_start_time"]).groupby("demand_id")["shift_start_time"].min().to_dict()
    )

    violations: list[str] = []
    for arc in arcs.itertuples(index=False):
        first_d = str(arc.first_demand_id)
        rest_d = str(arc.rest_demand_id)
        finish = finish_by_demand.get(first_d)
        rest_start = start_by_demand.get(rest_d)
        if pd.isna(finish) or pd.isna(rest_start) or finish is None or rest_start is None:
            continue
        required = pd.Timestamp(finish) + pd.Timedelta(hours=float(arc.lead_hours))
        if pd.Timestamp(rest_start) + pd.Timedelta(seconds=1) < required:
            violations.append(
                f"group={arc.group_id} first={first_d} rest={rest_d} "
                f"first_finish={pd.Timestamp(finish).isoformat()} "
                f"rest_start={pd.Timestamp(rest_start).isoformat()} "
                f"required>={required.isoformat()}"
            )
    if violations:
        runtime_issues.append(
            {
                "level": "warning",
                "where": "fai_violation",
                "message": (
                    f"{len(violations)} FAI precedence violations under window-pruning mode; "
                    f"sample={'; '.join(violations[:3])}"
                ),
            }
        )


def _key_name(key: tuple[Any, ...]) -> str:
    return "|".join(str(k) for k in key)
