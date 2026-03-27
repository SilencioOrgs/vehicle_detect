"""
WiFi Hotspot Control for Raspberry Pi
======================================
Manages WiFi hotspot enabling/disabling using nmcli.
Safe to use on Windows (no-op).
"""

import subprocess
import sys
import os


def is_raspberry_pi():
    """Check if running on Raspberry Pi."""
    return sys.platform.startswith('linux') and os.path.exists('/sys/firmware/devicetree/base/model')


def enable_hotspot(ssid="VehicleDetector", password="detection123"):
    """Enable WiFi hotspot on Raspberry Pi.
    
    Args:
        ssid: Network name
        password: WiFi password
    
    Returns:
        bool: True if successful or not on RPi
    """
    if not is_raspberry_pi():
        print("[INFO] Not on RPi - hotspot control skipped.")
        return True
    
    try:
        # Check if nmcli is available
        subprocess.run(['which', 'nmcli'], check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("[WARN] nmcli not found. Install NetworkManager or use hostapd.")
        return False
    
    try:
        # Create hotspot connection
        cmd = [
            'nmcli', 'device', 'wifi', 'hotspot',
            'ifname', 'wlan0',
            'ssid', ssid,
            'password', password,
            'channel', '6'
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            print(f"[INFO] Hotspot enabled: {ssid}")
            return True
        else:
            print(f"[WARN] Hotspot enable failed: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"[ERROR] Hotspot error: {e}")
        return False


def disable_hotspot():
    """Disable WiFi hotspot on Raspberry Pi.
    
    Returns:
        bool: True if successful or not on RPi
    """
    if not is_raspberry_pi():
        print("[INFO] Not on RPi - hotspot control skipped.")
        return True
    
    try:
        # Kill hotspot
        cmd = ['nmcli', 'device', 'wifi', 'hotspot', 'off']
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            print("[INFO] Hotspot disabled")
            return True
        else:
            print(f"[WARN] Hotspot disable failed: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"[ERROR] Hotspot disable error: {e}")
        return False


def get_hotspot_status():
    """Get current hotspot status.
    
    Returns:
        dict: {'active': bool, 'ssid': str or None}
    """
    if not is_raspberry_pi():
        return {'active': False, 'ssid': None}
    
    try:
        # Check if there's an active hotspot
        result = subprocess.run(
            ['nmcli', 'device', 'show'],
            capture_output=True, text=True
        )
        
        if 'Hotspot' in result.stdout:
            # Try to extract SSID
            for line in result.stdout.split('\n'):
                if 'SSID' in line:
                    ssid = line.split(':', 1)[1].strip()
                    return {'active': True, 'ssid': ssid}
            
            return {'active': True, 'ssid': 'Unknown'}
        
        return {'active': False, 'ssid': None}
        
    except Exception as e:
        print(f"[WARN] Could not check hotspot status: {e}")
        return {'active': False, 'ssid': None}


if __name__ == '__main__':
    # Test script
    print("Testing hotspot control...")
    print(f"Is RPi: {is_raspberry_pi()}")
    print(f"Status: {get_hotspot_status()}")
    
    if sys.argv[1:]:
        if sys.argv[1] == 'enable':
            enable_hotspot()
        elif sys.argv[1] == 'disable':
            disable_hotspot()
        elif sys.argv[1] == 'status':
            print(get_hotspot_status())
