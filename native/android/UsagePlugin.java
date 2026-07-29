package app.healthbuddy;

/*
 * HealthBuddy UsagePlugin — reads REAL screen time from Android's
 * UsageStatsManager (the same data source as the system's Digital Wellbeing).
 *
 * Permission model: "Usage access" is a special permission — there is no
 * popup dialog. The user must flip a switch for HealthBuddy on a system
 * settings screen. requestPermission() opens that exact screen for them;
 * the app detects the grant when they come back.
 *
 * Computation: we replay today's app-switch events since midnight and sum
 * every foreground session across all apps = total screen-on usage minutes.
 */

import android.app.AppOpsManager;
import android.app.usage.UsageEvents;
import android.app.usage.UsageStatsManager;
import android.content.Context;
import android.content.Intent;
import android.os.Process;
import android.provider.Settings;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import java.util.Calendar;
import java.util.HashMap;
import java.util.Map;

@CapacitorPlugin(name = "HBUsage")
public class UsagePlugin extends Plugin {

    private boolean hasUsageAccess() {
        AppOpsManager appOps = (AppOpsManager) getContext().getSystemService(Context.APP_OPS_SERVICE);
        int mode = appOps.unsafeCheckOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS,
                Process.myUid(), getContext().getPackageName());
        return mode == AppOpsManager.MODE_ALLOWED;
    }

    @PluginMethod
    public void isAvailable(PluginCall call) {
        JSObject ret = new JSObject();
        ret.put("available", true);          // every Android phone has this
        ret.put("granted", hasUsageAccess());
        call.resolve(ret);
    }

    @PluginMethod
    public void requestPermission(PluginCall call) {
        if (hasUsageAccess()) {
            JSObject ret = new JSObject(); ret.put("granted", true); call.resolve(ret); return;
        }
        // Send the user straight to the system switch for our app.
        Intent intent = new Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS);
        getContext().startActivity(intent);
        JSObject ret = new JSObject();
        ret.put("granted", false);
        ret.put("opened_settings", true);    // JS re-checks with isAvailable() on resume
        call.resolve(ret);
    }

    @PluginMethod
    public void getTodayScreenMinutes(PluginCall call) {
        if (!hasUsageAccess()) { call.reject("permission_denied"); return; }

        Calendar midnight = Calendar.getInstance();
        midnight.set(Calendar.HOUR_OF_DAY, 0);
        midnight.set(Calendar.MINUTE, 0);
        midnight.set(Calendar.SECOND, 0);
        midnight.set(Calendar.MILLISECOND, 0);
        long start = midnight.getTimeInMillis();
        long now = System.currentTimeMillis();

        UsageStatsManager usm = (UsageStatsManager) getContext()
                .getSystemService(Context.USAGE_STATS_SERVICE);
        UsageEvents events = usm.queryEvents(start, now);

        Map<String, Long> openedAt = new HashMap<>();
        long totalMs = 0;
        UsageEvents.Event e = new UsageEvents.Event();
        while (events.hasNextEvent()) {
            events.getNextEvent(e);
            String pkg = e.getPackageName();
            if (e.getEventType() == UsageEvents.Event.ACTIVITY_RESUMED) {
                openedAt.put(pkg, e.getTimeStamp());
            } else if (e.getEventType() == UsageEvents.Event.ACTIVITY_PAUSED) {
                Long opened = openedAt.remove(pkg);
                if (opened != null && e.getTimeStamp() > opened) {
                    totalMs += e.getTimeStamp() - opened;
                }
            }
        }
        for (Long opened : openedAt.values()) {         // apps still open right now
            if (now > opened) totalMs += now - opened;
        }

        JSObject ret = new JSObject();
        ret.put("minutes", (int) (totalMs / 60000));
        ret.put("source", "android_usage");
        call.resolve(ret);
    }
}
