# APS系统数据表目录：表名到表格作用对应关系

## 1. 说明

本文基于 `APS系统数据表目录.xlsx` 中的“数据表目录”工作表整理。  
与原目录表相比，这里对“表格作用”做了扩充，重点补充每张表在排程链路中的实际用途，包括：

- 这张表是主数据、需求数据、资源数据，还是规则配置数据
- 它主要解决什么业务问题
- 它通常和哪些表一起使用

## 2. 输入表

| 表名                                          | 中文名                              | 表格作用（扩充版）                                                                                                          |
| ------------------------------------------- | -------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `aps_schedule_master_pn_input`              | 排程物料主数据Input表                    | 产品主数据表。用于定义成品料号 `pn` 对应的机型、系列、Program、颜色、属性等静态信息。它本身不直接决定先排谁，但会影响线体匹配、UPH 匹配、换线规则、颜色/材料项排序等多个环节，是所有需求识别的基础字典表。     |
| `aps_schedule_demand_base_input`            | 排程Demand基础数据Input表               | 需求主表，是整个排程最核心的输入表。待生产订单、工单或拆分后的排程对象基本都从这里进入模型。它提供数量、齐套日期、交期、优先级、紧急标记、快单标记、定制化标记、材料项属性等关键信息，决定“哪些订单要排、什么时候能排、谁更优先”。 |
| `aps_schedule_demand_expand_input`          | 排程Demand拓展数据Input表               | 需求补充属性表，用来存放基础需求表中没有展开的流程性或状态性信息，比如是否需要 FAI、是否已开工单、是否存在特殊阻断等。它通常不是主排序来源，但会影响某些特殊业务规则是否生效。                          |
| `aps_schedule_demand_fai_input`             | 排程Demand FAI Input数据表            | FAI/FOT/RPQ 等特殊验证需求表。它的作用不是描述普通订单，而是描述“同一组需求之间的先后关系和等待关系”，例如首件先做、首件后等待一定时间、验证通过后才能继续做后续数量。                         |
| `aps_schedule_demand_fix_input`             | 排程Demand Fix Input数据表            | 需求固定排产表，用于表达业务已经明确指定的排程安排，例如某个订单必须在某天、某班、某条线、某个顺序生产。它代表的是“业务强约束”，不是普通优化偏好。                                         |
| `aps_schedule_demand_reserve_input`         | 排程预留Demand Input数据表              | 预留需求表。它不是普通客户订单，而是把部分产能以“需求”的形式预先占住，避免这部分产能被正常排程占用。它更多服务于特殊业务、插单、测试、保留窗口等场景。                                       |
| `aps_schedule_line_input`                   | 排程线体Input数据表                     | 线体主数据表，用于定义有哪些线体可参与排程，以及每条线的基本属性，比如线名、线体类型、开线类型、厂区、是否按 Rolling MO 口径占产能等。它回答的是“有哪些资源可用”。                           |
| `aps_schedule_line_calendar_input`          | 排程线体日历Input数据表                   | 线体班次日历表，用于定义每条线在每天每个班次是否开班、班次开始结束时间是什么、该班是否允许排普通订单、是否带有 FIX 属性等。它回答的是“这条线在这个时间点能不能排”。                              |
| `aps_schedule_off_time_input`               | 排程线体off Time Input数据表            | 线体停机时间表，用于记录休息、吃饭、维护等班内不可生产时段。它通常与线体日历一起使用，把“整班可用时间”进一步扣减成“净可排时间”。                                                 |
| `aps_schedule_uph_input`                    | 排程UPH Input数据表                   | 产能效率表。用于定义某机型在某条线、某一天、某个班次下的单位小时产出能力。因为同一机型在不同线体、班次、业务条件下速度可能不同，所以这张表直接决定“同样一批订单放在线 A 和线 B 上，产能占用会不会一样”。           |
| `aps_change_time_input`                     | 排程换线时间 Input数据表                  | 换线时间表，用于定义不同产品切换时的额外耗时。它影响的是排程效率和顺序优化，例如同线同班内是否要减少机型切换、Program 切换或物料类型切换。                                          |
| `aps_change_model_input`                    | 排程最优换线Model模型Input数据表            | 机型切换友好度表，用于表达两个机型、Program 或系列之间的相似程度。它通常不直接决定“能不能排”，而是服务于“怎么排更顺、更少损失”的效率优化。                                        |
| `aps_schedule_reserver_input`               | 排程预留Input数据表                     | 产能预留表，用于直接在某条线、某一天、某个班次、某个时间段上切出预留窗口。与预留需求表不同，这张表是从资源侧限制产能，回答的是“这段产能不能给普通订单用”。                                     |
| `aps_schedule_limit_setting_input`          | 排程限制条件 Input数据表                  | 业务限制规则配置表。用于定义机型、国家、材料项、数量、线体、班次、场景等限制条件。它的作用是把“哪些订单只能上哪些线、哪些班、哪些场景”配置化，而不是写死在程序里。                                 |
| `aps_schedule_order_ruler_input`            | 排程颜色材料项Input数据表                  | 班内排序规则表。用于定义同一条线、同一个机型条件下，不同颜色或材料项（如 KB、PCBA、Cover Assy、Thermal 等）在顺序上的优先关系，目标是减少切换损失、让生产更顺。                       |
| `aps_schedule_order_qty_setting_input`      | 排程大小单配置Input数据表                  | 大小单规则表，用于定义某条线对小单、大单的处理策略，例如某线只接小单、某线大小单都能接、某线只接大单。它经常和 Cell 线规则一起决定订单分配方向。                                        |
| `aps_schedule_priority_setting_input`       | 排程优先级配置表                         | 需求优先级配置表。用于把业务里“什么订单更应该先排”做成规则化配置，例如 Pre-Lock、Urgent、OTS 临近、FPSD 临近、D+2 出货等。它是订单先后顺序的重要来源之一。                       |
| `aps_merge_priority_setting_input`          | 排产合并优先级设定Input表                  | 需求合并优先级表。用于定义正式排程前，订单应先按哪些属性合并，例如先按产品属性合并、再按需求属性合并、再按颜色材料项合并等。它影响的是排程前的“颗粒度整理”。                                    |
| `aps_schedule_merge_priority_setting_input` | 排产合并demand需求排序优先级设定Input表        | 合并后需求排序规则表。它承接“需求已经合并完成”之后的排序逻辑，用于定义这些合并后的排程对象应该按什么条件继续排先后。                                                        |
| `aps_schedule_cycle_merge_setting_input`    | Cell线优先级排序循环配置&线体内进行合并排序配置 input | Cell 线和柔性线专用规则表。它通常用于快单、小单、定制化订单在 Cell 线上的优先策略，以及线体内循环排序或合并排序规则。它服务的是“柔性资源怎么用得更合理”。                                |
| `aps_adjust_schedule_input`                 | APS调整排程Input数据表                  | 调整排程输入表，通常代表上一轮结果、人工指定结果或需要继承的已定安排。它更多反映“已有安排”，用于在新一轮排程时保留、继承或局部调整，而不是从零开始重新排。                                     |

