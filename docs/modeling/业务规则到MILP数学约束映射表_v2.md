# BOX APS业务规则到 MILP 数学约束映射表 v2

## 1. 文档目的

本文基于以下资料整理：

- `APS系统数据表目录.xlsx`
- `BOX 智能排产约束规则.xlsx`
- `BOX APS脱敏数据-2.xlsx`

## 2. 建模边界与时间粒度

结合 BOX APS 当前数据结构，推荐把主模型的时间粒度定义为“线体-日期-班次”的离散时段。

即：

- 一个时段 `t` 对应一个 `(day, shift_seq)` 组合。
- 主模型负责决定“哪个需求排到哪条线、哪天、哪个班、排多少”。
- 班内精确顺序、分钟级换线、ABABA 消除等更细时序问题，建议作为二阶段细排模型处理。

为了让本文中的公式更容易落地，以下映射采用一个常见工程假设：

- 经过预处理后，参与主模型的 `demand_id` 已经是可管理的排产单元。
- 对于 FAI、FIX、超大单跨班等场景，可以先拆单，再进入主模型。

## 3. 集合、索引与参数

### 3.1 集合与索引

- 需求集合：($D$)，索引为 ($d$)
- 线体集合：($L$)，索引为 ($l$)
- 班次时段集合：($T$)，索引为 ($t$)
- 机型集合：($M$)，索引为 ($m$)
- FAI 分组集合：($G$)，索引为 ($g$)

常用子集：

- 冻结或已开工单集合：($D^{freeze}$)
- FIX 需求集合：($D^{fix}$)
- FAI 需求集合：($D^{fai}$)
- Fast Ship 需求集合：($D^{fast}$)
- 小单需求集合：($D^{small}$)
- 定制化需求集合：($D^{cust}$)
- Cell 线集合：($L^{cell}$)

### 3.2 时间与产能参数

- 时段开始时间：($a_t$)
- 时段结束时间：($b_t$)
- 线体班次总工时：($cap_{lt}$)
- 线体班次停机工时：($down_{lt}$)
- 线体班次预留工时：($res_{lt}$)
- 线体班次净可用工时：($avail_{lt}$)

净可用工时定义为：

($avail_{lt} = cap_{lt} - down_{lt} - res_{lt}$)

### 3.3 需求属性参数

- 需求数量：($q_d$)
- 物料齐套日期：($mr_d$)
- OTS 日期：($due_d^{ots}$)
- FPSD 日期：($due_d^{fpsd}$)
- Ship Date：($due_d^{ship}$)
- 紧急标记：($urgent_d \in \{0,1\}$)
- Pre-Lock 标记：($prelock_d \in \{0,1\}$)
- Fast Ship 标记：($fast_d \in \{0,1\}$)
- 小单标记：($small_d \in \{0,1\}$)
- 定制化标记：($cust_d \in \{0,1\}$)
- FIX 标记：($fix_d \in \{0,1\}$)
- 需求机型：($model_d$)
- 需求业务分类：($mcode_d$)

### 3.4 匹配与规则参数

- 需求在线体班次上的可行性：($elig_{dlt} \in \{0,1\}$)
- 需求在线体班次上的 UPH：($uph_{dlt}$)
- 线体是否为 Cell 线：($cell_l \in \{0,1\}$)
- 工单冻结线体：($line_d^{freeze}$)
- 工单冻结时段：($slot_d^{freeze}$)
- FIX 线体：($line_d^{fix}$)
- FIX 时段：($slot_d^{fix}$)
- FIX 数量：($qty_d^{fix}$)
- FIX 顺序：($seq_d^{fix}$)
- FAI 分组首件需求：($d_g^{first}$)
- FAI 最小间隔：($lead_g$)
- 两需求间的换线耗时：($ct_{d_1 d_2}$)
- 排序偏好系数：($pref_{d_1 d_2 l}$)
- 需求优先级权重：($prio_d$)
- 大 M 常数：($M$)

## 4. 决策变量

本节统一声明全文会用到的所有决策变量。  
如果项目只做班次级主模型，可以只使用前 6 类变量；如果项目继续做班内细排，则再启用后续顺序类变量。

