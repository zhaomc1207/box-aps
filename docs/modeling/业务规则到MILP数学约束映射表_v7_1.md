# BOX APS业务规则到 MILP 数学约束映射表 v7_1

## 1. 版本定位

`v7_1` 是 `v7` 的工程增强版，目标是“适当增加求解时间换取目标值与可执行性的提升”。它不改变 `v7` 的总体分层（预处理 / 候选压缩 / 主 MILP / 二阶段细排），而是针对 `v7` 中识别出的几处“近似过紧”或“后果不可观测”的位置做修补。

经过一次全量实测后，`v7_1` 的默认策略从“全量启用 `z`”调整为“候选放宽 + 默认不启用全量 `z` + 完整 demand 次级目标 + FAI 二次修复”。原因是全量 `z` 会把模型变成过重的强整数模型，在 600 秒内虽然能出解，但实际业务指标变差：完整完成 demand 数明显下降，交付 miss 变大。

1. 适度放宽候选压缩，给主 MILP 更多解空间。
2. 默认不启用全量候选启用变量 `z_{dlb}`；仅在严格单线场景显式开启。
3. 改进锁定订单的产能占用计算，避免 UPH 缺失时把占用错算成 0 而高估剩余产能。
4. 在 `qtymax` 模式下增加“完整 demand 数最大化”作为次级目标，避免为了少量数量增益牺牲大量完整订单。
5. FAI 默认仍按候选窗口剪枝，但若解中出现违反，则进入二次修复：剪掉违反 rest demand 的过早候选并重新求解。
6. 主模型解出后做一次结果一致性检查（同 demand 同桶单线、锁定保留、产能未超限），可观测性增强。

`v7_1` 的所有放宽都保留在“可调”范围内：保留 `--use-activation-binaries`、`--no-eliminate-locks`、`--enforce-fai-with-big-m`、`--fai-repair-iterations` 等开关，业务可在不同严格程度下切换。

## 2. 与 `v7` 的差异

### 2.1 候选压缩参数适度放宽

`v7` 默认 `K^{line}=3, K^{slot}=30, H^{due}=2, H^{bucket}=3`，候选数压到约 20 万；
`v7_1` 把默认参数调整为：

- 每 demand 每天最多候选线体数：`K^{line} = 5`（`v7` 是 3）
- 每 demand 最多候选数：`K^{slot} = 60`（`v7` 是 30）
- 交期 buffer 天数：`H^{due} = 3`（`v7` 是 2）
- 远期日桶起点：`H^{bucket} = 5`（`v7` 是 3）

预计候选规模约为 `v7` 的 1.5~2 倍，主 MILP 求解时间随之上升，但能显著降低“最优解被剪掉”的风险，尤其当某个 demand 在主选 3 条线被产能挤掉时仍可能在第 4、5 条线找到位置。

### 2.2 默认不启用全量候选启用变量 `z_{dlb}`

`v7` 默认不创建 `z_{dlb}`，因此“同一 demand 同一时间桶最多一条线”不被强制；解中可能出现同一 demand 在同一桶被拆分到多条线，需要二阶段后处理。

最初的 `v7_1` 试验曾默认开启 `use_activation_binaries`，但全量结果显示该策略导致模型过重：候选数放宽后再叠加 50 万级二进制变量，600 秒内出解质量反而差于 `v7`。因此当前 `v7_1` 默认仍不创建 `z_{dlb}`，只在用户显式传入 `--use-activation-binaries` 时创建：

- `z_{dlb} \in \{0,1\}, \forall (d,l,b) \in K`

并恢复以下硬约束：

- `x_{dlb} \le q_d \cdot z_{dlb}, \forall (d,l,b) \in K`
- `x_{dlb} \ge z_{dlb}, \forall (d,l,b) \in K`
- `\sum_{l:(d,l,b)\in K} z_{dlb} \le 1, \forall d, b`

