"""超标等级人工修正: 统一校验、留痕、批量原子提交与公布月冻结.

规则:
- 修正必须填写理由并署名操作人;
- 修正后列表/详情/看板/统计/导出统一使用 ``Exceedance.level`` (新等级),
  系统原始等级保存在 ``original_level``, 每次变化写入 ``LevelCorrection``;
- 批量修正在同一个事务内整体校验, 任一记录不满足条件则全部不生效;
- 超标数据所属月份一旦对外公布 (``MonthlyPublication``), 该月记录禁止再修正。
"""
from datetime import datetime

from sqlalchemy import func

from ..domain.constants import EXCEEDANCE_LEVEL_LABELS
from ..errors import ConflictError, NotFoundError, ValidationError
from ..extensions import db
from ..models import Exceedance, LevelCorrection, MonthlyPublication

LEVEL_CHOICES = tuple(EXCEEDANCE_LEVEL_LABELS.keys())

_MONTH_FMT = "%Y-%m"


def parse_month(value, field="月份"):
    """Parse a strict ``YYYY-MM`` string (month zero-padded); raises ValidationError."""
    text = str(value or "").strip()
    try:
        parsed = datetime.strptime(text, _MONTH_FMT).date()
    except ValueError:
        raise ValidationError(
            "%s格式应为 YYYY-MM" % field, fields={"period_month": "invalid_month"}
        )
    # strptime 容忍 "2026-8" 这类非零填充写法, 这里再做一次严格形态校验
    if parsed.strftime(_MONTH_FMT) != text:
        raise ValidationError(
            "%s格式应为 YYYY-MM" % field, fields={"period_month": "invalid_month"}
        )
    return parsed


def month_range(value):
    """Return (first_day, last_day) for ``YYYY-MM`` or None when unparseable."""
    from calendar import monthrange

    text = str(value or "").strip()
    try:
        first = datetime.strptime(text, _MONTH_FMT).date()
    except ValueError:
        return None
    last_day = monthrange(first.year, first.month)[1]
    from datetime import date as _date

    return first, _date(first.year, first.month, last_day)


# ---------------------------------------------------------------------------
# 公布月份
# ---------------------------------------------------------------------------

def is_month_published(period_month):
    if not period_month:
        return False
    return (
        db.session.query(MonthlyPublication.id)
        .filter(MonthlyPublication.period_month == period_month)
        .first()
        is not None
    )


def published_month_set():
    return {
        row[0]
        for row in db.session.query(MonthlyPublication.period_month).all()
    }


def list_publications():
    return (
        MonthlyPublication.query.order_by(
            MonthlyPublication.period_month.desc()
        ).all()
    )


def publish_month(period_month, published_by, remark=None):
    """标记某个监测月份已经对外公布 (幂等: 重复公布返回冲突提示)."""
    first_day = parse_month(period_month)
    period_month = first_day.strftime(_MONTH_FMT)
    published_by = _validate_operator(published_by)
    existing = MonthlyPublication.query.filter_by(period_month=period_month).first()
    if existing is not None:
        raise ConflictError("月份 %s 已公布, 无需重复公布" % period_month)
    record = MonthlyPublication(
        period_month=period_month,
        published_by=published_by,
        published_at=datetime.now(),
        remark=(remark or None),
    )
    db.session.add(record)
    db.session.commit()
    return record


# ---------------------------------------------------------------------------
# 校验 (单条与批量共用同一套规则)
# ---------------------------------------------------------------------------

def _validate_level(level):
    if level not in LEVEL_CHOICES:
        raise ValidationError(
            "超标等级取值不合法, 可选: %s" % ", ".join(LEVEL_CHOICES),
            fields={"level": "unknown"},
        )


def _validate_reason(reason):
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("修正等级必须填写修正理由", fields={"reason": "required"})
    if len(reason) > 1000:
        raise ValidationError("修正理由长度不能超过 1000 个字符", fields={"reason": "too_long"})
    return reason


def _validate_operator(operator):
    operator = (operator or "").strip()
    if not operator:
        raise ValidationError("修正等级必须填写操作人", fields={"operator": "required"})
    if len(operator) > 64:
        raise ValidationError("操作人长度不能超过 64 个字符", fields={"operator": "too_long"})
    return operator


