"""超标等级人工修正留痕.

每一次人工修正都会生成一条不可变记录, 即使同一条超标记录被反复修正,
也可以按先后顺序还原出每一次等级变化 (from_level -> to_level) 与修正理由。
"""
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
    station_id = db.Column(
        db.Integer, db.ForeignKey("stations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    measurement_id = db.Column(db.Integer, nullable=False, index=True)
    pollutant = db.Column(db.String(16), nullable=False, index=True)

    from_level = db.Column(db.String(16), nullable=False)
    to_level = db.Column(db.String(16), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    operator = db.Column(db.String(64), nullable=False, index=True)
    corrected_at = db.Column(db.DateTime, nullable=False, default=db.func.now(), index=True)

    # 同一次批量修正共享一个批次号, 便于按批次回溯
    batch_no = db.Column(db.String(40), index=True)
    # 修正跨越的、此前已对外公布的月份 (YYYY-MM); 为空表示未跨已公布月份
    published_month = db.Column(db.String(7), index=True)

    exceedance = db.relationship("Exceedance", back_populates="corrections")
    station = db.relationship("Station")

    def to_dict(self):
        month = self.exceedance.measured_at.strftime("%Y-%m") if self.exceedance else None
        return {
            "id": self.id,
            "exceedance_id": self.exceedance_id,
            "measurement_id": self.measurement_id,
            "station_id": self.station_id,
            "station_name": self.station.name if self.station else None,
            "station_code": self.station.code if self.station else None,
            "pollutant": self.pollutant,
            "from_level": self.from_level,
            "from_level_label": label_of(EXCEEDANCE_LEVEL_LABELS, self.from_level),
            "to_level": self.to_level,
            "to_level_label": label_of(EXCEEDANCE_LEVEL_LABELS, self.to_level),
            "reason": self.reason,
            "operator": self.operator,
            "corrected_at": iso(self.corrected_at),
            "batch_no": self.batch_no,
            "published_month": self.published_month,
            "measured_month": month,
        }

    def __repr__(self):
        return "<LevelCorrection #%s %s->%s by %s>" % (
            self.exceedance_id, self.from_level, self.to_level, self.operator,
        )
