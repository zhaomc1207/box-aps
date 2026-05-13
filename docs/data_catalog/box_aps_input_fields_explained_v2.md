# BOX APS输入表字段业务说明

## 1. 文档目的

本文基于 `APS系统数据表目录.xlsx` 中的 `BOX输入表` 工作表整理，目标是把每张输入表的每个字段翻译成更容易理解的业务语言。

阅读方式建议：

- 先看“表用途”，理解这张表在排产链路里扮演什么角色。
- 再看字段级说明，重点关注哪些字段用于需求识别、哪些字段用于约束、哪些字段用于排序与优先级。
- 对于同名字段，如 `schedule_version`、`demand_id`、`line_id`，可以跨表对照理解。

说明：

- “原始备注”来自 Excel。
- “业务理解”是在原始备注基础上，结合排产场景补充的解释。
- 若个别字段在原始文档中备注较短，本文会按主板/装配类 APS 常见业务口径做解释，最终仍建议以系统实现为准。

## 2. 输入表总览

| 表名                                          | 中文名                                        | 分组     | 字段数 | 作用概述                                                    |
| ------------------------------------------- | ------------------------------------------ | ------ | ---:| ------------------------------------------------------- |
| `aps_schedule_master_pn_input`              | 排程物料主数据Input表                              | 产品主数据  | 9   | 物料与机型主数据表，用于定义料号对应的机型、系列、Program、颜色等静态属性，是需求识别和线机匹配的基础。 |
| `aps_schedule_demand_base_input`            | 排程Demand基础数据Input表                         | 需求主数据  | 60  | 需求主表。所有待排需求基本都从这里进入，是交付、优先级、物料齐套和数量计算的核心来源。             |
| `aps_schedule_demand_expand_input`          | 排程Demand拓展数据Input表                         | 需求扩展   | 13  | 需求扩展属性表，用于补充基础需求表中没有直接展开的流程型或状态型属性。                     |
| `aps_schedule_demand_fai_input`             | 排程Demand FAI Input数据表                      | 特殊需求规则 | 8   | FAI/FOT/RPQ 等首件或特殊验证需求表，用于表达同组需求的先后关系和最小间隔。             |
| `aps_schedule_demand_fix_input`             | 排程Demand Fix Input数据表                      | 特殊需求规则 | 10  | 需求固定排产表，用于表达业务已经指定到某天、某班、某线、某顺序的需求。                     |
| `aps_schedule_demand_reserve_input`         | 排程预留Demand Input数据表                        | 特殊需求规则 | 7   | 预留需求表，用于表达不是普通订单、而是为了占用或预留产能而建立的需求对象。                   |
| `aps_adjust_schedule_input`                 | APS调整排程Input数据表                            | 人工调整输入 | 28  | 人工调整排程输入表，通常代表前一轮排程结果或人工指定结果，供本轮排程继承、调整或锁定。             |
| `aps_schedule_line_input`                   | 排程线体Input数据表                               | 资源主数据  | 10  | 线体主数据表，定义有哪些线、线体类型、开线类型等。                               |
| `aps_schedule_line_calendar_input`          | 排程线体日历Input数据表                             | 资源日历   | 14  | 线体班次日历表，定义每条线在每天每个班次是否开班、开班时间是什么。                       |
| `aps_schedule_off_time_input`               | 排程线体off Time Input数据表                      | 资源日历   | 9   | 线体停机时间表，用于扣减休息、吃饭、维护等不可生产时段。                            |
| `aps_schedule_uph_input`                    | 排程UPH Input数据表                             | 产能配置   | 15  | UPH 产能表，定义机型在特定线体、日期、班次上的单位小时产出能力。                      |
| `aps_change_time_input`                     | 排程换线时间 Input数据表                            | 换线配置   | 12  | 换线时间表，定义从一类产品切换到另一类产品时的额外耗时。                            |
| `aps_change_model_input`                    | 排程最优换线Model模型Input数据表                      | 换线配置   | 11  | 最优换型模型表，用于表达两个机型或 Program 之间的相似度、切换友好度。                 |
| `aps_schedule_reserver_input`               | 排程预留Input数据表                               | 产能预留   | 9   | 产能预留表，直接在日历上切出一段时间不可用于正常排产。                             |
| `aps_schedule_limit_setting_input`          | 排程限制条件 Input数据表                            | 规则配置   | 10  | 限制条件配置表，用于配置机型、班次、线体、场景等限制规则。                           |
| `aps_schedule_order_ruler_input`            | 排程颜色材料项Input数据表                            | 规则配置   | 9   | 颜色/材料项排序规则表，用于定义同线同班内不同订单的排序偏好。                         |
| `aps_schedule_order_qty_setting_input`      | 排程大小单配置Input数据表                            | 规则配置   | 7   | 大小单配置表，用于定义某线体对小单/大单的处理策略。                              |
| `aps_schedule_priority_setting_input`       | 排程优先级配置表                                   | 规则配置   | 12  | 需求优先级配置表，用于定义什么样的订单优先排。                                 |
| `aps_merge_priority_setting_input`          | 排产合并优先级设定Input表                            | 规则配置   | 8   | 需求合并优先级配置表，用于定义排程前如何按属性合并需求。                            |
| `aps_schedule_merge_priority_setting_input` | 排产合并demand需求排序优先级设定Input表                  | 规则配置   | 12  | 合并后需求的排序优先级配置表，用于定义合并后的 demand 进入排产时的排序逻辑。              |
| `aps_schedule_cycle_merge_setting_input`    | Cell线优先级排序循环配置&线体内进行合并排序配置 input（CPC 项目新增） | 规则配置   | 13  | Cell 线循环优先级与线体内合并排序配置表，主要服务小单、快单、定制化等柔性排产场景。            |

## 3. 字段逐表说明

### 3.1 `aps_schedule_master_pn_input`

- 中文名：排程物料主数据Input表
- 表用途：物料与机型主数据表，用于定义料号对应的机型、系列、Program、颜色等静态属性，是需求识别和线机匹配的基础。
- 字段数：9

| 字段名                    | 类型           | 可空  | 默认值  | 原始备注          | 业务理解                                           |
| ---------------------- | ------------ | --- | ---- | ------------- | ---------------------------------------------- |
| `id`                   | bigint       | N   |      | 主键（requestId） | 接口导入记录主键，通常与一次 requestId 绑定，主要用于追踪这一批数据来自哪次请求。 |
| `schedule_version`     | varchar(20)  | N   |      | 排程版本号         | 排产主版本号，标识一次完整排产任务；同一个版本下的输入数据会被一起计算。           |
| `sub_schedule_version` | varchar(30)  | N   |      | 子排程版本号        | 子排产版本号，用于区分同一主版本下的不同轮次、不同方案或重跑结果。              |
| `pn`                   | varchar(20)  | N   |      | 物料号           | 成品料号或物料号，是识别具体产品配置的核心字段。                       |
| `model`                | varchar(5)   | N   |      | 五码Model       | 五码机型，是线机匹配、UPH 匹配、换线和排序规则中最核心的产品属性之一。          |
| `series`               | varchar(30)  | Y   | 空字符串 | 系列            | 系列信息，用于归类相似机型，也常被用于换型相似度或规则过滤。**一般为空**         |
| `program`              | varchar(30)  | Y   | 空字符串 | Program       | Program 属性，通常与产品平台或程序版本相关，也会影响换线、匹配与排序。        |
| `texture`              | varchar(100) | Y   | 空字符串 | 属性            | 产品属性或材质维度，用来区分更细粒度的产品差异。                       |
| `color`                | varchar(20)  | Y   | 空字符串 | 颜色            | 颜色属性，常用于颜色切换、合并排序或业务偏好排序。                      |

### 3.2 `aps_schedule_demand_base_input`

- 中文名：排程Demand基础数据Input表
- 表用途：需求主表。所有待排需求基本都从这里进入，是交付、优先级、物料齐套和数量计算的核心来源。
- 字段数：60

