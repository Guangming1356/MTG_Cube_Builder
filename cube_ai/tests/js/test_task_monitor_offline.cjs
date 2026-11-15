// Exercise the real task-monitor code without a browser window or network.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.resolve(__dirname,'../../web/tasks-ui.js'),'utf8');
const page=fs.readFileSync(path.resolve(__dirname,'../../web/index.html'),'utf8');
assert.match(page,/id="task-connection-status"[^>]*role="status"[^>]*aria-live="polite"[^>]*hidden/);
let timer,delay,requests=[],fail=false;
const listeners={},windowListeners={};
const pause={dataset:{task:'job-1',action:'pause'},disabled:false};
const cancel={dataset:{task:'job-1',action:'cancel'},disabled:false};
const panel={hidden:true,_html:'',get innerHTML(){return this._html;},
  set innerHTML(value){this._html=value;pause.disabled=false;cancel.disabled=false;},querySelector:()=>null,
  querySelectorAll:selector=>['button[data-task]','button.task-control'].includes(selector)?[pause,cancel]:[],insertAdjacentHTML(){}};
const connection={hidden:true,textContent:''};
const job={id:'job-1',operation:'forge',state:'running',controllable:true,created_at:1,progress:'运行中'};
const context={
  navigator:{onLine:false},document:{hidden:false,addEventListener:(name,fn)=>{listeners[name]=fn;}},
  window:{cubeServiceClosed:false,addEventListener:(name,fn)=>{windowListeners[name]=fn;}},
  setTimeout:(fn,ms)=>{timer=fn;delay=ms;return 1;},clearTimeout:()=>{},
  onCubeReady:fn=>fn(),$:id=>{assert.ok(['task-monitor','task-connection-status'].includes(id));return id==='task-monitor'?panel:connection;},
  api:async (url,body)=>{requests.push([url,body]);if(fail)throw Error('offline service unavailable');
    if(url==='/api/jobs')return [job];if(url==='/api/task/control')return {progress:'已发送'};
    throw Error('unexpected endpoint '+url);},
  esc:value=>String(value??''),notice:()=>{},guard:fn=>fn(),Date,Map,Set,JSON,encodeURIComponent,
};
vm.createContext(context);vm.runInContext(source,context);
(async()=>{
  assert.equal(delay,0);await timer();
  assert.equal(requests[0][0],'/api/jobs');assert.equal(panel.hidden,false);
  assert.equal(connection.hidden,true);  // No internet is needed for localhost.
  assert.match(panel.innerHTML,/Forge 实战/);assert.match(panel.innerHTML,/暂停/);assert.match(panel.innerHTML,/强制结束/);
  assert.equal(delay,1500);
  await pause.onclick();await cancel.onclick();
  assert.deepEqual(requests.filter(x=>x[0]==='/api/task/control').map(x=>x[1].action),['pause','cancel']);
  const beforeHidden=requests.length;context.document.hidden=true;await timer();
  assert.equal(requests.length,beforeHidden);assert.equal(delay,30000);
  context.document.hidden=false;listeners.visibilitychange();assert.equal(delay,0);await timer();
  assert.equal(requests.length,beforeHidden+1);
  fail=true;await timer();assert.equal(delay,1500);assert.equal(connection.hidden,false);
  assert.match(connection.textContent,/正在重试/);assert.equal(pause.disabled,true);assert.equal(cancel.disabled,true);fail=false;
  const beforeRetry=requests.length;await timer();assert.equal(requests.length,beforeRetry+1);
  assert.equal(connection.hidden,true);assert.equal(pause.disabled,false);assert.equal(cancel.disabled,false);
  context.window.cubeServiceClosed=true;context.taskConnection(false);assert.equal(connection.hidden,true);
  timer=undefined;context.scheduleTaskMonitor(true);assert.equal(timer,undefined);
  console.log(JSON.stringify({passed:6,desktop_control:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
