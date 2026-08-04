/* HealthBuddy features.js — Period Care, Mind Games, Weekly Wrapped, notifications.
   Loads after app.js and extends its views/router (same global lexical scope). */
"use strict";

/* =============== Period Care =============== */

views.pc_offer = () => {
  $tabbar.classList.add("hidden");
  render(`
    <div style="max-width:400px;margin:40px auto 0;text-align:center">
      <div style="font-size:56px" aria-hidden="true">🌸</div>
      <h1>Period Care?</h1>
      <p class="muted">HealthBuddy can track your cycle, predict your next period,
      and send gentle reminders — hydration, iron-rich foods, rest, and yes,
      officially-sanctioned chocolate. Private by default: your data stays in your
      account and you can delete it anytime.</p>
      <button class="btn btn-primary btn-block section-gap" data-go="pc_setup">Yes, enable Period Care</button>
      <button class="btn btn-ghost btn-block" id="pc-skip">Maybe later</button>
    </div>`);
  document.getElementById("pc-skip").onclick = () => go("home");
};

views.pc_setup = () => {
  $tabbar.classList.add("hidden");
  const today = new Date().toISOString().slice(0, 10);
  render(`
    <div style="max-width:400px;margin:24px auto 0">
      <h1>Set up Period Care 🌸</h1>
      <p class="muted small">Rough answers are fine — predictions improve every cycle.</p>
      <div class="field"><label for="pc-date">When did your last period start?</label>
        <input id="pc-date" type="date" max="${today}"></div>
      <div class="field"><label for="pc-cycle">Average cycle length (days)</label>
        <input id="pc-cycle" type="number" value="28" min="15" max="60"></div>
      <div class="field"><label for="pc-len">Average period length (days)</label>
        <input id="pc-len" type="number" value="5" min="1" max="12"></div>
      <label class="check-row" style="cursor:pointer"><input type="checkbox" id="pc-remind" checked>
        <span class="grow">Send me supportive reminders</span></label>
      <label class="check-row section-gap" style="cursor:pointer"><input type="checkbox" id="pc-gcal">
        <span class="grow">Export predicted dates to Google Calendar <span class="muted small">(optional)</span></span></label>
      <p class="form-error" id="pc-err" role="alert"></p>
      <button class="btn btn-primary btn-block" id="pc-save">Save</button>
      <button class="btn btn-ghost btn-block section-gap" data-go="home">Cancel</button>
    </div>`);
  document.getElementById("pc-save").onclick = async () => {
    const err = document.getElementById("pc-err");
    err.textContent = "";
    try {
      const data = await api("/cycle/setup", { method: "POST", body: {
        last_period_start: document.getElementById("pc-date").value,
        avg_cycle_len: +document.getElementById("pc-cycle").value,
        avg_period_len: +document.getElementById("pc-len").value,
        remind: document.getElementById("pc-remind").checked,
        gcal_export: document.getElementById("pc-gcal").checked,
      }});
      rewardFeedback({ xp_earned: 0, new_badges: data.new_badges });
      toast("Period Care is on 🌸");
      go("home");
    } catch (e) { err.textContent = e.message; }
  };
};

function cycleCardHTML(st) {
  const m = st.phase_meta;
  return `
    <div class="card pc-card" style="--pc:${m.color}">
      <div class="row-between">
        <h3>${m.emoji} ${esc(m.label)} phase</h3>
        <span class="chip">day ${st.cycle_day}</span>
      </div>
      <div class="pc-grid">
        <div><div class="n">${st.days_left}</div><div class="muted small">day${st.days_left === 1 ? "" : "s"} to next period</div></div>
        <div><div class="n">${new Date(st.next_period + "T00:00").toLocaleDateString(undefined, { day: "numeric", month: "short" })}</div>
          <div class="muted small">predicted start</div></div>
      </div>
      <p class="muted small">${esc(st.prediction_note)}</p>
      ${st.checkin_due ? `<div class="pc-checkin">
        <strong>Did your period start today?</strong>
        <div class="nudge-actions">
          <button class="btn btn-primary btn-sm" data-pc-checkin="yes">Yes</button>
          <button class="btn btn-ghost btn-sm" data-pc-checkin="no">Not yet</button>
        </div></div>` : ""}
    </div>`;
}

function wireCycleCheckin() {
  $screen.querySelectorAll("[data-pc-checkin]").forEach((b) => b.onclick = async () => {
    try {
      const data = await api("/cycle/checkin", { method: "POST",
        body: { started: b.dataset.pcCheckin === "yes" } });
      toast(data.message);
      if (data.xp_earned) rewardFeedback(data);
      views.home();
    } catch (e) { toast(e.message); }
  });
}

