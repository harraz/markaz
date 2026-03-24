import os
import json
import time
import signal
import threading
import subprocess
from datetime import datetime
from urllib.request import urlopen
from urllib.error import URLError, HTTPError
# -----------------------------
# CONFIG
# -----------------------------
BROKER = "localhost"
RECORD_SCRIPT = "./capture_stream.sh"  # <-- update path
CAM_STREAM_PORT = 81                          # ESP32-CAM CameraWebServer stream port
DEFAULT_RECORD_SECONDS = 10

# Publish topics:
#   home/cam/<cam_ip>/status  : STARTED | DONE | ERROR | BUSY | STOPPED
#   home/cam/<cam_ip>/result  : JSON payload with details


# -----------------------------
# GLOBALS (locks + shutdown)
# -----------------------------
cam_locks = {}                 # cam_ip -> threading.Lock
_cam_locks_guard = threading.Lock()

stop_event = threading.Event() # set on shutdown

_active_procs = {}             # cam_ip -> subprocess.Popen
_active_procs_guard = threading.Lock()

_active_threads = set()
_active_threads_guard = threading.Lock()


# -----------------------------
# LOCK MANAGEMENT
# -----------------------------
def get_lock(cam_ip: str) -> threading.Lock:
    """One lock per camera IP (prevents overlapping recordings per camera)."""
    with _cam_locks_guard:
        if cam_ip not in cam_locks:
            cam_locks[cam_ip] = threading.Lock()
        return cam_locks[cam_ip]


# -----------------------------
# MQTT PUBLISH HELPERS
# -----------------------------
def publish_cam_status(client, cam_ip: str, status: str):
    client.publish(f"home/cam/{cam_ip}/status", status)

def publish_cam_result(client, cam_ip: str, payload: dict):
    client.publish(f"home/cam/{cam_ip}/result", json.dumps(payload))


# -----------------------------
# PROCESS TRACKING (for shutdown)
# -----------------------------
def _register_proc(cam_ip: str, proc: subprocess.Popen):
    with _active_procs_guard:
        _active_procs[cam_ip] = proc

def _unregister_proc(cam_ip: str):
    with _active_procs_guard:
        _active_procs.pop(cam_ip, None)

def _terminate_all_recordings():
    """Called during shutdown to stop any running ffmpeg recordings."""
    with _active_procs_guard:
        procs = list(_active_procs.items())

    for cam_ip, proc in procs:
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
        except Exception:
            pass
        finally:
            _unregister_proc(cam_ip)


