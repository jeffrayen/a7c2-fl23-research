"""3D .cube loading and trilinear application (float32, chunked)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shlex

import numpy as np

MAX_SIZE = 129
CHUNK = 1 << 20  # pixels per chunk keeps a 33 MP photo within a few hundred MB


class CubeError(ValueError):
    pass


@dataclass(frozen=True)
class Cube:
    title: str
    size: int
    table: np.ndarray  # [b, g, r, 3] float32, red varies fastest in the file
    domain_min: np.ndarray
    domain_max: np.ndarray
    path: Path | None = None

    @classmethod
    def load(cls, path: str | Path) -> "Cube":
        path = Path(path)
        title, size = path.stem, None
        lo, hi = np.zeros(3, np.float32), np.ones(3, np.float32)
        rows: list[list[float]] = []
        for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            try:
                words = shlex.split(line, comments=True)
            except ValueError as exc:
                raise CubeError(f"{path.name} 第 {number} 行無法解析") from exc
            if not words:
                continue
            key = words[0].upper()
            if key == "TITLE":
                title = " ".join(words[1:]) or title
            elif key == "LUT_3D_SIZE":
                size = int(words[1])
                if not 2 <= size <= MAX_SIZE:
                    raise CubeError(f"不支援的 LUT 尺寸 {size}")
            elif key == "LUT_1D_SIZE":
                raise CubeError("只支援 3D LUT，不支援 1D LUT")
            elif key == "DOMAIN_MIN":
                lo = np.array([float(v) for v in words[1:4]], np.float32)
            elif key == "DOMAIN_MAX":
                hi = np.array([float(v) for v in words[1:4]], np.float32)
            elif key[0].isdigit() or key[0] in "-.+":
                if len(words) != 3:
                    raise CubeError(f"{path.name} 第 {number} 行應為三個數值")
                rows.append([float(v) for v in words])
            else:
                raise CubeError(f"{path.name} 含有不支援的標頭：{words[0]}")
        if size is None:
            raise CubeError("缺少 LUT_3D_SIZE")
        if len(rows) != size ** 3:
            raise CubeError(f"資料行數 {len(rows)} 與 LUT_3D_SIZE {size} 不符")
        if np.any(hi <= lo):
            raise CubeError("DOMAIN_MAX 必須大於 DOMAIN_MIN")
        table = np.asarray(rows, np.float32).reshape(size, size, size, 3)
        if not np.isfinite(table).all():
            raise CubeError("LUT 含有非有限數值")
        return cls(title, size, table, lo, hi, path)

    def apply(self, rgb: np.ndarray, strength: float = 1.0) -> np.ndarray:
        """rgb: (..., 3) floats in 0..1. Returns float32 0..1, blended by strength."""
        strength = float(np.clip(strength, 0.0, 1.0))
        flat = np.asarray(rgb, np.float32).reshape(-1, 3)
        out = np.empty_like(flat)
        for start in range(0, len(flat), CHUNK):
            part = flat[start:start + CHUNK]
            looked = self._sample(part)
            out[start:start + CHUNK] = part + strength * (looked - part)
        return np.clip(out, 0.0, 1.0).reshape(np.shape(rgb))

    def table8(self, strength: float = 1.0) -> np.ndarray:
        """Precomputed result for every 8-bit RGB value, shape (256**3, 3) uint8.

        Index with r + 256 * (g + 256 * b). Building it costs about as much as one
        large photo; every later photo is then a single lookup.
        """
        ax = np.arange(256, dtype=np.float32) / 255.0
        g, r = np.meshgrid(ax, ax, indexing="ij")
        plane = np.column_stack([r.ravel(), g.ravel(), np.zeros(65536, np.float32)])
        out = np.empty((256, 65536, 3), np.uint8)
        for b in range(256):
            plane[:, 2] = ax[b]
            out[b] = np.round(self.apply(plane, strength) * 255.0).astype(np.uint8)
        return out.reshape(-1, 3)

    def _sample(self, rgb: np.ndarray) -> np.ndarray:
        n = self.size - 1
        x = np.clip((rgb - self.domain_min) / (self.domain_max - self.domain_min), 0.0, 1.0) * n
        i0 = np.minimum(x.astype(np.int32), n - 1)
        f = x - i0
        r0, g0, b0 = i0[:, 0], i0[:, 1], i0[:, 2]
        fr, fg, fb = f[:, 0:1], f[:, 1:2], f[:, 2:3]
        t = self.table
        c000 = t[b0, g0, r0]; c001 = t[b0, g0, r0 + 1]
        c010 = t[b0, g0 + 1, r0]; c011 = t[b0, g0 + 1, r0 + 1]
        c100 = t[b0 + 1, g0, r0]; c101 = t[b0 + 1, g0, r0 + 1]
        c110 = t[b0 + 1, g0 + 1, r0]; c111 = t[b0 + 1, g0 + 1, r0 + 1]
        c00 = c000 + (c001 - c000) * fr
        c01 = c010 + (c011 - c010) * fr
        c10 = c100 + (c101 - c100) * fr
        c11 = c110 + (c111 - c110) * fr
        c0 = c00 + (c01 - c00) * fg
        c1 = c10 + (c11 - c10) * fg
        return c0 + (c1 - c0) * fb


def discover(folder: str | Path) -> list[Cube]:
    """Load every readable .cube in a folder, sorted by title; unreadable files are skipped."""
    looks = []
    for path in sorted(Path(folder).glob("*.cube")):
        try:
            looks.append(Cube.load(path))
        except (OSError, CubeError, ValueError):
            continue
    return sorted(looks, key=lambda c: c.title.lower())
