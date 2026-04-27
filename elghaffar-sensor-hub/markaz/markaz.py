import os
import glob
import paho.mqtt.client as mqtt
import time
import threading
import json
from datetime import datetime
from collections import defaultdict
import pygame
import subprocess

# Load configuration from JSON file
with open('config.json', 'r') as f:
    config = json.load(f)

# Extract configuration variables
BROKER = config['broker']
BROKER_PORT = config['broker_port']
TOPICS = config['topics']
MOTION_THRESHOLD = config['motion_threshold']
COOLDOWN_PERIOD = config['cooldown_period']
CAMERA_DURATION = config['camera_duration']
CAMERA_RETRIES = config['camera_retries']
CAMERA_WAIT_TIME = config['camera_wait_time']
SOUND_ENABLED = config['sound_enabled']
SOUND_PATH = config['sound_path']
LOG_LEVEL = config['log_level']
CAPTURE_SCRIPT = config.get('camera_capture_script', './capture_stream.sh')
SOUND_FILES = config.get('sound_files', {})

# Mapping: source ESP MAC -> list of (target location, target MAC, relay ON time)
TRIGGERS = config['triggers']

CAM_BY_SOURCE = config['cam_by_source']

# Video cleanup configuration
VIDEO_CLEANUP = config.get('video_cleanup', {})
VIDEO_SOURCE_PATTERN = VIDEO_CLEANUP.get('source_pattern', '/home/harraz/Videos/*.avi')
VIDEO_DEST_DIR = VIDEO_CLEANUP.get('dest_dir', '~/network-share/disk1/share/motion_videos/')
VIDEO_INTERVAL_HOURS = VIDEO_CLEANUP.get('interval_hours', 6)
VIDEO_LOG_FILE = os.path.expanduser(VIDEO_CLEANUP.get('log_file', '~/video_cleanup_rsync.log'))

motion_count = defaultdict(lambda: {'count': 0, 'last_time': 0.0})

# Track the current REL_OFF timer version per relay command topic. This lets
# new motion extend the relay window without an older timer turning it off early.
relay_off_timer_versions = defaultdict(int)
relay_off_timer_lock = threading.Lock()

# Dictionary to collect motion events by camera IP
motion_events = {}
motion_events_lock = threading.Lock()

# Track currently capturing cameras to avoid duplicate concurrent captures
active_captures = set()
active_captures_lock = threading.Lock()

# Lock for pygame mixer operations (not thread-safe)
sound_lock = threading.Lock()

def log_markaz(message: str):
    print(f"[markaz] {message}")