| 字段名                    | 类型           | 可空  | 默认值     | 原始备注                                                                                                                 | 业务理解                                                       |
| ---------------------- | ------------ | --- | ------- | -------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------- |
| `id`                   | bigint       | N   |         | 主键（requestId）                                                                                                        | 接口导入记录主键，通常与一次 requestId 绑定，主要用于追踪这一批数据来自哪次请求。             |
| `schedule_version`     | varchar(20)  | N   |         | 排程版本号                                                                                                                | 排产主版本号，标识一次完整排产任务；同一个版本下的输入数据会被一起计算。                       |
| `sub_schedule_version` | varchar(30)  | N   |         | 子排程版本号                                                                                                               | 子排产版本号，用于区分同一主版本下的不同轮次、不同方案或重跑结果。                          |
| `mcode`                | varchar(30)  | N   |         | BU、ShipmentType、Brand                                                                                                | 业务分类键，通常同时承载 BU、ShipmentType、Brand 等信息，用于决定该需求或规则属于哪个业务口径。 |
| `demand_id`            | varchar(30)  | N   |         | MO/拆分后MR(FAI/FOT/RPQ/FIX /根据配置拆分数量)                                                                                  | 需求唯一标识，是需求主表、FAI、FIX、人工调整等多张表之间的核心关联键。                     |
| `dnno`                 | varchar(20)  |     |         | 订单号                                                                                                                  | 订单号，是需求在业务订单层面的主标识。                                        |
| `dndnline`             | varchar(30)  |     |         |                                                                                                                      | 订单号与订单行的组合键或扩展行号，常用于唯一识别订单行。                               |
| `dnline`               | varchar(10)  |     |         | 订单行                                                                                                                  | 订单行号。                                                      |
| `pn`                   | varchar(18)  | N   |         | 成品料号                                                                                                                 | 成品料号或物料号，是识别具体产品配置的核心字段。                                   |
| `mr_day`               | date         | N   |         | 齐套日期                                                                                                                 | 物料齐套日期，在这一天之前通常不允许正式投产。                                    |
| `mo`                   | varchar(20)  |     |         | MO                                                                                                                   | 制造工单号，是把需求与实际生产执行对象关联起来的关键字段。                              |
| `lot`                  | varchar(20)  |     |         | Lot                                                                                                                  | Lot 批次号，用于批次级追踪与排产。                                        |
| `demand_type`          | varchar(20)  |     |         | MR/ROLLING_MO/OPEN_MO/LOT/RESERVERD                                                                                  | 需求类型，用于区分 MR、OPEN MO、LOT、预留等不同来源的需求。                       |
| `qty`                  | Int          | N   |         | 需求数量                                                                                                                 | 当前需求行需要排产的数量。                                              |
| `ord_qty`              | int          | N   |         | 订单总数量                                                                                                                | 原始订单总数量，用来表示该订单全量规模。                                       |
| `line_qty`             | int          | N   |         | 实际计划生产数量                                                                                                             | 当前计划在生产侧实际安排的数量，通常用于区分订单总量和本次可排量。                          |
| `status`               | varchar(40)  |     |         | 齐套状态，C/P/N                                                                                                           | 状态字段，具体口径要结合所在表理解，可能表示齐套状态、启停状态或规则状态。                      |
| `procd`                | varchar(10)  |     |         | Product code：NB01/NB12                                                                                               | 产品代码或产品族代码，用于区分具体业务产品大类。                                   |
| `fg_ready_day`         | date         |     |         | FG Ready Day                                                                                                         | 成品可就绪日期，可视为供交付评估或节奏判断的一个时间点。                               |
| `total_index`          | Int          |     |         | 订单优先级                                                                                                                | 业务整体优先顺序号，常被用作订单优先级或排序参考。                                  |
| `pu_site`              | varchar      | N   |         | 厂区位置：YH/LCFC/JZ                                                                                                      | 厂区或园区位置，用于区分不同生产园区或站点。                                     |
| `plant`                | varchar      | N   |         | 财务工厂                                                                                                                 | 工厂代码，通常对应财务工厂或生产工厂口径。                                      |
| `pre_plan`             | varchar(1)   |     |         | Pre Plan                                                                                                             | 预排标记，表示这条需求是否带有预排计划属性。                                     |
| `pre_lock`             | varchar(1)   |     |         | Pre Lock                                                                                                             | 预锁标记，表示这条需求在排产时优先保持既定安排。                                   |
| `om_urgent`            | varchar(20)  |     |         | Om-Urgent                                                                                                            | 紧急订单标记，通常代表交付压力更高，应优先保障。                                   |
| `fpsd`                 | date         |     |         | FPSD                                                                                                                 | FPSD 交付相关日期，是优先级和达成率评估的重要输入。                               |
| `rersd`                | date         |     |         | Rersd                                                                                                                | 另一类交付参考日期，通常用于需求承诺或回推节奏判断。                                 |
| `ots_date`             | date         |     |         | Ots Target Date                                                                                                      | OTS 目标日期，是交付达成的重要考核时间点。                                    |
| `ship_date`            | date         |     |         | Ship Day                                                                                                             | 客户或业务要求的出货日期。                                              |
| `ship_day_two`         | date         |     |         | Ship Day2                                                                                                            | D+2 出货相关日期字段，常用于识别临近出货需求。                                  |
| `prs_date`             | date         |     |         | TDN Process Date                                                                                                     | 业务流程日期，通常是订单处理或 TDN 相关时间点。                                 |
| `country`              | varchar(3)   |     |         | 国家                                                                                                                   | 国家字段，常用于限制规则或交付优先级细分。                                      |
| `priority_code`        | int          |     |         | Priority Code                                                                                                        | 优先级编码，通常来自前置业务系统。                                          |
| `pending_pool`         | varchar(1)   |     |         | 缓冲池标识，X或空                                                                                                            | 缓冲池标记，表示需求是否暂时进入待排缓冲池。                                     |
| `fast_ship`            | varchar(1)   |     |         | Fast Ship 订单标识                                                                                                       | 快出货标记，通常意味着更高交付优先级，且更适合柔性线处理。                              |
| `eop`                  | varchar(40)  |     |         | EOP                                                                                                                  | EOP 相关业务标识，通常用于识别生命周期或特殊业务状态。                              |
| `create_by`            | varchar(50)  | 是   | 创建人     |                                                                                                                      | 创建人或创建来源，常用于审计数据来源是系统任务、人工维护还是接口同步。                        |
| `create_time`          | datetime     | 是   | 创建时间    | yyyy-MM-dd HH:mm:ss                                                                                                  | 创建时间，用于审计和排查数据导入先后顺序。                                      |
| `modify_by`            | varchar(50)  |     | 修改人     |                                                                                                                      | 最后修改人或修改来源。                                                |
| `modify_time`          | datetime     |     | 修改时间    | yyyy-MM-dd HH:mm:ss                                                                                                  | 最后修改时间。                                                    |
| `remark`               | varchar(200) |     | 备注      |                                                                                                                      | 备注字段，通常用于补充说明异常原因、业务解释或接口回传信息。                             |
| `material_type`        | varchar(30)  |     |         | 物料类型，Sub：SubType；Option：OptionType                                                                                   | 物料类型字段，用于区分 Sub、Option 等业务物料类别。                            |
| `create_mo_flag`       | varchar(1)   |     |         | PO ASSY/SUB/SUBSON是否开立MO，已开立：X                                                                                       | 是否已开立 MO 的标记，影响需求是否还需要继续开单或重新排产。                           |
| `kb`                   | varchar(20)  |     |         | 材料类型：KB                                                                                                              | 键盘类物料属性，用于排序、合并或物料切换规则。默认为空                                |
| `cover_assy`           | varchar(20)  |     |         | 材料类型：Cover Assy                                                                                                      | Cover Assy 物料属性，用于排序、合并或物料切换规则。                            |
| `log_up_assy`          | varchar(20)  |     |         | 材料类型：Log Up Assy                                                                                                     | Log Up Assy 物料属性，用于排序、合并或物料切换规则。                           |
| `pcba`                 | varchar(20)  |     |         | 材料类型：PCBA                                                                                                            | PCBA 物料属性，用于排序、合并或物料切换规则。                                  |
| `thermal`              | varchar(20)  |     |         | 材料类型：Thermal                                                                                                         | 散热件物料属性，用于排序、合并或物料切换规则。                                    |
| `material_sections`    | json         |     |         | 材料项属性集合（为增加材料项增加配置化）                                                                                                 | 材料项集合，通常以 JSON 形式记录更多材料属性，便于配置化扩展。                         |
| `tie_order`            | varchar(1)   |     |         | 绑单标识                                                                                                                 | 绑单标记，表示该需求需要与其他需求一起考虑，不宜随意拆散。                              |
| `vat_invno`            | varchar (12) |     |         | PO Flag                                                                                                              | PO Flag 或税务/单据相关标识，常被业务拿来做订单分组识别。                          |
| `dc`                   | varchar(5)   |     |         | Region                                                                                                               | 大区或区域字段，常用于业务分群或优先级细分。**一般为空**                             |
| `fast_ship_51j_status` | varchar (40) |     |         | Fast Ship 1st IPS 51J Status                                                                                         | Fast Ship 场景下首个 IPS/51J 流程状态，用于判断是否满足快单推进条件。               |
| `fast_ship_ots_date`   | date         |     |         | Fast Ship OTS Date                                                                                                   | Fast Ship 场景下单独维护的 OTS 日期。                                 |
| `ips_id`               | varchar(30)  |     |         | IPS_ID                                                                                                               | IPS 流程单号或识别号。                                              |
| `fix_flag`             | int          |     |         | 需求FIX标识：0-否；1-是                                                                                                      | 是否存在 FIX 约束的标记；为 1 时通常需要去 FIX 表读取更细的锁定规则。                  |
| `z_type`               | varchar(20)  |     |         | Option Type、Sub Type；取数逻辑：aps_assy_atblist//aps_server_atblist/aps_option_atblist-z_type，aps_sub_atblist-subtype_51j | 产品子类型字段，常用于区分 Option Type、Sub Type 等更细分物料类别。               |
| `shift_end_flag`       | int          |     |         | 跨班次标识：0-否；1-是；                                                                                                       | 跨班次标记，表示该需求在产能计算或细排时是否允许跨班结束。                              |
| `cust_svc`             | varchar(1)   |     | 定制化flag |                                                                                                                      | 定制化订单标记，常用于 Cell 线优先、快单优先等柔性排产逻辑。                          |
| `men_number`           | varchar(64)  |     | men 文   |                                                                                                                      | 业务附加编号字段，通常用于来源系统追溯或人工识别。                                  |

