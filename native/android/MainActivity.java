package app.healthbuddy;

import android.os.Bundle;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        // Register HealthBuddy's native data plugins BEFORE super.onCreate
        registerPlugin(StepsPlugin.class);
        registerPlugin(UsagePlugin.class);
        super.onCreate(savedInstanceState);
    }
}
