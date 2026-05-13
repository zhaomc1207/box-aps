# BOX APS业务规则到 MILP 数学约束映射表 v7

## 1. 建模范围与版本变化

本文基于 `v6` 的业务规则口径，并结合当前工程实现中的规模压缩策略，形成面向全量数据可求解的 `v7` 数学模型。

`v7` 的核心变化不是改变业务规则，而是改变规则进入优化器的方式：

1. `FIX` 和当前待排 demand 的继承锁定不再进入主 MILP 变量，而是在预处理/建模阶段直接形成固定排程并扣减线班产能。
2. 主模型不再对完整 `D × L × T` 或大规模稀疏三元组全集建变量，而是只对压缩后的候选集合建变量。
3. 近端窗口保留班次粒度，远期窗口合并为日桶，降低 slot 维度。
4. 默认不再建全量 `z_{dlt}` 和全局完工时间变量 `e_d`。
5. 交付目标改用累计交付 miss 约束表达。
6. FAI 默认通过候选窗口剪枝处理，只有在显式开启精确模式时才回退到 Big-M 约束。
7. 班内排序、精确换线、lot 连续、`A-B-A` 消除作为二阶段局部细排，不进入全局主 MILP。

当前默认压缩参数为：

- 交期 buffer：`due_buffer_days = 2`
- 每 demand 每天最多候选线体数：`max_lines_per_demand_day = 3`
- 每 demand 最多候选线班数：`max_slots_per_demand = 30`
- 远期日桶开始点：`bucket_after_days = 3`
- 默认锁定消元：开启
- 默认全量启用二进制变量 `z_{dlt}`：关闭
- 默认全局 FAI Big-M：关闭

## 2. 模型分层

`v7` 采用“四层口径”：

1. 预处理层  
   负责 demand 归并、主数据补齐、UPH 匹配、日历产能、停机、外部占能、优先级、候选三元组生成。
2. 候选压缩层  
   负责锁定订单消元、交期窗口剪枝、Top-K 线体剪枝、每 demand 最大候选数限制、远期日桶化。
3. 主 MILP 层  
   决定非锁定 demand 在压缩候选集合上的排产数量。
4. 二阶段细排层  
   对主模型输出的非空线班分别处理班内顺序、材料项排序、精确换线、lot 连续和 `A-B-A`。

## 3. 集合与索引

