#!/usr/bin/env python3
"""Generate videos using Yunwu API with first/last frame references.

Uses parallel generation: all videos are submitted simultaneously and polled concurrently.

Usage:
    python generate_videos.py --frames ./frames --prompts video_prompts.json --output ./videos
    python generate_videos.py --frames ./frames --prompts video_prompts.json --output ./videos --parallel 4
"""

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://yunwu.ai"
print_lock = Lock()


def safe_print(msg: str):
    """Thread-safe print."""
    with print_lock:
        print(msg)


def create_video(api_key: str, prompt: str, first_frame_path: str,
                model: str = "veo_3_1-fast", seconds: str = "8",
                size: str = "9x16") -> dict:
    """Create a video generation task with first frame reference."""
    url = f"{BASE_URL}/v1/videos"
    headers = {"Authorization": f"Bearer {api_key}"}

    with open(first_frame_path, "rb") as f:
        files = {
            "input_reference": (os.path.basename(first_frame_path), f, "image/png"),
        }
        data = {
            "model": model,
            "prompt": prompt,
            "seconds": seconds,
            "size": size,
            "watermark": "false",
        }
        response = requests.post(url, headers=headers, data=data, files=files)

    response.raise_for_status()
    return response.json()


def query_status(api_key: str, video_id: str) -> dict:
    """Query video generation status."""
    url = f"{BASE_URL}/v1/videos/{video_id}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()


