/**
 * PULSE · Globe engine (frontend/static/js/globe.js)
 *
 * Full-bleed CesiumJS globe with:
 *   - Google Photorealistic 3D Tiles when GOOGLE_MAPS_API_KEY is configured,
 *     otherwise an ellipsoid globe with satellite / street imagery
 *   - switchable map stack (3D city, satellite, dark, light)
 *   - "vision" post-process looks (NVG, FLIR, CRT)
 *   - an orbit-to-street cinematic intro over Delhi
 *
 * The approach follows the God's Eye View console: hide Cesium chrome,
 * hide the default globe under photoreal tiles, soften the atmosphere.
 */

/* global Cesium */

export const DELHI = { lat: 28.6139, lon: 77.2090 };

// Approximate ellipsoidal ground height across Delhi (orthometric ~215 m,
// EGM96 undulation ~ -50 m). Used when we cannot sample the 3D tiles.
const DELHI_ELLIPSOID_GROUND_M = 165;

const CITY_VIEW = {
  lon: 77.2050, lat: 28.4300, height: 26000, heading: 8, pitch: -48,
};

const CARTO_ATTR = '© OpenStreetMap contributors © CARTO';

export class PulseGlobe {
  constructor(containerId, config = {}) {
    this.config = config;
    this.containerId = containerId;
    this.viewer = null;
    this.tileset = null;
    this.stack = null;
    this.vision = 'normal';
    this._visionStage = null;
    this._imageryLayer = null;
    this._labelsLayer = null;
    this.labels = true;
    this._groundCache = new Map();
    this._spinRemove = null;
  }

  get photoreal() { return this.stack === 'photoreal' && !!this.tileset; }

  async init(onStatus = () => {}) {
    onStatus('Configuring viewer…');
    const credits = document.createElement('div');
    credits.id = 'globe-credits';
    document.body.appendChild(credits);

    const viewer = new Cesium.Viewer(this.containerId, {
      timeline: false,
      animation: false,
      baseLayerPicker: false,
      geocoder: false,
      homeButton: false,
      sceneModePicker: false,
      navigationHelpButton: false,
      fullscreenButton: false,
      vrButton: false,
      selectionIndicator: false,
      infoBox: false,
      baseLayer: false,
      creditContainer: credits,
      msaaSamples: 4,
      requestRenderMode: false,
    });
    this.viewer = viewer;
    viewer.targetFrameRate = 60;

    const scene = viewer.scene;
    scene.globe.baseColor = Cesium.Color.fromCssColorString('#0b1220');
    scene.globe.enableLighting = false;
    scene.globe.showGroundAtmosphere = true;
    scene.skyAtmosphere.show = true;
    scene.skyAtmosphere.atmosphereLightIntensity = 18;
    scene.skyAtmosphere.saturationShift = -0.12;
    scene.skyAtmosphere.brightnessShift = -0.08;
    scene.fog.enabled = true;
    scene.highDynamicRange = false;
    scene.screenSpaceCameraController.enableCollisionDetection = true;
    // Keep users from zooming out past a comfortable full-earth framing.
    const ssc = scene.screenSpaceCameraController;
    ssc.maximumZoomDistance = 30_000_000;
    ssc.minimumZoomDistance = 40;
    // Trackpad pinch arrives as Ctrl+wheel: let it zoom the globe, and stop the
    // browser from zooming the whole page instead.
    ssc.zoomEventTypes = [
      Cesium.CameraEventType.WHEEL,
      { eventType: Cesium.CameraEventType.WHEEL, modifier: Cesium.KeyboardEventModifier.CTRL },
      Cesium.CameraEventType.RIGHT_DRAG,
      Cesium.CameraEventType.PINCH,
    ];
    scene.canvas.addEventListener('wheel', (e) => { if (e.ctrlKey) e.preventDefault(); }, { passive: false });
    // Sharper imagery (and street names) at oblique angles.
    scene.globe.maximumScreenSpaceError = 1.5;

    // Google Photorealistic 3D Tiles (optional)
    const gKey = (this.config.googleMapsApiKey || '').trim();
    if (gKey) {
      onStatus('Loading Google photorealistic 3D tiles…');
      try {
        Cesium.GoogleMaps.defaultApiKey = gKey;
        this.tileset = await Cesium.createGooglePhotorealistic3DTileset({ onlyUsingWithGoogleGeocoder: true });
        this.tileset.maximumScreenSpaceError = 12;
        scene.primitives.add(this.tileset);
      } catch (err) {
        console.warn('[PULSE] Google 3D tiles unavailable, using imagery globe:', err);
        this.tileset = null;
        this.tilesError = (err && err.statusCode === 403)
          ? 'Google refused the 3D tiles request (403). Enable the Map Tiles API for this key in Google Cloud.'
          : 'Google 3D tiles could not be loaded.';
        onStatus('3D tiles unavailable — using satellite globe');
      }
    }

    let saved = null;
    try {
      saved = localStorage.getItem('pulse_globe_stack');
      this.labels = localStorage.getItem('pulse_globe_labels') !== '0';
    } catch (e) { /* storage blocked */ }
    const initial = (saved && (saved !== 'photoreal' || this.tileset)) ? saved : (this.tileset ? 'photoreal' : 'satellite');
    this.setStack(initial);

    // Camera starts in orbit above India.
    viewer.camera.setView({
      destination: Cesium.Cartesian3.fromDegrees(DELHI.lon, DELHI.lat - 6, 19_000_000),
      orientation: { heading: 0, pitch: Cesium.Math.toRadians(-90), roll: 0 },
    });
    return viewer;
  }

