"""超标等级人工修正: 留痕 / 批量原子校验 / 跨已公布月份冻结 / 检索."""
from app.extensions import db
from app.models import Exceedance, LevelCorrection, PublishedMonth
from app.services import level_correction_service


def _seed_exceedances(client, station, entry_payload, measured_at="2026-08-10 10:00"):
    client.post(
        "/api/measurements/entries",
        json=entry_payload(
            station.id,
            measured_at=measured_at,
            entries=[
                {"pollutant": "SO2", "value": 600.0},   # light  (500 限值)
                {"pollutant": "NO2", "value": 300.0},   # moderate (200 限值, 1.5x)
                {"pollutant": "PM25", "value": 40.0},   # 无小时限值, 不超标
            ],
        ),
    )
    return Exceedance.query.order_by(Exceedance.id.asc()).all()


# ---- 单条修正 ---------------------------------------------------------------

def test_correction_requires_reason_and_operator(client, station, entry_payload):
    records = _seed_exceedances(client, station, entry_payload)
    response = client.post(
        "/api/exceedances/%d/corrections" % records[0].id,
        json={"level": "severe", "reason": "", "operator": "王敏"},
    )
    assert response.status_code == 422
    assert response.get_json()["error"]["fields"]["reason"] == "required"

    response = client.post(
        "/api/exceedances/%d/corrections" % records[0].id,
        json={"level": "severe", "reason": "现场复核", "operator": ""},
    )
    assert response.status_code == 422
    assert response.get_json()["error"]["fields"]["operator"] == "required"


def test_correction_must_change_level(client, station, entry_payload):
    records = _seed_exceedances(client, station, entry_payload)
    current = records[0].level
    response = client.post(
        "/api/exceedances/%d/corrections" % records[0].id,
        json={"level": current, "reason": "现场复核", "operator": "王敏"},
    )
    assert response.status_code == 422
    assert response.get_json()["error"]["fields"]["level"] == "unchanged"