### 3.3 `aps_schedule_demand_expand_input`

- 中文名：排程Demand拓展数据Input表
- 表用途：需求扩展属性表，用于补充基础需求表中没有直接展开的流程型或状态型属性。
- 字段数：13

| 字段名                    | 类型          | 可空  | 默认值  | 原始备注                                | 业务理解                                           |
| ---------------------- | ----------- | --- | ---- | ----------------------------------- | ---------------------------------------------- |
| `id`                   | bigint      | N   |      | 主键（requestId）                       | 接口导入记录主键，通常与一次 requestId 绑定，主要用于追踪这一批数据来自哪次请求。 |
| `schedule_version`     | varchar(20) | N   |      | 排程版本号                               | 排产主版本号，标识一次完整排产任务；同一个版本下的输入数据会被一起计算。           |
| `sub_schedule_version` | varchar(30) | N   |      | 子排程版本号                              | 子排产版本号，用于区分同一主版本下的不同轮次、不同方案或重跑结果。              |
| `demand_id`            | varchar(30) | N   |      | 需求id                                | 需求唯一标识，是需求主表、FAI、FIX、人工调整等多张表之间的核心关联键。         |
| `c_or_p`               | varchar(1)  |     |      | Complete Or Partial                 | 齐套类型标记，表示 Complete 还是 Partial，用于判断是否允许投产。      |
| `create_mo`            | varchar (1) |     |      | 是否开立工单                              | 是否需要开立工单的标记。                                   |
| `need_fai`             | varchar (1) |     |      | Need Fai                            | 是否需要 FAI 首件验证的标记。                              |
| `hold_log`             | varchar (1) |     |      | Hold Log                            | 是否存在 Hold 相关日志或阻断信息。                           |
| `xn_hub_store`         | varchar(10) |     |      | XNHubStore：取值aps_sub_atblist-remark | 与 Hub/Store 相关的补充属性，通常来自其他业务表扩展。               |
| `create_by`            | varchar(50) | 是   | 创建人  |                                     | 创建人或创建来源，常用于审计数据来源是系统任务、人工维护还是接口同步。            |
| `create_time`          | datetime    | 是   | 创建时间 | yyyy-MM-dd HH:mm:ss                 | 创建时间，用于审计和排查数据导入先后顺序。                          |
| `modify_by`            | varchar(50) | 是   | 修改人  |                                     | 最后修改人或修改来源。                                    |
| `modify_time`          | datetime    | 是   | 修改时间 | yyyy-MM-dd HH:mm:ss                 | 最后修改时间。                                        |

### 3.4 `aps_schedule_demand_fai_input`

- 中文名：排程Demand FAI Input数据表
- 表用途：FAI/FOT/RPQ 等首件或特殊验证需求表，用于表达同组需求的先后关系和最小间隔。
- 字段数：8

| 字段名                    | 类型          | 可空  | 默认值 | 原始备注                                                | 业务理解                                           |
| ---------------------- | ----------- | --- | --- | --------------------------------------------------- | ---------------------------------------------- |
| `id`                   | bigint      | N   |     | 主键（requestId）                                       | 接口导入记录主键，通常与一次 requestId 绑定，主要用于追踪这一批数据来自哪次请求。 |
| `schedule_version`     | varchar(20) | N   |     | 排程生产版本                                              | 排产主版本号，标识一次完整排产任务；同一个版本下的输入数据会被一起计算。           |
| `sub_schedule_version` | varchar(30) | N   |     | 子排程版本号                                              | 子排产版本号，用于区分同一主版本下的不同轮次、不同方案或重跑结果。              |
| `group_id`             | varchar(20) | N   |     | 组Group号                                             | 业务分组号，用于把一组相关规则、相关需求或相关排序条件归并在一起。              |
| `demand_id`            | varchar(30) | N   |     | 需求id                                                | 需求唯一标识，是需求主表、FAI、FIX、人工调整等多张表之间的核心关联键。         |
| `group_first`          | bool        |     |     | 优先排产需求，1表示优先排产，否则为空；                                | 在分组需求中是否属于需要优先投产的那一条。                          |
| `lead_time`            | int         |     |     | 间隔时间，单位为分钟，当groupfirst=T 时有效，表示一组内剩余需求与T行的最小排产间隔时间； | 最小间隔时间，常用于表达首件完成后其余需求才能继续投入的等待窗口。              |
| `type`                 | varchar(20) | N   |     | 类型：FOT/FAI/RPQ                                      | FAI/FOT/RPQ 类型，用于区分这是首件验证、首单试产还是其他特殊验证场景。      |

### 3.5 `aps_schedule_demand_fix_input`

- 中文名：排程Demand Fix Input数据表
- 表用途：需求固定排产表，用于表达业务已经指定到某天、某班、某线、某顺序的需求。
- 字段数：10

