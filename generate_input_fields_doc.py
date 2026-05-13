import os
import re
import zipfile
import xml.etree.ElementTree as ET

NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "docrel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}

MARK_TABLE = "数据表名"
MARK_CN = "数据表中文名称"


TABLE_DESC = {
    "aps_schedule_master_pn_input": "物料与机型主数据表，用于定义料号对应的机型、系列、Program、颜色等静态属性，是需求识别和线机匹配的基础。",
    "aps_schedule_demand_base_input": "需求主表。所有待排需求基本都从这里进入，是交付、优先级、物料齐套和数量计算的核心来源。",
    "aps_schedule_demand_expand_input": "需求扩展属性表，用于补充基础需求表中没有直接展开的流程型或状态型属性。",
    "aps_schedule_demand_fai_input": "FAI/FOT/RPQ 等首件或特殊验证需求表，用于表达同组需求的先后关系和最小间隔。",
    "aps_schedule_demand_fix_input": "需求固定排产表，用于表达业务已经指定到某天、某班、某线、某顺序的需求。",
    "aps_schedule_demand_reserve_input": "预留需求表，用于表达不是普通订单、而是为了占用或预留产能而建立的需求对象。",
    "aps_adjust_schedule_input": "人工调整排程输入表，通常代表前一轮排程结果或人工指定结果，供本轮排程继承、调整或锁定。",
    "aps_schedule_line_input": "线体主数据表，定义有哪些线、线体类型、开线类型等。",
    "aps_schedule_line_calendar_input": "线体班次日历表，定义每条线在每天每个班次是否开班、开班时间是什么。",
    "aps_schedule_off_time_input": "线体停机时间表，用于扣减休息、吃饭、维护等不可生产时段。",
    "aps_schedule_uph_input": "UPH 产能表，定义机型在特定线体、日期、班次上的单位小时产出能力。",
    "aps_change_time_input": "换线时间表，定义从一类产品切换到另一类产品时的额外耗时。",
    "aps_change_model_input": "最优换型模型表，用于表达两个机型或 Program 之间的相似度、切换友好度。",
    "aps_schedule_reserver_input": "产能预留表，直接在日历上切出一段时间不可用于正常排产。",
    "aps_schedule_limit_setting_input": "限制条件配置表，用于配置机型、班次、线体、场景等限制规则。",
    "aps_schedule_order_ruler_input": "颜色/材料项排序规则表，用于定义同线同班内不同订单的排序偏好。",
    "aps_schedule_order_qty_setting_input": "大小单配置表，用于定义某线体对小单/大单的处理策略。",
    "aps_schedule_priority_setting_input": "需求优先级配置表，用于定义什么样的订单优先排。",
    "aps_merge_priority_setting_input": "需求合并优先级配置表，用于定义排程前如何按属性合并需求。",
    "aps_schedule_merge_priority_setting_input": "合并后需求的排序优先级配置表，用于定义合并后的 demand 进入排产时的排序逻辑。",
    "aps_schedule_cycle_merge_setting_input": "Cell 线循环优先级与线体内合并排序配置表，主要服务小单、快单、定制化等柔性排产场景。",
}


