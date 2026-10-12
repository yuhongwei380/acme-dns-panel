'use strict';
let libraryData = {domains:[]};
let deploymentCommands = null;
let deploymentRequest = 0;
// Keep all download-service traffic under the page's reverse-proxy prefix.
const publicPath = location.pathname.replace(/\/?$/, '/');
const publicBase = location.origin + publicPath;
const publicUrl = path => new URL(path, publicBase).href;

function clearDeployment() {
  deploymentRequest++;
  deploymentCommands = null;
  $('#deploy-results').hidden = true;
  $('#deploy-error').textContent = '';
  $('#deploy-diagnostics').hidden = true;
  $('#deploy-diagnostic-text').textContent = '';
}

function updateDeploymentCertificates() {
  const select = $('#deploy-certificate');
  const previous = select.value;
  const domains = libraryData.domains.filter(d => d.certificate.available && d.certificate.status !== 'expired');
  select.innerHTML = '<option value="">请选择 SSL 证书</option>' + domains.map(d => `<option value="${esc(d.name)}">${esc(d.name)}${d.staging ? '（测试 CA）' : ''}</option>`).join('');
  if (domains.some(d => d.name === previous)) select.value = previous;
  $('#deploy-generate').disabled = !domains.length;
  $('#deploy-availability').textContent = domains.length ? '' : '暂无可用证书，请先联系管理员签发证书。';
  if (previous && select.value !== previous) clearDeployment();
}
function renderLibrary() {
  const script = $('#client-script');
  script.hidden = !libraryData.script?.available;
  script.innerHTML = script.hidden ? '' : `<h3>客户端证书替换脚本</h3><p class="field-help">${libraryData.script.adaptable ? '从对应证书卡片下载 ssl-renew.sh，脚本会自动填入该域名和当前证书下载地址。' : '脚本模板缺少域名或证书下载地址配置，请联系管理员补充 example.com 示例配置。'}</p>`;
  const query = $('#search').value.trim().toLowerCase();
  const domains = libraryData.domains.filter(d => d.name.includes(query));
  const base = publicBase;
  if (!domains.length) {
    $('#library').innerHTML = `<div class="panel empty"><h3>${query ? '未找到匹配的域名' : '还没有可展示的域名'}</h3><p>${query ? '试试其他关键词。' : '管理员添加域名并签发后，证书会出现在这里。'}</p></div>`; return;
  }
  $('#library').innerHTML = `<div class="grid">${domains.map(d => {
    const c = d.certificate;
    return `<article class="panel certificate-card"><header><h2 class="domain-title">${esc(d.name)}</h2>${badge(c.status)}</header><p class="coverage mono">${esc((c.sans.length ? c.sans : [d.name,...(d.wildcard ? ['*.' + d.name] : [])]).join(' · '))}</p>${d.staging ? '<span class="badge warn">测试 CA · 非受信任证书</span>' : ''}<div class="expiry"><span class="muted">到期日期</span><span class="mono">${dateText(c.expires)}${c.days_left !== null ? ` · ${c.days_left < 0 ? '已过期' : c.days_left + ' 天'}` : ''}</span></div>${c.available ? ['fullchain.pem','privkey.pem'].map(file => `<div class="download-row"><span class="mono small">${file}</span><div class="actions"><a href="${esc(downloadUrl(base,d.name,file))}" download>下载</a></div></div>`).join('') + `<button class="copy-command" data-wget="${esc(d.name)}">复制 wget 下载命令</button>` + (libraryData.script?.adaptable ? `<div class="download-row script-row"><span class="mono small">ssl-renew.sh</span><div class="actions"><button data-copy="${esc(wgetCommand(base,d.name,['ssl-renew.sh']))}">复制 wget 命令</button><a class="download-button" href="${esc(downloadUrl(base,d.name,'ssl-renew.sh'))}" download="ssl-renew.sh">下载脚本</a></div></div>` : '') : '<p class="muted small">证书尚不可下载，请联系管理员。</p>'}</article>`;
  }).join('')}</div>`;
}
async function refreshLibrary() {
  $('#refresh').disabled = true;
  try {
    const response = await fetch(publicUrl('api/certificates'));
    if (!response.ok) throw new Error('无法读取证书，请稍后重试');
    libraryData = await response.json(); renderLibrary(); updateDeploymentCertificates();
    $('#updated').textContent = '更新于 ' + new Date().toLocaleTimeString('zh-CN', {hour12:false});
  } catch (error) { clearDeployment(); $('#deploy-generate').disabled = true; $('#deploy-availability').textContent = '证书读取失败，请刷新后重试。'; $('#client-script').hidden = true; $('#library').innerHTML = `<div class="panel empty"><h3>读取失败</h3><p>${esc(error.message)}</p></div>`; }
  finally { $('#refresh').disabled = false; }
}
$('#search').addEventListener('input', renderLibrary);
$('#refresh').addEventListener('click', refreshLibrary);
$('#deploy-form').addEventListener('input', clearDeployment);
$('#deploy-form').addEventListener('change', clearDeployment);
$('#deploy-form').addEventListener('submit', async event => {
  event.preventDefault(); clearDeployment();
  const request = deploymentRequest;
  const button = $('#deploy-generate'); button.disabled = true;
  const url = publicUrl('api/quick-deploy');
  const diagnostic = ['时间：' + new Date().toLocaleString('zh-CN', {hour12:false}), '请求：POST ' + url];
  try {
    const response = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json','X-Panel-Request':'1'}, body:JSON.stringify({certificate_domain:$('#deploy-certificate').value,service_domain:$('#deploy-domain').value.trim(),proxy_port:Number($('#deploy-port').value),public_path:publicPath})});
    diagnostic.push('HTTP 状态：' + response.status, '请求编号：' + (response.headers.get('X-Request-ID') || '未提供（请检查代理或服务版本）'));
    const body = await response.text();
    if (request !== deploymentRequest) return;
    let result;
    try { result = JSON.parse(body); }
    catch {
      diagnostic.push('响应类型：' + (response.headers.get('Content-Type') || '未知'));
      throw new Error(`接口返回了非 JSON 响应（HTTP ${response.status}），请检查反向代理配置和服务日志`);
    }
    if (response.status === 404 && result.detail === 'Not Found') throw new Error('部署接口未找到（HTTP 404），请检查下载服务路径和服务版本');
    if (!response.ok) throw new Error(Array.isArray(result.detail) ? result.detail.map(d => d.msg).join('；') : result.detail || '生成失败');
    if (typeof result.certificate_command !== 'string' || typeof result.nginx_command !== 'string') throw new Error('部署接口响应格式不正确，请检查反向代理配置和服务版本');
    deploymentCommands = result;
    $('#deploy-cert-command').textContent = result.certificate_command;
    $('#deploy-nginx-command').textContent = result.nginx_command;
    $('#deploy-results').hidden = false;
    const selected = libraryData.domains.find(d => d.name === $('#deploy-certificate').value);
    $('#deploy-error').textContent = selected?.staging ? '所选证书来自测试 CA，浏览器不会信任此证书。' : '';
  } catch(error) {
    if (request === deploymentRequest) {
      $('#deploy-error').textContent = error.message;
      diagnostic.push('错误：' + error.message);
      $('#deploy-diagnostic-text').textContent = diagnostic.join('\n');
      $('#deploy-diagnostics').hidden = false;
      console.error('快速部署请求失败', diagnostic.join('\n'));
    }
  }
  finally { button.disabled = !libraryData.domains.some(d => d.certificate.available && d.certificate.status !== 'expired'); }
});
document.addEventListener('click', event => {
  if (event.target.closest('[data-copy-diagnostics]')) copyText($('#deploy-diagnostic-text').textContent);
  const deployCopy = event.target.closest('[data-deploy-copy]');
  if (deployCopy && deploymentCommands) copyText(deploymentCommands[deployCopy.dataset.deployCopy]);
  const copy = event.target.closest('[data-copy]'); if (copy) copyText(copy.dataset.copy);
  const wget = event.target.closest('[data-wget]'); if (wget) copyText(wgetCommand(publicBase, wget.dataset.wget));
});
refreshLibrary();
setInterval(refreshLibrary, 30000);

