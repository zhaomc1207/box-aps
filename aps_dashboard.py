#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
工业级 APS 可视化调度看板（Streamlit）
启动：streamlit run aps_dashboard.py
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st


# ========================
# 字段识别
# ========================
FIELD_ALIASES: Dict[str, List[str]] = {
    "order_id": ["order_id", "order", "work_order", "wo", "工单", "工单号", "订单", "订单号", "demand_id"],
    "operation": ["operation", "operation_id", "op", "工序", "工序号", "工步", "schedule_cut_no", "schedule_seq"],
    "product": ["product", "product_id", "model", "pn", "mcode", "产品", "产品号", "物料", "料号"],
    "machine": ["machine", "resource", "equipment", "line", "line_id", "schedule_line", "schedule_line_id", "设备", "机器", "机台", "产线"],
    "start": ["start", "start_time", "begin", "schedule_start_time", "开始", "开始时间", "开工时间"],
    "end": ["end", "end_time", "finish", "schedule_end_time", "结束", "结束时间", "完工时间"],
    "setup_start": ["setup_start", "setup_start_time", "changeover_start", "换型开始", "setup开始时间"],
    "setup_end": ["setup_end", "setup_end_time", "changeover_end", "换型结束", "setup结束时间"],
    "changeover": ["changeover", "changeover_time", "setup_time", "换型时间", "换线时间", "准备时间"],
    "delay": ["delay", "delayed", "is_delayed", "late", "tardy", "逾期", "延迟", "延期", "schedule_problem_type"],
    "priority": ["priority", "priority_rank", "priority_level", "优先级", "优先级别"],
    "due": ["due", "due_time", "due_date", "交期", "交付日期", "计划交期"],
}


def _normalize_name(name: str) -> str:
    s = str(name).strip().lower()
    for ch in [" ", "-", "_", "/", "\\", "(", ")", "[", "]", "{", "}", ":", "："]:
        s = s.replace(ch, "")
    return s


def _infer_column(columns: List[str], candidates: List[str]) -> Optional[str]:
    norm_to_raw = {_normalize_name(c): c for c in columns}
    for cand in candidates:
        hit = norm_to_raw.get(_normalize_name(cand))
        if hit:
            return hit
    for cand in candidates:
        nc = _normalize_name(cand)
        for k, raw in norm_to_raw.items():
            if nc and (nc in k or k in nc):
                return raw
    return None


# ========================
# 数据层
# ========================
@st.cache_data(show_spinner=False)
def load_data(input_csv: str) -> pd.DataFrame:
    path = Path(input_csv)
    if not path.exists():
        raise FileNotFoundError(f"输入文件不存在: {input_csv}")
    encodings = ["utf-8-sig", "utf-8", "gbk", "gb18030"]
    last_err = None
    for enc in encodings:
        try:
            return pd.read_csv(path, encoding=enc)
        except Exception as e:  # noqa: BLE001
            last_err = e
    raise RuntimeError(f"CSV读取失败: {input_csv}; 最后错误: {last_err}")