| 字段名                    | 类型          | 可空  | 默认值 | 原始备注                  | 业务理解                                           |
| ---------------------- | ----------- | --- | --- | --------------------- | ---------------------------------------------- |
| `id`                   | bigint      | N   |     | 主键（requestId）         | 接口导入记录主键，通常与一次 requestId 绑定，主要用于追踪这一批数据来自哪次请求。 |
| `schedule_version`     | varchar(20) | N   |     | 排程版本号                 | 排产主版本号，标识一次完整排产任务；同一个版本下的输入数据会被一起计算。           |
| `sub_schedule_version` | varchar(30) | N   |     | 子排程版本号                | 子排产版本号，用于区分同一主版本下的不同轮次、不同方案或重跑结果。              |
| `demand_id`            | varchar(30) | N   |     | 需求Id                  | 需求唯一标识，是需求主表、FAI、FIX、人工调整等多张表之间的核心关联键。         |
| `fix_day`              | date        | N   |     | Fix天                  | 业务指定的固定排产日期。                                   |
| `fix_shift`            | int         | N   |     | Fix班次对应的编号            | 业务指定的固定班次。                                     |
| `fix_line`             | int         | N   |     | Fix线体id               | 业务指定的固定线体。                                     |
| `fix_sequence`         | Int         | N   |     | Fix顺序                 | 业务指定的固定顺序号。                                    |
| `fix_qty`              | Int         | N   |     | Fix数量                 | 业务指定必须固定排入的数量。                                 |
| `fix_type`             | varchar(1)  | N   |     | Fix类型：0：班次Fix，1：需求Fix | FIX 类型字段，用于说明这条 FIX 是按天班线锁定、按顺序锁定，还是其他固定方式。    |

### 3.6 `aps_schedule_demand_reserve_input`

- 中文名：排程预留Demand Input数据表
- 表用途：预留需求表，用于表达不是普通订单、而是为了占用或预留产能而建立的需求对象。
- 字段数：7

| 字段名                    | 类型          | 可空  | 默认值 | 原始备注          | 业务理解                                           |
| ---------------------- | ----------- | --- | --- | ------------- | ---------------------------------------------- |
| `id`                   | bigint      | N   |     | 主键（requestId） | 接口导入记录主键，通常与一次 requestId 绑定，主要用于追踪这一批数据来自哪次请求。 |
| `schedule_version`     | varchar(20) | N   |     | 排程版本号         | 排产主版本号，标识一次完整排产任务；同一个版本下的输入数据会被一起计算。           |
| `sub_schedule_version` | varchar(30) | N   |     | 子排程版本号        | 子排产版本号，用于区分同一主版本下的不同轮次、不同方案或重跑结果。              |
| `demand_id`            | varchar(30) | N   |     | 需求id          | 需求唯一标识，是需求主表、FAI、FIX、人工调整等多张表之间的核心关联键。         |
| `res_sequence`         | Int         | N   |     | Demand预留顺序    | 该字段的原始口径是“Demand预留顺序”，通常用于补充该表的业务判断、过滤条件或展示属性。 |
| `reserver_id`          | varchar(20) | N   |     | 预留编号          | 该字段的原始口径是“预留编号”，通常用于补充该表的业务判断、过滤条件或展示属性。       |
| `line_id`              | int         | N   |     | 线体id          | 线体唯一标识，是线体主数据、日历、UPH、限制规则和排产结果之间的主关联键。         |

### 3.7 `aps_adjust_schedule_input`

- 中文名：APS调整排程Input数据表
- 表用途：人工调整排程输入表，通常代表前一轮排程结果或人工指定结果，供本轮排程继承、调整或锁定。
- 字段数：28

| 字段名                     | 类型           | 可空  | 默认值 | 原始备注                  | 业务理解                                                       |
| ----------------------- | ------------ | --- | --- | --------------------- | ---------------------------------------------------------- |
| `id`                    | bigint       | N   |     | 主键（requestId）         | 接口导入记录主键，通常与一次 requestId 绑定，主要用于追踪这一批数据来自哪次请求。             |
| `run_version`           | varchar(20)  | N   |     | 运行版本                  | 该字段的原始口径是“运行版本”，通常用于补充该表的业务判断、过滤条件或展示属性。                   |
| `schedule_version`      | varchar(20)  | N   |     | 排程版本号                 | 排产主版本号，标识一次完整排产任务；同一个版本下的输入数据会被一起计算。                       |
| `sub_schedule_version`  | varchar(30)  | N   |     | 子排程版本号                | 子排产版本号，用于区分同一主版本下的不同轮次、不同方案或重跑结果。                          |
| `schedule_line_version` | int          | N   |     | 线体版本号                 | 线体版本号，用于标识线体配置快照版本。                                        |
| `mcode`                 | varchar(30)  | N   |     | BU、ShipmentType、Brand | 业务分类键，通常同时承载 BU、ShipmentType、Brand 等信息，用于决定该需求或规则属于哪个业务口径。 |
| `demand_id`             | bigint       | N   |     | 需求ID                  | 需求唯一标识，是需求主表、FAI、FIX、人工调整等多张表之间的核心关联键。                     |
| `schedule_qty`          | int          | N   |     | 排程数量                  | 当前记录对应的已排数量或计划数量。                                          |
| `line_id`               | bigint       | N   |     | 线体id                  | 线体唯一标识，是线体主数据、日历、UPH、限制规则和排产结果之间的主关联键。                     |
| `schedule_seq`          | int          | N   |     | 排程顺序                  | 人工调整后的排程顺序号，用于指定在线体班次内的先后。                                 |
| `schedule_day`          | date         | N   |     | 排程天                   | 人工调整后指定的排产日期。                                              |
| `shift_seq`             | int          | N   |     | 班次序号                  | 人工调整后指定的排产班次。                                              |
| `reserved_id`           | varchar(20)  | Y   |     | 预留号                   | 预留号，用于识别一段预留产能或预留任务。                                       |
| `pn`                    | varchar(20)  | N   |     | 物料号                   | 成品料号或物料号，是识别具体产品配置的核心字段。                                   |
| `model`                 | varchar(10)  | N   |     | 五码Model               | 五码机型，是线机匹配、UPH 匹配、换线和排序规则中最核心的产品属性之一。                      |
| `series`                | varchar(30)  | Y   |     | 系列                    | 系列信息，用于归类相似机型，也常被用于换型相似度或规则过滤。                             |
| `program`               | varchar(30)  | Y   |     | Program               | Program 属性，通常与产品平台或程序版本相关，也会影响换线、匹配与排序。                    |
| `texture`               | varchar(100) | Y   |     | 属性                    | 产品属性或材质维度，用来区分更细粒度的产品差异。                                   |
| `color`                 | varchar(20)  | Y   |     | 颜色                    | 颜色属性，常用于颜色切换、合并排序或业务偏好排序。                                  |
| `mo`                    | varchar(20)  | Y   |     | MO                    | 制造工单号，是把需求与实际生产执行对象关联起来的关键字段。                              |
| `lot`                   | varchar(20)  | Y   |     | Lot                   | Lot 批次号，用于批次级追踪与排产。                                        |
| `total_index`           | int          | Y   |     | 订单优先级                 | 业务整体优先顺序号，常被用作订单优先级或排序参考。                                  |
| `kb`                    | varchar(20)  | Y   |     | 材料类型：KB               | 键盘类物料属性，用于排序、合并或物料切换规则。                                    |
| `cover_assy`            | varchar(20)  | Y   |     | 材料类型：Cover Assy       | Cover Assy 物料属性，用于排序、合并或物料切换规则。                            |
| `log_up_assy`           | varchar(20)  | Y   |     | 材料类型：Log Up Assy      | Log Up Assy 物料属性，用于排序、合并或物料切换规则。                           |
| `pcba`                  | varchar(20)  | Y   |     | 材料类型：PCBA             | PCBA 物料属性，用于排序、合并或物料切换规则。                                  |
| `thermal`               | varchar(20)  | Y   |     | 材料类型：Thermal          | 散热件物料属性，用于排序、合并或物料切换规则。                                    |
| `material_sections`     | json         | Y   |     | 材料项属性集合（为增加材料项增加配置化）  | 材料项集合，通常以 JSON 形式记录更多材料属性，便于配置化扩展。                         |

### 3.8 `aps_schedule_line_input`

- 中文名：排程线体Input数据表
- 表用途：线体主数据表，定义有哪些线、线体类型、开线类型等。
- 字段数：10

