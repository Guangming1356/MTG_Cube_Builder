// Run the production request and job functions with deterministic local mocks.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.resolve(__dirname,'../../web/app.js'),'utf8');
const apiCode=source.slice(source.indexOf('async function api('),source.indexOf('function notice('));
const jobCode=source.slice(source.indexOf('async function job('),source.indexOf('async function refreshRuns('));
assert.ok(apiCode&&jobCode);
const retriable=()=>Object.assign(Error('temporarily unavailable'),{retryable:true});

async function checkRequests(){
  let outcome;
  const context={AbortController,TypeError,Error,fetch:async()=>{throw outcome;},setTimeout:()=>1,clearTimeout:()=>{}};
  vm.createContext(context);vm.runInContext(apiCode,context);
  for(const error of [new TypeError('network'),Object.assign(Error('timeout'),{name:'AbortError'})]){
    outcome=error;await assert.rejects(context.api('/test'),e=>e.retryable===true);
  }
  context.fetch=async()=>({ok:false,status:404,json:async()=>({error:'任务不存在'})});
  await assert.rejects(context.api('/test'),e=>e.message==='任务不存在'&&!e.retryable);
  context.fetch=async()=>({ok:false,status:503,json:async()=>({error:'稍后重试'})});
  await assert.rejects(context.api('/test'),e=>e.message==='稍后重试'&&e.retryable===true);
}

async function runJob(events){
  const calls=[],notices=[],delays=[];let submitted=0;
  const context={current:{cards:[{name:'Card'}],run_id:'run'},spec:()=>({mode:'commander'}),
    window:{scheduleTaskMonitor:()=>{}},document:{hidden:false},encodeURIComponent,Error,
    notice:text=>notices.push(text),setTimeout:(fn,delay)=>{delays.push(delay);fn();},
    api:async (url,payload)=>{
      calls.push(url);
      if(url==='/api/tasks'){submitted++;if(events.postError)throw events.postError;return {job_id:'id with space'};}
      assert.equal(url,'/api/job?id=id%20with%20space');
      const event=events.shift();if(event instanceof Error)throw event;
      assert.ok(event,'unexpected extra status request');return event;
    }};
  vm.createContext(context);vm.runInContext(jobCode,context);
  let value,error;try{value=await context.job('build');}catch(e){error=e;}
  return {value,error,calls,notices,delays,submitted};
}

async function checkRealLocalHTTP(){
  const http=require('node:http');let posts=0,gets=0;
  const server=http.createServer((req,res)=>{
    if(req.url==='/api/tasks'){posts++;res.setHeader('Content-Type','application/json');res.end(JSON.stringify({job_id:'local'}));return;}
    if(req.url==='/api/job?id=local'){
      gets++;if(gets===1){req.socket.destroy();return;}
      res.setHeader('Content-Type','application/json');
      res.end(JSON.stringify(gets===2?{state:'running',progress:'运行中'}:{state:'done',progress:'完成',result:{ok:true}}));return;
    }
    res.writeHead(404);res.end();
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  try{
    const base=`http://127.0.0.1:${server.address().port}`;
    const context={current:null,spec:()=>({mode:'commander'}),AbortController,TypeError,Error,encodeURIComponent,
      window:{scheduleTaskMonitor:()=>{}},document:{hidden:false},notice:()=>{},
      setTimeout:(fn,ms)=>setTimeout(fn,ms===30000?ms:1),clearTimeout,
      fetch:(url,options)=>fetch(base+url,options)};
    vm.createContext(context);vm.runInContext(apiCode+'\n'+jobCode,context);
    const result=await context.job('build');assert.equal(result.ok,true);assert.equal(posts,1);assert.equal(gets,3);
  }finally{await new Promise(resolve=>server.close(resolve));}
}

(async()=>{
  await checkRequests();
  let r=await runJob([retriable(),retriable(),{state:'running',progress:'运行中'},{state:'done',progress:'完成',result:{ok:true}}]);
  assert.equal(r.value.ok,true);assert.equal(r.submitted,1);assert.equal(r.calls.length,5);
  assert.deepEqual(r.delays,[1500,3000,1000]);assert.match(r.notices[0],/正在重新读取任务状态/);
  r=await runJob([retriable(),retriable(),retriable(),{state:'paused',progress:'已暂停'},
    retriable(),retriable(),retriable(),{state:'done',progress:'完成',result:{ok:true}}]);
  assert.equal(r.value.ok,true);assert.equal(r.submitted,1);assert.ok(r.delays.includes(3000));
  r=await runJob([retriable(),retriable(),retriable(),retriable()]);
  assert.equal(r.error.retryable,true);assert.equal(r.submitted,1);assert.equal(r.calls.length,5);
  r=await runJob([Error('任务不存在')]);assert.equal(r.error.message,'任务不存在');assert.equal(r.calls.length,2);
  r=await runJob([{state:'cancelled',progress:'已结束'}]);assert.equal(r.error.cancelled,true);assert.equal(r.calls.length,2);
  r=await runJob([{state:'failed',error:'任务出错',progress:'失败'}]);assert.equal(r.error.message,'任务出错');assert.equal(r.calls.length,2);
  const events=[];events.postError=retriable();r=await runJob(events);assert.equal(r.submitted,1);assert.equal(r.calls.length,1);
  if(typeof fetch==='function')await checkRealLocalHTTP();
  console.log(JSON.stringify({passed:7,desktop_control:false,local_http_tested:typeof fetch==='function'}));
})().catch(error=>{console.error(error);process.exitCode=1;});
