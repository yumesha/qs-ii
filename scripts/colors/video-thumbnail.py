#!/usr/bin/env python3
"""Prepare local wallpaper files without changing the selected wallpaper."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def prepare(filename):
    path = Path(filename).expanduser().resolve(strict=True)
    if not path.is_file():
        raise ValueError("Choose a readable video file.")
    stat = path.stat()
    key = hashlib.sha256(f"{path}\0{stat.st_mtime_ns}\0{stat.st_size}".encode()).hexdigest()
    cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "quickshell/video-wallpapers"
    cache.mkdir(parents=True, exist_ok=True)
    thumbnail = cache / f"{key}.png"
    if not thumbnail.exists():
        fd, temporary = tempfile.mkstemp(suffix=".png", dir=cache)
        os.close(fd)
        try:
            result = subprocess.run(
                ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(path),
                 "-map", "0:v:0", "-frames:v", "1", "-vf", "scale=1920:-2:force_original_aspect_ratio=decrease",
                 "-threads", "1", temporary],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode or Path(temporary).stat().st_size == 0:
                raise ValueError("This file could not be opened as a video. Choose another file.")
            os.replace(temporary, thumbnail)
        finally:
            Path(temporary).unlink(missing_ok=True)
    return {"path": str(path), "thumbnail": str(thumbnail)}


def prepare_image(filename):
    path = Path(filename).expanduser().resolve(strict=True)
    if not path.is_file():
        raise ValueError("Choose a readable image file.")
    result = subprocess.run(
        ["magick", "identify", "-quiet", "-format", "%w %h", str(path)],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode or not result.stdout.strip():
        raise ValueError("This file could not be opened as an image. Choose another file.")
    return {"path": str(path), "thumbnail": str(path)}


if __name__ == "__main__":
    try:
        if len(sys.argv) == 3 and sys.argv[1] == "--image":
            print(json.dumps(prepare_image(sys.argv[2])))
        elif len(sys.argv) == 2:
            print(json.dumps(prepare(sys.argv[1])))
        else:
            raise ValueError("Choose a local video file.")
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"Wallpaper: {error}", file=sys.stderr)
        sys.exit(1)
