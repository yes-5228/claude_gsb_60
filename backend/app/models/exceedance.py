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
    level = db.Column(db.String(16), nullable=False, default="light", index=True)
    # 系统按超标倍数自动判定的原始等级; 人工修正只改 level, 原始值始终保留。
    original_level = db.Column(db.String(16), nullable=False, default="light")
    level_corrected = db.Column(db.Boolean, nullable=False, default=False, index=True)
    status = db.Column(db.String(16), nullable=False, default="pending", index=True)
    note = db.Column(db.Text)
    annotator = db.Column(db.String(64))
    annotated_at = db.Column(db.DateTime)
    measured_at = db.Column(db.DateTime, nullable=False, index=True)

    measurement = db.relationship("Measurement", back_populates="exceedance")
    station = db.relationship("Station", back_populates="exceedances")
    level_corrections = db.relationship(
        "LevelCorrection",
        back_populates="exceedance",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="LevelCorrection.corrected_at.asc(), LevelCorrection.id.asc()",
    )

    @property
    def period_month(self):
        return self.measured_at.strftime("%Y-%m") if self.measured_at else None

    def to_dict(self, include_relations=False, include_corrections=False, published_months=None):
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
            "original_level": self.original_level,
            "original_level_label": label_of(EXCEEDANCE_LEVEL_LABELS, self.original_level),
            "level_corrected": bool(self.level_corrected),
            "period_month": self.period_month,
            "month_published": (
                self.period_month in published_months if published_months is not None else None
            ),
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
        }
        if include_relations and self.measurement:
            payload["measurement"] = self.measurement.to_dict(include_station=True)
        if include_corrections:
            payload["level_corrections"] = [item.to_dict() for item in self.level_corrections]
            payload["correction_count"] = len(self.level_corrections)
        return payload

    def __repr__(self):
        return "<Exceedance %s %s %.2f>" % (self.station_id, self.pollutant, self.value)
