/**
 * PULSE — Interactive Client Application (frontend/static/js/app.js)
 * Delhi DTC Bus Spatiotemporal Engine & Multi-Criteria Journey Planner
 */

// Application State
const state = {
  currentView: 'journey',
  map: null,
  routeLayer: null,
  busLayer: null,
  selectedOption: null,
  liveBuses: [],
  pollTimer: null
};

// Initialize Application
document.addEventListener('DOMContentLoaded', () => {
  initMap();
  initNavigation();
  initJourneyForm();
  initTimeMachine();
  loadCommandStatus();
});

// 1. Leaflet Map Initialization
function initMap() {
  // Center on Central Delhi (Connaught Place)
  state.map = L.map('map-element', {
    zoomControl: false
  }).setView([28.6250, 77.2200], 12);

  L.control.zoom({ position: 'bottomright' }).addTo(state.map);

  // CartoDB Dark Matter tile layer for high-contrast dark theme
  L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
    subdomains: 'abcd',
    maxZoom: 19
  }).addTo(state.map);

  state.routeLayer = L.featureGroup().addTo(state.map);
  state.busLayer = L.featureGroup().addTo(state.map);
}

// 2. Navigation Tabs
function initNavigation() {
  const tabs = document.querySelectorAll('.nav-tab');
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      const targetView = tab.dataset.view;
      switchView(targetView);
    });
  });
}

function switchView(viewName) {
  state.currentView = viewName;
  document.querySelectorAll('.nav-tab').forEach(t => {
    t.classList.toggle('active', t.dataset.view === viewName);
  });
  document.querySelectorAll('.view-pane').forEach(p => {
    p.classList.toggle('active', p.id === `view-${viewName}`);
  });

  // Handle Map Resizing & Specific Views
  setTimeout(() => {
    if (state.map) state.map.invalidateSize();
  }, 200);

  if (viewName === 'live') {
    loadLiveBuses();
  } else if (viewName === 'validation') {
    loadValidationLab();
  } else if (viewName === 'command') {
    loadCommandStatus();
  }
}

// 3. Journey Planner Form & Engine Call
function initJourneyForm() {
  const form = document.getElementById('journey-form');
  const swapBtn = document.getElementById('swap-locations-btn');
  const origInput = document.getElementById('input-origin');
  const destInput = document.getElementById('input-dest');
  const timeInput = document.getElementById('input-time');

  // Preset time buttons
  document.querySelectorAll('.preset-pill').forEach(pill => {
    pill.addEventListener('click', () => {
      document.querySelectorAll('.preset-pill').forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
      timeInput.value = pill.dataset.time;
    });
  });

  if (swapBtn) {
    swapBtn.addEventListener('click', () => {
      const tmp = origInput.value;
      origInput.value = destInput.value;
      destInput.value = tmp;
    });
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const from = origInput.value.trim();
    const to = destInput.value.trim();
    const timeVal = timeInput.value.trim();

    if (!from || !to) return;

    showLoadingState(true);
    try {
      const url = `/api/v1/journeys?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}&depart_at=${encodeURIComponent(timeVal)}`;
      const res = await fetch(url);
      const data = await res.json();
      renderJourneyResults(data);
    } catch (err) {
      alert("Error calculating journeys: " + err.message);
    } finally {
      showLoadingState(false);
    }
  });

  // Auto trigger default search for Kashmere Gate to Nehru Place
  setTimeout(() => {
    form.dispatchEvent(new Event('submit'));
  }, 600);
}

function showLoadingState(isLoading) {
  const btn = document.getElementById('plan-submit-btn');
  if (isLoading) {
    btn.innerHTML = '<span class="pulse-dot"></span> Calculating Model Travel Times...';
    btn.disabled = true;
  } else {
    btn.innerHTML = '<span>⚡</span> Plan Optimal Journey';
    btn.disabled = false;
  }
}

