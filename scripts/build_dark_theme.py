"""Generate frontend/src/dark.css from the light stylesheets.

Every colour declaration in styles.css and planner.css is re-emitted under
``:root[data-theme="dark"]`` with a colour chosen by the role it plays:
backgrounds become dark surfaces (keeping the light theme's elevation order),
text becomes light with at least 4.5:1 contrast, borders become subtle dark
lines, saturated brand fills keep their hue, chart and map marks are
brightened, and shadows become black. The light theme is left untouched.
Hand-tuned rules live in dark-extra.css.

    python scripts/build_dark_theme.py
"""

from __future__ import annotations

import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = [ROOT / "frontend/src/styles.css", ROOT / "frontend/src/planner.css"]
OUTPUT = ROOT / "frontend/src/dark.css"
SCOPE = ':root[data-theme="dark"]'
HEX = re.compile(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})\b")
NAMED = re.compile(r"(?<![-\w])(white|black)(?![-\w])")
NAMED_HEX = {"white": "#ffffff", "black": "#000000"}


# --- OKLab colour math --------------------------------------------------------
def _to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _to_srgb(c: float) -> float:
    c = max(0.0, min(1.0, c))
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def hex_to_oklch(value: str) -> tuple[float, float, float, str]:
    h = value.lstrip("#")
    if len(h) in (3, 4):
        h = "".join(ch * 2 for ch in h)
    alpha = h[6:8] if len(h) == 8 else ""
    r, g, b = (_to_linear(int(h[i:i + 2], 16) / 255) for i in (0, 2, 4))
    l = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    L = 0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s
    A = 1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s
    B = 0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s
    return L, math.hypot(A, B), math.atan2(B, A), alpha


def oklch_to_hex(L: float, C: float, hue: float, alpha: str = "") -> str:
    A, B = C * math.cos(hue), C * math.sin(hue)
    l = (L + 0.3963377774 * A + 0.2158037573 * B) ** 3
    m = (L - 0.1055613458 * A - 0.0638541728 * B) ** 3
    s = (L - 0.0894841775 * A - 1.2914855480 * B) ** 3
    r = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
    g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
    b = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s
    return "#" + "".join(f"{round(_to_srgb(c) * 255):02x}" for c in (r, g, b)) + alpha


# --- role mapping --------------------------------------------------------------
BRAND_HUE = 3.55  # radians; OKLCH hue of the brand teal #087e8b, set below


def dark_colour(value: str, role: str) -> str:
    L, C, hue, alpha = hex_to_oklch(value)
    clamp = lambda x, lo, hi: max(lo, min(hi, x))  # noqa: E731
    if role == "shadow":
        return "#000000" + (f"{min(255, int(int(alpha or 'ff', 16) * 1.6)):02x}" if alpha else "80")
    if role == "mark":
        return oklch_to_hex(clamp(L + 0.07, 0.6, 0.82), C, hue, alpha)
    if role == "fg":
        if L > 0.8:
            return value  # already light text, e.g. on brand buttons
        if C < 0.03 or L < 0.35:  # near-black ink becomes near-white ink
            return oklch_to_hex(clamp(1.02 - L * 0.45, 0.72, 0.94), min(C * 0.3, 0.012), hue, alpha)
        return oklch_to_hex(clamp(1.04 - L * 0.42, 0.76, 0.9), min(C, 0.14), hue, alpha)
    if role == "border":
        if C >= 0.03 and L < 0.8:
            return oklch_to_hex(clamp(L + 0.12, 0.55, 0.78), C, hue, alpha)
        if L < 0.5:
            return oklch_to_hex(0.5, C, hue, alpha)
        if C < 0.012:
            return oklch_to_hex(clamp(0.34 - (1 - L) * 0.55, 0.28, 0.42), 0.012, BRAND_HUE, alpha)
        return oklch_to_hex(0.37, clamp(C, 0.02, 0.05), hue, alpha)
    # background
    if C >= 0.06 and L < 0.8:
        return oklch_to_hex(clamp(L, 0.5, 0.66), C, hue, alpha)  # brand fills keep their colour
    if L < 0.5:
        return oklch_to_hex(L + 0.06, C, hue, alpha)  # already-dark overlays stay dark
    if C < 0.012:
        # Neutral surfaces keep the light theme's elevation order, with a faint brand tint.
        return oklch_to_hex(clamp(0.245 - (1 - L) * 0.9, 0.15, 0.32), 0.012, BRAND_HUE, alpha)
    return oklch_to_hex(0.285, clamp(C * 1.1, 0.025, 0.055), hue, alpha)  # tinted cards


