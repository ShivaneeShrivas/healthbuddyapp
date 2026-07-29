# 🌱 START HERE — The Only Guide You Need
### From zero → live app → real Android app reading actual steps & screen time
*This replaces ALL earlier guides. Delete old downloaded guides and old APKs — mixing versions caused the earlier confusion. Follow top to bottom, tick each box.*

---

## STEP 0 — Clean slate (5 min)

- [ ] On your phone: **uninstall every old HealthBuddy APK** and remove old
      home-screen shortcuts. We only trust what this guide produces.
- [ ] On your laptop: delete old healthbuddy zips/folders in Downloads.
      Extract ONLY the newest zip → you get one `healthbuddy` folder.
- [ ] What's inside (30-second tour): `healthbuddy/` = the app's screens and
      brain · `content/` = nudge cards · `native/` = Android sensor code ·
      `tests/` = 46 robot checks · `.github/workflows/` = the cloud APK
      builder · `BEGINNER_GUIDE.md` = how to edit things later.

**How the finished system works (one paragraph):** Your *server* lives on
Render and holds all data + intelligence. The *website version* of the app
(for anyone, instantly) is served straight from Render. The *Android app*
carries its screens inside the APK — which is what guarantees the
step-sensor and screen-time bridge works — and talks to the same server.
So: server changes update everyone instantly; screen changes reach the APK
on the next one-click rebuild.

---

## STEP 1 — Code into GitHub (15 min)

- [ ] github.com → log in → open your `healthbuddy` repository
      (or **New repository** named `healthbuddy` if starting truly fresh).
- [ ] **Add file → Upload files** → open your extracted folder → **Ctrl+A**
      → drag everything into the browser box.
      ⚠️ Drag the folder's *contents*, not the folder itself.
      ⚠️ If a file called `healthbuddy.db` exists, un-select it
      (`healthbuddy/db.py` stays — .py is code, .db is data).
- [ ] Wait for the full file list to appear (60+ files) → type
      `final version` → **Commit changes** (yes to replacing old files).

---

## STEP 2 — Server live on Render (10 min, or automatic)

**Already have the Render service?** It saw your commit and is redeploying
right now — skip to the checkbox below.

**Fresh setup:** render.com → sign in with GitHub → **New → Web Service** →
choose `healthbuddy` → fill exactly:
- Build Command: `pip install -r requirements.txt && python seed.py`
- Start Command: `gunicorn -w 2 -b 0.0.0.0:$PORT "healthbuddy:create_app()"`
- Environment variable: key `HB_SECRET_KEY`, value = 60+ random characters
→ **Create Web Service** → in ~3 min you get `https://xxxx.onrender.com`.

- [ ] **Verify:** open your link → register a test account as **Male** →
      Profile shows your details, no Period Care → Home shows ONE task with
      a countdown that survives refreshing → checklist +Log works and a
      **− appears** to undo mis-taps. All good = server done. ✅

---

## STEP 3 — Instant install for everyone (2 min)

Share your onrender.com link. Users install it themselves:
- **Android:** Chrome → ⋮ → *Add to Home screen*
- **iPhone:** Safari → Share □↑ → *Add to Home Screen*

Full app, your icon, no store. (This version can't read sensors — that's
what Steps 4–5 add for Android.) **This is your launch. You're live.**

---

## STEP 4 — Tell the Android build where your server is (2 min)

- [ ] On GitHub open `native/capacitor.config.json` → pencil ✏️ →
      replace `YOUR-APP-NAME.onrender.com` with your real address
      (keep `https://` and the quotes) → Commit.
      *(The build refuses to run until this is done — it checks.)*

---

## STEP 5 — Build the real Android APK in the cloud (10 min, no downloads)

GitHub's servers do the Android Studio work for you.

- [ ] Repository → **Actions** tab → **Build Android APK** (left sidebar) →
      **Run workflow** ▸ → green **Run workflow**.
