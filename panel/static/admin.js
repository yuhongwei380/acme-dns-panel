'use strict';
let csrf = '', tab = 'domains', query = '', logId = null;
let state = {accounts:[],domains:[],providers:[],jobs:[],settings:{}};
async function api(path, method = 'GET', body) {
  const headers = {'X-Panel-Request':'1'};
  if (csrf) headers['X-CSRF-Token'] = csrf;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const response = await fetch('/api' + path, {method, headers, body:body === undefined ? undefined : JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) {
    if (response.status === 401 && path !== '/login') showLogin();
    throw new Error(Array.isArray(data.detail) ? data.detail.map(d => d.msg).join('；') : data.detail || '请求失败');
  }
  return data;
}
function showLogin() { csrf = ''; $('#login-view').hidden = false; $('#app-view').hidden = true; $('#user-bar').hidden = true; for (const dialog of document.querySelectorAll('dialog[open]')) dialog.close(); }
async function enter(session) { csrf = session.csrf; $('#login-password').value = ''; $('#login-view').hidden = true; $('#app-view').hidden = false; $('#user-bar').hidden = false; await reload(); }
async function reload(renderView = true) {
  const [accounts,domains,providers,jobs,settings] = await Promise.all(['/accounts','/domains','/providers','/jobs','/settings'].map(path => api(path)));
  state = {accounts,domains,providers,jobs,settings};
  if (renderView) render();
}
function publicBase() {
  const url = new URL(location.origin); url.protocol = 'http:'; url.port = state.settings.public_port;
  return url.origin;
}
function render() {
  $('.tabs').querySelectorAll('[data-tab]').forEach(button => { button.classList.toggle('active', button.dataset.tab === tab); button.setAttribute('aria-current', button.dataset.tab === tab ? 'page' : 'false'); });
  if (tab === 'domains') renderDomains();
  if (tab === 'accounts') renderAccounts();
  if (tab === 'jobs') renderJobs();
  if (tab === 'settings') renderSettings();
  if (tab === 'script') renderScript().catch(error=>toast(error.message));
}
function renderDomains() {
  const domains = state.domains.filter(d => d.name.includes(query.toLowerCase()));
  const active = state.jobs.filter(j => ['running','queued'].includes(j.status)).length;
  $('#content').innerHTML = `<div class="heading"><div><div class="eyebrow">DNS → CERTIFICATE → DOWNLOAD</div><h1>域名证书</h1><p>管理签发与续期，让每个域名都有稳定的下载地址。</p></div><button class="primary" data-action="add-domain">＋ 添加域名</button></div>${!state.settings.acme_installed ? '<div class="notice warn">acme.sh 尚未安装。请在 Linux 运行部署脚本；当前可先配置 DNS 账户和域名。</div>' : ''}<div class="summary"><div><strong>${state.domains.length}</strong><span>个域名</span></div><div><strong>${state.domains.filter(d=>d.certificate.status==='valid').length}</strong><span>张有效证书</span></div><div><strong>${active}</strong><span>个进行中任务</span></div></div><div class="panel"><div class="toolbar"><input id="domain-search" type="search" aria-label="搜索域名" placeholder="搜索域名…" value="${esc(query)}"><a href="${esc(publicBase())}" target="_blank" rel="noopener">打开只读下载页 ↗</a></div>${domains.length ? `<div class="table-wrap"><table><thead><tr><th>域名 / 覆盖范围</th><th>证书状态</th><th>到期日期</th><th>DNS 账户</th><th>操作</th></tr></thead><tbody>${domains.map(d => `<tr><td><strong class="domain-title">${esc(d.name)}</strong><span class="sub mono">${d.wildcard ? '*.' + esc(d.name) : '单域名'} · ${esc(d.key_type)}${(d.server==='letsencrypt_test'||d.server==='https://acme-staging-v02.api.letsencrypt.org/directory') ? ' · 测试 CA' : ''}</span></td><td>${badge(d.job && ['running','queued'].includes(d.job.status) ? d.job.status : d.certificate.status)}<span class="sub">${d.auto_renew ? '自动续期已开启' : '自动续期已关闭'}</span></td><td class="mono">${dateText(d.certificate.expires)}<span class="sub">${d.certificate.days_left === null ? '等待首次签发' : d.certificate.days_left < 0 ? '已过期' : '剩余 ' + d.certificate.days_left + ' 天'}</span></td><td>${esc(d.account_name)}<span class="sub">${esc(state.providers.find(p=>p.id===d.provider)?.name)}</span></td><td><div class="actions"><button data-action="issue" data-id="${d.id}" ${d.job && ['queued','running'].includes(d.job.status) ? 'disabled' : ''}>${d.issued ? '检查续期' : '申请证书'}</button>${d.certificate.available ? `<button data-action="download" data-id="${d.id}">下载地址</button>` : ''}<button class="quiet" data-action="edit-domain" data-id="${d.id}">设置</button><button class="danger" data-action="delete-domain" data-id="${d.id}">移除</button></div></td></tr>`).join('')}</tbody></table></div>` : `<div class="empty"><h3>${query ? '未找到域名' : '从第一个域名开始'}</h3><p>${query ? '试试其他关键词。' : '先配置 DNS 账户，再添加域名申请普通或通配证书。'}</p>${query ? '' : '<button data-action="add-domain">添加域名</button>'}</div>`}</div><p class="footnote">证书统一安装在 <span class="mono">${esc(state.settings.root)}/ssl-renew/域名/</span> · 每天检查一次续期</p>`;
  $('#domain-search').addEventListener('input', event => { const position = event.target.selectionStart; query = event.target.value; renderDomains(); $('#domain-search').focus(); try { $('#domain-search').setSelectionRange(position,position); } catch {} });
}
function renderAccounts() {
  $('#content').innerHTML = `<div class="heading"><div><div class="eyebrow">DNS CREDENTIALS</div><h1>DNS 账户</h1><p>同一服务商可配置多个账户，密钥按账户隔离保存。</p></div><button class="primary" data-action="add-account">＋ 添加账户</button></div>${state.accounts.length ? `<div class="grid">${state.accounts.map(a => `<article class="panel account-card"><div class="account-head"><h3>${esc(a.name)}</h3><span class="badge good">已配置</span></div><span class="mono small">${esc(state.providers.find(p=>p.id===a.provider)?.plugin)}</span><p>${esc(state.providers.find(p=>p.id===a.provider)?.name)} · ${state.domains.filter(d=>d.account_id===a.id).length} 个域名<br>密钥已保存，编辑时留空可保留现有值。</p><div class="actions"><button data-action="edit-account" data-id="${a.id}">编辑账户</button><button class="danger" data-action="delete-account" data-id="${a.id}">移除</button></div></article>`).join('')}</div>` : '<div class="panel empty"><h3>添加你的 DNS 服务商</h3><p>支持阿里云、腾讯云、DNSPod、Cloudflare 和华为云。</p><button class="primary" data-action="add-account">添加 DNS 账户</button></div>'}`;
}
function renderJobs() {
  $('#content').innerHTML = `<div class="heading"><div><div class="eyebrow">ISSUE & RENEWAL</div><h1>任务记录</h1><p>签发与续期串行执行，日志中的账户密钥自动脱敏。</p></div><button data-action="refresh">刷新记录</button></div><div class="panel">${state.jobs.length ? `<div class="table-wrap"><table><thead><tr><th>域名</th><th>操作</th><th>状态</th><th>创建时间</th><th>日志</th></tr></thead><tbody>${state.jobs.map(j=>`<tr><td class="mono">${esc(j.domain_name)}</td><td>${j.action==='issue'?'申请证书':'检查续期'}</td><td>${badge(j.status)}</td><td class="mono small">${timeText(j.created)}</td><td><button data-action="logs" data-id="${j.id}">查看日志</button></td></tr>`).join('')}</tbody></table></div>` : '<div class="empty"><h3>还没有任务记录</h3><p>添加域名后点击「申请证书」，可以在这里跟踪进度。</p></div>'}</div>`;
}
function renderSettings() {
  $('#content').innerHTML = `<div class="heading"><div><div class="eyebrow">SERVICE CONFIGURATION</div><h1>服务设置</h1><p>设置 ACME 联系邮箱与证书下载端口。</p></div></div><div class="form-grid"><div><form id="settings-form" class="panel form-panel"><h3>证书服务</h3><label>ACME 联系邮箱 <span class="required-marker" aria-hidden="true">*</span><span class="muted">（必填）</span><input type="email" name="email" maxlength="254" value="${esc(state.settings.email)}" placeholder="you@example.com" required><span class="field-help">申请证书前必须填写，用于注册 CA 账户与接收证书相关通知。</span></label><div class="form-actions"><button type="submit" class="primary">保存设置</button></div></form><form id="download-form" class="panel form-panel"><h3>局域网下载服务</h3><label>下载端口<input type="number" name="public_port" min="1" max="65535" required value="${state.settings.public_port}"><span class="field-help">修改后点击重载即可生效，管理页面和证书任务继续运行。</span></label><p class="small muted">当前下载地址</p><a class="mono small path" id="download-address" href="${esc(publicBase())}" target="_blank" rel="noopener">${esc(publicBase())} ↗</a><p id="download-status" class="field-help" role="status"></p><div class="form-actions"><button type="submit" class="primary">重载下载服务</button></div></form><form id="password-form" class="panel form-panel"><h3>管理员密码 <span class="mono muted small">admin</span></h3>${secretField('current_password','当前密码',true,'current-password')}${secretField('new_password','新密码',true,'new-password')}<div class="form-actions"><button type="submit">更新密码</button></div></form></div><aside class="panel form-panel"><h3>运行信息</h3><div class="system-line"><span>面板版本</span><span class="mono">${esc(state.settings.version)}</span></div><div class="system-line"><span class="muted">acme.sh</span><span>${state.settings.acme_installed?'已安装':'待安装'}</span></div><div class="system-line"><span class="muted">管理端口</span><span class="mono">${state.settings.admin_port}</span></div><div class="system-line"><span class="muted">下载端口</span><span class="mono" id="runtime-public-port">${state.settings.public_port}</span></div><div class="system-line"><span class="muted">续期检查</span><span>每天一次</span></div><p class="footnote">统一数据目录</p><p class="mono small path">${esc(state.settings.root)}</p><p class="footnote">管理监听地址和端口在 config.toml 中配置，修改后需重启服务。下载端口可在此页面修改并重载。</p></aside></div>`;
  initEyes($('#content'));
  $('#settings-form').addEventListener('submit', async event => {event.preventDefault(); await submit(event.target, async () => { await api('/settings','PUT',Object.fromEntries(new FormData(event.target))); await reload(false); toast('服务设置已保存'); });});
  $('#download-form').addEventListener('submit',async event=>{
    event.preventDefault(); const button=$('button[type="submit"]',event.target); button.disabled=true;
    const status=$('#download-status'); status.textContent='正在重载下载服务…';
    try {
      const result=await api('/public-service/reload','POST',{public_port:Number(new FormData(event.target).get('public_port'))});
      state.settings.public_port=result.public_port;
      const address=$('#download-address'); address.href=publicBase(); address.textContent=publicBase()+' ↗';
      $('#runtime-public-port').textContent=result.public_port;
      $('#download-status').textContent='下载服务已就绪，新端口已保存。'; toast('下载服务已重载');
    } catch(error) {status.textContent=error.message; toast(error.message);} finally {button.disabled=false;}
  });
  $('#password-form').addEventListener('submit', async event => {event.preventDefault(); await submit(event.target, async () => { await api('/password','POST',Object.fromEntries(new FormData(event.target))); showLogin(); toast('密码已更新，请重新登录'); });});
}
async function renderScript() {
  const script = await api('/client-script');
  if (tab !== 'script') return;
  const example = 'DOMAIN="example.com"\nFULLCHAIN_URL="http://127.0.0.1:8001/example.com/fullchain.pem"\nPRIVKEY_URL="http://127.0.0.1:8001/example.com/privkey.pem"\nCERT_DIR="/home/vesoft/ssl-renewal/example.com"\nLOG_FILE="/var/log/ssl-renew-example.com.log"';
  $('#content').innerHTML = `<div class="heading"><div><div class="eyebrow">CLIENT SCRIPT</div><h1>客户端脚本</h1><p>编辑一份模板，为每张证书生成对应的 ssl-renew.sh。</p></div></div><form id="script-form" class="panel form-panel"><label for="script-content">脚本内容<textarea id="script-content" name="content" class="script-editor" maxlength="262144" spellcheck="false" autocapitalize="off" autocomplete="off" wrap="off" placeholder="#!/bin/bash">${esc(script.content)}</textarea></label><p class="field-help">保存后在各证书卡片公开下载，无需登录。通用脚本可用 example.com 作为示例域名。下载时自动替换域名、证书下载地址，以及目录和日志路径中的 example.com。也兼容 DOMAIN、FULLCHAIN_URL、PRIVKEY_URL 的单行配置。清空并保存可停止下载。</p><div class="form-actions"><button type="submit" class="primary">保存脚本</button></div></form><div class="panel form-panel script-download"><h3>模板配置示例</h3><pre class="script-example">${esc(example)}</pre><p class="field-help">下载地址自动使用当前访问主机和下载端口；example.com 自动替换为所选证书的主域名。也支持 {{DOMAIN}}、{{FULLCHAIN_URL}}、{{PRIVKEY_URL}} 和 {{DOWNLOAD_BASE}} 占位符。</p>${script.content.trim()&&!script.adaptable?'<p class="error">当前脚本缺少域名或下载地址配置，请按示例补充后保存。</p>':''}</div>`;
  $('#script-form').addEventListener('submit',async event=>{
    event.preventDefault();
    await submit(event.target,async()=>{
      await api('/client-script','PUT',{content:$('#script-content').value});
      await renderScript();
      toast('客户端脚本已保存');
    });
  });
}
function editor(title, body) { $('#editor-title').textContent = title; $('#editor-body').innerHTML = body; initEyes($('#editor-body')); enhanceSelects($('#editor-body')); $('#editor').showModal(); }
async function submit(form, fn) {
  const button = $('button[type="submit"]', form); button.disabled = true;
  try { await fn(); } catch (error) {toast(error.message);} finally {button.disabled = false;}
}
function accountEditor(id) {
  const account = state.accounts.find(a=>a.id===id);
  editor(account ? '编辑 DNS 账户' : '添加 DNS 账户', `<form id="account-form"><label>账户名称<input name="name" maxlength="80" required value="${esc(account?.name || '')}" placeholder="例如：阿里云生产账户"></label><label>DNS 服务商<select name="provider" id="provider-select" ${account?'disabled':''}>${state.providers.map(p=>`<option value="${p.id}" ${p.id===account?.provider?'selected':''}>${esc(p.name)}</option>`).join('')}</select></label><div id="credential-fields"></div><div class="form-actions"><button type="button" data-close="editor">取消</button><button type="submit" class="primary">保存账户</button></div></form>`);
  const fields = () => {
    const provider = state.providers.find(p=>p.id===$('#provider-select').value);
    $('#credential-fields').innerHTML = `<div class="notice provider-guide">${provider.hint.split('\n').map(line=>`<p>${esc(line)}</p>`).join('')}</div>${provider.fields.map(f=>`<div class="credential-field">${secretField(f.name,`${f.label}${f.required?(account?'':'（必填）'):'（可选）'}`, !account && f.required,'off',account?'留空保留已保存的值':'')}${f.help ? `<p class="field-help">${esc(f.help)}</p>` : ''}</div>`).join('')}${account ? '<p class="footnote">可选字段填写 - 可清空；其他字段留空保留。</p>' : ''}`; initEyes($('#credential-fields'));
  };
  fields(); $('#provider-select').addEventListener('change',fields);
  $('#account-form').addEventListener('submit', async event => { event.preventDefault(); await submit(event.target, async () => {
    const form = new FormData(event.target); const provider = $('#provider-select').value; const credentials = {};
    for (const f of state.providers.find(p=>p.id===provider).fields) {const value = String(form.get(f.name) || ''); if (value || !account) credentials[f.name] = !f.required && value==='-' ? '' : value;}
    await api(account?'/accounts/'+id:'/accounts',account?'PUT':'POST',{name:form.get('name'),provider,credentials}); $('#editor').close(); await reload(); toast('DNS 账户已保存');
  }); });
}
async function domainEditor(id) {
  const domain = state.domains.find(d=>d.id===id);
  if (!domain) {
    state.settings = await api('/settings');
    if (!String(state.settings.email || '').trim()) {
      toast('未填写 ACME 联系邮箱，无法添加证书。请先在「服务设置」中填写并保存');
      return;
    }
  }
  state.accounts = await api('/accounts');
  if (!state.accounts.length) {toast('未检测到 DNS 账户，无法添加域名。请先在「DNS 账户」中完成配置'); return;}
  const authorities = [['letsencrypt', "Let's Encrypt"], ['zerossl', 'ZeroSSL'], ['buypass', 'Buypass（已停止签发）'], ['other', '其他']];
  const customServer = !!domain && !authorities.some(([value]) => value === domain.server);
  const selectedServer = customServer ? 'other' : (domain?.server || 'letsencrypt');
  editor(domain?'域名设置':'添加域名', `<form id="domain-form"><label>主域名<input name="name" required value="${esc(domain?.name || '')}" placeholder="example.com" ${domain?'readonly':''}><span class="field-help">不包含协议或 *. 前缀；支持国际化域名。</span></label><label>DNS 账户<select name="account_id" ${domain?'disabled':''}>${state.accounts.map(a=>`<option value="${a.id}" ${a.id===domain?.account_id?'selected':''}>${esc(a.name)}</option>`).join('')}</select></label><label class="check"><input name="wildcard" type="checkbox" ${!domain||domain.wildcard?'checked':''} ${domain?'disabled':''}>同时申请通配域名（*.example.com）</label><div class="two-col"><label>密钥类型<select name="key_type" ${domain?'disabled':''}>${['ec-256','2048','4096'].map(k=>`<option value="${k}" ${k===domain?.key_type?'selected':''}>${k==='ec-256'?'ECC P-256（推荐）':'RSA '+k}</option>`).join('')}</select></label><label>证书颁发机构<select name="server" ${domain?'disabled':''}>${authorities.map(([value, label]) => `<option value="${value}" ${value===selectedServer?'selected':''}>${esc(label)}</option>`).join('')}</select></label></div><label id="custom-server-field" hidden>ACME Directory 地址<input type="url" name="custom_server" maxlength="2048" value="${esc(customServer ? domain.server : '')}" placeholder="https://ca.example.com/acme/directory" ${domain?'readonly':''}><span class="field-help">填写机构提供的完整 HTTPS ACME Directory 地址。</span></label><p id="ca-hint" class="field-help" hidden></p><label>DNS 等待时间（秒）<input type="number" name="dns_sleep" min="0" max="1800" value="${domain?.dns_sleep || 0}" required><span class="field-help">0 表示 acme.sh 自动检查 DNS 传播；可指定 120 秒。</span></label><label class="check"><input type="checkbox" name="auto_renew" ${!domain||domain.auto_renew?'checked':''}>每天自动检查续期</label><div class="form-actions"><button type="button" data-close="editor">取消</button><button type="submit" class="primary">${domain?'保存设置':'添加域名'}</button></div></form>`);
  const serverSelect = $('#domain-form select[name="server"]');
  const customInput = $('#domain-form input[name="custom_server"]');
  const updateAuthority = () => {
    const other = serverSelect.value === 'other';
    $('#custom-server-field').hidden = !other;
    customInput.disabled = !other;
    customInput.required = other && !domain;
    const hint = $('#ca-hint');
    hint.textContent = serverSelect.value === 'buypass' ? 'Buypass 已停止 TLS/SSL 证书签发与续期，请选择其他机构。' : serverSelect.value === 'zerossl' ? 'ZeroSSL 注册需要 EAB；acme.sh 会使用服务设置中的联系邮箱自动获取。' : customServer && domain.server === 'letsencrypt_test' ? '此域名使用旧版 Let’s Encrypt 测试 CA，证书不受信任；使用正式 CA 需移除后重新添加。' : other ? '自定义机构须兼容 ACME；如需额外 EAB 凭据，请先在对应 acme.sh 账户中完成注册。' : '';
    hint.hidden = !hint.textContent;
  };
  serverSelect.addEventListener('change', updateAuthority);
  updateAuthority();
  $('#domain-form').addEventListener('submit',async event=>{event.preventDefault();await submit(event.target,async()=>{
    const form = new FormData(event.target);
    const body = {name:form.get('name'),account_id:domain?.account_id || form.get('account_id'),wildcard:domain?!!domain.wildcard:form.has('wildcard'),key_type:domain?.key_type || form.get('key_type'),server:domain?.server || (form.get('server')==='other' ? String(form.get('custom_server') || '').trim() : form.get('server')),dns_sleep:Number(form.get('dns_sleep')),auto_renew:form.has('auto_renew')};
    await api(domain?'/domains/'+id:'/domains',domain?'PUT':'POST',body);$('#editor').close();await reload();toast(domain?'域名设置已保存':'域名已添加，可以申请证书');
  });});
}
function confirmAction(title,message,action) {
  const dialog = $('#confirm');
  const form = $('#confirm-form');
  const button = $('#confirm-yes');
  $('#confirm-title').textContent = title;
  $('#confirm-message').textContent = message;
  $('#confirm-error').textContent = '';
  $('#confirm-password-field').innerHTML = secretField('confirm-password','再次输入管理员密码',true,'current-password');
  $('#confirm-password').maxLength = 256;
  initEyes($('#confirm-password-field'));
  button.disabled = false;
  button.textContent = '确认移除';
  form.onsubmit = async event => {
    event.preventDefault();
    if (button.disabled || !form.reportValidity()) return;
    const input = $('#confirm-password');
    const password = input.value;
    input.value = '';
    $('#confirm-error').textContent = '';
    button.disabled = true;
    button.textContent = '正在验证并移除…';
    const closeButtons = dialog.querySelectorAll('[data-close]');
    closeButtons.forEach(close => { close.disabled = true; });
    try { await action(password); if ($('#confirm-password') === input) dialog.close(); }
    catch(error) {
      if ($('#confirm-password') === input) { $('#confirm-error').textContent = error.message; input.focus(); }
    }
    finally {
      closeButtons.forEach(close => { close.disabled = false; });
      button.disabled = false; button.textContent = '确认移除';
    }
  };
  dialog.showModal();
  $('#confirm-password').focus();
}
$('#confirm').addEventListener('cancel', event => {
  if ($('#confirm-yes').disabled) event.preventDefault();
});
$('#confirm').addEventListener('close', () => {
  $('#confirm-password-field').replaceChildren();
  $('#confirm-error').textContent = '';
  $('#confirm-form').onsubmit = null;
});
async function updateLog() {
  if (!logId || !$('#logs').open) return;
  const job = await api('/jobs/'+logId); $('#log-status').textContent = job.domain_name + ' · ' + (statusMap[job.status]?.[0] || job.status);
  $('#log-content').textContent = job.log || '任务等待执行…';
}
document.addEventListener('click', async event=>{
  const nav=event.target.closest('[data-tab]');if(nav){tab=nav.dataset.tab;render();return;}
  const button=event.target.closest('[data-action]');if(!button)return;
  const {action,id}=button.dataset;
  try {
    if(action==='add-account')accountEditor(); if(action==='edit-account')accountEditor(id);
    if(action==='add-domain')await domainEditor();if(action==='edit-domain')await domainEditor(id);
    if(action==='refresh')await reload();
    if(action==='delete-domain')confirmAction('移除域名证书',`即将移除 ${state.domains.find(d=>d.id===id)?.name || ''}。移除后停止续期，并从只读页面撤下。磁盘上的证书保留以便恢复。`,async password=>{await api('/domains/'+id,'DELETE',{password});await reload();toast('域名已移除');});
    if(action==='delete-account')confirmAction('移除 DNS 账户',`即将移除 ${state.accounts.find(a=>a.id===id)?.name || ''}。账户不能被域名使用。移除后删除面板保存的密钥文件；acme.sh 历史账户数据保留在磁盘。`,async password=>{await api('/accounts/'+id,'DELETE',{password});await reload();toast('DNS 账户已移除');});
    if(action==='issue') {const domain=state.domains.find(d=>d.id===id);button.disabled=true;const job=await api('/domains/'+id+'/jobs','POST',{action:domain.issued?'renew':'issue'});await reload();logId=job.id;$('#logs').showModal();await updateLog();}
    if(action==='logs'){logId=id;$('#logs').showModal();await updateLog();}
    if(action==='download'){const domain=state.domains.find(d=>d.id===id);await copyText(wgetCommand(publicBase(),domain.name));}
  } catch(error){toast(error.message);} finally{button.disabled=false;}
});
$('#login-form').addEventListener('submit',async event=>{event.preventDefault();const button=$('button[type="submit"]',event.target);button.disabled=true;$('#login-error').textContent='';try{const session=await api('/login','POST',{password:$('#login-password').value});await enter(session);}catch(error){$('#login-error').textContent=error.message;}finally{button.disabled=false;}});
$('#logout').addEventListener('click',async()=>{try{await api('/logout','POST');showLogin();}catch(error){toast(error.message);}});
async function boot(){try{await enter(await api('/session'));}catch{showLogin();}}
boot();
setInterval(async()=>{if(!csrf)return;try{await reload(!['settings','script'].includes(tab)&&!document.querySelector('dialog[open]')&&document.activeElement?.id!=='domain-search');await updateLog();}catch(error){if(csrf)toast(error.message);}},5000);
