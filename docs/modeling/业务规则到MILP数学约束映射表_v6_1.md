# BOX APS业务规则到 MILP 数学约束映射表 v7

## 1. 建模范围

本文基于以下资料形成 `box` 业务当前样例版的正式数学模型：

- `APS系统数据表目录.xlsx`
- `BOX-智能排产约束规则.xlsx`
- `0403-科大-联宝APS业务交流-逐字稿文本.txt`
- `0403业务规则交流.md`
- `BOX-APS脱敏数据-2.xlsx`

当前脱敏数据中明确不存在以下三张表：

- `aps_schedule_cycle_merge_setting_input`
- `aps_schedule_demand_expand_input`
- `aps_change_model_input`

当前脱敏数据中实际存在的关键输入表包括：

- `aps_schedule_demand_base_input`
- `aps_schedule_demand_fai_input`
- `aps_schedule_demand_fix_input`
- `aps_schedule_line_input`
- `aps_schedule_line_calendar`
- `aps_schedule_off_time_input`
- `aps_schedule_uph_input`
- `aps_change_time_input`
- `aps_schedule_limit_setting`
- `aps_schedule_order_ruler`
- `aps_schedule_order_qty`
- `aps_schedule_priority`
- `aps_merge_priority_setting`
- `aps_adjust_schedule_input`

本版 `v7` 采用以下口径：

1. 主模型仍以 `demand_id` 为排产对象，不直接把 `dnno` 当作独立排产对象。
2. `aps_merge_priority_setting` 仅解释为“排前合并阶段顺序”，不直接转成订单级目标权重。
3. `aps_schedule_priority` 必须按 `priority_group` 做“组内且、组间或”解释。
4. 当前样例中的 `FIX` 按整单精确锁定处理。
5. `aps_adjust_schedule_input` 拆成两类：
   - 当前待排 demand 的继承锁定
   - 当前不在 `demand_base` 中的外部已排任务，占用未来产能
6. `ship_day_two` 而不是原始 `ship_date`，作为 D+2 出货相关目标日期。
7. FAI 等待时长使用表中的 `lead_time`，不把“8小时”写死成常数。
8. 当前样例未看到独立 `aps_schedule_reserver_input` 数据，因此若没有额外预留数据，则按 ($res_{lt}=0$) 处理。
9. 当前样例中同一 `demand_id` 在 `aps_schedule_demand_base_input` 里可能对应多行，绝大多数情况下差异只在 `dnno`；按目录表定义，`dnno` 是订单号，不是工序或节奏，因此建模前需先归并到 demand 级。

## 2. 模型分层

本版采用“三层口径”：

1. 预处理层  
   负责把配置表、主数据表、历史排程表转成模型参数
2. 主模型层  
   用 MILP 决定“哪些 demand 在哪条线、哪天哪班排多少”
3. 二阶段细排层  
   解决班内先后、材料项排序、精确换线和 lot 连续性

## 3. 集合与索引

- 需求集合：($D$)，索引为 ($d$)
- 线体集合：($L$)，索引为 ($l$)
- 班次时段集合：($T$)，索引为 ($t$)
- 机型集合：($M$)，索引为 ($m$)
- FAI 分组集合：($G^{fai}$)，索引为 ($g$)
- 优先级条件行集合：($R^{pri}$)，索引为 ($r$)
- 优先级组集合：($G^{pri}$)，索引为 ($g$)
- 当前待排集合中的继承排程记录集合：($A^{adj,in}$)，索引为 ($a$)
- 当前待排集合之外的继承排程记录集合：($A^{adj,ext}$)，索引为 ($a$)

常用子集：

- FIX 需求集合：($D^{fix} \subseteq D$)
- 继承锁定需求集合：($D^{adj} \subseteq D$)
- FAI 首件需求集合：($D^{fai,first} \subseteq D$)
- FAI 余量需求集合：($D^{fai,rest} \subseteq D$)
- 机型为 ($m$) 的需求集合：($D_m \subseteq D$)
- Cell 线集合：($L^{cell} \subseteq L$)

