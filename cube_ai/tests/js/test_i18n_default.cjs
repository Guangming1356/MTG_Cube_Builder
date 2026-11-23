const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[2], 'utf8');

async function setup(saved, failure=false, changeBeforeLoad=null) {
  let resolveFetch;
  const pending = new Promise(resolve => { resolveFetch = resolve; });
  const selector = {value:'en', addEventListener(_name, fn) { this.change = fn; }};
  const preview = {};
  const paragraph = {nodeType:3,nodeValue:'你好',parentElement:{tagName:'DIV'}};
  const root = {nodeType:1,tagName:'HTML',childNodes:[paragraph],hasAttribute(){return false;}};
  let stored=saved;
  const context = {document:{documentElement:root,getElementById:id=>id==='ui-language'?selector:preview},
    window:{}, localStorage:{getItem(){if(saved==='denied')throw Error('disabled');return stored;},setItem(_k,v){if(saved==='denied')throw Error('disabled');stored=v;}},
    MutationObserver:class {observe(){}},fetch:()=>pending};
  vm.runInNewContext(source, context);
  if (changeBeforeLoad) { selector.value=changeBeforeLoad; selector.change(); }
  resolveFetch({ok:!failure,json:async()=>({'你好':'Hello'})});
  await new Promise(resolve=>setImmediate(resolve));
  return {root,paragraph,selector,preview,stored,context};
}

(async()=>{
  let app=await setup(null);
  assert.equal(app.selector.value,'en');assert.equal(app.root.lang,'en');assert.equal(app.paragraph.nodeValue,'Hello');
  app=await setup('zh-CN');
  assert.equal(app.selector.value,'zh-CN');assert.equal(app.paragraph.nodeValue,'你好');
  app=await setup('denied');
  assert.equal(app.selector.value,'en');assert.equal(app.paragraph.nodeValue,'Hello');
  app=await setup('en',false,'zh-CN');
  assert.equal(app.selector.value,'zh-CN');assert.equal(app.stored,'zh-CN');
  app=await setup('en',true);
  assert.equal(app.selector.value,'zh-CN');assert.equal(app.selector.disabled,true);assert.equal(app.stored,'en');
  console.log('default language checks passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
