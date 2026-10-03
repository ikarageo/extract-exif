import base64
import csv
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from PIL import Image
from PIL.TiffImagePlugin import IFDRational

import extract_exif


SCRIPT = Path(extract_exif.__file__)


def save_photo(path, *, capture_time=None, gps=None, image_time=None, extra_details=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    exif = Image.Exif()
    if image_time:
        exif[306] = image_time
    details = dict(extra_details or {})
    if capture_time:
        details[36867] = capture_time
    if details:
        exif[34665] = details
    if gps:
        exif[34853] = gps
    with Image.new("RGB", (8, 8), "blue") as photo:
        photo.save(path, exif=exif.tobytes())


def gps_tags(latitude_ref="N", longitude_ref="W"):
    return {
        1: latitude_ref,
        2: (IFDRational(37), IFDRational(30), IFDRational(30)),
        3: longitude_ref,
        4: (IFDRational(122), IFDRational(15), IFDRational(0)),
    }


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def run_cli(self, source, output):
        return subprocess.run(
            [sys.executable, str(SCRIPT), str(source), "--output-dir", str(output)],
            capture_output=True, text=True, check=False,
        )

    def test_capture_time_location_and_nested_tags(self):
        path = self.root / "photo.jpg"
        save_photo(
            path, capture_time="2025:06:07 08:09:10", gps=gps_tags(),
            image_time="2026:01:01 00:00:00",
            extra_details={37521: "123", 36881: "+02:00", 33434: IFDRational(1, 125)},
        )
        record = extract_exif.extract_metadata(path)
        self.assertEqual(record["date_time"], "2025-06-07T08:09:10.123+02:00")
        self.assertAlmostEqual(record["latitude"], 37.50833333)
        self.assertEqual(record["longitude"], -122.25)
        self.assertEqual(record["location"], "37.50833333, -122.25000000")
        self.assertEqual(record["exif"]["GPSInfo"]["GPSLatitudeRef"], "N")
        self.assertAlmostEqual(record["exif"]["ExifOffset"]["ExposureTime"], 1 / 125)

    def test_south_and_east_location(self):
        path = self.root / "south.jpg"
        save_photo(path, gps=gps_tags("S", "E"))
        record = extract_exif.extract_metadata(path)
        self.assertLess(record["latitude"], 0)
        self.assertGreater(record["longitude"], 0)

    def test_exif_in_other_supported_formats(self):
        for suffix in (".png", ".tiff", ".webp", ".avif"):
            with self.subTest(suffix=suffix):
                path = self.root / ("photo" + suffix)
                save_photo(path, capture_time="2025:06:07 08:09:10", gps=gps_tags())
                record = extract_exif.extract_metadata(path)
                self.assertEqual(record["date_time"], "2025-06-07T08:09:10")
                self.assertEqual(record["location"], "37.50833333, -122.25000000")

    def test_zero_coordinates_are_valid(self):
        path = self.root / "zero.jpg"
        save_photo(path, gps={1: "N", 2: (0, 0, 0), 3: "E", 4: (0, 0, 0)})
        record = extract_exif.extract_metadata(path)
        self.assertEqual(record["location"], "0.00000000, 0.00000000")

    def test_no_exif_still_produces_record(self):
        path = self.root / "plain.png"
        save_photo(path)
        record = extract_exif.extract_metadata(path)
        for field in ("date_time", "location", "latitude", "longitude"):
            self.assertEqual(record[field], "NA")
        self.assertEqual(record["exif"], {})

    def test_partial_gps_is_not_a_location(self):
        path = self.root / "partial.jpg"
        save_photo(path, gps={1: "N", 2: (10, 0, 0)})
        record = extract_exif.extract_metadata(path)
        self.assertEqual(record["location"], "NA")
        self.assertEqual(record["latitude"], 10)
        self.assertEqual(record["longitude"], "NA")

    def test_invalid_gps_values(self):
        for value, reference in (
            ((10, 60, 0), "N"), ((91, 0, 0), "N"), ((90, 0, 1), "N"),
            ((float("nan"), 0, 0), "N"), ((10, 0), "N"),
            ((10, 0, 0), "?"), (None, "N"),
        ):
            with self.subTest(value=value, reference=reference):
                self.assertIsNone(extract_exif.coordinate(value, reference, "N", "S", 90))

    def test_date_fallbacks(self):
        self.assertEqual(
            extract_exif.capture_datetime({306: "2024:02:29 12:34:56"}, {36867: "bad"}),
            "2024-02-29T12:34:56",
        )
        self.assertEqual(
            extract_exif.capture_datetime({}, {36868: b"2023:10:09 08:07:06\x00"}),
            "2023-10-09T08:07:06",
        )
        self.assertEqual(extract_exif.capture_datetime({}, {36867: "0000:00:00 00:00:00"}), "NA")

    def test_binary_metadata_remains_available(self):
        path = self.root / "binary.jpg"
        value = b"ASCII\x00\x00\x00a comment"
        save_photo(path, extra_details={37510: value})
        record = extract_exif.extract_metadata(path)
        encoded = record["exif"]["ExifOffset"]["UserComment"]
        self.assertEqual(encoded["encoding"], "base64")
        self.assertEqual(base64.b64decode(encoded["data"]), value)

    def test_recursive_cli_and_matching_json_csv(self):
        source = self.root / "photos with spaces"
        save_photo(source / 'été, "photo".JPG', capture_time="2025:01:02 03:04:05", gps=gps_tags())
        save_photo(source / "nested" / "plain.png")
        (source / "ignored.txt").write_text("not a photo", encoding="utf-8")
        output = self.root / "exports"
        result = self.run_cli(source, output)
        self.assertEqual(result.returncode, 0, result.stderr)
        records = json.loads((output / "exif_metadata.json").read_text(encoding="utf-8"))
        with (output / "exif_metadata.csv").open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(records), 2)
        self.assertEqual(len(rows), 2)
        for record, row in zip(records, rows):
            self.assertEqual(set(record), set(extract_exif.FIELDS))
            self.assertEqual(json.loads(row.pop("exif")), record["exif"])
            for field, value in row.items():
                self.assertEqual(value, str(record[field]))

    def test_unreadable_photo_reports_error_and_keeps_valid_output(self):
        source = self.root / "photos"
        save_photo(source / "good.jpg")
        (source / "bad.jpg").write_bytes(b"not an image")
        output = self.root / "exports"
        result = self.run_cli(source, output)
        self.assertEqual(result.returncode, 1)
        self.assertIn("bad.jpg", result.stderr)
        records = json.loads((output / "exif_metadata.json").read_text())
        self.assertEqual(len(records), 1)
        self.assertTrue((output / "exif_metadata.csv").is_file())

    def test_empty_directory_writes_empty_outputs(self):
        source = self.root / "empty"
        source.mkdir()
        output = self.root / "exports"
        result = self.run_cli(source, output)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads((output / "exif_metadata.json").read_text()), [])
        with (output / "exif_metadata.csv").open(newline="") as stream:
            self.assertEqual(list(csv.reader(stream)), [list(extract_exif.FIELDS)])

    def test_missing_input_directory(self):
        output = self.root / "exports"
        result = self.run_cli(self.root / "missing", output)
        self.assertEqual(result.returncode, 2)
        self.assertIn("not a directory", result.stderr)
        self.assertFalse(output.exists())

    def test_invalid_output_path(self):
        source = self.root / "photos"
        source.mkdir()
        output = self.root / "file"
        output.write_text("existing data")
        result = self.run_cli(source, output)
        self.assertEqual(result.returncode, 1)
        self.assertIn("cannot write output", result.stderr)
        self.assertEqual(output.read_text(), "existing data")

    def test_symlinks_are_skipped(self):
        source = self.root / "photos"
        save_photo(source / "actual" / "photo.jpg")
        (source / "loop").symlink_to(source, target_is_directory=True)
        (source / "duplicate.jpg").symlink_to(source / "actual" / "photo.jpg")
        records, errors = extract_exif.scan_photos(source)
        self.assertEqual(errors, 0)
        self.assertEqual(len(records), 1)


if __name__ == "__main__":
    unittest.main()
