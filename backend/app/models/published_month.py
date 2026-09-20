"""月份对外公布与公布时点的超标等级快照.

业务口径: 某月数据一旦对外公布, 该月所有超标记录的等级即被冻结。
此后即使发生跨月修正, 实时列表/统计使用新等级, 已公布月份对外口径保持不变。
冻结值以快照行的形式持久化, 不再依赖之后可能变化的 exceedances.level。
"""
from ..extensions import db
from .base import TimestampMixin, iso


class PublishedMonth(TimestampMixin, db.Model):
    __tablename__ = "published_months"

    id = db.Column(db.Integer, primary_key=True)
    month = db.Column(db.String(7), nullable=False, unique=True, index=True)  # YYYY-MM
    published_at = db.Column(db.DateTime, nullable=False, default=db.func.now())
    published_by = db.Column(db.String(64), nullable=False, default="系统")
    remark = db.Column(db.Text)

    snapshots = db.relationship(
        "PublishedExceedanceSnapshot",
        back_populates="published_month",
        cascade="all, delete-orphan",
    )

    def to_dict(self, include_counts=False):
        payload = {
            "id": self.id,
            "month": self.month,
            "published_at": iso(self.published_at),
            "published_by": self.published_by,
            "remark": self.remark,
        }
        if include_counts:
            payload["snapshot_count"] = len(self.snapshots)
        return payload


class PublishedExceedanceSnapshot(db.Model):
    """公布时点单条超标记录的等级快照 (不可变)。"""

    __tablename__ = "published_exceedance_snapshots"

    id = db.Column(db.Integer, primary_key=True)
    publish_id = db.Column(
        db.Integer,
        db.ForeignKey("published_months.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    month = db.Column(db.String(7), nullable=False, index=True)
    exceedance_id = db.Column(
        db.Integer,
        db.ForeignKey("exceedances.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    station_id = db.Column(db.Integer, nullable=False, index=True)
    station_code = db.Column(db.String(64))
    station_name = db.Column(db.String(128))
    pollutant = db.Column(db.String(16), nullable=False)
    measured_at = db.Column(db.DateTime, nullable=False)
    value = db.Column(db.Float, nullable=False)
    limit_value = db.Column(db.Float, nullable=False)
    exceed_ratio = db.Column(db.Float, nullable=False)
    level = db.Column(db.String(16), nullable=False)
    status = db.Column(db.String(16), nullable=False)

    published_month = db.relationship("PublishedMonth", back_populates="snapshots")

    __table_args__ = (
        db.UniqueConstraint("publish_id", "exceedance_id", name="uq_publish_exceedance"),
    )

    def to_dict(self, level_labels=None, status_labels=None):
        payload = {
            "id": self.id,
            "month": self.month,
            "exceedance_id": self.exceedance_id,
            "station_id": self.station_id,
            "station_code": self.station_code,
            "station_name": self.station_name,
            "pollutant": self.pollutant,
            "measured_at": iso(self.measured_at),
            "value": self.value,
            "limit_value": self.limit_value,
            "exceed_ratio": self.exceed_ratio,
            "level": self.level,
            "status": self.status,
        }
        if level_labels is not None:
            payload["level_label"] = level_labels.get(self.level, self.level)
        if status_labels is not None:
            payload["status_label"] = status_labels.get(self.status, self.status)
        return payload
