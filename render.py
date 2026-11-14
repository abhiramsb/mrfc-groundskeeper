"""Draws the pitch graphic with RSVPs per position."""

from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont, ImageOps

from formations import slots_for

W, H = 760, 980
MARGIN = 40

_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "DejaVuSans-Bold.ttf",
    "arialbd.ttf",
]
_font_cache: dict[int, ImageFont.FreeTypeFont] = {}


def _font(size: int):
    if size in _font_cache:
        return _font_cache[size]
    font = None
    for p in _FONT_PATHS:
        try:
            font = ImageFont.truetype(p, size)
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default(size)
    _font_cache[size] = font
    return font


def _fit(draw: ImageDraw.ImageDraw, text: str, size: int, max_w: int):
    """Shrink font / truncate so text fits max_w."""
    while size >= 14:
        f = _font(size)
        if draw.textlength(text, font=f) <= max_w:
            return text, f
        size -= 1
    f = _font(14)
    while text and draw.textlength(text + "…", font=f) > max_w:
        text = text[:-1]
    return text + "…", f


def _circle_avatar(data: bytes, size: int):
    try:
        im = Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:
        return None
    im = ImageOps.fit(im, (size, size))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)
    im.putalpha(mask)
    return im


def render_pitch(formation: str, taken: dict) -> bytes:
    """taken maps slot key -> name, or (name, avatar_png_bytes | None)."""
    taken = {k: (v if isinstance(v, tuple) else (v, None)) for k, v in taken.items()}
    img = Image.new("RGB", (W, H), (28, 110, 50))
    d = ImageDraw.Draw(img, "RGBA")

    # mowing stripes
    stripe_h = (H - 2 * MARGIN) / 10
    for i in range(10):
        if i % 2 == 0:
            y0 = MARGIN + i * stripe_h
            d.rectangle([MARGIN, y0, W - MARGIN, y0 + stripe_h], fill=(255, 255, 255, 12))

    line = (255, 255, 255, 190)
    lw = 4
    px0, py0, px1, py1 = MARGIN, MARGIN, W - MARGIN, H - MARGIN
    d.rectangle([px0, py0, px1, py1], outline=line, width=lw)
    midy = (py0 + py1) / 2
    d.line([px0, midy, px1, midy], fill=line, width=lw)
    d.ellipse([W / 2 - 70, midy - 70, W / 2 + 70, midy + 70], outline=line, width=lw)
    d.ellipse([W / 2 - 5, midy - 5, W / 2 + 5, midy + 5], fill=line)
    pw = W - 2 * MARGIN
    for top in (True, False):
        # penalty area + six-yard box
        pa_w, pa_h = pw * 0.62, 150
        sb_w, sb_h = pw * 0.30, 60
        if top:
            d.rectangle([W / 2 - pa_w / 2, py0, W / 2 + pa_w / 2, py0 + pa_h], outline=line, width=lw)
            d.rectangle([W / 2 - sb_w / 2, py0, W / 2 + sb_w / 2, py0 + sb_h], outline=line, width=lw)
        else:
            d.rectangle([W / 2 - pa_w / 2, py1 - pa_h, W / 2 + pa_w / 2, py1], outline=line, width=lw)
            d.rectangle([W / 2 - sb_w / 2, py1 - sb_h, W / 2 + sb_w / 2, py1], outline=line, width=lw)

    slots = slots_for(formation)
    inner_w = W - 2 * MARGIN - 80
    inner_h = H - 2 * MARGIN - 110
    r = 34
    for s in slots:
        cx = MARGIN + 40 + s.x * inner_w
        cy = MARGIN + 30 + s.y * inner_h
        name, avatar = taken.get(s.key, (None, None))
        if name:
            fill, outline, txt = (240, 200, 40, 255), (255, 255, 255, 255), (30, 30, 30)
        else:
            fill, outline, txt = (20, 60, 30, 170), (255, 255, 255, 140), (255, 255, 255)
        d.ellipse([cx - r + 3, cy - r + 5, cx + r + 3, cy + r + 5], fill=(0, 0, 0, 70))
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill, outline=outline, width=3)
        av = _circle_avatar(avatar, 2 * r - 6) if avatar else None
        if av:
            img.paste(av, (int(cx - r + 3), int(cy - r + 3)), av)
            # position badge on the avatar's top-right
            bf = _font(15)
            bw = d.textlength(s.label, font=bf)
            bx, by = cx + r - bw / 2 - 2, cy - r - 2
            d.rounded_rectangle([bx - bw / 2 - 6, by - 11, bx + bw / 2 + 6, by + 11], radius=8,
                                fill=(240, 200, 40, 255), outline=(255, 255, 255, 255), width=2)
            d.text((bx, by), s.label, font=bf, fill=(30, 30, 30), anchor="mm")
        else:
            d.text((cx, cy), s.label, font=_font(22), fill=txt, anchor="mm")

        # name plate
        if name:
            label, nf = _fit(d, name, 20, 128)
            fg = (255, 255, 255)
            bg = (10, 10, 10, 190)
        else:
            label, nf = "OPEN", _font(16)
            fg = (230, 230, 230)
            bg = (10, 10, 10, 90)
        tw = d.textlength(label, font=nf)
        ty = cy + r + 6
        d.rounded_rectangle([cx - tw / 2 - 8, ty, cx + tw / 2 + 8, ty + 28], radius=8, fill=bg)
        d.text((cx, ty + 14), label, font=nf, fill=fg, anchor="mm")

    # filled counter
    filled = sum(1 for s in slots if s.key in taken)
    tag = f"{formation}   {filled}/11"
    tf = _font(24)
    tw = d.textlength(tag, font=tf)
    d.rounded_rectangle([W / 2 - tw / 2 - 14, 8, W / 2 + tw / 2 + 14, 40], radius=10, fill=(0, 0, 0, 170))
    d.text((W / 2, 24), tag, font=tf, fill=(255, 255, 255), anchor="mm")

    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()
