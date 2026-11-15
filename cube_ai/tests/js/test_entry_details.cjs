// Test the production card renderer without opening a browser or desktop window.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.resolve(__dirname,'../../web/app.js'),'utf8');
const start=source.indexOf('async function detail(name)'),end=source.indexOf("$('close-dialog').onclick",start);
assert.ok(start>=0&&end>start);
let card={name:'Phyrexian Dreadnought',type:'Artifact Creature',mana_cost:'{1}',identity:'C',
  text:'When this creature enters, sacrifice it unless you sacrifice creatures with total power 12 or greater.',
  quality:1.83,enablers:['artifacts'],payoffs:[],tribal:[],url:'https://scryfall.com',
  entry_cost_notes:['进场需额外牺牲高总力量的生物']};
const detail={innerHTML:'',querySelector:()=>null},dialog={opened:false,showModal(){this.opened=true;}};
const context={api:async()=>card,$:id=>id==='card-detail'?detail:dialog,
  esc:value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),displayLabel:key=>key};
vm.createContext(context);vm.runInContext(source.slice(start,end),context);
(async()=>{
  await context.detail(card.name);
  assert.ok(dialog.opened);assert.match(detail.innerHTML,/进场代价/);assert.match(detail.innerHTML,/高总力量/);assert.match(detail.innerHTML,/1\.83/);
  card={...card,name:'Sun Titan',quality:4.05,entry_cost_notes:undefined};
  await context.detail(card.name);assert.ok(!detail.innerHTML.includes('进场代价'));
  console.log(JSON.stringify({passed:2,card_notes_rendered_without_desktop_control:true}));
})().catch(error=>{console.error(error);process.exitCode=1;});
