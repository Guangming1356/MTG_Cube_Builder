// Beginner entrance uses the same validated build / Forge pipelines as the advanced views.
let homeLibrary={saved:[],examples:[]};
function focusCurrent(){document.querySelector('#home-current').scrollIntoView({behavior:'smooth',block:'center'});}
// Keep the primary action visible on ordinary laptop screens; the full draft
// rules remain immediately below it.
$('quick-rules').before($('quick-build'));
window.refreshHomeLibrary=lib=>{
  homeLibrary=lib;const before=$('home-library').value;
  $('home-library').innerHTML='<option value="">请选择一套牌表…</option><optgroup label="已保存的版本">'+lib.saved.map(x=>`<option value="run:${esc(x.id)}">${esc(x.label)} · ${x.count} 张${x.status==='experimental'?' · 实验候选':''}${x.superseded_by?' · 已有后续版':''}</option>`).join('')+'</optgroup><optgroup label="项目原有的牌表">'+lib.examples.map(x=>`<option value="example:${esc(x.id)}">${esc(x.label)}</option>`).join('')+'</optgroup>';
  $('home-library').value=before;window.updateHome();
};
window.updateHome=()=>{
  const has=!!current;$('home-current-title').textContent=has?(current.spec?.name||'当前 Cube'):'还没有打开牌表';
  $('home-current-info').textContent=has?`${current.cards.length} 张 · ${current.audit.hard_errors===0?'已通过当前构筑检查':`有 ${current.audit.hard_errors} 项需要处理，请查看检查报告`}`:'先生成一套，或打开已有牌表。';
  $('home-assessment').textContent=current?.provenance?.validation_status==='experimental'?'实验候选：尚未通过全部独立测试，不代表已证实更强。':'';
  ['home-cards','home-check','home-save','home-optimize'].forEach(id=>$(id).disabled=working||!has||(id==='home-optimize'&&(current.spec?.mode!=='commander'||current.spec?.players!==3)));
  $('home-open').disabled=working||!$('home-library').value;
  $('home-downloads').innerHTML=has&&current.run_id?`<a class="download-button" href="/exports/${encodeURIComponent(current.run_id)}/cube.csv">下载牌表</a><a href="/exports/${encodeURIComponent(current.run_id)}/cube.json">保存完整备份</a><a href="/exports/${encodeURIComponent(current.run_id)}/cubecobra.txt">用于 CubeCobra</a>`:'';
};
const oldLock=lock;
lock=value=>{oldLock(value);window.updateHome();};
$('home-library').onchange=window.updateHome;
$('quick-mode').onchange=()=>{
  const edh=$('quick-mode').value==='commander';$('quick-power-controls').hidden=!edh;$('quick-name').value=edh?'我的三人 EDH Cube':'我的传统 Cube';
  $('quick-rules').textContent=edh?'三人每包 15 张，每人取 2 张，传过三人后弃 9 张；每人抓 60 张。选入任意张，再加基本地，组至少 60 张含指挥官的牌组。':'传统轮抓：8 人，每人 3 包 15 张，每次取 1 张；从抓到的牌中组 40 张牌组，基本地不限。';
};
$('quick-build').onclick=()=>guard(async()=>{
  const mode=$('quick-mode').value;fillSpec({...statusInfo.presets[mode],...quickPowerSpec(),name:$('quick-name').value.trim()||'我的 Cube',seed:Math.floor(Math.random()*1000000000)});
  notice('正在构筑，请稍等。完成后会自动保存。');setCube(await job('build'));await refreshRuns();view('home');focusCurrent();notice('牌表已生成并保存。可以下载牌表，或继续检查轮抓与实战。');
});
$('quick-details').onclick=()=>{fillSpec({...statusInfo.presets[$('quick-mode').value],...quickPowerSpec(),name:$('quick-name').value.trim()||'我的 Cube'});view('design');};
$('home-open').onclick=()=>guard(async()=>{
  const value=$('home-library').value;if(!value)throw Error('请先选择一套牌表');const [kind,id]=value.split(':');
  if(kind==='run'){
    const saved=await api('/exports/'+encodeURIComponent(id)+'/cube.json');fillSpec(saved.spec);
    const c=await analyzeRows(saved.cards);c.run_id=id;c.provenance=saved.provenance;setCube(c);
  }else{
    fillSpec(statusInfo.presets.commander);const {text}=await api('/api/example?id='+encodeURIComponent(id));
    const title=homeLibrary.examples.find(x=>x.id===id)?.label||'打开的 Cube';$('name').value=title;
    setCube(await api('/api/analyze',{spec:spec(),text}));
  }
  focusCurrent();notice('牌表已打开。可以查看、下载或进行实战改进。');
});
$('home-upload').onchange=()=>guard(async()=>{
  const file=$('home-upload').files[0];if(!file)return;const text=await file.text();
  if(file.name.toLowerCase().endsWith('.json')){
    const saved=JSON.parse(text);if(!saved.cards||!saved.spec)throw Error('请选择本工具导出的完整备份');
    fillSpec(saved.spec);const c=await analyzeRows(saved.cards);c.provenance=saved.provenance;setCube(c);
  }else{
    fillSpec(statusInfo.presets[$('quick-mode').value]);$('name').value=file.name.replace(/\.[^.]+$/,'');
    setCube(await api('/api/analyze',{spec:spec(),text}));
  }
  if(current.audit.hard_errors)notice('文件已打开。发现部分不符合当前玩法的内容，请点击“检查轮抓与实战”查看。',true);
  else notice('牌表文件已打开。点击“保存并下载牌表”可保存为项目的新版本。');
  focusCurrent();
});
$('home-cards').onclick=()=>view('cards');$('home-check').onclick=()=>view('report');
$('home-save').onclick=()=>guard(async()=>{
  if(!current)throw Error('请先打开一套牌表');
  setCube(await api('/api/save',{spec:spec(),cards:current.cards,require_valid:true}));await refreshRuns();
  view('home');focusCurrent();notice('牌表已保存。点击下面的“下载牌表”即可下载文件。');
});
$('home-optimize').onclick=()=>{view('report');$('optimization-profile').scrollIntoView({block:'center'});$('optimization-profile').focus();};
$('home-guide').onclick=()=>view('guide');
onCubeReady(()=>{$('quick-build').disabled=false;window.updateHome();});
(async()=>{
  try{const guide=await api('/api/design-guide');
    $('design-principles').innerHTML=guide.principles.map((p,i)=>`<article class="panel"><span class="step-label">${String(i+1).padStart(2,'0')}</span><h3>${esc(p.title)}</h3><p>${esc(p.description)}</p><details><summary>项目如何执行这一条</summary><p class="sub">${esc(p.path)}</p></details></article>`).join('');
    $('design-cases').innerHTML=guide.cases.map(c=>`<article class="case-card"><a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.title)} ↗</a><p>${esc(c.lesson)}</p><small>主牌 ${c.stats.main_slots} 张 · 本地识别 ${(c.stats.coverage*100).toFixed(1)}% · 未识别 ${c.stats.unknown_names.length} 张</small></article>`).join('');
    $('learning-websites').innerHTML=(guide.websites||[]).map(w=>`<article class="case-card"><a href="${esc(w.url)}" target="_blank" rel="noopener">${esc(w.name)} ↗</a><p>${esc(w.purpose)}</p></article>`).join('');
    $('learning-sources').innerHTML=(guide.sources||[]).map(s=>`<article class="case-card"><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title)} ↗</a><p>${esc(s.lesson)}</p><small>${esc(s.status_label)}</small><details><summary>玩法背景与本项目的取舍</summary><p>${esc(s.context)}</p><p>${esc(s.transfer)}</p>${s.evidence_url?`<a href="${esc(s.evidence_url)}" target="_blank" rel="noopener">查看设计说明 ↗</a>`:''}</details></article>`).join('');
  }catch(error){$('design-cases').textContent='设计资料暂时无法读取，请重新打开入口。';}
})();

