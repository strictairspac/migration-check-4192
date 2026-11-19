from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from src.config.database import Session
from src.models.branch import BranchRegistration, IntakeBatch, IntakeItem
from src.models.run import Run, TargetRow
from src.constants.enums import TYPES
from src.services.migration import digest, key_digest
from src.utils.serialization import record

MAX_ITEMS = 100
MAX_ROWS = 2000
ITEM_FIELDS = ('position', 'branch_code', 'original_run_id', 'digest',
               'local_run_id', 'status', 'reason')


def canonical_items(items):
    """按来源排序的规范化载荷；顺序不同但内容相同的重试得到同一指纹。"""
    return sorted(
        ({'branch_code': i.branch_code.strip(), 'original_run_id': i.original_run_id,
          'digest': digest(i.artifact)} for i in items),
        key=lambda x: (x['branch_code'], x['original_run_id']))


def fingerprint_of(canonical):
    return digest(canonical)


def verify_artifact(artifact, original_run_id, branch_code=None):
    """按结构、逐行摘要与自然键核对原件；异常即原件不可信。"""
    if not isinstance(artifact, dict):
        raise ValueError('原件不是有效的JSON对象')
    if artifact.get('version') != 1:
        raise ValueError('原件备份版本不支持')
    if artifact.get('kind') != 'logical-json-snapshot':
        raise ValueError('原件不是逻辑JSON备份')
    if artifact.get('run_id') != original_run_id:
        raise ValueError('原件运行号与来源不一致')
    declared_run = artifact.get('original_run_id')
    if declared_run is not None and declared_run != original_run_id:
        raise ValueError('原件声明原运行号与来源不一致')
    declared_branch = artifact.get('branch_code')
    if branch_code and declared_branch not in (None, branch_code):
        raise ValueError('原件分院标识与来源不一致')
    rows = artifact.get('rows')
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        raise ValueError('原件行数无效')
    if artifact.get('checksum') != digest(rows):
        raise ValueError('原件checksum不匹配')
    if artifact.get('row_hashes') != [digest(r) for r in rows]:
        raise ValueError('原件逐行摘要不匹配')
    if any(not isinstance(r, dict) or set(r) != set(TYPES) for r in rows):
        raise ValueError('原件目标schema不一致')
    if len({key_digest(r) for r in rows}) != len(rows):
        raise ValueError('原件自然键重复')
    return rows


def _lock(s, *keys):
    """事务级咨询锁：并发重试按同一顺序排队，避免重复建运行。"""
    if s.get_bind().dialect.name != 'postgresql':
        return
    for key in sorted({str(k) for k in keys if k is not None}):
        s.execute(text('SELECT pg_advisory_xact_lock(hashtext(:ns), hashtext(:key))'),
                  {'ns': 'branch-intake', 'key': key})


def _registration(s, branch_code, original_run_id):
    return s.query(BranchRegistration).filter_by(
        branch_code=branch_code, original_run_id=original_run_id).first()


def _run_for(s, branch_code, original_run_id):
    return s.query(Run).filter_by(branch_code=branch_code, original_run_id=original_run_id).first()


def _local_name(s, branch_code, original_run_id):
    base = f'分院{branch_code}-{original_run_id}'[:120]
    name, suffix = base, 2
    while s.query(Run).filter_by(name=name).first():
        name = f'{base}-{suffix}'[:120]
        suffix += 1
    return name


def _materialize(s, staged):
    """把通过核对的原件落成本地运行与目标行；由调用方在同一事务提交。"""
    for item in staged:
        artifact, rows = item['artifact'], item['rows']
        if item.get('existing_id'):
            item['local_run_id'] = item['existing_id']
            item['status'] = 'existing'
            continue
        run = Run(name=_local_name(s, item['branch_code'], item['original_run_id']),
                  batch_id=None, mapping_id=None, status='completed', origin='branch',
                  branch_code=item['branch_code'], original_run_id=item['original_run_id'],
                  snapshot={'origin': 'branch', 'branch_code': item['branch_code'],
                            'original_run_id': item['original_run_id'],
                            'artifact_digest': item['digest'],
                            'batch_name': artifact.get('batch_name', ''),
                            'row_count': len(rows)},
                  progress={'chunk': 1, 'processed': len(rows), 'accepted': len(rows), 'rejected': 0},
                  recovery=[])
        s.add(run)
        s.flush()
        result = {
            'origin': 'branch', 'branch_code': item['branch_code'],
            'original_run_id': item['original_run_id'], 'artifact_digest': item['digest'],
            'source_count': len(rows), 'accepted_count': len(rows), 'rejected_count': 0,
            'accepted_rows': rows, 'rejected_rows': [], 'row_hashes': artifact['row_hashes'],
            'checksum': artifact['checksum'],
            'chunks': ([{'chunk': 1, 'processed': len(rows), 'accepted': len(rows), 'rejected': 0}]
                       if rows else []),
            # 本地运行号写回备份头，沿用既有备注/恢复流程核对目标行。
            'backup': {**artifact, 'run_id': run.id, 'branch_code': item['branch_code'],
                       'original_run_id': item['original_run_id']},
        }
        run.result = result
        for ordinal, row in enumerate(rows):
            s.add(TargetRow(run_id=run.id, ordinal=ordinal,
                            key_digest=key_digest(row), payload=row))
        item['local_run_id'] = run.id
        item['status'] = 'accepted'