@st.cache_data(show_spinner=False)
def preprocess(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, Optional[str]], List[str]]:
    cols = list(df.columns)
    mapping = {k: _infer_column(cols, v) for k, v in FIELD_ALIASES.items()}

    required = ["machine", "start", "end"]
    missing = [k for k in required if mapping.get(k) is None]
    if missing:
        raise ValueError(f"缺少关键字段: {missing}。当前列: {cols}")

    x = df.copy()
    x["machine"] = x[mapping["machine"]].astype(str).str.strip()
    x["start"] = pd.to_datetime(x[mapping["start"]], errors="coerce")
    x["end"] = pd.to_datetime(x[mapping["end"]], errors="coerce")
    x["order_id"] = x[mapping["order_id"]].astype(str) if mapping["order_id"] else "UNKNOWN_ORDER"

    # product 识别优先避免误把 id 当产品
    if mapping["product"] and str(mapping["product"]).lower() != "id":
        x["product"] = x[mapping["product"]].astype(str)
    elif "model" in x.columns:
        x["product"] = x["model"].astype(str)
    elif "pn" in x.columns:
        x["product"] = x["pn"].astype(str)
    else:
        x["product"] = ""

    x["operation"] = x[mapping["operation"]].astype(str) if mapping["operation"] else ""
    x["priority"] = pd.to_numeric(x[mapping["priority"]], errors="coerce") if mapping["priority"] else np.nan
    x["due"] = pd.to_datetime(x[mapping["due"]], errors="coerce") if mapping["due"] else pd.NaT

    if mapping["delay"]:
        raw = x[mapping["delay"]].astype(str).str.strip().str.lower()
        true_set = {"1", "true", "yes", "y", "delay", "delayed", "late", "逾期", "延迟"}
        x["is_delayed"] = raw.isin(true_set) | ((raw != "") & (raw != "0") & (raw != "none") & (raw != "nan"))
    else:
        x["is_delayed"] = False

    issues: List[str] = []
    before = len(x)
    x = x.dropna(subset=["start", "end"])
    x = x[(x["machine"] != "") & (x["end"] > x["start"])]
    dropped = before - len(x)
    if dropped > 0:
        issues.append(f"过滤无效任务 {dropped} 条")

    if not mapping["delay"] and x["due"].notna().any():
        x["is_delayed"] = (x["end"] > x["due"]).fillna(False)

    # 主任务
    prod = x[["machine", "order_id", "operation", "product", "start", "end", "priority", "is_delayed"]].copy()
    prod["task_type"] = "production"

    # setup 构造
    setup = pd.DataFrame(columns=prod.columns)
    if mapping["setup_start"] and mapping["setup_end"]:
        ss = pd.to_datetime(x[mapping["setup_start"]], errors="coerce")
        se = pd.to_datetime(x[mapping["setup_end"]], errors="coerce")
        mask = ss.notna() & se.notna() & (se > ss)
        if mask.any():
            setup = x.loc[mask, ["machine", "order_id", "operation", "product", "priority", "is_delayed"]].copy()
            setup["start"] = ss[mask]
            setup["end"] = se[mask]
            setup["task_type"] = "setup"
    elif mapping["changeover"]:
        cm = pd.to_numeric(x[mapping["changeover"]], errors="coerce").fillna(0)
        mask = cm > 0
        if mask.any():
            setup = x.loc[mask, ["machine", "order_id", "operation", "product", "priority", "is_delayed"]].copy()
            setup["end"] = x.loc[mask, "start"]
            setup["start"] = setup["end"] - pd.to_timedelta(cm[mask], unit="m")
            setup = setup[setup["end"] > setup["start"]]
            setup["task_type"] = "setup"

    # idle 构造
    idle_rows = []
    for machine, g in prod.sort_values(["machine", "start", "end"]).groupby("machine", sort=False):
        g = g.reset_index(drop=True)
        for i in range(1, len(g)):
            pe, cs = g.loc[i - 1, "end"], g.loc[i, "start"]
            if cs > pe:
                idle_rows.append(
                    {
                        "machine": machine,
                        "order_id": "IDLE",
                        "operation": "",
                        "product": "",
                        "start": pe,
                        "end": cs,
                        "priority": np.nan,
                        "is_delayed": False,
                        "task_type": "idle",
                    }
                )
    idle = pd.DataFrame(idle_rows) if idle_rows else pd.DataFrame(columns=prod.columns)

    tasks = pd.concat([prod, setup, idle], ignore_index=True)
    tasks["duration_min"] = ((tasks["end"] - tasks["start"]).dt.total_seconds() / 60.0).clip(lower=0)
    tasks = tasks.sort_values(["machine", "start", "end"]).reset_index(drop=True)
    tasks["sequence_on_machine"] = tasks.groupby("machine").cumcount() + 1

    # 自动聚合超小任务（默认阈值 2 分钟）
    tasks = _aggregate_tiny_tasks(tasks, min_minutes=2.0)

    return tasks, mapping, issues


def _aggregate_tiny_tasks(tasks: pd.DataFrame, min_minutes: float = 2.0) -> pd.DataFrame:
    x = tasks.copy()
    tiny = x["duration_min"] < min_minutes
    if tiny.sum() == 0:
        return x

    # 只聚合 production 的超小碎片任务，按机器+5分钟桶+task_type
    t = x[tiny & (x["task_type"] == "production")].copy()
    r = x[~(tiny & (x["task_type"] == "production"))].copy()
    if t.empty:
        return x

    t["bucket"] = t["start"].dt.floor("5min")
    g = (
        t.groupby(["machine", "bucket", "task_type"], dropna=False)
        .agg(
            start=("start", "min"),
            end=("end", "max"),
            duration_min=("duration_min", "sum"),
            cnt=("order_id", "count"),
            delayed=("is_delayed", "max"),
        )
        .reset_index()
    )
    g["order_id"] = g["cnt"].map(lambda n: f"AGG_{int(n)}")
    g["operation"] = "aggregated"
    g["product"] = "aggregated"
    g["priority"] = np.nan
    g["is_delayed"] = g["delayed"].astype(bool)
    g["sequence_on_machine"] = -1

    g = g[["machine", "order_id", "operation", "product", "start", "end", "priority", "is_delayed", "task_type", "duration_min", "sequence_on_machine"]]
    out = pd.concat([r, g], ignore_index=True).sort_values(["machine", "start", "end"]).reset_index(drop=True)
    return out


