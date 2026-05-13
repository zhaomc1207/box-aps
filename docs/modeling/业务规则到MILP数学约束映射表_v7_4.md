# BOX APS业务规则到 MILP 数学约束映射表 v7.4

> **公式书写约定**  
> 
> - **行内**（符号、短式）：用**一对** `$` 包裹，如 `$D$`、`$x_{dlt}$`。  
> - **独立成行**：**首行只写** `$$`，**末行只写** `$$`，中间为公式；避免行首缩进的 `$$`。  
> - **避免**在同一句中连续拼接多段 `$$…$$`，以免渲染器误判为连续的 `$`。

---

## 1. 文档定位与建模范围

本版 **`v7.4`** 给出 BOX APS **主 MILP + 前置数据准备 + 班内细排** 的一体化数学描述。业务规则语义与 **`v6` 建模说明**对齐；在此基础上，为满足全量实例可解性，引入**稀疏候选集、锁定需求从主问题中扣除产能、远期时间聚合**等约定。**本文档不立基于任何特定代码仓库**，输入以 APS 标准化表与工作表为载体；字段语义可对照企业《输入字段说明》类文档。

### 1.1 相对 `v6` 的主要结构差异（数学层面）

| 议题             | `v6` 典型写法                         | `v7.4` 写法                                                   |
| -------------- | --------------------------------- | ----------------------------------------------------------- |
| 决策变量索引         | 常讨论完整或接近完整的 $D \times L \times T$ | 仅在与务规则一致的**稀疏候选集** $K \subseteq D \times L \times T$ 上建产量变量 |
| 锁定订单（FIX / 继承） | 可在主模型中联立等式                        | 可采用**锁定消元**：锁定量从可供普通需求使用的产能中扣减，主问题仅含非锁定需求                   |
| 交付 KPI         | 可与班末完工时刻变量联动                      | 可用「**及时时间槽集合**」上的累计产量界定 **miss**，不必引入全局连续完工时刻（见 §5、§8）      |
| 班内顺序与精确换线      | 二阶段或局部模型                          | 仍放在**细排层**，不进主 MILP                                         |

### 1.2 必选与可选输入（工作表层级）

以下为建模所依赖的常见 **Excel 工作表名**（与数据目录里的 `*_input` 表名可能一一对应，仅命名习惯不同）。

**必选**（缺一则无法构造完整可行数据）：

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
- `aps_schedule_priority`（目录中常与 `aps_schedule_priority_setting_input` 指同一逻辑表）
- `aps_merge_priority_setting`（目录中常与 `aps_merge_priority_setting_input` 指同一逻辑表；与「合并后再排序」的其它配置表区分开）
- `aps_adjust_schedule_input`

**可选**：

- `aps_schedule_reserver_input`（产能预留窗口）
- `aps_schedule_demand_reserve_input`（若存在，可为后续 demand 级预留扩展保留；本版数学描述中 net 产能以线体–槽位上已解析的预留量为准）

**导航**：排前合并（含 `lot` 排除、颜色材料项阶段、merge priority）→ **§7.0**；班内细排与 `aps_schedule_order_ruler` 作用 → **§10**。

**说明**：样本脱敏工作簿中通常含 `aps_merge_priority_setting`。**勿**将其与另一类「生命周期不同、在部分样本中未出现」的扩展表混淆；二者在数据目录里的名称相近，建模时需按字段与业务定义区分。

---

## 2. 术语与记号约定

### 2.1 业务术语

- **需求（demand）**  
  排产对象粒度，一般由原始表中的 demand 标识；经 **§7.0 排前合并** 后可对应**合并后的虚拟需求** $d \in D$。优先级规则的解释方式不因合并而改变（仍以规则表为准）。  
  **`lot`（批次）**：字段非空时表示存在批次可追溯要求，该类原始行在标准实现中**不参与**按键合并。

- **时间槽（slot）**  
  某条线体上一个可排产的班次时间段；远端规划上可把若干原始班次聚合为 **日桶（day bucket）**，仍记为广义「槽」$t \in T$，但 $t$ 可能对应合并后的标识。

- **UPH（units per hour）**  
  单位时间产量，用于把产量 $x$ 换成机时 $x/\mathrm{uph}$。