def test_correction_records_before_after_and_unified_new_level(client, station, entry_payload):
    records = _seed_exceedances(client, station, entry_payload)
    target = records[0]
    assert target.level == "light"
    assert target.auto_level == "light"
    assert target.level_source == "auto"

    response = client.post(
        "/api/exceedances/%d/corrections" % target.id,
        json={"level": "severe", "reason": "现场复核监测值接近重度, 上调等级", "operator": "王敏"},
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["cross_published"] is False
    assert body["exceedance"]["level"] == "severe"
    assert body["exceedance"]["auto_level"] == "light"  # 系统判定等级保留
    assert body["exceedance"]["level_source"] == "manual"
    assert body["exceedance"]["level_corrected"] is True
    assert body["correction"]["from_level"] == "light"
    assert body["correction"]["to_level"] == "severe"
    assert body["correction"]["reason"].startswith("现场复核")
    assert body["correction"]["operator"] == "王敏"

    # 列表 / 看板统计 / 导出 统一使用新等级
    listed = client.get("/api/exceedances?level=severe").get_json()
    assert listed["total"] == 1
    assert listed["items"][0]["id"] == target.id
    assert listed["summary"]["by_level"][2]["count"] == 1  # severe

    detail = client.get("/api/exceedances/%d" % target.id).get_json()
    assert detail["level"] == "severe"
    assert len(detail["corrections"]) == 1
    assert detail["corrections"][0]["from_level"] == "light"
    assert detail["corrections"][0]["to_level_label"] == "重度超标"

    csv_body = client.get("/api/exceedances/export").get_data(as_text=True)
    line = [row for row in csv_body.splitlines() if str(target.id) not in row]
    assert any("人工修正" in row for row in csv_body.splitlines())
    assert line is not None


def test_repeated_corrections_keep_full_chain(client, station, entry_payload):
    records = _seed_exceedances(client, station, entry_payload)
    target = records[0]
    for level, operator in [("moderate", "王敏"), ("severe", "李静"), ("light", "王敏")]:
        response = client.post(
            "/api/exceedances/%d/corrections" % target.id,
            json={"level": level, "reason": "第 N 次复核", "operator": operator},
        )
        assert response.status_code == 200

    chain = LevelCorrection.query.filter_by(exceedance_id=target.id).order_by(
        LevelCorrection.id.asc()
    ).all()
    assert [(c.from_level, c.to_level, c.operator) for c in chain] == [
        ("light", "moderate", "王敏"),
        ("moderate", "severe", "李静"),
        ("severe", "light", "王敏"),
    ]
    assert Exceedance.query.get(target.id).level == "light"
    assert Exceedance.query.get(target.id).level_source == "manual"


def test_auto_recompute_does_not_overwrite_manual_level(client, station, entry_payload):
    records = _seed_exceedances(client, station, entry_payload)
    target = records[0]
    client.post(
        "/api/exceedances/%d/corrections" % target.id,
        json={"level": "severe", "reason": "人工上调", "operator": "王敏"},
    )

    # 用更低的值覆盖录入: 自动等级回到 light, 但生效等级仍为人工修正的 severe
    client.post(
        "/api/measurements/entries",
        json=entry_payload(
            station.id,
            measured_at="2026-08-10 10:00",
            overwrite=True,
            entries=[{"pollutant": "SO2", "value": 550.0}],
        ),
    )
    refreshed = Exceedance.query.get(target.id)
    assert refreshed.auto_level == "light"
    assert refreshed.level == "severe"
    assert refreshed.level_source == "manual"


# ---- 批量修正 ---------------------------------------------------------------

def test_batch_correction_is_all_or_nothing(client, station, entry_payload):
    records = _seed_exceedances(client, station, entry_payload)
    payload = {
        "items": [
            {"id": records[0].id, "level": "severe"},
            {"id": records[1].id, "level": records[1].level},  # 等级未变化, 不合法
        ],
        "reason": "批量上调",
        "operator": "王敏",
    }
    response = client.post("/api/exceedances/corrections/batch", json=payload)
    assert response.status_code == 422
    fields = response.get_json()["error"]["fields"]
    assert any(key.startswith("items[") for key in fields)
    # 一条都不能改
    assert Exceedance.query.get(records[0].id).level == "light"
    assert LevelCorrection.query.count() == 0


def test_batch_correction_rejects_unknown_ids_entirely(client, station, entry_payload):
    records = _seed_exceedances(client, station, entry_payload)
    response = client.post(
        "/api/exceedances/corrections/batch",
        json={
            "ids": [records[0].id, 99999],
            "level": "severe",
            "reason": "批量上调",
            "operator": "王敏",
        },
    )
    assert response.status_code == 422
    assert response.get_json()["error"]["fields"]["missing"] == [99999]
    assert Exceedance.query.get(records[0].id).level == "light"


def test_batch_correction_applies_atomically_and_shares_batch_no(client, station, entry_payload):
    records = _seed_exceedances(client, station, entry_payload)
    response = client.post(
        "/api/exceedances/corrections/batch",
        json={
            "ids": [record.id for record in records],
            "level": "severe",
            "reason": "统一上调: 同期比对结果偏高",
            "operator": "李静",
        },
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["updated"] == 2
    batch_nos = {c.batch_no for c in LevelCorrection.query.all()}
    assert batch_nos == {body["batch_no"]}
    assert all(record.level == "severe" for record in Exceedance.query.all())


def test_batch_correction_requires_reason(client, station, entry_payload):
    records = _seed_exceedances(client, station, entry_payload)
    response = client.post(
        "/api/exceedances/corrections/batch",
        json={"ids": [records[0].id], "level": "severe", "reason": "", "operator": "李静"},
    )
    assert response.status_code == 422
    assert response.get_json()["error"]["fields"]["reason"] == "required"


# ---- 月份公布 / 跨月冻结 ----------------------------------------------------

def _publish(month, operator="管理员"):
    return level_correction_service.publish_month(month, operator, remark="月度对外报送")


def test_publish_freezes_level_and_cross_month_correction_keeps_published(client, station, entry_payload):
    records = _seed_exceedances(client, station, entry_payload, measured_at="2026-07-15 10:00")
    target = records[0]
    result = _publish("2026-07")
    assert result["snapshot_count"] == 2

    # 公布之后 (跨月) 修正该记录等级
    response = client.post(
        "/api/exceedances/%d/corrections" % target.id,
        json={"level": "severe", "reason": "8 月复核发现 7 月数据等级偏低", "operator": "王敏"},
    )
    body = response.get_json()
    assert body["cross_published"] is True
    assert body["published_month"] == "2026-07"

    # 实时口径使用新等级
    assert Exceedance.query.get(target.id).level == "severe"

    # 已公布月份的对外口径仍是公布时冻结的旧等级
    frozen = client.get("/api/exceedances/published-months/2026-07/exceedances").get_json()
    frozen_row = [row for row in frozen["items"] if row["exceedance_id"] == target.id][0]
    assert frozen_row["level"] == "light"
    assert frozen_row["level_label"] == "轻度超标"

    frozen_summary = client.get("/api/exceedances/published-months/2026-07").get_json()
    level_map = {item["key"]: item["count"] for item in frozen_summary["level_summary"]["by_level"]}
    assert level_map == {"light": 1, "moderate": 1, "severe": 0}

    # 留痕上带跨公布月份标记
    correction = LevelCorrection.query.filter_by(exceedance_id=target.id).one()
    assert correction.published_month == "2026-07"


def test_publish_same_month_twice_conflicts(client, station, entry_payload):
    _seed_exceedances(client, station, entry_payload, measured_at="2026-06-15 10:00")
    _publish("2026-06")
    from app.errors import ConflictError

    try:
        _publish("2026-06")
        assert False, "重复公布应当冲突"
    except ConflictError:
        pass


def test_published_month_listing_and_404(client, station, entry_payload):
    listed = client.get("/api/exceedances/published-months").get_json()
    assert listed["items"] == []

    response = client.get("/api/exceedances/published-months/2099-01")
    assert response.status_code == 404


# ---- 留痕检索 ---------------------------------------------------------------

def test_correction_history_filterable_by_operator_and_time(client, station, entry_payload):
    records = _seed_exceedances(client, station, entry_payload, measured_at="2026-08-10 10:00")
    client.post(
        "/api/exceedances/%d/corrections" % records[0].id,
        json={"level": "severe", "reason": "王敏复核", "operator": "王敏"},
    )
    client.post(
        "/api/exceedances/%d/corrections" % records[1].id,
        json={"level": "light", "reason": "李静复核", "operator": "李静"},
    )

    by_wang = client.get("/api/exceedances/corrections?operator=王敏").get_json()
    assert by_wang["total"] == 1
    assert by_wang["items"][0]["operator"] == "王敏"
    assert "王敏" in by_wang["summary"]["operators"]

    by_record = client.get(
        "/api/exceedances/corrections?exceedance_id=%d" % records[1].id
    ).get_json()
    assert by_record["total"] == 1
    assert by_record["items"][0]["to_level"] == "light"

    # 时间窗: 明天之后无记录
    none_future = client.get("/api/exceedances/corrections?date_from=2099-01-01").get_json()
    assert none_future["total"] == 0

    # 时间窗: 今天应包含全部
    today = client.get("/api/exceedances/corrections?date_from=2020-01-01").get_json()
    assert today["total"] == 2


def test_correction_history_can_filter_cross_published(client, station, entry_payload):
    records = _seed_exceedances(client, station, entry_payload, measured_at="2026-07-15 10:00")
    _publish("2026-07")
    client.post(
        "/api/exceedances/%d/corrections" % records[0].id,
        json={"level": "severe", "reason": "跨月修正", "operator": "王敏"},
    )
    records_more = _seed_exceedances(
        client, station, entry_payload, measured_at="2026-08-20 10:00"
    )
    client.post(
        "/api/exceedances/%d/corrections" % records_more[0].id,
        json={"level": "severe", "reason": "当月修正", "operator": "王敏"},
    )

    cross = client.get("/api/exceedances/corrections?cross_published=true").get_json()
    assert cross["total"] == 1
    assert cross["items"][0]["published_month"] == "2026-07"
    assert cross["summary"]["cross_published_count"] == 1
