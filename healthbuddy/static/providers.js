/* HealthBuddy providers.js — cross-platform device-data adapters.
   =================================================================
   The rest of the app never asks "which OS is this?" — it asks
   Providers.activity.getDailySteps() and gets an honest answer.

   Native plugin names MUST match the @CapacitorPlugin(name=...) values in
   native/android/*.java:  HBSteps  and  HBUsage.

   Adapters:
   - Android: real hardware step counter (HBSteps) + UsageStats screen time
     (HBUsage). Both behind explicit OS permission prompts.
   - iOS: HealthKit steps via the @capgo/capacitor-health plugin ("Health").
     Screen time is not readable by third-party apps (Apple policy).
   - Web: honestly unavailable — browsers cannot read system sensors.
   - Manual: always available fallback; typing the number is the consent.
   ================================================================= */
"use strict";

/* Resolve a native plugin by name. Capacitor exposes plugins either on
   window.Capacitor.Plugins or via registerPlugin(). Exposed globally so the
   diagnostic line in Data & Permissions can report what was found. */
window.__hbPlugin = function (name) {
  const C = window.Capacitor;
  if (!C) return null;
  if (C.Plugins && C.Plugins[name]) return C.Plugins[name];
  if (typeof C.isPluginAvailable === "function" && !C.isPluginAvailable(name)) return null;
  if (typeof C.registerPlugin === "function") {
    try { return C.registerPlugin(name); } catch (_) { /* not registered */ }
  }
  return null;
};

const Providers = (() => {
  const native = () => window.Capacitor?.getPlatform?.() || null;   // 'android' | 'ios' | null
  const P = (n) => window.__hbPlugin(n);

  /* Cache filled by detect(): { steps: bool, screen: bool } — set by actually
     calling the plugin, so a missing/broken plugin can never look available. */
  const found = { steps: false, screen: false, checked: false };

  /* ---------- Activity (steps) ---------- */
  const AndroidActivityProvider = {
    name: "device_sensor",
    isAvailable: () => native() === "android" && !!P("HBSteps"),
    requestPermission: async () => (await P("HBSteps").requestPermission()).granted,
    getDailySteps: async () => (await P("HBSteps").getTodaySteps()).steps,
  };
  const IOSActivityProvider = {
    name: "healthkit",
    isAvailable: () => native() === "ios" && !!P("Health"),
    requestPermission: async () => {
      await P("Health").requestAuthorization({ read: ["steps"] });
      return true;
    },
    getDailySteps: async () => {
      const start = new Date(); start.setHours(0, 0, 0, 0);
      const r = await P("Health").queryAggregated({
        dataType: "steps", startDate: start.toISOString(), endDate: new Date().toISOString() });
      return Math.round(r?.aggregatedData?.[0]?.value ?? r?.value ?? 0);
    },
  };
  const WebActivityProvider = {
    name: "web", isAvailable: () => false,
    requestPermission: async () => false, getDailySteps: async () => null,
  };
  const ManualActivityProvider = {
    name: "manual", isAvailable: () => true, requestPermission: async () => true,
    submit: (steps) => api("/activity/manual", { method: "POST", body: { steps } }),
  };

  /* ---------- Screen time ---------- */
  const AndroidWellbeingProvider = {
    name: "android_usage",
    isAvailable: () => native() === "android" && !!P("HBUsage"),
    requestPermission: async () => {
      const r = await P("HBUsage").requestPermission();
      return r.opened_settings ? "pending" : !!r.granted;
    },
    getScreenMinutes: async () => (await P("HBUsage").getTodayScreenMinutes()).minutes,
  };
  const IOSWellbeingProvider = {   // Apple blocks third-party reads
    name: "ios_screentime", isAvailable: () => false,
    requestPermission: async () => false, getScreenMinutes: async () => null,
  };
  const WebWellbeingProvider = {
    name: "web", isAvailable: () => false,
    requestPermission: async () => false, getScreenMinutes: async () => null,
  };
  const ManualWellbeingProvider = {
    name: "manual", isAvailable: () => true, requestPermission: async () => true,
    submit: (m) => api("/wellbeing/manual", { method: "POST", body: { screen_time_minutes: m } }),
  };

  const pick = (chain) => chain.find((p) => p.isAvailable());

  const api_ = {
    activity: {
      auto: () => pick([AndroidActivityProvider, IOSActivityProvider, WebActivityProvider]),
      manual: ManualActivityProvider,
      autoAvailable: () => found.steps || !!pick([AndroidActivityProvider, IOSActivityProvider]),
    },
    wellbeing: {
      auto: () => pick([AndroidWellbeingProvider, IOSWellbeingProvider, WebWellbeingProvider]),
      manual: ManualWellbeingProvider,
      autoAvailable: () => found.screen || !!pick([AndroidWellbeingProvider]),
    },
    platform: () => native() || "web",
    status: () => ({ ...found, platform: native() || "web", bridge: !!window.Capacitor }),

    /* Ask the plugins themselves whether they can work here. Safe on web:
       no plugins → everything false, app behaves exactly as before. */
    async detect() {
      if (found.checked) return found;
      try {
        const s = P("HBSteps");
        if (s) found.steps = !!(await s.isAvailable()).available;
      } catch (_) { found.steps = false; }
      try {
        const u = P("HBUsage");
        if (u) found.screen = !!(await u.isAvailable()).available;
      } catch (_) { found.screen = false; }
      if (native() === "ios") found.steps = !!P("Health");
      found.checked = true;
      return found;
    },

    /* Read the device and push to the server. Runs on app open + every 15 min
       inside the native app; silent no-op on the website. */
    async autoSync() {
      await this.detect();
      const a = this.activity.auto();
      if (a && a.getDailySteps) {
        try {
          const steps = await a.getDailySteps();
          if (steps !== null && steps !== undefined)
            await api("/activity/sync", { method: "POST", body: { steps, source: a.name } });
        } catch (_) { /* permission not granted yet */ }
      }
      const w = this.wellbeing.auto();
      if (w && w.getScreenMinutes) {
        try {
          const mins = await w.getScreenMinutes();
          if (mins !== null && mins !== undefined)
            await api("/wellbeing/sync", { method: "POST", body: { screen_time_minutes: mins, source: w.name } });
        } catch (_) { }
      }
    },
  };
  return api_;
})();

if (window.Capacitor) {
  setTimeout(() => Providers.autoSync(), 1500);
  setInterval(() => Providers.autoSync(), 15 * 60 * 1000);
  document.addEventListener("resume", () => Providers.autoSync());
}