  /* ── Map stack ─────────────────────────────────────────── */
  setStack(stack) {
    const v = this.viewer;
    if (stack === 'photoreal' && !this.tileset) stack = 'satellite';
    this.stack = stack;
    try { localStorage.setItem('pulse_globe_stack', stack); } catch (e) { /* ignore */ }

    if (this.tileset) this.tileset.show = stack === 'photoreal';
    v.scene.globe.show = stack !== 'photoreal';

    if (stack !== 'photoreal') {
      if (this._imageryLayer) {
        v.imageryLayers.remove(this._imageryLayer, true);
        this._imageryLayer = null;
      }
      const provider = this._imageryProvider(stack);
      this._imageryLayer = v.imageryLayers.addImageryProvider(provider, 0);
      if (stack === 'dark') {
        this._imageryLayer.brightness = 1.15;
      }
    }
    this._syncLabels();
    this._groundCache.clear();
    document.querySelectorAll('[data-stack]').forEach((b) => {
      b.classList.toggle('active', b.dataset.stack === stack);
      if (b.dataset.stack === 'photoreal') {
        b.disabled = !this.tileset;
        b.title = this.tileset
          ? 'Google Photorealistic 3D Tiles'
          : (this.tilesError || 'Set GOOGLE_MAPS_API_KEY (with the Map Tiles API enabled) to unlock photoreal 3D buildings');
      }
    });
    v.scene.requestRender();
    return stack;
  }

  /** Road and place names. Street maps carry their own; satellite gets a
   *  transparent CARTO label layer on top. (Labels cannot be draped on the
   *  photoreal 3D tiles.) */
  setLabels(on) {
    this.labels = !!on;
    try { localStorage.setItem('pulse_globe_labels', this.labels ? '1' : '0'); } catch (e) { /* ignore */ }
    this._syncLabels();
    return this.labels;
  }