| 字段名                    | 类型          | 可空  | 默认值 | 原始备注                               | 业务理解                                             |
| ---------------------- | ----------- | --- | --- | ---------------------------------- | ------------------------------------------------ |
| `id`                   | bigint      | N   |     | 主键（requestId）                      | 接口导入记录主键，通常与一次 requestId 绑定，主要用于追踪这一批数据来自哪次请求。   |
| `schedule_version`     | varchar(20) | N   |     | 排程版本号                              | 排产主版本号，标识一次完整排产任务；同一个版本下的输入数据会被一起计算。             |
| `sub_schedule_version` | varchar(30) | N   |     | 子排程版本号                             | 子排产版本号，用于区分同一主版本下的不同轮次、不同方案或重跑结果。                |
| `line_id`              | bigint      | N   |     | 线体id                               | 线体唯一标识，是线体主数据、日历、UPH、限制规则和排产结果之间的主关联键。           |
| `line`                 | varchar(10) | N   |     | 线体名称                               | 线体名称或线别简称，是业务现场识别产线的展示字段。                        |
| `line_type`            | varchar(20) | N   |     | 线体类型：Cell线/水星线                     | 线体类型，用于区分 normal 线、cell 线等不同排产模式。                |
| `open_type`            | varchar(20) | N   |     | 开班类型：大线/小线                         | 线体开线类型或组织类型，常用于区分大线、小线、特殊线等。                     |
| `pu_site`              | varchar(10) | N   |     | 厂区位置：LCFC/YH                       | 厂区或园区位置，用于区分不同生产园区或站点。                           |
| `pu`                   | varchar(10) | N   |     | 生产厂区：PU1/PU2                       | 该字段的原始口径是“生产厂区：PU1/PU2”，通常用于补充该表的业务判断、过滤条件或展示属性。 |
| `rolling_flag`         | varchar(1)  |     |     | Rolling MO不占产能：0-不占用产能；1-占用产能；默认是1 | 是否参与滚动排程的标记。                                     |

### 3.9 `aps_schedule_line_calendar_input`

- 中文名：排程线体日历Input数据表
- 表用途：线体班次日历表，定义每条线在每天每个班次是否开班、开班时间是什么。
- 字段数：14

| 字段名                     | 类型          | 可空  | 默认值 | 原始备注                            | 业务理解                                           |
| ----------------------- | ----------- | --- | --- | ------------------------------- | ---------------------------------------------- |
| `id`                    | bigint      | N   |     | 主键（requestId）                   | 接口导入记录主键，通常与一次 requestId 绑定，主要用于追踪这一批数据来自哪次请求。 |
| `schedule_version`      | varchar(20) | N   |     | 排程版本号                           | 排产主版本号，标识一次完整排产任务；同一个版本下的输入数据会被一起计算。           |
| `sub_schedule_version`  | varchar(30) | N   |     | 子排程版本号                          | 子排产版本号，用于区分同一主版本下的不同轮次、不同方案或重跑结果。              |
| `line_id`               | bigint      | N   |     | 线体id                            | 线体唯一标识，是线体主数据、日历、UPH、限制规则和排产结果之间的主关联键。         |
| `schedule_line_version` | int         |     |     | 线体版本号                           | 线体版本号，用于标识线体配置快照版本。统一为1                        |
| `day`                   | date        | N   |     | 日期                              | 业务日期字段，一般表示某条线某个班次对应的自然日。                      |
| `shift_seq`             | smallint    | N   |     | 班序号                             | 班次序号，通常用于区分白班、夜班等班次。                           |
| `shift`                 | varchar(10) |     |     | 班次                              | 该字段的原始口径是“班次”，通常用于补充该表的业务判断、过滤条件或展示属性。默认为空     |
| `shift_start_time`      | datetime    | N   |     | 班次开始时间                          | 班次开始时间。                                        |
| `shift_end_time`        | datetime    | N   |     | 班次结束时间                          | 班次结束时间。                                        |
| `shift_status`          | varchar(5)  | N   |     | 班次状态                            | 班次状态，常见口径为 ON/OFF，用于判断该班是否可以生产。                |
| `non_merge_flag`        | smallint    | N   |     | 班次不合并标识，0-不合并，1-合并              | 不可合并标记，表示该班次或时间块内不能做合并排产。                      |
| `fix_type`              | smallint    | N   |     | Fix类型：0：班次Fix，1：需求Fix           | 班次固定属性，常用于表示该班次是否已被固定计划占用或带有特定约束。              |
| `demand_flag`           | smallint    | N   |     | 排程订单类型：0：所有订单均可排；1：不可排Normal订单； | 是否允许安排正常需求的标记。                                 |

### 3.10 `aps_schedule_off_time_input`

- 中文名：排程线体off Time Input数据表
- 表用途：线体停机时间表，用于扣减休息、吃饭、维护等不可生产时段。
- 字段数：9

| 字段名                    | 类型          | 可空  | 默认值 | 原始备注          | 业务理解                                           |
| ---------------------- | ----------- | --- | --- | ------------- | ---------------------------------------------- |
| `id`                   | bigint      | N   |     | 主键（requestId） | 接口导入记录主键，通常与一次 requestId 绑定，主要用于追踪这一批数据来自哪次请求。 |
| `schedule_version`     | varchar(20) | N   |     | 排程版本号         | 排产主版本号，标识一次完整排产任务；同一个版本下的输入数据会被一起计算。           |
| `sub_schedule_version` | varchar(30) | N   |     | 子排程版本号        | 子排产版本号，用于区分同一主版本下的不同轮次、不同方案或重跑结果。              |
| `line_id`              | bigint      | N   |     | 线体id          | 线体唯一标识，是线体主数据、日历、UPH、限制规则和排产结果之间的主关联键。         |
| `day`                  | date        | N   |     | 日期            | 业务日期字段，一般表示某条线某个班次对应的自然日。                      |
| `shift_seq`            | varchar(1)  | N   |     | 班序号           | 班次序号，通常用于区分白班、夜班等班次。                           |
| `start_time`           | datetime    | N   |     | 开始时间          | 某段停机、预留或任务的开始时间。                               |
| `end_time`             | datetime    | N   |     | 结束时间          | 某段停机、预留或任务的结束时间。                               |
| `off_type`             | varchar(20) |     |     | OFF类型         | 停机类型，如休息、吃饭、维护等。                               |

### 3.11 `aps_schedule_uph_input`

- 中文名：排程UPH Input数据表
- 表用途：UPH 产能表，定义机型在特定线体、日期、班次上的单位小时产出能力。
- 字段数：15

| 字段名                    | 类型           | 可空  | 默认值     | 原始备注                       | 业务理解                                                       |
| ---------------------- | ------------ | --- | ------- | -------------------------- | ---------------------------------------------------------- |
| `id`                   | bigint       | N   |         | 主键（requestId）              | 接口导入记录主键，通常与一次 requestId 绑定，主要用于追踪这一批数据来自哪次请求。             |
| `schedule_version`     | varchar(20)  | N   |         | 排程版本号                      | 排产主版本号，标识一次完整排产任务；同一个版本下的输入数据会被一起计算。                       |
| `sub_schedule_version` | varchar(30)  | N   |         | 子排程版本号                     | 子排产版本号，用于区分同一主版本下的不同轮次、不同方案或重跑结果。                          |
| `line_id`              | bigint       | N   |         | 线体id                       | 线体唯一标识，是线体主数据、日历、UPH、限制规则和排产结果之间的主关联键。                     |
| `day`                  | date         | N   |         | 日期                         | 业务日期字段，一般表示某条线某个班次对应的自然日。                                  |
| `shift_seq`            | varchar(1)   | N   |         | 班序号                        | 班次序号，通常用于区分白班、夜班等班次。                                       |
| `model`                | varchar(5)   | N   |         | 五码Model                    | 五码机型，是线机匹配、UPH 匹配、换线和排序规则中最核心的产品属性之一。                      |
| `texture`              | varchar(100) |     |         | 属性                         | 产品属性或材质维度，用来区分更细粒度的产品差异。                                   |
| `fast_ship_flag`       | varchar(1)   |     |         | Fast Ship Flag             | 该字段的原始口径是“Fast Ship Flag”，通常用于补充该表的业务判断、过滤条件或展示属性。         |
| `cust_svc`             | varchar(1)   |     | 定制化flag |                            | 定制化订单标记，常用于 Cell 线优先、快单优先等柔性排产逻辑。                          |
| `priority`             | int          | N   |         | 优先级                        | UPH 记录优先级。当同一线体、班次、机型存在多条效率配置时，用它决定取哪条。                    |
| `transform_priority`   | int          | N   |         | 转换后的优先级；=priority          | 转换优先级或换型优先级，用于同一机型多条 UPH 记录冲突时的择优。                         |
| `uph_qty`              | int          | N   |         | UPH值                       | 单位小时产能，是把数量换算成占用工时的关键参数。                                   |
| `mcode`                | varchar(30)  | N   |         | BU、ShipmentType、Brand      | 业务分类键，通常同时承载 BU、ShipmentType、Brand 等信息，用于决定该需求或规则属于哪个业务口径。 |
| `mat_type`             | varchar(20)  |     |         | 物料类型（option type、sub type） | 材料或物料类型维度，用于更精细的产能匹配。                                      |

