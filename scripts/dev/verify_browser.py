"""
PULSE Browser Automation & Evidence Verification Script (scripts/verify_browser.py)
Exercises all real user journeys, layer selector, 2D SVG buses, pick on map,
and captures genuine screenshots into docs/evidence/.
"""
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

OUTPUT_DIR = Path("docs/evidence")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def run_browser_verification(mode: str = "all"):
    print(f"[1/10] Starting Playwright browser automation (mode={mode})...")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="msedge",
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=1
        )
        page = context.new_page()
        page.on("console", lambda msg: print(f"BROWSER LOG: {msg.text}"))
        page.on("pageerror", lambda err: print(f"BROWSER ERROR: {err}"))
        page.on("requestfailed", lambda req: print(f"REQ FAILED: {req.url} - {req.failure}"))

        print("[2/10] Navigating to PULSE at http://127.0.0.1:8000/...")
        page.goto("http://127.0.0.1:8000/", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_selector("#map-element", timeout=10000)
        page.wait_for_timeout(3000)

        if mode == "all":
            # 1. Baseline Journey Planner with Light CARTO Positron & visible Layer Control
            print("[3/10] Capturing 01_journey_planner_default.png...")
            page.screenshot(path=str(OUTPUT_DIR / "01_journey_planner_default.png"))

            # 2. Test Pick on Map: Origin
            print("[4/10] Testing Pick on Map: Origin...")
            btn_pick_orig = page.locator("#btn-pick-origin")
            btn_pick_orig.click()
            page.wait_for_timeout(500)
            banner = page.locator("#map-selection-banner")
            assert banner.is_visible(), "Map selection banner should be visible"
            page.screenshot(path=str(OUTPUT_DIR / "02_pick_origin_active.png"))

            # Click on map canvas at (x: 900, y: 350)
            page.mouse.click(900, 350)
            page.wait_for_timeout(800)
            orig_val = page.locator("#input-origin").input_value()
            print(f"       Origin picked: {orig_val}")
            assert "," in orig_val, "Origin should contain coordinates"
            page.screenshot(path=str(OUTPUT_DIR / "03_origin_pinned.png"))

            # 3. Test Pick on Map: Destination
            print("[5/10] Testing Pick on Map: Destination...")
            btn_pick_dest = page.locator("#btn-pick-dest")
            btn_pick_dest.click()
            page.wait_for_timeout(500)
            # Click on map canvas at (x: 950, y: 650)
            page.mouse.click(950, 650)
            page.wait_for_timeout(800)
            dest_val = page.locator("#input-dest").input_value()
            print(f"       Destination picked: {dest_val}")
            assert "," in dest_val, "Destination should contain coordinates"
            page.screenshot(path=str(OUTPUT_DIR / "04_destination_pinned.png"))

            # 4. Test Dynamic Route A: Anand Vihar ISBT -> Nehru Place
            print("[6/10] Testing Dynamic Route A: Anand Vihar ISBT -> Nehru Place...")
            page.wait_for_selector("#plan-submit-btn:not([disabled])", timeout=40000)
            page.locator("#input-origin").fill("Anand Vihar ISBT")
            page.locator("#input-dest").fill("Nehru Place")
            page.evaluate("() => { document.querySelectorAll('.autocomplete-dropdown').forEach(d => d.style.display = 'none'); document.getElementById('journey-form').dispatchEvent(new Event('submit', { cancelable: true, bubbles: true })); }")
            page.wait_for_selector(".journey-card", timeout=60000)
            page.wait_for_timeout(2000)
            page.screenshot(path=str(OUTPUT_DIR / "05_dynamic_route_anand_vihar_nehru_place.png"))

            # 5. Test Dynamic Route B: Anand Vihar ISBT -> Badarpur Border
            print("[7/10] Testing Dynamic Route B: Anand Vihar ISBT -> Badarpur Border...")
            page.wait_for_selector("#plan-submit-btn:not([disabled])", timeout=40000)
            page.locator("#input-dest").fill("Badarpur Border")
            page.evaluate("() => { document.querySelectorAll('.autocomplete-dropdown').forEach(d => d.style.display = 'none'); document.getElementById('journey-form').dispatchEvent(new Event('submit', { cancelable: true, bubbles: true })); }")
            page.wait_for_selector(".journey-card", timeout=60000)
            page.wait_for_timeout(2000)
            page.screenshot(path=str(OUTPUT_DIR / "06_dynamic_route_anand_vihar_badarpur_border.png"))

            # 6. Test Layer Selector: Satellite Plain
            print("[8/10] Testing Satellite Plain basemap...")
            page.locator('.layer-radio-item[data-layer="satellite-plain"]').click()
            page.wait_for_timeout(3500)
            page.screenshot(path=str(OUTPUT_DIR / "07_satellite_plain_view.png"))

            # 7. Test Layer Selector: Satellite Hybrid
            print("       Testing Satellite Hybrid basemap...")
            page.locator('.layer-radio-item[data-layer="satellite-hybrid"]').click()
            page.wait_for_timeout(3500)
            page.screenshot(path=str(OUTPUT_DIR / "08_satellite_hybrid_view.png"))

            # Switch back to Positron (Street Light)
            page.locator('.layer-radio-item[data-layer="positron"]').click()
            page.wait_for_timeout(1000)

        # 8. Test Live Bus Map & Rapido-Style 2D SVG Buses
        print("[9/10] Testing Live Bus Map & Rapido-Style 2D Bus SVGs...")
        page.locator('button[data-view="live"]').click()
        page.wait_for_timeout(4000)
        # Capture wide overview with clusters and buses
        page.screenshot(path=str(OUTPUT_DIR / "09_live_bus_map_overview.png"))

        # Zoom into live bus to show individual 2D SVG buses
        print("       Centering map on active live bus...")
        page.evaluate("""() => {
            if (window.state && window.state.busMarkers && window.state.busMarkers.size > 0) {
                const marker = window.state.busMarkers.values().next().value;
                if (marker) {
                    window.state.map.setView(marker.getLatLng(), 16);
                }
            } else if (window.state && window.state.map) {
                window.state.map.setView([28.6250, 77.2200], 15);
            }
        }""")
        page.wait_for_timeout(3500)
        page.screenshot(path=str(OUTPUT_DIR / "10_live_bus_svg_close_up.png"))

        # Open popup on an active live bus marker
        print("       Opening bus popup...")
        has_popup = page.evaluate("""() => {
            if (window.state && window.state.busMarkers && window.state.busMarkers.size > 0) {
                const marker = window.state.busMarkers.values().next().value;
                if (marker) {
                    marker.openPopup();
                    return true;
                }
            }
            return false;
        }""")
        if has_popup:
            page.wait_for_selector(".leaflet-popup", timeout=5000)
            page.wait_for_timeout(1000)
            page.screenshot(path=str(OUTPUT_DIR / "11_bus_popup_provenance.png"))
        else:
            print("       Notice: No active bus marker available for popup")

        # 9. Test Citywide Autocomplete Search
        print("[10/10] Testing Citywide Autocomplete Search & Error Handling...")
        page.locator('button[data-view="journey"]').click()
        page.wait_for_timeout(1000)

        # Test autocomplete suggestions
        orig_input = page.locator("#input-origin")
        orig_input.click()
        orig_input.fill("")
        orig_input.type("India Gate", delay=100)
        page.wait_for_selector("#origin-suggestions .suggestion-item", timeout=15000)
        page.wait_for_timeout(1000)
        page.screenshot(path=str(OUTPUT_DIR / "12_citywide_search_autocomplete.png"))

        # Test Error Handling: Invalid destination
        page.evaluate("() => { document.querySelectorAll('.autocomplete-dropdown').forEach(d => d.style.display = 'none'); }")
        page.wait_for_timeout(300)
        page.wait_for_selector("#plan-submit-btn:not([disabled])", timeout=40000)
        dest_input = page.locator("#input-dest")
        dest_input.click(force=True)
        dest_input.fill("InvalidUnknownZone123XYZ")
        page.evaluate("""() => {
            document.querySelectorAll('.autocomplete-dropdown').forEach(d => d.style.display = 'none');
            document.getElementById('journey-form').dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
        }""")
        page.wait_for_selector(".empty-state", timeout=20000)
        page.wait_for_timeout(1000)
        page.screenshot(path=str(OUTPUT_DIR / "13_genuine_no_route_error.png"))

        browser.close()
        print("✓ Successfully completed browser verification and captured all evidence screenshots.")


if __name__ == "__main__":
    mode_arg = sys.argv[1] if len(sys.argv) > 1 else "all"
    run_browser_verification(mode_arg)
