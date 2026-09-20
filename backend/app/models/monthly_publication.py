"""已对外公布的监测月份.

月份一旦公布即视为定稿: 其后发生的超标等级人工修正不得改变该月已经
对外公布的结果, 因此公布月份内的超标记录禁止再做等级修正。
"""
from ..extensions import db
from .base import TimestampMixin, iso


class MonthlyPublication(TimestampMixin, db.Model):
    __tablename__ = "monthly_publications"

    id = db.Column(db.Integer, primary_key=True)
    period_month = db.Column(db.String(7), nullable=False, unique=True, index=True)  # YYYY-MM
    published_by = db.Column(db.String(64), nullable=False)
    published_at = db.Column(db.DateTime, nullable=False)
    remark = db.Column(db.Text)

    def to_dict(self):
        return {
            "id": self.id,
            "period_month": self.period_month,
            "published_by": self.published_by,
            "published_at": iso(self.published_at),
            "remark": self.remark,
            "created_at": iso(self.created_at),
        }

    def __repr__(self):
        return "<MonthlyPublication %s by %s>" % (self.period_month, self.published_by)