## 3. 输出表

| 表名                           | 中文名              | 表格作用（扩充版）                                                           |
| ---------------------------- | ---------------- | ------------------------------------------------------------------- |
| `aps_adjust_schedule_output` | APS调整排程Output数据表 | 业务侧最直观的排程结果表。通常记录某个需求最终被安排到哪条线、哪天、哪个班、排了多少、顺序是多少，适合给业务、系统接口或前台页面消费。 |
| `aps_schedule_change_line`   | 排程换线次数记录表        | 线体换线统计表，用于记录每条线每天每班发生了多少次换线。它主要服务于效率评估、方案优劣比较，以及“排程是否过于碎片化”的分析。     |
| `aps_schedule_result`        | 排程结果表            | 更底层、更细粒度的结果表。除了正式生产块外，它往往还会记录休息、停机、换线、预留等时间块，用于还原整条线在整个班次内的实际时间安排。  |
| `aps_schedule_runtime_log`   | 排程执行状态           | 排程运行日志表，用于记录排程过程中的开始时间、结束时间、阶段状态、异常信息等。它主要服务于运行监控、问题排查和失败原因追溯。      |

## 4. 如何理解这张目录表

如果从业务角度看，这张目录表其实可以分成 5 层：

1. 产品与需求层  
   解决“要排什么”
- `aps_schedule_master_pn_input`
- `aps_schedule_demand_base_input`
- `aps_schedule_demand_expand_input`
- `aps_schedule_demand_fai_input`
- `aps_schedule_demand_fix_input`
- `aps_schedule_demand_reserve_input`
2. 资源与日历层  
   解决“在哪里排、什么时候能排”
- `aps_schedule_line_input`
- `aps_schedule_line_calendar_input`
- `aps_schedule_off_time_input`
- `aps_schedule_reserver_input`
3. 产能与效率层  
   解决“排这单要占多少产能、怎么排更顺”
- `aps_schedule_uph_input`
- `aps_change_time_input`
- `aps_change_model_input`
4. 业务规则层  
   解决“谁优先、谁受限制、如何排序、何时合并”
- `aps_schedule_limit_setting_input`
- `aps_schedule_order_ruler_input`
- `aps_schedule_order_qty_setting_input`
- `aps_schedule_priority_setting_input`
- `aps_merge_priority_setting_input`
- `aps_schedule_merge_priority_setting_input`
- `aps_schedule_cycle_merge_setting_input`
5. 结果与执行层  
   解决“最终排成什么样、过程是否成功”
- `aps_adjust_schedule_input`
- `aps_adjust_schedule_output`
- `aps_schedule_change_line`
- `aps_schedule_result`
- `aps_schedule_runtime_log`

# 
