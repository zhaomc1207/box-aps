# BOX APS 业务规则到 MILP 数学约束映射表 v7_2

## 1. 版本定位

`v7_2` 在 `v7_1` 工程压缩 + 二次修复架构之上，对 `BOX-智能排产约束规则.xlsx` 的逐条规则做闭环对齐。它不改变模型分层，仅修补了 v7/v7_1 中与规则表口径直接对不上的几处实现：

1. 规则 13.1 / 13.2 / 13.4 的交付指标 buffer 方向反了。`v7` 把 `due_end` 设成 `due + 1day`，等同于"排到 OTS 当天 + 1 天还算达成"。规则要求 `OTS - 排程日期 ≥ 2`，因此应当 `due_end = due − 2 days`。`v7_2` 通过 `ots_buffer_days / fpsd_buffer_days / ship2_buffer_days` 三个参数显式建模，默认 2。
2. 规则 13.1 / 13.2 的 "MR Day 限制的订单除外" 没有实现。`v7_2` 在 `_date_kappa` 中增加 `exempt_mr_limited` 选项：当 `mr_day_dt > due_date − buffer_days` 时把对应 KPI 的 `kappa_d^*` 置 0，避免把"物理上无法满足"的需求计入达成率。
3. 规则 13.3 "Urgent Order 优先排产" 之前只在数据层把 `om_urgent` 转成 `urgent`，目标函数从未使用。`v7_2` 在主目标 `obj1` 中给 `urgent=1` 的需求乘以 `(1 + urgent_priority_boost)`，默认 boost 1.0 → 紧急订单获得 2× 的延误惩罚权重。
4. 规则 7 "产能预留" 之前完全没有读取相关表。`v7_2` 增加可选输入 `aps_schedule_reserver_input` 与 `aps_schedule_demand_reserve_input`，并在线班产能上扣除显式预留窗口。脱敏数据中没有这两张表时优雅降级。
5. 规则 6 中 `demand_flag` 的语义此前在代码里被反向使用（`demand_flag=1` 反而被视为允许）。规则文档明确 `demand_flag=1 → 不可排 Normal 订单`，`v7_2` 修正语义；并把 `non_merge_flag / fix_type` 透传到 `line_slots` 与桶聚合，便于二阶段使用。
6. 规则 14.2 "同班次内机型合并，不可 ABABA"。`v7_1` 二阶段排序顺序为 lot → mo → model，model 排在 lot/mo 之后，仍可能出现 ABABA。`v7_2` 把 model 提前到二阶段排序的关键键，lot/mo 作为同 model 内的次级聚合键。
7. v7_1 的 FAI 二次修复迭代次数默认 1，全量数据下 508 处违规一次无法收敛。`v7_2` 将默认值提到 3。
8. v7_1 的 `consistency_capacity` 检查使用 `triples` 中的 UPH 计算锁定行 `qty/uph`，但锁定行的产能扣减在主流程是用 lock-side 兜底 UPH 完成的，单位不一致导致虚假"超产能"。`v7_2` 在 post-solve 检查里：
   - 锁定行优先用 `locked_schedule.uph` 计算 `qty/uph`；
   - 与"物理总产能 = avail + locked_occupied"对齐，避免双重扣减带来的伪违规。

## 2. 与 `v7_1` 的差异

### 2.1 交付 KPI buffer 改用业务口径

设 `H^{ots}, H^{fpsd}, H^{ship2}` 为对应 due 类型的 buffer 天数，`v7_2` 默认全部为 2。则：

```math
B_d^{ots} = \{b \in B \mid e_b \le ots_d - H^{ots}\}
```

```math
B_d^{fpsd} = \{b \in B \mid e_b \le fpsd_d - H^{fpsd}\}
```

```math
B_d^{ship2} = \{b \in B \mid e_b \le ship2_d - H^{ship2}\}
```

`miss_d` 与 `v7_1` 一致：

```math
miss_d^{ots} \ge q_d - \sum_{(l,b):(d,l,b)\in K,\ b\in B_d^{ots}} x_{dlb}
```

### 2.2 MR Day 限制订单的 KPI 豁免

记 `mr_d` 为齐套日期。当 `mr_d > due_d - H^{*}` 时，该需求物理上不可能在 buffer 内完成，因此把 KPI 评价开关置 0：

```math
\kappa_d^{ots} = \begin{cases} 0, & \text{ots}_d \text{ 缺失} \\ 0, & \text{ots}_d \text{ 存在但 } mr_d > ots_d - H^{ots} \\ 1, & \text{otherwise} \end{cases}
```

`fpsd / ship2` 同理。CLI 提供 `--no-mr-exempt-{ots,fpsd,ship2}` 关闭对应豁免。