function renderJourneyResults(data) {
  const container = document.getElementById('journey-results-list');
  container.innerHTML = '';
  state.routeLayer.clearLayers();

  if (data.status !== 'SUCCESS' || !data.options || data.options.length === 0) {
    container.innerHTML = `
      <div class="empty-state" style="padding: 24px; text-align: center; color: var(--text-muted);">
        <p>No bus connection found for this query.</p>
        <p style="font-size: 11px; margin-top: 4px;">Try searching for major stops like "Kashmere Gate", "Nehru Place", or "Connaught Place".</p>
      </div>
    `;
    return;
  }

  // Render Comparative Intelligence Banner
  if (data.off_peak_comparison) {
    const comp = data.off_peak_comparison;
    const banner = document.createElement('div');
    banner.className = 'comparative-banner';
    banner.innerHTML = `
      <div class="banner-icon">💡</div>
      <div class="banner-text">
        <h4>Spatiotemporal Traffic Insight</h4>
        <p>${comp.insight} (Travel time drops from <strong>${comp.peak_duration_minutes}m</strong> to <strong>${comp.off_peak_duration_minutes}m</strong>).</p>
      </div>
    `;
    container.appendChild(banner);
  }

  // Render Journey Cards
  data.options.forEach((opt, idx) => {
    const card = document.createElement('div');
    card.className = `journey-card ${idx === 0 ? 'selected' : ''}`;
    
    let legSummaryHtml = '';
    opt.legs.forEach(leg => {
      if (leg.type === 'BUS') {
        legSummaryHtml += `
          <div class="timeline-leg">
            <span class="timeline-dot bus"></span>
            <span>Take <strong>${leg.route_name}</strong> to <em>${leg.alighting_stop}</em> (${leg.predicted_duration_minutes}m)</span>
          </div>
        `;
      } else if (leg.type === 'TRANSFER') {
        legSummaryHtml += `
          <div class="timeline-leg">
            <span class="timeline-dot xfer"></span>
            <span style="color: var(--accent-saffron);">${leg.instruction}</span>
          </div>
        `;
      } else if (leg.type === 'WALK') {
        legSummaryHtml += `
          <div class="timeline-leg">
            <span class="timeline-dot"></span>
            <span>${leg.instruction} (${leg.duration_minutes}m)</span>
          </div>
        `;
      }
    });

    card.innerHTML = `
      <div class="card-header-row">
        <div class="time-total">
          ${opt.total_duration_minutes} <span>min</span>
        </div>
        <div class="badges-row">
          <span class="badge badge-historical">${opt.provenance}</span>
          <span class="badge badge-high">${opt.confidence} CONFIDENCE</span>
        </div>
      </div>
      
      <div class="metrics-strip">
        <div class="metric-item">
          <span class="metric-label">In-Vehicle</span>
          <span class="metric-value">${opt.in_vehicle_minutes}m</span>
        </div>
        <div class="metric-item">
          <span class="metric-label">Walking</span>
          <span class="metric-value">${opt.walking_minutes}m</span>
        </div>
        <div class="metric-item">
          <span class="metric-label">Transfers</span>
          <span class="metric-value">${opt.transfers}</span>
        </div>
      </div>

      <div class="legs-timeline">
        ${legSummaryHtml}
      </div>
    `;

    card.addEventListener('click', () => {
      document.querySelectorAll('.journey-card').forEach(c => c.classList.remove('selected'));
      card.classList.add('selected');
      highlightJourneyOnMap(opt);
    });

    container.appendChild(card);
  });

  // Highlight first option by default
  highlightJourneyOnMap(data.options[0]);
}

function highlightJourneyOnMap(option) {
  state.routeLayer.clearLayers();
  
  // Plot Delhi bus stops and legs
  const points = [];
  option.legs.forEach(leg => {
    if (leg.type === 'BUS') {
      // Create mock representative line along corridor
      // Connect boarding stop to alighting stop
      const origCoords = [28.6675, 77.2281]; // Kashmere Gate
      const destCoords = [28.5492, 77.2526]; // Nehru Place
      
      const poly = L.polyline([origCoords, [28.6300, 77.2300], [28.5800, 77.2400], destCoords], {
        color: '#00e5ff',
        weight: 5,
        opacity: 0.85
      }).addTo(state.routeLayer);
      
      L.circleMarker(origCoords, { radius: 6, color: '#00e676', fillColor: '#000', fillOpacity: 0.8 }).bindPopup(`<b>Boarding:</b> ${leg.boarding_stop}`).addTo(state.routeLayer);
      L.circleMarker(destCoords, { radius: 6, color: '#ff1744', fillColor: '#000', fillOpacity: 0.8 }).bindPopup(`<b>Alighting:</b> ${leg.alighting_stop}`).addTo(state.routeLayer);

      points.push(origCoords, destCoords);
    }
  });

  if (points.length > 0) {
    state.map.fitBounds(state.routeLayer.getBounds(), { padding: [40, 40] });
  }
}

