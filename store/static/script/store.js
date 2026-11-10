/* StyleKart demo store: storefront + COD checkout + simulated customer phone */
const VERIFYCOD = 'http://127.0.0.1:8000';
/* API key this store posts orders with. It files every order under merchant 1
   (StyleKart, the demo merchant) — so the orders show up in the dashboard
   when you sign in with the DEMO login. The key only allows CREATING orders;
   it cannot read the dashboard or any other merchant's data.
   To point this store at YOUR merchant instead: create a key in the
   dashboard (API Keys page), copy the vc_live_... value (shown once), and
   paste it here in place of the demo key. Then the store's orders land in
   YOUR dashboard. */
const API_KEY = 'vc_live_demo_stylekart_7f3a9c2e5b8d4f6a1c0e9b8d7f6a5c4e3d2';
const $ = id => document.getElementById(id);
const player = $('player');
const inr = n => '₹' + n.toLocaleString('en-IN');

const PRODUCTS = [
  { id: 'kurta', name: 'Cotton Kurta', desc: 'Handloom cotton, all sizes', price: 1299, was: 1799, cat: 'Clothing', icon: '👘', bg: '#ffe3d1', rate: 4.6, n: 312, tag: 'Bestseller' },
  { id: 'sneakers', name: 'Running Sneakers', desc: 'Lightweight, size 6–11', price: 1999, was: 2499, cat: 'Footwear', icon: '👟', bg: '#e3ecff', rate: 4.5, n: 208, tag: 'New' },
  { id: 'case', name: 'Phone Case', desc: 'Shock-proof, all models', price: 499, cat: 'Accessories', icon: '📱', bg: '#e6f5e9', rate: 4.3, n: 540 },
  { id: 'tshirt', name: 'Cotton T-Shirt', desc: 'Pack of 2, assorted colours', price: 699, was: 899, cat: 'Clothing', icon: '👕', bg: '#fff1d6', rate: 4.4, n: 421 },
  { id: 'bag', name: 'Daypack Backpack', desc: '20L, water resistant', price: 1499, was: 1999, cat: 'Accessories', icon: '🎒', bg: '#f0e6ff', rate: 4.7, n: 156, tag: 'Top rated' },
  { id: 'watch', name: 'Classic Watch', desc: 'Analog, leather strap', price: 2499, cat: 'Accessories', icon: '⌚', bg: '#ffe6ea', rate: 4.2, n: 98 },
  { id: 'shades', name: 'Aviator Sunglasses', desc: 'UV400, metal frame', price: 899, was: 1299, cat: 'Accessories', icon: '🕶️', bg: '#e1f3f5', rate: 4.1, n: 187 },
  { id: 'cap', name: 'Everyday Cap', desc: 'Adjustable, breathable', price: 399, cat: 'Clothing', icon: '🧢', bg: '#fdebd2', rate: 4.0, n: 233 },
];
const CATS = ['All', 'Clothing', 'Footwear', 'Accessories'];
let cart = [], cat = 'All', q = '';
let verificationId = null, pollTimer = null;
let callState = null, callHistory = [], callCtx = {}, callTimer = null;

/* ---------- storefront ---------- */
function renderChips() {
  $('chips').innerHTML = CATS.map(c => `<button class="${c === cat ? 'on' : ''}" onclick="setCat('${c}')">${c}</button>`).join('');
}
function setCat(c) { cat = c; renderChips(); renderProducts(); }
function renderProducts() {
  const list = PRODUCTS.filter(p => (cat === 'All' || p.cat === cat) && (p.name + ' ' + p.desc).toLowerCase().includes(q));
  $('products').innerHTML = list.length ? list.map(p => `<article class="product">
    <div class="art" style="background:${p.bg}">${p.tag ? `<em>${p.tag}</em>` : ''}${p.icon}</div>
    <div class="pinfo"><h3>${p.name}</h3><p>${p.desc}</p><div class="rating"><b>★ ${p.rate}</b> (${p.n})</div>
    <div class="buy"><span class="price">${inr(p.price)}${p.was ? `<s>${inr(p.was)}</s>` : ''}</span><button onclick="addToCart('${p.id}')">Add</button></div></div></article>`).join('')
    : '<div class="noresult">Nothing matches your search.</div>';
}
$('search').oninput = e => { q = e.target.value.trim().toLowerCase(); renderProducts(); };