### 3.12 `aps_change_time_input`

- 中文名：排程换线时间 Input数据表
- 表用途：换线时间表，定义从一类产品切换到另一类产品时的额外耗时。
- 字段数：12

| 字段名                    | 类型          | 可空  | 默认值 | 原始备注                               | 业务理解                                                                   |
| ---------------------- | ----------- | --- | --- | ---------------------------------- | ---------------------------------------------------------------------- |
| `id`                   | bigint      | N   |     | 主键（requestId）                      | 接口导入记录主键，通常与一次 requestId 绑定，主要用于追踪这一批数据来自哪次请求。                         |
| `schedule_version`     | varchar(20) | N   |     | 排程版本号                              | 排产主版本号，标识一次完整排产任务；同一个版本下的输入数据会被一起计算。                                   |
| `sub_schedule_version` | varchar(30) | N   |     | 子排程版本号                             | 子排产版本号，用于区分同一主版本下的不同轮次、不同方案或重跑结果。                                      |
| `mcode`                | varchar(30) | N   |     | BU、ShipmentType、Brand              | 业务分类键，通常同时承载 BU、ShipmentType、Brand 等信息，用于决定该需求或规则属于哪个业务口径。             |
| `model_one`            | varchar(5)  |     |     | 五码Model                            | 换型规则中的起始机型。                                                            |
| `model_two`            | varchar(5)  |     |     | 五码Model                            | 换型规则中的目标机型。                                                            |
| `program_one`          | varchar(30) |     |     | Program                            | 换型规则中的起始 Program。                                                      |
| `program_two`          | varchar(30) |     |     | Program                            | 换型规则中的目标 Program。                                                      |
| `material_type_one`    | varchar(30) |     |     | 物料类型，Sub：SubType；Option：OptionType | 该字段的原始口径是“物料类型，Sub：SubType；Option：OptionType”，通常用于补充该表的业务判断、过滤条件或展示属性。 |
| `material_type_two`    | varchar(30) |     |     | 物料类型，Sub：SubType；Option：OptionType | 该字段的原始口径是“物料类型，Sub：SubType；Option：OptionType”，通常用于补充该表的业务判断、过滤条件或展示属性。 |
| `pu`                   | varchar(20) |     |     | 生产厂区                               | 该字段的原始口径是“生产厂区”，通常用于补充该表的业务判断、过滤条件或展示属性。                               |
| `change_time`          | int         | N   |     | 换线时间/min                           | 换线耗时，是估算换型损失和排程效率的重要输入。                                                |

### 3.13 `aps_change_model_input`

- 中文名：排程最优换线Model模型Input数据表
- 表用途：最优换型模型表，用于表达两个机型或 Program 之间的相似度、切换友好度。
- 字段数：11

| 字段名                    | 类型          | 可空  | 默认值 | 原始备注          | 业务理解                                           |
| ---------------------- | ----------- | --- | --- | ------------- | ---------------------------------------------- |
| `id`                   | bigint      | N   |     | 主键（requestId） | 接口导入记录主键，通常与一次 requestId 绑定，主要用于追踪这一批数据来自哪次请求。 |
| `schedule_version`     | varchar(20) | N   |     | 排程版本号         | 排产主版本号，标识一次完整排产任务；同一个版本下的输入数据会被一起计算。           |
| `sub_schedule_version` | varchar(30) | N   |     | 子排程版本号        | 子排产版本号，用于区分同一主版本下的不同轮次、不同方案或重跑结果。              |
| `line_id`              | bigint      | N   |     | 线体id          | 线体唯一标识，是线体主数据、日历、UPH、限制规则和排产结果之间的主关联键。         |
| `model_one`            | varchar(5)  |     |     | 五码Model1      | 换型规则中的起始机型。                                    |
| `model_two`            | varchar(5)  |     |     | 五码Model2      | 换型规则中的目标机型。                                    |
| `program_one`          | varchar(30) |     |     | Program1      | 换型规则中的起始 Program。                              |
| `program_two`          | varchar(30) |     |     | Program2      | 换型规则中的目标 Program。                              |
| `series_one`           | varchar(30) |     |     | Series1       | 换型规则中的起始系列。                                    |
| `series_two`           | varchar(30) |     |     | Series2       | 换型规则中的目标系列。                                    |
| `change_rate`          | int         | N   |     | 机型换线相似百分比     | 两个机型之间的相似度百分比，数值越高通常表示越容易切换。                   |

### 3.14 `aps_schedule_reserver_input`

- 中文名：排程预留Input数据表
- 表用途：产能预留表，直接在日历上切出一段时间不可用于正常排产。
- 字段数：9

| 字段名                    | 类型          | 可空  | 默认值 | 原始备注          | 业务理解                                           |
| ---------------------- | ----------- | --- | --- | ------------- | ---------------------------------------------- |
| `id`                   | bigint      | N   |     | 主键（requestId） | 接口导入记录主键，通常与一次 requestId 绑定，主要用于追踪这一批数据来自哪次请求。 |
| `schedule_version`     | varchar(20) | N   |     | 排程版本号         | 排产主版本号，标识一次完整排产任务；同一个版本下的输入数据会被一起计算。           |
| `sub_schedule_version` | varchar(30) | N   |     | 子排程版本号        | 子排产版本号，用于区分同一主版本下的不同轮次、不同方案或重跑结果。              |
| `reserved_id`          | varchar(20) | N   |     | 预留号           | 预留号，用于识别一段预留产能或预留任务。                           |
| `reserved_day`         | date        | N   |     | 预留天           | 预留发生的日期。                                       |
| `reserved_start_time`  | time        | N   |     | 预留开始时间        | 预留开始时间。                                        |
| `reserved_end_time`    | time        | N   |     | 预留结束时间        | 预留结束时间。                                        |
| `line_id`              | bigint      | N   |     | 预留线体          | 被预留掉的线体；这段时间内该线通常不能再安排普通需求。                    |
| `shift_seq`            | int         | N   |     | 班次序号          | 班次序号，通常用于区分白班、夜班等班次。                           |

### 3.15 `aps_schedule_limit_setting_input`

- 中文名：排程限制条件 Input数据表
- 表用途：限制条件配置表，用于配置机型、班次、线体、场景等限制规则。
- 字段数：10

