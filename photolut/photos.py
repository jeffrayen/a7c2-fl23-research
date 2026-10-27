"""Read a JPEG, apply a look, and write a new JPEG that keeps EXIF and ICC data."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from .lut import Cube

JPEG_SUFFIXES = {".jpg", ".jpeg"}
EXIF_IFD = 0x8769
COLOR_SPACE = 0xA001
INTEROP_IFD = 0xA005
INTEROP_INDEX = 0x0001


@dataclass
class PhotoInfo:
    path: Path
    width: int
    height: int
    warnings: list[str] = field(default_factory=list)


def inspect(path: str | Path) -> PhotoInfo:
    path = Path(path)
    with Image.open(path) as img:
        info = PhotoInfo(path, img.width, img.height)
        if img.format not in ("JPEG", "MPO"):
            info.warnings.append("不是 JPEG")
        if img.mode not in ("RGB", "L"):
            info.warnings.append(f"色彩模式 {img.mode}，可能不是一般照片")
        exif = img.getexif()
        sub = exif.get_ifd(EXIF_IFD)
        space = sub.get(COLOR_SPACE)
        try:
            interop = exif.get_ifd(INTEROP_IFD).get(INTEROP_INDEX)
        except KeyError:
            interop = None
        icc = img.info.get("icc_profile") or b""
        if space not in (None, 1) or interop == "R03" or b"Adobe RGB" in icc:
            info.warnings.append("似乎是 Adobe RGB，風格是以 sRGB 製作，顏色會不準")
    return info


def load_rgb(path: str | Path, max_side: int | None = None, upright: bool = False) -> np.ndarray:
    """Return float32 RGB 0..1. max_side downsizes (for previews); upright applies EXIF rotation."""
    with Image.open(path) as img:
        img.seek(0)
        im = ImageOps.exif_transpose(img) if upright else img
        im = im.convert("RGB")
        if max_side and max(im.size) > max_side:
            im.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        return np.asarray(im, np.float32) / 255.0


def to_image(rgb: np.ndarray) -> Image.Image:
    return Image.fromarray(np.round(np.clip(rgb, 0, 1) * 255).astype(np.uint8))


def output_path(source: Path, folder: Path, suffix: str) -> Path:
    base = folder / f"{source.stem}_{suffix}.jpg"
    candidate, n = base, 2
    while candidate.exists():
        candidate = folder / f"{source.stem}_{suffix}-{n}.jpg"
        n += 1
    return candidate


def apply_table(pixels: np.ndarray, table: np.ndarray) -> np.ndarray:
    """pixels: (h, w, 3) uint8; table from Cube.table8."""
    p = pixels.astype(np.int32)
    return table[p[..., 0] + 256 * (p[..., 1] + 256 * p[..., 2])]


def process(source: str | Path, cube: Cube, strength: float, folder: str | Path,
            suffix: str, quality: int = 95, table: np.ndarray | None = None) -> Path:
    """Write a new JPEG; the original file is only read. Pass table (Cube.table8) for batches."""
    source, folder = Path(source), Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    if folder.resolve() == source.parent.resolve() and not suffix:
        raise ValueError("輸出到原資料夾時必須有檔名後綴，避免覆蓋原檔")
    with Image.open(source) as img:
        img.seek(0)
        exif = img.info.get("exif")
        icc = img.info.get("icc_profile")
        pixels = np.asarray(img.convert("RGB"))
    if table is not None:
        out = Image.fromarray(apply_table(pixels, table))
    else:
        out = to_image(cube.apply(pixels.astype(np.float32) / 255.0, strength))
    target = output_path(source, folder, suffix)
    kwargs = dict(quality=int(quality), subsampling=0)
    if exif:
        kwargs["exif"] = exif
    if icc:
        kwargs["icc_profile"] = icc
    tmp = target.with_name(target.name + ".part")
    out.save(tmp, "JPEG", **kwargs)
    tmp.replace(target)
    return target


def is_jpeg(path: str | Path) -> bool:
    return Path(path).suffix.lower() in JPEG_SUFFIXES
