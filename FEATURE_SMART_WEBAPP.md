# Smart Relay Vehicle Detection Web App Feature

## Overview

This feature adds a **Flask-based web dashboard** to your YOLO11 vehicle detection system with intelligent event logging and 5-second debouncing. 

### Key Features:

✅ **Web Dashboard** - Real-time view of detection events  
✅ **Smart 5-Second Debouncing** - Multiple vehicles within 5s = same row, no duplicates  
✅ **Event Logging** - Tracks detection time, relay signal time, and relay off time  
✅ **WiFi Hotspot** - Auto-enable hotspot on RPi for mobile access  
✅ **REST API** - Full API for integration with external systems  

---

## How It Works

### Detection Flow:

```
┌─────────────────────────────────────────────────────────────┐
│ User clicks "Start Detection" in web app                     │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   ▼
      ┌────────────────────────────┐
      │ YOLO detects Vehicle #1    │
      │ - Record detection_time    │
      │ - Start 5-second timer     │
      │ - Activate relay           │
      │ - Record relay_signal_time │
      └────────────┬───────────────┘
                   │
      ┌────────────▼───────────────────────────────────────┐
      │ Timer Running (5 seconds)                          │
      │                                                     │
      │ ┌─ If Vehicle Detected (within 5s)                │
      │ │  └─ Reset timer, NO new row                     │
      │ │     (same event/session)                        │
      │ │                                                 │
      │ └─ If No New Vehicles (timer expired)             │
      │    └─ Relay OFF                                  │
      │    └─ Event marked COMPLETED                     │
      │    └─ Ready for new detection                    │
      └────────────┬────────────────────────────────────┘
                   │
      ┌────────────▼─────────────────┐
      │ New Vehicle Detected         │
      │ (after 5s cooldown)          │
      │ - New Event ID               │
      │ - New Row in Table           │
      │ - Relay activates again      │
      └──────────────────────────────┘
```

### Web Dashboard Columns:

| Column | Description |
|--------|-------------|
| Event ID | Unique ID for this 5-second detection session |
| Detection Time | When vehicle was first detected |
| Relay Signal Time | When relay was activated |
| Relay Off Time | When relay timer expired |
| Duration (s) | How long relay stayed ON |
| Vehicles | Total vehicle count in this session |
| Status | pending/active/completed |

---

## Installation

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

The new dependencies are:
- `flask>=2.3.0` - Web server
- `flask-cors>=4.0.0` - Enable cross-origin requests

### 2. Run the Application

```bash
python main.py
```

### 3. Access the Dashboard

Open your browser to:
```
http://<your-device-ip>:5000
```

On **Raspberry Pi**:
- A WiFi hotspot named `VehicleDetector` (password: `detection123`) will auto-enable
- Mobile devices can connect to this hotspot
- Open `http://192.168.4.1:5000` on your phone's browser

---

## API Endpoints

### POST `/api/start`
Start vehicle detection and enable hotspot.

**Response:**
```json
{
  "status": "started",
  "message": "Detection started. Hotspot enabled if on RPi."
}
```

### POST `/api/stop`
Stop vehicle detection and disable hotspot.

**Response:**
```json
{
  "status": "stopped",
  "message": "Detection stopped. Hotspot disabled if on RPi."
}
```

### GET `/api/events`
Get all completed detection events and current session.

**Response:**
```json
{
  "events": [
    {
      "event_id": 1,
      "detection_time": "2026-03-27T10:15:30.123456",
      "relay_signal_time": "2026-03-27T10:15:30.200456",
      "relay_off_time": "2026-03-27T10:15:35.200456",
      "vehicle_count": 2,
      "status": "completed",
      "duration_seconds": 5.0
    }
  ],
  "current_event": {
    "event_id": 2,
    "detection_time": "2026-03-27T10:15:36.123456",
    "relay_signal_time": "2026-03-27T10:15:36.200456",
    "relay_off_time": null,
    "vehicle_count": 1,
    "status": "active",
    "duration_seconds": null
  },
  "total_events": 1
}
```

### GET `/api/status`
Get current application status.

**Response:**
```json
{
  "running": true,
  "detection_enabled": true,
  "relay_enabled": true,
  "current_event": {...},
  "timestamp": "2026-03-27T10:15:40.123456"
}
```

### POST `/api/clear-events`
Clear all stored events (for testing).

**Response:**
```json
{
  "status": "cleared"
}
```

---

## Configuration

