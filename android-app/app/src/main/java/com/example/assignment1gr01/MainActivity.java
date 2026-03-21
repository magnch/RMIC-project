package com.example.assignment1gr01;

import android.graphics.Color;
import android.os.Bundle;
import android.util.Log;
import android.widget.Button;
import android.widget.SeekBar;
import android.widget.TextView;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import androidx.activity.EdgeToEdge;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.graphics.Insets;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowInsetsCompat;

import com.google.firebase.database.DataSnapshot;
import com.google.firebase.database.DatabaseError;
import com.google.firebase.database.DatabaseReference;
import com.google.firebase.database.FirebaseDatabase;
import com.google.firebase.database.ValueEventListener;
import java.util.Locale;

public class MainActivity extends AppCompatActivity {
    private static final String TAG = "MainActivity";

    // Android emulator reaches host machine via 10.0.2.2
    private static final String TRACKING_STREAM_URL = "http://10.0.2.2:8090/stream.mjpg";
    private static final String FIREBASE_DB_URL = "https://iot-alarm-app-b4b9c-default-rtdb.europe-west1.firebasedatabase.app";
    private static final String FIREBASE_LIGHT_PATH = "bots/alphabot/light_on";
    private static final String FIREBASE_DISPLAY_PATH = "bots/alphabot/app_display";
    private static final String FIREBASE_CONTROL_MODE_PATH = "bots/alphabot/app_control/mode_profile";

    private static final String MODE_IDLE = "IDLE";
    private static final String MODE_PATROL_ONLY = "PATROL_ONLY";
    private static final String MODE_FOLLOW_ONLY = "FOLLOW_ONLY";
    private static final String MODE_PATROL_FOLLOW = "PATROL_FOLLOW";

    private TextView modeValueTextView;
    private TextView personValueTextView;
    private TextView distanceValueTextView;
    private TextView controlModeValueTextView;
    private WebView frameWebView;
    private Button lightToggleButton;
    private SeekBar controlModeSeekBar;

    private DatabaseReference lightRef;
    private DatabaseReference displayRef;
    private DatabaseReference controlModeRef;
    private boolean currentLightOn = false;
    private boolean updatingControlFromFirebase = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        EdgeToEdge.enable(this);
        setContentView(R.layout.activity_main);
        ViewCompat.setOnApplyWindowInsetsListener(findViewById(R.id.main), (v, insets) -> {
            Insets systemBars = insets.getInsets(WindowInsetsCompat.Type.systemBars());
            v.setPadding(systemBars.left, systemBars.top, systemBars.right, systemBars.bottom);
            return insets;
        });

        modeValueTextView = findViewById(R.id.modeValueTextView);
        personValueTextView = findViewById(R.id.personValueTextView);
        distanceValueTextView = findViewById(R.id.distanceValueTextView);
        controlModeValueTextView = findViewById(R.id.controlModeValueTextView);
        frameWebView = findViewById(R.id.directWebView);
        lightToggleButton = findViewById(R.id.lightToggleButton);
        controlModeSeekBar = findViewById(R.id.controlModeSeekBar);

        setupWebView(frameWebView);
        loadMjpegStream(frameWebView, TRACKING_STREAM_URL);
        setDisplayFallback();

        FirebaseDatabase database = FirebaseDatabase.getInstance(FIREBASE_DB_URL);
        Log.i(TAG, "Using Firebase DB URL: " + FIREBASE_DB_URL);

        lightRef = database.getReference(FIREBASE_LIGHT_PATH);
        lightRef.addValueEventListener(new ValueEventListener() {
            @Override
            public void onDataChange(DataSnapshot snapshot) {
                Object value = snapshot.getValue();
                if (value instanceof Boolean) {
                    currentLightOn = (Boolean) value;
                    updateLightButtonLabel();
                }
            }

            @Override
            public void onCancelled(DatabaseError error) {
                Log.e(TAG, "Light read failed: " + error.getCode());
            }
        });

        displayRef = database.getReference(FIREBASE_DISPLAY_PATH);
        displayRef.addValueEventListener(new ValueEventListener() {
            @Override
            public void onDataChange(DataSnapshot snapshot) {
                if (!snapshot.exists()) {
                    modeValueTextView.setText("-");
                    return;
                }

                String mode = snapshot.child("mode").getValue(String.class);
                Boolean alarm = snapshot.child("tracking_alarm").getValue(Boolean.class);

                Number distanceValue = getNumericValue(snapshot.child("ultrasonic_cm"));
                updateDisplayCards(mode, alarm, distanceValue);

                Log.d(TAG, "Display listener update received");
            }

            @Override
            public void onCancelled(DatabaseError error) {
                Log.e(TAG, "Display listener cancelled: " + error.getMessage());
                modeValueTextView.setText("OFFLINE");
            }
        });

        controlModeRef = database.getReference(FIREBASE_CONTROL_MODE_PATH);
        controlModeRef.addValueEventListener(new ValueEventListener() {
            @Override
            public void onDataChange(DataSnapshot snapshot) {
                String modeProfile = normalizeModeProfile(snapshot.getValue(String.class));
                int progress = modeProfileToProgress(modeProfile);

                updatingControlFromFirebase = true;
                controlModeSeekBar.setProgress(progress);
                updatingControlFromFirebase = false;

                controlModeValueTextView.setText(modeProfileToLabel(modeProfile));
            }

            @Override
            public void onCancelled(DatabaseError error) {
                Log.e(TAG, "Control mode read failed: " + error.getMessage());
            }
        });

