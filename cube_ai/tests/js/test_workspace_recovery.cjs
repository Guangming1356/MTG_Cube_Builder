// Exercise the actual recovery script with a controlled delayed HTTP response.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.resolve(__dirname,'../../web/workspace.js'),'utf8');

function fixture(){
  let finish;
  const response=new Promise(resolve=>{finish=resolve;});
  const nodes=new Map(),events=[];
  const saved={version:1,view:'cards',spec:{name:'saved'},cards:[{name:'Sun Titan',role:'Main'}]};
  const context={current:null,working:false,activeView:'home',viewChanges:0,
    statusInfo:{workspace_id:'isolated-test'},
    $:id=>{if(!nodes.has(id))nodes.set(id,{setAttribute(){}});return nodes.get(id);},
    document:{addEventListener(){}},localStorage:{getItem:()=>JSON.stringify(saved),setItem(){}},
    onCubeReady(){},api:()=>response,notice:message=>events.push(message),
    setTimeout,clearTimeout,
  };
  context.window=context;
  context.setCube=cube=>{context.current=cube;};
  context.view=id=>{context.activeView=id;context.viewChanges++;};
  vm.createContext(context);vm.runInContext(source,context,{filename:'workspace.js'});
  return {context,finish,events};
}

(async()=>{
  {
    const {context,finish}=fixture();const pending=context.restoreWorkspace();
    finish({spec:{name:'saved'},cards:[]});await pending;
    assert.equal(context.current.spec.name,'saved');assert.equal(context.activeView,'cards');
  }
  {
    const {context,finish}=fixture();context.view('report');
    const pending=context.restoreWorkspace();finish({spec:{name:'saved'},cards:[]});await pending;
    assert.equal(context.current.spec.name,'saved');assert.equal(context.activeView,'report');
  }
  {
    const {context,finish}=fixture();const pending=context.restoreWorkspace();
    context.view('advisor');finish({spec:{name:'saved'},cards:[]});await pending;
    assert.equal(context.current.spec.name,'saved');assert.equal(context.activeView,'advisor');
  }
  {
    const {context,finish,events}=fixture();const pending=context.restoreWorkspace();
    const opened={spec:{name:'explicitly opened'},cards:[{name:'Counterspell'}]};
    context.current=opened;context.view('cards');
    finish({spec:{name:'stale saved'},cards:[]});await pending;
    assert.strictEqual(context.current,opened);assert.equal(events.length,0);
  }
  console.log(JSON.stringify({passed:4,delayed_response_does_not_override_navigation_or_new_cube:true}));
})().catch(error=>{console.error(error);process.exitCode=1;});
