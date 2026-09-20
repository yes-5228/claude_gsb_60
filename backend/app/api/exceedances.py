"""超标记录标注 / 等级人工修正 API."""
from flask import Blueprint, current_app, request

from ..domain.constants import EXCEEDANCE_LEVEL_LABELS, EXCEEDANCE_STATUS_LABELS, PERIOD_LABELS
from ..services import exceedance_service, level_correction_service
from ..utils.pagination import paginate_query
from ..utils.validation import Validator
from .helpers import json_payload, list_payload

bp = Blueprint("exceedances", __name__)


@bp.get("/", strict_slashes=False)
def list_exceedances():
    """超标记录列表: 支持状态/等级/因子/站点/时间过滤, 并附带筛选后的统计."""
    query = exceedance_service.exceedance_query(request.args)
    result = paginate_query(query, lambda row: row.to_dict())
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
    }


@bp.get("/export")
def export_exceedances():
    """导出当前实时口径 (修正后的新等级在列表/统计/导出中统一生效)。"""
    from ..utils.csv_export import csv_response

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
        ("系统判定等级", lambda row: EXCEEDANCE_LEVEL_LABELS.get(row.auto_level, row.auto_level)),
        ("超标等级(生效)", lambda row: EXCEEDANCE_LEVEL_LABELS.get(row.level, row.level)),
        ("等级来源", lambda row: "人工修正" if row.level_source == "manual" else "系统判定"),
        ("标注状态", lambda row: EXCEEDANCE_STATUS_LABELS.get(row.status, row.status)),
        ("监测时间", lambda row: row.measured_at.strftime("%Y-%m-%d %H:%M")),
        ("标注说明", "note"),
        ("标注人", "annotator"),
        ("标注时间", lambda row: row.annotated_at.strftime("%Y-%m-%d %H:%M")
            if row.annotated_at else ""),
    ]
    return csv_response(rows, columns, "exceedance_records")


@bp.get("/corrections")
def list_corrections():
    """等级修正留痕: 支持按操作人、时间区间、记录、因子、批次检索。"""
    query = level_correction_service.correction_query(request.args)
    result = paginate_query(query, lambda row: row.to_dict())
    result["summary"] = level_correction_service.correction_summary(request.args)
    return result


@bp.get("/corrections/export")
def export_corrections():
    from ..utils.csv_export import csv_response

    rows = level_correction_service.correction_query(request.args).limit(
        current_app.config["MAX_EXPORT_ROWS"]
    ).all()
    columns = [
        ("修正时间", lambda row: row.corrected_at.strftime("%Y-%m-%d %H:%M:%S")),
        ("超标记录ID", "exceedance_id"),
        ("站点编码", lambda row: row.station.code if row.station else ""),
        ("站点名称", lambda row: row.station.name if row.station else ""),
        ("监测因子", "pollutant"),
        ("修正前等级", lambda row: EXCEEDANCE_LEVEL_LABELS.get(row.from_level, row.from_level)),
        ("修正后等级", lambda row: EXCEEDANCE_LEVEL_LABELS.get(row.to_level, row.to_level)),
        ("修正理由", "reason"),
        ("操作人", "operator"),
        ("修正批次", lambda row: row.batch_no or ""),
        ("数据所属月", lambda row: row.exceedance.measured_at.strftime("%Y-%m")
            if row.exceedance else ""),
        ("跨已公布月份", lambda row: row.published_month or ""),
    ]
    return csv_response(rows, columns, "level_corrections")


@bp.post("/corrections/batch")
def batch_correct_level():
    """批量等级修正: 整体校验通过后原子提交, 任一不满足则整批不改。

    支持两种提交形式:
    - {"items": [{"id": 1, "level": "severe"}, ...], "reason", "operator"}
    - {"ids": [1, 2], "level": "severe", "reason", "operator"}
    """
    data = json_payload()
    validator = Validator(data)
    to_level = validator.choice(
        "level", "修正后等级", choices=tuple(EXCEEDANCE_LEVEL_LABELS.keys()), required=False
    )
    validator.text("reason", "修正理由", required=False, max_length=500)
    validator.text("operator", "操作人", required=False, max_length=64)
    validator.raise_if_invalid("等级修正信息不合法")

    reason = (data.get("reason") or "").strip()
    operator = (data.get("operator") or "").strip()

    raw_items = data.get("items")
    if raw_items is not None:
        if not isinstance(raw_items, list):
            from ..errors import ValidationError

            raise ValidationError("字段 items 必须是数组", fields={"items": "invalid"})
        if len(raw_items) > current_app.config["MAX_BATCH_SIZE"]:
            from ..errors import ValidationError

            raise ValidationError(
                "items 一次最多提交 %d 条" % current_app.config["MAX_BATCH_SIZE"],
                fields={"items": "too_many"},
            )
        items = [
            {
                "id": item.get("id") if isinstance(item, dict) else item,
                "level": (item.get("level") if isinstance(item, dict) else None) or to_level,
            }
            for item in raw_items
        ]
    else:
        raw_ids = data.get("ids")
        if not isinstance(raw_ids, list):
            from ..errors import ValidationError

            raise ValidationError("请提供 items 或 ids 列表", fields={"items": "required"})
        if len(raw_ids) > current_app.config["MAX_BATCH_SIZE"]:
            from ..errors import ValidationError

            raise ValidationError(
                "ids 一次最多提交 %d 条" % current_app.config["MAX_BATCH_SIZE"],
                fields={"ids": "too_many"},
            )
        items = [{"id": item, "level": to_level} for item in raw_ids]

    return level_correction_service.correct_batch(items, reason, operator)


