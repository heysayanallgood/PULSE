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
  baseLayers: {},
  currentBaseLayer: null,
  currentBaseLayerKey: 'positron',
  routeLayer: null,
  originDestLayer: null,
  clusterGroup: null,
  busMarkers: new Map(), // vehicle_id -> L.Marker
  originPinMarker: null,
  destPinMarker: null,
  originCoords: null,
  destCoords: null,
  pickMode: null, // 'origin' | 'destination' | null
  pollTimer: null,
  selectedOption: null,
  activeJourneyId: null,
  searchAbortController: null,
  _initialLiveFitted: false
};
window.state = state;

// Safe JSON fetch wrapper with standardized error handling
async function safeFetchJson(url, options = {}) {
  const res = await fetch(url, options);
  const contentType = res.headers.get('content-type') || '';
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    if (contentType.includes('application/json')) {
      try {
        const errData = await res.json();
        msg = errData?.error?.message || errData?.detail || msg;
      } catch (e) {
        msg = res.statusText || msg;
      }
    } else {
      try {
        const text = await res.text();
        msg = text.slice(0, 100) || msg;
      } catch (e) {
        msg = res.statusText || msg;
      }
    }
    const err = new Error(msg);
    err.status = res.status;
    throw err;
  }
  if (!contentType.includes('application/json')) {
    throw new Error('Unexpected non-JSON response from server');
  }
  return await res.json();
}

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
async function initMap() {
  // Center on Central Delhi (Connaught Place)
  state.map = L.map('map-element', {
    zoomControl: false
  }).setView([28.6250, 77.2200], 12);

  L.control.zoom({ position: 'bottomright' }).addTo(state.map);

  // Retrieve injected client configurations
  let cartoKey = (window.PULSE_CONFIG && window.PULSE_CONFIG.cartoApiKey) 
    ? window.PULSE_CONFIG.cartoApiKey.trim() 
    : 'cb1_5d19_1_258c3b9d8e04bf2290f574b2';
  let maptilerKey = (window.PULSE_CONFIG && window.PULSE_CONFIG.maptilerApiKey) 
    ? window.PULSE_CONFIG.maptilerApiKey.trim() 
    : '';

  try {
    const mapCfg = await safeFetchJson('/api/v1/config/map');
    if (mapCfg.carto_api_key) cartoKey = mapCfg.carto_api_key.trim();
    if (mapCfg.maptiler_api_key) maptilerKey = mapCfg.maptiler_api_key.trim();
  } catch (e) {
    // Fall back to injected bootstrap keys
  }

  const cartoAttr = '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions" target="_blank">CARTO</a>';
  const osmAttr = '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a> contributors';
  const esriAttr = 'Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community';
  const maptilerAttr = '&copy; <a href="https://www.maptiler.com/copyright/" target="_blank">MapTiler</a> &copy; OpenStreetMap contributors';

  // Base Layers
  // 1. CARTO Positron (Default Light Street Map)
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

  // 4a. Satellite Plain (MapTiler Satellite v4 / Esri fallback)
  const satPlainUrl = maptilerKey 
    ? `https://api.maptiler.com/maps/satellite-v4/{z}/{x}/{y}.jpg?key=${encodeURIComponent(maptilerKey)}`
    : 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';
  const satellitePlainLayer = L.tileLayer(satPlainUrl, { 
    attribution: maptilerKey ? maptilerAttr : esriAttr, 
    maxZoom: 20,
    tileSize: maptilerKey ? 512 : 256,
    zoomOffset: maptilerKey ? -1 : 0,
    crossOrigin: true
  });

  // 4b. Satellite Hybrid (MapTiler Hybrid with Road Overlays / Esri fallback)
  const satHybridUrl = maptilerKey 
    ? `https://api.maptiler.com/maps/hybrid-v4/{z}/{x}/{y}.png?key=${encodeURIComponent(maptilerKey)}`
    : 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';
  const satelliteHybridLayer = L.tileLayer(satHybridUrl, { 
    attribution: maptilerKey ? maptilerAttr : esriAttr, 
    maxZoom: 20,
    tileSize: maptilerKey ? 512 : 256,
    zoomOffset: maptilerKey ? -1 : 0,
    crossOrigin: true
  });

  // 5. OpenStreetMap Standard
  const osmLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: osmAttr, maxZoom: 19 });

  // Diagnostic Tile Error Handlers (Section 2.7)
  [positronLayer, voyagerLayer, darkLayer, satellitePlainLayer, satelliteHybridLayer, osmLayer].forEach(layer => {
    layer.on('tileerror', function() {
      const statusDot = document.getElementById('layer-status-indicator');
      if (statusDot) {
        statusDot.className = 'layer-status-dot warning';
        statusDot.title = 'Tile connection warning (fallback active)';
      }
    });
  });

  state.baseLayers = {
    'positron': positronLayer,
    'voyager': voyagerLayer,
    'dark': darkLayer,
    'satellite-plain': satellitePlainLayer,
    'satellite-hybrid': satelliteHybridLayer,
    'osm': osmLayer
  };

  // Add default layer: Positron (Light)
  positronLayer.addTo(state.map);
  state.currentBaseLayer = positronLayer;
  state.currentBaseLayerKey = 'positron';

  // Wire up visible styled Map Style Selector (Section 2.5)
  initCustomLayerSelector(state.baseLayers);

  // Overlay Feature Groups
  state.routeLayer = L.featureGroup().addTo(state.map);
  state.originDestLayer = L.featureGroup().addTo(state.map);

  // Marker Cluster Group for Live DTC Buses
  if (typeof L.markerClusterGroup === 'function') {
    state.clusterGroup = L.markerClusterGroup({
      disableClusteringAtZoom: 13, // individual bus icons with bearings at zoom >= 13
      maxClusterRadius: 45,
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
  // Initially not added to map since default view is Journey Planner

  // Map Click Listener for Coordinates & Picking
  state.map.on('click', onMapClick);
}

function initCustomLayerSelector(baseLayers) {
  const labels = document.querySelectorAll('.layer-radio-item');
  const radios = document.querySelectorAll('input[name="pulse-map-style"]');
  const statusIndicator = document.getElementById('layer-status-indicator');

  function switchLayer(layerKey) {
    if (!baseLayers[layerKey]) return;

    // Remove existing base layers
    Object.values(baseLayers).forEach(layer => {
      if (state.map.hasLayer(layer)) {
        state.map.removeLayer(layer);
      }
    });

    // Add selected layer
    const newLayer = baseLayers[layerKey];
    newLayer.addTo(state.map);
    state.currentBaseLayer = newLayer;
    state.currentBaseLayerKey = layerKey;

    // Update active UI classes
    labels.forEach(lbl => {
      const isMatch = (lbl.dataset.layer === layerKey);
      lbl.classList.toggle('active', isMatch);
      const radio = lbl.querySelector('input[type="radio"]');
      if (radio) radio.checked = isMatch;
    });

    if (statusIndicator) {
      statusIndicator.className = 'layer-status-dot';
      statusIndicator.title = `Active: ${layerKey}`;
    }
  }

  labels.forEach(lbl => {
    lbl.addEventListener('click', (e) => {
      const key = lbl.dataset.layer;
      switchLayer(key);
    });
  });

  radios.forEach(r => {
    r.addEventListener('change', () => {
      switchLayer(r.value);
    });
  });
}

// ==========================================
// 2. RAPIDO-STYLE TOP-DOWN 2D CITY BUS SVG
// ==========================================
function createBusSvg(freshnessState, bearing) {
  const glowColor = freshnessState === 'FRESH' ? '#10B981' : (freshnessState === 'AGING' ? '#F59E0B' : '#EF4444');
  const strokeColor = freshnessState === 'FRESH' ? '#059669' : (freshnessState === 'AGING' ? '#92400E' : '#7F1D1D');
  const highlightColor = freshnessState === 'FRESH' ? '#86EFAC' : (freshnessState === 'AGING' ? '#FDE68A' : '#FCA5A5');
  const rotation = (typeof bearing === 'number' && !isNaN(bearing)) ? Math.round(bearing) : 0;
  const hasBearing = (typeof bearing === 'number' && !isNaN(bearing) && bearing >= 0);

  return `
    <div class="pulse-bus-rotate rapido-bus-icon" style="transform: rotate(${rotation}deg); transform-origin: center center;">
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 120" width="32" height="60" shape-rendering="geometricPrecision">
        <defs>
          <filter id="bus-glow-${freshnessState}" x="-30%" y="-30%" width="160%" height="160%">
            <feDropShadow dx="0" dy="1" stdDeviation="3.0" flood-color="${glowColor}" flood-opacity="0.85"/>
            <feDropShadow dx="0" dy="0" stdDeviation="6.0" flood-color="${glowColor}" flood-opacity="0.45"/>
          </filter>
          <linearGradient id="windshield-grad" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stop-color="#E0F2FE" />
            <stop offset="100%" stop-color="#93C5FD" />
          </linearGradient>
        </defs>
        <g filter="url(#bus-glow-${freshnessState})">
          <!-- 4 Side Wheels -->
          <rect x="2" y="18" width="5" height="18" rx="2" fill="#1e293b"/>
          <rect x="57" y="18" width="5" height="18" rx="2" fill="#1e293b"/>
          <rect x="2" y="84" width="5" height="18" rx="2" fill="#1e293b"/>
          <rect x="57" y="84" width="5" height="18" rx="2" fill="#1e293b"/>

          <!-- Main Bus Chassis -->
          <rect x="6" y="8" width="52" height="104" rx="10" ry="10" fill="#ffffff" stroke="${strokeColor}" stroke-width="2.2"/>
          
          <!-- Directional Headlight Beams (Front) -->
          <polygon points="10,8 14,0 22,0 18,8" fill="#FEF08A" opacity="${hasBearing ? '0.95' : '0.4'}"/>
          <polygon points="54,8 50,0 42,0 46,8" fill="#FEF08A" opacity="${hasBearing ? '0.95' : '0.4'}"/>
          
          <!-- Front Bumper Color Strip -->
          <rect x="14" y="6" width="36" height="5" rx="2" fill="${glowColor}"/>

          <!-- Destination Display Strip -->
          <rect x="16" y="13" width="32" height="6" rx="1.5" fill="#FACC15"/>
          
          <!-- Curved Windshield with Gradient -->
          <path d="M 12 24 Q 32 18 52 24 L 50 38 L 14 38 Z" fill="url(#windshield-grad)" stroke="#38bdf8" stroke-width="0.8"/>
          
          <!-- Side Mirrors -->
          <rect x="0" y="22" width="6" height="9" rx="2" fill="#334155"/>
          <rect x="58" y="22" width="6" height="9" rx="2" fill="#334155"/>
          
          <!-- Side Highlight Stripes -->
          <line x1="8" y1="42" x2="8" y2="94" stroke="${highlightColor}" stroke-width="1.5"/>
          <line x1="56" y1="42" x2="56" y2="94" stroke="${highlightColor}" stroke-width="1.5"/>

          <!-- Side Windows (Left & Right strips) -->
          <rect x="9" y="44" width="4" height="48" rx="1.5" fill="#334155"/>
          <rect x="51" y="44" width="4" height="48" rx="1.5" fill="#334155"/>
          
          <!-- Roof Top AC Climate Unit with Louvers -->
          <rect x="18" y="48" width="28" height="28" rx="4" fill="#f8fafc" stroke="#94a3b8" stroke-width="1.2"/>
          <line x1="22" y1="55" x2="42" y2="55" stroke="#64748b" stroke-width="1.2" stroke-linecap="round"/>
          <line x1="22" y1="62" x2="42" y2="62" stroke="#64748b" stroke-width="1.2" stroke-linecap="round"/>
          <line x1="22" y1="69" x2="42" y2="69" stroke="#64748b" stroke-width="1.2" stroke-linecap="round"/>
          
          <!-- Rear Window & Taillights -->
          <rect x="14" y="98" width="36" height="4" rx="1.5" fill="#0f172a"/>
          <rect x="8" y="104" width="6" height="4" rx="1.5" fill="#EF4444"/>
          <rect x="50" y="104" width="6" height="4" rx="1.5" fill="#EF4444"/>
          <!-- Rear Bumper -->
          <rect x="14" y="110" width="36" height="3" rx="1.5" fill="#1e293b"/>
        </g>
      </svg>
    </div>
  `;
}

function getBusPopupHtml(b) {
  const freshnessColor = b.freshness === 'FRESH' ? '#10B981' : (b.freshness === 'AGING' ? '#F59E0B' : '#EF4444');
  const speedDisplay = (b.speed_kmh !== null && !isNaN(b.speed_kmh)) ? `${b.speed_kmh} km/h` : 'UNKNOWN';
  const bearingDisplay = (b.bearing !== null && !isNaN(b.bearing)) ? `${Math.round(b.bearing)}°` : 'UNKNOWN';
  return `
    <div style="font-size: 12px; font-family: var(--font-sans); min-width: 190px; color: #1e293b;">
      <div style="font-weight: 800; font-size: 13px; color: #0f172a; border-bottom: 1px solid #e2e8f0; padding-bottom: 4px; margin-bottom: 6px;">
        🚍 DTC Bus ${b.vehicle_id}
      </div>
      <div><b>Route:</b> ${b.route_id ? 'Route ' + b.route_id : 'DTC Corridor'}</div>
      <div><b>Trip ID:</b> ${b.trip_id || 'N/A'}</div>
      <div><b>Speed:</b> ${speedDisplay}</div>
      <div><b>Bearing:</b> ${bearingDisplay}</div>
      <div><b>Freshness:</b> <span style="font-weight: 700; color: ${freshnessColor};">${b.freshness}</span> (${b.age_seconds}s ago)</div>
      <div><b>Provenance:</b> <span style="color: #059669; font-weight: 700;">LIVE</span></div>
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
    let buses = await safeFetchJson('/api/v1/vehicles?limit=3000');

    // If no buses in cache yet, trigger on-demand refresh
    if (!buses || buses.length === 0) {
      await fetch('/api/v1/vehicles/refresh', { method: 'POST' });
      buses = await safeFetchJson('/api/v1/vehicles?limit=3000');
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
          className: 'pulse-bus-marker',
          iconSize: [32, 60],
          iconAnchor: [16, 30],
          popupAnchor: [0, -28]
        }));
        marker.setPopupContent(getBusPopupHtml(b));
      } else {
        // Create new marker
        const iconHtml = createBusSvg(b.freshness, b.bearing);
        const icon = L.divIcon({
          html: iconHtml,
          className: 'pulse-bus-marker',
          iconSize: [32, 60],
          iconAnchor: [16, 30],
          popupAnchor: [0, -28]
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
    console.warn("Live feed poll notice:", err.message);
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
    btnPickOrig.addEventListener('click', (e) => {
      e.preventDefault();
      if (state.pickMode === 'origin') cancelPickMode();
      else startPickMode('origin');
    });
  }
  if (btnPickDest) {
    btnPickDest.addEventListener('click', (e) => {
      e.preventDefault();
      if (state.pickMode === 'destination') cancelPickMode();
      else startPickMode('destination');
    });
  }
  if (btnCancel) {
    btnCancel.addEventListener('click', (e) => {
      e.preventDefault();
      cancelPickMode();
    });
  }
}

function startPickMode(target) {
  state.pickMode = target; // 'origin' or 'destination'
  const banner = document.getElementById('map-selection-banner');
  const text = document.getElementById('map-selection-text');
  const btnOrig = document.getElementById('btn-pick-origin');
  const btnDest = document.getElementById('btn-pick-dest');

  if (target === 'origin') {
    if (btnOrig) btnOrig.classList.add('active');
    if (btnDest) btnDest.classList.remove('active');
    if (text) text.innerText = '📍 PICK ORIGIN: Click anywhere on the map to select your starting point.';
  } else {
    if (btnDest) btnDest.classList.add('active');
    if (btnOrig) btnOrig.classList.remove('active');
    if (text) text.innerText = '📍 PICK DESTINATION: Click anywhere on the map to select your destination.';
  }
  if (banner) banner.style.display = 'flex';
  if (state.map) state.map.getContainer().style.cursor = 'crosshair';
}

function cancelPickMode() {
  state.pickMode = null;
  const banner = document.getElementById('map-selection-banner');
  if (banner) banner.style.display = 'none';
  const btnOrig = document.getElementById('btn-pick-origin');
  const btnDest = document.getElementById('btn-pick-dest');
  if (btnOrig) btnOrig.classList.remove('active');
  if (btnDest) btnDest.classList.remove('active');
  if (state.map) state.map.getContainer().style.cursor = '';
}

function onMapClick(e) {
  const { lat, lng } = e.latlng;
  const latNum = parseFloat(lat.toFixed(5));
  const lonNum = parseFloat(lng.toFixed(5));
  const coordStr = `${latNum.toFixed(4)}, ${lonNum.toFixed(4)}`;

  if (state.pickMode === 'origin') {
    setOrigin(coordStr, latNum, lonNum);
    cancelPickMode();
    return;
  } else if (state.pickMode === 'destination' || state.pickMode === 'dest') {
    setDestination(coordStr, latNum, lonNum);
    cancelPickMode();
    return;
  }

  // If not in pick mode, show mini context popup on Journey Planner
  if (state.currentView === 'journey') {
    const popupContent = `
      <div class="map-context-popup">
        <div style="font-weight: 700; margin-bottom: 4px;">📍 Selected Location</div>
        <div style="color: #64748b; font-size: 11px; margin-bottom: 8px;">${coordStr}</div>
        <div style="display: flex; gap: 6px;">
          <button onclick="setOrigin('${coordStr}', ${latNum}, ${lonNum}); state.map.closePopup();" class="btn-popup btn-popup-green">🟢 Set Origin</button>
          <button onclick="setDestination('${coordStr}', ${latNum}, ${lonNum}); state.map.closePopup();" class="btn-popup btn-popup-red">🔴 Set Destination</button>
        </div>
      </div>
    `;
    L.popup().setLatLng(e.latlng).setContent(popupContent).openOn(state.map);
  }
}

window.setOrigin = function(name, lat, lon) {
  const input = document.getElementById('input-origin');
  if (input) input.value = name;
  state.originCoords = { lat, lon, name };

  if (state.originPinMarker) state.originDestLayer.removeLayer(state.originPinMarker);
  if (typeof lat === 'number' && typeof lon === 'number') {
    state.originPinMarker = L.marker([lat, lon], {
      icon: L.divIcon({
        className: 'pulse-pin-marker',
        html: `<div class="pulse-pin pin-origin" title="Selected Origin"><span class="pulse-pin-dot"></span></div>`,
        iconSize: [24, 24],
        iconAnchor: [12, 24],
        popupAnchor: [0, -24]
      })
    }).bindPopup(`<b>Selected Origin:</b><br/>${name}`).addTo(state.originDestLayer);
  }
};

window.setDestination = function(name, lat, lon) {
  const input = document.getElementById('input-dest');
  if (input) input.value = name;
  state.destCoords = { lat, lon, name };

  if (state.destPinMarker) state.originDestLayer.removeLayer(state.destPinMarker);
  if (typeof lat === 'number' && typeof lon === 'number') {
    state.destPinMarker = L.marker([lat, lon], {
      icon: L.divIcon({
        className: 'pulse-pin-marker',
        html: `<div class="pulse-pin pin-dest" title="Selected Destination"><span class="pulse-pin-dot"></span></div>`,
        iconSize: [24, 24],
        iconAnchor: [12, 24],
        popupAnchor: [0, -24]
      })
    }).bindPopup(`<b>Selected Destination:</b><br/>${name}`).addTo(state.originDestLayer);
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
        const data = await safeFetchJson(`/api/v1/places/autocomplete?q=${encodeURIComponent(val)}&limit=8`);
        renderSuggestions(dropdown, data.suggestions || [], onSelect);
      } catch (err) {
        console.warn("Autocomplete notice:", err.message);
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

  input.addEventListener('blur', () => {
    setTimeout(() => {
      dropdown.style.display = 'none';
    }, 250);
  });

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' || e.key === 'Enter') {
      dropdown.style.display = 'none';
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
    if (state.map && !state.map.hasLayer(state.originDestLayer)) {
      state.map.addLayer(state.originDestLayer);
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
    if (state.map && state.map.hasLayer(state.originDestLayer)) {
      state.map.removeLayer(state.originDestLayer);
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

    // Close any open autocomplete suggestion dropdowns
    const origDrop = document.getElementById('origin-suggestions');
    const destDrop = document.getElementById('dest-suggestions');
    if (origDrop) origDrop.style.display = 'none';
    if (destDrop) destDrop.style.display = 'none';

    // Abort previous pending query if active
    if (state.searchAbortController) {
      state.searchAbortController.abort();
    }
    state.searchAbortController = new AbortController();

    // Atomically clear route layer before new query begins
    state.routeLayer.clearLayers();
    showLoadingState(true);

    try {
      const url = `/api/v1/journeys?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}&depart_at=${encodeURIComponent(timeVal)}`;
      const data = await safeFetchJson(url, { signal: state.searchAbortController.signal });
      renderJourneyResults(data);
    } catch (err) {
      if (err.name === 'AbortError') return;
      renderJourneyError(err.message);
    } finally {
      showLoadingState(false);
    }
  });
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

function renderJourneyError(errorMsg) {
  const container = document.getElementById('journey-results-list');
  container.innerHTML = `
    <div class="empty-state" style="padding: 24px; text-align: center; border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 12px; background: rgba(239, 68, 68, 0.05); margin-top: 12px;">
      <div style="font-size: 24px; margin-bottom: 8px;">⚠️</div>
      <div style="font-weight: 700; color: #ef4444; font-size: 14px;">Journey Notice</div>
      <p style="font-size: 12px; color: var(--text-muted); margin-top: 6px;">${errorMsg}</p>
      <p style="font-size: 11px; color: var(--text-muted); margin-top: 8px;">Try selecting from autocomplete suggestions or click the map to set exact coordinates.</p>
    </div>
  `;
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
      state.activeJourneyId = opt.journey_id || opt.option_id;
      highlightJourneyOnMap(opt);
    });

    container.appendChild(card);
  });

  // Highlight first option by default
  state.activeJourneyId = data.options[0]?.journey_id || 1;
  highlightJourneyOnMap(data.options[0]);
}

function highlightJourneyOnMap(option) {
  state.routeLayer.clearLayers();
  const allBounds = [];

  const routeColors = ['#0284c7', '#7c3aed', '#059669']; // High-contrast corridor colors
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

  if (state.originCoords && typeof state.originCoords.lat === 'number') {
    allBounds.push([state.originCoords.lat, state.originCoords.lon]);
  }
  if (state.destCoords && typeof state.destCoords.lat === 'number') {
    allBounds.push([state.destCoords.lat, state.destCoords.lon]);
  }

  if (allBounds.length > 0) {
    state.map.fitBounds(L.latLngBounds(allBounds), { padding: [50, 50] });
  }
}

// ==========================================
// 8. TRAFFIC TIME MACHINE
// ==========================================
function initTimeMachine() {
  const routeSelect = document.getElementById('tm-route-select');
  const dowSelect = document.getElementById('tm-dow-select');
  const slider = document.getElementById('tm-hour-slider');
  const hourDisplay = document.getElementById('tm-hour-display');

  if (!routeSelect || !slider) return;

  // Load available major routes
  safeFetchJson('/api/v1/routes?limit=50')
    .then(routes => {
      routeSelect.innerHTML = '';
      routes.forEach(r => {
        const opt = document.createElement('option');
        opt.value = r.route_id;
        opt.innerText = `${r.route_short_name} (${r.route_long_name || 'DTC Route'})`;
        routeSelect.appendChild(opt);
      });
      // Initial trigger
      updateTimeComparison();
    })
    .catch(err => console.warn("Failed to load routes for Time Machine:", err.message));

  routeSelect.addEventListener('change', updateTimeComparison);
  if (dowSelect) dowSelect.addEventListener('change', updateTimeComparison);

  slider.addEventListener('input', () => {
    const hr = parseInt(slider.value, 10);
    const ampm = hr >= 12 ? 'PM' : 'AM';
    const displayHr = hr % 12 === 0 ? 12 : hr % 12;
    if (hourDisplay) hourDisplay.innerText = `${String(displayHr).padStart(2, '0')}:00 ${ampm}`;
    updateTimeComparison();
  });
}

async function updateTimeComparison() {
  const routeSelect = document.getElementById('tm-route-select');
  const dowSelect = document.getElementById('tm-dow-select');
  const slider = document.getElementById('tm-hour-slider');

  if (!routeSelect || !slider) return;

  const routeId = routeSelect.value;
  const isWeekend = dowSelect ? dowSelect.value : '0';
  const hour = slider.value;

  if (!routeId) return;

  try {
    const url = `/api/v1/analytics/time-comparison?route_id=${encodeURIComponent(routeId)}&hour=${hour}&is_weekend=${isWeekend}`;
    const data = await safeFetchJson(url);

    // Update KPI Tiles
    const curEl = document.getElementById('tm-current-time');
    const freeEl = document.getElementById('tm-freeflow-time');
    const delayEl = document.getElementById('tm-delay-time');
    const speedEl = document.getElementById('tm-avg-speed');

    if (curEl) curEl.innerText = `${data.selected_hour_duration_minutes}m`;
    if (freeEl) freeEl.innerText = `${data.freeflow_duration_minutes}m`;
    if (delayEl) delayEl.innerText = `+${data.delay_minutes}m`;
    if (speedEl) speedEl.innerText = `${data.avg_speed_kmh} km/h`;

    updateTimeMachineChart(data.hourly_profile, parseInt(hour, 10));
  } catch (err) {
    console.warn("Time comparison query notice:", err.message);
  }
}

function updateTimeMachineChart(profile, activeHour) {
  const chartContainer = document.getElementById('tm-chart-bars');
  if (!chartContainer || !profile) return;

  chartContainer.innerHTML = '';
  const maxVal = Math.max(...profile.map(p => p.travel_time_minutes));

  profile.forEach(p => {
    const barWrap = document.createElement('div');
    barWrap.className = `chart-bar-col ${p.hour === activeHour ? 'active' : ''}`;

    const heightPct = Math.max(12, Math.round((p.travel_time_minutes / maxVal) * 100));
    const isPeak = (p.hour >= 8 && p.hour <= 11) || (p.hour >= 17 && p.hour <= 20);

    barWrap.innerHTML = `
      <div class="chart-bar ${isPeak ? 'peak' : ''}" style="height: ${heightPct}%;">
        <span class="bar-tooltip">${p.travel_time_minutes}m (${p.speed_kmh} km/h)</span>
      </div>
      <span class="bar-label">${p.hour}h</span>
    `;

    barWrap.addEventListener('click', () => {
      const slider = document.getElementById('tm-hour-slider');
      if (slider) {
        slider.value = p.hour;
        slider.dispatchEvent(new Event('input'));
      }
    });

    chartContainer.appendChild(barWrap);
  });
}

// ==========================================
// 9. VALIDATION LAB BENCHMARKS
// ==========================================
async function loadValidationLab() {
  try {
    const data = await safeFetchJson('/api/v1/validation/summary');
    
    const maeModel = document.getElementById('val-model-mae');
    const maeStatic = document.getElementById('val-static-mae');
    const errorRed = document.getElementById('val-error-reduction');
    const accuracy = document.getElementById('val-accuracy');

    if (maeModel) maeModel.innerText = `${data.pulse_model_mae_minutes}m`;
    if (maeStatic) maeStatic.innerText = `${data.static_schedule_mae_minutes}m`;
    if (errorRed) errorRed.innerText = `-${data.error_reduction_pct}%`;
    if (accuracy) accuracy.innerText = `${data.model_accuracy_pct}%`;

    // Render benchmark rows
    const tbody = document.getElementById('val-benchmarks-tbody');
    if (tbody && data.benchmarks) {
      tbody.innerHTML = '';
      data.benchmarks.forEach(b => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td><strong>${b.corridor}</strong><br/><span style="font-size: 11px; color: var(--text-muted);">${b.condition}</span></td>
          <td>${b.distance_km} km</td>
          <td style="color: #ef4444; font-weight: 700;">${b.static_timetable_minutes}m</td>
          <td style="color: var(--text-main); font-weight: 700;">${b.observed_bus_minutes}m</td>
          <td style="color: var(--accent-cyan); font-weight: 800;">${b.pulse_predicted_minutes}m</td>
          <td style="color: var(--text-muted);">${b.google_maps_minutes}m</td>
          <td><span class="badge badge-high">${b.accuracy_pct}%</span></td>
        `;
        tbody.appendChild(tr);
      });
    }
  } catch (err) {
    console.warn("Failed to load validation lab data:", err.message);
  }
}

// ==========================================
// 10. SYSTEM COMMAND CENTER
// ==========================================
async function loadCommandStatus() {
  try {
    const data = await safeFetchJson('/api/v1/system/status');

    const diskEl = document.getElementById('cmd-disk-storage');
    const histEl = document.getElementById('cmd-hist-dbs');
    const gtfsEl = document.getElementById('cmd-gtfs-stops');
    const feedEl = document.getElementById('cmd-feed-status');

    if (diskEl) diskEl.innerText = `${data.storage.free_gb} GB Free (E:)`;
    if (histEl) histEl.innerText = `${data.datasets.historical_sqlite.database_count} / 31 DBs`;
    if (gtfsEl) gtfsEl.innerText = `6,862 Stops`;
    if (feedEl) {
      feedEl.innerText = data.live_feed.status;
      feedEl.style.color = data.live_feed.status === 'ACTIVE' ? '#10B981' : '#F59E0B';
    }
  } catch (err) {
    console.warn("Failed to load command status:", err.message);
  }
}
