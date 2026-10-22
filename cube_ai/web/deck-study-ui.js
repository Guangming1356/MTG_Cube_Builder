// Optional, controlled comparison; no Cube or default deck policy is changed.
$('report').insertAdjacentHTML('beforeend',`
<article class="panel" id="deck-study-panel">
  <span class="eyebrow">同一批抓牌，比较组牌后的体验</span>
  <h2>比较两种组牌方式 <span class="badge">实验</span></h2>
  <p>比较“优先单卡质量”和“均衡费用”：抓到的牌、指挥官、颜色与地牌数量保持相同，只调整选入的非地牌。每种方式都用 Forge 实际对局并轮换座位，不会修改当前 Cube。</p>
  <div class="fields">
    <label>费用调整方式<select id="deck-study-variant"><option value="balanced">原均衡费用（实验）</option><option value="protected">保留已选终结牌（实验）</option></select></label>
    <label>独立轮抓桌数<select id="deck-study-pods"><option value="10">10 桌 · 流程试跑</option><option value="20" selected>20 桌 · 初步观察</option><option value="50">50 桌 · 扩大验证</option></select></label>
    <label>同时进行的对局<select id="deck-study-workers"><option value="0">自动安排</option></select></label>
    <label>单局时限（秒）<input id="deck-study-clock" type="number" min="30" max="300" step="30" value="180"></label>
  </div>
  <p class="sub" id="deck-study-budget"></p>
  <div class="actions"><button id="deck-study-run" class="primary" disabled>开始组牌方式对照</button><label>已完成的对照<select id="deck-study-history"><option value="">选择记录…</option></select></label><button id="deck-study-load">查看对照记录</button></div>
  <p class="sub">“保留已选终结牌”仅调整其他咒语；保留牌张不保证它们更容易施放，仍须看实战对照。这是较长的实验，可在任务区暂停或结束。重复对照不会自动算作新增学习样本；少量机器人对局也不能证明人类娱乐性或色组强度。</p>
  <div id="deck-study-result"></div>
</article>`);