代价是约 50 万级二进制变量。建议只在小规模、局部重排或业务强制要求“同 demand 同桶单线”时开启；全量默认通过事后一致性检查发现拆分风险，再交给二阶段修复。

### 2.3 锁定订单的占用产能改用 `model+line` 兜底 UPH

`v7` 在 `_build_locked_schedule` 中，锁定记录的 UPH 通过查询当前主模型 `triples` 表得到。如果该 `(d,l,t)` 在剪枝中被删除或在 UPH 表中没有匹配项，`matched_uph = 0`，对应 `occupied_hours = 0`，相当于不扣产能。这会让其他 demand 误以为线班还空着。

`v7_1` 改为多级兜底：

1. 先查 `triples` 表中精确 `(d,l,b)` 的 UPH。
2. 不命中则在原始 UPH 表中按 `(model, line)` 的最优 UPH 兜底。
3. 仍不命中则按该 demand 在所有线上的最大 UPH 兜底。
4. 全部失败时退回到 `v7` 的“占用 0 + warning”，但 `issues` 升级为 `error` 级。

在工程实现上：

```math
occ_{lb}^{lock} = \sum_{d \in D^{lock}: l_d^{lock}=l, b_d^{lock}=b} \frac{q_d^{lock}}{uph_d^{lock,*}}
```

其中 `uph_d^{lock,*}` 按上述四级兜底取得，相比 `v7` 大幅降低产能高估的概率。

### 2.4 `qtymax` 下增加完整 demand 次级目标

`v7` 在 `qtymax` 模式下第二层目标为：

```math
\min Obj_2 = \sum_{d \in D'} c_d
```

它只关心总未排数量，不区分“完整完成 100 个小 demand”和“每个 demand 都排一部分”。全量实测中，候选放宽后确实能多排少量数量，但会显著减少完整完成 demand 数，这不符合实际排产业务偏好。

因此 `v7_1` 在 `qtymax` 后新增一层轻量次级目标：

```math
\max Obj_3 = \sum_{d \in D'} u_d
```

其中：

```math
\sum_{(l,b):(d,l,b)\in K} x_{dlb} \ge q_d \cdot u_d
```

```math
\sum_{(l,b):(d,l,b)\in K} x_{dlb} \le q_d - (1-u_d)
```

该改动只增加 demand 级二进制变量，约 2 万个，比全量候选级 `z_{dlb}` 轻很多；它不会牺牲第一层交付和第二层排产量，只在数量相近时偏向完整完成更多 demand。

### 2.5 FAI 默认剪枝模式 + 二次修复

`v7` 的 FAI 默认按候选窗口剪枝（即 rest demand 候选必须满足 `a_b \ge \widehat{E}_g^{first} + lead_g`），其中 `\widehat{E}_g^{first}` 是首件最早可能完工时间。但首件实际可能被产能或优先级挤到更晚的班次，rest 实际仍可能被排得过早，模型层面看不出来。

`v7_1` 默认仍先走候选窗口剪枝（保规模），但在 `extract_solution` 之后增加 FAI 修复循环：

对每个 FAI 组 `g`：

- 取首件 `d_g^{first}` 在解中的最晚完工时刻 `E_g^{first,*}`
- 对每个 rest `r \in D_g^{rest}`，取其在解中的最早开始时刻 `S_r^*`
- 若 `S_r^* < E_g^{first,*} + lead_g`，则在 `issues` 写入：

若违反，则记录修复阈值：

```math
a_b \ge E_g^{first,*} + lead_g
```

对这些违反的 rest demand，剪掉早于该阈值的候选，然后重新求解。默认 `--fai-repair-iterations=1`，即最多做一次二次修复；若业务希望完全收敛，可提高该值。该策略比全量 FAI Big-M 轻，比单纯事后告警更有效。

业务对 FAI 严格的场景仍可加 `--enforce-fai-with-big-m`，自动联动 `--use-activation-binaries`，即 `v6/v7 严格模式`。

### 2.6 主模型结果事后一致性检查