COMMON = {
    "id": "接口导入记录主键，通常与一次 requestId 绑定，主要用于追踪这一批数据来自哪次请求。",
    "schedule_version": "排产主版本号，标识一次完整排产任务；同一个版本下的输入数据会被一起计算。",
    "sub_schedule_version": "子排产版本号，用于区分同一主版本下的不同轮次、不同方案或重跑结果。",
    "create_by": "创建人或创建来源，常用于审计数据来源是系统任务、人工维护还是接口同步。",
    "create_time": "创建时间，用于审计和排查数据导入先后顺序。",
    "modify_by": "最后修改人或修改来源。",
    "modify_time": "最后修改时间。",
    "remark": "备注字段，通常用于补充说明异常原因、业务解释或接口回传信息。",
    "mcode": "业务分类键，通常同时承载 BU、ShipmentType、Brand 等信息，用于决定该需求或规则属于哪个业务口径。",
    "demand_id": "需求唯一标识，是需求主表、FAI、FIX、人工调整等多张表之间的核心关联键。",
    "pn": "成品料号或物料号，是识别具体产品配置的核心字段。",
    "model": "五码机型，是线机匹配、UPH 匹配、换线和排序规则中最核心的产品属性之一。",
    "series": "系列信息，用于归类相似机型，也常被用于换型相似度或规则过滤。",
    "program": "Program 属性，通常与产品平台或程序版本相关，也会影响换线、匹配与排序。",
    "texture": "产品属性或材质维度，用来区分更细粒度的产品差异。",
    "color": "颜色属性，常用于颜色切换、合并排序或业务偏好排序。",
    "line_id": "线体唯一标识，是线体主数据、日历、UPH、限制规则和排产结果之间的主关联键。",
    "line": "线体名称或线别简称，是业务现场识别产线的展示字段。",
    "line_type": "线体类型，用于区分 normal 线、cell 线等不同排产模式。",
    "day": "业务日期字段，一般表示某条线某个班次对应的自然日。",
    "shift_seq": "班次序号，通常用于区分白班、夜班等班次。",
    "shift_start_time": "班次开始时间。",
    "shift_end_time": "班次结束时间。",
    "start_time": "某段停机、预留或任务的开始时间。",
    "end_time": "某段停机、预留或任务的结束时间。",
    "qty": "当前需求行需要排产的数量。",
    "ord_qty": "原始订单总数量，用来表示该订单全量规模。",
    "line_qty": "当前计划在生产侧实际安排的数量，通常用于区分订单总量和本次可排量。",
    "schedule_qty": "当前记录对应的已排数量或计划数量。",
    "fix_qty": "业务指定必须固定排入的数量。",
    "priority": "优先级数值，通常数值越靠前代表越优先，但最终仍应以业务配置口径为准。",
    "priority_group": "优先级组号，用于把多条优先规则组织成一个分组。",
    "priority_desc": "优先级规则的业务说明，用来解释这一条规则到底在排什么。",
    "group_id": "业务分组号，用于把一组相关规则、相关需求或相关排序条件归并在一起。",
    "condition_key": "规则作用的字段名，也就是“拿哪个字段来判断”。",
    "condition_type": "规则判断方式，如等于、大于、小于、区间等。",
    "condition_value": "规则判断值，也就是“字段要满足什么值”。",
    "status": "状态字段，具体口径要结合所在表理解，可能表示齐套状态、启停状态或规则状态。",
    "type": "类型字段，具体口径依赖所在表，通常用来区分不同业务子类型。",
    "plant": "工厂代码，通常对应财务工厂或生产工厂口径。",
    "pu_site": "厂区或园区位置，用于区分不同生产园区或站点。",
    "mo": "制造工单号，是把需求与实际生产执行对象关联起来的关键字段。",
    "lot": "Lot 批次号，用于批次级追踪与排产。",
    "mr_day": "物料齐套日期，在这一天之前通常不允许正式投产。",
    "demand_type": "需求类型，用于区分 MR、OPEN MO、LOT、预留等不同来源的需求。",
    "fg_ready_day": "成品可就绪日期，可视为供交付评估或节奏判断的一个时间点。",
    "total_index": "业务整体优先顺序号，常被用作订单优先级或排序参考。",
    "pre_plan": "预排标记，表示这条需求是否带有预排计划属性。",
    "pre_lock": "预锁标记，表示这条需求在排产时优先保持既定安排。",
    "om_urgent": "紧急订单标记，通常代表交付压力更高，应优先保障。",
    "fpsd": "FPSD 交付相关日期，是优先级和达成率评估的重要输入。",
    "rersd": "另一类交付参考日期，通常用于需求承诺或回推节奏判断。",
    "ots_date": "OTS 目标日期，是交付达成的重要考核时间点。",
    "ship_date": "客户或业务要求的出货日期。",
    "ship_day_two": "D+2 出货相关日期字段，常用于识别临近出货需求。",
    "prs_date": "业务流程日期，通常是订单处理或 TDN 相关时间点。",
    "country": "国家字段，常用于限制规则或交付优先级细分。",
    "priority_code": "优先级编码，通常来自前置业务系统。",
    "pending_pool": "缓冲池标记，表示需求是否暂时进入待排缓冲池。",
    "fast_ship": "快出货标记，通常意味着更高交付优先级，且更适合柔性线处理。",
    "eop": "EOP 相关业务标识，通常用于识别生命周期或特殊业务状态。",
    "material_type": "物料类型字段，用于区分 Sub、Option 等业务物料类别。",
    "create_mo_flag": "是否已开立 MO 的标记，影响需求是否还需要继续开单或重新排产。",
    "kb": "键盘类物料属性，用于排序、合并或物料切换规则。",
    "cover_assy": "Cover Assy 物料属性，用于排序、合并或物料切换规则。",
    "log_up_assy": "Log Up Assy 物料属性，用于排序、合并或物料切换规则。",
    "pcba": "PCBA 物料属性，用于排序、合并或物料切换规则。",
    "thermal": "散热件物料属性，用于排序、合并或物料切换规则。",
    "material_sections": "材料项集合，通常以 JSON 形式记录更多材料属性，便于配置化扩展。",
    "tie_order": "绑单标记，表示该需求需要与其他需求一起考虑，不宜随意拆散。",
    "vat_invno": "PO Flag 或税务/单据相关标识，常被业务拿来做订单分组识别。",
    "dc": "大区或区域字段，常用于业务分群或优先级细分。",
    "fast_ship_51j_status": "Fast Ship 场景下首个 IPS/51J 流程状态，用于判断是否满足快单推进条件。",
    "fast_ship_ots_date": "Fast Ship 场景下单独维护的 OTS 日期。",
    "ips_id": "IPS 流程单号或识别号。",
    "fix_flag": "是否存在 FIX 约束的标记；为 1 时通常需要去 FIX 表读取更细的锁定规则。",
    "z_type": "产品子类型字段，常用于区分 Option Type、Sub Type 等更细分物料类别。",
    "shift_end_flag": "跨班次标记，表示该需求在产能计算或细排时是否允许跨班结束。",
    "cust_svc": "定制化订单标记，常用于 Cell 线优先、快单优先等柔性排产逻辑。",
    "men_number": "业务附加编号字段，通常用于来源系统追溯或人工识别。",
    "c_or_p": "齐套类型标记，表示 Complete 还是 Partial，用于判断是否允许投产。",
    "create_mo": "是否需要开立工单的标记。",
    "need_fai": "是否需要 FAI 首件验证的标记。",
    "hold_log": "是否存在 Hold 相关日志或阻断信息。",
    "xn_hub_store": "与 Hub/Store 相关的补充属性，通常来自其他业务表扩展。",
    "group_first": "在分组需求中是否属于需要优先投产的那一条。",
    "lead_time": "最小间隔时间，常用于表达首件完成后其余需求才能继续投入的等待窗口。",
    "fix_day": "业务指定的固定排产日期。",
    "fix_shift": "业务指定的固定班次。",
    "fix_line": "业务指定的固定线体。",
    "fix_line_id": "业务指定的固定线体。",
    "fix_sequence": "业务指定的固定顺序号。",
    "fix_seq": "业务指定的固定顺序号。",
    "fix_type": "FIX 的类型标记，用来区分是整单固定、部分固定还是其他业务变体。",
    "reserved_id": "预留号，用于识别一段预留产能或预留任务。",
    "reserved_day": "预留发生的日期。",
    "reserved_start_time": "预留开始时间。",
    "reserved_end_time": "预留结束时间。",
    "schedule_line_version": "线体版本号，用于标识线体配置快照版本。",
    "rolling_flag": "是否参与滚动排程的标记。",
    "open_type": "线体开线类型或组织类型，常用于区分大线、小线、特殊线等。",
    "shift_status": "班次状态，常见口径为 ON/OFF，用于判断该班是否可以生产。",
    "non_merge_flag": "不可合并标记，表示该班次或时间块内不能做合并排产。",
    "demand_flag": "是否允许安排正常需求的标记。",
    "off_type": "停机类型，如休息、吃饭、维护等。",
    "uph_qty": "单位小时产能，是把数量换算成占用工时的关键参数。",
    "transform_priority": "转换优先级或换型优先级，用于同一机型多条 UPH 记录冲突时的择优。",
    "mat_type": "材料或物料类型维度，用于更精细的产能匹配。",
    "change_time": "换线耗时，是估算换型损失和排程效率的重要输入。",
    "model_one": "换型规则中的起始机型。",
    "model_two": "换型规则中的目标机型。",
    "program_one": "换型规则中的起始 Program。",
    "program_two": "换型规则中的目标 Program。",
    "series_one": "换型规则中的起始系列。",
    "series_two": "换型规则中的目标系列。",
    "change_rate": "两个机型之间的相似度百分比，数值越高通常表示越容易切换。",
    "limite_type": "限制规则的大类，决定这一组配置是在限制颜色、国家、数量、线体还是日期。",
    "scene_type": "规则适用场景，如 Normal、Cell、MPS，用于按场景切换规则。",
    "flag_type": "大小单配置类型，用于定义这条线到底接小单、大单还是都接。",
    "small_qty": "小单阈值，用来判断需求是小单还是大单。",
    "first_priority_desc": "一级优先规则说明，用于让业务能读懂优先级配置。",
    "second_priority_desc": "二级优先规则说明，用于描述更细的排序逻辑。",
    "kpi": "全局优化方向，例如最大化排产数量、最大化订单笔数等。",
    "priority_type": "配置类型字段，用于区分是 Cell 线循环优先还是线体内合并排序。",
    "biz_type": "业务类型字段，用于区分 ASSY、Server、Option 等不同产品族。",
    "code": "规则编码或优先级编码，通常是给程序使用的内部标识。",
    "procd": "产品代码或产品族代码，用于区分具体业务产品大类。",
    "dnno": "订单号，是需求在业务订单层面的主标识。",
    "dndnline": "订单号与订单行的组合键或扩展行号，常用于唯一识别订单行。",
    "dnline": "订单行号。",
}


