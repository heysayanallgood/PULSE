/**
 * PULSE · Globe client (frontend/static/js/app.js)
 *
 * Modes (bottom dock):
 *   journey     plan a trip; legs are drawn in 3D on the globe
 *   live        GTFS-RT buses as heading-rotated billboards
 *   congestion  per-stretch congestion index by hour (traffic model layer)
 *   validation  measured accuracy vs held-out trips, timetable, Google
 *   system      engine + dataset status
 */
/* global Cesium */
import { PulseGlobe } from './globe.js';

const PULSE_BUILD_VERSION = '20261123-v3.0.0-globe';
window.PULSE_BUILD_VERSION = PULSE_BUILD_VERSION;

const CFG = window.PULSE_CONFIG || {};
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const state = {
  mode: 'journey',
  globe: null,
  originCoords: null,
  destCoords: null,
  pickMode: null,
  journeyDs: null,
  journeyData: null,
  selectedOption: 0,
  journeyAbort: null,
  busCollection: null,
  busById: new Map(),
  busLayer: null,
  routeBusLayer: null,
  routeBusTimer: null,
  follow: null,
  followTimer: null,
  liveTimer: null,
  liveRows: [],
  congestionPrim: null,
  congestionWalls: null,
  cgExtrude: true,
  congestionCache: new Map(),
  cgHour: 8,
  cgWeekend: 0,
  cgPlayTimer: null,
  modelStatus: null,
};
window.pulseState = state;

const ROUTE_COLORS = ['#00d4ff', '#b18cff', '#22d38a'];
const FRESH_COLORS = { FRESH: '#22d38a', AGING: '#f5b13d', STALE: '#ff5a5f' };

/* ── helpers ─────────────────────────────────────────────── */
function esc(v) {
  return String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

async function fetchJson(url, options = {}) {
  const res = await fetch(url, options);
  const type = res.headers.get('content-type') || '';
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    if (type.includes('application/json')) {
      try { const e = await res.json(); msg = e?.error?.message || e?.detail || msg; } catch (e) { /* keep */ }
    }
    const err = new Error(msg); err.status = res.status; throw err;
  }
  if (!type.includes('application/json')) throw new Error('The server sent an unexpected response.');
  return res.json();
}

let toastTimer = null;
function toast(msg, ms = 2600) {
  const el = $('#toast');
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), ms);
}

const fmtMin = (m) => (m == null || Number.isNaN(m) ? '–' : `${Math.round(m)}`);
const color = (css, a = 1) => Cesium.Color.fromCssColorString(css).withAlpha(a);

/* ── boot ────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', boot);

async function boot() {
  const status = $('.loader-status');
  if (typeof Cesium === 'undefined') {
    status.textContent = 'Could not load the 3D engine (CesiumJS). Check the network and reload.';
    return;
  }
  const globe = new PulseGlobe('globe', CFG);
  state.globe = globe;
  try {
    await globe.init((s) => { status.textContent = s; });
  } catch (err) {
    console.error(err);
    status.textContent = `Globe failed to start: ${err.message}`;
    return;
  }
  const viewer = globe.viewer;
  state.journeyDs = new Cesium.CustomDataSource('journey');
  viewer.dataSources.add(state.journeyDs);
  state.busLayer = new BusLayer(viewer);
  state.busLayer.show = false;
  state.busCollection = state.busLayer.billboards;
  state.routeBusLayer = new BusLayer(viewer, { alwaysIcons: true });

  wireChrome();
  wireJourney();
  wireLive();
  wireCongestion();
  wireClicks();
  startHud();
  loadModelStatus();
  checkFeed();

  status.textContent = 'Locking on to Delhi…';
  setTimeout(() => $('#loading-screen').classList.add('done'), 600);
  globe.intro();
}

/* ── chrome: dock, chips, rail ───────────────────────────── */
function wireChrome() {
  $$('.dock-btn').forEach((b) => b.addEventListener('click', () => setMode(b.dataset.mode)));
  $$('[data-stack]').forEach((b) => b.addEventListener('click', () => {
    const s = state.globe.setStack(b.dataset.stack);
    toast(`Map: ${b.textContent.trim()}`);
    if (state.journeyData) drawJourney(state.journeyData.options[state.selectedOption]);
    if (state.mode === 'live') renderBuses(state.liveRows);
    return s;
  }));
  $$('button[data-vision]').forEach((b) => b.addEventListener('click', () => state.globe.setVision(b.dataset.vision)));
  $('#btn-fly-delhi').addEventListener('click', () => state.globe.flyToCity(2.5));
  $('#btn-zoom-in').addEventListener('click', () => state.globe.zoom(0.45));
  $('#btn-zoom-out').addEventListener('click', () => state.globe.zoom(-0.8));
  $$('[data-labels]').forEach((b) => b.addEventListener('click', () => {
    const on = state.globe.setLabels(!state.globe.labels);
    toast(on ? 'Road and place names on' : 'Names off');
  }));
  $('#btn-reset-globe').addEventListener('click', () => state.globe.resetGlobe());
  $('#btn-tilt').addEventListener('click', () => state.globe.toggleTilt());
  $('#btn-inspector-close').addEventListener('click', closeInspector);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { cancelPick(); closeInspector(); }
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || '');
    if (typing) return;
    if (e.key === '+' || e.key === '=') state.globe.zoom(0.45);
    if (e.key === '-' || e.key === '_') state.globe.zoom(-0.8);
  });
}

function setMode(mode) {
  if (state.mode === mode) return;
  state.mode = mode;
  document.body.dataset.mode = mode;
  $$('.dock-btn').forEach((b) => b.classList.toggle('active', b.dataset.mode === mode));
  $$('.mode-pane').forEach((p) => p.classList.toggle('active', p.dataset.pane === mode));
  $('#mode-indicator-value').textContent = mode.toUpperCase();
  cancelPick();
  closeInspector();

  state.journeyDs.show = mode === 'journey';
  state.busLayer.show = mode === 'live';
  state.routeBusLayer.show = mode === 'journey';
  if (mode !== 'journey') stopRouteBuses(); else if (state.journeyData) startRouteBuses();
  if (state.congestionPrim) state.congestionPrim.show = mode === 'congestion';
  if (state.congestionWalls) state.congestionWalls.show = mode === 'congestion' && state.cgExtrude;

  clearTimeout(state.liveTimer); state.liveTimer = null;
  stopFollow();
  if (mode !== 'congestion') stopPlay();

  if (mode === 'live') {
    liveLoop();
  } else if (mode === 'congestion') {
    loadCongestion();
  } else if (mode === 'validation') {
    loadValidation();
  } else if (mode === 'system') {
    loadSystem();
  }
}

/* ── HUD ─────────────────────────────────────────────────── */
function startHud() {
  const viewer = state.globe.viewer;
  const ll = $('#hud-latlon'); const alt = $('#hud-alt'); const hdg = $('#hud-hdg'); const pit = $('#hud-pitch');
  const clock = $('#hud-clock'); const loc = $('#hud-locality');
  const istFmt = new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
  setInterval(() => {
    const cam = viewer.camera;
    const h = cam.positionCartographic.height;
    alt.textContent = h > 100000 ? `${(h / 1000).toFixed(0)} KM` : `${Math.round(h).toLocaleString()} M`;
    hdg.textContent = `${String(Math.round(Cesium.Math.toDegrees(cam.heading)) % 360).padStart(3, '0')}°`;
    pit.textContent = `${Math.round(Cesium.Math.toDegrees(cam.pitch))}°`;
    clock.textContent = istFmt.format(new Date());
    const canvas = viewer.scene.canvas;
    const c = state.globe.pickLatLon(new Cesium.Cartesian2(canvas.clientWidth / 2, canvas.clientHeight / 2));
    if (c) {
      ll.textContent = `${Math.abs(c.lat).toFixed(4)}${c.lat >= 0 ? 'N' : 'S'} ${Math.abs(c.lon).toFixed(4)}${c.lon >= 0 ? 'E' : 'W'}`;
      const inDelhi = c.lat > 28.40 && c.lat < 28.90 && c.lon > 76.84 && c.lon < 77.35;
      loc.textContent = inDelhi ? 'NATIONAL CAPITAL TERRITORY · DTC NETWORK' : (h > 2_000_000 ? 'ORBITAL VIEW' : 'OUTSIDE SERVICE AREA');
    } else {
      ll.textContent = 'SPACE';
      loc.textContent = 'ORBITAL VIEW';
    }
  }, 250);
}

async function loadModelStatus() {
  try {
    const m = await fetchJson('/api/v1/analytics/model');
    state.modelStatus = m;
    $('#hud-model').textContent = m.status === 'READY'
      ? `MODEL · ${m.cells_measured_pct}% CELLS MEASURED`
      : 'MODEL · NOT TRAINED';
  } catch (e) {
    $('#hud-model').textContent = 'MODEL · UNAVAILABLE';
  }
}

