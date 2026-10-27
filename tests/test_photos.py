import numpy as np
from PIL import Image

from photolut.lut import Cube
from photolut.photos import inspect, load_rgb, process

from test_lut import ROOT, write_cube


def make_jpeg(path, space=1):
    rgb = (np.random.default_rng(3).random((48, 64, 3)) * 255).astype(np.uint8)
    img = Image.fromarray(rgb)
    exif = Image.Exif()
    exif[0x010F] = "SONY"
    exif[0x0110] = "ILCE-7CM2"
    exif[0x0112] = 6
    exif.get_ifd(0x8769)[0xA001] = space
    exif.get_ifd(0x8769)[0x829D] = (28, 10)
    img.save(path, "JPEG", quality=98, exif=exif.tobytes())
    return path


def test_process_keeps_exif_and_original(tmp_path):
    src = make_jpeg(tmp_path / "DSC00001.JPG")
    before = src.read_bytes()
    cube = Cube.load(write_cube(tmp_path / "inv.cube", 5, lambda c: 1 - c, 'TITLE "Inv"'))
    out = process(src, cube, 1.0, tmp_path / "out", "Inv", 95)
    assert src.read_bytes() == before
    assert out.name == "DSC00001_Inv.jpg"
    with Image.open(src) as original:
        raw_exif = original.info["exif"]
    with Image.open(out) as img:
        assert img.info["exif"] == raw_exif  # EXIF block copied byte for byte
        exif = img.getexif()
        assert exif[0x0110] == "ILCE-7CM2"
        assert exif[0x0112] == 6  # orientation kept, pixels not rotated
        assert img.size == (64, 48)
    a, b = load_rgb(src), load_rgb(out)
    assert np.abs((1 - a) - b).mean() < 0.02
    second = process(src, cube, 1.0, tmp_path / "out", "Inv", 95)
    assert second.name == "DSC00001_Inv-2.jpg"


def test_inspect_warns_for_adobe_rgb(tmp_path):
    assert inspect(make_jpeg(tmp_path / "s.jpg", 1)).warnings == []
    assert inspect(make_jpeg(tmp_path / "a.jpg", 0xFFFF)).warnings


def test_table_path_matches_direct(tmp_path):
    src = make_jpeg(tmp_path / "x.jpg")
    cube = Cube.load(ROOT / "looks" / "HNCS.cube")
    direct = process(src, cube, 0.6, tmp_path / "d", "H", 100)
    fast = process(src, cube, 0.6, tmp_path / "f", "H", 100, cube.table8(0.6))
    a = np.asarray(Image.open(direct), np.int16)
    b = np.asarray(Image.open(fast), np.int16)
    assert np.abs(a - b).max() <= 1
