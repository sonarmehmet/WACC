#!/usr/bin/env python3
"""Generate and prepare mobile/android (it is not committed; see mobile/README.md).

    cd mobile && python3 tool/prepare_android.py

1. `flutter create` makes the android/ folder (lib/ and test/ are left alone).
2. minSdk is raised to 23 (flutter_secure_storage needs it).
3. INTERNET permission goes into the main manifest (release builds need it).
4. Plain `http://` (cleartext) is allowed ONLY in the debug manifest, for the emulator address
   http://10.0.2.2:8765. Release builds stay https-only.

Fails loudly when a patch point is not found (Flutter templates change between versions).
"""
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
ANDROID = ROOT / "android"
MIN_SDK = 23


def fail(msg: str) -> None:
    sys.exit(f"prepare_android: {msg}")


def create() -> None:
    subprocess.run(
        ["flutter", "create", "--org", "com.wacc", "--project-name", "wacc_mobile", "--platforms", "android", "."],
        cwd=ROOT,
        check=True,
    )


def patch_min_sdk() -> None:
    for name in ("build.gradle.kts", "build.gradle"):
        path = ANDROID / "app" / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        new, count = re.subn(
            r"(minSdk(?:Version)?)(\s*=\s*|\s+)flutter\.minSdkVersion",
            lambda m: f"{m.group(1)}{m.group(2)}{MIN_SDK}",
            text,
        )
        if count == 0:
            if re.search(rf"minSdk(?:Version)?(\s*=\s*|\s+){MIN_SDK}\b", text):
                return
            fail(f"minSdk line not found in {path}")
        path.write_text(new, encoding="utf-8")
        return
    fail("android/app/build.gradle(.kts) not found")


def patch_main_manifest() -> None:
    path = ANDROID / "app" / "src" / "main" / "AndroidManifest.xml"
    text = path.read_text(encoding="utf-8")
    new = text
    if "android.permission.INTERNET" not in new:
        new = new.replace("<application", '<uses-permission android:name="android.permission.INTERNET"/>\n    <application', 1)
    # No cloud/adb backup of the app's data (saved server addresses, encrypted token store).
    if "android:allowBackup" not in new:
        new = new.replace("<application", '<application android:allowBackup="false"', 1)
    if new == text and "<application" not in text:
        fail(f"<application> not found in {path}")
    if new != text:
        path.write_text(new, encoding="utf-8")


def write_debug_manifest() -> None:
    path = ANDROID / "app" / "src" / "debug" / "AndroidManifest.xml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    xmlns:tools="http://schemas.android.com/tools">
    <uses-permission android:name="android.permission.INTERNET"/>
    <!-- Debug only: lets the emulator reach http://10.0.2.2:8765 / :8800. -->
    <application android:usesCleartextTraffic="true" tools:replace="android:usesCleartextTraffic"/>
</manifest>
""",
        encoding="utf-8",
    )


def main() -> None:
    if not (ANDROID / "app").exists():
        create()
    patch_min_sdk()
    patch_main_manifest()
    write_debug_manifest()
    print("prepare_android: ok")


if __name__ == "__main__":
    main()
