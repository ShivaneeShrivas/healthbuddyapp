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
  (new_badges || []).forEach((b) => {
    celebrate(b.emoji);
    modal(`<span class="big-em">${b.emoji}</span>
           <h2>Badge earned!</h2><h3>${esc(b.name)}</h3>
           <p class="muted">${esc(b.desc)}</p>
           <button class="btn btn-primary btn-block section-gap" data-close>Nice!</button>`);
  });
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

/* ---------------- notifications (native local + web push) ----------------
   Android's Capacitor WebView does NOT implement the Web Push API
   (window.PushManager is simply absent there), so the browser-style push
   flow below only ever works on the website / installed PWA. Inside the
   actual APK we use @capacitor/local-notifications instead: notifications
   scheduled on-device at fixed daily times, no server round-trip, no VAPID,
   no cron needed. Every call site below (login, onboarding, Profile card)
   goes through pushStatus()/enablePush()/disablePush() and doesn't need to
   know which mechanism is actually running underneath. */

/* Fixed daily nudge times for the native build - one per SLOTS window in
   services/notify.py. Local notifications can't fetch personalized content
   at fire-time (the device may be offline), so each carries a small rotating
   line in the same voice as the server-composed ones, picked once when
   notifications are enabled. IDs are fixed so they can be found & cancelled. */
const LOCAL_SLOTS = [
  { id: 101, hour: 8, minute: 30, title: "☀️ Rise and shine",
    body: "Before the chai, before the scroll — one glass of water first." },
  { id: 102, hour: 13, minute: 30, title: "🪑 Chair check",
    body: "You've been one with your chair since morning. Time to remind your legs they still work." },
  { id: 103, hour: 18, minute: 30, title: "🧘 Stretch o'clock",
    body: "Pause for 60 seconds and stretch. Your spine has been quietly judging you all day." },
  { id: 104, hour: 21, minute: 30, title: "🌙 Wind-down nudge",
    body: "Screens off in 20 minutes? Just as an experiment — see how you feel tomorrow." },
];

function nativeLocalNotifAvailable() {
  return !!window.Capacitor?.isNativePlatform?.() && !!window.__hbPlugin?.("LocalNotifications");
}

function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
}

function webPushSupported() {
  return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
}

function pushSupported() {
  return nativeLocalNotifAvailable() || webPushSupported();
}

async function localNotifStatus() {
  try {
    const LN = window.__hbPlugin("LocalNotifications");
    const perm = await LN.checkPermissions();
    if (perm.display === "denied") return "denied";
    if (perm.display !== "granted") return "undecided";
    const pending = await LN.getPending();
    const ids = new Set(LOCAL_SLOTS.map((s) => s.id));
    const scheduled = pending.notifications.some((n) => ids.has(n.id));
    return scheduled ? "on" : "off";
  } catch (e) {
    console.error("[push] localNotifStatus() failed:", e);
    return "error";
  }
}

async function webPushStatus() {
  if (!webPushSupported()) return "unsupported";
  if (Notification.permission === "denied") return "denied";
  if (Notification.permission === "default") return "undecided";

  // navigator.serviceWorker.ready can hang indefinitely in an SPA that
  // navigates via hash changes rather than full reloads, if this exact
  // page instance loaded before the SW finished activating. Never let
  // the UI hang forever waiting on it - race it against a timeout.
  const timeout = new Promise((resolve) => setTimeout(() => resolve("timeout"), 4000));
  try {
    const result = await Promise.race([
      navigator.serviceWorker.ready.then(async (reg) => {
        const sub = await reg.pushManager.getSubscription();
        return sub ? "on" : "off";
      }),
      timeout,
    ]);
    if (result === "timeout") {
      console.error("[push] navigator.serviceWorker.ready did not resolve within 4s - " +
        "try a full page reload (not just an in-app navigation).");
      return "sw-timeout";
    }
    return result;
  } catch (e) {
    console.error("[push] webPushStatus() failed:", e);
    return "error";
  }
}

