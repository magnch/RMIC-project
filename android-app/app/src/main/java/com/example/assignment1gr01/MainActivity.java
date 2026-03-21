package com.example.assignment1gr01;

import android.graphics.Color;
import android.os.Bundle;
import android.util.Log;
import android.widget.Button;
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

    private TextView modeValueTextView;
    private TextView personValueTextView;
    private TextView distanceValueTextView;
    private TextView stateValueTextView;
    private TextView trackingLinkValueTextView;
    private WebView frameWebView;
    private Button lightToggleButton;

    private DatabaseReference lightRef;
    private DatabaseReference displayRef;
    private boolean currentLightOn = false;

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
        stateValueTextView = findViewById(R.id.stateValueTextView);
        trackingLinkValueTextView = findViewById(R.id.trackingLinkValueTextView);
        frameWebView = findViewById(R.id.directWebView);
        lightToggleButton = findViewById(R.id.lightToggleButton);

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
                stateValueTextView.setText("light read failed: " + error.getCode());
            }
        });

        displayRef = database.getReference(FIREBASE_DISPLAY_PATH);
        displayRef.addValueEventListener(new ValueEventListener() {
            @Override
            public void onDataChange(DataSnapshot snapshot) {
                if (!snapshot.exists()) {
                    stateValueTextView.setText("no app_display data yet");
                    trackingLinkValueTextView.setText("offline");
                    return;
                }

                String mode = snapshot.child("mode").getValue(String.class);
                String trackingState = snapshot.child("tracking_state").getValue(String.class);
                Boolean alarm = snapshot.child("tracking_alarm").getValue(Boolean.class);
                Boolean trackingOnline = snapshot.child("tracking_online").getValue(Boolean.class);

                Number distanceValue = getNumericValue(snapshot.child("ultrasonic_cm"));
                Number holdValue = getNumericValue(snapshot.child("hold_timer_s"));
                String updatedAt = snapshot.child("updated_at").getValue(String.class);

                updateDisplayCards(
                        mode,
                        alarm,
                        distanceValue,
                        trackingState,
                        holdValue,
                        trackingOnline
                );

                if (updatedAt != null && !updatedAt.isBlank()) {
                    boolean online = trackingOnline != null && trackingOnline;
                    trackingLinkValueTextView.setText((online ? "online" : "offline") + " · " + updatedAt);
                }

                Log.d(TAG, "Display listener update received");
            }

            @Override
            public void onCancelled(DatabaseError error) {
                Log.e(TAG, "Display listener cancelled: " + error.getMessage());
                setDisplayOffline();
                stateValueTextView.setText("display read failed: " + error.getCode());
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

        updateLightButtonLabel();
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
        stateValueTextView.setText("waiting for data...");
        trackingLinkValueTextView.setText("offline");
    }

    private void setDisplayOffline() {
        trackingLinkValueTextView.setText("offline");
        stateValueTextView.setText("firebase read failed");
    }

    private void updateDisplayCards(
            String mode,
            Boolean alarm,
            Number distanceValue,
            String trackingState,
            Number holdValue,
            Boolean trackingOnline
    ) {
        String normalizedMode = (mode == null || mode.isBlank()) ? "-" : mode.toUpperCase(Locale.ROOT);
        boolean personDetected = alarm != null && alarm;
        String personText = personDetected ? "DETECTED" : "CLEAR";

        String distanceText = "n/a";
        if (distanceValue != null) {
            distanceText = String.format(Locale.US, "%.1f cm", distanceValue.doubleValue());
        }

        String stateText = (trackingState == null || trackingState.isBlank()) ? "-" : trackingState;
        if (holdValue != null && holdValue.doubleValue() > 0.0) {
            stateText = stateText + String.format(Locale.US, " (hold %.1fs)", holdValue.doubleValue());
        }

        boolean online = trackingOnline != null && trackingOnline;

        modeValueTextView.setText(normalizedMode);
        personValueTextView.setText(personText);
        distanceValueTextView.setText(distanceText);
        stateValueTextView.setText(stateText);
        trackingLinkValueTextView.setText(online ? "online" : "offline");
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
        webView.setBackgroundColor(Color.BLACK);
        webView.setWebViewClient(new WebViewClient());
    }

    private void loadMjpegStream(WebView webView, String streamUrl) {
        String safeUrl = streamUrl.replace("'", "\\'");
        String html = "<html><body style='margin:0;background:#000;display:flex;align-items:center;justify-content:center;'>"
                + "<img id='cam' style='width:100%;height:100%;object-fit:contain;'/>"
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
