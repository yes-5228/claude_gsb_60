"""超标记录 (含人工标注)."""
from ..domain.constants import (
    EXCEEDANCE_LEVEL_LABELS,
    EXCEEDANCE_STATUS_LABELS,
    PERIOD_LABELS,
    label_of,
)
from ..extensions import db
from .base import TimestampMixin, iso


class Exceedance(TimestampMixin, db.Model):
    __tablename__ = "exceedances"

    id = db.Column(db.Integer, primary_key=True)
    measurement_id = db.Column(
        db.Integer,
        db.ForeignKey("measurements.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    station_id = db.Column(
        db.Integer, db.ForeignKey("stations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    pollutant = db.Column(db.String(16), nullable=False, index=True)
    period = db.Column(db.String(16), nullable=False, default="hourly")
    value = db.Column(db.Float, nullable=False)
    limit_value = db.Column(db.Float, nullable=False)
    exceed_ratio = db.Column(db.Float, nullable=False)
    # level: 当前生效等级 (列表/详情/看板/统计/导出统一使用), 人工修正后以修正值为准
    level = db.Column(db.String(16), nullable=False, default="light", index=True)
    # auto_level: 按 GB 3095-2012 倍数规则自动判定的等级, 仅随监测数据重算, 不被人工修正改动
    auto_level = db.Column(db.String(16), nullable=False, default="light")
    # auto / manual: 标识当前 level 来自系统判定还是人工修正
    level_source = db.Column(db.String(16), nullable=False, default="auto")
    status = db.Column(db.String(16), nullable=False, default="pending", index=True)
    note = db.Column(db.Text)
    annotator = db.Column(db.String(64))
    annotated_at = db.Column(db.DateTime)
    measured_at = db.Column(db.DateTime, nullable=False, index=True)

    measurement = db.relationship("Measurement", back_populates="exceedance")
    station = db.relationship("Station", back_populates="exceedances")
    corrections = db.relationship(
        "LevelCorrection",
        back_populates="exceedance",
        cascade="all, delete-orphan",
        order_by="LevelCorrection.corrected_at.desc()",
    )

    def to_dict(self, include_relations=False):
        payload = {
            "id": self.id,
            "measurement_id": self.measurement_id,
            "station_id": self.station_id,
            "pollutant": self.pollutant,
            "pollutant_label": self.measurement.pollutant_label() if self.measurement else self.pollutant,
            "period": self.period,
            "period_label": label_of(PERIOD_LABELS, self.period),
            "value": self.value,
            "limit_value": self.limit_value,
            "exceed_ratio": self.exceed_ratio,
            "level": self.level,
            "level_label": label_of(EXCEEDANCE_LEVEL_LABELS, self.level),
            "auto_level": self.auto_level,
            "auto_level_label": label_of(EXCEEDANCE_LEVEL_LABELS, self.auto_level),
            "level_source": self.level_source,
            "level_corrected": self.level_source == "manual",
            "status": self.status,
            "status_label": label_of(EXCEEDANCE_STATUS_LABELS, self.status),
            "note": self.note,
            "annotator": self.annotator,
            "annotated_at": iso(self.annotated_at),
            "measured_at": iso(self.measured_at),
            "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at),
            "station_name": self.station.name if self.station else None,
            "station_code": self.station.code if self.station else None,
            "unit": self.measurement.unit if self.measurement else None,
            "correction_count": len(self.corrections) if "corrections" in self.__dict__ else None,
        }
        if include_relations:
            payload["measurement"] = self.measurement.to_dict(include_station=True)
            payload["corrections"] = [item.to_dict() for item in self.corrections]
        return payload

    def __repr__(self):
        return "<Exceedance %s %s %.2f>" % (self.station_id, self.pollutant, self.value)
