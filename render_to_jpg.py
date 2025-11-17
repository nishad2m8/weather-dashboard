#!/usr/bin/env python3
"""
Render index.html to index.jpg using Playwright
"""
import asyncio
from playwright.async_api import async_playwright
from pathlib import Path


async def render_html_to_jpg():
    """Render the index.html file to a JPG screenshot"""
    async with async_playwright() as p:
        # Launch browser in headless mode
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # Set viewport size (adjust as needed for your layout)
        await page.set_viewport_size({"width": 800, "height": 480})

        # Get the path to index.html
        html_path = Path(__file__).parent / "index.html"
        file_url = f"file://{html_path.absolute()}"

        # Navigate to the HTML file
        await page.goto(file_url, wait_until="networkidle")

        # Wait a bit for any dynamic content to load
        await page.wait_for_timeout(2000)

        # Take screenshot and save as JPG
        await page.screenshot(
            path="index.jpg",
            type="jpeg",
            quality=100,
            full_page=False
        )

        await browser.close()
        print("Successfully rendered index.html to index.jpg")


if __name__ == "__main__":
    asyncio.run(render_html_to_jpg())