- [ ] Wait ~8 min for the **green tick** ✅.
      (Red ✗? Open the run → click the red step → copy the text → paste it
      to Claude → get the exact fix.)
- [ ] Open the finished run → bottom → **Artifacts** → download
      **HealthBuddy-APK** (small zip) → extract → `app-debug.apk` →
      WhatsApp it to your phone → tap → *Install anyway* (normal warning
      for test builds) → installed.

Behind the scenes the build: bundles your screens INTO the app (guaranteed
sensor bridge), injects `StepsPlugin` (hardware step counter, with midnight
and reboot handling) and `UsagePlugin` (screen time — same source as
Digital Wellbeing), adds the permissions, points everything at your server.

---

## STEP 6 — The moment of truth 🎉 (5 min, do it as a team)

In the NEW app (the one installed from `app-debug.apk`):

- [ ] Profile → Data & Permissions → **Connect** on Activity/Steps →
      Android asks *"Allow HealthBuddy to access your physical activity?"*
      → **Allow**.
- [ ] Pocket the phone, **walk around the room 2 minutes**, reopen →
      the Home steps card shows a number that grew by itself. That's the
      hardware sensor. Nobody typed anything.
- [ ] **Connect** on Screen Time → system settings opens → find HealthBuddy
      → flip the switch → back → real minutes appear (compare with
      Settings → Digital Wellbeing — they'll match).
- [ ] Both now re-sync automatically every 15 minutes and on every app
      open, and power the smart nudges (goal hit → "your legs showed up
      today 🔥" instead of walk reminders).

**If Connect ever shows a "type it yourself" popup**, you're in the website
version (Chrome/home-screen shortcut), not the APK — browsers can never
read sensors, and the app says so honestly. Open the installed APK instead.

---

## STEP 7 — iPhone users (honest version)

- **Today:** they use the Step 3 install — the full app, minus sensors.
- **Automatic steps (fully allowed by Apple):** needs a Mac + Apple
  Developer account ($99/yr). On the Mac, in `native/`:
  `npm install @capgo/capacitor-health && npx cap add ios && npx cap sync`,
  open in Xcode, enable the HealthKit capability, build. The app's code
  already speaks HealthKit — users get Apple's standard permission sheet.
- **Screen time:** Apple lets apps *display* it in a sealed view only —
  the numbers can't be exported for nudges, and it needs special Apple
  entitlement approval. That's an Apple rule for every app on Earth. The
  app already tells iPhone users this gracefully.

---

## FOREVER AFTER — updating your live product

| You changed… | Do… | Users get it… |
|---|---|---|
| Server stuff: nudges, cards, plans, predictions, API (anything in `healthbuddy/services`, `routes`, `content/`) | push to GitHub | instantly, everywhere — website AND installed APKs |
| Screens: `app.js`, `features.js`, `styles.css`, `index.html` | push to GitHub → website updates instantly; press **Run workflow** again for a fresh APK | website: instantly · APK: on reinstall |
| Native sensor code in `native/` | push + Run workflow | on reinstall |

Before every push: `python -m unittest discover tests` → 46 greens = safe.
Team rhythm: A writes nudges & talks to users · B owns screens · C owns
GitHub/Render/APK builds and backups.

## Play Store (when ready for the public, not needed for the pilot)
One-time $25 Google Play account → Android Studio's *Generate Signed App
Bundle* (or ask Claude for the signed-build workflow) → declare Usage
Access as digital-wellbeing functionality → link a privacy page (your Data
& Permissions text, nearly verbatim). Sideloading is fine until then.

## Troubleshooting
| Problem | Fix |
|---|---|
| Render deploy fails | Render → Logs → copy red lines → Claude |
| Build workflow red ✗ | open run → red step → copy text → Claude |
| APK installs, blank screen | wrong/missing `https://` URL in Step 4 |
| Steps stay 0 after Allow | walk 20+ steps, reopen (sensors report in batches) |
| Screen-time switch missing | some phone brands hide it under Settings → Apps → Special access → Usage access |
| Anything else | exact error → Claude → exact fix |
