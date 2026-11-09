/* VerifyCOD — shared script. body[data-page] picks landing or dashboard. */
const API = '';
const PAGE = document.body.dataset.page;
const TOKEN = localStorage.getItem('vc_token');
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

/* ================= LANDING ================= */
function openAuth(which) {
  closeAuth();
  $('auth-' + which).classList.add('open');
  const first = document.querySelector('#auth-' + which + ' input');
  if (first) first.focus();
}
function closeAuth() { document.querySelectorAll('.auth-bg').forEach(m => m.classList.remove('open')); }
function showErr(id, msg) { const el = $(id); el.textContent = msg; el.classList.add('show'); }
function saveTokenAndGo(data) {
  localStorage.setItem('vc_token', data.token);
  if (data.merchant) localStorage.setItem('vc_merchant', JSON.stringify(data.merchant));
  location.href = '/dashboard';
}
function heroSignup(e) {
  e.preventDefault();
  openAuth('signup');
  $('suEmail').value = $('heroEmail').value;
  $('suName').focus();
}
async function authCall(path, body, btn, label, errId, fail) {
  btn.disabled = true; btn.textContent = label + '…';
  try {
    const res = await fetch(API + path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const data = await res.json();
    if (!res.ok) { showErr(errId, fail(data)); btn.disabled = false; btn.textContent = label; return; }
    saveTokenAndGo(data);
  } catch (err) {
    showErr(errId, 'Could not reach the server. Start the API and try again.');
    btn.disabled = false; btn.textContent = label;
  }
}
function doSignup(e) {
  e.preventDefault();
  authCall('/v1/auth/signup', {
    name: $('suName').value.trim(), brand_name: $('suBrand').value.trim(),
    email: $('suEmail').value.trim(), password: $('suPass').value,
  }, $('suBtn'), 'Create account', 'signupErr',
  d => d.detail === 'email_taken' ? 'An account with this email already exists. Try signing in.' : (d.detail || 'Could not create the account. Try again.'));
}
function doSignin(e) {
  e.preventDefault();
  authCall('/v1/auth/signin', { email: $('siEmail').value.trim(), password: $('siPass').value },
    $('siBtn'), 'Sign in', 'signinErr', () => 'Wrong email or password. Try again.');
}
async function tryDemo() {
  try {
    const res = await fetch(API + '/v1/auth/demo', { method: 'POST' });
    const data = await res.json();
    if (!res.ok) throw 0;
    saveTokenAndGo(data);
  } catch (e) { alert('The demo is not available right now. Sign up instead.'); }
}
function initLanding() {
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeAuth(); });
  if (TOKEN) $('navCta').innerHTML = '<button onclick="location.href=\'/dashboard\'">Open dashboard →</button>';

  const SCRIPT = [
    ['agent', 'Namaste! Main StyleKart se bol raha hoon. Aapne ek Phone Case order kiya tha, ₹499, cash on delivery. Kya ye order aapka hai?'],
    ['customer', 'Haan, mera hi hai.'],
    ['agent', 'Shukriya! Address confirm kar dein: Flat 302, Banseri Avenue, Vadodara, 390001?'],
    ['customer', 'Haan, sahi hai. Kal bhej do.'],
    ['agent', 'Done! Aapka order kal deliver ho jayega. Dhanyavaad!'],
  ];
  let i = 0, secs = 0;
  const body = $('callBody'), typing = $('typing'), pill = $('outcomePill');
  const fmt = s => String(Math.floor(s / 60)).padStart(2, '0') + ':' + String(s % 60).padStart(2, '0');
  setInterval(() => { secs++; $('callTimer').textContent = fmt(secs); }, 1000);
  (function next() {
    if (i >= SCRIPT.length) {
      typing.style.display = 'none'; pill.classList.add('show');
      setTimeout(() => {
        body.innerHTML = ''; pill.classList.remove('show');
        typing.style.display = ''; typing.textContent = 'VerifyCOD is calling…';
        i = 0; secs = 0; setTimeout(next, 1200);
      }, 4200);
      return;
    }
    const [who, text] = SCRIPT[i++];
    typing.textContent = who === 'agent' ? 'Agent is speaking…' : 'Customer is speaking…';
    const d = document.createElement('div');
    d.className = 'msg ' + who;
    d.innerHTML = '<span class="tag">' + (who === 'agent' ? 'Agent' : 'Customer') + '</span>' + esc(text);
    body.appendChild(d);
    setTimeout(next, who === 'agent' ? 2600 : 1800);
  })();
}

