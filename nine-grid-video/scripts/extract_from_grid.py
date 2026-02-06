#!/usr/bin/env python3
"""Extract and upscale specific panels directly from a 3x3 grid image.

Method B: Directly extract and upscale panels from the full grid image
without pre-cropping. Uses Gemini to identify and recreate each panel
as a standalone 2K image.

Usage:
    python extract_from_grid.py --grid ./storyboard.png --output ./frames_hd
    python extract_from_grid.py --grid ./storyboard.png --output ./frames_hd --parallel 9
"""

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

from dotenv import load_dotenv
from google import genai
from google.genai import types
from PIL import Image

load_dotenv()

print_lock = Lock()

PANEL_POSITIONS = {
    "K1": "top-left",
    "K2": "top-center",
    "K3": "top-right",
    "K4": "middle-left",
    "K5": "center",
    "K6": "middle-right",
    "K7": "bottom-left",
    "K8": "bottom-center",
    "K9": "bottom-right",
}


def safe_print(msg: str):
    """Thread-safe print."""
    with print_lock:
        print(msg, flush=True)


def extract_panel_from_grid(client, grid_image: Image.Image, panel_name: str, output_path: str) -> bool:
    """Extract and upscale a specific panel from the grid image. Returns True on success."""
    position = PANEL_POSITIONS.get(panel_name, "unknown")

    # v5 提示词 - 简单直接的分步指令
    prompt = f"""This image contains a 3x3 grid of 9 storyboard panels.

I want you to create a NEW single image based on the {position} panel only.

Instructions:
1. Find the {position} panel in the grid (this is {panel_name})
2. Look at what's happening in that specific panel
3. Create a brand new 2K image (2048x2048) showing ONLY that scene
4. The new image should NOT be a grid - just one scene filling the whole canvas
5. Remove any "{panel_name}" text label
6. Keep the same character, pose, colors, and art style

IMPORTANT: Your output must be a single scene, not a grid of panels."""

    try:
        response = client.models.generate_content(
            model="gemini-3-pro-image-preview",
            contents=[prompt, grid_image],
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                image_config=types.ImageConfig(
                    aspect_ratio="1:1",
                    image_size="2K",  # 输出 2048x2048
                ),
            ),
        )

        for part in response.parts:
            if part.inline_data and part.inline_data.mime_type.startswith("image/"):
                # 直接保存二进制数据
                with open(output_path, "wb") as f:
                    f.write(part.inline_data.data)
                return True

        return False

    except Exception as e:
        safe_print(f"[{panel_name}] Error: {e}")
        return False


def extract_panel_task(client, grid_image: Image.Image, panel_name: str, output_path: str) -> dict:
    """Task function for parallel extraction."""
    safe_print(f"[{panel_name}] Extracting from grid...")

    try:
        success = extract_panel_from_grid(client, grid_image, panel_name, output_path)

        if success and os.path.exists(output_path):
            saved_img = Image.open(output_path)
            safe_print(f"[{panel_name}]   Output size: {saved_img.size}")
            saved_img.close()
            safe_print(f"[{panel_name}]   Saved: {output_path}")
            return {"name": panel_name, "status": "success", "path": output_path}
        else:
            safe_print(f"[{panel_name}]   Failed to extract")
            return {"name": panel_name, "status": "failed", "error": "No image generated"}

    except Exception as e:
        safe_print(f"[{panel_name}]   Error: {e}")
        return {"name": panel_name, "status": "failed", "error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="Extract panels directly from grid image")
    parser.add_argument("--grid", required=True, help="Path to the 3x3 grid storyboard image")
    parser.add_argument("--output", required=True, help="Output directory for extracted panels")
    parser.add_argument("--panels", default="K1,K2,K3,K4,K5,K6,K7,K8,K9",
                       help="Comma-separated list of panels to extract (default: all)")
    parser.add_argument("--parallel", type=int, default=9,
                       help="Max parallel tasks (default: 9)")
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not set in environment")
        sys.exit(1)

    if not os.path.exists(args.grid):
        print(f"Error: Grid image not found: {args.grid}")
        sys.exit(1)

    os.makedirs(args.output, exist_ok=True)

    print("Initializing Gemini client...")
    client = genai.Client(api_key=api_key)

    # Load grid image once
    grid_image = Image.open(args.grid)
    print(f"Grid image size: {grid_image.size}")

    # Parse panels to extract
    panels = [p.strip().upper() for p in args.panels.split(",")]
    valid_panels = [p for p in panels if p in PANEL_POSITIONS]

    if not valid_panels:
        print(f"Error: No valid panels specified. Use K1-K9.")
        sys.exit(1)

    print(f"\n=== Extracting {len(valid_panels)} panels in parallel (max {args.parallel} workers) ===\n")

    results = []

    with ThreadPoolExecutor(max_workers=args.parallel) as executor:
        futures = []
        for panel in valid_panels:
            output_path = os.path.join(args.output, f"{panel}.png")
            future = executor.submit(
                extract_panel_task,
                client,
                grid_image,
                panel,
                output_path
            )
            futures.append(future)

        for future in as_completed(futures):
            result = future.result()
            results.append(result)

    success_count = sum(1 for r in results if r.get("status") == "success")
    print(f"\n{success_count}/{len(valid_panels)} panels extracted successfully")
    print(f"Output directory: {args.output}")
    print("Done!")


if __name__ == "__main__":
    main()