- **Buffer（缓冲天数，交付类）**  
  对某一交付截止日 $\mathrm{due}$（如 OTS、FPSD、D+2 出货相关日），业务上常要求**计划完成时刻不晚于「截止日往前数 $H$ 个日历日」的当日界限**。这里的非负整数 $H$ 称为该指标的 **buffer**。  
  等价表述：若用日历比较，「及时」指槽的结束时刻落在 $\mathrm{due}$ 前移 $H$ 天所确定的**截止截面**之前（见 §5.5）。

- **交期窗口（与交付 KPI 对应的「及时」窗口）**  
  对每个需求 $d$ 及某一 KPI，所有**若在该槽结束排产则算作该 KPI 下及时交付**的时间槽集合，记为例如 $T_d^{\mathrm{on,ots}}$（OTS）。它由截止日期与 buffer 共同决定。

- **交期外窗口约束（候选集上的扩充，亦称交期 Relax / Extension）**  
  仅在**构建稀疏候选集合**时使用：即使某槽 $t$ 已超出「交付及时」的日历界限，为了在优化中保留**后期补救排产**的可能，仍可把「截止日期之后、但不超过外加 $H^{\mathrm{ext}}$ 个自然日的槽」保留在候选集 $K$ 中；$H^{\mathrm{ext}}$ 为**交期外扩展天数**。**注意**：计入 $K$ 不等于算「及时」，及时性仍仅由 §8 中的 **miss** 与 $T_d^{\mathrm{on},\cdot}$ 刻画。

- **锁定消元**  
  将 FIX / 锁定继承排程的需求量从线体–槽位的**可供机时**中扣除，并将对应需求排除在主问题决策之外；数学上等价于固定部分变量后与主问题解耦。

- **FAI 首件 / 余量**  
  首件合格后须等待不少于 $lead_g$（小时）再放行同组余量需求；可先通过**缩小候选**近似，或通过 **Big-M 线性化**在主模型中强加先后（见 §11）。

- **词典序目标**  
  多目标按优先级逐级优化：先生成上一轮最优可行域（或等价标量权重足够分离），再在次一级目标上寻优。

### 2.2 通用数学记号

- $\mathbb{Z}_{\geq 0}$：非负整数；$\mathbb{R}_{\geq 0}$：非负实数。  
- $\mathbf{1}(\cdot)$：指示函数，条件成立取 1，否则 0。  
- 对时间槽 $t$，记 $\epsilon_t$ 为该槽**结束时刻**在统一时间轴上的标量（日历时间戳或相对规划起点的连续小时，全文采用一种口径即可）。  
- 大 M 法中的常数记为 $M$，须满足大于任何相关时间差上界。

---

## 3. 模型分层

1. **数据准备层**  
   读入规范化表；**排前需求合并（见 §7.0）**；由 UPH、日历、MR、限制规则、大小单规则等生成**原始稀疏候选** $K^0$；计算机时、外部占用、预留、锁定占用；解析优先级与 KPI 模式；解析 FAI 弧与换线下界。

2. **候选压缩层**  
   在 $K^0$ 上实施：剔除已锁定需求的候选、**交期外窗口扩充**内的剪枝边界、每日保留线体数上界 $K^{\mathrm{line}}$、每需求候选数上界 $K^{\mathrm{slot}}$、远期**日桶**合并，输出主模型可用的 $K$。

3. **主 MILP 层**  
   在 $K$ 上分配整数产量，满足产能、（可选）激活逻辑、交付 **miss**、（可选）FAI Big-M、机型出现与粗换线下界。

4. **班内细排与校核层**  
   对每个有线产量的线体–槽，确定执行顺序并校核：**拆单风险**、FAI 日历口径、产能平衡、物料切换顺序等与主模型离散化相关的项。

---

## 4. 集合与索引

- $D$：用作主 MILP 索引的**合并后需求**集合，元素仍记 $d$；原始行集合与映射见 §7.0。

- $L$：线体索引 $l$。

- $T$：时间槽索引 $t$（可含原始班次与日桶）。

- $M^{model}$：机型（model）取值集合（为与「大 M」区分，本节用 $M^{model}$，下文仍按需写 $\mathrm{model}(d)$）。

- $$
  K^0 \subseteq D \times L \times T
  $$
  
  ：**原始**可行候选三元组集合。

$$
K \subseteq D' \times L \times T
$$

：**压缩后**主模型候选集；主产量变量只对 $(d,l,t) \in K$ 定义。

$$
D^{\mathrm{lock}} = D^{\mathrm{fix}} \cup D^{\mathrm{adj}}
$$