function toast(msg) { const t = $('toast'); t.textContent = msg; t.classList.add('show'); setTimeout(() => t.classList.remove('show'), 2000); }

/* ---------- cart ---------- */
const subtotal = () => cart.reduce((n, l) => n + l.p.price * l.qty, 0);
function addToCart(id) {
  const l = cart.find(x => x.p.id === id);
  l ? l.qty++ : cart.push({ p: PRODUCTS.find(x => x.id === id), qty: 1 });
  renderCart(); toast('Added to cart');
}
function changeQty(id, d) {
  const l = cart.find(x => x.p.id === id); l.qty += d;
  if (l.qty <= 0) cart = cart.filter(x => x !== l);
  renderCart();
}
function renderCart() {
  $('cartCount').textContent = cart.reduce((n, l) => n + l.qty, 0);
  $('cart').innerHTML = cart.length ? cart.map(l => `<div class="line"><div class="th" style="background:${l.p.bg}">${l.p.icon}</div>
    <div><b>${l.p.name}</b><small>${inr(l.p.price)}</small><div class="qty"><button onclick="changeQty('${l.p.id}',-1)" aria-label="Less">−</button>${l.qty}<button onclick="changeQty('${l.p.id}',1)" aria-label="More">+</button></div></div>
    <b>${inr(l.p.price * l.qty)}</b></div>`).join('') : '<div class="empty">Your cart is empty.<br>Add something you like.</div>';
  const ship = subtotal() >= 999 || !cart.length ? 0 : 60;
  $('cartFoot').innerHTML = cart.length ? `<div class="tot"><span>Subtotal</span><span>${inr(subtotal())}</span></div>
    <div class="tot"><span>Shipping</span><span>${ship ? inr(ship) : 'Free'}</span></div>
    <div class="tot big"><span>Total (COD)</span><span>${inr(subtotal() + ship)}</span></div><button class="btn block" onclick="openCheckout()">Checkout</button>` : '';
}
function openModalEl(id) { $('scrim').classList.add('on'); $(id).classList.add('open'); }
function closeAll() {
  $('scrim').classList.remove('on'); $('drawer').classList.remove('open');
  $('checkout').classList.remove('open'); $('result').classList.remove('open');
}
function openCart() { closeAll(); $('scrim').classList.add('on'); $('drawer').classList.add('open'); }
function openCheckout() {
  closeAll();
  const ship = subtotal() >= 999 ? 0 : 60;
  $('summary').innerHTML = '<h4>Order summary</h4>' + cart.map(l => `<div class="tot"><span>${l.p.name} × ${l.qty}</span><span>${inr(l.p.price * l.qty)}</span></div>`).join('')
    + `<div class="tot"><span>Shipping</span><span>${ship ? inr(ship) : 'Free'}</span></div><div class="tot big" style="margin:10px 0 0"><span>Pay on delivery</span><span>${inr(subtotal() + ship)}</span></div>`;
  $('orderStatus').textContent = ''; $('checkoutBtn').disabled = false;
  openModalEl('checkout');
}
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeAll(); });

