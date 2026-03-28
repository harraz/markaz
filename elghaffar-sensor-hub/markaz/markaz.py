import paho.mqtt.client as mqtt
import time
import threading
import json
from datetime import datetime
import pygame
import subprocess

# Mapping: source ESP MAC -> list of (target location, target MAC, relay ON time)
TRIGGERS = {
    "244CAB4F1201": [("DAHROOG", "5CCF7F44C358", 60)],  # /ABBAS>DAHROOG
    "4CEBD6ECEB83": [("DAHROOG", "5CCF7F44C358", 60)],  # /SHANKAL>DAHROOG
    #"5CCF7F44C358": [],  # /DAHROOG
    "8CCE4EE74956": [("DAHROOG", "5CCF7F44C358", 60)],  # /MARZOOK>>DAHROOG
}

CAM_BY_SOURCE = {
    #"8CCE4EE74956": "192.168.1.247",  # MARZOOK
    #"4CEBD6ECEB83": "192.168.1.176",    # SHANKAL
    "5CCF7F44C358": "192.168.1.179",    # DAHROOG
}

BROKER = "localhost"

# Dictionary to collect motion events by camera IP
motion_events = {}

def on_motion(client, userdata, msg):
    current_timestamp = (datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

    try:
        payload = msg.payload.decode()
        print(f"{current_timestamp} - [Motion] {msg.topic}: {payload}")
        data = json.loads(payload)
        source_mac = data.get("mac", "")
        cam_ip = CAM_BY_SOURCE.get(source_mac)

        if source_mac not in TRIGGERS:
            print(f"{current_timestamp} - No relay trigger configured for source MAC: {source_mac}")
            return  # Return if no triggers are found

        for target_location, target_mac, delay in TRIGGERS[source_mac]:
            relay_cmd_topic = f"home/{target_location}/{target_mac}/cmd"
            print(f"{current_timestamp} - [Relay] {msg.topic} Sending REL_ON to {relay_cmd_topic}")
            client.publish(relay_cmd_topic, "REL_ON")

            def delayed_off(topic=relay_cmd_topic, delay=delay):
                time.sleep(delay)
                print(f"{current_timestamp} - [Relay] {msg.topic} Sending REL_OFF to {topic}")
                client.publish(topic, "REL_OFF")
            
            threading.Thread(target=delayed_off, daemon=True).start()

            # Play the appropriate sound
            # if source_mac == '8CCE4EE74956':    # MARZOOK
                # play_sound('alarm-no3-14864.mp3')
            # elif source_mac == 'BCDDC2347051':  # DAHROOG
                # play_sound('warning-alarm-loop-1-279206.mp3')
            # elif source_mac == '4CEBD6ECEB83':  # SHANKAL
                # play_sound('warning-alarm-loop-1-279206.mp3')
            # else:
                # play_sound('snd_fragment_retrievewav-14728.mp3')
        
        # Collect motion events for this camera IP
        if cam_ip:
            if cam_ip not in motion_events:
                motion_events[cam_ip] = []  # Initialize the list if it doesn't exist
            motion_events[cam_ip].append(current_timestamp)  # Store the event
        
        #print(TRIGGERS[source_mac][0][1])
        if source_mac:
            target_ghafeer_mac=TRIGGERS[source_mac][0][1]
            remote_cam_ip=CAM_BY_SOURCE.get(target_ghafeer_mac)
            if remote_cam_ip not in motion_events:
                motion_events[remote_cam_ip] = []  # Initialize the list if it doesn't exist
            motion_events[remote_cam_ip].append(current_timestamp)  # Store remote camera ip
            print(f"{current_timestamp} - Calling Ghafeer mac - {target_ghafeer_mac} :Remote ghafeer camera - {remote_cam_ip}")

    except Exception as e:
        print(f"{current_timestamp} - Error handling motion: {e}")

def process_motion_events(current_timestamp):
    
    """Processes collected motion events and starts camera captures."""
    for cam_ip, events in motion_events.items():
        if events:  # If there are motion events for this camera IP
            print(f"{current_timestamp} - Starting capture for camera {cam_ip} with {len(events)} motion events.")
            threading.Thread(target=run_capture, args=(current_timestamp, cam_ip,), daemon=True).start()
            # After starting capture, clear the events to avoid duplicate captures
            motion_events[cam_ip] = []

def play_sound(file_name: str):
    fixed_path = '/home/harraz/Downloads/'
    full_path = fixed_path + file_name

    # Stop the music if already playing
    if pygame.mixer.music.get_busy():
        time.sleep(3)
        pygame.mixer.music.stop()

    pygame.mixer.music.load(full_path)
    pygame.mixer.music.play()

def run_capture(current_timestamp, cam_ip, duration=50, retries=3, wait_time=2):
    script_path = "./capture_stream.sh"
    command = ['bash', script_path, cam_ip, str(duration)]

    for attempt in range(retries):
        try:
            print(f"{datetime.now()} - Attempting to start camera capture (Attempt {attempt + 1})...")
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            print(result)
            #print("Video Output:", result.stdout)
            #print("Script executed successfully.")
            return  # Exit on success

        except subprocess.CalledProcessError as e:
            print(f"Attempt {attempt + 1} failed with return code: {e.returncode}. Error Output: {e.stderr}")
            if attempt < retries - 1:
                print(f"{current_timestamp} - Retrying in {wait_time} seconds...")
                time.sleep(wait_time)  # Wait before retrying

    print(f"{current_timestamp} - All attempts to start camera capture have failed.")

def main():
    
    current_timestamp = (datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

    client = mqtt.Client()
    client.on_message = on_motion

    print(f"Connecting to MQTT broker at {BROKER}...")
    client.connect(BROKER, 1883, 60)

    motion_topic = "home/+/+/motion"
    client.subscribe(motion_topic)
    print(f"Subscribed to: {motion_topic}")
    
    pygame.mixer.init()

    while True:
        client.loop()  # Handle MQTT messages
        process_motion_events(current_timestamp)  # Process and handle motion events

if __name__ == "__main__":
    main()
