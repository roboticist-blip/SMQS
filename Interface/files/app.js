/**
 * app.js — IoT Telemetry Dashboard (STM32 5-channel ADC)
 *
 * Fetches 5 ADC channels (A0–A4, 12-bit, 0–4095) from FastAPI backend.
 * Auto-refreshes every 3 seconds.
 */

'use strict';

const CONFIG = {
  API_BASE:         'http://localhost:8000/api',
  REFRESH_INTERVAL: 3000,
  HISTORY_DEFAULT:  60,
  HISTORY_LIMIT:    300,
  MAX_TABLE_ROWS:   50,
  CHART_MAX_POINTS: 120,
  ADC_MAX:          4095,
};

// 5 channels — colours and labels
const CHANNELS = [
  { key: 'A0', color: '#ff6b35', label: 'A0' },
  { key: 'A1', color: '#38bdf8', label: 'A1' },
  { key: 'A2', color: '#a78bfa', label: 'A2' },
  { key: 'A3', color: '#34d399', label: 'A3' },
  { key: 'A4', color: '#fbbf24', label: 'A4' },
];

const state = {
  devices:        [],
  latestReadings: [],
  history:        [],
  selectedDevice: null,
  rangeMinutes:   CONFIG.HISTORY_DEFAULT,
  connected:      false,
  lastUpdate:     null,
  messageCount:   0,
  charts:         {},
  sparklines:     {},
  refreshTimer:   null,
  countdownTimer: null,
  _prevValues:    {},      // device_id -> {A0..A4} for trend arrows
};

let dom = {};

function resolveDOM() {
  dom = {
    statusDot:      document.getElementById('statusDot'),
    statusText:     document.getElementById('statusText'),
    refreshBtn:     document.getElementById('refreshBtn'),
    alertBar:       document.getElementById('alertBar'),
    deviceList:     document.getElementById('deviceList'),
    lastUpdateTime: document.getElementById('lastUpdateTime'),
    dataCount:      document.getElementById('dataCount'),
    tableBody:      document.getElementById('tableBody'),
    tableCount:     document.getElementById('tableCount'),
    countdownProg:  document.getElementById('countdownProgress'),
    footerDevice:   document.getElementById('footerDevice'),
    footerMsgs:     document.getElementById('footerMsgs'),
    chartTimestamp: document.getElementById('chartTimestamp'),
  };
}

// ─────────────────────────────────────────────
// API
// ─────────────────────────────────────────────
async function fetchJSON(path) {
  const res = await fetch(CONFIG.API_BASE + path, { signal: AbortSignal.timeout(5000) });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}
const fetchLatest  = () => fetchJSON('/latest');
const fetchDevices = () => fetchJSON('/devices');
const fetchHistory = () => {
  const dev = state.selectedDevice ? `&device_id=${state.selectedDevice}` : '';
  return fetchJSON(`/history?range_minutes=${state.rangeMinutes}&limit=${CONFIG.HISTORY_LIMIT}${dev}`);
};

// ─────────────────────────────────────────────
// Connection status
// ─────────────────────────────────────────────
function setConnected(ok) {
  state.connected = ok;
  dom.statusDot.className = 'status-dot' + (ok ? ' online pulse' : '');
  dom.statusText.textContent = ok ? 'LIVE' : 'OFFLINE';
  dom.alertBar.className = ok ? 'alert-bar' : 'alert-bar error';
  if (!ok) dom.alertBar.textContent = '⚠  Cannot reach backend — retrying…';
}

