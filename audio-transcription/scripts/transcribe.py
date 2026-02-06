#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Audio Transcription Script
使用云雾AI Whisper API将音频/视频文件转换为文字
"""

import argparse
import os
import sys
import requests


def load_env_file(env_path=None):
    """从 .env 文件加载环境变量"""
    if env_path is None:
        # 查找 .env 文件：当前目录 -> 父目录 -> 项目根目录
        search_paths = [
            os.path.join(os.getcwd(), ".env"),
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
        ]
        for path in search_paths:
            if os.path.exists(path):
                env_path = path
                break

    if env_path and os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key not in os.environ:
                        os.environ[key] = value


# 加载 .env 文件
load_env_file()


def transcribe(file_path, api_key, language=None, model="whisper-1", prompt=None):
    """
    调用云雾AI Whisper API进行音频转录

    Args:
        file_path: 音频/视频文件路径
        api_key: 云雾AI API Key
        language: 语言代码 (如 zh, en)，可选
        model: 模型名称，默认 whisper-1
        prompt: 提示词，可选

    Returns:
        转录的文本内容
    """
    url = "https://yunwu.ai/v1/audio/transcriptions"
    headers = {"Authorization": f"Bearer {api_key}"}

    if not os.path.exists(file_path):
        print(f"Error: File not found: {file_path}", file=sys.stderr)
        sys.exit(1)

    file_size = os.path.getsize(file_path)
    print(f"File: {file_path}")
    print(f"Size: {file_size / 1024 / 1024:.2f} MB")
    print(f"Model: {model}")
    if language:
        print(f"Language: {language}")
    print("Transcribing...")

    try:
        with open(file_path, "rb") as f:
            files = {"file": (os.path.basename(file_path), f)}
            data = {"model": model, "response_format": "json"}

            if language:
                data["language"] = language
            if prompt:
                data["prompt"] = prompt

            response = requests.post(url, headers=headers, files=files, data=data, timeout=300)
            response.raise_for_status()

            result = response.json()
            text = result.get("text", "")

            return text

    except requests.exceptions.Timeout:
        print("Error: Request timed out", file=sys.stderr)
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"Error: API request failed: {e}", file=sys.stderr)
        if hasattr(e, 'response') and e.response is not None:
            print(f"Response: {e.response.text}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Audio/Video transcription using Yunwu AI Whisper API"
    )
    parser.add_argument(
        "--file", "-f",
        required=True,
        help="Path to audio/video file (mp3, wav, m4a, mp4, flac, ogg, webm)"
    )
    parser.add_argument(
        "--api-key", "-k",
        default=os.environ.get("YUNWU_API_KEY"),
        help="Yunwu AI API Key (default: YUNWU_API_KEY env var)"
    )
    parser.add_argument(
        "--language", "-l",
        help="Language code (e.g., zh, en). Auto-detect if not specified"
    )
    parser.add_argument(
        "--model", "-m",
        default="whisper-1",
        choices=["whisper-1", "gpt-4o-mini-transcribe"],
        help="Model to use (default: whisper-1)"
    )
    parser.add_argument(
        "--prompt", "-p",
        help="Optional prompt to guide the transcription style"
    )
    parser.add_argument(
        "--output", "-o",
        help="Output file path (default: print to stdout)"
    )
    parser.add_argument(
        "--env",
        help="Path to .env file"
    )

    args = parser.parse_args()

    # 如果指定了 .env 文件，重新加载
    if args.env:
        load_env_file(args.env)
        if not args.api_key:
            args.api_key = os.environ.get("YUNWU_API_KEY")

    if not args.api_key:
        print("Error: API key required. Set YUNWU_API_KEY env var or use --api-key", file=sys.stderr)
        sys.exit(1)

    text = transcribe(
        file_path=args.file,
        api_key=args.api_key,
        language=args.language,
        model=args.model,
        prompt=args.prompt
    )

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"\nTranscription saved to: {args.output}")
    else:
        print("\n--- Transcription ---")
        print(text)

    return text


if __name__ == "__main__":
    main()
