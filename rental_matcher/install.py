"""
Register the helper with Chrome, once (v1.24). After this, the extension
starts and stops the helper itself: nothing to run before a pull.

    python -m rental_matcher.install [--prefs preferences/my.json] [--deps]
    python -m rental_matcher.install --uninstall

What it writes, all for this user only (no admin rights):
- a small launcher next to a host description, in %LOCALAPPDATA%\\RentalMatcher
  (Windows) or ~/.local/share/rental-matcher (Linux/macOS): it starts this
  Python on rental_matcher.native with the preferences file;
- where Chrome looks for it: the registry key
  HKCU\\Software\\Google\\Chrome\\NativeMessagingHosts\\com.rental_matcher.helper
  on Windows, the NativeMessagingHosts folder on Linux/macOS.

Chrome lets only the Rental Matcher extension start it: the extension's id
is fixed by the public key in browser/manifest.json and listed here.
`--deps` first installs what the helper needs (requirements.txt) into this
Python.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

HOST = "com.rental_matcher.helper"
EXTENSION_ID = "mdkhokkcolgcnoghfimmpkcnlbhkllnh"  # from the "key" in browser/manifest.json
REPO = Path(__file__).resolve().parents[1]
WINDOWS = sys.platform == "win32"
REG_KEY = rf"Software\Google\Chrome\NativeMessagingHosts\{HOST}"


def data_dir() -> Path:
    if WINDOWS:
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "RentalMatcher"
    return Path.home() / ".local" / "share" / "rental-matcher"


def chrome_host_dirs() -> list[Path]:
    """Where Chrome (and Chromium) look for a user's hosts, off Windows."""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
        return [base / "Google" / "Chrome" / "NativeMessagingHosts", base / "Chromium" / "NativeMessagingHosts"]
    base = Path.home() / ".config"
    return [base / "google-chrome" / "NativeMessagingHosts", base / "chromium" / "NativeMessagingHosts"]


def write_launcher(where: Path, python: str, prefs: Path) -> Path:
    where.mkdir(parents=True, exist_ok=True)
    if WINDOWS:
        p = where / "rental_matcher_host.bat"
        # chcp 65001: cmd reads this file as UTF-8, so a Hebrew folder name works (v1.28)
        p.write_text(f'@echo off\r\n@chcp 65001 >nul 2>&1\r\ncd /d "{REPO}"\r\n"{python}" -m rental_matcher.native --prefs "{prefs}" %*\r\n',
                     encoding="utf-8")
    else:
        p = where / "rental_matcher_host.sh"
        p.write_text(f'#!/bin/sh\ncd "{REPO}"\nexec "{python}" -m rental_matcher.native --prefs "{prefs}" "$@"\n', encoding="utf-8")
        p.chmod(0o755)
    return p


def manifest(launcher: Path) -> dict:
    return {"name": HOST, "description": "Rental Matcher's helper: plans pulls and scores listings on this computer.",
            "path": str(launcher), "type": "stdio", "allowed_origins": [f"chrome-extension://{EXTENSION_ID}/"]}


def install(prefs: Path, python: str = sys.executable, host_dirs: Optional[list[Path]] = None, where: Optional[Path] = None) -> list[Path]:
    """Write the launcher and the host description, and tell Chrome where
    they are. Returns what was written."""
    where = where or data_dir()
    launcher = write_launcher(where, python, prefs.resolve())
    desc = where / f"{HOST}.json"
    desc.write_text(json.dumps(manifest(launcher), indent=2) + "\n", encoding="utf-8")
    written = [launcher, desc]
    if WINDOWS and host_dirs is None:
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_KEY) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, str(desc))
    else:
        for d in host_dirs if host_dirs is not None else chrome_host_dirs():
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{HOST}.json").write_text(desc.read_text(encoding="utf-8"), encoding="utf-8")
            written.append(d / f"{HOST}.json")
    return written


def uninstall(host_dirs: Optional[list[Path]] = None, where: Optional[Path] = None) -> None:
    where = where or data_dir()
    if WINDOWS and host_dirs is None:
        import winreg

        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, REG_KEY)
        except FileNotFoundError:
            pass
    else:
        for d in host_dirs if host_dirs is not None else chrome_host_dirs():
            (d / f"{HOST}.json").unlink(missing_ok=True)
    for name in ("rental_matcher_host.bat", "rental_matcher_host.sh", f"{HOST}.json"):
        (where / name).unlink(missing_ok=True)


def check(python: str = sys.executable) -> Optional[str]:
    """None if this Python can run the helper, else what's missing."""
    r = subprocess.run([python, "-c", "import rental_matcher.native"], cwd=REPO, capture_output=True, text=True)
    return None if r.returncode == 0 else (r.stderr.strip().splitlines() or ["unknown error"])[-1]


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Register Rental Matcher's helper with Chrome")
    ap.add_argument("--prefs", default=str(REPO / "preferences" / "my.json"))
    ap.add_argument("--deps", action="store_true", help="first pip-install requirements.txt into this Python")
    ap.add_argument("--uninstall", action="store_true")
    a = ap.parse_args(argv)
    if a.uninstall:
        uninstall()
        print("Removed. Chrome won't start the helper any more.")
        return 0
    if a.deps:
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(REPO / "requirements.txt")], check=True)
    missing = check()
    if missing:
        print(f"This Python can't run the helper yet ({missing}). Run again with --deps.")
        return 1
    prefs = Path(a.prefs)
    if not prefs.is_file():
        example = REPO / "preferences" / "example.json"
        if not example.is_file():
            print(f"No preferences file at {prefs}.")
            return 1
        prefs.parent.mkdir(parents=True, exist_ok=True)
        prefs.write_text(example.read_text(encoding="utf-8").replace('"owner": "example"', '"owner": "me"'), encoding="utf-8")
        print(f"No preferences yet: copied preferences/example.json to {prefs}. Edit it, or change the settings in the extension.")
    for p in install(prefs):
        print(f"wrote {p}")
    if WINDOWS:
        print(rf"registered HKCU\{REG_KEY}")
    print("Done. Chrome starts the helper by itself when you press Pull (reload the extension if it was open).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
