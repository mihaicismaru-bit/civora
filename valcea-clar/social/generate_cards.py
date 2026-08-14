#!/usr/bin/env python3
"""Render art-directed, story-specific Facebook cards for VÂLCEA CLAR."""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "valcea-clar" / "social" / "generated"
W, H = 1200, 630
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
SERIF = "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"


def f(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def rounded(draw: ImageDraw.ImageDraw, xy: tuple[int, int, int, int], radius: int, fill, outline=None, width=1) -> None:
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def wrap(draw: ImageDraw.ImageDraw, text: str, face: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines: list[str] = []
    line = ""
    for word in text.split():
        candidate = word if not line else f"{line} {word}"
        if draw.textbbox((0, 0), candidate, font=face)[2] <= max_width:
            line = candidate
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def brand(draw: ImageDraw.ImageDraw, x: int = 60, y: int = 42, dark=(25, 25, 25), accent=(185, 30, 46)) -> None:
    face = f(BOLD, 28)
    draw.text((x, y), "VÂLCEA", font=face, fill=dark)
    width = draw.textbbox((x, y), "VÂLCEA", font=face)[2] - x
    draw.text((x + width + 10, y), "CLAR", font=face, fill=accent)
    draw.line((x, y + 39, x + 206, y + 39), fill=accent, width=4)


def save(img: Image.Image, filename: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(OUT / filename, quality=82, optimize=True, progressive=True)


def launch() -> None:
    img = Image.new("RGB", (W, H), (246, 242, 234))
    d = ImageDraw.Draw(img)
    for x in range(0, W, 80):
        d.line((x, 0, x, H), fill=(235, 230, 220), width=1)
    for y in range(0, H, 80):
        d.line((0, y, W, y), fill=(235, 230, 220), width=1)
    d.rectangle((850, 0, W, H), fill=(176, 29, 46))
    rounded(d, (900, 120, 1110, 330), 24, (250, 247, 240))
    d.text((934, 145), "VC", font=f(BOLD, 100), fill=(176, 29, 46))
    d.text((898, 358), "JURNALISM LOCAL", font=f(BOLD, 24), fill="white")
    d.text((915, 395), "fără zgomot", font=f(REG, 22), fill=(255, 230, 232))
    brand(d)
    d.text((62, 130), "VÂLCEA CLAR", font=f(SERIF, 68), fill=(28, 28, 28))
    d.text((62, 218), "ESTE ONLINE", font=f(BOLD, 68), fill=(176, 29, 46))
    d.text((65, 326), "Știrile Vâlcii, fără zgomot.", font=f(REG, 34), fill=(53, 53, 53))
    d.text((65, 382), "Informație locală verificată • oameni • evenimente • investigații", font=f(REG, 22), fill=(80, 80, 80))
    rounded(d, (62, 480, 482, 548), 14, (28, 28, 28))
    d.text((88, 496), "valceaclar.ro", font=f(BOLD, 28), fill="white")
    save(img, "launch-valcea-clar.jpg")


def spartan() -> None:
    img = Image.new("RGB", (W, H), (20, 21, 22))
    d = ImageDraw.Draw(img)
    for x in range(W):
        t = x / W
        d.line((x, 0, x, H), fill=(int(35 + 120 * t), int(22 + 5 * t), int(23 + 8 * t)))
    d.polygon([(0, 0), (720, 0), (610, H), (0, H)], fill=(17, 18, 20))
    cx, cy = 900, 315
    d.ellipse((760, 185, 1080, 505), fill=(238, 225, 205), outline="white", width=5)
    d.ellipse((815, 235, 1025, 455), fill=(202, 79, 50))
    colors = [(245, 214, 102), (82, 146, 73), (244, 239, 221), (174, 50, 50), (109, 70, 45)]
    for i in range(16):
        angle = 2 * math.pi * i / 16
        x, y = cx + 70 * math.cos(angle), cy + 70 * math.sin(angle)
        radius = 18 if i % 2 == 0 else 14
        d.ellipse((x - radius, y - radius, x + radius, y + radius), fill=colors[i % len(colors)])
    rounded(d, (755, 60, 1095, 138), 12, (211, 28, 48))
    d.text((790, 78), "SPARTAN", font=f(BOLD, 42), fill="white")
    brand(d, dark="white", accent=(237, 54, 70))
    d.text((60, 132), "NOU ÎN ORAȘ", font=f(BOLD, 25), fill=(237, 54, 70))
    y = 178
    face = f(SERIF, 54)
    for line in wrap(d, "Spartan a deschis la Râmnicu Vâlcea", face, 560):
        d.text((60, y), line, font=face, fill="white")
        y += 68
    d.text((60, 386), "Shopping City • Str. Ferdinand 38A", font=f(REG, 26), fill=(231, 231, 231))
    rounded(d, (60, 448, 590, 533), 14, (237, 54, 70))
    d.text((84, 467), "Investiție anunțată: aproape 1,5 mil. lei", font=f(BOLD, 25), fill="white")
    d.text((60, 570), "Cine operează franciza și ce știm despre locație", font=f(REG, 22), fill=(210, 210, 210))
    save(img, "spartan-ramnicu-valcea.jpg")


def festival() -> None:
    img = Image.new("RGB", (W, H), (24, 10, 35))
    center = (870, 220)
    colors = [(203, 25, 69), (250, 87, 48), (100, 35, 175), (30, 125, 220)]
    for i, color in enumerate(colors):
        angle = -0.55 + i * 0.37
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        ld.polygon([center, (center[0] + 650 * math.cos(angle - 0.15), center[1] + 650 * math.sin(angle - 0.15)), (center[0] + 650 * math.cos(angle + 0.15), center[1] + 650 * math.sin(angle + 0.15))], fill=(*color, 85))
        img = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")
    d = ImageDraw.Draw(img)
    d.rectangle((650, 330, 1160, 475), fill=(10, 10, 14))
    d.rectangle((700, 265, 1110, 335), fill=(30, 30, 40))
    for x in (730, 820, 910, 1000, 1090):
        d.ellipse((x - 20, 285, x + 20, 325), fill=(255, 80, 90))
    for i in range(70):
        x = 610 + i * 9
        height = 30 + ((i * 17) % 45)
        d.ellipse((x, 510 - height, x + 10, 520 - height), fill=(4, 4, 6))
        d.rectangle((x + 3, 520 - height, x + 7, 545), fill=(4, 4, 6))
    brand(d, dark="white", accent=(255, 59, 88))
    rounded(d, (58, 118, 265, 168), 12, (255, 59, 88))
    d.text((83, 129), "AZI • 18:00", font=f(BOLD, 23), fill="white")
    d.text((58, 205), "MUSICLOVER", font=f(SERIF, 58), fill="white")
    d.text((58, 274), "FESTIVAL", font=f(BOLD, 72), fill=(255, 59, 88))
    d.text((60, 367), "RED DAY • Platoul Fețeni", font=f(BOLD, 30), fill="white")
    d.text((60, 418), "Puya • Johny Romano • Shift", font=f(REG, 26), fill=(244, 230, 246))
    d.text((60, 455), "Badd G • DJ Matei • Bogdanov", font=f(REG, 26), fill=(244, 230, 246))
    rounded(d, (58, 520, 520, 578), 12, "white")
    d.text((80, 534), "14–16 AUGUST • RÂMNICU VÂLCEA", font=f(BOLD, 22), fill=(34, 15, 48))
    save(img, "musiclover-red-day.jpg")


def council() -> None:
    img = Image.new("RGB", (W, H), (239, 243, 246))
    d = ImageDraw.Draw(img)
    d.rectangle((760, 0, W, H), fill=(34, 61, 82))
    for x in (800, 890, 980, 1070):
        d.rectangle((x, 155, x + 48, 500), fill=(228, 232, 235))
        d.polygon([(x - 12, 155), (x + 72, 155), (x + 58, 120), (x + 2, 120)], fill=(228, 232, 235))
    d.rectangle((770, 500, 1160, 540), fill=(228, 232, 235))
    d.polygon([(760, 118), (1168, 118), (1090, 55), (838, 55)], fill=(228, 232, 235))
    rounded(d, (610, 85, 805, 300), 16, "white", outline=(180, 190, 198), width=2)
    d.text((645, 115), "HCL", font=f(BOLD, 45), fill=(34, 61, 82))
    d.text((641, 172), "159/2026", font=f(BOLD, 27), fill=(176, 29, 46))
    for y in (220, 245, 270):
        d.line((640, y, 770, y), fill=(170, 180, 188), width=3)
    brand(d, dark=(34, 61, 82), accent=(176, 29, 46))
    d.text((58, 130), "BANI PUBLICI", font=f(BOLD, 25), fill=(176, 29, 46))
    d.text((58, 182), "650.000 LEI", font=f(SERIF, 70), fill=(34, 61, 82))
    d.text((61, 270), "pentru Music Lover Festival", font=f(BOLD, 34), fill=(44, 77, 103))
    d.text((61, 335), "Ce a aprobat Consiliul Local", font=f(REG, 30), fill=(55, 67, 77))
    d.text((61, 382), "Hotărârea nr. 159 • 28 mai 2026", font=f(REG, 23), fill=(91, 101, 108))
    rounded(d, (58, 470, 575, 550), 14, (34, 61, 82))
    d.text((82, 490), "1,2 mil. lei • pachet cultural suplimentar", font=f(BOLD, 24), fill="white")
    d.text((60, 578), "Document verificat • sursă publică", font=f(REG, 20), fill=(98, 108, 115))
    save(img, "consiliul-local-buget-musiclover.jpg")


def main() -> int:
    launch()
    spartan()
    festival()
    council()
    for file in sorted(OUT.glob("*.jpg")):
        print(f"Rendered {file.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