/* ================= DASHBOARD ================= */
const fmtINR = n => '₹' + Number(n || 0).toLocaleString('en-IN');
const fmtDate = t => t ? new Date(t * 1000).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—';
const maskPhone = p => { const d = String(p || '').replace(/\D/g, ''); return d.length > 4 ? '+' + d.slice(0, 2) + ' ' + d.slice(2, 7) + '****' + d.slice(-1) : p; };

async function api(path, opts = {}) {
  const res = await fetch(API + path, { headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + TOKEN, ...(opts.headers || {}) }, ...opts });
  if (res.status === 401) { localStorage.removeItem('vc_token'); localStorage.removeItem('vc_merchant'); location.href = '/'; throw new Error('Signed out'); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || ('HTTP ' + res.status));
  return data;
}
function toast(msg) { const t = $('toast'); t.textContent = msg; t.classList.add('show'); setTimeout(() => t.classList.remove('show'), 2600); }
function copyText(txt, msg) {
  (navigator.clipboard ? navigator.clipboard.writeText(txt) : Promise.reject())
    .catch(() => { const ta = document.createElement('textarea'); ta.value = txt; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); ta.remove(); })
    .then(() => toast(msg || 'Copied'));
}
function openDrawer(html) { $('drawer').innerHTML = html; $('drawer').classList.add('open'); $('overlay').classList.add('open'); }
function closeDrawer() { $('drawer').classList.remove('open'); if (!$('modal').classList.contains('open')) $('overlay').classList.remove('open'); $('sidebar').classList.remove('open'); }
function openModal(html) { $('modal').innerHTML = html; $('modal').classList.add('open'); $('overlay').classList.add('open'); }
function closeModal() { $('modal').classList.remove('open'); if (!$('drawer').classList.contains('open')) $('overlay').classList.remove('open'); }
function closeSearch() { $('searchOverlay').classList.remove('open'); }
function openSearch() { $('searchOverlay').classList.add('open'); $('searchInput').value = ''; $('searchResults').innerHTML = ''; $('searchInput').focus(); }

let mode = localStorage.getItem('vc_mode') || 'live';
let pollers = [];
const stopPollers = () => { pollers.forEach(clearInterval); pollers = []; };

/* charts (colours match the light theme) */
function lineChart(days) {
  const W = 560, H = 180, P = 28;
  const maxV = Math.max(1, ...days.flatMap(d => [d.total || 0, d.confirmed || 0]));
  const x = i => P + (i * (W - 2 * P)) / Math.max(1, days.length - 1);
  const y = v => H - P - (v / maxV) * (H - 2 * P);
  const path = k => days.map((d, i) => (i ? 'L' : 'M') + x(i).toFixed(1) + ',' + y(d[k] || 0).toFixed(1)).join(' ');
  const dots = (k, c) => days.map((d, i) => `<circle cx="${x(i)}" cy="${y(d[k] || 0)}" r="3.5" fill="${c}"/>`).join('');
  return `<svg viewBox="0 0 ${W} ${H}" style="width:100%">
    <line x1="${P}" y1="${H - P}" x2="${W - P}" y2="${H - P}" stroke="#eadfd4"/>
    <path d="${path('total')}" fill="none" stroke="#cfc3b8" stroke-width="2.5"/>${dots('total', '#cfc3b8')}
    <path d="${path('confirmed')}" fill="none" stroke="#ff6a13" stroke-width="2.5"/>${dots('confirmed', '#ff6a13')}
    <text x="${P}" y="14" fill="#7a706a" font-size="11">Total (grey) vs confirmed (orange), last ${days.length} days</text>
    ${days.map((d, i) => `<text x="${x(i)}" y="${H - 8}" fill="#a0968d" font-size="10" text-anchor="middle">${esc(d.date.slice(5))}</text>`).join('')}</svg>`;
}
function donutChart(split) {
  const total = Object.values(split).reduce((a, b) => a + b, 0) || 1;
  const col = { CONFIRMED: '#ff6a13', ADDRESS_UPDATED: '#3b82f6', CANCELLED_BY_CUSTOMER: '#e5484d', RESCHEDULED: '#f2a33a', WRONG_PERSON: '#a0968d', CALLBACK_REQUESTED: '#8b5cf6', NEEDS_REVIEW: '#14110f' };
  let off = 25, segs = '';
  for (const [k, v] of Object.entries(split)) {
    const f = v / total;
    segs += `<circle r="15.915" cx="21" cy="21" fill="transparent" stroke="${col[k] || '#a0968d'}" stroke-width="6" stroke-dasharray="${(f * 100).toFixed(1)} ${100 - f * 100}" stroke-dashoffset="${off}"/>`;
    off -= f * 100;
  }
  return `<div class="row-flex" style="gap:16px"><svg viewBox="0 0 42 42" style="width:120px;height:120px">${segs}
    <text x="21" y="22" fill="#14110f" font-size="8" text-anchor="middle" font-weight="800">${total}</text>
    <text x="21" y="29" fill="#7a706a" font-size="4.5" text-anchor="middle">calls</text></svg>
    <div>${Object.entries(split).map(([k, v]) => `<div class="small" style="margin:4px 0"><span style="display:inline-block;width:10px;height:10px;border-radius:3px;background:${col[k] || '#a0968d'};margin-right:6px"></span>${esc(k)} <b>${v}</b></div>`).join('')}</div></div>`;
}
function outcomeBadge(v) {
  const o = v.outcome || v.status;
  const c = (o === 'CONFIRMED' || o === 'ADDRESS_UPDATED') ? 'ok' : o === 'NEEDS_REVIEW' ? 'warn' : (o === 'CANCELLED_BY_CUSTOMER' || o === 'cancelled') ? 'bad' : 'idle';
  return `<span class="badge ${c}">${esc(o)}</span>`;
}
function statusBadge(s) {
  const c = s === 'completed' ? 'ok' : s === 'needs_review' ? 'warn' : s === 'cancelled' ? 'bad' : s === 'calling' ? 'info' : 'idle';
  return `<span class="badge ${c}">${esc(s)}</span>`;
}

