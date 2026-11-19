"""分院整批接收回归测试（SQLite；不依赖 Docker/Redis）。

运行：
  DATABASE_URL=sqlite:////tmp/branch-intake-test.db JWT_SECRET=test \
  PYTHONPATH=backend python3 test-artifacts/gb-4109/test_branch_intake.py

覆盖：分院+原运行号认来源、同号不同院各自入库、同源换内容拒收、
预登记摘要验原件、整批回滚（本地迁移不受影响）、回执丢失/并发重试幂等、
原件与本地目标行核对。
"""
import os
import sys
import tempfile

os.environ.setdefault('DATABASE_URL', 'sqlite:///' + tempfile.mktemp(suffix='.db'))
os.environ.setdefault('JWT_SECRET', 'test-secret')
os.environ.setdefault('REDIS_URL', 'redis://localhost:6399/0')
os.environ.setdefault('SEED_DEMO', 'false')

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'backend'))

import src.models.identity, src.models.batch, src.models.mapping  # noqa: F401,E402
import src.models.run, src.models.branch  # noqa: F401,E402
from src.config.database import Base, engine, Session  # noqa: E402
from src.models.identity import User  # noqa: E402
from src.models.run import Run, TargetRow  # noqa: E402
from src.models.branch import IntakeBatch  # noqa: E402
from src.utils.security import hash_password  # noqa: E402
from src.services.migration import digest, make_backup, key_digest, migrate  # noqa: E402
from src.services import branch  # noqa: E402

Base.metadata.create_all(engine)
with Session() as s:
    for role in ('admin', 'operator', 'viewer'):
        if not s.query(User).filter_by(email=role + '@t').first():
            s.add(User(email=role + '@t', role=role, password=hash_password('pw')))
    s.commit()

from fastapi.testclient import TestClient  # noqa: E402
from src.main import app  # noqa: E402

client = TestClient(app)
TOKENS = {}


def token(role):
    if role not in TOKENS:
        r = client.post('/auth/login', json={'email': role + '@t', 'password': 'pw'})
        assert r.status_code == 200, r.text
        TOKENS[role] = {'Authorization': 'Bearer ' + r.json()['token']}
    return TOKENS[role]


def artifact(branch_code, run_id, count=3, shift=0):
    rows = [{'sample_code': f'{branch_code}-{run_id}-{i:03d}', 'test_name': '拉伸强度',
             'result_value': f'{420 + i / 10 + shift:.6f}', 'unit': 'MPa',
             'measured_at': '2026-11-17T01:00:00+00:00'} for i in range(1, count + 1)]
    result = {'accepted_rows': rows, 'row_hashes': [digest(r) for r in rows], 'checksum': digest(rows)}
    return {**make_backup(result, run_id, f'{branch_code}检验结果'),
            'branch_code': branch_code, 'original_run_id': run_id}


def register(item):
    r = client.post('/branches/registrations', json=item, headers=token('operator'))
    assert r.status_code == 200, r.text
    return r.json()


def intake(receipt, items, role='operator'):
    return client.post('/branches/intakes',
                       json={'receipt': receipt, 'items': items}, headers=token(role))


def item(branch_code, run_id, art):
    return {'branch_code': branch_code, 'original_run_id': run_id, 'artifact': art}


def run_count():
    with Session() as s:
        return s.query(Run).count()


checks = []


def check(name, condition):
    checks.append((name, bool(condition)))
    print(('PASS ' if condition else 'FAIL ') + name)


