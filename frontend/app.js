const state = {
  personas: [], sessions: [], activePersona: null, activeSession: null,
  messages: [], memories: [], promises: [], relationship: {}, loading: false,
};

const $ = (selector) => document.querySelector(selector);
const escapeHTML = (value = '') => String(value).replace(/[&<>'"]/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
const avatarPalette = ['#aa7180, #746078', '#c38d83, #80677a', '#a183ad, #6f6687', '#bc8d72, #866d60'];
const avatarStyle = (persona) => `background:linear-gradient(135deg,${persona?.accent || avatarPalette[0]})`;

async function api(path, options = {}) {
  const response = await fetch(path, { headers: {'Content-Type': 'application/json', ...(options.headers || {})}, ...options });
  const type = response.headers.get('content-type') || '';
  const data = type.includes('application/json') ? await response.json() : await response.text();
  if (!response.ok) throw new Error(data?.detail || data || `请求失败（${response.status}）`);
  return data && Array.isArray(data.items) ? data.items : data;
}

function renderPersonaList() {
  const container = $('#personaList');
  if (!state.personas.length) { container.innerHTML = '<div class="memory-empty">还没有角色，创建一个开始吧。</div>'; return; }
  container.innerHTML = state.personas.map((p, index) => `
    <button class="persona-card ${p.id === state.activePersona?.id ? 'active' : ''}" data-persona-id="${escapeHTML(p.id)}">
      <div class="avatar avatar-sm" style="${avatarStyle(p)}">${escapeHTML(p.avatar || ['✦','◒','☽','✿'][index % 4])}</div>
      <div class="persona-meta"><div class="persona-name">${escapeHTML(p.name)}</div><div class="persona-tagline">${escapeHTML(p.tagline || p.description || '等待一次相遇')}</div></div><span class="persona-state"></span>
    </button>`).join('');
  container.querySelectorAll('.persona-card').forEach((card) => card.addEventListener('click', () => selectPersona(card.dataset.personaId)));
}

function renderHeader() {
  const p = state.activePersona || {};
  const avatar = p.avatar || '✦';
  $('#headerAvatar').textContent = avatar; $('#headerAvatar').style = avatarStyle(p);
  $('#welcomeAvatar').textContent = avatar; $('#welcomeAvatar').style = avatarStyle(p);
  $('#headerName').textContent = p.name || '人机恋';
  $('#headerTagline').textContent = p.tagline || p.description || '正在准备我们的空间';
  $('#welcomeText').textContent = p.description || '每一次对话都会让我们更了解彼此。你可以从一句简单的问候开始。';
}

function formatTime(value) { if (!value) return ''; const date = new Date(value); return date.toLocaleTimeString('zh-CN', {hour:'2-digit', minute:'2-digit'}); }
function renderMessages() {
  const list = $('#messageList');
  $('#welcomeState').style.display = state.messages.length ? 'none' : 'flex';
  list.innerHTML = state.messages.map((m) => {
    const isUser = m.role === 'user';
    return `<div class="message-row ${isUser ? 'user' : ''}">${!isUser ? `<div class="mini-avatar" style="${avatarStyle(state.activePersona)}">${escapeHTML(state.activePersona?.avatar || '✦')}</div>` : ''}<div class="message-bubble">${escapeHTML(m.content)}</div><span class="message-time">${formatTime(m.created_at)}</span></div>`;
  }).join('');
  const viewport = $('#chatViewport'); requestAnimationFrame(() => { viewport.scrollTop = viewport.scrollHeight; });
}

function setMetric(name, value) { const safe = Math.max(0, Math.min(100, Number(value ?? 0))); const label = $(`#metric${name[0].toUpperCase() + name.slice(1)}`); const bar = $(`#bar${name[0].toUpperCase() + name.slice(1)}`); if (label) label.textContent = Math.round(safe); if (bar) bar.style.width = `${safe}%`; }
function renderRelationship() {
  const rel = state.relationship || {}; setMetric('affection', rel.affection ?? 68); setMetric('trust', rel.trust ?? 54); setMetric('intimacy', rel.intimacy ?? 38); setMetric('tension', rel.tension ?? 12);
  $('#stateEnergy').textContent = `能量 ${Math.round(rel.energy ?? 72)}`; $('#stateMoodLabel').textContent = rel.mood_label || (rel.tension > 60 ? '有一点紧张' : '心情不错'); $('#stateMoodEmoji').textContent = rel.tension > 60 ? '◌' : '☼';
}
function renderMemories() {
  const list = $('#memoryList'); if (!state.memories.length) { list.innerHTML = '<div class="memory-empty">聊得更多，记忆会在这里慢慢长出来。</div>'; return; }
  list.innerHTML = state.memories.slice(0, 3).map((m) => `<div class="memory-item"><div class="memory-type">${escapeHTML(m.category || '共同记忆')}</div>${escapeHTML(m.content)}</div>`).join('');
}
function renderPromises() { const list = $('#promiseList'); const promises = state.promises || []; $('#promiseCount').textContent = promises.length; if (!promises.length) { list.innerHTML = '<div class="memory-empty">还没有需要兑现的约定。</div>'; return; } list.innerHTML = promises.slice(0, 3).map((p) => `<div class="promise-item">${escapeHTML(p.content || p.text)}<br><small style="color:#b99198">${escapeHTML(p.status || 'pending')}</small></div>`).join(''); }

async function selectPersona(personaId) {
  state.activePersona = state.personas.find((p) => String(p.id) === String(personaId)) || state.personas[0]; renderPersonaList(); renderHeader();
  try { const sessions = await api(`/api/sessions?persona_id=${encodeURIComponent(state.activePersona.id)}`); state.sessions = sessions.filter((session) => String(session.persona_id) === String(state.activePersona.id)); state.activeSession = state.sessions[0] || await api('/api/sessions', {method:'POST', body: JSON.stringify({persona_id: state.activePersona.id})}); await loadSession(); } catch (error) { toast(error.message); }
}
async function loadSession() {
  if (!state.activeSession) return; const sessionId = state.activeSession.id;
  try { const [messages, memories, relationship, promises] = await Promise.all([api(`/api/sessions/${sessionId}/messages`), api(`/api/sessions/${sessionId}/memories`), api(`/api/sessions/${sessionId}/state`).catch(() => ({})), api(`/api/sessions/${sessionId}/promises`).catch(() => [])]); state.messages = messages; state.memories = memories; state.relationship = relationship; state.promises = promises; renderMessages(); renderRelationship(); renderMemories(); renderPromises(); } catch (error) { toast(error.message); }
}

async function sendMessage(raw) {
  const content = raw.trim(); if (!content || state.loading || !state.activeSession) return;
  state.loading = true; $('#sendBtn').disabled = true; $('#messageInput').value = ''; autoGrow();
  const optimistic = {role:'user', content, created_at: new Date().toISOString()}; state.messages.push(optimistic); renderMessages(); $('#typingIndicator').hidden = false; scrollChat();
  try {
    const clientMessageId = crypto.randomUUID?.() || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
    const result = await api(`/api/sessions/${state.activeSession.id}/messages`, {method:'POST', body: JSON.stringify({content, client_message_id: clientMessageId})});
    if (result?.message) state.messages.push(result.message); else if (result?.assistant_message) state.messages.push(result.assistant_message); else if (result?.content) state.messages.push({role:'assistant', content: result.content, created_at: new Date().toISOString()});
    if (result?.state) state.relationship = result.state;
    const createdMemory = result?.memory || result?.memory_created;
    if (createdMemory) state.memories = [createdMemory, ...state.memories];
    if (result?.memories) state.memories = result.memories;
    if (result?.promises) state.promises = result.promises;
    renderMessages(); renderRelationship(); renderMemories(); renderPromises();
  } catch (error) { state.messages.pop(); renderMessages(); toast(error.message || '回复失败，请稍后再试'); } finally { state.loading = false; $('#typingIndicator').hidden = true; $('#sendBtn').disabled = false; $('#messageInput').focus(); }
}
function scrollChat() { const viewport = $('#chatViewport'); requestAnimationFrame(() => viewport.scrollTop = viewport.scrollHeight); }
function autoGrow() { const input = $('#messageInput'); input.style.height = 'auto'; input.style.height = `${Math.min(input.scrollHeight, 120)}px`; }
function toast(message) { const existing = document.querySelector('.toast'); if (existing) existing.remove(); const node = document.createElement('div'); node.className = 'toast'; node.textContent = message; Object.assign(node.style, {position:'fixed',bottom:'28px',left:'50%',transform:'translateX(-50%)',padding:'10px 15px',borderRadius:'12px',background:'#453b43',color:'#fff',fontSize:'11px',zIndex:20,boxShadow:'0 8px 20px rgba(0,0,0,.15)'}); document.body.appendChild(node); setTimeout(() => node.remove(), 2800); }

function openSettings() {
  const root = $('#modalRoot'); root.hidden = false; root.innerHTML = `<div class="modal"><h3>连接你的模型</h3><p>人机恋只需要一个 OpenAI-compatible API。密钥只保存在当前后端进程内，不会写入浏览器；重启后请重新设置，生产环境建议使用环境变量。</p><label>Base URL<input id="settingBase" placeholder="https://api.openai.com/v1" /></label><label>模型名称<input id="settingModel" placeholder="gpt-4o-mini" /></label><label>API Key（可选）<input id="settingKey" type="password" placeholder="无 Key 时使用本地演示回复" /></label><div class="modal-actions"><button class="btn-secondary" data-close>先不设置</button><button class="btn-primary" id="saveSettings">保存设置</button></div></div>`;
  root.querySelector('[data-close]').onclick = closeModal; root.querySelector('#saveSettings').onclick = async () => { try { await api('/api/settings/provider', {method:'PATCH', body: JSON.stringify({base_url: root.querySelector('#settingBase').value, model: root.querySelector('#settingModel').value, api_key: root.querySelector('#settingKey').value})}); toast('设置已保存'); closeModal(); } catch (error) { toast(error.message); } };
}
function openNewPersona() { const root = $('#modalRoot'); root.hidden = false; root.innerHTML = `<div class="modal"><h3>创造一个新的人</h3><p>先给 TA 一个名字和一句让你想认识 TA 的话。</p><label>名字<input id="newName" placeholder="例如：林深" /></label><label>一句话介绍<input id="newTagline" placeholder="安静地收集每一场日落" /></label><label>性格关键词<input id="newTraits" placeholder="温柔、慢热、观察力强" /></label><div class="modal-actions"><button class="btn-secondary" data-close>取消</button><button class="btn-primary" id="createPersona">开始相遇</button></div></div>`; root.querySelector('[data-close]').onclick = closeModal; root.querySelector('#createPersona').onclick = async () => { const name = root.querySelector('#newName').value.trim(); if (!name) return toast('先给 TA 一个名字吧'); try { const p = await api('/api/personas', {method:'POST', body: JSON.stringify({slug: `companion-${Date.now().toString(36)}`, name, tagline: root.querySelector('#newTagline').value.trim(), traits: root.querySelector('#newTraits').value.split(/[，,]/).map((v) => v.trim()).filter(Boolean)})}); state.personas.push(p); closeModal(); await selectPersona(p.id); } catch (error) { toast(error.message); } }; }
function closeModal() { $('#modalRoot').hidden = true; $('#modalRoot').innerHTML = ''; }

async function init() { try { state.personas = await api('/api/personas'); renderPersonaList(); if (state.personas.length) await selectPersona(state.personas[0].id); else { renderHeader(); } } catch (error) { $('#personaList').innerHTML = `<div class="memory-empty">无法连接后端：${escapeHTML(error.message)}</div>`; toast('后端尚未启动，请先运行启动命令'); } }

$('#messageInput').addEventListener('input', autoGrow); $('#messageInput').addEventListener('keydown', (event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); sendMessage($('#messageInput').value); } }); $('#sendBtn').addEventListener('click', () => sendMessage($('#messageInput').value)); document.querySelectorAll('.suggestion').forEach((button) => button.addEventListener('click', () => { $('#messageInput').value = button.dataset.suggestion; autoGrow(); $('#messageInput').focus(); })); $('#newPersonaBtn').addEventListener('click', openNewPersona); $('#settingsBtn').addEventListener('click', openSettings); $('#memoryBtn').addEventListener('click', () => { $('#insightPanel').classList.add('open'); $('#memoryList').scrollIntoView({behavior:'smooth'}); }); $('#closeInsightBtn').addEventListener('click', () => $('#insightPanel').classList.remove('open')); $('#viewMemoriesBtn').addEventListener('click', () => toast(state.memories.length ? `我们已经记住 ${state.memories.length} 件事` : '还没有长期记忆')); $('#clearBtn').addEventListener('click', async () => { if (!state.activeSession || !confirm('要开启一段新的对话吗？')) return; try { state.activeSession = await api('/api/sessions', {method:'POST', body: JSON.stringify({persona_id: state.activePersona.id})}); state.messages = []; state.memories = []; state.promises = []; state.relationship = {}; renderMessages(); renderMemories(); renderPromises(); renderRelationship(); } catch (error) { toast(error.message); } }); $('#modalRoot').addEventListener('click', (event) => { if (event.target.id === 'modalRoot') closeModal(); });
init();
