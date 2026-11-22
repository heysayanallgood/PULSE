/**
 * PULSE — Interactive Client Application (frontend/static/js/app.js)
 * Delhi DTC Bus Spatiotemporal Engine & Multi-Criteria Journey Planner
 * Upgraded with Light & Satellite Maps, Rapido-style 2D Bus SVGs,
 * Marker Clustering, Debounced Delhi Stop Search & Real GTFS Shape Polylines.
 */

// Application State
const state = {
  currentView: 'journey',
  map: null,
  routeLayer: null,
  clusterGroup: null,
  busMarkers: new Map(), // vehicle_id -> L.Marker
  originPinMarker: null,
  destPinMarker: null,
  pickMode: null, // 'origin' | 'dest' | null
  pollTimer: null,
  selectedOption: null,
  _osmFallbackAdded: false
};

// Initialize Application on DOM Ready
document.addEventListener('DOMContentLoaded', () => {
  initMap();
  initNavigation();
  initAutocomplete();
  initMapPickMode();
  initJourneyForm();
  initTimeMachine();
  loadCommandStatus();
});

// ==========================================
// 1. LEAFLET MAP INITIALIZATION & BASEMAPS
// ==========================================
function initMap() {
  // Center on Central Delhi (Connaught Place)
  state.map = L.map('map-element', {
    zoomControl: false
  }).setView([28.6250, 77.2200], 12);

  L.control.zoom({ position: 'bottomright' }).addTo(state.map);

  // Retrieve injected client configurations
  const cartoKey = (window.PULSE_CONFIG && window.PULSE_CONFIG.cartoApiKey) 
    ? window.PULSE_CONFIG.cartoApiKey.trim() 
    : 'cb1_5d19_1_258c3b9d8e04bf2290f574b2';
  const maptilerKey = (window.PULSE_CONFIG && window.PULSE_CONFIG.maptilerApiKey) 
    ? window.PULSE_CONFIG.maptilerApiKey.trim() 
    : '';

  const cartoAttr = '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions" target="_blank">CARTO</a>';
  const osmAttr = '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a> contributors';
  const esriAttr = 'Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community';

  // Base Layers
  // 1. CARTO Positron (Default Light & Realistic Street Map)
  const positronUrl = cartoKey 
    ? `https://{s}.basemaps.cartocdn.com/rastertiles/light_all/{z}/{x}/{y}.png?key=${encodeURIComponent(cartoKey)}`
    : 'https://{s}.basemaps.cartocdn.com/rastertiles/light_all/{z}/{x}/{y}.png';
  const positronLayer = L.tileLayer(positronUrl, { attribution: cartoAttr, subdomains: 'abcd', maxZoom: 19 });

  // 2. CARTO Voyager (Detailed Clean Street Map)
  const voyagerUrl = cartoKey 
    ? `https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png?key=${encodeURIComponent(cartoKey)}`
    : 'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png';
  const voyagerLayer = L.tileLayer(voyagerUrl, { attribution: cartoAttr, subdomains: 'abcd', maxZoom: 19 });

  // 3. CARTO Dark Matter (High-contrast Dark)
  const darkUrl = cartoKey 
    ? `https://{s}.basemaps.cartocdn.com/rastertiles/dark_all/{z}/{x}/{y}.png?key=${encodeURIComponent(cartoKey)}`
    : 'https://{s}.basemaps.cartocdn.com/rastertiles/dark_all/{z}/{x}/{y}.png';
  const darkLayer = L.tileLayer(darkUrl, { attribution: cartoAttr, subdomains: 'abcd', maxZoom: 19 });

  // 4. Satellite Imagery (MapTiler if configured, else Esri World Imagery fallback)
  const satelliteUrl = maptilerKey 
    ? `https://api.maptiler.com/maps/satellite/{z}/{x}/{y}.jpg?key=${encodeURIComponent(maptilerKey)}`
    : 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';
  const satelliteLayer = L.tileLayer(satelliteUrl, { 
    attribution: maptilerKey ? '&copy; <a href="https://www.maptiler.com/copyright/" target="_blank">MapTiler</a>' : esriAttr, 
    maxZoom: 19 
  });

  // 5. OpenStreetMap Standard
  const osmLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: osmAttr, maxZoom: 19 });

  // Add default layer: Positron (Light)
  positronLayer.addTo(state.map);

  // Layer Switcher Control
  const baseMaps = {
    "☀️ Street (Positron)": positronLayer,
    "🧭 Voyager (Detailed)": voyagerLayer,
    "🌙 Dark Matter": darkLayer,
    "🛰️ Satellite Imagery": satelliteLayer,
    "🗺️ OpenStreetMap": osmLayer
  };
  L.control.layers(baseMaps, null, { position: 'topright', collapsed: true }).addTo(state.map);

  // Overlay Feature Groups
  state.routeLayer = L.featureGroup().addTo(state.map);

  // Marker Cluster Group for Live DTC Buses
  if (typeof L.markerClusterGroup === 'function') {
    state.clusterGroup = L.markerClusterGroup({
      disableClusteringAtZoom: 14, // individual bus icons with bearings at zoom >= 14
      maxClusterRadius: 50,
      spiderfyOnMaxZoom: true,
      showCoverageOnHover: false,
      zoomToBoundsOnClick: true,
      iconCreateFunction: function (cluster) {
        const count = cluster.getChildCount();
        return L.divIcon({
          html: `<div class="pulse-cluster"><span class="pulse-cluster-inner">${count}</span></div>`,
          className: 'pulse-cluster-wrapper',
          iconSize: [36, 36],
          iconAnchor: [18, 18]
        });
      }
    });
  } else {
    state.clusterGroup = L.featureGroup();
  }
  state.clusterGroup.addTo(state.map);

  // Map Click Listener for Coordinates & Picking
  state.map.on('click', onMapClick);
}

