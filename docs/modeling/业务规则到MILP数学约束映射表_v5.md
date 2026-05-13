# BOX APS业务规则到 MILP 数学约束映射表 v5

## 1. 建模范围

本文基于以下三份资料形成当前数据版的正式数学模型：

- `APS系统数据表目录.xlsx`
- `BOX-智能排产约束规则.xlsx`
- `BOX-APS脱敏数据-2.xlsx`

结合目录表与脱敏数据的实际 sheet，可确认当前样例数据中存在的主要输入表包括：

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

当前样例数据中明确不存在以下三张表：

- `aps_schedule_cycle_merge_setting_input`
- `aps_schedule_demand_expand_input`
- `aps_change_model_input`

因此，v5 采用以下当前数据版建模边界：

1. `aps_merge_priority_setting` 作为排前合并阶段顺序配置使用。  
   它描述的是“先按哪一层做合并/分组”，不是订单级优先级权重，因此不直接进入主模型目标函数。

2. 不做基于 `aps_schedule_cycle_merge_setting_input` 的 Cell 线循环排序建模。  
   Cell 线只保留主模型中的线体偏好目标。

3. 不使用 `aps_schedule_demand_expand_input` 中的扩展字段。  
   FAI、FIX、继承排程等规则直接由专门表或基础需求表字段驱动。

4. 本版正式模型的换线时间仅基于 `aps_change_time_input`。由于当前样例数据中不存在 `aps_change_model_input`，因此本版不使用机型相似度修正换线时间。

5. `aps_adjust_schedule_input` 需要拆成两部分理解：  
   一部分是当前待排 demand 的继承锁定；另一部分是当前不在 `demand_base` 中、但已经占用未来线班产能的外部已排任务。

## 2. 建模目标

第一阶段主 MILP 在“线体-日期-班次”粒度上解决以下问题：

- 哪个需求排到哪条线、哪天、哪班
- 每个需求排多少
- 如何在交付、产能、FIX、FAI、继承排程、线体匹配等条件下得到可行解
- 如何在可行解中进一步优化优先级、排程量、Cell 线偏好、换线损失和班内机型集中度

第二阶段细排只解决：

- 班内颜色 / 材料项排序
- 精确换线顺序
- ABABA 消除

## 3. 集合与索引

- 需求集合：($D$)，索引为 ($d$)
- 线体集合：($L$)，索引为 ($l$)
- 班次时段集合：($T$)，索引为 ($t$)
- 机型集合：($M$)，索引为 ($m$)
- FAI 分组集合：($G$)，索引为 ($g$)
- 主优先级条件行集合：($R^{pri}$)，索引为 ($r$)
- 主优先级分组集合：($G^{pri}$)，索引为 ($g$)
- 合并阶段集合：($K^{merge}$)，索引为 ($k$)

常用子集：

- FIX 需求集合：($D^{fix} \subseteq D$)
- 当前待排集合中的继承排程需求集合：($D^{adj} \subseteq D$)
- FAI 需求集合：($D^{fai} \subseteq D$)
- 机型为 ($m$) 的需求集合：($D_m \subseteq D$)
- Cell 线集合：($L^{cell} \subseteq L$)
- 继承排程中属于当前待排集合的记录集合：($A^{adj,in}$)
- 继承排程中不属于当前待排集合、仅占用产能的记录集合：($A^{adj,ext}$)

## 4. 参数

### 4.1 基础参数

- 需求数量：($q_d$)
- 需求机型：($model_d$)
- 业务分类：($mcode_d$)
- 时段开始时间：($a_t$)
- 时段结束时间：($b_t$)

### 4.2 产能与可行域参数

- 班次总工时：($cap_{lt}$)
- 停机工时：($down_{lt}$)
- 预留工时：($res_{lt}$)
- 外部已排任务占用工时：($occ_{lt}^{adj}$)
- 净可用工时：($avail_{lt}$)
- 合法 UPH：($uph_{dlt}$)
- 基础线机可行性：($elig^{base}_{dlt} \in \{0,1\}$)
- 限制规则可行性：($allow^{limit}_{dlt} \in \{0,1\}$)
- 大小单规则可行性：($allow^{qty}_{dl} \in \{0,1\}$)
- 日历可行性：($allow^{cal}_{lt} \in \{0,1\}$)
- MR Date 可行性：($allow^{mr}_{dt} \in \{0,1\}$)
- 综合可行性：($elig_{dlt} \in \{0,1\}$)
- 线体是否为 Cell 线：($cell_l \in \{0,1\}$)

