# BOX APS业务规则到 MILP 数学约束映射表 v3

## 1. 文档目的

本文在 `业务规则到MILP数学约束映射表_v2` 的基础上重写，目标是把 v3 调整成更接近正式模型说明书的结构：

- 先给出主模型能够完成排产所必需的基础数学公式。
- 再给出在主模型之上追加的业务约束和附加目标。
- 最后说明哪些表不进入模型，只用于结果回写或运行日志。

本文继续基于以下资料：

- `APS系统数据表目录.xlsx`
- `BOX 智能排产约束规则.xlsx`
- `BOX APS脱敏数据-2.xlsx`

## 2. 建模边界

### 2.1 主模型边界

主模型采用“线体-日期-班次”的离散时段粒度，负责决定：

- 哪个需求排到哪条线
- 哪天哪班排
- 排多少

主模型不直接解决：

- 班内分钟级排序
- 颜色/材料项细排序
- Cell 线循环排序
- 详细换线块切分

这些内容放到二阶段细排中处理。

### 2.2 预处理边界

在进入主模型之前，先做两类预处理：

1. 需求合并  
   由 `aps_merge_priority_setting_input` 决定原始需求如何合并成主模型中的排产对象。

2. 可行域裁剪  
   由以下表共同生成主模型可行域参数：
   
   - `aps_schedule_limit_setting_input`
   - `aps_schedule_order_qty_setting_input`
   - `aps_schedule_line_input`
   - `aps_schedule_line_calendar_input`
   - `aps_schedule_off_time_input`
   - `aps_schedule_uph_input`

## 3. 集合、参数、决策变量

### 3.1 集合与索引

- 原始需求集合：($R$)，索引为 ($r$)
- 合并后需求集合：($D$)，索引为 ($d$)
- 线体集合：($L$)，索引为 ($l$)
- 班次时段集合：($T$)，索引为 ($t$)
- FAI 分组集合：($G$)，索引为 ($g$)

常用子集：

- FIX 需求集合：($D^{fix}$)
- 继承旧方案的需求集合：($D^{adj}$)
- FAI 首件分组集合：($G^{fai}$)
- Cell 线集合：($L^{cell}$)

### 3.2 参数

#### 3.2.1 基础参数

- 需求数量：($q_d$)
- 需求机型：($model_d$)
- 业务分类：($mcode_d$)
- 时段开始时间：($a_t$)
- 时段结束时间：($b_t$)
- 班次总工时：($cap_{lt}$)
- 停机工时：($down_{lt}$)
- 预留工时：($res_{lt}$)
- 净可用工时：($avail_{lt}$)
- 合法 UPH：($uph_{dlt}$)
- 线体是否为 Cell 线：($cell_l \in \{0,1\}$)

#### 3.2.2 可行域参数

- 基础线机可行性：($elig_{dlt}^{base} \in \{0,1\}$)
- 限制规则可行性：($allow_{dlt}^{limit} \in \{0,1\}$)
- 大小单规则可行性：($allow_{dl}^{qty} \in \{0,1\}$)
- 日历可行性：($allow_{lt}^{cal} \in \{0,1\}$)
- MR Date 可行性：($allow_{dt}^{mr} \in \{0,1\}$)
- 综合可行性：($elig_{dlt} \in \{0,1\}$)

#### 3.2.3 交付参数

- 原始需求 OTS 截止时段集合：($T_r^{ots,raw} \subseteq T$)
- 原始需求 FPSD 截止时段集合：($T_r^{fpsd,raw} \subseteq T$)
- 原始需求 Ship Date 截止时段集合：($T_r^{ship,raw} \subseteq T$)
- OTS 截止时段集合：($T_d^{ots} \subseteq T$)
- FPSD 截止时段集合：($T_d^{fpsd} \subseteq T$)
- Ship Date 截止时段集合：($T_d^{ship} \subseteq T$)

#### 3.2.4 特殊规则参数

- FIX 线体：($line_d^{fix}$)
- FIX 时段：($slot_d^{fix}$)
- FIX 数量：($qty_d^{fix}$)
- 继承线体：($line_d^{adj}$)
- 继承时段：($slot_d^{adj}$)
- 继承数量：($qty_d^{adj}$)
- FAI 首件需求：($d_g^{first}$)
- FAI 余量需求集合：($D_g^{rest}$)
- FAI 等待时长：($lead_g$)

#### 3.2.5 优先级与排序参数

- 主优先级层级：($priority_d^{pri}$)
- 合并后优先级层级：($priority_d^{merge}$)
- 主优先级权重：($W_d^{pri}$)
- 合并后优先级权重：($W_d^{merge}$)
- Cell 线偏好系数：($W_{dl}^{cell}$)
- 材料项排序偏好：($P_{d_1 d_2 l}^{order}$)
- Cell 循环偏好：($P_{dlt}^{cycle}$)
- 换线工时：($ct_{d_1 d_2}$)
- 大 M 常数：($M$)

