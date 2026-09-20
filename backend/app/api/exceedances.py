"""超标记录标注 API (含等级人工修正与公布月管理)."""
from flask import Blueprint, current_app, request

from ..domain.constants import EXCEEDANCE_LEVEL_LABELS, EXCEEDANCE_STATUS_LABELS, PERIOD_LABELS
from ..services import correction_service, exceedance_service
from ..utils.csv_export import csv_response
from ..utils.pagination import paginate_query
from ..utils.validation import Validator
from .helpers import json_payload, list_payload

bp = Blueprint("exceedances", __name__)


@bp.get("/", strict_slashes=False)
def list_exceedances():
    """超标记录列表: 支持状态/等级/因子/站点/时间过滤, 并附带筛选后的统计."""
    query = exceedance_service.exceedance_query(request.args)
    published_months = correction_service.published_month_set()
    result = paginate_query(
        query, lambda row: row.to_dict(published_months=published_months)
    )
    result["summary"] = exceedance_service.summary(request.args)
    return result


@bp.get("/summary")
def exceedance_summary():
    return exceedance_service.summary(request.args)


@bp.get("/options")
def exceedance_options():
    return {
        "levels": [
            {"value": key, "label": label}
            for key, label in EXCEEDANCE_LEVEL_LABELS.items()
        ],
        "statuses": [
            {"value": key, "label": label}
            for key, label in EXCEEDANCE_STATUS_LABELS.items()
        ],
        "periods": [{"value": key, "label": label} for key, label in PERIOD_LABELS.items()],
        "published_months": [
            item.period_month for item in correction_service.list_publications()
        ],
    }


@bp.get("/export")
def export_exceedances():
    rows = exceedance_service.exceedance_query(request.args).limit(
        current_app.config["MAX_EXPORT_ROWS"]
    ).all()
    columns = [
        ("站点编码", lambda row: row.station.code if row.station else ""),
        ("站点名称", lambda row: row.station.name if row.station else ""),
        ("监测因子", "pollutant"),
        ("监测值", "value"),
        ("限值", "limit_value"),
        ("超标倍数", "exceed_ratio"),
        ("超标等级", lambda row: EXCEEDANCE_LEVEL_LABELS.get(row.level, row.level)),
        ("系统原始等级", lambda row: EXCEEDANCE_LEVEL_LABELS.get(row.original_level, row.original_level)),
        ("等级是否修正", lambda row: "是" if row.level_corrected else "否"),
        ("标注状态", lambda row: EXCEEDANCE_STATUS_LABELS.get(row.status, row.status)),
        ("所属月份", "period_month"),
        ("监测时间", lambda row: row.measured_at.strftime("%Y-%m-%d %H:%M")),
        ("标注说明", "note"),
        ("标注人", "annotator"),
        ("标注时间", lambda row: row.annotated_at.strftime("%Y-%m-%d %H:%M")
            if row.annotated_at else ""),
    ]
    return csv_response(rows, columns, "exceedance_records")


@bp.get("/corrections/export")
def export_corrections():
    """导出等级修正留痕 (审计用, 含前后等级对比与操作人)."""
    rows = correction_service.correction_query(request.args).limit(
        current_app.config["MAX_EXPORT_ROWS"]
    ).all()
    columns = [
        ("批次号", "batch_no"),
        ("超标记录ID", "exceedance_id"),
        ("站点编码", lambda row: row.exceedance.station.code
            if row.exceedance and row.exceedance.station else ""),
        ("站点名称", lambda row: row.exceedance.station.name
            if row.exceedance and row.exceedance.station else ""),
        ("监测因子", "pollutant"),
        ("所属月份", "period_month"),
        ("修正前等级", lambda row: EXCEEDANCE_LEVEL_LABELS.get(row.level_before, row.level_before)),
        ("修正后等级", lambda row: EXCEEDANCE_LEVEL_LABELS.get(row.level_after, row.level_after)),
        ("修正理由", "reason"),
        ("操作人", "operator"),
        ("修正时间", lambda row: row.corrected_at.strftime("%Y-%m-%d %H:%M:%S")),
    ]
    return csv_response(rows, columns, "level_corrections")


@bp.get("/corrections")
def list_corrections():
    """等级修正留痕: 可按操作人、操作时间区间、月份、批次号、因子等检索."""
    query = correction_service.correction_query(request.args)
    result = paginate_query(query, lambda row: row.to_dict())
    result["summary"] = correction_service.correction_summary(request.args)
    return result