def on_message(client, userdata, msg):
    current_timestamp = (datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

    try:
        payload = msg.payload.decode()
        log_markaz(f"{current_timestamp} - [Message] {msg.topic}: {payload}")

        if msg.topic.endswith('/motion'):
            # Handle motion events
            handle_motion(client, msg, payload, current_timestamp)
        elif msg.topic.endswith('/status'):
            # Handle status events
            handle_status(msg, payload, current_timestamp)
        else:
            # Handle other topics if needed
            log_markaz(f"{current_timestamp} - [Unknown] Unhandled topic: {msg.topic}")

    except Exception as e:
        log_markaz(f"{current_timestamp} - Error handling message: {e}")

def handle_motion(client, msg, payload, current_timestamp):
    data = json.loads(payload)
    source_mac = data.get("mac", "")
    cam_ip = CAM_BY_SOURCE.get(source_mac)
    current_time = time.time()  # Get the current time in seconds

    if source_mac not in TRIGGERS:
        log_markaz(f"{current_timestamp} - No relay trigger configured for source MAC: {source_mac}")
        return  # Return if no triggers are found

    # Throttle logic
    if motion_count[source_mac]['last_time'] == 0:
        motion_count[source_mac]['last_time'] = current_time

    # Check if the cooldown period has passed
    if current_time - motion_count[source_mac]['last_time'] < COOLDOWN_PERIOD:
        motion_count[source_mac]['count'] += 1
        if motion_count[source_mac]['count'] > MOTION_THRESHOLD:
            log_markaz(f"{current_timestamp} - [Throttled] Motion from {source_mac} ignored due to cooldown.")
            return  # Ignore this motion event
    else:
        # Reset count and last_time if cooldown period has passed
        motion_count[source_mac]['count'] = 1
        motion_count[source_mac]['last_time'] = current_time

    for target_location, target_mac, delay in TRIGGERS[source_mac]:
        relay_cmd_topic = f"home/{target_location}/{target_mac}/cmd"
        log_markaz(f"{current_timestamp} - [Relay] {msg.topic} Sending REL_ON to {relay_cmd_topic}")
        client.publish(relay_cmd_topic, "REL_ON")

        relay_off_timer_lock.acquire()
        try:
            relay_off_timer_versions[relay_cmd_topic] += 1
            off_timer_version = relay_off_timer_versions[relay_cmd_topic]
        finally:
            relay_off_timer_lock.release()

        def delayed_off(topic=relay_cmd_topic, motion_topic=msg.topic, timer_version=off_timer_version):
            time.sleep(delay)

            relay_off_timer_lock.acquire()
            try:
                if relay_off_timer_versions[topic] != timer_version:
                    off_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    log_markaz(f"{off_timestamp} - [Relay] {motion_topic} Skipping stale REL_OFF to {topic}")
                    return
            finally:
                relay_off_timer_lock.release()

            off_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            log_markaz(f"{off_timestamp} - [Relay] {motion_topic} Sending REL_OFF to {topic}")
            client.publish(topic, "REL_OFF")

        threading.Thread(target=delayed_off, daemon=True).start()

        # Play the appropriate sound (if enabled)
        if SOUND_ENABLED:
            sound_file = SOUND_FILES.get(source_mac, SOUND_FILES.get('default'))
            if sound_file:
                threading.Thread(target=play_sound, args=(sound_file,), daemon=True).start()
    
    # Collect motion events for this camera IP
    with motion_events_lock:
        if cam_ip:
            motion_events.setdefault(cam_ip, []).append(current_timestamp)

        #print(TRIGGERS[source_mac][0][1])
        if source_mac:
            target_ghafeer_mac = TRIGGERS[source_mac][0][1]
            remote_cam_ip = CAM_BY_SOURCE.get(target_ghafeer_mac)
            if remote_cam_ip:
                motion_events.setdefault(remote_cam_ip, []).append(current_timestamp)
            log_markaz(f"{current_timestamp} - Calling Ghafeer mac - {target_ghafeer_mac} :Remote ghafeer camera - {remote_cam_ip}")

def handle_status(msg, payload, current_timestamp):
    # For status topics, just log the payload
    log_markaz(f"{current_timestamp} - [Status] {msg.topic}: {payload}")
    # You can add more logic here, e.g., store status in a dict or trigger actions

def process_motion_events():
    """Processes collected motion events and starts camera captures."""
    with motion_events_lock:
        for cam_ip, events in list(motion_events.items()):
            if not events:
                continue

            current_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            with active_captures_lock:
                if cam_ip in active_captures:
                    log_markaz(f"{current_timestamp} - Capture already running for {cam_ip}, skipping")
                    continue
                active_captures.add(cam_ip)

            log_markaz(f"{current_timestamp} - Starting capture for camera {cam_ip} with {len(events)} motion events.")
            threading.Thread(target=run_capture, args=(cam_ip,), daemon=True).start()
            # After queueing capture, clear stored events
            motion_events[cam_ip] = []

def play_sound(file_name: str):
    full_path = os.path.join(SOUND_PATH, file_name)

    if not os.path.isfile(full_path):
        log_markaz(f"Sound file not found: {full_path}. Skipping sound playback.")
        return

    try:
        with sound_lock:
            # Stop the music if already playing
            if pygame.mixer.music.get_busy():
                time.sleep(1)
                pygame.mixer.music.stop()

            pygame.mixer.music.load(full_path)
            pygame.mixer.music.play()
    except Exception as e:
        log_markaz(f"Error playing sound {full_path}: {e}. Continuing without crash.")


def cleanup_videos():
    source_pattern = VIDEO_SOURCE_PATTERN
    dest_dir = os.path.expanduser(VIDEO_DEST_DIR)
    # subprocess.run([...]) does not expand shell globs like "*.avi", so
    # resolve the configured pattern to concrete file paths before calling rsync.
    source_files = sorted(glob.glob(source_pattern))

    log_markaz(f"{datetime.now()} - Starting video cleanup...")

    try:
        if not source_files:
            log_markaz(f"{datetime.now()} - No video files matched {source_pattern}. Skipping cleanup.")
            return

        # Rsync the files
        log_markaz(f"{datetime.now()} - Syncing files to {dest_dir}...")
        with open(VIDEO_LOG_FILE, 'a', encoding='utf-8') as rsync_log:
            rsync_log.write(f"{datetime.now()} - Starting rsync to {dest_dir}\n")
            rsync_log.flush()
            subprocess.run(
                ['rsync', '-av', '--no-perms', '--no-times', *source_files, dest_dir],
                check=True,
                stdout=rsync_log,
                stderr=rsync_log,
                # Run rsync in its own session so it is less likely to be interrupted
                # by a SIGHUP when the parent process loses its controlling terminal.
                start_new_session=True,
            )
        log_markaz(f"{datetime.now()} - Rsync completed successfully.")

        # Remove local files
        log_markaz(f"{datetime.now()} - Removing local files...")
        # Delete the exact files that were synced instead of passing the glob
        # pattern to an external rm command.
        for video_file in source_files:
            os.remove(video_file)
        log_markaz(f"{datetime.now()} - Video cleanup completed successfully.")

    except subprocess.CalledProcessError as e:
        log_markaz(f"{datetime.now()} - Error during video cleanup: Command '{e.cmd}' failed with return code {e.returncode}. Stderr: {e.stderr}")
    except Exception as e:
        log_markaz(f"{datetime.now()} - Unexpected error during video cleanup: {e}")


def cleanup_loop():
    while True:
        try:
            time.sleep(VIDEO_INTERVAL_HOURS * 3600)  # Sleep for configured hours
            cleanup_videos()
        except Exception as e:
            log_markaz(f"{datetime.now()} - Error in cleanup loop: {e}. Continuing...")


def run_capture(cam_ip, duration=CAMERA_DURATION, retries=CAMERA_RETRIES, wait_time=CAMERA_WAIT_TIME):
    try:
        script_path = CAPTURE_SCRIPT
        command = ['bash', script_path, cam_ip, str(duration)]

        for attempt in range(retries):
            try:
                log_markaz(f"{datetime.now()} - Attempting to start camera capture for {cam_ip} (Attempt {attempt + 1})...")
                result = subprocess.run(command, capture_output=True, text=True, check=True)
                log_markaz(str(result))
                #print("Video Output:", result.stdout)
                #print("Script executed successfully.")
                return  # Exit on success

            except subprocess.CalledProcessError as e:
                log_markaz(f"Attempt {attempt + 1} failed with return code: {e.returncode}. Error Output: {e.stderr}")
                if attempt < retries - 1:
                    log_markaz(f"{datetime.now()} - Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)  # Wait before retrying

        log_markaz(f"{datetime.now()} - All attempts to start camera capture for {cam_ip} have failed.")

    finally:
        with active_captures_lock:
            active_captures.discard(cam_ip)


def main():
    client = mqtt.Client()
    client.on_message = on_message

    log_markaz(f"Connecting to MQTT broker at {BROKER}:{BROKER_PORT}...")
    client.connect(BROKER, BROKER_PORT, 60)

    for topic in TOPICS:
        client.subscribe(topic)
        log_markaz(f"Subscribed to: {topic}")
    
    if SOUND_ENABLED:
        pygame.mixer.init()

    # Keep cleanup on a non-daemon thread so the process does not tear it down
    # in the middle of a long-running rsync.
    threading.Thread(target=cleanup_loop, daemon=False).start()

    while True:
        client.loop()  # Handle MQTT messages
        process_motion_events()  # Process and handle motion events

if __name__ == "__main__":
    main()