def role_for(prop: str, value: str) -> str:
    if "gradient(" in value:
        return "mark"
    if prop == "box-shadow":
        return "shadow"
    if prop in {"color", "-webkit-text-fill-color", "caret-color"}:
        return "fg"
    if prop in {"stroke", "accent-color"}:
        L, C, _, _ = hex_to_oklch(HEX.search(value).group(0))
        return "border" if C < 0.03 and L > 0.8 else "mark"  # pale gridlines stay recessive
    if prop == "fill":
        L, C, _, _ = hex_to_oklch(HEX.search(value).group(0))
        return "fg" if C < 0.03 else "mark"
    if prop.startswith("border") or prop.startswith("outline") or prop == "scrollbar-color":
        return "border"
    return "bg"


# --- a small CSS walker (flat rules and @media blocks) ---------------------------
def blocks(css: str):
    """Yield (media, selector, body) for every rule; @keyframes are skipped."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    i = 0

    def read_block(start: int) -> tuple[str, int]:
        depth, j = 0, start
        while j < len(css):
            if css[j] == "{":
                depth += 1
            elif css[j] == "}":
                depth -= 1
                if depth == 0:
                    return css[start + 1:j], j + 1
            j += 1
        raise ValueError("unbalanced CSS")

    while i < len(css):
        brace = css.find("{", i)
        if brace < 0:
            break
        head = css[i:brace].strip()
        body, i = read_block(brace)
        if head.startswith("@media"):
            for _, selector, inner in blocks(body):
                yield head, selector, inner
        elif head.startswith("@"):
            continue
        else:
            yield None, head, body


def scoped(selector: str) -> str:
    parts = []
    for part in selector.split(","):
        part = " ".join(part.split())
        if part in {":root", "html"}:
            parts.append(SCOPE)
        else:
            parts.append(f"{SCOPE} {part}")
    return ", ".join(parts)


def main() -> None:
    global BRAND_HUE
    BRAND_HUE = hex_to_oklch("#087e8b")[2]
    out: list[str] = [
        "/* Generated by scripts/build_dark_theme.py from styles.css and planner.css. Do not edit;",
        "   hand-tuned dark rules live in dark-extra.css. */",
    ]
    changed = 0
    for source in SOURCES:
        media_groups: dict[str | None, list[str]] = {}
        for media, selector, body in blocks(source.read_text(encoding="utf-8")):
            declarations = []
            for prop, value in re.findall(r"([a-zA-Z-]+)\s*:\s*([^;]+)", body):
                prop = prop.strip().lower()
                value = NAMED.sub(lambda m: NAMED_HEX[m.group(0)], value)
                if not HEX.search(value):
                    continue
                role = role_for(prop, value)
                new_value = HEX.sub(lambda m: dark_colour(m.group(0), role), value.strip())
                declarations.append(f"  {prop}: {new_value};")
                changed += 1
            if declarations:
                media_groups.setdefault(media, []).append(f"{scoped(selector)} {{\n" + "\n".join(declarations) + "\n}")
        out.append(f"\n/* ---- from {source.name} ---- */")
        for media, rules in media_groups.items():
            if media is None:
                out.extend(rules)
            else:
                out.append(f"{media} {{\n" + "\n".join("  " + rule.replace("\n", "\n  ") for rule in rules) + "\n}")
    OUTPUT.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT)}: {changed} colour declarations")


if __name__ == "__main__":
    main()