async function pushStatus() {
  return nativeLocalNotifAvailable() ? localNotifStatus() : webPushStatus();
}

async function enableLocalNotifs() {
  const LN = window.__hbPlugin("LocalNotifications");
  if (!LN) { toast("Notifications plugin not available on this build."); return false; }
  try {
    const perm = await LN.requestPermissions();
    if (perm.display !== "granted") {
      toast(perm.display === "denied"
        ? "Notifications are blocked. Enable them in your phone's Settings → Apps → HealthBuddy → Notifications."
        : "No worries — you can turn this on later in Profile.");
      return false;
    }
    await LN.schedule({
      notifications: LOCAL_SLOTS.map((s) => ({
        id: s.id, title: s.title, body: s.body,
        schedule: { on: { hour: s.hour, minute: s.minute }, allowWhileIdle: true },
      })),
    });
    toast("Notifications on 🔔 — daily nudges at set times, even with the app closed.");
    return true;
  } catch (e) {
    toast("Couldn't turn on notifications: " + e.message);
    return false;
  }
}

/* Must be called from a direct user click - browsers silently ignore
   permission requests that aren't tied to a user gesture. */
async function enableWebPush() {
  if (!webPushSupported()) { toast("Push notifications aren't supported on this browser."); return false; }

  const permission = await Notification.requestPermission();
  if (permission !== "granted") {
    toast(permission === "denied"
      ? "Notifications are blocked. Enable them in your browser/app settings to get nudges."
      : "No worries — you can turn this on later in Profile.");
    return false;
  }

  try {
    const { public_key } = await api("/push/public-key");
    const reg = await navigator.serviceWorker.ready;
    let sub = await reg.pushManager.getSubscription();
    if (!sub) {
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(public_key),
      });
    }
    await api("/push/subscribe", { method: "POST", body: { subscription: sub.toJSON() } });
    toast("Notifications on 🔔 — you'll get nudges even when the app's closed.");
    return true;
  } catch (e) {
    toast("Couldn't turn on notifications: " + e.message);
    return false;
  }
}

async function enablePush() {
  return nativeLocalNotifAvailable() ? enableLocalNotifs() : enableWebPush();
}

async function disableLocalNotifs() {
  try {
    const LN = window.__hbPlugin("LocalNotifications");
    await LN.cancel({ notifications: LOCAL_SLOTS.map((s) => ({ id: s.id })) });
    toast("Notifications turned off.");
  } catch (e) { toast(e.message); }
}

async function disableWebPush() {
  try {
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();
    if (sub) {
      await api("/push/unsubscribe", { method: "POST", body: { endpoint: sub.endpoint } });
      await sub.unsubscribe();
    }
    toast("Notifications turned off.");
  } catch (e) { toast(e.message); }
}

async function disablePush() {
  return nativeLocalNotifAvailable() ? disableLocalNotifs() : disableWebPush();
}

/* Shown after onboarding AND after every login, on any device, until the
   person has actually decided (not just dismissed once elsewhere) - so a
   new device/browser always gets a real chance to ask, not just day one. */
async function maybePromptForPush() {
  const status = await pushStatus();
  if (status !== "undecided") return;
  modal(`<span class="big-em">🔔</span>
    <h2>Want nudges to actually reach you?</h2>
    <p class="muted">Turn on notifications and HealthBuddy can nudge you even when the
    app's closed — like a text from a friend, not a boring alarm.</p>
    <button class="btn btn-primary btn-block section-gap" id="push-yes">Enable notifications</button>
    <button class="btn btn-ghost btn-block" data-close>Maybe later</button>`);
  document.getElementById("push-yes").onclick = async (e) => {
    await enablePush();
    e.target.closest(".modal-backdrop")?.remove();
  };
}


/* ---------------- views ---------------- */
const views = {};

