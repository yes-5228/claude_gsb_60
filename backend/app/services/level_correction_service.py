"""超标等级人工修正: 留痕、批量原子校验、跨已公布月份冻结.

业务规则:
- 等级修正必须填写理由与操作人, 每次修正生成不可变留痕 (前后等级对比)。
- 修正后实时口径 (列表/详情/看板/统计/导出) 统一使用新等级;
  同一条记录反复修正时, 每一次变化都可按时间顺序追溯。
- 批量修正按同一套校验"整体成立": 任一记录不满足条件则整批拒绝, 不会只改一半。
- 修正落在已对外公布的月份时, 修正照常留痕并生效于实时口径,
  但公布时冻结的月份快照不被改变 (公布口径不变)。
"""
import uuid
from datetime import datetime

from sqlalchemy import func

from ..domain.constants import EXCEEDANCE_LEVEL_LABELS
from ..errors import ConflictError, NotFoundError, ValidationError
from ..extensions import db
from ..models import (
    Exceedance,
    LevelCorrection,
    PublishedExceedanceSnapshot,
    PublishedMonth,
)
from ..models.base import iso
from ..utils.validation import parse_date

LEVEL_CHOICES = tuple(EXCEEDANCE_LEVEL_LABELS.keys())
REASON_MAX_LENGTH = 500


# ---- 月份工具 ---------------------------------------------------------------

def month_of(value):
    """Return the YYYY-MM business month of a datetime."""
    return value.strftime("%Y-%m")


def parse_month(value, field="month"):
    text = str(value or "").strip()
    try:
        parsed = datetime.strptime(text, "%Y-%m")
    except ValueError:
        raise ValidationError(
            "%s格式应为 YYYY-MM" % field, fields={field: "invalid_month"}
        )
    return parsed.strftime("%Y-%m")


def _published_month_map():
    return {row.month: row for row in PublishedMonth.query.all()}


def is_month_published(month):
    return PublishedMonth.query.filter_by(month=month).first() is not None


# ---- 单条 / 批量修正 --------------------------------------------------------

def _validate_reason_operator(reason, operator):
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("等级修正必须填写修正理由", fields={"reason": "required"})
    if len(reason) > REASON_MAX_LENGTH:
        raise ValidationError(
            "修正理由不能超过 %d 个字符" % REASON_MAX_LENGTH, fields={"reason": "too_long"}
        )
    operator = (operator or "").strip()
    if not operator:
        raise ValidationError("等级修正必须填写操作人", fields={"operator": "required"})
    if len(operator) > 64:
        raise ValidationError("操作人长度不能超过 64 个字符", fields={"operator": "too_long"})
    return reason, operator


def _check_target(exceedance, to_level):
    """Validate one correction target; returns an error code string or None."""
    if to_level not in LEVEL_CHOICES:
        return "unknown_level"
    if exceedance.level == to_level:
        return "unchanged"
    return None


def correct_level(exceedance, to_level, reason, operator, batch_no=None):
    """Apply one level correction and append an immutable audit row."""
    reason, operator = _validate_reason_operator(reason, operator)
    problem = _check_target(exceedance, to_level)
    if problem == "unknown_level":
        raise ValidationError(
            "超标等级取值不合法, 可选: %s" % ", ".join(LEVEL_CHOICES),
            fields={"level": "unknown"},
        )
    if problem == "unchanged":
        raise ValidationError(
            "新等级与当前等级相同, 无需修正", fields={"level": "unchanged"}
        )

    from_level = exceedance.level
    month = month_of(exceedance.measured_at)
    published_month = month if is_month_published(month) else None

    correction = LevelCorrection(
        exceedance_id=exceedance.id,
        station_id=exceedance.station_id,
        measurement_id=exceedance.measurement_id,
        pollutant=exceedance.pollutant,
        from_level=from_level,
        to_level=to_level,
        reason=reason,
        operator=operator,
        corrected_at=datetime.now(),
        batch_no=batch_no,
        published_month=published_month,
    )
    db.session.add(correction)

    exceedance.level = to_level
    exceedance.level_source = "manual"

    db.session.commit()
    return {
        "exceedance": exceedance,
        "correction": correction,
        "cross_published": published_month is not None,
        "published_month": published_month,
    }


