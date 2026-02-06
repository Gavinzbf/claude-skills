"""
Nano Banana Pro 批量生图脚本
支持多种模式：
1. composite       - 拼接用户已有的白底产品图
2. extract-product - 从实拍/模特图提炼产品白底图
3. scenes          - 生成角色参考图 + 首尾帧（默认）

用法：
    # 拼接已有白底图
    python generate_images.py --mode composite --product-images "img1.png,img2.png" --output ./output/images

    # 从实拍图提炼产品白底图
    python generate_images.py --mode extract-product --product-images "img1.png,img2.png" --output ./output/images [--with-back]

    # 生成角色参考图 + 首尾帧
    python generate_images.py --prompts prompts.json --output ./output/images
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
    for parents_level in range(6):
        env_file = Path(__file__).resolve().parents[parents_level] / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("GEMINI_API_KEY="):
                    return line.split("=", 1)[1].strip()
    print("Error: GEMINI_API_KEY not found. Set it in .env or environment variable.")
    sys.exit(1)


def generate_one(client, model, contents, output_path, types):
    """Generate a single image and save it. Returns the PIL Image or None."""
    try:
        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(
                response_modalities=["image", "text"]
            ),
        )
        for part in response.parts:
            if part.inline_data is not None:
                image = part.as_image()
                image.save(str(output_path))
                print(f"  Saved: {output_path}")
                return image
            elif part.text is not None:
                print(f"  Model text: {part.text[:200]}")
        print(f"  Warning: No image generated")
        return None
    except Exception as e:
        print(f"  Error: {e}")
        return None


def load_product_images(args, Image):
    """Load product images from comma-separated paths."""
    image_paths = [p.strip() for p in args.product_images.split(",") if p.strip()]
    if not image_paths:
        print("Error: No product images provided.")
        sys.exit(1)
    images = []
    for p in image_paths:
        if not Path(p).exists():
            print(f"Warning: Image not found: {p}")
            continue
        images.append(Image.open(p))
        print(f"Loaded: {p}")
    if not images:
        print("Error: No valid product images found.")
        sys.exit(1)
    return images


def make_composite(images, output_path, Image):
    """Horizontally concatenate images into one composite."""
    if len(images) == 1:
        images[0].save(str(output_path))
        print(f"  Single image copied to: {output_path}")
        return
    heights = [img.height for img in images]
    target_h = min(heights)
    resized = [img.resize((int(img.width * target_h / img.height), target_h)) for img in images]
    total_w = sum(img.width for img in resized)
    composite = Image.new("RGB", (total_w, target_h), (255, 255, 255))
    x = 0
    for img in resized:
        composite.paste(img, (x, 0))
        x += img.width
    composite.save(str(output_path))
    print(f"  Composite saved: {output_path} ({len(images)} images)")


def mode_composite(args, Image):
    """Concatenate user's existing white-bg product images."""
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    images = load_product_images(args, Image)
    print("\nCompositing product images...")
    make_composite(images, output_dir / "product_composite.png", Image)
    print("Done!")


def mode_extract_product(args, client, model, Image, types):
    """Extract product white-bg images from real photos using AI."""
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    ref_images = load_product_images(args, Image)

    front_prompt = (
        "严格参考提供的参考图（reference image）中的产品外观\n"
        "产品的颜色、图案、材质、细节必须与参考图高度一致\n"
        "不要改变产品设计 不要添加不存在的图案或文字\n\n"
        "将产品从参考图中提取出来，以正面朝向镜头的角度展示\n"
        "只保留产品本身 去除模特、背景、其他物品\n"
        "产品完整呈现在画面中 四边不裁切\n"
        "纯白色背景 无阴影 无装饰 无其他物品\n"
        "产品居中 占画面60%-80%\n"
        "产品自然平铺或悬挂展示 保持真实形态\n"
        "高清产品摄影风格 光线均匀 色彩真实\n"
        "电商白底产品图标准"
    )

    back_prompt = front_prompt.replace(
        "以正面朝向镜头的角度展示",
        "以背面朝向镜头的角度展示"
    )

    generated = []

    # Front
    print("\n[1] Extracting product front white-bg image...")
    contents = ref_images + [front_prompt]
    front_img = generate_one(client, model, contents, output_dir / "product_front.png", types)
    if front_img:
        generated.append(front_img)
    time.sleep(2)

    # Back
    if args.with_back:
        print("\n[2] Extracting product back white-bg image...")
        contents = ref_images + [back_prompt]
        back_img = generate_one(client, model, contents, output_dir / "product_back.png", types)
        if back_img:
            generated.append(back_img)
        time.sleep(2)

    # Also create composite from generated white-bg images
    if generated:
        print("\nCreating composite from extracted images...")
        make_composite(generated, output_dir / "product_composite.png", Image)

    print("\nProduct extraction done!")