views.welcome = () => {
  $tabbar.classList.add("hidden");
  render(`
    <div class="welcome">
      <div class="logo">${logoImg(72)}</div>
      <h1>Hey! I'm <span class="brand-name">HealthBuddy</span></h1>
      <p class="muted">Your friendly nudge companion — not a clinical tracker.
      Tiny healthy habits, one fun nudge at a time.</p>
      <button class="btn btn-primary btn-block" data-go="register">Get started</button>
      <button class="btn btn-ghost btn-block" data-go="login">I already have an account</button>
    </div>`);
};

/* Same shape check the server enforces (routes/api.py, via email_validate.py)
   - a fast, no-round-trip pass for obviously malformed input as the person
   types. The server still does the real work: rejecting bad shapes outright,
   plus a live DNS/MX lookup so a syntactically-fine but made-up domain
   (asdf@asdf123.zzz) still gets caught on submit, not just typos. */
const EMAIL_RE_CLIENT = /^[A-Za-z0-9](?:[A-Za-z0-9._%+-]*[A-Za-z0-9])?@(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z]{2,}$/;

function authForm(mode) {
  $tabbar.classList.add("hidden");
  const isReg = mode === "register";
  render(`
    <div style="max-width:400px;margin:40px auto 0">
      <h1>${isReg ? "Create your account" : "Welcome back!"}</h1>
      <p class="muted" style="margin-bottom:24px">${isReg ? "Two fields and a password — that's it." : "Good to see you again."}</p>
      ${isReg ? `<div class="field"><label for="f-name">Name</label><input id="f-name" autocomplete="name"></div>` : ""}
      <div class="field">
        <label for="f-email">Email</label>
        <input id="f-email" type="email" autocomplete="email" inputmode="email">
        <p class="field-hint" id="f-email-hint" role="alert"></p>
      </div>
      <div class="field"><label for="f-pass">Password</label><input id="f-pass" type="password" autocomplete="${isReg ? "new-password" : "current-password"}"></div>
      ${!isReg ? `<button class="btn btn-link" id="f-forgot" type="button" style="margin:-8px 0 0">Forgot password?</button>` : ""}
      <p class="form-error" id="f-err" role="alert"></p>
      <button class="btn btn-primary btn-block section-gap" id="f-submit">${isReg ? "Create account" : "Sign in"}</button>
      <button class="btn btn-ghost btn-block section-gap" data-go="${isReg ? "login" : "register"}">
        ${isReg ? "I already have an account" : "I'm new here"}</button>
    </div>`);

  const $email = document.getElementById("f-email");
  const $emailHint = document.getElementById("f-email-hint");
  function checkEmailShape(showValid) {
    const v = $email.value.trim();
    if (!v) { $email.classList.remove("invalid", "valid"); $emailHint.textContent = ""; return true; }
    const ok = EMAIL_RE_CLIENT.test(v);
    $email.classList.toggle("invalid", !ok);
    $email.classList.toggle("valid", ok && showValid);
    $emailHint.textContent = ok ? "" : "That doesn't look like a real email address.";
    return ok;
  }
  $email.addEventListener("input", () => checkEmailShape(false));
  $email.addEventListener("blur", () => checkEmailShape(true));

  document.getElementById("f-submit").onclick = async () => {
    const err = document.getElementById("f-err");
    err.textContent = "";
    if (!checkEmailShape(true)) { $email.focus(); return; }
    try {
      const body = {
        email: $email.value.trim(),
        password: document.getElementById("f-pass").value,
      };
      if (isReg) body.name = document.getElementById("f-name").value;
      const data = await api("/auth/" + mode, { method: "POST", body });
      if (data.otp_required) {
        toast(data.message);
        loginOtpFlow(data.email, data.dev_otp_code || "");
        return;
      }
      saveSession(data);
      go(data.user.onboarded ? "home" : "onboarding");
      if (data.user.onboarded) await maybePromptForPush();
    } catch (e) { err.textContent = e.message; }
  };
  document.getElementById("f-forgot")?.addEventListener("click", () => forgotPasswordFlow());
}
views.register = () => authForm("register");
views.login = () => authForm("login");