### 4.3 交付参数

- OTS 截止时段集合：($T_d^{ots} \subseteq T$)
- FPSD 截止时段集合：($T_d^{fpsd} \subseteq T$)
- `ship_day_two` 截止时段集合：($T_d^{ship2} \subseteq T$)
- OTS KPI 是否评价该需求：($\kappa_d^{ots} \in \{0,1\}$)
- FPSD KPI 是否评价该需求：($\kappa_d^{fpsd} \in \{0,1\}$)

### 4.4 优先级与线体偏好参数

- 主优先级组顺位：($p_g^{pri}$)
- 主优先级条件行命中参数：($sat_{dr}^{pri} \in \{0,1\}$)
- 主优先级组命中参数：($hit_{dg}^{pri} \in \{0,1\}$)
- 订单主优先级顺位：($p_d^{pri}$)
- 主优先级权重：($W_d^{pri}$)
- 排前合并阶段顺序：($p_k^{merge}$)
- 线体偏好成本：($C_{dl}^{line}$)
- Cell 线偏好成本：($C_{dl}^{cell}$)
- 材料项排序偏好系数：($P_{d_1d_2l}^{order}$)
- OTS 惩罚权重：($\omega_{ots}$)
- FPSD 惩罚权重：($\omega_{fpsd}$)
- `ship_day_two` 惩罚权重：($\omega_{ship2}$)
- 未排数量惩罚权重：($\omega_{uns}$)

说明：

- `aps_schedule_priority` 是规则表，不是订单级权重表。
- 同一 `priority_group` 内是“且”关系；同一 `priority` 下不同 `priority_group` 是“或”关系。
- 因此先对每条条件行判断是否命中，得到 ($sat_{dr}^{pri}$)；再按组聚合，得到 ($hit_{dg}^{pri}$)。
- 对每个优先级组 ($g \in G^{pri}$)，由组内对应条件行的公共 `priority` 生成组顺位 ($p_g^{pri}$)。
- 再由命中优先级组生成订单主优先级顺位：

($p_d^{pri} = \min \{p_g^{pri} : g \in G^{pri},\ hit_{dg}^{pri}=1\},\ \forall d \in D$)

- 最后将订单主优先级顺位映射为优化权重：

($W_d^{pri} = w(p_d^{pri}),\ \forall d \in D$)

- `aps_merge_priority_setting` 不生成订单级权重。它只定义排前合并阶段的执行顺序，例如 `pn属性合并 -> demand属性合并 -> 颜色材料项合并 -> pn合并`。

### 4.5 特殊规则参数

- FIX 线体：($line_d^{fix}$)
- FIX 时段：($slot_d^{fix}$)
- FIX 数量：($qty_d^{fix}$)
- 继承线体：($line_d^{adj}$)
- 继承时段：($slot_d^{adj}$)
- 继承数量：($qty_d^{adj}$)
- FAI 首件需求：($d_g^{first}$)
- FAI 余量需求集合：($D_g^{rest}$)
- FAI 等待时长：($lead_g$)

### 4.6 换线参数

当前数据版仅基于 `aps_change_time_input` 定义换线时间。

- 需求对之间的基础换线时间：($ct_{d_1d_2l}$)
- 班次最小基础换线时间：($\underline{ct}_{l}$)

其中：

($ct_{d_1d_2l} = f_{time}(mcode, model, program, material\_type, pu),\ \forall d_1,d_2 \in D,l \in L$)

若未命中具体规则，则按该 `mcode` 的默认换线时间取值。  
若同机型且业务认定不发生换线，则可设：

($ct_{d_1d_2l} = 0,\ \forall d_1,d_2 \in D,l \in L \text{ with } model_{d_1}=model_{d_2}$)

班次最小基础换线时间定义为：

($\underline{ct}_{l} = \min \{ct_{d_1d_2l}: d_1,d_2 \in D,\ d_1 \neq d_2,\ model_{d_1} \neq model_{d_2}\},\ \forall l \in L$)

