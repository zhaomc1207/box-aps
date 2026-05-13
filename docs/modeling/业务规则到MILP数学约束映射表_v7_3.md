# BOX APS：业务规则与主 MILP 数学模型映射（v7\_3）

本文为**数学建模导向**的说明文档：先给出符号、集合、变量与约束的**数学表述**，再简要对应实现文件与 `BOX-智能排产约束规则.xlsx`。**v7\_3** 在 **v7\_2** 的规则口径与工程分层上**不变**，仅将**工程默认求解策略**升级为「激活变量 + FAI Big-M 硬性优先」为主流，并据此更新参数表与 CLI 说明。

---

## 0. 文档范围与模型分层

求解管线在工程上分为四层（与代码目录一致）：

1. **预处理**：输入 Excel → 规范化表 → 稀疏候选三元组集合 \(K\) 及参数（`box_aps_milp/data.py`）。
2. **主 MILP**：在 \(K\) 上分配产量、满足产能与（可选）激活/机型/交付松驰等约束（`box_aps_milp/model.py`）。
3. **二阶段**：对已定线–班产量做班内排序与规则校核（`box_aps_milp/second_stage.py`），**不**再解全局 MILP。
4. **导出**：解映射为 APS 输出表（`box_aps_milp/export.py`）。

下文**主模型**仅指第 2 层；**v7\_2 已对齐**的交付 KPI buffer、MR 豁免、Urgent 权重、产能预留、日历 `demand_flag` 语义、二阶段 model 优先排序等，**在 v7\_3 中保持相同数学含义**，不再逐条重复推导，仅在第 8 节用对照表归纳。

---

## 1. 集合与索引

