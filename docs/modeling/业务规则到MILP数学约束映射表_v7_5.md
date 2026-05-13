# BOX APS业务规则到 MILP 数学约束映射表 v7.5

> **公式书写约定**  
> 
> - **行内**（符号、短式）：用**一对** `$` 包裹，如 `$D$`、`$x_{dlt}$`。  
> - **独立成行**：**首行只写** `$$`，**末行只写** `$$`，中间为公式；避免行首缩进的 `$$`。  
> - **避免**在同一句中连续拼接多段 `$$…$$`，以免渲染器误判为连续的 `$`。

---

## 1. 文档定位与建模范围

本版 **`v7.5`** 给出 BOX APS **主 MILP + 前置数据准备 + 班内细排 + 解后校核** 的完整数学建模说明。本文档直接面向实现，目标是把输入表、业务语义、可行域、目标函数、二阶段排序与审计口径一次性定义清楚，使不同实现者在不依赖口头解释的情况下也能构造语义一致的模型。

本版的设计原则如下：

1. **以 demand 为主索引对象**，但允许排前按规则把若干原始需求合并为**虚拟需求**参与主 MILP。
2. **主 MILP 只决定线体–槽位上的整数产量分配**，不在主问题中展开班内精确执行顺序。
3. **锁定需求允许按数量级处理**；当业务数据表现为整单锁定时，该数量级模型自然退化为整单锁定。
4. **交付及时性按“提前 buffer 后的及时槽集合”定义**，并对不同 KPI 分别配置。
5. **MR 既决定最早可投产时刻，也可决定 KPI 豁免**；“能否生产”与“是否计入交付 KPI”是两个相互关联但不相同的概念。
6. **FAI、换线、材料排序、lot 连续性**在主模型中只保留必要的聚合表达，其余细节留给二阶段排序与校核。

本文档不依附于某个特定代码仓库，但默认输入来源是 APS 标准化工作簿中的工作表集合。字段语义以企业输入表定义与业务澄清口径为准。

### 1.1 建模边界

本文覆盖以下四层：

1. **数据准备层**：版本过滤、主数据补全、排前合并、锁定识别、外部占用、UPH 匹配、候选生成、日桶化。
2. **主 MILP 层**：在稀疏候选集上进行整数排产，满足能力、交付、锁定、可行性、粗换线与可选 FAI 先后。
3. **班内细排层**：对主 MILP 已分配的线体–槽位产量做顺序化，体现 FIX 顺序、机型聚合、lot 连续与材料排序键。
4. **解后校核层**：审计 FAI 日历口径、同槽拆线、实际换线摘要、锁定一致性与交付统计。

### 1.2 不进入主 MILP 的业务内容

以下内容不作为主 MILP 的精确硬约束，而是通过候选生成、二阶段排序、目标偏好或解后校核处理：

- 同槽内逐件执行顺序；
- `aps_schedule_order_ruler` 给出的材料项排序链；
- lot / mo 的连续性最优组织；
- 精确的相邻任务换线成本；
- FAI 在分钟级/小时级精确班内落点；
- 颜色材料项合并后的原始行回写顺序。

### 1.3 输入表范围

以下工作表在本版建模中有明确作用：

**必选**

- `aps_schedule_master_pn_input`
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

**可选**

- `aps_schedule_reserver_input`
- `aps_schedule_demand_reserve_input`
- `aps_schedule_merge_priority_setting`
- `aps_schedule_cycle_merge_setting`

---

## 2. 业务术语与记号约定

### 2.1 业务术语

- **原始需求行**  
  指 `aps_schedule_demand_base_input` 中一条待排记录，记为 $r \in R$。

- **虚拟需求 / 合并后需求**  
  指在排前合并后进入主 MILP 的需求对象，记为 $d \in D$。一个 $d$ 可对应一条或多条原始需求行。

- **锁定需求**  
  指业务已明确指定线体、班次或顺序，主模型不再自由重排的需求。包括 FIX 与当前待排集内的继承排程两类。

- **外部占用**  
  指出现在 `aps_adjust_schedule_input` 中、但不属于当前待排集的历史/外部已排任务，对本轮主问题表现为产能占用。

- **槽（slot）**  
  指线体上可供主 MILP 分配产量的离散时间段。可为原始班次，也可为远期聚合形成的日桶。

- **及时槽集合**  
  对某需求 $d$ 和某 KPI 而言，凡在这些槽上完工即可视为该 KPI “及时”的槽集合，记为 $T_d^{\mathrm{on},k}$。

- **交期外扩展窗口**  
  仅用于保留候选，不等于及时交付。即使超出及时槽集合，仍可在一定自然日扩展内保留候选以便安排补救生产。

- **班内细排**  
  在给定线体–槽位已分配产量的前提下，对该槽内任务生成顺序号 `seq`，以体现 FIX 顺序、机型聚合、lot / mo 连续与材料排序链。

### 2.2 通用数学记号