/* ---------- checkout: POST the order to VerifyCOD ---------- */
$('checkoutBtn').onclick = async () => {
  const ship = subtotal() >= 999 ? 0 : 60, total = subtotal() + ship;
  const order = {
    external_order_id: 'SK-' + Date.now(),
    customer: { name: $('fName').value.trim(), phone: $('fPhone').value.trim(), language_hint: 'hi-en' },
    address: { line1: $('fLine1').value.trim(), landmark: $('fLandmark').value.trim(), city: $('fCity').value.trim(), state: $('fState').value.trim(), pincode: $('fPincode').value.trim() },
    items: cart.map(l => ({ name: l.p.name, qty: l.qty, price: l.p.price })),
    amount: total, currency: 'INR', payment_mode: 'COD',
    options: { call_now: true, max_attempts: 3, metadata: { campaign: 'demo' } },
  };
  $('checkoutBtn').disabled = true; $('orderStatus').textContent = 'Placing your order…';
  try {
    const res = await fetch(VERIFYCOD + '/v1/orders', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-API-Key': API_KEY }, body: JSON.stringify(order) });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'VerifyCOD error');
    verificationId = data.verification_id;
    cart = []; renderCart(); closeAll();
    $('resTitle').textContent = 'Order placed'; $('resId').textContent = 'Order ' + order.external_order_id + ' · ' + inr(total) + ' on delivery';
    $('orderBadge').textContent = 'Waiting for the verification call'; $('orderBadge').className = 'badge idle'; $('orderJson').textContent = '—';
    setSteps('calling'); openModalEl('result');
    setPhoneStatus('Waiting for the verification call…'); startPolling();
  } catch (err) {
    $('orderStatus').textContent = 'Could not place the order: ' + err.message + '. Is the VerifyCOD API running on port 8000?';
    $('checkoutBtn').disabled = false;
  }
};
function setSteps(s) {
  const c = $('stCall'), d = $('stDone');
  c.className = s === 'calling' ? 'active' : 'done';
  d.className = s === 'ok' ? 'done' : s === 'fail' ? 'fail' : s === 'review' ? 'active' : '';
  d.textContent = s === 'fail' ? 'Order not confirmed' : s === 'review' ? 'Seller is reviewing' : 'Confirmed for shipping';
}

/* ---------- customer phone ---------- */
const phone = $('phone');
function togglePhone() { phone.classList.toggle('open'); }
const tick = () => { const d = new Date(); $('clock').textContent = d.getHours() + ':' + String(d.getMinutes()).padStart(2, '0'); };
tick(); setInterval(tick, 30000);

function startPolling() {
  stopPolling();
  pollTimer = setInterval(async () => {
    if (!verificationId) return;
    try {
      const v = await (await fetch(VERIFYCOD + '/v1/verifications/' + verificationId)).json();
      if (v.status === 'calling' && loopState === 'idle') ring(v);
      if ((v.status === 'completed' || v.status === 'needs_review') && v.outcome_detail) showOrderResult(v);
      if (v.status === 'cancelled') { setPhoneStatus('Call cancelled by the seller.'); phone.classList.remove('ringing'); stopPolling(); }
    } catch (e) { /* API down, keep polling */ }
  }, 2000);
}
function stopPolling() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } }
function setPhoneStatus(t) { $('phoneStatus').textContent = t; }