        lightToggleButton.setOnClickListener(v -> {
            boolean newState = !currentLightOn;
            lightRef.setValue(newState)
                    .addOnSuccessListener(unused -> {
                        currentLightOn = newState;
                        updateLightButtonLabel();
                    });
        });

        controlModeSeekBar.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override
            public void onProgressChanged(SeekBar seekBar, int progress, boolean fromUser) {
                String modeProfile = progressToModeProfile(progress);
                controlModeValueTextView.setText(modeProfileToLabel(modeProfile));

                if (fromUser && !updatingControlFromFirebase && controlModeRef != null) {
                    controlModeRef.setValue(modeProfile);
                }
            }

            @Override
            public void onStartTrackingTouch(SeekBar seekBar) {
            }

            @Override
            public void onStopTrackingTouch(SeekBar seekBar) {
            }
        });

        updateLightButtonLabel();
        controlModeValueTextView.setText(modeProfileToLabel(MODE_PATROL_FOLLOW));
    }

    private String normalizeModeProfile(String value) {
        if (value == null || value.isBlank()) {
            return MODE_PATROL_FOLLOW;
        }
        String normalized = value.trim().toUpperCase(Locale.ROOT);
        switch (normalized) {
            case MODE_IDLE:
            case MODE_PATROL_ONLY:
            case MODE_FOLLOW_ONLY:
            case MODE_PATROL_FOLLOW:
                return normalized;
            default:
                return MODE_PATROL_FOLLOW;
        }
    }

    private int modeProfileToProgress(String modeProfile) {
        switch (modeProfile) {
            case MODE_IDLE:
                return 0;
            case MODE_PATROL_ONLY:
                return 1;
            case MODE_FOLLOW_ONLY:
                return 2;
            case MODE_PATROL_FOLLOW:
            default:
                return 3;
        }
    }

    private String progressToModeProfile(int progress) {
        switch (progress) {
            case 0:
                return MODE_IDLE;
            case 1:
                return MODE_PATROL_ONLY;
            case 2:
                return MODE_FOLLOW_ONLY;
            case 3:
            default:
                return MODE_PATROL_FOLLOW;
        }
    }

    private String modeProfileToLabel(String modeProfile) {
        switch (modeProfile) {
            case MODE_IDLE:
                return "IDLE";
            case MODE_PATROL_ONLY:
                return "PATROL ONLY";
            case MODE_FOLLOW_ONLY:
                return "FOLLOW ONLY";
            case MODE_PATROL_FOLLOW:
            default:
                return "PATROL + FOLLOW";
        }
    }

    private Number getNumericValue(DataSnapshot snapshot) {
        Object value = snapshot.getValue();
        if (value instanceof Number) {
            return (Number) value;
        }
        if (value instanceof String) {
            try {
                return Double.parseDouble((String) value);
            } catch (NumberFormatException ignored) {
                return null;
            }
        }
        return null;
    }

    private void setDisplayFallback() {
        modeValueTextView.setText("-");
        personValueTextView.setText("NO");
        distanceValueTextView.setText("n/a");
    }

    private void updateDisplayCards(
            String mode,
            Boolean alarm,
            Number distanceValue
    ) {
        String normalizedMode = (mode == null || mode.isBlank()) ? "-" : mode.toUpperCase(Locale.ROOT);
        boolean personDetected = alarm != null && alarm;
        String personText = personDetected ? "DETECTED" : "CLEAR";

        String distanceText = "n/a";
        if (distanceValue != null) {
            distanceText = String.format(Locale.US, "%.1f cm", distanceValue.doubleValue());
        }

        modeValueTextView.setText(normalizedMode);
        personValueTextView.setText(personText);
        distanceValueTextView.setText(distanceText);
    }

    private void updateLightButtonLabel() {
        if (lightToggleButton == null) {
            return;
        }
        lightToggleButton.setText(currentLightOn ? "Light: ON" : "Light: OFF");
    }

    private void setupWebView(WebView webView) {
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setLoadWithOverviewMode(true);
        settings.setUseWideViewPort(true);
        webView.setBackgroundColor(Color.WHITE);
        webView.setWebViewClient(new WebViewClient());
    }

    private void loadMjpegStream(WebView webView, String streamUrl) {
        String safeUrl = streamUrl.replace("'", "\\'");
        String html = "<html><body style='margin:0;background:#fff;display:flex;align-items:center;justify-content:center;overflow:hidden;'>"
            + "<img id='cam' style='width:100%;height:100%;object-fit:cover;'/>"
                + "<script>"
                + "const base='" + safeUrl + "';"
                + "const img=document.getElementById('cam');"
                + "img.src=base;"
                + "</script></body></html>";
        webView.loadDataWithBaseURL(streamUrl, html, "text/html", "UTF-8", null);
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();

        if (frameWebView != null) {
            frameWebView.destroy();
        }
    }
}