def correct_batch(items, reason, operator):
    """Batch correction: validate every target first, then commit atomically.

    ``items`` is a list of {"id": int, "level": str}. If any record is missing
    or fails validation the whole request is rejected and nothing is changed.
    """
    reason, operator = _validate_reason_operator(reason, operator)

    if not isinstance(items, list) or not items:
        raise ValidationError("请至少选择一条超标记录", fields={"items": "empty"})

    # 去重 (同一条记录在一批里只允许出现一次)
    seen = set()
    normalized = []
    duplicate_indices = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValidationError(
                "items 第 %d 项格式不正确" % (index + 1), fields={"items": "invalid_item"}
            )
        raw_id = item.get("id")
        try:
            record_id = int(raw_id)
        except (TypeError, ValueError):
            raise ValidationError(
                "items 第 %d 项缺少合法记录 id" % (index + 1),
                fields={"items[%d].id" % index: "invalid"},
            )
        if record_id in seen:
            duplicate_indices.append(index)
            continue
        seen.add(record_id)
        normalized.append((index, record_id, str(item.get("level") or "").strip()))

    if duplicate_indices:
        raise ValidationError(
            "同一批修正中存在重复记录 (第 %s 项)"
            % ", ".join(str(i + 1) for i in duplicate_indices),
            fields={"items": "duplicated"},
        )

    records = (
        db.session.query(Exceedance)
        .filter(Exceedance.id.in_([record_id for _, record_id, _ in normalized]))
        .all()
    )
    record_map = {record.id: record for record in records}

    # ---- 全量校验阶段 (不修改任何对象) ----
    missing = []
    item_errors = {}
    targets = []
    for index, record_id, to_level in normalized:
        record = record_map.get(record_id)
        if record is None:
            missing.append(record_id)
            continue
        problem = _check_target(record, to_level)
        if problem:
            item_errors["items[%d].level" % index] = problem
        else:
            targets.append((record, to_level))

    if missing:
        raise ValidationError(
            "以下超标记录不存在, 本批未做任何修改: %s" % ", ".join(map(str, missing)),
            fields={"missing": missing},
        )
    if item_errors:
        raise ValidationError(
            "批量修正中有 %d 条记录不满足条件, 本批未做任何修改" % len(item_errors),
            fields=item_errors,
        )

    # ---- 全部通过后一次性落库 (原子提交) ----
    published_map = _published_month_map()
    batch_no = "BC%s-%s" % (datetime.now().strftime("%Y%m%d%H%M%S"), uuid.uuid4().hex[:8])
    applied = []
    cross_published = []
    for record, to_level in targets:
        from_level = record.level
        month = month_of(record.measured_at)
        published_month = month if month in published_map else None
        correction = LevelCorrection(
            exceedance_id=record.id,
            station_id=record.station_id,
            measurement_id=record.measurement_id,
            pollutant=record.pollutant,
            from_level=from_level,
            to_level=to_level,
            reason=reason,
            operator=operator,
            corrected_at=datetime.now(),
            batch_no=batch_no,
            published_month=published_month,
        )
        db.session.add(correction)
        record.level = to_level
        record.level_source = "manual"
        applied.append(
            {"exceedance_id": record.id, "from_level": from_level, "to_level": to_level}
        )
        if published_month:
            cross_published.append(
                {"exceedance_id": record.id, "published_month": published_month}
            )

    db.session.commit()
    return {
        "updated": len(applied),
        "items": applied,
        "batch_no": batch_no,
        "cross_published": cross_published,
    }


# ---- 修正历史检索 -----------------------------------------------------------

def correction_query(args):
    """Audit trail query: filter by operator/time/record/pollutant/batch."""
    query = db.session.query(LevelCorrection).join(
        Exceedance, LevelCorrection.exceedance_id == Exceedance.id
    )

    operator = (args.get("operator") or "").strip()
    if operator:
        query = query.filter(LevelCorrection.operator.like("%" + operator + "%"))
    pollutant = (args.get("pollutant") or "").strip()
    if pollutant:
        query = query.filter(LevelCorrection.pollutant == pollutant.upper())
    exceedance_id = args.get("exceedance_id")
    if exceedance_id not in (None, ""):
        try:
            query = query.filter(LevelCorrection.exceedance_id == int(exceedance_id))
        except ValueError:
            raise ValidationError(
                "exceedance_id 必须为整数", fields={"exceedance_id": "invalid"}
            )
    station_id = args.get("station_id")
    if station_id not in (None, ""):
        try:
            query = query.filter(LevelCorrection.station_id == int(station_id))
        except ValueError:
            raise ValidationError(
                "station_id 必须为整数", fields={"station_id": "invalid"}
            )
    batch_no = (args.get("batch_no") or "").strip()
    if batch_no:
        query = query.filter(LevelCorrection.batch_no == batch_no)

    published = (args.get("cross_published") or "").strip().lower()
    if published in {"1", "true", "yes"}:
        query = query.filter(LevelCorrection.published_month.isnot(None))
    elif published in {"0", "false", "no"}:
        query = query.filter(LevelCorrection.published_month.is_(None))

    raw_from, raw_to = args.get("date_from"), args.get("date_to")
    if raw_from not in (None, ""):
        from datetime import datetime as _dt
        from datetime import time as _time

        query = query.filter(
            LevelCorrection.corrected_at
            >= _dt.combine(parse_date(raw_from, "date_from"), _time.min)
        )
    if raw_to not in (None, ""):
        from datetime import datetime as _dt
        from datetime import time as _time

        query = query.filter(
            LevelCorrection.corrected_at
            <= _dt.combine(parse_date(raw_to, "date_to"), _time.max)
        )

    return query.order_by(LevelCorrection.corrected_at.desc(), LevelCorrection.id.desc())