/* --- login step 2: email OTP -------------------------------------------
   Password already checked out server-side; this trades the emailed
   6-digit code for the actual session tokens (/auth/login/verify-otp). */
function loginOtpFlow(email, prefillCode) {
  modal(`<h2>Verify it's you</h2>
    ${prefillCode
      ? `<p class="muted small">No email service is set up on this server yet, so here's your code directly.</p>`
      : `<p class="muted small">Enter the 6-digit code we emailed to ${esc(email)}.</p>`}
    <div class="field"><label for="lo-code">6-digit code</label>
      <input id="lo-code" value="${esc(prefillCode)}" inputmode="numeric" maxlength="6" autocomplete="one-time-code"
        style="letter-spacing:6px;font-size:22px;font-weight:800;text-align:center"></div>
    <p class="form-error" id="lo-err" role="alert"></p>
    <button class="btn btn-primary btn-block section-gap" id="lo-submit">Verify & sign in</button>
    <button class="btn btn-ghost btn-block" id="lo-resend">Resend code</button>
    <button class="btn btn-ghost btn-block" data-close>Cancel</button>`);
  document.getElementById("lo-code")?.focus();
  document.getElementById("lo-submit").onclick = async () => {
    const err = document.getElementById("lo-err");
    err.textContent = "";
    try {
      const data = await rawApi("/auth/login/verify-otp", {
        method: "POST", body: { email, code: document.getElementById("lo-code").value.trim() },
      }).then(({ res, data }) => { if (!res.ok) throw new Error(data.error || "Something went wrong."); return data; });
      document.querySelector(".modal-backdrop")?.remove();
      saveSession(data);
      go(data.user.onboarded ? "home" : "onboarding");
      if (data.user.onboarded) await maybePromptForPush();
    } catch (e) { err.textContent = e.message; }
  };
  document.getElementById("lo-resend").onclick = async () => {
    const err = document.getElementById("lo-err");
    err.textContent = "";
    try {
      const data = await rawApi("/auth/login/resend-otp", {
        method: "POST", body: { email },
      }).then(({ res, data }) => { if (!res.ok) throw new Error(data.error || "Something went wrong."); return data; });
      toast("New code sent.");
      document.getElementById("lo-code").value = data.dev_otp_code || "";
    } catch (e) { err.textContent = e.message; }
  };
}

/* --- forgot / reset password: two small modal steps, chained together ---
   Step 1 collects the email and calls /auth/forgot-password, which emails
   a 6-digit code (services/mailer.py). If no SMTP provider is configured
   yet, the dev response includes the code directly so the flow stays
   testable without an inbox - see routes/api.py. Step 2 collects that
   code + the new password, scoped to the same email. */
function forgotPasswordFlow() {
  modal(`<h2>Reset your password</h2>
    <p class="muted small">Enter your account email and we'll send you a 6-digit code.</p>
    <div class="field"><label for="fp-email">Email</label><input id="fp-email" type="email" autocomplete="email" inputmode="email"></div>
    <p class="form-error" id="fp-err" role="alert"></p>
    <button class="btn btn-primary btn-block section-gap" id="fp-submit">Send reset code</button>
    <button class="btn btn-ghost btn-block" data-close>Cancel</button>`);
  document.getElementById("fp-submit").onclick = async () => {
    const err = document.getElementById("fp-err");
    err.textContent = "";
    const email = document.getElementById("fp-email").value.trim();
    if (!EMAIL_RE_CLIENT.test(email)) { err.textContent = "That doesn't look like a real email address."; return; }
    try {
      const data = await rawApi("/auth/forgot-password", {
        method: "POST", body: { email },
      }).then(({ res, data }) => { if (!res.ok) throw new Error(data.error || "Something went wrong."); return data; });
      document.querySelector(".modal-backdrop")?.remove();
      toast(data.message);
      resetPasswordFlow(email, data.dev_reset_code || "");
    } catch (e) { err.textContent = e.message; }
  };
}

function resetPasswordFlow(email, prefillCode) {
  modal(`<h2>Enter your code</h2>
    ${prefillCode
      ? `<p class="muted small">No email service is set up on this server yet, so here's your code directly.</p>`
      : `<p class="muted small">Check your inbox for a 6-digit code sent to ${esc(email)}.</p>`}
    <div class="field"><label for="rp-code">6-digit code</label>
      <input id="rp-code" value="${esc(prefillCode)}" inputmode="numeric" maxlength="6" autocomplete="one-time-code"
        style="letter-spacing:6px;font-size:22px;font-weight:800;text-align:center"></div>
    <div class="field"><label for="rp-pass">New password</label><input id="rp-pass" type="password" autocomplete="new-password"></div>
    <p class="form-error" id="rp-err" role="alert"></p>
    <button class="btn btn-primary btn-block section-gap" id="rp-submit">Update password</button>
    <button class="btn btn-ghost btn-block" id="rp-resend">Resend code</button>
    <button class="btn btn-ghost btn-block" data-close>Cancel</button>`);
  document.getElementById("rp-submit").onclick = async () => {
    const err = document.getElementById("rp-err");
    err.textContent = "";
    try {
      const data = await rawApi("/auth/reset-password", {
        method: "POST",
        body: { email, code: document.getElementById("rp-code").value.trim(), password: document.getElementById("rp-pass").value },
      }).then(({ res, data }) => { if (!res.ok) throw new Error(data.error || "Something went wrong."); return data; });
      document.querySelector(".modal-backdrop")?.remove();
      toast(data.message || "Password updated. Please sign in again.");
      go("login");
    } catch (e) { err.textContent = e.message; }
  };
  document.getElementById("rp-resend").onclick = async () => {
    const err = document.getElementById("rp-err");
    err.textContent = "";
    try {
      const data = await rawApi("/auth/forgot-password", {
        method: "POST", body: { email },
      }).then(({ res, data }) => { if (!res.ok) throw new Error(data.error || "Something went wrong."); return data; });
      toast("New code sent.");
      document.getElementById("rp-code").value = data.dev_reset_code || "";
    } catch (e) { err.textContent = e.message; }
  };
}

/* --- brand logo (reusable; swap logo.svg to rebrand everywhere at once) --- */
const logoImg = (size, extraClass = "", id = "") =>
  `<img src="/static/logo.svg" width="${size}" height="${size}" alt=""` +
  ` class="brand-logo${extraClass ? " " + extraClass : ""}"${id ? ` id="${id}"` : ""} aria-hidden="true">`;

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
      go("home");
      await maybePromptForPush();
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

/* --- Buddy: a living avatar that reflects today's score & streaks -----
   Mood tier is purely derived from the score that's already on screen (no
   extra state to keep in sync), and a streak of 3+ on ANY habit wraps the
   avatar in a glowing "on fire" aura. */
const BUDDY_CAPTIONS = {
  sleepy: ["Still waking up… log something to give me a boost!", "Feeling a little sluggish today."],
  okay: ["Doing alright — keep it up!", "One habit at a time, we've got this."],
  happy: ["Feeling pretty good today! 🌿", "You're taking good care of me!"],
  great: ["Feeling amazing today! ✨", "Fully charged and glowing! 🌟"],
};
const BUDDY_TAP_MESSAGES = ["👋 Hey there!", "Let's log something healthy!", "Thanks for checking on me!", "Ready when you are 🌱"];

function buddyMood(pct) {
  return pct >= 90 ? "great" : pct >= 60 ? "happy" : pct >= 25 ? "okay" : "sleepy";
}

views.home = async () => {
  showTabs("home");
  Providers.syncDeviceData?.(); // pull real device steps/screen-time when the phone allows it
  const d = await api("/dashboard");
  renderHome(d);
  loadDailyPlan();
  loadActivityCard(d);
  loadScreenTimeCard();
};

function renderHome(d) {
  const pct = d.score.score, C = 2 * Math.PI * 80;
  const hello = new Date().getHours() < 12 ? "Good morning" : new Date().getHours() < 17 ? "Good afternoon" : "Good evening";
  const onFire = Object.values(d.streaks).some((s) => s >= 3);
  const mood = buddyMood(pct);
  const caption = onFire
    ? "On a streak — I'm on fire! 🔥"
    : BUDDY_CAPTIONS[mood][Math.floor(Math.random() * BUDDY_CAPTIONS[mood].length)];
  render(`
    <div class="row-between">
      <div><h1>${hello}, ${esc(d.greeting_name)}!</h1>
      <p class="muted">Level ${d.level} · ${d.xp} XP</p></div>
    </div>

    <div class="buddy-stage">
      <button type="button" class="buddy-aura ${onFire ? "on-fire" : ""}" id="buddy-aura" aria-label="Your HealthBuddy — tap to say hi">
        ${logoImg(104, `buddy-avatar mood-${mood}`, "buddy-avatar-img")}
      </button>
      <p class="buddy-caption" id="buddy-caption">${esc(caption)}</p>
    </div>

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
        return `<div class="check-row" data-habit-row="${h.type}">
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
      ${HABITS.map((h) => `<div class="streak-pill ${d.streaks[h.type] >= 3 ? "hot" : ""}"><span aria-hidden="true">${h.emoji}</span>
        <div class="n">${d.streaks[h.type]}</div><div class="muted small">day${d.streaks[h.type] === 1 ? "" : "s"}</div></div>`).join("")}
    </div>`);

  $screen.querySelectorAll("[data-log]").forEach((btn) => {
    btn.onclick = () => quickLog(HABITS.find((h) => h.type === btn.dataset.log), d);
  });
  $screen.querySelectorAll("[data-unlog]").forEach((btn) => btn.onclick = async () => {
    try {
      const { message } = await api(`/logs/${btn.dataset.unlog}`, { method: "DELETE" });
      toast(message);
      views.home();
    } catch (e) { toast(e.message); }
  });
  document.getElementById("buddy-aura")?.addEventListener("click", () => {
    const img = document.getElementById("buddy-avatar-img");
    if (!img) return;
    img.classList.remove("waving", "dancing"); void img.offsetWidth; // restart animation if clicked repeatedly
    img.classList.add(Math.random() < 0.3 ? "dancing" : "waving");
    toast(BUDDY_TAP_MESSAGES[Math.floor(Math.random() * BUDDY_TAP_MESSAGES.length)]);
  });
  startBuddyIdleDance();
}

