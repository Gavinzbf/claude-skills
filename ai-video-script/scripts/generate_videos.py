"""
Veo 3.1 Fast 批量生视频脚本
使用首尾帧图片生成视频片段。

用法：
    python generate_videos.py --prompts prompts.json --images ./output/images --output ./output/videos

prompts.json 格式：
[
    {"name": "video1", "prompt": "...", "first_frame": "scene1_first.png", "last_frame": "scene1_last.png"},
    {"name": "video2", "prompt": "...", "first_frame": "scene2_first.png", "last_frame": "scene2_last.png"},
    ...
]
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

def load_api_key():
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key
    env_file = Path(__file__).resolve().parents[4] / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("GEMINI_API_KEY="):
                return line.split("=", 1)[1].strip()
    print("Error: GEMINI_API_KEY not found. Set it in .env or environment variable.")
    sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Veo 3.1 Fast batch video generation")
    parser.add_argument("--prompts", required=True, help="Path to prompts JSON file")
    parser.add_argument("--images", required=True, help="Directory containing first/last frame images")
    parser.add_argument("--output", required=True, help="Output directory for videos")
    parser.add_argument("--model", default="veo-3.1-fast-generate-preview", help="Model name")
    parser.add_argument("--poll-interval", type=int, default=10, help="Polling interval in seconds")
    args = parser.parse_args()

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        print("Error: google-genai package not installed. Run: pip install google-genai")
        sys.exit(1)

    try:
        from PIL import Image
    except ImportError:
        print("Error: Pillow package not installed. Run: pip install Pillow")
        sys.exit(1)

    api_key = load_api_key()
    client = genai.Client(api_key=api_key)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    images_dir = Path(args.images)

    with open(args.prompts, "r", encoding="utf-8") as f:
        prompts = json.load(f)

    print(f"Generating {len(prompts)} videos with model {args.model}...")

    for i, item in enumerate(prompts):
        name = item["name"]
        prompt_text = item["prompt"]
        first_frame_path = images_dir / item["first_frame"]
        last_frame_path = images_dir / item["last_frame"]
        output_path = output_dir / f"{name}.mp4"

        print(f"\n[{i+1}/{len(prompts)}] Generating: {name}")

        if not first_frame_path.exists():
            print(f"  Error: First frame not found: {first_frame_path}")
            continue
        if not last_frame_path.exists():
            print(f"  Error: Last frame not found: {last_frame_path}")
            continue

        first_image = Image.open(first_frame_path)
        last_image = Image.open(last_frame_path)

        try:
            print(f"  Submitting generation request...")
            operation = client.models.generate_videos(
                model=args.model,
                prompt=prompt_text,
                image=first_image,
                config=types.GenerateVideosConfig(
                    last_frame=last_image
                ),
            )

            print(f"  Waiting for completion...", end="", flush=True)
            while not operation.done:
                print(".", end="", flush=True)
                time.sleep(args.poll_interval)
                operation = client.operations.get(operation)

            print()

            if operation.response and operation.response.generated_videos:
                video = operation.response.generated_videos[0]
                client.files.download(file=video.video)
                video.video.save(str(output_path))
                print(f"  Saved: {output_path}")
            else:
                print(f"  Warning: No video generated for {name}")

        except Exception as e:
            print(f"  Error generating {name}: {e}")

    print(f"\nDone! Videos saved to: {output_dir}")

if __name__ == "__main__":
    main()
