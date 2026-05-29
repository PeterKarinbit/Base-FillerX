import subprocess
import sys
import time
import os

print("[FillerX] Launching unified production workflow...")

# Start Searcher Bot
print("[FillerX] Starting Searcher...")
searcher = subprocess.Popen([sys.executable, "searcher.py"])

print("[FillerX] Starting Telegram Bot...")
tg_bot = subprocess.Popen([sys.executable, "tg_bot.py"])

try:
    while True:
        # Monitor processes. If one crashes, restart it.
        if searcher.poll() is not None:
            print("[WARNING] Searcher exited. Restarting...")
            searcher = subprocess.Popen([sys.executable, "searcher.py"], env=searcher_env)
        
        if tg_bot.poll() is not None:
            print("[WARNING] Telegram Bot exited. Restarting...")
            tg_bot = subprocess.Popen([sys.executable, "tg_bot.py"])
            
        time.sleep(5)
except KeyboardInterrupt:
    print("[FillerX] Shutting down both services...")
    searcher.terminate()
    tg_bot.terminate()