// ─────────────────────────────────────────────
// Charts
// ─────────────────────────────────────────────
const CHART_DEFAULTS = {
  responsive: true,
  maintainAspectRatio: false,
  animation: { duration: 0 },
  plugins: {
    legend: { display: false },
    tooltip: {
      backgroundColor: '#181c22',
      borderColor: '#2a3040',
      borderWidth: 1,
      titleFont: { family: "'IBM Plex Mono', monospace", size: 10 },
      bodyFont:  { family: "'IBM Plex Mono', monospace", size: 11 },
      titleColor: '#8a96a8',
      bodyColor:  '#e8edf5',
    },
  },
  scales: {
    x: {
      type: 'time',
      time: { tooltipFormat: 'HH:mm:ss', displayFormats: { minute: 'HH:mm', second: 'HH:mm:ss' } },
      ticks: { color: '#8a96a8', font: { family: "'IBM Plex Mono', monospace", size: 9 }, maxTicksLimit: 8 },
      grid:  { color: 'rgba(42,48,64,0.8)' },
    },
    y: {
      min: 0,
      max: CONFIG.ADC_MAX,
      ticks: { color: '#8a96a8', font: { family: "'IBM Plex Mono', monospace", size: 9 } },
      grid:  { color: 'rgba(42,48,64,0.8)' },
    },
  },
};

function makeDataset(label, color, data = []) {
  return {
    label,
    data,
    borderColor:     color,
    backgroundColor: color + '18',
    borderWidth:     1.5,
    pointRadius:     0,
    pointHoverRadius: 3,
    fill:    true,
    tension: 0.3,
  };
}

function initCharts() {
  Chart.defaults.color = '#8a96a8';

  // Individual channel charts (A0–A4)
  CHANNELS.forEach(ch => {
    const canvas = document.getElementById(`chart${ch.key}`);
    if (!canvas) return;
    state.charts[ch.key] = new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: { datasets: [makeDataset(ch.label, ch.color)] },
      options: {
        ...CHART_DEFAULTS,
        scales: {
          ...CHART_DEFAULTS.scales,
          y: {
            ...CHART_DEFAULTS.scales.y,
            title: { display: true, text: 'ADC', color: ch.color,
                     font: { family: "'IBM Plex Mono', monospace", size: 9 } },
          },
        },
      },
    });
  });

  // All-channels combined chart
  state.charts.combined = new Chart(
    document.getElementById('chartCombined').getContext('2d'),
    {
      type: 'line',
      data: { datasets: CHANNELS.map(ch => makeDataset(ch.label, ch.color)) },
      options: {
        ...CHART_DEFAULTS,
        plugins: {
          ...CHART_DEFAULTS.plugins,
          legend: {
            display: true,
            labels: {
              color: '#8a96a8',
              font: { family: "'IBM Plex Mono', monospace", size: 10 },
              boxWidth: 12,
              padding: 16,
            },
          },
        },
      },
    }
  );
}

function initSparkline(id, color) {
  const canvas = document.getElementById(id);
  if (!canvas) return;
  state.sparklines[id] = new Chart(canvas.getContext('2d'), {
    type: 'line',
    data: { datasets: [{ data: [], borderColor: color, borderWidth: 1.5, pointRadius: 0, fill: false, tension: 0.4 }] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 200 },
      plugins: { legend: { display: false }, tooltip: { enabled: false } },
      scales: {
        x: { display: false, type: 'time' },
        y: { display: false, min: 0, max: CONFIG.ADC_MAX },
      },
    },
  });
}

// ─────────────────────────────────────────────
// Countdown ring
// ─────────────────────────────────────────────
const RING_C = 2 * Math.PI * 11;

function startCountdown() {
  clearInterval(state.countdownTimer);
  const total = CONFIG.REFRESH_INTERVAL / 1000;
  let rem = total;
  state.countdownTimer = setInterval(() => {
    rem -= 1;
    if (rem < 0) rem = total;
    if (dom.countdownProg)
      dom.countdownProg.style.strokeDashoffset = RING_C * (1 - rem / total);
  }, 1000);
}

