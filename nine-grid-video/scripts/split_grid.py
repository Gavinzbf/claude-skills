#!/usr/bin/env python3
"""Split a 3x3 nine-grid storyboard image into 9 individual frames.

Usage:
    python split_grid.py --input storyboard.png --output ./frames
"""

import argparse
import os
import sys
from pathlib import Path

from PIL import Image


def split_grid(input_path: str, output_dir: str, grid_size: tuple = (3, 3)):
    """Split a grid image into individual panels.

    Args:
        input_path: Path to the nine-grid storyboard image
        output_dir: Directory to save individual frames
        grid_size: Tuple of (columns, rows), default (3, 3)

    Returns:
        List of paths to saved frames
    """
    img = Image.open(input_path)
    width, height = img.size
    cols, rows = grid_size

    panel_width = width // cols
    panel_height = height // rows

    os.makedirs(output_dir, exist_ok=True)

    saved_paths = []
    frame_num = 1

    for row in range(rows):
        for col in range(cols):
            left = col * panel_width
            upper = row * panel_height
            right = left + panel_width
            lower = upper + panel_height

            panel = img.crop((left, upper, right, lower))
            output_path = os.path.join(output_dir, f"K{frame_num}.png")
            panel.save(output_path)
            saved_paths.append(output_path)
            print(f"Saved: K{frame_num}.png ({panel_width}x{panel_height})")
            frame_num += 1

    return saved_paths


def main():
    parser = argparse.ArgumentParser(description="Split nine-grid storyboard into frames")
    parser.add_argument("--input", required=True, help="Path to storyboard image")
    parser.add_argument("--output", required=True, help="Output directory for frames")
    parser.add_argument("--cols", type=int, default=3, help="Number of columns (default: 3)")
    parser.add_argument("--rows", type=int, default=3, help="Number of rows (default: 3)")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Error: Input file not found: {args.input}")
        sys.exit(1)

    print(f"Splitting {args.input} into {args.cols}x{args.rows} grid...")
    paths = split_grid(args.input, args.output, (args.cols, args.rows))

    print(f"\nSplit complete! {len(paths)} frames saved to {args.output}")

    # Generate video prompts template
    prompts_path = os.path.join(os.path.dirname(args.output), "video_prompts.json")
    if not os.path.exists(prompts_path):
        import json
        prompts = []
        for i in range(1, len(paths)):
            prompts.append({
                "name": f"scene_{i:02d}",
                "prompt": f"Starting from the scene in frame K{i}, smoothly transition to the scene of K{i+1}. Camera slowly moves, character performs subtle action.",
                "first_frame": f"K{i}.png"
            })
        with open(prompts_path, "w", encoding="utf-8") as f:
            json.dump(prompts, f, indent=2, ensure_ascii=False)
        print(f"Generated video prompts template: {prompts_path}")


if __name__ == "__main__":
    main()