  _syncLabels() {
    const v = this.viewer;
    const want = this.labels && this.stack === 'satellite';
    if (want && !this._labelsLayer) {
      const carto = (this.config.cartoApiKey || '').trim();
      this._labelsLayer = v.imageryLayers.addImageryProvider(new Cesium.UrlTemplateImageryProvider({
        url: `https://{s}.basemaps.cartocdn.com/rastertiles/light_only_labels/{z}/{x}/{y}@2x.png${carto ? `?key=${encodeURIComponent(carto)}` : ''}`,
        subdomains: 'abcd', tileWidth: 512, tileHeight: 512, maximumLevel: 19, credit: CARTO_ATTR,
      }));
    } else if (!want && this._labelsLayer) {
      v.imageryLayers.remove(this._labelsLayer, true);
      this._labelsLayer = null;
    }
    if (this._labelsLayer) v.imageryLayers.raiseToTop(this._labelsLayer);
    document.querySelectorAll('[data-labels]').forEach((b) => {
      b.classList.toggle('active', this.labels);
      b.setAttribute('aria-pressed', String(this.labels));
      b.disabled = this.stack === 'photoreal';
    });
  }

  zoom(factor) {
    const cam = this.viewer.camera;
    const h = cam.positionCartographic.height;
    const amount = h * Math.abs(factor);
    if (factor > 0) cam.zoomIn(Math.min(amount, Math.max(h - 60, 0)));
    else cam.zoomOut(amount);
  }

  _imageryProvider(stack) {
    const mt = (this.config.maptilerApiKey || '').trim();
    const carto = (this.config.cartoApiKey || '').trim();
    const cartoUrl = (style) => `https://{s}.basemaps.cartocdn.com/rastertiles/${style}/{z}/{x}/{y}@2x.png${carto ? `?key=${encodeURIComponent(carto)}` : ''}`;
    if (stack === 'dark') {
      return new Cesium.UrlTemplateImageryProvider({ url: cartoUrl('dark_all'), subdomains: 'abcd', tileWidth: 512, tileHeight: 512, maximumLevel: 19, credit: CARTO_ATTR });
    }
    if (stack === 'light') {
      return new Cesium.UrlTemplateImageryProvider({ url: cartoUrl('voyager'), subdomains: 'abcd', tileWidth: 512, tileHeight: 512, maximumLevel: 19, credit: CARTO_ATTR });
    }
    if (mt) {
      return new Cesium.UrlTemplateImageryProvider({
        url: `https://api.maptiler.com/maps/satellite-v4/{z}/{x}/{y}.jpg?key=${encodeURIComponent(mt)}`,
        tileWidth: 512, tileHeight: 512, maximumLevel: 20,
        credit: '© MapTiler © OpenStreetMap contributors',
      });
    }
    return new Cesium.UrlTemplateImageryProvider({
      url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
      maximumLevel: 19,
      credit: 'Tiles © Esri — Esri, Maxar, Earthstar Geographics, and the GIS User Community',
    });
  }

  /* ── Vision post-process looks ─────────────────────────── */
  setVision(name) {
    const stages = this.viewer.scene.postProcessStages;
    if (this._visionStage) {
      stages.remove(this._visionStage);
      this._visionStage = null;
    }
    this.vision = name;
    document.body.dataset.vision = name;
    document.querySelectorAll('[data-vision]').forEach((b) => {
      if (b.tagName === 'BUTTON') b.classList.toggle('active', b.dataset.vision === name);
    });
    const frag = VISION_SHADERS[name];
    if (!frag) return;
    const start = performance.now();
    this._visionStage = stages.add(new Cesium.PostProcessStage({
      fragmentShader: frag,
      uniforms: { time: () => (performance.now() - start) / 1000 },
    }));
  }

  /* ── Camera verbs ──────────────────────────────────────── */
  intro(onDone) {
    const cam = this.viewer.camera;
    // A slow spin while the tiles warm up, then dive into Delhi.
    let spinning = true;
    const spin = () => { if (spinning) cam.rotate(Cesium.Cartesian3.UNIT_Z, -0.0009); };
    this._spinRemove = this.viewer.clock.onTick.addEventListener(spin);
    setTimeout(() => {
      spinning = false;
      if (this._spinRemove) { this._spinRemove(); this._spinRemove = null; }
      this.flyToCity(5.5, onDone);
    }, 1400);
  }

