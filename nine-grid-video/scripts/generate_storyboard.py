#!/usr/bin/env python3
"""Generate 3x3 nine-grid storyboard image using Gemini API.

Usage:
    python generate_storyboard.py --prompt "故事提示词" --output ./output
    python generate_storyboard.py --prompt-file prompts.txt --output ./output
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()


def get_output_dir(base_output: str) -> Path:
    """Generate output directory with format: YYYYMMDD_NNN"""
    today = datetime.now().strftime("%Y%m%d")
    parent = Path(base_output)
    parent.mkdir(parents=True, exist_ok=True)

    existing = []
    for d in parent.iterdir():
        if d.is_dir() and d.name.startswith(today + "_"):
            try:
                seq = int(d.name.split("_")[1])
                existing.append(seq)
            except (IndexError, ValueError):
                pass

    next_seq = max(existing, default=0) + 1
    run_dir = parent / f"{today}_{next_seq:03d}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def generate_storyboard(client, prompt: str, aspect_ratio: str = "1:1"):
    """Generate a nine-grid storyboard image."""

    full_prompt = f"""{prompt}

Important requirements:
- Create a 3x3 grid layout (nine panels total)
- Each panel should be a distinct scene/moment
- Maintain consistent character appearance across all 9 panels
- Maintain consistent art style, lighting, and color tone
- Panels flow left-to-right, top-to-bottom (K1 to K9)
- No text, speech bubbles, or panel numbers
- Each panel should be clearly separated"""

    response = client.models.generate_content(
        model="gemini-3-pro-image-preview",
        contents=[full_prompt],
        config=types.GenerateContentConfig(
            response_modalities=["TEXT", "IMAGE"],
            image_config=types.ImageConfig(
                aspect_ratio=aspect_ratio,
            ),
        ),
    )

    for part in response.parts:
        if part.text is not None:
            print(f"Model response: {part.text[:200]}")
        elif image := part.as_image():
            return image
    return None


def main():
    parser = argparse.ArgumentParser(description="Generate nine-grid storyboard")
    parser.add_argument("--prompt", help="Storyboard prompt text")
    parser.add_argument("--prompt-file", help="Path to file containing prompt")
    parser.add_argument("--style", default="", help="Additional style description")
    parser.add_argument("--aspect-ratio", default="1:1",
                       choices=["1:1", "9:16", "16:9", "3:4", "4:3"],
                       help="Image aspect ratio")
    parser.add_argument("--output", default="./output", help="Output directory")
    args = parser.parse_args()

    if not args.prompt and not args.prompt_file:
        print("Error: Either --prompt or --prompt-file required")
        sys.exit(1)

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not set in environment")
        sys.exit(1)

    # Get prompt
    if args.prompt_file:
        with open(args.prompt_file, "r", encoding="utf-8") as f:
            prompt = f.read().strip()
    else:
        prompt = args.prompt

    # Add style if provided
    if args.style:
        prompt = f"{prompt}\n\nVisual style: {args.style}"

    print("Initializing Gemini client...")
    client = genai.Client(api_key=api_key)

    # Create output directory
    output_dir = get_output_dir(args.output)
    print(f"Output directory: {output_dir}")

    print("Generating nine-grid storyboard...")
    image = generate_storyboard(client, prompt, args.aspect_ratio)

    if image:
        output_path = output_dir / "storyboard.png"
        image.save(str(output_path))
        print(f"Saved: {output_path}")

        # Save prompt for reference
        prompt_path = output_dir / "storyboard_prompt.txt"
        with open(prompt_path, "w", encoding="utf-8") as f:
            f.write(prompt)
        print(f"Saved prompt: {prompt_path}")

        print("Done!")
        return str(output_dir)
    else:
        print("Error: Failed to generate storyboard image")
        sys.exit(1)


if __name__ == "__main__":
    main()
