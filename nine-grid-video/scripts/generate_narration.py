#!/usr/bin/env python3
"""Generate narration text for each scene based on the story.

This script generates the narration/voiceover text for each video segment.
The actual text generation should be done by Claude based on the story context.

Usage:
    python generate_narration.py --story "故事大纲" --scenes 8 --language 中文 --output narration.json
"""

import argparse
import json
import os
import sys


def generate_narration_template(story: str, num_scenes: int, language: str) -> dict:
    """Generate a narration template structure.

    In practice, this template should be filled in by Claude based on the story.
    """
    narrations = {}

    # Template prompts for Claude to generate narrations
    template_prompt = f"""
Based on the following story, generate {num_scenes} narration segments in {language}.
Each narration should:
- Be 15-25 characters (for Chinese) or 8-15 words (for English)
- Match the visual content of the corresponding scene
- Create emotional resonance
- Use present tense for immersion

Story: {story}

Generate narrations for scenes 1-{num_scenes}:
"""

    for i in range(1, num_scenes + 1):
        narrations[f"scene_{i:02d}"] = {
            "text": f"[Scene {i} narration placeholder - to be filled by Claude]",
            "duration_hint": "3-5 seconds"
        }

    return {
        "story": story,
        "language": language,
        "generation_prompt": template_prompt,
        "narrations": narrations
    }


def main():
    parser = argparse.ArgumentParser(description="Generate narration text template")
    parser.add_argument("--story", required=True, help="Story outline/synopsis")
    parser.add_argument("--scenes", type=int, default=8, help="Number of scenes (default: 8)")
    parser.add_argument("--language", default="中文", help="Narration language")
    parser.add_argument("--output", required=True, help="Output JSON file path")
    args = parser.parse_args()

    print(f"Generating narration template for {args.scenes} scenes...")

    result = generate_narration_template(args.story, args.scenes, args.language)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"Saved narration template: {args.output}")
    print("\nNote: The narration text placeholders should be filled in by Claude")
    print("based on the story context and visual content of each scene.")
    print(f"\nGeneration prompt for Claude:\n{result['generation_prompt']}")


if __name__ == "__main__":
    main()
