// Exercise the production form functions against actual HTML IDs, without a browser.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.resolve(__dirname,'../../web');
const source=fs.readFileSync(path.join(root,'app.js'),'utf8'),html=fs.readFileSync(path.join(root,'index.html'),'utf8');
const elements=new Map([...html.matchAll(/\bid="([^"]+)"/g)].map(match=>[match[1],{value:'',checked:false}]));
const samples=JSON.parse(fs.readFileSync(0,'utf8'));
const context={$:id=>{if(id==='report-deck-policy')return null;assert.ok(elements.has(id),`Missing form element ${id}`);return elements.get(id);},window:{},statusInfo:{presets:{commander:samples[0],classic:samples[0]}}};
const start=source.indexOf('function fillSpec(s)'),end=source.indexOf("$('mode').onchange",start);
assert.ok(start>=0&&end>start);vm.createContext(context);vm.runInContext(source.slice(start,end),context);
const results=[];
for(const sample of samples){
  context.fillSpec(sample);
  assert.equal(elements.get('allow_setup_commanders').checked,sample.allow_setup_commanders??false);
  assert.ok(!Object.hasOwn(JSON.parse(elements.get('advanced').value),'allow_setup_commanders'));
  results.push(context.spec());
}
process.stdout.write(JSON.stringify(results));