async function checkFeed() {
  try {
    const h = await fetchJson('/api/v1/vehicles/health');
    const st = (h.status || h.feed_status || '').toString().toUpperCase();
    $('#hud-feed').textContent = CFG.liveEnabled ? (st || 'CONFIGURED') : 'OFF · HISTORICAL MODE';
  } catch (e) {
    $('#hud-feed').textContent = CFG.liveEnabled ? 'UNREACHABLE' : 'OFF · HISTORICAL MODE';
  }
}

/* ── globe clicks + pick mode ────────────────────────────── */
function wireClicks() {
  const viewer = state.globe.viewer;
  const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
  handler.setInputAction((ev) => {
    const ll = state.globe.pickLatLon(ev.position);
    if (state.pickMode) {
      if (!ll) { toast('Click on the ground, not the sky'); return; }
      const label = `${ll.lat.toFixed(5)}, ${ll.lon.toFixed(5)}`;
      if (state.pickMode === 'origin') setOrigin(label, ll.lat, ll.lon); else setDestination(label, ll.lat, ll.lon);
      cancelPick();
      return;
    }
    const picked = viewer.scene.pick(ev.position);
    if (picked && picked.primitive && picked.id && picked.id.kind === 'bus') {
      const layer = picked.id.layer === 'route' ? state.routeBusLayer : state.busLayer;
      showBus(layer.rows.get(picked.id.vehicle_id) || picked.id.vehicle);
      return;
    }
    if (picked && picked.id instanceof Cesium.Entity && picked.id.properties) {
      const p = picked.id.properties.getValue(Cesium.JulianDate.now());
      if (p && p.html) { openInspector(p.html); return; }
    }
    if (state.mode === 'journey' && ll) {
      const label = `${ll.lat.toFixed(5)}, ${ll.lon.toFixed(5)}`;
      openInspector(`
        <div class="insp-kicker">SELECTED POINT</div>
        <div class="insp-title">${ll.lat.toFixed(4)}°N, ${ll.lon.toFixed(4)}°E</div>
        <p class="muted small">Use this spot as the start or end of a journey. PULSE walks you to the nearest stops.</p>
        <div class="insp-actions">
          <button class="btn-ghost" id="insp-set-from"><span class="material-symbols-outlined">trip_origin</span>Set as From</button>
          <button class="btn-ghost" id="insp-set-to"><span class="material-symbols-outlined">location_on</span>Set as To</button>
        </div>`);
      $('#insp-set-from').onclick = () => { setOrigin(label, ll.lat, ll.lon); closeInspector(); };
      $('#insp-set-to').onclick = () => { setDestination(label, ll.lat, ll.lon); closeInspector(); };
    } else if (state.mode === 'congestion' && ll) {
      // nothing selectable on the ground-classified layer; keep the clock card in focus
    }
  }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

  $('#btn-pick-origin').addEventListener('click', () => (state.pickMode === 'origin' ? cancelPick() : startPick('origin')));
  $('#btn-pick-dest').addEventListener('click', () => (state.pickMode === 'destination' ? cancelPick() : startPick('destination')));
  $('#btn-cancel-pick').addEventListener('click', cancelPick);
}

function startPick(target) {
  state.pickMode = target;
  document.body.classList.add('picking');
  $('#pick-banner').hidden = false;
  $('#pick-banner-text').textContent = target === 'origin' ? 'Click the globe to set where you start' : 'Click the globe to set where you are going';
  $('#btn-pick-origin').classList.toggle('active', target === 'origin');
  $('#btn-pick-dest').classList.toggle('active', target === 'destination');
}

function cancelPick() {
  state.pickMode = null;
  document.body.classList.remove('picking');
  $('#pick-banner').hidden = true;
  $('#btn-pick-origin').classList.remove('active');
  $('#btn-pick-dest').classList.remove('active');
}

function openInspector(html) {
  $('#inspector-body').innerHTML = html;
  $('#inspector').hidden = false;
}
function closeInspector() { $('#inspector').hidden = true; stopFollow(); }

/* ── JOURNEY ─────────────────────────────────────────────── */
function wireJourney() {
  setupAutocomplete($('#input-origin'), $('#origin-suggestions'), (it) => setOrigin(it.name, it.lat, it.lon));
  setupAutocomplete($('#input-dest'), $('#dest-suggestions'), (it) => setDestination(it.name, it.lat, it.lon));
  $$('.preset').forEach((p) => p.addEventListener('click', () => {
    $$('.preset').forEach((x) => x.classList.remove('active'));
    p.classList.add('active');
    if (p.dataset.time === 'now') {
      const parts = Object.fromEntries(new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })
        .formatToParts(new Date()).map((x) => [x.type, x.value]));
      $('#input-time').value = `${parts.hour === '24' ? '00' : parts.hour}:${parts.minute}`;
      $('#input-date').value = `${parts.year}-${parts.month}-${parts.day}`;
    } else {
      $('#input-time').value = p.dataset.time;
    }
  }));
  $('#input-time').addEventListener('input', () => $$('.preset').forEach((x) => x.classList.toggle('active', x.dataset.time === $('#input-time').value)));
  $('#btn-swap').addEventListener('click', () => {
    const o = $('#input-origin'); const d = $('#input-dest');
    [o.value, d.value] = [d.value, o.value];
    [state.originCoords, state.destCoords] = [state.destCoords, state.originCoords];
  });
  $('#input-origin').addEventListener('input', () => { state.originCoords = null; });
  $('#input-dest').addEventListener('input', () => { state.destCoords = null; });
  $('#journey-form').addEventListener('submit', (e) => { e.preventDefault(); planJourney(); });
}

window.setOrigin = function setOrigin(name, lat, lon) {
  $('#input-origin').value = name;
  state.originCoords = (typeof lat === 'number' && typeof lon === 'number') ? { lat, lon, name } : null;
  drawEndpoints();
};
window.setDestination = function setDestination(name, lat, lon) {
  $('#input-dest').value = name;
  state.destCoords = (typeof lat === 'number' && typeof lon === 'number') ? { lat, lon, name } : null;
  drawEndpoints();
};
const setOrigin = window.setOrigin;
const setDestination = window.setDestination;

function setupAutocomplete(input, box, onSelect) {
  let timer = null; let items = []; let focus = -1; let ctrl = null;
  const close = () => { box.hidden = true; focus = -1; };
  const render = () => {
    box.innerHTML = items.map((it, i) => {
      const icon = it.type === 'STOP' ? 'directions_bus' : (it.type === 'COORDINATE' ? 'my_location' : 'place');
      const tag = it.type === 'STOP' ? 'STOP' : (it.type === 'COORDINATE' ? 'COORD' : 'PLACE');
      return `<div class="suggestion${i === focus ? ' focused' : ''}" role="option" data-i="${i}">
        <span class="material-symbols-outlined">${icon}</span>
        <div class="suggestion-main"><div class="suggestion-name">${esc(it.name)}</div><div class="suggestion-sub">${esc(it.formatted_address || '')}</div></div>
        <span class="suggestion-tag">${tag}</span></div>`;
    }).join('');
    box.hidden = items.length === 0;
  };
  box.addEventListener('mousedown', (e) => {
    const row = e.target.closest('.suggestion');
    if (!row) return;
    e.preventDefault();
    onSelect(items[Number(row.dataset.i)]);
    close();
  });
  input.addEventListener('input', () => {
    const q = input.value.trim();
    clearTimeout(timer);
    if (q.length < 2) { items = []; close(); return; }
    timer = setTimeout(async () => {
      try {
        if (ctrl) ctrl.abort();
        ctrl = new AbortController();
        const data = await fetchJson(`/api/v1/places/autocomplete?q=${encodeURIComponent(q)}&limit=8`, { signal: ctrl.signal });
        items = data.suggestions || []; focus = -1; render();
      } catch (err) { if (err.name !== 'AbortError') console.warn('autocomplete', err.message); }
    }, 200);
  });
  input.addEventListener('keydown', (e) => {
    if (box.hidden) return;
    if (e.key === 'ArrowDown') { focus = Math.min(items.length - 1, focus + 1); render(); e.preventDefault(); }
    else if (e.key === 'ArrowUp') { focus = Math.max(0, focus - 1); render(); e.preventDefault(); }
    else if (e.key === 'Enter' && focus >= 0) { onSelect(items[focus]); close(); e.preventDefault(); }
    else if (e.key === 'Escape') close();
  });
  input.addEventListener('blur', () => setTimeout(close, 120));
}

function locationParam(coords, text) {
  return coords ? `${coords.lat.toFixed(5)}, ${coords.lon.toFixed(5)}` : text;
}

