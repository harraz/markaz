import os
import glob
import paho.mqtt.client as mqtt
import time
import threading
import json
from datetime import datetime
from collections import defaultdict
import subprocess

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
CAMERA_START_DELAY = config.get('camera_start_delay', 0)
SOUND_ENABLED = config['sound_enabled']
SOUND_PATH = config['sound_path']
LOG_LEVEL = config['log_level']
CAPTURE_SCRIPT = config.get('camera_capture_script', './capture_stream.sh')
CAMERA_OUTPUT_DIR = config.get('camera_output_dir')
SOUND_FILES = config.get('sound_files', {})
CAM_BY_SOURCE = config.get('cam_by_source', {})


print(CAM_BY_SOURCE.get('E8F60A16E85C')) 
print(CAMERA_OUTPUT_DIR)
