"""
Vehicle Detection & Counter using YOLO11
=========================================
Optimized for Raspberry Pi 4B (Bookworm OS) with threaded camera capture
for smooth preview. All detected vehicle types (car, bus, truck, motorcycle,
bicycle, train) are labeled as "Vehicle".

Based on architecture from github.com/Asnor14/cpe4bVehicleDetection
"""

import os
import sys
import threading
import time

# Fix for OpenCV Qt/Wayland issues on RPi Bookworm
if os.environ.get("XDG_SESSION_TYPE") == "wayland" and not os.environ.get("QT_QPA_PLATFORM"):
    os.environ["QT_QPA_PLATFORM"] = "xcb"
if not os.environ.get("QT_QPA_FONTDIR") and os.path.isdir("/usr/share/fonts/truetype/dejavu"):
    os.environ["QT_QPA_FONTDIR"] = "/usr/share/fonts/truetype/dejavu"
os.environ['KMP_DUPLICATE_LIB_OK'] = 'TRUE'

import cv2
import numpy as np
from ultralytics import YOLO

try:
    import torch
except ImportError:
    torch = None

# GPIO — only available on Raspberry Pi
try:
    import RPi.GPIO as GPIO
    HAS_GPIO = True
except ImportError:
    GPIO = None
    HAS_GPIO = False

# Web App Integration
from webapp import (
    app as flask_app, 
    log_detection_event, 
    log_relay_signal,
    log_relay_timeout,
    set_app_state
)
from hotspot import enable_hotspot, disable_hotspot

# ============================================================================
# Configuration — tweak these for your setup
# ============================================================================

# Model: Use yolo11n (nano) on RPi for speed. Use yolo11s or yolo11l on desktop.
MODEL_PATH = 'yolo11n.pt'

# Webcam settings
CAM_INDEX = 0                  # 0 = default camera, 1 = second USB camera
FRAME_WIDTH = 640              # Camera capture width
FRAME_HEIGHT = 480             # Camera capture height
TARGET_FPS = 30                # Requested camera FPS

# YOLO inference settings
IMG_SIZE = 512                 # YOLO input image size (512 catches motorcycles better)
DETECT_CONF = 0.15             # Low confidence to catch motorcycles easier
FRAME_SKIP = 1                 # Process every Nth frame (1 = every frame)

# COCO class IDs for vehicles:
#   1=bicycle, 2=car, 3=motorcycle, 5=bus, 6=train, 7=truck
VEHICLE_CLASSES = [1, 2, 3, 5, 6, 7]

# Generic label — all vehicles shown as "Vehicle" instead of individual types
GENERIC_LABEL = 'Vehicle'

# Counting line (relative to frame height, 0.0=top, 1.0=bottom)
LINE_POSITION_RATIO = 0.65    # 65% down the frame
LINE_MARGIN_X = 50             # Pixels from left/right edge

# Output video
SAVE_OUTPUT = False            # Set True to record output (uses more CPU)
OUTPUT_PATH = 'output_webcam.mp4'

# GPIO Relay settings (Raspberry Pi only)
RELAY_ON_PIN = 17              # GPIO pin to trigger relay ON
RELAY_OFF_PIN = 27             # GPIO pin to trigger relay OFF
RELAY_ACTIVE_SECONDS = 5.0    # How long the relay stays ON after detection
RELAY_TRIGGER_PULSE_SECONDS = 0.2  # Duration of the trigger pulse

# Window
WINDOW_NAME = "Vehicle Detection & Counter (Press Q to quit)"

# ============================================================================
# Shared state between threads
# ============================================================================
state_lock = threading.Lock()
last_boxes = []                # List of (x1,y1,x2,y2,confidence)
latest_frame = None
latest_frame_idx = 0
running = True
inference_error = None

# Relay timer state (shared between inference thread and main loop)
relay_lock = threading.Lock()
relay_is_on = False            # Current relay state
last_detection_time = 0.0      # Timestamp of last vehicle detection
relay_timer_remaining = 0.0    # Countdown value for display
detected_count_now = 0         # How many vehicles in current frame

# Smart debouncing: tracks current detection event
current_event_id = None        # Current detection event ID (for 5-second debounce)


# ============================================================================
# CPU optimization for RPi
# ============================================================================
def configure_runtime():
    """Apply CPU-side optimizations for Raspberry Pi."""
    cv2.setUseOptimized(True)
    if hasattr(cv2, "setNumThreads"):
        cv2.setNumThreads(max(1, min(2, os.cpu_count() or 1)))
    if torch is not None:
        thread_count = max(1, min(4, os.cpu_count() or 1))
        torch.set_num_threads(thread_count)
        try:
            torch.set_num_interop_threads(1)
        except RuntimeError:
            pass


