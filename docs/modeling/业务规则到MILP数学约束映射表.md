# BOX APS业务规则到 MILP 数学约束映射表

## 1. 文档目的

本文在 [规则梳理.md](D:\box-aps\规则梳理.md) 的基础上，进一步把业务规则翻译为可落地的 MILP 建模语言。  
写法上我采用了笔记本电脑主板/装配类离散制造的排产视角，但所有映射都严格基于当前 BOX APS 的数据目录与规则清单。

本文重点回答四个问题：

1. 每条业务规则在 MILP 中应建成硬约束还是软约束。
2. 需要哪些集合、参数、决策变量。
3. 各规则对应的典型数学表达是什么。
4. 哪些规则建议直接进 MILP，哪些更适合预处理或启发式协同。

## 2. 建模范围与抽象层级

结合当前 BOX APS 数据结构，建议以“需求-线体-日期-班次”为主建模粒度。

原因如下：

- 业务输入天然按 `demand_id`、`line_id`、`day`、`shift_seq` 管理。
- UPH、日历、线体限制、FIX、FAI 等规则都可以映射到班次级。
- 若直接做到秒级/分钟级连续时间 MILP，模型规模会迅速膨胀，不利于业务落地。

因此，推荐的主模型采用：

- 主决策层：班次级分配与排序
- 细排层：班内顺序和时间块展开

如果后续要进一步细化到班内分钟级时间块，可在本模型上追加二阶段时序模型。

## 3. 集合、索引、参数、变量定义

### 3.1 集合与索引

- `d ∈ D`：需求集合，对应 `demand_id`
- `l ∈ L`：线体集合，对应 `line_id`
- `t ∈ T`：排产时段集合，建议定义为 `(day, shift_seq)` 的组合
- `m ∈ M`：机型集合，对应 `model`
- `p ∈ P`：料号集合，对应 `pn`
- `g ∈ G_fai`：FAI 分组集合，对应 `group_id`
- `k ∈ K`：优先级规则集合

辅助子集：

- `D_fix`：存在 FIX 要求的需求集合
- `D_fai`：存在 FAI 规则的需求集合
- `D_fast`：Fast Ship 需求集合
- `L_cell`：Cell 线集合
- `L_normal`：普通线集合
- `A_d`：需求 d 的可行线体集合
- `T_d`：需求 `d` 的可行班次集合

### 3.2 输入参数

以下参数均可从现有 BOX APS 表结构推导：

- `q_d`：需求数量，来自 `aps_schedule_demand_base_input.qty`
- `mr_d`：MR Date，来自 `mr_day`
- `due_d^ots`：OTS 日期，来自 `ots_date`
- `due_d^fpsd`：FPSD 日期，来自 `fpsd`
- `due_d^ship`：Ship Date，来自 `ship_date`
- `urgent_d`：紧急标记，来自 `om_urgent`
- `prelock_d`：预锁标记，来自 `pre_lock`
- `fast_d`：Fast Ship 标记，来自 `fast_ship`
- `fix_d`：FIX 标记，来自 `fix_flag`
- `model_d`：需求机型，来自 `model`
- `mcode_d`：业务分类，来自 `mcode`
- `uph_dlt`：需求 `d` 在线体 `l`、班次 `t` 的单位小时产能
- `cap_lt`：线体 `l` 在班次 `t` 的净可用工时
- `res_lt`：线体 `l` 在班次 `t` 的预留工时
- `down_lt`：线体 `l` 在班次 `t` 的停机/休息工时
- `elig_dlt ∈ {0,1}`：需求 `d` 是否允许在线体 `l`、班次 `t` 排产
- `chg_{m1,m2}`：从机型 `m1` 切到 `m2` 的换线时间
- `seqpref_{d1,d2,l}`：在线体 `l` 上，需求 `d1` 在 `d2` 前是否更优
- `small_d ∈ {0,1}`：小单标记，可由 `aps_schedule_order_qty_setting_input` 与 `q_d` 推导

