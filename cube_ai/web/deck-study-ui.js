// Controlled comparison always uses quality-first as its fixed control.
$('report').insertAdjacentHTML('beforeend',`
<article class="panel" id="deck-study-panel">
  <span class="eyebrow">同一批抓牌，比较组牌后的体验</span>
  <h2>比较组牌后的体验 <span class="badge">实验</span></h2>
  <p>用同一批抓牌，比较质量优先与指定策略。Forge 会实际对局，每桌轮换三次座位，结果保存在对照记录中。</p>
  <div class="fields">
    <label>对照策略<select id="deck-study-variant"><option value="balanced">均衡费用</option><option value="protected">保留已选终结牌</option></select></label>
    <label>轮抓桌数<select id="deck-study-pods"><option value="10">10 桌 · 快速体验</option><option value="20" selected>20 桌 · 常规观察</option><option value="50">50 桌 · 深入比较</option></select></label>
    <label>同时进行的对局<select id="deck-study-workers"><option value="0">自动安排</option></select></label>
    <label>单局时限（秒）<input id="deck-study-clock" type="number" min="30" max="300" step="30" value="180"></label>
  </div>
  <p class="sub" id="deck-study-budget"></p>
  <div class="actions"><button id="deck-study-run" class="primary" disabled>开始组牌方式对照</button><label>已完成的对照<select id="deck-study-history"><option value="">选择记录…</option></select></label><button id="deck-study-load">查看对照记录</button></div>
  <p class="sub">观察前期是否更容易连续行动，以及终结牌是否实际用上。“保留已选终结牌”策略只替换其他咒语。</p>
  <div id="deck-study-result"></div>
</article>`);

function renderDeckStudy(result){
  const summary=result.summary;if(!summary)throw Error('对照尚未完成，请在任务区查看进度。');
  const pct=value=>value==null?'记录不足':(value*100).toFixed(1)+'%';
  const delta=value=>value==null?'记录不足':(value>=0?'+':'')+(value*100).toFixed(1)+' 个百分点';
  const cycleMetric='no_action_difference' in summary;
  const metric=cycleMetric?'前期空过比例':'前期未施放咒语';
  const interval=cycleMetric?summary.no_action_cluster_interval95:summary.no_spell_cluster_interval95;
  const base='/studies/'+encodeURIComponent(result.study_id)+'/';
  const balancedLabel=result.policy?.preserve_finishers?'保留已选终结牌':'均衡费用';
  const difference=cycleMetric?summary.no_action_difference:summary.no_spell_difference;
  const change=difference==null?'暂缺可比较记录':Math.abs(difference)<.0005?'基本持平':`${difference<0?'下降':'上升'} ${Math.abs(difference*100).toFixed(1)} 个百分点`;
  const labels={normal_completion:'正常完成率足够',first4_coverage:'前四完整周期观测充足',independent_pods:'独立轮抓桌数足够',fewer_no_action_cycles:'零行动比例有改善',fewer_no_spell_turns:'零施放比例有改善',finisher_observation_not_lower:'终结施放的观测未明显下降'};
  $('deck-study-result').innerHTML=`<h3>${summary.supports_activity_improvement?'前期行动更连贯':'本次尚未观察到明确改善'}</h3>
    <p>「${esc(result.spec.name)}」· ${result.pods} 桌 · 完整配对 ${summary.paired_complete_pods} 桌。</p>
    <p>相对质量优先，${balancedLabel}的${metric}<strong>${change}</strong>。</p>
    <div class="table-wrap"><table><thead><tr><th>组牌策略</th><th>正常完成 / 计划</th><th>${metric} ↓</th><th>用到终结牌的玩家 ↑</th></tr></thead><tbody>${[['quality','质量优先'],['balanced',balancedLabel]].map(([key,label])=>{const value=summary.policies[key];return `<tr><td>${label}</td><td>${value.normal} / ${result.games_per_policy}</td><td>${pct(cycleMetric?value.no_action_cycle_rate:value.no_spell_first4_rate)}</td><td>${pct(value.finisher_presence)}</td></tr>`;}).join('')}</tbody></table></div>
    ${renderEngineDiagnostics(result.games)}
    ${!summary.gates.normal_completion?'<p class="issue error">正常完成率不足 90%，请先查看异常对局。</p>':''}
    <details><summary>详细统计、判定依据与原始记录</summary>
      <p>${interval?`前期比例变化的整桌配对 95% 区间：${delta(interval[0])} 至 ${delta(interval[1])}。`:'当前独立观测不足，暂不显示统计区间。'}</p>
      ${Object.entries(summary.gates).map(([key,passed])=>`<p>${passed?'✓':'待观察'} ${esc(labels[key]||key)}</p>`).join('')}
      ${result.skipped_pods?`<p>有 ${result.skipped_pods} 桌因无法组牌或缺少引擎支持而未运行。</p>`:''}
      <p class="sub">${esc(result.activity_definition||'旧版只记录自己回合施放。')} 空过也可能是保留互动。${esc(summary.limitation)}</p>
      ${renderDiagnosticActions(result.games,'study',result.study_id)}
      <div class="actions"><a href="${base}report.json">完整数据</a><a href="${base}evidence.zip">牌组与原始日志</a></div>
    </details>
    <div class="actions"><a href="${base}report.md">下载对照报告</a></div>`;
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
function updateDeckStudyBudget(){const pods=Number($('deck-study-pods').value);$('deck-study-budget').textContent=`预计 ${pods*6} 局（${pods} 桌 × 两种组牌 × 三次换座）。可在任务区暂停或结束。`;}
$('deck-study-pods').onchange=updateDeckStudyBudget;updateDeckStudyBudget();
$('deck-study-run').onclick=()=>guard(async()=>{
  const variant=$('deck-study-variant').value;
  if(variant==='protected'&&!statusInfo?.features?.protected_deck_study)throw Error('请在当前任务结束后关闭并重开助手，再选择保留终结的对照。');
  const result=await job('deck-study',{pods:Number($('deck-study-pods').value),workers:Number($('deck-study-workers').value),clock_seconds:Number($('deck-study-clock').value),deck_variant:variant});
  renderDeckStudy(result);await refreshDeckStudies();notice('对照已保存，可随时查看。');
});
$('deck-study-load').onclick=()=>guard(async()=>{
  const id=$('deck-study-history').value;if(!id)throw Error('请先选择对照记录');
  renderDeckStudy(await api('/studies/'+encodeURIComponent(id)+'/report.json'));
});
onCubeReady(()=>{configureExperiments();refreshActions();refreshDeckStudies().catch(()=>{});});
