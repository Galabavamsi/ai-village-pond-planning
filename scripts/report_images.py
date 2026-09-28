"""Convert the report screenshots (output/screenshots/report/*.png) to JPEGs in latex/figures/.

Tall captures (the results panel, the controls panel and the phone layout)
are trimmed and split into columns at blank gaps between sections, so no card
is cut in half.

    python scripts/report_images.py
"""

from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "output" / "screenshots" / "report"
TARGET = ROOT / "latex" / "figures"
SPLITS = {"r07-results-panel": 3, "r14-controls-panel": 2, "r10-mobile": 2}
# The map area alone, for the annotated figure (pixel box in the 1.5x capture).
CROPS = {"r01-sample-results": ("r01-map", (472, 214, 1625, 1350))}
MAX_WIDTH = 2000


def blank_rows(pixels: np.ndarray) -> np.ndarray:
    """Rows that are a single flat colour (the gaps between cards)."""
    return pixels[:, 4:-4].std(axis=1).max(axis=1) < 1.5


def trim_bottom(image: Image.Image) -> Image.Image:
    pixels = np.asarray(image.convert("RGB"), dtype=float)
    blank = blank_rows(pixels)
    last = len(blank) - 1
    while last > 0 and blank[last]:
        last -= 1
    return image.crop((0, 0, image.width, min(image.height, last + 24)))


def split(image: Image.Image, parts: int) -> list[Image.Image]:
    pixels = np.asarray(image.convert("RGB"), dtype=float)
    blank = np.flatnonzero(blank_rows(pixels))
    cuts = [0]
    for k in range(1, parts):
        target = image.height * k / parts
        cuts.append(int(blank[np.argmin(np.abs(blank - target))]) if len(blank) else int(target))
    cuts.append(image.height)
    return [image.crop((0, top, image.width, bottom)) for top, bottom in zip(cuts, cuts[1:])]


def save(image: Image.Image, name: str) -> None:
    image = image.convert("RGB")
    if image.width > MAX_WIDTH:
        image = image.resize((MAX_WIDTH, round(image.height * MAX_WIDTH / image.width)), Image.LANCZOS)
    image.save(TARGET / f"{name}.jpg", quality=86, optimize=True, progressive=True)
    print(f"{name}.jpg {image.size}")


def main() -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    for path in sorted(SOURCE.glob("r*.png")):
        image = Image.open(path)
        parts = SPLITS.get(path.stem)
        if parts:
            for index, piece in enumerate(split(trim_bottom(image), parts), start=1):
                save(piece, f"{path.stem}-{index}")
        else:
            save(image, path.stem)
        if path.stem in CROPS:
            name, box = CROPS[path.stem]
            save(image.crop(box), name)


if __name__ == "__main__":
    main()
