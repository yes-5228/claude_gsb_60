"""超标等级人工修正留痕 (append-only).

每次人工修正 (单条或批量) 都写入一条不可变记录, 保存修正前后的等级、
修正理由、操作人与批次号; 同一条超标记录被反复修正时可串成完整变化链。
"""
from datetime import datetime

from ..domain.constants import EXCEEDANCE_LEVEL_LABELS, label_of
from ..extensions import db
from .base import TimestampMixin, iso


class LevelCorrection(TimestampMixin, db.Model):
    __tablename__ = "level_corrections"

    id = db.Column(db.Integer, primary_key=True)
    exceedance_id = db.Column(
        db.Integer,
        db.ForeignKey("exceedances.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    measurement_id = db.Column(db.Integer, nullable=False, index=True)
    station_id = db.Column(db.Integer, nullable=False, index=True)
    pollutant = db.Column(db.String(16), nullable=False, index=True)
    period_month = db.Column(db.String(7), nullable=False, index=True)  # 超标数据所属月份 YYYY-MM
    level_before = db.Column(db.String(16), nullable=False)
    level_after = db.Column(db.String(16), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    operator = db.Column(db.String(64), nullable=False, index=True)
    batch_no = db.Column(db.String(40), nullable=False, index=True)  # 同一次批量修正共享批次号
    corrected_at = db.Column(db.DateTime, nullable=False, default=datetime.now, index=True)

    exceedance = db.relationship("Exceedance", back_populates="level_corrections")

    def to_dict(self, include_exceedance=False):
        payload = {
            "id": self.id,
            "exceedance_id": self.exceedance_id,
            "measurement_id": self.measurement_id,
            "station_id": self.station_id,
            "station_name": self.exceedance.station.name if self.exceedance and self.exceedance.station else None,
            "station_code": self.exceedance.station.code if self.exceedance and self.exceedance.station else None,
            "pollutant": self.pollutant,
            "period_month": self.period_month,
            "measured_at": iso(self.exceedance.measured_at) if self.exceedance else None,
            "level_before": self.level_before,
            "level_before_label": label_of(EXCEEDANCE_LEVEL_LABELS, self.level_before),
            "level_after": self.level_after,
            "level_after_label": label_of(EXCEEDANCE_LEVEL_LABELS, self.level_after),
            "reason": self.reason,
            "operator": self.operator,
            "batch_no": self.batch_no,
            "corrected_at": iso(self.corrected_at),
            "created_at": iso(self.created_at),
        }
        if include_exceedance and self.exceedance:
            payload["exceedance"] = self.exceedance.to_dict()
        return payload

    def __repr__(self):
        return "<LevelCorrection %s %s->%s by %s>" % (
            self.exceedance_id, self.level_before, self.level_after, self.operator,
        )