### Flask Settings (in `webapp.py`)

```python
DEBOUNCE_SECONDS = 5.0  # 5-second timer before creating new row
```

### WiFi Hotspot Settings (in `hotspot.py`)

```python
SSID = "VehicleDetector"      # Network name
PASSWORD = "detection123"     # WiFi password
CHANNEL = "6"                 # WiFi channel (adjust if needed)
```

### Relay Settings (in `main.py`)

```python
RELAY_ACTIVE_SECONDS = 5.0    # Must match DEBOUNCE_SECONDS for consistency
```

---

## Project Structure

```
Vehicle-Detection-and-Counter-using-Yolo11/
│
├── main.py                    # Updated with Flask integration
├── webapp.py                  # NEW: Flask web app + event logging
├── hotspot.py                 # NEW: WiFi hotspot control (RPi)
├── templates/
│   └── dashboard.html         # NEW: Web dashboard UI
├── requirements.txt           # Updated with Flask + flask-cors
│
├── yolo11n.pt                 # YOLO model (unchanged)
├── README.md
└── ...
```

---

## Smart Debouncing Logic

### Why 5-Second Debouncing?

Prevents **duplicate rows** when:
- Multiple vehicles pass through in succession
- Single vehicle detected multiple times per frame
- Noise or multiple bounding boxes for same vehicle

### How It Works:

```python
SENSOR 1 (Vehicle A) → START TIMER
    ↓ (within 5s)
SENSOR 2 (Vehicle B) → RESET TIMER to 5s
    → NO NEW ROW (same session)
    ↓ (within 5s)
SENSOR 3 (Vehicle C) → RESET TIMER to 5s
    → NO NEW ROW (still same session)
    ↓ (5s passes)
TIMER EXPIRES → RELAY OFF → Event Completed
    ↓
SENSOR 4 (Vehicle D) → NEW EVENT → NEW ROW
    → Relay activates again
```

---

## Testing

### Test the Web App Locally

```bash
# In one terminal, run main.py
python main.py

# In another terminal, test API (Windows PowerShell)
Invoke-RestMethod -Uri "http://localhost:5000/api/start" -Method POST
Invoke-RestMethod -Uri "http://localhost:5000/api/events" -Method GET
```

### Test on Raspberry Pi

1. SSH into RPi
2. Run: `python main.py`
3. On your phone, connect to WiFi hotspot "VehicleDetector"
4. Open browser: `http://192.168.4.1:5000`

---

## Troubleshooting

### Flask app won't start
```
Error: Address already in use
Solution: Port 5000 is busy. Change port in main.py:
    flask_app.run(host='0.0.0.0', port=5001, ...)
```

### Hotspot not appearing on RPi
```
Solution: nmcli/NetworkManager may not be configured
1. Install: sudo apt install network-manager
2. Edit /etc/NetworkManager/conf.d/default-wifi-powersave-on.conf
3. Set wifi.powersave = 2
4. Restart: sudo systemctl restart NetworkManager
```

### Web app not accessible from mobile
```
On RPi, disable firewall:
    sudo ufw allow 5000/tcp
    
Or find RPi's IP:
    hostname -I
    
Then access: http://<IP>:5000
```

### Relay not activating
```
Check GPIO pins in main.py:
    RELAY_ON_PIN = 17      # GPIO pin for ON
    RELAY_OFF_PIN = 27     # GPIO pin for OFF

Test GPIO:
    python -c "import RPi.GPIO as GPIO; GPIO.setmode(GPIO.BCM); print('GPIO OK')"
```

---

## Next Steps / Enhancements

- [ ] Add persistent database (SQLite) for event history
- [ ] Email/SMS notifications on detection
- [ ] Adjustable debounce interval via web UI
- [ ] Vehicle type classification (car, truck, motorcycle)
- [ ] Camera stream preview in web dashboard
- [ ] CSV export of events
- [ ] Mobile app (instead of web app)
- [ ] MQTT integration with other systems
- [ ] Configurable WiFi credentials via UI

---

## Files Modified

- `main.py` - Integrated Flask + event logging
- `requirements.txt` - Added Flask dependencies

## Files Created

- `webapp.py` - Flask web server + EventLogger class
- `hotspot.py` - WiFi hotspot control
- `templates/dashboard.html` - Web dashboard UI

---

**Author**: GitHub Copilot  
**Date**: March 27, 2026  
**Feature**: Smart 5-Second Debouncing with Web Dashboard
