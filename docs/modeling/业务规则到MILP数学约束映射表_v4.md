# BOX APS业务规则到 MILP 数学约束映射表 v4

## 1. 审核结论

在重新核对以下三份资料后：

- `APS系统数据表目录.xlsx`
- `BOX-智能排产约束规则.xlsx`
- `业务规则到MILP数学约束映射表_v3.md`

可以得到一个更清晰的判断：

v3 中“额外业务约束与附加目标”这一节里，确实有一部分内容不应继续放在“主模型之外”，而应直接并入主模型。

应并入主模型的内容：

- `aps_schedule_limit_setting_input` 对应的限制可行域
- `aps_schedule_order_qty_setting_input` 中会改变可行域的大小单限制
- `aps_schedule_priority_setting_input` 对应的主优先级目标
- `aps_schedule_merge_priority_setting_input` 对应的合并后需求优先级目标
- `aps_adjust_schedule_input` 在滚动排程场景下对应的继承/冻结约束
- FIX 约束
- FAI 约束
- 客制化小单 / Fast Ship / 定制化订单优先 Cell 线的粗粒度分配目标
- 班次内机型合并的粗粒度目标

不应并入主模型、仍应留在预处理或二阶段的内容：

- `aps_merge_priority_setting_input`
- `aps_schedule_order_ruler_input`
- `aps_schedule_cycle_merge_setting_input`
- 分钟级换线和精确 ABABA 消除

因此，v4 的核心调整是：

- 把“影响可行性”的规则统一纳入主模型硬约束。
- 把“影响线体-班次分配倾向”的规则统一纳入主模型目标层。
- 只把真正依赖班内顺序的规则留在二阶段。

## 2. 更统一的模型分层

### 2.1 模型外预处理

以下内容在进入主模型前完成：

1. 原始需求合并  
   由 `aps_merge_priority_setting_input` 决定原始需求集合如何合并为主模型需求集合。
   
   > **由于该表在脱敏数据中不存在，因此此处待定**

2. 参数生成  
   由输入表生成：
   
   - 可行域参数
   - 产能参数
   - 交付参数
   - 优先级参数
   - Cell 线偏好参数
   - 粗粒度机型合并参数

### 2.2 主 MILP

主 MILP 统一解决：

- 哪个需求分配到哪条线、哪天、哪班
- 排多少
- 哪些需求先保
- 哪些需求优先上 Cell 线
- 哪些线体班次尽量少混机型
- 是否沿用旧方案 / FIX / FAI

### 2.3 二阶段细排

二阶段只处理：

- 班内颜色/材料项排序
- Cell 线循环排序
- 精确换线
- ABABA 消除

## 3. 集合、参数、决策变量

### 3.1 集合与索引

- 原始需求集合：($R$)，索引为 ($r$)
- 合并后需求集合：($D$)，索引为 ($d$)
- 线体集合：($L$)，索引为 ($l$)
- 班次时段集合：($T$)，索引为 ($t$)
- 机型集合：($M$)，索引为 ($m$)
- FAI 分组集合：($G$)，索引为 ($g$)

子集：

- FIX 需求集合：($D^{fix}$)
- 滚动继承需求集合：($D^{adj}$)
- Cell 线集合：($L^{cell}$)
- 机型为 ($m$) 的需求集合：($D_m$)

### 3.2 参数

#### 3.2.1 合并与基础参数

- 合并映射：($\phi: R \rightarrow D$)
- 需求数量：($q_d$)
- 需求机型：($model_d$)
- 需求业务分类：($mcode_d$)
- 时段开始时间：($a_t$)
- 时段结束时间：($b_t$)

#### 3.2.2 产能参数

- 班次总工时：($cap_{lt}$)
- 停机工时：($down_{lt}$)
- 预留工时：($res_{lt}$)
- 净可用工时：($avail_{lt}$)
- 合法 UPH：($uph_{dlt}$)
- 线体是否为 Cell 线：($cell_l \in \{0,1\}$)

#### 3.2.3 可行域参数

- 基础线机可行性：($elig_{dlt}^{base} \in \{0,1\}$)
- 限制规则可行性：($allow_{dlt}^{limit} \in \{0,1\}$)
- 大小单规则可行性：($allow_{dl}^{qty} \in \{0,1\}$)
- 日历可行性：($allow_{lt}^{cal} \in \{0,1\}$)
- MR Date 可行性：($allow_{dt}^{mr} \in \{0,1\}$)
- 综合可行性：($elig_{dlt} \in \{0,1\}$)

