// Local workspace recovery and bounded card-table rendering.
const workspaceKey='cube-atelier-workspace-v1';
const workspaceStorageKey=()=>statusInfo?.workspace_id?workspaceKey+':'+statusInfo.workspace_id:null;
let workspaceRestored=false,cardPage=1,cardQueryTimer;
const roleLabels={Commander:'指挥官',Main:'主牌',Land:'地牌'};
let workspaceEditRevision=0,workspaceSaveTimer,lastWorkspaceSnapshot='',recoverableWorkspaceCube=null;
const workspaceExtraFields=['quick-mode','quick-name','quick-bracket','quick-power','quick-deck-policy',
  'trials','forge-pods','forge-games','forge-clock','forge-workers',
  'optimization-profile','optimization-swaps','optimization-workers','optimization-search','optimization-scoring',
  'calibration-mode','calibration-goal','deck-study-variant','deck-study-pods','deck-study-workers','deck-study-clock'];

function workspaceFields(){
  return [...Array.from($('spec-form')?.elements||[]),...workspaceExtraFields.map(id=>$(id))]
    .filter(node=>node?.id&&['INPUT','SELECT','TEXTAREA'].includes(node.tagName)&&node.type!=='file'&&typeof node.value==='string');
}
function captureWorkspaceDraft(){
  return Object.fromEntries(workspaceFields().map(node=>[node.id,node.type==='checkbox'?node.checked:node.value]));
}
function applyWorkspaceDraft(draft){
  if(!draft||typeof draft!=='object'||Array.isArray(draft))return;
  for(const node of workspaceFields()){
    if(!Object.hasOwn(draft,node.id))continue;
    const value=draft[node.id];
    if(node.type==='checkbox'){if(typeof value==='boolean')node.checked=value;}
    else if(typeof value==='string'){
      if(node.tagName==='SELECT'&&!Array.from(node.options||[]).some(option=>option.value===value))continue;
      node.value=value;
    }
  }
  if($('report-deck-policy'))$('report-deck-policy').value=$('deck_policy').value;
  window.updateBracketControls?.();window.updateQuickMode?.(false);
  window.updateQuickBracket?.();
  for(const id of ['optimization-profile','deck-study-pods'])$(id)?.onchange?.();
}

function persistWorkspace(){
  clearTimeout(workspaceSaveTimer);
  // Startup navigation must not overwrite a workspace before we have read it.
  if(!workspaceRestored&&!current)return;
  const cube=current?{spec:current.spec,
    cards:current.cards.map(({name,role})=>({name,role})),
    run_id:current.run_id,provenance:current.provenance}:recoverableWorkspaceCube;
  const state={version:2,view:activeView,cube,form:captureWorkspaceDraft()};
  try{
    const key=workspaceStorageKey();
    if(!key)return;
    const snapshot=JSON.stringify(state);if(snapshot===lastWorkspaceSnapshot)return;
    localStorage.setItem(key,JSON.stringify({...state,saved_at:Date.now()}));lastWorkspaceSnapshot=snapshot;
    $('workspace-status').hidden=false;
    $('workspace-status').textContent=current?`${current.spec.name} · ${current.cards.length} 张 · 牌表和设置已保留，刷新可继续`:'设置草稿已保留，刷新可继续';
  }catch{
    $('workspace-status').hidden=false;
    $('workspace-status').textContent='浏览器暂时不能保留工作区，请下载完整备份后再关闭页面。';
  }
}

window.restoreWorkspace=async()=>{
  if(workspaceRestored||current)return;
  workspaceRestored=true;
  try{
    const key=workspaceStorageKey();if(!key)return;
    const raw=localStorage.getItem(key);if(!raw){if(workspaceEditRevision)persistWorkspace();return;}
    const state=JSON.parse(raw);
    if(!state||![1,2].includes(state.version))return;
    const cube=state.version===1?state:state.cube;
    const revision=workspaceEditRevision;
    let draft=revision?captureWorkspaceDraft():state.form;
    if(!cube){
      applyWorkspaceDraft(draft);
      if(viewChanges===0&&['home','design'].includes(state.view))view(state.view);
      persistWorkspace();notice('已恢复上次的设置草稿，可以继续构筑。');return;
    }
    if(!Array.isArray(cube.cards)||!cube.spec||cube.cards.length>900)return;
    recoverableWorkspaceCube=cube;
    applyWorkspaceDraft(draft);
    const result=await api('/api/analyze',{spec:cube.spec,cards:cube.cards});
    // A late startup response must not replace a Cube explicitly opened since.
    if(current)return;
    if(workspaceEditRevision!==revision)draft=captureWorkspaceDraft();
    result.run_id=cube.run_id;result.provenance=cube.provenance;setCube(result);
    applyWorkspaceDraft(draft);persistWorkspace();
    // Preserve navigation made before or during the asynchronous recovery.
    if(viewChanges===0&&['home','cards','report','design','advisor','guide','learning'].includes(state.view))view(state.view);
    notice('已恢复牌表和设置草稿，牌表已按当前牌库重新检查。');
  }catch(error){notice('上次工作区未能恢复。原保存记录和下载备份仍可打开：'+error.message,true);}
};

