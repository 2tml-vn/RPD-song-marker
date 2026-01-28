#!/usr/bin/env python3
"""
JRPD Auto-Start Launcher
Automatically starts the JRPD server and keeps it running
"""

import subprocess
import sys
import os
import time

def main():
    print("JRPD Auto-Start Launcher")
    print("Starting label_marks_complete.py server...")
    
    # Change to the script directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    
    # Start the server script
    try:
        # Use sys.executable to ensure the same Python interpreter is used
        process = subprocess.Popen([sys.executable, "label_marks_complete.py"])
        
        print("Server started successfully!")
        print("You can now begin marking timestamps in YouTube videos.")
        print("Press Ctrl+C to stop the server.")
        
        # Wait for the process to complete (it shouldn't unless interrupted)
        process.wait()
        
    except KeyboardInterrupt:
        print("\nShutting down server...")
        if process.poll() is None:  # Process is still running
            process.terminate()
            try:
                process.wait(timeout=5)  # Wait up to 5 seconds for graceful shutdown
            except subprocess.TimeoutExpired:
                process.kill()  # Force kill if it doesn't shut down gracefully
        
        print("Server stopped.")
    except Exception as e:
        print(f"Error starting server: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()