- $\mathbb{Z}_{\ge 0}$：非负整数；$\mathbb{R}_{\ge 0}$：非负实数。
- $\mathbf{1}(\cdot)$：指示函数，条件成立取 1，否则取 0。
- 对槽 $t$，记 $\sigma_t,\epsilon_t$ 分别为该槽的开始、结束时刻在统一时间轴上的标量。
- 若槽 $t$ 是日桶，则 $\sigma_t,\epsilon_t$ 分别为该桶最早开始与最晚结束时刻。
- $M$：Big-M 常数，取值须不小于所有相关时间差的安全上界。

---

## 3. 模型分层

1. **输入清洗与版本过滤**  
   读取工作簿，按 `schedule_version` 与可选 `sub_schedule_version` 过滤，并统一字段类型、日期格式与主键口径。

2. **排前需求组织层**  
   做主数据补全、排前合并、锁定识别、外部占用抽取、优先级与 KPI 规则解释。

3. **稀疏候选构造层**  
   基于 MR、UPH、日历、限制规则、大小单规则、交期外扩展等构造原始候选集 $K^0$，再做压缩得到 $K$。

4. **主 MILP 层**  
   在 $K$ 上定义整数产量、未排量、交付 miss、粗换线与可选激活变量，求解主问题。

5. **班内细排层**  
   对每个有产量的 $(l,t)$，结合锁定序、机型、lot、mo、材料键生成执行顺序。

6. **审计与回写层**  
   把虚拟需求解拆回原始需求行，输出交付统计、FAI 校核、同槽拆线校核与换线摘要。

---

## 4. 集合、索引与映射

- $R$：原始需求行集合，元素记为 $r$。
- $D$：排前合并后的需求集合，元素记为 $d$。
- $D^{\mathrm{lock}}$：锁定需求集合。
- $D' = D \setminus D^{\mathrm{lock\_elim}}$：在采用锁定消元时真正进入主 MILP 的需求集合。
- $L$：线体集合，元素记为 $l$。
- $T$：主 MILP 使用的槽集合，元素记为 $t$。
- $M^{model}$：机型取值集合，元素记为 $m$。
- $G$：排前合并组集合，元素记为 $g$。
- $\mathcal{A}^{\mathrm{fai}}$：FAI 有向弧集合，元素为 $(p,q)$，其中 $p$ 为首件需求，$q$ 为余量需求。

定义映射：

$$
\phi : R \to D
$$

表示原始需求行到虚拟需求的映射。

$$
R_d = \{r \in R \mid \phi(r)=d\}
$$

表示虚拟需求 $d$ 对应的原始需求行集合。

$$
K^0 \subseteq D \times L \times T
$$

表示压缩前原始候选集。

$$
K \subseteq \bar{D} \times L \times T
$$

表示主 MILP 候选集，其中 $\bar{D}=D$ 或 $\bar{D}=D'$，视锁定建模方式而定。

$$
LT = \{(l,t)\in L\times T \mid \mathrm{Avail}_{lt}>0\}
$$

表示净可用机时为正的线体–槽位集合。

---

## 5. 输入表到参数的映射

### 5.1 需求主数据

来自 `aps_schedule_demand_base_input`：

- `demand_id`：原始需求主键；
- `qty`：需求数量；
- `mr_day`：物料齐套日期；
- `ots_date`、`fpsd`、`ship_day_two`：交付相关日期；
- `mcode`、`plant`、`pn`、`model`、`program`、`texture`、`color`、`country`；
- `mo`、`lot`；
- `pre_lock`、`pre_plan`、`om_urgent`、`fast_ship`、`cust_svc`；
- `ord_qty`、`line_qty`、`priority_code`、`total_index` 等。

### 5.2 产品主数据补全

来自 `aps_schedule_master_pn_input`，用于用 `pn` 补全：

- `model`
- `series`
- `program`
- `texture`
- `color`

若需求主表与主数据表同名字段不一致，则以“需求表显式值优先，缺失时由主数据补齐”为准。

### 5.3 线体与日历

来自：

- `aps_schedule_line_input`
- `aps_schedule_line_calendar`
- `aps_schedule_off_time_input`
- 可选 `aps_schedule_reserver_input`

共同构成：

- 槽集合 $T$；
- 线体集合 $L$；
- 槽起止时刻；
- 班次开闭状态；
- 基础机时上界、停机扣减与预留扣减。

### 5.4 产能与换线

来自：

- `aps_schedule_uph_input`
- `aps_change_time_input`

共同构成：

- 候选 $(d,l,t)$ 上的 UPH；
- 粗换线时间下界；
- 快单/定制单等差异化 UPH 匹配。

### 5.5 规则类输入

来自：

- `aps_schedule_priority`
- `aps_merge_priority_setting`
- 可选 `aps_schedule_merge_priority_setting`
- `aps_schedule_limit_setting`
- `aps_schedule_order_qty`
- `aps_schedule_order_ruler`
- 可选 `aps_schedule_cycle_merge_setting`

共同决定：

- 排前合并键；
- 优先级与 KPI 模式；
- 候选限制；
- 大小单适线规则；
- 班内排序键链；
- Cell 线偏好等软规则。