function ring() {
  phone.classList.add('open', 'ringing');
  $('phoneBody').innerHTML = `<div class="callee ring"><div class="av">S</div><b>StyleKart</b><span>Order verification · incoming call</span></div>
    <div class="call-btns"><button class="decline" onclick="declineCall()" aria-label="Decline">✕</button><button class="answer" onclick="answerCall()" aria-label="Answer">✓</button></div>`;
  setPhoneStatus('Ringing… answer it!');
}
async function answerCall() {
  phone.classList.remove('ringing');
  $('phoneBody').innerHTML = '<p style="text-align:center;color:#b8aca2;margin-top:80px">Connecting…</p>';
  setPhoneStatus('Agent bol raha hai…');
  try {
    await startMic(); // open the mic first so barge-in works during the greeting
    const form = new FormData(); form.append('verification_id', verificationId);
    const res = await fetch(VERIFYCOD + '/api/start', { method: 'POST', body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'server error');
    callHistory = data.history; callCtx = data.ctx; callState = data.next_state;
    renderPhoneTranscript();
    let secs = 0;
    $('phoneBody').innerHTML = `<div class="callee"><div class="av">S</div><b>StyleKart</b><span id="callTimer">00:00</span></div>
      <div class="level-wrap"><div id="levelBar"></div></div>
      <p class="hint">Always listening. Just speak, or interrupt the agent anytime.<br>Use headphones to avoid echo.</p>
      <button class="endbtn" onclick="endCall()">End call</button>`;
    callTimer = setInterval(() => { secs++; const t = $('callTimer'); if (t) t.textContent = String(Math.floor(secs / 60)).padStart(2, '0') + ':' + String(secs % 60).padStart(2, '0'); }, 1000);
    playAudio(data.audio_base64); loopState = 'speaking';
    setPhoneStatus('Agent bol raha hai… (bolna ho to beech mein bolo)');
  } catch (err) {
    stopMic();
    stopPolling(); // a failed pickup must NOT re-ring — retry with a fresh order
    let msg;
    if (err.name === 'NotFoundError') {
      msg = 'Mic nahi mila — browser ko koi microphone nahi dikh raha. Mic plug in / enable karo, mic use karne wale dusre apps band karo, phir naya order place karke dobara try karo.';
    } else if (err.name === 'NotAllowedError') {
      msg = 'Mic permission nahi mili — address bar ke lock/tune icon se Microphone ko Allow karo, phir naya order place karo.';
    } else {
      msg = 'Error: ' + err.message;
    }
    $('phoneBody').innerHTML = '<div class="idle-msg">' + msg + '</div>';
    setPhoneStatus(msg);
    verificationId = null;
  }
}
function declineCall() {
  stopPolling(); phone.classList.remove('ringing');
  $('phoneBody').innerHTML = '<div class="idle-msg">Call declined.<br>The order stays unverified.</div>';
  setPhoneStatus('Declined. Place a new order to try again.');
  fetch(VERIFYCOD + '/v1/verifications/' + verificationId + '/cancel', { method: 'POST', headers: { 'X-API-Key': API_KEY } }).catch(() => {});
  setSteps('calling'); $('stCall').className = 'fail'; $('orderBadge').textContent = 'Call declined'; $('orderBadge').className = 'badge bad';
  verificationId = null;
}
function endCall() {
  stopMic(); clearInterval(callTimer); loopState = 'done'; stopPolling();
  $('phoneBody').innerHTML = '<div class="idle-msg">Call ended.</div>';
  setPhoneStatus('Call ended. Place a new order to try again.');
}
function renderPhoneTranscript() {
  $('phoneTranscript').innerHTML = callHistory.map(t => `<div class="turn ${t.speaker}"><div class="who">${t.speaker === 'agent' ? 'Agent' : 'You'}</div>${t.text}</div>`).join('');
  $('phoneTranscript').scrollTop = $('phoneTranscript').scrollHeight;
}
function playAudio(b64) { player.src = 'data:audio/wav;base64,' + b64; player.play().catch(() => {}); }
player.onended = () => { if (loopState === 'speaking') { loopState = 'listening'; setPhoneStatus('Sun raha hoon… bolo!'); } };

/* ---------------------------------------------------------------------------
   Continuous voice loop + barge-in (unchanged logic).
   listening -> capturing (user speaks) -> sending (1.5s silence) -> speaking
   (agent reply; mic still monitored so the user can interrupt) -> done.
   Barge-in needs a higher volume held for 300ms, so a blip of agent echo
   doesn't interrupt. Headphones make it bulletproof.
--------------------------------------------------------------------------- */
const SPEAK_THRESHOLD = 0.02, BARGE_IN_THRESHOLD = 0.035;
const SILENCE_MS = 1500, BARGE_IN_MS = 300, MIN_SPEECH_MS = 400;
let loopState = 'idle'; // idle | listening | capturing | sending | speaking | done
let micStream = null, audioCtx = null, analyser = null, processor = null, vadTimer = null, recChunks = [];
let speechStartAt = 0, silenceSince = 0, bargeSince = 0;

async function startMic() {
  micStream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
  audioCtx = new AudioContext();
  const src = audioCtx.createMediaStreamSource(micStream);
  analyser = audioCtx.createAnalyser(); analyser.fftSize = 512; src.connect(analyser);
  processor = audioCtx.createScriptProcessor(4096, 1, 1); // output stays silent, so no mic audio hits the speakers
  processor.onaudioprocess = e => { if (loopState === 'capturing') recChunks.push(new Float32Array(e.inputBuffer.getChannelData(0))); };
  src.connect(processor); processor.connect(audioCtx.destination);
  loopState = 'listening'; vadTimer = setInterval(vadTick, 100);
}
function stopMic() {
  if (vadTimer) { clearInterval(vadTimer); vadTimer = null; }
  if (processor) { try { processor.disconnect(); } catch (e) {} processor = null; }
  if (micStream) { micStream.getTracks().forEach(t => t.stop()); micStream = null; }
  if (audioCtx) { audioCtx.close().catch(() => {}); audioCtx = null; }
  analyser = null;
}
function micRms() {
  const buf = new Uint8Array(analyser.fftSize); analyser.getByteTimeDomainData(buf);
  let sum = 0; for (let i = 0; i < buf.length; i++) { const v = (buf[i] - 128) / 128; sum += v * v; }
  return Math.sqrt(sum / buf.length);
}
function vadTick() {
  if (!analyser || loopState === 'idle' || loopState === 'done' || loopState === 'sending') return;
  const rms = micRms(), now = Date.now(), bar = $('levelBar');
  if (bar) bar.style.width = Math.min(100, Math.round(rms * 1000)) + '%';
  if (loopState === 'listening') {
    if (rms > SPEAK_THRESHOLD) { loopState = 'capturing'; recChunks = []; speechStartAt = now; silenceSince = 0; setPhoneStatus('Sun raha hoon… bol rahe ho!'); }
  } else if (loopState === 'capturing') {
    if (rms > SPEAK_THRESHOLD) silenceSince = 0;
    else { if (!silenceSince) silenceSince = now; if (now - silenceSince > SILENCE_MS && now - speechStartAt > MIN_SPEECH_MS) sendClip(); }
  } else if (loopState === 'speaking') {
    if (rms > BARGE_IN_THRESHOLD) {
      if (!bargeSince) bargeSince = now;
      if (now - bargeSince > BARGE_IN_MS) {
        player.pause(); bargeSince = 0; loopState = 'capturing'; recChunks = []; speechStartAt = now; silenceSince = 0;
        setPhoneStatus('Ruk gaya, aap bolo, sun raha hoon!');
      }
    } else bargeSince = 0;
  }
}
async function sendClip() {
  loopState = 'sending'; setPhoneStatus('Bhej raha hoon…');
  const total = recChunks.reduce((n, c) => n + c.length, 0), samples = new Float32Array(total);
  let off = 0; recChunks.forEach(c => { samples.set(c, off); off += c.length; }); recChunks = [];
  const form = new FormData();
  form.append('audio', encodeWav(samples, audioCtx.sampleRate), 'clip.wav');
  form.append('verification_id', verificationId); form.append('state', callState);
  form.append('history', JSON.stringify(callHistory)); form.append('ctx', JSON.stringify(callCtx));
  try {
    const res = await fetch(VERIFYCOD + '/api/voice', { method: 'POST', body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'server error');
    callHistory = data.history; callCtx = data.ctx; callState = data.next_state;
    renderPhoneTranscript();
    if (data.done) { finishCall(data.outcome); return; }
    playAudio(data.audio_base64); loopState = 'speaking';
    setPhoneStatus('Agent bol raha hai… (bolna ho to beech mein bolo)');
  } catch (err) { setPhoneStatus('Error: ' + err.message + ', phir se bolo.'); loopState = 'listening'; }
}
// Gnani STT takes wav/mp3/flac/ogg/m4a/aac, not webm, so we encode 16-bit mono WAV ourselves.
function encodeWav(samples, sampleRate) {
  const buf = new ArrayBuffer(44 + samples.length * 2), v = new DataView(buf);
  const w = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  w(0, 'RIFF'); v.setUint32(4, 36 + samples.length * 2, true); w(8, 'WAVE'); w(12, 'fmt '); v.setUint32(16, 16, true);
  v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, sampleRate, true); v.setUint32(28, sampleRate * 2, true);
  v.setUint16(32, 2, true); v.setUint16(34, 16, true); w(36, 'data'); v.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) { const s = Math.max(-1, Math.min(1, samples[i])); v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7FFF, true); }
  return new Blob([buf], { type: 'audio/wav' });
}
function finishCall(outcome) {
  stopMic(); clearInterval(callTimer); loopState = 'done';
  $('phoneBody').innerHTML = '<div class="idle-msg">Call finished.<br>Thanks for confirming!</div>';
  setPhoneStatus('Call finished: ' + outcome.outcome + '.');
  showOrderResult({ outcome_detail: outcome, outcome: outcome.outcome }); stopPolling();
}
function showOrderResult(v) {
  const o = v.outcome_detail || {}, out = v.outcome || o.outcome || '—';
  const good = out === 'CONFIRMED' || out === 'ADDRESS_UPDATED';
  $('orderBadge').textContent = out + (o.confidence !== undefined ? ' · confidence ' + o.confidence : '');
  $('orderBadge').className = 'badge ' + (good ? 'ok' : out === 'NEEDS_REVIEW' ? 'warn' : 'bad');
  $('orderJson').textContent = JSON.stringify(o, null, 2);
  $('resTitle').textContent = good ? 'Order confirmed' : out === 'NEEDS_REVIEW' ? 'Order under review' : 'Order not confirmed';
  setSteps(good ? 'ok' : out === 'NEEDS_REVIEW' ? 'review' : 'fail');
  if (!$('result').classList.contains('open')) openModalEl('result');
}

renderChips(); renderProducts(); renderCart();