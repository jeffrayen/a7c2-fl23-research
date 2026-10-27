import numpy as np
import pytest

from photolut.lut import Cube, CubeError, discover

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]


def write_cube(path, size, fn, header=""):
    ax = np.linspace(0, 1, size)
    lines = [header, f"LUT_3D_SIZE {size}"]
    for b in ax:
        for g in ax:
            for r in ax:
                lines.append("%.6f %.6f %.6f" % tuple(fn(np.array([r, g, b]))))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_identity_is_exact(tmp_path):
    cube = Cube.load(write_cube(tmp_path / "id.cube", 17, lambda c: c))
    rgb = np.random.default_rng(1).random((5000, 3), dtype=np.float32)
    assert np.abs(cube.apply(rgb) - rgb).max() < 1e-5


def test_red_varies_fastest(tmp_path):
    # swap channels: output = (b, g, r); detects any axis-order mistake
    cube = Cube.load(write_cube(tmp_path / "swap.cube", 9, lambda c: c[::-1], 'TITLE "Swap"'))
    rgb = np.array([[0.9, 0.2, 0.1], [0.125, 0.5, 0.875]], np.float32)
    assert cube.title == "Swap"
    assert np.allclose(cube.apply(rgb), rgb[:, ::-1], atol=1e-5)


def test_trilinear_matches_linear_function(tmp_path):
    m = np.array([[0.8, 0.1, 0.1], [0.2, 0.7, 0.1], [0.0, 0.3, 0.7]])
    cube = Cube.load(write_cube(tmp_path / "lin.cube", 5, lambda c: m @ c))
    rgb = np.random.default_rng(2).random((2000, 3), dtype=np.float32)
    assert np.abs(cube.apply(rgb) - rgb @ m.T).max() < 1e-5


def test_strength_blends(tmp_path):
    cube = Cube.load(write_cube(tmp_path / "inv.cube", 3, lambda c: 1 - c))
    rgb = np.array([[0.2, 0.4, 0.6]], np.float32)
    assert np.allclose(cube.apply(rgb, 0.0), rgb)
    assert np.allclose(cube.apply(rgb, 0.5), 0.5, atol=1e-6)


def test_rejects_bad_files(tmp_path):
    bad = tmp_path / "bad.cube"
    bad.write_text("LUT_3D_SIZE 2\n0 0 0\n", encoding="utf-8")
    with pytest.raises(CubeError):
        Cube.load(bad)
    bad.write_text("LUT_1D_SIZE 4\n", encoding="utf-8")
    with pytest.raises(CubeError):
        Cube.load(bad)


def test_bundled_hncs_loads_and_keeps_grays():
    looks = {c.title: c for c in discover(ROOT / "looks")}
    hncs = looks["HNCS"]
    assert hncs.size == 33
    gray = np.repeat(np.linspace(0, 1, 33, dtype=np.float32)[:, None], 3, 1)
    assert np.abs(hncs.apply(gray) - gray).max() < 1e-4