### 5.6 特殊需求规则

来自：

- `aps_schedule_demand_fix_input`
- `aps_adjust_schedule_input`
- `aps_schedule_demand_fai_input`

共同决定：

- FIX 锁定；
- 当前待排集内继承锁定；
- 当前待排集外部占用；
- FAI 首件/余量先后与等待时间。

---

## 6. 参数定义

### 6.1 需求侧参数

对每个 $d\in D$：

- $q_d \in \mathbb{Z}_{\ge 0}$：虚拟需求总量；
- $mr_d$：最早可投产日历时间；
- $ots_d, fpsd_d, ship2_d$：交付相关日期；
- $\mathrm{model}(d)$：机型；
- $\mathrm{mcode}(d)$、$\mathrm{plant}(d)$：业务分类与工厂；
- $u^{\mathrm{fast}}_d, u^{\mathrm{cust}}_d, u^{\mathrm{urgent}}_d \in \{0,1\}$：快单、定制、紧急标记；
- $\mathrm{lot}(d)$、$\mathrm{mo}(d)$：lot 与工单属性；
- $W_d^{\mathrm{pri}}$：优先级基础权重；
- $W_d^{\mathrm{eff}}$：考虑紧急放大后的有效权重。

对合并组内日期，采用以下保守聚合：

$$
mr_d = \max_{r\in R_d} mr_r
$$

$$
ots_d = \min_{r\in R_d} ots_r,\quad
fpsd_d = \min_{r\in R_d} fpsd_r,\quad
ship2_d = \min_{r\in R_d} ship2_r
$$

布尔型标记采用“或”聚合：

$$
u^{\mathrm{fast}}_d = \max_{r\in R_d} u^{\mathrm{fast}}_r
$$

其余布尔标记同理。

### 6.2 线体–槽位参数

对每个 $(l,t)\in L\times T$：

- $\mathrm{Cap}_{lt}$：班次原始机时上界；
- $\mathrm{Down}_{lt}$：停机、休息、维护扣减；
- $\mathrm{Res}_{lt}$：预留扣减；
- $\mathrm{Occ}^{\mathrm{ext}}_{lt}$：外部占用；
- $\mathrm{Occ}^{\mathrm{lock}}_{lt}$：锁定需求占用；
- $\mathrm{Avail}_{lt}$：净可用机时；
- $\mathrm{cell}_l \in \{0,1\}$：是否 Cell 线。

定义：

$$
\mathrm{Avail}_{lt}=
\mathrm{Cap}_{lt}
-\mathrm{Down}_{lt}
-\mathrm{Res}_{lt}
-\mathrm{Occ}^{\mathrm{ext}}_{lt}
-\mathrm{Occ}^{\mathrm{lock}}_{lt}
$$

### 6.3 候选与可行性参数

对每个 $(d,l,t)\in K^0$：

- $\mathrm{uph}_{dlt}>0$：单位小时产量；
- $\mathrm{elig}_{dlt}\in\{0,1\}$：综合可行性指示；
- $C_{dlt}\ge 0$：线体偏好或非 Cell 惩罚系数。

### 6.4 KPI 与交付参数

定义 KPI 集合：

$$
\mathcal{K}=\{\mathrm{ots},\mathrm{fpsd},\mathrm{ship2}\}
$$

对每类 KPI $k\in\mathcal{K}$：

- $H^k \in \mathbb{Z}_{\ge 0}$：及时 buffer 天数；
- $H^{k,\mathrm{ext}} \in \mathbb{Z}_{\ge 0}$：交期外候选扩展天数；
- $\omega_k \in \mathbb{R}_{\ge 0}$：该类 miss 权重。

对每个需求 $d$：

- $\kappa_d^k \in \{0,1\}$：该需求在 KPI $k$ 下是否计入考核；
- $\tau_d^k$：KPI $k$ 的及时截面时刻；
- $T_d^{\mathrm{on},k}\subseteq T$：及时槽集合。

### 6.5 目标模式与放大系数

- $\mathrm{KPI}^{\mathrm{mode}}\in\{\mathrm{qtymax},\mathrm{ordermax}\}$；
- $\alpha^{\mathrm{urgent}}\ge 0$：紧急单权重放大系数；
- $\omega_{\mathrm{uns}}\ge 0$：未排产量权重。

定义：

$$
W_d^{\mathrm{eff}} = W_d^{\mathrm{pri}}\left(1+\alpha^{\mathrm{urgent}}u_d^{\mathrm{urgent}}\right)
$$

### 6.6 FAI 参数

对每条 FAI 弧 $(p,q)\in \mathcal{A}^{\mathrm{fai}}$：

- $\mathrm{lead}_{pq}\ge 0$：首件到余量的最小等待时长（小时）；
- $p$：首件需求；
- $q$：余量需求。

### 6.7 换线与候选压缩参数

- $ct_l^{\min}\ge 0$：线体 $l$ 的粗换线下界；
- $K^{\mathrm{line}}$：每需求每天最多保留线体数；
- $K^{\mathrm{slot}}$：每需求最多保留槽数；
- $H^{\mathrm{bucket}}$：超过该天数后的槽允许聚合为日桶；
- $M$：Big-M 常数。

