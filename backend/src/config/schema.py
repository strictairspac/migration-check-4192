from sqlalchemy import inspect,text
from src.config.database import Base,engine
import src.models.identity,src.models.batch,src.models.mapping,src.models.run,src.models.branch  # noqa: F401

# v2 为 runs 追加的分院来源列；create_all 不会修改既有表，这里做幂等补齐。
_RUN_COLUMNS={
 'origin':"VARCHAR(20) NOT NULL DEFAULT 'local'",
 'branch_code':'VARCHAR(60)',
 'original_run_id':'INTEGER',
}

def ensure_schema():
 """建表并幂等补齐既有库缺少的 v2 列/索引，旧库无需清空即可升级。"""
 dialect=engine.dialect.name
 Base.metadata.create_all(engine)
 with engine.begin() as conn:
  existing={c['name'] for c in inspect(conn).get_columns('runs')}
  for name,ddl in _RUN_COLUMNS.items():
   if name not in existing:conn.execute(text(f'ALTER TABLE runs ADD COLUMN {name} {ddl}'))
  # 同院同号只入库一次；NULL 在唯一索引中互不冲突，本地运行不受影响。
  conn.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS uq_run_branch_source ON runs (branch_code, original_run_id)'))
  if dialect=='postgresql':
   # 既有列在 v1 为 NOT NULL，分院运行不来自本地批次/映射。
   conn.execute(text('ALTER TABLE runs ALTER COLUMN batch_id DROP NOT NULL'))
   conn.execute(text('ALTER TABLE runs ALTER COLUMN mapping_id DROP NOT NULL'))
