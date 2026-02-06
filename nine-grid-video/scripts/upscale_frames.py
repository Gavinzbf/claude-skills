#!/usr/bin/env python3
"""Upscale frame images to 2K resolution using Gemini image-to-image.

Takes low-resolution cropped frames and generates high-resolution 2K versions
while removing text markers (K1, K2, etc.) and maintaining style consistency.

Usage:
    python upscale_frames.py --input ./frames --output ./frames_hd
    python upscale_frames.py --input ./frames --output ./frames_hd --parallel 9
"""

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

from dotenv import load_dotenv
from google import genai
from google.genai import types
from PIL import Image

load_dotenv()

print_lock = Lock()


def safe_print(msg: str):
    """Thread-safe print."""
    with print_lock:
        print(msg, flush=True)


def upscale_single_frame(client, low_res_image: Image.Image, frame_name: str) -> Image.Image | None:
    """Upscale a single frame to 2K resolution using Gemini.

    Args:
        client: Gemini client
        low_res_image: Low resolution PIL Image
        frame_name: Frame name (e.g., "K1") for logging

    Returns:
        High resolution PIL Image or None if failed
    """
    prompt = f"""Recreate this image at 2K resolution (2048x2048 pixels).

Core requirements:
1. Preserve all visual elements exactly: characters, poses, expressions, background
2. Remove any text labels or markers (like "{frame_name}") - fill with surrounding content
3. Enhance clarity and detail while maintaining the original artistic style
4. Keep identical color tones and lighting

Reference: This is frame {frame_name} from a storyboard sequence."""

    try:
        response = client.models.generate_content(
            model="gemini-3-pro-image-preview",
            contents=[prompt, low_res_image],
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                image_config=types.ImageConfig(
                    aspect_ratio="1:1",
                    image_size="2K",  # 输出 2048x2048
                ),
            ),
        )

        for part in response.parts:
            if image := part.as_image():
                return image

        return None

    except Exception as e:
        safe_print(f"[{frame_name}] Error: {e}")
        return None


def upscale_frame_task(client, input_path: str, output_path: str, frame_name: str) -> dict:
    """Task function for parallel upscaling."""
    safe_print(f"[{frame_name}] Upscaling...")

    try:
        # Load low-res image
        low_res_img = Image.open(input_path)
        safe_print(f"[{frame_name}]   Input size: {low_res_img.size}")

        # Upscale with Gemini
        high_res_img = upscale_single_frame(client, low_res_img, frame_name)

        if high_res_img:
            high_res_img.save(output_path)
            # Get actual output size
            saved_img = Image.open(output_path)
            safe_print(f"[{frame_name}]   Output size: {saved_img.size}")
            safe_print(f"[{frame_name}]   Saved: {output_path}")
            return {"name": frame_name, "status": "success", "path": output_path}
        else:
            safe_print(f"[{frame_name}]   Failed to generate")
            return {"name": frame_name, "status": "failed", "error": "No image generated"}

    except Exception as e:
        safe_print(f"[{frame_name}]   Error: {e}")
        return {"name": frame_name, "status": "failed", "error": str(e)}


def upscale_frames_parallel(client, input_dir: str, output_dir: str, max_workers: int = 9) -> list:
    """Upscale all frames in parallel.

    Args:
        client: Gemini client
        input_dir: Directory containing K1.png - K9.png
        output_dir: Output directory for upscaled frames
        max_workers: Maximum parallel tasks

    Returns:
        List of result dicts
    """
    os.makedirs(output_dir, exist_ok=True)

    # Find all frame files
    frame_files = []
    for i in range(1, 10):
        frame_name = f"K{i}"
        input_path = os.path.join(input_dir, f"{frame_name}.png")
        if os.path.exists(input_path):
            output_path = os.path.join(output_dir, f"{frame_name}.png")
            frame_files.append({
                "name": frame_name,
                "input": input_path,
                "output": output_path
            })

    if not frame_files:
        print(f"Error: No frame files (K1.png - K9.png) found in {input_dir}")
        return []

    print(f"\n=== Upscaling {len(frame_files)} frames to 2K in parallel (max {max_workers} workers) ===\n")

    results = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for frame in frame_files:
            future = executor.submit(
                upscale_frame_task,
                client,
                frame["input"],
                frame["output"],
                frame["name"]
            )
            futures.append(future)

        for future in as_completed(futures):
            result = future.result()
            results.append(result)

    return results


def main():
    parser = argparse.ArgumentParser(description="Upscale frame images to 2K resolution")
    parser.add_argument("--input", required=True, help="Input directory with K1.png - K9.png")
    parser.add_argument("--output", required=True, help="Output directory for upscaled frames")
    parser.add_argument("--parallel", type=int, default=9,
                       help="Max parallel tasks (default: 9)")
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not set in environment")
        sys.exit(1)

    if not os.path.exists(args.input):
        print(f"Error: Input directory not found: {args.input}")
        sys.exit(1)

    print("Initializing Gemini client...")
    client = genai.Client(api_key=api_key)

    results = upscale_frames_parallel(client, args.input, args.output, args.parallel)

    success_count = sum(1 for r in results if r.get("status") == "success")
    total = len(results)

    print(f"\n{success_count}/{total} frames upscaled successfully")
    print(f"Output directory: {args.output}")
    print("Done!")


if __name__ == "__main__":
    main()