`v7_1` 在 `extract_solution` 完成后增加三类一致性检查：

1. **锁定保留**：每个 `d \in D^{lock}` 在结果中应至少存在一行 `(line, slot) = (l_d^{lock}, b_d^{lock})`，数量不小于 `q_d^{lock}`。
2. **同 demand 同桶单线**：每个 `(d, b)`，结果中出现的 `line_id` 数量应 `≤ 1`。
3. **线班产能未超限**：对每个 `(l, b)`，`\sum_d \frac{x_{dlb}^*}{uph_{dlb}} + setup_{lb}^* \le avail_{lb} + 1e-3`，其中 `1e-3` 为浮点容差。

任一项违反在 `issues` 中以 `error` 级别记录；可写入 `summary.consistency`，便于持续集成或运维监控。

## 3. 主模型完整描述（仅列出与 `v7` 的差异）

### 3.1 决策变量（默认）

新增（默认创建）：

- 完整完成变量：`u_d \in \{0,1\}, \forall d \in D'`

可选创建：

- 候选启用变量：`z_{dlb} \in \{0,1\}, \forall (d,l,b) \in K`

### 3.2 主模型新增/恢复的约束

默认新增完整完成变量联动：

```math
\sum_{(l,b):(d,l,b)\in K} x_{dlb} \ge q_d \cdot u_d
```

```math
\sum_{(l,b):(d,l,b)\in K} x_{dlb} \le q_d - (1-u_d)
```

若开启 `--use-activation-binaries`，再恢复：

```math
x_{dlb} \le q_d \cdot z_{dlb}, \quad \forall (d,l,b) \in K
```

```math
x_{dlb} \ge z_{dlb}, \quad \forall (d,l,b) \in K
```

```math
\sum_{l:(d,l,b)\in K} z_{dlb} \le 1, \quad \forall d \in D', b \in B
```

机型出现变量联动同步切换为：

```math
\sum_{(d,l,b)\in K_{lmb}} z_{dlb} \le |K_{lmb}| \cdot g_{lmb}
```

```math
g_{lmb} \le \sum_{(d,l,b)\in K_{lmb}} z_{dlb}
```

### 3.3 主模型未改变的部分

需求平衡、线体时间桶产能、交付 miss 等均与 `v7` 一致。目标层级调整为：

1. 交付达成与主优先级
2. `qtymax` 总排产量最大化 / 未排量最小化
3. 完整 demand 数最大化
4. 线体与 Cell 线偏好
5. 粗粒度效率

## 4. 默认参数对照

| 参数 | `v7` 默认 | `v7_1` 默认 | 含义 |
| --- | --- | --- | --- |
| `due_buffer_days` | 2 | 3 | 交期窗口外保留天数 |
| `max_lines_per_demand_day` | 3 | 5 | 每 demand 每天保留的最优线体数 |
| `max_slots_per_demand` | 30 | 60 | 每 demand 最大候选数 |
| `bucket_after_days` | 3 | 5 | 远期日桶起点 |
| `use_activation_binaries` | False | False | 是否创建 `z_{dlb}` |
| `prefer_complete_demands` | - | True | `qtymax` 后偏向完整完成 demand |
| `fai_repair_iterations` | - | 1 | FAI 违反后二次修复次数 |
| `eliminate_locks` | True | True | 锁定消元（不变） |
| `enforce_fai_with_big_m` | False | False | 默认仍走候选窗口剪枝 |

## 5. 关键表到模型位置映射

与 `v7` 完全一致，无新增表/字段口径。

## 6. 当前结论

`v7_1` 不替代 `v7`：业务规则、模型分层、变量符号体系完全保持一致。当前默认策略是“放宽候选 + 保持主模型相对轻量 + 完整订单偏好 + FAI 二次修复”。它比全量启用 `z` 更适合作为默认全量求解口径；若业务需要严格单线或严格 FAI，可通过 `--use-activation-binaries` 或 `--enforce-fai-with-big-m` 显式升级为更重的严格模式。