对班次净产能，推荐预处理为：

`avail_lt = cap_lt - res_lt - down_lt`

其中：

- `cap_lt` 来自日历班次总时长
- `res_lt` 来自产能预留
- `down_lt` 来自休息/维护/off time

### 3.3 决策变量

推荐使用以下主变量：

- `x_dlt ≥ 0`，整数：需求 `d` 在 `(l,t)` 上排产的数量
- `z_dlt ∈ {0,1}`：需求 `d` 是否在线体 `l`、班次 `t` 上排产
- `u_d ∈ {0,1}`：需求 `d` 是否至少排到一部分
- `c_d ≥ 0`：需求 `d` 未排数量

若要在班内显式表达顺序，再增加：

- `y_{d1,d2,l,t} ∈ {0,1}`：在线体 `l`、班次 `t` 上，`d1` 是否排在 `d2` 前
- `s_d`：需求 `d` 的开始班次序号或开始时间
- `e_d`：需求 `d` 的结束班次序号或结束时间

若只做班次级模型，可不显式建连续时间变量，而把排序相关内容放入二阶段细排。

## 4. 基础约束框架

### 4.1 需求平衡约束

每个需求的已排量与未排量之和等于总需求量：

`∑_{l∈L} ∑_{t∈T} x_dlt + c_d = q_d , ∀d ∈ D`

如果要求不允许超排：

`∑_{l∈L} ∑_{t∈T} x_dlt ≤ q_d , ∀d ∈ D`

### 4.2 变量联动约束

若需求未在线体班次上启用，则数量不能大于 0：

`x_dlt ≤ q_d · z_dlt , ∀d,l,t`

需求是否被排到与数量联动：

`∑_{l,t} x_dlt ≥ u_d , ∀d`

`∑_{l,t} x_dlt ≤ q_d · u_d , ∀d`

### 4.3 线体班次产能约束

每条线每个班次的总占用工时不得超过净可用工时：

`∑_{d∈D} x_dlt / uph_dlt + setup_lt ≤ avail_lt , ∀l,t`

其中：

- `setup_lt` 为该班次内换线损失时间
- 若阶段一不显式建换线，可先忽略或用估计值近似

### 4.4 可行域裁剪约束

若需求 `d` 在 `(l,t)` 上不可排，则直接禁止：

`x_dlt ≤ q_d · elig_dlt , ∀d,l,t`

这个约束非常关键，建议在预处理阶段就尽量收缩 `elig_dlt`，避免 MILP 规模过大。

## 5. 业务规则到 MILP 数学映射

以下表格按“规则编号-业务规则-模型归类-数学表达”展开。

## 5.1 规则映射总表

| 规则  | 业务含义                       | 模型归类    | 典型数学表达                   |
| --- | -------------------------- | ------- | ------------------------ |
| 1   | 已开工单遵循原计划                  | 硬约束     | 锁定到指定日期/线体/顺序            |
| 2   | 普通订单参与优化排程                 | 基础对象    | 需求平衡与可行域约束               |
| 3   | 不得早于 MR Date               | 硬约束     | `x_dlt = 0, if t < mr_d` |
| 4   | 按优先级排产                     | 软约束/目标  | 优先级加权或分层优化               |
| 5   | 按 UPH 计算产能                 | 硬约束     | `∑ x/uph ≤ avail`        |
| 6   | 遵循生产日历                     | 硬约束     | 非开班班次禁止排产                |
| 7   | 预留产能不可占用                   | 硬约束     | `avail = cap-res-down`   |
| 8   | 线体与机型匹配                    | 硬约束     | `elig_dlt = 0/1`         |
| 9   | 客制化/小单/Fast Ship 优先 Cell 线 | 软约束或硬约束 | 限制或奖励 Cell 分配            |
| 10  | FIX 到指定线体/班次/顺序            | 硬约束     | 指定 `x,z,s`               |
| 11  | 机型班次/线体限制                  | 硬约束     | 指定可行线体班次集合               |
| 12  | FAI 首片先行、间隔投产              | 硬约束     | 先后与最小时差约束                |
| 13  | 交付指标优先                     | 软约束/主目标 | 最小化延期/最大化达成              |
| 14  | 换线少、同机型合并、排程量最大            | 软约束/次目标 | 最小换线、最大排程量               |

