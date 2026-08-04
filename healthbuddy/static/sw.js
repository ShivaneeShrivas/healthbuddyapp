/* Minimal service worker: makes the app installable today and is the hook
   where web push notifications plug in later (see DEPLOYMENT.md Phase 2). */
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(clients.claim()));
self.addEventListener("fetch", () => {}); /* network passthrough for now */
