// Exercise the real task-monitor code without a browser window or network.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.resolve(__dirname,'../../web/tasks-ui.js'),'utf8');
let timer,delay,requests=[],fail=false;
const listeners={},windowListeners={};
const pause={dataset:{task:'job-1',action:'pause'},disabled:false};
const cancel={dataset:{task:'job-1',action:'cancel'},disabled:false};
const panel={hidden:true,innerHTML:'',querySelector:()=>null,
  querySelectorAll:selector=>selector==='button[data-task]'?[pause,cancel]:[],insertAdjacentHTML(){}};
const job={id:'job-1',operation:'forge',state:'running',controllable:true,created_at:1,progress:'运行中'};
const context={
  navigator:{onLine:false},document:{hidden:false,addEventListener:(name,fn)=>{listeners[name]=fn;}},
  window:{cubeServiceClosed:false,addEventListener:(name,fn)=>{windowListeners[name]=fn;}},
  setTimeout:(fn,ms)=>{timer=fn;delay=ms;return 1;},clearTimeout:()=>{},
  onCubeReady:fn=>fn(),$:id=>{assert.equal(id,'task-monitor');return panel;},
  api:async (url,body)=>{requests.push([url,body]);if(fail)throw Error('offline service unavailable');
    if(url==='/api/jobs')return [job];if(url==='/api/task/control')return {progress:'已发送'};
    throw Error('unexpected endpoint '+url);},
  esc:value=>String(value??''),notice:()=>{},guard:fn=>fn(),Date,Map,Set,JSON,encodeURIComponent,
};
vm.createContext(context);vm.runInContext(source,context);
(async()=>{
  assert.equal(delay,0);await timer();
  assert.equal(requests[0][0],'/api/jobs');assert.equal(panel.hidden,false);
  assert.match(panel.innerHTML,/Forge 实战/);assert.match(panel.innerHTML,/暂停/);assert.match(panel.innerHTML,/强制结束/);
  assert.equal(delay,1500);
  await pause.onclick();await cancel.onclick();
  assert.deepEqual(requests.filter(x=>x[0]==='/api/task/control').map(x=>x[1].action),['pause','cancel']);
  const beforeHidden=requests.length;context.document.hidden=true;await timer();
  assert.equal(requests.length,beforeHidden);assert.equal(delay,30000);
  context.document.hidden=false;listeners.visibilitychange();assert.equal(delay,0);await timer();
  assert.equal(requests.length,beforeHidden+1);
  fail=true;await timer();assert.equal(delay,1500);fail=false;
  const beforeRetry=requests.length;await timer();assert.equal(requests.length,beforeRetry+1);
  context.window.cubeServiceClosed=true;timer=undefined;context.scheduleTaskMonitor(true);assert.equal(timer,undefined);
  console.log(JSON.stringify({passed:6,desktop_control:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