// ==========================================
// 2. RAPIDO-STYLE TOP-DOWN 2D CITY BUS SVG
// ==========================================
function createBusSvg(freshnessState, bearing) {
  const glowColor = freshnessState === 'FRESH' ? '#00e676' : (freshnessState === 'AGING' ? '#ffab00' : '#ff5252');
  const strokeColor = freshnessState === 'FRESH' ? '#00b248' : (freshnessState === 'AGING' ? '#d97706' : '#dc2626');
  const rotation = (typeof bearing === 'number' && !isNaN(bearing)) ? Math.round(bearing) : 0;
  const hasBearing = (typeof bearing === 'number' && !isNaN(bearing) && bearing > 0);

  return `
    <div class="rapido-bus-icon" style="transform: rotate(${rotation}deg);">
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 44" width="24" height="44" shape-rendering="geometricPrecision">
        <defs>
          <filter id="bus-glow-${freshnessState}" x="-25%" y="-25%" width="150%" height="150%">
            <feDropShadow dx="0" dy="1" stdDeviation="2.5" flood-color="${glowColor}" flood-opacity="0.85"/>
          </filter>
        </defs>
        <g filter="url(#bus-glow-${freshnessState})">
          <!-- Main Bus Chassis -->
          <rect x="3" y="4" width="18" height="36" rx="4.5" ry="4.5" fill="#ffffff" stroke="${strokeColor}" stroke-width="1.4"/>
          
          <!-- Directional Headlight Beams (Front) -->
          <polygon points="4,4 6,0.5 8.5,0.5 6.5,4" fill="#fef08a" opacity="${hasBearing ? '0.95' : '0.4'}"/>
          <polygon points="20,4 17.5,0.5 15.5,0.5 17.5,4" fill="#fef08a" opacity="${hasBearing ? '0.95' : '0.4'}"/>
          
          <!-- Front Bumper Color Strip -->
          <rect x="5.5" y="3.2" width="13" height="2.5" rx="1" fill="${glowColor}"/>
          
          <!-- Curved Windshield -->
          <path d="M 4.5 9 Q 12 6.5 19.5 9 L 19 14.5 L 5 14.5 Z" fill="#0f172a"/>
          
          <!-- Mirrors -->
          <rect x="0.8" y="7.5" width="2.2" height="3.5" rx="0.8" fill="#334155"/>
          <rect x="21" y="7.5" width="2.2" height="3.5" rx="0.8" fill="#334155"/>
          
          <!-- Side Windows (Left & Right strips) -->
          <rect x="4.2" y="15.5" width="1.8" height="20" rx="0.6" fill="#334155"/>
          <rect x="18" y="15.5" width="1.8" height="20" rx="0.6" fill="#334155"/>
          
          <!-- Roof Top AC Climate Unit -->
          <rect x="7.5" y="18" width="9" height="11" rx="2" fill="#f8fafc" stroke="#94a3b8" stroke-width="0.8"/>
          <line x1="9" y1="20.5" x2="15" y2="20.5" stroke="#64748b" stroke-width="0.8" stroke-linecap="round"/>
          <line x1="9" y1="23.5" x2="15" y2="23.5" stroke="#64748b" stroke-width="0.8" stroke-linecap="round"/>
          <line x1="9" y1="26.5" x2="15" y2="26.5" stroke="#64748b" stroke-width="0.8" stroke-linecap="round"/>
          
          <!-- Rear Windshield & Taillights -->
          <rect x="5.5" y="37.5" width="13" height="1.8" rx="0.5" fill="#0f172a"/>
          <rect x="3.5" y="37.8" width="2" height="1.6" rx="0.5" fill="#ef4444"/>
          <rect x="18.5" y="37.8" width="2" height="1.6" rx="0.5" fill="#ef4444"/>
        </g>
      </svg>
    </div>
  `;
}