## 5.2 逐条详细映射

### 规则 1：工单冻结

业务解释：

- 已开立、已承诺的工单不应被重新打散或改期。

建议建模方式：

- 若工单完全冻结，则直接固定其排产结果。
- 若只冻结日期不冻结线体，则只锁定日期。

数学表达：

若工单 `d` 固定在线体 `l*`、班次 `t*`：

`x_d,l*,t* = q_d`

`x_dlt = 0 , ∀(l,t) ≠ (l*,t*)`

若只冻结日期：

`x_dlt = 0 , ∀t ≠ t*`

### 规则 2：订单是主优化对象

业务解释：

- 未冻结需求是 APS 主排产对象。

数学表达：

直接进入基础需求平衡与产能约束，不需要额外单独约束。

### 规则 3：MR Date 约束

业务解释：

- 物料齐套前不得投产。

数学表达：

对所有早于 `mr_d` 的班次，禁止排产：

`x_dlt = 0 , ∀d, l, t < mr_d`

若 `t` 用班次序号表示，可写成：

`x_dlt = 0 , ∀d,l,t : day(t) < mr_d`

这是典型硬约束。

### 规则 4：排产优先级

业务解释：

- 业务不是“先到先排”，而是按优先级组、规则条件和 KPI 倾向排产。

数据来源：

- `aps_schedule_priority`
- 需求属性字段，如 `pre_lock`、`ots_date`、`fpsd`、`ship_day_two`、`om_urgent`

推荐建模方式：

定义需求优先级得分 `prio_d`，或按优先级组分层优化。

目标函数示例：

`max ∑_{d∈D} prio_d · ∑_{l,t} x_dlt`

更推荐的业务型表达：

1. 先最小化高优先级需求未排量  
2. 再最小化次优先级需求未排量  
3. 再优化换线与效率

即词典序目标：

`min ( ∑_{d∈D1} c_d , ∑_{d∈D2} c_d , ... )`

其中 `D1,D2,...` 为不同优先级层。

### 规则 5：UPH 约束

业务解释：

- 同一机型在不同线体、不同班次上的产能不同。

数学表达：

`∑_{d∈D} x_dlt / uph_dlt + setup_lt ≤ avail_lt , ∀l,t`

若某 `uph_dlt` 不存在，建议直接令 `elig_dlt = 0`。

这是硬约束。

### 规则 6：生产日历约束

业务解释：

- 只能在开班时间内生产。

数学表达：

若 `(l,t)` 非开班状态，则：

`x_dlt = 0 , ∀d`

若采用净工时方式，也可直接反映在 `avail_lt = 0`。

这是硬约束。

### 规则 7：产能预留约束

业务解释：

- 某些班次产能要留给其他业务，不允许本次排程占用。

数学表达：

`avail_lt = cap_lt - res_lt - down_lt`

然后统一使用：

`∑_{d} x_dlt / uph_dlt + setup_lt ≤ avail_lt`

若整班全部预留：

`avail_lt = 0`

这是硬约束。

### 规则 8：产线与机型匹配约束

业务解释：

- 并非所有机型都能在所有线体生产。
- 某些线体只是“可生产”，某些线体是“优先生产”。

建模建议：

- 可生产关系作为硬约束。
- 优先关系作为目标偏好。

数学表达：

不可生产：

`x_dlt = 0 , if line l not compatible with demand d`

优先生产线可通过奖励表达：

`max ∑_{d,l,t} pref_dlt · x_dlt`