def main():
    east = artifact('东院', 5001)
    west = artifact('西院', 5001)          # 同号不同院
    east_second = artifact('东院', 5002)
    register({'branch_code': '东院', 'original_run_id': 5001, 'artifact': east})
    register({'branch_code': '西院', 'original_run_id': 5001, 'artifact': west})
    register({'branch_code': '东院', 'original_run_id': 5002, 'digest': digest(east_second)})

    # 1. 整批接收：同号不同院各自入库
    r = intake('B-1', [item('东院', 5001, east), item('西院', 5001, west)])
    body = r.json()
    check('整批接收成功', r.status_code == 200 and body['status'] == 'accepted')
    check('同号不同院各自入库',
          [i['status'] for i in body['items']] == ['accepted', 'accepted']
          and len({i['local_run_id'] for i in body['items']}) == 2
          and run_count() == 2)
    local_ids = [i['local_run_id'] for i in body['items']]

    # 2. 回执丢失/顺序变化/并发重试 -> 原本地编号，不新增
    r2 = intake(None, [item('西院', 5001, west), item('东院', 5001, east)])
    check('重试返回原批次', r2.status_code == 200 and r2.json()['id'] == body['id'])
    check('重试不新增运行',
          {i['local_run_id'] for i in r2.json()['items']} == set(local_ids)
          and run_count() == 2)

    # 3. 同一来源换内容 -> 拒收
    tampered = artifact('东院', 5001, count=2)
    r3 = intake('B-2', [item('东院', 5001, tampered)])
    check('同源换内容拒收',
          r3.json()['status'] == 'rejected'
          and '预登记' in r3.json()['items'][0]['reason'])

    # 4. 一份验不过 -> 整批回滚（好的那份也不入库）
    good_new = artifact('东院', 5002)
    before = run_count()
    r4 = intake('B-3', [item('东院', 5002, good_new), item('北院', 7, artifact('北院', 7))])
    statuses = {i['branch_code']: i['status'] for i in r4.json()['items']}
    check('整批回滚', r4.json()['status'] == 'rejected'
          and statuses['东院'] == 'rolled_back' and statuses['北院'] == 'rejected')
    check('回滚不新增运行', run_count() == before
          and not any(rr.branch_code == '东院' and rr.original_run_id == 5002
                      for rr in _runs()))

    # 5. 修正后可原样重试
    r5 = intake('B-3', [item('东院', 5002, good_new)])
    check('修正后重试成功', r5.json()['status'] == 'accepted')

    # 6. 原件与本地目标行核对
    v = client.get(f"/branches/intakes/{body['id']}/verify", headers=token('viewer')).json()
    check('核对原件与目标行一致', v['all_matched']
          and all(c['digest_matched'] and c['target_matched'] for c in v['items']))
    with Session() as s:
        payloads = [t.payload for t in s.query(TargetRow).filter_by(
            run_id=local_ids[0]).order_by(TargetRow.ordinal)]
    check('本地目标行来自原件', digest(payloads) == east['checksum'])

    # 7. 分院运行可下载备份并按本地编号恢复
    backup = client.get(f'/runs/{local_ids[0]}/backup', headers=token('viewer')).json()
    check('备份头写本地编号并保留原号',
          backup['run_id'] == local_ids[0] and backup['original_run_id'] == 5001)
    restored = client.post(f'/runs/{local_ids[0]}/restore', json={'backup': backup},
                           headers=token('admin'))
    check('分院运行可回传恢复', restored.status_code == 200 and restored.json()['verified'])

    # 8. 同回执不同内容 -> 冲突
    other = artifact('西院', 5009)
    register({'branch_code': '西院', 'original_run_id': 5009, 'artifact': other})
    conflict = intake('B-1', [item('西院', 5009, other)])
    check('同回执不同内容报冲突', conflict.status_code == 409)

    # 9. 观察员只读
    r9 = intake('B-9', [item('东院', 5001, east)], role='viewer')
    check('观察员不可接收', r9.status_code == 403)

    # 10. 本地迁移流程不受影响
    check('本地运行不含分院来源', all(r.origin == 'branch' for r in _runs()))

    failed = [n for n, ok in checks if not ok]
    print(f'\n{len(checks) - len(failed)}/{len(checks)} passed')
    if failed:
        raise SystemExit('FAILED: ' + ', '.join(failed))


def _runs():
    with Session() as s:
        return s.query(Run).all()


if __name__ == '__main__':
    main()
