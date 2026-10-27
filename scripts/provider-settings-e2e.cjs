// Provider selection only; dummy credentials never reach an external service.
const {chromium}=require('playwright');
const {spawn,spawnSync}=require('node:child_process');
const path=require('node:path'),net=require('node:net'),fs=require('node:fs'),os=require('node:os');
const assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),temp=fs.mkdtempSync(path.join(os.tmpdir(),'refund-provider-'));
let server,browser;
(async()=>{
 const port=await new Promise(resolve=>{const socket=net.createServer();socket.listen(0,'127.0.0.1',()=>{const p=socket.address().port;socket.close(()=>resolve(p))})});
 const base=`http://127.0.0.1:${port}`;
 server=spawn(path.join(root,process.platform==='win32'?'.venv/Scripts/python.exe':'.venv/bin/python'),['-m','uvicorn','refundops.main:app','--host','127.0.0.1','--port',String(port)],{cwd:root,env:{...process.env,PYTHONPATH:path.join(root,'backend'),REFUNDOPS_DB:path.join(temp,'app.sqlite3'),REFUNDOPS_AUTO_ANALYZE:'0',REFUNDOPS_SOURCE_POLICIES:'0',AI_PROVIDER:'openai',OPENAI_API_KEY:'',OPENROUTER_API_KEY:''},stdio:'ignore',windowsHide:true});
 for(let i=0;i<100;i++){try{if((await fetch(base+'/api/health')).ok)break}catch{}await new Promise(r=>setTimeout(r,100))}
 // Explicit fixture for a native OpenAI response that reports tokens, not dollars.
 const fixture=spawnSync(path.join(root,process.platform==='win32'?'.venv/Scripts/python.exe':'.venv/bin/python'),['-c',"import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute(\"INSERT INTO llm_calls VALUES(?,?,?,?,?,?,?,?,?)\",('ui-cost-fixture','fixture','fixture-model','openai','{}',None,1.5,'ok','2026-10-27T00:00:00Z')); c.commit(); c.close()",path.join(temp,'app.sqlite3')],{cwd:root,encoding:'utf8',windowsHide:true});
 assert.equal(fixture.status,0,fixture.stderr);
 const status=async()=>{const result=await fetch(base+'/api/settings/llm',{headers:{'X-Demo-Role':'manager'}});assert(result.ok);return result.json()};
 browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE||undefined});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
 page.on('pageerror',error=>errors.push(error.message));
 await page.goto(base);
 await page.getByRole('button',{name:/^Refund Operations Manager/}).click();
 await page.locator('.sidebar').getByRole('button',{name:'Settings',exact:true}).click();
 await page.getByRole('heading',{name:'AI connection',exact:true}).waitFor();
 assert.equal(await page.getByText(/Automatic routing checks|Preparing automatic routing|Routing checks|Model qualification/).count(),0);
 await page.getByText('p95 latency',{exact:true}).waitFor();
 assert.equal(await page.locator('.detail-grid > div').filter({has:page.getByText('Reported inference cost',{exact:true})}).locator('strong').innerText(),'Unknown');
 assert(await page.getByText(/this threshold cannot limit OpenAI spending/).isVisible());
 const initialStatus=await status();
 assert.equal('validation' in initialStatus,false);
 assert.equal('qualified' in initialStatus,false);
 assert.equal(await page.getByLabel('AI provider',{exact:true}).inputValue(),'openai');
 for(const [provider,key,model] of [['openrouter','sk-or-ui-dummy-key-not-real','openai/gpt-6.1-sol'],['openai','sk-proj-ui-dummy-key-not-real','gpt-6.1-sol']]){
  await page.getByLabel('AI provider',{exact:true}).selectOption(provider);
  assert.equal(await page.getByLabel('Model',{exact:true}).inputValue(),model);
  await page.getByLabel('API key',{exact:true}).fill(key);
  await page.getByRole('button',{name:'Save connection',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('input[type="password"]')?.value==='');
  const saved=await status();assert.equal(saved.provider,provider);assert.equal(saved.model,model);assert(saved.configured);assert(!JSON.stringify(saved).includes(key));
  assert.equal('validation' in saved,false);assert.equal('qualified' in saved,false);
 }
 // Deliberately exercise a plain-text 500 response; the UI must not expose a JSON parser error.
 const failingDisconnect=async route=>route.request().method()==='DELETE'?route.fulfill({status:500,contentType:'text/plain',body:'Internal Server Error'}):route.continue();
 await page.route(base+'/api/settings/llm',failingDisconnect);
 await page.getByRole('button',{name:'Disconnect AI',exact:true}).click();
 await page.getByRole('alert').filter({hasText:'The server could not complete this request. Try again.'}).waitFor();
 assert.equal((await status()).configured,true);
 await page.unroute(base+'/api/settings/llm',failingDisconnect);
 await page.getByRole('button',{name:'Disconnect AI',exact:true}).click();
 await page.getByRole('status').filter({hasText:'Live AI disabled'}).waitFor();
 assert.equal((await status()).configured,false);assert.deepEqual(errors,[]);
 console.log('OpenAI and OpenRouter settings passed: connectivity and usage only, no model exam. No paid calls or operational data changes.');
})().catch(error=>{console.error(error);process.exitCode=1}).finally(async()=>{
 if(browser)await browser.close();
 if(server){server.kill();await new Promise(resolve=>{if(server.exitCode!==null)resolve();else server.once('exit',resolve)})}
 const cleanup=fs.realpathSync(temp),tempRoot=fs.realpathSync(os.tmpdir());
 assert.equal(path.dirname(cleanup),tempRoot);assert(path.basename(cleanup).startsWith('refund-provider-'));
 fs.rmSync(cleanup,{recursive:true,force:true});
});