// ─────────────────────────────────────────────
// Metric cards
// ─────────────────────────────────────────────
function updateCards(latest) {
  if (!latest?.length) return;

  const readings = state.selectedDevice
    ? latest.filter(r => r.device_id === state.selectedDevice)
    : latest;
  if (!readings.length) return;

  const avg = field => Math.round(readings.reduce((s, r) => s + r[field], 0) / readings.length);

  CHANNELS.forEach(ch => {
    const val    = avg(ch.key);
    const valEl  = document.getElementById(`val${ch.key}`);
    const trendEl = document.getElementById(`trend${ch.key}`);
    const metaEl = document.getElementById(`meta${ch.key}`);
    const barEl  = document.getElementById(`bar${ch.key}`);

    if (valEl) {
      valEl.classList.remove('data-update');
      void valEl.offsetWidth;
      valEl.textContent = val;
      valEl.classList.add('data-update');
    }

    // Percentage bar fill
    if (barEl) {
      const pct = (val / CONFIG.ADC_MAX * 100).toFixed(1);
      barEl.style.width = pct + '%';
      barEl.title = `${pct}% of full scale`;
    }

    // Trend arrow
    const prevKey = ch.key;
    const prev    = state._prevValues[prevKey];
    if (trendEl) {
      if (prev != null) {
        const delta = val - prev;
        if (Math.abs(delta) < 2) {
          trendEl.className = 'card-trend flat';
          trendEl.textContent = '—';
        } else if (delta > 0) {
          trendEl.className = 'card-trend up';
          trendEl.textContent = `↑ ${delta}`;
        } else {
          trendEl.className = 'card-trend down';
          trendEl.textContent = `↓ ${Math.abs(delta)}`;
        }
      }
    }
    state._prevValues[prevKey] = val;

    // Timestamp
    const newest = readings.reduce((a, b) =>
      new Date(a.timestamp) > new Date(b.timestamp) ? a : b);
    if (metaEl) metaEl.textContent = `updated ${new Date(newest.timestamp).toLocaleTimeString()}`;
  });

  state.messageCount++;
  if (dom.footerMsgs) dom.footerMsgs.textContent = state.messageCount;
}

// ─────────────────────────────────────────────
// Sparklines
// ─────────────────────────────────────────────
function updateSparklines(history) {
  const recent = (history.readings || []).slice(-30);
  CHANNELS.forEach(ch => {
    const sp = state.sparklines[`spark${ch.key}`];
    if (!sp) return;
    sp.data.datasets[0].data = recent.map(r => ({ x: new Date(r.timestamp), y: r[ch.key] }));
    sp.update('none');
  });
}

// ─────────────────────────────────────────────
// Charts update
// ─────────────────────────────────────────────
function updateCharts(history) {
  const readings = history.readings || [];
  const thin = (arr, max) => {
    if (arr.length <= max) return arr;
    const step = Math.ceil(arr.length / max);
    return arr.filter((_, i) => i % step === 0);
  };
  const pts = thin(readings, CONFIG.CHART_MAX_POINTS);

  CHANNELS.forEach((ch, i) => {
    const data = pts.map(r => ({ x: new Date(r.timestamp), y: r[ch.key] }));
    if (state.charts[ch.key]) {
      state.charts[ch.key].data.datasets[0].data = data;
      state.charts[ch.key].update('none');
    }
    if (state.charts.combined) {
      state.charts.combined.data.datasets[i].data = data;
    }
  });
  if (state.charts.combined) state.charts.combined.update('none');

  if (dom.chartTimestamp)
    dom.chartTimestamp.textContent = `${readings.length} pts · ${new Date().toLocaleTimeString()}`;
  if (dom.dataCount)
    dom.dataCount.textContent = history.count || readings.length;
}

// ─────────────────────────────────────────────
// Device sidebar
// ─────────────────────────────────────────────
function updateDeviceList(devicesResp) {
  if (!dom.deviceList || !devicesResp) return;
  const devices = devicesResp.devices || [];
  state.devices = devices;
  dom.deviceList.innerHTML = '';

  const allLi = document.createElement('li');
  allLi.className = 'device-item' + (state.selectedDevice === null ? ' active' : '');
  allLi.innerHTML = `<span class="device-icon live"></span><span class="device-name">all devices</span>`;
  allLi.addEventListener('click', () => selectDevice(null));
  dom.deviceList.appendChild(allLi);

  devices.forEach(d => {
    const li = document.createElement('li');
    li.className = 'device-item' + (state.selectedDevice === d.device_id ? ' active' : '');
    const isRecent = (Date.now() - new Date(d.last_seen)) < 30000;
    li.innerHTML = `
      <span class="device-icon ${isRecent ? 'live' : ''}"></span>
      <span class="device-name" title="${d.device_id}">${d.device_id}</span>
    `;
    li.addEventListener('click', () => selectDevice(d.device_id));
    dom.deviceList.appendChild(li);
  });

  if (dom.footerDevice) dom.footerDevice.textContent = devices.length;
}