def _check_correctable(exceedance, new_level, published_months):
    """返回 (field, message) 形式的错误; None 表示可修正。"""
    if exceedance is None:
        return "missing", "超标记录不存在"
    if exceedance.period_month in published_months:
        return "month_published", "所属月份 %s 已对外公布, 等级不得再修正" % exceedance.period_month
    if new_level == exceedance.level:
        return "unchanged", "修正后等级与当前等级一致, 无需修正"
    return None


# ---------------------------------------------------------------------------
# 单条 / 批量修正
# ---------------------------------------------------------------------------

def _new_batch_no():
    return "C%s%06d" % (datetime.now().strftime("%Y%m%d%H%M%S"), datetime.now().microsecond % 1000000)


def _write_correction(exceedance, new_level, reason, operator, batch_no, now):
    log = LevelCorrection(
        exceedance_id=exceedance.id,
        measurement_id=exceedance.measurement_id,
        station_id=exceedance.station_id,
        pollutant=exceedance.pollutant,
        period_month=exceedance.period_month,
        level_before=exceedance.level,
        level_after=new_level,
        reason=reason,
        operator=operator,
        batch_no=batch_no,
        corrected_at=now,
    )
    db.session.add(log)
    exceedance.level = new_level
    exceedance.level_corrected = True
    return log


def correct_level(exceedance, new_level, reason, operator):
    """修正单条超标记录的等级并写入留痕."""
    _validate_level(new_level)
    reason = _validate_reason(reason)
    operator = _validate_operator(operator)

    error = _check_correctable(exceedance, new_level, published_month_set())
    if error:
        field, message = error
        raise ValidationError(message, fields={"level": field})

    now = datetime.now()
    log = _write_correction(exceedance, new_level, reason, operator, _new_batch_no(), now)
    db.session.commit()
    return {"exceedance": exceedance, "correction": log}


def correct_level_batch(items, operator, reason=None):
    """批量修正: items 为 [{"id": int, "level": str}], 整体校验通过后一次性提交。

    - 所有记录共享同一次操作的操作人与批次号, 每条可使用各自的理由,
      未单独填写时回退到公共 ``reason``;
    - 任一条校验失败 (含不存在/月份已公布/等级未变/重复选择) 整体回滚。
    """
    if not isinstance(items, list) or not items:
        raise ValidationError("请至少选择一条超标记录", fields={"items": "empty"})

    operator = _validate_operator(operator)
    common_reason = (reason or "").strip()

    # 先解析并去重, 同时收集字段级错误
    parsed = []
    seen = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValidationError(
                "items 第 %d 项必须是对象" % (index + 1),
                fields={"items": "invalid"},
            )
        record_id = item.get("id")
        new_level = item.get("level")
        item_reason = (item.get("reason") or "").strip()
        try:
            record_id = int(record_id)
        except (TypeError, ValueError):
            raise ValidationError(
                "第 %d 条记录 id 必须为整数" % (index + 1),
                fields={"items[%d].id" % index: "invalid_integer"},
            )
        if new_level not in LEVEL_CHOICES:
            raise ValidationError(
                "记录 %d 的目标等级不合法, 可选: %s" % (record_id, ", ".join(LEVEL_CHOICES)),
                fields={"items[%d].level" % index: "unknown"},
            )
        if record_id in seen:
            raise ValidationError(
                "记录 %d 在批量中重复出现" % record_id,
                fields={"items[%d].id" % index: "duplicated"},
            )
        seen.add(record_id)
        if not item_reason and not common_reason:
            raise ValidationError(
                "记录 %d 缺少修正理由" % record_id,
                fields={"items[%d].reason" % index: "required"},
            )
        if len(item_reason or common_reason) > 1000:
            raise ValidationError(
                "记录 %d 的修正理由长度不能超过 1000 字" % record_id,
                fields={"items[%d].reason" % index: "too_long"},
            )
        parsed.append(
            {"id": record_id, "level": new_level, "reason": item_reason or common_reason}
        )

    # 一次性取出所有记录, 然后统一跑业务校验: 任何一条不满足都整体拒绝
    records = {
        row.id: row
        for row in Exceedance.query.filter(Exceedance.id.in_(list(seen))).all()
    }
    published_months = published_month_set()
    failures = []
    for entry in parsed:
        record = records.get(entry["id"])
        if record is None:
            failures.append({"id": entry["id"], "code": "missing", "reason": "超标记录不存在"})
            continue
        result = _check_correctable(record, entry["level"], published_months)
        if result:
            code, message = result
            failures.append({"id": entry["id"], "code": code, "reason": message})
    if failures:
        raise ValidationError(
            "批量修正中有 %d 条记录不满足条件, 已全部取消, 未改动任何数据: %s"
            % (
                len(failures),
                "; ".join("id=%s %s" % (item["id"], item["reason"]) for item in failures[:10]),
            ),
            fields={"failures": failures},
        )

    # 校验全部通过 -> 同一事务内写入, 保证不会只改一半
    batch_no = _new_batch_no()
    now = datetime.now()
    logs = []
    try:
        for entry in parsed:
            logs.append(
                _write_correction(
                    records[entry["id"]],
                    entry["level"],
                    entry["reason"],
                    operator,
                    batch_no,
                    now,
                )
            )
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return {
        "updated": len(logs),
        "updated_ids": [entry["id"] for entry in parsed],
        "batch_no": batch_no,
        "operator": operator,
        "corrections": [log.to_dict() for log in logs],
    }