function quickPowerSpec(){if($('quick-mode').value!=='commander')return {bracket:null};const bracket=Number($('quick-bracket').value);return {bracket,power_tuning:$('quick-power').value,exclude_game_changers:bracket<=2};}
function bracketNote(value){const p=statusInfo?.brackets?.profiles.find(p=>p.bracket===Number(value));return p?`${p.description} 每副牌 Game Changers：${p.deck_gc??'不限'}。${p.own_turns?`官方体验预期：通常至少经历 ${p.own_turns} 个自己的回合才进入胜负阶段；这是对局预期，不能据此认证轮抓牌组。`:'竞技意图与环境适配需要额外验证。'}`:'保留自定义参数，不按官方 Bracket 目标认证。';}
window.updateBracketControls=()=>{const b=Number($('bracket').value),low=b>0&&b<=3;$('bracket-controls').hidden=$('mode').value!=='commander';$('bracket-note').textContent=bracketNote($('bracket').value);['allow_extra_turns','allow_infinite_combos','allow_mass_land_destruction'].forEach(id=>$(id).disabled=working||low);$('exclude_game_changers').disabled=working||(b===1||b===2);$('cube_gc_limit').disabled=working||(b===1||b===2);};
$('bracket').onchange=()=>{const b=Number($('bracket').value);$('exclude_game_changers').checked=b===1||b===2;$('cube_gc_limit').value='';if(b>0&&b<=3)['allow_extra_turns','allow_infinite_combos','allow_mass_land_destruction'].forEach(id=>$(id).checked=false);window.updateBracketControls();};
const lockWithBracket=lock;lock=value=>{lockWithBracket(value);if(statusInfo)window.updateBracketControls();};
function updateQuickBracket(){$('quick-bracket-note').textContent=bracketNote($('quick-bracket').value);}
$('quick-bracket').onchange=updateQuickBracket;onCubeReady(()=>{updateQuickBracket();window.updateBracketControls();});