：锁定集合（FIX + 在当前需求集合内的继承排程）。

在**采用锁定消元**时：

$$
D' = D \setminus D^{\mathrm{lock}},\quad K \subseteq D' \times L \times T.
$$

$$
LT = \bigl\{ (l,t) \in L \times T \mid \text{该线–槽有可用的正 Net 机时} \ \mathrm{Avail}_{lt} > 0 \bigr\}.
$$

- $\mathcal{A}^{\mathrm{fai}}$：FAI 有向弧 $(d^{\mathrm{first}}, d^{\mathrm{rest}})$ 及组等待 $lead_g$；若部分端点被锁定消元移出 $D'$，则相应弧可不进入主模型。

**说明**：若采用「桶化」槽，则 $T$ 中元素与业务上的 `slot_id` 一一对应或经合并映射；数学上统一记为 $t$。

---

## 5. 参数

### 5.1 需求侧

- $q_d \in \mathbb{Z}_{\geq 0}$：需求量。  
- $mr_d$：物料齐套日期（MR Date）。  
- $ots_d,\ fpsd_d,\ ship2_d$：各交付相关截止日（含 D+2 出货类字段等，以业务定义为准）。  
- 业务标记：如预锁、快运、客制、紧急等，进入权重或成本系数（见 $W_d^{\mathrm{eff}}$、$C_{dlt}$）。  
- 机型、程序、材料键、工单、批次等：用于 UPH 匹配、换线、细排物料序。

### 5.2 线体–槽位

- $\mathrm{Cap}_{lt}$：该线–该槽在扣除各项占用前的**计划总机时上界**。  
- $\mathrm{Down}_{lt}$：停机/休息扣减。  
- $\mathrm{Res}_{lt}$：预留扣减。  
- $\mathrm{Occ}^{\mathrm{ext}}_{lt}$：外部已排（非本批需求）占用。  
- $\mathrm{Occ}^{\mathrm{lock}}_{lt}$：锁定需求占用（锁定消元时计入右端项扣减）。  

**净机时**（主问题右端项）：

$$
\mathrm{Avail}_{lt} = \mathrm{Cap}_{lt} - \mathrm{Down}_{lt} - \mathrm{Res}_{lt} - \mathrm{Occ}^{\mathrm{ext}}_{lt} - \mathrm{Occ}^{\mathrm{lock}}_{lt}.
$$

### 5.3 候选与效率

- $\mathrm{uph}_{dlt} > 0$：候选 $(d,l,t)$ 上的 UPH。  
- $\mathrm{elig}_{dlt} \in \{0,1\}$：综合可行性（正常为 1；为 0 则强制 $x_{dlt}=0$）。

### 5.4 优先级与 KPI

- $W_d^{\mathrm{pri}}$：由优先级规则表（组内且、组间或）得到的主优先级权重。  

- 紧急单放大系数 $\alpha \geq 0$：
  
  $$
  W_d^{\mathrm{eff}} = W_d^{\mathrm{pri}} \bigl(1 + \alpha \cdot \mathbf{1}(\text{需求 } d \text{ 标记为紧急})\bigr).
  $$

- $\kappa_d^{ots},\kappa_d^{fpsd},\kappa_d^{ship2} \in \{0,1\}$：各 KPI 是否计入目标（见 §5.6「MR 豁免」）。  

- $\mathrm{KPI}^{\mathrm{mode}} \in \{\mathrm{qtymax},\ \mathrm{ordermax}\}$：由优先级规则表汇总的版本级 KPI 模式。

### 5.5 交付 Buffer 与「及时」槽集

对每一类截止日设非负整数 buffer：$H^{ots},H^{fpsd},H^{ship2}$。  
将截止日 $due$ 规范到日历日后，定义**截面时刻**（业务上等价于「截止日前第 $H$ 个日历日的日界」）$\tau_d^{\cdot}$，并定义

$$
T_d^{\mathrm{on},\cdot} = \left\{ t \in T \;\middle|\; \epsilon_t \leq \tau_d^{\cdot} \right\}.
$$

若某需求缺少对应 $due$，可令 $T_d^{\mathrm{on},\cdot} = T$（该 KPI 不限制「及时」槽形）或令 $\kappa_d^{\cdot}=0$，二者取其一并与企业口径一致。

### 5.6 MR 与 KPI 豁免（可选业务规则）