function renderDeckStudy(result){
  const summary=result.summary;if(!summary)throw Error('对照尚未完成，请在任务区查看进度。');
  const pct=value=>value==null?'记录不足':(value*100).toFixed(1)+'%';
  const delta=value=>value==null?'记录不足':(value>=0?'+':'')+(value*100).toFixed(1)+' 个百分点';
  const cycleMetric='no_action_difference' in summary;
  const metric=cycleMetric?'前四完整周期零行动':'前四自己回合零施放';
  const interval=cycleMetric?summary.no_action_cluster_interval95:summary.no_spell_cluster_interval95;
  const base='/studies/'+encodeURIComponent(result.study_id)+'/';
  const balancedLabel=result.policy?.preserve_finishers?'保留终结的均衡费用（实验）':'均衡费用（实验）';
  const labels={normal_completion:'正常完成率足够',first4_coverage:'前四完整周期观测充足',independent_pods:'独立轮抓桌数足够',fewer_no_action_cycles:'零行动比例有改善',fewer_no_spell_turns:'零施放比例有改善',finisher_observation_not_lower:'终结施放的观测未明显下降'};
  $('deck-study-result').innerHTML=`<h3>${summary.supports_activity_improvement?'这批对照支持前期行动改善':'目前不足以确认前期行动改善'}</h3>
    <p>「${esc(result.spec.name)}」· ${result.pods} 桌 · 完整配对 ${summary.paired_complete_pods} 桌。默认组牌和当前 Cube 都未改变。${result.skipped_pods?`有 ${result.skipped_pods} 桌因无法组牌或缺少引擎支持而未运行，未重新开包。`:''}</p>
    ${result.policy?.preserve_finishers?'<p class="sub">本次额外保留原先选入的全部终结牌；即使无法达到低费或高费数量目标，也不会为满足目标而删去这些牌。</p>':''}
    <div class="table-wrap"><table><thead><tr><th>组牌方式</th><th>正常完成 / 计划</th><th>${metric}</th><th>施放过终结牌的玩家</th></tr></thead><tbody>${[['quality','单卡质量优先'],['balanced',balancedLabel]].map(([key,label])=>{const value=summary.policies[key];return `<tr><td>${label}</td><td>${value.normal} / ${result.games_per_policy}</td><td>${pct(cycleMetric?value.no_action_cycle_rate:value.no_spell_first4_rate)}</td><td>${pct(value.finisher_presence)}</td></tr>`;}).join('')}</tbody></table></div>
    ${renderEngineDiagnostics(result.games)}${renderDiagnosticActions(result.games,'study',result.study_id)}
    ${!summary.gates.normal_completion?'<p class="issue error">正常完成率未达到 90%，目前无法可靠比较组牌改善。异常局已保留，不当作正常胜负，也不据此判断某张牌较弱。</p>':''}
    <p>均衡费用相对单卡优先，${cycleMetric?'零行动':'零施放'}比例变化：<strong>${delta(cycleMetric?summary.no_action_difference:summary.no_spell_difference)}</strong>；负值表示这项比例下降。${interval?`整桌配对的描述性 95% 区间：${delta(interval[0])} 至 ${delta(interval[1])}。`:'独立观测不足，暂不显示区间。'}</p>
    <details><summary>查看观察门槛与边界</summary>${Object.entries(summary.gates).map(([key,passed])=>`<p>${passed?'✓':'待观察'} ${esc(labels[key]||key)}</p>`).join('')}<p class="sub">${esc(result.activity_definition||'旧版只记录自己回合施放，可能漏掉回合外互动。')} 零行动也可能是保留互动，不能直接当作卡手。${esc(summary.limitation)}</p></details>
    <div class="actions"><a href="${base}report.md">下载对照报告</a><a href="${base}report.json">完整数据</a><a href="${base}evidence.zip">全部牌组与原始日志</a></div>`;
}

async function refreshDeckStudies(){
  const records=await api('/api/deck-studies');
  const stamp=id=>{
    const match=/^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})_/.exec(id);
    if(!match)return id;
    const date=new Date(`${match[1]}-${match[2]}-${match[3]}T${match[4]}:${match[5]}:${match[6]}Z`);
    return date.toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false})+' · '+id.slice(-4);
  };
  $('deck-study-history').innerHTML='<option value="">选择记录…</option>'+records.map(record=>`<option value="${esc(record.id)}">${esc(record.label)} · ${record.pods} 桌 · ${esc(stamp(record.id))}</option>`).join('');
}
function updateDeckStudyBudget(){const pods=Number($('deck-study-pods').value);$('deck-study-budget').textContent=`${pods} 桌 × 两种组牌 × 每种 3 局换座，共计划 ${pods*6} 局。10 桌只适合试跑，不能据此确认效果。`;}
$('deck-study-pods').onchange=updateDeckStudyBudget;updateDeckStudyBudget();
$('deck-study-run').onclick=()=>guard(async()=>{
  const variant=$('deck-study-variant').value;
  if(variant==='protected'&&!statusInfo?.features?.protected_deck_study)throw Error('请在当前任务结束后关闭并重开助手，再选择保留终结的对照。');
  const result=await job('deck-study',{pods:Number($('deck-study-pods').value),workers:Number($('deck-study-workers').value),clock_seconds:Number($('deck-study-clock').value),deck_variant:variant});
  renderDeckStudy(result);await refreshDeckStudies();notice('组牌方式对照已保存；未修改当前 Cube 或默认组牌。');
});
$('deck-study-load').onclick=()=>guard(async()=>{
  const id=$('deck-study-history').value;if(!id)throw Error('请先选择对照记录');
  renderDeckStudy(await api('/studies/'+encodeURIComponent(id)+'/report.json'));
});
onCubeReady(()=>{configureExperiments();refreshActions();refreshDeckStudies().catch(()=>{});});