| 字段名                    | 类型          | 可空  | 默认值 | 原始备注                                                                                     | 业务理解                                                       |
| ---------------------- | ----------- | --- | --- | ---------------------------------------------------------------------------------------- | ---------------------------------------------------------- |
| `id`                   | bigint      | N   |     | 主键（requestId）                                                                            | 接口导入记录主键，通常与一次 requestId 绑定，主要用于追踪这一批数据来自哪次请求。             |
| `schedule_version`     | varchar(20) | N   |     | 排程版本号                                                                                    | 排产主版本号，标识一次完整排产任务；同一个版本下的输入数据会被一起计算。                       |
| `sub_schedule_version` | varchar(30) | N   |     | 子排程版本号                                                                                   | 子排产版本号，用于区分同一主版本下的不同轮次、不同方案或重跑结果。                          |
| `mcode`                | varchar(30) | N   |     | BU、ShipmentType、Brand                                                                    | 业务分类键，通常同时承载 BU、ShipmentType、Brand 等信息，用于决定该需求或规则属于哪个业务口径。 |
| `group_id`             | int         | N   |     | 限制实例                                                                                     | 业务分组号，用于把一组相关规则、相关需求或相关排序条件归并在一起。                          |
| `limite_type`          | varchar(50) | N   |     | 限制类型（Color、Country、Material、Qty or Line、Scheduling Date、ASSY/SUB Shift、SUB/SUBSON Shift） | 限制规则的大类，决定这一组配置是在限制颜色、国家、数量、线体还是日期。                        |
| `type`                 | varchar(50) | N   |     | 条件类型：1、PO条件字段类型；2、限制条件字段类型；3、限制值字段类型                                                     | 这一行在限制配置中的角色，表示当前是在定义“筛选条件”“限制对象”还是“限制值”。                  |
| `condition_key`        | varchar(30) | N   |     | 字段名                                                                                      | 规则作用的字段名，也就是“拿哪个字段来判断”。                                    |
| `condition_value`      | varchar(10) | N   |     | 字段值                                                                                      | 规则判断值，也就是“字段要满足什么值”。                                       |
| `scene_type`           | varchar(10) | N   |     | 限制业务场景：0.Normal；1.Cell；2.MPS                                                             | 规则适用场景，如 Normal、Cell、MPS，用于按场景切换规则。                        |

### 3.16 `aps_schedule_order_ruler_input`

- 中文名：排程颜色材料项Input数据表
- 表用途：颜色/材料项排序规则表，用于定义同线同班内不同订单的排序偏好。
- 字段数：9

| 字段名                    | 类型          | 可空  | 默认值 | 原始备注                                              | 业务理解                                                       |
| ---------------------- | ----------- | --- | --- | ------------------------------------------------- | ---------------------------------------------------------- |
| `id`                   | bigint      | N   |     | 主键（requestId）                                     | 接口导入记录主键，通常与一次 requestId 绑定，主要用于追踪这一批数据来自哪次请求。             |
| `schedule_version`     | varchar(20) | N   |     | 排程版本号                                             | 排产主版本号，标识一次完整排产任务；同一个版本下的输入数据会被一起计算。                       |
| `sub_schedule_version` | varchar(30) | N   |     | 子排程版本号                                            | 子排产版本号，用于区分同一主版本下的不同轮次、不同方案或重跑结果。                          |
| `mcode`                | varchar(30) | N   |     | BU、ShipmentType、Brand                             | 业务分类键，通常同时承载 BU、ShipmentType、Brand 等信息，用于决定该需求或规则属于哪个业务口径。 |
| `line_id`              | bigint      | N   |     | 线体id                                              | 线体唯一标识，是线体主数据、日历、UPH、限制规则和排产结果之间的主关联键。                     |
| `model`                | varchar(5)  | N   |     | 五码Model                                           | 五码机型，是线机匹配、UPH 匹配、换线和排序规则中最核心的产品属性之一。                      |
| `group_id`             | varchar(5)  | N   |     | 组                                                 | 业务分组号，用于把一组相关规则、相关需求或相关排序条件归并在一起。                          |
| `condition_key`        | varchar(30) | N   |     | 字段名（kb、cover_assy、log_up_assy、pcba、thermal、color） | 规则作用的字段名，也就是“拿哪个字段来判断”。                                    |
| `priority`             | Int         | N   |     | color默认为0                                         | 排序优先级，数值用于决定材料项、颜色等在排产顺序中的先后。                              |

### 3.17 `aps_schedule_order_qty_setting_input`

- 中文名：排程大小单配置Input数据表
- 表用途：大小单配置表，用于定义某线体对小单/大单的处理策略。
- 字段数：7

| 字段名                    | 类型          | 可空  | 默认值 | 原始备注                              | 业务理解                                           |
| ---------------------- | ----------- | --- | --- | --------------------------------- | ---------------------------------------------- |
| `id`                   | bigint      | N   |     | 主键（requestId）                     | 接口导入记录主键，通常与一次 requestId 绑定，主要用于追踪这一批数据来自哪次请求。 |
| `schedule_version`     | varchar(20) | N   |     | 排程版本号                             | 排产主版本号，标识一次完整排产任务；同一个版本下的输入数据会被一起计算。           |
| `sub_schedule_version` | varchar(30) | N   |     | 子排程版本号                            | 子排产版本号，用于区分同一主版本下的不同轮次、不同方案或重跑结果。              |
| `line_id`              | bigint      | N   |     | 线体id                              | 线体唯一标识，是线体主数据、日历、UPH、限制规则和排产结果之间的主关联键。         |
| `model`                | varchar(5)  | N   |     | 五码model                           | 五码机型，是线机匹配、UPH 匹配、换线和排序规则中最核心的产品属性之一。          |
| `flag_type`            | varchar(1)  | N   |     | 配置类型：1、只可排产小单；2、可排产小单+大单；3、只可排产大单 | 大小单配置类型，用于定义这条线到底接小单、大单还是都接。                   |
| `small_qty`            | int         | N   |     | 小单数量                              | 小单阈值，用来判断需求是小单还是大单。                            |

### 3.18 `aps_schedule_priority_setting_input`

- 中文名：排程优先级配置表
- 表用途：需求优先级配置表，用于定义什么样的订单优先排。
- 字段数：12

| 字段名                    | 类型          | 可空  | 默认值 | 原始备注                                     | 业务理解                                                       |
| ---------------------- | ----------- | --- | --- | ---------------------------------------- | ---------------------------------------------------------- |
| `id`                   | bigint      | N   |     | 主键（requestId）                            | 接口导入记录主键，通常与一次 requestId 绑定，主要用于追踪这一批数据来自哪次请求。             |
| `schedule_version`     | varchar(20) | N   |     | 排程版本号                                    | 排产主版本号，标识一次完整排产任务；同一个版本下的输入数据会被一起计算。                       |
| `sub_schedule_version` | varchar(30) | N   |     | 子排程版本号                                   | 子排产版本号，用于区分同一主版本下的不同轮次、不同方案或重跑结果。                          |
| `mcode`                | varchar(30) | N   |     | BU、ShipmentType、Brand                    | 业务分类键，通常同时承载 BU、ShipmentType、Brand 等信息，用于决定该需求或规则属于哪个业务口径。 |
| `priority_group`       | varchar(4)  | N   |     | 优先级配置组                                   | 优先级组号，用于把多条优先规则组织成一个分组。                                    |
| `priority`             | int         | N   |     | 优先级                                      | 需求优先级顺位。通常越靠前越先排，但应以配置中心口径为准。                              |
| `first_priority_desc`  | varchar(30) | N   |     | 一级优先级描述、ROLLING MO特殊处理                   | 一级优先规则说明，用于让业务能读懂优先级配置。                                    |
| `second_priority_desc` | varchar(30) | N   |     | 二级优先级描述                                  | 二级优先规则说明，用于描述更细的排序逻辑。                                      |
| `condition_key`        | varchar(30) | N   |     | ATB眉头名称，条件字段                             | 规则作用的字段名，也就是“拿哪个字段来判断”。                                    |
| `condition_type`       | varchar(10) | N   |     | 条件类型：=，>,<…                              | 规则判断方式，如等于、大于、小于、区间等。                                      |
| `condition_value`      | varchar(30) | N   |     | 条件值                                      | 规则判断值，也就是“字段要满足什么值”。                                       |
| `kpi`                  | varchar(30) |     |     | 全局型目标：qtymax（订单数量最大化）， ordermax（订单笔数最大化） | 全局优化方向，例如最大化排产数量、最大化订单笔数等。                                 |

### 3.19 `aps_merge_priority_setting_input`

- 中文名：排产合并优先级设定Input表
- 表用途：需求合并优先级配置表，用于定义排程前如何按属性合并需求。
- 字段数：8