### 2.3 Urgent 优先级权重

设 `urgent_d \in \{0,1\}` 为 `om_urgent` 标记。`v7_2` 在主目标 `obj1` 内对每个需求采用 effective 权重：

```math
W_d^{eff} = W_d^{pri} \cdot (1 + \alpha \cdot urgent_d)
```

其中 `α = urgent_priority_boost`，默认 1.0，即紧急订单的延误惩罚 / 未排惩罚翻倍。CLI 通过 `--urgent-priority-boost` 调节。

```math
\min Obj_1 = \sum_{d \in D'} W_d^{eff} \cdot (\omega_{ots}\kappa_d^{ots}miss_d^{ots} + \omega_{fpsd}\kappa_d^{fpsd}miss_d^{fpsd} + \omega_{ship2}\kappa_d^{ship2}miss_d^{ship2} + \omega_{uns}c_d)
```

### 2.4 产能预留 (规则 7)

新增可选 sheet `aps_schedule_reserver_input`，字段口径见 `data_catalog/box_aps_input_fields_explained_v2.md` 表 3.14。预处理步骤：

1. 解析 `reserved_day + reserved_start_time` / `reserved_end_time` 形成 `[start_dt, end_dt]` 区间。
2. 对每个 `(line_id, slot_id)` 与该区间求交集，得到该班次内的 `reserved_hours`。
3. 累加同一线班的所有预留窗口；并入 `_recalc_avail`：

```math
avail_{lb} = cap_{lb} - down_{lb} - reserved_{lb} - occ_{lb}^{ext} - occ_{lb}^{lock}
```

如表为空或字段无法解析，记录 `info` 级 issue 并按 0 处理。

### 2.5 二阶段排序键

```
sort_by = [line_id, slot_id, _locked_first, _source_rank, _seq_sort,
           model, lot, mo, order_ruler_keys..., demand_id]
```

排序首先把锁定行钉死，其次按 model 把同机型聚成连续段（规则 14.2），随后才按 lot/mo 在同 model 内做次级聚合，最后按 `aps_schedule_order_ruler` 配置的物料切换顺序（规则 14.4）调整 PO 内部顺序。

### 2.6 FAI 修复默认更激进

`--fai-repair-iterations` 默认从 1 提升到 3。每轮迭代会对违规 rest demand 剪掉早于 `E_g^{first,*} + lead_g` 的候选，再次求解。若仍有违规，再次迭代，直到收敛或迭代次数耗尽。

### 2.7 一致性检查与产能口径对齐

post-solve `consistency_capacity` 检查重写：

- 锁定行优先用 `locked_schedule.uph` 计算 `qty / uph_d^{lock,*}`，避免与 lock-side 兜底 UPH 解耦；
- 比对的容量改成"物理总容量 = `avail_hours` + `Σ_d∈D^lock occupied_hours`"，避免在 `eliminate_locks` 模式下双重扣减。

## 3. 默认参数对照

| 参数 | v7_1 默认 | v7_2 默认 | 含义 |
| --- | --- | --- | --- |
| `due_buffer_days` (预处理候选剪枝) | 3 | 3 | 候选窗口外保留天数 |
| `max_lines_per_demand_day` | 5 | 5 | 每 demand 每天保留线体数 |
| `max_slots_per_demand` | 60 | 60 | 每 demand 候选数 |
| `bucket_after_days` | 5 | 5 | 远期日桶起点 |
| `use_activation_binaries` | False | False | 默认不启用 z |
| `prefer_complete_demands` | True | True | qtymax 后偏向完整 demand |
| `fai_repair_iterations` | 1 | 3 | FAI 二次修复次数 |
| `eliminate_locks` | True | True | 锁定消元 |
| `enforce_fai_with_big_m` | False | False | 默认走候选窗口剪枝 |
| **`ots_buffer_days`** | n/a (隐式 -1) | **2** | OTS 达成 buffer |
| **`fpsd_buffer_days`** | n/a (隐式 -1) | **2** | FPSD 达成 buffer |
| **`ship2_buffer_days`** | n/a (隐式 -1) | **2** | ship_day_two buffer |
| **`urgent_priority_boost`** | n/a | **1.0** | 紧急订单权重倍率 |
| **`exempt_mr_limited_*`** | n/a | **True** | MR 限制订单 KPI 豁免 |

## 4. 与规则表 14 条规则的对齐结果