// 4. Live DTC Bus Map
async function loadLiveBuses() {
  state.busLayer.clearLayers();
  try {
    const res = await fetch('/api/v1/vehicles?limit=100');
    const buses = await res.json();
    document.getElementById('live-bus-count').innerText = `${buses.length} Active Vehicles`;
    
    buses.forEach(b => {
      const marker = L.circleMarker([b.lat, b.lon], {
        radius: 5,
        color: b.freshness === 'FRESH' ? '#00e676' : '#ffd600',
        fillColor: '#000',
        fillOpacity: 0.8,
        weight: 2
      }).addTo(state.busLayer);

      marker.bindPopup(`
        <div style="font-size: 12px;">
          <b>Bus:</b> ${b.vehicle_id}<br/>
          <b>Route:</b> ${b.route_id || 'DTC Corridor'}<br/>
          <b>Speed:</b> ${b.speed_kmh ? b.speed_kmh + ' km/h' : 'Stationary'}<br/>
          <b>Freshness:</b> <span style="color: #00e676;">${b.freshness}</span> (${b.age_seconds}s ago)
        </div>
      `);
    });

    if (buses.length > 0) {
      state.map.fitBounds(state.busLayer.getBounds(), { padding: [30, 30] });
    }
  } catch (err) {
    console.warn("Live feed offline:", err);
  }
}

// 5. Traffic Time Machine
function initTimeMachine() {
  const slider = document.getElementById('time-machine-slider');
  const clockDisplay = document.getElementById('tm-clock-display');
  const durationDisplay = document.getElementById('tm-duration-display');
  const speedDisplay = document.getElementById('tm-speed-display');

  slider.addEventListener('input', async () => {
    const hour = parseInt(slider.value);
    const timeStr = `${hour.toString().padStart(2, '0')}:00`;
    clockDisplay.innerText = timeStr;

    // Fetch comparison for corridor
    try {
      const res = await fetch(`/api/v1/analytics/time-comparison?route_id=1728&shape_id=shp_3_2436&from_dist=0&to_dist=15000`);
      const comps = await res.json();
      const match = comps.find(c => c.hour === hour) || comps[0];
      
      durationDisplay.innerText = `${match.duration_minutes} min`;
      speedDisplay.innerText = `${match.speed_kmh} km/h`;
      
      const badge = document.getElementById('tm-traffic-badge');
      if (match.speed_kmh <= 14) {
        badge.innerText = 'HEAVY CONGESTION (PEAK)';
        badge.style.color = '#ff1744';
      } else if (match.speed_kmh <= 22) {
        badge.innerText = 'MODERATE TRAFFIC';
        badge.style.color = '#ffd600';
      } else {
        badge.innerText = 'FREE-FLOW TRAFFIC';
        badge.style.color = '#00e676';
      }
    } catch (e) {
      console.warn("Time machine fetch error:", e);
    }
  });

  // Trigger initial value
  slider.dispatchEvent(new Event('input'));
}

// 6. Validation Laboratory
async function loadValidationLab() {
  try {
    const res = await fetch('/api/v1/validation/summary');
    const data = await res.json();
    
    document.getElementById('val-mae-pulse').innerText = `${data.metrics.mae_pulse_minutes}m`;
    document.getElementById('val-mae-tt').innerText = `${data.metrics.mae_timetable_minutes}m`;
    document.getElementById('val-err-reduction').innerText = `-${data.metrics.error_reduction_pct}% Error`;
    document.getElementById('val-accuracy').innerText = `${data.metrics.mean_accuracy_pct}%`;

    const tbody = document.getElementById('val-benchmarks-body');
    tbody.innerHTML = '';
    
    data.benchmarks.forEach(b => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td><strong>${b.corridor}</strong><br/><span style="color: var(--text-muted); font-size: 11px;">${b.departure_time}</span></td>
        <td>${b.distance_km} km</td>
        <td style="color: var(--accent-rose);">${b.static_timetable_minutes} min</td>
        <td style="font-weight: 700;">${b.observed_bus_trip_minutes} min</td>
        <td style="color: var(--accent-cyan); font-weight: 700;">${b.pulse_predicted_minutes} min</td>
        <td>${b.google_maps_bus_minutes} min</td>
        <td><span class="badge badge-high">${b.pulse_accuracy_pct}%</span></td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error("Failed to load validation lab:", err);
  }
}

// 7. Command Center Status
async function loadCommandStatus() {
  try {
    const res = await fetch('/api/v1/system/status');
    const data = await res.json();

    document.getElementById('cmd-drive-free').innerText = `${data.storage.free_gb} GB`;
    document.getElementById('cmd-db-count').innerText = `${data.datasets.historical_sqlite.database_count} / 31 DBs`;
    document.getElementById('cmd-gtfs-stops').innerText = '6,862 Stops';
    document.getElementById('cmd-gtfs-routes').innerText = '2,574 Routes';
    document.getElementById('cmd-live-status').innerText = data.live_feed.status;
  } catch (err) {
    console.warn("Status fetch error:", err);
  }
}