### 3.3 决策变量

- 排产数量：($x_{dlt} \in \mathbb{Z}_+$)
- 排产启用：($z_{dlt} \in \{0,1\}$)
- 需求是否有排产：($u_d \in \{0,1\}$)
- 未排数量：($c_d \in \mathbb{Z}_+$)
- 需求完成时间：($e_d \in \mathbb{R}_+$)
- OTS 未达成量：($miss_d^{ots} \in \mathbb{R}_+$)
- FPSD 未达成量：($miss_d^{fpsd} \in \mathbb{R}_+$)
- Ship Date 未达成量：($miss_d^{ship} \in \mathbb{R}_+$)

二阶段细排变量：

- 同班次先后变量：($y_{d_1 d_2 l t} \in \{0,1\}$)
- 相邻换线变量：($\chi_{d_1 d_2 l t} \in \{0,1\}$)
- 班次换线工时：($setup_{lt} \in \mathbb{R}_+$)

## 4. 主模型基础公式

本节只保留“没有这些公式就无法完成排产”的主模型主体。

### 4.1 预处理后统一参数

净可用工时定义为：

($avail_{lt} = cap_{lt} - down_{lt} - res_{lt},\ \forall l \in L,t \in T$)

综合可行性定义为：

($elig_{dlt} = elig_{dlt}^{base} \cdot allow_{dlt}^{limit} \cdot allow_{dl}^{qty} \cdot allow_{lt}^{cal} \cdot allow_{dt}^{mr},\ \forall d \in D,l \in L,t \in T$)

### 4.2 需求平衡

每个需求的已排量与未排量之和等于需求总量：

($\sum_{l \in L}\sum_{t \in T} x_{dlt} + c_d = q_d,\ \forall d \in D$)

### 4.3 数量与启用联动

如果某个需求在某线某班没有启用，则该位置不能排量：

($x_{dlt} \le q_d \cdot z_{dlt},\ \forall d \in D,l \in L,t \in T$)

若该位置启用，则至少要排 1 个单位：

($x_{dlt} \ge z_{dlt},\ \forall d \in D,l \in L,t \in T$)

### 4.4 需求是否被安排

($\sum_{l \in L}\sum_{t \in T} x_{dlt} \le q_d \cdot u_d,\ \forall d \in D$)

($\sum_{l \in L}\sum_{t \in T} x_{dlt} \ge u_d,\ \forall d \in D$)

### 4.5 同一需求同一班次不并行占多条线

如果主模型采用“同一需求同一班次最多上一条线”的工程假设，则加入：

($\sum_{l \in L} z_{dlt} \le 1,\ \forall d \in D,t \in T$)

### 4.6 线体班次产能

线体班次内所有已排数量折算工时后，不得超过净可用工时：

($\sum_{d \in D}\frac{x_{dlt}}{uph_{dlt}} \le avail_{lt},\ \forall l \in L,t \in T$)

如果主模型已经同时考虑班次内换线损失，则可写为：

($\sum_{d \in D}\frac{x_{dlt}}{uph_{dlt}} + setup_{lt} \le avail_{lt},\ \forall l \in L,t \in T$)

### 4.7 基础可行域约束

如果需求在某条线某个时段不可行，则直接禁止排产：

($x_{dlt} \le q_d \cdot elig_{dlt},\ \forall d \in D,l \in L,t \in T$)

### 4.8 完工时间定义

若需求在某个时段有排产，则其完工时间不得早于该时段结束时间：

($e_d \ge b_t - M(1-z_{dlt}),\ \forall d \in D,l \in L,t \in T$)

### 4.9 交付未达成量定义

OTS 未达成量：

($miss_d^{ots} \ge q_d - \sum_{l \in L}\sum_{t \in T_d^{ots}} x_{dlt},\ \forall d \in D$)

($miss_d^{ots} \ge 0,\ \forall d \in D$)

FPSD 未达成量：

($miss_d^{fpsd} \ge q_d - \sum_{l \in L}\sum_{t \in T_d^{fpsd}} x_{dlt},\ \forall d \in D$)

($miss_d^{fpsd} \ge 0,\ \forall d \in D$)

Ship Date 未达成量：

($miss_d^{ship} \ge q_d - \sum_{l \in L}\sum_{t \in T_d^{ship}} x_{dlt},\ \forall d \in D$)

($miss_d^{ship} \ge 0,\ \forall d \in D$)

### 4.10 主模型基础目标

如果先不引入额外优先级表，则主模型可采用以下基础目标层级：

