// Checks independent reviewer form state against an isolated local database.
const {chromium}=require('playwright');
const {spawn}=require('node:child_process');
const path=require('node:path'),net=require('node:net'),fs=require('node:fs'),os=require('node:os');
const assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');
const temp=fs.mkdtempSync(path.join(os.tmpdir(),'refund-forms-'));
let server,browser;
const waitFor=async fn=>{for(let i=0;i<100;i++){if(await fn())return;await new Promise(r=>setTimeout(r,100))}throw new Error('Backend did not start')};
(async()=>{
  const port=await new Promise(resolve=>{const socket=net.createServer();socket.listen(0,'127.0.0.1',()=>{const p=socket.address().port;socket.close(()=>resolve(p))})});
  const base=`http://127.0.0.1:${port}`;
  server=spawn(path.join(root,process.platform==='win32'?'.venv/Scripts/python.exe':'.venv/bin/python'),
    ['-m','uvicorn','refundops.main:app','--host','127.0.0.1','--port',String(port)],
    {cwd:root,env:{...process.env,PYTHONPATH:path.join(root,'backend'),REFUNDOPS_DB:path.join(temp,'app.sqlite3'),REFUNDOPS_AUTO_ANALYZE:'0',REFUNDOPS_SOURCE_POLICIES:'0',OPENROUTER_API_KEY:''},stdio:'ignore',windowsHide:true});
  await waitFor(async()=>{try{return(await fetch(base+'/api/health')).ok}catch{return false}});
  const api=async(url,body)=>{const response=await fetch(base+'/api'+url,{method:body?'POST':'GET',headers:{'X-Demo-Role':'reviewer','Content-Type':'application/json'},...(body?{body:JSON.stringify(body)}:{})});assert(response.ok,await response.clone().text());return response.json()};
  const requests=await api('/requests');
  const settled=requests.find(r=>r.external_id==='RF-1067');
  await api(`/requests/${settled.id}/decisions`,{version:settled.version,action:'rejected',amount_cents:null,reason:'Isolated test decision',idempotency_key:'reviewer-forms-test'});
  browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE||undefined});
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base);
  await page.getByRole('button',{name:/^Reviewer/}).click();
  assert.equal(await page.getByText(/Automatic routing checks|Preparing automatic routing|Routing checks|Model qualification/).count(),0);
  await page.getByRole('row',{name:'Open RF-2183',exact:true}).click();
  await page.getByLabel('Conflict resolution reason').fill('Canonical amount evidence only');
  await page.getByText('Record staff evidence or complete note review',{exact:true}).click();
  assert.equal(await page.getByLabel('Evidence review note').inputValue(),'');
  await page.getByLabel('Evidence review note').fill('Photo evidence only');
  assert.equal(await page.getByLabel('Conflict resolution reason').inputValue(),'Canonical amount evidence only');
  await page.getByRole('button',{name:'Close request',exact:true}).click();
  await page.getByRole('row',{name:'Open RF-1067',exact:true}).click();
  await page.getByText('Reopen for follow-up',{exact:true}).click();
  await page.getByLabel('Follow-up reason').fill('Independent follow-up note');
  await page.getByText('Record follow-up outcome',{exact:true}).click();
  assert.equal(await page.getByLabel('Outcome type').inputValue(),'');
  assert.equal(await page.getByLabel('Outcome note').inputValue(),'');
  await page.getByLabel('Outcome note').fill('Independent outcome note');
  assert(await page.getByRole('button',{name:'Record outcome',exact:true}).isDisabled());
  await page.getByLabel('Outcome type').selectOption('audit_pass');
  assert(await page.getByRole('button',{name:'Record outcome',exact:true}).isEnabled());
  assert.equal(await page.getByLabel('Follow-up reason').inputValue(),'Independent follow-up note');
  assert.deepEqual(errors,[]);
  console.log('Reviewer form isolation passed. Operational data untouched.');
})().catch(error=>{console.error(error);process.exitCode=1}).finally(async()=>{
  if(browser)await browser.close();
  if(server){server.kill();await new Promise(resolve=>{if(server.exitCode!==null)resolve();else server.once('exit',resolve)})}
  const cleanup=fs.realpathSync(temp),tempRoot=fs.realpathSync(os.tmpdir());
  assert.equal(path.dirname(cleanup),tempRoot,'Only remove the dedicated OS temp test directory');
  assert(path.basename(cleanup).startsWith('refund-forms-'));
  fs.rmSync(cleanup,{recursive:true,force:true});
});