  flyToCity(duration = 3, complete) {
    const v = CITY_VIEW;
    this.viewer.camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(v.lon, v.lat, v.height),
      orientation: { heading: Cesium.Math.toRadians(v.heading), pitch: Cesium.Math.toRadians(v.pitch), roll: 0 },
      duration,
      easingFunction: Cesium.EasingFunction.CUBIC_IN_OUT,
      complete,
    });
  }

  resetGlobe() {
    this.viewer.camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(DELHI.lon, DELHI.lat - 6, 19_000_000),
      orientation: { heading: 0, pitch: Cesium.Math.toRadians(-90), roll: 0 },
      duration: 3,
      easingFunction: Cesium.EasingFunction.CUBIC_IN_OUT,
    });
  }

  toggleTilt() {
    const cam = this.viewer.camera;
    const center = this.pickCenter();
    if (!center) return;
    const topDown = Cesium.Math.toDegrees(cam.pitch) < -80;
    const range = Math.max(800, Cesium.Cartesian3.distance(cam.positionWC, center));
    cam.flyToBoundingSphere(new Cesium.BoundingSphere(center, 1), {
      offset: new Cesium.HeadingPitchRange(cam.heading, Cesium.Math.toRadians(topDown ? -42 : -89.5), range),
      duration: 1.4,
    });
  }

  flyToPositions(latLons, { pitch = -45, padding = 1.5, duration = 2.2, avoidPanel = false } = {}) {
    if (!latLons.length) return;
    const pts = latLons.map(([lat, lon]) => Cesium.Cartesian3.fromDegrees(lon, lat, this.baseHeight()));
    const sphere = Cesium.BoundingSphere.fromPoints(pts);
    const range = Math.max(1600, sphere.radius * 2.2 * padding);
    const cam = this.viewer.camera;
    cam.flyToBoundingSphere(sphere, {
      offset: new Cesium.HeadingPitchRange(Cesium.Math.toRadians(10), Cesium.Math.toRadians(pitch), range),
      duration,
      complete: () => {
        if (!avoidPanel) return;
        // Shift the view so the subject sits in the free area right of the panel.
        const panel = document.getElementById('panel');
        const canvas = this.viewer.scene.canvas;
        if (!panel || window.innerWidth < 860) return;
        const covered = panel.getBoundingClientRect().right;
        const frac = (covered / 2) / canvas.clientWidth;
        const fov = cam.frustum.fov || Cesium.Math.toRadians(60);
        const halfWidth = range * Math.tan(fov / 2);
        cam.moveLeft(2 * halfWidth * frac);
      },
    });
  }

  /* ── Picking ───────────────────────────────────────────── */
  pickLatLon(screenPos) {
    const scene = this.viewer.scene;
    let cart = null;
    if (scene.pickPositionSupported) {
      try { cart = scene.pickPosition(screenPos); } catch (e) { cart = null; }
    }
    if (!Cesium.defined(cart)) {
      cart = this.viewer.camera.pickEllipsoid(screenPos, scene.globe.ellipsoid);
    }
    if (!Cesium.defined(cart)) return null;
    const c = Cesium.Cartographic.fromCartesian(cart);
    if (!c) return null;
    return { lat: Cesium.Math.toDegrees(c.latitude), lon: Cesium.Math.toDegrees(c.longitude) };
  }

  pickCenter() {
    const canvas = this.viewer.scene.canvas;
    const p = new Cesium.Cartesian2(canvas.clientWidth / 2, canvas.clientHeight / 2);
    const ll = this.pickLatLon(p);
    if (!ll) return null;
    return Cesium.Cartesian3.fromDegrees(ll.lon, ll.lat, this.baseHeight());
  }

  /** Ground height to build 3D geometry on (walls, beams, buses). */
  baseHeight() {
    return this.photoreal ? DELHI_ELLIPSOID_GROUND_M : 0;
  }

  /** Best-effort ground height at a point, sampling the photoreal tiles when available. */
  async groundHeight(lat, lon) {
    if (!this.photoreal) return 0;
    const key = `${lat.toFixed(3)},${lon.toFixed(3)}`;
    if (this._groundCache.has(key)) return this._groundCache.get(key);
    let h = DELHI_ELLIPSOID_GROUND_M;
    try {
      const carto = [Cesium.Cartographic.fromDegrees(lon, lat)];
      const sampled = await Promise.race([
        this.viewer.scene.sampleHeightMostDetailed(carto),
        new Promise((resolve) => setTimeout(() => resolve(null), 2500)),
      ]);
      if (sampled && Number.isFinite(sampled[0].height)) {
        // Rooftops can be sampled; clamp to a sane band for Delhi.
        h = Math.min(Math.max(sampled[0].height, 120), 320);
      }
    } catch (e) { /* fall back */ }
    this._groundCache.set(key, h);
    return h;
  }
}

