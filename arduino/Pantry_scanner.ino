# include "esp_camera.h"
# include <WiFi.h>
#include <HTTPClient.h>

const char* WIFI_SSID ="gigacube-CCBFC3";
const char*WIFI_PASSWORD ="3jLTgj5yg3y32882";
const char*BACKEND_URL = "http://192.168.0.250:5000/decode-label";

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

#define BUTTON_PIN 13
#define LED_PIN 14

bool cameraReady = false;

void blinkLED(int times, int delayMs = 150){
  for(int i=0; i< times; i++){
    digitalWrite(LED_PIN, HIGH);
    delay(delayMs);
    digitalWrite(LED_PIN, LOW);
    delay(delayMs);
  }
}

void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.disconnect(true);
  delay(100);

  Serial.printf("Connecting to Wi-Fi: %s", WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 30) {
    delay(500);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println();
    Serial.print("Wi-Fi connected. IP address: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println();
    Serial.println("Wi-Fi connection failed - will retry before each capture.");
  }
}

void uploadToBackend(camera_fb_t *fb) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("Not connected to Wi-Fi - attempting reconnect...");
    connectWiFi();
    if (WiFi.status() != WL_CONNECTED) {
      Serial.println("Still no Wi-Fi - skipping upload this time.");
      return;
    }
  }

  HTTPClient http;
  http.begin(BACKEND_URL);
  http.addHeader("Content-Type", "image/jpeg");

  Serial.println("Uploading photo to backend...");
  int httpCode = http.POST(fb->buf, fb->len);

  if (httpCode > 0) {
    String response = http.getString();
    Serial.printf("Backend responded (HTTP %d):\n", httpCode);
    Serial.println(response);
  } else {
    Serial.printf("Upload failed: %s\n", http.errorToString(httpCode).c_str());
    Serial.println("Check that app.py is running and BACKEND_URL matches your computer's IP.");
  }

  http.end();
}

bool initCamera(){
  camera_config_t config = {};
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1= Y3_GPIO_NUM;
  config.pin_d2= Y4_GPIO_NUM;
  config.pin_d3= Y5_GPIO_NUM;
  config.pin_d4= Y6_GPIO_NUM;
  config.pin_d5= Y7_GPIO_NUM;
  config.pin_d6= Y8_GPIO_NUM;
  config.pin_d7= Y9_GPIO_NUM;
  config.pin_xclk= XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;

  if (psramFound()){
    config.frame_size = FRAMESIZE_UXGA;
    config.jpeg_quality = 10;
    config.fb_count = 2 ;
  } else{
    config.frame_size = FRAMESIZE_SVGA;
    config.jpeg_quality = 12;
    config.fb_count = 1;
  }

  esp_err_t err = esp_camera_init(&config);
  if(err != ESP_OK){
    Serial.printf("Camera init failed with error 0x%x\n", err);
    return false;
  }
  return true;
}

void captureAndReport(){
  for (int i = 0; i < 2; i++){
    camera_fb_t * stale_fb = esp_camera_fb_get();
    if(stale_fb){
      esp_camera_fb_return(stale_fb);
    }
  }
  camera_fb_t * fb = esp_camera_fb_get();
  if(!fb){
    Serial.println("Capture failed - check wiring/power.");
    blinkLED(5,80);
    return;
  }
  Serial.printf("Captured frame: %u bytes, %ux%u\n", fb->len, fb->width, fb->height);

  digitalWrite(LED_PIN, HIGH);
  uploadToBackend(fb);
  digitalWrite(LED_PIN, LOW);

  esp_camera_fb_return(fb);
  blinkLED(3);
}

void setup() {
  Serial.begin(115200);
  delay(500);

  pinMode(BUTTON_PIN, INPUT_PULLUP);
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

  Serial.println("Initializing camera ...");
  cameraReady = initCamera();

  if(cameraReady){
    Serial.println("Camera ready.");
    blinkLED(2);
  } else{
    Serial.println("Camera init failed - check wiring before continuing.");
  }

  connectWiFi();   
  Serial.println("Press the button to capture and upload.");
}

void loop() {
  static bool lastState = HIGH;
  bool state = digitalRead(BUTTON_PIN);

  if(lastState == HIGH && state ==LOW){
    delay(30);
    if(digitalRead(BUTTON_PIN) == LOW){
      if(cameraReady){
        Serial.println("Button pressed - capturing ...");
        captureAndReport();
      }else {
        Serial.println("Camera not ready, can't capture.");
      }
    }
  }
  lastState = state;
  delay(10);
}