@bp.get("/publications")
def list_publications():
    """已对外公布的月份清单."""
    rows = correction_service.list_publications()
    return {
        "items": [row.to_dict() for row in rows],
        "total": len(rows),
    }


@bp.post("/publications")
def create_publication():
    """把某个监测月份标记为已对外公布, 公布月内记录禁止再修正等级."""
    data = json_payload()
    validator = Validator(data)
    period_month = validator.text("period_month", "公布月份", required=True, max_length=7)
    published_by = validator.text("published_by", "公布操作人", required=True, max_length=64)
    remark = validator.text("remark", "备注", required=False, max_length=500)
    validator.raise_if_invalid("公布信息不合法")

    # 归一化校验 YYYY-MM
    first_day = correction_service.parse_month(period_month, field="公布月份")
    record = correction_service.publish_month(
        first_day.strftime("%Y-%m"), published_by, remark=remark
    )
    return record.to_dict()


@bp.get("/<int:exceedance_id>")
def get_exceedance(exceedance_id):
    exceedance = exceedance_service.get_exceedance(exceedance_id)
    published_months = correction_service.published_month_set()
    return exceedance.to_dict(
        include_relations=True,
        include_corrections=True,
        published_months=published_months,
    )


@bp.patch("/<int:exceedance_id>")
def annotate_exceedance(exceedance_id):
    """单条标注: 确认 / 忽略 / 重置待标注 (需填写说明)."""
    exceedance = exceedance_service.get_exceedance(exceedance_id)
    data = json_payload()
    validator = Validator(data)
    status = validator.choice(
        "status", "标注状态", choices=tuple(EXCEEDANCE_STATUS_LABELS.keys()), required=False
    )
    note = validator.text("note", "标注说明", required=False, max_length=1000)
    annotator = validator.text("annotator", "标注人", required=False, max_length=64)
    validator.raise_if_invalid("标注信息不合法")

    updated = exceedance_service.annotate(
        exceedance, status=status, note=note, annotator=annotator
    )
    return updated.to_dict(
        include_corrections=True,
        published_months=correction_service.published_month_set(),
    )


@bp.post("/<int:exceedance_id>/corrections")
def correct_exceedance_level(exceedance_id):
    """单条等级人工修正: 必填修正理由与操作人, 写入留痕."""
    exceedance = exceedance_service.get_exceedance(exceedance_id)
    data = json_payload()
    validator = Validator(data)
    level = validator.choice(
        "level", "修正后等级", choices=tuple(EXCEEDANCE_LEVEL_LABELS.keys()), required=True
    )
    reason = validator.text("reason", "修正理由", required=True, max_length=1000)
    operator = validator.text("operator", "操作人", required=True, max_length=64)
    validator.raise_if_invalid("修正信息不合法")

    result = correction_service.correct_level(exceedance, level, reason, operator)
    return {
        "updated": 1,
        "batch_no": result["correction"].batch_no,
        "correction": result["correction"].to_dict(),
        "exceedance": result["exceedance"].to_dict(include_corrections=True),
    }


@bp.post("/corrections/batch")
def batch_correct_levels():
    """批量等级修正: 同一套校验整体成立才提交, 否则一条都不改。"""
    data = json_payload()
    validator = Validator(data)
    operator = validator.text("operator", "操作人", required=True, max_length=64)
    reason = validator.text("reason", "公共修正理由", required=False, max_length=1000)
    validator.raise_if_invalid("批量修正信息不合法")

    items = list_payload("items", data)
    return correction_service.correct_level_batch(items, operator, reason=reason)


@bp.post("/annotations")
def batch_annotate():
    """批量标注: 工作台勾选多条后一次性确认或忽略."""
    data = json_payload()
    validator = Validator(data)
    status = validator.choice(
        "status", "标注状态", choices=tuple(EXCEEDANCE_STATUS_LABELS.keys()), required=True
    )
    note = validator.text("note", "标注说明", required=False, max_length=1000)
    annotator = validator.text("annotator", "标注人", required=False, max_length=64)
    validator.raise_if_invalid("标注信息不合法")

    ids = list_payload("ids", data)
    return exceedance_service.annotate_batch(ids, status, note=note, annotator=annotator)