---

## 7. 排前合并规则

### 7.1 合并目标

排前合并的目的是压缩主问题规模，并把在业务上可视为同一排产单元的需求先合并成虚拟需求。合并只影响主 MILP 的决策粒度，不改变原始需求行的追溯关系。

### 7.2 不参与合并的原始需求

以下原始需求行不参与普通键合并，而是单独保留：

1. `lot` 非空的需求；
2. 出现在 FIX 表中的需求；
3. 出现在当前待排集内继承锁定中的需求；
4. 出现在 FAI 表中的需求；
5. 因业务要求必须逐行追踪的保留对象。

### 7.3 合并分区

先按 $(mcode, plant)$ 分区；若 `plant` 维度在数据中缺失或业务未启用，可退化为仅按 `mcode` 分区。

### 7.4 合并阶段与键向量

对每个分区，按 `aps_merge_priority_setting` 中 `priority`、`code` 升序读取多行，每行的 `priority_desc` 对应一组键字段。阶段名和字段族的典型对应如下：

- `PN属性合并 / MTM属性合并`：`model`、`program`、`texture`、`series`
- `demand属性合并`：`demand_type`、`priority_code`、`status`、`pre_lock`、`pre_plan`、`fast_ship`、`cust_svc`、`om_urgent`、`mr_day`、`ots_date`、`fpsd`、`ship_day_two`
- `颜色材料项合并`：`color`、`kb`、`cover_assy`、`log_up_assy`、`pcba`、`thermal`、`material_sections`、`material_type`、`country`
- `PN合并 / MTM合并`：`pn`

记原始需求行 $r$ 在该分区上的合并键向量为

$$
\pi(r)=\bigl(a_1(r),a_2(r),\ldots,a_s(r)\bigr)
$$