/* ── GLSL vision looks (WebGL2 / Cesium post-process) ───── */
const VISION_COMMON = /* glsl */ `
  uniform sampler2D colorTexture;
  uniform float time;
  in vec2 v_textureCoordinates;
  float hash(vec2 p) { vec3 p3 = fract(vec3(p.xyx) * 0.1031); p3 += dot(p3, p3.yzx + 33.33); return fract((p3.x + p3.y) * p3.z); }
  float luma(vec3 c) { return dot(c, vec3(0.299, 0.587, 0.114)); }
  float vignette(vec2 uv, float k) { vec2 d = uv - 0.5; return clamp(1.0 - dot(d, d) * k, 0.0, 1.0); }
`;

const VISION_SHADERS = {
  nvg: VISION_COMMON + /* glsl */ `
    void main() {
      vec2 uv = v_textureCoordinates;
      vec3 c = texture(colorTexture, uv).rgb;
      float l = luma(c);
      // Auto-gain with a contrast curve so roads and markers stay legible.
      l = smoothstep(0.04, 0.85, l);
      l = pow(l, 1.35);
      float n = hash(uv * vec2(1920.0, 1080.0) + fract(time) * 100.0);
      l += (n - 0.5) * 0.07;
      float scan = 0.93 + 0.07 * sin(uv.y * 900.0);
      vec3 g = mix(vec3(0.02, 0.10, 0.03), vec3(0.55, 1.0, 0.55), clamp(l, 0.0, 1.0)) * scan;
      g *= vignette(uv, 2.4);
      out_FragColor = vec4(g, 1.0);
    }
  `,
  flir: VISION_COMMON + /* glsl */ `
    void main() {
      vec2 uv = v_textureCoordinates;
      vec3 c = texture(colorTexture, uv).rgb;
      float l = luma(c);
      // Treat warm (red-heavy) surfaces and bright surfaces as hot.
      float heat = clamp(l * 0.85 + (c.r - c.b) * 0.6, 0.0, 1.0);
      heat = smoothstep(0.05, 0.95, heat);
      float n = hash(uv * vec2(1280.0, 720.0) + time) * 0.05;
      vec3 col = vec3(heat + n);
      col *= vignette(uv, 1.6);
      out_FragColor = vec4(col, 1.0);
    }
  `,
  crt: VISION_COMMON + /* glsl */ `
    void main() {
      vec2 uv = v_textureCoordinates;
      vec2 off = (uv - 0.5) * 0.004;
      float r = texture(colorTexture, uv + off).r;
      float g = texture(colorTexture, uv).g;
      float b = texture(colorTexture, uv - off).b;
      float l = luma(vec3(r, g, b));
      float scan = 0.82 + 0.18 * sin(uv.y * 1400.0 + time * 6.0);
      float flicker = 0.97 + 0.03 * sin(time * 50.0);
      vec3 amber = vec3(1.0, 0.68, 0.12) * pow(l, 0.9) * 1.3;
      vec3 col = mix(vec3(r, g, b) * 0.25, amber, 0.85) * scan * flicker;
      col *= vignette(uv, 2.0);
      out_FragColor = vec4(col, 1.0);
    }
  `,
};