### 4.1 主模型变量

- 排产数量变量：($x_{dlt} \in \mathbb{Z}_+$)  
  表示需求 ($d$) 在线体 ($l$)、时段 ($t$) 上安排的数量。

- 排产启用变量：($z_{dlt} \in \{0,1\}$)  
  表示需求 ($d$) 是否在线体 ($l$)、时段 ($t$) 上发生排产。

- 需求是否被排到：($u_d \in \{0,1\}$)  
  表示需求 ($d$) 是否至少有一部分被安排。

- 未排数量变量：($c_d \in \mathbb{Z}_+$)  
  表示需求 ($d$) 在当前排程版本中的未满足数量。

- 需求开始时刻：($s_d \in \mathbb{R}_+$)  
  用于表达需求的开始投产时间，尤其服务 FAI、先后关系和细排。

- 需求完成时刻：($e_d \in \mathbb{R}_+$)  
  用于表达需求的完成时间，尤其服务交付约束与 KPI 计算。

### 4.2 细排与顺序变量

- 同班次先后变量：($y_{d_1 d_2 l t} \in \{0,1\}$)  
  表示在同一线体同一时段内，需求 ($d_1$) 是否排在需求 ($d_2$) 前面。

- 相邻换线变量：($\chi_{d_1 d_2 l t} \in \{0,1\}$)  
  表示在同一线体同一时段内，需求 ($d_1$) 与需求 ($d_2$) 是否构成一次相邻切换。

- 机型激活变量：($g_{lmt} \in \{0,1\}$)  
  表示机型 ($m$) 是否在线体 ($l$)、时段 ($t$) 上出现。

- 换线总工时变量：($setup_{lt} \in \mathbb{R}_+$)  
  表示线体 ($l$) 在时段 ($t$) 内由于换线产生的额外损失工时。

### 4.3 交付 KPI 变量

- OTS 延期变量：($late_d^{ots} \in \mathbb{R}_+$)
- FPSD 延期变量：($late_d^{fpsd} \in \mathbb{R}_+$)
- Ship Date 延期变量：($late_d^{ship} \in \mathbb{R}_+$)

## 5. 基础约束框架

### 5.1 需求平衡

每个需求的已排量与未排量之和等于需求总量：

($\sum_{l \in L}\sum_{t \in T} x_{dlt} + c_d = q_d,\ \forall d \in D$)

### 5.2 数量与启用变量联动

如果需求没有在某线某班启用，则该位置不能排量：

($x_{dlt} \le q_d \cdot z_{dlt},\ \forall d \in D, l \in L, t \in T$)

### 5.3 需求是否被排到

($\sum_{l \in L}\sum_{t \in T} x_{dlt} \le q_d \cdot u_d,\ \forall d \in D$)

($\sum_{l \in L}\sum_{t \in T} x_{dlt} \ge u_d,\ \forall d \in D$)

### 5.4 线体班次产能

线体班次内所有排产数量折算成工时后，不得超过净可用工时：

($\sum_{d \in D}\frac{x_{dlt}}{uph_{dlt}} + setup_{lt} \le avail_{lt},\ \forall l \in L, t \in T$)

### 5.5 可行域裁剪

如果需求在线体班次上不可行，则直接禁止排产：

($x_{dlt} \le q_d \cdot elig_{dlt},\ \forall d \in D, l \in L, t \in T$)

## 6. 业务规则到 MILP 的逐条映射

### 6.1 规则 1：工单冻结

业务含义：已经开立且不希望重排的工单，需遵循原计划。

模型归类：硬约束。

如果需求 ($d$) 属于冻结工单，且业务要求固定到指定线体与时段：

($x_{d, line_d^{freeze}, slot_d^{freeze}} = q_d,\ \forall d \in D^{freeze}$)

($x_{dlt} = 0,\ \forall d \in D^{freeze}, (l,t) \neq (line_d^{freeze}, slot_d^{freeze})$)

如果业务只冻结日期、不冻结线体，则只保留时段约束：

($x_{dlt} = 0,\ \forall d \in D^{freeze}, t \neq slot_d^{freeze}$)