async function planJourney() {
  const from = locationParam(state.originCoords, $('#input-origin').value.trim());
  const to = locationParam(state.destCoords, $('#input-dest').value.trim());
  if (!from || !to) return;
  const time = $('#input-time').value || '08:30';
  const date = $('#input-date').value;
  const btn = $('#btn-plan');
  btn.disabled = true;
  btn.querySelector('.btn-label').textContent = 'Running the traffic model…';
  const results = $('#journey-results');
  results.innerHTML = '<div class="skeleton"></div><div class="skeleton"></div>';
  if (state.journeyAbort) state.journeyAbort.abort();
  state.journeyAbort = new AbortController();
  stopRouteBuses();
  state.routeBusLayer.clear();
  try {
    const url = `/api/v1/journeys?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}&depart_at=${encodeURIComponent(`${time}:00`)}${date ? `&date=${date}` : ''}`;
    const data = await fetchJson(url, { signal: state.journeyAbort.signal });
    state.journeyData = data;
    renderJourney(data);
  } catch (err) {
    if (err.name === 'AbortError') return;
    state.journeyData = null;
    state.journeyDs.entities.removeAll();
    results.innerHTML = `<div class="notice error"><strong>No journey found.</strong> ${esc(err.message)}<br>Pick a suggestion from the list, or click the globe to drop an exact point.</div>`;
  } finally {
    btn.disabled = false;
    btn.querySelector('.btn-label').textContent = 'Find journeys';
  }
}

function heatStrip(opt) {
  const runs = (opt.legs || []).filter((l) => l.type === 'BUS').flatMap((l) => l.heat || []);
  if (!runs.length) return '';
  const total = runs.reduce((a, r) => a + r.coords.length - 1, 0) || 1;
  const spans = runs.map((r) => {
    const [cr, cg, cb] = ciColor(r.ci);
    return `<span style="width:${((r.coords.length - 1) / total) * 100}%;background:rgb(${cr},${cg},${cb})" title="${esc(r.time)} · ${r.ci}× · ${r.speed_kmh} km/h"></span>`;
  }).join('');
  const worst = runs.reduce((a, r) => (r.ci > a.ci ? r : a), runs[0]);
  return `<div class="heat-label"><span>Traffic along the ride</span><span>worst ${worst.ci}× at ${esc(worst.time)}</span></div><div class="heat-strip" aria-hidden="true">${spans}</div>`;
}

function sourceBadge(opt) {
  const legs = (opt.legs || []).filter((l) => l.type === 'BUS');
  const shares = legs.map((l) => l.measured_share).filter((x) => typeof x === 'number');
  const share = shares.length ? shares.reduce((a, b) => a + b, 0) / shares.length : null;
  const prov = String(opt.provenance || '');
  if (prov.includes('LIVE')) return '<span class="badge live" title="Live GPS fused with history">LIVE + HISTORY</span>';
  if (prov === 'UNTRAINED') return '<span class="badge borrowed" title="Model not trained yet">UNTRAINED</span>';
  if (share != null) {
    const pct = Math.round(share * 100);
    const cls = pct >= 50 ? 'hist' : 'borrowed';
    return `<span class="badge ${cls}" title="Share of road stretches with direct GPS measurements at this time; the rest borrow from the same stretch at nearby times, the route, or the network">${pct}% MEASURED</span>`;
  }
  return `<span class="badge hist">${esc(prov || 'HISTORICAL')}</span>`;
}

function renderJourney(data) {
  const box = $('#journey-results');
  if (data.status !== 'SUCCESS' || !data.options?.length) {
    state.journeyDs.entities.removeAll();
    box.innerHTML = `<div class="empty">No bus connection found between <strong>${esc(data.origin)}</strong> and <strong>${esc(data.destination)}</strong>.<br>Try a nearby major stop, or drop a point on the globe.</div>`;
    return;
  }
  let html = '';
  if (data.off_peak_comparison && Math.abs(data.off_peak_comparison.peak_duration_minutes - data.off_peak_comparison.off_peak_duration_minutes) >= 1) {
    const c = data.off_peak_comparison;
    html += `<div class="insight"><span class="material-symbols-outlined">insights</span><div>The same trip at <strong>${esc(c.off_peak_departure)}</strong> is predicted at <strong>${fmtMin(c.off_peak_duration_minutes)} min</strong> vs <strong>${fmtMin(c.peak_duration_minutes)} min</strong> at your time.</div></div>`;
  }
  data.options.forEach((opt, i) => {
    const walk = opt.walking_minutes || 0; const wait = opt.waiting_minutes || 0; const ride = opt.in_vehicle_minutes || 0;
    const total = Math.max(walk + wait + ride, 1);
    const lo = opt.lower_bound_minutes; const hi = opt.upper_bound_minutes;
    let busIdx = 0;
    const legs = (opt.legs || []).map((l) => {
      if (l.type === 'BUS') {
        const c = ROUTE_COLORS[busIdx++ % ROUTE_COLORS.length];
        return `<div class="leg"><div class="leg-rail"><span class="material-symbols-outlined" style="color:${c}">directions_bus</span></div>
          <div class="leg-body"><span class="leg-route" style="background:${c}">${esc(l.route_name)}</span> ${esc(l.boarding_stop)} → ${esc(l.alighting_stop)}
          <div class="leg-meta">Ride ${fmtMin(l.predicted_duration_minutes)} min (${fmtMin(l.lower_bound_minutes)}–${fmtMin(l.upper_bound_minutes)}) · ${l.distance_km} km · ${l.stops_traversed} stops${l.expected_wait_minutes != null ? ` · wait ~${fmtMin(l.expected_wait_minutes)} min` : ''}${l.congestion_index > 1.05 ? ` · ${l.congestion_index}× free-flow time` : ''}${l.live_weight > 0.05 ? ` · <span style="color:var(--fresh)">live ${Math.round(l.live_weight * 100)}% (${l.live_buses} buses)</span>` : ''}</div></div></div>`;
      }
      if (l.type === 'TRANSFER') {
        return `<div class="leg"><div class="leg-rail"><span class="material-symbols-outlined" style="color:var(--transfer)">transfer_within_a_station</span></div>
          <div class="leg-body">${esc(l.instruction || `Change at ${l.transfer_stop}`)}<div class="leg-meta">${l.expected_wait_minutes != null ? `Wait ~${fmtMin(l.expected_wait_minutes)} min` : ''}</div></div></div>`;
      }
      return `<div class="leg"><div class="leg-rail"><span class="material-symbols-outlined">directions_walk</span></div>
        <div class="leg-body">${esc(l.instruction)}<div class="leg-meta">${fmtMin(l.duration_minutes)} min · ${Math.round(l.distance_m || 0)} m</div></div></div>`;
    }).join('');
    html += `
      <article class="journey-card${i === state.selectedOption ? ' selected' : ''}" data-i="${i}" tabindex="0">
        <div class="jc-top">
          <div>
            <div class="jc-time">${fmtMin(opt.total_duration_minutes)}<small>min</small></div>
            <div class="jc-range">Likely ${fmtMin(lo)}–${fmtMin(hi)} min · ${opt.transfers === 0 ? 'direct' : `${opt.transfers} change${opt.transfers > 1 ? 's' : ''}`}</div>
          </div>
          <div class="jc-badges">${sourceBadge(opt)}<span class="badge ${opt.confidence === 'HIGH' ? 'high' : 'low'}">${esc(opt.confidence)}</span></div>
        </div>
        <div class="time-bar" aria-hidden="true">
          <span class="tb-walk" style="width:${(walk / total) * 100}%"></span>
          <span class="tb-wait" style="width:${(wait / total) * 100}%"></span>
          <span class="tb-ride" style="width:${(ride / total) * 100}%"></span>
        </div>
        <div class="time-legend">
          <span><i style="background:#8a93a6"></i>Walk ${fmtMin(walk)}</span>
          <span><i style="background:var(--transfer)"></i>Wait ${fmtMin(wait)}</span>
          <span><i style="background:var(--accent)"></i>Ride ${fmtMin(ride)}</span>
        </div>
        ${heatStrip(opt)}
        <div class="route-buses" hidden></div>
        <div class="legs">${legs}</div>
      </article>`;
  });
  box.innerHTML = html;
  state.selectedOption = 0;
  $$('.journey-card').forEach((card) => {
    const pick = () => {
      $$('.journey-card').forEach((c) => c.classList.remove('selected'));
      card.classList.add('selected');
      state.selectedOption = Number(card.dataset.i);
      drawJourney(data.options[state.selectedOption], true);
      startRouteBuses();
    };
    card.addEventListener('click', pick);
    card.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(); } });
  });
  $$('.journey-card')[0]?.classList.add('selected');
  drawJourney(data.options[0], true);
  if (state.mode === 'journey') startRouteBuses();
}