## 4. 参数

### 4.1 需求与产品参数

- 需求数量：($q_d$)
- 业务分类：($mcode_d$)
- 需求类型：($type_d$)
- 物料齐套日期：($mr_d$)
- OTS 日期：($ots_d$)
- FPSD 日期：($fpsd_d$)
- `ship_day_two` 日期：($ship2_d$)
- 是否 `pre_lock`：($prelock_d \in \{0,1\}$)
- 是否 `fast_ship`：($fast_d \in \{0,1\}$)
- 是否定制化：($cust_d \in \{0,1\}$)
- 是否 urgent：($urgent_d \in \{0,1\}$)
- 机型：($model_d$)
- Program：($program_d$)
- 颜色：($color_d$)
- 材料项键值：($kb_d, logup_d, cover_d, pcba_d$)
- 关联订单号集合：($O_d$)
- 工单号：($mo_d$)
- 批次号：($lot_d$)

### 4.2 资源与产能参数

- 班次总时长：($cap_{lt}$)
- 停机与休息时长：($down_{lt}$)
- 预留时长：($res_{lt}$)
- 外部已排任务占用时长：($occ_{lt}^{adj}$)
- 班次净可用时长：($avail_{lt}$)
- 班次开始时刻：($a_t$)
- 班次结束时刻：($b_t$)
- 线体所属 PU：($pu_l$)
- 线体是否为 Cell 线：($cell_l \in \{0,1\}$)
- 合法 UPH：($uph_{dlt}$)

### 4.3 可行域参数

- 基础线机可行性：($elig^{base}_{dlt} \in \{0,1\}$)
- 限制规则可行性：($allow^{limit}_{dlt} \in \{0,1\}$)
- 大小单规则可行性：($allow^{qty}_{dl} \in \{0,1\}$)
- 日历可行性：($allow^{cal}_{lt} \in \{0,1\}$)
- MR Date 可行性：($allow^{mr}_{dt} \in \{0,1\}$)
- 综合可行性：($elig_{dlt} \in \{0,1\}$)

### 4.4 优先级与 KPI 参数

- 优先级条件行命中参数：($sat_{dr}^{pri} \in \{0,1\}$)
- 优先级组命中参数：($hit_{dg}^{pri} \in \{0,1\}$)
- 优先级组顺位：($p_g^{pri}$)
- 订单主优先级顺位：($p_d^{pri}$)
- 主优先级权重：($W_d^{pri}$)
- 版本级 KPI 模式：($kpi^{mode} \in \{qtymax, ordermax\}$)
- OTS KPI 是否评价该需求：($\kappa_d^{ots} \in \{0,1\}$)
- FPSD KPI 是否评价该需求：($\kappa_d^{fpsd} \in \{0,1\}$)
- 不晚于 OTS 的可交付班次集合：($T_d^{ots}$)
- 不晚于 FPSD 的可交付班次集合：($T_d^{fpsd}$)
- 不晚于 `ship_day_two` 的可交付班次集合：($T_d^{ship2}$)

### 4.5 线体偏好与细排参数

- 线体分配偏好成本：($C_{dl}^{line}$)
- Cell 线偏好成本：($C_{dl}^{cell}$)
- 材料项排序偏好系数：($P_{d_1d_2l}^{order}$)

### 4.6 FIX、继承排程与 FAI 参数

- FIX 线体：($line_d^{fix}$)
- FIX 时段：($slot_d^{fix}$)
- FIX 班内顺序：($seq_d^{fix}$)
- 继承线体：($line_d^{adj}$)
- 继承时段：($slot_d^{adj}$)
- 继承班内顺序：($seq_d^{adj}$)
- 继承记录数量：($qty_a^{adj}$)
- 继承记录匹配到的 UPH：($uph_a^{adj}$)
- FAI 首件需求：($d_g^{first}$)
- FAI 余量需求集合：($D_g^{rest}$)
- FAI 等待时长：($lead_g$)

### 4.7 换线参数