### 6.2 规则 2：订单作为主优化对象

业务含义：普通待生产订单是主排产对象。

模型归类：基础对象，不单独形成特殊约束。

其核心已经体现在需求平衡、产能约束、可行域约束和目标函数中。

### 6.3 规则 3：MR Date 约束

业务含义：排产日期不能早于物料齐套日期。

模型归类：硬约束。

若时段开始时间早于齐套日期，则禁止排产：

($x_{dlt} = 0,\ \forall d \in D, l \in L, t \in T \text{ s.t. } a_t < mr_d$)

### 6.4 规则 4：排产优先级

业务含义：需求不能简单先到先排，而应按业务定义的优先级分层。

模型归类：软约束或目标函数。

最直接的写法是最大化高优先级需求的已排量：

($\max \sum_{d \in D} prio_d \cdot \sum_{l \in L}\sum_{t \in T} x_{dlt}$)

更推荐的工程写法是分层优化：

($\min Obj_1 = \sum_{d \in D} (\omega_1 \cdot urgent_d + \omega_2 \cdot prelock_d + \omega_3 \cdot prio_d)\cdot c_d$)

即优先最小化高优先级需求的未排量。

### 6.5 规则 5：UPH 约束

业务含义：同一机型在不同线体、不同班次上的生产效率不同。

模型归类：硬约束。

该规则已经反映在线体班次产能约束中：

($\sum_{d \in D}\frac{x_{dlt}}{uph_{dlt}} + setup_{lt} \le avail_{lt},\ \forall l \in L, t \in T$)

如果某个需求在线体班次上没有合法 UPH，则建议预处理为：

($elig_{dlt} = 0$)

### 6.6 规则 6：生产日历约束

业务含义：只能在开班时段内排产。

模型归类：硬约束。

如果某条线在某班次不开班，则净可用工时为 0，或者直接禁排：

($avail_{lt} = 0,\ \forall (l,t) \text{ 为停班时段}$)

等价地，也可以写成：

($x_{dlt} = 0,\ \forall d \in D,\ \forall (l,t) \text{ 为停班时段}$)

### 6.7 规则 7：产能预留

业务含义：部分班次产能需预留给其他用途，不能被普通排产占用。

模型归类：硬约束。

先通过净工时计算把预留工时扣掉：

($avail_{lt} = cap_{lt} - down_{lt} - res_{lt}$)

再统一进入产能约束：

($\sum_{d \in D}\frac{x_{dlt}}{uph_{dlt}} + setup_{lt} \le avail_{lt},\ \forall l \in L, t \in T$)

### 6.8 规则 8：产线与机型匹配

业务含义：不是所有机型都能在所有线体生产，且可生产线中还存在优先线。

模型归类：

- 可生产关系是硬约束
- 优先线关系是软约束

硬约束写法：

($x_{dlt} \le q_d \cdot elig_{dlt},\ \forall d \in D, l \in L, t \in T$)

若要表达优先线偏好，可在目标中增加奖励项：

($\max \sum_{d \in D}\sum_{l \in L}\sum_{t \in T} pref_{dlt}^{line} \cdot x_{dlt}$)

其中 ($pref_{dlt}^{line}$) 是来自业务配置的线机偏好系数。

### 6.9 规则 9：客制化订单、小单、Fast Ship 优先 Cell 线

业务含义：这类需求更适合柔性更高的 Cell 线。

模型归类：

- 若业务定义为“优先”，则作为软约束
- 若业务定义为“必须”，则作为硬约束

软约束写法：

($\min Obj_{cell} = \sum_{d \in D}\sum_{l \in L}\sum_{t \in T}(fast_d + small_d + cust_d)\cdot (1-cell_l)\cdot x_{dlt}$)

即尽量减少快单、小单、定制化订单落在非 Cell 线上的数量。

硬约束写法：

($x_{dlt} = 0,\ \forall d \in D^{fast}\cup D^{small}\cup D^{cust},\ l \notin L^{cell},\ t \in T$)

### 6.10 规则 10：FIX 约束

业务含义：业务已明确指定某需求在某天某班某线甚至某顺序执行。

模型归类：硬约束。