#### 3.2.4 交付参数

- 原始需求 OTS 截止时段集合：($T_r^{ots,raw} \subseteq T$)
- 原始需求 FPSD 截止时段集合：($T_r^{fpsd,raw} \subseteq T$)
- 原始需求 Ship Date 截止时段集合：($T_r^{ship,raw} \subseteq T$)
- OTS 截止时段集合：($T_d^{ots} \subseteq T$)
- FPSD 截止时段集合：($T_d^{fpsd} \subseteq T$)
- Ship Date 截止时段集合：($T_d^{ship} \subseteq T$)

#### 3.2.5 业务优先级参数

- 主优先级权重：($W_d^{pri}$)
- 合并后优先级权重：($W_d^{merge}$)
- 线体偏好成本：($C_{dl}^{line}$)
- Cell 线偏好成本：($C_{dl}^{cell}$)

#### 3.2.6 特殊规则参数

- FIX 线体：($line_d^{fix}$)
- FIX 时段：($slot_d^{fix}$)
- FIX 数量：($qty_d^{fix}$)
- 继承线体：($line_d^{adj}$)
- 继承时段：($slot_d^{adj}$)
- 继承数量：($qty_d^{adj}$)
- FAI 首件需求：($d_g^{first}$)
- FAI 余量需求集合：($D_g^{rest}$)
- FAI 等待时长：($lead_g$)
- 大 M 常数：($M$)

### 3.3 决策变量

- 排产数量：($x_{dlt} \in \mathbb{Z}_+$)
- 排产启用：($z_{dlt} \in \{0,1\}$)
- 需求是否被排到：($u_d \in \{0,1\}$)
- 未排数量：($c_d \in \mathbb{Z}_+$)
- 需求完成时间：($e_d \in \mathbb{R}_+$)
- OTS 未达成量：($miss_d^{ots} \in \mathbb{R}_+$)
- FPSD 未达成量：($miss_d^{fpsd} \in \mathbb{R}_+$)
- Ship Date 未达成量：($miss_d^{ship} \in \mathbb{R}_+$)
- 机型在班次上线体上是否出现：($g_{lmt} \in \{0,1\}$)

二阶段变量：

- 同班次先后变量：($y_{d_1 d_2 l t} \in \{0,1\}$)
- 相邻换线变量：($\chi_{d_1 d_2 l t} \in \{0,1\}$)
- 换线工时：($setup_{lt} \in \mathbb{R}_+$)

## 4. 预处理公式

### 4.1 合并规则

`aps_merge_priority_setting_input` 不直接进入主 MILP，而是先决定合并映射 ($\phi$)。

合并后数量：

($q_d = \sum_{r \in \phi^{-1}(d)} q_r,\ \forall d \in D$)

合并后交付集合取更严格口径：

($T_d^{ots} = \bigcap_{r \in \phi^{-1}(d)} T_r^{ots,raw},\ \forall d \in D$)

($T_d^{fpsd} = \bigcap_{r \in \phi^{-1}(d)} T_r^{fpsd,raw},\ \forall d \in D$)

($T_d^{ship} = \bigcap_{r \in \phi^{-1}(d)} T_r^{ship,raw},\ \forall d \in D$)

> **由于该表在脱敏数据中不存在，因此此处待定。**

### 4.2 可行域合成

净可用工时：

($avail_{lt} = cap_{lt} - down_{lt} - res_{lt},\ \forall l \in L,t \in T$)

综合可行性：

($elig_{dlt} = elig_{dlt}^{base} \cdot allow_{dlt}^{limit} \cdot allow_{dl}^{qty} \cdot allow_{lt}^{cal} \cdot allow_{dt}^{mr},\ \forall d \in D,l \in L,t \in T$)

## 5. 统一后的主模型硬约束

### 5.1 需求平衡

($\sum_{l \in L}\sum_{t \in T} x_{dlt} + c_d = q_d,\ \forall d \in D$)

### 5.2 启用联动

($x_{dlt} \le q_d \cdot z_{dlt},\ \forall d \in D,l \in L,t \in T$)

($x_{dlt} \ge z_{dlt},\ \forall d \in D,l \in L,t \in T$)

### 5.3 需求是否被排到

($\sum_{l \in L}\sum_{t \in T} x_{dlt} \le q_d \cdot u_d,\ \forall d \in D$)

