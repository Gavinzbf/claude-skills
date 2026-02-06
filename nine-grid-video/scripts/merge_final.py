#!/usr/bin/env python3
"""Merge video segments and audio narrations into final video.

Uses ffmpeg to:
1. Add audio narration to each video segment
2. Concatenate all segments into final video

Usage:
    python merge_final.py --videos ./videos --audio ./audio --output final.mp4
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path


def get_video_duration(video_path: str) -> float:
    """Get video duration in seconds using ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        return float(result.stdout.strip())
    return 0.0


def add_audio_to_video(video_path: str, audio_path: str, output_path: str) -> bool:
    """Add audio track to video, adjusting audio to fit video duration."""
    # Get video duration
    video_duration = get_video_duration(video_path)

    if os.path.exists(audio_path):
        # Mix video with audio, fade audio if needed
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", audio_path,
            "-c:v", "copy",
            "-c:a", "aac",
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-shortest",
            output_path
        ]
    else:
        # No audio, just copy video
        cmd = ["ffmpeg", "-y", "-i", video_path, "-c", "copy", output_path]

    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0


def concatenate_videos(video_files: list, output_path: str) -> bool:
    """Concatenate multiple videos using ffmpeg concat demuxer."""
    if len(video_files) == 0:
        print("Error: No videos to concatenate")
        return False

    if len(video_files) == 1:
        # Just copy the single video
        import shutil
        shutil.copy(video_files[0], output_path)
        return True

    # Create concat list file
    concat_list_path = output_path.replace(".mp4", "_concat_list.txt")
    with open(concat_list_path, "w", encoding="utf-8") as f:
        for vf in video_files:
            # Use absolute path and escape single quotes
            abs_path = os.path.abspath(vf).replace("'", "'\\''")
            f.write(f"file '{abs_path}'\n")

    # Try stream copy first (faster, but may fail if formats differ)
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_list_path,
        "-c", "copy",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print("Stream copy failed, retrying with re-encoding...")
        # Re-encode to ensure compatibility
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_list_path,
            "-c:v", "libx264",
            "-c:a", "aac",
            "-shortest",
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)

    # Cleanup
    if os.path.exists(concat_list_path):
        os.remove(concat_list_path)

    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description="Merge videos and audio into final video")
    parser.add_argument("--videos", required=True, help="Directory with video segments")
    parser.add_argument("--audio", help="Directory with audio files (optional)")
    parser.add_argument("--output", required=True, help="Output final video path")
    parser.add_argument("--no-audio", action="store_true", help="Skip audio merging")
    args = parser.parse_args()

    # Check ffmpeg
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("Error: ffmpeg not found. Please install ffmpeg first.")
        sys.exit(1)

    # Find video files
    video_dir = Path(args.videos)
    video_files = sorted(video_dir.glob("scene_*.mp4"))

    if not video_files:
        print(f"Error: No scene_*.mp4 files found in {args.videos}")
        sys.exit(1)

    print(f"Found {len(video_files)} video segments")

    # Create temp directory for processed videos
    temp_dir = Path(args.output).parent / "temp_merge"
    temp_dir.mkdir(parents=True, exist_ok=True)

    processed_videos = []

    # Process each video segment
    for i, video_path in enumerate(video_files):
        scene_name = video_path.stem  # e.g., "scene_01"
        print(f"\n[{i+1}/{len(video_files)}] Processing {scene_name}...")

        if args.no_audio or not args.audio:
            # No audio processing, use original video
            processed_videos.append(str(video_path))
            print(f"  Using original video (no audio)")
        else:
            # Try to find matching audio file
            audio_path = Path(args.audio) / f"{scene_name}.mp3"
            output_path = temp_dir / f"{scene_name}_with_audio.mp4"

            if add_audio_to_video(str(video_path), str(audio_path), str(output_path)):
                processed_videos.append(str(output_path))
                print(f"  Added audio: {audio_path.name if audio_path.exists() else 'none'}")
            else:
                print(f"  Warning: Failed to process, using original")
                processed_videos.append(str(video_path))

    # Concatenate all videos
    print(f"\nConcatenating {len(processed_videos)} videos...")
    if concatenate_videos(processed_videos, args.output):
        print(f"\nFinal video saved: {args.output}")

        # Cleanup temp directory
        import shutil
        if temp_dir.exists():
            shutil.rmtree(temp_dir)

        print("Done!")
    else:
        print("Error: Failed to concatenate videos")
        sys.exit(1)


if __name__ == "__main__":
    main()
