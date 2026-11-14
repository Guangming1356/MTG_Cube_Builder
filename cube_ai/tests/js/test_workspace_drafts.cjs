// Exercise real persistence/recovery with raw form drafts and delayed analysis.
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.resolve(__dirname,'../../web/workspace.js'),'utf8');
const clone=value=>JSON.parse(JSON.stringify(value));
function fixture(stored=null){
  const nodes=new Map(),handlers=new Map(),calls=[],messages=[],storage={value:stored,writes:0};
  const field=(id,value,type='text')=>{
    const node={id,value,type,checked:false,tagName:'INPUT',setAttribute(){}};
    nodes.set(id,node);return node;
  };
  const formFields=[field('name','loaded'),field('deck_policy','balanced'),field('advanced','{}'),field('avoid_tribal','', 'checkbox')];
  formFields[3].checked=true;
  field('quick-name','new cube');field('quick-mode','commander');field('quick-deck-policy','balanced');
  field('forge-pods','10');field('forge-workers','0');field('trials','100');field('report-deck-policy','balanced');
  nodes.set('spec-form',{elements:formFields});
  let finish,fail;
  const pending=new Promise((resolve,reject)=>{finish=resolve;fail=reject;});
  const context={current:null,working:false,activeView:'home',viewChanges:0,statusInfo:{workspace_id:'draft-test'},
    $:id=>{if(!nodes.has(id))nodes.set(id,{id,setAttribute(){}});return nodes.get(id);},
    document:{addEventListener(name,fn){handlers.set(name,fn);}},
    localStorage:{getItem:()=>storage.value?JSON.stringify(storage.value):null,setItem(key,text){storage.writes++;storage.value=JSON.parse(text);}},
    addEventListener(name,fn){handlers.set('window:'+name,fn);},
    onCubeReady(){},api:(url,data)=>{calls.push({url,data});return pending;},notice:message=>messages.push(message),
    setTimeout,clearTimeout,
  };
  context.window=context;
  context.fillSpec=spec=>{for(const id of ['name','deck_policy'])if(spec[id]!=null)nodes.get(id).value=spec[id];};
  context.setCube=cube=>{context.current=cube;context.fillSpec(cube.spec);handlers.get('cube-changed')?.();};
  context.view=id=>{context.activeView=id;context.viewChanges++;};
  vm.createContext(context);vm.runInContext(source,context,{filename:'workspace.js'});
  const loaded={spec:{name:'loaded',deck_policy:'balanced'},cards:[{name:'Sun Titan',role:'Main'}],run_id:'existing'};
  return {context,nodes,handlers,calls,messages,storage,finish,fail,loaded};
}
async function recover(stored){
  const test=fixture(stored),pending=test.context.restoreWorkspace();
  test.finish(clone(test.loaded));await pending;return test;
}
(async()=>{
  let passed=0;
  {
    const test=fixture();test.context.current=clone(test.loaded);
    test.nodes.get('deck_policy').value='quality';test.nodes.get('forge-pods').value='25';
    test.context.persistWorkspace();
    const restored=await recover(test.storage.value);
    assert.equal(restored.nodes.get('deck_policy').value,'quality');
    assert.equal(restored.nodes.get('report-deck-policy').value,'quality');
    assert.equal(restored.nodes.get('forge-pods').value,'25');
    assert.equal(restored.context.current.spec.deck_policy,'balanced');
    assert.equal(restored.calls[0].data.spec.deck_policy,'balanced');passed++;
  }
  {
    const test=fixture();test.context.current=clone(test.loaded);
    test.nodes.get('advanced').value='{"players":';test.context.persistWorkspace();
    const restored=await recover(test.storage.value);
    assert.equal(restored.nodes.get('advanced').value,'{"players":');
    assert.equal(restored.context.current.run_id,'existing');passed++;
  }
  {
    const test=fixture();await test.context.restoreWorkspace();test.nodes.get('quick-mode').value='classic';test.nodes.get('quick-name').value='my first cube';
    test.nodes.get('name').value='unsaved recipe';test.context.persistWorkspace();
    assert.ok(test.storage.value,'A first-time draft must survive without any loaded Cube');
    const restored=await recover(test.storage.value);
    assert.equal(restored.nodes.get('quick-mode').value,'classic');
    assert.equal(restored.nodes.get('quick-name').value,'my first cube');
    assert.equal(restored.nodes.get('name').value,'unsaved recipe');
    assert.equal(restored.context.current,null);assert.equal(restored.calls.length,0);passed++;
  }
  {
    const old=fixture();old.context.current=clone(old.loaded);old.context.persistWorkspace();
    const test=fixture(old.storage.value),pending=test.context.restoreWorkspace();
    test.nodes.get('name').value='typed during loading';test.nodes.get('deck_policy').value='quality';
    test.handlers.get('input')({target:test.nodes.get('name')});
    test.finish(clone(test.loaded));await pending;
    assert.equal(test.nodes.get('name').value,'typed during loading');
    assert.equal(test.nodes.get('deck_policy').value,'quality');passed++;
  }
  {
    const test=fixture();test.context.current=clone(test.loaded);
    test.nodes.get('name').value='last keystroke';test.handlers.get('input')({target:test.nodes.get('name')});
    test.handlers.get('window:beforeunload')();
    const restored=await recover(test.storage.value);
    assert.equal(restored.nodes.get('name').value,'last keystroke');passed++;
  }
  {
    const test=fixture();test.context.current=clone(test.loaded);test.context.persistWorkspace();
    const restored=fixture(test.storage.value),pending=restored.context.restoreWorkspace();
    const opened={spec:{name:'explicit new cube'},cards:[]};restored.context.current=opened;
    restored.finish(clone(restored.loaded));await pending;
    assert.strictEqual(restored.context.current,opened);assert.equal(restored.messages.length,0);passed++;
  }
  {
    const saved={version:1,spec:{name:'previous'},cards:[{name:'Sun Titan',role:'Main'}]};
    const test=fixture(saved);test.context.view('report');test.context.persistWorkspace();
    assert.deepEqual(test.storage.value,saved,'Navigation during startup must keep the unread workspace');
    const pending=test.context.restoreWorkspace();test.finish(clone(test.loaded));await pending;
    assert.equal(test.calls[0].data.spec.name,'previous');passed++;
  }
  {
    const old=fixture();old.context.current=clone(old.loaded);old.nodes.get('deck_policy').value='quality';old.context.persistWorkspace();
    const test=fixture(old.storage.value),pending=test.context.restoreWorkspace();
    test.fail(new Error('local server unavailable'));await pending;
    assert.equal(test.nodes.get('deck_policy').value,'quality');
    test.nodes.get('name').value='keep editing';test.context.persistWorkspace();
    assert.equal(test.storage.value.cube.spec.name,'loaded');
    assert.equal(test.storage.value.cube.cards[0].name,'Sun Titan');passed++;
  }
  {
    const test=fixture();test.context.current=clone(test.loaded);
    for(let i=0;i<10;i++)test.context.persistWorkspace();
    assert.equal(test.storage.writes,1,'Identical snapshots should not rewrite localStorage');
    test.nodes.get('deck_policy').value='quality';test.context.persistWorkspace();
    assert.equal(test.storage.writes,2);passed++;
  }
  {
    const test=fixture();test.context.current=clone(test.loaded);
    test.nodes.set('api-key',{id:'api-key',tagName:'INPUT',type:'password',value:'test-only-credential'});
    test.context.persistWorkspace();
    assert.ok(!JSON.stringify(test.storage.value).includes('test-only-credential'));passed++;
  }
  console.log(JSON.stringify({passed,separate_loaded_cube_and_form_draft:true}));
})().catch(error=>{console.error(error);process.exitCode=1;});