| 规则 | 实现位置 | 状态 |
| --- | --- | --- |
| 1 工单 | `_build_fixed_locks` + `_split_adjust_schedule` | ✅ |
| 2 订单 | `_build_demands` | ✅ |
| 3 订单 MR Date | `_apply_mr_rule` | ✅ |
| 4 排产优先级 | `_build_priority` (priority groups → priority_weight) | ✅ |
| 5 UPH 多档位 | `_lookup_uph` (model/mcode/fast_ship/cust_svc/mat_type/priority) | ✅ |
| 6 生产日历 | `_build_slots_and_line_slots` + `_apply_downtime`，v7_2 修正 `demand_flag` 语义 | ✅ |
| 7 产能预留 | v7_2 新增 `_apply_reservations` | ✅ |
| 8 产线机型匹配 | UPH 表隐含过滤 | ✅ |
| 9 客制化 / Fast Ship 优先 Cell | `non_cell_penalty_for_small_or_special` | ✅ |
| 10 FIX 限制 | `_build_fixed_locks` + 锁定消元 | ✅ |
| 11 机型限制 | `_apply_limit_rules` | ✅ |
| 12 FAI 限制 | 候选窗口剪枝 + v7_2 默认 3 轮二次修复 | ✅ |
| 13.1 OTS 达成率 | v7_2 `H^{ots}=2` + MR 豁免 | ✅ |
| 13.2 FPSD | v7_2 `H^{fpsd}=2` + MR 豁免 | ✅ |
| 13.3 Urgent | v7_2 `urgent_priority_boost` | ✅ |
| 13.4 D+2 ShipDate 优先 | priority groups (G031/G067 等) + v7_2 `H^{ship2}=2` 一致化 | ✅ |
| 14.1 机型换线最优 | `obj4 = Σ setup_{lb} + Σ g_{lmb}` | ✅ |
| 14.2 班次内机型合并 | v7_2 二阶段排序 model 优先 | ✅ |
| 14.3 排程量最多 | qtymax → `min Σ c_d` | ✅ |
| 14.4 PO 物料排序 | `aps_schedule_order_ruler` → `_sort_columns_from_demands` | ✅ |

## 5. CLI 新增开关

```
--ots-buffer-days N            # 默认 2
--fpsd-buffer-days N           # 默认 2
--ship2-buffer-days N          # 默认 2
--urgent-priority-boost X      # 默认 1.0
--no-mr-exempt-ots             # 关闭 OTS MR 豁免
--no-mr-exempt-fpsd            # 关闭 FPSD MR 豁免
--no-mr-exempt-ship2           # 关闭 ship_day_two MR 豁免
--fai-repair-iterations N      # 默认 3
```

## 6. 关键表到模型位置映射

| 表 | 模型位置 | 说明 |
| --- | --- | --- |
| `aps_schedule_demand_base_input` | `_build_demands` | demand 主表，含 `om_urgent / pre_lock / fast_ship / cust_svc / mr_day` |
| `aps_schedule_master_pn_input` | `_build_demands` PN 主数据合并 | 补 model / program / color / texture |
| `aps_schedule_line_input` | `_build_lines` | 线体集合，cell_flag 推导 |
| `aps_schedule_line_calendar` | `_build_slots_and_line_slots` | 班次时间，v7_2 修正 demand_flag 语义并透传 non_merge / fix_type |
| `aps_schedule_off_time_input` | `_apply_downtime` | 休息 / 维护时间 |
| `aps_schedule_reserver_input` (可选, v7_2 新增) | `_apply_reservations` | 显式产能预留窗口 |
| `aps_schedule_demand_reserve_input` (可选) | 当前未使用，预留接入 | demand-level 预留对象 |
| `aps_schedule_uph_input` | `_normalize_uph` + `_build_sparse_triples` | 候选 UPH，多档位选优 |
| `aps_change_time_input` | `_build_change_min` | 粗换线下界 |
| `aps_schedule_limit_setting` | `_apply_limit_rules` | 机型 / 班次 / 线体限制 |
| `aps_schedule_order_ruler` | `_build_order_keys` + 二阶段排序 | PO 物料排序 |
| `aps_schedule_order_qty` | `_apply_order_qty_rule` | 大小单 |
| `aps_schedule_priority` | `_build_priority` | 优先级分组 + KPI 模式 |
| `aps_schedule_demand_fix_input` | `_build_fixed_locks` | FIX 锁定 |
| `aps_schedule_demand_fai_input` | `_build_fai_arcs` | FAI 首件先后 |
| `aps_adjust_schedule_input` | `_split_adjust_schedule` + `_build_external_occupation` | 继承排程锁定 + 外部占能 |

## 7. 当前结论

`v7_2` 与 `v7_1` 在求解架构上一致；它把 `BOX-智能排产约束规则.xlsx` 中此前隐式 / 错配的口径补齐，主要修复点集中在交付 KPI、Urgent 优先、产能预留与日历语义。运行成本与 v7_1 接近，主要差异是 FAI 修复默认更彻底，Urgent boost 不显著放大模型规模。建议作为新的全量默认排产口径。
