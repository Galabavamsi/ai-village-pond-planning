from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "screenshots"
SAMPLE = ROOT / "contour-maps" / "contours_1m.kml"
BASE_URL = "http://127.0.0.1:8000"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
        page.goto(f"{BASE_URL}/docs", wait_until="networkidle")
        page.screenshot(path=str(OUT / "01_swagger_api_overview.png"), full_page=True)

        operation_container = page.locator(".opblock").filter(has_text="/analyzeContour")
        operation_summary = operation_container.locator(".opblock-summary")
        operation_summary.scroll_into_view_if_needed()
        operation_summary.click()
        page.get_by_role("button", name="Try it out").click()
        upload = page.locator('input[type="file"]')
        upload.set_input_files(str(SAMPLE))
        operation_container.screenshot(path=str(OUT / "02_swagger_upload_form.png"))

        page.get_by_role("button", name="Execute").click()
        page.locator(".live-responses-table").filter(has_text="completed").wait_for(state="visible", timeout=120_000)
        page.wait_for_timeout(500)
        page.locator(".live-responses-table").screenshot(path=str(OUT / "03_swagger_success_response.png"))
        browser.close()
    print(OUT)


if __name__ == "__main__":
    main()
