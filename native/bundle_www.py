"""Bundles HealthBuddy's screens into the native app (run by the workflow).

Reads the Render URL from capacitor.config.json's server.url, copies the
frontend into native/www with that URL baked in as the API base, then removes
server.url so Capacitor serves the bundled screens locally — which guarantees
the sensor bridge is present.

templates/index.html is a Jinja template (rendered normally by Flask when
served from Render), but this script isn't running inside Flask — it just
reads the file — so any {{ ... }} placeholders in it need to be substituted
here too, or they'd ship into the APK as literal, broken text.
"""
import json
import os
import pathlib
import shutil
import time

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

# Mirrors Config.APP_VERSION's logic (healthbuddy/config.py) for the same
# reason: something that changes on every build, so a stale APK's bundled
# assets are never confused with a fresh one. GITHUB_SHA is set automatically
# in Actions; falls back to build time when run locally.
app_version = os.environ.get("GITHUB_SHA", "")[:8] or str(int(time.time()))

html = (root / "healthbuddy" / "templates" / "index.html").read_text()
html = html.replace("{{ app_version }}", app_version)  # render the only Jinja var this template uses
inject = f"<script>window.HB_API_BASE='{url}';</script>\n"
marker = f'<script src="/static/providers.js?v={app_version}"></script>'
assert marker in html, "index.html changed — update bundle_www.py's marker"
html = html.replace(marker, inject + marker)
(www / "index.html").write_text(html)

cfg.pop("server", None)  # serve bundled screens locally
cfg_path.write_text(json.dumps(cfg, indent=2))
print("bundled screens; API base:", url, "| version:", app_version)