function getBusPopupHtml(b) {
  const freshnessColor = b.freshness === 'FRESH' ? '#00e676' : (b.freshness === 'AGING' ? '#ffab00' : '#ff5252');
  return `
    <div style="font-size: 12px; font-family: var(--font-sans); min-width: 180px; color: #1e293b;">
      <div style="font-weight: 800; font-size: 13px; color: #0f172a; border-bottom: 1px solid #e2e8f0; padding-bottom: 4px; margin-bottom: 6px;">
        🚍 ${b.vehicle_id}
      </div>
      <div><b>Route:</b> ${b.route_id ? 'Route ' + b.route_id : 'DTC Corridor'}</div>
      <div><b>Trip ID:</b> ${b.trip_id || 'N/A'}</div>
      <div><b>Speed:</b> ${b.speed_kmh !== null ? b.speed_kmh + ' km/h' : 'UNKNOWN'}</div>
      <div><b>Freshness:</b> <span style="font-weight: 700; color: ${freshnessColor};">${b.freshness}</span> (${b.age_seconds}s ago)</div>
      <div><b>Matching:</b> ${b.route_id ? 'Matched to GTFS Corridor' : 'Raw AVL Position'}</div>
    </div>
  `;
}

// ==========================================
// 3. LIVE DTC BUS FEED POLLER & CLUSTERING
// ==========================================
async function loadLiveBuses() {
  const countEl = document.getElementById('live-bus-count');
  if (countEl) countEl.innerText = 'Polling Live Feed...';

  try {
    let res = await fetch('/api/v1/vehicles?limit=3000');
    let buses = await res.json();

    // If no buses in cache yet, trigger on-demand refresh
    if (!buses || buses.length === 0) {
      await fetch('/api/v1/vehicles/refresh', { method: 'POST' });
      res = await fetch('/api/v1/vehicles?limit=3000');
      buses = await res.json();
    }

    if (countEl) countEl.innerText = `${buses.length.toLocaleString()} Active Vehicles`;

    const currentFeedIds = new Set();

    // In-place marker update (does not rebuild 2,500 markers from scratch)
    buses.forEach(b => {
      currentFeedIds.add(b.vehicle_id);

      if (state.busMarkers.has(b.vehicle_id)) {
        // Update existing marker
        const marker = state.busMarkers.get(b.vehicle_id);
        marker.setLatLng([b.lat, b.lon]);
        
        // Update SVG icon with bearing & freshness
        const iconHtml = createBusSvg(b.freshness, b.bearing);
        marker.setIcon(L.divIcon({
          html: iconHtml,
          className: 'rapido-bus-marker',
          iconSize: [24, 44],
          iconAnchor: [12, 22],
          popupAnchor: [0, -18]
        }));
        marker.setPopupContent(getBusPopupHtml(b));
      } else {
        // Create new marker
        const iconHtml = createBusSvg(b.freshness, b.bearing);
        const icon = L.divIcon({
          html: iconHtml,
          className: 'rapido-bus-marker',
          iconSize: [24, 44],
          iconAnchor: [12, 22],
          popupAnchor: [0, -18]
        });

        const marker = L.marker([b.lat, b.lon], { icon: icon });
        marker.bindPopup(getBusPopupHtml(b));

        state.clusterGroup.addLayer(marker);
        state.busMarkers.set(b.vehicle_id, marker);
      }
    });

    // Remove expired vehicles no longer in feed
    for (const [vid, marker] of state.busMarkers.entries()) {
      if (!currentFeedIds.has(vid)) {
        state.clusterGroup.removeLayer(marker);
        state.busMarkers.delete(vid);
      }
    }

    // Fit bounds on first load if markers exist
    if (buses.length > 0 && !state._initialLiveFitted) {
      state._initialLiveFitted = true;
      state.map.fitBounds(state.clusterGroup.getBounds(), { padding: [30, 30] });
    }
  } catch (err) {
    console.warn("Live feed poll error:", err);
    if (countEl) countEl.innerText = 'Feed Offline';
  }
}

