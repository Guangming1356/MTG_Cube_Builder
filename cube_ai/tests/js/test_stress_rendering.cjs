const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.resolve(__dirname,'../../web/app.js'),'utf8');
const start=source.indexOf('function renderStress('),end=source.indexOf("$('stress').onclick=",start);
assert.ok(start>=0&&end>start);
const result={innerHTML:''};
const context={$:()=>result,esc:value=>String(value??'').replaceAll('<','&lt;'),
  deckPolicyLabel:value=>value==='balanced'?'均衡费用':'质量优先'};
vm.createContext(context);vm.runInContext(source.slice(start,end),context);
context.renderStress({trials:5,buildable_rate:1,deck_policy:'balanced',drafted_pool_sizes:{60:15},cards_discarded_per_pack:9,
  guilds:{UW:{decks:0,buildable_rate:0,ready_by_turn:{1:0}},BR:{decks:3,buildable_rate:1,ready_by_turn:{1:.5,2:.75,3:1,4:1}}},
  examples:[{commander:'sample'}],limitation:'轮抓检查'});
assert.match(result.innerHTML,/<td>UW<\/td><td>尚无样本<\/td><td>—<\/td>/);
assert.match(result.innerHTML,/<td>BR<\/td><td>3 \/ 100%<\/td><td>50% \/ 75% \/ 100% \/ 100%<\/td>/);
assert.match(result.innerHTML,/组牌：均衡费用/);assert.match(result.innerHTML,/sample/);
context.renderStress({trials:5,buildable_rate:0,drafted_pool_sizes:{60:15},cards_discarded_per_pack:9,
  guilds:{UW:{decks:3,buildable_rate:0,ready_by_turn:{1:0}}},examples:[],limitation:'旧记录'});
assert.match(result.innerHTML,/<td>UW<\/td><td>3 \/ 0%<\/td><td>—<\/td>/);
assert.match(result.innerHTML,/组牌：质量优先/);
console.log(JSON.stringify({passed:2,missing_observations_are_not_zero_rates:true}));
