"""Preparation failures must preserve takes and reach the caller."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "skills/scenario-kinetic-music-video/scripts"


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.take = self.root / "assets/video/take"
        (self.take / "m_vision").mkdir(parents=True)
        for name in ("f_00001.jpg", "m_00001.png", "meta.json", "pose.json", "track.json", "m_vision/backup.png", "notes.txt"):
            (self.take / name).write_bytes(b"previous take")

    def files(self):
        return {str(p.relative_to(self.take)): p.read_bytes() for p in self.take.rglob("*") if p.is_file()}

    def prep(self, source):
        return subprocess.run([sys.executable, str(SCRIPTS / "prep_video.py"), str(source), "take", "--width", "16"],
                              cwd=self.root, capture_output=True, text=True)

    @unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg")
    def test_failed_replacement_preserves_all_previous_bytes(self):
        before = self.files()
        for source in ("missing.mp4", "corrupt.mp4"):
            with self.subTest(source=source):
                if source == "corrupt.mp4":
                    (self.root / source).write_bytes(b"not video")
                result = self.prep(source)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.files(), before)

    @unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg")
    def test_success_replaces_derived_files_and_keeps_notes(self):
        source = self.root / "source.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=red:s=16x16:d=0.1", str(source)], check=True)
        result = self.prep(source)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertGreater(json.loads((self.take / "meta.json").read_text())["n"], 0)
        self.assertEqual((self.take / "notes.txt").read_bytes(), b"previous take")
        for name in ("m_00001.png", "m_vision", "pose.json", "track.json"):
            self.assertFalse((self.take / name).exists(), name)

    @unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg")
    def test_metadata_failure_after_decode_preserves_previous_take(self):
        source = self.root / "source.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=red:s=16x16:d=0.1", str(source)], check=True)
        binary = self.root / "bin"
        binary.mkdir()
        probe = binary / "ffprobe"
        probe.write_text("#!/bin/sh\nexit 23\n")
        probe.chmod(0o755)
        before = self.files()
        result = subprocess.run([sys.executable, str(SCRIPTS / "prep_video.py"), str(source), "take", "--width", "16"],
                                cwd=self.root, env={**os.environ, "PATH": str(binary) + os.pathsep + os.environ["PATH"]},
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.files(), before)

    @unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg")
    def test_failed_promotion_restores_previous_directory(self):
        source = self.root / "source.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=red:s=16x16:d=0.1", str(source)], check=True)
        before = self.files()
        code = """
import os, runpy, sys
from unittest.mock import patch
rename = os.rename

def fail_promotion(source, target):
    if os.path.basename(source) == 'take' and os.path.basename(os.path.dirname(source)).startswith('.prep-'):
        raise OSError('injected promotion failure')
    return rename(source, target)

sys.argv = [sys.argv[1], sys.argv[2], 'take', '--width', '16']
with patch('os.rename', side_effect=fail_promotion):
    runpy.run_path(sys.argv[0], run_name='__main__')
"""
        result = subprocess.run([sys.executable, "-c", code, str(SCRIPTS / "prep_video.py"), str(source)],
                                cwd=self.root, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("injected promotion failure", result.stderr)
        self.assertEqual(self.files(), before)

    def wrapper(self, stage):
        tools = self.root / "tools"
        tools.mkdir(exist_ok=True)
        shutil.copy2(SCRIPTS / "prep_clip.sh", tools / "prep_clip.sh")
        clips = self.root / "assets/clips"
        clips.mkdir(exist_ok=True)
        (clips / "take.mp4").touch()
        bin_dir = self.root / ".venv/bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        python = bin_dir / "python"
        python.write_text('#!/bin/bash\ncase "$1" in\n*prep_video.py) stage=prep;;\n*track.py) stage=track;;\n*) stage=metadata;;\nesac\n[ "$stage" != "$FAIL_STAGE" ]\n')
        python.chmod(0o755)
        probe = bin_dir / "ffprobe"
        probe.write_text('#!/bin/bash\n[ "$FAIL_STAGE" != probe ] || exit 23\necho 16\n')
        probe.chmod(0o755)
        matte = tools / "matte"
        matte.write_text('#!/bin/bash\n[ "$FAIL_STAGE" != matte ]\n')
        matte.chmod(0o755)
        return subprocess.run(["bash", str(tools / "prep_clip.sh"), "take"], cwd=self.root,
                              env={**os.environ, "FAIL_STAGE": stage, "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"]},
                              capture_output=True, text=True)

    def test_wrapper_propagates_each_failed_stage(self):
        for stage in ("probe", "prep", "matte", "metadata", "track"):
            with self.subTest(stage=stage):
                result = self.wrapper(stage)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertNotIn("PREP_DONE", result.stdout)

    def test_wrapper_accepts_silent_success(self):
        result = self.wrapper("none")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PREP_DONE", result.stdout)