/* 3D route drawing: a glowing ground line, a translucent "curtain" wall
   rising from it, and light beams with labels at stops. */
async function drawJourney(opt, fly = false) {
  const ds = state.journeyDs;
  const g = state.globe;
  ds.entities.removeAll();
  if (!opt) { drawEndpoints(); return; }
  const all = [];
  let busIdx = 0;
  for (const leg of opt.legs || []) {
    const geom = (leg.geometry || []).filter((p) => Array.isArray(p) && p.length >= 2);
    geom.forEach((p) => all.push(p));
    if (leg.type === 'WALK' && geom.length >= 2) {
      ds.entities.add({
        polyline: {
          positions: Cesium.Cartesian3.fromDegreesArray(geom.flatMap(([la, lo]) => [lo, la])),
          width: 3,
          clampToGround: true,
          material: new Cesium.PolylineDashMaterialProperty({ color: color('#c9d1e0', 0.9), dashLength: 14 }),
        },
      });
    }
    if (leg.type === 'BUS' && geom.length >= 2) {
      const css = ROUTE_COLORS[busIdx++ % ROUTE_COLORS.length];
      const base = await g.groundHeight(geom[0][0], geom[0][1]);
      const heat = (leg.heat || []).filter((r) => r.coords && r.coords.length >= 2);
      if (heat.length) {
        // Traffic heat map along the route at the time the bus is predicted to
        // pass each stretch (same colour scale as the Congestion view); walls
        // rise where it is slow.
        for (const r of heat) {
          const [cr, cg, cb] = ciColor(r.ci);
          const c = new Cesium.Color(cr / 255, cg / 255, cb / 255, 1);
          const html = `<div class="insp-kicker">ROUTE ${esc(leg.route_name)} · STRETCH AT ${esc(r.time)}</div>
            <div class="insp-title">${r.ci}× free-flow time</div>
            <dl class="kv"><dt>Bus speed</dt><dd>${r.speed_kmh} km/h</dd><dt>Data</dt><dd>${r.measured ? 'measured at this time' : 'borrowed (nearby time / route / network)'}</dd></dl>`;
          const flatR = r.coords.flatMap(([la, lo]) => [lo, la]);
          ds.entities.add({
            polyline: { positions: Cesium.Cartesian3.fromDegreesArray(flatR), width: 8, clampToGround: true, material: c.withAlpha(0.95) },
            properties: { html },
          });
          const h = 60 + Math.min(600, Math.max(0, r.ci - 1) * 260);
          ds.entities.add({
            wall: {
              positions: Cesium.Cartesian3.fromDegreesArray(flatR),
              minimumHeights: r.coords.map(() => base),
              maximumHeights: r.coords.map(() => base + h),
              material: c.withAlpha(0.32),
              outline: false,
            },
            properties: { html },
          });
        }
      } else {
        ds.entities.add({
          polyline: {
            positions: Cesium.Cartesian3.fromDegreesArray(geom.flatMap(([la, lo]) => [lo, la])),
            width: 7,
            clampToGround: true,
            material: new Cesium.PolylineGlowMaterialProperty({ glowPower: 0.22, color: color(css, 0.95) }),
          },
        });
      }
      addBeam(leg.boarding_lat, leg.boarding_lon, base, `${leg.route_name} · board`, leg.boarding_stop, css, 260,
        `<div class="insp-kicker">BOARD · ROUTE ${esc(leg.route_name)}</div><div class="insp-title">${esc(leg.boarding_stop)}</div>
         <dl class="kv"><dt>Departs</dt><dd>${esc(leg.departure_time || '–')}</dd><dt>Ride</dt><dd>${fmtMin(leg.predicted_duration_minutes)} min (${fmtMin(leg.lower_bound_minutes)}–${fmtMin(leg.upper_bound_minutes)})</dd>
         <dt>Distance</dt><dd>${leg.distance_km} km</dd><dt>Stops</dt><dd>${leg.stops_traversed}</dd>
         <dt>Wait</dt><dd>${leg.expected_wait_minutes != null ? `~${fmtMin(leg.expected_wait_minutes)} min` : '–'} <span class="muted small">(${esc(leg.wait_source || '')})</span></dd>
         <dt>Measured</dt><dd>${leg.measured_share != null ? `${Math.round(leg.measured_share * 100)}% of stretches` : '–'}</dd>
         <dt>Traffic</dt><dd>${leg.congestion_index ? `${leg.congestion_index}× free-flow` : '–'}</dd></dl>`);
      addBeam(leg.alighting_lat, leg.alighting_lon, base, 'alight', leg.alighting_stop, css, 200,
        `<div class="insp-kicker">ALIGHT</div><div class="insp-title">${esc(leg.alighting_stop)}</div>`);
    }
    if (leg.type === 'TRANSFER' && leg.transfer_lat && leg.transfer_lon) {
      const base = await g.groundHeight(leg.transfer_lat, leg.transfer_lon);
      addBeam(leg.transfer_lat, leg.transfer_lon, base, 'change', leg.transfer_stop, '#ffb020', 300,
        `<div class="insp-kicker">CHANGE BUSES</div><div class="insp-title">${esc(leg.transfer_stop)}</div><p class="small muted">${esc(leg.instruction || '')}</p>`);
    }
  }
  drawEndpoints();
  if (state.originCoords) all.push([state.originCoords.lat, state.originCoords.lon]);
  if (state.destCoords) all.push([state.destCoords.lat, state.destCoords.lon]);
  if (fly && all.length) g.flyToPositions(all, { pitch: -42, padding: 1.45, avoidPanel: true });
}

function addBeam(lat, lon, base, caption, name, css, height, html) {
  if (typeof lat !== 'number' || typeof lon !== 'number') return;
  const ds = state.journeyDs;
  ds.entities.add({
    polyline: {
      positions: Cesium.Cartesian3.fromDegreesArrayHeights([lon, lat, base, lon, lat, base + height]),
      width: 6,
      material: new Cesium.PolylineGlowMaterialProperty({ glowPower: 0.35, color: color(css, 0.9) }),
    },
    properties: { html },
  });
  ds.entities.add({
    position: Cesium.Cartesian3.fromDegrees(lon, lat, base + height + 12),
    point: { pixelSize: 9, color: color(css), outlineColor: Cesium.Color.BLACK.withAlpha(0.6), outlineWidth: 2, disableDepthTestDistance: Number.POSITIVE_INFINITY },
    label: {
      text: `${name || ''}`.toUpperCase().slice(0, 34),
      font: '600 12px "JetBrains Mono", monospace',
      fillColor: Cesium.Color.WHITE,
      outlineColor: Cesium.Color.BLACK,
      outlineWidth: 3,
      style: Cesium.LabelStyle.FILL_AND_OUTLINE,
      pixelOffset: new Cesium.Cartesian2(0, -16),
      showBackground: true,
      backgroundColor: color('#07080d', 0.66),
      backgroundPadding: new Cesium.Cartesian2(7, 4),
      disableDepthTestDistance: Number.POSITIVE_INFINITY,
      distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, 60000),
    },
    properties: { html },
  });
}

