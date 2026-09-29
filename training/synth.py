"""Synthetic 7-segment digit generator for LCD and LED displays.

Usage:
    uv run python synth.py --preview preview.png   # write a sample grid to inspect
"""
import argparse

import cv2
import numpy as np

from common import BLANK, CLASSES, IMG_H, IMG_W, UNSURE, normalize

SEGMENTS = "abcdefg"

# Several displays draw 6, 7 and 9 differently, so each digit can have variants.
DIGIT_PATTERNS = {
    0: ["abcdef"],
    1: ["bc"],
    2: ["abdeg"],
    3: ["abcdg"],
    4: ["bcfg"],
    5: ["acdfg"],
    6: ["acdefg", "cdefg"],
    7: ["abc", "abcf"],
    8: ["abcdefg"],
    9: ["abcdfg", "abcfg"],
}
VALID = {frozenset(p) for ps in DIGIT_PATTERNS.values() for p in ps}

# Render canvas, same aspect ratio as the model input.
CW, CH = IMG_W * 6, IMG_H * 6
# Nominal digit size inside the canvas.
DW, DH = 90, 160


def segment_polys(w, h, t, gap, slant):
    """Hexagonal polygons for segments a..g, digit origin at top-left."""
    ht = t / 2

    def horiz(x0, x1, y):
        return [(x0, y), (x0 + ht, y - ht), (x1 - ht, y - ht),
                (x1, y), (x1 - ht, y + ht), (x0 + ht, y + ht)]

    def vert(x, y0, y1):
        return [(x, y0), (x + ht, y0 + ht), (x + ht, y1 - ht),
                (x, y1), (x - ht, y1 - ht), (x - ht, y0 + ht)]

    xl, xr = ht, w - ht
    yt, ym, yb = ht, h / 2, h - ht
    polys = {
        "a": horiz(xl + gap, xr - gap, yt),
        "g": horiz(xl + gap, xr - gap, ym),
        "d": horiz(xl + gap, xr - gap, yb),
        "f": vert(xl, yt + gap, ym - gap),
        "b": vert(xr, yt + gap, ym - gap),
        "e": vert(xl, ym + gap, yb - gap),
        "c": vert(xr, ym + gap, yb - gap),
    }
    # Italic slant: shift the top to the right.
    return {k: np.array([(x + slant * (h / 2 - y), y) for x, y in p], np.float32)
            for k, p in polys.items()}


def random_pattern(rng, cls):
    """Return {segment: intensity 0..1} for a class."""
    if cls < 10:
        pats = DIGIT_PATTERNS[cls]
        return {s: 1.0 for s in pats[rng.integers(len(pats))]}
    if cls == BLANK:
        return {}
    # unsure: invalid segment set, a half-faded transition between two digits,
    # or a digit hidden by glare (glare handled in render()).
    mode = rng.integers(3)
    if mode == 0:
        while True:
            segs = frozenset(s for s in SEGMENTS if rng.random() < 0.5)
            if segs and segs not in VALID:
                return {s: 1.0 for s in segs}
    # Skip pairs whose union is itself a digit (e.g. 0 -> 8), which would just look like that digit.
    while True:
        a, b = rng.choice(10, 2, replace=False)
        pa, pb = DIGIT_PATTERNS[a][0], DIGIT_PATTERNS[b][0]
        if frozenset(pa) | frozenset(pb) not in VALID:
            break
    fade = rng.uniform(0.3, 0.55)
    out = {s: 1.0 for s in pa}
    for s in pb:
        if s not in out:
            out[s] = fade
    for s in pa:
        if s not in pb:
            out[s] = 1.0 - fade + 0.35
    if mode == 2:
        out["_glare"] = 1.0
    return out


