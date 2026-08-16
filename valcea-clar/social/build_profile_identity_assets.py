#!/usr/bin/env python3
"""Generate the canonical VÂLCEA CLAR social profile identity asset kit."""
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
VC = ROOT / "valcea-clar"
PROFILE = VC / "social" / "profile_identity_system.json"
BRAND = VC / "social" / "social_brand_system.json"
OUTPUT = VC / "social" / "profile-assets"
SERIF_BOLD = ["/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf", "/usr/share/fonts/truetype/liberation2/LiberationSerif-Bold.ttf"]
SANS_REGULAR = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"]
SANS_BOLD = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"]


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def font(candidates: list[str], size: int) -> ImageFont.FreeTypeFont:
    for raw in candidates:
        path = Path(raw)
        if path.is_file():
            return ImageFont.truetype(str(path), size=size)
    raise RuntimeError("No supported newsroom identity font found")


def rgb(value: Any) -> tuple[int, int, int]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"invalid RGB value: {value!r}")
    return tuple(int(x) for x in value)


def colors(brand: dict[str, Any]) -> dict[str, tuple[int, int, int]]:
    palette = brand["brand"]["palette"]
    return {"ink": rgb(palette["ink_rgb"]), "paper": rgb(palette["paper_rgb"]), "accent": rgb(palette["accent_rgb"]), "white": rgb(palette["white_rgb"])}


def width(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.FreeTypeFont) -> int:
    box = draw.textbbox((0, 0), text, font=fnt)
    return box[2] - box[0]


def fit(draw: ImageDraw.ImageDraw, text: str, candidates: list[str], max_width: int, max_size: int, min_size: int) -> ImageFont.FreeTypeFont:
    for size in range(max_size, min_size - 1, -2):
        candidate = font(candidates, size)
        if width(draw, text, candidate) <= max_width:
            return candidate
    raise RuntimeError(f"text does not fit identity safe zone: {text!r}")


def render_avatar(width_px: int, height_px: int, palette: dict[str, tuple[int, int, int]], output: Path) -> None:
    if width_px != height_px:
        raise ValueError("avatar export must remain square")
    image = Image.new("RGB", (width_px, height_px), palette["paper"])
    draw = ImageDraw.Draw(image)
    side = width_px
    mark = "VC"
    mark_font = fit(draw, mark, SERIF_BOLD, round(side * 0.62), round(side * 0.42), round(side * 0.22))
    mark_w = width(draw, mark, mark_font)
    box = draw.textbbox((0, 0), mark, font=mark_font)
    mark_h = box[3] - box[1]
    x = round((side - mark_w) / 2) - round(side * 0.025)
    y = round((side - mark_h) / 2) - box[1] - round(side * 0.015)
    draw.text((x, y), mark, font=mark_font, fill=palette["ink"])
    dot_r = max(4, round(side * 0.032))
    dot_x = min(side - dot_r * 3, x + mark_w + round(side * 0.025))
    dot_y = y + mark_h - round(side * 0.01)
    draw.ellipse((dot_x, dot_y, dot_x + dot_r * 2, dot_y + dot_r * 2), fill=palette["accent"])
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, "PNG", optimize=True)


