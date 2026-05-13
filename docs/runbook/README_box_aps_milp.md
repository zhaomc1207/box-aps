# BOX APS MILP 代码说明

本目录把 `docs/modeling/业务规则到MILP数学约束映射表_v7_2.md` 中的工程模型落成了四段流水线：

- `box_aps_milp/data.py`：数据处理，完成 demand 归并、PN 主数据补齐、日历产能扣减、UPH 匹配、锁定/继承、外部占能、优先级和候选压缩。
- `box_aps_milp/model.py`：主模型求解，用 Gurobi 建立主 MILP，决定 demand 在线体/时间桶上的排产数量。
- `box_aps_milp/second_stage.py`：二阶段处理，做班内排序、锁定顺序锚定、FAI/产能/拆分校验和局部换线统计。
- `box_aps_milp/export.py`：按 `data/reference/APS系统数据表目录.xlsx` 输出 BOX APS 结果表。

## 一键运行

推荐使用 `run-all` 一次完成“数据处理 -> 主模型求解 -> 二阶段处理 -> 输出表导出”：

```bash
.venv/bin/python -m box_aps_milp run-all \
  --input "data/input/BOX-APS脱敏数据-2.xlsx" \
  --processed outputs/processed_v7_1_full \
  --solution outputs/solution_v7_1_full.csv \
  --summary outputs/solve_v7_1_full.json \
  --gurobi-log-file outputs/gurobi_v7_1_full.log \
  --fai-lead-time-unit minutes \
  --output-dir outputs/box_output_tables_v7_1_full \
  --source-input "data/input/BOX-APS脱敏数据-2.xlsx" \
  --time-limit 600 \
  --mip-gap 0.05 \
  --threads 32
```

该命令会生成：

- 预处理表：`outputs/processed_v7_1_full/`
- 二阶段后的排产解：`outputs/solution_v7_1_full.csv`
- 求解摘要与二阶段校验报告：`outputs/solve_v7_1_full.json`
- Gurobi 日志：`outputs/gurobi_v7_1_full.log`
- APS 输出表：`outputs/box_output_tables_v7_1_full/`

## 分步运行

## 运行预处理

可以先运行预处理：

```powershell
python run_box_aps.py preprocess --input "data/input/BOX-APS脱敏数据-2.xlsx" --output outputs\processed --horizon-days 3 --max-demands 200
```

完整数据去掉 `--horizon-days` 和 `--max-demands`：

```powershell
python run_box_aps.py preprocess --input "data/input/BOX-APS脱敏数据-2.xlsx" --output outputs\processed_full
```

## Gurobi 求解

在装有 Gurobi 与 `gurobipy` 的 Python 环境中运行：

```powershell
python run_box_aps.py solve --processed outputs\processed --output outputs\solution.csv --time-limit 600 --mip-gap 0.01
```

也可以边预处理边求解：

```powershell
python run_box_aps.py solve --input "data/input/BOX-APS脱敏数据-2.xlsx" --horizon-days 3 --max-demands 200 --output outputs\solution.csv
```

## 导出 APS 输出表

求解完成后，可把解映射成 `data/reference/APS系统数据表目录.xlsx` 中的 BOX 输出表 CSV：

```bash
.venv/bin/python run_box_aps.py export-outputs \
  --solution outputs/solution_optimized_full.csv \
  --processed outputs/processed_optimized_full \
  --source-input "data/input/BOX-APS脱敏数据-2.xlsx" \
  --output-dir outputs/box_output_tables_full \
  --run-version ASSY260310001 \
  --sub-schedule-version ASSY260310001001 \
  --schedule-line-version 1
```

当前会生成 `aps_adjust_schedule_output.csv`、`aps_schedule_change_line.csv` 和 `aps_schedule_result.csv`。`--source-input` 用于补齐原始输入中的 `plant/thermal/material_sections/shift/fix_shift` 等字段。

## 服务器部署建议

推荐在服务器上用虚拟环境安装：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

安装后可以不依赖仓库当前目录，直接调用命令：

```bash
box-aps-milp preprocess \
  --input /data/input/BOX-APS脱敏数据-2.xlsx \
  --output /data/aps_runs/run_001/processed \
  --log-file /data/aps_runs/run_001/preprocess.log
```

求解时建议同时输出应用日志、Gurobi 日志和机器可读摘要：

```bash
box-aps-milp solve \
  --processed /data/aps_runs/run_001/processed \
  --output /data/aps_runs/run_001/solution.csv \
  --summary /data/aps_runs/run_001/solve_summary.json \
  --log-file /data/aps_runs/run_001/solve.log \
  --gurobi-log-file /data/aps_runs/run_001/gurobi.log \
  --fai-lead-time-unit minutes \
  --time-limit 3600 \
  --mip-gap 0.01 \
  --threads 16 
```

也支持模块方式运行：

```bash
python -m box_aps_milp preprocess --input /data/input.xlsx --output /data/processed
```

服务器运行前需要确认：

- Gurobi 已安装，且 `gurobipy` 与服务器 Python 版本匹配。
- License 可用，例如已配置 `GRB_LICENSE_FILE`，或可访问 Gurobi token/license server。
- 输入、输出、日志目录对运行账号有读写权限。
- 生产全量求解不要传 `--max-demands`；`--horizon-days` 仅用于限制排产窗口或做小样本压测。

## 重要口径

- 主模型以 `demand_id` 为排产对象；样例数据中重复的 `demand_id` 会先按 demand 级归并，数量取 `qty` 最大值。
- `aps_schedule_priority` 按 `priority_group` 做组内且、组间或，最终取命中的最小 `priority`。
- `FIX` 和当前 demand 的 `aps_adjust_schedule_input` 按整单精确锁定。
- 不在当前 demand 集合中的 `aps_adjust_schedule_input` 记录只扣减对应线班可用产能。
- UPH 优先按同 `mcode + model + line + slot` 精确匹配；若某个 demand 的 `mcode` 在 UPH 表中没有精确记录，则按同 `model + line + slot` 兜底匹配。这是为了兼容样例数据中 demand 存在 `LN`、但 UPH 只有 `TN/LD/DT/CB` 的情况。
- `ship_day_two` 用于 D+2 出货目标。
- `aps_schedule_demand_fai_input.lead_time` 默认按小时解释；如业务确认是分钟，可传 `--fai-lead-time-unit minutes`。
- `aps_schedule_order_ruler` 已预处理为二阶段细排的排序键；v6 建议二阶段采用启发式或局部小模型，因此当前代码先完成主 MILP。
- 全量数据下候选三元组约 244 万，默认不添加 `e_d` 的精确上界约束以降低建模压力；如果需要完全贴近 v6 的完工时刻上下界定义，可在求解命令中加 `--completion-upper`。
