/* HealthBuddy SPA — vanilla JS, no build step.
   Structure: api client → tiny helpers → views → router → boot. */
"use strict";

const $screen = document.getElementById("screen");
const $tabbar = document.getElementById("tabbar");
const state = {
  token: localStorage.getItem("hb_token"),
  refreshToken: localStorage.getItem("hb_refresh"),
  user: null,
};

/* ---------------- API client ---------------- */
/* In the native phone app, the screens are bundled locally and talk to the
   server across the network; HB_API_BASE carries the server address then.
   On the website it's empty and everything works same-origin as before. */
const API_BASE = window.HB_API_BASE || "";

function saveSession(data) {
  state.token = data.token;
  localStorage.setItem("hb_token", data.token);
  if (data.refresh_token) {
    state.refreshToken = data.refresh_token;
    localStorage.setItem("hb_refresh", data.refresh_token);
  }
  if (data.user) state.user = data.user;
}

async function rawApi(path, { method = "GET", body } = {}) {
  const res = await fetch(API_BASE + "/api" + path, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(state.token ? { Authorization: "Bearer " + state.token } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  return { res, data };
}

/* Swaps the (possibly expired) access token for a fresh one using the
   long-lived refresh token, without bothering the user. Returns true on
   success so the caller can retry the original request. */
let _refreshing = null;
async function silentRefresh() {
  if (!state.refreshToken) return false;
  if (!_refreshing) {
    _refreshing = rawApi("/auth/refresh", { method: "POST", body: { refresh_token: state.refreshToken } })
      .then(({ res, data }) => {
        if (!res.ok) throw new Error(data.error || "refresh failed");
        saveSession(data);
        return true;
      })
      .catch(() => { clearSession(); return false; })
      .finally(() => { _refreshing = null; });
  }
  return _refreshing;
}

async function api(path, opts = {}) {
  let { res, data } = await rawApi(path, opts);
  if (res.status === 401 && path !== "/auth/refresh") {
    const recovered = await silentRefresh();
    if (recovered) ({ res, data } = await rawApi(path, opts));
  }
  if (!res.ok) {
    if (res.status === 401 && state.user) return logout();
    throw new Error(data.error || "Something went wrong. Try again.");
  }
  return data;
}

/* ---------------- helpers ---------------- */
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function toast(msg, cls = "") {
  const el = document.createElement("div");
  el.className = "toast " + cls;
  el.textContent = msg;
  document.getElementById("toast-zone").appendChild(el);
  setTimeout(() => el.remove(), 2600);
}

function rewardFeedback({ xp_earned, new_badges }) {
  if (xp_earned) toast(`+${xp_earned} XP ✨`, "xp");
  (new_badges || []).forEach((b) =>
    modal(`<span class="big-em">${b.emoji}</span>
           <h2>Badge earned!</h2><h3>${esc(b.name)}</h3>
           <p class="muted">${esc(b.desc)}</p>
           <button class="btn btn-primary btn-block section-gap" data-close>Nice!</button>`));
}

function modal(html) {
  const wrap = document.createElement("div");
  wrap.className = "modal-backdrop";
  wrap.innerHTML = `<div class="modal" role="dialog" aria-modal="true">${html}</div>`;
  wrap.addEventListener("click", (e) => {
    if (e.target === wrap || e.target.closest("[data-close]")) wrap.remove();
  });
  document.getElementById("modal-zone").appendChild(wrap);
  wrap.querySelector("button, [tabindex]")?.focus();
}

function render(html) {
  $screen.innerHTML = html;
  $screen.focus({ preventScroll: true });
  window.scrollTo(0, 0);
}

function clearSession() {
  localStorage.removeItem("hb_token");
  localStorage.removeItem("hb_refresh");
  state.token = null; state.refreshToken = null; state.user = null;
}

function logout() {
  const refreshToken = state.refreshToken;
  clearSession();
  go("welcome");
  // Best-effort revoke so this device can't silently refresh again; the user
  // is already signed out locally regardless of whether this call succeeds.
  if (refreshToken) {
    rawApi("/auth/logout", { method: "POST", body: { refresh_token: refreshToken } }).catch(() => {});
  }
}

/* ---------------- theme ---------------- */
function currentTheme() { return document.documentElement.getAttribute("data-theme") || "dark"; }
function applyTheme(t) {
  document.documentElement.setAttribute("data-theme", t);
  localStorage.setItem("hb_theme", t);
  const meta = document.getElementById("theme-color-meta");
  if (meta) meta.setAttribute("content", t === "light" ? "#FFF9F4" : "#1C1526");
  document.querySelectorAll("[data-theme-toggle]").forEach((b) => { b.textContent = t === "light" ? "🌙" : "☀️"; });
  document.querySelectorAll("[data-theme-opt]").forEach((b) =>
    b.setAttribute("aria-pressed", String(b.dataset.themeOpt === t)));
}
function toggleTheme() { applyTheme(currentTheme() === "light" ? "dark" : "light"); }

/* ---------------- buddy companion ----------------
   One shared mascot, many poses. computeBuddyState() picks a pose from
   time-of-day + today's progress; setBuddyMood() briefly overrides it
   right after a log so the buddy visibly reacts to what you just did. */
const BUDDY = {
  baseline:  { src: "/static/buddy/buddy-baseline.png",  line: "Ready when you are!" },
  water:     { src: "/static/buddy/buddy-water.png",     line: "Ahh, refreshing! 💧" },
  meal:      { src: "/static/buddy/buddy-meal.png",      line: "Yum, thanks for feeding us! 🍽️" },
  sleepy:    { src: "/static/buddy/buddy-sleepy.png",    line: "Getting cozy… 😴" },
  tired:     { src: "/static/buddy/buddy-tired.png",     line: "Rough one, huh? Let's ease into it." },
  ready:     { src: "/static/buddy/buddy-ready.png",     line: "Let's crush today! 💪" },
  celebrate: { src: "/static/buddy/buddy-celebrate.png", line: "WOO! Everything's logged today!! 🎉" },
  morning:   { src: "/static/buddy/buddy-morning.png",   line: "Good morning! Coffee's on ☕" },
};
const PET_LINES = [
  "Hehe, that tickles! 😄", "You're doing great today 🌟", "Let's keep that streak alive!",
  "I believe in you 💚", "Small steps count too.", "Proud of you for showing up.",
];
state.buddyMood = null; // { key, until }

function computeBuddyState(d) {
  if (state.buddyMood && Date.now() < state.buddyMood.until) return state.buddyMood.key;
  const hr = new Date().getHours();
  const today = (d && d.score && d.score.today) || {};
  const allDone = HABITS.every((h) => {
    const t = today[h.type] || { count: 0, total: 0 };
    return h.type === "water" ? (t.total || 0) >= h.target : h.type === "meal" ? t.count >= h.target : t.count > 0;
  });
  if (allDone) return "celebrate";
  if (hr >= 22 || hr < 6) return "sleepy";
  if (hr >= 6 && hr < 11) return "morning";
  return "baseline";
}

function setBuddyMood(key, ms = 4500) {
  state.buddyMood = { key, until: Date.now() + ms };
  setTimeout(() => {
    if (state.buddyMood && state.buddyMood.key === key && Date.now() >= state.buddyMood.until) {
      state.buddyMood = null;
      paintBuddy();
    }
  }, ms + 30);
}

function buddyHeroHTML(d) {
  const key = computeBuddyState(d);
  const b = BUDDY[key] || BUDDY.baseline;
  return `<div class="buddy-hero" id="buddy-hero" data-mood="${key}">
    <div class="buddy-badge" id="buddy-badge"><img src="${b.src}" alt="Your HealthBuddy buddy" class="buddy-img"></div>
    <p class="buddy-line small muted" id="buddy-line">${esc(b.line)}</p>
    <p class="buddy-hint small">tap your buddy to say hi</p>
  </div>`;
}

function paintBuddy(d) {
  const holder = document.getElementById("buddy-hero");
  if (!holder) return;
  const key = computeBuddyState(d || state.lastDashboard);
  const b = BUDDY[key] || BUDDY.baseline;
  holder.dataset.mood = key;
  const img = holder.querySelector(".buddy-img");
  if (img && !img.src.endsWith(b.src)) img.src = b.src;
  const line = document.getElementById("buddy-line");
  if (line) line.textContent = b.line;
}

function petBuddy() {
  const el = document.getElementById("buddy-badge");
  if (!el) return;
  el.classList.remove("boop");
  void el.offsetWidth; // restart animation
  el.classList.add("boop");
  toast(PET_LINES[Math.floor(Math.random() * PET_LINES.length)]);
}

document.addEventListener("click", (e) => {
  if (e.target.closest("#buddy-badge")) petBuddy();
  if (e.target.closest("[data-theme-toggle]")) toggleTheme();
  const opt = e.target.closest("[data-theme-opt]");
  if (opt) applyTheme(opt.dataset.themeOpt);
});

/* ---------------- views ---------------- */
const views = {};

views.welcome = () => {
  $tabbar.classList.add("hidden");
  render(`
    <button class="theme-toggle" data-theme-toggle aria-label="Toggle light/dark theme">${currentTheme() === "light" ? "🌙" : "☀️"}</button>
    <div class="welcome">
      <div class="logo"><div class="app-icon-badge"><img src="/static/icon-192.png" alt="HealthBuddy"></div></div>
      <h1>Hey! I'm <span class="brand-name">HealthBuddy</span></h1>
      <p class="muted">Your friendly nudge companion — not a clinical tracker.
      Tiny healthy habits, one fun nudge at a time.</p>
      <button class="btn btn-primary btn-block" data-go="register">Get started</button>
      <button class="btn btn-ghost btn-block" data-go="login">I already have an account</button>
    </div>`);
};

function authForm(mode) {
  $tabbar.classList.add("hidden");
  const isReg = mode === "register";
  render(`
    <div style="max-width:400px;margin:40px auto 0">
      <h1>${isReg ? "Create your account" : "Welcome back!"}</h1>
      <p class="muted" style="margin-bottom:24px">${isReg ? "Two fields and a password — that's it." : "Good to see you again."}</p>
      ${isReg ? `<div class="field"><label for="f-name">Name</label><input id="f-name" autocomplete="name"></div>` : ""}
      <div class="field"><label for="f-email">Email</label><input id="f-email" type="email" autocomplete="email"></div>
      <div class="field"><label for="f-pass">Password</label><input id="f-pass" type="password" autocomplete="${isReg ? "new-password" : "current-password"}"></div>
      <p class="form-error" id="f-err" role="alert"></p>
      <button class="btn btn-primary btn-block" id="f-submit">${isReg ? "Create account" : "Sign in"}</button>
      <button class="btn btn-ghost btn-block section-gap" data-go="${isReg ? "login" : "register"}">
        ${isReg ? "I already have an account" : "I'm new here"}</button>
    </div>`);
  document.getElementById("f-submit").onclick = async () => {
    const err = document.getElementById("f-err");
    err.textContent = "";
    try {
      const body = {
        email: document.getElementById("f-email").value,
        password: document.getElementById("f-pass").value,
      };
      if (isReg) body.name = document.getElementById("f-name").value;
      const data = await api("/auth/" + mode, { method: "POST", body });
      saveSession(data);
      go(data.user.onboarded ? "home" : "onboarding");
    } catch (e) { err.textContent = e.message; }
  };
}
views.register = () => authForm("register");
views.login = () => authForm("login");

/* --- brand logo (reusable; swap logo.svg to rebrand everywhere at once) --- */
const logoImg = (size) =>
  `<img src="/static/logo.svg" width="${size}" height="${size}" alt="" class="brand-logo" aria-hidden="true">`;

/* --- onboarding (4-step stepper) --- */
const OB_STEPS = [
  { key: "health_goals", multi: true, q: "What are your goals right now?",
    hint: "Pick as many as you like.", opts: [
    ["fitness", "💪", "Get fitter"], ["stress", "🧘", "Manage stress"],
    ["sleep", "😴", "Sleep better"], ["eat_better", "🥗", "Eat better"],
    ["general", "✨", "General wellness"]] },
  { key: "occupation", q: "What describes you best?", opts: [
    ["student", "🎓", "Student"], ["professional", "💼", "Working professional"],
    ["other", "🤝", "Other / prefer not to say"]] },
  { key: "activity_level", q: "How active are you these days?", opts: [
    ["active", "🏃", "Pretty active"], ["moderate", "🚶", "Somewhat active"],
    ["inactive", "🛋️", "Not really active"]] },
  { key: "gender", q: "How do you identify? (only used to pick better card content)", opts: [
    ["female", "🙋‍♀️", "Female"], ["male", "🙋‍♂️", "Male"],
    ["nonbinary", "🧑", "Non-binary"], ["prefer_not", "🤐", "Prefer not to say"]] },
];

views.onboarding = () => {
  $tabbar.classList.add("hidden");
  const answers = {};
  let step = 0;
  const finish = async () => {
    try {
      const data = await api("/onboarding", { method: "POST", body: answers });
      state.user = data.user;
      rewardFeedback({ xp_earned: data.xp_earned, new_badges: [] });
      toast("You're all set! 🌱");
      setBuddyMood("celebrate", 6000);
      go("home");
    } catch (e) { toast(e.message); }
  };
  const advance = () => {
    if (step < OB_STEPS.length - 1) { step++; setTimeout(draw, 180); } else finish();
  };
  const draw = () => {
    const s = OB_STEPS[step];
    render(`
      <div style="max-width:400px;margin:24px auto 0">
        <div class="progress" role="progressbar" aria-valuenow="${step + 1}" aria-valuemin="1" aria-valuemax="4"
             aria-label="Onboarding step ${step + 1} of 4"><div style="width:${((step + 1) / 4) * 100}%"></div></div>
        <h2>${s.q}</h2>
        ${s.hint ? `<p class="muted small">${s.hint}</p>` : ""}
        <div class="choice-grid">
          ${s.opts.map(([v, em, label]) =>
            `<button class="choice" data-v="${v}" aria-pressed="false">
               <span class="em" aria-hidden="true">${em}</span>${label}</button>`).join("")}
        </div>
        ${s.multi ? `<button class="btn btn-primary btn-block section-gap" id="ob-next" disabled>Continue</button>` : ""}
        <p class="muted small">Your answers set your starting nudges. HealthBuddy keeps learning from what you actually do.</p>
      </div>`);
    if (s.multi) {
      const picked = new Set(answers[s.key] || []);
      const sync = () => {
        $screen.querySelectorAll(".choice").forEach((b) =>
          b.setAttribute("aria-pressed", String(picked.has(b.dataset.v))));
        document.getElementById("ob-next").disabled = picked.size === 0;
      };
      $screen.querySelectorAll(".choice").forEach((btn) => btn.onclick = () => {
        picked.has(btn.dataset.v) ? picked.delete(btn.dataset.v) : picked.add(btn.dataset.v);
        answers[s.key] = [...picked];
        sync();
      });
      document.getElementById("ob-next").onclick = advance;
      sync();
    } else {
      $screen.querySelectorAll(".choice").forEach((btn) => {
        btn.onclick = () => {
          btn.setAttribute("aria-pressed", "true");
          answers[s.key] = btn.dataset.v;
          advance();
        };
      });
    }
  };
  draw();
};

/* --- home dashboard --- */
const HABITS = [
  { type: "water", emoji: "💧", label: "Water", unit: "glasses", value: 1, target: 8 },
  { type: "meal", emoji: "🍽️", label: "Meals", unit: "meals", value: 1, target: 3 },
  { type: "sleep", emoji: "😴", label: "Sleep", unit: "hours", value: 8, target: 1, prompt: true },
  { type: "mood", emoji: "🙂", label: "Mood", unit: "1–5", value: 4, target: 1, prompt: true, min: 1, max: 5 },
];

views.home = async () => {
  showTabs("home");
  Providers.syncDeviceData?.(); // pull real device steps/screen-time when the phone allows it
  const d = await api("/dashboard");
  state.lastDashboard = d;
  const pct = d.score.score, C = 2 * Math.PI * 80;
  const hello = new Date().getHours() < 12 ? "Good morning" : new Date().getHours() < 17 ? "Good afternoon" : "Good evening";
  render(`
    <button class="theme-toggle" data-theme-toggle aria-label="Toggle light/dark theme">${currentTheme() === "light" ? "🌙" : "☀️"}</button>
    <div class="row-between home-head">
      <div><h1>${hello}, ${esc(d.greeting_name)}!</h1>
      <p class="muted">Level ${d.level} · ${d.xp} XP</p></div>
      ${logoImg(40)}
    </div>
    ${buddyHeroHTML(d)}
    <div class="ring-wrap"><div class="ring">
      <svg width="190" height="190" viewBox="0 0 190 190" role="img" aria-label="Today's health score: ${pct} out of 100">
        <defs><linearGradient id="ringGrad" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stop-color="#FF8A5C"/><stop offset="1" stop-color="#FF5C8A"/></linearGradient></defs>
        <circle class="track" cx="95" cy="95" r="80" fill="none" stroke-width="16"/>
        <circle class="arc" cx="95" cy="95" r="80" fill="none" stroke-width="16"
          stroke-dasharray="${C}" stroke-dashoffset="${C * (1 - pct / 100)}"/>
      </svg>
      <div class="ring-center"><span class="score">${pct}</span><span class="muted small">today's score</span></div>
    </div></div>

    <div id="daily-plan-slot"><div class="card"><p class="muted">Loading today's plan…</p></div></div>

    <h2 class="section-gap">Today's checklist</h2>
    <div class="checklist">
      ${HABITS.map((h) => {
        const t = d.score.today[h.type] || { count: 0, total: 0 };
        const done = h.type === "water" ? `${t.total || 0}/${h.target}` :
                     h.type === "meal" ? `${t.count}/${h.target}` :
                     t.count > 0 ? "logged" : "not yet";
        const isDone = h.type === "water" ? (t.total || 0) >= h.target :
                       h.type === "meal" ? t.count >= h.target : t.count > 0;
        return `<div class="check-row ${state.justLogged === h.type ? "pop" : ""}">
          <span class="em" aria-hidden="true">${h.emoji}</span>
          <div class="grow"><strong>${h.label}</strong>
            <span class="chip ${isDone ? "done" : ""}">${done}</span></div>
          ${(h.type === "water" ? (t.total || 0) : t.count) > 0
            ? `<button class="btn btn-ghost btn-sm btn-minus" data-unlog="${h.type}" aria-label="Undo last ${h.label} log">−</button>` : ""}
          <button class="btn btn-primary btn-sm" data-log="${h.type}" aria-label="Log ${h.label}">＋ Log</button>
        </div>`;
      }).join("")}
    </div>

    <h2 class="section-gap">Streaks 🔥</h2>
    <div class="streak-strip">
      ${HABITS.map((h) => `<div class="streak-pill"><span aria-hidden="true">${h.emoji}</span>
        <div class="n">${d.streaks[h.type]}</div><div class="muted small">day${d.streaks[h.type] === 1 ? "" : "s"}</div></div>`).join("")}
    </div>`);

  $screen.querySelectorAll("[data-log]").forEach((btn) => {
    btn.onclick = () => quickLog(HABITS.find((h) => h.type === btn.dataset.log));
  });
  $screen.querySelectorAll("[data-unlog]").forEach((btn) => btn.onclick = async () => {
    try {
      const { message } = await api(`/logs/${btn.dataset.unlog}`, { method: "DELETE" });
      toast(message);
      views.home();
    } catch (e) { toast(e.message); }
  });
  loadDailyPlan();
  loadActivityCard(d);
  loadScreenTimeCard();
  state.justLogged = null;
};

/* --- Today's Plan: ONE task at a time, with a countdown ---------------
   Morning 6:00–12:00 · Afternoon 12:00–18:00 · Night 18:00–23:00.
   Complete it inside the window → XP. Window closes → the task retires
   gracefully and the next one takes the stage. All 3 done → +30 bonus. */
const PLAN_WINDOWS = { morning: [6, 12], afternoon: [12, 18], night: [18, 23] };
let planTimer = null;

function fmtLeft(ms) {
  const m = Math.max(0, Math.floor(ms / 60000));
  return m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m}m`;
}

async function loadDailyPlan() {
  const slot = document.getElementById("daily-plan-slot");
  if (!slot) return;
  if (planTimer) { clearInterval(planTimer); planTimer = null; }
  try {
    const { plan } = await api("/daily-plan");
    const now = new Date();
    const h = now.getHours();
    const tasks = plan.tasks.map((t) => {
      const [a, b] = PLAN_WINDOWS[t.slot];
      const status = t.done ? "done" : h >= b ? "missed" : h >= a ? "active" : "upcoming";
      return { ...t, winStart: a, winEnd: b, status };
    });
    const active = tasks.find((t) => t.status === "active");
    const upcoming = tasks.find((t) => t.status === "upcoming");
    const doneCount = tasks.filter((t) => t.status === "done").length;

    const dots = tasks.map((t) => `
      <span class="plan-dot ${t.status}" title="${t.slot_label}">
        ${t.status === "done" ? "✓" : t.status === "missed" ? "·" : t.slot_emoji}
      </span>`).join('<span class="plan-line"></span>');

    let stage;
    if (active) {
      const endMs = new Date(now).setHours(active.winEnd, 0, 0, 0) - now;
      stage = `
        <div class="card plan-card plan-stage" style="--cat:${active.color}">
          <div class="plan-head">
            <span class="chip">${active.slot_emoji} ${active.slot_label} task</span>
            <span class="chip countdown" id="plan-count" data-end="${active.winEnd}">⏳ ${fmtLeft(endMs)} left</span>
          </div>
          <strong>${active.emoji} ${esc(active.title)}</strong>
          <p class="small">${esc(active.body)}</p>
          <button class="btn btn-primary" data-plan-done="${active.id}">${esc(active.action_label)} ✓ &nbsp;+10 XP</button>
        </div>`;
    } else if (doneCount === 3) {
      stage = `<div class="card plan-stage" style="text-align:center">
        <div style="font-size:40px">🏆</div>
        <strong>All three done — full house!</strong>
        <p class="muted small">${plan.bonus_earned ? "+30 XP bonus banked. " : ""}Fresh plan tomorrow morning 🌅</p></div>`;
    } else if (upcoming) {
      const startMs = new Date(now).setHours(upcoming.winStart, 0, 0, 0) - now;
      stage = `<div class="card plan-stage" style="text-align:center">
        <div style="font-size:34px">${upcoming.slot_emoji}</div>
        <strong>${upcoming.slot_label} task unlocks in ${fmtLeft(startMs)}</strong>
        <p class="muted small">A little mystery keeps it fun. See you at ${upcoming.winStart}:00!</p></div>`;
    } else {
      stage = `<div class="card plan-stage" style="text-align:center">
        <div style="font-size:34px">🌙</div>
        <strong>Day's a wrap${doneCount ? ` — ${doneCount}/3 done` : ""}!</strong>
        <p class="muted small">New plan lands tomorrow at 6:00. Rest up 💜</p></div>`;
    }

    slot.innerHTML = `
      <div class="row-between"><h2>Today's plan 📋</h2>
        <span class="chip ${doneCount === 3 ? "done" : ""}">${doneCount}/3${plan.bonus_earned ? " · +30 ✓" : ""}</span></div>
      <div class="plan-dots" aria-hidden="true">${dots}</div>
      ${stage}`;

    slot.querySelectorAll("[data-plan-done]").forEach((btn) => btn.onclick = async () => {
      try {
        const data = await api(`/nudges/${btn.dataset.planDone}/interact`,
          { method: "POST", body: { action: "acted" } });
        rewardFeedback(data);
        if (data.daily_plan_bonus) toast(`Full house! All 3 done — +${data.daily_plan_bonus} XP bonus 🎉`);
        loadDailyPlan();
      } catch (e) { toast(e.message); }
    });

    /* live countdown, refreshes each minute; flips stages at window edges */
    planTimer = setInterval(() => {
      const c = document.getElementById("plan-count");
      if (!c) { if (new Date().getMinutes() === 0) loadDailyPlan(); return; }
      const left = new Date(new Date().setHours(+c.dataset.end, 0, 0, 0)) - new Date();
      if (left <= 0) return loadDailyPlan();      // window closed → next stage
      c.textContent = `⏳ ${fmtLeft(left)} left`;
    }, 30000);
  } catch (e) {
    slot.innerHTML = `<div class="card"><p class="muted">${esc(e.message)}</p></div>`;
  }
}

/* --- Steps card: honest data or connect/manual fallback, never fake zeros --- */
async function loadActivityCard(dash) {
  const slot = document.getElementById("daily-plan-slot");
  if (!slot) return;
  try {
    const { activity, step_goal } = await api("/activity/today");
    const card = document.createElement("div");
    if (activity) {
      const pct = Math.min(100, Math.round(activity.steps / step_goal * 100));
      const left = Math.max(0, step_goal - activity.steps);
      card.innerHTML = `<div class="card steps-card">
        <div class="row-between"><strong>🚶 Today's steps</strong>
          <span class="muted small">${activity.source === "manual" ? "entered manually" : "synced"}</span></div>
        <div class="steps-n">${activity.steps.toLocaleString()} <span class="muted small">/ ${step_goal.toLocaleString()}</span></div>
        <div class="bar"><div style="width:${pct}%"></div></div>
        <p class="muted small">${left > 0 ? `Keep going! Just ${left.toLocaleString()} steps to your goal 🌱`
          : "Goal reached — your legs definitely showed up today 🔥"}</p>
        ${activity.source === "manual" ? `<button class="btn btn-ghost btn-sm" id="steps-update">Update</button>` : ""}
      </div>`;
    } else {
      return; /* not connected → keep Home clean; setup lives in Profile → Data & Permissions */
    }
    slot.insertAdjacentElement("afterend", card.firstElementChild);
    const upd = document.getElementById("steps-update");
    if (upd) upd.onclick = async () => {
      const v = prompt("How many steps today?", activity ? activity.steps : 5000);
      if (v === null) return;
      try {
        await Providers.activity.manual.submit(parseInt(v, 10));
        toast("Steps saved 🚶 +context for smarter nudges");
        views.home();
      } catch (e) { toast(e.message); }
    };
  } catch (_) { /* card is optional; home still works */ }
}

/* --- Screen time card: shown only when real data exists (never fake) --- */
async function loadScreenTimeCard() {
  const anchor = $screen.querySelector(".steps-card") || document.getElementById("daily-plan-slot");
  if (!anchor) return;
  try {
    const { wellbeing } = await api("/wellbeing/today");
    if (!wellbeing) return;   /* not connected → Home stays clean */
    const m = wellbeing.screen_time_minutes;
    const h = Math.floor(m / 60), mins = m % 60;
    const pretty = h ? `${h}h ${mins}m` : `${mins}m`;
    /* Friendly, never preachy — tone scales with the number, no shaming. */
    const note = m >= 360 ? "Long day on the glass. Your eyes have earned a break 👀"
               : m >= 180 ? "Decent chunk of screen today. Blink twice, look far away 🌿"
               : "Nice and light so far. Your eyes say thanks 💚";
    const card = document.createElement("div");
    card.innerHTML = `<div class="card steps-card">
      <div class="row-between"><strong>📱 Screen time today</strong>
        <span class="muted small">${wellbeing.source === "manual" ? "entered manually" : "synced"}</span></div>
      <div class="steps-n">${pretty}</div>
      <p class="muted small">${note}</p>
      ${wellbeing.source === "manual" ? `<button class="btn btn-ghost btn-sm" id="screen-update">Update</button>` : ""}
    </div>`;
    anchor.insertAdjacentElement("afterend", card.firstElementChild);
    const upd = document.getElementById("screen-update");
    if (upd) upd.onclick = async () => {
      const v = prompt("Roughly how many minutes on screens today?", m);
      if (v === null) return;
      try {
        await Providers.wellbeing.manual.submit(parseInt(v, 10));
        toast("Saved 📱");
        views.home();
      } catch (e) { toast(e.message); }
    };
  } catch (_) { /* optional card */ }
}

async function loadInlineNudge() {
  const slot = document.getElementById("daily-nudge-slot");
  try {
    const { nudge } = await api("/nudges/next");
    if (slot) slot.outerHTML = nudgeCardHTML(nudge, true);
    wireNudgeActions();
  } catch (e) { if (slot) slot.innerHTML = `<p class="muted">${esc(e.message)}</p>`; }
}

async function quickLog(h) {
  let value = h.value;
  if (h.prompt) {
    const raw = prompt(h.type === "sleep" ? "How many hours did you sleep?" : "How's your mood, 1 (rough) to 5 (great)?", h.value);
    if (raw === null) return;
    value = parseFloat(raw);
    if (Number.isNaN(value)) return toast("That needs to be a number.");
  }
  try {
    const data = await api("/logs", { method: "POST", body: { type: h.type, value } });
    rewardFeedback(data);
    if (data.streak >= 2) toast(`${h.emoji} ${data.streak}-day ${h.label.toLowerCase()} streak!`);
    state.justLogged = h.type;
    const moodKey = h.type === "water" ? "water" : h.type === "meal" ? "meal" : h.type === "sleep" ? "sleepy"
      : h.type === "mood" ? (value >= 4 ? "ready" : value <= 2 ? "tired" : "baseline") : "baseline";
    setBuddyMood(moodKey);
    views.home();
  } catch (e) { toast(e.message); }
}

/* --- nudges feed --- */
function nudgeCardHTML(n, fresh = false) {
  return `<article class="nudge-card" style="--cat:${n.color}" data-nudge="${n.id}">
    <div class="nudge-head">
      <span class="nudge-emoji" aria-hidden="true">${n.emoji}</span>
      <div><span class="cat-tag">${esc(n.category_label)}</span>
      <h3>${esc(n.title)}</h3></div>
    </div>
    <p>${esc(n.body)}</p>
    ${fresh ? `<div class="nudge-actions">
      <button class="btn btn-primary btn-sm" data-act="acted">${esc(n.action_label)} ✓</button>
      <button class="btn btn-ghost btn-sm" data-act="snoozed">Remind me later</button>
      <button class="btn btn-ghost btn-sm" data-act="dismissed" aria-label="Not interested">Not for me</button>
    </div>` : ""}
  </article>`;
}

function wireNudgeActions() {
  $screen.querySelectorAll(".nudge-card [data-act]").forEach((btn) => {
    btn.onclick = async () => {
      const card = btn.closest(".nudge-card");
      try {
        const data = await api(`/nudges/${card.dataset.nudge}/interact`,
          { method: "POST", body: { action: btn.dataset.act } });
        rewardFeedback(data);
        if (btn.dataset.act === "acted") toast("Love that for you 💪");
        if (btn.dataset.act === "snoozed") toast("No stress — I'll circle back.");
        card.querySelector(".nudge-actions").remove();
      } catch (e) { toast(e.message); }
    };
  });
}

views.nudges = async () => {
  showTabs("nudges");
  render(`<h1>Nudges ✨</h1>
    <p class="muted">Fresh nudge on top; your recent ones below. Every tap teaches HealthBuddy what works for you.</p>
    <div id="fresh"></div><h2 class="section-gap">Recent</h2><div id="feed"><p class="muted">Loading…</p></div>`);
  try {
    const { nudge } = await api("/nudges/next");
    document.getElementById("fresh").innerHTML = nudgeCardHTML(nudge, true);
    wireNudgeActions();
  } catch (e) { document.getElementById("fresh").innerHTML = `<p class="muted">${esc(e.message)}</p>`; }
  const { feed } = await api("/nudges/feed");
  document.getElementById("feed").innerHTML = feed.length
    ? feed.slice(1).map((n) => nudgeCardHTML(n)).join("") || `<p class="muted">That was your first one!</p>`
    : `<p class="muted">No nudges yet — your first one is waiting above.</p>`;
};

/* --- explore / knowledge hub --- */
views.explore = async () => {
  showTabs("explore");
  render(`<h1>Explore 📚</h1><div id="hero"></div>
    <div class="cat-filter" id="filters" role="group" aria-label="Filter by category"></div>
    <div id="cardlist"><p class="muted">Loading…</p></div>`);
  const [{ card }, all] = await Promise.all([api("/cards/daily"), api("/cards")]);
  document.getElementById("hero").innerHTML = `
    <div class="hero-card"><span class="small" style="font-weight:800">CARD OF THE DAY ${card.emoji}</span>
      <h3>${esc(card.title)}</h3><p class="small">${esc(card.deep_dive || card.body)}</p></div>`;
  let active = null;
  const drawFilters = () => {
    document.getElementById("filters").innerHTML =
      [`<button class="chipbtn" aria-pressed="${active === null}" data-cat="">All</button>`,
        ...all.categories.map((c) =>
          `<button class="chipbtn" style="--cat:${c.color}" aria-pressed="${active === c.key}" data-cat="${c.key}">${c.emoji} ${c.label}</button>`)].join("");
    document.querySelectorAll("#filters .chipbtn").forEach((b) => b.onclick = () => { active = b.dataset.cat || null; drawFilters(); drawList(); });
  };
  const drawList = () => {
    const cards = all.cards.filter((c) => !active || c.category === active);
    document.getElementById("cardlist").innerHTML = cards.map((n) => nudgeCardHTML(n)).join("");
  };
  drawFilters(); drawList();
};

/* --- challenges --- */
views.challenges = async () => {
  showTabs("challenges");
  const { challenges } = await api("/challenges");
  render(`<h1>Challenges 🏆</h1>
    <p class="muted">Opt-in, low pressure, high bragging rights.</p>
    ${challenges.map((c) => `
      <div class="card challenge-card">
        <div class="row-between"><h3>${c.emoji} ${esc(c.title)}</h3>
          <span class="chip">${c.members} joined</span></div>
        <p class="muted small">${esc(c.description)}</p>
        ${c.joined ? `
          <div class="bar" role="progressbar" aria-valuenow="${c.progress}" aria-valuemax="${c.target}" aria-label="Progress">
            <div style="width:${(c.progress / c.target) * 100}%"></div></div>
          <div class="row-between"><span class="small muted">${c.progress}/${c.target} · ends ${c.ends_on}</span>
          <button class="btn btn-ghost btn-sm" data-lb="${c.id}">Leaderboard</button></div>`
        : `<button class="btn btn-primary btn-sm section-gap" data-join="${c.id}">Join challenge</button>`}
      </div>`).join("") || `<p class="muted">No live challenges right now — check back soon!</p>`}`);
  $screen.querySelectorAll("[data-join]").forEach((b) => b.onclick = async () => {
    try { rewardFeedback(await api(`/challenges/${b.dataset.join}/join`, { method: "POST" })); views.challenges(); }
    catch (e) { toast(e.message); }
  });
  $screen.querySelectorAll("[data-lb]").forEach((b) => b.onclick = async () => {
    const { challenge, leaderboard } = await api(`/challenges/${b.dataset.lb}/leaderboard`);
    modal(`<h2>${challenge.emoji} ${esc(challenge.title)}</h2>
      <div style="text-align:left;margin-top:12px">
      ${leaderboard.map((r) => `<div class="lb-row"><span class="rank">${r.rank === 1 ? "🥇" : r.rank === 2 ? "🥈" : r.rank === 3 ? "🥉" : r.rank}</span>
        <span class="grow" style="flex:1">${esc(r.name)}</span><strong>${r.progress}/${challenge.target}</strong></div>`).join("") || `<p class="muted">Be the first on the board!</p>`}
      </div><button class="btn btn-ghost btn-block section-gap" data-close>Close</button>`);
  });
};

/* --- profile & achievements --- */

const FIELD_LABELS = {
  gender: { female: "Female", male: "Male", nonbinary: "Non-binary", prefer_not: "Prefer not to say" },
  occupation: { student: "🎓 Student", professional: "💼 Working professional", other: "🤝 Other" },
  activity_level: { active: "🏃 Pretty active", moderate: "🚶 Somewhat active", inactive: "🛋️ Not very active" },
  health_goal: { fitness: "💪 Get fitter", stress: "🧘 Manage stress", sleep: "😴 Sleep better",
                 eat_better: "🥗 Eat better", general: "✨ General wellness" },
  age_range: { under_18: "Under 18", "18_24": "18–24", "25_34": "25–34", "35_44": "35–44",
               "45_54": "45–54", "55_plus": "55+" },
};

views.profile = async () => {
  showTabs("profile");
  const [p, t, bud, prof] = await Promise.all([
    api("/gamification/profile"), api("/transparency"), api("/buddies"), api("/profile")]);
  const me = prof.profile;
  state.me = me; // gender etc. available to features.js gating
  const chips = [
    ...me.health_goals.map((g) => FIELD_LABELS.health_goal[g]).filter(Boolean),
    FIELD_LABELS.occupation[me.occupation],
    FIELD_LABELS.activity_level[me.activity_level],
    me.age_range ? FIELD_LABELS.age_range[me.age_range] : null,
    me.gender ? FIELD_LABELS.gender[me.gender] : null,
  ].filter(Boolean);
  render(`<h1>Profile 🙂</h1>
    <div class="card me-card">
      <div class="me-head">
        <span class="me-avatar" aria-hidden="true">${esc(me.avatar || "🙂")}</span>
        <div class="grow">
          <h2 style="margin:0">👤 ${esc(me.name)}</h2>
          <p class="muted small" style="margin:2px 0 0">${esc(me.email)}</p>
        </div>
        <button class="btn btn-ghost btn-sm" data-go="edit_profile">✏️ Edit</button>
      </div>
      <div class="me-chips">${chips.map((c) => `<span class="chip">${esc(c)}</span>`).join("")}</div>
      <p class="muted small">🚶 Daily step goal: ${(me.step_goal || 8000).toLocaleString()}</p>
    </div>
    <div class="card level-card">
      <div class="row-between"><strong>Level ${p.level}</strong>
        <span class="muted small">${p.xp} XP · ${p.next_at - p.xp} to next</span></div>
      <div class="bar" role="progressbar" aria-valuenow="${p.xp}" aria-valuemax="${p.next_at}" aria-label="XP progress">
        <div style="width:${p.progress * 100}%"></div></div>
      <div class="badge-strip">🏅 ${p.badges.filter((b) => b.earned).map((b) =>
        `<span title="${esc(b.name)}: ${esc(b.desc)}">${b.emoji}</span>`).join(" ") || `<span class="muted small">badges land here</span>`}
        <span class="muted small">· ${p.badges.filter((b) => b.earned).length}/${p.badges.length}</span></div>
    </div>

    <details class="fold"><summary>🎨 Appearance</summary>
    <div class="card">
      <p class="small muted" style="margin-bottom:10px">Pick the look that's easiest on your eyes.</p>
      <div class="theme-row">
        <button class="theme-opt" data-theme-opt="dark" aria-pressed="${currentTheme() === "dark"}">
          <span class="em">🌙</span>Dark</button>
        <button class="theme-opt" data-theme-opt="light" aria-pressed="${currentTheme() === "light"}">
          <span class="em">☀️</span>Light</button>
      </div>
    </div>
    </details>
    <details class="fold"><summary>🐝 Buddies${bud.buddies.length ? ` · ${bud.buddies.length}` : ""}</summary>
    <div class="card">
      <p class="small">Your buddy code: <strong>${esc(bud.my_code)}</strong> — share it so a friend can link up. You'll see each other's streaks.</p>
      <div class="field section-gap"><label for="bud-code">Friend's code</label><input id="bud-code" placeholder="HB-XXXXXX"></div>
      <button class="btn btn-primary btn-sm" id="bud-link">Link buddy</button>
      ${bud.buddies.map((b) => `<div class="check-row section-gap"><span class="em">🙂</span>
        <div class="grow"><strong>${esc(b.name)}</strong>
        <div class="muted small">💧${b.streaks.water} 🍽️${b.streaks.meal} 😴${b.streaks.sleep} 🙂${b.streaks.mood} day streaks</div></div>
        <button class="btn btn-ghost btn-sm" data-unbuddy="${b.id}" aria-label="Unlink ${esc(b.name)}">✕</button></div>`).join("")}
    </div>

    </details>
    <details class="fold"><summary>🧠 Why am I seeing this?</summary>
    <div class="card">
      <p class="muted small">${esc(t.explanation)}</p>
      <div class="section-gap">
      ${t.state.map((s) => `<div class="affinity-row"><span style="width:110px" class="small"><strong>${s.emoji} ${esc(s.label)}</strong></span>
        <div class="bar"><div style="width:${Math.min(s.affinity * 100, 100)}%;background:${s.color}"></div></div>
        <span class="small muted" style="width:44px;text-align:right">${Math.round(s.affinity * 100)}%</span></div>`).join("")}
      </div>
      <p class="muted small section-gap">Want less of a category? Tap it to tune it down.</p>
      <div class="cat-filter">${t.state.map((s) =>
        `<button class="chipbtn" style="--cat:${s.color}" data-tune="${s.category}" data-mult="${s.pref_multiplier}">
          ${s.emoji} ${s.pref_multiplier < 1 ? "muted" : "normal"}</button>`).join("")}</div>
    </div>
    </details>
    <button class="btn btn-ghost btn-block section-gap" id="signout">Sign out</button>`);

  $screen.querySelectorAll("[data-unbuddy]").forEach((b) => b.onclick = async () => {
    const { message } = await api(`/buddies/${b.dataset.unbuddy}`, { method: "DELETE" });
    toast(message); views.profile();
  });
  document.getElementById("bud-link").onclick = async () => {
    try {
      const { buddy } = await api("/buddies/link", { method: "POST", body: { code: document.getElementById("bud-code").value } });
      toast(`You and ${buddy.name} are buddies now! 🐝`);
      views.profile(); return;
    } catch (e) { toast(e.message); }
  };
  $screen.querySelectorAll("[data-tune]").forEach((b) => b.onclick = async () => {
    const next = parseFloat(b.dataset.mult) < 1 ? 1.0 : 0.4;
    await api("/preferences", { method: "PATCH", body: { category_weights: { [b.dataset.tune]: next } } });
    toast(next < 1 ? "Got it — you'll see less of that." : "Back to normal for that category.");
    views.profile();
  });
  document.getElementById("signout").onclick = logout;
};

/* ---------------- router & boot ---------------- */
function showTabs(active) {
  $tabbar.classList.remove("hidden");
  $tabbar.querySelectorAll(".tab").forEach((t) =>
    t.classList.toggle("active", t.dataset.route === active));
}

function go(route) {
  location.hash = route;
}

async function route() {
  const r = location.hash.replace("#", "") || "welcome";
  if (!state.token && !["welcome", "login", "register"].includes(r)) return go("welcome");
  try { await (views[r] || views.welcome)(); }
  catch (e) { toast(e.message); }
}

document.addEventListener("click", (e) => {
  const nav = e.target.closest("[data-go]");
  if (nav) go(nav.dataset.go);
  const tab = e.target.closest(".tab");
  if (tab) go(tab.dataset.route);
});
window.addEventListener("hashchange", route);

(async function boot() {
  if (!state.token && state.refreshToken) await silentRefresh();
  if (state.token) {
    try {
      const { user } = await api("/me");
      state.user = user;
      if (!location.hash || location.hash === "#welcome") go(user.onboarded ? "home" : "onboarding");
    } catch { /* token invalid → logout already handled */ }
  }
  route();
})();

/* --- Edit Profile --- */
views.edit_profile = async () => {
  showTabs("profile");
  const { profile: me } = await api("/profile");
  const AVATARS = ["🙂", "😎", "🌸", "🐼", "🦊", "🌟", "🧘", "🏃", "🐝", "🌱"];
  const opt = (map, sel) => Object.entries(map).map(([v, l]) =>
    `<option value="${v}" ${v === sel ? "selected" : ""}>${l.replace(/^[^ ]+ /, "")}</option>`).join("");
  render(`<button class="btn btn-ghost btn-sm" data-go="profile">← Profile</button>
    <h1 style="margin-top:10px">✏️ Edit profile</h1>
    <div class="card">
      <div class="field"><label>Avatar</label>
        <div class="cat-filter" id="ep-avatars">${AVATARS.map((a) =>
          `<button class="chipbtn" data-av="${a}" aria-pressed="${a === me.avatar}">${a}</button>`).join("")}</div></div>
      <div class="field"><label for="ep-name">Name</label><input id="ep-name" value="${esc(me.name)}" maxlength="60"></div>
      <div class="field"><label>Email</label><input value="${esc(me.email)}" disabled>
        <span class="muted small">Email changes need re-verification — coming later.</span></div>
      <div class="field"><label for="ep-age">Age range <span class="muted small">(optional)</span></label>
        <select id="ep-age"><option value="">Skip</option>${opt(FIELD_LABELS.age_range, me.age_range)}</select></div>
      <div class="field"><label for="ep-gender">Gender</label>
        <select id="ep-gender">${opt(FIELD_LABELS.gender, me.gender)}</select></div>
      <div class="field"><label>Health goals <span class="muted small">(pick any)</span></label>
        <div class="cat-filter" id="ep-goals">${Object.entries(FIELD_LABELS.health_goal).map(([v, l]) =>
          `<button class="chipbtn" data-goal="${v}" aria-pressed="${me.health_goals.includes(v)}">${l}</button>`).join("")}</div></div>
      <div class="field"><label for="ep-act">Activity level</label>
        <select id="ep-act">${opt(FIELD_LABELS.activity_level, me.activity_level)}</select></div>
      <div class="field"><label for="ep-occ">You are a…</label>
        <select id="ep-occ">${opt(FIELD_LABELS.occupation, me.occupation)}</select></div>
      <div class="field"><label for="ep-steps">Daily step goal</label>
        <input id="ep-steps" type="number" min="1000" max="50000" step="500" value="${me.step_goal}">
        <span class="muted small">Whatever suits YOUR life — 10,000 is a marketing number, not a prescription.</span></div>
      <p class="form-error" id="ep-err" role="alert"></p>
      <button class="btn btn-primary btn-block" id="ep-save">Save changes</button>
    </div>`);
  let avatar = me.avatar;
  document.querySelectorAll("[data-av]").forEach((b) => b.onclick = () => {
    avatar = b.dataset.av;
    document.querySelectorAll("[data-av]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
  });
  const goals = new Set(me.health_goals);
  document.querySelectorAll("[data-goal]").forEach((b) => b.onclick = () => {
    goals.has(b.dataset.goal) ? goals.delete(b.dataset.goal) : goals.add(b.dataset.goal);
    b.setAttribute("aria-pressed", String(goals.has(b.dataset.goal)));
  });
  document.getElementById("ep-save").onclick = async () => {
    const err = document.getElementById("ep-err");
    err.textContent = "";
    if (!goals.size) { err.textContent = "Pick at least one health goal."; return; }
    try {
      const data = await api("/profile", { method: "PATCH", body: {
        name: document.getElementById("ep-name").value,
        avatar,
        age_range: document.getElementById("ep-age").value || null,
        gender: document.getElementById("ep-gender").value,
        health_goals: [...goals],
        activity_level: document.getElementById("ep-act").value,
        occupation: document.getElementById("ep-occ").value,
        step_goal: +document.getElementById("ep-steps").value,
      }});
      toast(data.message);
      go("profile");
    } catch (e) { err.textContent = e.message; }
  };
};