/* Buddy spontaneously does a little dance every so often while you're on
   the home screen, so it reads as "alive" rather than a static sticker.
   One interval total (guarded), cleared whenever we leave the home view. */
let _buddyIdleTimer = null;
function startBuddyIdleDance() {
  if (_buddyIdleTimer) clearInterval(_buddyIdleTimer);
  _buddyIdleTimer = setInterval(() => {
    const img = document.getElementById("buddy-avatar-img");
    if (!img || prefersReducedMotion()) return;
    img.classList.remove("dancing"); void img.offsetWidth;
    img.classList.add("dancing");
  }, 14000);
}

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

/* --- micro-interactions: a small, satisfying animation plays inside the
   habit's own row before the dashboard refreshes, per the "Interactive
   Logging" spec (water splash / meal power-up / sleep day-to-night /
   mood emoji burst), plus a confetti burst if the log just hit today's
   goal. Skips entirely under prefers-reduced-motion. --- */
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const prefersReducedMotion = () =>
  window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function fxLayer(row) {
  let layer = row.querySelector(".fx-layer");
  if (!layer) {
    layer = document.createElement("div");
    layer.className = "fx-layer";
    row.appendChild(layer);
  }
  return layer;
}

function spawnFx(layer, cls, html, style) {
  const el = document.createElement("span");
  el.className = cls;
  el.innerHTML = html;
  if (style) Object.assign(el.style, style);
  layer.appendChild(el);
  el.addEventListener("animationend", () => el.remove(), { once: true });
  return el;
}