def correction_summary(args):
    """Small counters for the audit trail view."""
    base = correction_query(args)
    total = base.count()
    # 复用同一过滤条件统计跨公布月份数量
    cross_count = base.filter(LevelCorrection.published_month.isnot(None)).count()
    operators = [
        row[0]
        for row in db.session.query(LevelCorrection.operator)
        .distinct()
        .order_by(LevelCorrection.operator.asc())
        .all()
    ]
    return {
        "total": total,
        "cross_published_count": cross_count,
        "operators": operators,
    }


# ---- 月份公布与冻结快照 -----------------------------------------------------

def publish_month(month, operator, remark=None):
    """Freeze current exceedance levels of a month as the published version."""
    month = parse_month(month)
    operator = (operator or "").strip() or "系统"
    remark = (remark or "").strip() or None

    if PublishedMonth.query.filter_by(month=month).first() is not None:
        raise ConflictError("月份 %s 已对外公布, 不能重复公布" % month)

    start = datetime.strptime(month + "-01", "%Y-%m-%d")
    if start.month == 12:
        end = datetime(start.year + 1, 1, 1)
    else:
        end = datetime(start.year, start.month + 1, 1)

    records = (
        Exceedance.query.filter(Exceedance.measured_at >= start)
        .filter(Exceedance.measured_at < end)
        .all()
    )

    publication = PublishedMonth(
        month=month,
        published_at=datetime.now(),
        published_by=operator,
        remark=remark,
    )
    db.session.add(publication)
    db.session.flush()  # 取 publication.id

    for record in records:
        db.session.add(
            PublishedExceedanceSnapshot(
                publish_id=publication.id,
                month=month,
                exceedance_id=record.id,
                station_id=record.station_id,
                station_code=record.station.code if record.station else None,
                station_name=record.station.name if record.station else None,
                pollutant=record.pollutant,
                measured_at=record.measured_at,
                value=record.value,
                limit_value=record.limit_value,
                exceed_ratio=record.exceed_ratio,
                level=record.level,
                status=record.status,
            )
        )

    db.session.commit()
    return {
        "month": month,
        "published_by": operator,
        "published_at": iso(publication.published_at),
        "snapshot_count": len(records),
    }


def list_published_months():
    return [
        month.to_dict(include_counts=True)
        for month in PublishedMonth.query.order_by(PublishedMonth.month.desc()).all()
    ]


def get_published_month(month):
    month = parse_month(month)
    publication = PublishedMonth.query.filter_by(month=month).first()
    if publication is None:
        raise NotFoundError("月份 %s 尚未对外公布" % month)
    return publication


def published_snapshot_query(month):
    get_published_month(month)  # 不存在直接 404
    return PublishedExceedanceSnapshot.query.filter_by(month=month).order_by(
        PublishedExceedanceSnapshot.measured_at.desc(),
        PublishedExceedanceSnapshot.id.desc(),
    )


def published_level_summary(month):
    """Frozen level distribution of the published month (公布口径统计)."""
    get_published_month(month)
    rows = (
        db.session.query(
            PublishedExceedanceSnapshot.level, func.count(PublishedExceedanceSnapshot.id)
        )
        .filter(PublishedExceedanceSnapshot.month == month)
        .group_by(PublishedExceedanceSnapshot.level)
        .all()
    )
    counts = {level: 0 for level in EXCEEDANCE_LEVEL_LABELS}
    for level, count in rows:
        counts[level] = int(count)
    return {
        "month": month,
        "total": sum(counts.values()),
        "by_level": [
            {"key": key, "label": label, "count": counts.get(key, 0)}
            for key, label in EXCEEDANCE_LEVEL_LABELS.items()
        ],
    }