# -----------------------------
# RECORDING (safe wrapper + bash invocation)
# -----------------------------
def record_cam_safe(client, cam_ip: str, seconds: int = DEFAULT_RECORD_SECONDS):
    """
    Runs the bash script safely:
      record_cam.sh <CAM_IP> <DUR>

    - Non-blocking: runs in a worker thread.
    - One recording per camera at a time (lock).
    - Publishes STARTED/DONE/ERROR/BUSY to MQTT.
    - Graceful shutdown: terminates ffmpeg process if stopping.
    """
    if stop_event.is_set():
        publish_cam_status(client, cam_ip, "STOPPED")
        return

    lock = get_lock(cam_ip)
    if not lock.acquire(blocking=False):
        publish_cam_status(client, cam_ip, "BUSY")
        publish_cam_result(client, cam_ip, {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "cam_ip": cam_ip,
            "seconds": seconds,
            "status": "BUSY"
        })
        return

    def worker():
        try:
            
            publish_cam_status(client, cam_ip, "WAKING")

            if not wait_for_camera(client, cam_ip, timeout_sec=16):
                publish_cam_status(client, cam_ip, "ERROR0")
                publish_cam_result(client, cam_ip, {
                    "error0": "camera_not_reachable"
                })
                return

            publish_cam_status(client, cam_ip, "READY")

            publish_cam_status(client, cam_ip, "STARTED")
            publish_cam_result(client, cam_ip, {
                "ts": datetime.now().isoformat(timespec="seconds"),
                "cam_ip": cam_ip,
                "seconds": seconds,
                "status": "STARTED"
            })

            if not os.path.exists(RECORD_SCRIPT):
                raise RuntimeError(f"Script not found: {RECORD_SCRIPT}")

            # Use Popen so we can terminate it on shutdown
            proc = subprocess.Popen(
                [RECORD_SCRIPT, cam_ip, str(seconds)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            _register_proc(cam_ip, proc)

            # Wait for completion, but allow early exit if stop_event is set
            while proc.poll() is None:
                if stop_event.is_set():
                    # Graceful stop
                    try:
                        proc.terminate()
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    break
                time.sleep(0.1)

            stdout, stderr = proc.communicate(timeout=1) if proc.stdout is not None else ("", "")
            stdout = (stdout or "").strip()
            stderr = (stderr or "").strip()

            if stop_event.is_set():
                publish_cam_status(client, cam_ip, "STOPPED")
                publish_cam_result(client, cam_ip, {
                    "ts": datetime.now().isoformat(timespec="seconds"),
                    "cam_ip": cam_ip,
                    "seconds": seconds,
                    "status": "STOPPED",
                    "stdout": stdout[-500:],
                    "stderr": stderr[-500:],
                })
                return

            if proc.returncode != 0:
                publish_cam_status(client, cam_ip, "ERROR1")
                publish_cam_result(client, cam_ip, {
                    "ts": datetime.now().isoformat(timespec="seconds"),
                    "cam_ip": cam_ip,
                    "seconds": seconds,
                    "status": "ERROR1",
                    "error": "record_script_failed",
                    "returncode": proc.returncode,
                    "stdout": stdout[-800:],
                    "stderr": stderr[-800:],
                })
                return

            # Parse saved file path from script output:
            saved_file = stdout
            if saved_file.lower().startswith("saved:"):
                saved_file = saved_file.split(":", 1)[1].strip()

            publish_cam_status(client, cam_ip, "DONE")
            publish_cam_result(client, cam_ip, {
                "ts": datetime.now().isoformat(timespec="seconds"),
                "cam_ip": cam_ip,
                "seconds": seconds,
                "status": "DONE",
                "file": saved_file,
                "stdout": stdout[-500:],
                "stderr": stderr[-500:],
            })

        except Exception as e:
            publish_cam_status(client, cam_ip, "ERROR2")
            print(str(e))
            publish_cam_result(client, cam_ip, {
                "ts": datetime.now().isoformat(timespec="seconds"),
                "cam_ip": cam_ip,
                "seconds": seconds,
                "status": "ERROR2",
                "error": str(e),
            })
        finally:
            _unregister_proc(cam_ip)
            lock.release()
            with _active_threads_guard:
                _active_threads.discard(threading.current_thread())

    t = threading.Thread(target=worker, daemon=False)
    with _active_threads_guard:
        _active_threads.add(t)
    t.start()


# -----------------------------
# GRACEFUL SHUTDOWN HANDLING
# -----------------------------
def setup_graceful_shutdown(mqtt_client):
    """
    Installs SIGINT/SIGTERM handlers:
      - set stop_event
      - terminate any active recordings
      - stop MQTT loop and disconnect
      - join worker threads briefly
    """
    def _shutdown(signum, frame):
        if stop_event.is_set():
            return  # already shutting down

        stop_event.set()

        # Stop ongoing recordings (ffmpeg)
        _terminate_all_recordings()

        # Stop MQTT loop
        try:
            mqtt_client.loop_stop()
        except Exception:
            pass

        try:
            mqtt_client.disconnect()
        except Exception:
            pass

        # Join worker threads briefly
        with _active_threads_guard:
            threads = list(_active_threads)
        for th in threads:
            try:
                th.join(timeout=2)
            except Exception:
                pass

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)


# -----------------------------
# OPTIONAL: STREAM PROBE (port 81) - useful for debugging
# -----------------------------
def stream_url(cam_ip: str) -> str:
    return f"http://{cam_ip}:{CAM_STREAM_PORT}/stream"

def wait_for_camera(client,
                    cam_ip: str,
                    timeout_sec: float = 6.0,
                    interval_sec: float = 0.5) -> bool:
    """
    Returns True when ESP32-CAM /capture endpoint responds with HTTP 200.
    Uses only Python standard library.
    """
    url = f"http://{cam_ip}/capture"
    deadline = time.time() + timeout_sec

    while time.time() < deadline:
        try:
            with urlopen(url, timeout=1) as resp:
                if resp.status == 200:
                    publish_cam_status(client, cam_ip, "CAMOnline")
                    return True
        except (URLError, HTTPError):
            pass
        time.sleep(interval_sec)

    return False


# -----------------------------
# HOW YOU CALL IT FROM on_motion
# -----------------------------
# Example:
# cam_ip = CAM_BY_SOURCE.get(source_mac)
# if cam_ip:
#     record_cam_safe(client, cam_ip, seconds=10)
#
# Make sure your record_cam.sh ends with:
#   echo "$OUT"