def render_header(*, width_px: int, height_px: int, safe: dict[str, Any], palette: dict[str, tuple[int, int, int]], wordmark: str, tagline: str, domain: str, variant: str, output: Path) -> None:
    image = Image.new("RGB", (width_px, height_px), palette["paper"])
    draw = ImageDraw.Draw(image)
    x, y = int(safe["x"]), int(safe["y"])
    sw, sh = int(safe["width"]), int(safe["height"])
    rule_h = max(5, round(height_px * 0.014))
    draw.rectangle((x, y, x + min(sw, round(sw * 0.17)), y + rule_h), fill=palette["accent"])
    mast = fit(draw, wordmark, SERIF_BOLD, sw, max(36, round(sh * 0.30)), max(24, round(sh * 0.15)))
    box = draw.textbbox((0, 0), wordmark, font=mast)
    mast_h = box[3] - box[1]
    text_y = y + round(sh * 0.17)
    draw.text((x, text_y - box[1]), wordmark, font=mast, fill=palette["ink"])
    support_size = max(20, min(round(sh * 0.085), round(height_px * 0.055)))
    support_y = text_y + mast_h + round(sh * 0.11)
    domain_font = font(SANS_BOLD, support_size)
    if variant == "masthead_tagline_domain":
        tagline_font = fit(draw, tagline, SANS_REGULAR, sw, support_size, max(18, support_size - 10))
        draw.text((x, support_y), tagline, font=tagline_font, fill=palette["ink"])
        draw.text((x, support_y + round(tagline_font.size * 1.65)), domain, font=domain_font, fill=palette["ink"])
    elif variant == "masthead_domain":
        draw.text((x, support_y), domain, font=domain_font, fill=palette["ink"])
    else:
        raise ValueError(f"unknown header variant: {variant}")
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, "JPEG", quality=95, optimize=True, progressive=True, subsampling=0)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def image_size(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return image.size


def build(output_dir: Path = OUTPUT) -> dict[str, Any]:
    profile, brand = load(PROFILE), load(BRAND)
    palette = colors(brand)
    masthead, platforms = profile["masthead"], profile["platforms"]
    output_dir.mkdir(parents=True, exist_ok=True)
    for old in output_dir.iterdir():
        if old.is_file() and old.name != ".gitkeep":
            old.unlink()
    records: list[dict[str, Any]] = []

    master = profile["avatar"]["master"]
    master_path = output_dir / "avatar-master.png"
    render_avatar(int(master["width"]), int(master["height"]), palette, master_path)
    records.append({"asset_id": "avatar-master", "platform": "master", "kind": "avatar", "file": master_path.name})

    for platform, cfg in sorted(platforms.items()):
        av = cfg["avatar_export"]
        avatar_path = output_dir / f"{platform}-avatar.png"
        render_avatar(int(av["width"]), int(av["height"]), palette, avatar_path)
        records.append({"asset_id": f"{platform}-avatar", "platform": platform, "kind": "avatar", "file": avatar_path.name})
        header = cfg.get("header_export")
        if isinstance(header, dict):
            header_path = output_dir / f"{platform}-header.jpg"
            render_header(width_px=int(header["width"]), height_px=int(header["height"]), safe=header["safe_zone"], palette=palette, wordmark=str(masthead["wordmark"]), tagline=str(masthead["tagline"]), domain=str(masthead["domain"]), variant=str(cfg.get("header_variant") or ""), output=header_path)
            records.append({"asset_id": f"{platform}-header", "platform": platform, "kind": "header", "file": header_path.name, "safe_zone": header["safe_zone"], "spec_source": header.get("spec_source")})

    assets = []
    for record in records:
        path = output_dir / record["file"]
        w, h = image_size(path)
        assets.append({**record, "width": w, "height": h, "bytes": path.stat().st_size, "sha256": sha256(path)})
    manifest = {
        "schema_version": "1.0",
        "product": "VÂLCEA CLAR Social Profile Identity Assets",
        "generator": "build_profile_identity_assets.py",
        "generation": "deterministic_editorial_profile_identity",
        "brand_source": "valcea-clar/social/social_brand_system.json",
        "profile_source": "valcea-clar/social/profile_identity_system.json",
        "photo_free_headers": True,
        "master_avatar": "avatar-master.png",
        "assets": assets,
        "profile_copy": {platform: {"display_name": cfg.get("display_name"), "bio": cfg.get("bio"), "about": cfg.get("about")} for platform, cfg in sorted(platforms.items())},
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def self_test() -> int:
    palette = {"ink": (20, 20, 20), "paper": (247, 246, 243), "accent": (196, 27, 35), "white": (255, 255, 255)}
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        avatar, header = tmp / "avatar.png", tmp / "header.jpg"
        render_avatar(400, 400, palette, avatar)
        render_header(width_px=1500, height_px=500, safe={"x": 180, "y": 70, "width": 1140, "height": 360}, palette=palette, wordmark="VÂLCEA CLAR", tagline="Ce se întâmplă. Ce știm. Ce contează.", domain="valceaclar.ro", variant="masthead_domain", output=header)
        assert image_size(avatar) == (400, 400)
        assert image_size(header) == (1500, 500)
        assert avatar.stat().st_size > 5000 and header.stat().st_size > 10000
    print("VÂLCEA CLAR profile identity asset generator self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    print(json.dumps(build(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