SPECIFIC = {
    ("aps_schedule_demand_fix_input", "fix_type"): "FIX 类型字段，用于说明这条 FIX 是按天班线锁定、按顺序锁定，还是其他固定方式。",
    ("aps_schedule_demand_fai_input", "type"): "FAI/FOT/RPQ 类型，用于区分这是首件验证、首单试产还是其他特殊验证场景。",
    ("aps_schedule_line_calendar_input", "fix_type"): "班次固定属性，常用于表示该班次是否已被固定计划占用或带有特定约束。",
    ("aps_schedule_uph_input", "priority"): "UPH 记录优先级。当同一线体、班次、机型存在多条效率配置时，用它决定取哪条。",
    ("aps_schedule_order_ruler_input", "priority"): "排序优先级，数值用于决定材料项、颜色等在排产顺序中的先后。",
    ("aps_schedule_limit_setting_input", "type"): "这一行在限制配置中的角色，表示当前是在定义“筛选条件”“限制对象”还是“限制值”。",
    ("aps_schedule_priority_setting_input", "priority"): "需求优先级顺位。通常越靠前越先排，但应以配置中心口径为准。",
    ("aps_schedule_cycle_merge_setting_input", "priority"): "Cell 线循环规则或合并排序规则里的顺位值。",
    ("aps_schedule_cycle_merge_setting_input", "condition_key"): "业务场景条件键。这里往往不是简单字段名，而是一个被系统约定好的场景标签。",
    ("aps_schedule_cycle_merge_setting_input", "condition_value"): "与场景条件键配套的阈值或匹配值，例如大小单阈值。",
    ("aps_schedule_reserver_input", "line_id"): "被预留掉的线体；这段时间内该线通常不能再安排普通需求。",
    ("aps_adjust_schedule_input", "schedule_seq"): "人工调整后的排程顺序号，用于指定在线体班次内的先后。",
    ("aps_adjust_schedule_input", "schedule_day"): "人工调整后指定的排产日期。",
    ("aps_adjust_schedule_input", "shift_seq"): "人工调整后指定的排产班次。",
}


