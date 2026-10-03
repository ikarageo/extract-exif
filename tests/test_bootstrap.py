"""Exercise the launcher against real virtual environments without network access."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
import venv


PROJECT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("bash") and os.name == "posix", "requires Bash on Linux/macOS/WSL")
class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory(prefix="exif bootstrap ")
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name) / "project with spaces"
        self.project.mkdir()
        shutil.copy2(PROJECT / "run.sh", self.project / "run.sh")
        (self.project / "requirements.txt").write_text("", encoding="utf-8")
        # A probe reports which interpreter the real launcher uses, without Pillow.
        (self.project / "extract_exif.py").write_text(
            "import json, sys\n"
            "print(json.dumps({'prefix': sys.prefix, 'arguments': sys.argv[1:]}))\n",
            encoding="utf-8",
        )
        self.venv_path = self.project / ".venv"
        self.python = self.venv_path / "bin" / "python"
        self.environment = os.environ.copy()
        self.environment["PIP_NO_INDEX"] = "1"
        self.environment["PATH"] = str(Path(sys.executable).parent) + os.pathsep + self.environment["PATH"]

    def run_launcher(self):
        result = subprocess.run(
            ["bash", str(self.project / "run.sh"), "photos with spaces", "--output-dir", "results"],
            cwd=self.temporary.name, env=self.environment,
            capture_output=True, text=True, timeout=90,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        probe = json.loads(result.stdout.splitlines()[-1])
        self.assertEqual(probe["prefix"], str(self.venv_path))
        self.assertEqual(probe["arguments"], ["photos with spaces", "--output-dir", "results"])
        return result

    def test_creates_new_environment_with_pip(self):
        self.assertFalse(self.venv_path.exists())
        self.run_launcher()
        result = subprocess.run([str(self.python), "-m", "pip", "--version"], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_repairs_missing_pip_and_reuses_environment(self):
        venv.create(self.venv_path, with_pip=False)
        result = subprocess.run([str(self.python), "-m", "pip", "--version"], capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        marker = self.venv_path / "existing-user-file"
        marker.write_text("preserve me", encoding="utf-8")
        config_timestamp = (self.venv_path / "pyvenv.cfg").stat().st_mtime_ns

        result = self.run_launcher()
        self.assertIn("Installing missing pip", result.stderr)
        result = self.run_launcher()
        self.assertNotIn("Installing missing pip", result.stderr)
        self.assertEqual(marker.read_text(encoding="utf-8"), "preserve me")
        self.assertEqual((self.venv_path / "pyvenv.cfg").stat().st_mtime_ns, config_timestamp)


if __name__ == "__main__":
    unittest.main()
