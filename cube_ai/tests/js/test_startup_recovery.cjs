// Exercise the real startup functions without launching or controlling a browser.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.resolve(__dirname,'../../web/app.js'),'utf8');
const page=fs.readFileSync(path.resolve(__dirname,'../../web/index.html'),'utf8');
assert.match(page,/id="startup-retry" hidden/);
const start=source.indexOf("let startupNotice='';"),end=source.indexOf('function renderBracketReport(',start);
assert.ok(start>=0&&end>start);const code=source.slice(start,end);
const transient=()=>Object.assign(Error('暂时断开'),{retryable:true});

function fixture(plans,{edited=false,restoreNotice=false}={}){
  const ids=['startup-retry','application-version','connection','snapshot','catalog-count','knowledge-count','color-filter','examples','notice'];
  const nodes=Object.fromEntries(ids.map(id=>[id,{id,hidden:id==='startup-retry',disabled:false,dataset:{},innerHTML:'',textContent:'',value:''}]));
  nodes['color-filter'].innerHTML='<option>全部颜色</option>';nodes.examples.innerHTML='<option>选择牌表</option>';
  const counts={},events=[],fills=[],libraries=[],delays=[];
  const status={version:'test',snapshot:'2026-10-08',cards:31070,knowledge_chunks:5,presets:{commander:{name:'default'}},gpt:{},feedback:{}};
  const data={'/api/status':status,'/api/examples':[{id:'one',label:'Example'}],'/api/library':{saved:[],examples:[]}};
  const context={window:{cubeReady:false,cubeServiceClosed:false,workspaceHasDraftEdits:()=>edited,
      restoreWorkspace:async()=>{if(restoreNotice)context.notice('已恢复工作区');}},
    document:{dispatchEvent:event=>events.push(event.type)},Event:class{constructor(type){this.type=type;}},
    $:id=>{assert.ok(nodes[id],id);return nodes[id];},esc:s=>String(s),statusInfo:null,current:null,
    configureExperiments:()=>{},fillSpec:s=>fills.push(s),renderFeedback:()=>{},lock:()=>{},
    refreshRuns:async lib=>libraries.push(lib),
    notice:(text)=>{nodes.notice.textContent=text;nodes.notice.hidden=false;},
    setTimeout:(fn,ms)=>{delays.push(ms);queueMicrotask(fn);},
    api:async url=>{counts[url]=(counts[url]||0)+1;const plan=plans[url]||[];
      if(plan.length){const next=plan.shift();if(next instanceof Error)throw next;if(next instanceof Promise)return next;}
      return data[url];}};
  vm.createContext(context);vm.runInContext(code,context);
  return {context,nodes,counts,events,fills,libraries,delays,data};
}
async function settle(check){for(let i=0;i<100&&!check();i++)await new Promise(resolve=>setImmediate(resolve));assert.ok(check(),'startup did not settle');}

(async()=>{
  let f=fixture({'/api/status':[transient(),transient()],'/api/examples':[transient()],'/api/library':[transient()]},{edited:true,restoreNotice:true});
  await settle(()=>f.context.window.cubeReady);
  assert.deepEqual(f.counts,{'/api/status':3,'/api/examples':2,'/api/library':2});
  assert.equal(f.fills.length,0);assert.equal(f.events.filter(x=>x==='cube-ready').length,1);
  assert.equal(f.nodes['startup-retry'].hidden,true);assert.equal(f.nodes.notice.textContent,'已恢复工作区');
  assert.equal((f.nodes.examples.innerHTML.match(/value="one"/g)||[]).length,1);assert.equal(f.libraries.length,1);

  f=fixture({'/api/examples':[Error('设置错误')]});await settle(()=>!f.nodes['startup-retry'].hidden);
  assert.equal(f.context.window.cubeReady,false);assert.match(f.nodes.notice.textContent,/重新连接/);
  await f.nodes['startup-retry'].onclick();assert.equal(f.context.window.cubeReady,true);
  assert.equal(f.events.filter(x=>x==='cube-ready').length,1);assert.equal(f.fills.length,1);
  assert.equal((f.nodes.examples.innerHTML.match(/value="one"/g)||[]).length,1);

  let release;const deferred=new Promise(resolve=>{release=resolve;});
  f=fixture({'/api/status':[deferred]});await f.context.startApp();assert.equal(f.counts['/api/status'],1);
  release(f.data['/api/status']);await settle(()=>f.context.window.cubeReady);assert.equal(f.counts['/api/status'],1);

  f=fixture({'/api/status':[transient(),transient(),transient(),transient()]});
  await settle(()=>!f.nodes['startup-retry'].hidden);assert.equal(f.counts['/api/status'],4);
  assert.equal(f.context.window.cubeReady,false);assert.deepEqual(f.delays,[1500,3000,4500]);
  console.log(JSON.stringify({passed:4,desktop_control:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