如果 FIX 需求只固定一部分数量：

($x_{d, line_d^{fix}, slot_d^{fix}} \ge qty_d^{fix},\ \forall d \in D^{fix}$)

如果 FIX 需求是整单锁死：

($x_{d, line_d^{fix}, slot_d^{fix}} = q_d,\ \forall d \in D^{fix}$)

($x_{dlt} = 0,\ \forall d \in D^{fix}, (l,t) \neq (line_d^{fix}, slot_d^{fix})$)

如果需要固定班内顺序，则在细排模型中再加入：

($s_d = seq_d^{fix},\ \forall d \in D^{fix}$)

更严格地说，若 ($seq_d^{fix}$) 不是时间而是序号，则应在二阶段细排模型中映射到顺序变量。

### 6.11 规则 11：机型限制

业务含义：某些机型只能在特定班次、特定线体、特定场景中生产。

模型归类：硬约束。

这类规则本质上仍然是“缩小可行域”，统一落在：

($x_{dlt} \le q_d \cdot elig_{dlt},\ \forall d \in D, l \in L, t \in T$)

其中 ($elig_{dlt}$) 应由以下信息共同预处理得到：

- `aps_schedule_limit_setting_input`
- `aps_schedule_line_input`
- `aps_schedule_uph_input`
- `scene_type`

### 6.12 规则 12：FAI 限制

业务含义：FAI 首件需求必须先做，且同组后续需求要满足最小间隔。

模型归类：硬约束。

建议做法：

- 先把首件需求与余量需求拆成独立 job。
- 对拆分后的 job 定义开始和结束时刻变量。

对于每个 FAI 分组 ($g \in G$)，设首件需求为 ($d_g^{first}$)，组内其他需求集合为 ($D_g^{rest}$)，则：

($s_r \ge e_{d_g^{first}} + lead_g,\ \forall g \in G,\ \forall r \in D_g^{rest}$)

若还要求首件必须先于同组其他需求开始，则可再加：

($s_r \ge s_{d_g^{first}},\ \forall g \in G,\ \forall r \in D_g^{rest}$)

### 6.13 规则 13：订单交付指标

业务含义：优先保障 OTS、FPSD、Urgent、D+2 ShipDate 等交付类 KPI。

模型归类：核心优化目标。

把需求完成时间与交期比较，定义延期变量：

($late_d^{ots} \ge e_d - due_d^{ots},\ \forall d \in D$)

($late_d^{fpsd} \ge e_d - due_d^{fpsd},\ \forall d \in D$)

($late_d^{ship} \ge e_d - due_d^{ship},\ \forall d \in D$)

($late_d^{ots} \ge 0,\ \forall d \in D$)

($late_d^{fpsd} \ge 0,\ \forall d \in D$)

($late_d^{ship} \ge 0,\ \forall d \in D$)

对应的一层目标函数可以写成：

($\min Obj_{delivery} = \sum_{d \in D}(\omega_{ots}\cdot late_d^{ots} + \omega_{fpsd}\cdot late_d^{fpsd} + \omega_{ship}\cdot late_d^{ship} + \omega_{urg}\cdot urgent_d \cdot c_d)$)

如果希望把 Pre-Lock 也体现为高优先级保障，可以再加：

($\min Obj_{delivery} = Obj_{delivery} + \sum_{d \in D}\omega_{lock}\cdot prelock_d \cdot c_d$)

### 6.14 规则 14：生产效率指标

该规则建议拆成四个子目标处理。

#### 6.14.1 机型换线最优

业务含义：同一线体同一班次内，换线越少越好。

细排模型中可定义换线总工时：

($setup_{lt} = \sum_{d_1 \in D}\sum_{d_2 \in D, d_1 \neq d_2} ct_{d_1 d_2}\cdot \chi_{d_1 d_2 l t},\ \forall l \in L, t \in T$)

再最小化：

($\min Obj_{setup} = \sum_{l \in L}\sum_{t \in T} setup_{lt}$)

#### 6.14.2 班次内同机型合并

业务含义：尽量减少同一班次内出现过多机型混排。

主模型可先用机型激活变量做近似：