若启用「MR 过晚则无法物理满足 buffer」的豁免：当 $mr_d$ 晚于 $\tau_d^{\cdot}$（按自然日比较）时，令 $\kappa_d^{\cdot}=0$，该需求不再对相应 **miss** 计入惩罚。

### 5.7 换线

- $ct^{\min}_l$：线体 $l$ 上由换线规则表聚合得到的**粗粒度**单机种切换时间下界（小时）。更细的 $d_1\!\to\!d_2$ 换线留在细排层。

### 5.8 目标权重

- $\omega_{ots},\omega_{fpsd},\omega_{ship2},\omega_{uns} \in \mathbb{R}_{\geq 0}$：各 **miss** 与未排产量在首层目标中的权重。  
- $M$：Big-M 常数。

### 5.9 候选压缩标量（典型取值仅作规模参考）

| 记号                    | 含义                     | 典型取值（可随实例调整） |
| --------------------- | ---------------------- | ------------ |
| $H^{\mathrm{ext}}$    | 交期外候选扩展天数（§2.1）        | $3$          |
| $K^{\mathrm{line}}$   | 每个需求每个自然日保留的线体数上界      | $5$          |
| $K^{\mathrm{slot}}$   | 每个需求保留的候选槽总数上界         | $60$         |
| $H^{\mathrm{bucket}}$ | 自规划首日起算，超过该天数后的班次用日桶聚合 | $5$          |

---

## 6. 决策变量（主 MILP，基准形式）

以下默认 $d \in D'$，$(d,l,t) \in K$。

- $x_{dlt} \in \mathbb{Z}_{\geq 0}$：排产数量。  
- $c_d \in \mathbb{Z}_{\geq 0}$：未排松驰。  
- $\mathrm{miss}_d^{ots},\mathrm{miss}_d^{fpsd},\mathrm{miss}_d^{ship2} \in \mathbb{R}_{\geq 0}$：交付未达成量。  
- $g_{lmt} \in \{0,1\}$：线 $l$、槽 $t$ 是否出现机型 $m$（$m \in M^{model}$）。  
- $h_{lt} \in \mathbb{Z}_{\geq 0}$，$\mathrm{setup}_{lt} \in \mathbb{R}_{\geq 0}$：粗粒度换线次数与换线机时下界。

**二元扩展（基准形式采用，见 §11 可关闭）**：

- $z_{dlt} \in \{0,1\}$：$x_{dlt}>0$ 当且仅当 $z_{dlt}=1$（上界可收紧为 $x_{dlt} \leq q_d z_{dlt}$）。  
- $u_d \in \{0,1\}$：需求 $d$ 是否**整单排满**（用于 $\mathrm{ordermax}$ 或在 $\mathrm{qtymax}$ 下偏好完整订单的次级目标）。  
- $e_d \in \mathbb{R}_{\geq 0}$：**仅当**主模型对 FAI 使用 Big-M 与 $z$ 同时启用时，作为需求 $d$ 的完工时刻下界辅助变量。

---

## 7. 数据准备与候选集构造（要点）

### 7.0 排前合并规则表：`aps_merge_priority_setting`（merge priority）

**位置说明**：本节对应工作表 **`aps_merge_priority_setting`**（数据目录常与 `aps_merge_priority_setting_input` 同名）；**不进入主 MILP 目标系数**，仅在数据准备阶段**压缩需求粒度**。与 **`v6` 定性一致**：该表表示「合并阶段先后顺序与维度」，**不等于**优先级权重表。

**业务目的**：在构图与求解前，将若干原始需求归为同一**虚拟需求** $d$，使 $|D|$ 下降、同源订单在配置上可一并处理。**主模型中的所有 $d,q_d,x_{dlt},\cdots$ 均指合并后的需求**，除非下文另称「原始行」。

**排除合并的原始需求**（仍单独保留为一个需求参与后续步骤）：

- **`lot` 非空**：有批次追溯要求，**不参与**本节所述键合并。  
- 出现在 **FIX 锁定**需求表中的标识。  
- 出现在 **FAI** 需求关联表中的标识。  
- 出现在 **继承/调整排程**输入中，且对应需求**属于当前本批待排集合**的行（已与工单锁定语义绑定）。

对上述以外的原始行，若在规则表允许的 $(mcode, plant)$ 分区内且可构造合并键，则进入合并。