/* =============== Notification bell =============== */

async function loadBell() {
  try {
    const { notifications } = await api("/notifications");
    const bell = document.getElementById("bell");
    if (!bell) return;
    bell.dataset.n = notifications.length;
    bell.onclick = () => modal(`
      <h2>For you right now 🔔</h2>
      <div style="text-align:left;margin-top:12px">
        ${notifications.map((n) => `
          <div class="notif-row" data-kind="${n.kind}">
            <span class="em" aria-hidden="true">${n.emoji}</span>
            <div><strong>${esc(n.title)}</strong>
            <p class="muted small">${esc(n.body)}</p>
            ${n.kind === "cycle_checkin" ? `<div class="nudge-actions">
              <button class="btn btn-primary btn-sm" data-mchk="yes">Yes</button>
              <button class="btn btn-ghost btn-sm" data-mchk="no">Not yet</button></div>` : ""}
            </div>
          </div>`).join("") || `<p class="muted">All quiet — you're on top of things. ✨</p>`}
      </div>
      <p class="muted small section-gap">On the phone app these arrive as push notifications, quiet hours respected.</p>
      <button class="btn btn-ghost btn-block section-gap" data-close>Close</button>`);
    setTimeout(() => {
      document.querySelectorAll("[data-mchk]").forEach((b) => b.onclick = async () => {
        const data = await api("/cycle/checkin", { method: "POST", body: { started: b.dataset.mchk === "yes" } });
        toast(data.message);
        document.querySelector(".modal-backdrop")?.remove();
        views.home();
      });
    }, 0);
  } catch (_) { /* bell is decorative if it fails */ }
}

/* =============== Home extensions (cycle card, bell, shortcuts) =============== */

const _origHome = views.home;
views.home = async () => {
  await _origHome();
  const h1 = $screen.querySelector("h1");
  if (h1 && !document.getElementById("bell"))
    h1.insertAdjacentHTML("beforebegin",
      `<button id="bell" class="bell" aria-label="Notifications">🔔</button>`);
  loadBell();

  const slot = document.getElementById("daily-nudge-slot") || $screen.querySelector(".nudge-card");
  const anchor = slot || $screen.querySelector(".checklist");
  try {
    const { status } = await api("/cycle/status");
    anchor?.insertAdjacentHTML("beforebegin", cycleCardHTML(status));
    wireCycleCheckin();
  } catch (_) { /* Period Care not enabled — nothing to show */ }

};

/* =============== Mind Games =============== */

const GAME_META = {
  memory:   { emoji: "🃏", label: "Memory Match",   desc: "Flip cards, find pairs." },
  pattern:  { emoji: "🎨", label: "Pattern Recall", desc: "Repeat the growing sequence." },
  reaction: { emoji: "⚡", label: "Reaction Time",  desc: "Tap the instant it turns green." },
  logic:    { emoji: "🧩", label: "Logic Sprint",   desc: "30 seconds of quick true/false." },
};
let gameChoice = { game: "memory", difficulty: "easy" };

views.play = async () => {
  showTabs("play");
  const s = await api("/games");
  render(`<h1>Mind Games 🎮</h1>
    <div class="card daily-banner">
      <div class="row-between"><strong>🌟 Daily challenge: ${GAME_META[s.daily_game].label}</strong>
      <span class="chip">2× XP</span></div>
      <p class="muted small">Everyone gets the same challenge. Play streak: ${s.play_streak} day${s.play_streak === 1 ? "" : "s"} 🔥</p>
      <button class="btn btn-primary btn-sm" data-play="${s.daily_game}" data-daily="1">Play now</button>
    </div>
    <div class="row-between section-gap"><h2>Brain score</h2><span class="chip">${s.brain_score}/100</span></div>
    <div class="bar"><div style="width:${s.brain_score}%"></div></div>
    <p class="muted small">Grows with regular play, variety, and beating your bests.</p>
    <h2 class="section-gap">Games</h2>
    <div class="games-grid">
      ${s.games.map((gm) => `
        <button class="card game-card" data-play="${gm.game}">
          <span style="font-size:32px" aria-hidden="true">${gm.emoji}</span>
          <strong>${esc(gm.label)}</strong>
          <span class="muted small">${GAME_META[gm.game].desc}</span>
          <span class="muted small">${gm.plays ? `best ${Math.round(gm.best)} · ${gm.plays} plays` : "not played yet"}
          ${gm.trend_pct !== null ? ` · <span style="color:var(--ok)">${gm.trend_pct >= 0 ? "▲" : "▼"} ${Math.abs(gm.trend_pct)}%</span>` : ""}</span>
        </button>`).join("")}
    </div>
    <p class="muted small section-gap">Trends compare your recent games with your first ones — watch memory, focus, reaction, and logic sharpen over time.</p>`);
  $screen.querySelectorAll("[data-play]").forEach((b) => b.onclick = () => {
    gameChoice = { game: b.dataset.play, difficulty: "easy", daily: !!b.dataset.daily };
    go("game");
  });
};

views.game = () => {
  showTabs("play");
  const { game } = gameChoice;
  const m = GAME_META[game];
  render(`<button class="btn btn-ghost btn-sm" data-go="play">← Games</button>
    <h1 style="margin-top:10px">${m.emoji} ${m.label}</h1>
    <div class="cat-filter" role="group" aria-label="Difficulty">
      ${["easy", "medium", "hard"].map((d) => `<button class="chipbtn" data-diff="${d}"
        aria-pressed="${gameChoice.difficulty === d}">${d}</button>`).join("")}
    </div>
    <div id="stage" class="card game-stage"></div>`);
  $screen.querySelectorAll("[data-diff]").forEach((b) => b.onclick = () => {
    gameChoice.difficulty = b.dataset.diff; views.game();
  });
  ({ memory: playMemory, pattern: playPattern, reaction: playReaction, logic: playLogic })[game]();
};

async function submitScore(score, extra = "") {
  try {
    const data = await api("/games/score", { method: "POST",
      body: { ...gameChoice, score: Math.round(score), is_daily: gameChoice.daily } });
    rewardFeedback(data);
    toast(`Score ${Math.round(score)}${extra} · +${data.xp_earned} XP`);
  } catch (e) { toast(e.message); }
}

function stage() { return document.getElementById("stage"); }

/* --- Memory Match --- */
function playMemory() {
  const pairs = { easy: 6, medium: 8, hard: 10 }[gameChoice.difficulty];
  const emo = ["🍎", "🌊", "🌙", "⚡", "🌸", "🎈", "🍀", "🔥", "🎧", "🚲"].slice(0, pairs);
  const deck = [...emo, ...emo].sort(() => Math.random() - 0.5);
  let open = [], found = 0, moves = 0, t0 = Date.now();
  stage().innerHTML = `<p class="muted small">Find all ${pairs} pairs. Fewer moves, better score.</p>
    <div class="mem-grid" style="grid-template-columns:repeat(4,1fr)">
      ${deck.map((e, i) => `<button class="mem-card" data-i="${i}" aria-label="card"><span>${e}</span></button>`).join("")}
    </div><p class="small muted" id="mem-hud">moves: 0</p>`;
  stage().querySelectorAll(".mem-card").forEach((c) => c.onclick = () => {
    if (c.classList.contains("up") || open.length === 2) return;
    c.classList.add("up");
    open.push(c);
    if (open.length === 2) {
      moves++;
      document.getElementById("mem-hud").textContent = "moves: " + moves;
      const [a, b] = open;
      if (deck[a.dataset.i] === deck[b.dataset.i]) {
        a.classList.add("won"); b.classList.add("won");
        open = [];
        if (++found === pairs) {
          const secs = (Date.now() - t0) / 1000;
          const score = Math.max(10, pairs * 100 - moves * 8 - secs * 2);
          stage().insertAdjacentHTML("beforeend", `<p><strong>🎉 Done in ${moves} moves, ${Math.round(secs)}s</strong></p>`);
          submitScore(score);
        }
      } else setTimeout(() => { a.classList.remove("up"); b.classList.remove("up"); open = []; }, 650);
    }
  });
}

/* --- Pattern Recall (Simon) --- */
function playPattern() {
  const target = { easy: 5, medium: 7, hard: 9 }[gameChoice.difficulty];
  const speed = { easy: 650, medium: 500, hard: 380 }[gameChoice.difficulty];
  const colors = ["#FF8A5C", "#4FC3F7", "#7ED957", "#B39DFF"];
  let seq = [], input = 0, showing = false;
  stage().innerHTML = `<p class="muted small">Watch the pads light up, then repeat. Reach round ${target}!</p>
    <div class="simon">${colors.map((c, i) => `<button class="pad" data-p="${i}" style="--pad:${c}" aria-label="pad ${i + 1}"></button>`).join("")}</div>
    <p class="small muted" id="sim-hud">round 0</p>
    <button class="btn btn-primary btn-sm" id="sim-start">Start</button>`;
  const flash = (i) => new Promise((r) => {
    const p = stage().querySelector(`[data-p="${i}"]`);
    p.classList.add("lit"); setTimeout(() => { p.classList.remove("lit"); setTimeout(r, 120); }, speed);
  });
  const show = async () => {
    showing = true;
    for (const i of seq) await flash(i);
    showing = false; input = 0;
  };
  const round = () => {
    seq.push(Math.floor(Math.random() * 4));
    document.getElementById("sim-hud").textContent = "round " + seq.length;
    show();
  };
  document.getElementById("sim-start").onclick = (e) => { e.target.remove(); seq = []; round(); };
  stage().querySelectorAll(".pad").forEach((p) => p.onclick = async () => {
    if (showing || !seq.length) return;
    flash(+p.dataset.p);
    if (+p.dataset.p !== seq[input++]) {
      const score = (seq.length - 1) * 100;
      stage().insertAdjacentHTML("beforeend", `<p><strong>Round ${seq.length} tripped you up — ${seq.length - 1} clean rounds.</strong></p>`);
      return submitScore(score);
    }
    if (input === seq.length) {
      if (seq.length >= target) {
        stage().insertAdjacentHTML("beforeend", `<p><strong>🎉 Perfect run to round ${target}!</strong></p>`);
        return submitScore(target * 100 + 50);
      }
      setTimeout(round, 500);
    }
  });
}

/* --- Reaction Time --- */
function playReaction() {
  const trials = { easy: 3, medium: 5, hard: 7 }[gameChoice.difficulty];
  let times = [], t0 = 0, ready = false, timer;
  stage().innerHTML = `<p class="muted small">${trials} rounds. Tap the instant the box turns green. Early taps restart the round!</p>
    <button id="rx" class="rx wait">Tap to begin</button><p class="small muted" id="rx-hud"></p>`;
  const box = document.getElementById("rx"), hud = document.getElementById("rx-hud");
  const arm = () => {
    box.className = "rx wait"; box.textContent = "Wait for green…"; ready = false;
    timer = setTimeout(() => { box.className = "rx gogo"; box.textContent = "TAP!"; t0 = performance.now(); ready = true; },
      800 + Math.random() * 1700);
  };
  let started = false;
  box.onclick = () => {
    if (!started) { started = true; return arm(); }
    if (!ready) { clearTimeout(timer); hud.textContent = "Too soon! 😅 Round restarted."; return arm(); }
    const ms = performance.now() - t0;
    times.push(ms);
    hud.textContent = `${Math.round(ms)} ms · ${times.length}/${trials}`;
    if (times.length === trials) {
      const avg = times.reduce((a, b) => a + b) / times.length;
      box.className = "rx wait"; box.textContent = `Avg ${Math.round(avg)} ms`;
      box.onclick = null;
      submitScore(Math.max(0, 1000 - avg), ` (avg ${Math.round(avg)} ms)`);
    } else arm();
  };
}

/* --- Logic Sprint --- */
function playLogic() {
  const secsTotal = 30;
  const hardness = { easy: 10, medium: 25, hard: 60 }[gameChoice.difficulty];
  let right = 0, wrong = 0, endAt = 0, tick;
  const q = () => {
    const a = 1 + Math.floor(Math.random() * hardness), b = 1 + Math.floor(Math.random() * hardness);
    const op = ["+", "-", "×"][Math.floor(Math.random() * 3)];
    const real = op === "+" ? a + b : op === "-" ? a - b : a * b;
    const lie = real + (Math.random() < 0.5 ? -1 : 1) * (1 + Math.floor(Math.random() * 3));
    const shown = Math.random() < 0.5 ? real : lie;
    return { text: `${a} ${op} ${b} = ${shown}`, truth: shown === real };
  };
  let cur = q();
  stage().innerHTML = `<p class="muted small">Is the equation true or false? ${secsTotal} seconds on the clock.</p>
    <h2 id="lq" style="text-align:center;font-size:34px;margin:18px 0">${cur.text}</h2>
    <div class="nudge-actions" style="justify-content:center">
      <button class="btn btn-primary" data-ans="1">True ✓</button>
      <button class="btn btn-ghost" data-ans="0">False ✗</button></div>
    <p class="small muted" id="lg-hud" style="text-align:center">30s · 0 right</p>`;
  endAt = Date.now() + secsTotal * 1000;
  const hud = document.getElementById("lg-hud");
  tick = setInterval(() => {
    const left = Math.max(0, Math.ceil((endAt - Date.now()) / 1000));
    hud.textContent = `${left}s · ${right} right · ${wrong} wrong`;
    if (left <= 0) {
      clearInterval(tick);
      stage().querySelectorAll("[data-ans]").forEach((b) => (b.disabled = true));
      stage().insertAdjacentHTML("beforeend", `<p style="text-align:center"><strong>⏱️ ${right} right, ${wrong} wrong</strong></p>`);
      submitScore(Math.max(0, right * 20 - wrong * 5));
    }
  }, 250);
  stage().querySelectorAll("[data-ans]").forEach((b) => b.onclick = () => {
    if (Date.now() > endAt) return;
    (!!+b.dataset.ans === cur.truth) ? right++ : wrong++;
    cur = q();
    document.getElementById("lq").textContent = cur.text;
  });
}

/* =============== Weekly Wrapped =============== */

views.wrapped = async () => {
  showTabs("home");
  const { wrapped: w, new_badges, xp_earned } = await api("/wrapped");
  if (xp_earned) rewardFeedback({ xp_earned, new_badges });
  const range = `${new Date(w.range.start + "T00:00").toLocaleDateString(undefined, { day: "numeric", month: "short" })} – ${new Date(w.range.end + "T00:00").toLocaleDateString(undefined, { day: "numeric", month: "short" })}`;
  const slides = [
    { bg: "linear-gradient(160deg,#FF8A5C,#FF5C8A)", emoji: "🎁", kicker: "YOUR WEEK, WRAPPED",
      big: w.health_score, unit: "/100", label: "overall health score", foot: range },
    { bg: "linear-gradient(160deg,#B39DFF,#4FC3F7)", emoji: "🧠", kicker: "BRAIN SCORE",
      big: w.brain_score, unit: "/100", label: `${w.games.plays} mind-game sessions`,
      foot: w.games.trends.map((t) => `${t.emoji} ${t.label} ${t.trend_pct >= 0 ? "▲" : "▼"}${Math.abs(t.trend_pct)}%`).join("  ") || "play more to unlock trends" },
    { bg: "linear-gradient(160deg,#4FC3F7,#7ED957)", emoji: "💧", kicker: "HYDRATION",
      big: w.hydration.glasses, unit: " glasses", label: `across ${w.hydration.days} day${w.hydration.days === 1 ? "" : "s"}`,
      foot: w.hydration.glasses >= 40 ? "certified hydration icon" : "your kidneys remain optimistic" },
    { bg: "linear-gradient(160deg,#2A2138,#B39DFF)", emoji: "😴", kicker: "SLEEP",
      big: w.sleep.avg_hours || "—", unit: w.sleep.avg_hours ? " h avg" : "", label: `${w.sleep.nights} night${w.sleep.nights === 1 ? "" : "s"} logged`,
      foot: w.movement_note },
    { bg: "linear-gradient(160deg,#FFD166,#FF8A5C)", emoji: "✨", kicker: "NUDGES",
      big: w.nudges.acted, unit: " acted on", label: w.nudges.top_category ? `top category: ${w.nudges.top_category.emoji} ${w.nudges.top_category.label}` : "your bandit is warming up",
      foot: `+${w.xp} XP earned this week` },
    { bg: "linear-gradient(160deg,#F7A8C4,#B39DFF)", emoji: "🏅", kicker: "ACHIEVEMENTS",
      big: w.badges.length, unit: w.badges.length === 1 ? " badge" : " badges", label: w.badges.map((b) => b.emoji + " " + b.name).join(" · ") || "the badge wall awaits",
      foot: `avg mood ${w.mood.avg || "—"}/5 across ${w.mood.checkins} check-ins` },
    { bg: "linear-gradient(160deg,#7ED957,#4FC3F7)", emoji: "🧭", kicker: "AI INSIGHTS",
      list: w.insights, label: "", foot: "" },
    { bg: "linear-gradient(160deg,#FF5C8A,#B39DFF)", emoji: "🎯", kicker: "NEXT WEEK'S GOALS",
      list: w.goals.map((g) => `${g.emoji} ${g.text}`), foot: "see you next Sunday 💜" },
  ];
  let i = 0;
  render(`<button class="btn btn-ghost btn-sm" data-go="home">← Home</button>
    <div class="wrap-stage"><div id="wrap-card" class="wrap-card"></div>
      <div class="wrap-nav">
        <button class="btn btn-ghost btn-sm" id="w-prev" aria-label="Previous">←</button>
        <div id="w-dots" class="wrap-dots"></div>
        <button class="btn btn-ghost btn-sm" id="w-next" aria-label="Next">→</button>
      </div>
      <button class="btn btn-primary btn-block section-gap" id="w-share">Share this card 📤</button>
      <p class="muted small" style="text-align:center">Downloads a story-sized image for Instagram / WhatsApp.</p>
    </div>`);
  const draw = () => {
    const s = slides[i];
    document.getElementById("wrap-card").style.background = s.bg;
    document.getElementById("wrap-card").innerHTML = `
      <span class="wk">${s.kicker}</span>
      <span class="we" aria-hidden="true">${s.emoji}</span>
      ${s.list ? `<ul class="wl">${s.list.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`
        : `<div class="wb">${esc(String(s.big))}<span class="wu">${esc(s.unit || "")}</span></div>
           <div class="wlab">${esc(s.label)}</div>`}
      <div class="wf">${esc(s.foot || "")}</div>
      <div class="wbrand">🌱 HealthBuddy</div>`;
    document.getElementById("w-dots").innerHTML =
      slides.map((_, d) => `<span class="dot ${d === i ? "on" : ""}"></span>`).join("");
  };
  document.getElementById("w-prev").onclick = () => { i = (i - 1 + slides.length) % slides.length; draw(); };
  document.getElementById("w-next").onclick = () => { i = (i + 1) % slides.length; draw(); };
  document.getElementById("w-share").onclick = () => shareSlide(slides[i]);
  draw();
};

function shareSlide(s) {
  const cv = document.createElement("canvas");
  cv.width = 540; cv.height = 960;
  const x = cv.getContext("2d");
  const g = x.createLinearGradient(0, 0, 540, 960);
  const cols = (s.bg.match(/#[0-9A-Fa-f]{6}/g)) || ["#FF8A5C", "#FF5C8A"];
  g.addColorStop(0, cols[0]); g.addColorStop(1, cols[1] || cols[0]);
  x.fillStyle = g; x.fillRect(0, 0, 540, 960);
  x.fillStyle = "rgba(255,255,255,.92)"; x.textAlign = "center";
  x.font = "700 26px sans-serif"; x.fillText(s.kicker, 270, 150);
  x.font = "120px serif"; x.fillText(s.emoji, 270, 330);
  if (s.list) {
    x.font = "600 26px sans-serif";
    s.list.slice(0, 5).forEach((t, n) => x.fillText(t.length > 38 ? t.slice(0, 37) + "…" : t, 270, 460 + n * 60));
  } else {
    x.font = "800 130px sans-serif"; x.fillText(String(s.big), 270, 520);
    x.font = "600 34px sans-serif"; x.fillText((s.unit || "").trim(), 270, 575);
    x.font = "26px sans-serif"; x.fillText(s.label.length > 40 ? s.label.slice(0, 39) + "…" : s.label, 270, 650);
  }
  x.font = "22px sans-serif"; x.fillText((s.foot || "").slice(0, 44), 270, 800);
  x.font = "700 28px sans-serif"; x.fillText("🌱 HealthBuddy", 270, 900);
  const a = document.createElement("a");
  a.download = "healthbuddy-wrapped.png";
  a.href = cv.toDataURL("image/png");
  a.click();
  toast("Card saved — go make the group chat jealous 📤");
}

/* =============== Profile extension: Period Care settings =============== */

const _origProfile = views.profile;
views.profile = async () => {
  await _origProfile();
  /* Period Care visibility rules (opt-in always; never assume):
     - already enabled (any gender)  → show manage block (data is theirs)
     - gender female                 → show the optional enable offer
     - gender male                   → no Period Care UI here at all
     - non-binary / prefer-not      → available inside Data & Permissions
       ("Optional features"), not pushed on the main profile.           */
  let gender = state.me?.gender;
  if (!gender) {
    try { gender = (state.me = (await api("/profile")).profile).gender; } catch (_) {}
  }
  let enabled = false, status = null;
  try { status = (await api("/cycle/status")).status; enabled = true; } catch (_) {}

  let block = "";
  if (enabled) {
    block = `<details class="fold" open><summary>🌸 Period Care · ${status.phase_meta.label}</summary><div class="card" id="pc-block">
      <p class="small">${status.phase_meta.emoji} <strong>${esc(status.phase_meta.label)}</strong> · cycle day ${status.cycle_day} · next period in ${status.days_left} day${status.days_left === 1 ? "" : "s"}.</p>
      <p class="muted small">${esc(status.prediction_note)} Avg cycle: ${status.avg_cycle_len} days.</p>
      <div class="nudge-actions">
        <button class="btn btn-ghost btn-sm" data-go="pc_setup">Edit settings</button>
        <button class="btn btn-ghost btn-sm" id="pc-export">Export to Calendar</button>
        <button class="btn btn-ghost btn-sm" id="pc-del">Delete all data</button>
      </div></div></details>`;
  } else if (gender === "female") {
    block = `<details class="fold"><summary>🌸 Period Care</summary><div class="card" id="pc-block">
      <p class="muted small">Cycle tracking with gentle, supportive reminders. Private by default — enable it any time, delete it any time.</p>
      <button class="btn btn-primary btn-sm" data-go="pc_setup">Enable Period Care</button></div></details>`;
  }
  document.getElementById("signout")?.insertAdjacentHTML("beforebegin",
    `<div class="card wrapped-row">
       <span style="font-size:26px" aria-hidden="true">🎁</span>
       <div class="grow"><strong>Weekly Wrapped</strong>
         <p class="muted small" style="margin:2px 0 0">Your week in shareable story cards.</p></div>
       <button class="btn btn-primary btn-sm" data-go="wrapped">View</button>
     </div>` + block);
  loadPermissionsCenter(gender, enabled);
  document.getElementById("pc-del") && (document.getElementById("pc-del").onclick = async () => {
    const { message } = await api("/cycle", { method: "DELETE" });
    toast(message); views.profile();
  });
  document.getElementById("pc-export") && (document.getElementById("pc-export").onclick = async () => {
    try {
      const { events } = await api("/cycle/export");
      modal(`<h2>📅 Calendar export</h2>
        <p class="muted small">Predicted dates (the phone app hands these to Google Calendar after you approve the permission):</p>
        <div style="text-align:left">${events.map((e) => `<p class="small">🌸 ${e.start} → ${e.end}</p>`).join("")}</div>
        <button class="btn btn-ghost btn-block section-gap" data-close>Close</button>`);
    } catch (e) { toast(e.message); }
  });
};

/* =============== Onboarding hook: offer Period Care to female users =============== */
/* app.js routes to #home after onboarding; if the user said "female", detour
   through the Period Care offer. Others can enable it from Profile anytime. */
const _origOnboarding = views.onboarding;
views.onboarding = () => {
  _origOnboarding();
  const seen = new MutationObserver(() => {
    $screen.querySelectorAll('[data-v="female"]').forEach((btn) => {
      if (btn.dataset.pcHooked) return;
      btn.dataset.pcHooked = "1";
      btn.addEventListener("click", () => { state.pcOffer = true; });
    });
  });
  seen.observe($screen, { childList: true, subtree: true });
  const _stop = () => seen.disconnect();
  window.addEventListener("hashchange", function h() {
    if (!location.hash.includes("onboarding")) { _stop(); window.removeEventListener("hashchange", h); }
  });
};
const _origHomeGate = views.home;
views.home = async () => {
  if (state.pcOffer) { state.pcOffer = false; return go("pc_offer"); }
  await _origHomeGate();
};

/* =============== Data & Permissions center =============== */

/* One quiet line that tells us exactly which world the app is running in —
   screenshot this if Connect ever misbehaves. */
function deviceDiagnostic() {
  const s = Providers.status();
  if (!s.bridge) return "Running as a website — automatic sensors need the installed app.";
  return `App build: ${s.platform} · step sensor: ${s.steps ? "ready ✓" : "not found"}`
       + ` · screen time: ${s.screen ? "ready ✓" : "not found"}`;
}

async function loadPermissionsCenter(gender, cycleEnabled) {
  try {
    await Providers.detect();          // ask the plugins themselves
    const { integrations } = await api("/permissions");
    const badge = (st) => ({
      connected: `<span class="chip done">Connected</span>`,
      disconnected: `<span class="chip">Off</span>`,
      not_connected: `<span class="chip">Not connected</span>`,
      revoked: `<span class="chip">Revoked</span>`,
    }[st] || `<span class="chip">${esc(st)}</span>`);
    const autoNote = {
      activity: Providers.activity.autoAvailable() ? "" :
        " Automatic sync needs the phone app — manual entry works everywhere.",
      screen_time: Providers.wellbeing.autoAvailable() ? "" :
        " Not readable on web/iPhone — manual entry only, and that's okay.",
    };
    const rows = integrations
      .filter((i) => !(i.key === "period_care" && gender === "male" && !cycleEnabled))
      .map((i) => `
      <div class="perm-row">
        <span class="em" aria-hidden="true">${i.emoji}</span>
        <div class="grow"><strong>${esc(i.label)}</strong> ${badge(i.status)}
          <p class="muted small">${esc(i.why)}${esc(autoNote[i.key] || "")}</p></div>
        ${permAction(i, gender)}
      </div>`).join("");
    document.getElementById("signout")?.insertAdjacentHTML("beforebegin",
      `<h2 class="section-gap">Data & Permissions 🔒</h2>
       <div class="card">
         <p class="muted small">HealthBuddy only uses data you explicitly share, only to personalize your nudges. Nothing here is ever visible to buddies or leaderboards.</p>
         ${rows}
         <p class="muted small" style="margin-top:10px">${deviceDiagnostic()}</p>
       </div>`);
    $screen.querySelectorAll("[data-perm]").forEach((b) => b.onclick = async () => {
      const [kind, status] = b.dataset.perm.split(":");
      if (kind === "period_setup") return go("pc_setup");
      await Providers.detect();
      const prov0 = kind === "activity" ? Providers.activity.auto()
                  : kind === "screen_time" ? Providers.wellbeing.auto() : null;
      const needsDevice = !(prov0 && prov0.requestPermission && Providers.platform() !== "web");
      if (status === "connected" && !needsDevice) {
        /* Native app: fire the real OS permission dialog first. */
        const prov = kind === "activity" ? Providers.activity.auto() : Providers.wellbeing.auto();
        try {
          const granted = await prov.requestPermission();
          if (!granted) {
            toast(kind === "screen_time"
              ? "Flip the toggle for HealthBuddy in that settings screen, then come back 🙂"
              : "Permission not granted yet — you can retry anytime.");
            return;
          }
        } catch (e) { toast(e.message); return; }
        await api("/permissions", { method: "PATCH", body: { integration: kind, status } });
        toast("Connected ✓ Your data will sync automatically now.");
        await Providers.autoSync();
        views.profile();
        return;
      }
      if (status === "connected" && needsDevice) {
        /* Honesty first: on web there's no automatic source to connect to.
           Offer manual entry instead of pretending. */
        const isSteps = kind === "activity";
        return modal(`<h2>${isSteps ? "🚶 Steps" : "📱 Screen time"} on this device</h2>
          <p class="muted small" style="text-align:left">Automatic ${isSteps ? "step tracking (Health Connect on Android, Apple Health on iPhone)" : "screen-time reading"}
          becomes available in the phone-app version of HealthBuddy. In the browser, no app can read that data — so instead of showing fake numbers, HealthBuddy lets you enter it yourself. Manual entries power the exact same smart nudges.</p>
          <button class="btn btn-primary btn-block" id="perm-manual">＋ Enter today's ${isSteps ? "steps" : "screen minutes"}</button>
          <button class="btn btn-ghost btn-block section-gap" data-close>Close</button>`),
          setTimeout(() => {
            document.getElementById("perm-manual").onclick = async () => {
              const v = prompt(isSteps ? "How many steps today?" : "Roughly how many minutes on screens today?", isSteps ? 5000 : 180);
              if (v === null) return;
              try {
                await (isSteps ? Providers.activity.manual.submit(parseInt(v, 10))
                               : Providers.wellbeing.manual.submit(parseInt(v, 10)));
                document.querySelector(".modal-backdrop")?.remove();
                toast("Saved — your nudges just got smarter ✓");
                views.profile();
              } catch (e) { toast(e.message); }
            };
          }, 0);
      }
      await api("/permissions", { method: "PATCH", body: { integration: kind, status } });
      toast(status === "connected" ? "Connected ✓" : "Turned off — that signal won't be used.");
      views.profile();
    });
  } catch (_) { /* permissions center is additive */ }
}

function permAction(i, gender) {
  if (i.key === "period_care")
    return i.status === "connected"
      ? `<span class="muted small">manage above</span>`
      : (gender !== "female"
          ? `<button class="btn btn-ghost btn-sm" data-perm="period_setup:x">Enable</button>`
          : `<span class="muted small">see above</span>`);
  if (i.status === "connected")
    return `<button class="btn btn-ghost btn-sm" data-perm="${i.key}:revoked">Disconnect</button>`;
  return `<button class="btn btn-ghost btn-sm" data-perm="${i.key}:connected">Connect</button>`;
}
