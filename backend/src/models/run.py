from sqlalchemy import Column,Integer,String,JSON,DateTime,func,ForeignKey,Boolean,UniqueConstraint,Index
from src.config.database import Base
class Run(Base):
 __tablename__='runs'
 # 同院同号只入库一次；本地运行两列为 NULL，不参与冲突。
 __table_args__=(Index('uq_run_branch_source','branch_code','original_run_id',unique=True),)
 id=Column(Integer,primary_key=True)
 name=Column(String(120),unique=True,nullable=False)
 batch_id=Column(Integer,ForeignKey('batches.id'),nullable=True)
 mapping_id=Column(Integer,ForeignKey('mappings.id'),nullable=True)
 status=Column(String(20),nullable=False,default='queued')
 cancel_requested=Column(Boolean,nullable=False,default=False)
 origin=Column(String(20),nullable=False,default='local')
 branch_code=Column(String(60),nullable=True)
 original_run_id=Column(Integer,nullable=True)
 snapshot=Column(JSON,nullable=False)
 progress=Column(JSON,nullable=True)
 result=Column(JSON,nullable=True)
 recovery=Column(JSON,nullable=True)
 error=Column(String(1000),nullable=True)
 created_at=Column(DateTime,server_default=func.now())
class TargetRow(Base):
 __tablename__='target_rows'
 __table_args__=(UniqueConstraint('run_id','key_digest'),)
 id=Column(Integer,primary_key=True)
 run_id=Column(Integer,ForeignKey('runs.id'),nullable=False)
 ordinal=Column(Integer,nullable=False)
 key_digest=Column(String(64),nullable=False)
 payload=Column(JSON,nullable=False)