同一分区内满足 $\pi(r)=\pi(r')$ 的原始需求行可进入同一合并组。

### 7.5 合并后虚拟需求量

对合并组 $g$ 对应的虚拟需求 $d$：

$$
q_d=\sum_{r\in R_d} q_r
$$

其中 $q_r$ 为原始需求行数量。

### 7.6 合并后优先级

合并后的需求继续参与 `aps_schedule_priority` 匹配。优先级规则在合并后需求层解释，具体做法为：

1. 对聚合后的字段重新计算条件命中；
2. 若某规则字段在聚合时存在多值，则按该规则所需的保守语义先聚合，再判断命中；
3. 同一 `priority_group` 内是“且”关系；同一 `priority` 下不同组是“或”关系；
4. 命中多个优先级时，取最高优先级。

### 7.7 合并后回写映射

必须输出映射表：

$$
\{(r,d,\rho_r)\mid r\in R,\ \phi(r)=d\}
$$

其中 $\rho_r$ 为原始行在组内回写顺序或拆分参考顺序。该映射用于：

- 将主 MILP 的虚拟需求解拆回原始需求；
- 生成报表；
- 二阶段在同组原始需求间做细粒度顺序恢复。

---

## 8. 时间槽、及时窗口与 KPI 口径

### 8.1 槽的统一定义

每个槽 $t$ 都具有：

- 日历日；
- 开始时刻 $\sigma_t$；
- 结束时刻 $\epsilon_t$；
- 所属线体可用性；
- 在日桶化情况下的聚合范围。

主模型统一按“在槽上安排的产量视为于槽结束时刻完成”处理交付及时性。

### 8.2 及时截面的定义

对需求 $d$ 和 KPI $k$，设原始交付日期为 $\mathrm{due}_d^k$。先将其规范到自然日，再定义：

$$
\tau_d^k = \text{EndOfDay}\bigl(\mathrm{due}_d^k - H^k \text{ days}\bigr)
$$

其中 `EndOfDay` 表示该自然日的日终时刻。于是及时槽集合定义为：

$$
T_d^{\mathrm{on},k} = \left\{ t\in T \mid \epsilon_t \le \tau_d^k \right\}
$$

这一定义明确表达“必须在交付日前提前 buffer 天完成”。

### 8.3 候选扩展窗口

为保留补救排产空间，允许在候选生成时保留超出及时集合但仍处于扩展窗口内的槽：

$$
T_d^{\mathrm{ext},k}=
\left\{t\in T\mid
\tau_d^k < \epsilon_t \le \text{EndOfDay}(\mathrm{due}_d^k + H^{k,\mathrm{ext}}\text{ days})
\right\}
$$

这些槽只影响候选保留，不影响“及时”的定义。

### 8.4 缺失日期字段时的口径

若某需求缺少某 KPI 对应日期，则定义：

$$
\kappa_d^k = 0
$$

且不对该 KPI 建及时考核惩罚。这样避免“字段缺失但默认全时及时”带来的口径混乱。

### 8.5 MR 豁免

对每个 $d,k$，若业务启用 MR 豁免并满足

$$
mr_d > \tau_d^k
$$

则定义：

$$
\kappa_d^k = 0
$$

这表示该需求在 KPI $k$ 下不计入及时交付惩罚；但该需求仍允许在 $mr_d$ 之后参与排产。

---

## 9. 锁定、继承与外部占用

### 9.1 FIX 锁定

对 FIX 表中的每条记录，定义锁定对象：

$$
\lambda = (d,l,t,s,q^{\mathrm{lock}})
$$

其中：

- $d$：需求；
- $l$：固定线体；
- $t$：固定槽；
- $s$：班内固定顺序；
- $q^{\mathrm{lock}}$：锁定数量。

若样例业务口径为整单 FIX，则有

$$
q^{\mathrm{lock}}=q_d
$$

若未来业务提供部分 FIX，则允许

$$
0 < q^{\mathrm{lock}} < q_d
$$

本版主模型统一按数量级锁定建模，因此同时兼容整单 FIX 与部分 FIX。

### 9.2 继承排程

来自 `aps_adjust_schedule_input` 的记录分成两类：

1. **当前待排集内记录**：对应当前需求集合中的需求，视为继承锁定；
2. **当前待排集外记录**：不属于当前需求集合，仅表现为外部占用。

对当前待排集内继承记录，同样定义锁定数量 $q^{\mathrm{lock}}$，允许整单锁定或部分锁定。

### 9.3 锁定建模方式

可采用两种等价建模形态：

1. **锁定消元**：把锁定数量从主问题中剥离，并从可用机时中扣减；
2. **主问题保留锁定变量**：锁定产量仍在主模型中出现，但以等式固定到指定位置。

本版默认推荐“**数量级锁定消元**”。

### 9.4 数量级锁定消元

对需求 $d$，定义其锁定总量：

$$
q_d^{\mathrm{lock}} = \sum_{\lambda\in\Lambda_d} q_\lambda^{\mathrm{lock}}
$$

则进入主 MILP 的剩余需求量为：

$$
\bar{q}_d = q_d - q_d^{\mathrm{lock}}
$$

若 $\bar{q}_d = 0$，则该需求不进入主 MILP。

对每个线体–槽位 $(l,t)$，锁定占用定义为：

$$
\mathrm{Occ}^{\mathrm{lock}}_{lt}
=
\sum_{\lambda:\,(l_\lambda,t_\lambda)=(l,t)}
\frac{q_\lambda^{\mathrm{lock}}}{\mathrm{uph}_\lambda^{\mathrm{lock}}}
$$

其中 $\mathrm{uph}_\lambda^{\mathrm{lock}}$ 由锁定位置可匹配的 UPH 决定。

### 9.5 外部占用

对 `aps_adjust_schedule_input` 中不属于当前需求集的记录，记其集合为 $\Lambda^{\mathrm{ext}}$。对每个 $(l,t)$：

$$
\mathrm{Occ}^{\mathrm{ext}}_{lt}
=
\sum_{\lambda\in\Lambda^{\mathrm{ext}}:\,(l_\lambda,t_\lambda)=(l,t)}
\frac{q_\lambda^{\mathrm{ext}}}{\mathrm{uph}_\lambda^{\mathrm{ext}}}
$$

这些占用只扣减产能，不对应主问题中的需求变量。

---

## 10. 候选集构造与压缩

### 10.1 原始候选集 $K^0$

对每个需求 $d$、线体 $l$、槽 $t$，若同时满足以下条件，则 $(d,l,t)$ 可进入 $K^0$：

1. $t$ 的开始时刻不早于 $mr_d$；
2. 线体–槽位在日历上可生产；
3. 可匹配到有效 UPH；
4. 通过限制规则；
5. 通过大小单规则；
6. 不与已消元锁定直接冲突。

### 10.2 MR 可行性

定义：

$$
\sigma_t \ge mr_d \quad \Longrightarrow \quad \text{可满足最早开工时刻约束}
$$

若采用“槽内整段生产”的近似，则只要槽开始不早于 $mr_d$ 即允许。

### 10.3 UPH 匹配

对每个候选 $(d,l,t)$，从 `aps_schedule_uph_input` 中按以下优先级匹配：

1. `mcode + line + day + shift + model + fast_ship + cust_svc` 的最具体规则；
2. 在属性不完全匹配时按配置优先级回退；
3. 选取满足需求属性的最高优先级有效 UPH。

若找不到正 UPH，则该候选不可用。

### 10.4 限制规则

`aps_schedule_limit_setting` 按 `group_id` 聚合解释。一条限制规则可理解为：

- 一组 PO/需求条件；
- 一组线体/班次/场景条件；
- 一组限制对象与限制值。

若某需求命中限制规则且某线体–槽位被该规则禁止，则令

$$
\mathrm{elig}_{dlt}=0
$$

### 10.5 大小单规则

由 `aps_schedule_order_qty` 定义：

- `flag_type = 1`：只允许小单；
- `flag_type = 2`：大小单都允许；
- `flag_type = 3`：只允许大单。

若需求量以 `small_qty` 为阈值被识别为小单/大单，则在不允许的线体上令 $\mathrm{elig}_{dlt}=0$。

### 10.6 交期外扩展候选

若某候选不在及时槽集合内，但在至少一个 KPI 的扩展窗口内，则可保留以便补救排产。

### 10.7 每日保留线体数压缩

对每个需求 $d$、自然日 $\delta$，计算该日所有候选线体得分并按以下顺序排序：

1. 更高 UPH；
2. 更早槽位；
3. 更高匹配特异性；
4. 更高业务优先线。

仅保留前 $K^{\mathrm{line}}$ 条线体。

### 10.8 每需求保留槽数压缩

对每个需求 $d$，按以下顺序保留最多 $K^{\mathrm{slot}}$ 个槽：

1. 及时槽优先于非及时槽；
2. 更早槽优先；
3. 更高 UPH 优先。

### 10.9 防剪空回退

若经过压缩后某需求没有任何候选，则从压缩前候选中按最早槽、最高 UPH 回退保留至少一个可行候选集合。

### 10.10 日桶聚合

对规划开始后超过 $H^{\mathrm{bucket}}$ 天的槽，可将同一天内若干班次聚合为一个日桶。日桶上的参数按如下规则生成：

- 机时容量求和；
- 停机与预留求和；
- 开始时刻取最早；
- 结束时刻取最晚；
- 候选 UPH 取规则化代表值，通常取同日候选中保守值或最大值，具体口径须在实现中固定。

---

## 11. 主 MILP 决策变量

以下默认对每个 $d\in D^{\star}$、$(d,l,t)\in K$ 定义，其中 $D^{\star}$ 表示进入主问题的需求集合。

- $x_{dlt}\in\mathbb{Z}_{\ge 0}$：需求 $d$ 在 $(l,t)$ 上的排产数量；
- $c_d\in\mathbb{Z}_{\ge 0}$：未排产量；
- $\mathrm{miss}_d^k\in\mathbb{R}_{\ge 0}$：需求 $d$ 在 KPI $k$ 下的未及时量；
- $z_{dlt}\in\{0,1\}$：候选激活变量，表示 $x_{dlt}>0$；
- $u_d\in\{0,1\}$：整单完成标记；
- $g_{lmt}\in\{0,1\}$：线体 $l$ 在槽 $t$ 是否出现机型 $m$；
- $h_{lt}\in\mathbb{Z}_{\ge 0}$：槽 $(l,t)$ 的粗换线次数下界；
- $\mathrm{setup}_{lt}\in\mathbb{R}_{\ge 0}$：粗换线机时下界；
- $e_d\in\mathbb{R}_{\ge 0}$：需求完工时刻下界辅助变量，仅在主模型显式加入 FAI Big-M 时使用。

---

## 12. 主模型约束

### 12.1 需求平衡

对每个进入主问题的需求 $d$：

$$
\sum_{(l,t):(d,l,t)\in K} x_{dlt} + c_d = \bar{q}_d
$$

其中 $\bar{q}_d$ 为扣除锁定后的剩余可调数量；若未采用锁定消元，则 $\bar{q}_d=q_d$。

### 12.2 激活与可行域

对每个 $(d,l,t)\in K$：

$$
x_{dlt} \le \bar{q}_d z_{dlt}
$$

$$
x_{dlt} \ge z_{dlt}
$$

$$
x_{dlt} \le \bar{q}_d \mathrm{elig}_{dlt}
$$

若不启用激活变量，则仅保留第三式。

### 12.3 同需求同槽单线约束

若业务不允许同一需求在同一槽位同时落到多条线，则对每个 $d,t$：

$$
\sum_{l:(d,l,t)\in K} z_{dlt}\le 1
$$

若未来业务允许同槽多线拆分，则可关闭该约束并由二阶段或解后校核承担风险提示。

### 12.4 产能约束

对每个 $(l,t)\in LT$：

$$
\sum_{d:(d,l,t)\in K}\frac{x_{dlt}}{\mathrm{uph}_{dlt}} + \mathrm{setup}_{lt}
\le
\mathrm{Avail}_{lt}
$$

### 12.5 整单完成变量

对每个需求 $d$：

$$
\sum_{(l,t):(d,l,t)\in K} x_{dlt} \ge \bar{q}_d u_d
$$

$$
\sum_{(l,t):(d,l,t)\in K} x_{dlt} \le \bar{q}_d - (1-u_d),\qquad \bar{q}_d\ge 1
$$

该约束保证 $u_d=1$ 当且仅当该需求剩余可调量被全部排满。

### 12.6 交付 miss 约束

对每个需求 $d$、每类 KPI $k\in\mathcal{K}$：

$$
\mathrm{miss}_d^k \ge
\bar{q}_d - \sum_{\substack{l,t:(d,l,t)\in K\\ t\in T_d^{\mathrm{on},k}}} x_{dlt}
$$

$$
\mathrm{miss}_d^k \ge 0
$$

若 $\kappa_d^k=0$，则该 miss 不进入目标函数。

### 12.7 锁定未消元时的等式约束

若锁定不消元，而是保留在主问题中，则对每条锁定记录 $\lambda=(d,l,t,s,q^{\mathrm{lock}})$：

$$
x_{dlt} \ge q^{\mathrm{lock}}
$$

若该锁定要求精确占满该槽位上的锁定产量，则可写为

$$
x_{dlt}^{\mathrm{lock}} = q^{\mathrm{lock}}
$$

并对同需求其余不允许位置加零约束或互斥约束。

### 12.8 FAI：候选剪枝形式

若 FAI 不在主模型中显式 Big-M 建模，则对余量需求 $q$ 的候选预先剪枝，只保留满足：

$$
\sigma_t \ge \underline{e}_p + \mathrm{lead}_{pq}
$$

的槽，其中 $\underline{e}_p$ 是首件需求 $p$ 在当前离散时间格下的理论最早完工下界。

### 12.9 FAI：Big-M 形式

若启用显式 FAI 先后，则对每个需求 $d$ 与候选 $(d,l,t)\in K$：

$$
e_d \ge \epsilon_t - M(1-z_{dlt})
$$

对每条弧 $(p,q)\in\mathcal{A}^{\mathrm{fai}}$ 及每个 $(q,l,t)\in K$：

$$
\sigma_t + M(1-z_{qlt}) \ge e_p + \mathrm{lead}_{pq}
$$

### 12.10 机型出现变量

记

$$
K_{lmt}=\{(d,l,t)\in K\mid \mathrm{model}(d)=m\}
$$

则对每个 $(l,m,t)$：

$$
\sum_{(d,l,t)\in K_{lmt}} z_{dlt} \le |K_{lmt}|\, g_{lmt}
$$

$$
g_{lmt} \le \sum_{(d,l,t)\in K_{lmt}} z_{dlt}
$$

若不启用 $z$，则可改用产量上界与 $g_{lmt}$ 连接。

### 12.11 粗换线下界

对每个 $(l,t)$：

$$
h_{lt} \ge \sum_{m\in M^{model}} g_{lmt} - 1
$$

$$
\mathrm{setup}_{lt} \ge ct_l^{\min} h_{lt}
$$

该组约束表达“槽内出现的机型越多，粗换线次数下界越大”。

---

## 13. 目标函数

采用词典序多目标。

### 13.1 第一层：交付与主优先级

$$
\min\ \mathrm{Obj}_1
=
\sum_{d\in D^{\star}} W_d^{\mathrm{eff}}
\left(
\sum_{k\in\mathcal{K}} \omega_k \kappa_d^k \mathrm{miss}_d^k
 + \omega_{\mathrm{uns}} c_d
\right)
$$

### 13.2 第二层：与 KPI 模式一致

若 $\mathrm{KPI}^{\mathrm{mode}}=\mathrm{qtymax}$，则

$$
\min\ \mathrm{Obj}_2 = \sum_{d\in D^{\star}} c_d
$$

若 $\mathrm{KPI}^{\mathrm{mode}}=\mathrm{ordermax}$，则

$$
\max\ \sum_{d\in D^{\star}} u_d
$$

等价地也可写为

$$
\min\ \sum_{d\in D^{\star}}(1-u_d)
$$

### 13.3 第三层：在 qtymax 下偏好更多整单完成

当 $\mathrm{KPI}^{\mathrm{mode}}=\mathrm{qtymax}$ 时，可继续增加：

$$
\max\ \sum_{d\in D^{\star}} u_d
$$

### 13.4 第四层：线体偏好与 Cell 惩罚

$$
\min\ \mathrm{Obj}_3 = \sum_{(d,l,t)\in K} C_{dlt} x_{dlt}
$$

### 13.5 第五层：粗效率

$$
\min\ \mathrm{Obj}_4
=
\sum_{(l,t)\in LT}\mathrm{setup}_{lt}
 + \sum_{l,m,t} g_{lmt}
$$

词典序实现可通过：

- 求解器原生多目标；
- 逐层固定最优值；
- epsilon-约束。

---

## 14. 班内细排（二阶段）

### 14.1 输入

班内细排读取：

- 主 MILP 解中的正产量 $(d,l,t,x_{dlt})$；
- FIX 与继承锁定中的 `seq`；
- `aps_schedule_order_ruler` 给出的材料排序键；
- 需求属性：`model`、`lot`、`mo`、`kb`、`log_up_assy`、`cover_assy`、`pcba`、`thermal`、`color` 等。

### 14.2 全序排序键

对每个 $(l,t)$ 的任务集合，按以下优先级给定全序：

1. 锁定任务优先于主 MILP 新排任务；
2. 不同锁定来源的业务顺位；
3. FIX / 继承记录中的显式 `seq` 升序；
4. `model`；
5. `lot`；
6. `mo`；
7. `aps_schedule_order_ruler` 给出的材料键序列；
8. 合并后 demand 标识。

### 14.3 班内细排输出

班内细排输出：

- `sequence`：槽内顺序号；
- `same_model_run`：机型连续段信息；
- `changeover_count`：班内实际换线次数摘要；
- `lot_break_flag`：同 lot 是否被打散；
- `material_key_trace`：排序键轨迹。

### 14.4 班内细排不改变的内容

班内细排不得改变：

- 主 MILP 的线体–槽位分配数量；
- FIX / 继承锁定的位置；
- 主 MILP 已确定的同槽总产量。

---

## 15. 解后校核

### 15.1 同槽拆线校核

若主模型关闭“同需求同槽单线”约束，则需在解后审计是否存在：

$$
\exists d,t:\ |\{l\mid x_{dlt}>0\}|>1
$$

并输出风险清单。

### 15.2 FAI 日历校核

用二阶段后的实际开始/结束时刻重新检查：

$$
\mathrm{Start}(q) \ge \mathrm{Finish}(p) + \mathrm{lead}_{pq}
$$

若不满足，则输出 FAI 违规。

### 15.3 容量校核

校核每个 $(l,t)$：

$$
\sum_d \frac{x_{dlt}}{\mathrm{uph}_{dlt}^{\mathrm{used}}}
 + \mathrm{lock\_hours}_{lt}
 + \mathrm{ext\_hours}_{lt}
\le
\mathrm{Cap}_{lt}-\mathrm{Down}_{lt}-\mathrm{Res}_{lt}
$$

其中 $\mathrm{uph}_{dlt}^{\mathrm{used}}$ 为实际用于该行的 UPH 口径。

### 15.4 交付统计校核

基于最终槽结束时刻重新汇总：

- 及时产量；
- miss 产量；
- 未排产量；
- OTS / FPSD / D+2 达成率。

### 15.5 锁定一致性校核

对每条 FIX / 继承锁定记录检查：

- 锁定位置是否被保留；
- 锁定数量是否满足；
- 显式顺序号是否被破坏。

---

## 16. 典型实现开关

### 16.1 锁定开关

- **数量级锁定消元**：推荐默认；
- **主问题保留锁定等式**：用于调试或审计。

### 16.2 FAI 开关

- **候选剪枝**：规模较小；
- **Big-M 显式约束**：语义更强，但规模更大。

### 16.3 激活变量开关

- **开**：更容易控制同槽拆线、FAI 与机型出现变量；
- **关**：模型规模更小。

### 16.4 日桶开关

- **开**：远期实例更易求解；
- **关**：时间表达更精细。

### 16.5 Cell 线偏好开关

- **软惩罚**：推荐默认；
- **硬约束**：仅在业务明确要求时启用。

---

## 17. 输入表与建模环节对照

| 工作表 / 逻辑表                        | 建模环节                                     |
| -------------------------------- | ---------------------------------------- |
| `aps_schedule_demand_base_input` | 原始需求集合、数量、MR、交付日期、flag                   |
| `aps_schedule_master_pn_input`   | `pn` 到 `model/program/texture/color` 的补全 |
| `aps_merge_priority_setting`     | 排前合并阶段与键向量                               |
| `aps_schedule_priority`          | 优先级、KPI 模式、KPI 计权                        |
| `aps_schedule_line_input`        | 线体主数据、Cell 标记                            |
| `aps_schedule_line_calendar`     | 槽集合、班次时段、开关班                             |
| `aps_schedule_off_time_input`    | 停机扣减                                     |
| `aps_schedule_reserver_input`    | 预留扣减                                     |
| `aps_schedule_uph_input`         | 候选 UPH                                   |
| `aps_change_time_input`          | 粗换线时间下界                                  |
| `aps_schedule_limit_setting`     | 候选可行性限制                                  |
| `aps_schedule_order_qty`         | 大小单适线规则                                  |
| `aps_schedule_order_ruler`       | 班内材料排序键链                                 |
| `aps_schedule_demand_fix_input`  | FIX 锁定                                   |
| `aps_adjust_schedule_input`      | 继承锁定与外部占用                                |
| `aps_schedule_demand_fai_input`  | FAI 先后与等待时间                              |

---

## 18. 小结

`v7.5` 的核心特征是：

1. 明确把**排前合并**定义为主问题粒度压缩机制，而不是简单的重复 `demand_id` 聚合；
2. 明确把**及时交付**定义为“交付日前提前 buffer 天的日终截面之前完成”；
3. 明确区分**MR 最早投产约束**与**MR 导致的 KPI 豁免**；
4. 明确把**FIX / 继承锁定**统一到数量级建模，使整单锁定与部分锁定都能表达；
5. 明确把**外部已排任务**从“继承锁定”中拆出，单独作用于产能；
6. 明确主 MILP、班内细排、解后校核三者的职责边界。

按照本版口径，主模型追求的是：在业务允许的稀疏候选集上，优先满足交付与高优先级需求，同时兼顾排产数量、整单完成、线体偏好与换线效率；而 lot 连续、材料排序链、精确换线顺序与 FAI 日历细节则由二阶段和审计层补足。这一划分既保留了数学模型的可解性，也尽量贴近 BOX APS 当前输入表和业务规则的真实口径。