@bp.get("/published-months")
def list_published_months():
    return {"items": level_correction_service.list_published_months()}


@bp.post("/published-months")
def publish_month():
    """对外公布某月: 冻结该月全部超标记录的当前等级。"""
    data = json_payload()
    validator = Validator(data)
    month = validator.text("month", "公布月份", required=True, max_length=7)
    operator = validator.text("published_by", "公布操作人", required=False, max_length=64, default="系统")
    remark = validator.text("remark", "备注", required=False, max_length=500)
    validator.raise_if_invalid("月份公布信息不合法")
    return level_correction_service.publish_month(month, operator or "系统", remark)


@bp.get("/published-months/<month>")
def get_published_month(month):
    publication = level_correction_service.get_published_month(month)
    payload = publication.to_dict(include_counts=True)
    payload["level_summary"] = level_correction_service.published_level_summary(month)
    return payload


@bp.get("/published-months/<month>/exceedances")
def list_published_exceedances(month):
    """已公布月份的冻结口径明细 (跨月修正不影响这里)。"""
    query = level_correction_service.published_snapshot_query(month)
    return paginate_query(
        query,
        lambda row: row.to_dict(
            level_labels=EXCEEDANCE_LEVEL_LABELS, status_labels=EXCEEDANCE_STATUS_LABELS
        ),
    )


@bp.get("/published-months/<month>/export")
def export_published_month(month):
    from ..utils.csv_export import csv_response

    level_correction_service.get_published_month(month)
    rows = level_correction_service.published_snapshot_query(month).limit(
        current_app.config["MAX_EXPORT_ROWS"]
    ).all()
    columns = [
        ("公布月份", "month"),
        ("站点编码", "station_code"),
        ("站点名称", "station_name"),
        ("监测因子", "pollutant"),
        ("监测值", "value"),
        ("限值", "limit_value"),
        ("超标倍数", "exceed_ratio"),
        ("公布时等级", lambda row: EXCEEDANCE_LEVEL_LABELS.get(row.level, row.level)),
        ("标注状态", lambda row: EXCEEDANCE_STATUS_LABELS.get(row.status, row.status)),
        ("监测时间", lambda row: row.measured_at.strftime("%Y-%m-%d %H:%M")),
    ]
    return csv_response(rows, columns, "published_%s" % month)


@bp.get("/<int:exceedance_id>")
def get_exceedance(exceedance_id):
    exceedance = exceedance_service.get_exceedance(exceedance_id)
    return exceedance.to_dict(include_relations=True)


@bp.patch("/<int:exceedance_id>")
def annotate_exceedance(exceedance_id):
    """单条标注: 确认/忽略 (必须填写说明)。等级修正请走专用修正接口以完整留痕。"""
    exceedance = exceedance_service.get_exceedance(exceedance_id)
    data = json_payload()
    if str(data.get("level") or "").strip():
        from ..errors import ValidationError

        raise ValidationError(
            "超标等级修正请使用等级修正接口 (/corrections), 以便记录修正理由与前后对比",
            fields={"level": "use_correction_endpoint"},
        )
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
    return updated.to_dict()


@bp.post("/<int:exceedance_id>/corrections")
def correct_exceedance_level(exceedance_id):
    """单条等级人工修正: 必填理由, 记录前后等级对比并形成可追溯留痕。"""
    exceedance = exceedance_service.get_exceedance(exceedance_id)
    data = json_payload()
    validator = Validator(data)
    to_level = validator.choice(
        "level", "修正后等级", choices=tuple(EXCEEDANCE_LEVEL_LABELS.keys()), required=True
    )
    # 必填由 service 层校验, 以返回统一的字段错误码 (required)
    validator.text("reason", "修正理由", required=False, max_length=500)
    validator.text("operator", "操作人", required=False, max_length=64)
    validator.raise_if_invalid("等级修正信息不合法")

    reason = (data.get("reason") or "").strip()
    operator = (data.get("operator") or "").strip()
    result = level_correction_service.correct_level(exceedance, to_level, reason, operator)
    return {
        "exceedance": result["exceedance"].to_dict(include_relations=True),
        "correction": result["correction"].to_dict(),
        "cross_published": result["cross_published"],
        "published_month": result["published_month"],
    }


@bp.post("/annotations")
def batch_annotate():
    """批量标注: 工作台勾选多条后一次性确认或忽略 (不含等级修正)。"""
    data = json_payload()
    if str(data.get("level") or "").strip():
        from ..errors import ValidationError

        raise ValidationError(
            "批量标注不支持修改等级, 请使用批量等级修正接口 (/corrections/batch)",
            fields={"level": "use_correction_endpoint"},
        )
    validator = Validator(data)
    status = validator.choice(
        "status", "标注状态", choices=tuple(EXCEEDANCE_STATUS_LABELS.keys()), required=True
    )
    note = validator.text("note", "标注说明", required=False, max_length=1000)
    annotator = validator.text("annotator", "标注人", required=False, max_length=64)
    validator.raise_if_invalid("标注信息不合法")

    ids = list_payload("ids", data)
    return exceedance_service.annotate_batch(ids, status, note=note, annotator=annotator)
