from sqlalchemy import Column,Integer,String,JSON,DateTime,func,ForeignKey,Index,Text,text
from src.config.database import Base

_ACCEPTED = text("status = 'accepted'")


class BranchRegistration(Base):
 __tablename__='branch_registrations'
 __table_args__=(Index('uq_branch_registration_source','branch_code','original_run_id',unique=True),)
 id=Column(Integer,primary_key=True)
 branch_code=Column(String(60),nullable=False)
 original_run_id=Column(Integer,nullable=False)
 digest=Column(String(64),nullable=False)
 reference=Column(JSON,nullable=True)
 note=Column(String(500),nullable=False,default='')
 created_at=Column(DateTime,server_default=func.now())


class IntakeBatch(Base):
 """一次整批接收。仅“已接收”批次占用回执号与内容指纹，便于拒收后修正重试。"""
 __tablename__='intake_batches'
 __table_args__=(
  Index('uq_intake_accepted_receipt','receipt',unique=True,
        postgresql_where=_ACCEPTED,sqlite_where=_ACCEPTED),
  Index('uq_intake_accepted_fingerprint','fingerprint',unique=True,
        postgresql_where=_ACCEPTED,sqlite_where=_ACCEPTED),
 )
 id=Column(Integer,primary_key=True)
 receipt=Column(String(120),nullable=False)
 fingerprint=Column(String(64),nullable=False)
 status=Column(String(20),nullable=False)
 actor=Column(String(120),nullable=False,default='')
 request=Column(JSON,nullable=False)
 result=Column(JSON,nullable=False)
 created_at=Column(DateTime,server_default=func.now())


class IntakeItem(Base):
 __tablename__='intake_items'
 id=Column(Integer,primary_key=True)
 intake_id=Column(Integer,ForeignKey('intake_batches.id'),nullable=False)
 position=Column(Integer,nullable=False)
 branch_code=Column(String(60),nullable=False)
 original_run_id=Column(Integer,nullable=False)
 digest=Column(String(64),nullable=True)
 artifact=Column(JSON,nullable=False)
 local_run_id=Column(Integer,ForeignKey('runs.id'),nullable=True)
 status=Column(String(20),nullable=False)
 reason=Column(Text,nullable=True)
