"""Lightweight idempotent schema bootstrap.

项目不依赖迁移框架 (SQLite 零依赖启动)。当已有数据库缺少新版本列/表时,
在启动阶段做幂等补齐:
- 新增列以 ALTER TABLE ADD COLUMN 方式补上 (仅用于可空或带默认值的列);
- 新表直接由 SQLAlchemy metadata 创建。

全新数据库无需走这里 (db.create_all 已建出最新结构)。
"""
from sqlalchemy import inspect, text

from ..extensions import db

# table -> [(column, DDL type/default), ...]
_EXTRA_COLUMNS = {
    "exceedances": [
        ("auto_level", "VARCHAR(16) NOT NULL DEFAULT 'light'"),
        ("level_source", "VARCHAR(16) NOT NULL DEFAULT 'auto'"),
    ],
}


def ensure_schema(app=None):
    """Create missing tables and columns without touching existing data."""
    inspector = inspect(db.engine)
    db.create_all()  # 幂等: 只创建尚不存在的表

    existing_tables = set(inspector.get_table_names())
    for table, columns in _EXTRA_COLUMNS.items():
        if table not in existing_tables:
            continue  # create_all 已按最新定义建出
        present = {column["name"] for column in inspector.get_columns(table)}
        with db.engine.begin() as connection:
            for name, ddl in columns:
                if name not in present:
                    connection.execute(
                        text("ALTER TABLE %s ADD COLUMN %s %s" % (table, name, ddl))
                    )