function celebrate(emoji = "🎉") {
  if (prefersReducedMotion()) return;
  const colors = ["#FF8A5C", "#FF5C8A", "#7ED957", "#4FC3F7", "#FFD166", "#B39DFF"];
  const layer = document.createElement("div");
  layer.className = "celebrate-layer";
  document.body.appendChild(layer);
  for (let i = 0; i < 26; i++) {
    const el = document.createElement("span");
    el.className = "cel-confetti";
    el.style.left = `${Math.random() * 100}%`;
    el.style.background = colors[i % colors.length];
    el.style.animationDuration = `${900 + Math.random() * 700}ms`;
    el.style.animationDelay = `${Math.random() * 250}ms`;
    layer.appendChild(el);
  }
  const burst = document.createElement("span");
  burst.className = "cel-burst";
  burst.textContent = emoji;
  layer.appendChild(burst);
  setTimeout(() => layer.remove(), 1700);
}

function confettiBurst(layer) {
  const colors = ["#FF8A5C", "#FF5C8A", "#7ED957", "#4FC3F7", "#FFD166"];
  for (let i = 0; i < 14; i++) {
    setTimeout(() => spawnFx(layer, "fx-confetti", "", {
      left: `${Math.random() * 100}%`,
      background: colors[i % colors.length],
    }), i * 18);
  }
}