- 需求集合：($D$)，索引为 ($d$)
- 原始线体集合：($L$)，索引为 ($l$)
- 原始班次集合：($T$)，索引为 ($t$)
- 压缩后时间桶集合：($B$)，索引为 ($b$)
- 近端班次桶集合：($B^{slot} \subseteq B$)
- 远期日桶集合：($B^{day} \subseteq B$)
- 线体时间桶集合：($LB \subseteq L \times B$)
- 原始可行候选集合：($K^0 \subseteq D \times L \times T$)
- 剪枝后候选集合：($K \subseteq D' \times L \times B$)
- 锁定需求集合：($D^{lock} = D^{fix} \cup D^{adj}$)
- 主模型待优化需求集合：($D' = D \setminus D^{lock}$)
- 机型集合：($M$)，索引为 ($m$)
- FAI 分组集合：($G^{fai}$)，索引为 ($g$)

其中，($K$) 是主 MILP 的核心索引集合。所有主变量只在 ($K$) 上创建，而不是在完整 ($D \times L \times B$) 上创建。

## 4. 参数

### 4.1 需求参数

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
- 机型：($model_d$)
- Program：($program_d$)
- 材料项键值：($kb_d, logup_d, cover_d, pcba_d$)
- 工单号：($mo_d$)
- 批次号：($lot_d$)
- 主优先级权重：($W_d^{pri}$)
- KPI 评价开关：($\kappa_d^{ots}, \kappa_d^{fpsd}, \kappa_d^{ship2}$)

### 4.2 线体时间桶参数

- 时间桶开始时刻：($a_b$)
- 时间桶结束时刻：($e_b$)
- 时间桶排序号：($rank_b$)
- 线体时间桶总产能：($cap_{lb}$)
- 停机与休息时长：($down_{lb}$)
- 外部已排占用时长：($occ_{lb}^{ext}$)
- 锁定订单占用时长：($occ_{lb}^{lock}$)
- 净可用时长：($avail_{lb}$)
- 线体是否为 Cell 线：($cell_l \in \{0,1\}$)
- 线体所属 PU：($pu_l$)
- 候选 UPH：($uph_{dlb}$)，仅对 ($d,l,b) \in K$ 定义

线体时间桶净产能定义为：

($avail_{lb} = cap_{lb} - down_{lb} - occ_{lb}^{ext} - occ_{lb}^{lock},\quad \forall (l,b) \in LB$)

### 4.3 锁定排程参数

对每个锁定需求 ($d \in D^{lock}$)，预处理得到：

- 锁定线体：($l_d^{lock}$)
- 锁定时间桶：($b_d^{lock}$)
- 锁定数量：($q_d^{lock}$)
- 锁定顺序：($seq_d^{lock}$)
- 锁定 UPH：($uph_d^{lock}$)

其占用产能为：

($occ_{lb}^{lock} = \sum_{d \in D^{lock}: l_d^{lock}=l,\ b_d^{lock}=b} \frac{q_d^{lock}}{uph_d^{lock}},\quad \forall (l,b) \in LB$)

### 4.4 候选剪枝参数

- 交期 buffer 天数：($H^{due}$)，默认 `2`
- 每 demand 每天最多保留线体数：($K^{line}$)，默认 `3`
- 每 demand 最多保留候选数：($K^{slot}$)，默认 `30`
- 远期日桶起点：($H^{bucket}$)，默认 `3` 天

### 4.5 换线参数

- 线体最小换线时间下界：($\underline{ct}_l$)
- 机型是否在某线体时间桶出现：由变量 ($g_{lmb}$) 表达
- 粗粒度换线次数：($h_{lb}$)
- 粗粒度换线工时：($setup_{lb}$)

## 5. 候选集合生成与压缩

### 5.1 原始稀疏候选集合

首先按 UPH、线体、日历、MR Date、限制规则、大小单规则生成原始稀疏候选：

($K^0 = \{(d,l,t): elig^{base}_{dlt}=1,\ allow^{cal}_{lt}=1,\ allow^{mr}_{dt}=1,\ allow^{limit}_{dlt}=1,\ allow^{qty}_{dl}=1\}$)

### 5.2 锁定需求消元

对 ($d \in D^{lock}$)，不再在主模型中保留候选：

($D' = D \setminus D^{lock}$)

($K^1 = \{(d,l,t) \in K^0: d \in D'\}$)

锁定需求直接进入固定排程输出，并通过 ($occ_{lb}^{lock}$) 扣减产能。

### 5.3 交期窗口剪枝

定义需求最早交期：

($due_d = \min\{ots_d, fpsd_d, ship2_d\}$)

若 ($due_d$) 存在，仅保留：

($a_t \le due_d + H^{due}$)

即：

($K^2 = \{(d,l,t) \in K^1: due_d \text{ 为空 } \lor a_t \le due_d + H^{due}\}$)

若某个 demand 被交期窗口完全剪空，则从其原始候选中按时间和 UPH 追加 fallback 候选，保证原本有可行候选的 demand 不会因为剪枝直接丧失全部排产机会。

### 5.4 每日 Top-K 线体剪枝

对每个 demand 和每个自然日，只保留综合排序最优的 ($K^{line}$) 条线。排序依据为：

1. UPH 专用性更高优先
2. UPH 规则优先级更高优先
3. UPH 更高优先
4. 更早时间桶优先

得到候选集合 ($K^3$)。

### 5.5 每 demand 最大候选数限制

对每个 demand，将候选按“是否在交期内、时间先后、UPH 高低”排序，只保留前 ($K^{slot}$) 个：

($|K_d| \le K^{slot},\quad \forall d \in D'$)

得到 ($K^4$)。

### 5.6 远期日桶化

对开始时间在 ($H^{bucket}$) 天之后的班次，按自然日合并为日桶：

($b(t) = \begin{cases}t, & a_t < start + H^{bucket} \\ day(t), & a_t \ge start + H^{bucket}\end{cases}$)

于是最终主模型候选为：

($K = \{(d,l,b(t)): (d,l,t) \in K^4\}$)

若多个原始班次合并到同一 ($d,l,b$)，保留一条候选，UPH 取该候选中排序最优记录。

线体时间桶产能同步聚合：

($cap_{lb} = \sum_{t: b(t)=b} cap_{lt}$)

($down_{lb} = \sum_{t: b(t)=b} down_{lt}$)

($occ_{lb}^{ext} = \sum_{t: b(t)=b} occ_{lt}^{ext}$)

## 6. 主模型决策变量

### 6.1 默认主模型变量

- 排产数量：($x_{dlb} \in \mathbb{Z}_+,\quad \forall (d,l,b) \in K$)
- 未排数量：($c_d \in \mathbb{Z}_+,\quad \forall d \in D'$)
- OTS 未达成量：($miss_d^{ots} \in \mathbb{R}_+,\quad \forall d \in D'$)
- FPSD 未达成量：($miss_d^{fpsd} \in \mathbb{R}_+,\quad \forall d \in D'$)
- `ship_day_two` 未达成量：($miss_d^{ship2} \in \mathbb{R}_+,\quad \forall d \in D'$)
- 机型出现变量：($g_{lmb} \in \{0,1\}$)
- 粗粒度换线次数：($h_{lb} \in \mathbb{Z}_+$)
- 粗粒度换线工时：($setup_{lb} \in \mathbb{R}_+$)

### 6.2 可选精确逻辑变量

以下变量默认不创建，仅在显式开启精确模式时创建：

- 候选启用变量：($z_{dlb} \in \{0,1\}$)
- demand 完整完成变量：($u_d \in \{0,1\}$)，仅当 KPI 模式为 `ordermax` 时需要
- 完工时间变量：($E_d \in \mathbb{R}_+$)，仅当开启 FAI Big-M 精确模式时需要

## 7. 主模型约束

### 7.1 需求平衡

($\sum_{(l,b):(d,l,b)\in K} x_{dlb} + c_d = q_d,\quad \forall d \in D'$)

锁定需求不进入该约束，因为其数量已由固定排程满足。

### 7.2 稀疏可行域上界

由于 ($K$) 已经只包含可行候选，主模型只需对候选变量设置数量上界：

($x_{dlb} \le q_d,\quad \forall (d,l,b) \in K$)

若保留 `elig_{dlb}` 字段，则可写为：

($x_{dlb} \le q_d \cdot elig_{dlb},\quad \forall (d,l,b) \in K$)

### 7.3 线体时间桶产能

($\sum_{d:(d,l,b)\in K} \frac{x_{dlb}}{uph_{dlb}} + setup_{lb} \le avail_{lb},\quad \forall (l,b) \in LB$)

其中 ($avail_{lb}$) 已扣除外部已排占能和锁定订单占能。

### 7.4 交付未达成量

定义不晚于目标日期的候选桶集合：

($B_d^{ots} = \{b \in B: e_b \le ots_d + 1day\}$)

($B_d^{fpsd} = \{b \in B: e_b \le fpsd_d + 1day\}$)

($B_d^{ship2} = \{b \in B: e_b \le ship2_d + 1day\}$)

则：

($miss_d^{ots} \ge q_d - \sum_{(l,b):(d,l,b)\in K,\ b\in B_d^{ots}} x_{dlb},\quad \forall d \in D'$)

($miss_d^{fpsd} \ge q_d - \sum_{(l,b):(d,l,b)\in K,\ b\in B_d^{fpsd}} x_{dlb},\quad \forall d \in D'$)

($miss_d^{ship2} \ge q_d - \sum_{(l,b):(d,l,b)\in K,\ b\in B_d^{ship2}} x_{dlb},\quad \forall d \in D'$)

因此，`v7` 不需要用全局完工时间变量 ($E_d$) 来表达交付目标。

### 7.5 机型出现变量联动

令：

($K_{lmb} = \{(d,l,b) \in K: model_d=m\}$)

默认无全量 `z` 时：

($\sum_{(d,l,b)\in K_{lmb}} x_{dlb} \le U_{lmb}\cdot g_{lmb},\quad \forall l,m,b$)

($g_{lmb} \le \sum_{(d,l,b)\in K_{lmb}} x_{dlb},\quad \forall l,m,b$)

其中：

($U_{lmb} = \sum_{(d,l,b)\in K_{lmb}} q_d$)

若启用 `z` 精确模式，则可替换为：

($\sum_{(d,l,b)\in K_{lmb}} z_{dlb} \le |K_{lmb}|\cdot g_{lmb}$)

($g_{lmb} \le \sum_{(d,l,b)\in K_{lmb}} z_{dlb}$)

### 7.6 粗粒度换线次数与工时

($h_{lb} \ge \sum_m g_{lmb} - 1,\quad \forall (l,b) \in LB$)

($setup_{lb} \ge \underline{ct}_l \cdot h_{lb},\quad \forall (l,b) \in LB$)

该约束只提供主模型层面的换线时间下界，精确换线在二阶段处理。

## 8. 可选精确约束

### 8.1 候选启用变量联动

若开启 `use_activation_binaries`，则：

($x_{dlb} \le q_d \cdot z_{dlb},\quad \forall (d,l,b) \in K$)

($x_{dlb} \ge z_{dlb},\quad \forall (d,l,b) \in K$)

同一 demand 同一时间桶最多上一条线：

($\sum_{l:(d,l,b)\in K} z_{dlb} \le 1,\quad \forall d,b$)

默认压缩模式下不启用该约束；若出现同一 demand 同桶多线拆分，由二阶段或后处理修复。

### 8.2 订单笔数 KPI

若版本级 KPI 为 `ordermax`，创建 ($u_d$)：

($\sum_{(l,b):(d,l,b)\in K} x_{dlb} \ge q_d \cdot u_d,\quad \forall d \in D'$)

($\sum_{(l,b):(d,l,b)\in K} x_{dlb} \le q_d - (1-u_d),\quad \forall d \in D'$)

若 KPI 为 `qtymax`，不创建 ($u_d$)。

### 8.3 FAI Big-M 精确模式

默认模式下，FAI 通过候选窗口剪枝表达：

对 FAI 组 ($g$)，若首件最早可完成时间为 ($\widehat{E}_{g}^{first}$)，则 rest demand 的候选必须满足：

($a_b \ge \widehat{E}_{g}^{first} + lead_g$)

若开启 Big-M 精确模式，则创建 ($E_d$) 和 ($z_{dlb}$)：

($E_d \ge e_b - M(1-z_{dlb}),\quad \forall (d,l,b)\in K$)

($a_b + M(1-z_{rlb}) \ge E_{d_g^{first}} + lead_g,\quad \forall g,\ r\in D_g^{rest},\ (r,l,b)\in K$)

该模式更贴近 `v6`，但会显著增加变量和约束。

## 9. 目标函数

建议仍采用词典序优化。

### 9.1 第一层：交付达成与主优先级

($\min Obj_1 = \sum_{d \in D'} W_d^{pri}\cdot(\omega_{ots}\kappa_d^{ots}miss_d^{ots} + \omega_{fpsd}\kappa_d^{fpsd}miss_d^{fpsd} + \omega_{ship2}\kappa_d^{ship2}miss_d^{ship2} + \omega_{uns}c_d)$)

### 9.2 第二层：KPI 模式

若 ($kpi^{mode}=qtymax$)：

($\min Obj_2 = \sum_{d \in D'} c_d$)

若 ($kpi^{mode}=ordermax$)：

($\max Obj_2' = \sum_{d \in D'} u_d$)

### 9.3 第三层：线体与 Cell 线偏好

($\min Obj_3 = \sum_{(d,l,b)\in K} C_{dl}^{line}\cdot x_{dlb}$)

其中，若 demand 为 `fast_ship` 或定制化需求，且线体不是 Cell 线，则成本中加入非 Cell 惩罚。

### 9.4 第四层：粗粒度效率

($\min Obj_4 = \sum_{(l,b)\in LB} setup_{lb} + \sum_{l,m,b} g_{lmb}$)

## 10. 二阶段细排

### 10.1 输入

二阶段以主模型输出和锁定排程合并后的非空线体时间桶为输入：

($S_{lb} = \{d: x_{dlb} > 0\} \cup \{d \in D^{lock}: l_d^{lock}=l,\ b_d^{lock}=b\}$)

对每个非空 ($l,b$) 独立求解或启发式排序。

### 10.2 排序优先级

当前实现中，二阶段结果提取会为每个线班生成 `sequence`。排序口径为：

1. 已锁定任务优先，并按 `fix_seq` / `schedule_seq` 锚定
2. 相同 `lot` 尽量连续
3. 相同 `mo` 尽量连续
4. 相同 `model` 尽量集中
5. demand_id 稳定排序

### 10.3 后续可增强的局部 MIP

若需要更精确的班内细排，可在每个 ($l,b$) 的小集合 ($S_{lb}$) 上定义：

- 先后变量：($y_{ij}^{lb} \in \{0,1\}$)
- 相邻变量：($\chi_{ij}^{lb} \in \{0,1\}$)
- 位置变量：($pos_i^{lb}$)

并局部优化材料项排序、精确换线和 `A-B-A` 消除。该局部问题规模为 ($|S_{lb}|^2$)，不进入全局主模型。

## 11. 关键表到模型位置映射

- `aps_schedule_demand_base_input`：按 `demand_id` 归并为 demand 集合 ($D$)
- `aps_schedule_master_pn_input`：补齐 `model/program/color/texture`
- `aps_schedule_line_input`：生成线体集合 ($L$) 和 Cell 标记
- `aps_schedule_line_calendar`：生成原始班次和线体时间桶
- `aps_schedule_off_time_input`：扣减停机时间
- `aps_schedule_uph_input`：生成原始稀疏候选 ($K^0$)
- `aps_schedule_limit_setting`：进入候选可行域剪枝
- `aps_schedule_order_qty`：进入大小单候选剪枝
- `aps_schedule_demand_fix_input`：生成锁定排程并扣产能，不进入主变量
- `aps_adjust_schedule_input`：当前 demand 生成继承锁定；外部 demand 扣减外部占能
- `aps_schedule_demand_fai_input`：默认进入 FAI 候选窗口剪枝；精确模式进入 Big-M 约束
- `aps_schedule_priority`：生成优先级权重和 KPI 模式
- `aps_change_time_input`：生成粗粒度换线下界和二阶段精确换线参数
- `aps_schedule_order_ruler`：进入二阶段班内排序
- `aps_merge_priority_setting`：仍作为排前合并阶段顺序说明，不直接转成订单级目标权重

## 12. 规模效果

以当前全量预处理结果为例：

- 原始稀疏候选三元组：`2,442,153`
- 候选剪枝后：`489,506`
- 远期日桶化后：`298,177`
- 锁定消元后主模型候选约：`199,532`
- 主模型 active demand 候选中位数约：`15`

因此，`v7` 的主模型变量规模由 `v6` 的百万级 `x/z` 组合，压缩为默认约二十万级 `x` 变量，并默认取消全量 `z`、`e`、`u`，只保留必要的交付 miss、产能、机型出现和粗换线变量。

## 13. 当前结论

`v7` 保持 `v6` 的业务规则含义，但将全局 MILP 从“完整细粒度一次性求解”调整为“候选压缩 + 锁定消元 + 近端班次/远期日桶 + 主模型数量分配 + 二阶段局部细排”的工程可求解版本。

该版本适合作为全量 APS 排产的默认建模口径；若业务需要更严格的单线选择、FAI 精确先后或订单笔数最大化，可通过开启对应精确模式恢复相关二进制变量和 Big-M 约束。