### 4.7 大 M 参数

- 大 M 常数：($M$)

## 5. 决策变量

### 5.1 主模型变量

- 排产数量：($x_{dlt} \in \mathbb{Z}_+$)
- 排产启用：($z_{dlt} \in \{0,1\}$)
- 需求是否被排到：($u_d \in \{0,1\}$)
- 未排数量：($c_d \in \mathbb{Z}_+$)
- 需求完成时间：($e_d \in \mathbb{R}_+$)
- OTS 未达成量：($miss_d^{ots} \in \mathbb{R}_+$)
- FPSD 未达成量：($miss_d^{fpsd} \in \mathbb{R}_+$)
- Ship Date 未达成量：($miss_d^{ship} \in \mathbb{R}_+$)
- 机型在班次上线体上是否出现：($g_{lmt} \in \{0,1\}$)
- 班次粗粒度换线次数下界：($h_{lt} \in \mathbb{Z}_+$)
- 班次粗粒度换线工时：($setup_{lt} \in \mathbb{R}_+$)

### 5.2 二阶段变量

- 同班次先后变量：($y_{d_1d_2lt} \in \{0,1\}$)
- 相邻换线变量：($\chi_{d_1d_2lt} \in \{0,1\}$)
- 精确换线工时：($setup_{lt}^{seq} \in \mathbb{R}_+$)

## 6. 预处理定义

### 6.1 净可用工时

($avail_{lt} = cap_{lt} - down_{lt} - res_{lt} - occ_{lt}^{adj},\ \forall l \in L,t \in T$)

### 6.2 综合可行性

($elig_{dlt} = elig^{base}_{dlt} \cdot allow^{limit}_{dlt} \cdot allow^{qty}_{dl} \cdot allow^{cal}_{lt} \cdot allow^{mr}_{dt},\ \forall d \in D,l \in L,t \in T$)

## 7. 主模型目标函数

建议采用词典序优化。

### 7.1 第一层：交付与主优先级

先由 `aps_schedule_priority` 生成订单级主优先级顺位与权重：

($p_d^{pri} = \min \{p_g^{pri} : g \in G^{pri},\ hit_{dg}^{pri}=1\},\ \forall d \in D$)

($W_d^{pri} = w(p_d^{pri}),\ \forall d \in D$)

($\min Obj_1 = \sum_{d \in D} W_d^{pri}\cdot (\omega_{ots}\cdot \kappa_d^{ots}\cdot miss_d^{ots} + \omega_{fpsd}\cdot \kappa_d^{fpsd}\cdot miss_d^{fpsd} + \omega_{ship2}\cdot miss_d^{ship} + \omega_{uns}\cdot c_d)$)

### 7.2 第二层：排程量最大或订单笔数最大

`aps_schedule_priority` 中的 `kpi` 字段用于给出优化方向。  
在数学模型中，应先将其整理为版本级 KPI 模式，再决定第二层目标。

当前样例数据默认 `qtymax`：

($\min Obj_2 = \sum_{d \in D} c_d$)

若版本级 KPI 模式为 `ordermax`：

