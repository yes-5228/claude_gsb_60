"""超标等级人工修正: 留痕、统一生效、批量原子性、跨月冻结与留痕检索."""
from app.extensions import db
from app.models import Exceedance, LevelCorrection


def _create_exceedances(client, station, entry_payload, measured_at="2026-09-01 10:00"):
    client.post(
        "/api/measurements/entries",
        json=entry_payload(
            station.id,
            measured_at=measured_at,
            entries=[
                {"pollutant": "SO2", "value": 600.0},   # light
                {"pollutant": "NO2", "value": 300.0},   # moderate
                {"pollutant": "PM25", "value": 40.0},
            ],
        ),
    )


def _ids_by_pollutant():
    return {row.pollutant: row.id for row in Exceedance.query.all()}


# ---------------------------------------------------------------------------
# 单条修正
# ---------------------------------------------------------------------------

def test_correction_requires_reason_and_operator(client, station, entry_payload):
    _create_exceedances(client, station, entry_payload)
    target = Exceedance.query.filter_by(pollutant="SO2").first()

    resp = client.post(
        "/api/exceedances/%d/corrections" % target.id,
        json={"level": "severe", "operator": "王敏"},
    )
    assert resp.status_code == 422
    assert "reason" in resp.get_json()["error"]["fields"]

    resp = client.post(
        "/api/exceedances/%d/corrections" % target.id,
        json={"level": "severe", "reason": "有理由"},
    )
    assert resp.status_code == 422
    assert "operator" in resp.get_json()["error"]["fields"]


def test_correction_rejects_invalid_and_unchanged_level(client, station, entry_payload):
    _create_exceedances(client, station, entry_payload)
    target = Exceedance.query.filter_by(pollutant="SO2").first()

    resp = client.post(
        "/api/exceedances/%d/corrections" % target.id,
        json={"level": "catastrophic", "reason": "理由", "operator": "王敏"},
    )
    assert resp.status_code == 422

    resp = client.post(
        "/api/exceedances/%d/corrections" % target.id,
        json={"level": target.level, "reason": "没变也要改", "operator": "王敏"},
    )
    assert resp.status_code == 422
    assert resp.get_json()["error"]["fields"]["level"] == "unchanged"