($\sum_{l \in L}\sum_{t \in T} x_{dlt} \ge u_d,\ \forall d \in D$)

### 5.4 同一需求同一班次最多上一条线

($\sum_{l \in L} z_{dlt} \le 1,\ \forall d \in D,t \in T$)

### 5.5 线体班次产能

($\sum_{d \in D}\frac{x_{dlt}}{uph_{dlt}} \le avail_{lt},\ \forall l \in L,t \in T$)

### 5.6 综合可行域

这条约束已经把以下规则统一并入主模型：

- MR Date
- 日历
- 停机
- 预留
- 线机匹配
- `aps_schedule_limit_setting_input`
- `aps_schedule_order_qty_setting_input` 中会改变可行域的部分

数学形式为：

($x_{dlt} \le q_d \cdot elig_{dlt},\ \forall d \in D,l \in L,t \in T$)

### 5.7 完工时间定义

($e_d \ge b_t - M(1-z_{dlt}),\ \forall d \in D,l \in L,t \in T$)

### 5.8 交付未达成量定义

($miss_d^{ots} \ge q_d - \sum_{l \in L}\sum_{t \in T_d^{ots}} x_{dlt},\ \forall d \in D$)

($miss_d^{fpsd} \ge q_d - \sum_{l \in L}\sum_{t \in T_d^{fpsd}} x_{dlt},\ \forall d \in D$)

($miss_d^{ship} \ge q_d - \sum_{l \in L}\sum_{t \in T_d^{ship}} x_{dlt},\ \forall d \in D$)

($miss_d^{ots} \ge 0,\ \forall d \in D$)

($miss_d^{fpsd} \ge 0,\ \forall d \in D$)

($miss_d^{ship} \ge 0,\ \forall d \in D$)

### 5.9 FIX 约束

FIX 直接改变可行解，因此应并入主模型，而不应继续放在“附加约束”里。

若 FIX 为部分锁定：

($x_{d,line_d^{fix},slot_d^{fix}} \ge qty_d^{fix},\ \forall d \in D^{fix}$)

若 FIX 为整单锁定：

($x_{d,line_d^{fix},slot_d^{fix}} = q_d,\ \forall d \in D^{fix}$)

($x_{dlt} = 0,\ \forall d \in D^{fix},(l,t) \neq (line_d^{fix},slot_d^{fix})$)

### 5.10 滚动排程继承约束

若本轮使用 `aps_adjust_schedule_input` 做方案继承，则这类约束也应并入主模型。

部分继承：

($x_{d,line_d^{adj},slot_d^{adj}} \ge qty_d^{adj},\ \forall d \in D^{adj}$)

整单继承：

($x_{d,line_d^{adj},slot_d^{adj}} = q_d,\ \forall d \in D^{adj}$)

($x_{dlt} = 0,\ \forall d \in D^{adj},(l,t) \neq (line_d^{adj},slot_d^{adj})$)

> **此处待定**

### 5.11 FAI 约束

FAI 也是可行性约束，应并入主模型。

若首件需求已拆单，则余量需求的投产时段不得早于首件完成加等待时长：

($a_t + M(1-z_{rlt}) \ge e_{d_g^{first}} + lead_g,\ \forall g \in G,r \in D_g^{rest},l \in L,t \in T$)

### 5.12 班次内机型合并的粗粒度约束

`BOX-智能排产约束规则` 中“班次内机型合并”虽然最终表现为排序问题，但在主模型中至少应加入机型出现变量，用于粗粒度地减少一个班次内混入过多机型。

联动关系：

($\sum_{d \in D_m} z_{dlt} \le |D_m| \cdot g_{lmt},\ \forall l \in L,m \in M,t \in T$)

这不是精确排序，但它已经把“同班次尽量少混机型”前移到了主模型。

## 6. 统一后的主模型目标函数

v3 中有几项目标放在“附加目标”中，但从业务上看，它们其实属于主模型目标层，应该直接纳入统一优化框架。

### 6.1 第一层：交付 + 主优先级

`aps_schedule_priority_setting_input` 对应的优先级应并入主模型第一层目标。

($\min Obj_1 = \sum_{d \in D} W_d^{pri}\cdot (\omega_{ots}\cdot miss_d^{ots} + \omega_{fpsd}\cdot miss_d^{fpsd} + \omega_{ship}\cdot miss_d^{ship} + \omega_{uns}\cdot c_d)$)

