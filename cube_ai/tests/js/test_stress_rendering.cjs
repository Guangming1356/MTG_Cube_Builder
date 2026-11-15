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
assert.ok(!result.innerHTML.includes('费用准备度如何计算'));
context.renderStress({trials:5,buildable_rate:1,deck_policy:'balanced',drafted_pool_sizes:{60:15},cards_discarded_per_pack:9,
  guilds:{},examples:[],limitation:'轮抓检查',mana_model:{version:'printed-cost-2',assumptions:'没有法术力费用不等于 <0>；起始 40 生命'}});
assert.match(result.innerHTML,/可组牌率/);assert.match(result.innerHTML,/费用准备度如何计算/);
assert.match(result.innerHTML,/&lt;0>/);assert.match(result.innerHTML,/40 生命/);
context.renderStress({trials:5,buildable_rate:1,deck_policy:'balanced',drafted_pool_sizes:{60:15},cards_discarded_per_pack:9,
  guilds:{},examples:[],limitation:'轮抓检查',mana_model:{assumptions:'费用检查',hands_per_deck:40,cards_per_hand:11,stream_version:'readiness-fork-1'}});
assert.match(result.innerHTML,/40 手/);assert.match(result.innerHTML,/11 张牌/);assert.match(result.innerHTML,/不影响后续轮抓/);
console.log(JSON.stringify({passed:4,missing_observations_are_not_zero_rates:true}));