($\max Obj_2' = \sum_{d \in D} u_d$)

### 7.3 第三层：排前合并阶段顺序

`aps_merge_priority_setting` 在当前样例中只定义排前合并阶段的执行顺序，不直接形成订单级目标函数。  
因此本版主模型仍以 `demand_id` 为排产对象，合并阶段顺序仅作为预处理规则保留。

### 7.4 第四层：线体分配偏好

($\min Obj_4 = \sum_{d \in D}\sum_{l \in L}\sum_{t \in T} C_{dl}^{line}\cdot x_{dlt}$)

### 7.5 第五层：Cell 线偏好

($\min Obj_5 = \sum_{d \in D}\sum_{l \in L}\sum_{t \in T} C_{dl}^{cell}\cdot (1-cell_l)\cdot x_{dlt}$)

### 7.6 第六层：粗粒度换线工时最少

($\min Obj_6 = \sum_{l \in L}\sum_{t \in T} setup_{lt}$)

### 7.7 第七层：班次内机型种类最少

($\min Obj_7 = \sum_{l \in L}\sum_{m \in M}\sum_{t \in T} g_{lmt}$)

## 8. 主模型约束

### 8.1 需求平衡

($\sum_{l \in L}\sum_{t \in T} x_{dlt} + c_d = q_d,\ \forall d \in D$)

### 8.2 启用联动

($x_{dlt} \le q_d \cdot z_{dlt},\ \forall d \in D,l \in L,t \in T$)

($x_{dlt} \ge z_{dlt},\ \forall d \in D,l \in L,t \in T$)

### 8.3 需求是否被排到

($\sum_{l \in L}\sum_{t \in T} x_{dlt} \le q_d \cdot u_d,\ \forall d \in D$)

($\sum_{l \in L}\sum_{t \in T} x_{dlt} \ge u_d,\ \forall d \in D$)

### 8.4 同一需求同一班次最多上一条线

($\sum_{l \in L} z_{dlt} \le 1,\ \forall d \in D,t \in T$)

### 8.5 线体班次产能

生产工时与粗粒度换线工时之和不得超过班次净可用工时：

($\sum_{d \in D:, elig_{dlt}=1}\frac{x_{dlt}}{uph_{dlt}} + setup_{lt} \le avail_{lt},\ \forall l \in L,t \in T$)

### 8.6 综合可行域

该约束统一覆盖以下业务规则：

- MR Date
- 生产日历
- off time
- 预留产能
- 线机匹配
- 限制条件
- 大小单限制

数学形式为：

($x_{dlt} \le q_d \cdot elig_{dlt},\ \forall d \in D,l \in L,t \in T$)

### 8.7 完工时间定义

($e_d \ge b_t - M(1-z_{dlt}),\ \forall d \in D,l \in L,t \in T$)

### 8.8 交付未达成量定义

($miss_d^{ots} \ge q_d - \sum_{l \in L}\sum_{t \in T_d^{ots}} x_{dlt},\ \forall d \in D$)

($miss_d^{fpsd} \ge q_d - \sum_{l \in L}\sum_{t \in T_d^{fpsd}} x_{dlt},\ \forall d \in D$)

($miss_d^{ship} \ge q_d - \sum_{l \in L}\sum_{t \in T_d^{ship2}} x_{dlt},\ \forall d \in D$)

($miss_d^{ots} \ge 0,\ \forall d \in D$)

($miss_d^{fpsd} \ge 0,\ \forall d \in D$)

($miss_d^{ship} \ge 0,\ \forall d \in D$)

### 8.9 FIX 约束

当前样例数据中，`aps_schedule_demand_fix_input` 满足：

- 一条 `demand_id` 对应一条 FIX 记录
- `fix_qty = q_d`

因此，v5 按“整单精确锁定”处理：

($x_{d,line_d^{fix},slot_d^{fix}} = q_d,\ \forall d \in D^{fix}$)

($x_{dlt} = 0,\ \forall d \in D^{fix},(l,t) \neq (line_d^{fix},slot_d^{fix})$)

### 8.10 继承排程约束

`aps_adjust_schedule_input` 在当前样例里应拆分为两类：

1. 对于 `demand_id` 仍在当前 $D$ 中的记录，做整单精确继承  
2. 对于 `demand_id` 不在当前 $D$ 中的记录，仅作为外部已排任务占用产能，并已汇总进 ($occ_{lt}^{adj}$)

对第一类记录，当前样例中 `schedule_qty = q_d`，且一条 `demand_id` 只对应一条记录，因此写为：

($x_{d,line_d^{adj},slot_d^{adj}} = q_d,\ \forall d \in D^{adj}$)

($x_{dlt} = 0,\ \forall d \in D^{adj},(l,t) \neq (line_d^{adj},slot_d^{adj})$)

### 8.11 FAI 约束

若首件需求已拆分为独立需求，则余量需求的投产时段不得早于首件完成加等待时长：

($a_t + M(1-z_{rlt}) \ge e_{d_g^{first}} + lead_g,\ \forall g \in G,\forall r \in D_g^{rest},\forall l \in L,\forall t \in T$)

### 8.12 机型出现变量联动

($\sum_{d \in D_m} z_{dlt} \le |D_m| \cdot g_{lmt},\ \forall l \in L,m \in M,t \in T$)

### 8.13 粗粒度换线次数下界

若同一线体同一班次出现多个机型，则至少发生换线：

($h_{lt} \ge \sum_{m \in M} g_{lmt} - 1,\ \forall l \in L,t \in T$)

($h_{lt} \ge 0,\ \forall l \in L,t \in T$)

### 8.14 粗粒度换线工时下界

($setup_{lt} \ge \underline{ct}_{l}\cdot h_{lt},\ \forall l \in L,t \in T$)

## 9. 二阶段细排模型

当前数据版二阶段只保留 `aps_schedule_order_ruler` 与 `aps_change_time_input` 对应的精细排序与换线优化。

### 9.1 先后变量与启用变量联动

($y_{d_1d_2lt} \le z_{d_1lt},\ \forall d_1,d_2,l,t$)

($y_{d_1d_2lt} \le z_{d_2lt},\ \forall d_1,d_2,l,t$)

($y_{d_1d_2lt} + y_{d_2d_1lt} \le 1,\ \forall d_1 \neq d_2,l,t$)

($y_{d_1d_2lt} + y_{d_2d_1lt} \ge z_{d_1lt} + z_{d_2lt} - 1,\ \forall d_1 \neq d_2,\ l,t$)

### 9.2 相邻换线变量联动

($\chi_{d_1d_2lt} \le y_{d_1d_2lt},\ \forall d_1,d_2,l,t$)

### 9.3 精确换线工时

($setup_{lt}^{seq} = \sum_{d_1 \in D}\sum_{d_2 \in D,d_1 \neq d_2} ct_{d_1d_2l}\cdot \chi_{d_1d_2lt},\ \forall l \in L,t \in T$)

### 9.4 材料项排序目标

设由 `aps_schedule_order_ruler` 生成排序偏好系数 ($P_{d_1d_2l}^{order}$)，则：

($\max Obj_{order} = \sum_{l \in L}\sum_{t \in T}\sum_{d_1 \in D}\sum_{d_2 \in D} P_{d_1d_2l}^{order}\cdot y_{d_1d_2lt}$)

### 9.5 精确换线目标

($\min Obj_{setup} = \sum_{l \in L}\sum_{t \in T} setup_{lt}^{seq}$)

## 10. 当前数据版不纳入模型的表

以下三张表因为当前样例数据中不存在，所以不纳入 v5 正式模型：

- `aps_schedule_cycle_merge_setting_input`
- `aps_schedule_demand_expand_input`
- `aps_change_model_input`

对应处理方式如下：

1. `aps_schedule_cycle_merge_setting_input`  
   当前不做 Cell 线循环排序建模，只保留主模型中的 Cell 线偏好目标。

2. `aps_schedule_demand_expand_input`  
   当前不使用扩展字段来驱动规则，相关规则直接由基础需求表、FAI 表、FIX 表和继承排程表驱动。

3. `aps_change_model_input`  
   当前不使用机型相似度修正换线时间，换线时间仅按 `aps_change_time_input` 生成。

补充说明：

- `aps_merge_priority_setting` 当前样例中存在，但它只表示排前合并阶段顺序，不直接形成主模型目标函数。

## 11. 后续扩展说明

若后续实际运行数据补充 `aps_change_model_input`，可将换线参数扩展为：

- 机型换线相似度：($sim_{d_1d_2l} \in [0,1]$)
- 有效换线时间：($ct^{eff}_{d_1d_2l} = ct^{base}_{d_1d_2l}\cdot (1-sim_{d_1d_2l})$)

此时，第 4.6 节和第 9.3 节中的 ($ct_{d_1d_2l}$) 可整体替换为 ($ct^{eff}_{d_1d_2l}$)。

## 12. 结论

v5 当前已经从“规则映射说明”收敛为“当前数据版正式数学模型”，并且与当前实际数据保持一致：

- 不再依赖当前样例数据中不存在的四张表
- 主模型直接以 `demand_id` 为排产对象
- Cell 线循环排序不纳入当前版本
- 扩展字段不纳入当前版本
- 机型相似度不纳入当前版本
- 换线时间在当前版本中仅由 `aps_change_time_input` 显式进入主模型和二阶段

因此，当前 v5 可以作为后续建模实现的正式基础版本。
