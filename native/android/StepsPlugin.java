package app.healthbuddy;

/*
 * HealthBuddy StepsPlugin — reads REAL steps from the phone's hardware
 * step-counter sensor (present on virtually every Android phone since 2014).
 *
 * How it works (simple + reliable, no external services needed):
 * - Sensor.TYPE_STEP_COUNTER reports total steps since the phone last booted.
 * - At the first reading of each calendar day we store that number as the
 *   day's "baseline" in SharedPreferences.
 * - Today's steps = current sensor value - today's baseline.
 * - Survives app restarts; resets correctly at midnight and after reboots.
 *
 * Permission: ACTIVITY_RECOGNITION (Android 10+) — a normal runtime
 * permission dialog, requested only when the user taps Connect.
 *
 * Upgrade path (optional, later): Health Connect can replace this class to
 * also merge steps from smartwatches. The JS side won't change — that's the
 * point of the provider abstraction.
 */

import android.Manifest;
import android.content.Context;
import android.content.SharedPreferences;
import android.hardware.Sensor;
import android.hardware.SensorEvent;
import android.hardware.SensorEventListener;
import android.hardware.SensorManager;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.getcapacitor.annotation.Permission;
import com.getcapacitor.annotation.PermissionCallback;

import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

@CapacitorPlugin(
    name = "HBSteps",
    permissions = { @Permission(strings = { Manifest.permission.ACTIVITY_RECOGNITION }, alias = "activity") }
)
public class StepsPlugin extends Plugin implements SensorEventListener {

    private SensorManager sensorManager;
    private Float latestSinceBoot = null;
    private PluginCall pendingRead = null;

    private SharedPreferences prefs() {
        return getContext().getSharedPreferences("hb_steps", Context.MODE_PRIVATE);
    }

    private String todayKey() {
        return "base_" + new SimpleDateFormat("yyyy-MM-dd", Locale.US).format(new Date());
    }

    @PluginMethod
    public void isAvailable(PluginCall call) {
        SensorManager sm = (SensorManager) getContext().getSystemService(Context.SENSOR_SERVICE);
        boolean ok = sm != null && sm.getDefaultSensor(Sensor.TYPE_STEP_COUNTER) != null;
        JSObject ret = new JSObject();
        ret.put("available", ok);
        ret.put("granted", getPermissionState("activity") == com.getcapacitor.PermissionState.GRANTED);
        call.resolve(ret);
    }

    @PluginMethod
    public void requestPermission(PluginCall call) {
        if (getPermissionState("activity") == com.getcapacitor.PermissionState.GRANTED) {
            JSObject ret = new JSObject(); ret.put("granted", true); call.resolve(ret);
        } else {
            requestPermissionForAlias("activity", call, "permDone");
        }
    }

    @PermissionCallback
    private void permDone(PluginCall call) {
        JSObject ret = new JSObject();
        ret.put("granted", getPermissionState("activity") == com.getcapacitor.PermissionState.GRANTED);
        call.resolve(ret);
    }

    @PluginMethod
    public void getTodaySteps(PluginCall call) {
        if (getPermissionState("activity") != com.getcapacitor.PermissionState.GRANTED) {
            call.reject("permission_denied");
            return;
        }
        sensorManager = (SensorManager) getContext().getSystemService(Context.SENSOR_SERVICE);
        Sensor s = sensorManager == null ? null : sensorManager.getDefaultSensor(Sensor.TYPE_STEP_COUNTER);
        if (s == null) { call.reject("no_sensor"); return; }
        pendingRead = call;
        call.setKeepAlive(true);
        sensorManager.registerListener(this, s, SensorManager.SENSOR_DELAY_UI);
    }

    @Override
    public void onSensorChanged(SensorEvent event) {
        latestSinceBoot = event.values[0];
        if (pendingRead == null) return;

        SharedPreferences p = prefs();
        String key = todayKey();
        float baseline;
        if (p.contains(key)) {
            baseline = p.getFloat(key, latestSinceBoot);
            // Phone rebooted since baseline (counter reset below baseline):
            if (latestSinceBoot < baseline) {
                float carried = p.getFloat(key + "_carry", 0f);
                p.edit().putFloat(key + "_carry", carried + baseline)  // keep earlier steps
                        .putFloat(key, 0f).apply();
                baseline = 0f;
            }
        } else {
            baseline = latestSinceBoot;                 // first reading today
            p.edit().putFloat(key, baseline).apply();
        }
        float carry = p.getFloat(key + "_carry", 0f);
        int today = Math.max(0, Math.round(latestSinceBoot - baseline + carry));

        JSObject ret = new JSObject();
        ret.put("steps", today);
        ret.put("source", "device_sensor");
        pendingRead.resolve(ret);
        pendingRead.setKeepAlive(false);
        pendingRead = null;
        sensorManager.unregisterListener(this);
    }

    @Override
    public void onAccuracyChanged(Sensor sensor, int accuracy) { }
}