# ========================
# 分析层
# ========================
def utilization_analysis(tasks: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, float]]:
    prod = tasks[tasks["task_type"] == "production"].copy()
    if prod.empty:
        return pd.DataFrame(
            columns=[
                "machine",
                "task_count",
                "busy_hours",
                "window_hours",
                "global_window_hours",
                "active_window_utilization_pct",
                "global_window_utilization_pct",
                "utilization_pct",
                "overlap_count",
                "overlap_minutes",
                "has_overlap",
                "is_bottleneck",
            ]
        ), {
            "makespan_hours": 0.0,
            "total_tasks": 0,
            "avg_util_pct": 0.0,
            "max_util_pct": 0.0,
            "max_continuous_work_hours": 0.0,
            "bottleneck": "-",
        }

    overall_start, overall_end = prod["start"].min(), prod["end"].max()
    makespan_hours = (overall_end - overall_start).total_seconds() / 3600.0
    global_window_hours = max(makespan_hours, 1e-9)

    rows = []
    global_max_chain = 0.0
    for machine, g in prod.sort_values(["machine", "start", "end"]).groupby("machine", sort=False):
        g = g.reset_index(drop=True)
        # 原始任务总时长（可能包含重叠）
        raw_busy_hours = ((g["end"] - g["start"]).dt.total_seconds() / 3600.0).sum()
        active_window_hours = max((g["end"].max() - g["start"].min()).total_seconds() / 3600.0, 1e-9)

        # 同设备重叠检测 + 去重后的有效忙碌时长（union）
        overlap_count = 0
        merged_start = g.loc[0, "start"]
        merged_end = g.loc[0, "end"]
        union_hours = 0.0
        overlap_hours = 0.0
        for i in range(1, len(g)):
            s, e = g.loc[i, "start"], g.loc[i, "end"]
            if s < merged_end:
                overlap_count += 1
                overlap_hours += (min(e, merged_end) - s).total_seconds() / 3600.0
                merged_end = max(merged_end, e)
            else:
                union_hours += (merged_end - merged_start).total_seconds() / 3600.0
                merged_start, merged_end = s, e
        union_hours += (merged_end - merged_start).total_seconds() / 3600.0

        active_util = union_hours / active_window_hours
        global_util = union_hours / global_window_hours

        # 最大连续工作
        chain_start = g.loc[0, "start"]
        chain_end = g.loc[0, "end"]
        local_max = 0.0
        for i in range(1, len(g)):
            s, e = g.loc[i, "start"], g.loc[i, "end"]
            if s <= chain_end:
                chain_end = max(chain_end, e)
            else:
                local_max = max(local_max, (chain_end - chain_start).total_seconds() / 3600.0)
                chain_start, chain_end = s, e
        local_max = max(local_max, (chain_end - chain_start).total_seconds() / 3600.0)
        global_max_chain = max(global_max_chain, local_max)

        rows.append(
            {
                "machine": machine,
                "task_count": int(len(g)),
                "busy_hours": round(float(union_hours), 3),
                "window_hours": round(float(active_window_hours), 3),
                "global_window_hours": round(float(global_window_hours), 3),
                "active_window_utilization_pct": round(float(active_util * 100), 2),
                "global_window_utilization_pct": round(float(global_util * 100), 2),
                # 兼容旧字段：utilization_pct 继续保留，口径改为 global window
                "utilization_pct": round(float(global_util * 100), 2),
                "overlap_count": int(overlap_count),
                "overlap_minutes": round(float(max(overlap_hours, raw_busy_hours - union_hours) * 60.0), 2),
                "has_overlap": bool(overlap_count > 0),
            }
        )

    util = pd.DataFrame(rows).sort_values("global_window_utilization_pct", ascending=False).reset_index(drop=True)
    p90 = (
        util["global_window_utilization_pct"].quantile(0.9)
        if len(util) > 1
        else util["global_window_utilization_pct"].iloc[0]
    )
    util["is_bottleneck"] = (util["global_window_utilization_pct"] >= p90) | (util["global_window_utilization_pct"] >= 85.0)

    bottlenecks = util[util["is_bottleneck"]]["machine"].astype(str).tolist()
    panel = {
        "makespan_hours": round(float(makespan_hours), 2),
        "total_tasks": int(len(prod)),
        # 按要求：改为 global_window_utilization_pct 口径
        "avg_util_pct": round(float(util["global_window_utilization_pct"].mean()), 2),
        "max_util_pct": round(float(util["global_window_utilization_pct"].max()), 2),
        "max_continuous_work_hours": round(float(global_max_chain), 2),
        "bottleneck": ", ".join(bottlenecks[:8]) if bottlenecks else "-",
    }
    return util, panel


# ========================
# 侧边筛选
# ========================
def sidebar_filters(tasks: pd.DataFrame, util: pd.DataFrame) -> Dict[str, object]:
    st.sidebar.header("筛选与性能控制")

    machines = sorted(tasks["machine"].dropna().astype(str).unique().tolist())
    orders = sorted(tasks["order_id"].dropna().astype(str).unique().tolist())
    products = sorted(tasks["product"].dropna().astype(str).unique().tolist())

    only_bottleneck = st.sidebar.checkbox("仅显示瓶颈设备", value=False)
    if only_bottleneck and not util.empty:
        bottleneck_set = set(util.loc[util["is_bottleneck"], "machine"].astype(str).tolist())
        machines_default = [m for m in machines if m in bottleneck_set] or machines[: min(5, len(machines))]
    else:
        machines_default = machines[: min(10, len(machines))]

    selected_machines = st.sidebar.multiselect("设备筛选", machines, default=machines_default)

    selected_orders = st.sidebar.multiselect("工单筛选", orders, default=[])
    selected_products = st.sidebar.multiselect("产品筛选", products, default=[])

    # 时间窗口
    min_t = pd.Timestamp(tasks["start"].min()).to_pydatetime()
    max_t = pd.Timestamp(tasks["end"].max()).to_pydatetime()
    default_end = min_t + pd.Timedelta(days=7)
    if default_end > max_t:
        default_end = max_t
    window = st.sidebar.slider("时间窗口", min_value=min_t, max_value=max_t, value=(min_t, default_end), format="YYYY-MM-DD HH:mm")

    show_setup = st.sidebar.checkbox("显示 setup", value=True)
    show_idle = st.sidebar.checkbox("显示 idle", value=False)

    max_tasks = st.sidebar.slider("最大显示任务数", min_value=1000, max_value=50000, value=12000, step=1000)
    view_mode = st.sidebar.radio("视图模式", options=["Task级", "工单级概览"], index=0, horizontal=True)
    chart_mode = st.sidebar.radio("图表模式", options=["甘特图", "热力图"], index=0, horizontal=True)
    heat_bucket = st.sidebar.selectbox("热力图时间粒度", options=["1h", "4h", "1d"], index=0)

    return {
        "machines": selected_machines,
        "orders": selected_orders,
        "products": selected_products,
        "t0": pd.Timestamp(window[0]),
        "t1": pd.Timestamp(window[1]),
        "show_setup": show_setup,
        "show_idle": show_idle,
        "only_bottleneck": only_bottleneck,
        "max_tasks": int(max_tasks),
        "view_mode": view_mode,
        "chart_mode": chart_mode,
        "heat_bucket": heat_bucket,
    }


