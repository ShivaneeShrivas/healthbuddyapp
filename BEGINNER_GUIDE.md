# HealthBuddy — The Complete Beginner's Guide

Written for someone who has **never built an app before**. Read it top to
bottom once, then use it as a checklist. Every technical word is explained
the first time it appears, and there's a glossary at the very end.

---

## Part 1 — What you actually have right now

Think of HealthBuddy like a restaurant:

- **The frontend** = the dining area. Everything the user sees and taps:
  screens, buttons, colors. In your project this is the `healthbuddy/static`
  and `healthbuddy/templates` folders.
- **The backend** = the kitchen. Invisible to users, it does the real work:
  checks passwords, saves water logs, predicts periods, decides which nudge
  you get. This is the Python code in `healthbuddy/services` and
  `healthbuddy/routes`.
- **The database** = the storeroom. One file (`healthbuddy.db`) where all
  user data is kept: accounts, logs, scores, cycle dates.
- **The prototype HTML file** = a plastic display model of the restaurant.
  Looks real, works when you tap it, but the kitchen is fake (demo data).
  Great for showing people; not the real product.

Map of the zip (only the folders you'll actually touch):

```
healthbuddy/
├── run.py                     ← the "ON switch" for your laptop
├── seed.py                    ← fills the app with starter content once
├── requirements.txt           ← the shopping list of tools Python needs
├── content/
│   └── cards.json             ← ✏️ all 60 nudge cards (plain text, edit freely)
├── healthbuddy/
│   ├── config.py              ← ✏️ XP amounts, category colors/emoji
│   ├── services/
│   │   ├── notify.py          ← ✏️ YOUR FUN NOTIFICATIONS live here
│   │   ├── cycle.py           ← period tracking brain
│   │   ├── bandit.py          ← the "learns what you like" brain
│   │   ├── games.py           ← mind-games scoring
│   │   └── wrapped.py         ← weekly recap builder
│   ├── static/
│   │   ├── styles.css         ← ✏️ every color, font, and size
│   │   ├── app.js             ← main screens
│   │   └── features.js        ← games, wrapped, period-care screens
│   └── templates/index.html   ← the single page that loads everything
└── tests/                     ← robots that check nothing is broken
```

✏️ = the four files you'll edit 90% of the time. **You can change the app's
entire personality without touching anything else.**

---

## Part 2 — Run the app on your own laptop (30–45 minutes, one time)

### Step 1. Install Python
Python is the language the kitchen is written in.
1. Go to https://python.org/downloads and click the big yellow button.
2. **Windows, IMPORTANT:** on the first install screen, tick the checkbox
   **"Add Python to PATH"** before clicking Install. (Mac: just install.)
3. Check it worked: open **Command Prompt** (Windows: press Start, type
   `cmd`) or **Terminal** (Mac), type `python --version` and press Enter.
   Seeing something like `Python 3.12` = success.

### Step 2. Install VS Code (your editor)
This is like MS Word, but for code. Free, from https://code.visualstudio.com.
You'll use it to open the project folder and edit files.

### Step 3. Unzip and open the project
1. Unzip `healthbuddy.zip` somewhere easy, e.g. `Documents/healthbuddy`.
2. Open VS Code → File → Open Folder → pick that folder.
3. In VS Code, open the built-in terminal: menu **Terminal → New Terminal**.
   Every command below is typed there, then Enter.

### Step 4. Install the app's tools (once)
```
pip install -r requirements.txt
```
This reads the "shopping list" and downloads the three tools the kitchen
needs. Takes a minute.

### Step 5. Add the starter content (once)
```
python seed.py --demo
```
This loads the 60 nudge cards, 3 challenges, and creates a test account:
**demo@healthbuddy.app / demopass123**

### Step 6. Turn it on
```
python run.py
```
You'll see `Running on http://127.0.0.1:8000`. That means: the app is now
running **on your laptop only**. Open a browser, go to
**http://localhost:8000** — that's your real app, real database and all.

To stop it: click in the terminal and press **Ctrl+C**. To start again:
`python run.py`. That's the whole cycle.

### Step 7. See it like a phone
In the browser press **F12**, then click the little phone/tablet icon
(top-left of the panel that opens). The page reshapes to phone size.

---

## Part 3 — How to change things (the part you asked about most)

Golden rule: **edit → save the file → refresh the browser.** That's it.
(If you changed a Python file, also press Ctrl+C and `python run.py` again —
the kitchen has to restart to read new recipes; the dining room doesn't.)

### "I want to add/change a fun notification"
Open `healthbuddy/services/notify.py`. Find `TEMPLATES = [`. Each line is one
notification:
```python
("legs_texted", "inactive", (10, 20), False, "🦵", "1 new message",
 "Your legs texted. They said 'we exist.' Please reply with a walk.", 3),
```
Reading left to right: a nickname for it · **when it applies** ("inactive" =
user hasn't done anything today) · the hours it may fire (10:00–20:00) ·
weekend-only? · emoji · title · your message · priority (bigger = more
important). Copy a line, change the words, save. Done — you've written a
notification. The conditions you can use are listed in the `_context`
function just below (water_low, no_sleep_log, late_night, long_session,
inactive, daily_game_pending, or "any").

### "I want to change/add nudge cards"
Open `content/cards.json` — it's plain text. Copy any block between `{ }`,
change the words, save, then run `python seed.py` once to load them in.

### "I want to change colors or fonts"
Open `healthbuddy/static/styles.css`. The first 20 lines are the whole color
scheme (`--bg` is the background, `--brand-a`/`--brand-b` make the
orange-pink gradient). Change a color code (pick new ones at
https://coolors.co), save, refresh. The entire app re-paints.

### "I want to change the daily plan or its bonus"
Tasks come from `healthbuddy/services/daily_plan.py` (which categories suit
morning/afternoon/night are at the top in `SLOT_LEANINGS`). The +30 bonus
amount lives in `config.py` under `daily_plan_bonus`.

### "I want to change what counts as 'low steps' or edit step nudges"
`healthbuddy/services/notify.py` — the step templates are near the top, and
the thresholds (40% of goal = low, 80% = close) are in `_context`.

### "I want to change the logo"
Replace one file: `healthbuddy/static/logo.svg` (plus the icon PNGs for the
home-screen icon). Every screen updates automatically.

### "I want to change XP amounts or category emoji"
`healthbuddy/config.py` — everything's at the top, labelled.

### "I want to change words on a screen"
Screens live in `healthbuddy/static/app.js` (main) and `features.js`
(games/wrapped/period care). In VS Code press **Ctrl+Shift+F** and search for
the exact words you see on screen — it jumps you to the right line. Change the
words between the quotes. Don't touch the `${...}` parts (those are filled in
automatically).

### The safety net
After any change, run:
```
python -m unittest discover tests
```
25 robot checks run. `OK` = you broke nothing. An error = it names the exact
file and line to look at. **This is what makes the app safe for you to
modify** — you can't silently break login or predictions without a robot
yelling.

---

## Part 4 — Put it on the internet (so anyone can use it)

Right now the app runs only on your laptop. "Deploying" just means renting a
computer that never sleeps and running `python run.py` there. The service
below has a free tier and no credit card needed.

Using **Render** (https://render.com):
1. First put your code on **GitHub** (a free online locker for code):
   create an account at https://github.com, click **New repository**, name it
   `healthbuddy`, then follow its "upload existing files" option and drag
   your project folder's contents in. (Ask Person C to do this via `git`
   later — the drag-and-drop way works for day one.)
2. Create a free account on render.com → **New → Web Service** → connect
   your GitHub → pick the `healthbuddy` repository.
3. Fill three boxes:
   - **Build command:** `pip install -r requirements.txt && python seed.py`
   - **Start command:** `gunicorn -w 2 -b 0.0.0.0:$PORT "healthbuddy:create_app()"`
   - **Environment variables:** add one called `HB_SECRET_KEY`, value = any
     long random gibberish (60+ characters, keep it secret; it's what makes
     login tokens unforgeable).
4. Click deploy. After ~3 minutes you get a link like
   `https://healthbuddy.onrender.com`. **That's your app, live on the
   internet.** Send it to friends.
5. Every time you push a change to GitHub, Render redeploys automatically —
   this is why future changes stay easy.

(One honest note: the free tier "sleeps" after 15 quiet minutes and takes
~30 seconds to wake on the next visit. Fine for a pilot; the ~$7/month tier
removes it later.)

## Part 5 — Make it feel like a phone app (already wired in!)

Your app is a **PWA** (Progressive Web App): open your Render link on a
phone in Chrome → menu (⋮) → **"Add to Home screen."** It gets an icon
(green sprout, already made), opens full-screen with no browser bar, and
looks/feels like an installed app. **This is your launch strategy — no app
store, no approval process, live today.**

## Part 6 — Real pop-up notifications on the phone

How it works, in plain words: your server can't just shout at phones. Google
runs a messenger service called **Firebase Cloud Messaging (FCM)** — free —
that all Android phones (and Chrome) listen to. Your server hands FCM a
message + a phone's "address" (called a device token), FCM pops it up on that
phone, even if the app is closed.

The clever part is already built: `notify.py` **decides** what to say and to
whom, respecting quiet hours (no messages while users sleep). What's left is
the **delivery pipe**, in this order (this is Person C's Month-2 project,
detailed technically in DEPLOYMENT.md "Phase 2"):
1. Create a free Firebase project at https://console.firebase.google.com.
2. Add a tiny endpoint where phones register their token (a "give me your
   address" form).
3. Run a second small program (`push_worker.py`) beside the app that, every
   20 minutes, asks `notify.py` "anything to say to anyone?" and hands
   results to FCM.

One honest limitation: **screen-time nudges** ("scrolling long enough to bake
bread") can't come from the server — it can't see the user's screen. Those
need the *phone itself* to run the logic, which requires wrapping your PWA
into a real installable app (a free tool called **Capacitor** does this — it
puts your existing web app inside an Android app shell). That's also the door
to the Play Store, step counting via Google Fit, and it's a Month-3 project,
not a launch blocker.

## Part 7 — Other connections (your Google Calendar question)

- **Google Calendar** — already built, and the right way: OFF by default,
  the user opts in, and only *predicted period dates* are shared, nothing
  else. You don't need Calendar for anything more; your own database stores
  everything (as your spec required).
- **Weather (recommended, easy):** your rain/heat notifications currently
  fire on a schedule. Connect **Open-Meteo** (https://open-meteo.com — free,
  no signup) so "it's so hot even your ice cream is sweating" fires only when
  it's actually 38°C. This is a fun 20-line task for Person C in week 3.
- **Steps / Google Fit / Apple Health:** needs the Capacitor phone-app wrap
  (Month 3). Until then, movement nudges work on "did you act on nudges"
  instead of step counts — already handled.
- **You do NOT need:** your own servers, a company, or paid accounts for
  anything above. Everything in this guide is free-tier.

---

## Part 8 — The plan for your team of 3

Give each person a lane so nobody blocks anybody:

**Person A — Product & Content (no coding needed to start)**
Owns the app's personality. Writes new notifications in `notify.py` and cards
in `cards.json` (the two easiest files in the project). Tests every screen on
their own phone weekly and keeps a bug list. Recruits the first 20 users and
collects their feedback. Decides what gets built next.

**Person B — Design & Frontend**
Owns everything users see. Learns `styles.css` first (colors/fonts), then
`app.js`/`features.js` (screens and words). Makes the app feel great on small
phones, polishes the games and Wrapped cards, designs a proper logo to
replace the generated icon.

**Person C — Backend & Deployment ("the plumber")**
Owns everything invisible. Does Part 4 (GitHub + Render) in week 1, learns to
read `services/` code, sets up Firebase push (Part 6), adds the weather
hookup, keeps the tests green, and takes daily database backups once real
users arrive.

**A realistic 4-week schedule:**
- **Week 1:** everyone does Part 2 on their own laptop. Person C also
  finishes Part 4 → you have a live link. Person A starts rewriting
  notification copy in their own voice.
- **Week 2:** soft launch — the 3 of you + ~10 friends install it from the
  link (Part 5). Person A collects every complaint. Person B fixes the top 5
  visual annoyances. Person C sets up nightly database backup on Render.
- **Week 3:** Person C starts Firebase push + weather. Person B polishes
  games/Wrapped based on feedback. Person A grows the card bank toward 100+.
- **Week 4:** push notifications go live to your pilot group (with the max
  4-per-day cap!). Review what people actually acted on — the app's
  learning stats (Profile → "Why am I seeing this?") tell you.

---

## Glossary (one-liners)

- **Frontend / Backend** — what users see / the invisible kitchen doing the work.
- **Database** — the file where all user data is saved.
- **API** — the waiter: how frontend asks backend for things ("log 1 water").
- **Server** — any computer running your backend; "deploying" = renting one online.
- **localhost:8000** — "this app, running on my own machine."
- **GitHub** — online locker for code; also your undo-history and team-sharing tool.
- **Render** — the company whose computer runs your app 24/7 (free tier).
- **Environment variable** — a secret setting (like your `HB_SECRET_KEY`) stored
  outside the code so it's never accidentally shared.
- **PWA** — a website that installs like an app. What you have now.
- **FCM / Firebase** — Google's free service that pops notifications on phones.
- **Device token** — a phone's postal address for notifications.
- **Capacitor** — free tool that wraps your web app into a real Android/iOS app.
- **Tests** — robot checks (`python -m unittest discover tests`) that catch mistakes.

**Where to get unstuck:** paste any error message into Claude or Google —
90% of beginner errors are one missing command. And every file in this
project has comments at the top explaining what it does. You've got this. 🌱