function drawEndpoints() {
  const ds = state.journeyDs;
  if (!ds) return;
  ['pin-origin', 'pin-dest'].forEach((id) => { const e = ds.entities.getById(id); if (e) ds.entities.remove(e); });
  const base = state.globe.baseHeight();
  const add = (id, c, css, tag) => {
    if (!c) return;
    ds.entities.add({
      id,
      position: Cesium.Cartesian3.fromDegrees(c.lon, c.lat, base + 340),
      point: { pixelSize: 12, color: color(css), outlineColor: Cesium.Color.WHITE, outlineWidth: 2, disableDepthTestDistance: Number.POSITIVE_INFINITY },
      label: {
        text: tag, font: '700 11px "JetBrains Mono", monospace', fillColor: color(css), outlineColor: Cesium.Color.BLACK, outlineWidth: 3,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE, pixelOffset: new Cesium.Cartesian2(0, -18), disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
      polyline: {
        positions: Cesium.Cartesian3.fromDegreesArrayHeights([c.lon, c.lat, base, c.lon, c.lat, base + 340]),
        width: 8,
        material: new Cesium.PolylineGlowMaterialProperty({ glowPower: 0.3, color: color(css, 0.9) }),
      },
    });
  };
  add('pin-origin', state.originCoords, '#22d38a', 'FROM');
  add('pin-dest', state.destCoords, '#ff4d6d', 'TO');
}

/* ── LIVE ────────────────────────────────────────────────── */
const busImageCache = {};
function busImage(freshness) {
  const key = (freshness || 'FRESH').toUpperCase();
  if (!busImageCache[key]) {
    busImageCache[key] = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(createBusSvg(key, 0))}`;
  }
  return busImageCache[key];
}

/**
 * Top-down 2D city bus used as a globe billboard. The billboard itself is
 * rotated to the vehicle bearing (alignedAxis = up), so the SVG is drawn
 * pointing north.
 */
function createBusSvg(freshnessState, bearing) {
  const fState = (freshnessState || 'FRESH').toUpperCase();
  const glowColor = fState === 'FRESH' ? '#10B981' : (fState === 'AGING' ? '#F59E0B' : '#EF4444');
  const strokeColor = fState === 'FRESH' ? '#059669' : (fState === 'AGING' ? '#92400E' : '#7F1D1D');
  const highlightColor = fState === 'FRESH' ? '#86EFAC' : (fState === 'AGING' ? '#FDE68A' : '#FCA5A5');
  const rotation = (typeof bearing === 'number' && !Number.isNaN(bearing)) ? Math.round(bearing) : 0;
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 120" width="32" height="60" data-rotation="${rotation}">
  <defs>
    <filter id="g" x="-30%" y="-30%" width="160%" height="160%"><feDropShadow dx="0" dy="0" stdDeviation="4" flood-color="${glowColor}" flood-opacity="0.9"/></filter>
    <linearGradient id="windshield-grad" x1="0%" y1="0%" x2="0%" y2="100%"><stop offset="0%" stop-color="#E0F2FE"/><stop offset="100%" stop-color="#93C5FD"/></linearGradient>
  </defs>
  <g filter="url(#g)">
    <!-- 4 Side Wheels -->
    <rect x="2" y="18" width="5" height="18" rx="2" fill="#1e293b"/><rect x="57" y="18" width="5" height="18" rx="2" fill="#1e293b"/>
    <rect x="2" y="84" width="5" height="18" rx="2" fill="#1e293b"/><rect x="57" y="84" width="5" height="18" rx="2" fill="#1e293b"/>
    <rect x="6" y="8" width="52" height="104" rx="10" fill="#ffffff" stroke="${strokeColor}" stroke-width="2.2"/>
    <polygon points="10,8 14,0 22,0 18,8" fill="#FEF08A"/><polygon points="54,8 50,0 42,0 46,8" fill="#FEF08A"/>
    <rect x="14" y="6" width="36" height="5" rx="2" fill="${glowColor}"/>
    <rect x="16" y="13" width="32" height="6" rx="1.5" fill="#FACC15"/>
    <path d="M 12 24 Q 32 18 52 24 L 50 38 L 14 38 Z" fill="url(#windshield-grad)" stroke="#38bdf8" stroke-width="0.8"/>
    <line x1="8" y1="42" x2="8" y2="94" stroke="${highlightColor}" stroke-width="1.5"/><line x1="56" y1="42" x2="56" y2="94" stroke="${highlightColor}" stroke-width="1.5"/>
    <rect x="9" y="44" width="4" height="48" rx="1.5" fill="#334155"/><rect x="51" y="44" width="4" height="48" rx="1.5" fill="#334155"/>
    <!-- Roof Top AC Climate Unit -->
    <rect x="18" y="48" width="28" height="28" rx="4" fill="#f8fafc" stroke="#94a3b8" stroke-width="1.2"/>
    <line x1="22" y1="55" x2="42" y2="55" stroke="#64748b" stroke-width="1.2"/><line x1="22" y1="62" x2="42" y2="62" stroke="#64748b" stroke-width="1.2"/><line x1="22" y1="69" x2="42" y2="69" stroke="#64748b" stroke-width="1.2"/>
    <rect x="14" y="98" width="36" height="4" rx="1.5" fill="#0f172a"/>
    <rect x="8" y="104" width="6" height="4" rx="1.5" fill="#EF4444"/><rect x="50" y="104" width="6" height="4" rx="1.5" fill="#EF4444"/>
  </g>
</svg>`;
}
window.createBusSvg = createBusSvg;

/* A set of live buses on the globe. Billboards persist between polls and
   glide to each new fix (no flicker); zoomed out they show as freshness dots. */
class BusLayer {
  constructor(viewer, { alwaysIcons = false } = {}) {
    this.viewer = viewer;
    this.alwaysIcons = alwaysIcons;
    this.billboards = viewer.scene.primitives.add(new Cesium.BillboardCollection({ scene: viewer.scene }));
    this.dots = alwaysIcons ? null : viewer.scene.primitives.add(new Cesium.PointPrimitiveCollection());
    this.items = new Map();   // vehicle_id -> { bb, dot, from, to, t0 }
    this.rows = new Map();    // vehicle_id -> latest record
    this.glideMs = 2500;
    viewer.scene.preRender.addEventListener(() => this._tick());
  }

  set show(v) { this.billboards.show = v; if (this.dots) this.dots.show = v; }
  get show() { return this.billboards.show; }

  clear() {
    this.billboards.removeAll();
    if (this.dots) this.dots.removeAll();
    this.items.clear();
    this.rows.clear();
  }

  update(rows, layerName = 'live') {
    const base = state.globe.baseHeight() + 14;
    const seen = new Set();
    const now = performance.now();
    for (const b of rows) {
      seen.add(b.vehicle_id);
      this.rows.set(b.vehicle_id, b);
      const pos = Cesium.Cartesian3.fromDegrees(b.lon, b.lat, base);
      const f = (b.freshness || 'FRESH').toUpperCase();
      const css = FRESH_COLORS[f] || FRESH_COLORS.STALE;
      const rot = (typeof b.bearing === 'number' && !Number.isNaN(b.bearing)) ? -Cesium.Math.toRadians(b.bearing) : 0;
      const id = { kind: 'bus', vehicle_id: b.vehicle_id, vehicle: b, layer: layerName };
      let it = this.items.get(b.vehicle_id);
      if (!it) {
        const bb = this.billboards.add({
          position: pos, image: busImage(f), width: 22, height: 41, rotation: rot,
          alignedAxis: Cesium.Cartesian3.UNIT_Z,
          scaleByDistance: this.alwaysIcons ? new Cesium.NearFarScalar(600, 1.5, 40000, 0.75) : new Cesium.NearFarScalar(600, 1.3, 9000, 0.6),
          translucencyByDistance: this.alwaysIcons ? undefined : new Cesium.NearFarScalar(5000, 1.0, 9000, 0.0),
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
          id,
        });
        const dot = this.dots ? this.dots.add({
          position: pos, pixelSize: 5, color: Cesium.Color.fromCssColorString(css),
          outlineColor: Cesium.Color.fromCssColorString(css).withAlpha(0.25), outlineWidth: 3,
          scaleByDistance: new Cesium.NearFarScalar(5000, 1.3, 80000, 0.7),
          translucencyByDistance: new Cesium.NearFarScalar(5000, 0.0, 9000, 1.0),
          disableDepthTestDistance: Number.POSITIVE_INFINITY, id,
        }) : null;
        it = { bb, dot, from: pos, to: pos, t0: now };
        this.items.set(b.vehicle_id, it);
      } else {
        it.from = it.bb.position;
        it.to = pos;
        it.t0 = now;
        it.bb.image = busImage(f);
        it.bb.rotation = rot;
        it.bb.id = id;
        if (it.dot) { it.dot.color = Cesium.Color.fromCssColorString(css); it.dot.id = id; }
      }
    }
    for (const [vid, it] of this.items) {
      if (!seen.has(vid)) {
        this.billboards.remove(it.bb);
        if (it.dot) this.dots.remove(it.dot);
        this.items.delete(vid);
        this.rows.delete(vid);
      }
    }
  }

  /** Move one bus (follow mode) without touching the others. */
  updateOne(b, layerName = 'live') {
    const rows = [...this.rows.values()].map((r) => (r.vehicle_id === b.vehicle_id ? b : r));
    if (!this.rows.has(b.vehicle_id)) rows.push(b);
    this.update(rows, layerName);
  }

  position(vid) { const it = this.items.get(vid); return it ? it.bb.position : null; }

  _tick() {
    const now = performance.now();
    for (const it of this.items.values()) {
      if (it.from === it.to) continue;
      const t = Math.min(1, (now - it.t0) / this.glideMs);
      const p = Cesium.Cartesian3.lerp(it.from, it.to, t, new Cesium.Cartesian3());
      it.bb.position = p;
      if (it.dot) it.dot.position = p;
      if (t >= 1) it.from = it.to;
    }
  }
}

function routeMatches(b, q) {
  if (!q) return true;
  const needle = q.toLowerCase().replace(/\s+/g, '');
  const name = String(b.route_name || '').toLowerCase().replace(/\s+/g, '');
  const id = String(b.route_id || '').toLowerCase();
  // "534" matches 534, 534UP, 534DOWN, 534A… but not 1534.
  return id === needle || name === needle || (name.startsWith(needle) && !/^\d/.test(name.slice(needle.length)));
}

function wireLive() {
  $('#btn-live-refresh').addEventListener('click', () => loadLive(true));
  let t = null;
  $('#live-route-filter').addEventListener('input', () => { clearTimeout(t); t = setTimeout(() => renderBuses(state.liveRows, true), 200); });
}

/* Poll faster when zoomed in: every 10 s below ~8 km altitude, else 30 s. */
function liveLoop() {
  clearTimeout(state.liveTimer);
  if (state.mode !== 'live') return;
  const h = state.globe.viewer.camera.positionCartographic.height;
  const close = h < 8000;
  loadLive(close).finally(() => {
    if (state.mode !== 'live') return;
    state.liveTimer = setTimeout(liveLoop, (close ? 10 : Math.max(15, CFG.pollIntervalSeconds || 30)) * 1000);
  });
}

async function loadLive(fresh = false) {
  const notice = $('#live-notice');
  try {
    const rows = await fetchJson(`/api/v1/vehicles?limit=5000${fresh ? '&fresh=true' : ''}`);
    state.liveRows = rows;
    renderBuses(rows);
    $('#live-updated').textContent = `Updated ${new Date().toLocaleTimeString('en-GB', { timeZone: 'Asia/Kolkata' })} IST`;
    if (!rows.length) {
      notice.hidden = false;
      notice.className = 'notice warn';
      notice.innerHTML = CFG.liveEnabled
        ? '<strong>The live feed returned no buses.</strong> The Delhi OTD feed may be down or rate-limited. Nothing is simulated in its place.'
        : '<strong>Live feed is off.</strong> Set <code>OTD_API_KEY</code> and <code>LIVE_FEED_ENABLED=true</code> in <code>.env</code> to see buses moving. Journey times still use the historical model.';
    }
    $('#hud-feed').textContent = rows.length ? `LIVE · ${rows.length.toLocaleString()} BUSES` : (CFG.liveEnabled ? 'NO DATA' : 'OFF · HISTORICAL MODE');
  } catch (err) {
    notice.hidden = false;
    notice.className = 'notice error';
    notice.innerHTML = `<strong>Couldn't reach the live feed.</strong> ${esc(err.message)}. Retrying shortly.`;
  }
}

function renderBuses(rows, filterChanged = false) {
  if (!state.busLayer) return;
  const q = $('#live-route-filter').value.trim();
  const shown = rows.filter((b) => routeMatches(b, q));
  if (filterChanged) state.busLayer.clear();
  state.busLayer.update(shown);
  state.busById = new Map(shown.map((b) => [b.vehicle_id, b]));
  const counts = { FRESH: 0, AGING: 0, STALE: 0 };
  shown.forEach((b) => { const f = (b.freshness || 'FRESH').toUpperCase(); counts[f] = (counts[f] || 0) + 1; });
  $('#live-count').textContent = shown.length.toLocaleString();
  $('#live-fresh').textContent = counts.FRESH.toLocaleString();
  $('#live-aging').textContent = counts.AGING.toLocaleString();
  $('#live-stale').textContent = counts.STALE.toLocaleString();
  const notice = $('#live-notice');
  if (q && rows.length && !shown.length) {
    notice.hidden = false; notice.className = 'notice warn';
    notice.innerHTML = `No bus on route <strong>${esc(q)}</strong> is reporting right now. Use the number on the bus, e.g. <code>534</code> or <code>0114(NS)UP</code>.`;
  } else if (rows.length) {
    notice.hidden = true;
  }
  if (filterChanged && q && shown.length) {
    state.globe.flyToPositions(shown.map((b) => [b.lat, b.lon]), { pitch: -55, padding: 1.3, duration: 1.6, avoidPanel: true });
    toast(`${shown.length} bus${shown.length > 1 ? 'es' : ''} on route ${q}`);
  }
}

function busCard(b, following) {
  const f = (b.freshness || '').toUpperCase();
  const fc = f === 'FRESH' ? 'var(--fresh)' : (f === 'AGING' ? 'var(--aging)' : 'var(--stale)');
  return `
    <div class="insp-kicker">DTC BUS · LIVE${following ? ' · FOLLOWING' : ''}</div>
    <div class="insp-title">${esc(b.route_name || b.route_id || 'Bus')} <span class="muted small">${esc(b.vehicle_id)}</span></div>
    <dl class="kv">
      <dt>Route</dt><dd>${esc(b.route_name || '–')} <span class="muted small">(id ${esc(b.route_id || '–')})</span></dd>
      <dt>Trip</dt><dd>${esc(b.trip_id || '–')}</dd>
      <dt>Speed</dt><dd>${b.speed_kmh != null ? `${b.speed_kmh} km/h` : 'unknown'}</dd>
      <dt>Heading</dt><dd>${typeof b.bearing === 'number' ? `${Math.round(b.bearing)}°` : 'unknown'}</dd>
      <dt>Fix age</dt><dd style="color:${fc}" id="insp-age">${esc(f)} · ${b.age_seconds ?? '–'} s</dd>
      <dt>Position</dt><dd id="insp-pos">${Number(b.lat).toFixed(5)}, ${Number(b.lon).toFixed(5)}</dd>
    </dl>
    <div class="insp-actions">${following
      ? '<button class="btn-ghost active" id="insp-follow"><span class="material-symbols-outlined">pause_circle</span>Stop following</button>'
      : '<button class="btn-ghost" id="insp-follow"><span class="material-symbols-outlined">my_location</span>Zoom &amp; follow</button>'}</div>
    ${following ? '<p class="small muted" style="margin-top:8px">Checking for a new fix every 3 s; the feed itself updates every ~10–30 s.</p>' : ''}`;
}

function showBus(b) {
  if (!b) return;
  openInspector(busCard(b, state.follow === b.vehicle_id));
  $('#insp-follow').onclick = () => (state.follow === b.vehicle_id ? (stopFollow(), showBus(b)) : startFollow(b));
}

/* Follow one bus: fly to it, keep the camera on it, and refresh its fix as
   fast as the feed allows (server polls at most every 8 s). */
function startFollow(b) {
  const layer = state.mode === 'journey' ? state.routeBusLayer : state.busLayer;
  stopFollow();
  state.follow = b.vehicle_id;
  state.followLayer = layer;
  openInspector(busCard(b, true));
  $('#insp-follow').onclick = () => { stopFollow(); showBus(b); };
  state.globe.flyToPositions([[b.lat, b.lon]], { pitch: -50, padding: 0.35, duration: 1.6 });
  const tick = async () => {
    if (!state.follow) return;
    try {
      const nb = await fetchJson(`/api/v1/vehicles/${encodeURIComponent(state.follow)}`);
      const before = layer.position(nb.vehicle_id);
      layer.updateOne(nb, layer === state.routeBusLayer ? 'route' : 'live');
      const age = $('#insp-age'); const pos = $('#insp-pos');
      if (age) age.textContent = `${nb.freshness} · ${nb.age_seconds} s`;
      if (pos) pos.textContent = `${Number(nb.lat).toFixed(5)}, ${Number(nb.lon).toFixed(5)}`;
      if (before) state.followAnchor = before;
    } catch (e) {
      toast('This bus has left the live feed');
      stopFollow();
    }
  };
  tick();
  state.followTimer = setInterval(tick, 3000);
  // Keep the camera locked on the gliding bus.
  if (!state.followListener) {
    state.followListener = state.globe.viewer.scene.preRender.addEventListener(() => {
      if (!state.follow || !state.followLayer || state.globe.viewer.camera._currentFlight) return;
      const p = state.followLayer.position(state.follow);
      if (!p) return;
      if (state.followLast) {
        const d = Cesium.Cartesian3.subtract(p, state.followLast, new Cesium.Cartesian3());
        if (Cesium.Cartesian3.magnitude(d) > 0.01 && Cesium.Cartesian3.magnitude(d) < 2000) {
          const cam = state.globe.viewer.camera;
          cam.setView({
            destination: Cesium.Cartesian3.add(cam.positionWC, d, new Cesium.Cartesian3()),
            orientation: { heading: cam.heading, pitch: cam.pitch, roll: cam.roll },
          });
        }
      }
      state.followLast = Cesium.Cartesian3.clone(p);
    });
  }
  state.followLast = null;
}

function stopFollow() {
  clearInterval(state.followTimer);
  state.followTimer = null;
  state.follow = null;
  state.followLast = null;
}

/* Live buses of the routes in the selected journey (journey mode). */
function journeyRouteIds() {
  const opt = state.journeyData?.options?.[state.selectedOption];
  return opt ? [...new Set((opt.legs || []).filter((l) => l.type === 'BUS').map((l) => String(l.route_id)))] : [];
}

async function loadRouteBuses() {
  const ids = journeyRouteIds();
  if (!ids.length || state.mode !== 'journey') return;
  try {
    const lists = await Promise.all(ids.map((r) => fetchJson(`/api/v1/vehicles?route_id=${encodeURIComponent(r)}&limit=500&fresh=true`)));
    const rows = lists.flat();
    state.routeBusLayer.update(rows, 'route');
    const opt = state.journeyData?.options?.[state.selectedOption];
    const el = document.querySelector(`.journey-card[data-i="${state.selectedOption}"] .route-buses`);
    if (el && opt) {
      const parts = (opt.legs || []).filter((l) => l.type === 'BUS').map((l) => {
        const mine = rows.filter((b) => String(b.route_id) === String(l.route_id));
        if (!mine.length) return `<span><strong>${esc(l.route_name)}</strong>: no bus reporting now</span>`;
        const near = mine.map((b) => ({ b, d: haversineKm(b.lat, b.lon, l.boarding_lat, l.boarding_lon) })).sort((a, c) => a.d - c.d)[0];
        return `<span><strong>${esc(l.route_name)}</strong>: ${mine.length} bus${mine.length > 1 ? 'es' : ''} live · nearest ${near.d.toFixed(1)} km from ${esc(l.boarding_stop)}</span>`;
      });
      el.innerHTML = `<span class="material-symbols-outlined">directions_bus</span><div>${parts.join('<br>')}</div>`;
      el.hidden = false;
    }
  } catch (e) { console.warn('route buses', e); }
}

function startRouteBuses() {
  stopRouteBuses();
  state.routeBusLayer.clear();
  loadRouteBuses();
  state.routeBusTimer = setInterval(loadRouteBuses, 10000);
}
function stopRouteBuses() { clearInterval(state.routeBusTimer); state.routeBusTimer = null; }

function haversineKm(la1, lo1, la2, lo2) {
  const r = Math.PI / 180;
  const a = Math.sin(((la2 - la1) * r) / 2) ** 2 + Math.cos(la1 * r) * Math.cos(la2 * r) * Math.sin(((lo2 - lo1) * r) / 2) ** 2;
  return 12742 * Math.asin(Math.sqrt(a));
}

/* ── CONGESTION ──────────────────────────────────────────── */
function wireCongestion() {
  const slider = $('#cg-hour');
  slider.addEventListener('input', () => { state.cgHour = Number(slider.value); updateClock(); debounceCongestion(); });
  $$('.seg[data-weekend]').forEach((b) => b.addEventListener('click', () => {
    $$('.seg[data-weekend]').forEach((x) => x.classList.toggle('active', x === b));
    state.cgWeekend = Number(b.dataset.weekend);
    loadCongestion();
  }));
  $('#btn-cg-play').addEventListener('click', () => (state.cgPlayTimer ? stopPlay() : startPlay()));
  $('#btn-cg-extrude').addEventListener('click', () => {
    state.cgExtrude = !state.cgExtrude;
    $('#btn-cg-extrude').classList.toggle('active', state.cgExtrude);
    $('#btn-cg-extrude').setAttribute('aria-pressed', String(state.cgExtrude));
    if (state.congestionWalls) state.congestionWalls.show = state.cgExtrude;
    if (state.cgExtrude && Cesium.Math.toDegrees(state.globe.viewer.camera.pitch) < -75) state.globe.toggleTilt();
  });
  updateClock();
}

let cgDebounce = null;
function debounceCongestion() { clearTimeout(cgDebounce); cgDebounce = setTimeout(loadCongestion, 120); }

function bandLabel(h) {
  if (h >= 7 && h <= 10) return 'AM PEAK';
  if (h >= 17 && h <= 20) return 'PM PEAK';
  if (h >= 23 || h <= 5) return 'NIGHT';
  return 'OFF-PEAK';
}
function updateClock() {
  $('#cg-clock').textContent = `${String(state.cgHour).padStart(2, '0')}:00`;
  $('#cg-badge').textContent = bandLabel(state.cgHour);
  $('#cg-hour').value = state.cgHour;
  $$('.spark-bar').forEach((b) => b.classList.toggle('active', Number(b.dataset.h) === state.cgHour));
}

function startPlay() {
  $('#btn-cg-play').innerHTML = '<span class="material-symbols-outlined">pause</span>Pause';
  state.cgPlayTimer = setInterval(() => { state.cgHour = (state.cgHour + 1) % 24; updateClock(); loadCongestion(); }, 1700);
}
function stopPlay() {
  clearInterval(state.cgPlayTimer); state.cgPlayTimer = null;
  const b = $('#btn-cg-play');
  if (b) b.innerHTML = '<span class="material-symbols-outlined">play_arrow</span>Play day';
}

function ciColor(ci) {
  // 1.0 = the stretch's own free-flow time (its fastest typical hour) → 3.0× jammed
  const stops = [[1.0, [34, 211, 138]], [1.4, [198, 232, 59]], [1.8, [245, 177, 61]], [2.3, [255, 90, 95]], [3.0, [176, 21, 74]]];
  if (ci <= stops[0][0]) return stops[0][1];
  for (let i = 1; i < stops.length; i++) {
    if (ci <= stops[i][0]) {
      const [a, ca] = stops[i - 1]; const [b, cb] = stops[i];
      const t = (ci - a) / (b - a);
      return ca.map((v, k) => Math.round(v + (cb[k] - v) * t));
    }
  }
  return stops[stops.length - 1][1];
}

async function loadCongestion() {
  const key = `${state.cgHour}:${state.cgWeekend}`;
  const notice = $('#cg-notice');
  let data = state.congestionCache.get(key);
  if (!data) {
    try {
      data = await fetchJson(`/api/v1/analytics/congestion?hour=${state.cgHour}&is_weekend=${state.cgWeekend}`);
      state.congestionCache.set(key, data);
    } catch (err) {
      notice.hidden = false; notice.className = 'notice error';
      notice.innerHTML = `<strong>Couldn't load the traffic layer.</strong> ${esc(err.message)}`;
      return;
    }
  }
  if (key !== `${state.cgHour}:${state.cgWeekend}` || state.mode !== 'congestion') return;
  if (data.status !== 'OK') {
    notice.hidden = false; notice.className = 'notice warn';
    notice.innerHTML = '<strong>The traffic model is not trained yet.</strong> Run <code>python scripts/build_traffic_model.py all</code> to build it from the GPS archive.';
    return;
  }
  notice.hidden = true;
  drawCongestion(data);
  const s = data.summary || {};
  $('#cg-count').textContent = (s.stretches ?? 0).toLocaleString();
  $('#cg-speed').textContent = s.median_speed_kmh != null ? `${s.median_speed_kmh} km/h` : '–';
  $('#cg-slow').textContent = s.share_slowed_2x != null ? `${Math.round(s.share_slowed_2x * 100)}%` : '–';
  $('#cg-measured').textContent = s.share_measured != null ? `${Math.round(s.share_measured * 100)}%` : '–';
  renderSpark(data.network_speed_kmh_by_hour || []);
}

function drawCongestion(data) {
  const scene = state.globe.viewer.scene;
  if (state.congestionPrim) { scene.groundPrimitives.remove(state.congestionPrim); state.congestionPrim = null; }
  if (state.congestionWalls) { scene.primitives.remove(state.congestionWalls); state.congestionWalls = null; }
  const instances = [];
  const walls = [];
  const base = state.globe.baseHeight();
  for (const f of data.features) {
    const [la0, lo0, la1, lo1, ci] = f;
    if (la0 === la1 && lo0 === lo1) continue;
    const [r, g, b] = ciColor(ci);
    instances.push(new Cesium.GeometryInstance({
      geometry: new Cesium.GroundPolylineGeometry({
        positions: Cesium.Cartesian3.fromDegreesArray([lo0, la0, lo1, la1]),
        width: ci >= 2 ? 4.5 : 3.2,
      }),
      attributes: { color: Cesium.ColorGeometryInstanceAttribute.fromColor(new Cesium.Color(r / 255, g / 255, b / 255, 0.92)) },
    }));
    if (ci >= 2.0) {
      const h = Math.min(700, (ci - 1.8) * 420);
      walls.push(new Cesium.GeometryInstance({
        geometry: new Cesium.WallGeometry({
          positions: Cesium.Cartesian3.fromDegreesArray([lo0, la0, lo1, la1]),
          minimumHeights: [base, base],
          maximumHeights: [base + h, base + h],
        }),
        attributes: { color: Cesium.ColorGeometryInstanceAttribute.fromColor(new Cesium.Color(r / 255, g / 255, b / 255, 0.3)) },
      }));
    }
  }
  if (!instances.length) return;
  state.congestionPrim = scene.groundPrimitives.add(new Cesium.GroundPolylinePrimitive({
    geometryInstances: instances,
    appearance: new Cesium.PolylineColorAppearance(),
    classificationType: Cesium.ClassificationType.BOTH,
    asynchronous: true,
  }));
  state.congestionPrim.show = state.mode === 'congestion';
  if (walls.length) {
    state.congestionWalls = scene.primitives.add(new Cesium.Primitive({
      geometryInstances: walls,
      appearance: new Cesium.PerInstanceColorAppearance({ translucent: true, flat: true }),
      asynchronous: true,
    }));
    state.congestionWalls.show = state.mode === 'congestion' && state.cgExtrude;
  }
}

function renderSpark(speeds) {
  const box = $('#cg-spark');
  if (!speeds.length) { box.innerHTML = ''; return; }
  const max = Math.max(...speeds); const min = Math.min(...speeds);
  box.innerHTML = speeds.map((v, h) => {
    const pct = 18 + ((v - min) / Math.max(max - min, 0.1)) * 82;
    return `<div class="spark-bar${h === state.cgHour ? ' active' : ''}" data-h="${h}" style="height:${pct}%" title="${String(h).padStart(2, '0')}:00 · ${v} km/h"></div>`;
  }).join('');
  if (!box.nextElementSibling || !box.nextElementSibling.classList.contains('spark-axis')) {
    box.insertAdjacentHTML('afterend', '<div class="spark-axis"><span>00</span><span>06</span><span>12</span><span>18</span><span>23</span></div>');
  }
  box.querySelectorAll('.spark-bar').forEach((b) => b.addEventListener('click', () => { state.cgHour = Number(b.dataset.h); updateClock(); loadCongestion(); }));
}

/* ── VALIDATION ──────────────────────────────────────────── */
async function loadValidation() {
  const body = $('#validation-body');
  let d;
  try {
    d = await fetchJson('/api/v1/validation/summary');
  } catch (err) {
    body.innerHTML = `<div class="notice error"><strong>Couldn't load validation results.</strong> ${esc(err.message)}</div>`;
    return;
  }
  if (d.status !== 'OK') {
    body.innerHTML = `<div class="notice warn"><strong>Validation has not been run yet.</strong><br>Build the model and score it on held-out days:<br><code>python scripts/build_traffic_model.py all</code><br>Results appear here; no number on this page is typed by hand.</div>`;
    return;
  }
  const o = d.overall;
  const rows = [
    ['PULSE model', o.pulse, ''],
    ['Flat avg speed', o.flat_speed, 'base'],
    ['GTFS timetable', o.timetable, 'base'],
  ];
  const g = d.google || {};
  const maxMae = Math.max(...rows.map((r) => r[1]?.mae_min || 0), 1);
  const bars = rows.map(([name, m, cls]) => (m && m.n ? `
    <div class="v-bar-row"><span>${name}</span>
      <div class="v-bar-track"><div class="v-bar-fill ${cls}" style="width:${(m.mae_min / maxMae) * 100}%"></div></div>
      <span class="v-num">${m.mae_min} min</span></div>` : `
    <div class="v-bar-row"><span>${name}</span><div class="v-bar-track"></div><span class="v-num muted">n/a</span></div>`)).join('');
  const bands = Object.entries(d.by_time_band || {}).map(([k, v]) => `
    <tr><td>${esc(k)}</td><td class="num">${(v.pulse.n || 0).toLocaleString()}</td><td class="num">${v.pulse.mae_min ?? '–'}</td><td class="num">${v.flat_speed.mae_min ?? '–'}</td><td class="num">${v.timetable.mae_min ?? '–'}</td></tr>`).join('');
  const ex = (d.examples || []).slice(0, 8).map((e) => `
    <tr><td>${esc(e.route_id)}</td><td>${esc(e.depart_ist)}</td><td class="num">${e.distance_km}</td><td class="num">${e.actual_min}</td><td class="num">${e.pulse_min}</td><td class="num">${e.timetable_min ?? '–'}</td></tr>`).join('');
  const googleBlock = g.status === 'OK'
    ? `<div class="card-label">PULSE vs Google Maps (door to door)</div>
       <div class="stat-grid">
         <div class="stat"><span class="stat-label">Mean |diff|</span><span class="stat-value">${g.mean_abs_diff_min} min</span><span class="stat-sub">${g.n_comparable} comparable queries</span></div>
         <div class="stat"><span class="stat-label">Within ±20%</span><span class="stat-value">${g.within_20pct_of_google_pct}%</span><span class="stat-sub">median ratio ${g.median_ratio_pulse_over_google}×</span></div>
       </div>
       <p class="small muted">${g.google_unavailable} queries had no Google bus route and are excluded, not guessed. Run ${esc(String(g.generated_at || '').slice(0, 10))}.</p>`
    : '<div class="notice small"><strong>Google Maps comparison not run.</strong> <code>scripts/compare_google.py</code> queries the Google Routes API (transit) with your key; until then this column stays empty instead of showing a guess.</div>';
  body.innerHTML = `
    <div class="stat-grid">
      <div class="stat"><span class="stat-label">PULSE MAE</span><span class="stat-value">${o.pulse.mae_min} min</span><span class="stat-sub">median ${o.pulse.median_abs_err_min} min</span></div>
      <div class="stat"><span class="stat-label">Within ±20%</span><span class="stat-value">${o.pulse.within_20pct_pct}%</span><span class="stat-sub">±5 min: ${o.pulse.within_5min_pct}%</span></div>
      <div class="stat"><span class="stat-label">Held-out runs</span><span class="stat-value">${d.n_runs.toLocaleString()}</span><span class="stat-sub">days ${d.method.test_days[0]}–${d.method.test_days.at(-1)} Oct</span></div>
      <div class="stat"><span class="stat-label">Range hit rate</span><span class="stat-value">${o.pulse.interval_coverage_pct ?? '–'}%</span><span class="stat-sub">actual inside predicted range</span></div>
    </div>
    <div class="card-label">Mean absolute error (lower is better)</div>
    <div class="v-bars">${bars}</div>
    <p class="small muted">Timetable matched ${d.timetable_match_pct}% of runs; on those same runs PULSE MAE is ${o.pulse_on_timetable_subset.mae_min ?? '–'} min. Bias ${o.pulse.bias_min > 0 ? '+' : ''}${o.pulse.bias_min} min.</p>
    <div class="card-label" style="margin-top:14px">By time of day · MAE (min)</div>
    <table class="v-table"><thead><tr><th>Band</th><th>Runs</th><th>PULSE</th><th>Flat</th><th>Timetable</th></tr></thead><tbody>${bands}</tbody></table>
    <div class="card-label">Sample held-out runs (min)</div>
    <table class="v-table"><thead><tr><th>Route</th><th>Dep</th><th>km</th><th>Actual</th><th>PULSE</th><th>Sched</th></tr></thead><tbody>${ex}</tbody></table>
    ${googleBlock}
    <p class="small muted" style="margin-top:10px">Model trained on days ${d.method.train_days?.[0]}–${d.method.train_days?.at(-1)}; ${d.method.model_coverage_measured_cells_pct}% of stretch×time cells are direct measurements. Full method in <code>docs/VALIDATION_REPORT.md</code>.</p>`;
}

/* ── SYSTEM ──────────────────────────────────────────────── */
async function loadSystem() {
  try {
    const s = await fetchJson('/api/v1/system/status');
    const h = s.datasets?.historical_sqlite;
    $('#sys-gps').textContent = h ? `${h.database_count}/${h.expected_count} days` : '–';
    $('#sys-gtfs').textContent = s.datasets?.static_gtfs ? `${s.datasets.static_gtfs.file_count} files` : '–';
    $('#sys-disk').textContent = s.storage ? `${Math.round(s.storage.free_gb)} GB` : '–';
    const feed = s.live_feed?.status || '–';
    $('#sys-feed').textContent = feed === 'ACTIVE' ? 'ACTIVE' : 'OFF';
    $('#sys-feed').className = `stat-value ${feed === 'ACTIVE' ? 'fresh' : 'aging'}`;
    const m = s.traffic_model || {};
    let el = $('#sys-model');
    if (!el) {
      $('#system-stats').insertAdjacentHTML('beforeend', `
        <div class="stat" style="grid-column:1/-1"><span class="stat-label">Traffic model</span><span class="stat-value small" id="sys-model"></span><span class="stat-sub" id="sys-model-sub"></span></div>`);
      el = $('#sys-model');
    }
    if (m.status === 'READY') {
      el.textContent = `${(m.segments || 0).toLocaleString()} stretches · ${m.cells_measured_pct}% cells measured`;
      $('#sys-model-sub').textContent = `Trained on days ${m.train_days?.[0]}–${m.train_days?.at(-1)} Oct · built ${String(m.built_at || '').slice(0, 16).replace('T', ' ')} UTC`;
    } else {
      el.textContent = 'Not trained';
      $('#sys-model-sub').textContent = 'python scripts/build_traffic_model.py all';
    }
  } catch (err) {
    toast(`System status unavailable: ${err.message}`);
  }
}
