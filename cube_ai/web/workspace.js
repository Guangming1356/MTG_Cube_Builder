// Local workspace recovery and bounded card-table rendering.
const workspaceKey='cube-atelier-workspace-v1';
const workspaceStorageKey=()=>statusInfo?.workspace_id?workspaceKey+':'+statusInfo.workspace_id:null;
let workspaceRestored=false,cardPage=1,cardQueryTimer;
const roleLabels={Commander:'指挥官',Main:'主牌',Land:'地牌'};

function persistWorkspace(){
  if(!current)return;
  const state={version:1,view:activeView,spec:current.spec,
    cards:current.cards.map(({name,role})=>({name,role})),
    run_id:current.run_id,provenance:current.provenance,saved_at:Date.now()};
  try{
    const key=workspaceStorageKey();
    if(!key)return;
    localStorage.setItem(key,JSON.stringify(state));
    $('workspace-status').hidden=false;
    $('workspace-status').textContent=`${current.spec.name} · ${current.cards.length} 张 · 已在此浏览器保留，刷新可继续`;
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
    const raw=localStorage.getItem(key);if(!raw)return;
    const state=JSON.parse(raw);
    if(state.version!==1||!Array.isArray(state.cards)||!state.spec||state.cards.length>900)return;
    const result=await api('/api/analyze',{spec:state.spec,cards:state.cards});
    // A late startup response must not replace a Cube explicitly opened since.
    if(current)return;
    result.run_id=state.run_id;result.provenance=state.provenance;setCube(result);
    // Preserve navigation made before or during the asynchronous recovery.
    if(viewChanges===0&&['home','cards','report','design','advisor','guide','learning'].includes(state.view))view(state.view);
    notice('已恢复上次打开的牌表，并按当前牌库重新检查。');
  }catch(error){notice('上次工作区未能恢复。原保存记录和下载备份仍可打开：'+error.message,true);}
};

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
document.addEventListener('cube-changed',()=>{cardPage=1;persistWorkspace();});
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