# ============================================================================
# GPIO Relay functions (Raspberry Pi only)
# ============================================================================
def set_relay_idle():
    """Set both relay pins to idle (HIGH = inactive for active-low relay)."""
    if not HAS_GPIO:
        return
    GPIO.output(RELAY_ON_PIN, GPIO.HIGH)
    GPIO.output(RELAY_OFF_PIN, GPIO.HIGH)


def initialize_gpio():
    """Set up GPIO pins for relay control. Returns True if successful."""
    if not HAS_GPIO:
        print("[INFO] RPi.GPIO not available — relay control disabled (normal on Windows).")
        return False
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(RELAY_ON_PIN, GPIO.OUT, initial=GPIO.HIGH)
    GPIO.setup(RELAY_OFF_PIN, GPIO.OUT, initial=GPIO.HIGH)
    set_relay_idle()
    print(f"[INFO] GPIO initialized: ON=GPIO{RELAY_ON_PIN}, OFF=GPIO{RELAY_OFF_PIN}")
    return True


def pulse_relay_on():
    """Send a brief LOW pulse on the ON pin to activate the relay."""
    if not HAS_GPIO:
        return
    with relay_lock:
        GPIO.output(RELAY_OFF_PIN, GPIO.HIGH)
        GPIO.output(RELAY_ON_PIN, GPIO.LOW)
    time.sleep(RELAY_TRIGGER_PULSE_SECONDS)
    with relay_lock:
        GPIO.output(RELAY_ON_PIN, GPIO.HIGH)


def pulse_relay_off():
    """Send a brief LOW pulse on the OFF pin to deactivate the relay."""
    if not HAS_GPIO:
        return
    with relay_lock:
        GPIO.output(RELAY_ON_PIN, GPIO.HIGH)
        GPIO.output(RELAY_OFF_PIN, GPIO.LOW)
    time.sleep(RELAY_TRIGGER_PULSE_SECONDS)
    with relay_lock:
        GPIO.output(RELAY_OFF_PIN, GPIO.HIGH)


def activate_relay():
    """Turn relay ON and reset the countdown timer."""
    global relay_is_on, last_detection_time
    with relay_lock:
        last_detection_time = time.time()
        if not relay_is_on:
            relay_is_on = True
            # Pulse ON in a short thread to avoid blocking inference
            threading.Thread(target=pulse_relay_on, daemon=True).start()


def reset_relay_timer():
    """Reset the countdown timer (called when a new vehicle is detected)."""
    global last_detection_time
    with relay_lock:
        last_detection_time = time.time()


def check_relay_timeout():
    """Check if the relay timer has expired. If so, turn relay OFF.
    
    Returns (relay_on: bool, remaining_seconds: float) for display.
    """
    global relay_is_on, relay_timer_remaining
    with relay_lock:
        if not relay_is_on:
            relay_timer_remaining = 0.0
            return False, 0.0

        elapsed = time.time() - last_detection_time
        remaining = max(0.0, RELAY_ACTIVE_SECONDS - elapsed)
        relay_timer_remaining = remaining

        if remaining <= 0:
            relay_is_on = False
            # Pulse OFF in a short thread
            threading.Thread(target=pulse_relay_off, daemon=True).start()
            # Log the relay timeout for web app event completion
            log_relay_timeout()
            return False, 0.0

        return True, remaining


def cleanup_gpio():
    """Release GPIO pins on shutdown."""
    global relay_is_on
    if not HAS_GPIO:
        return
    # Make sure relay is OFF before cleanup
    if relay_is_on:
        pulse_relay_off()
        relay_is_on = False
    with relay_lock:
        set_relay_idle()
        GPIO.cleanup((RELAY_ON_PIN, RELAY_OFF_PIN))
    print("[INFO] GPIO cleaned up.")