# ---------------------------------------------------------------------------
# 留痕检索 (按操作人 / 时间 / 月份 / 批次等)
# ---------------------------------------------------------------------------

def _split(value):
    if not value:
        return []
    return [item.strip() for item in str(value).split(",") if item.strip()]


def correction_query(args):
    query = db.session.query(LevelCorrection)

    exceedance_id = args.get("exceedance_id")
    if exceedance_id not in (None, ""):
        try:
            query = query.filter(LevelCorrection.exceedance_id == int(exceedance_id))
        except ValueError:
            raise ValidationError(
                "exceedance_id 必须为整数", fields={"exceedance_id": "invalid_integer"}
            )
    station_ids = _split(args.get("station_id"))
    if station_ids:
        try:
            query = query.filter(
                LevelCorrection.station_id.in_([int(item) for item in station_ids])
            )
        except ValueError:
            raise ValidationError(
                "station_id 必须为整数", fields={"station_id": "invalid_integer"}
            )
    pollutants = [item.upper() for item in _split(args.get("pollutant"))]
    if pollutants:
        query = query.filter(LevelCorrection.pollutant.in_(pollutants))
    levels = _split(args.get("level_after"))
    if levels:
        query = query.filter(LevelCorrection.level_after.in_(levels))
    months = _split(args.get("period_month"))
    if months:
        query = query.filter(LevelCorrection.period_month.in_(months))
    operator = (args.get("operator") or "").strip()
    if operator:
        query = query.filter(LevelCorrection.operator.like("%" + operator + "%"))
    batch_no = (args.get("batch_no") or "").strip()
    if batch_no:
        query = query.filter(LevelCorrection.batch_no == batch_no)

    from ..utils.validation import parse_date
    date_from = args.get("date_from")
    if date_from not in (None, ""):
        query = query.filter(LevelCorrection.corrected_at >= parse_date(date_from, "开始日期"))
    date_to = args.get("date_to")
    if date_to not in (None, ""):
        from datetime import time as dtime
        query = query.filter(
            LevelCorrection.corrected_at
            <= datetime.combine(parse_date(date_to, "结束日期"), dtime.max)
        )

    order = (args.get("order") or "desc").lower()
    primary = (
        LevelCorrection.corrected_at.asc()
        if order == "asc"
        else LevelCorrection.corrected_at.desc()
    )
    return query.order_by(primary, LevelCorrection.id.desc())


def correction_summary(args=None):
    """留痕页统计: 修正次数 / 涉及记录数 / 操作人数."""
    base = correction_query(args or {})
    totals = base.with_entities(
        func.count(LevelCorrection.id),
        func.count(func.distinct(LevelCorrection.exceedance_id)),
        func.count(func.distinct(LevelCorrection.operator)),
    ).one()
    return {
        "correction_count": int(totals[0] or 0),
        "affected_records": int(totals[1] or 0),
        "operator_count": int(totals[2] or 0),
    }


def get_exceedance_or_404(exceedance_id):
    record = db.session.get(Exceedance, exceedance_id)
    if record is None:
        raise NotFoundError("超标记录不存在: id=%s" % exceedance_id)
    return record
