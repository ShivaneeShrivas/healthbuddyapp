"""Bundles HealthBuddy's screens into the native app (run by the workflow).

Reads the Render URL from capacitor.config.json's server.url, copies the
frontend into native/www with that URL baked in as the API base, then removes
server.url so Capacitor serves the bundled screens locally — which guarantees
the sensor bridge is present.
"""
import json
import pathlib
import shutil

root = pathlib.Path(__file__).resolve().parent.parent
cfg_path = root / "native" / "capacitor.config.json"
cfg = json.loads(cfg_path.read_text())
url = cfg.get("server", {}).get("url", "").rstrip("/")
assert url and "YOUR-APP-NAME" not in url, \
    "Edit native/capacitor.config.json: set your real onrender.com URL first."

www = root / "native" / "www"
shutil.rmtree(www, ignore_errors=True)
(www / "static").mkdir(parents=True)
for f in (root / "healthbuddy" / "static").iterdir():
    shutil.copy(f, www / "static" / f.name)

html = (root / "healthbuddy" / "templates" / "index.html").read_text()
inject = f"<script>window.HB_API_BASE='{url}';</script>\n"
marker = '<script src="/static/providers.js"></script>'
assert marker in html, "index.html changed — update bundle_www.py's marker"
html = html.replace(marker, inject + marker)
(www / "index.html").write_text(html)

cfg.pop("server", None)  # serve bundled screens locally
cfg_path.write_text(json.dumps(cfg, indent=2))
print("bundled screens; API base:", url)
