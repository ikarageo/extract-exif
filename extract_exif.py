#!/usr/bin/env python3
"""Recursively export photo EXIF metadata to JSON and CSV."""

from __future__ import annotations

import argparse
import base64
from collections.abc import Callable
import csv
from datetime import datetime
from itertools import cycle
import json
import math
import os
from pathlib import Path
import re
import sys
import threading
from typing import Any

from PIL import ExifTags, Image
from PIL.TiffImagePlugin import IFDRational


PHOTO_EXTENSIONS = {
    ".jpg", ".jpeg", ".jpe", ".jfif", ".tif", ".tiff", ".png",
    ".webp", ".avif", ".bmp", ".gif",
}
FIELDS = ("file_path", "date_time", "location", "latitude", "longitude", "exif")
MISSING = "NA"


class Spinner:
    """Animate stderr on terminals and keep warning messages on separate lines."""

    def __init__(self, message: str):
        self.message = message
        self.stream = sys.stderr
        self.enabled = self.stream.isatty() and os.environ.get("TERM") != "dumb"
        self._frames = cycle("|/-\\")
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._animate, daemon=True)

    def _draw(self) -> None:
        self.stream.write(f"\r{next(self._frames)} {self.message}")
        self.stream.flush()

    def _clear(self) -> None:
        self.stream.write("\r" + " " * (len(self.message) + 2) + "\r")
        self.stream.flush()

    def _animate(self) -> None:
        while not self._stop.wait(0.1):
            with self._lock:
                self._draw()

    def write(self, message: str) -> None:
        with self._lock:
            if self.enabled:
                self._clear()
            print(message, file=self.stream, flush=True)

    def __enter__(self) -> Spinner:
        if self.enabled:
            try:
                self._draw()
                self._thread.start()
            except BaseException:
                self._stop.set()
                if self._thread.is_alive():
                    self._thread.join()
                self._clear()
                raise
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if self.enabled:
            self._stop.set()
            self._thread.join()
            self._clear()


def text_value(value: Any) -> str:
    """Clean EXIF ASCII strings, which sometimes include trailing null bytes."""
    if isinstance(value, bytes):
        value = value.decode("ascii", errors="replace")
    return str(value).strip("\x00 \t\r\n") if value is not None else ""


def capture_datetime(exif: dict, details: dict) -> str:
    """Prefer capture time, then digitization time, then the image timestamp."""
    for tag, subsecond, offset in (
        (36867, 37521, 36881),  # DateTimeOriginal
        (36868, 37522, 36882),  # DateTimeDigitized
        (306, 37520, 36880),    # DateTime
    ):
        value = text_value(details.get(tag, exif.get(tag)))
        try:
            date_time = datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
        except ValueError:
            continue
        result = date_time.isoformat()
        fraction = text_value(details.get(subsecond, exif.get(subsecond)))
        if re.fullmatch(r"[0-9]+", fraction):
            result += "." + fraction
        zone = text_value(details.get(offset, exif.get(offset)))
        if re.fullmatch(r"[+-](?:[01][0-9]|2[0-3]):[0-5][0-9]", zone):
            result += zone
        return result
    return MISSING


def coordinate(value: Any, reference: Any, positive: str, negative: str, limit: int) -> float | None:
    """Convert an EXIF degrees/minutes/seconds tuple into signed degrees."""
    try:
        degrees, minutes, seconds = (float(part) for part in value)
        direction = text_value(reference).upper()
        if direction not in (positive, negative):
            return None
        if not all(math.isfinite(part) for part in (degrees, minutes, seconds)):
            return None
        if not (0 <= degrees <= limit and 0 <= minutes < 60 and 0 <= seconds < 60):
            return None
        decimal = degrees + minutes / 60 + seconds / 3600
        if decimal > limit:
            return None
        return round(-decimal if direction == negative else decimal, 8)
    except (TypeError, ValueError, OverflowError, ZeroDivisionError):
        return None