def _persist(s, receipt, fingerprint, actor, request, status, items):
    summary = [{k: i.get(k) for k in ITEM_FIELDS} for i in sorted(items, key=lambda x: x['position'])]
    batch = IntakeBatch(receipt=receipt, fingerprint=fingerprint, status=status,
                        actor=actor, request=request, result={})
    s.add(batch)
    s.flush()
    batch.result = {'intake_id': batch.id, 'receipt': receipt, 'fingerprint': fingerprint,
                    'status': status,
                    'accepted_count': sum(1 for i in items if i['status'] in ('accepted', 'existing')),
                    'rejected_count': sum(1 for i in items if i['status'] == 'rejected'),
                    'rolled_back_count': sum(1 for i in items if i['status'] == 'rolled_back'),
                    'items': summary}
    for item in items:
        s.add(IntakeItem(intake_id=batch.id, position=item['position'],
                         branch_code=item['branch_code'],
                         original_run_id=item['original_run_id'],
                         digest=item.get('digest'), artifact=item['artifact'],
                         local_run_id=item.get('local_run_id'),
                         status=item['status'], reason=item.get('reason')))
    return batch


def _valid_digest(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value.lower())


def register(data, actor):
    branch_code = data.branch_code.strip()
    pub_digest = data.digest.strip() if isinstance(data.digest, str) else None
    if pub_digest and not _valid_digest(pub_digest):
        raise HTTPException(422, '预登记摘要须为64位十六进制SHA-256')
    if data.artifact is not None:
        computed = digest(data.artifact)
        if pub_digest and pub_digest != computed:
            raise HTTPException(422, '提交的摘要与原件内容不一致')
        try:
            verify_artifact(data.artifact, data.original_run_id, branch_code)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        pub_digest = computed
    if not pub_digest:
        raise HTTPException(422, '请提供预登记摘要或原件')
    with Session() as s:
        _lock(s, f'reg:{branch_code}:{data.original_run_id}')
        existing = _registration(s, branch_code, data.original_run_id)
        if existing:
            if existing.digest != pub_digest:
                raise HTTPException(409, '该分院运行号已预登记不同摘要，原件内容变更须人工核对')
            return record(existing)
        row = BranchRegistration(branch_code=branch_code, original_run_id=data.original_run_id,
                                 digest=pub_digest, reference=data.reference, note=data.note)
        s.add(row)
        try:
            s.commit()
        except IntegrityError:
            s.rollback()
            raise HTTPException(409, '该分院运行号已被并发登记，请刷新后重试')
        s.refresh(row)
        return record(row)


def list_registrations():
    with Session() as s:
        return [record(r) for r in s.query(BranchRegistration)
                .order_by(BranchRegistration.id.desc()).limit(200)]


def _prior_batch(s, fingerprint):
    """按内容指纹认领已成功接收的批次：并发重试或回执丢失时返回原批次，不重复落库。
    被拒批次不参与认领，修正登记后可原样重试。"""
    return s.query(IntakeBatch).filter_by(fingerprint=fingerprint,
                                          status='accepted').order_by(IntakeBatch.id).first()


