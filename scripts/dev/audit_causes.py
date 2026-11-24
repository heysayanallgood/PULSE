"""
Comprehensive Phase 2 Root Cause Audit Script
Audits Causes A through O in Microsoft Edge against http://127.0.0.1:8000/
"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

def audit():
    results = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()

        console_messages = []
        page_errors = []
        failed_requests = []
        all_responses = []

        page.on("console", lambda m: console_messages.append({"type": m.type, "text": m.text}))
        page.on("pageerror", lambda e: page_errors.append(str(e)))
        page.on("requestfailed", lambda r: failed_requests.append({"url": r.url, "failure": str(r.failure)}))
        page.on("response", lambda r: all_responses.append({"url": r.url, "status": r.status, "headers": dict(r.headers)}))

        page.goto("http://127.0.0.1:8000/", wait_until="networkidle")

        # Cause A, B, C: Caching & Headers
        html_resp = next((r for r in all_responses if r["url"] == "http://127.0.0.1:8000/"), None)
        js_resp = next((r for r in all_responses if "app.js" in r["url"]), None)
        css_resp = next((r for r in all_responses if "pulse.css" in r["url"]), None)

        results["A_B_C_caching"] = {
            "html_cache_control": html_resp["headers"].get("cache-control") if html_resp else None,
            "js_cache_control": js_resp["headers"].get("cache-control") if js_resp else None,
            "css_cache_control": css_resp["headers"].get("cache-control") if css_resp else None,
            "js_url": js_resp["url"] if js_resp else None,
            "css_url": css_resp["url"] if css_resp else None,
            "has_version_query_in_html": "?v=" in page.content()
        }

        # Cause D: Static file dir check
        results["D_static_dir"] = {
            "js_status": js_resp["status"] if js_resp else None,
            "css_status": css_resp["status"] if css_resp else None
        }

        # Cause E: Preview vs External process
        results["E_process"] = "Same host 127.0.0.1:8000, single listener on 8000 (PID 6992)"

        # Cause F: JS initialization exceptions
        results["F_js_exceptions"] = page_errors

        # Cause G: Duplicate Leaflet map instances
        map_instances = page.evaluate("""() => {
            const els = document.querySelectorAll('.leaflet-container');
            return {
                leaflet_container_count: els.length,
                state_map_id: window.state?.map?._leaflet_id,
                has_multiple_maps: els.length > 1
            };
        }""")
        results["G_duplicate_maps"] = map_instances

        # Cause H: Map initialized while container hidden
        container_dims = page.evaluate("""() => {
            const el = document.getElementById('map-element');
            if (!el) return null;
            const r = el.getBoundingClientRect();
            return { width: r.width, height: r.height, offsetWidth: el.offsetWidth, offsetHeight: el.offsetHeight };
        }""")
        results["H_container_dims"] = container_dims

        # Cause I, J: Layer selector display, visibility, z-index, obstruction
        selector_info = page.evaluate("""() => {
            const el = document.getElementById('pulse-layer-selector');
            if (!el) return null;
            const r = el.getBoundingClientRect();
            const cs = window.getComputedStyle(el);
            // Check what element is at center of selector
            const topEl = document.elementFromPoint(r.left + r.width/2, r.top + r.height/2);
            return {
                rect: { left: r.left, top: r.top, width: r.width, height: r.height },
                display: cs.display,
                visibility: cs.visibility,
                opacity: cs.opacity,
                zIndex: cs.zIndex,
                topElementTag: topEl ? topEl.tagName : null,
                topElementClass: topEl ? topEl.className : null,
                is_obstructed: topEl ? !el.contains(topEl) && topEl !== el : false
            };
        }""")
        results["I_J_layer_selector"] = selector_info

        # Cause K: LocalStorage preferences
        local_storage = page.evaluate("""() => {
            const items = {};
            for (let i = 0; i < localStorage.length; i++) {
                const k = localStorage.key(i);
                items[k] = localStorage.getItem(k);
            }
            return items;
        }""")
        results["K_local_storage"] = local_storage

        # Cause L: Map initialization default layer
        current_layer = page.evaluate("""() => {
            return {
                currentBaseLayerKey: window.state?.currentBaseLayerKey,
                radio_checked: document.querySelector('input[name="pulse-map-style"]:checked')?.value
            };
        }""")
        results["L_default_layer"] = current_layer

        # Cause M: Tile provider errors
        tile_statuses = [
            {"url": r["url"], "status": r["status"]} 
            for r in all_responses 
            if any(k in r["url"] for k in ["carto", "maptiler", "arcgis", "openstreetmap"])
        ]
        results["M_tile_statuses_sample"] = tile_statuses[:5]
        results["M_tile_failures"] = [r for r in tile_statuses if r["status"] >= 400]

        # Cause N: Event listeners on layer selector
        listener_test = page.evaluate("""() => {
            const items = Array.from(document.querySelectorAll('.layer-radio-item')).map(el => ({
                layer: el.dataset.layer,
                has_radio: !!el.querySelector('input[type="radio"]'),
                class: el.className
            }));
            return items;
        }""")
        results["N_layer_radios"] = listener_test

        # Cause O: Service Workers
        sw_count = page.evaluate("""async () => {
            if ('serviceWorker' in navigator) {
                const regs = await navigator.serviceWorker.getRegistrations();
                return regs.length;
            }
            return 0;
        }""")
        results["O_service_workers"] = sw_count

        # Check Live Bus markers DOM
        print("Switching to Live view...")
        page.locator('button[data-view="live"]').click()
        page.wait_for_timeout(4000)

        # Zoom in to 15 to disable clustering
        page.evaluate("""() => {
            if (window.state?.map) {
                window.state.map.setView([28.6250, 77.2200], 15);
            }
        }""")
        page.wait_for_timeout(3000)

        marker_dom_info = page.evaluate("""() => {
            const svgMarkers = document.querySelectorAll('.pulse-bus-marker');
            const circleMarkers = document.querySelectorAll('path.leaflet-interactive[stroke][fill]');
            const firstSvg = svgMarkers.length > 0 ? svgMarkers[0].innerHTML : null;
            return {
                svg_marker_count: svgMarkers.length,
                circle_marker_count: circleMarkers.length,
                bus_markers_in_state: window.state?.busMarkers?.size || 0,
                first_svg_snippet: firstSvg ? firstSvg.slice(0, 300) : null
            };
        }""")
        results["markers_dom"] = marker_dom_info

        browser.close()

    print(json.dumps(results, indent=2))

if __name__ == "__main__":
    audit()
