const API = '';  // same origin
let userId = localStorage.getItem('ase_user_id') || crypto.randomUUID();
localStorage.setItem('ase_user_id', userId);

let sessionId = null;
let selectedScore = null;

// ── Context select ────────────────────────────────────────────
document.getElementById('context-select').addEventListener('change', e => {
  const custom = document.getElementById('custom-context-row');
  custom.classList.toggle('hidden', e.target.value !== 'custom');
});

// ── Start session ─────────────────────────────────────────────
document.getElementById('start-btn').addEventListener('click', async () => {
  const select = document.getElementById('context-select');
  const context = select.value === 'custom'
    ? document.getElementById('custom-context').value.trim()
    : select.value;

  if (!context) return;

  const btn = document.getElementById('start-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>Starting…';

  const res = await fetch(`${API}/sessions/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_id: userId, context }),
  });
  const data = await res.json();
  sessionId = data.session_id;

  document.getElementById('session-context-badge').textContent = context;
  document.getElementById('session-id-badge').textContent = sessionId.slice(0, 8) + '…';

  document.getElementById('step-setup').classList.add('hidden');
  document.getElementById('step-suggest').classList.remove('hidden');
});

// ── Get suggestions ───────────────────────────────────────────
document.getElementById('suggest-btn').addEventListener('click', async () => {
  const prompt = document.getElementById('prompt-input').value.trim();
  if (!prompt) return;

  const context = document.getElementById('session-context-badge').textContent;
  const btn = document.getElementById('suggest-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>Thinking…';

  const res = await fetch(`${API}/suggest/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_id: userId, session_id: sessionId, context, prompt, n: 3 }),
  });
  const data = await res.json();

  btn.disabled = false;
  btn.textContent = 'Get Suggestions';

  renderSuggestions(data.suggestions || []);
  document.getElementById('suggestions-area').classList.remove('hidden');
  document.getElementById('step-outcome').classList.remove('hidden');
});

function renderSuggestions(suggestions) {
  const list = document.getElementById('suggestions-list');
  list.innerHTML = '';

  if (!suggestions.length) {
    list.innerHTML = '<div class="empty-state">No suggestions returned.</div>';
    return;
  }

  const firstType = suggestions[0]?.type || '';
  document.getElementById('suggestion-type-badge').textContent = firstType;

  suggestions.forEach((s, i) => {
    const pct = Math.round((s.predicted_success || 0.5) * 100);
    const card = document.createElement('div');
    card.className = 'suggestion-card';
    card.dataset.id = s.id || '';
    card.innerHTML = `
      <div class="suggestion-rank">#${i + 1}</div>
      <div class="suggestion-body">
        <div class="suggestion-text">${s.text}</div>
        <div class="suggestion-meta">
          <span class="suggestion-angle">${s.angle || ''}</span>
          <div class="success-bar-wrap">
            <div class="success-bar"><div class="success-fill" style="width:${pct}%"></div></div>
            <span>${pct}% success rate</span>
          </div>
          <button class="use-btn" onclick="markUsed(this, '${s.id || ''}')">Use this</button>
        </div>
      </div>`;
    list.appendChild(card);
  });
}

window.markUsed = async (btn, suggestionId) => {
  if (!suggestionId) return;
  btn.closest('.suggestion-card').classList.add('accepted');
  btn.textContent = 'Used ✓';
  btn.disabled = true;

  await fetch(`${API}/suggest/feedback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ suggestion_id: suggestionId, accepted: true }),
  });
};

// ── Star rating ───────────────────────────────────────────────
document.querySelectorAll('.star').forEach(star => {
  star.addEventListener('click', () => {
    selectedScore = parseInt(star.dataset.v);
    document.querySelectorAll('.star').forEach(s => {
      s.classList.toggle('active', parseInt(s.dataset.v) <= selectedScore);
    });
  });
});

// ── Submit outcome ────────────────────────────────────────────
document.getElementById('outcome-btn').addEventListener('click', async () => {
  if (!selectedScore) { alert('Please rate the outcome first.'); return; }

  const notes = document.getElementById('outcome-notes').value.trim();
  const btn = document.getElementById('outcome-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>Learning…';

  const res = await fetch(`${API}/sessions/${sessionId}/end`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ outcome_score: selectedScore, outcome_notes: notes }),
  });
  const data = await res.json();

  document.getElementById('step-suggest').classList.add('hidden');
  document.getElementById('step-outcome').classList.add('hidden');
  renderLearned(data.learning || {});
  document.getElementById('step-learned').classList.remove('hidden');
});

function renderLearned(learning) {
  const list = document.getElementById('learned-list');
  const items = learning.learned || [];

  if (!items.length) {
    list.innerHTML = '<div class="muted">Not enough data yet — keep going!</div>';
    return;
  }

  list.innerHTML = items.map(item => `
    <div class="learned-row">
      <span style="text-transform:capitalize">${item.type} suggestions</span>
      <div class="rate-change">
        ${item.old_rate !== null ? `<span style="color:var(--muted)">${Math.round(item.old_rate * 100)}%</span> <span class="rate-arrow">→</span>` : ''}
        <strong style="color:var(--success)">${Math.round(item.new_rate * 100)}% success rate</strong>
      </div>
    </div>`).join('');
}

// ── New session ───────────────────────────────────────────────
document.getElementById('new-session-btn').addEventListener('click', () => {
  sessionId = null;
  selectedScore = null;
  document.getElementById('prompt-input').value = '';
  document.getElementById('outcome-notes').value = '';
  document.getElementById('suggestions-list').innerHTML = '';
  document.getElementById('suggestions-area').classList.add('hidden');
  document.querySelectorAll('.star').forEach(s => s.classList.remove('active'));
  document.getElementById('step-learned').classList.add('hidden');
  document.getElementById('step-outcome').classList.add('hidden');
  document.getElementById('step-setup').classList.remove('hidden');
  document.getElementById('start-btn').disabled = false;
  document.getElementById('start-btn').textContent = 'Start Session';
});