// ==========================================
// 4. MAP CLICK SELECTION & ARBITRARY COORDS
// ==========================================
function initMapPickMode() {
  const btnPickOrig = document.getElementById('btn-pick-origin');
  const btnPickDest = document.getElementById('btn-pick-dest');
  const btnCancel = document.getElementById('btn-cancel-pick');

  if (btnPickOrig) {
    btnPickOrig.addEventListener('click', () => startPickMode('origin'));
  }
  if (btnPickDest) {
    btnPickDest.addEventListener('click', () => startPickMode('dest'));
  }
  if (btnCancel) {
    btnCancel.addEventListener('click', cancelPickMode);
  }
}

function startPickMode(target) {
  state.pickMode = target;
  const banner = document.getElementById('map-selection-banner');
  const text = document.getElementById('map-selection-text');
  if (banner && text) {
    banner.style.display = 'flex';
    text.innerText = target === 'origin' 
      ? '📍 Click anywhere on the map to set Origin...' 
      : '📍 Click anywhere on the map to set Destination...';
  }
  state.map.getContainer().style.cursor = 'crosshair';
}

function cancelPickMode() {
  state.pickMode = null;
  const banner = document.getElementById('map-selection-banner');
  if (banner) banner.style.display = 'none';
  state.map.getContainer().style.cursor = '';
}

function onMapClick(e) {
  const { lat, lng } = e.latlng;
  const latStr = lat.toFixed(5);
  const lonStr = lng.toFixed(5);
  const coordStr = `${latStr}, ${lonStr}`;

  if (state.pickMode === 'origin') {
    setOrigin(coordStr, lat, lng);
    cancelPickMode();
    return;
  } else if (state.pickMode === 'dest') {
    setDestination(coordStr, lat, lng);
    cancelPickMode();
    return;
  }

  // If not in pick mode, show mini context popup
  if (state.currentView === 'journey') {
    const popupContent = `
      <div class="map-context-popup">
        <div style="font-weight: 700; margin-bottom: 4px;">📍 Selected Location</div>
        <div style="color: #64748b; font-size: 11px; margin-bottom: 8px;">${coordStr}</div>
        <div style="display: flex; gap: 6px;">
          <button onclick="setOrigin('${coordStr}', ${lat}, ${lng}); state.map.closePopup();" class="btn-popup btn-popup-green">🟢 Set Origin</button>
          <button onclick="setDestination('${coordStr}', ${lat}, ${lng}); state.map.closePopup();" class="btn-popup btn-popup-red">🔴 Set Destination</button>
        </div>
      </div>
    `;
    L.popup().setLatLng(e.latlng).setContent(popupContent).openOn(state.map);
  }
}

window.setOrigin = function(name, lat, lon) {
  const input = document.getElementById('input-origin');
  if (input) input.value = name;

  if (state.originPinMarker) state.routeLayer.removeLayer(state.originPinMarker);
  if (typeof lat === 'number' && typeof lon === 'number') {
    state.originPinMarker = L.circleMarker([lat, lon], {
      radius: 8,
      color: '#00e676',
      fillColor: '#00e676',
      fillOpacity: 0.9,
      weight: 2
    }).bindPopup(`<b>Origin:</b> ${name}`).addTo(state.routeLayer);
  }
};

window.setDestination = function(name, lat, lon) {
  const input = document.getElementById('input-dest');
  if (input) input.value = name;

  if (state.destPinMarker) state.routeLayer.removeLayer(state.destPinMarker);
  if (typeof lat === 'number' && typeof lon === 'number') {
    state.destPinMarker = L.circleMarker([lat, lon], {
      radius: 8,
      color: '#ff1744',
      fillColor: '#ff1744',
      fillOpacity: 0.9,
      weight: 2
    }).bindPopup(`<b>Destination:</b> ${name}`).addTo(state.routeLayer);
  }
};

