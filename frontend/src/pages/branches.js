import {store,refresh} from '../stores/business.js';import {esc} from '../utils/html.js';import {table} from '../components/common/table.js';import {branches} from '../api/business.js';
import {feedback} from '../components/common/feedback.js';

const ITEM_LABELS={accepted:'已入库',existing:'已存在',rolled_back:'整批回滚',rejected:'拒收'};
const statusTag=s=>`<span class="status ${s==='accepted'?'completed':'failed'}">${ITEM_LABELS[s]||s}</span>`;

export function branchesPage(){
 const rows=store.intakes.map(b=>[
  `<b>${esc(b.receipt)}</b><small>批次 #${b.id} · ${esc(b.created_at)}</small>`,
  `<span class="status ${b.status==='accepted'?'completed':'failed'}">${b.status==='accepted'?'整批已接收':'整批拒收'}</span><small>接收${b.result?.accepted_count??0} / 拒收${b.result?.rejected_count??0} / 回滚${b.result?.rolled_back_count??0}</small>`,
  b.items.map(i=>`<small>${esc(i.branch_code)} #${i.original_run_id} ${statusTag(i.status)}${i.local_run_id?` → 本地运行 <b>${i.local_run_id}</b>`:''}${i.reason?`<br><span class="muted">${esc(i.reason)}</span>`:''}</small>`).join(''),
  `<button class="quiet" data-intake="${b.id}">核对原件</button>`
 ]);
 return `<div class="split"><section>
 <h2>接收分院整批备份</h2>
 <p>以“分院 + 原运行号”识别来源；同号不同院各自入库。原件先按分院预登记摘要核验，再写入本地运行。一份验不过整批回滚，不新增本地运行。</p>
 <form id="branch-intake-form">
  <label>选择分院备份文件（可多选，自动识别分院与原运行号）<input id="branch-files" type="file" accept=".json,application/json" multiple></label>
  <label>回执号（可留空；重试会返回原批次）<input name="receipt" placeholder="FP-20261117-AM"></label>
  <label>交接说明<input name="note" placeholder="东院+西院日班合并交来"></label>
  <label>原件清单 JSON（branch_code / original_run_id / artifact）<textarea name="items" class="code-input" rows="10" required placeholder='[{"branch_code":"东院","original_run_id":1001,"artifact":{...}}]'></textarea></label>
  <small>每份原件为 version=1 逻辑JSON备份；分院须先登记摘要。最多100份。</small>
  <button type="submit">核对并接收整批 →</button>
 </form>
 <aside class="note">回执丢失或并发重试不会新增运行，直接返回原本地编号。同一来源换了内容将整批拒收。</aside>
 <h3>登记分院摘要</h3>
 <p>接收前先登记来源摘要；同一来源换内容会被拒收。</p>
 <form id="branch-register-form">
  <div class="duo"><label>分院代码<input name="branch_code" required placeholder="东院"></label><label>原运行号<input name="original_run_id" type="number" min="1" required placeholder="1001"></label></div>
  <label>预登记摘要<input name="digest" placeholder="64位SHA-256；与原件同时提交可留空"></label>
  <label>原件（可选，提交时即时计算摘要）<input name="artifact_file" type="file" accept=".json,application/json"></label>
  <label>备注<input name="note" placeholder="由分院质控在接收前电话/邮件确认"></label>
  <button type="submit">登记摘要</button>
 </form>
 <h3>分院预登记摘要 <em>${store.registrations.length}</em></h3>
 ${table(['来源 / 摘要','参考','示例'],store.registrations.map(r=>[
  `<b>${esc(r.branch_code)} #${r.original_run_id}</b><small class="checksum">${esc(r.digest)}</small>`,
  `<small>${esc(r.note)}</small>`,
  r.reference?.demo_artifact?`<button class="quiet" data-demo="${r.id}">取示例原件</button>`:'<small class="muted">—</small>'
 ]))}
 </section><section>
 <h2>接收记录 <em>${store.intakes.length}</em></h2>
 ${table(['回执','结果','来源 / 本地编号 / 拒收原因','操作'],rows)}
 <h3>原件与本地编号核对</h3>
 <pre id="intake-verify">选择一条接收记录后点“核对原件”。</pre>
 </section></div>`;
}

export function bindBranches(){
 document.getElementById('branch-register-form')?.addEventListener('submit',async e=>{
  e.preventDefault();
  const f=e.target,b=f.querySelector('[type=submit]');b.disabled=true;
  try{
   const payload={branch_code:f.elements.branch_code.value,original_run_id:Number(f.elements.original_run_id.value),digest:f.elements.digest.value.trim()||null,note:f.elements.note.value};
   const file=f.elements.artifact_file.files[0];
   if(file)payload.artifact=JSON.parse(await file.text());
   await branches.register(payload);
   await refresh();globalThis.__rerender?.();
   feedback('已登记 '+payload.branch_code+' #'+payload.original_run_id+' 的摘要。');
  }catch(err){feedback(err.message,true);}finally{b.disabled=false;}
 });
 document.getElementById('branch-files')?.addEventListener('change',async e=>{
  try{
   const picked=await Promise.all([...e.target.files].map(async f=>{
    const artifact=JSON.parse(await f.text());
    const branch_code=(artifact.branch_code||'').trim(),original_run_id=artifact.original_run_id??artifact.run_id;
    if(!branch_code||!Number.isInteger(original_run_id))throw Error(f.name+' 缺少分院标识或原运行号');
    return {branch_code,original_run_id,artifact};
   }));
   document.querySelector('#branch-intake-form [name=items]').value=JSON.stringify(picked,null,2);
   feedback('已读取 '+picked.length+' 份原件，确认无误后提交接收。');
  }catch(err){feedback('文件读取失败：'+err.message,true);}
 });
 document.getElementById('branch-intake-form')?.addEventListener('submit',async e=>{
  e.preventDefault();
  const f=e.target,b=f.querySelector('[type=submit]');b.disabled=true;
  try{
   const items=JSON.parse(f.elements.items.value);
   const r=await branches.intake({receipt:f.elements.receipt.value.trim()||null,note:f.elements.note.value,items});
   await refresh();globalThis.__rerender?.();
   feedback(r.status==='accepted'?'整批已接收，本地运行已生成；回执 '+r.receipt:'整批拒收并已回滚，未新增本地运行；回执 '+r.receipt,r.status!=='accepted');
  }catch(err){feedback(err.message,true);}finally{b.disabled=false;}
 });
 document.querySelectorAll('[data-demo]').forEach(btn=>btn.onclick=()=>{
  const reg=store.registrations.find(r=>r.id===Number(btn.dataset.demo));
  if(!reg?.reference?.demo_artifact)return feedback('该登记没有示例原件',true);
  const form=document.getElementById('branch-intake-form');
  form.elements.items.value=JSON.stringify([{branch_code:reg.branch_code,original_run_id:reg.original_run_id,artifact:reg.reference.demo_artifact}],null,2);
  feedback('已填入示例原件，提交即可接收样例。');
 });
 document.querySelectorAll('[data-intake]').forEach(btn=>btn.onclick=async()=>{
  try{
   const v=await branches.verify(btn.dataset.intake);
   const el=document.getElementById('intake-verify');el.hidden=false;
   el.textContent=JSON.stringify(v,null,2);
   feedback(v.all_matched?'原件摘要与本地目标行均核对一致。':'存在未核对一致的项，请查看下方明细。',!v.all_matched);
  }catch(err){feedback(err.message,true);}
 });
}