# ========================
# 可视化
# ========================
def build_gantt(tasks: pd.DataFrame, util: pd.DataFrame, filters: Dict[str, object]) -> Tuple[object, int, int, List[str]]:
    x = tasks.copy()

    # 只渲染选中设备 + 时间窗口
    if filters["machines"]:
        x = x[x["machine"].astype(str).isin(filters["machines"])].copy()
    x = x[(x["start"] < filters["t1"]) & (x["end"] > filters["t0"])].copy()

    # 订单/产品过滤
    if filters["orders"]:
        x = x[x["order_id"].astype(str).isin(filters["orders"])].copy()
    if filters["products"]:
        x = x[x["product"].astype(str).isin(filters["products"])].copy()

    # setup/idle 开关
    keep_types = {"production"}
    if filters["show_setup"]:
        keep_types.add("setup")
    if filters["show_idle"]:
        keep_types.add("idle")
    x = x[x["task_type"].isin(keep_types)].copy()

    before_limit = len(x)
    sampled = []
    if before_limit > filters["max_tasks"]:
        # 分设备按开始时间截取，保证每台设备都有展示
        chunks = []
        group_count = x["machine"].nunique()
        per_machine = max(1, filters["max_tasks"] // max(1, group_count))
        for _, g in x.sort_values(["machine", "start", "end"]).groupby("machine", sort=False):
            chunks.append(g.head(per_machine))
        x = pd.concat(chunks, ignore_index=True)
        if len(x) > filters["max_tasks"]:
            x = x.head(filters["max_tasks"]).copy()
        sampled.append(f"任务量过大，已从 {before_limit} 条裁剪为 {len(x)} 条")

    x = x.sort_values(["machine", "start", "end"]).reset_index(drop=True)

    # 工单级概览模式：按设备+工单聚合时间段，降低视觉噪声
    if filters.get("view_mode") == "工单级概览" and not x.empty:
        grouped = (
            x.groupby(["machine", "order_id"], dropna=False)
            .agg(
                start=("start", "min"),
                end=("end", "max"),
                actual_work_minutes=("duration_min", "sum"),
                task_count=("order_id", "size"),
                operation=("operation", "first"),
                product=("product", "first"),
                has_delay=("is_delayed", "max"),
                has_setup=("task_type", lambda s: int((s == "setup").any())),
                has_idle=("task_type", lambda s: int((s == "idle").any())),
            )
            .reset_index()
        )
        grouped["span_minutes"] = ((grouped["end"] - grouped["start"]).dt.total_seconds() / 60.0).clip(lower=0.0)
        grouped["gap_minutes"] = (grouped["span_minutes"] - grouped["actual_work_minutes"]).clip(lower=0.0)
        grouped["task_type"] = "production"
        grouped["is_delayed"] = grouped["has_delay"].astype(bool)
        grouped["operation"] = grouped["task_count"].map(lambda n: f"聚合任务({int(n)}条)")
        grouped["product"] = grouped["product"].fillna("").astype(str)
        grouped["view_record_type"] = "工单聚合记录"
        grouped = grouped.sort_values(["machine", "start", "end"]).reset_index(drop=True)
        grouped["sequence_on_machine"] = grouped.groupby("machine").cumcount() + 1
        # 保持 duration_min 兼容现有逻辑
        grouped["duration_min"] = grouped["actual_work_minutes"]
        x = grouped[
            [
                "machine",
                "order_id",
                "operation",
                "product",
                "start",
                "end",
                "duration_min",
                "task_type",
                "is_delayed",
                "task_count",
                "actual_work_minutes",
                "span_minutes",
                "gap_minutes",
                "has_delay",
                "has_setup",
                "has_idle",
                "sequence_on_machine",
                "view_record_type",
            ]
        ].copy()
        sampled.append("当前为工单级概览：同一设备内同工单已合并显示")

    # 瓶颈设备排序置顶
    bottleneck_set = set(util.loc[util["is_bottleneck"], "machine"].astype(str).tolist()) if not util.empty else set()
    machine_order = (
        sorted(x["machine"].astype(str).unique().tolist(), key=lambda m: (0 if m in bottleneck_set else 1, m))
        if not x.empty
        else []
    )

    # 纯时间轴：直接使用开始/结束时间，避免横轴出现 xxM 数值刻度
    # 颜色语义：
    # - 生产任务：蓝色
    # - setup/changeover：黄色
    # - idle：深灰
    # 延期任务使用红色边框；瓶颈任务额外高亮边框。
    x["display_type"] = "生产任务"
    x.loc[x["task_type"] == "setup", "display_type"] = "Setup/换型"
    x.loc[x["task_type"] == "idle", "display_type"] = "Idle/空闲"

    bottleneck_set = set(util.loc[util["is_bottleneck"], "machine"].astype(str).tolist()) if not util.empty else set()
    x["is_bottleneck_task"] = x["machine"].astype(str).isin(bottleneck_set)
    x["is_delayed"] = x["is_delayed"].astype(bool)

    color_map = {
        "生产任务": "#3B82F6",
        "Setup/换型": "#F59E0B",
        "Idle/空闲": "#1F2937",
    }

    # 按视图模式构造 hover 字段，并做防御式字段兜底，避免 hover_data 引用不存在列
    if filters.get("view_mode") == "工单级概览":
        desired_hover = {
            "order_id": True,
            "product": True,
            "operation": True,
            "task_count": True,
            "actual_work_minutes": True,
            "span_minutes": True,
            "gap_minutes": True,
            "has_delay": True,
            "has_setup": True,
            "has_idle": True,
            "view_record_type": True,
            "start": True,
            "end": True,
            "display_type": False,
        }
    else:
        desired_hover = {
            "order_id": True,
            "operation": True,
            "product": True,
            "task_type": True,
            "duration_min": True,
            "sequence_on_machine": True,
            "is_delayed": True,
            "is_bottleneck_task": True,
            "start": True,
            "end": True,
            "display_type": False,
        }
    hover_data = {k: v for k, v in desired_hover.items() if k in x.columns}

    fig = px.timeline(
        x,
        x_start="start",
        x_end="end",
        y="machine",
        color="display_type",
        color_discrete_map=color_map,
        category_orders={"machine": machine_order},
        hover_data=hover_data,
    )

    # 延期任务：红色边框；瓶颈任务：青色高亮边框（延期优先）
    # 仅在 Task级应用该边框语义，工单级概览不做逐任务语义边框。
    if filters.get("view_mode") == "工单级概览":
        return fig, before_limit, len(x), sampled
    for tr in fig.data:
        cd = tr.customdata
        if cd is None or len(cd) == 0:
            continue
        # customdata 顺序由 hover_data 决定
        # [order_id, operation, product, task_type, duration_min, sequence_on_machine, is_delayed, is_bottleneck_task, start, end]
        delayed = [bool(row[6]) for row in cd]
        bottleneck = [bool(row[7]) for row in cd]
        line_colors = []
        line_widths = []
        for d, b in zip(delayed, bottleneck):
            if d:
                line_colors.append("#DC2626")  # 红边
                line_widths.append(2.0)
            elif b:
                line_colors.append("#22D3EE")  # 瓶颈高亮
                line_widths.append(1.6)
            else:
                line_colors.append("rgba(0,0,0,0)")
                line_widths.append(0.0)
        tr.marker.line.color = line_colors
        tr.marker.line.width = line_widths

    fig.update_layout(
        barmode="overlay",
        template="plotly_dark",
        height=max(500, min(2200, 120 + 36 * max(1, len(machine_order)))),
        margin=dict(l=120, r=20, t=50, b=40),
        xaxis=dict(
            type="date",
            title="时间",
            showgrid=True,
            gridcolor="#334155",
            tickformat="%m-%d %H:%M",
            rangeslider=dict(visible=True),
            rangeselector=dict(
                buttons=[
                    dict(count=8, label="8h", step="hour", stepmode="backward"),
                    dict(count=1, label="1d", step="day", stepmode="backward"),
                    dict(count=7, label="7d", step="day", stepmode="backward"),
                    dict(step="all", label="全部"),
                ]
            ),
        ),
        yaxis=dict(title="设备", showgrid=True, gridcolor="#1F2937", categoryorder="array", categoryarray=machine_order, autorange="reversed"),
        legend=dict(orientation="h", y=1.08, x=0),
        hovermode="closest",
    )

    # 固定关闭 legend，避免大量点位时的前端重排卡顿
    fig.update_layout(showlegend=False)

    return fig, before_limit, len(x), sampled


def build_heatmap(tasks: pd.DataFrame, util: pd.DataFrame, filters: Dict[str, object]) -> Tuple[object, int]:
    """设备负载热力图：横轴时间、纵轴设备、颜色=利用率。"""
    x = tasks.copy()
    if filters["machines"]:
        x = x[x["machine"].astype(str).isin(filters["machines"])].copy()
    x = x[(x["start"] < filters["t1"]) & (x["end"] > filters["t0"])].copy()

    # 热力图只看生产任务负载（setup/idle 不计入负载）
    x = x[x["task_type"] == "production"].copy()
    if x.empty:
        fig = px.imshow(np.zeros((1, 1)), text_auto=True, aspect="auto", template="plotly_dark")
        fig.update_layout(title="设备负载热力图（无数据）")
        return fig, 0

    freq_map = {"1h": "1h", "4h": "4h", "1d": "1d"}
    freq = freq_map.get(filters.get("heat_bucket", "1h"), "1h")

    t0 = pd.Timestamp(filters["t0"]).floor(freq)
    t1 = pd.Timestamp(filters["t1"]).ceil(freq)
    bins = pd.date_range(t0, t1, freq=freq)
    if len(bins) < 2:
        bins = pd.date_range(t0, t0 + pd.Timedelta(hours=1), freq=freq)
    bucket_hours = (bins[1] - bins[0]).total_seconds() / 3600.0

    machines = sorted(x["machine"].astype(str).unique().tolist())
    machine_idx = {m: i for i, m in enumerate(machines)}
    slot_idx = {bins[i]: i for i in range(len(bins) - 1)}
    mat = np.zeros((len(machines), len(bins) - 1), dtype=float)

    # 逐任务分摊到时间桶（按重叠时长）
    for row in x[["machine", "start", "end"]].itertuples(index=False):
        m = str(row.machine)
        s = max(pd.Timestamp(row.start), t0)
        e = min(pd.Timestamp(row.end), t1)
        if e <= s:
            continue
        left = s.floor(freq)
        right = e.ceil(freq)
        for b_start in pd.date_range(left, right, freq=freq):
            if b_start not in slot_idx:
                continue
            b_end = b_start + (bins[1] - bins[0])
            ov = (min(e, b_end) - max(s, b_start)).total_seconds() / 3600.0
            if ov > 0:
                mat[machine_idx[m], slot_idx[b_start]] += ov

    # 利用率裁到 [0,1]
    util_mat = np.clip(mat / max(bucket_hours, 1e-9), 0.0, 1.0)
    x_labels = [b.strftime("%m-%d %H:%M") for b in bins[:-1]]

    # 颜色语义：深色(空闲)->蓝(正常)->黄(高负载)->红(瓶颈)
    colorscale = [
        [0.00, "#0B1220"],
        [0.25, "#1E3A8A"],
        [0.60, "#2563EB"],
        [0.80, "#F59E0B"],
        [1.00, "#DC2626"],
    ]

    fig = go.Figure(
        data=go.Heatmap(
            z=util_mat,
            x=x_labels,
            y=machines,
            colorscale=colorscale,
            zmin=0,
            zmax=1,
            colorbar=dict(title="利用率"),
            hovertemplate="设备: %{y}<br>时间: %{x}<br>利用率: %{z:.1%}<extra></extra>",
        )
    )
    fig.update_layout(
        template="plotly_dark",
        title=f"设备负载热力图（粒度: {filters.get('heat_bucket','1h')}）",
        xaxis_title="时间",
        yaxis_title="设备",
        margin=dict(l=120, r=20, t=50, b=40),
        height=max(500, min(1800, 120 + 30 * max(1, len(machines)))),
    )
    fig.update_yaxes(autorange="reversed")
    return fig, int(util_mat.size)


def _filtered_tasks_for_kpi(tasks: pd.DataFrame, filters: Dict[str, object]) -> pd.DataFrame:
    """复用与图表一致的筛选/限流规则，供 KPI 面板统计。"""
    x = tasks.copy()
    if filters["machines"]:
        x = x[x["machine"].astype(str).isin(filters["machines"])].copy()
    x = x[(x["start"] < filters["t1"]) & (x["end"] > filters["t0"])].copy()
    if filters["orders"]:
        x = x[x["order_id"].astype(str).isin(filters["orders"])].copy()
    if filters["products"]:
        x = x[x["product"].astype(str).isin(filters["products"])].copy()

    keep_types = {"production"}
    if filters["show_setup"]:
        keep_types.add("setup")
    if filters["show_idle"]:
        keep_types.add("idle")
    x = x[x["task_type"].isin(keep_types)].copy()

    if len(x) > filters["max_tasks"]:
        chunks = []
        group_count = x["machine"].nunique()
        per_machine = max(1, filters["max_tasks"] // max(1, group_count))
        for _, g in x.sort_values(["machine", "start", "end"]).groupby("machine", sort=False):
            chunks.append(g.head(per_machine))
        x = pd.concat(chunks, ignore_index=True)
        if len(x) > filters["max_tasks"]:
            x = x.head(filters["max_tasks"]).copy()
    return x


def _filtered_tasks_for_kpi_full(tasks: pd.DataFrame, filters: Dict[str, object]) -> pd.DataFrame:
    """KPI专用：只应用设备/工单/产品/时间窗口筛选，不受 show_setup/show_idle/max_tasks 影响。"""
    x = tasks.copy()
    if filters["machines"]:
        x = x[x["machine"].astype(str).isin(filters["machines"])].copy()
    x = x[(x["start"] < filters["t1"]) & (x["end"] > filters["t0"])].copy()
    if filters["orders"]:
        x = x[x["order_id"].astype(str).isin(filters["orders"])].copy()
    if filters["products"]:
        x = x[x["product"].astype(str).isin(filters["products"])].copy()
    return x


# ========================
# 页面
# ========================
def main() -> None:
    st.set_page_config(page_title="APS 工业级可视化调度看板", layout="wide")

    st.markdown(
        """
        <style>
        .stApp {background-color: #0b1220; color: #e5e7eb;}
        [data-testid="stSidebar"] {background-color: #111827;}
        div[data-testid="metric-container"] {background: #111827; border: 1px solid #1f2937; padding: 8px; border-radius: 8px;}
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.title("工业级 APS 可视化调度看板")

    default_input = "outputs/run_009_2h/box_output_tables/aps_schedule_result.csv"
    input_path = st.text_input("输入 CSV 路径", value=default_input)

    with st.spinner("加载并预处理数据..."):
        raw = load_data(input_path)
        tasks, mapping, issues = preprocess(raw)
        util, panel = utilization_analysis(tasks)

    filters = sidebar_filters(tasks, util)
    fig, before_limit, shown_count, notices = build_gantt(tasks, util, filters)
    kpi_df = _filtered_tasks_for_kpi(tasks, filters)
    kpi_df_full = _filtered_tasks_for_kpi_full(tasks, filters)
    heat_fig, _ = build_heatmap(tasks, util, filters)

    # 当前显示范围的 setup/idle 占比（按时长）
    # 按要求：setup/idle KPI 改用 full 口径（不受 show_setup/show_idle 和 max_tasks 影响）
    total_min = float(kpi_df_full["duration_min"].sum()) if len(kpi_df_full) else 0.0
    setup_min = float(kpi_df_full.loc[kpi_df_full["task_type"] == "setup", "duration_min"].sum()) if len(kpi_df_full) else 0.0
    idle_min = float(kpi_df_full.loc[kpi_df_full["task_type"] == "idle", "duration_min"].sum()) if len(kpi_df_full) else 0.0
    setup_ratio = (setup_min / total_min * 100.0) if total_min > 0 else 0.0
    idle_ratio = (idle_min / total_min * 100.0) if total_min > 0 else 0.0
    setup_count = int((kpi_df_full["task_type"] == "setup").sum()) if len(kpi_df_full) else 0
    idle_count = int((kpi_df_full["task_type"] == "idle").sum()) if len(kpi_df_full) else 0

    # 顶部 KPI 面板（深色工业风卡片）
    st.markdown(
        """
        <style>
        div[data-testid="metric-container"] {
            background: linear-gradient(180deg, #111827 0%, #0f172a 100%);
            border: 1px solid #1f2937;
            border-radius: 10px;
            padding: 10px 12px;
            box-shadow: 0 1px 0 rgba(255,255,255,0.03) inset;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    c1, c2, c3, c4 = st.columns(4)
    c5, c6, c7, c8 = st.columns(4)
    c1.metric("Makespan(h)", panel["makespan_hours"])
    c2.metric("总任务数", panel["total_tasks"])
    c3.metric("当前显示任务数", shown_count)
    c4.metric("平均设备利用率", f"{panel['avg_util_pct']}%")
    c5.metric("最大设备利用率", f"{panel['max_util_pct']}%")
    c6.metric("setup占比", f"{setup_ratio:.2f}%")
    c7.metric("idle占比", f"{idle_ratio:.2f}%")
    c8.metric("瓶颈设备", panel["bottleneck"] if len(str(panel["bottleneck"])) < 28 else str(panel["bottleneck"])[:28] + "...")

    # setup / idle 统计（工业语义补充）
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Setup任务数", setup_count)
    s2.metric("Setup总时长(h)", f"{setup_min/60.0:.2f}")
    s3.metric("Idle任务数", idle_count)
    s4.metric("Idle总时长(h)", f"{idle_min/60.0:.2f}")

    # 排程诊断（基于当前筛选时间窗口）
    with st.expander("排程诊断", expanded=True):
        if kpi_df_full.empty:
            st.info("当前筛选范围无任务数据，暂无法生成诊断结论。")
        else:
            max_global_util = float(panel.get("max_util_pct", 0.0) or 0.0)
            avg_global_util = float(panel.get("avg_util_pct", 0.0) or 0.0)
            max_active_util = float(util["active_window_utilization_pct"].max()) if not util.empty else 0.0
            overlap_total = int(util["overlap_count"].sum()) if ("overlap_count" in util.columns and not util.empty) else 0
            delayed_count = int(
                (
                    (kpi_df_full["task_type"] == "production")
                    & (kpi_df_full["is_delayed"].astype(bool))
                ).sum()
            )

            if max_global_util >= 85:
                st.warning(f"存在高负载瓶颈设备：最大设备利用率 {max_global_util:.2f}%（>=85%）。")
            if max_global_util < 85 and avg_global_util < 50:
                st.info(f"整体产能尚有余量：平均设备利用率 {avg_global_util:.2f}%，最大设备利用率 {max_global_util:.2f}%。")
            if max_active_util > 100 or overlap_total > 0:
                st.error(
                    f"存在任务重叠或并行口径问题：max_active_window_utilization_pct={max_active_util:.2f}% ，"
                    f"overlap_count总数={overlap_total}。"
                )
            if (max_global_util - avg_global_util) >= 30:
                st.warning(
                    f"设备负载不均衡：最大利用率与平均利用率差值为 {(max_global_util - avg_global_util):.2f} 个百分点。"
                )
            if idle_ratio >= 20:
                st.warning(f"当前筛选范围内空闲时间偏高：idle占比 {idle_ratio:.2f}%。")
            if setup_ratio >= 10:
                st.warning(f"当前筛选范围内换型/setup占比较高：setup占比 {setup_ratio:.2f}%。")
            if delayed_count > 0:
                st.error(f"存在延期任务：延期任务数量 {delayed_count}。")

            if (
                max_global_util < 85
                and not (max_active_util > 100 or overlap_total > 0)
                and (max_global_util - avg_global_util) < 30
                and idle_ratio < 20
                and setup_ratio < 10
                and delayed_count == 0
            ):
                st.success("当前筛选范围内未触发主要风险诊断规则。")

    if notices:
        for n in notices:
            st.warning(n)

    # 固定工业语义图例与口径说明
    st.info(
        "工业语义图例：生产=蓝色，Setup/换型=黄色，Idle=深灰，延期=红色边框，瓶颈任务=青色高亮边框。"
    )
    st.caption(
        "KPI口径：总任务数/平均设备利用率/最大设备利用率为全量口径；"
        "当前显示任务数、setup占比、idle占比、setup/idle统计为“当前筛选 + 时间窗口 + 限流后”口径。"
    )
    st.caption("瓶颈判定规则：设备利用率 >= P90 或 >= 85%。")
    st.caption(
        "利用率口径说明：全局窗口利用率 = 设备生产时长 / 全局排程 Makespan；"
        "活跃窗口利用率 = 设备生产时长 / 该设备首尾任务时间跨度。"
    )

    # 重叠冲突告警：最大利用率超过 100% 或存在 overlap
    max_active_util_all = float(util["active_window_utilization_pct"].max()) if not util.empty else 0.0
    overlap_total_all = int(util["overlap_count"].sum()) if ("overlap_count" in util.columns and not util.empty) else 0
    if max_active_util_all > 100 or overlap_total_all > 0:
        st.warning("检测到设备任务重叠，最大利用率可能超过 100%。请确认设备是否允许并行加工，或检查排程冲突。")

    if filters.get("chart_mode") == "热力图":
        st.plotly_chart(heat_fig, use_container_width=True, config={"displaylogo": False, "scrollZoom": True})
        st.caption(
            f"热力图口径：仅统计生产任务负载；时间粒度={filters.get('heat_bucket','1h')}；"
            "颜色阈值：深色(空闲)→蓝(正常)→黄(高负载)→红(瓶颈)。"
        )
    else:
        if filters.get("view_mode") == "工单级概览":
            st.info(
                "当前为工单级概览：同一设备内同一工单已聚合显示。该视图用于降低任务密度和快速浏览工单分布，"
                "可能掩盖中间空隙、setup/idle、任务重叠等细节；精确排程诊断请切换到 Task级。"
            )
        st.markdown(
            """
            <div style="
                display:flex; flex-wrap:wrap; gap:14px; align-items:center;
                background:#0f172a; border:1px solid #1f2937; border-radius:8px;
                padding:10px 12px; margin-bottom:8px; font-size:13px; color:#d1d5db;">
              <div style="display:flex; align-items:center; gap:6px;">
                <span style="display:inline-block; width:16px; height:10px; background:#3B82F6; border:1px solid #3B82F6;"></span>
                <span>生产任务</span>
              </div>
              <div style="display:flex; align-items:center; gap:6px;">
                <span style="display:inline-block; width:16px; height:10px; background:#F59E0B; border:1px solid #F59E0B;"></span>
                <span>Setup/换型</span>
              </div>
              <div style="display:flex; align-items:center; gap:6px;">
                <span style="display:inline-block; width:16px; height:10px; background:#1F2937; border:1px solid #1F2937;"></span>
                <span>Idle/空闲</span>
              </div>
              <div style="display:flex; align-items:center; gap:6px;">
                <span style="display:inline-block; width:16px; height:10px; background:#3B82F6; border:2px solid #DC2626;"></span>
                <span>延期任务（红色边框）</span>
              </div>
              <div style="display:flex; align-items:center; gap:6px;">
                <span style="display:inline-block; width:16px; height:10px; background:#3B82F6; border:2px solid #22D3EE;"></span>
                <span>瓶颈任务（青色边框）</span>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.plotly_chart(fig, use_container_width=True, config={"displaylogo": False, "scrollZoom": True})

    st.subheader("瓶颈分析 Top10")
    if util.empty:
        st.info("无可用利用率数据")
    else:
        util_sorted = util.sort_values(
            ["global_window_utilization_pct", "overlap_minutes"],
            ascending=[False, False],
        ).reset_index(drop=True)
        show_cols = [
            "machine",
            "task_count",
            "busy_hours",
            "global_window_utilization_pct",
            "active_window_utilization_pct",
            "window_hours",
            "overlap_count",
            "overlap_minutes",
            "is_bottleneck",
        ]
        top10 = util_sorted[show_cols].head(10).copy()
        st.dataframe(top10, use_container_width=True, height=320)

    st.subheader("数据与字段识别")
    st.write({"source": input_path, "raw_rows": len(raw), "tasks_after_preprocess": len(tasks), "tasks_before_limit": before_limit})
    st.write({"mapping": mapping})
    if issues:
        st.write({"issues": issues})

    st.caption("扩展建议：接入实时调度流（Kafka/DB）、支持重排产按钮、按工厂/车间多租户路由。")


if __name__ == "__main__":
    main()