TABLE_GROUP_HINT = {
    "aps_schedule_master_pn_input": "产品主数据",
    "aps_schedule_demand_base_input": "需求主数据",
    "aps_schedule_demand_expand_input": "需求扩展",
    "aps_schedule_demand_fai_input": "特殊需求规则",
    "aps_schedule_demand_fix_input": "特殊需求规则",
    "aps_schedule_demand_reserve_input": "特殊需求规则",
    "aps_adjust_schedule_input": "人工调整输入",
    "aps_schedule_line_input": "资源主数据",
    "aps_schedule_line_calendar_input": "资源日历",
    "aps_schedule_off_time_input": "资源日历",
    "aps_schedule_uph_input": "产能配置",
    "aps_change_time_input": "换线配置",
    "aps_change_model_input": "换线配置",
    "aps_schedule_reserver_input": "产能预留",
    "aps_schedule_limit_setting_input": "规则配置",
    "aps_schedule_order_ruler_input": "规则配置",
    "aps_schedule_order_qty_setting_input": "规则配置",
    "aps_schedule_priority_setting_input": "规则配置",
    "aps_merge_priority_setting_input": "规则配置",
    "aps_schedule_merge_priority_setting_input": "规则配置",
    "aps_schedule_cycle_merge_setting_input": "规则配置",
}


def col_to_num(col: str) -> int:
    n = 0
    for ch in col:
        if "A" <= ch <= "Z":
            n = n * 26 + (ord(ch) - 64)
    return n