- 需求对之间的换线时间：($ct_{d_1d_2l}$)
- 班次最小换线时间下界：($\underline{ct}_{l}$)

### 4.8 惩罚权重与大 M 参数

- OTS 惩罚权重：($\omega_{ots}$)
- FPSD 惩罚权重：($\omega_{fpsd}$)
- `ship_day_two` 惩罚权重：($\omega_{ship2}$)
- 未排数量惩罚权重：($\omega_{uns}$)
- 大 M 常数：($M$)

## 5. 决策变量

### 5.1 主模型变量

- 排产数量：($x_{dlt} \in \mathbb{Z}_+$)
- 排产启用变量：($z_{dlt} \in \{0,1\}$)
- 需求是否被完整排完：($u_d \in \{0,1\}$)
- 未排数量：($c_d \in \mathbb{Z}_+$)
- 需求班次粒度完工时刻：($e_d \in \mathbb{R}_+$)
- OTS 未达成量：($miss_d^{ots} \in \mathbb{R}_+$)
- FPSD 未达成量：($miss_d^{fpsd} \in \mathbb{R}_+$)
- `ship_day_two` 未达成量：($miss_d^{ship2} \in \mathbb{R}_+$)
- 机型是否在班次上线：($g_{lmt} \in \{0,1\}$)
- 班次粗粒度换线次数下界：($h_{lt} \in \mathbb{Z}_+$)
- 班次粗粒度换线工时：($setup_{lt} \in \mathbb{R}_+$)

### 5.2 二阶段变量

- 同班次先后变量：($y_{d_1d_2lt} \in \{0,1\}$)
- 班内位置变量：($pos_{dlt} \in \mathbb{Z}_+$)
- 相邻换线变量：($\chi_{d_1d_2lt} \in \{0,1\}$)
- 班内首任务标记：($head_{dlt} \in \{0,1\}$)
- 班内尾任务标记：($tail_{dlt} \in \{0,1\}$)
- 精确换线工时：($setup_{lt}^{seq} \in \mathbb{R}_+$)

## 6. 预处理定义

### 6.1 需求属性补齐

以 `aps_schedule_demand_base_input` 为主表，先按 `demand_id` 做需求级归并，再结合 `aps_schedule_master_pn_input` 补齐属性。

当前样例实际观察到：

- 同一 `demand_id` 通常出现两行
- 绝大多数情况下两行只在 `dnno` 上不同
- `qty` 在同一 `demand_id` 下保持一致

按 `APS系统数据表目录.xlsx` 字段说明，`dnno` 是订单号，不是工序或节奏。  
因此，同一 `demand_id` 下多条 `dnno` 记录应解释为“同一排产对象在订单层的展开/映射”，而不是“该 demand 还有多个未独立建模的工序”。

预处理时采用以下规则：

1. 以 `demand_id` 为键归并 `aps_schedule_demand_base_input`
2. 对每个 demand 记录其关联订单号集合：

($O_d = \{dnno_i : i \text{ 为属于 demand } d \text{ 的基础表原始行}\},\ \forall d \in D$)

3. 排产数量、齐套日期、交付日期、`mo`、`lot`、`model` 等排产参数仍按 demand 级唯一值生成，即：

($q_d = qty_i,\ \forall i \text{ 为属于 demand } d \text{ 的基础表原始行}$)

4. 若同一 `demand_id` 下出现 `qty`、`mr_day`、`mo`、`lot`、`model` 等排产关键字段不一致，则应判为数据异常，不直接进入本模型

完成上述 demand 级归并后，再补齐：

- `model`
- `program`
- `texture`
- `color`

得到 demand 级属性参数。  
其中，($O_d$) 仅用于订单层追溯、报表回写或结果映射，不额外产生新的排产义务。

### 6.2 优先级组命中

`aps_schedule_priority` 是规则表，不是订单权重表。  
应按以下顺序预处理：

1. 对每条条件行计算 ($sat_{dr}^{pri}$)
2. 对每个 `priority_group` 按“组内且”汇总出 ($hit_{dg}^{pri}$)
3. 同一 `priority` 下按“组间或”解释
4. 对每个 demand 取命中的最小优先级层级

