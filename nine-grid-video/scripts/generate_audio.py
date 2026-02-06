#!/usr/bin/env python3
"""Generate audio narration using ElevenLabs TTS API.

Usage:
    python generate_audio.py --narration narration.json --voice "voice_id" --output ./audio
"""

import argparse
import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

ELEVENLABS_API_URL = "https://api.elevenlabs.io/v1"

# Some common voice IDs for reference
VOICE_IDS = {
    "rachel": "21m00Tcm4TlvDq8ikWAM",  # American female
    "drew": "29vD33N1CtxCmqQRPOHJ",    # American male
    "clyde": "2EiwWnXFnvU5JabPnv8n",   # American male (deep)
    "domi": "AZnzlk1XvdvUeBnXmlld",    # American female (young)
    "bella": "EXAVITQu4vr4xnSDxMaL",   # American female
    "antoni": "ErXwobaYiN019PkySvjV",  # American male
    "elli": "MF3mGyEYCl7XYWbV9V6O",    # American female (young)
    "josh": "TxGEqnHWrfWFTfGW9XjX",    # American male (young)
    "arnold": "VR6AewLTigWG4xSOukaG",  # American male (deep)
    "adam": "pNInz6obpgDQGcFmaJgB",    # American male
    "sam": "yoZ06aMxZJJ28mfd3POQ",     # American male (narrational)
}


def text_to_speech(api_key: str, text: str, voice_id: str, output_path: str,
                  model_id: str = "eleven_multilingual_v2") -> bool:
    """Convert text to speech using ElevenLabs API."""
    url = f"{ELEVENLABS_API_URL}/text-to-speech/{voice_id}"

    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": api_key,
    }

    data = {
        "text": text,
        "model_id": model_id,
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
            "style": 0.0,
            "use_speaker_boost": True
        }
    }

    response = requests.post(url, json=data, headers=headers)

    if response.status_code == 200:
        with open(output_path, "wb") as f:
            f.write(response.content)
        return True
    else:
        print(f"  Error: {response.status_code} - {response.text}")
        return False


def get_voices(api_key: str) -> list:
    """Get list of available voices."""
    url = f"{ELEVENLABS_API_URL}/voices"
    headers = {"xi-api-key": api_key}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json().get("voices", [])
    return []


def main():
    parser = argparse.ArgumentParser(description="Generate audio from narration")
    parser.add_argument("--narration", required=True, help="Path to narration.json")
    parser.add_argument("--voice", default="sam", help="Voice ID or name (default: sam)")
    parser.add_argument("--model", default="eleven_multilingual_v2",
                       help="TTS model (default: eleven_multilingual_v2)")
    parser.add_argument("--output", required=True, help="Output directory for audio files")
    parser.add_argument("--list-voices", action="store_true", help="List available voices and exit")
    args = parser.parse_args()

    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        print("Error: ELEVENLABS_API_KEY not set in environment")
        sys.exit(1)

    if args.list_voices:
        print("Fetching available voices...")
        voices = get_voices(api_key)
        print("\nAvailable voices:")
        for v in voices:
            print(f"  {v['voice_id']}: {v['name']} ({v.get('labels', {}).get('accent', 'unknown')})")
        print("\nBuilt-in voice shortcuts:")
        for name, vid in VOICE_IDS.items():
            print(f"  {name}: {vid}")
        return

    # Resolve voice ID
    voice_id = args.voice
    if args.voice.lower() in VOICE_IDS:
        voice_id = VOICE_IDS[args.voice.lower()]
        print(f"Using voice: {args.voice} ({voice_id})")

    os.makedirs(args.output, exist_ok=True)

    with open(args.narration, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Support both list format and dict format
    if isinstance(data, list):
        narration_list = data
    else:
        narration_list = [{"scene": k, "text": v.get("text", "")} for k, v in data.get("narrations", {}).items()]

    total = len(narration_list)
    success = 0

    for i, item in enumerate(narration_list):
        scene_name = item.get("scene", f"scene_{i+1:02d}")
        text = item.get("text", "")
        if not text or text.startswith("["):  # Skip placeholder text
            print(f"[{i+1}/{total}] Skipping {scene_name} (no text)")
            continue

        print(f"[{i+1}/{total}] Generating audio for {scene_name}...")
        output_path = os.path.join(args.output, f"{scene_name}.mp3")

        if text_to_speech(api_key, text, voice_id, output_path, args.model):
            print(f"  Saved: {output_path}")
            success += 1
        else:
            print(f"  Failed to generate audio for {scene_name}")

    print(f"\n{success}/{total} audio files generated successfully")
    print("Done!")


if __name__ == "__main__":
    main()