其中 `pref_dlt` 越高，代表越符合线机优先关系。

### 规则 9：客制化订单、小单、Fast Ship 优先 Cell 线

业务解释：

- 这类需求更适合小线体、柔性线体快速处理。

两种建模方式：

1. 若业务要求“优先”，用软约束  
2. 若业务要求“必须”，用硬约束

软约束写法：

定义 `cellpref_d = 1` 当需求 `d` 属于小单/Fast Ship/客制化需求。

目标中增加：

`max ∑_{d∈D_fast∪D_small} ∑_{l∈L_cell,t} x_dlt`

硬约束写法：

`x_dlt = 0 , ∀d∈D_fast∪D_small, l∉L_cell, t`

通常更建议先按软约束处理，因为主板/装配现场经常会遇到 Cell 线容量不足的问题。

### 规则 10：FIX 约束

业务解释：

- 某些需求已被业务指定到某日某班某线某顺序某数量。

数据来源：

- `aps_schedule_demand_fix_input`

数学表达：

若 FIX 记录指定：

- 线体 `l_fix(d)` ，即该fix需求d所在的线体`l`
- 班次 `t_fix(d)`
- 数量 `q_fix(d)`

则：

`x_d,l_fix(d),t_fix(d) ≥ q_fix(d)`

`x_dlt = 0 , ∀(l,t) ≠ (l_fix(d),t_fix(d))`  
当业务要求“整单固定”时成立。

若只固定一部分：

`x_d,l_fix(d),t_fix(d) ≥ q_fix(d)`

其余部分允许在其他可行班次继续排。

若显式建顺序变量，还需要：

`s_d = seq_fix(d)` 或对应排序位置约束。

### 规则 11：机型限制

业务解释：

- 某些机型只能上特定班次、特定线体。

数据来源：

- `aps_schedule_limit_setting`

数学表达：

若机型 `m` 仅允许在线体集合 `L(m)`、班次集合 `T(m)`：

`x_dlt = 0 , ∀d: model_d=m, l∉L(m), t`

`x_dlt = 0 , ∀d: model_d=m, l, t∉T(m)`

这是硬约束。

### 规则 12：FAI 首件与间隔约束

业务解释：

- FAI 首片订单必须先做。
- 首片完成后，经过验证窗口，剩余订单才能继续投产。

这是主板/新机种导入中非常典型的工程约束。

数据来源：

- `aps_schedule_demand_fai_input`

推荐建模变量：

- `s_d`：需求开始时点
- `e_d`：需求结束时点

设同组内：

- `d_first(g)`：首件需求
- `D_rest(g)`：剩余需求
- `lead_g`：首件与后续投产的最小间隔

数学表达：

`s_r ≥ e_{d_first(g)} + lead_g , ∀g, r ∈ D_rest(g)`

若首件固定数量为 2 pcs，可通过需求拆单方式处理，效果最好：

- 首件 2 pcs 作为独立需求
- 余量作为另一独立需求

这样模型表达最清晰。

### 规则 13：订单交付指标

业务解释：

- 优先保障 OTS、FPSD、Urgent、D+2 ShipDate 等交付指标。

推荐做法：

把交付指标转为“延期/未达成”惩罚变量。

定义：

- `late_d^ots ≥ 0`
- `late_d^fpsd ≥ 0`
- `late_d^ship ≥ 0`

若 `E_d` 表示需求最终完成日期，则：

`late_d^ots ≥ E_d - due_d^ots`

`late_d^fpsd ≥ E_d - due_d^fpsd`

`late_d^ship ≥ E_d - due_d^ship`

目标函数：

`min ∑_d (w_ots·late_d^ots + w_fpsd·late_d^fpsd + w_ship·late_d^ship + w_urg·urgent_d·c_d )`

其中：

- `w_urg` 应显著高于普通需求
- `w_ots`, `w_fpsd`, `w_ship` 为权重
- 若 D+2 ShipDate 是单独 KPI，可单独设大权重