// ==========================================
// 5. AUTOCOMPLETE FOR ALL DELHI STOPS & PLACES
// ==========================================
function initAutocomplete() {
  setupAutocomplete('input-origin', 'origin-suggestions', (item) => {
    setOrigin(item.name, item.lat, item.lon);
  });
  setupAutocomplete('input-dest', 'dest-suggestions', (item) => {
    setDestination(item.name, item.lat, item.lon);
  });
}

function setupAutocomplete(inputId, dropdownId, onSelect) {
  const input = document.getElementById(inputId);
  const dropdown = document.getElementById(dropdownId);
  if (!input || !dropdown) return;

  let debounceTimer = null;

  input.addEventListener('input', () => {
    const val = input.value.trim();
    clearTimeout(debounceTimer);

    if (val.length < 2) {
      dropdown.style.display = 'none';
      dropdown.innerHTML = '';
      return;
    }

    debounceTimer = setTimeout(async () => {
      try {
        const res = await fetch(`/api/v1/places/autocomplete?q=${encodeURIComponent(val)}&limit=8`);
        const data = await res.json();
        renderSuggestions(dropdown, data.suggestions || [], onSelect);
      } catch (err) {
        console.warn("Autocomplete error:", err);
      }
    }, 220);
  });

  // Close dropdown when clicking outside
  document.addEventListener('click', (e) => {
    if (!input.contains(e.target) && !dropdown.contains(e.target)) {
      dropdown.style.display = 'none';
    }
  });

  input.addEventListener('focus', () => {
    if (dropdown.children.length > 0 && input.value.trim().length >= 2) {
      dropdown.style.display = 'block';
    }
  });
}

function renderSuggestions(dropdown, items, onSelect) {
  dropdown.innerHTML = '';
  if (!items || items.length === 0) {
    dropdown.style.display = 'none';
    return;
  }

  items.forEach(item => {
    const div = document.createElement('div');
    div.className = 'suggestion-item';

    const icon = item.type === 'STOP' ? '🚏' : (item.type === 'COORDINATE' ? '🌐' : '📍');
    const badgeText = item.type === 'STOP' ? 'DTC STOP' : (item.type === 'COORDINATE' ? 'COORDINATES' : 'PLACE');

    div.innerHTML = `
      <div class="suggestion-icon">${icon}</div>
      <div class="suggestion-content">
        <div class="suggestion-name">${item.name}</div>
        <div class="suggestion-sub">${item.formatted_address || ''}</div>
      </div>
      <div class="suggestion-badge">${badgeText}</div>
    `;

    div.addEventListener('click', () => {
      onSelect(item);
      dropdown.style.display = 'none';
    });

    dropdown.appendChild(div);
  });

  dropdown.style.display = 'block';
}

// ==========================================
// 6. NAVIGATION TABS & VIEW SWITCHER
// ==========================================
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

  cancelPickMode();

  // Handle map layer visibility between views
  if (viewName === 'journey') {
    if (state.map && !state.map.hasLayer(state.routeLayer)) {
      state.map.addLayer(state.routeLayer);
    }
    if (state.map && state.map.hasLayer(state.clusterGroup)) {
      state.map.removeLayer(state.clusterGroup);
    }
    if (state.pollTimer) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
    }
  } else if (viewName === 'live') {
    if (state.map && !state.map.hasLayer(state.clusterGroup)) {
      state.map.addLayer(state.clusterGroup);
    }
    if (state.map && state.map.hasLayer(state.routeLayer)) {
      state.map.removeLayer(state.routeLayer);
    }
    loadLiveBuses();
    if (!state.pollTimer) {
      state.pollTimer = setInterval(loadLiveBuses, 30000);
    }
  } else {
    // Hidden on full-screen views
    if (state.pollTimer) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
    }
    if (viewName === 'validation') {
      loadValidationLab();
    } else if (viewName === 'command') {
      loadCommandStatus();
    }
  }

  // Handle Map Resizing
  setTimeout(() => {
    if (state.map) state.map.invalidateSize();
  }, 200);
}