| 符号                                | 含义             | 说明                                                                        |
| --------------------------------- | -------------- | ------------------------------------------------------------------------- |
| \(D\)                             | 需求（demand）集合   | 预处理得到的订单行集合；主 MILP 中可能为子集 \(D'\subseteq D\)（见锁单消元）。                       |
| \(L\)                             | 产线集合           |                                                                           |
| \(B\)                             | 时间桶（班次）集合      | 与 `slot_id` 一一对应；具有有序标量时间参数。                                              |
| \(K \subseteq D\times L\times B\) | **可行三元组**集合    | 仅当 \((d,\ell,b)\) 通过 UPH、MR、order\_qty、limit 等筛选后 ∈ \(K\)；实现中为 `triples`。 |
| \(\mathcal{L}_b\)                 | 桶 \(b\) 可用的线集合 | 与 `line_slots` 一致。                                                        |
| \(G\)                             | 机型出现指示所涉的组     | 实现中为 `(line_id, model, slot_id)`。                                         |

锁单（FIX / adjust）若采用**消元**模式，则从主问题中移除已锁需求，并将其产量从可用产能中扣除；数学上等价于缩小 \(D'\) 与 \(K\)，并在产能右端项中扣除锁定占用。

---

## 2. 参数（由预处理与业务表给出）

下列均为**输入数据或派生标量**，在主模型中为常数。

| 记号                                                              | 含义                                                                                                          |
| --------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| \(q_d \in \mathbb{Z}_{\ge 0}\)                                  | 需求 \(d\) 的总数量。                                                                                              |
| \(\mathrm{uph}_{d\ell b} > 0\)                                  | 三元组上的产能效率（单位产量/小时）；无则该三元不可行或不参与产能分母。                                                                        |
| \(\mathrm{avail}_{\ell b}\)                                     | 线 \(\ell\) 桶 \(b\) 的可用机时（已扣停机、外部占用、预留、锁单占用等，与实现一致）。                                                         |
| \(s_b,\, e_b\)                                                  | 桶 \(b\) 的起止时间标量（实现中为 `start_hour` / `end_hour` 等，用于 FAI Big-M）。                                             |
| \(\kappa_d^{ots},\kappa_d^{fpsd},\kappa_d^{ship2} \in \{0,1\}\) | 各交付 KPI 是否参与惩罚（含 MR 豁免逻辑，v7\_2）。                                                                            |
| \(W_d^{pri}\)                                                   | 优先级权重；紧急订单有效权重 \(W_d^{eff} = W_d^{pri}(1+\alpha\cdot\mathrm{urgent}_d)\)。                                   |
| \(\omega_{ots},\omega_{fpsd},\omega_{ship2},\omega_{uns}\)      | 目标中各松驰项权重。                                                                                                  |
| \(B_d^{ots},B_d^{fpsd},B_d^{ship2} \subseteq B\)                | 各 KPI 下「计为及时」的桶集合（由 due 与 buffer 天数截断，v7\_2 口径）。                                                            |
| \(\mathrm{lead}_{g} \in \mathbb{R}_{\ge 0}\)                    | FAI 组 \(g\) 的首批完工后的**最短等待时间（小时）**；由 `aps_schedule_demand_fai_input.lead_time` 与 `--fai-lead-time-unit` 换算得。 |

**FAI 弧集（预处理全量）**  
记 \(\mathcal{A}^{fai}\) 为有序对 \((d^{first}, d^{rest})\) 及组元数据；实现中 `ProcessedData.fai_arcs`。**送入主 MILP 的子集**记 \(\mathcal{A}^{milp} \subseteq \mathcal{A}^{fai}\)（实现变量名 `data_fai_arcs`）：在锁单消元时，通常**剔除**「rest 需求已被整单锁定出主问题」的弧，以免对不存在变量强加约束。

---

## 3. 决策变量（主 MILP）

主模型使用 Gurobi；类型与下列一致（实现中变量名略有缩写）。

| 变量                                                                                              | 类型      | 含义                                             |
| ----------------------------------------------------------------------------------------------- | ------- | ---------------------------------------------- |
| \(x_{d\ell b} \in \mathbb{Z}_{\ge 0}\)                                                          | 整数      | 在 \((d,\ell,b)\in K\) 上安排的产量。                  |
| \(z_{d\ell b} \in \{0,1\}\)                                                                     | 二元      | **当启用激活变量时**：\(z=1\) 表示该三元组上产量可正（与 \(x\) 联动）。  |
| \(c_d \in \mathbb{Z}_{\ge 0}\)                                                                  | 整数      | 未排产量松驰。                                        |
| \(\mathrm{miss}_d^{ots},\mathrm{miss}_d^{fpsd},\mathrm{miss}_d^{ship2} \in \mathbb{R}_{\ge 0}\) | 连续      | 交付 KPI 欠产松驰。                                   |
| \(u_d \in \{0,1\}\)                                                                             | 二元      | （在 qtymax 且偏好完整订单时）是否排满 \(q_d\)。               |
| \(e_d \in \mathbb{R}_{\ge 0}\)                                                                  | 连续      | **仅当 FAI Big-M 启用时**：需求 \(d\) 的**完工时间下界**辅助变量。 |
| \(g_{\ell m b} \in \{0,1\}\)                                                                    | 二元      | 桶 \(b\) 线 \(\ell\) 是否出现机型 \(m\)。               |
| \(h_{\ell b}\) / \(\mathrm{setup}_{\ell b}\)                                                    | 整数 / 连续 | 换线相关（粗粒度，与 `change_min` 等一致）。                  |

---

## 4. 主约束（数学形式）

以下默认考虑 **\(D'\)** 与 **\(K\)** 已在预处理后确定；为简洁仍记 \(d\in D\)、\((d,\ell,b)\in K\)。

### 4.1 需求平衡

\[
\sum_{(\ell,b):(d,\ell,b)\in K} x_{d\ell b} + c_d = q_d \quad \forall d\in D'
\]

### 4.2 激活与（可选）单线单桶

若启用二元变量 \(z\)（v7\_3 **默认启用**）：

\[
x_{d\ell b} \le q_d\, z_{d\ell b},\quad x_{d\ell b} \ge z_{d\ell b} \quad \forall (d,\ell,b)\in K
\]

\[
\sum_{\ell:(d,\ell,b)\in K} z_{d\ell b} \le 1 \quad \forall d\in D',\; b\in B
\]

（同一需求同一桶最多一条线出现正产量。）

若 `elig` 标记为 0 的三元组，实现中另有上界 \(x_{d\ell b}\le 0\)。

### 4.3 产能

\[
\sum_{(d,\ell,b)\in K:\,(\ell,b)=(\ell_0,b_0)} \frac{x_{d\ell b}}{\mathrm{uph}_{d\ell b}} + \mathrm{setup}_{\ell_0 b_0} \le \mathrm{avail}_{\ell_0 b_0}
\]

（实现中对 \(\mathrm{uph}=0\) 的项跳过。）

### 4.4 交付松驰（与 v7\_2 桶集合一致）

\[
\mathrm{miss}_d^{ots} \ge q_d - \sum_{\substack{(d,\ell,b)\in K\\ b\in B_d^{ots}}} x_{d\ell b}
\]

FPSD、ship2 同理。

### 4.5 FAI 先后（Big-M 模式，v7\_3 **默认**）

**前提**：`enforce_fai_with_big_m` 与 `use_activation_binaries` 同时为真（否则走剪枝+修复，见第 5 节）。

取足够大的 \(M\)（实现中由时间轴推导）。定义辅助变量 \(e_d\) 满足：若 \(z_{d\ell b}=1\)，则 \(e_d \ge e_b\)（桶结束时间标量）。

\[
e_d \ge e_b - M(1-z_{d\ell b}) \quad \forall d,\;\forall (d,\ell,b)\in K
\]

对每条送入模型的 FAI 弧 \((d^{first},d^{rest}) \in \mathcal{A}^{milp}\)（含等待 \(\mathrm{lead}\)）及每个 \((d^{rest},\ell,b)\in K\)：

\[
s_b + M(1-z_{d^{rest}\ell b}) \ge e_{d^{first}} + \mathrm{lead}
\]

含义：若 rest 在某桶开工（\(z=1\)），则该桶开始时间不早于「first 的完工下界 + lead」。  
**注意**：该表述使用**桶级标量时间**；二阶段使用**日历时间 min/max** 对**全量** \(\mathcal{A}^{fai}\) 再验一次，二者集合与时间聚合可能不一致，故二阶段 `fai_violation_count` 在 Big-M 开启时仍可能非零（见第 6 节）。

### 4.6 机型出现与换线（略）

与 v7 / v7\_1 / v7\_2 相同：用 \(g_{\ell m b}\) 将「某线某桶是否出现某 model」与 \(z\) 或 \(x\) 关联，并进入 `setup` 与目标 \(\mathrm{Obj}_4\)。细节见实现 `model.py` 8.12 节。

### 4.7 锁单不进主问题时的处理

若 `eliminate_locks=True`：已锁需求 \(d\notin D'\)，其产量从 \(\mathrm{avail}\) 扣减；FAI 弧集用 \(\mathcal{A}^{milp}\) 相对 \(\mathcal{A}^{fai}\) 裁剪。**未**出现在 \(D'\) 的 first/rest 不会生成 Big-M 行（实现中 `continue`）。

---

## 5. FAI 的两种工程模式（与 v7\_3 默认）

| 模式               | 开关                                                             | 主模型行为                                                              | 事后修复                                             |
| ---------------- | -------------------------------------------------------------- | ------------------------------------------------------------------ | ------------------------------------------------ |
| **A. Big-M 硬约束** | `enforce_fai_with_big_m=True` 且 `use_activation_binaries=True` | 第 4.5 节约束生效；**不**再对 rest 做窗口剪枝（实现中跳过 `_prune_fai_rest_candidates`） | `fai_repair_iterations` 在实现中取 **0** 轮（无需基于剪枝的迭代） |
| **B. 轻量模式**      | `enforce_fai_with_big_m=False`                                 | 仅用 `_prune_fai_rest_candidates` 缩小 \(K\)；**不**保证可行                 | 最多执行 `fai-repair-iterations` 轮剪枝重解               |

**v7\_3 默认采用模式 A**（与当前 `ModelConfig` / CLI `set_defaults` 一致）。轻量试算可加 `--no-enforce-fai-with-big-m`。

---

## 6. 二阶段与全量 FAI 校核的差异（建模说明）

二阶段对每条 **\(\mathcal{A}^{fai}\)** 弧，用解中该 `demand_id` 的 **最早 `shift_start_time`** 与 **最晚 `shift_end_time`** 与 \(\mathrm{lead}\) 比较。这与主模型中 **桶标量 \(s_b,e_b\)** + **\(e_d\) 下界** 的联合并不保证逐弧数值完全一致；再叠加 **\(\mathcal{A}^{fai}\setminus \mathcal{A}^{milp}\)** 中弧未被主模型约束，**`fai_violation_count` 可为正**。因此二阶段报告宜解读为**可执行性审计**，而非「主模型未加 FAI」的唯一判据。

---

## 7. 目标函数（分层字典序 / Gurobi `setObjectiveN`）

与 v7\_2 一致，主问题为**多目标**，实现中按优先级从高到低（示例）：

1. \(\mathrm{Obj}_1\)：加权交付松驰 + 未排惩罚（使用 \(W_d^{eff}\) 与 \(\kappa\)）。  
2. \(\mathrm{Obj}_2\)：KPI 模式相关（如 qtymax 时最小化 \(\sum c_d\) 等）。  
3. \(\mathrm{Obj}_3\)：线体/Cell 偏好成本。  
4. \(\mathrm{Obj}_4\)：粗换线与机型出现惩罚。

具体系数与 `prefer_complete_demands` 分支见 `model.py`。

---

## 8. 默认参数：v7\_2 → v7\_3 变更对照

| 参数 / CLI                                                   | v7\_2 默认 | **v7\_3 默认**                                         | 说明                                                 |
| ---------------------------------------------------------- | -------- | ---------------------------------------------------- | -------------------------------------------------- |
| `use_activation_binaries`                                  | False    | **True**                                             | 启用 \(z\) 与「同需求同桶至多一线」                              |
| `enforce_fai_with_big_m`                                   | False    | **True**                                             | 默认 FAI 模式 A（硬约束）；试算可 `--no-enforce-fai-with-big-m` |
| `fai_repair_iterations`                                    | 3        | **1**                                                | Big-M 默认下多为 0 轮有效修复；轻量模式可调大                        |
| `fai_lead_time_unit`（预处理）                                  | hours    | 仍默认 **hours**；业务为分钟时传 `--fai-lead-time-unit minutes` | 与 README / runbook 示例一致                            |
| 其余 v7\_2 项（buffer=2、MR 豁免、Urgent boost、产能预留、二阶段 model 优先等） | 同 v7\_2  | **不变**                                               |                                                    |

---

## 9. CLI 摘要（v7\_3）

与 FAI / 激活相关的当前约定：

```
--use-activation-binaries      # 默认已开
--no-activation-binaries       # 关闭 z（则 Big-M FAI 不会添加）

--enforce-fai-with-big-m       # 默认已开
--no-enforce-fai-with-big-m    # 退回窗口剪枝 + fai-repair

--fai-repair-iterations N      # 默认 1（Big-M 下通常不触发迭代）
--fai-lead-time-unit {minutes,hours,days}
```

交付 KPI、MR 豁免、Urgent 等开关与 v7\_2 文档相同（`--ots-buffer-days` 等）。

---

## 10. 业务规则 14 条与实现位置（与 v7\_2 一致，规则 12 更新表述）

| 规则                            | 实现位置                                              | v7\_3 备注        |
| ----------------------------- | ------------------------------------------------- | --------------- |
| 1 工单                          | `_build_fixed_locks` + `_split_adjust_schedule`   |                 |
| 2 订单                          | `_build_demands`                                  |                 |
| 3 MR Date                     | `_apply_mr_rule`                                  |                 |
| 4 优先级                         | `_build_priority`                                 |                 |
| 5 UPH                         | `_lookup_uph` + `_build_sparse_triples`           |                 |
| 6 生产日历                        | `_build_slots_and_line_slots` + `_apply_downtime` |                 |
| 7 产能预留                        | `_apply_reservations`                             |                 |
| 8 产线机型                        | UPH 隐含                                            |                 |
| 9 Cell 偏好                     | `non_cell_penalty_for_small_or_special`           |                 |
| 10 FIX                        | 锁单 + 消元 / 或进模型                                    |                 |
| 11 机型限制                       | `_apply_limit_rules`                              |                 |
| **12 FAI**                    | **`_build_fai_arcs`；主模型默认 Big-M + \(z\)；可选剪枝模式**  | **v7\_3 默认硬约束** |
| 13.1–13.4 交付与 Urgent          | buffer + κ + `urgent_priority_boost`              | 同 v7\_2         |
| 14.1–14.4 换线 / qtymax / PO 排序 | `obj4` + 二阶段排序                                    | 同 v7\_2         |

---

## 11. 关键输入表 → 模型对象（与 v7\_2 相同）

见 v7\_2 文档第 6 节表；或 `docs/data_catalog/box_aps_input_fields_explained_v2.md`。**v7\_3 不新增必选表**。

---

## 12. v7\_3 版本小结

- **数学规则集合**：继承 v7\_2（交付 buffer、MR 豁免、Urgent、预留、日历语义、二阶段 ABABA、产能一致性校准等）。  
- **求解器默认拓扑**：升级为 **\(z\)  activation 默认开启** + **FAI Big-M 默认开启**，使「同桶单线」与「FAI 在 MILP 内硬满足（在 \(\mathcal{A}^{milp}\) 与时间离散口径下）」成为默认路径。  
- **文档体裁**：本节将原「changelog 罗列」收口为 **集合–变量–约束–目标–双模式 FAI** 的建模叙述，并与工程开关对齐。

若需回溯 v7\_2 的逐条补丁说明原文，请参阅 `业务规则到MILP数学约束映射表_v7_2.md` 第 1–2 节。