于是：

($p_d^{pri} = \min \{p_g^{pri} : g \in G^{pri},\ hit_{dg}^{pri}=1\},\ \forall d \in D$)

($W_d^{pri} = w(p_d^{pri}),\ \forall d \in D$)

### 6.3 版本级 KPI 模式

`kpi` 字段挂在优先级规则行上。  
正式模型需要先汇总出一个版本级 KPI 模式：

- 若非空 `kpi` 一致为 `qtymax`，则取 ($kpi^{mode} = qtymax$)
- 若非空 `kpi` 一致为 `ordermax`，则取 ($kpi^{mode} = ordermax$)
- 若同版本出现多种非空 `kpi`，则应先由业务确定汇总口径

当前样例数据中，非空 `kpi` 全部为 `qtymax`。

### 6.4 外部已排任务占用工时

对 `aps_adjust_schedule_input` 中那些 `demand_id \notin D` 的记录，只作为外部已排任务占用未来产能。  
记 ($A_{lt}^{adj,ext} \subseteq A^{adj,ext}$) 为被锁定在线体 ($l$)、班次 ($t$) 的外部已排任务集合。  
其占用工时汇总为：

($occ_{lt}^{adj} = \sum_{a \in A_{lt}^{adj,ext}} \frac{qty_a^{adj}}{uph_a^{adj}},\ \forall l \in L,t \in T$)

### 6.5 班次净可用工时

($avail_{lt} = cap_{lt} - down_{lt} - res_{lt} - occ_{lt}^{adj},\ \forall l \in L,t \in T$)

### 6.6 综合可行性

($elig_{dlt} = elig^{base}_{dlt} \cdot allow^{limit}_{dlt} \cdot allow^{qty}_{dl} \cdot allow^{cal}_{lt} \cdot allow^{mr}_{dt},\ \forall d \in D,l \in L,t \in T$)

其中：

- `allow^{limit}` 由 `aps_schedule_limit_setting` 按 `group_id` 聚合生成
- `allow^{qty}` 由 `aps_schedule_order_qty` 生成
- `elig^{base}` 主要由线体、班次、机型和 UPH 是否可匹配生成

### 6.7 换线时间匹配

`aps_change_time_input` 按以下顺序匹配：

1. 同 `mcode + pu` 下，`model_one -> model_two` 正向精确匹配
2. `model_two -> model_one` 反向精确匹配
3. `program_one -> program_two` 正向匹配
4. `program_two -> program_one` 反向匹配
5. 带 `*` 的默认规则

因此：

($ct_{d_1d_2l} = f^{match}(mcode_{d_1}, pu_l, model_{d_1}, model_{d_2}, program_{d_1}, program_{d_2}),\ \forall d_1,d_2 \in D,l \in L$)

($\underline{ct}_{l} = \min \{ct_{d_1d_2l}: d_1,d_2 \in D,\ d_1 \neq d_2,\ model_{d_1}\neq model_{d_2}\},\ \forall l \in L$)

当前样例中实际可用的是各 `mcode` 的默认 `3` 分钟规则。

## 7. 主模型目标函数

建议采用词典序优化。

### 7.1 第一层：交付达成与主优先级

($\min Obj_1 = \sum_{d \in D} W_d^{pri}\cdot (\omega_{ots}\cdot \kappa_d^{ots}\cdot miss_d^{ots} + \omega_{fpsd}\cdot \kappa_d^{fpsd}\cdot miss_d^{fpsd} + \omega_{ship2}\cdot miss_d^{ship2} + \omega_{uns}\cdot c_d)$)

### 7.2 第二层：排程量最大化或订单笔数最大化

当前 ($kpi^{mode} = qtymax$)，则：

($\min Obj_2 = \sum_{d \in D} c_d$)

若 ($kpi^{mode} = ordermax$)，则：