def json_value(value: Any) -> Any:
    """Keep all EXIF values serializable, including rational and binary fields."""
    if isinstance(value, bytes):
        return {"encoding": "base64", "data": base64.b64encode(value).decode("ascii")}
    if isinstance(value, IFDRational):
        try:
            return json_value(float(value))
        except (ValueError, OverflowError, ZeroDivisionError):
            return str(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    return str(value)


def named_tags(tags: dict, names: dict) -> dict[str, Any]:
    return {names.get(tag, str(tag)): json_value(value) for tag, value in tags.items()}


def extract_metadata(path: Path) -> dict[str, Any]:
    with Image.open(path) as photo:
        exif = photo.getexif()
        details = exif.get_ifd(ExifTags.IFD.Exif) if ExifTags.IFD.Exif in exif else {}
        gps = exif.get_ifd(ExifTags.IFD.GPSInfo) if ExifTags.IFD.GPSInfo in exif else {}
        all_tags = named_tags(dict(exif), ExifTags.TAGS)
        if ExifTags.IFD.Exif in exif:
            all_tags["ExifOffset"] = named_tags(details, ExifTags.TAGS)
            if ExifTags.IFD.Interop in details:
                interop = exif.get_ifd(ExifTags.IFD.Interop)
                all_tags["ExifOffset"]["ExifInteroperabilityOffset"] = named_tags(interop, ExifTags.TAGS)
        if ExifTags.IFD.GPSInfo in exif:
            all_tags["GPSInfo"] = named_tags(gps, ExifTags.GPSTAGS)

        latitude = coordinate(gps.get(2), gps.get(1), "N", "S", 90)
        longitude = coordinate(gps.get(4), gps.get(3), "E", "W", 180)
        location = MISSING
        if latitude is not None and longitude is not None:
            location = f"{latitude:.8f}, {longitude:.8f}"

        return {
            "file_path": str(path.absolute()),
            "date_time": capture_datetime(dict(exif), details),
            "location": location,
            "latitude": latitude if latitude is not None else MISSING,
            "longitude": longitude if longitude is not None else MISSING,
            "exif": all_tags,
        }


def scan_photos(
    directory: Path, on_warning: Callable[[str], None] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    records = []
    errors = 0
    warn = on_warning if on_warning is not None else lambda message: print(message, file=sys.stderr)

    def report_error(error: OSError) -> None:
        nonlocal errors
        errors += 1
        warn(f"Warning: cannot scan directory: {error}")

    for root, directories, filenames in os.walk(directory, onerror=report_error, followlinks=False):
        directories[:] = sorted(name for name in directories if not (Path(root) / name).is_symlink())
        for name in sorted(filenames):
            path = Path(root) / name
            if path.suffix.lower() not in PHOTO_EXTENSIONS or path.is_symlink():
                continue
            try:
                records.append(extract_metadata(path))
            except (OSError, ValueError, TypeError, SyntaxError, KeyError, OverflowError,
                    ZeroDivisionError, Image.DecompressionBombError) as error:
                errors += 1
                warn(f"Warning: cannot read {path}: {error}")
    return records, errors


def write_outputs(records: list[dict[str, Any]], output_directory: Path) -> tuple[Path, Path]:
    output_directory.mkdir(parents=True, exist_ok=True)
    json_path = output_directory / "exif_metadata.json"
    csv_path = output_directory / "exif_metadata.csv"
    with json_path.open("w", encoding="utf-8") as output:
        json.dump(records, output, ensure_ascii=False, indent=2, allow_nan=False)
        output.write("\n")
    with csv_path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS)
        writer.writeheader()
        for record in records:
            writer.writerow({**record, "exif": json.dumps(record["exif"], ensure_ascii=False, allow_nan=False)})
    return json_path, csv_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="directory of photos to scan recursively")
    parser.add_argument(
        "--output-dir", type=Path, default=Path.cwd(),
        help="directory for exif_metadata.json and exif_metadata.csv (default: current directory)",
    )
    args = parser.parse_args(argv)
    directory = args.directory.expanduser().absolute()
    if not directory.is_dir():
        parser.error(f"not a directory: {directory}")

    try:
        with Spinner("Extracting and exporting metadata...") as progress:
            records, errors = scan_photos(directory, on_warning=progress.write)
            json_path, csv_path = write_outputs(records, args.output_dir.expanduser().absolute())
    except OSError as error:
        print(f"Error: cannot write output: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    print(f"Exported {len(records)} photo(s) to {json_path} and {csv_path}.")
    if errors:
        print(f"Completed with {errors} read/scan error(s); see warnings above.", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
