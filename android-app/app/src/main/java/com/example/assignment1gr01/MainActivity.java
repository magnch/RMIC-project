package com.example.assignment1gr01;

import android.media.Ringtone;
import android.media.RingtoneManager;
import android.net.Uri;
import android.os.Bundle;
import android.widget.Button;
import android.widget.TextView;

import androidx.activity.EdgeToEdge;
import androidx.annotation.NonNull;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.graphics.Insets;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowInsetsCompat;

import com.google.firebase.database.DataSnapshot;
import com.google.firebase.database.DatabaseError;
import com.google.firebase.database.DatabaseReference;
import com.google.firebase.database.FirebaseDatabase;
import com.google.firebase.database.ValueEventListener;

public class MainActivity extends AppCompatActivity {

    TextView measurementTextView;
    TextView alarmStatusTextView;
    Button actionButton;

    DatabaseReference measurementRef;
    DatabaseReference alarmStatusRef;
    DatabaseReference enableAlertSoundRef;

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

        measurementTextView = findViewById(R.id.measurementTextView);
        alarmStatusTextView = findViewById(R.id.alarmStatusTextView);
        actionButton = findViewById(R.id.actionButton);

        FirebaseDatabase database = FirebaseDatabase.getInstance();
        measurementRef = database.getReference("measurement");
        alarmStatusRef = database.getReference("alarm_status");
        enableAlertSoundRef = database.getReference("enable_alert_sound");

        measurementRef.addValueEventListener(new ValueEventListener() {
            @Override
            public void onDataChange(@NonNull DataSnapshot dataSnapshot) {
                Float value = dataSnapshot.getValue(Float.class);
                if (value != null) {
                    measurementTextView.setText(String.valueOf(value));
                }
            }

            @Override
            public void onCancelled(@NonNull DatabaseError error) {
            }
        });

        alarmStatusRef.addValueEventListener(new ValueEventListener() {
            @Override
            public void onDataChange(@NonNull DataSnapshot dataSnapshot) {
                Boolean value = dataSnapshot.getValue(Boolean.class);
                if (value != null) {
                    if (value) {
                        alarmStatusTextView.setText("ALERT! ALERT!");
                        try {
                            Uri notification = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION);
                            Ringtone r = RingtoneManager.getRingtone(getApplicationContext(), notification);
                            r.play();
                        } catch (Exception e) {
                            e.printStackTrace();
                        }
                    } else {
                        alarmStatusTextView.setText("Nothing to Report");
                    }
                }
            }

            @Override
            public void onCancelled(@NonNull DatabaseError error) {
            }
        });

        enableAlertSoundRef.addValueEventListener(new ValueEventListener() {
            @Override
            public void onDataChange(@NonNull DataSnapshot dataSnapshot) {
                Boolean value = dataSnapshot.getValue(Boolean.class);
                if (value != null) {
                    if (value) {
                        actionButton.setText("Disable Buzzer");
                    } else {
                        actionButton.setText("Enable Buzzer");
                    }
                }
            }

            @Override
            public void onCancelled(@NonNull DatabaseError error) {
            }
        });

        actionButton.setOnClickListener(v -> enableAlertSoundRef.addListenerForSingleValueEvent(new ValueEventListener() {
            @Override
            public void onDataChange(@NonNull DataSnapshot dataSnapshot) {
                Boolean value = dataSnapshot.getValue(Boolean.class);
                if (value != null) {
                    enableAlertSoundRef.setValue(!value);
                }
            }

            @Override
            public void onCancelled(@NonNull DatabaseError error) {
            }
        }));
    }
}