def render(rng, cls):
    style = "lcd" if rng.random() < 0.5 else "led"
    if style == "lcd":
        bg = rng.uniform(130, 225)
        fg = rng.uniform(10, bg - 70)
        ghost = bg - rng.uniform(0, 0.15) * (bg - fg)
    else:
        bg = rng.uniform(0, 50)
        fg = rng.uniform(bg + 90, 255)
        ghost = bg + rng.uniform(0, 0.15) * (fg - bg)

    scale = rng.uniform(0.8, 1.0)
    w, h = DW * scale * rng.uniform(0.85, 1.1), DH * scale
    t = h * rng.uniform(0.08, 0.16)
    gap = rng.uniform(0, t * 0.35)
    slant = rng.uniform(0, 0.15) if rng.random() < 0.6 else 0.0
    spacing = w * rng.uniform(0.25, 0.6)

    canvas = np.full((CH, CW), bg, np.float32)
    ox = (CW - w) / 2 + rng.normal(0, CW * 0.04)
    oy = (CH - h) / 2 + rng.normal(0, CH * 0.03)

    pattern = random_pattern(rng, cls)
    glare = pattern.pop("_glare", 0.0)
    # Neighbour digits, visible when the install-time box is loose.
    for dx, pat in ((-(w + spacing), None), (0, pattern), (w + spacing, None)):
        if pat is None:
            pat = random_pattern(rng, int(rng.integers(11)))
        polys = segment_polys(w, h, t, gap, slant)
        for s, poly in polys.items():
            level = pat.get(s, 0.0)
            val = ghost + (fg - ghost) * level
            pts = (poly + (ox + dx, oy)).round().astype(np.int32)
            cv2.fillPoly(canvas, [pts], float(val), lineType=cv2.LINE_AA)
        if rng.random() < 0.15:
            cx = int(ox + dx + w + spacing / 2)
            cv2.circle(canvas, (cx, int(oy + h - t / 2)), int(t / 2), float(fg), -1, cv2.LINE_AA)

    if style == "led":
        glow = cv2.GaussianBlur(canvas, (0, 0), rng.uniform(2, 6))
        canvas = np.maximum(canvas, bg + (glow - bg) * rng.uniform(0.3, 1.0))

    canvas = augment(rng, canvas, glare)
    return normalize(canvas)


def augment(rng, img, forced_glare=0.0):
    h, w = img.shape
    # Small rotation, scale and shear from an imperfect mount.
    m = cv2.getRotationMatrix2D((w / 2, h / 2), rng.uniform(-4, 4), rng.uniform(0.92, 1.08))
    m[0, 1] += rng.uniform(-0.05, 0.05)
    img = cv2.warpAffine(img, m, (w, h), borderMode=cv2.BORDER_REFLECT)

    # Uneven lighting.
    gx, gy = np.meshgrid(np.linspace(-1, 1, w), np.linspace(-1, 1, h))
    shade = 1 + rng.uniform(-0.25, 0.25) * gx + rng.uniform(-0.25, 0.25) * gy
    img = img * shade

    # Specular glare spot (flash reflection on the display glass).
    if forced_glare or rng.random() < 0.2:
        cx, cy = rng.uniform(0, w), rng.uniform(0, h)
        r = rng.uniform(0.15, 0.4) * w * (2.5 if forced_glare else 1)
        d2 = (np.arange(w)[None] - cx) ** 2 + (np.arange(h)[:, None] - cy) ** 2
        strength = 255 if forced_glare else rng.uniform(30, 150)
        img = img + strength * np.exp(-d2 / (2 * r * r))

    img = cv2.GaussianBlur(img, (0, 0), rng.uniform(0.3, 3.0))
    img = img + rng.normal(0, rng.uniform(1, 12), img.shape)
    img = np.clip(img, 0, 255)
    gamma = rng.uniform(0.7, 1.4)
    img = 255 * (img / 255) ** gamma
    return img.astype(np.uint8)


def class_weights():
    p = np.full(len(CLASSES), 0.84 / 10)
    p[BLANK] = 0.08
    p[UNSURE] = 0.08
    return p


def generate(n, seed=0):
    rng = np.random.default_rng(seed)
    labels = rng.choice(len(CLASSES), n, p=class_weights())
    images = np.stack([render(rng, int(c)) for c in labels])
    return images, labels.astype(np.int64)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", default="preview.png")
    ap.add_argument("--per-class", type=int, default=16)
    args = ap.parse_args()

    rng = np.random.default_rng()
    rows = []
    for c in range(len(CLASSES)):
        tiles = [render(rng, c) for _ in range(args.per_class)]
        rows.append(np.hstack([np.pad(t, 1, constant_values=128) for t in tiles]))
    grid = np.vstack(rows)
    grid = cv2.resize(grid, None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST)
    cv2.imwrite(args.preview, grid)
    print(f"wrote {args.preview}: rows are {CLASSES}")


if __name__ == "__main__":
    main()
