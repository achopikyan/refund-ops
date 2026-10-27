// Isolated fixture database; no provider calls, source workspace writes or real money.
const {chromium}=require('playwright');
const {spawn,spawnSync}=require('node:child_process');
const path=require('node:path'),fs=require('node:fs'),net=require('node:net'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),py=path.join(root,process.platform==='win32'?'.venv/Scripts/python.exe':'.venv/bin/python');
const db=path.join(root,'var',`decision-evidence-e2e-${Date.now()}.sqlite3`);
let browser,server,page;
const waitFor=async(fn,message,attempts=100)=>{for(let i=0;i<attempts;i++){if(await fn())return;await new Promise(r=>setTimeout(r,100))}throw new Error(message)};
(async()=>{
 const port=await new Promise(resolve=>{const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>resolve(p))})});
 const base=`http://127.0.0.1:${port}`;
 const env={...process.env,PYTHONPATH:path.join(root,'backend'),REFUNDOPS_DB:db,REFUNDOPS_AUTO_ANALYZE:'1',REFUNDOPS_SOURCE_POLICIES:'0',AI_PROVIDER:'openrouter',OPENROUTER_API_KEY:'',OPENROUTER_MODEL:'fixture/no-network'};
 // Pre-fill validated fixture evidence with the exact runtime key, then exercise the real API/UI.
 const fixture=`
import os,sys
fixture_db=os.environ['REFUNDOPS_DB']
from pathlib import Path
sys.path.insert(0,str(Path('backend/tests').resolve()))
from conftest import raw,csv_text,small_policy
from refundops.storage import Store
from refundops.providers import AIProvider
from refundops.analysis_pipeline import EvidencePipeline
from refundops.domain import pending_evidence,fingerprint
store=Store(fixture_db)
batch=store.import_preview(csv_text(raw(request_id='H1',decision='approved',decided_by='human',review_minutes='5'),raw(request_id='H2',amount_usd='65',decision='partial',decided_by='human',outcome_note='30% issued'),raw(request_id='H3',amount_usd='300',decision='rejected',decided_by='human',outcome_note='chargeback')),'history.csv','history');store.import_commit(batch['id'])
llm=AIProvider(store);p=EvidencePipeline(store,llm)
for data in p.history.records():
 obj=p.history.obj(data);key=p.key(obj,[])
 p.save(obj['id'],key,'completed',evidence={**pending_evidence(obj['data']),'method':'live','complete':True,'issues':[],'criteria_hash':fingerprint([]),'model_manifest':fingerprint(llm.manifest()),'analysis_key':key},attempts=1)
candidate=store.save_draft(small_policy(store.policy()['data'],7500))
store.save_draft(small_policy(store.policy()['data'],35000))
`;
 const seeded=spawnSync(py,['-c',fixture],{cwd:root,env,encoding:'utf8',windowsHide:true});assert.equal(seeded.status,0,seeded.stderr);
 // Avoid loading the supplied demonstration data: use the app factory explicitly.
 server=spawn(py,['-c',"import uvicorn; from refundops.main import create_app,app; c=app.state.store.connect(); c.execute(\"DELETE FROM history WHERE json_extract(data,'$.request_id') NOT IN ('H1','H2','H3')\"); c.execute('DELETE FROM requests'); c.close(); uvicorn.run(create_app(seed=False),host='127.0.0.1',port="+port+")"],{cwd:root,env,stdio:'ignore',windowsHide:true});
 await waitFor(async()=>{try{return(await fetch(base+'/api/health')).ok}catch{return false}},'Backend did not start');
 const api=async(url,body,method)=>{const r=await fetch(base+'/api'+url,{method:method||(body===undefined?'GET':'POST'),headers:{'X-Demo-Role':'manager','Content-Type':'application/json'},...(body===undefined?{}:{body:JSON.stringify(body)})});assert(r.ok,await r.clone().text());return r.json()};
 const policies=await api('/policies'),draft=policies.find(p=>p.status==='draft'),other=policies.filter(p=>p.status==='draft')[1],current=policies.find(p=>p.status==='active');
 const check=await api('/trials',{policy:draft.data,policy_id:draft.id});
 await api('/trials/'+check.id+'/backtest',{});
 browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE||undefined});
 page=await browser.newPage({viewport:{width:1440,height:1050}});page.setDefaultTimeout(12000);
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(base);await page.getByRole('button',{name:/^Refund Operations Manager/}).click();
 await page.locator('.sidebar').getByRole('button',{name:'Compare versions',exact:true}).click();
 await page.locator('.comparison-picker label').filter({hasText:'Policy v'+draft.version}).click();
 await page.locator('.comparison-picker label').filter({hasText:'Policy v'+other.version}).click();
 await page.getByRole('heading',{name:'Compare 3 versions',exact:true}).waitFor();
 assert.equal(await page.getByLabel('Detailed comparison version').count(),0);
 assert.equal(await page.getByText('Request by request',{exact:true}).count(),0);
 assert((await api('/policy-comparisons/backtest?policy_ids='+draft.id)).versions[0].decision_report.quality.complete_evidence===3);
 const comparison=page.getByRole('region',{name:'Version comparison',exact:true});
 let report=comparison;
 await report.getByRole('heading',{name:'Decision context',exact:true}).waitFor();
 assert.equal(await report.locator('.multi-policy-cases').count(),0);
 fs.mkdirSync(path.join(root,'var/reports/ui'),{recursive:true});
 await report.screenshot({path:path.join(root,'var/reports/ui/decision-evidence-summary.png')});
 for(const title of ['Safety & evidence','Workload & money','Segments & rules','Cases']){
  await report.getByRole('button',{name:title,exact:true}).click();assert(await report.isVisible());
  for(const p of [current,draft,other])assert(await report.locator('table').first().getByRole('columnheader',{name:'Policy v'+p.version,exact:p!==current}).isVisible());
  if(title!=='Cases')assert.equal(await report.locator('.multi-policy-cases').count(),0);
 }
 await report.getByRole('combobox').selectOption('recorded_chargeback');
 assert(await report.getByText('H3',{exact:true}).isVisible());assert.equal(await report.getByText('H1',{exact:true}).count(),0);
 await report.getByRole('button',{name:'Segments & rules',exact:true}).click();
 await report.getByRole('combobox',{name:'Segment dimension'}).selectOption('source_channel');
 assert(await report.getByText('Other / unknown',{exact:true}).isVisible());
 await page.locator('.sidebar').getByRole('button',{name:'Policies',exact:true}).click();
 await page.getByRole('button',{name:'Open Policy v'+draft.version,exact:true}).click();
 const nav=page.getByRole('navigation',{name:'Selected policy version'});
 assert.equal(await nav.getByRole('button',{name:'Performance',exact:true}).count(),0);
 await nav.getByRole('button',{name:'Backtest',exact:true}).click();
 report=page.getByRole('region',{name:'Decision evidence',exact:true});
 await report.getByRole('heading',{name:'Policy results',exact:true}).waitFor();
 assert.equal(await report.getByRole('heading',{name:'What changes',exact:true}).count(),0);
 await report.getByRole('button',{name:'Workload & money',exact:true}).click();
 assert(!/NaN|undefined/.test(await report.innerText()));
 await report.getByRole('button',{name:'Segments & rules',exact:true}).click();
 assert.equal(await report.getByRole('heading',{name:'Routing transitions',exact:true}).count(),0);
 await report.getByRole('button',{name:'Cases',exact:true}).click();
 assert.equal(await report.getByRole('columnheader',{name:/Current|baseline/}).count(),0);
 assert.equal(await report.locator('table').count(),1);
 await report.getByRole('button',{name:'Decision',exact:true}).click();
 assert.equal(await report.locator('.decision-cases').count(),0);
 await nav.getByRole('button',{name:'Shadow',exact:true}).click();
 await page.getByRole('button',{name:'Start Shadow',exact:true}).click();
 await report.getByRole('heading',{name:'No evidence in this cohort yet',exact:true}).waitFor();
 await page.getByRole('button',{name:/^Existing requests/}).click();
 assert(await report.locator('.decision-notice').getByText(/cannot qualify a release/).isVisible());

 // Runtime changes renew checks on the SAME saved version and leave Shadow off.
 const policyCount=(await api('/policies')).length;
 await api('/settings/llm',{model:'fixture/no-network-v2',enabled:false},'PUT');
 let renewed;
 await waitFor(async()=>{const list=await api('/policy-versions');renewed=list.versions.find(v=>v.id===draft.id);return renewed.checks_id!==check.id},'Checks were not renewed automatically');
 await page.getByText('Backtest is queued and will be saved automatically after extraction finishes.',{exact:true}).waitFor();
 assert.equal(await page.getByText('Checks out of date',{exact:true}).count(),0);
 const refill=`
import sys,os
from pathlib import Path
sys.path.insert(0,str(Path('backend').resolve()))
from refundops.storage import Store
from refundops.providers import AIProvider
from refundops.analysis_pipeline import EvidencePipeline
from refundops.domain import pending_evidence,fingerprint
s=Store(os.environ['REFUNDOPS_DB']);l=AIProvider(s);l.model='fixture/no-network-v2';p=EvidencePipeline(s,l)
for data in p.history.records():
 obj=p.history.obj(data);key=p.key(obj,[])
 p.save(obj['id'],key,'completed',evidence={**pending_evidence(obj['data']),'method':'live','complete':True,'issues':[],'criteria_hash':fingerprint([]),'model_manifest':fingerprint(l.manifest()),'analysis_key':key},attempts=1)
`;
 const filled=spawnSync(py,['-c',refill],{cwd:root,env,encoding:'utf8',windowsHide:true});assert.equal(filled.status,0,filled.stderr);
 await waitFor(async()=>{const r=await api('/trials/'+renewed.checks_id);return r.experiment.status==='backtested'},'Automatic replay did not finish from saved evidence',450);
 assert.equal((await api('/policies')).length,policyCount);
 assert.equal((await api('/trials/'+check.id)).experiment.status,'superseded');
 assert.equal((await api('/trials/'+renewed.checks_id)).experiment.started_at,null);
 await nav.getByRole('button',{name:'Shadow',exact:true}).click();
 await page.getByRole('button',{name:'Start Shadow',exact:true}).waitFor();
 await page.setViewportSize({width:900,height:1050});
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Unexpected page-level horizontal overflow');

 await page.locator('.sidebar').getByRole('button',{name:'Policies',exact:true}).click();
 await page.getByRole('button',{name:'Open Policy v'+current.version,exact:true}).click();
 // Current may be replayed diagnostically, but every path into Shadow stays closed.
 assert(await nav.getByRole('button',{name:'Shadow',exact:true}).isDisabled());
 await nav.getByRole('button',{name:'Backtest',exact:true}).click();
 await page.getByRole('button',{name:'Run backtest',exact:true}).click();
 await page.getByRole('region',{name:'Decision evidence',exact:true}).getByRole('heading',{name:'Policy results',exact:true}).waitFor();
 assert(await nav.getByRole('button',{name:'Shadow',exact:true}).isDisabled());
 for(const name of ['Set up Shadow','Open Shadow','Start Shadow']) {
  assert.equal(await page.getByRole('button',{name,exact:true}).count(),0,'Current must not offer '+name);
 }
 assert.equal((await api('/policies')).find(p=>p.id===current.id).status,'active');
 await nav.getByRole('button',{name:'Performance',exact:true}).click();
 const performance=page.getByRole('region',{name:'Policy performance',exact:true});
 await performance.getByRole('heading',{name:'Where ready requests go',exact:true}).waitFor();
 assert.equal(await page.locator('.sidebar').getByRole('button',{name:/performance/i}).count(),0);
 await performance.getByRole('button',{name:'Decisions & outcomes',exact:true}).click();
 assert(await performance.getByRole('heading',{name:'No decisions recorded under this version yet',exact:true}).isVisible());
 assert.equal(await performance.getByRole('heading',{name:'Where ready requests go',exact:true}).count(),0);
 await performance.getByRole('button',{name:'Execution & limits',exact:true}).click();
 assert(await performance.getByText('On',{exact:true}).isVisible());
 for(const name of ['Stop automation','Enable qualified version','Execute eligible'])assert.equal(await performance.getByRole('button',{name,exact:true}).count(),0);
 await page.setViewportSize({width:1440,height:1050});
 await performance.screenshot({path:path.join(root,'var/reports/ui/policy-performance-execution.png')});
 await performance.getByRole('button',{name:'Queue now',exact:true}).click();
 await performance.screenshot({path:path.join(root,'var/reports/ui/policy-performance-queue.png')});
 assert.deepEqual(errors,[]);
 console.log('Three-policy comparison, standalone reports, embedded Performance and always-on controls E2E passed: live-cache replay, shared comparison, safety, economics, segment and case filters, saved Backtest, manual Shadow and cohort boundaries.');
})().catch(async e=>{console.error(e);if(page)await page.screenshot({path:path.join(root,'var/reports/ui/decision-evidence-error.png')}).catch(()=>{});process.exitCode=1}).finally(async()=>{if(browser)await browser.close();if(server)server.kill()});
