import json
import pathlib
import shutil

root = pathlib.Path(__file__).resolve().parent.parent

cfg_path = root / "native" / "capacitor.config.json"

cfg = json.loads(cfg_path.read_text())

url = cfg.get("server", {}).get("url", "").rstrip("/")

assert url and "YOUR-APP-NAME" not in url, \
    "Edit native/capacitor.config.json with your Render URL."

www = root / "native" / "www"

shutil.rmtree(www, ignore_errors=True)

(www / "static").mkdir(parents=True, exist_ok=True)

static = root / "healthbuddy" / "static"

for item in static.iterdir():

    dest = www / "static" / item.name

    if item.is_file():
        shutil.copy2(item, dest)

    elif item.is_dir():
        shutil.copytree(item, dest, dirs_exist_ok=True)

html = (root / "healthbuddy" / "templates" / "index.html").read_text()

inject = f"<script>window.HB_API_BASE='{url}';</script>\n"

marker = '<script src="/static/providers.js"></script>'

assert marker in html, "providers.js marker not found."

html = html.replace(marker, inject + marker)

(www / "index.html").write_text(html)

cfg.pop("server", None)

cfg_path.write_text(json.dumps(cfg, indent=2))

print("Bundle created successfully.")