def mode_scenes(args, client, model, Image, types):
    """Generate character ref + scene first/last frame images."""
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    with open(args.prompts, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Step 1: Generate character reference image
    char_ref = None
    if "character_prompt" in data:
        print("\n[Step 1] Generating character reference image...")
        char_ref = generate_one(
            client, model,
            [data["character_prompt"]],
            output_dir / "character_ref.png",
            types
        )
        time.sleep(2)

    # Load product reference images if available
    product_front = None
    product_back = None
    front_path = output_dir / "product_front.png"
    back_path = output_dir / "product_back.png"
    if front_path.exists():
        product_front = Image.open(front_path)
        print(f"Loaded product front ref: {front_path}")
    if back_path.exists():
        product_back = Image.open(back_path)
        print(f"Loaded product back ref: {back_path}")

    # Step 2: Generate scene first/last frames
    scenes = data.get("scenes", [])
    total = len(scenes) * 2
    count = 0

    for scene in scenes:
        scene_num = scene["scene"]
        # Determine which product ref to use per frame
        product_ref_first = scene.get("product_ref_first", "front")
        product_ref_last = scene.get("product_ref_last", "front")

        def get_product_ref(ref_type):
            if ref_type == "back" and product_back:
                return product_back
            if product_front:
                return product_front
            return None

        # Generate first frame
        count += 1
        first_item = scene["first"]
        print(f"\n[{count}/{total}] Generating: {first_item['name']}")
        contents = []
        if char_ref:
            contents.append(char_ref)
        prod_ref = get_product_ref(product_ref_first)
        if prod_ref:
            contents.append(prod_ref)
        contents.append(first_item["prompt"])

        first_image = generate_one(
            client, model, contents,
            output_dir / f"{first_item['name']}.png",
            types
        )
        time.sleep(2)

        # Generate last frame (with first frame as anchor)
        count += 1
        last_item = scene["last"]
        print(f"\n[{count}/{total}] Generating: {last_item['name']}")
        contents = []
        if char_ref:
            contents.append(char_ref)
        prod_ref = get_product_ref(product_ref_last)
        if prod_ref:
            contents.append(prod_ref)
        if first_image:
            contents.append(first_image)
        contents.append(last_item["prompt"])

        generate_one(
            client, model, contents,
            output_dir / f"{last_item['name']}.png",
            types
        )
        time.sleep(2)

    print(f"\nDone! All images saved to: {output_dir}")


def main():
    parser = argparse.ArgumentParser(description="Nano Banana Pro image generation")
    parser.add_argument("--mode", default="scenes",
                        choices=["composite", "extract-product", "scenes"],
                        help="Mode: composite (concat white-bg), extract-product (AI extract), scenes (frames)")
    parser.add_argument("--prompts", default=None, help="Path to prompts JSON file (for scenes mode)")
    parser.add_argument("--output", required=True, help="Output directory")
    parser.add_argument("--product-images", default=None,
                        help="Comma-separated paths to product images (for product mode)")
    parser.add_argument("--with-back", action="store_true",
                        help="Also generate back view white-bg image (for product mode)")
    parser.add_argument("--model", default="gemini-3-pro-image-preview", help="Model name")
    args = parser.parse_args()

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        print("Error: google-genai not installed. Run: pip install google-genai")
        sys.exit(1)

    try:
        from PIL import Image
    except ImportError:
        print("Error: Pillow not installed. Run: pip install Pillow")
        sys.exit(1)

    api_key = load_api_key()
    client = genai.Client(api_key=api_key)

    if args.mode == "composite":
        if not args.product_images:
            print("Error: --product-images required for composite mode")
            sys.exit(1)
        mode_composite(args, Image)
        return
    elif args.mode == "extract-product":
        if not args.product_images:
            print("Error: --product-images required for extract-product mode")
            sys.exit(1)
        mode_extract_product(args, client, args.model, Image, types)
        return
    else:
        if not args.prompts:
            print("Error: --prompts required for scenes mode")
            sys.exit(1)
        mode_scenes(args, client, args.model, Image, types)


if __name__ == "__main__":
    main()