# ============================================================================
# Inference worker thread — runs YOLO on frames without blocking the camera
# ============================================================================
def inference_worker(model):
    """Run YOLO inference on the latest frame in a background thread.
    
    This is the key to smooth camera preview: the main thread never waits
    for YOLO to finish. Instead, inference runs in parallel and updates
    shared detection results.
    """
    global last_boxes, running, inference_error, detected_count_now
    processed_idx = -1

    while running:
        # Grab the latest frame
        with state_lock:
            frame_idx = latest_frame_idx
            frame_for_infer = (
                latest_frame.copy()
                if latest_frame is not None and frame_idx != processed_idx
                else None
            )

        if frame_for_infer is None:
            time.sleep(0.002)
            continue

        processed_idx = frame_idx

        # Skip frames for performance
        if frame_idx % FRAME_SKIP != 0:
            continue

        try:
            results = model.predict(
                source=frame_for_infer,
                classes=VEHICLE_CLASSES,
                imgsz=IMG_SIZE,
                conf=DETECT_CONF,
                device='cpu',
                verbose=False,
            )
        except Exception as exc:
            inference_error = str(exc)
            running = False
            break

        current_boxes = []
        if results[0].boxes is not None and len(results[0].boxes) > 0:
            boxes = results[0].boxes.xyxy.cpu()
            confidences = results[0].boxes.conf.cpu().tolist()

            for box, confidence in zip(boxes, confidences):
                x1, y1, x2, y2 = map(int, box)
                current_boxes.append((x1, y1, x2, y2, float(confidence)))

        # Smart Detection Event Logging (Web App Integration):
        #   Vehicle detected → log event (handles 5-second debouncing internally)
        #   Multiple vehicles within 5s → same event (no new row)
        #   After 5s timeout → new event on next detection
        global current_event_id
        if current_boxes:
            # Log detection (intelligently handles debouncing)
            event_id = log_detection_event()
            
            # If this is a NEW event (not same as last one), signal relay
            if event_id != current_event_id:
                current_event_id = event_id
                if not relay_is_on:
                    # First detection in new event → turn relay ON
                    activate_relay()
                    # Log the relay signal for this event
                    log_relay_signal(event_id)
            else:
                # Same event (within 5s debounce window) → just reset timer
                if relay_is_on:
                    reset_relay_timer()
        
        # Update detected count for UI display
        with state_lock:
            detected_count_now = len(current_boxes)

        with state_lock:
            last_boxes = current_boxes