function workspaceEdited(event){
  const id=event.target?.id;if(!id)return;
  if(id!=='report-deck-policy'&&!workspaceFields().some(node=>node.id===id))return;
  workspaceEditRevision++;clearTimeout(workspaceSaveTimer);
  if(event.type==='change')persistWorkspace();
  else workspaceSaveTimer=setTimeout(persistWorkspace,250);
}
window.workspaceHasDraftEdits=()=>workspaceEditRevision>0;
document.addEventListener('input',workspaceEdited);
document.addEventListener('change',workspaceEdited);
window.addEventListener?.('beforeunload',persistWorkspace);

window.renderWorkspaceCards=()=>{
  if(!current)return;
  const colorFilter=$('color-filter'),identities=[...new Set(current.cards.map(card=>card.identity))].sort((a,b)=>a.length-b.length||a.localeCompare(b));
  const colorSignature=identities.join(',');
  if(colorFilter.dataset.groups!==colorSignature){
    const previous=colorFilter.value;
    colorFilter.innerHTML='<option value="">全部颜色</option>'+identities.map(identity=>`<option>${esc(identity)}</option>`).join('');
    colorFilter.value=identities.includes(previous)?previous:'';colorFilter.dataset.groups=colorSignature;
  }
  const query=$('card-search').value.trim().toLocaleLowerCase(),identity=$('color-filter').value,role=$('role-filter').value;
  const rows=current.cards.filter(c=>(!identity||c.identity===identity)&&(!role||c.role===role)&&
    (!query||[c.name,roleLabels[c.role],c.identity,...(c.themes||[])].join(' ').toLocaleLowerCase().includes(query)));
  const order=$('card-sort').value;
  if(order!=='original')rows.sort((a,b)=>{
    const delta=order==='mv'?a.mv-b.mv:order==='quality'?b.quality-a.quality:order==='color'?a.identity.localeCompare(b.identity):0;
    return delta||a.name.localeCompare(b.name);
  });
  const size=Number($('card-page-size').value),pages=Math.max(1,Math.ceil(rows.length/size));
  cardPage=Math.max(1,Math.min(cardPage,pages));
  const offset=(cardPage-1)*size,shown=rows.slice(offset,offset+size);
  $('shown').textContent=`找到 ${rows.length} / ${current.cards.length} 张`;
  $('card-rows').innerHTML=shown.map(c=>`<tr><td><button class="name-link" data-name="${esc(c.name)}">${esc(c.name)}</button></td><td><span class="mana-identity">${esc(c.identity)}</span></td><td>${c.mv}</td><td>${esc(roleLabels[c.role]||c.role)}</td><td>${c.quality}</td><td><button data-replace="${esc(c.name)}" ${working?'disabled':''}>找替换</button></td></tr>`).join('')||'<tr><td colspan="6" class="empty-state">没有符合条件的牌。试着缩短搜索词，或选择全部颜色与槽位。</td></tr>';
  $('card-page-info').textContent=`第 ${cardPage} / ${pages} 页${rows.length?` · ${offset+1}–${offset+shown.length} 张`:''}`;
  $('card-prev').disabled=cardPage<=1;$('card-next').disabled=cardPage>=pages;
};

$('card-rows').onclick=event=>{
  const button=event.target.closest('button');if(!button)return;
  if(button.dataset.name)detail(button.dataset.name).catch(error=>notice(error.message,true));
  else if(button.dataset.replace)guard(()=>replace(button.dataset.replace));
};
for(const id of ['card-search','color-filter','role-filter','card-sort','card-page-size']){
  $(id).setAttribute('aria-label',({'card-search':'搜索当前牌表','color-filter':'按颜色筛选','role-filter':'按槽位筛选','card-sort':'牌表排序','card-page-size':'每页张数'})[id]);
  $(id).oninput=()=>{
    clearTimeout(cardQueryTimer);
    const update=()=>{cardPage=1;renderCards();};
    if(id==='card-search')cardQueryTimer=setTimeout(update,120);else update();
  };
}
$('card-prev').onclick=()=>{cardPage--;renderCards();};
$('card-next').onclick=()=>{cardPage++;renderCards();};
document.addEventListener('cube-changed',()=>{cardPage=1;recoverableWorkspaceCube=null;persistWorkspace();});
document.addEventListener('workspace-view',persistWorkspace);
onCubeReady(()=>window.restoreWorkspace());

$('close-assistant').onclick=async()=>{
  persistWorkspace();$('close-assistant').disabled=true;
  try{
    const result=await api('/api/shutdown',{});
    window.cubeServiceClosed=true;clearTimeout(taskMonitorTimer);
    lock(true);$('connection').textContent='● 已退出，后台资源已释放';notice(result.message);
  }catch(error){notice(error.message,true);$('close-assistant').disabled=false;}
};