function selectDevice(deviceId) {
  state.selectedDevice = deviceId;
  dom.deviceList.querySelectorAll('.device-item').forEach((li, i) => {
    const id = i === 0 ? null : state.devices[i - 1]?.device_id;
    li.classList.toggle('active', id === deviceId);
  });
  loadHistory();
}

// ─────────────────────────────────────────────
// Data table
// ─────────────────────────────────────────────
function updateTable(history) {
  if (!dom.tableBody) return;
  const readings = (history.readings || []).slice().reverse().slice(0, CONFIG.MAX_TABLE_ROWS);

  if (!readings.length) {
    dom.tableBody.innerHTML = `<tr><td colspan="7" class="empty-state">No data in selected range</td></tr>`;
    return;
  }

  dom.tableBody.innerHTML = readings.map(r => `
    <tr>
      <td class="td-device">${escHtml(r.device_id)}</td>
      <td style="color:#ff6b35">${r.A0}</td>
      <td style="color:#38bdf8">${r.A1}</td>
      <td style="color:#a78bfa">${r.A2}</td>
      <td style="color:#34d399">${r.A3}</td>
      <td style="color:#fbbf24">${r.A4}</td>
      <td class="td-time">${new Date(r.timestamp).toLocaleTimeString()}</td>
    </tr>
  `).join('');

  if (dom.tableCount) dom.tableCount.textContent = `${readings.length} rows`;
}

function escHtml(s) {
  return String(s).replace(/[&<>"']/g, c =>
    ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c]));
}

// ─────────────────────────────────────────────
// Load helpers
// ─────────────────────────────────────────────
async function loadLatest() {
  try {
    const data = await fetchLatest();
    setConnected(true);
    state.latestReadings = data;
    updateCards(data);
  } catch (err) {
    setConnected(false);
    console.warn('[latest]', err.message);
  }
}

async function loadHistory() {
  try {
    const data = await fetchHistory();
    updateCharts(data);
    updateSparklines(data);
    updateTable(data);
  } catch (err) {
    console.warn('[history]', err.message);
  }
}

async function loadDevices() {
  try {
    const data = await fetchDevices();
    updateDeviceList(data);
  } catch (err) {
    console.warn('[devices]', err.message);
  }
}

async function refresh() {
  dom.refreshBtn.classList.add('spinning');
  try {
    await loadLatest();
    await loadHistory();
    await loadDevices();
    state.lastUpdate = new Date();
    if (dom.lastUpdateTime) dom.lastUpdateTime.textContent = state.lastUpdate.toLocaleTimeString();
  } finally {
    dom.refreshBtn.classList.remove('spinning');
  }
}

// ─────────────────────────────────────────────
// Range buttons
// ─────────────────────────────────────────────
function setupRangeButtons() {
  document.querySelectorAll('.range-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.range-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.rangeMinutes = parseInt(btn.dataset.minutes, 10);
      loadHistory();
    });
  });
}

function setupRefreshButton() {
  dom.refreshBtn.addEventListener('click', () => {
    clearInterval(state.refreshTimer);
    refresh().then(() => {
      state.refreshTimer = setInterval(refresh, CONFIG.REFRESH_INTERVAL);
      startCountdown();
    });
  });
}

// ─────────────────────────────────────────────
// Bootstrap
// ─────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  resolveDOM();
  initCharts();
  CHANNELS.forEach(ch => initSparkline(`spark${ch.key}`, ch.color));
  setupRangeButtons();
  setupRefreshButton();

  await refresh();
  state.refreshTimer = setInterval(refresh, CONFIG.REFRESH_INTERVAL);
  startCountdown();
  console.info('[IoT Dashboard] Running — STM32 5-ch ADC, refresh %dms', CONFIG.REFRESH_INTERVAL);
});
