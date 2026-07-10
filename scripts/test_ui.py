import os
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ARTIFACT_DIR = Path(
    "C:/Users/kondu/.gemini/antigravity-ide/brain/d98da0af-b160-499f-b564-49db44b966cc"
)
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)


def run_ui_test():
    print("==========================================================")
    print("Launching backend (uvicorn) and dashboard (vite) servers...")
    print("==========================================================")

    # Launch uvicorn backend
    backend_log = open(str(ARTIFACT_DIR / "playwright_uvicorn.log"), "w", encoding="utf-8")
    backend_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "agent.api:app", "--host", "127.0.0.1", "--port", "8000"],
        stdout=backend_log,
        stderr=backend_log,
        text=True,
    )

    # Launch Vite dashboard dev server
    dashboard_log = open(str(ARTIFACT_DIR / "playwright_vite.log"), "w", encoding="utf-8")
    dashboard_dir = Path(__file__).resolve().parent.parent / "dashboard"
    dashboard_proc = subprocess.Popen(
        ["npm", "run", "dev"],
        cwd=str(dashboard_dir),
        stdout=dashboard_log,
        stderr=dashboard_log,
        text=True,
        shell=True,
    )

    time.sleep(5)  # Wait for startup

    success = False
    console_errors = []
    console_warnings = []
    failed_requests = []

    try:
        with sync_playwright() as p:
            # Launch chromium browser
            browser = p.chromium.launch(headless=True)

            # Setup context with tracing and video recording
            context = browser.new_context(
                record_video_dir=str(ARTIFACT_DIR), record_video_size={"width": 1280, "height": 720}
            )
            context.tracing.start(screenshots=True, snapshots=True, sources=True)

            page = context.new_page()

            # Collect console messages and errors
            def on_console(msg):
                if msg.type == "error":
                    console_errors.append(msg.text)
                elif msg.type == "warning":
                    console_warnings.append(msg.text)

            page.on("console", on_console)

            def on_request_failed(request):
                failed_requests.append(
                    f"{request.method} {request.url} failed: {request.failure if request.failure else 'Unknown error'}"
                )

            page.on("requestfailed", on_request_failed)

            # 1. Open home page
            print("Navigating to http://localhost:5173/...")
            page.goto("http://localhost:5173/", timeout=15000)
            page.wait_for_timeout(2000)

            # Take screenshot of landing page
            screenshot_path = ARTIFACT_DIR / "dashboard_home_playwright.png"
            page.screenshot(path=str(screenshot_path))
            print(f"Captured dashboard landing page screenshot: {screenshot_path}")

            # Verify page title
            header_text = page.locator("h1").inner_text()
            assert "AI Voice Sales Agent" in header_text, f"Header title mismatch: {header_text}"

            # 2. Verify theme toggle & localStorage persistence
            print("Testing theme toggle...")
            html_element = page.locator("html")

            # Get initial theme class (Vite default or localStorage)
            is_dark_init = "dark" in html_element.evaluate("el => el.className")
            print(f"Initial theme: {'dark' if is_dark_init else 'light'}")

            # Toggle once
            page.locator("#btn-theme-toggle").click()
            page.wait_for_timeout(500)
            is_dark_after_toggle = "dark" in html_element.evaluate("el => el.className")
            print(f"Theme after click: {'dark' if is_dark_after_toggle else 'light'}")
            assert is_dark_init != is_dark_after_toggle, (
                "Theme did not toggle classes on html element"
            )

            # Capture light/dark screenshots
            if not is_dark_after_toggle:
                page.screenshot(path=str(ARTIFACT_DIR / "dashboard_light_theme_playwright.png"))
                print("Captured light theme screenshot")
            else:
                page.screenshot(path=str(ARTIFACT_DIR / "dashboard_dark_theme_playwright.png"))
                print("Captured dark theme screenshot")

            # Reload page to test localStorage persistence
            print("Reloading page to verify theme persistence...")
            page.reload()
            page.wait_for_timeout(1000)
            is_dark_after_reload = "dark" in html_element.evaluate("el => el.className")
            assert is_dark_after_reload == is_dark_after_toggle, (
                "Theme selection did not persist after reload"
            )
            print("Theme persistence verified successfully")

            # 3. Test Leads Tab
            print("Testing Leads tab...")
            page.locator("role=tab[name='👥 Leads']").click()
            page.wait_for_timeout(1000)
            page.screenshot(path=str(ARTIFACT_DIR / "dashboard_leads_tab_playwright.png"))

            # Search for a lead
            print("Searching for 'Rahul'...")
            page.locator("#input-search").fill("Rahul")
            page.wait_for_timeout(1000)
            page.screenshot(path=str(ARTIFACT_DIR / "dashboard_leads_search_playwright.png"))

            # Click on the first row to view lead details
            print("Clicking on first lead row to view details...")
            lead_row = page.locator("table tbody tr").first
            lead_row.click()
            page.wait_for_timeout(1000)
            page.screenshot(path=str(ARTIFACT_DIR / "dashboard_lead_details_playwright.png"))

            # 4. Click other tabs
            print("Clicking other tabs...")
            tabs = [
                ("Meetings", "📅 Meetings"),
                ("CallHistory", "📞 Call History"),
                ("Analytics", "📈 Analytics"),
                ("Logs", "📋 Live Logs"),
            ]
            for tab_name, btn_label in tabs:
                print(f"Clicking {tab_name} tab...")
                page.locator(f"role=tab[name='{btn_label}']").click()
                page.wait_for_timeout(1000)
                page.screenshot(
                    path=str(ARTIFACT_DIR / f"dashboard_{tab_name.lower()}_tab_playwright.png")
                )

            # 5. Test Export Button
            print("Testing Export button...")
            with page.expect_download() as download_info:
                page.locator("#btn-export").click()
            download = download_info.value
            download_path = ARTIFACT_DIR / "sales-agent-export-playwright.json"
            download.save_as(str(download_path))
            print(f"Verified export. File saved to: {download_path}")

            # Stop tracing
            trace_path = ARTIFACT_DIR / "playwright_trace.zip"
            context.tracing.stop(path=str(trace_path))
            print(f"Trace saved to: {trace_path}")

            # Close browser
            browser.close()

            # Find and rename video file
            video = page.video
            if video:
                video_path = video.path()
                final_video_path = ARTIFACT_DIR / "dashboard_ui_verification.webm"
                try:
                    if os.path.exists(video_path):
                        os.replace(video_path, str(final_video_path))
                        print(f"Video saved to: {final_video_path}")
                except Exception as ve:
                    print(f"Failed to copy video file: {ve}")

            success = True
            print("Playwright UI verification script completed successfully!")

    except Exception as e:
        print(f"Playwright test failed with exception: {e}")
        import traceback

        traceback.print_exc()
    finally:
        # Terminate background processes
        print("Terminating background servers...")
        backend_proc.terminate()
        backend_proc.wait()

        # Kill npm process cleanly
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(dashboard_proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            dashboard_proc.terminate()
            dashboard_proc.wait()

        # Close log files
        backend_log.close()
        dashboard_log.close()

    # Write playwright verification results
    with open(str(ARTIFACT_DIR / "playwright_console_errors.log"), "w", encoding="utf-8") as f:
        f.write("\n".join(console_errors))
    with open(str(ARTIFACT_DIR / "playwright_console_warnings.log"), "w", encoding="utf-8") as f:
        f.write("\n".join(console_warnings))
    with open(str(ARTIFACT_DIR / "playwright_failed_requests.log"), "w", encoding="utf-8") as f:
        f.write("\n".join(failed_requests))

    print(f"Console errors collected: {len(console_errors)}")
    print(f"Console warnings collected: {len(console_warnings)}")
    print(f"Failed requests collected: {len(failed_requests)}")

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    run_ui_test()
