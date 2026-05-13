# BOX APS MILP

本项目用于把 BOX APS 输入表转换为 MILP 排产模型，并输出 APS 结果表。

## 推荐入口

优先使用一键命令：

```bash
.venv/bin/python -m box_aps_milp run-all \
  --input "data/input/BOX-APS脱敏数据-2.xlsx" \
  --processed outputs/run_001/processed \
  --solution outputs/run_001/solution.csv \
  --summary outputs/run_001/summary.json \
  --gurobi-log-file outputs/run_001/gurobi.log \
  --fai-lead-time-unit minutes \
  --output-dir outputs/run_001/box_output_tables \
  --source-input "data/input/BOX-APS脱敏数据-2.xlsx" \
  --time-limit 600 \
  --mip-gap 0.05 \
  --threads 32
```

该命令会依次执行：

1. 数据处理：`box_aps_milp/data.py`
2. 主模型求解：`box_aps_milp/model.py`
3. 二阶段处理：`box_aps_milp/second_stage.py`
4. 输出表导出：`box_aps_milp/export.py`

详细说明见 `docs/runbook/README_box_aps_milp.md`。

## 目录说明

- `box_aps_milp/`：主代码包
- `run_box_aps.py`：兼容旧用法的 CLI 入口
- `data/input/`：排产输入数据
- `data/rules/`：业务规则 Excel
- `data/reference/`：APS 输出/输入表目录
- `docs/modeling/`：MILP 数学模型版本文档
- `docs/business/`：业务交流和规则梳理文档
- `docs/questions/`：待确认问题清单
- `docs/data_catalog/`：数据字段与表映射说明
- `docs/runbook/`：详细运行说明
- `outputs/`：运行产物目录，已被 `.gitignore` 忽略
- `docs/modeling/业务规则到MILP数学约束映射表_v7_2.md`：当前工程模型口径
- `docs/runbook/README_box_aps_milp.md`：运行命令和模型说明

## 当前模型口径

当前默认版本是 `v7_2`，在 `v7_1` 工程压缩 + 二次修复架构上对齐 `BOX-智能排产约束规则.xlsx` 的全部 14 条规则：

- 交付 KPI（OTS/FPSD/ship_day_two）按业务规则 13.1/13.2/13.4 采用 `due − 2 days` 的 buffer，并对 MR 限制订单做 KPI 豁免。
- Urgent 订单（规则 13.3）通过 `urgent_priority_boost` 在 `obj1` 中获得 2× 默认权重。
- 产能预留（规则 7）通过可选 `aps_schedule_reserver_input` 显式扣减线班产能。
- 二阶段排序按规则 14.2 把同 model 聚成连续段，避免 ABABA。
- FAI 二次修复迭代默认 3 次，更易收敛。
- 容量一致性检查与锁定行 UPH 兜底口径对齐，消除虚假超产能告警。
- `qtymax` 模式下保持完整 demand 次级目标和软线体偏好。