### 6.2 第二层：排程量最大或订单笔数最大

若 `kpi = qtymax`：

($\min Obj_2 = \sum_{d \in D} c_d$)

若 `kpi = ordermax`：

($\max Obj_2' = \sum_{d \in D} u_d$)

> **此处kpi代表的业务规则不清晰，待定**

### 6.3 第三层：合并后需求优先级

`aps_schedule_merge_priority_setting_input` 对应的权重也应并入主模型，而不是留在模型之外。

($\min Obj_3 = \sum_{d \in D} W_d^{merge}\cdot c_d$)

### 6.4 第四层：线体分配偏好

规则 8 提到“按产线对应机型优先级顺序排产机型”，因此主模型中应增加线体偏好成本：

($\min Obj_4 = \sum_{d \in D}\sum_{l \in L}\sum_{t \in T} C_{dl}^{line}\cdot x_{dlt}$)

### 6.5 第五层：Cell 线偏好

规则 9 属于线体-班次层面的分配偏好，不必等到二阶段，因此应直接纳入主模型：

($\min Obj_5 = \sum_{d \in D}\sum_{l \in L}\sum_{t \in T} C_{dl}^{cell}\cdot (1-cell_l)\cdot x_{dlt}$)

### 6.6 第六层：班次内机型合并

主模型不能精确做班内排序，但可以最小化班次内出现的机型种类数：

($\min Obj_6 = \sum_{l \in L}\sum_{m \in M}\sum_{t \in T} g_{lmt}$)

这一步对应规则 14 中“班次内机型合并”的粗粒度近似。

## 7. 保留在二阶段的内容

经过本次审核，以下内容仍然不建议前移到主模型：

### 7.1 `aps_schedule_order_ruler_input`

该表控制颜色、KB、PCBA、Cover Assy、Thermal 等材料项顺序，实质上依赖班内顺序变量。

对应目标：

($\max Obj_{order} = \sum_{l \in L}\sum_{t \in T}\sum_{d_1 \in D}\sum_{d_2 \in D} P_{d_1 d_2 l}^{order}\cdot y_{d_1 d_2 l t}$)

### 7.2 `aps_schedule_cycle_merge_setting_input`

该表偏向 Cell 线循环排序和线内合并排序，更适合二阶段局部调度：

($\max Obj_{cycle} = \sum_{d \in D}\sum_{l \in L^{cell}}\sum_{t \in T} P_{dlt}^{cycle}\cdot x_{dlt}$)

> **由于该表在脱敏数据中不存在，因此此处待定**

### 7.3 精确换线

分钟级换线与 ABABA 消除仍放在二阶段：

($setup_{lt} = \sum_{d_1 \in D}\sum_{d_2 \in D,d_1 \neq d_2} ct_{d_1 d_2}\cdot \chi_{d_1 d_2 l t},\ \forall l \in L,t \in T$)

($\min Obj_{setup} = \sum_{l \in L}\sum_{t \in T} setup_{lt}$)

## 8. 统一后的完整框架

综上， 建议把 BOX APS 的数学模型框架统一为：

### 8.1 模型外

- `aps_merge_priority_setting_input`：决定需求合并

- 各输入表共同生成 $elig_{dlt}$、$avail_{lt}$、$W_d^{pri}$、$W_d^{merge}$、$C_{dl}^{line}$、$C_{dl}^{cell}$

> 由于`aps_merge_priority_setting_input`在脱敏数据中不存在，因此此处待定

### 8.2 主 MILP

硬约束：

- 需求平衡
- 启用联动
- 是否被排到
- 同一需求同班不并线
- 线体班次产能
- 综合可行域
- FIX
- 滚动继承
- FAI
- 粗粒度机型合并联动

目标层：

- 交付 + 主优先级
- 排程量 / 订单笔数
- 合并后需求优先级
- 线体分配偏好
- Cell 线偏好
- 班次内机型种类最少

### 8.3 二阶段

- 材料项排序
- Cell 循环排序
- 精确换线
- ABABA 消除

## 9. 结论

相较于 v3，v4 的关键改进不是“增加更多公式”，而是把公式放回更合适的层次：

- 会影响可行解的，必须进入主模型硬约束
- 会影响线体-班次分配倾向的，应该进入主模型目标
- 只有真正依赖班内顺序的，才留在二阶段

这样之后，主模型与二阶段的边界会更清楚，数学框架也更统一。
