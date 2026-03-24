#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#  test_cam.py
#  
#  Copyright 2026  <harraz@raspberrypi>
#  
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#  
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#  
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.
#  
#  

import subprocess

def run_capture(cam_ip, duration=20):
    # Replace 'your_script.sh' with the actual path to your script
    script_path = "./capture_stream.sh" 
    
    # Prepare the command with arguments
    command = ['bash', script_path, cam_ip, str(duration)]

    try:
        # Execute the script and wait for it to complete
        result = subprocess.run(command, capture_output=True, text=True, check=True)

        # If successful, print the output
        print("Script executed successfully.")
        print("Output:", result.stdout)

    except subprocess.CalledProcessError as e:
        # Handle errors during execution
        print("Script failed with return code:", e.returncode)
        print("Error Output:", e.stderr)

def main(args):
    
    run_capture("192.168.1.247")
    
    return 0

if __name__ == '__main__':
    import sys
    sys.exit(main(sys.argv))
