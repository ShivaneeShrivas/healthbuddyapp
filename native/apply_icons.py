"""Stamps the HealthBuddy logo onto the generated Android project.

Capacitor ships a placeholder icon; this replaces every launcher icon with
our heart+sprout mark so the installed app is unmistakable on the home
screen (and so you can tell a fresh build from an old one at a glance).
"""
import pathlib
import shutil

root = pathlib.Path(__file__).resolve().parent.parent
src = root / "healthbuddy" / "static" / "icon-512.png"
res = root / "native" / "android" / "app" / "src" / "main" / "res"
assert src.exists(), "icon-512.png missing"
assert res.exists(), "run after `npx cap add android`"

count = 0
for folder in res.glob("mipmap-*"):
    if folder.name.endswith("-v26"):
        # Adaptive-icon XML would override our PNG — drop it so the PNG wins.
        shutil.rmtree(folder, ignore_errors=True)
        continue
    for name in ("ic_launcher.png", "ic_launcher_round.png", "ic_launcher_foreground.png"):
        shutil.copy(src, folder / name)
        count += 1
print(f"icons applied to {count} files")