第一层：优先减少交付未达成量

($\min Obj_1 = \sum_{d \in D} (\omega_{ots}\cdot miss_d^{ots} + \omega_{fpsd}\cdot miss_d^{fpsd} + \omega_{ship}\cdot miss_d^{ship})$)

第二层：最大化总排程量

($\min Obj_2 = \sum_{d \in D} c_d$)

第三层：若启用换线近似，则最小化换线损失

($\min Obj_3 = \sum_{l \in L}\sum_{t \in T} setup_{lt}$)

## 5. 额外业务约束与附加目标

本节是在第 4 节主模型可运行的基础上，再追加业务规则。

### 5.1 `aps_schedule_limit_setting_input`

该表用于定义机型、班次、线体、场景等限制规则。  
其处理方式不是直接把表中每一行写成一个公式，而是先生成限制可行集：

($\mathcal{F}_d^{limit} \subseteq L \times T,\ \forall d \in D$)

若 ($(l,t) \notin \mathcal{F}_d^{limit}$)，则：

($x_{dlt} = 0,\ \forall d \in D,(l,t) \notin \mathcal{F}_d^{limit}$)

等价地，也可以写回主模型统一可行域参数：

($allow_{dlt}^{limit} = 0,\ \forall d \in D,(l,t) \notin \mathcal{F}_d^{limit}$)

### 5.2 `aps_schedule_order_qty_setting_input`

该表决定大小单能否上某条线，也决定小单是否偏向 Cell 线。

先由 `flag_type` 和 `small_qty` 生成允许线集合：

($\mathcal{L}_d^{qty} \subseteq L,\ \forall d \in D$)

若 ($l \notin \mathcal{L}_d^{qty}$)，则：

($x_{dlt} = 0,\ \forall d \in D,l \notin \mathcal{L}_d^{qty},t \in T$)

若还要体现“小单 / Fast Ship / 定制化优先 Cell 线”，可增加软目标：

($\min Obj_{cell} = \sum_{d \in D}\sum_{l \in L}\sum_{t \in T} W_{dl}^{cell}\cdot (1-cell_l)\cdot x_{dlt}$)

### 5.3 `aps_schedule_priority_setting_input`

该表不改变可行域，主要改变“谁先保”。

由该表生成每个需求的主优先级权重：

($W_d^{pri} = w(priority_d^{pri}),\ \forall d \in D$)

则主模型第一层目标可改写为：

