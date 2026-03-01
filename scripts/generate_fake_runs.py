#!/usr/bin/env python3
"""
Generate fake test runs to populate dashboard data.
Usage: python3 scripts/generate_fake_runs.py
"""

import json
import random
import time
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
RUNS_DIR = BASE_DIR / "runs"

ERRORS = [
    "TimeoutError: waiting for selector \"button[type='submit']\"",
    "AssertionError: expect(received).toBe(expected)\nExpected: \"Welcome\"\nReceived: \"Login\"",
    "Error: Target closed. checks if the browser is closed",
    "TimeoutError: page.goto: Timeout 30000ms exceeded.",
    "ReferenceError: someVariable is not defined",
    "Error: Network violation blocked request to https://analytics.google.com"
]

def generate_runs(count=20):
    print(f"🚀 Generating {count} fake runs...")
    RUNS_DIR.mkdir(exist_ok=True)
    
    end_date = datetime.now()
    start_date = end_date - timedelta(days=7)
    
    for i in range(count):
        # Random date in last 7 days
        random_seconds = random.randint(0, int((end_date - start_date).total_seconds()))
        run_date = start_date + timedelta(seconds=random_seconds)
        
        run_id = run_date.strftime("%Y-%m-%d_%H-%M-%S")
        run_dir = RUNS_DIR / run_id
        run_dir.mkdir(exist_ok=True)
        
        # 80% pass rate
        passed = random.random() < 0.8
        
        steps = []
        duration = random.uniform(5.0, 45.0)
        
        if passed:
            final_state = "passed"
            steps = [
                {"action": "GOTO", "description": "Navigate to homepage", "result": "success"},
                {"action": "CLICK", "description": "Click login", "result": "success"},
                {"action": "ASSERT", "description": "Check welcome message", "result": "success"}
            ]
        else:
            final_state = "failed"
            error_msg = random.choice(ERRORS)
            steps = [
                {"action": "GOTO", "description": "Navigate to homepage", "result": "success"},
                {"action": "CLICK", "description": "Click login", "result": "failed", "error": error_msg}
            ]
            duration = random.uniform(1.0, 10.0) # Fail faster typically

        run_data = {
            "testName": f"Test Scenario {random.randint(1, 5)}",
            "finalState": final_state,
            "duration": round(duration, 2),
            "steps": steps,
            "browser": "chromium"
        }
        
        (run_dir / "run.json").write_text(json.dumps(run_data, indent=2))
        
        # Also touch the directory to set modification time
        # This helps backend sorting if it relies on mtime
        timestamp = run_date.timestamp()
        try:
            import os
            os.utime(run_dir, (timestamp, timestamp))
        except:
            pass

    print(f"✅ Generated {count} runs in {RUNS_DIR}")

if __name__ == "__main__":
    generate_runs()
