// One adaptive monitor: no overlapping requests and quiet while the tab is hidden.
let taskMonitorTimer,taskMonitorLoading=false,taskPanelSignature='',taskMonitorActive=false;
const taskLabels={build:'生成 Cube',repair:'修订 Cube',stress:'轮抓检查',forge:'Forge 实战',optimize:'实战改进',calibrate:'机器测速','deck-study':'组牌方式对照','diagnose-game':'对局异常诊断','learn-games':'更新实战评分',chat:'AI 分析',plan:'构筑规划',legacy:'旧后台任务'};
const taskStateLabels={queued:'排队中',running:'运行中',pausing:'等待安全暂停',paused:'已暂停',cancelling:'正在结束',cancelled:'已结束',done:'已完成',failed:'未完成'};
const liveTaskStates=new Set(['queued','running','pausing','paused','cancelling']);

function taskDuration(job){
  if(!job.created_at)return '';
  const seconds=Math.max(0,Math.floor((job.finished_at||Date.now()/1000)-job.created_at));
  return seconds<60?`${seconds} 秒`:`${Math.floor(seconds/60)} 分 ${seconds%60} 秒`;
}

function taskRow(job){
  const active=liveTaskStates.has(job.state);
  const controls=active&&job.controllable?`${!job.legacy?`<button class="task-control" data-task="${esc(job.id)}" data-action="${['paused','pausing'].includes(job.state)?'resume':'pause'}" ${job.state==='cancelling'?'disabled':''}>${['paused','pausing'].includes(job.state)?'继续':'暂停'}</button>`:''}<button class="task-control danger-button" data-task="${esc(job.id)}" data-action="cancel" ${job.state==='cancelling'?'disabled':''}>${job.legacy?'结束旧后台全部任务':'强制结束'}</button>`:'';
  return `<div class="task-row"><div><strong>${esc(taskLabels[job.operation]||job.operation)} · ${esc(taskStateLabels[job.state]||job.state)}</strong><p>${esc(job.cube_name||'')}${taskDuration(job)?` · ${taskDuration(job)}（含等待与暂停）`:''}</p><p>${esc(job.error||job.progress)}</p>${job.note?`<p class="sub">${esc(job.note)}</p>`:''}${job.checkpoint?.completed_game_records?`<p class="sub">已保存 ${job.checkpoint.completed_game_records} 条比赛记录 · <a href="/api/job/checkpoint?id=${encodeURIComponent(job.id)}" download="已完成对局.json">下载记录</a></p>`:''}</div><div class="actions">${controls}${job.state==='done'?`<button class="task-control" data-result="${esc(job.id)}">查看结果</button>`:''}</div></div>`;
}

async function showTaskResult(id){
  const job=await api('/api/job?id='+encodeURIComponent(id));
  if(job.state!=='done'||!job.result)throw Error('结果尚未准备好，请稍后再看。');
  const result=job.result;
  if(['build','repair'].includes(job.operation)){setCube(result);await refreshRuns();view('cards');}
  else if(job.operation==='forge'){renderForge(result);view('report');$('forge-result').scrollIntoView({block:'start'});await refreshForge();}
  else if(job.operation==='optimize'){renderOptimization(result);view('report');$('optimization-result').scrollIntoView({block:'start'});await refreshOptimizations();}
  else if(job.operation==='deck-study'){renderDeckStudy(result);view('report');$('deck-study-result').scrollIntoView({block:'start'});await refreshDeckStudies();}
  else if(job.operation==='diagnose-game'){renderNativeDiagnostic(result);view('report');$('native-diagnostic-panel').scrollIntoView({block:'start'});}
  else if(job.operation==='plan'){fillSpec(result.spec);view('design');}
  else if(job.operation==='stress'){
    $('stress-result').innerHTML=`<h3>${result.trials} 桌轮抓已完成</h3><p>合法组牌率 ${(result.buildable_rate*100).toFixed(1)}%。这是组牌与法术力检查，不代表实战胜率。</p><details><summary>查看完整轮抓结果</summary><pre>${esc(JSON.stringify(result,null,2))}</pre></details>`;
    view('report');$('stress-result').scrollIntoView({block:'start'});
  }else if(job.operation==='chat'){
    $('ai-output').innerHTML=`<h3>已完成的顾问建议</h3><p>${esc(result.analysis||result.summary||'分析已完成，完整结果见下方。')}</p><details><summary>完整建议</summary><pre>${esc(JSON.stringify(result,null,2))}</pre></details>`;view('advisor');
  }else{
    const target=job.operation==='calibrate'?'calibration-result':'learning-result';
    $(target).innerHTML=`<h3>${esc(taskLabels[job.operation])}已完成</h3><details open><summary>查看结果</summary><pre>${esc(JSON.stringify(result,null,2))}</pre></details>`;
    view('report');$(target).scrollIntoView({block:'start'});await refreshPerformance();
  }
  notice(`已打开${job.cube_name?'「'+job.cube_name+'」的':''}${taskLabels[job.operation]||'任务'}结果。`);
}

async function refreshTaskMonitor(){
  if(taskMonitorLoading)return;
  taskMonitorLoading=true;
  try{
    const jobs=await api('/api/jobs'),panel=$('task-monitor');
    const active=jobs.filter(job=>liveTaskStates.has(job.state));
    const recent=jobs.filter(job=>!liveTaskStates.has(job.state)).slice(-5).reverse();
    taskMonitorActive=active.length>0;
    const signature=JSON.stringify([active,recent,Math.floor(Date.now()/10000)]);
    if(signature===taskPanelSignature)return;taskPanelSignature=signature;
    panel.hidden=!active.length&&!recent.length;if(panel.hidden)return;
    const wasOpen=panel.querySelector('details')?.open;
    panel.innerHTML=`<h2>任务与进度</h2>${active.length?'<p class="sub">暂停会等待当前步骤结束并释放空闲对局内存；继续时可能需要稍等。强制结束会回收该任务的计算进程，已保存结果保留。</p>'+active.map(taskRow).join(''):'<p class="sub">当前没有进行中的任务。</p>'}${recent.length?`<details ${wasOpen?'open':''}><summary>最近任务 · ${recent.length} 条记录</summary>${recent.map(taskRow).join('')}</details>`:''}`;
    for(const button of panel.querySelectorAll('button[data-task]'))button.onclick=async()=>{
      button.disabled=true;
      try{const result=await api('/api/task/control',{id:button.dataset.task,action:button.dataset.action});notice(result.progress);taskPanelSignature='';await refreshTaskMonitor();}
      catch(error){notice(error.message,true);button.disabled=false;}
    };
    for(const button of panel.querySelectorAll('button[data-result]'))button.onclick=()=>guard(()=>showTaskResult(button.dataset.result));
  }finally{taskMonitorLoading=false;}
}

function scheduleTaskMonitor(immediate=false){
  clearTimeout(taskMonitorTimer);
  if(window.cubeServiceClosed)return;
  taskMonitorTimer=setTimeout(async()=>{
    if(!document.hidden&&navigator.onLine){try{await refreshTaskMonitor();}catch{}}
    scheduleTaskMonitor();
  },immediate?0:document.hidden?30000:taskMonitorActive?1500:12000);
}
document.addEventListener('visibilitychange',()=>scheduleTaskMonitor(!document.hidden));
window.addEventListener('online',()=>scheduleTaskMonitor(true));
onCubeReady(()=>scheduleTaskMonitor(true));