# ============================================================================
# Main — camera capture + display on main thread
# ============================================================================
def main():
    global latest_frame, latest_frame_idx, running

    configure_runtime()

    # Initialize GPIO (no-op on Windows)
    gpio_ready = initialize_gpio()

    # Start Flask Web App in background thread
    print("[INFO] Starting Flask web app on port 5000...")
    flask_thread = threading.Thread(
        target=lambda: flask_app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False),
        daemon=True
    )
    flask_thread.start()
    time.sleep(2)  # Give Flask time to start
    print("[INFO] Web app running at http://<your-ip>:5000")

    # Enable WiFi hotspot (no-op on non-RPi)
    enable_hotspot(ssid="VehicleDetector", password="detection123")
    
    # Update app state to indicate detection is ready
    set_app_state(running=True, detection_enabled=False)

    # Load model
    print(f"[INFO] Loading YOLO model: {MODEL_PATH}")
    model = YOLO(MODEL_PATH)
    print("[INFO] Model loaded successfully.")

    # Open webcam
    print(f"[INFO] Opening webcam (index={CAM_INDEX})...")

    # Use V4L2 backend on Linux (RPi), default on Windows
    if sys.platform.startswith('linux'):
        cap = cv2.VideoCapture(CAM_INDEX, cv2.CAP_V4L2)
    else:
        cap = cv2.VideoCapture(CAM_INDEX)

    if not cap.isOpened():
        print("[ERROR] Could not open webcam. Check your camera connection.")
        sys.exit(1)

    # Request MJPG to reduce USB bandwidth and decode overhead (smooth on RPi)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
    cap.set(cv2.CAP_PROP_FPS, TARGET_FPS)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Minimal buffer = less latency

    # Read actual values (camera may not support requested resolution)
    actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or FRAME_WIDTH
    actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or FRAME_HEIGHT
    fps = int(cap.get(cv2.CAP_PROP_FPS)) or TARGET_FPS

    print(f"[INFO] Webcam: {actual_width}x{actual_height} @ {fps}fps")

    # Calculate counting line position
    line_y = int(actual_height * LINE_POSITION_RATIO)
    line_x_start = LINE_MARGIN_X
    line_x_end = actual_width - LINE_MARGIN_X

    # Video writer (optional)
    out = None
    if SAVE_OUTPUT:
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(OUTPUT_PATH, fourcc, fps, (actual_width, actual_height))
        print(f"[INFO] Recording to: {OUTPUT_PATH}")

    # Vehicle counter state
    vehicle_count = 0
    crossed_ids = set()  # Track which detection zones have crossed the line

    # Start inference thread
    infer_thread = threading.Thread(target=inference_worker, args=(model,), daemon=True)
    infer_thread.start()

    frame_idx = 0
    prev_time = time.time()

    print("[INFO] Starting vehicle detection... Press 'Q' to quit.")

    try:
        while cap.isOpened() and running:
            ret, frame = cap.read()
            if not ret:
                print("[WARN] Failed to grab frame. Retrying...")
                continue

            frame_idx += 1

            # Share frame with inference thread
            with state_lock:
                latest_frame = frame
                latest_frame_idx = frame_idx
                boxes_snapshot = list(last_boxes)

            # --- Draw counting line ---
            cv2.line(frame, (line_x_start, line_y), (line_x_end, line_y), (0, 0, 255), 3)
            cv2.putText(frame, 'Counting Line', (line_x_start, line_y - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)

            # --- Draw detections ---
            for x1, y1, x2, y2, confidence in boxes_snapshot:
                cx = (x1 + x2) // 2
                cy = (y1 + y2) // 2

                # Draw bounding box with generic "Vehicle" label
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(frame, f'{GENERIC_LABEL} {confidence:.2f}',
                            (x1, max(15, y1 - 8)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1)
                cv2.circle(frame, (cx, cy), 4, (0, 0, 255), -1)

                # Count vehicles crossing the line
                # Use bounding box hash as simple identifier (since we use predict, not track)
                box_id = (x1 // 10, y1 // 10, x2 // 10, y2 // 10)
                if cy > line_y and box_id not in crossed_ids:
                    crossed_ids.add(box_id)
                    vehicle_count += 1

            # --- Check relay timer (turn OFF if expired) ---
            is_relay_on, remaining = check_relay_timeout()

            # --- Draw status panel (top-left labels) ---
            label_y = 30

            # Vehicle count
            cv2.putText(frame, f"Vehicles Counted: {vehicle_count}", (10, label_y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 0), 2)
            label_y += 30

            # Detected right now
            with state_lock:
                current_detected = detected_count_now
            cv2.putText(frame, f"Detected Now: {current_detected}", (10, label_y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)
            label_y += 30

            # Relay status
            if is_relay_on:
                relay_status = "ON"
                relay_color = (0, 255, 0)     # Green
            else:
                relay_status = "OFF"
                relay_color = (0, 0, 255)     # Red
            cv2.putText(frame, f"Relay: {relay_status}", (10, label_y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, relay_color, 2)
            label_y += 30

            # Timer countdown (only show when relay is ON)
            if is_relay_on:
                timer_int = int(remaining) + 1  # Show ceiling (5,4,3,2,1)
                timer_int = min(timer_int, int(RELAY_ACTIVE_SECONDS))
                cv2.putText(frame, f"Timer: {timer_int}s", (10, label_y),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 2)
            else:
                cv2.putText(frame, "Timer: --", (10, label_y),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.65, (128, 128, 128), 2)
            label_y += 30

            # --- Display FPS (top-right) ---
            curr_time = time.time()
            fps_display = 1.0 / (curr_time - prev_time) if (curr_time - prev_time) > 0 else 0
            prev_time = curr_time
            cv2.putText(frame, f"FPS: {fps_display:.1f}", (actual_width - 150, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)

            # Save frame
            if out is not None:
                out.write(frame)

            # Display
            cv2.imshow(WINDOW_NAME, frame)

            # Press 'Q' to exit
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q') or key == 27:  # Q or Esc
                print("[INFO] Quitting...")
                break

            # Check for inference errors
            if inference_error:
                print(f"[ERROR] Inference failed: {inference_error}")
                break

    finally:
        running = False
        
        # Update app state
        set_app_state(running=False, detection_enabled=False)

        # Wait for inference thread to finish
        if infer_thread is not None:
            infer_thread.join(timeout=2.0)

        # Release resources
        if cap is not None:
            cap.release()
        if out is not None:
            out.release()
        cv2.destroyAllWindows()

        # Cleanup GPIO
        if gpio_ready:
            cleanup_gpio()
        
        # Disable WiFi hotspot (no-op on non-RPi)
        disable_hotspot()
        
        print("[INFO] Hotspot disabled and cleanup complete.")

    # Print summary
    print()
    print("=" * 50)
    print("  Vehicle Count Summary")
    print("=" * 50)
    print(f"  Total Vehicles Counted: {vehicle_count}")
    print("=" * 50)

    if SAVE_OUTPUT:
        print(f"\n  Output saved: {OUTPUT_PATH}")


if __name__ == '__main__':
    main()