async function playLogAnimation(h, value, goalHit) {
  const row = $screen.querySelector(`[data-habit-row="${h.type}"]`);
  if (!row || prefersReducedMotion()) return;
  row.classList.add(`anim-${h.type}`);
  const layer = fxLayer(row);

  if (h.type === "water") {
    spawnFx(layer, "fx-droplet", "💧");
    setTimeout(() => spawnFx(layer, "fx-ripple", ""), 380);
  } else if (h.type === "meal") {
    spawnFx(layer, "fx-plate", "🍽️", { left: "44%", top: "38%" });
    for (let i = 0; i < 5; i++) {
      setTimeout(() => spawnFx(layer, "fx-spark", i % 2 ? "💚" : "✨", {
        left: `${28 + Math.random() * 44}%`, top: "55%",
      }), 200 + i * 90);
    }
  } else if (h.type === "sleep") {
    spawnFx(layer, "fx-moon", "🌙");
    for (let i = 0; i < 3; i++) {
      setTimeout(() => spawnFx(layer, "fx-zzz", "z".repeat(i + 1), {
        left: `${18 + i * 16}%`, fontSize: `${12 + i * 3}px`,
      }), 150 + i * 160);
    }
  } else if (h.type === "mood") {
    const moodEmoji = ["😞", "😕", "😐", "🙂", "😄"][Math.max(0, Math.min(4, Math.round(value || 4) - 1))];
    for (let i = 0; i < 8; i++) {
      setTimeout(() => spawnFx(layer, "fx-emoji-burst", moodEmoji, {
        left: `${8 + Math.random() * 82}%`, top: `${15 + Math.random() * 30}%`,
      }), i * 45);
    }
    const buddyImg = document.getElementById("buddy-avatar-img");
    if (buddyImg) {
      buddyImg.classList.add("mood-copy");
      setTimeout(() => buddyImg.classList.remove("mood-copy"), 900);
    }
  }
  if (goalHit) confettiBurst(layer);
  await wait(goalHit ? 950 : 650);
}

