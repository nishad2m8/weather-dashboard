#!/usr/bin/env python3
"""
Render windy.html to windy.jpg and convert to LVGL binary format
"""
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from PIL import Image
import struct

try:
    from playwright.async_api import async_playwright
except ModuleNotFoundError:
    async_playwright = None

LV_IMG_CF_TRUE_COLOR = 4


def rgb888_to_rgb565(r, g, b):
    """Convert RGB888 (24-bit) to RGB565 (16-bit) format"""
    # RGB565: 5 bits red, 6 bits green, 5 bits blue
    r5 = (r >> 3) & 0x1F
    g6 = (g >> 2) & 0x3F
    b5 = (b >> 3) & 0x1F
    return (r5 << 11) | (g6 << 5) | b5


def build_lvgl_header(width, height, color_format=LV_IMG_CF_TRUE_COLOR):
    """Create the 4-byte LVGL image header."""
    if width >= (1 << 11) or height >= (1 << 11):
        raise ValueError("LVGL header only supports dimensions up to 2047x2047")

    header_value = (
        (color_format & 0x1F)
        | ((width & 0x7FF) << 10)
        | ((height & 0x7FF) << 21)
    )
    return header_value.to_bytes(4, "little")


def _clamp_channel(value):
    """Clamp floating point values to the valid 0-255 range."""
    return max(0.0, min(255.0, value))


def _expand_bits(value, bits):
    """Expand 5/6-bit channel values back to the 0-255 range."""
    if bits == 5:
        return (value << 3) | (value >> 2)
    if bits == 6:
        return (value << 2) | (value >> 4)
    raise ValueError("Unsupported bit depth for RGB565 expansion")


def _quantize_channel(value, bits):
    """Convert an 8-bit value to 5/6-bit with rounding."""
    max_value = (1 << bits) - 1
    quantized = int(round((value / 255.0) * max_value))
    return max(0, min(max_value, quantized))


def convert_image_to_lvgl_bin(input_path, output_path, dithering=False, big_endian=False):
    """
    Convert image to LVGL binary format (RGB565 + LVGL header)

    Args:
        input_path: Path to input image (JPG, PNG, etc.)
        output_path: Path to output binary file
        dithering: Enable Floyd-Steinberg dithering matched to RGB565
        big_endian: Output pixel data in big-endian order. LVGL's converter
                    uses little-endian on most MCUs, so False matches it.
    """
    print(f"Converting {input_path} to LVGL binary format...")

    img = Image.open(input_path).convert('RGB')
    width, height = img.size
    pixels = img.load()

    endian_fmt = '>H' if big_endian else '<H'
    binary_data = bytearray(build_lvgl_header(width, height))

    if dithering:
        row_error = [[0.0, 0.0, 0.0] for _ in range(width)]
        for y in range(height):
            next_row_error = [[0.0, 0.0, 0.0] for _ in range(width)]
            for x in range(width):
                r, g, b = pixels[x, y]
                r_adj = _clamp_channel(r + row_error[x][0])
                g_adj = _clamp_channel(g + row_error[x][1])
                b_adj = _clamp_channel(b + row_error[x][2])

                r5 = _quantize_channel(r_adj, 5)
                g6 = _quantize_channel(g_adj, 6)
                b5 = _quantize_channel(b_adj, 5)

                rgb565 = (r5 << 11) | (g6 << 5) | b5
                binary_data.extend(struct.pack(endian_fmt, rgb565))

                quant_r = _expand_bits(r5, 5)
                quant_g = _expand_bits(g6, 6)
                quant_b = _expand_bits(b5, 5)

                err_r = r_adj - quant_r
                err_g = g_adj - quant_g
                err_b = b_adj - quant_b

                if x + 1 < width:
                    row_error[x + 1][0] += err_r * 7 / 16
                    row_error[x + 1][1] += err_g * 7 / 16
                    row_error[x + 1][2] += err_b * 7 / 16

                if y + 1 < height:
                    if x > 0:
                        next_row_error[x - 1][0] += err_r * 3 / 16
                        next_row_error[x - 1][1] += err_g * 3 / 16
                        next_row_error[x - 1][2] += err_b * 3 / 16

                    next_row_error[x][0] += err_r * 5 / 16
                    next_row_error[x][1] += err_g * 5 / 16
                    next_row_error[x][2] += err_b * 5 / 16

                    if x + 1 < width:
                        next_row_error[x + 1][0] += err_r * 1 / 16
                        next_row_error[x + 1][1] += err_g * 1 / 16
                        next_row_error[x + 1][2] += err_b * 1 / 16

            row_error = next_row_error
    else:
        for y in range(height):
            for x in range(width):
                r, g, b = pixels[x, y]
                rgb565 = rgb888_to_rgb565(r, g, b)
                binary_data.extend(struct.pack(endian_fmt, rgb565))

    with open(output_path, 'wb') as f:
        f.write(binary_data)

    print(f"Successfully converted to {output_path}")
    print(f"  Dimensions: {width}x{height}")
    print("  LVGL header: cf=TRUE_COLOR, includes width/height metadata")
    print(f"  Format: RGB565 {'(Big-endian)' if big_endian else '(Little-endian)'}")
    print(f"  Dithering: {'Enabled' if dithering else 'Disabled'}")
    print(f"  File size: {len(binary_data)} bytes (including header)")


async def render_html_to_jpg():
    """Render the windy.html file to a JPG screenshot"""
    if async_playwright is None:
        raise RuntimeError(
            "playwright is not installed. Install it with `pip install playwright` "
            "and run `playwright install` to enable HTML rendering."
        )

    async with async_playwright() as p:
        # Launch browser in headless mode
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # Set viewport size (adjust as needed for your layout)
        await page.set_viewport_size({"width": 800, "height": 480})

        # Get the path to windy.html
        html_path = Path(__file__).parent / "windy.html"
        file_url = f"file://{html_path.absolute()}"

        # Navigate to the HTML file
        await page.goto(file_url, wait_until="networkidle")

        # Wait a bit for any dynamic content to load
        await page.wait_for_timeout(2000)

        # Get current timestamp in Bahrain timezone (Asia/Bahrain)
        # Format: "DD/MM/YY, HH:MM AM"
        bahrain_tz = ZoneInfo("Asia/Bahrain")
        now = datetime.now(bahrain_tz)
        timestamp = now.strftime("%d/%m/%y, %I:%M %p")

        # Inject the render timestamp into the page
        await page.evaluate(f"""
            const timestampElement = document.getElementById('renderTimestamp');
            if (timestampElement) {{
                timestampElement.textContent = '{timestamp}';
            }}
        """)

        # Take screenshot and save as JPG
        jpg_output = "windy.jpg"
        await page.screenshot(
            path=jpg_output,
            type="jpeg",
            quality=100,
            full_page=False
        )

        await browser.close()
        print(f"Successfully rendered windy.html to {jpg_output}")

    # Convert JPG to LVGL binary format
    bin_output = "windy.bin"
    convert_image_to_lvgl_bin(
        input_path=jpg_output,
        output_path=bin_output,
        dithering=False,
        big_endian=False
    )


if __name__ == "__main__":
    asyncio.run(render_html_to_jpg())
