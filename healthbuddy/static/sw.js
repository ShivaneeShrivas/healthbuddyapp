/* Minimal service worker: makes the app installable, AND is the delivery
   layer for real push notifications - this is what fires "phone buzzes"
   alerts even when the app/tab is fully closed. Registered from /sw.js
   (see healthbuddy/__init__.py) so its scope covers the whole app, not
   just /static/ - a narrower scope silently breaks
   navigator.serviceWorker.ready on every other page. */
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(clients.claim()));
self.addEventListener("fetch", () => {}); /* network passthrough for now */

/* A push message arrived from the server (see services/push.py). Show it as
   a system notification with two direct-action buttons, so the person can
   respond without ever opening the app. */
self.addEventListener("push", (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch { data = {}; }

  const title = data.title || "HealthBuddy";
  const body = data.body || "You've got a nudge waiting.";
  const url = data.url || "/#nudges";

  const options = {
    body,
    icon: "/static/icon-192.png",
    badge: "/static/icon-192.png",
    tag: data.tag || "healthbuddy-nudge", // replaces older un-tapped nudges instead of stacking spam
    renotify: true,
    data: { url, templateId: data.tag, userId: data.user_id, sig: data.sig },
    actions: [
      { action: "remind", title: "Remind in 1h" },
      { action: "done", title: "Done ✓" },
    ],
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

/* User tapped the notification itself OR one of its action buttons. */
self.addEventListener("notificationclick", (event) => {
  const notif = event.notification;
  const { url, templateId, userId, sig } = notif.data || {};
  notif.close();

  if (event.action === "remind" || event.action === "done") {
    const endpoint = event.action === "remind" ? "/api/push/snooze" : "/api/push/ack";
    event.waitUntil(
      fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId, template_id: templateId, sig }),
      }).catch(() => {})
    );
    return; // action buttons resolve in place - don't also open/focus the app
  }

  // Tapped the notification body itself: focus an existing tab if one's
  // open, otherwise open a new one, and land on the right screen.
  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        if ("focus" in client) {
          client.navigate(url);
          return client.focus();
        }
      }
      if (clients.openWindow) return clients.openWindow(url);
    })
  );
});