async function quickLog(h, prevDash) {
  let value = h.value;
  if (h.prompt) {
    const raw = prompt(h.type === "sleep" ? "How many hours did you sleep?" : "How's your mood, 1 (rough) to 5 (great)?", h.value);
    if (raw === null) return;
    value = parseFloat(raw);
    if (Number.isNaN(value)) return toast("That needs to be a number.");
  }
  try {
    const data = await api("/logs", { method: "POST", body: { type: h.type, value } });
    const prevToday = (prevDash && prevDash.score.today[h.type]) || { count: 0, total: 0 };
    let goalHit = false;
    if (h.type === "water") {
      const prevTotal = prevToday.total || 0;
      goalHit = prevTotal < h.target && prevTotal + value >= h.target;
    } else if (h.type === "meal") {
      goalHit = prevToday.count < h.target && prevToday.count + 1 >= h.target;
    }
    const buddyImg = document.getElementById("buddy-avatar-img");
    if (buddyImg) {
      buddyImg.classList.remove("dancing"); void buddyImg.offsetWidth;
      buddyImg.classList.add("dancing");
    }
    await playLogAnimation(h, value, goalHit);
    if (goalHit) celebrate(h.emoji);
    if (data.streak && data.streak % 7 === 0) celebrate("🔥");
    rewardFeedback(data);
    if (data.streak >= 2) toast(`${h.emoji} ${data.streak}-day ${h.label.toLowerCase()} streak!`);
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
    <details class="fold"><summary>🔔 Notifications</summary>
    <div class="card" id="push-card"><p class="muted small">Checking status…</p></div>
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
  renderPushCard();
};

async function renderPushCard() {
  const card = document.getElementById("push-card");
  if (!card) return;
  let status;
  try {
    status = await pushStatus();
  } catch (e) {
    console.error("[push] renderPushCard failed:", e);
    status = "error";
  }
  const copy = {
    unsupported: ["😕", "Not supported on this browser.", null],
    denied: ["🔕", "Blocked — enable notifications for HealthBuddy in your device/browser settings.", null],
    undecided: ["🔔", "Off — turn these on so nudges reach you even when the app's closed.", "on"],
    off: ["🔔", "Permission granted, but not active on this device yet.", "on"],
    on: ["✅", "On — you'll get nudges even when the app's closed.", "off"],
    "sw-timeout": ["⚠️", "Taking too long to check — do a full page reload (Cmd/Ctrl+Shift+R), not just switching tabs.", "retry"],
    error: ["⚠️", "Couldn't check notification status. Open the browser console for details.", "retry"],
  }[status] || ["⚠️", "Unknown status.", "retry"];
  const [emoji, text, action] = copy;
  card.innerHTML = `
    <div class="check-row">
      <span class="em" aria-hidden="true">${emoji}</span>
      <div class="grow"><span class="small">${text}</span></div>
      ${action === "on" ? `<button class="btn btn-primary btn-sm" id="push-toggle">Enable</button>` : ""}
      ${action === "off" ? `<button class="btn btn-ghost btn-sm" id="push-toggle">Turn off</button>` : ""}
      ${action === "retry" ? `<button class="btn btn-ghost btn-sm" id="push-retry">Retry</button>` : ""}
    </div>
    ${status === "on" ? `<button class="btn btn-ghost btn-sm btn-block section-gap" id="push-test-btn">Send me a test notification</button>` : ""}`;
  document.getElementById("push-toggle")?.addEventListener("click", async () => {
    if (action === "on") await enablePush(); else await disablePush();
    renderPushCard();
  });
  document.getElementById("push-retry")?.addEventListener("click", () => renderPushCard());
  document.getElementById("push-test-btn")?.addEventListener("click", async () => {
    try {
      if (nativeLocalNotifAvailable()) {
        const LN = window.__hbPlugin("LocalNotifications");
        await LN.schedule({ notifications: [{
          id: 199, title: "✅ HealthBuddy", body: "Test notification — if you can see this, it's working!",
          schedule: { at: new Date(Date.now() + 5000) },
        }] });
        toast("Test scheduled — check your notification tray in ~5 seconds!");
      } else {
        await api("/push/test", { method: "POST" });
        toast("Test sent — check your notification tray!");
      }
    } catch (e) { toast(e.message); }
  });
}

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
