"""Run a local browser E2E check against scripts.local_fake_buscados_server.

Expected server:
    python -m uvicorn scripts.local_fake_buscados_server:app --host 127.0.0.1 --port 8096

This does not hit production, Postgres, Spaces, or InsightFace.
"""

from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
QUERY_IMAGE = ROOT / "output" / "local_fake_data" / "query.png"
SCREENSHOT_DIR = ROOT / "output" / "playwright"


def main() -> None:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto("http://127.0.0.1:8096/", wait_until="networkidle")

        page.set_input_files("#f_file", str(QUERY_IMAGE))
        page.fill("#f_nombre", "Prueba Local")
        page.fill("#f_tel", "0414-000-0000")
        page.select_option("#f_limite", "10")

        page.click("#f_btn")
        expect(page.locator("#f_res")).to_contain_text("Mostrando 10 de 23")
        expect(page.locator(".match")).to_have_count(10)
        expect(page.locator("#f_more")).to_be_visible()
        page.screenshot(
            path=str(SCREENSHOT_DIR / "familiar-load-more-page-1.png"),
            full_page=True,
        )

        page.click("#f_more")
        expect(page.locator("#f_res")).to_contain_text("Mostrando 20 de 23")
        expect(page.locator(".match")).to_have_count(20)
        expect(page.locator("#f_more")).to_be_visible()
        page.screenshot(
            path=str(SCREENSHOT_DIR / "familiar-load-more-page-2.png"),
            full_page=True,
        )

        page.click("#f_more")
        expect(page.locator("#f_res")).to_contain_text("Mostrando 23 de 23")
        expect(page.locator(".match")).to_have_count(23)
        expect(page.locator("#f_more")).to_have_count(0)
        page.screenshot(
            path=str(SCREENSHOT_DIR / "familiar-load-more-page-3.png"),
            full_page=True,
        )

        browser.close()

    print("Local fake /buscados E2E passed.")


if __name__ == "__main__":
    main()
