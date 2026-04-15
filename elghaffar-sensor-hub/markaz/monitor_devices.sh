#!/bin/bash

# List of IPs to monitor
IPS=("192.168.1.151" "192.168.1.204" "192.168.1.188" "192.168.1.179" 
"192.168.1.207" "192.168.1.181")

RED='\033[41m'
GREEN='\033[42m'
NC='\033[0m'

tput civis
trap "tput cnorm; exit" SIGINT

clear
echo "Ping Monitor (Ctrl+C to exit):"

while true; do
    row=2
    for ip in "${IPS[@]}"; do
        # Ping the IP
        if ping -c 1 -W 1 $ip &> /dev/null; then
            tput cup $row 0
            echo -ne "${GREEN}   ${NC} $ip - UP"
        else
            tput cup $row 0
            echo -ne "${RED}   ${NC} $ip - DOWN"
        fi

        # Fetch MAC address
        mac=$(ip neigh | grep "$ip" | awk '{print $5}')
        
        if [ -n "$mac" ]; then
            echo -ne " - MAC: $mac"
        else
            echo -ne " - MAC: Unknown"
        fi

        echo
        ((row++))
    done
    sleep 2
done