($\min Obj_1' = \sum_{d \in D} W_d^{pri}\cdot (\omega_{ots}\cdot miss_d^{ots} + \omega_{fpsd}\cdot miss_d^{fpsd} + \omega_{ship}\cdot miss_d^{ship} + \omega_{uns}\cdot c_d)$)

若该表的 `kpi = qtymax`，则第二层目标保持：

($\min Obj_2 = \sum_{d \in D} c_d$)

若该表的 `kpi = ordermax`，则第二层目标改为：

($\max Obj_2' = \sum_{d \in D} u_d$)

### 5.4 `aps_merge_priority_setting_input`

该表不直接生成主模型约束，而是在主模型之前决定原始需求如何合并。

记合并映射为：

($\phi: R \rightarrow D$)

则合并后参数可定义为：

($q_d = \sum_{r \in \phi^{-1}(d)} q_r,\ \forall d \in D$)

($T_d^{ots} = \bigcap_{r \in \phi^{-1}(d)} T_r^{ots,\ raw},\ \forall d \in D$)

($T_d^{fpsd} = \bigcap_{r \in \phi^{-1}(d)} T_r^{fpsd,\ raw},\ \forall d \in D$)

($T_d^{ship} = \bigcap_{r \in \phi^{-1}(d)} T_r^{ship,\ raw},\ \forall d \in D$)

即：合并后需求的交付口径取更严格的截止集合，避免合并后放松交付要求。

### 5.5 `aps_schedule_merge_priority_setting_input`

该表用于合并后 demand 的次级排序，不改变可行域。

由该表生成合并后优先级权重：

($W_d^{merge} = w'(priority_d^{merge}),\ \forall d \in D$)

则可作为主模型第三层或第四层目标：

($\min Obj_{merge} = \sum_{d \in D} W_d^{merge}\cdot c_d$)

### 5.6 `aps_adjust_schedule_input`

该表只在滚动排程、续排或人工调排场景下进入模型。

#### 情形 A：旧方案必须保留

若旧方案中的指定数量必须沿用，则：

($x_{d,line_d^{adj},slot_d^{adj}} \ge qty_d^{adj},\ \forall d \in D^{adj}$)

若业务要求整单保留，则：

($x_{d,line_d^{adj},slot_d^{adj}} = q_d,\ \forall d \in D^{adj}$)

并可进一步限制其他位置：

($x_{dlt} = 0,\ \forall d \in D^{adj},(l,t) \neq (line_d^{adj},slot_d^{adj})$)

#### 情形 B：旧方案只是优先沿用

此时不加硬约束，而是把该表作为求解器初始解，不写入数学模型。

### 5.7 FIX 约束

若 `aps_schedule_demand_fix_input` 指定某需求在某天某班某线生产，则：

($x_{d,line_d^{fix},slot_d^{fix}} \ge qty_d^{fix},\ \forall d \in D^{fix}$)

若 FIX 为整单锁定，则：

($x_{d,line_d^{fix},slot_d^{fix}} = q_d,\ \forall d \in D^{fix}$)

($x_{dlt} = 0,\ \forall d \in D^{fix},(l,t) \neq (line_d^{fix},slot_d^{fix})$)

### 5.8 FAI 约束

若 FAI 首件已拆成独立需求，则首件完成后，余量需求才能开始：

($a_t + M(1-z_{rlt}) \ge e_{d_g^{first}} + lead_g,\ \forall g \in G^{fai},r \in D_g^{rest},l \in L,t \in T$)

这条公式表示：只要余量需求 ($r$) 在时段 ($t$) 上排产，则该时段开始时间必须晚于首件完成时间加等待时长。

### 5.9 `aps_schedule_order_ruler_input`

该表主要解决颜色/材料项顺序，更适合二阶段细排。

先后关系变量与启用变量联动：

($y_{d_1 d_2 l t} \le z_{d_1lt},\ \forall d_1,d_2,l,t$)

($y_{d_1 d_2 l t} \le z_{d_2lt},\ \forall d_1,d_2,l,t$)

($y_{d_1 d_2 l t} + y_{d_2 d_1 l t} \le 1,\ \forall d_1 \neq d_2,l,t$)

排序偏好目标：

($\max Obj_{order} = \sum_{l \in L}\sum_{t \in T}\sum_{d_1 \in D}\sum_{d_2 \in D} P_{d_1 d_2 l}^{order}\cdot y_{d_1 d_2 l t}$)

### 5.10 `aps_schedule_cycle_merge_setting_input`

该表主要服务 Cell 线循环策略和线内合并排序，建议作为二阶段偏好目标处理：

($\max Obj_{cycle} = \sum_{d \in D}\sum_{l \in L^{cell}}\sum_{t \in T} P_{dlt}^{cycle}\cdot x_{dlt}$)

如果项目一期只做主模型，则这一项可以先不启用。

### 5.11 换线优化

若二阶段细排需要显式统计换线，则定义：

($setup_{lt} = \sum_{d_1 \in D}\sum_{d_2 \in D,d_1 \neq d_2} ct_{d_1 d_2}\cdot \chi_{d_1 d_2 l t},\ \forall l \in L,t \in T$)

并最小化：

($\min Obj_{setup} = \sum_{l \in L}\sum_{t \in T} setup_{lt}$)

## 6. 建议的目标函数层级

如果采用词典序优化，建议顺序如下：

1. 主交付目标  
   ($\min Obj_1'$)

2. 总排程量或订单笔数  
   ($\min Obj_2$) 或 ($\max Obj_2'$)

3. 合并后 demand 的次级优先级  
   ($\min Obj_{merge}$)

4. Cell 线偏好  
   ($\min Obj_{cell}$)

5. 班内颜色/材料项排序  
   ($\max Obj_{order}$)

6. 换线损失  
   ($\min Obj_{setup}$)

## 7. 不进入模型的结果表

以下表不作为模型输入，只由求解结果回写生成：

- `aps_adjust_schedule_output`
- `aps_schedule_change_line`
- `aps_schedule_result`
- `aps_schedule_runtime_log`

其中：

`aps_schedule_change_line` 可由二阶段结果统计：

($chg_{lt} = \sum_{d_1 \in D}\sum_{d_2 \in D,d_1 \neq d_2} \chi_{d_1 d_2 l t}$)

`aps_adjust_schedule_output` 直接由所有 ($x_{dlt} > 0$) 的解生成。

`aps_schedule_result` 由生产块、停机块、预留块、换线块拼装生成。

`aps_schedule_runtime_log` 仅记录运行状态，不进入模型。

## 8. v3 总结

v3 的整理原则是：

- 第 4 节只保留主模型排产必需公式。
- 第 5 节再逐项追加业务约束和业务偏好。
- 能改变可行域的规则，优先写成硬约束。
- 只影响“排得更顺”的规则，优先放到二阶段目标。

如果你继续往下做，下一步最自然的是再补一版：

- “参数口径表：每个参数对应哪张表、哪个字段、如何计算”