def test_single_correction_records_before_after_and_takes_effect_everywhere(
    client, station, entry_payload
):
    _create_exceedances(client, station, entry_payload)
    target = Exceedance.query.filter_by(pollutant="SO2").first()
    assert target.level == "light"

    resp = client.post(
        "/api/exceedances/%d/corrections" % target.id,
        json={"level": "severe", "reason": "周边排放源持续超排, 上调等级", "operator": "王敏"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["updated"] == 1
    assert body["correction"]["level_before"] == "light"
    assert body["correction"]["level_after"] == "severe"
    assert body["correction"]["level_before_label"] == "轻度超标"
    assert body["correction"]["level_after_label"] == "重度超标"
    assert body["correction"]["reason"].startswith("周边排放源")
    assert body["correction"]["operator"] == "王敏"
    assert body["correction"]["batch_no"]

    # 列表 / 详情 / 看板统计统一用新等级
    target = db.session.get(Exceedance, target.id)
    assert target.level == "severe"
    assert target.original_level == "light"
    assert target.level_corrected is True

    listed = client.get("/api/exceedances").get_json()
    row = next(item for item in listed["items"] if item["id"] == target.id)
    assert row["level"] == "severe"
    assert row["original_level"] == "light"
    assert row["level_corrected"] is True

    by_level = {item["key"]: item["count"] for item in listed["summary"]["by_level"]}
    assert by_level["severe"] >= 1

    detail = client.get("/api/exceedances/%d" % target.id).get_json()
    assert detail["level"] == "severe"
    assert len(detail["level_corrections"]) == 1

    # 导出使用新等级并带原始等级/修正标记列
    csv_body = client.get("/api/exceedances/export").get_data(as_text=True)
    assert "系统原始等级" in csv_body
    assert "等级是否修正" in csv_body


def test_repeated_corrections_keep_full_chain(client, station, entry_payload):
    _create_exceedances(client, station, entry_payload)
    target = Exceedance.query.filter_by(pollutant="SO2").first()

    for level in ("moderate", "severe", "light"):
        resp = client.post(
            "/api/exceedances/%d/corrections" % target.id,
            json={"level": level, "reason": "第 %s 次复核调整" % level, "operator": "王敏"},
        )
        assert resp.status_code == 200

    logs = LevelCorrection.query.filter_by(exceedance_id=target.id).order_by(
        LevelCorrection.id.asc()
    ).all()
    assert [(log.level_before, log.level_after) for log in logs] == [
        ("light", "moderate"),
        ("moderate", "severe"),
        ("severe", "light"),
    ]
    detail = client.get("/api/exceedances/%d" % target.id).get_json()
    assert detail["correction_count"] == 3
    # 链条最后一条之后有效等级回到 light, 但仍然属于“被修正过”
    assert detail["level"] == "light"
    assert detail["level_corrected"] is True


def test_reevaluating_measurement_keeps_manual_level(client, station, entry_payload):
    _create_exceedances(client, station, entry_payload)
    target = Exceedance.query.filter_by(pollutant="SO2").first()
    client.post(
        "/api/exceedances/%d/corrections" % target.id,
        json={"level": "severe", "reason": "人工上调", "operator": "王敏"},
    )

    # 覆盖录入重新触发自动判定, 人工等级保留, 系统原始等级随新倍数更新
    resp = client.post(
        "/api/measurements/entries",
        json=entry_payload(
            station.id,
            measured_at="2026-09-01 10:00",
            overwrite=True,
            entries=[{"pollutant": "SO2", "value": 620.0}],
        ),
    )
    assert resp.status_code in (200, 201)
    target = db.session.get(Exceedance, target.id)
    assert target.level == "severe"
    assert target.level_corrected is True
    assert target.original_level == "light"
    assert LevelCorrection.query.filter_by(exceedance_id=target.id).count() == 1


# ---------------------------------------------------------------------------
# 批量修正
# ---------------------------------------------------------------------------

def test_batch_correction_is_atomic(client, station, entry_payload):
    _create_exceedances(client, station, entry_payload)
    ids = _ids_by_pollutant()

    # 第二条目标等级与当前一致 -> 整批应被拒绝, 任何一条都不改
    resp = client.post(
        "/api/exceedances/corrections/batch",
        json={
            "operator": "管理员",
            "reason": "批量统一上调",
            "items": [
                {"id": ids["SO2"], "level": "severe"},
                {"id": ids["NO2"], "level": "moderate"},  # 与当前一致
            ],
        },
    )
    assert resp.status_code == 422
    payload = resp.get_json()["error"]
    failure_ids = [item["id"] for item in payload["fields"]["failures"]]
    assert ids["NO2"] in failure_ids

    assert db.session.get(Exceedance, ids["SO2"]).level == "light"
    assert LevelCorrection.query.count() == 0


def test_batch_correction_succeeds_with_shared_batch_no(client, station, entry_payload):
    _create_exceedances(client, station, entry_payload)
    ids = _ids_by_pollutant()

    resp = client.post(
        "/api/exceedances/corrections/batch",
        json={
            "operator": "管理员",
            "reason": "月度复核统一调整",
            "items": [
                {"id": ids["SO2"], "level": "severe"},
                {"id": ids["NO2"], "level": "severe"},
            ],
        },
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["updated"] == 2
    batch_nos = {item["batch_no"] for item in body["corrections"]}
    assert len(batch_nos) == 1
    logs = LevelCorrection.query.filter(LevelCorrection.exceedance_id.in_(
        [ids["SO2"], ids["NO2"]]
    )).all()
    assert {log.operator for log in logs} == {"管理员"}
    assert {log.batch_no for log in logs} == batch_nos


def test_batch_correction_per_item_reason_or_common_reason(client, station, entry_payload):
    _create_exceedances(client, station, entry_payload)
    ids = _ids_by_pollutant()

    # 没有公共理由, 且其中一条没给理由 -> 拒绝
    resp = client.post(
        "/api/exceedances/corrections/batch",
        json={
            "operator": "管理员",
            "items": [
                {"id": ids["SO2"], "level": "severe", "reason": "单独理由"},
                {"id": ids["NO2"], "level": "severe"},
            ],
        },
    )
    assert resp.status_code == 422

    # 每条自带理由也合法
    resp = client.post(
        "/api/exceedances/corrections/batch",
        json={
            "operator": "管理员",
            "items": [
                {"id": ids["SO2"], "level": "severe", "reason": "SO2 单独理由"},
                {"id": ids["NO2"], "level": "severe", "reason": "NO2 单独理由"},
            ],
        },
    )
    assert resp.status_code == 200


def test_batch_correction_rejects_duplicate_and_missing_ids(client, station, entry_payload):
    _create_exceedances(client, station, entry_payload)
    ids = _ids_by_pollutant()

    dup = client.post(
        "/api/exceedances/corrections/batch",
        json={
            "operator": "管理员",
            "reason": "重复选择",
            "items": [
                {"id": ids["SO2"], "level": "severe"},
                {"id": ids["SO2"], "level": "moderate"},
            ],
        },
    )
    assert dup.status_code == 422

    missing = client.post(
        "/api/exceedances/corrections/batch",
        json={
            "operator": "管理员",
            "reason": "含不存在记录",
            "items": [
                {"id": ids["SO2"], "level": "severe"},
                {"id": 9999, "level": "severe"},
            ],
        },
    )
    assert missing.status_code == 422
    assert any(
        item["id"] == 9999 and item["code"] == "missing"
        for item in missing.get_json()["error"]["fields"]["failures"]
    )
    assert LevelCorrection.query.count() == 0


# ---------------------------------------------------------------------------
# 跨月冻结
# ---------------------------------------------------------------------------

def test_correction_blocked_for_published_month(client, station, entry_payload):
    client.post(
        "/api/measurements/entries",
        json=entry_payload(
            station.id,
            measured_at="2026-08-15 10:00",
            entries=[{"pollutant": "SO2", "value": 600.0}],
        ),
    )
    target = Exceedance.query.filter_by(pollutant="SO2").first()

    # 公布 2026-08
    resp = client.post(
        "/api/exceedances/publications",
        json={"period_month": "2026-08", "published_by": "管理员", "remark": "月报已发布"},
    )
    assert resp.status_code == 200

    blocked = client.post(
        "/api/exceedances/%d/corrections" % target.id,
        json={"level": "severe", "reason": "想改已公布月份", "operator": "王敏"},
    )
    assert blocked.status_code == 422
    assert blocked.get_json()["error"]["fields"]["level"] == "month_published"
    assert db.session.get(Exceedance, target.id).level == "light"
    assert LevelCorrection.query.count() == 0

    # 批量场景里混入已公布月份记录同样整体失败
    client.post(
        "/api/measurements/entries",
        json=entry_payload(
            station.id,
            measured_at="2026-09-15 10:00",
            entries=[{"pollutant": "NO2", "value": 300.0}],
        ),
    )
    september = Exceedance.query.filter(Exceedance.pollutant == "NO2").first()
    resp = client.post(
        "/api/exceedances/corrections/batch",
        json={
            "operator": "管理员",
            "reason": "跨月批量",
            "items": [
                {"id": target.id, "level": "severe"},
                {"id": september.id, "level": "severe"},
            ],
        },
    )
    assert resp.status_code == 422
    assert db.session.get(Exceedance, september.id).level == "moderate"


def test_publish_month_validation_and_duplicate(client):
    resp = client.post(
        "/api/exceedances/publications",
        json={"period_month": "2026-8", "published_by": "管理员"},
    )
    assert resp.status_code == 422

    client.post(
        "/api/exceedances/publications",
        json={"period_month": "2026-07", "published_by": "管理员"},
    )
    dup = client.post(
        "/api/exceedances/publications",
        json={"period_month": "2026-07", "published_by": "管理员"},
    )
    assert dup.status_code == 409

    listed = client.get("/api/exceedances/publications").get_json()
    assert [item["period_month"] for item in listed["items"]] == ["2026-07"]


# ---------------------------------------------------------------------------
# 留痕检索
# ---------------------------------------------------------------------------

def test_correction_logs_searchable_by_operator_and_time(client, station, entry_payload):
    _create_exceedances(client, station, entry_payload)
    ids = _ids_by_pollutant()
    client.post(
        "/api/exceedances/%d/corrections" % ids["SO2"],
        json={"level": "severe", "reason": "王敏上调", "operator": "王敏"},
    )
    client.post(
        "/api/exceedances/%d/corrections" % ids["NO2"],
        json={"level": "severe", "reason": "李静上调", "operator": "李静"},
    )

    by_operator = client.get("/api/exceedances/corrections?operator=%E7%8E%8B%E6%95%8F").get_json()
    assert by_operator["total"] == 1
    assert by_operator["items"][0]["operator"] == "王敏"
    assert by_operator["summary"]["operator_count"] == 1

    by_exceedance = client.get(
        "/api/exceedances/corrections?exceedance_id=%d" % ids["NO2"]
    ).get_json()
    assert by_exceedance["total"] == 1

    # 时间区间: 只查未来日期应无结果
    future = client.get("/api/exceedances/corrections?date_from=2099-01-01").get_json()
    assert future["total"] == 0

    # 月份与修正后等级过滤
    month_filtered = client.get(
        "/api/exceedances/corrections?period_month=2026-09&level_after=severe"
    ).get_json()
    assert month_filtered["total"] == 2

    # 导出留痕 CSV
    csv_body = client.get("/api/exceedances/corrections/export").get_data(as_text=True)
    assert "批次号" in csv_body and "修正前等级" in csv_body and "修正后等级" in csv_body
    assert "王敏" in csv_body