($\sum_{d \in D: model_d = m} z_{dlt} \le |D_m|\cdot g_{lmt},\ \forall l \in L, m \in M, t \in T$)

再最小化：

($\min Obj_{merge} = \sum_{l \in L}\sum_{m \in M}\sum_{t \in T} g_{lmt}$)

这个写法不能完全消除 ABABA，但可以在主模型中先减少同班次的机型种类数。

#### 6.14.3 排程量最大

业务含义：在满足高优先级交付的前提下，希望排出尽可能多的数量。

可写成最大化已排量：

($\max Obj_{qty} = \sum_{d \in D}\sum_{l \in L}\sum_{t \in T} x_{dlt}$)

等价地，也可以写成最小化未排量：

($\min Obj_{qty} = \sum_{d \in D} c_d$)

#### 6.14.4 PO 物料顺序优化

业务含义：按照材料项、颜色、PCBA、KB 等业务定义顺序优化班内排程。

如果进入二阶段细排，则可用先后变量表达排序偏好：

($\max Obj_{seq} = \sum_{l \in L}\sum_{t \in T}\sum_{d_1 \in D}\sum_{d_2 \in D} pref_{d_1 d_2 l}\cdot y_{d_1 d_2 l t}$)

需要配套的顺序联动约束：

($y_{d_1 d_2 l t} \le z_{d_1 l t},\ \forall d_1,d_2,l,t$)

($y_{d_1 d_2 l t} \le z_{d_2 l t},\ \forall d_1,d_2,l,t$)

($y_{d_1 d_2 l t} + y_{d_2 d_1 l t} \le 1,\ \forall d_1 \neq d_2, l, t$)

## 7. 推荐目标函数层级

从笔记本电脑主板与装配类排产经验看，不建议把所有目标一次性糅成一个权重和，而更推荐词典序或分层优化。

推荐顺序如下：

### 第一层：先保证可行

这一层不需要目标函数，重点是满足所有硬约束：

- MR Date
- 日历
- 预留
- UPH
- 线机匹配
- FIX
- FAI
- 机型限制

### 第二层：交付优先

($\min Obj_1 = \sum_{d \in D}(\omega_{ots}\cdot late_d^{ots} + \omega_{fpsd}\cdot late_d^{fpsd} + \omega_{ship}\cdot late_d^{ship} + \omega_{urg}\cdot urgent_d \cdot c_d + \omega_{lock}\cdot prelock_d \cdot c_d)$)

### 第三层：排程量最大

($\min Obj_2 = \sum_{d \in D} c_d$)

### 第四层：效率最优

($\min Obj_3 = \omega_{setup}\sum_{l \in L}\sum_{t \in T} setup_{lt} + \omega_{model}\sum_{l \in L}\sum_{m \in M}\sum_{t \in T} g_{lmt}$)

### 第五层：柔性线与排序偏好

($\min Obj_4 = \omega_{cell}\sum_{d \in D}\sum_{l \in L}\sum_{t \in T}(fast_d + small_d + cust_d)\cdot (1-cell_l)\cdot x_{dlt} - \omega_{seq}\sum_{l \in L}\sum_{t \in T}\sum_{d_1 \in D}\sum_{d_2 \in D} pref_{d_1 d_2 l}\cdot y_{d_1 d_2 l t}$)

## 8. 落地建议

### 8.1 适合直接放进主 MILP 的部分

- 需求平衡
- MR Date
- 日历可用性
- 预留产能
- UPH 产能
- 线机匹配
- FIX 锁定
- 机型班次限制
- 交付 KPI

### 8.2 更适合二阶段细排的部分

- 分钟级换线最优
- ABABA 消除
- 同班次复杂排序
- 材料项精细顺序

### 8.3 实操建议

- 先预处理 `elig_{dlt}`，尽量缩小可行域。
- 先拆分 FAI、FIX、超大单等特殊需求，再做主模型。
- 主模型先解“排哪条线哪天哪班”，二阶段再细排班内顺序。

## 9. 后续

如果继续往下推进，下一步最值得补的是两份材料：

- “参数口径说明表”
- “原型数学模型说明书（sets / params / vars / constraints / objectives）”
