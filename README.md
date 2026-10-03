# extract-exif

Recursively extract photo EXIF metadata into both JSON and CSV using Python.

## Run

Requires Python 3.10 or newer, Bash, and Python's `venv` module. On Debian/Ubuntu,
install `python3-venv` if virtual environment creation reports that it is missing.

```bash
./run.sh "/path/to/photos"
```

The launcher creates `.venv` beside itself if needed, installs the pinned Pillow
dependency into it, and runs the program with that environment's Python. The first
run needs access to PyPI; later runs reuse the environment and installed package.
Paths containing spaces are supported when quoted. You can invoke the launcher
from any working directory.

A spinner appears while scanning photos and writing the exports in an interactive
terminal, including WSL. It clears when the job finishes, fails, or is interrupted
with Ctrl+C. Warnings remain visible on their own lines. The spinner is disabled
when stderr is redirected or the terminal type is `dumb`.

If an existing `.venv` is missing `pip`, the launcher repairs it using Python's
built-in `ensurepip` module. On Ubuntu/Debian under WSL, install the prerequisite
if the launcher reports that `venv` or `ensurepip` is unavailable:

```bash
sudo apt update
sudo apt install python3-venv
./run.sh "/mnt/c/Users/your-name/Pictures"
```

For a nondefault Python version, install its matching package (for example,
`python3.12-venv` for Python 3.12). To repair an environment manually when using
an older copy of the launcher, run `.venv/bin/python -m ensurepip --upgrade`.
Create and use the environment inside WSL; Windows virtual environments cannot
be reused as Linux virtual environments.

By default, `exif_metadata.json` and `exif_metadata.csv` are written in your current
working directory. Choose another output directory with:

```bash
./run.sh "/path/to/photos" --output-dir "/path/to/results"
```

The output directory is created if necessary. Existing files with these output
names are overwritten. Original photos are opened for reading only.

Once the environment exists, you can also run Python directly:

```bash
.venv/bin/python extract_exif.py "/path/to/photos" --output-dir results
```

## Output

JSON contains a list of records, one per readable photo. CSV contains the same
records with these columns:

| Field | Meaning |
| --- | --- |
| `file_path` | Absolute path to the photo. |
| `date_time` | ISO 8601 EXIF capture timestamp, or `"NA"` if unavailable. |
| `location` | `"latitude, longitude"` in decimal degrees, or `"NA"` if either coordinate is missing or invalid. |
| `latitude` | Signed decimal degrees, or `"NA"`. |
| `longitude` | Signed decimal degrees, or `"NA"`. |
| `exif` | EXIF tags readable by Pillow, including nested EXIF and GPS fields. This is an object in JSON and a JSON-encoded cell in CSV. |

The timestamp uses `DateTimeOriginal`, then `DateTimeDigitized`, then `DateTime`.
EXIF subseconds and UTC offset are included when available. A timestamp without
an offset retains the camera's local time; no timezone is guessed. Filesystem
creation/modification times are not substituted for missing EXIF dates.

Location is a GPS coordinate string, not a street address or city name. No network
service or API key is needed for extraction. Binary EXIF values are represented
as objects with `encoding: "base64"` and `data`; rational values become numbers.
Vendor-specific maker notes remain raw binary when Pillow does not decode them.

The scanner recognizes JPEG (`.jpg`, `.jpeg`, `.jpe`, `.jfif`), TIFF, PNG, WebP,
AVIF, BMP, and GIF filenames, case-insensitively. Available EXIF varies by format
and image. HEIC/HEIF and camera RAW formats are not supported. For multi-frame
images, metadata is read from the first frame. Symbolic links within the scan
are skipped, preventing loops and duplicate traversal.

Photos without EXIF still appear with `"NA"` values and an empty EXIF object.
Unreadable images or directories produce warnings on stderr; the scan continues
and exports readable photos. Exit codes are `0` for a successful scan, `1` for
read/scan or output errors, `2` for invalid command-line arguments, and `130` for
Ctrl+C. An empty scan produces `[]` in JSON and a header-only CSV.

## Tests

After running the launcher once (even with `--help`):

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Tests generate small local images and cover recursive extraction, GPS and missing
metadata, date selection, binary tags, JSON/CSV agreement, and error handling.
Bootstrap tests also check fresh environment creation and recovery of an existing
environment without pip, using temporary directories and no package downloads.