def get_text(si):
    return "".join(t.text or "" for t in si.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t"))


def find_catalog(base: str) -> str:
    for name in os.listdir(base):
        if name.endswith(".xlsx") and not name.startswith("~$") and not name.startswith("BOX"):
            return os.path.join(base, name)
    raise FileNotFoundError("catalog xlsx not found")


def read_sheet_by_index(path: str, sheet_index: int):
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            shared = [get_text(si) for si in root.findall("main:si", NS)]

        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        rid_to_target = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels.findall("rel:Relationship", NS)}

        sheet = wb.find("main:sheets", NS)[sheet_index]
        rid = sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
        target = rid_to_target[rid]
        if not target.startswith("xl/"):
            target = "xl/" + target

        root = ET.fromstring(z.read(target))
        rows = []
        max_col = 0

        for row in root.find("main:sheetData", NS).findall("main:row", NS):
            vals = {}
            for c in row.findall("main:c", NS):
                ref = c.attrib.get("r", "")
                m = re.match(r"([A-Z]+)(\d+)", ref)
                if not m:
                    continue
                col = col_to_num(m.group(1))
                max_col = max(max_col, col)
                cell_type = c.attrib.get("t")
                v = c.find("main:v", NS)
                value = ""
                if cell_type == "s" and v is not None and v.text is not None:
                    idx = int(v.text)
                    value = shared[idx] if idx < len(shared) else v.text
                elif cell_type == "inlineStr":
                    t = c.find("main:is/main:t", NS)
                    value = t.text if t is not None else ""
                elif v is not None:
                    value = v.text or ""
                vals[col] = value.strip()
            rows.append([vals.get(i, "") for i in range(1, max_col + 1)])
        return rows


def parse_tables(rows):
    tables = []
    i = 0
    while i < len(rows):
        row = rows[i]
        if len(row) >= 2 and row[0] == MARK_TABLE and row[1]:
            table_name = row[1]
            cn_name = rows[i + 1][1] if i + 1 < len(rows) and len(rows[i + 1]) > 1 and rows[i + 1][0] == MARK_CN else ""
            j = i + 3
            fields = []
            while j < len(rows):
                r = rows[j]
                if len(r) >= 2 and r[0] == MARK_TABLE and r[1]:
                    break
                if any(cell for cell in r[:6]):
                    fields.append(
                        {
                            "field": r[0] if len(r) > 0 else "",
                            "type": r[1] if len(r) > 1 else "",
                            "nullable": r[2] if len(r) > 2 else "",
                            "default": r[3] if len(r) > 3 else "",
                            "unique": r[4] if len(r) > 4 else "",
                            "remark": r[5] if len(r) > 5 else "",
                        }
                    )
                j += 1
            tables.append({"table": table_name, "cn_name": cn_name, "fields": fields})
            i = j
        else:
            i += 1
    return tables


def explain(table: str, field: str, remark: str) -> str:
    if (table, field) in SPECIFIC:
        return SPECIFIC[(table, field)]
    if field in COMMON:
        return COMMON[field]
    if remark:
        return f"该字段的原始口径是“{remark}”，通常用于补充该表的业务判断、过滤条件或展示属性。"
    if field.endswith("_id"):
        return "这是一个业务主键或关联键，用于把当前表与其他主数据、需求表或结果表关联起来。"
    if field.endswith("_date") or field.endswith("_day"):
        return "这是一个日期类字段，通常用于交期判断、排产窗口判断或业务节点控制。"
    if field.endswith("_time"):
        return "这是一个时间类字段，通常用于计算可用时间窗、顺序先后或停机区间。"
    if "flag" in field:
        return "这是一个标记类字段，通常用于控制是否启用某条规则或识别某类特殊业务。"
    if "priority" in field:
        return "这是一个优先级相关字段，用于控制排序、择优或规则先后。"
    return "该字段是当前业务对象的补充属性，建议结合同表其他字段和具体排产规则一起理解。"


def esc(s: str) -> str:
    return (s or "").replace("|", "\\|").replace("\n", "<br>")