/* router */
const ROUTES = {
  '/': ['Dashboard', pageDashboard], '/orders': ['Orders', pageOrders], '/conversations': ['Conversations', pageConversations],
  '/review': ['Review queue', pageReview], '/developers/keys': ['API Keys', pageApiKeys], '/billing': ['Billing', pageBilling],
  '/logout': ['Signed out', pageLogout],
};
const PENDING = { '/analytics': 'Analytics', '/integrations': 'Integrations', '/developers/webhooks': 'Webhooks', '/settings': 'Settings', '/team': 'Team' };
async function route() {
  stopPollers(); closeDrawer();
  let path = '/' + (location.hash.replace(/^#/, '').split('/').filter(Boolean)[0] === 'developers'
    ? location.hash.replace(/^#\//, '') : (location.hash.replace(/^#\//, '').split('/')[0] || ''));
  if (path.startsWith('/conversations')) path = '/conversations';
  const r = ROUTES[path] || (PENDING[path] ? [PENDING[path], pagePending] : ROUTES['/']);
  $('pageTitle').textContent = r[0];
  document.querySelectorAll('.nav-item[data-route]').forEach(n => n.classList.toggle('active', !n.dataset.external && n.dataset.route === '#' + (ROUTES[path] || PENDING[path] ? path : '/')));
  $('app').innerHTML = '<p class="muted">Loading…</p>';
  try { await r[1]($('app'), r[0]); }
  catch (err) { $('app').innerHTML = `<div class="card"><h2>Couldn't load this page</h2><p class="muted">${esc(err.message)}</p><p class="small muted">Check the API is running: <span class="mono">uvicorn app:app --port 8000</span></p></div>`; }
  updateCredits(); updateReviewBadge();
}
function pagePending(app, title) {
  app.innerHTML = `<div class="card"><div class="empty"><h2>${esc(title)}</h2>This page isn't in the new script yet. Move its page function from your old dashboard.html into script.js. The CSS classes already match.</div></div>`;
}
async function updateCredits() { try { $('creditsLeft').textContent = Number((await api('/v1/billing')).credits_left).toFixed(0); } catch (e) { $('creditsLeft').textContent = '—'; } }
async function updateReviewBadge() {
  try {
    const q = await api('/v1/verifications?status=needs_review&limit=100');
    const el = $('reviewCount'); el.style.display = q.length ? '' : 'none'; el.textContent = q.length;
    $('bellDot').style.display = q.length ? '' : 'none';
  } catch (e) {}
}

/* shared actions */
async function sendTestOrder() {
  const order = {
    external_order_id: 'SK-TEST-' + Date.now(),
    customer: { name: 'Ramesh Patel', phone: '+919876543210', language_hint: 'hi-en' },
    address: { line1: 'Flat 302, Shanti Nagar', landmark: 'near Hanuman mandir', city: 'Vadodara', state: 'Gujarat', pincode: '390001' },
    items: [{ name: 'Phone Case', qty: 1, price: 499 }], amount: 499, currency: 'INR', payment_mode: 'COD',
    options: { call_now: true, max_attempts: 3, metadata: { campaign: 'test' } },
  };
  const d = await api('/v1/orders', { method: 'POST', body: JSON.stringify(order) });
  toast('Test order sent: ' + d.verification_id); return d;
}
function downloadCsv(name, rows) {
  const csv = rows.map(r => r.map(c => '"' + String(c ?? '').replace(/"/g, '""') + '"').join(',')).join('\n');
  const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' })); a.download = name; a.click();
}

/* pages */
async function pageDashboard(app) {
  const s = await api('/v1/analytics/summary'), k = s.kpis || {};
  const kpi = (l, n, sub) => `<div class="card kpi"><div class="lbl">${l}</div><div class="n">${n}</div>${sub ? `<div class="lbl">${sub}</div>` : ''}</div>`;
  app.innerHTML = `
    ${mode === 'test' ? '<div class="alert">Test mode: orders here are sandbox data. Switch to Live for real orders.</div>' : ''}
    ${(s.alerts || []).map(a => `<div class="alert ${a.type === 'error' ? 'red' : ''}">${esc(a.message)}</div>`).join('')}
    <div class="grid kpis">
      ${kpi('Orders received', k.orders || 0)}${kpi('Calls made', k.calls || 0)}
      ${kpi('Confirmation rate', Math.round((k.confirmation_rate || 0) * 100) + '%')}${kpi('Cancellations', k.cancellations || 0)}
      ${kpi('Addresses fixed', k.addresses_fixed || 0)}${kpi('Est. money saved', fmtINR(k.money_saved), 'return shipping avoided')}
    </div>
    <div class="grid two">
      <div class="card"><h2>Orders &amp; outcomes</h2>${(s.outcomes_by_day || []).length ? lineChart(s.outcomes_by_day) : '<p class="muted">No data yet. Send a test order.</p>'}</div>
      <div class="card"><h2>Outcomes</h2>${Object.keys(s.outcome_split || {}).length ? donutChart(s.outcome_split) : '<p class="muted">No completed calls yet.</p>'}</div>
    </div>
    <div class="grid two">
      <div class="card"><h2>Live activity</h2><div id="activityFeed"></div></div>
      <div class="card"><h2>Quick actions</h2>
        <div class="row-flex"><button onclick="sendTestOrder().then(route)">Add test order</button><button class="ghost" onclick="location.hash='#/integrations'">Upload CSV</button></div>
        <p class="muted small" style="margin-top:14px">Demo store: <a class="or" href="http://127.0.0.1:8001/" target="_blank">open the store</a>, place a COD order and the verification call rings.</p>
      </div>
    </div>`;
  const feed = async () => {
    try {
      const v = await api('/v1/verifications?limit=10');
      $('activityFeed').innerHTML = v.length ? v.map(x => `<div class="feed-item">📞 <b>${esc((x.order?.customer || {}).name || '—')}</b>, ${esc(x.outcome || x.status)} <span class="muted">${fmtDate(x.created_at)}</span></div>`).join('') : '<p class="muted">No activity yet.</p>';
    } catch (e) {}
  };
  feed(); pollers.push(setInterval(feed, 10000));
}

let ordersCache = [];
async function pageOrders(app) {
  ordersCache = await api('/v1/verifications?limit=100');
  app.innerHTML = `<p class="page-sub">Every COD order and its verification status. Click a row for the timeline.</p>
    <div class="card">
      <div class="row-flex" style="margin-bottom:12px">
        <input id="ordSearch" placeholder="Search phone, order id or name" style="flex:1;min-width:180px">
        <select id="ordStatus"><option value="">All statuses</option><option>queued</option><option>calling</option><option>completed</option><option>needs_review</option><option>cancelled</option></select>
        <select id="ordOutcome"><option value="">All outcomes</option><option>CONFIRMED</option><option>ADDRESS_UPDATED</option><option>CANCELLED_BY_CUSTOMER</option><option>RESCHEDULED</option><option>WRONG_PERSON</option><option>CALLBACK_REQUESTED</option><option>NEEDS_REVIEW</option></select>
        <button class="ghost" id="ordExport">Export CSV</button>
      </div>
      <div class="row-flex" id="ordBulk" style="margin-bottom:12px;display:none"><span class="small muted" id="ordBulkCount"></span>
        <button class="sm" onclick="bulkAct('retry')">Retry selected</button><button class="sm danger" onclick="bulkAct('cancel')">Cancel selected</button></div>
      <div style="overflow-x:auto"><table><thead><tr><th></th><th>Order</th><th>Customer</th><th>Phone</th><th>Amount</th><th>Status</th><th>Outcome</th><th>Tries</th><th>Created</th></tr></thead><tbody id="ordRows"></tbody></table></div>
      <div id="ordEmpty"></div></div>`;
  const bulk = () => { const n = document.querySelectorAll('.ordSel:checked').length; $('ordBulk').style.display = n ? '' : 'none'; $('ordBulkCount').textContent = n + ' selected'; };
  const render = () => {
    const q = $('ordSearch').value.toLowerCase(), st = $('ordStatus').value, oc = $('ordOutcome').value;
    const rows = ordersCache.filter(v => {
      const o = v.order || {}, hay = ((o.external_order_id || '') + ' ' + ((o.customer || {}).name || '') + ' ' + ((o.customer || {}).phone || '')).toLowerCase();
      return (!q || hay.includes(q)) && (!st || v.status === st) && (!oc || v.outcome === oc);
    });
    $('ordRows').innerHTML = rows.map(v => {
      const o = v.order || {};
      return `<tr class="clickable" onclick="openOrderDrawer('${v.verification_id}')"><td onclick="event.stopPropagation()"><input type="checkbox" class="ordSel" value="${v.verification_id}"></td>
        <td class="mono">${esc(o.external_order_id || v.verification_id)}</td><td>${esc((o.customer || {}).name || '—')}</td><td>${maskPhone((o.customer || {}).phone)}</td>
        <td>${fmtINR(o.amount)}</td><td>${statusBadge(v.status)}</td><td>${outcomeBadge(v)}</td><td>${v.attempts || 0}</td><td class="muted">${fmtDate(v.created_at)}</td></tr>`;
    }).join('');
    $('ordEmpty').innerHTML = rows.length ? '' : '<div class="empty">No orders match.<br><button onclick="sendTestOrder().then(route)">Send a test order</button></div>';
    document.querySelectorAll('.ordSel').forEach(c => c.onchange = bulk); bulk();
  };
  ['ordSearch', 'ordStatus', 'ordOutcome'].forEach(id => $(id).oninput = render);
  $('ordExport').onclick = () => {
    const rows = [['order_id', 'customer', 'phone', 'amount', 'status', 'outcome', 'attempts', 'created_at']];
    ordersCache.forEach(v => { const o = v.order || {}; rows.push([o.external_order_id || v.verification_id, (o.customer || {}).name, (o.customer || {}).phone, o.amount, v.status, v.outcome, v.attempts, new Date((v.created_at || 0) * 1000).toISOString()]); });
    downloadCsv('verifycod-orders.csv', rows); toast('Orders exported');
  };
  render();
}
async function bulkAct(action) {
  const ids = [...document.querySelectorAll('.ordSel:checked')].map(c => c.value);
  for (const id of ids) { try { await api('/v1/verifications/' + id + '/' + action, { method: 'POST' }); } catch (e) {} }
  toast(ids.length + (action === 'retry' ? ' re-queued' : ' cancelled')); route();
}
async function openOrderDrawer(id) {
  const v = await api('/v1/verifications/' + id), o = v.order || {}, a = o.address || {}, oc = v.outcome_detail || {};
  openDrawer(`<h2 style="font-size:20px">${esc(o.external_order_id || id)}</h2>
    <p class="muted small">${esc((o.customer || {}).name || '—')} · ${maskPhone((o.customer || {}).phone)} · ${fmtINR(o.amount)}</p>
    <p style="margin-top:8px">${statusBadge(v.status)} ${outcomeBadge(v)}</p>
    <div class="card" style="margin-top:14px;box-shadow:none;background:#faf6f1"><h3>Address</h3><p class="small">${esc([a.line1, a.landmark, a.city, a.state, a.pincode].filter(Boolean).join(', ') || '—')}</p>
    ${oc.corrected_address ? `<h3>Corrected address</h3><p class="small">${esc([oc.corrected_address.line1, oc.corrected_address.landmark, oc.corrected_address.pincode].filter(Boolean).join(', '))}</p>` : ''}</div>
    <h3>Items</h3>${(o.items || []).map(i => `<div class="feed-item">${esc(i.name)} × ${i.qty}, ${fmtINR(i.price)}</div>`).join('') || '<p class="muted small">—</p>'}
    <h3>Transcript</h3>${(v.transcript || []).map(t => `<div class="turn ${t.speaker}"><div class="who">${t.speaker === 'agent' ? 'Agent' : 'Customer'}</div>${esc(t.text)}</div>`).join('') || '<p class="muted small">No turns yet.</p>'}
    ${Object.keys(oc).length ? `<h3>Outcome JSON</h3><pre>${esc(JSON.stringify(oc, null, 2))}</pre>` : ''}
    <div class="row-flex" style="margin-top:18px"><button onclick="verAct('${id}','retry')">Retry</button>
      <button class="ghost" onclick="overrideVerification('${id}')">Manual override</button><button class="danger" onclick="verAct('${id}','cancel')">Cancel</button>
      <button class="ghost" onclick="closeDrawer()">Close</button></div>`);
}
async function verAct(id, action) { await api('/v1/verifications/' + id + '/' + action, { method: 'POST' }); toast(action === 'retry' ? 'Re-queued' : 'Cancelled'); closeDrawer(); route(); }
async function overrideVerification(id) {
  const outcome = prompt('Outcome (CONFIRMED, ADDRESS_UPDATED, CANCELLED_BY_CUSTOMER, RESCHEDULED, WRONG_PERSON, CALLBACK_REQUESTED, NEEDS_REVIEW):', 'CONFIRMED');
  if (!outcome) return;
  try { await api('/v1/verifications/' + id + '/override', { method: 'POST', body: JSON.stringify({ outcome: outcome.trim().toUpperCase() }) }); toast('Outcome overridden'); closeDrawer(); route(); }
  catch (e) { toast('Override failed: ' + e.message); }
}

async function pageConversations(app) {
  const calls = await api('/v1/calls?limit=50');
  app.innerHTML = `<p class="page-sub">Every call with its outcome and cost.</p><div class="card">${calls.length ? `<div style="overflow-x:auto"><table>
    <thead><tr><th>Call</th><th>Customer</th><th>Language</th><th>Duration</th><th>Outcome</th><th>Sentiment</th><th>Cost</th></tr></thead>
    <tbody>${calls.map(c => `<tr><td class="mono">call_${esc(c.call_id)}</td><td>${esc(c.customer_name || '—')}</td><td>${esc(c.language || 'hi-en')}</td>
    <td>${c.duration_s ? Math.round(c.duration_s) + 's' : '—'}</td><td>${outcomeBadge({ outcome: c.outcome })}</td><td>${esc(c.sentiment || '—')}</td><td>${fmtINR(c.cost)}</td></tr>`).join('')}</tbody></table></div>`
    : '<div class="empty">No calls yet.<br><button onclick="sendTestOrder().then(() => location.hash=\'#/orders\')">Send a test order</button></div>'}</div>`;
}

async function pageReview(app) {
  const q = await api('/v1/verifications?status=needs_review&limit=50');
  app.innerHTML = `<p class="page-sub">Calls the AI wasn't sure about. A human decides: approve, edit or call back.</p>
    ${q.length ? `<div class="grid two" style="grid-template-columns:1fr 1fr">${q.map(v => {
      const o = v.order || {};
      return `<div class="card"><h2>${esc((o.customer || {}).name || '—')} <span class="muted small">${esc(o.external_order_id || v.verification_id)}</span></h2>
        <p>${outcomeBadge(v)} <span class="muted small">confidence ${v.outcome_detail?.confidence ?? '—'}</span></p>
        ${(v.transcript || []).slice(-2).map(t => `<div class="turn ${t.speaker}"><div class="who">${t.speaker}</div>${esc(t.text)}</div>`).join('')}
        <div class="row-flex" style="margin-top:14px"><button onclick="reviewSet('${v.verification_id}','CONFIRMED')">Approve</button>
        <button class="ghost" onclick="overrideVerification('${v.verification_id}')">Edit outcome</button>
        <button class="ghost" onclick="verAct('${v.verification_id}','retry')">Call back</button></div></div>`;
    }).join('')}</div>` : '<div class="card"><div class="empty">🎉 Review queue is clear. Nothing needs a human right now.</div></div>'}`;
}
async function reviewSet(id, outcome) { await api('/v1/verifications/' + id + '/override', { method: 'POST', body: JSON.stringify({ outcome }) }); toast('Approved as confirmed'); route(); }

async function pageApiKeys(app) {
  const keys = await api('/v1/api-keys');
  app.innerHTML = `<p class="page-sub">Keys authenticate your store to VerifyCOD. A key is shown <b>once</b> at creation, so copy it then.</p>
    <div class="card"><div class="row-flex" style="margin-bottom:12px"><button onclick="createApiKey()">Create key</button></div>
    ${keys.length ? `<table><thead><tr><th>Label</th><th>Prefix</th><th>Created</th><th>Last used</th><th>Status</th><th></th></tr></thead><tbody>${keys.map(k => `<tr>
      <td>${esc(k.label)}</td><td class="mono">${esc(k.prefix)}…</td><td>${fmtDate(k.created_at)}</td><td>${k.last_used_at ? fmtDate(k.last_used_at) : 'Never'}</td>
      <td>${k.status === 'active' ? '<span class="badge ok">Active</span>' : '<span class="badge idle">Revoked</span>'}</td>
      <td>${k.status === 'active' ? `<button class="ghost sm" onclick="revokeKey(${k.id})">Revoke</button>` : ''}</td></tr>`).join('')}</tbody></table>`
      : '<div class="empty">No API keys yet.<br><button onclick="createApiKey()">Create your first key</button></div>'}</div>
    <div class="card"><h2>Quick start</h2><pre>curl -X POST /v1/orders \\
  -H "Authorization: Bearer vc_live_…" \\
  -H "Content-Type: application/json" \\
  -d '{"external_order_id":"SK-1001","customer":{"name":"Ramesh Patel","phone":"+919876543210"},"items":[{"name":"Phone Case","qty":1,"price":499}],"amount":499}'</pre></div>`;
}
async function createApiKey() {
  const label = prompt('Label for this key (e.g. "Shopify production"):', 'Store key');
  if (!label) return;
  const k = await api('/v1/api-keys', { method: 'POST', body: JSON.stringify({ label }) });
  openModal(`<h2>Key created. Copy it now.</h2><p class="small muted">This is the only time the full key is shown.</p><pre>${esc(k.key)}</pre>
    <div class="row-flex"><button onclick="copyText('${esc(k.key)}','API key copied')">Copy key</button><button class="ghost" onclick="closeModal();route()">Done</button></div>`);
}
async function revokeKey(id) { if (!confirm('Revoke this key? Calls using it will fail.')) return; await api('/v1/api-keys/' + id, { method: 'DELETE' }); toast('Key revoked'); route(); }

async function pageBilling(app) {
  const b = await api('/v1/billing');
  app.innerHTML = `<p class="page-sub">Credits pay for calls. Each connected call costs about ₹2 + ₹0.50/min.</p>
    <div class="grid two" style="grid-template-columns:1fr 1fr">
      <div class="card kpi"><h2>Credit balance</h2><div class="n">${fmtINR(b.credits_left)}</div><div class="lbl">${b.calls_this_month || 0} calls this month</div>
        <div style="margin-top:14px"><button onclick="addCredits()">Add credits</button></div></div>
      <div class="card"><h2>Usage this month</h2>
        <div class="feed-item">Connected calls: <b>${b.connected || 0}</b></div><div class="feed-item">Unanswered: <b>${b.unanswered || 0}</b></div>
        <div class="feed-item">Credits used: <b>${fmtINR(b.credits_used_this_month)}</b></div></div></div>
    <div class="card"><h2>Invoices</h2>${(b.invoices || []).length ? `<table><thead><tr><th>Invoice</th><th>Date</th><th>Amount</th></tr></thead><tbody>${b.invoices.map(i => `<tr><td class="mono">${esc(i.id)}</td><td>${esc(i.date)}</td><td>${fmtINR(i.amount)}</td></tr>`).join('')}</tbody></table>` : '<div class="empty">No invoices yet. Add credits and your first invoice appears here.</div>'}</div>`;
}
async function addCredits() {
  const amount = prompt('Add how many credits? (₹)', '500');
  if (!amount) return;
  const b = await api('/v1/billing/add-credits', { method: 'POST', body: JSON.stringify({ amount: parseFloat(amount) }) });
  toast('Credits added. Balance ' + fmtINR(b.credits_left)); route();
}

function pageLogout(app) {
  fetch(API + '/v1/auth/signout', { method: 'POST', headers: { 'Authorization': 'Bearer ' + TOKEN } }).catch(() => {});
  localStorage.removeItem('vc_token'); localStorage.removeItem('vc_merchant');
  app.innerHTML = `<div class="card"><div class="empty"><h2>You signed out</h2><p>Your data is still here when you sign back in.</p><button onclick="location.href='/'">Back to VerifyCOD</button></div></div>`;
}

function initDashboard() {
  if (!TOKEN) { location.href = '/'; return; }
  const renderMode = () => document.querySelectorAll('#modeToggle button').forEach(b => b.classList.toggle('on', b.dataset.mode === mode));
  document.querySelectorAll('#modeToggle button').forEach(b => b.onclick = () => {
    mode = b.dataset.mode; localStorage.setItem('vc_mode', mode); renderMode();
    toast(mode === 'test' ? 'Test mode: sandbox data only' : 'Live mode'); route();
  });
  renderMode();
  $('overlay').onclick = () => { closeDrawer(); closeModal(); closeSearch(); };
  $('hamburger').onclick = () => $('sidebar').classList.toggle('open');
  document.addEventListener('keydown', e => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); openSearch(); }
    if (e.key === 'Escape') { closeSearch(); closeDrawer(); closeModal(); }
  });
  let cache = null;
  $('searchInput').addEventListener('input', async e => {
    const q = e.target.value.trim().toLowerCase();
    if (q.length < 2) { $('searchResults').innerHTML = ''; return; }
    try {
      cache = cache || await api('/v1/verifications?limit=100');
      const hits = cache.filter(v => { const o = v.order || {}, c = o.customer || {};
        return [v.verification_id, o.external_order_id, c.name, c.phone].some(x => (x || '').toLowerCase().includes(q)); }).slice(0, 8);
      $('searchResults').innerHTML = hits.length ? hits.map(v => `<div class="search-hit" onclick="closeSearch();location.hash='#/orders';openOrderDrawer('${v.verification_id}')">
        <b>${esc((v.order?.customer || {}).name || '—')}</b> · ${esc(v.order?.external_order_id || v.verification_id)} <span class="muted">${esc(v.outcome || v.status)}</span></div>`).join('') : '<p class="muted small" style="padding:8px">No matches.</p>';
    } catch (err) { $('searchResults').innerHTML = '<p class="muted small" style="padding:8px">Search unavailable. Is the API running?</p>'; }
  });
  window.addEventListener('hashchange', route);
  document.querySelectorAll('.nav-item[data-route]').forEach(n => n.onclick = () => {
    if (n.dataset.external) { window.open(n.dataset.route, '_blank'); return; }
    location.hash = n.dataset.route.slice(1) || '/'; $('sidebar').classList.remove('open');
  });
  $('bellBtn').onclick = async () => {
    try {
      const s = await api('/v1/analytics/summary'), r = await api('/v1/verifications?status=needs_review&limit=5');
      openModal(`<h2>Notifications</h2>${(s.alerts || []).map(a => `<div class="feed-item">⚠️ ${esc(a.message)}</div>`).join('') || '<p class="muted">No alerts.</p>'}
        <h3>Review queue</h3>${r.length ? r.map(v => `<div class="feed-item">${esc((v.order?.customer || {}).name || '—')}, ${esc(v.outcome || v.status)}</div>`).join('') : '<p class="muted">Review queue is clear.</p>'}
        <div style="margin-top:16px;text-align:right"><button class="ghost" onclick="closeModal()">Close</button></div>`);
      $('bellDot').style.display = 'none';
    } catch (e) { toast('Could not load notifications'); }
  };
  $('avatarBtn').onclick = async () => {
    let name = 'Merchant', email = '', brand = '';
    try { const me = await api('/v1/auth/me'); name = me.user?.name || name; email = me.user?.email || ''; brand = me.merchant?.brand_name || me.merchant?.name || ''; }
    catch (e) { const m = JSON.parse(localStorage.getItem('vc_merchant') || '{}'); brand = m.brand_name || m.name || ''; }
    $('avatarBtn').textContent = (name || 'M').trim().charAt(0).toUpperCase();
    openModal(`<h2>${esc(brand || name)}</h2><p class="muted">Signed in as ${esc(name)}${email ? ' (' + esc(email) + ')' : ''}.</p>
      <div class="row-flex" style="margin-top:14px"><button class="ghost" onclick="closeModal()">Close</button><button onclick="location.hash='#/logout';closeModal()">Sign out</button></div>`);
  };
  route();
}

PAGE === 'landing' ? initLanding() : initDashboard();