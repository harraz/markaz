#!/bin/bash

# Check if the correct number of arguments is provided
if [ "$#" -ne 1 ]; then
  echo "Usage: $0 <base_topic>"
  exit 1
fi

BASE_TOPIC=$1  # Assign the first argument to BASE_TOPIC

# Publish commands with a delay
mosquitto_pub -h 192.168.1.246 -t "$BASE_TOPIC/cmd" -m "STATUS"
sleep 2
mosquitto_pub -h 192.168.1.246 -t "$BASE_TOPIC/cmd" -m "RELAY_MAX_ON_DURATION:6000"
sleep 2
mosquitto_pub -h 192.168.1.246 -t "$BASE_TOPIC/cmd" -m "SKIP_LOCAL_RELAY:0"
sleep 2
mosquitto_pub -h 192.168.1.246 -t "$BASE_TOPIC/cmd" -m "PIR_INTERVAL:50000"
sleep 2
mosquitto_pub -h 192.168.1.246 -t "$BASE_TOPIC/cmd" -m "STATUS"

echo "Setup complete"