($\max Obj_2' = \sum_{d \in D} u_d$)

其中，($u_d=1$) 表示该 demand 全量完成。

### 7.3 第三层：线体与 Cell 线偏好

($\min Obj_3 = \sum_{d \in D}\sum_{l \in L}\sum_{t \in T} (C_{dl}^{line} + C_{dl}^{cell}\cdot (1-cell_l))\cdot x_{dlt}$)

### 7.4 第四层：粗粒度效率优化

($\min Obj_4 = \sum_{l \in L}\sum_{t \in T} setup_{lt} + \sum_{l \in L}\sum_{m \in M}\sum_{t \in T} g_{lmt}$)

## 8. 主模型约束

### 8.1 需求平衡

($\sum_{l \in L}\sum_{t \in T} x_{dlt} + c_d = q_d,\ \forall d \in D$)

这里的 ($q_d$) 是按 `demand_id` 归并后的 demand 级数量。  
若同一 `demand_id` 在基础表中对应多个 `dnno`，这些 `dnno` 只作为订单层映射，不重复累加数量。

### 8.2 启用联动

($x_{dlt} \le q_d \cdot z_{dlt},\ \forall d \in D,l \in L,t \in T$)

($x_{dlt} \ge z_{dlt},\ \forall d \in D,l \in L,t \in T$)

### 8.3 需求是否被完整排完

($\sum_{l \in L}\sum_{t \in T} x_{dlt} \ge q_d \cdot u_d,\ \forall d \in D$)

($\sum_{l \in L}\sum_{t \in T} x_{dlt} \le q_d - (1-u_d),\ \forall d \in D$)

因此，($u_d=1$) 的含义是“该 `demand_id` 对应的 demand 级数量全部完成”，而不是“其关联的每一个 `dnno` 都各自形成独立完成量”。  
当前样例下若同一 `demand_id` 映射到多个 `dnno`，则这些 `dnno` 共享同一条 demand 级排产结果。

### 8.4 同一需求同一班次最多上一条线

($\sum_{l \in L} z_{dlt} \le 1,\ \forall d \in D,t \in T$)

### 8.5 线体班次产能

($\sum_{d \in D: elig_{dlt}=1}\frac{x_{dlt}}{uph_{dlt}} + setup_{lt} \le avail_{lt},\ \forall l \in L,t \in T$)

### 8.6 综合可行域

($x_{dlt} \le q_d \cdot elig_{dlt},\ \forall d \in D,l \in L,t \in T$)

### 8.7 完工时间定义

设 ($T$) 已按时间先后排序，($a_t$) 和 ($b_t$) 分别表示班次 ($t$) 的开始与结束时刻。  
主模型按班次粒度刻画完工时刻，因此 ($e_d$) 取该 demand 所有被选班次中最晚的班次结束时刻。

($e_d \ge b_t - M(1-z_{dlt}),\ \forall d \in D,l \in L,t \in T$)

($e_d \le b_t + M(1-z_{dlt} + \sum_{l' \in L}\sum_{\tau \in T:\tau>t} z_{dl'\tau}),\ \forall d \in D,l \in L,t \in T$)

### 8.8 交付未达成量定义

($miss_d^{ots} \ge q_d - \sum_{l \in L}\sum_{t \in T_d^{ots}} x_{dlt},\ \forall d \in D$)

($miss_d^{fpsd} \ge q_d - \sum_{l \in L}\sum_{t \in T_d^{fpsd}} x_{dlt},\ \forall d \in D$)

($miss_d^{ship2} \ge q_d - \sum_{l \in L}\sum_{t \in T_d^{ship2}} x_{dlt},\ \forall d \in D$)

($miss_d^{ots} \ge 0,\ \forall d \in D$)

($miss_d^{fpsd} \ge 0,\ \forall d \in D$)

($miss_d^{ship2} \ge 0,\ \forall d \in D$)

### 8.9 FIX 精确锁定

当前样例中 `aps_schedule_demand_fix_input` 满足：

- 一条 `demand_id` 仅对应一条 FIX 记录
- `fix_qty = q_d`

因此：

($x_{d,line_d^{fix},slot_d^{fix}} = q_d,\ \forall d \in D^{fix}$)

($x_{dlt} = 0,\ \forall d \in D^{fix},(l,t)\neq(line_d^{fix},slot_d^{fix})$)

### 8.10 继承排程精确锁定

对那些 `demand_id` 仍在当前待排集合中的继承记录，当前样例满足：

- 一条 `demand_id` 仅对应一条继承记录
- `schedule_qty = q_d`

因此：

($x_{d,line_d^{adj},slot_d^{adj}} = q_d,\ \forall d \in D^{adj}$)

($x_{dlt} = 0,\ \forall d \in D^{adj},(l,t)\neq(line_d^{adj},slot_d^{adj})$)

### 8.11 FAI 首件与余量先后关系

在主模型的班次粒度下，FAI 等待时间按“首件完工班次结束时刻 -> 余量投产班次开始时刻”控制。  
若首件 demand 跨多个班次，则按最后完工班次保守处理。

($a_t + M(1-z_{rlt}) \ge e_{d_g^{first}} + lead_g,\ \forall g \in G^{fai},\forall r \in D_g^{rest},\forall l \in L,\forall t \in T$)

### 8.12 机型出现变量联动

($\sum_{d \in D_m} z_{dlt} \le |D_m| \cdot g_{lmt},\ \forall l \in L,m \in M,t \in T$)

($g_{lmt} \le \sum_{d \in D_m} z_{dlt},\quad \forall l \in L,m \in M,t \in T$)

### 8.13 粗粒度换线次数下界

($h_{lt} \ge \sum_{m \in M} g_{lmt} - 1,\ \forall l \in L,t \in T$)

($h_{lt} \ge 0,\ \forall l \in L,t \in T$)

### 8.14 粗粒度换线工时下界

($setup_{lt} \ge \underline{ct}_{l}\cdot h_{lt},\ \forall l \in L,t \in T$)

## 9. 二阶段细排

### 9.1 适用范围

二阶段细排负责解决：

- `fix_seq` 与 `schedule_seq` 的班内先后
- `aps_schedule_order_ruler` 的材料项排序
- `aps_change_time_input` 的精确换线
- lot 连续与 `A-B-A` 消除

二阶段按主模型已经分配好的非空线班 ($l,t$) 分别求解。  
在工程实现上，更推荐“启发式 + 局部小规模 MIP”的混合方式。

### 9.2 先后变量、位置变量与启用变量联动

($y_{d_1d_2lt} \le z_{d_1lt},\ \forall d_1,d_2,l,t$)

($y_{d_1d_2lt} \le z_{d_2lt},\ \forall d_1,d_2,l,t$)

($y_{d_1d_2lt} + y_{d_2d_1lt} \le 1,\ \forall d_1 \neq d_2,l,t$)

($y_{d_1d_2lt} + y_{d_2d_1lt} \ge z_{d_1lt} + z_{d_2lt} - 1,\ \forall d_1 \neq d_2,l,t$)

($pos_{dlt} \le |D| \cdot z_{dlt},\ \forall d,l,t$)

($pos_{dlt} \ge z_{dlt},\ \forall d,l,t$)

($pos_{d_1lt} + 1 \le pos_{d_2lt} + |D|\cdot (1-y_{d_1d_2lt}),\ \forall d_1 \neq d_2,l,t$)

### 9.3 FIX 与继承顺序锚定

若同一线同一班次内两条已锁定任务满足 `seq_i < seq_j`，则：

($y_{ijlt} = 1,\ \forall (i,j,l,t)\text{ 满足固定顺序关系}$)

这条规则同时适用于：

- `fix_seq`
- `schedule_seq`

### 9.4 相邻换线变量联动与路径闭合

($\chi_{d_1d_2lt} \le y_{d_1d_2lt},\ \forall d_1,d_2,l,t$)

($pos_{d_2lt} \ge pos_{d_1lt} + 1 - |D|\cdot (1-\chi_{d_1d_2lt}),\ \forall d_1 \neq d_2,l,t$)

($pos_{d_2lt} \le pos_{d_1lt} + 1 + |D|\cdot (1-\chi_{d_1d_2lt}),\ \forall d_1 \neq d_2,l,t$)

($\sum_{d_2 \in D:d_2 \neq d_1} \chi_{d_1d_2lt} + tail_{d_1lt} = z_{d_1lt},\ \forall d_1,l,t$)

($\sum_{d_2 \in D:d_2 \neq d_1} \chi_{d_2d_1lt} + head_{d_1lt} = z_{d_1lt},\ \forall d_1,l,t$)

对每个进入二阶段的非空线班 ($l,t$)，有：

($\sum_{d \in D} head_{dlt} = 1,\ \forall (l,t)$)

($\sum_{d \in D} tail_{dlt} = 1,\ \forall (l,t)$)

### 9.5 精确换线工时

($setup_{lt}^{seq} = \sum_{d_1 \in D}\sum_{d_2 \in D,d_1 \neq d_2} ct_{d_1d_2l}\cdot \chi_{d_1d_2lt},\ \forall l \in L,t \in T$)

### 9.6 材料项排序目标

`aps_schedule_order_ruler` 当前样例给出的实际排序键顺序是：

1. `kb`
2. `log_up_assy`
3. `cover_assy`
4. `pcba`

将其预处理成排序偏好系数 ($P_{d_1d_2l}^{order}$) 后，可写成：

($\max Obj_{order} = \sum_{l \in L}\sum_{t \in T}\sum_{d_1 \in D}\sum_{d_2 \in D} P_{d_1d_2l}^{order}\cdot y_{d_1d_2lt}$)

### 9.7 精确换线目标

($\min Obj_{setup} = \sum_{l \in L}\sum_{t \in T} setup_{lt}^{seq}$)

### 9.8 lot 连续与 ABABA

lot 连续性和 `A-B-A` 消除在业务上重要，但完整线性化代价较高。  
本版建议放在二阶段启发式或局部小模型中处理，不强行放入主模型。

## 10. 关键表到模型位置映射

- `aps_schedule_demand_base_input`：主需求表，先按 `demand_id` 归并，再进入主模型
- `aps_schedule_demand_fai_input`：FAI 分组与等待时间，进入主模型硬约束
- `aps_schedule_demand_fix_input`：FIX 精确锁定，进入主模型硬约束
- `aps_schedule_line_input`：线体属性，进入参数生成
- `aps_schedule_line_calendar`：班次时段与开关，进入参数生成
- `aps_schedule_off_time_input`：停机与休息，进入参数生成
- `aps_schedule_uph_input`：UPH 与线机匹配，进入参数生成
- `aps_change_time_input`：换线时间，进入主模型粗粒度效率目标和二阶段精确换线
- `aps_schedule_limit_setting`：按 `group_id` 聚合后进入可行域参数
- `aps_schedule_order_qty`：大小单规则，进入可行域参数
- `aps_schedule_priority`：优先级组命中与 KPI 模式，进入主模型目标函数
- `aps_merge_priority_setting`：排前合并阶段顺序，作为预处理说明，不直接进入主模型目标
- `aps_schedule_order_ruler`：班内材料项排序，进入二阶段细排
- `aps_adjust_schedule_input`：一部分进入主模型硬锁定，一部分进入占用产能参数

## 11. 当前样例版结论

本版 `v7` 在 `v6` 基础上，进一步修正了 `aps_schedule_demand_base_input` 的 demand 定义口径：

1. 明确 `dnno` 按目录表定义是订单号，不是工序或节奏
2. 明确基础表需先按 `demand_id` 归并后再进入模型
3. 明确同一 `demand_id` 下若仅 `dnno` 不同，不应重复累加数量
4. 明确 demand 是否完成 (`u_d`) 的定义是 demand 级完成，而不是 `dnno` 级逐条完成
5. 保持 `v6` 中已成立的主模型符号、变量和主要公式不变，只修正这次由 `dnno` 展开导致的完成定义问题