// ==========================================
// 7. JOURNEY PLANNER & TRUE GTFS SHAPE DRAWING
// ==========================================
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
  }, 500);
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
        <p style="font-size: 11px; margin-top: 4px;">Try searching for major stops like "Kashmere Gate", "Nehru Place", or enter coordinates.</p>
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

    const provBadgeClass = opt.provenance === 'LIVE' ? 'badge-live' : (opt.provenance === 'HISTORICAL' ? 'badge-historical' : 'badge-fallback');
    const confBadgeClass = opt.confidence === 'HIGH' ? 'badge-high' : 'badge-fallback';

    card.innerHTML = `
      <div class="journey-header">
        <div>
          <span class="journey-time">${opt.total_duration_minutes}</span>
          <span class="journey-time-unit">min</span>
        </div>
        <div style="display: flex; gap: 6px;">
          <span class="badge ${provBadgeClass}">${opt.provenance}</span>
          <span class="badge ${confBadgeClass}">${opt.confidence} CONFIDENCE</span>
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
  const allBounds = [];

  const routeColors = ['#0284c7', '#7c3aed', '#059669']; // Vibrant contrast colors for bus legs
  let busLegIndex = 0;

  option.legs.forEach(leg => {
    if (leg.type === 'WALK') {
      // Dashed walking path
      if (leg.geometry && leg.geometry.length >= 2) {
        const poly = L.polyline(leg.geometry, {
          color: '#64748b',
          weight: 3.5,
          dashArray: '6, 8',
          opacity: 0.85
        }).addTo(state.routeLayer);
        poly.bindPopup(`<b>Walking Leg:</b> ${leg.instruction} (${leg.duration_minutes}m)`);
        allBounds.push(...leg.geometry);
      }
    } else if (leg.type === 'BUS') {
      const color = routeColors[busLegIndex % routeColors.length];
      busLegIndex++;

      // Authentic GTFS Road Geometry
      if (leg.geometry && leg.geometry.length >= 2) {
        const poly = L.polyline(leg.geometry, {
          color: color,
          weight: 5.5,
          opacity: 0.95
        }).addTo(state.routeLayer);

        poly.bindPopup(`
          <div style="font-size: 12px; font-family: var(--font-sans);">
            <b>Route:</b> ${leg.route_name}<br/>
            <b>From:</b> ${leg.boarding_stop}<br/>
            <b>To:</b> ${leg.alighting_stop}<br/>
            <b>Duration:</b> ${leg.predicted_duration_minutes} min (${leg.distance_km} km)<br/>
            <b>Stops Traversed:</b> ${leg.stops_traversed} stops
          </div>
        `);
        allBounds.push(...leg.geometry);
      }

      // Boarding Stop Marker
      if (leg.boarding_lat && leg.boarding_lon) {
        L.circleMarker([leg.boarding_lat, leg.boarding_lon], {
          radius: 7,
          color: '#00e676',
          fillColor: '#ffffff',
          fillOpacity: 1.0,
          weight: 3
        }).bindPopup(`<b>Boarding Stop:</b> ${leg.boarding_stop} (Route ${leg.route_name})`).addTo(state.routeLayer);
        allBounds.push([leg.boarding_lat, leg.boarding_lon]);
      }

      // Alighting Stop Marker
      if (leg.alighting_lat && leg.alighting_lon) {
        L.circleMarker([leg.alighting_lat, leg.alighting_lon], {
          radius: 7,
          color: '#ff1744',
          fillColor: '#ffffff',
          fillOpacity: 1.0,
          weight: 3
        }).bindPopup(`<b>Alighting Stop:</b> ${leg.alighting_stop}`).addTo(state.routeLayer);
        allBounds.push([leg.alighting_lat, leg.alighting_lon]);
      }
    } else if (leg.type === 'TRANSFER') {
      if (leg.transfer_lat && leg.transfer_lon) {
        L.circleMarker([leg.transfer_lat, leg.transfer_lon], {
          radius: 8,
          color: '#ffab00',
          fillColor: '#ffffff',
          fillOpacity: 1.0,
          weight: 3
        }).bindPopup(`<b>Transfer Hub:</b> ${leg.transfer_stop}<br/>${leg.instruction}`).addTo(state.routeLayer);
        allBounds.push([leg.transfer_lat, leg.transfer_lon]);
      }
    }
  });

  if (allBounds.length > 0) {
    state.map.fitBounds(L.latLngBounds(allBounds), { padding: [50, 50] });
  }
}

// ==========================================
// 8. TRAFFIC TIME MACHINE
// ==========================================
function initTimeMachine() {
  const slider = document.getElementById('time-machine-slider');
  const clockDisplay = document.getElementById('tm-clock-display');
  const durationDisplay = document.getElementById('tm-duration-display');
  const speedDisplay = document.getElementById('tm-speed-display');

  if (!slider) return;

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

// ==========================================
// 9. VALIDATION LABORATORY
// ==========================================
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

// ==========================================
// 10. COMMAND CENTER STATUS
// ==========================================
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