### 规则 14：生产效率指标

该规则包含四部分，建议拆开建模。

#### 14.1 最小化换线次数

业务解释：

- 同一线体、同一班次内，机型切换越少越好。

若建顺序变量，可定义：

- `change_{d1,d2,l,t} ∈ {0,1}` 表示相邻切换

目标：

`min ∑_{l,t,d1,d2} chg_{model_{d1},model_{d2}} · change_{d1,d2,l,t}`

若阶段一不做顺序建模，可先用近似项替代，例如最小化同班次内机型种类数。

#### 14.2 同机型合并，避免 ABABA

业务解释：

- 同一机型应尽量连续，不要被多次打断。

推荐方式：

- 在细排模型中使用排序变量建模。
- 或在主模型中对“同班次同机型分散到多个段”加罚。

近似目标：

`min ∑_{l,t,m} split_{l,t,m}`

其中 `split_{l,t,m}` 表示机型 `m` 在班次 `(l,t)` 中被切分的段数。

#### 14.3 最大化排程量

业务解释：

- 在满足高优先级交付前提下，希望排到最多数量。

目标：

`max ∑_{d,l,t} x_dlt`

或等价写成：

`min ∑_d c_d`

#### 14.4 PO 物料顺序优化

业务解释：

- 按颜色、材料项、KB、PCBA、Cover Assy 等业务偏好排序。

数据来源：

- `aps_schedule_order_ruler`
- `aps_schedule_merge_priority`

建模建议：

- 对复杂排序偏好，建议在主模型中做软引导，在细排模型中做显式排序。

若 `pref_{d1,d2,l}` 表示 `d1` 在 `d2` 前更优，则：

`max ∑_{l,t,d1,d2} pref_{d1,d2,l} · y_{d1,d2,l,t}`

## 6. 推荐目标函数层级

从笔记本主板/装配排产实战看，最稳妥的做法不是把所有目标一次性加权求和，而是采用分层求解。

推荐层级如下：

### 第一层：满足硬约束

- MR Date
- 日历
- UPH
- 预留
- 线机匹配
- FIX
- FAI
- 机型限制

### 第二层：保障交付

最小化：

`Obj1 = ∑_d (w1·late_d^ots + w2·late_d^fpsd + w3·late_d^ship + w4·urgent_d·c_d)`

### 第三层：最大化已排数量

最小化：

`Obj2 = ∑_d c_d`

### 第四层：优化效率

最小化：

`Obj3 = ∑_{l,t} setup_lt + ∑_{l,t,m} split_{l,t,m}`

### 第五层：优化业务偏好

最大化：

`Obj4 = ∑_{d,l,t} cellpref_d · I(l∈L_cell) · x_dlt + ∑ pref_{d1,d2,l}·y_{d1,d2,l,t}`

若求解器支持多目标优化，建议直接使用 lexicographic objective。  
若不支持，则可以设置足够拉开的层级权重。

## 7. 数据表到模型参数映射

| 数据表                              | 关键字段                                                                                       | 模型参数/变量用途       |
| -------------------------------- | ------------------------------------------------------------------------------------------ | --------------- |
| `aps_schedule_demand_base_input` | `demand_id, qty, mr_day, ots_date, fpsd, ship_date, pre_lock, om_urgent, fast_ship, model` | 需求量、交期、优先级、机型属性 |
| `aps_schedule_demand_fai_input`  | `group_id, group_first, lead_time, demand_id`                                              | FAI 分组、首件先后、间隔  |
| `aps_schedule_demand_fix_input`  | `fix_day, fix_shift, fix_line_id, fix_seq, fix_qty`                                        | FIX 锁定约束        |
| `aps_schedule_line_input`        | `line_id, line_type, open_type`                                                            | 线体集合、Cell线识别    |
| `aps_schedule_line_calendar`     | `day, shift_seq, shift_start_time, shift_end_time, shift_status`                           | 班次可用性、总工时       |
| `aps_schedule_off_time_input`    | `start_time, end_time, off_type`                                                           | 休息/维护扣减         |
| `aps_schedule_uph_input`         | `line_id, day, shift_seq, model, uph_qty, priority`                                        | 产能参数、线机匹配       |
| `aps_change_time_input`          | `model_one, model_two, change_time`                                                        | 换线损失            |
| `aps_schedule_limit_setting`     | `condition_key, condition_value`                                                           | 机型、班次、线体限制      |
| `aps_schedule_order_ruler`       | `priority, condition_key`                                                                  | 排序偏好、物料顺序       |
| `aps_schedule_order_qty`         | `small_qty, flag_type`                                                                     | 小单识别阈值          |
| `aps_schedule_priority`          | `priority_group, priority, condition_key, condition_value`                                 | 需求优先级打分         |

