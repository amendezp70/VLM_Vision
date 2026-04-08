// vlm_vision/overlay/bay.js
/**
 * Connects to the WebSocket at ws://localhost:{port}/bay/{bayId}
 * and renders detection bounding boxes on the canvas overlay.
 *
 * URL params: ?bay=1  (defaults to 1)
 * State machine: waiting → active → correct|wrong → waiting
 */

// ── Configuration ────────────────────────────────────────────────────────────
const params   = new URLSearchParams(window.location.search);
const BAY_ID   = parseInt(params.get('bay') || '1', 10);
const WS_PORT  = parseInt(params.get('port') || location.port || '8765', 10);
const WS_URL   = `ws://${location.hostname}:${WS_PORT}/bay/${BAY_ID}`;
// Source resolution the model was trained on (must match camera capture res)
const SRC_W    = 3840;
const SRC_H    = 2160;
// Colours
const COL_TARGET = '#ffd700';  // gold
const COL_OTHER  = '#4a9eff';  // blue
// Flash durations (ms)
const CORRECT_FLASH_MS = 1500;
const WRONG_FLASH_MS   = 3000;

// ── DOM refs ──────────────────────────────────────────────────────────────────
const app         = document.getElementById('app');
const bayLabel    = document.getElementById('bay-label');
const liveDot     = document.getElementById('live-dot');
const videoFeed   = document.getElementById('video-feed');
const canvas      = document.getElementById('overlay-canvas');
const ctx         = canvas.getContext('2d');
const orderIdEl   = document.getElementById('order-id-label');
const skuEl       = document.getElementById('sku-display');
const skuDescEl   = document.getElementById('sku-desc');
const qtyEl       = document.getElementById('qty-display');
const timerEl     = document.getElementById('pick-timer');
const lastResultEl= document.getElementById('last-result');
const wrongDetail = document.getElementById('wrong-detail');
const wsStatusEl  = document.getElementById('ws-status');

// ── State ─────────────────────────────────────────────────────────────────────
let currentState   = 'waiting';
let pickStartTime  = null;
let flashTimeout   = null;
let timerInterval  = null;

// ── Initialise ────────────────────────────────────────────────────────────────
bayLabel.textContent = `BAY ${BAY_ID}`;
videoFeed.src = `/bay/${BAY_ID}/video`;

// Resize canvas to match displayed image size whenever window resizes
function resizeCanvas() {
  const rect = videoFeed.getBoundingClientRect();
  canvas.width  = rect.width  || videoFeed.offsetWidth;
  canvas.height = rect.height || videoFeed.offsetHeight;
  canvas.style.left = rect.left - videoFeed.parentElement.getBoundingClientRect().left + 'px';
  canvas.style.top  = rect.top  - videoFeed.parentElement.getBoundingClientRect().top  + 'px';
}
window.addEventListener('resize', resizeCanvas);
videoFeed.addEventListener('load', resizeCanvas);

// ── State machine ─────────────────────────────────────────────────────────────
function setState(state, extra) {
  if (flashTimeout && state !== 'correct' && state !== 'wrong') {
    clearTimeout(flashTimeout);
    flashTimeout = null;
  }
  currentState = state;
  app.className = `state-${state}`;

  if (state === 'active') {
    if (!pickStartTime) {
      pickStartTime = Date.now();
      timerInterval = setInterval(updateTimer, 500);
    }
  }

  if (state === 'correct') {
    playBeep(880, 0.15);
    stopTimer();
    lastResultEl.textContent = '✓ Correct pick';
    lastResultEl.className = 'result-correct';
    flashTimeout = setTimeout(() => setState('waiting'), CORRECT_FLASH_MS);
  }

  if (state === 'wrong') {
    playBeep(220, 0.4);
    stopTimer();
    wrongDetail.textContent = extra ? `Got: ${extra}` : '';
    lastResultEl.textContent = '✗ Wrong pick';
    lastResultEl.className = 'result-wrong';
    flashTimeout = setTimeout(() => setState('waiting'), WRONG_FLASH_MS);
  }

  if (state === 'waiting') {
    stopTimer();
    pickStartTime = null;
    clearCanvas();
  }
}

function stopTimer() {
  if (timerInterval) { clearInterval(timerInterval); timerInterval = null; }
}

function updateTimer() {
  if (!pickStartTime) return;
  const elapsed = Math.floor((Date.now() - pickStartTime) / 1000);
  const m = String(Math.floor(elapsed / 60)).padStart(2, '0');
  const s = String(elapsed % 60).padStart(2, '0');
  timerEl.textContent = `${m}:${s}`;
}

