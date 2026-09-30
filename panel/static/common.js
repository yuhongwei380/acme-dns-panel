'use strict';
const $ = (selector, root = document) => root.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const eyeSvg = visible => `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>${visible ? '<path d="m3 3 18 18"/>' : ''}</svg>`;
function initEyes(root = document) { root.querySelectorAll('[data-eye]').forEach(button => { button.innerHTML = eyeSvg(false); }); }
document.addEventListener('click', event => {
  const eye = event.target.closest('[data-eye]');
  if (eye) {
    const input = document.getElementById(eye.dataset.eye);
    const visible = input.type === 'password';
    input.type = visible ? 'text' : 'password';
    eye.innerHTML = eyeSvg(visible);
    eye.setAttribute('aria-label', visible ? '隐藏密码' : '显示密码');
    eye.setAttribute('aria-pressed', String(visible));
  }
  const close = event.target.closest('[data-close]');
  if (close) document.getElementById(close.dataset.close).close();
});
let toastTimer;
function toast(message) {
  $('#toast').textContent = message; $('#toast').hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { $('#toast').hidden = true; }, 4000);
}
async function copyText(text) {
  try { await navigator.clipboard.writeText(text); toast('已复制'); }
  catch { $('#copy-text').value = text; $('#copy-dialog').showModal(); $('#copy-text').focus(); $('#copy-text').select(); }
}
function dateText(value) { return value ? new Date(value).toLocaleDateString('zh-CN') : '—'; }
function timeText(value) { return value ? new Date(value).toLocaleString('zh-CN', {hour12:false}) : '—'; }
const statusMap = {pending:['待签发',''],valid:['有效','good'],expiring:['即将到期','warn'],expired:['已过期','bad'],invalid:['文件异常','bad'],queued:['等待中','warn'],running:['执行中','warn'],success:['已完成','good'],failed:['失败','bad'],interrupted:['已中断','bad']};
function badge(status) { const [label, tone] = statusMap[status] || [status,'']; return `<span class="badge ${tone}">${esc(label)}</span>`; }
function secretField(id, label, required = true, autocomplete = 'off', placeholder = '') {
  return `<label for="${esc(id)}">${esc(label)}<div class="password-wrap"><input id="${esc(id)}" name="${esc(id)}" type="password" autocomplete="${autocomplete}" ${required ? 'required' : ''} placeholder="${esc(placeholder)}"><button type="button" class="eye" data-eye="${esc(id)}" aria-label="显示密码" aria-pressed="false"></button></div></label>`;
}
function downloadUrl(base, domain, file) { return `${base.replace(/\/$/, '')}/${encodeURIComponent(domain)}/${file}`; }
function wgetCommand(base, domain) { return ['fullchain.pem','privkey.pem'].map(file => `wget '${downloadUrl(base, domain, file).replace(/'/g, "'\\''")}'`).join('\n'); }
initEyes();