def download_video(video_url: str, output_path: str) -> bool:
    """Download completed video from URL."""
    response = requests.get(video_url, stream=True)
    response.raise_for_status()
    with open(output_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    return True


def submit_video_task(api_key: str, name: str, prompt: str, first_frame_path: str,
                      output_path: str, model: str = "veo_3_1-fast") -> dict:
    """Submit a video generation task and return task info."""
    try:
        safe_print(f"[{name}] Submitting task...")
        safe_print(f"[{name}]   First frame: {first_frame_path}")

        result = create_video(api_key, prompt, first_frame_path, model=model)
        video_id = result.get("id")
        if not video_id:
            safe_print(f"[{name}]   Error: No video ID returned: {result}")
            return {"name": name, "status": "failed", "error": "No video ID"}

        safe_print(f"[{name}]   Task created: {video_id}")
        return {
            "name": name,
            "video_id": video_id,
            "output_path": output_path,
            "status": "submitted"
        }

    except Exception as e:
        safe_print(f"[{name}]   Submit error: {e}")
        return {"name": name, "status": "failed", "error": str(e)}


def poll_and_download(api_key: str, task: dict) -> dict:
    """Poll a single task until completion and download the video."""
    name = task["name"]
    video_id = task["video_id"]
    output_path = task["output_path"]

    try:
        while True:
            time.sleep(15)
            status_result = query_status(api_key, video_id)
            status = status_result.get("status", "")

            if status == "completed":
                video_url = status_result.get("video_url")
                safe_print(f"[{name}] Completed! Downloading...")
                download_video(video_url, output_path)
                safe_print(f"[{name}] Saved: {output_path}")
                return {"name": name, "status": "success", "path": output_path}

            elif status in ("queued", "pending", "processing", "in_progress"):
                progress = status_result.get("progress", 0)
                safe_print(f"[{name}] Status: {status}, progress: {progress}%")

            elif status == "failed":
                safe_print(f"[{name}] Task failed: {status_result}")
                return {"name": name, "status": "failed", "error": status_result}

            else:
                progress = status_result.get("progress", 0)
                safe_print(f"[{name}] Status: {status}, progress: {progress}%")

    except Exception as e:
        safe_print(f"[{name}] Poll error: {e}")
        return {"name": name, "status": "failed", "error": str(e)}


def generate_videos_parallel(api_key: str, tasks_info: list, model: str,
                            max_workers: int = 8) -> list:
    """Generate all videos in parallel.

    Phase 1: Submit all tasks concurrently
    Phase 2: Poll and download all tasks concurrently
    """
    results = []
    submitted_tasks = []

    # Phase 1: Submit all tasks in parallel
    safe_print(f"\n=== Phase 1: Submitting {len(tasks_info)} tasks in parallel ===\n")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for info in tasks_info:
            future = executor.submit(
                submit_video_task,
                api_key,
                info["name"],
                info["prompt"],
                info["first_frame_path"],
                info["output_path"],
                model
            )
            futures.append(future)

        for future in as_completed(futures):
            result = future.result()
            if result.get("status") == "submitted":
                submitted_tasks.append(result)
            else:
                results.append(result)

    safe_print(f"\n=== Phase 2: Polling {len(submitted_tasks)} tasks in parallel ===\n")

    # Phase 2: Poll all submitted tasks in parallel
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for task in submitted_tasks:
            future = executor.submit(poll_and_download, api_key, task)
            futures.append(future)

        for future in as_completed(futures):
            result = future.result()
            results.append(result)

    return results


def generate_single_video(api_key: str, prompt: str, first_frame_path: str,
                         output_path: str, model: str = "veo_3_1-fast") -> bool:
    """Generate a single video and wait for completion (legacy serial mode)."""
    try:
        print(f"  First frame: {first_frame_path}")

        result = create_video(api_key, prompt, first_frame_path, model=model)
        video_id = result.get("id")
        if not video_id:
            print(f"  Error: No video ID returned: {result}")
            return False

        print(f"  Task created: {video_id}")

        # Poll for completion
        while True:
            time.sleep(15)
            status_result = query_status(api_key, video_id)
            status = status_result.get("status", "")

            if status == "completed":
                video_url = status_result.get("video_url")
                print(f"  Completed! Downloading...")
                download_video(video_url, output_path)
                print(f"  Saved: {output_path}")
                return True
            elif status in ("queued", "pending", "processing", "in_progress"):
                progress = status_result.get("progress", 0)
                print(f"  Status: {status}, progress: {progress}%")
            elif status == "failed":
                print(f"  Task failed: {status_result}")
                return False
            else:
                progress = status_result.get("progress", 0)
                print(f"  Status: {status}, progress: {progress}%")

    except Exception as e:
        print(f"  Error: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Generate videos using Yunwu API")
    parser.add_argument("--frames", required=True, help="Directory with frame images (K1.png - K9.png)")
    parser.add_argument("--prompts", required=True, help="Path to video_prompts.json")
    parser.add_argument("--output", required=True, help="Output directory for videos")
    parser.add_argument("--model", default="veo_3_1-fast",
                       choices=["veo_3_1", "veo_3_1-fast"],
                       help="Model to use")
    parser.add_argument("--parallel", type=int, default=8,
                       help="Max parallel tasks (default: 8, use 1 for serial mode)")
    args = parser.parse_args()

    api_key = os.environ.get("YUNWU_API_KEY")
    if not api_key:
        print("Error: YUNWU_API_KEY not set in environment")
        sys.exit(1)

    os.makedirs(args.output, exist_ok=True)

    with open(args.prompts, "r", encoding="utf-8") as f:
        prompts = json.load(f)

    total = len(prompts)

    # Check for HD frames directory (prioritize if exists)
    frames_dir = args.frames
    hd_frames_dir = args.frames + "_hd"
    if os.path.exists(hd_frames_dir):
        frames_dir = hd_frames_dir
        print(f"Using HD frames directory: {hd_frames_dir}")
    else:
        print(f"Using frames directory: {frames_dir}")

    # Prepare task info
    tasks_info = []
    for i, item in enumerate(prompts):
        name = item["name"]
        prompt = item["prompt"]
        first_frame = item.get("first_frame", f"K{i+1}.png")
        first_path = os.path.join(frames_dir, first_frame)

        if not os.path.exists(first_path):
            print(f"Warning: First frame not found: {first_path}, skipping {name}")
            continue

        output_path = os.path.join(args.output, f"{name}.mp4")
        tasks_info.append({
            "name": name,
            "prompt": prompt,
            "first_frame_path": first_path,
            "output_path": output_path
        })

    if args.parallel == 1:
        # Serial mode (legacy behavior)
        print("Running in serial mode...")
        video_files = []
        for i, info in enumerate(tasks_info):
            print(f"\n[{i+1}/{total}] Generating {info['name']}...")
            success = generate_single_video(
                api_key, info["prompt"], info["first_frame_path"],
                info["output_path"], model=args.model
            )
            if success and os.path.exists(info["output_path"]):
                video_files.append(info["output_path"])
        success_count = len(video_files)
    else:
        # Parallel mode (default)
        print(f"Running in parallel mode (max {args.parallel} workers)...")
        results = generate_videos_parallel(api_key, tasks_info, args.model, args.parallel)
        success_count = sum(1 for r in results if r.get("status") == "success")

    print(f"\n{success_count}/{total} videos generated successfully")
    print("Done!")


if __name__ == "__main__":
    main()
