package com.example.assignment1gr01;

import android.graphics.Color;
import android.os.Handler;
import android.os.Looper;
import android.os.Bundle;
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

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

public class MainActivity extends AppCompatActivity {

    // Android emulator reaches host machine via 10.0.2.2
    private static final String TRACKING_STREAM_URL = "http://10.0.2.2:8090/stream.mjpg";
    private static final String TRACKING_STATUS_URL = "http://10.0.2.2:8091/status.json";
    private static final String FIREBASE_LIGHT_PATH = "bots/alphabot/light_on";
    private static final long STATUS_POLL_MS = 350;

    private TextView trackingStateTextView;
    private WebView frameWebView;
    private Button lightToggleButton;

    private DatabaseReference lightRef;
    private boolean currentLightOn = false;
    private final Handler statusHandler = new Handler(Looper.getMainLooper());
    private final Runnable statusPollRunnable = new Runnable() {
        @Override
        public void run() {
            fetchTrackingStatusAsync();
            statusHandler.postDelayed(this, STATUS_POLL_MS);
        }
    };

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

        trackingStateTextView = findViewById(R.id.trackingStateTextView);
        frameWebView = findViewById(R.id.directWebView);
        lightToggleButton = findViewById(R.id.lightToggleButton);

        setupWebView(frameWebView);
        loadMjpegStream(frameWebView, TRACKING_STREAM_URL);
        trackingStateTextView.setText("Pose: - | State: loading...");
        statusHandler.post(statusPollRunnable);

        lightRef = FirebaseDatabase.getInstance().getReference(FIREBASE_LIGHT_PATH);
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

    private void fetchTrackingStatusAsync() {
        new Thread(() -> {
            HttpURLConnection connection = null;
            try {
                URL url = new URL(TRACKING_STATUS_URL);
                connection = (HttpURLConnection) url.openConnection();
                connection.setConnectTimeout(1200);
                connection.setReadTimeout(1200);
                connection.setRequestMethod("GET");

                int code = connection.getResponseCode();
                if (code != HttpURLConnection.HTTP_OK) {
                    runOnUiThread(() -> trackingStateTextView.setText("Pose: - | State: offline"));
                    return;
                }

                BufferedReader reader = new BufferedReader(
                        new InputStreamReader(connection.getInputStream(), StandardCharsets.UTF_8)
                );
                StringBuilder builder = new StringBuilder();
                String line;
                while ((line = reader.readLine()) != null) {
                    builder.append(line);
                }
                reader.close();

                JSONObject json = new JSONObject(builder.toString());
                String mode = json.optString("mode", "-");
                boolean pose = json.optBoolean("pose", false);
                String state = json.optString("state", "-");
                double holdTimer = json.optDouble("hold_timer_s", 0.0);
                String normalizedState = normalizeState(state);

                runOnUiThread(() -> {
                    String timerPart = holdTimer > 0.0
                            ? String.format(" | Timer: %.1fs", holdTimer)
                            : "";
                    trackingStateTextView.setText(
                            "Mode: " + mode
                                + " | Pose: " + (pose ? "YES" : "NO")
                                    + timerPart
                                    + " | State: " + normalizedState
                    );
                });
            } catch (Exception e) {
                runOnUiThread(() -> trackingStateTextView.setText("Mode: - | Pose: - | State: offline"));
            } finally {
                if (connection != null) {
                    connection.disconnect();
                }
            }
        }).start();
    }

    private String normalizeState(String state) {
        if (state == null || state.isBlank()) {
            return "-";
        }
        String lower = state.toLowerCase();
        if (lower.contains("no pose") || lower.contains("keine pose")) {
            return "no pose";
        }
        return state;
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        statusHandler.removeCallbacks(statusPollRunnable);

        if (frameWebView != null) {
            frameWebView.destroy();
        }
    }
}