## 8. 推荐的建模拆分方案

从十多年主板排产经验看，以下规则适合放在主 MILP 中，以下规则更适合二阶段处理。

### 8.1 适合直接进入主 MILP 的规则

- 需求平衡
- MR Date
- 日历可用性
- UPH 产能
- 预留产能
- 线机匹配
- FIX 锁定
- 机型/班次/线体限制
- FAI 先后与最小间隔
- 交付类 KPI

### 8.2 更适合二阶段细排或启发式的规则

- 班内复杂换线序列
- ABABA 交叉消除
- 多属性 PO 精细排序
- 同机型合并到连续分钟级时间块

原因很简单：

- 这类规则一旦直接放进主 MILP，二元变量数量会爆炸。
- 对业务而言，先得到“哪单上哪线哪班次”通常已经解决 80% 的问题。
- 班内秒级/分钟级最优序列更适合在第二阶段用 MIP、CP 或启发式算法处理。

## 9. 实施建议

### 9.1 预处理建议

求解前强烈建议做三类预处理：

1. 可行域裁剪  
   先根据 MR Date、线机匹配、机型限制、日历状态生成 `elig_dlt`。

2. 需求拆单  
   对 FAI、FIX、部分小单/优先订单先拆成独立需求，降低模型表达复杂度。

3. 班次净工时计算  
   先把班次总时长扣减休息、维护、预留，统一生成 `avail_lt`。

### 9.2 求解策略建议

推荐的工程落地方案：

1. 第一阶段 MILP：求“需求到线体班次”的最优分配  
2. 第二阶段细排：求“班内顺序和时间块”  
3. 第三阶段校验：回写换线次数、交付 KPI、异常日志

### 9.3 与当前 BOX APS 输出表的衔接

建议如下：

- 第一阶段输出对齐 `aps_adjust_schedule_output`
- 第二阶段时间块结果对齐 `aps_schedule_result`
- 换线统计对齐 `aps_schedule_change_line`
- 求解过程与异常对齐 `aps_schedule_runtime_log`

## 10. 结论

BOX APS 当前的业务规则已经具备较好的 MILP 转译条件。  
从业务抽象上看，它本质上是一个“多约束、多目标、带部分冻结需求和特殊工艺规则的离散制造排产问题”。

对主板/装配类场景，最推荐的落地方式不是一次性构造一个超大而全的 MILP，而是：

1. 用主 MILP 解决需求分配、交付保障和核心可行性问题。
2. 用二阶段细排解决班内换线、合并排序和物料顺序问题。

这样既符合求解器性能规律，也更符合工厂业务的可解释性和可维护性。

## 11. 下一步建议

如果继续往下推进，建议下一步直接补三份文档：

1. “参数口径说明表”  
   把每个模型参数的字段来源、单位、取值规则写清楚。

2. “变量字典与求解输出字典”  
   把每个决策变量如何回写到结果表写清楚。

3. “原型数学模型说明书”  
   按 sets / params / vars / constraints / objectives 的形式整理成正式建模稿。
