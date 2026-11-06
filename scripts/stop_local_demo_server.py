"""Safe Shutdown Script for Local Demo Vite Server."""

import subprocess
import sys

def stop_demo_server():
    print("Stopping local demo Vite dev server on port 5173...")
    try:
        # On Windows, find PID using netstat and kill
        res = subprocess.run(
            'netstat -ano | findstr :5173',
            shell=True,
            capture_output=True,
            text=True
        )
        pids = set()
        for line in res.stdout.strip().splitlines():
            parts = line.split()
            if len(parts) >= 5 and "LISTENING" in parts:
                pids.add(parts[-1])
        
        if pids:
            for pid in pids:
                subprocess.run(f"taskkill /PID {pid} /F", shell=True, capture_output=True)
                print(f"Terminated process {pid} on port 5173.")
            print("Dev server successfully stopped.")
        else:
            print("No active server process found on port 5173.")
    except Exception as e:
        print(f"Error stopping server: {e}")

if __name__ == "__main__":
    stop_demo_server()

