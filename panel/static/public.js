'use strict';
let libraryData = {domains:[]};
function renderLibrary() {
  const script = $('#client-script');
  script.hidden = !libraryData.script?.available;
  script.innerHTML = script.hidden ? '' : `<div class="script-download-heading"><div><h3>客户端证书替换脚本</h3><p class="field-help mono">ssl-renew.sh</p></div><div class="actions"><button data-copy="${esc(location.origin + '/ssl-renew.sh')}">复制链接</button><a class="download-button" href="/ssl-renew.sh" download="ssl-renew.sh">下载脚本</a></div></div>`;
  const query = $('#search').value.trim().toLowerCase();
  const domains = libraryData.domains.filter(d => d.name.includes(query));
  const base = location.origin;
  if (!domains.length) {
    $('#library').innerHTML = `<div class="panel empty"><h3>${query ? '未找到匹配的域名' : '还没有可展示的域名'}</h3><p>${query ? '试试其他关键词。' : '管理员添加域名并签发后，证书会出现在这里。'}</p></div>`; return;
  }
  $('#library').innerHTML = `<div class="grid">${domains.map(d => {
    const c = d.certificate;
    return `<article class="panel certificate-card"><header><h2 class="domain-title">${esc(d.name)}</h2>${badge(c.status)}</header><p class="coverage mono">${esc((c.sans.length ? c.sans : [d.name,...(d.wildcard ? ['*.' + d.name] : [])]).join(' · '))}</p>${d.staging ? '<span class="badge warn">测试 CA · 非受信任证书</span>' : ''}<div class="expiry"><span class="muted">到期日期</span><span class="mono">${dateText(c.expires)}${c.days_left !== null ? ` · ${c.days_left < 0 ? '已过期' : c.days_left + ' 天'}` : ''}</span></div>${c.available ? ['fullchain.pem','privkey.pem'].map(file => `<div class="download-row"><span class="mono small">${file}</span><div class="actions"><button data-copy="${esc(downloadUrl(base,d.name,file))}">复制链接</button><a href="${esc(downloadUrl(base,d.name,file))}" download>下载</a></div></div>`).join('') + `<button class="copy-command" data-wget="${esc(d.name)}">复制 wget 下载命令</button>` : '<p class="muted small">证书尚不可下载，请联系管理员。</p>'}</article>`;
  }).join('')}</div>`;
}
async function refreshLibrary() {
  $('#refresh').disabled = true;
  try {
    const response = await fetch('/api/certificates');
    if (!response.ok) throw new Error('无法读取证书，请稍后重试');
    libraryData = await response.json(); renderLibrary();
    $('#updated').textContent = '更新于 ' + new Date().toLocaleTimeString('zh-CN', {hour12:false});
  } catch (error) { $('#client-script').hidden = true; $('#library').innerHTML = `<div class="panel empty"><h3>读取失败</h3><p>${esc(error.message)}</p></div>`; }
  finally { $('#refresh').disabled = false; }
}
$('#search').addEventListener('input', renderLibrary);
$('#refresh').addEventListener('click', refreshLibrary);
document.addEventListener('click', event => {
  const copy = event.target.closest('[data-copy]'); if (copy) copyText(copy.dataset.copy);
  const wget = event.target.closest('[data-wget]'); if (wget) copyText(wgetCommand(location.origin, wget.dataset.wget));
});
refreshLibrary();
setInterval(refreshLibrary, 30000);

