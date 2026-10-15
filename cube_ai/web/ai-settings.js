/* Keys remain in the local server; only the password field holds newly typed input. */
let aiSettings = null;
let aiAuthPoll = null;
function updateAIStatus(s) {
  if(statusInfo) statusInfo.gpt=s;
  $('gpt-status').textContent=s.configured?`${s.label} · ${s.model}`:'AI 未连接 · 离线可用';
  $('api-help').textContent=s.configured?'顾问会向所选服务发送需求、当前牌表与检索内容。建议经过本地检查，确认后才应用。':'请打开“AI 设置”，选择 ChatGPT 登录、其他 API 或本地模型。离线构筑与模拟可直接使用。';
  if(!working) { $('plan').disabled=!s.configured; $('chat').disabled=!s.configured; }
}
function renderAIProfile() {
  const id=$('ai-provider').value,p=aiSettings.profiles[id],plus=id==='chatgpt',offline=id==='offline';
  $('ai-provider-help').textContent=p.help;
  $('ai-docs').hidden=!p.docs;$('ai-docs').href=p.docs||'#';
  $('ai-api-fields').hidden=plus||offline;$('ai-model-fields').hidden=offline;
  $('ai-plus-fields').hidden=!plus;
  $('ai-base').value=p.base;$('ai-model').value=p.model;
  $('ai-key').value='';$('ai-key-label').textContent=p.key_present?'API 密钥（已保存，留空可保留）':'API 密钥';
  $('ai-key-wrap').hidden=!p.key_required;
  $('ai-style').value=p.style;$('ai-format').value=p.format;$('ai-token-param').value=p.token_parameter;
  $('ai-model-options').innerHTML='';
  $('ai-model-picker-wrap').hidden=true;$('ai-test-result').textContent='';
  $('ai-account').innerHTML='<option value="">添加新账户 / 工作空间</option>'+aiSettings.accounts.map(a=>`<option value="${esc(a.id)}">${esc(a.label)}${a.connected?'':'（已退出）'}${a.plan_enabled?'':' · 未启用套餐'}</option>`).join('');
  $('ai-account').value=aiSettings.active_account||'';
  $('ai-connection').textContent=aiSettings.status.configured?`当前已启用：${aiSettings.status.label} · ${aiSettings.status.model}`:'离线功能已就绪。AI 顾问需要完成连接并选择模型。';
  $('ai-auth-result').textContent=aiSettings.auth.message||'';
  $('ai-save').textContent=offline?'切换为离线模式':'保存并使用';
}
async function refreshAI(render=true) {
  aiSettings=await api('/api/ai/settings');
  updateAIStatus(aiSettings.status);
  if(render){
    $('ai-provider').innerHTML=Object.entries(aiSettings.profiles).map(([k,p])=>`<option value="${esc(k)}">${esc(p.label)}</option>`).join('');
    $('ai-provider').value=aiSettings.provider;renderAIProfile();
  }
  return aiSettings;
}
function aiPayload(clear=false) {
  return {provider:$('ai-provider').value,base:$('ai-base').value.trim(),model:$('ai-model').value.trim(),
    key:$('ai-key').value.trim(),clear_key:clear,style:$('ai-style').value,
    format:$('ai-format').value,token_parameter:$('ai-token-param').value};
}
async function saveAI(clear=false) {
  aiSettings=await api('/api/ai/settings',aiPayload(clear));
  $('ai-key').value='';updateAIStatus(aiSettings.status);renderAIProfile();
}
$('ai-provider').onchange=renderAIProfile;
$('ai-save').onclick=()=>guard(async()=>{await saveAI();notice('AI 设置已保存并生效，无需重启。');});
$('ai-clear-key').onclick=()=>guard(async()=>{await saveAI(true);notice('已清除此服务的本地密钥。');});
$('ai-test').onclick=()=>guard(async()=>{
  await saveAI();notice('正在测试连接与 JSON 输出…');
  const result=await api('/api/ai/test',{});$('ai-test-result').textContent=result.message;notice(result.message);
});
$('ai-models').onclick=()=>guard(async()=>{
  await saveAI();notice('正在读取当前账户的模型列表…');
  const {models}=await api('/api/ai/models',{});
  $('ai-model-options').innerHTML=models.map(m=>`<option value="${esc(m.id)}">${esc(m.label)}</option>`).join('');
  $('ai-model-picker').innerHTML='<option value="">选择一个模型…</option>'+models.map(m=>`<option value="${esc(m.id)}">${esc(m.label)}</option>`).join('');
  $('ai-model-picker-wrap').hidden=!models.length;
  notice(models.length?'模型列表已读取，选择后点击“保存并使用”。':'服务没有返回可选模型，请确认权限或手动填写。');
});
$('ai-model-picker').onchange=()=>{if($('ai-model-picker').value)$('ai-model').value=$('ai-model-picker').value;};
function startAuthPoll() {
  clearInterval(aiAuthPoll);
  aiAuthPoll=setInterval(async()=>{
    try {
      const state=await refreshAI(false);$('ai-auth-result').textContent=state.auth.message;
      if(!['pending','exchanging'].includes(state.auth.phase)){
        clearInterval(aiAuthPoll);aiAuthPoll=null;
        if(state.auth.phase==='done') { await refreshAI();notice(state.auth.message); }
        else notice(state.auth.message||'登录没有完成，请重试。',true);
      }
    }catch(e){clearInterval(aiAuthPoll);aiAuthPoll=null;notice(e.message,true);}
  },2000);
}
$('ai-login').onclick=()=>guard(async()=>{
  const s=await api('/api/ai/chatgpt/login',{account_id:$('ai-account').value});
  $('ai-auth-result').textContent=s.message;notice(s.message,s.phase==='failed');
  if(s.phase==='pending')startAuthPoll();
});
$('ai-account-use').onclick=()=>guard(async()=>{
  if(!$('ai-account').value)throw Error('请选择一个已保存的账户。');
  await api('/api/ai/chatgpt/select',{account_id:$('ai-account').value});
  await refreshAI();notice('已切换账户，请重新读取该账户的模型列表。');
});
$('ai-logout').onclick=()=>guard(async()=>{
  if(!$('ai-account').value)throw Error('请选择要退出的账户。');
  const result=await api('/api/ai/chatgpt/logout',{account_id:$('ai-account').value});
  clearInterval(aiAuthPoll);await refreshAI();notice(result.message);
});
$('advisor-settings').onclick=()=>view('ai-settings');
$('gpt-status').onclick=()=>view('ai-settings');
$('gpt-status').setAttribute('role','button');$('gpt-status').tabIndex=0;
$('gpt-status').onkeydown=e=>{if(e.key==='Enter'||e.key===' ')view('ai-settings');};
document.addEventListener('cube-ready',()=>refreshAI().then(s=>{
  if(['pending','exchanging'].includes(s.auth.phase))startAuthPoll();
}).catch(e=>notice(e.message,true)));
