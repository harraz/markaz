#!/bin/bash

# Check if the correct number of arguments is provided
if [ "$#" -ne 1 ]; then
  echo "Usage: $0 <base_topic>"
  exit 1
fi

BASE_TOPIC=$1  # Assign the first argument to BASE_TOPIC

# Function to publish a command and receive status
publish_command_and_receive_status() {
  local command=$1
  
  # Publish the command
  mosquitto_pub -h 192.168.1.246 -t "$BASE_TOPIC/cmd" -m "$command"
  echo "Published command: $command"
  
  # Wait for a moment to allow the status to be sent
  sleep 2
  
  # Subscribe to the status topic for a short time
  # This assumes the status topic is in the format <base_topic>/status
  STATUS=$(mosquitto_sub -h 192.168.1.246 -t "$BASE_TOPIC/status" -C 5 -W 1)
  
  # Print the received status
  echo "Received status: $STATUS"
}

# Publish commands and receive status
publish_command_and_receive_status "STATUS"
publish_command_and_receive_status "RELAY_MAX_ON_DURATION:6000"
publish_command_and_receive_status "SKIP_LOCAL_RELAY:0"
publish_command_and_receive_status "PIR_INTERVAL:6000"
publish_command_and_receive_status "STATUS"

echo "Setup complete."