// ── Audio feedback ────────────────────────────────────────────────────────────
let _audioCtx = null;
function playBeep(freq, gain) {
  try {
    if (!_audioCtx) _audioCtx = new AudioContext();
    const osc = _audioCtx.createOscillator();
    const vol = _audioCtx.createGain();
    osc.connect(vol);
    vol.connect(_audioCtx.destination);
    osc.frequency.value = freq;
    vol.gain.setValueAtTime(gain, _audioCtx.currentTime);
    vol.gain.exponentialRampToValueAtTime(0.001, _audioCtx.currentTime + 0.4);
    osc.start();
    osc.stop(_audioCtx.currentTime + 0.4);
  } catch (_) { /* audio blocked by browser policy — silently ignore */ }
}

// ── Canvas rendering ──────────────────────────────────────────────────────────
function clearCanvas() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
}

function drawDetections(detections, activeOrder) {
  resizeCanvas();
  clearCanvas();

  const scaleX = canvas.width  / SRC_W;
  const scaleY = canvas.height / SRC_H;

  for (const det of detections) {
    const [x1, y1, x2, y2] = det.bbox;
    const sx = x1 * scaleX;
    const sy = y1 * scaleY;
    const sw = (x2 - x1) * scaleX;
    const sh = (y2 - y1) * scaleY;

    const isTarget = activeOrder && det.sku === activeOrder.sku;
    const colour   = isTarget ? COL_TARGET : COL_OTHER;
    const lineW    = isTarget ? 3 : 1.5;

    // Bounding box
    ctx.strokeStyle = colour;
    ctx.lineWidth   = lineW;
    if (isTarget) {
      // Pulsing glow
      ctx.shadowColor = COL_TARGET;
      ctx.shadowBlur  = 12;
    } else {
      ctx.shadowBlur = 0;
    }
    ctx.strokeRect(sx, sy, sw, sh);
    ctx.shadowBlur = 0;

    // Label background
    const label    = isTarget ? `▶ PICK THIS  ${det.sku}` : det.sku;
    const fontSize = isTarget ? 14 : 11;
    ctx.font       = `bold ${fontSize}px monospace`;
    const tw       = ctx.measureText(label).width + 8;
    const th       = fontSize + 6;
    ctx.fillStyle  = isTarget ? 'rgba(255,215,0,0.85)' : 'rgba(74,158,255,0.75)';
    ctx.fillRect(sx, sy - th, tw, th);

    // Label text
    ctx.fillStyle = isTarget ? '#000' : '#fff';
    ctx.fillText(label, sx + 4, sy - 4);

    // Arrow pointer for target
    if (isTarget) {
      ctx.fillStyle  = COL_TARGET;
      ctx.font       = 'bold 20px sans-serif';
      ctx.fillText('→', sx - 28, sy + sh / 2 + 8);
    }
  }
}

// ── Order bar update ──────────────────────────────────────────────────────────
function updateOrderBar(order) {
  if (!order) {
    orderIdEl.textContent = '—';
    skuEl.textContent     = '—';
    skuDescEl.textContent = 'Waiting for order';
    qtyEl.textContent     = '—';
    return;
  }
  orderIdEl.textContent = `ORDER ${order.order_id}`;
  skuEl.textContent     = order.sku;
  skuDescEl.textContent = order.sku.replace(/-/g, ' ').toLowerCase();
  qtyEl.textContent     = `× ${order.qty}`;
}

// ── WebSocket ─────────────────────────────────────────────────────────────────
function connect() {
  wsStatusEl.textContent = 'Connecting…';
  liveDot.className = 'dot-offline';
  liveDot.textContent = '● CONNECTING';

  const ws = new WebSocket(WS_URL);

  ws.onopen = () => {
    wsStatusEl.textContent = 'Connected';
    liveDot.className = 'dot-live';
    liveDot.textContent = '● LIVE';
    // Send heartbeats every 5s to keep connection alive
    const hb = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send('ping');
      else clearInterval(hb);
    }, 5000);
  };

  ws.onmessage = (evt) => {
    let msg;
    try { msg = JSON.parse(evt.data); } catch (_) { return; }

    const { status, detections = [], active_order } = msg;

    updateOrderBar(active_order);

    if (status === 'waiting') {
      if (currentState !== 'correct' && currentState !== 'wrong') {
        setState('waiting');
      }
      clearCanvas();
    } else if (status === 'active') {
      if (currentState === 'waiting') setState('active');
      drawDetections(detections, active_order);
    } else if (status === 'confirming') {
      // result is "correct" | "wrong" | "short" — sent by the server after PickVerifier runs
      if (msg.result === 'wrong' || msg.result === 'short') {
        setState('wrong');
      } else {
        setState('correct');
      }
      clearCanvas();
    }
  };

  ws.onclose = () => {
    wsStatusEl.textContent = 'Disconnected — retrying…';
    liveDot.className = 'dot-offline';
    liveDot.textContent = '● OFFLINE';
    setState('waiting');
    setTimeout(connect, 3000);
  };

  ws.onerror = () => ws.close();
}

connect();
