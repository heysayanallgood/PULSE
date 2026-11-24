"""
Edge Browser Diagnostics & Tile Verification Script
"""
from playwright.sync_api import sync_playwright

def test_layers():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})

        tile_responses = []
        failed_requests = []
        page.on("response", lambda r: tile_responses.append((r.status, r.url)) if any(k in r.url for k in ["carto", "maptiler", "arcgis", "openstreetmap"]) else None)
        page.on("requestfailed", lambda req: failed_requests.append((req.url, req.failure)))

        print("Navigating to http://127.0.0.1:8000/ ...")
        page.goto("http://127.0.0.1:8000/", wait_until="networkidle")

        print("\n--- 1. Testing Positron (Initial) ---")
        positron_tiles = [t for t in tile_responses if "light_all" in t[1]]
        print(f"Positron tiles loaded: {len(positron_tiles)}")
        if positron_tiles:
            print(f"Sample: {positron_tiles[0]}")

        print("\n--- 2. Switching to Satellite Plain ---")
        page.locator('.layer-radio-item[data-layer="satellite-plain"]').click()
        page.wait_for_timeout(3000)
        sat_plain_tiles = [t for t in tile_responses if "satellite" in t[1]]
        print(f"Satellite Plain tiles loaded: {len(sat_plain_tiles)}")
        for st, u in sat_plain_tiles[:5]:
            print(f"  {st}: {u}")

        print("\n--- 3. Switching to Satellite Hybrid ---")
        page.locator('.layer-radio-item[data-layer="satellite-hybrid"]').click()
        page.wait_for_timeout(3000)
        sat_hybrid_tiles = [t for t in tile_responses if "hybrid" in t[1]]
        print(f"Satellite Hybrid tiles loaded: {len(sat_hybrid_tiles)}")
        for st, u in sat_hybrid_tiles[:5]:
            print(f"  {st}: {u}")

        print("\n--- 4. Switching to Dark Street ---")
        page.locator('.layer-radio-item[data-layer="dark"]').click()
        page.wait_for_timeout(2000)
        dark_tiles = [t for t in tile_responses if "dark_all" in t[1]]
        print(f"Dark tiles loaded: {len(dark_tiles)}")

        print("\n--- 5. Switching back to Street Light (Positron) ---")
        page.locator('.layer-radio-item[data-layer="positron"]').click()
        page.wait_for_timeout(2000)

        print("\n--- Failed Requests ---")
        print(f"Total failed requests: {len(failed_requests)}")
        for u, f in failed_requests:
            print(f"  FAILED: {u} -> {f}")

        browser.close()

if __name__ == "__main__":
    test_layers()
