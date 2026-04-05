#include "esp_camera.h"
#include <WiFi.h>
#include <WebServer.h>
#include "esp_http_server.h"
#include <Firebase_ESP_Client.h>

// AI Thinker ESP32-CAM Pinout
#define PWDN_GPIO_NUM 32
#define RESET_GPIO_NUM -1
#define XCLK_GPIO_NUM 0
#define SIOD_GPIO_NUM 26
#define SIOC_GPIO_NUM 27

#define Y9_GPIO_NUM 35
#define Y8_GPIO_NUM 34
#define Y7_GPIO_NUM 39
#define Y6_GPIO_NUM 36
#define Y5_GPIO_NUM 21
#define Y4_GPIO_NUM 19
#define Y3_GPIO_NUM 18
#define Y2_GPIO_NUM 5
#define VSYNC_GPIO_NUM 25
#define HREF_GPIO_NUM 23
#define PCLK_GPIO_NUM 22


const char *ssid = "iPhone";
const char *password = "";

// Firebase (direct ESP -> RTDB, no Python bridge needed)
const char *FIREBASE_API_KEY = " ";
const char *FIREBASE_DB_URL = "https://iot-alarm-app-b4b9c-default-rtdb.europe-west1.firebasedatabase.app";
const char *FIREBASE_LIGHT_PATH = "bots/alphabot/light_on";

WebServer server(80);
String lastStatus = "";
bool cameraReady = false;
httpd_handle_t streamHttpd = NULL;

const int LIGHT_PIN = 4; // ESP32-CAM flash LED

FirebaseData fbdo;
FirebaseAuth auth;
FirebaseConfig firebaseConfig;
bool firebaseReady = false;
unsigned long lastFirebasePollAt = 0;
const unsigned long FIREBASE_POLL_INTERVAL_MS = 250;

bool lightOn = false;

#define PART_BOUNDARY "123456789000000000000987654321"
static const char* STREAM_CONTENT_TYPE = "multipart/x-mixed-replace;boundary=" PART_BOUNDARY;
static const char* STREAM_BOUNDARY = "\r\n--" PART_BOUNDARY "\r\n";
static const char* STREAM_PART = "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

esp_err_t streamHandler(httpd_req_t *req) {
  if (!cameraReady) {
    httpd_resp_set_status(req, "503 Service Unavailable");
    httpd_resp_set_type(req, "text/plain");
    return httpd_resp_send(req, "Camera not ready", HTTPD_RESP_USE_STRLEN);
  }

  httpd_resp_set_type(req, STREAM_CONTENT_TYPE);
  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
  httpd_resp_set_hdr(req, "Cache-Control", "no-store, no-cache, must-revalidate, max-age=0");

  esp_err_t res = ESP_OK;
  char partHeader[64];

  while (res == ESP_OK) {
    camera_fb_t *fb = esp_camera_fb_get();
    if (!fb) {
      res = ESP_FAIL;
      continue;
    }

    size_t headerLen = snprintf(partHeader, sizeof(partHeader), STREAM_PART, fb->len);
    res = httpd_resp_send_chunk(req, STREAM_BOUNDARY, strlen(STREAM_BOUNDARY));
    if (res == ESP_OK) res = httpd_resp_send_chunk(req, partHeader, headerLen);
    if (res == ESP_OK) res = httpd_resp_send_chunk(req, (const char *)fb->buf, fb->len);
    if (res == ESP_OK) res = httpd_resp_send_chunk(req, "\r\n", 2);

    esp_camera_fb_return(fb);
  }

  return res;
}

void setLight(bool on) {
  lightOn = on;
  digitalWrite(LIGHT_PIN, on ? HIGH : LOW);
}

void initFirebase() {
  firebaseConfig.api_key = FIREBASE_API_KEY;
  firebaseConfig.database_url = FIREBASE_DB_URL;

  Firebase.reconnectWiFi(true);

  // Anonymous auth (same pattern as your existing lab1 sketch)
  if (Firebase.signUp(&firebaseConfig, &auth, "", "")) {
    Firebase.begin(&firebaseConfig, &auth);
    firebaseReady = true;
    Serial.println("Firebase ready (anonymous auth)");
  } else {
    firebaseReady = false;
    Serial.print("Firebase signUp failed: ");
    Serial.println(firebaseConfig.signer.signupError.message.c_str());
  }
}

void pollFirebaseControls() {
  if (!firebaseReady || !Firebase.ready()) {
    return;
  }

  unsigned long now = millis();
  if (now - lastFirebasePollAt < FIREBASE_POLL_INTERVAL_MS) {
    return;
  }
  lastFirebasePollAt = now;

  bool remoteLight = lightOn;
  if (Firebase.RTDB.getBool(&fbdo, FIREBASE_LIGHT_PATH)) {
    remoteLight = fbdo.boolData();
  }

  if (remoteLight != lightOn) {
    setLight(remoteLight);
  }
}

void startStreamServer() {
  httpd_config_t config = HTTPD_DEFAULT_CONFIG();
  config.server_port = 81;
  config.ctrl_port = 32769;
  config.max_uri_handlers = 4;

  httpd_uri_t streamUri = {
    .uri = "/stream",
    .method = HTTP_GET,
    .handler = streamHandler,
    .user_ctx = NULL
  };

  if (httpd_start(&streamHttpd, &config) == ESP_OK) {
    httpd_register_uri_handler(streamHttpd, &streamUri);
    Serial.println("MJPEG stream server started on :81/stream");
  } else {
    Serial.println("Failed to start MJPEG stream server");
  }
}

bool initCamera() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;

  config.frame_size = FRAMESIZE_QVGA;
  config.jpeg_quality = 18;
  config.fb_count = 1;

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed: 0x%x\n", err);
    return false;
  }

  return true;
}

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println();
  Serial.println("[boot] ESP32 starting...");
  pinMode(LIGHT_PIN, OUTPUT);
  setLight(false);

  Serial.print("[wifi] Connecting to SSID: ");
  Serial.println(ssid);
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    Serial.print(".");
    delay(500);
  }
  Serial.println();
  Serial.print("[wifi] Connected. IP: ");
  Serial.println(WiFi.localIP());

  WiFi.setSleep(false);
  initFirebase();

  bool cameraOk = initCamera();
  cameraReady = cameraOk;
  Serial.print("Camera status: ");
  Serial.println(cameraOk ? "OK" : "FAILED");
  if (cameraOk) {
    startStreamServer();
  }

  // Control endpoint: receives commands like /cmd?p=...
  server.on("/cmd", [](){
    if(server.hasArg("p")) {
      String p = server.arg("p");
      if (p == "L1") {
        setLight(true);
        if (firebaseReady && Firebase.ready()) {
          Firebase.RTDB.setBool(&fbdo, FIREBASE_LIGHT_PATH, true);
        }
      } else if (p == "L0") {
        setLight(false);
        if (firebaseReady && Firebase.ready()) {
          Firebase.RTDB.setBool(&fbdo, FIREBASE_LIGHT_PATH, false);
        }
      } else {
        Serial.println(p); // Forward all other commands to Arduino (motor/servo)
      }
    }
    server.send(200, "text/plain", "OK");
  });

  server.on("/status", [](){ server.send(200, "text/plain", lastStatus); });

  server.begin();

  Serial.print("Control/status server: http://");
  Serial.println(WiFi.localIP());
  Serial.print("Stream URL: http://");
  Serial.print(WiFi.localIP());
  Serial.println(":81/stream");
}

void loop() {
  server.handleClient();
  if (Serial.available()) {
    lastStatus = Serial.readStringUntil('\n');
  }
  pollFirebaseControls();
}