def main():
    base = r"D:\box-aps"
    path = find_catalog(base)
    rows = read_sheet_by_index(path, 1)
    tables = parse_tables(rows)

    out = []
    out.append("# BOX APS输入表字段业务说明")
    out.append("")
    out.append("## 1. 文档目的")
    out.append("")
    out.append("本文基于 `APS系统数据表目录.xlsx` 中的 `BOX输入表` 工作表整理，目标是把每张输入表的每个字段翻译成更容易理解的业务语言。")
    out.append("")
    out.append("阅读方式建议：")
    out.append("")
    out.append("- 先看“表用途”，理解这张表在排产链路里扮演什么角色。")
    out.append("- 再看字段级说明，重点关注哪些字段用于需求识别、哪些字段用于约束、哪些字段用于排序与优先级。")
    out.append("- 对于同名字段，如 `schedule_version`、`demand_id`、`line_id`，可以跨表对照理解。")
    out.append("")
    out.append("说明：")
    out.append("")
    out.append("- “原始备注”来自 Excel。")
    out.append("- “业务理解”是在原始备注基础上，结合排产场景补充的解释。")
    out.append("- 若个别字段在原始文档中备注较短，本文会按主板/装配类 APS 常见业务口径做解释，最终仍建议以系统实现为准。")
    out.append("")
    out.append("## 2. 输入表总览")
    out.append("")
    out.append("| 表名 | 中文名 | 分组 | 字段数 | 作用概述 |")
    out.append("| --- | --- | --- | ---: | --- |")
    for t in tables:
        out.append(
            f"| `{t['table']}` | {esc(t['cn_name'])} | {TABLE_GROUP_HINT.get(t['table'], '未分类')} | {len(t['fields'])} | {esc(TABLE_DESC.get(t['table'], '输入业务表。'))} |"
        )
    out.append("")
    out.append("## 3. 字段逐表说明")
    out.append("")

    for idx, t in enumerate(tables, start=1):
        out.append(f"### 3.{idx} `{t['table']}`")
        out.append("")
        out.append(f"- 中文名：{t['cn_name']}")
        out.append(f"- 表用途：{TABLE_DESC.get(t['table'], '输入业务表。')}")
        out.append(f"- 字段数：{len(t['fields'])}")
        out.append("")
        out.append("| 字段名 | 类型 | 可空 | 默认值 | 原始备注 | 业务理解 |")
        out.append("| --- | --- | --- | --- | --- | --- |")
        for f in t["fields"]:
            out.append(
                f"| `{esc(f['field'])}` | {esc(f['type'])} | {esc(f['nullable'])} | {esc(f['default'])} | {esc(f['remark'])} | {esc(explain(t['table'], f['field'], f['remark']))} |"
            )
        out.append("")

    out.append("## 4. 建议优先理解的关键字段")
    out.append("")
    out.append("如果你是第一次接触这套 APS 输入数据，最建议先建立下面这几条主线：")
    out.append("")
    out.append("- 版本主线：`schedule_version`、`sub_schedule_version`。这两个字段决定“这一批数据属于哪次排产”。")
    out.append("- 需求主线：`demand_id`。这是需求跨表关联的核心键。")
    out.append("- 资源主线：`line_id`、`day`、`shift_seq`。这三个字段决定需求被排到哪条线、哪天、哪个班。")
    out.append("- 产品主线：`pn`、`model`、`program`、`series`、`color`。这组字段决定产品属性、线机匹配和换线难度。")
    out.append("- 交付主线：`mr_day`、`fpsd`、`ots_date`、`ship_date`。这组字段决定需求什么时候能排、应该优先排谁。")
    out.append("- 特殊约束主线：`fix_flag`、FAI 表、FIX 表、限制条件表、预留表。它们决定“不是所有需求都能自由优化”。")
    out.append("")
    out.append("## 5. 结论")
    out.append("")
    out.append("从输入表结构可以看出，BOX APS 已经不是简单的“订单 + 产线”排程，而是一套比较成熟的规则驱动排产体系。")
    out.append("")
    out.append("它的输入至少分成六层：")
    out.append("")
    out.append("- 产品主数据")
    out.append("- 需求主数据")
    out.append("- 特殊需求与锁定规则")
    out.append("- 线体与班次日历")
    out.append("- 产能与换线配置")
    out.append("- 排序、优先级、大小单、Cell线等规则配置")
    out.append("")
    out.append("因此，理解字段时最重要的不是孤立看单个字段，而是看它属于哪一层、它会影响“可不可排”“排到哪里”还是“谁先排”。")
    out.append("")

    target = os.path.join(base, "box_aps_input_fields_explained_v2.md")
    with open(target, "w", encoding="utf-8-sig", newline="\n") as f:
        f.write("\n".join(out))
    print(target)
    print(f"tables={len(tables)}")


if __name__ == "__main__":
    main()