def intake(data, actor):
    if not data.items:
        raise HTTPException(422, '接收批次至少需要一份分院备份')
    if len(data.items) > MAX_ITEMS:
        raise HTTPException(422, f'单批最多{MAX_ITEMS}份备份')
    canonical = canonical_items(data.items)
    fingerprint = fingerprint_of(canonical)
    supplied = (data.receipt or '').strip()
    receipt = supplied or f'FP-{fingerprint[:24]}'
    request = {'receipt': receipt, 'note': data.note, 'items': canonical}
    sources = sorted({(i['branch_code'], i['original_run_id']) for i in canonical})

    with Session() as s:
        _lock(s, f'batch:{receipt}', f'fp:{fingerprint}',
              *[f'src:{b}:{r}' for b, r in sources])
        prior = _prior_batch(s, fingerprint)
        if prior:
            # 回执丢失或并发重试：直接返回原先的本地运行编号，不新增。
            return _detail_view(s, prior.id)
        same_receipt = s.query(IntakeBatch).filter_by(receipt=receipt, status='accepted').first()
        if same_receipt:
            raise HTTPException(409, '该回执号已用于内容不同的批次，请核对后重试')

        staged, rejected, seen = [], [], set()
        for position, item in enumerate(data.items):
            branch_code = item.branch_code.strip()
            base = {'position': position, 'branch_code': branch_code,
                    'original_run_id': item.original_run_id, 'artifact': item.artifact}
            try:
                source = (branch_code, item.original_run_id)
                if source in seen:
                    raise ValueError('同批内来源重复，拒收')
                seen.add(source)
                registration = _registration(s, branch_code, item.original_run_id)
                if not registration:
                    raise ValueError('未找到分院预先登记的摘要，拒收')
                rows = verify_artifact(item.artifact, item.original_run_id, branch_code)
                artifact_digest = digest(item.artifact)
                if artifact_digest != registration.digest:
                    raise ValueError('原件摘要与分院预登记不一致，拒收')
                existing = _run_for(s, branch_code, item.original_run_id)
                if existing:
                    if (existing.result or {}).get('artifact_digest') != artifact_digest:
                        raise ValueError('同一分院运行号已入库不同内容，拒收')
                    base.update(digest=artifact_digest, rows=rows,
                                existing_id=existing.id, status='existing')
                else:
                    base.update(digest=artifact_digest, rows=rows, status='accepted')
                staged.append(base)
            except ValueError as exc:
                rejected.append({**base, 'status': 'rejected', 'reason': str(exc)})

        if rejected:
            # 一份验不过：整批回滚，不新增任何本地运行；已存在的运行原样保留。
            # 拒收批次不参与指纹认领：修正预登记后可用原内容重试。
            for item in staged:
                item['status'] = 'rolled_back'
                item['reason'] = '整批回滚：同批存在拒收项，本批未新增本地运行'
                item['local_run_id'] = item.get('existing_id')
            batch = _persist(s, receipt, fingerprint, actor, request, 'rejected',
                             staged + rejected)
            s.commit()
            return _detail_view(s, batch.id)

        _materialize(s, staged)
        batch = _persist(s, receipt, fingerprint, actor, request, 'accepted', staged)
        try:
            s.commit()
        except IntegrityError:
            s.rollback()
            prior = _prior_batch(s, fingerprint)
            if prior:
                return _detail_view(s, prior.id)
            raise HTTPException(409, '并发接收冲突，请刷新后重试')
        return _detail_view(s, batch.id)


def _intake_view(batch, items, with_artifact=False):
    payload = {'id': batch.id, 'receipt': batch.receipt, 'fingerprint': batch.fingerprint,
               'status': batch.status, 'actor': batch.actor,
               'created_at': batch.created_at.isoformat() if batch.created_at else None,
               'result': batch.result, 'items': []}
    for item in items:
        entry = record(item)
        if not with_artifact:
            entry.pop('artifact', None)
        payload['items'].append(entry)
    return payload


def list_items():
    with Session() as s:
        output = []
        for batch in s.query(IntakeBatch).order_by(IntakeBatch.id.desc()).limit(100):
            items = s.query(IntakeItem).filter_by(intake_id=batch.id).order_by(IntakeItem.position)
            output.append(_intake_view(batch, items))
        return output


def _detail_view(s, intake_id, with_artifact=True):
    batch = s.get(IntakeBatch, intake_id)
    if not batch:
        raise HTTPException(404, '未找到接收批次')
    items = s.query(IntakeItem).filter_by(intake_id=intake_id).order_by(IntakeItem.position)
    return _intake_view(batch, items, with_artifact=with_artifact)


def detail(intake_id):
    with Session() as s:
        return _detail_view(s, intake_id, with_artifact=True)


def verify(intake_id):
    """原件仍可核对：用预登记摘要复核留存原件，并与本地运行的目标行对照。"""
    with Session() as s:
        batch = s.get(IntakeBatch, intake_id)
        if not batch:
            raise HTTPException(404, '未找到接收批次')
        checks = []
        for item in s.query(IntakeItem).filter_by(intake_id=intake_id).order_by(IntakeItem.position):
            registration = _registration(s, item.branch_code, item.original_run_id)
            stored = digest(item.artifact)
            check = {'position': item.position, 'branch_code': item.branch_code,
                     'original_run_id': item.original_run_id,
                     'original_digest': stored,
                     'registered_digest': registration.digest if registration else None,
                     'digest_matched': bool(registration) and registration.digest == stored,
                     'artifact_checksum': (item.artifact or {}).get('checksum'),
                     'local_run_id': item.local_run_id,
                     'local_checksum': None, 'target_matched': None}
            if item.local_run_id:
                rows = [t.payload for t in s.query(TargetRow)
                        .filter_by(run_id=item.local_run_id).order_by(TargetRow.ordinal)]
                check['local_checksum'] = digest(rows)
                check['target_matched'] = check['local_checksum'] == check['artifact_checksum']
            checks.append(check)
        return {'intake_id': intake_id, 'receipt': batch.receipt, 'status': batch.status,
                'all_matched': bool(checks) and all(
                    c['digest_matched'] and c['target_matched'] is not False for c in checks),
                'items': checks}