| 字段名                    | 类型          | 可空  | 默认值 | 原始备注                                   | 业务理解                                                       |
| ---------------------- | ----------- | --- | --- | -------------------------------------- | ---------------------------------------------------------- |
| `id`                   | bigint      | N   |     | 主键（requestId）                          | 接口导入记录主键，通常与一次 requestId 绑定，主要用于追踪这一批数据来自哪次请求。             |
| `schedule_version`     | varchar(20) | N   |     | 排程版本号                                  | 排产主版本号，标识一次完整排产任务；同一个版本下的输入数据会被一起计算。                       |
| `sub_schedule_version` | varchar(30) | N   |     | 子排程版本号                                 | 子排产版本号，用于区分同一主版本下的不同轮次、不同方案或重跑结果。                          |
| `mcode`                | varchar(30) | N   |     | BU、ShipmentType、Brand                  | 业务分类键，通常同时承载 BU、ShipmentType、Brand 等信息，用于决定该需求或规则属于哪个业务口径。 |
| `plant`                | varchar(30) | N   |     | 工厂                                     | 工厂代码，通常对应财务工厂或生产工厂口径。                                      |
| `priority`             | int         | N   |     | 合并优先级                                  | 优先级数值，通常数值越靠前代表越优先，但最终仍应以业务配置口径为准。                         |
| `priority_desc`        | varchar(30) | N   |     | 优先级描述：MTM属性合并/MTM合并/demand属性合并/颜色材料项合并 | 优先级规则的业务说明，用来解释这一条规则到底在排什么。                                |
| `code`                 | int         | N   |     | 优先级描述对应code                            | 规则编码或优先级编码，通常是给程序使用的内部标识。                                  |

### 3.20 `aps_schedule_merge_priority_setting_input`

- 中文名：排产合并demand需求排序优先级设定Input表
- 表用途：合并后需求的排序优先级配置表，用于定义合并后的 demand 进入排产时的排序逻辑。
- 字段数：12

| 字段名                    | 类型          | 可空  | 默认值 | 原始备注                  | 业务理解                                                       |
| ---------------------- | ----------- | --- | --- | --------------------- | ---------------------------------------------------------- |
| `id`                   | bigint      | N   |     | 主键（requestId）         | 接口导入记录主键，通常与一次 requestId 绑定，主要用于追踪这一批数据来自哪次请求。             |
| `schedule_version`     | varchar(20) | N   |     | 排程版本号                 | 排产主版本号，标识一次完整排产任务；同一个版本下的输入数据会被一起计算。                       |
| `sub_schedule_version` | varchar(30) | N   |     | 子排程版本号                | 子排产版本号，用于区分同一主版本下的不同轮次、不同方案或重跑结果。                          |
| `plant`                | varchar(30) | N   |     | 工厂                    | 工厂代码，通常对应财务工厂或生产工厂口径。                                      |
| `priority_group`       | varchar(4)  | N   |     | 排序Group组，自动生成：G001…   | 优先级组号，用于把多条优先规则组织成一个分组。                                    |
| `priority`             | int         | N   |     | 订单排序优先级               | 优先级数值，通常数值越靠前代表越优先，但最终仍应以业务配置口径为准。                         |
| `priority_desc`        | varchar(30) | N   |     | 排序描述                  | 优先级规则的业务说明，用来解释这一条规则到底在排什么。                                |
| `condition_key`        | varchar(30) | N   |     | demand眉头名称，条件字段       | 规则作用的字段名，也就是“拿哪个字段来判断”。                                    |
| `condition_type`       | varchar(10) | N   |     | 条件类型：=，>,<…           | 规则判断方式，如等于、大于、小于、区间等。                                      |
| `condition_value`      | varchar(30) | N   |     | 条件值                   | 规则判断值，也就是“字段要满足什么值”。                                       |
| `status`               | varchar(10) | N   |     | 状态：1.启用、0.不启用         | 状态字段，具体口径要结合所在表理解，可能表示齐套状态、启停状态或规则状态。                      |
| `mcode`                | varchar(30) | N   |     | BU、ShipmentType、Brand | 业务分类键，通常同时承载 BU、ShipmentType、Brand 等信息，用于决定该需求或规则属于哪个业务口径。 |

### 3.21 `aps_schedule_cycle_merge_setting_input`

- 中文名：Cell线优先级排序循环配置&线体内进行合并排序配置 input（CPC 项目新增）
- 表用途：Cell 线循环优先级与线体内合并排序配置表，主要服务小单、快单、定制化等柔性排产场景。
- 字段数：13

| 字段名                    | 类型          | 可空  | 默认值                     | 原始备注          | 业务理解                                                       |
| ---------------------- | ----------- | --- | ----------------------- | ------------- | ---------------------------------------------------------- |
| `id`                   | bigint      | N   |                         | 主键（requestId） | 接口导入记录主键，通常与一次 requestId 绑定，主要用于追踪这一批数据来自哪次请求。             |
| `schedule_version`     | varchar(20) | N   |                         | 排程版本号         | 排产主版本号，标识一次完整排产任务；同一个版本下的输入数据会被一起计算。                       |
| `sub_schedule_version` | varchar(30) | N   |                         | 子排程版本号        | 子排产版本号，用于区分同一主版本下的不同轮次、不同方案或重跑结果。                          |
| `mcode`                | varchar(30) | 是   | BU、ShipmentType、Brand   | Y             | 业务分类键，通常同时承载 BU、ShipmentType、Brand 等信息，用于决定该需求或规则属于哪个业务口径。 |
| `biz_type`             | varchar(10) | 是   | 业务类型，ASSY、Server、Option | Y             | 业务类型字段，用于区分 ASSY、Server、Option 等不同产品族。                     |
| `priority_type`        | varchar(10) | 是   | 配置类型                    | Y             | 配置类型字段，用于区分是 Cell 线循环优先还是线体内合并排序。                          |
| `line_type`            | varchar(30) |     | cell 线、非cell 线          | Y             | 线体类型，用于区分 normal 线、cell 线等不同排产模式。                          |
| `priority_group`       | varchar(4)  | 是   | 排序Group组，自动生成：G001…     | Y             | 优先级组号，用于把多条优先规则组织成一个分组。                                    |
| `priority`             | int         | 是   | 订单排序优先级                 | Y             | Cell 线循环规则或合并排序规则里的顺位值。                                    |
| `priority_desc`        | varchar(30) | 是   | 排序描述                    | Y             | 优先级规则的业务说明，用来解释这一条规则到底在排什么。                                |
| `condition_key`        | varchar(30) |     | 条件字段                    | Y             | 业务场景条件键。这里往往不是简单字段名，而是一个被系统约定好的场景标签。                       |
| `condition_type`       | varchar(10) |     | 条件类型：=，>,<…             |               | 规则判断方式，如等于、大于、小于、区间等。                                      |
| `condition_value`      | varchar(30) |     | 条件值                     |               | 与场景条件键配套的阈值或匹配值，例如大小单阈值。                                   |

## 4. 建议优先理解的关键字段

如果你是第一次接触这套 APS 输入数据，最建议先建立下面这几条主线：

- 版本主线：`schedule_version`、`sub_schedule_version`。这两个字段决定“这一批数据属于哪次排产”。
- 需求主线：`demand_id`。这是需求跨表关联的核心键。
- 资源主线：`line_id`、`day`、`shift_seq`。这三个字段决定需求被排到哪条线、哪天、哪个班。
- 产品主线：`pn`、`model`、`program`、`series`、`color`。这组字段决定产品属性、线机匹配和换线难度。
- 交付主线：`mr_day`、`fpsd`、`ots_date`、`ship_date`。这组字段决定需求什么时候能排、应该优先排谁。
- 特殊约束主线：`fix_flag`、FAI 表、FIX 表、限制条件表、预留表。它们决定“不是所有需求都能自由优化”。

## 5. 结论

从输入表结构可以看出，BOX APS 已经不是简单的“订单 + 产线”排程，而是一套比较成熟的规则驱动排产体系。

它的输入至少分成六层：

- 产品主数据
- 需求主数据
- 特殊需求与锁定规则
- 线体与班次日历
- 产能与换线配置
- 排序、优先级、大小单、Cell线等规则配置

因此，理解字段时最重要的不是孤立看单个字段，而是看它属于哪一层、它会影响“可不可排”“排到哪里”还是“谁先排”。