**规则表粒度**：按 **`mcode`（及可选 `plant`）** 分区；在每个分区内，按表内 **`priority`、`code`** 升序阅读多行，每行的 **`priority_desc`** 指明一个**合并阶段**名称。系统将阶段名称映射为一组**键字段**，并在该分区内将多阶段映射得到的字段**按出现顺序做去重连结**，形成该分区下的**合并键向量**：

$$
\pi(r) = \bigl(\text{字段}_1(r),\ldots,\text{字段}_s(r)\bigr),\quad \text{同属一分区且 } \pi(r)=\pi(r')\text{ 的原始行 } r,r'\text{ 可合并}.
$$

**常用阶段名称与维度（与企业配置表一致时可出现）**：配置中的 `priority_desc` 若为下表左列字面量或其常见写法，则右列字段（若存在于需求宽表中）并入键。**颜色材料项合并**即其中之一。

| 阶段名示例（`priority_desc`）   | 合并判定所参照的典型字段维度                                                                                                                            |
| ------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------- |
| PN 属性合并 / MTM 属性合并（视为同类） | `model`、`program`、`texture`、`series`                                                                                                      |
| demand 属性合并              | `demand_type`、`priority_code`、`status`、`pre_lock`、`pre_plan`、`fast_ship`、`cust_svc`、`om_urgent`、`mr_day`、`ots_date`、`fpsd`、`ship_day_two` |
| **颜色材料项合并**              | `color`、`kb`、`cover_assy`、`log_up_assy`、`pcba`、`thermal`、`material_sections`、`material_type`、`country`                                    |
| PN 合并 / MTM 合并           | `pn`                                                                                                                                      |

未识别的阶段名将忽略并产生业务告警；空规则表等价于不进行键合并。

设某 $(mcode, plant)$ 分区内，索引为 $i,j,\ldots$ 的原始行落入同一合并组 $G$，记虚拟需求 $d$ 代表该组：

$$
q_{d}=\sum_{r \in G} q_{r}^{\circ}.
$$

组内 MR 与各交期可取**最晚 MR**、**最早 OTS / FPSD / ship_day_two** 等保守聚合；布尔类标记可取类内「或」语义；工单号等非键字段多值时取值规则由企业规定。**虚拟标识**与原始行的多对一应写入**映射**，供下游将线–槽解拆分回原始行，不改变 §8–§9。

完成后得到合并后的需求集 $D$ 与工作表 **`aps_schedule_priority` 匹配的优先级赋值**仍以合并后行为准；原始行侧的优先级可被回写对齐，以便于报表。

---

1. **主数据补全**（主需求表 + 料号主数据）。  
2. **优先级**：条件行 $\to$ 组内且 $\to$ 组间或 $\to$ 需求最小层级 $\to$ $W_d^{\mathrm{pri}}$；汇总 $\mathrm{KPI}^{\mathrm{mode}}$。  
3. **日历与 demand_flag**：`demand_flag=1` 的线–槽对 Normal 需求关闭（进入 $\mathrm{elig}$ 或剔除候选）。  
4. **预留**：若有预留表，从 $\mathrm{Avail}_{lt}$ 中扣减重叠区间机时。  
5. **外部占用与锁定占用**：非本批 demand 的已排量 $\to \mathrm{Occ}^{\mathrm{ext}}$；锁定量 $\to \mathrm{Occ}^{\mathrm{lock}}$（消元时同步从 $D'$、$K$ 去掉）。  
6. **$K^0$**：UPH、MR、限制、大小单、日历等交集。  
7. **压缩到 $K$**：交期外扩展 $H^{\mathrm{ext}}$、Top-$K^{\mathrm{line}}$、Top-$K^{\mathrm{slot}}$、防剪空回退、远期日桶合并；桶内 UPH 取规则化代表值。  
8. **FAI**：生成 $\mathcal{A}^{\mathrm{fai}}$ 与 $lead_g$；若不采用主模型 Big-M，可对余量需求的候选施加「不早于首件理论最早完成 + $lead$」的**预剪枝**。

---

## 8. 主模型约束（锁定消元情形）

### 8.1 需求平衡

$$
\sum_{(l,t):(d,l,t)\in K} x_{dlt} + c_d = q_d,\qquad \forall d \in D'.
$$

### 8.2 激活与可行域（当使用 $z_{dlt}$ 时）

$$
\begin{aligned}
& x_{dlt} \leq q_d\, z_{dlt},\qquad x_{dlt} \geq z_{dlt}, && \forall (d,l,t)\in K, \\
& x_{dlt} \leq q_d\, \mathrm{elig}_{dlt}, && \forall (d,l,t)\in K, \\
& \sum_{l:(d,l,t)\in K} z_{dlt} \leq 1, && \forall d\in D',\ \forall t\in T.
\end{aligned}
$$

第三式：同一需求在同一时间槽至多选一条线（防止同槽拆线，除非另有业务允许）。

### 8.3 产能

$$
\sum_{d:(d,l,t)\in K} \frac{x_{dlt}}{\mathrm{uph}_{dlt}} + \mathrm{setup}_{lt} \leq \mathrm{Avail}_{lt},\qquad \forall (l,t)\in LT,
$$

其中求和项跳过 $\mathrm{uph}_{dlt}=0$ 的退化候选（若有）。

### 8.4 整单完成（当建模 $u_d$）

$$
\sum_{l,t:\,(d,l,t)\in K} x_{dlt} \geq q_d\, u_d,\qquad
\sum_{l,t:\,(d,l,t)\in K} x_{dlt} \leq q_d - (1-u_d),\qquad \forall d\in D',\ q_d \geq 1.
$$

### 8.5 交付 Miss（累计及时）

$$
\begin{aligned}
\mathrm{miss}_d^{ots} &\geq q_d - \!\!\sum_{\substack{l,t:\, (d,l,t)\in K\\ t\in T_d^{\mathrm{on,ots}}}} \!\! x_{dlt}, \\
\mathrm{miss}_d^{fpsd} &\geq q_d - \!\!\sum_{\substack{l,t:\, (d,l,t)\in K\\ t\in T_d^{\mathrm{on,fpsd}}}} \!\! x_{dlt}, \\
\mathrm{miss}_d^{ship2} &\geq q_d - \!\!\sum_{\substack{l,t:\, (d,l,t)\in K\\ t\in T_d^{\mathrm{on,ship2}}}} \!\! x_{dlt}, \\
\mathrm{miss}_d^{ots},\,\mathrm{miss}_d^{fpsd},\,\mathrm{miss}_d^{ship2} &\geq 0.
\end{aligned}
$$

与 `v6` 显式完工时刻相比，上式用「在及时槽集合内累计产量」刻画交付，**无需**全局 $e_d$ 即可线性表达 miss。

### 8.6 FAI：Big-M 形式（与 $z$ 联用）

对每条弧 $(p,q)\in\mathcal{A}^{\mathrm{fai}}$（$p$ 为首件需求，$q$ 为余量需求），两端均在 $D'$ 且等待时间为 $\mathrm{lead}_{pq}$（小时）；$\sigma_t,\epsilon_t$ 分别为槽 $t$ 在开始–结束在同一时间轴上的标量（与 §2.2 一致）。则：

$$
\begin{aligned}
e_d &\geq \epsilon_t - M\bigl(1-z_{dlt}\bigr), && \forall d\in D',\ \forall (d,l,t)\in K, \\
\sigma_t + M\bigl(1-z_{qlt}\bigr) &\geq e_p + \mathrm{lead}_{pq}, && \forall (p,q)\in \mathcal{A}^{\mathrm{fai}},\ \forall (q,l,t)\in K.
\end{aligned}
$$

**说明**：若以日历审计细排结果，离散槽标量与时间戳之间可能存在余项，宜在细排层再次核对。

### 8.7 机型与粗换线

记 $K_{lmt}=\{(d,l,t)\in K \mid \mathrm{model}(d)=m\}$，$m\in M^{model}$。当使用 $z_{dlt}$ 时：

$$
\begin{aligned}
\sum_{(d,l,t)\in K_{lmt}} z_{dlt} &\leq \lvert K_{lmt}\rvert \, g_{lmt}, \\
g_{lmt} &\leq \sum_{(d,l,t)\in K_{lmt}} z_{dlt}.
\end{aligned}
$$

无 $\{z_{dlt}\}$ 时，可采用 $\sum_{(d,l,t)\in K_{lmt}} x_{dlt} \leq R_{lmt}\, g_{lmt}$（$R_{lmt}$ 为该组产量上界的有限上估计）及对偶下界连结 $g_{lmt}$，形式与「上界+M」族一致。

$$
\begin{aligned}
h_{lt} &\geq \sum_{m\in M^{model}} g_{lmt} - 1, \\
\mathrm{setup}_{lt} &\geq ct^{\min}_l\, h_{lt}.
\end{aligned}
$$

### 8.8 锁定未消元的情形（简述）

若锁定排程变量保留在主模型中，则需对每条锁定记录施加等式（在对应 $(d,l,t)$ 上产量等于锁定量）及与其余槽互斥约束；形式与 **`v6` 整单锁定表述**等价；此处从略。

---

## 9. 目标函数（词典序）

设有 $P$ 个优先级层级（典型 $P=4$ 或 $5$），按 $p=1$ 最重要依次减弱。

**第一层（$p=1$）**——交付与主优先级：

$$
\min\ \mathrm{Obj}_1 = \sum_{d \in D'} W_d^{\mathrm{eff}} \Bigl(
\omega_{ots}\,\kappa_d^{ots}\,\mathrm{miss}_d^{ots}
+ \omega_{fpsd}\,\kappa_d^{fpsd}\,\mathrm{miss}_d^{fpsd}
+ \omega_{ship2}\,\kappa_d^{ship2}\,\mathrm{miss}_d^{ship2}
+ \omega_{uns}\, c_d
\Bigr).
$$

**第二层**——与 $\mathrm{KPI}^{\mathrm{mode}}$ 一致：  
若 $\mathrm{qtymax}$，则 $\min\ \mathrm{Obj}_2 = \sum_{d\in D'} c_d$；  
若 $\mathrm{ordermax}$，则 $\max\ \sum_{d\in D'} u_d$（标量化时可写为等价的 $\min\sum_{d\in D'} (1-u_d)$）。

**第三层（可选）**——在 $\mathrm{qtymax}$ 下偏好更多**整单完成**：

$$
\max\ \sum_{d\in D'} u_d.
$$

**第四层**——线体偏好与 Cell 惩罚（系数 $C_{dlt}$ 由业务偏好表与线体 Cell 标记构成）： 

$$
\min\ \mathrm{Obj}_3 = \sum_{(d,l,t)\in K} C_{dlt}\, x_{dlt}. 

$$

**第五层**——粗效率：  

$$
\min\ \mathrm{Obj}_4 = \sum_{(l,t)\in LT} \mathrm{setup}_{lt} + \sum_{l,m,t} g_{lmt}.
$$

词典序实现方式不限于某一种求解器 API；核心是**按层级逐次固定或 epsilon-约束**。

---

## 10. 班内细排（二阶段）：作用、输入与校核

**与主模型的分界**：主 MILP 只决定各 $(l,t,d)$（线体–槽–**合并后**需求）上的**非负整数产量**；**不决定**同槽内线序。**班内细排层**在满足主模型产量的前提下，为每个有线体产量的槽输出任务**执行顺序**（常以班次内序号 $\mathrm{seq}$ 表示），以满足锁定序、机型连续性与物料切换等规则。

### 10.1 输入

| 类别                                 | 内容                                                                     |
| ---------------------------------- | ---------------------------------------------------------------------- |
| 主模型解                               | 各 $(l,t,d)$ 上正产量及线、槽                                                   |
| 锁定/FIX、继承调整                        | 业务表给定的先后顺序（若有），细排不得破坏已定相对顺序                                            |
| 物料排序规则表 `aps_schedule_order_ruler` | 解析为物料键次序（常按「线体 + 优先级」）；默认键链等价 KB → LOG UP ASSY → COVER → PCBA（以字段存在为准） |
| 需求属性                               | `model`、`lot`、`mo` 与各物料键，用于同级别排序比较                                     |

无二阶段专有数值超参：顺序仅靠 `aps_schedule_order_ruler` 与 §10.2；若需改动则改规则表或通过 §11 与主模型形态组合调整。

### 10.2 排序键优先级

对每个 $(l,t)$ 的非空任务集给定全序，自上而下逐键比较：

1. 锁定任务相对于 MILP 新排产的优先；
2. 不同锁定来源的业务顺位（若有）；
3. FIX/继承表内显式顺序号递增；
4. **机型**，先于批次与工单键，以降低机型 **ABABA** 交错；
5. **`lot`、`mo` 及批次语义字段**（同机型内二次聚合）；
6. `aps_schedule_order_ruler` 给出的物料键序列；
7. 合并后 demand 标识作平局打破。

### 10.3 校核汇报

对同槽拆线、基于日历的首末时刻与 **FAI** $\mathrm{lead}$（小时）、合成机时对 $\mathrm{Avail}_{lt}$、换线摘要等做一致性说明；可与 §8 槽离散标尺存在余项，仅供参考与执行。

---

## 11. 实现形态变体（不展开具体工程开关）

为平衡规模与严格性，可在实现层选择不同组合（**以下仅列数学含义，不绑定具体参数名**）：

1. **激活变量 $z$**  
   
   - **开**：强化「同需求同槽单线」、便于 FAI Big-M、机型 $g$ 与 $z$ 联动。  
   - **关**：模型更小，但可能出现同槽多线拆分，依赖细排或事后规则修复。

2. **FAI**  
   
   - **主模型 Big-M + $z$**：在 $\mathcal{A}^{\mathrm{fai}}$ 子集上硬满足先后（时间离散化意义下）。  
   - **仅候选剪枝 ± 解后迭代收缩候选再解**：规模较小，不保证与日历审计逐条一致。

3. **锁定**  
   
   - **消元**（扣减 $\mathrm{Avail}_{lt}$、缩小 $D'$、$K$）或 **留在主问题等式锁定**。

4. **交付 buffer、MR 豁免、紧急权重放大**  
   诸参数均为**业务标定**；实现上应能独立调节各截止类 buffer、是否启用 MR 豁免、$\alpha$ 等，而不改变 §5–§9 的结构。

---

## 12. 输入表与模型环节的对应关系（业务视角）

| 工作表 / 逻辑表                                                              | 对应建模环节                                                   |
| ---------------------------------------------------------------------- | -------------------------------------------------------- |
| `aps_schedule_demand_base_input`                                       | 需求集 $D$、数量与日期字段                                          |
| `aps_schedule_master_pn_input`                                         | 机型、程序等主数据合并                                              |
| `aps_schedule_priority`（目录常作 `aps_schedule_priority_setting_input`）    | $W_d^{\mathrm{pri}}$、$\mathrm{KPI}^{\mathrm{mode}}$      |
| `aps_merge_priority_setting`（目录常作 `aps_merge_priority_setting_input`）  | **§7.0**：排前合并阶段与键、`lot`/FIX/FAI/继承排除规则、合并后集合 $D$         |
| `aps_schedule_line_input`                                              | 线体 Cell 标记等                                              |
| `aps_schedule_line_calendar`、`aps_schedule_off_time_input`             | 槽集合、停机、日历与 demand_flag                                   |
| `aps_schedule_reserver_input`                                          | $\mathrm{Res}_{lt}$（可选）                                  |
| `aps_schedule_uph_input`                                               | $\mathrm{uph}_{dlt}$ 与可行匹配                               |
| `aps_change_time_input`                                                | $ct^{\min}_l$ 与细排挤换                                      |
| `aps_schedule_limit_setting`                                           | 机型/线体/班次限制，进入 $\mathrm{elig}$                            |
| `aps_schedule_order_qty`                                               | 大小单规则，进入候选或 $\mathrm{elig}$                              |
| `aps_schedule_order_ruler`                                             | **§10**：细排物料键顺序；输入与键链见 **§10.1、§10.2**                   |
| `aps_schedule_demand_fix_input`、`aps_adjust_schedule_input`（及继承/FIX语义） | 锁定集 $D^{\mathrm{lock}}$、外部 $\mathrm{Occ}^{\mathrm{ext}}$ |
| `aps_schedule_demand_fai_input`                                        | $\mathcal{A}^{\mathrm{fai}}$、$lead_g$                    |

求解过程可产出**中间数据集**（如需求维表、候选三元组表、线体–槽可用机时表、FAI 弧表）供求解器读入与审计；具体持久化文件名属实现细节，不在建模正文展开。

---

## 13. 小结

`v7.4` 在**业务 KPI 含义、优先级分组逻辑、FIX/合并语义**等方面与 **`v6`** 对齐，同时采用**稀疏候选、锁定消元、日桶聚合、交付 miss 的槽集合表述**以降低全实例规模。**实现上**可在「轻量近似」与「严格整数 + Big-M」之间切换（§11），与求解器无关。字段级定义仍以企业数据字典为准；若业务规则修订，应先更新 §2、§5 的语义，再推导 §8–§9 是否需要增删约束或层级。
