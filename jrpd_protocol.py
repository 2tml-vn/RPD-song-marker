"""
JRPD protocol handler - invoked by Windows when a jrpd:// URL is opened.

Registered by setup_protocol.bat under HKCU\\Software\\Classes\\jrpd:
    <python.exe> D:\\rpd\\jrpd_protocol.py "jrpd://<video_id>"

Behavior:
- Extracts the video/session ID from the URL.
- Refuses (with an explanatory message) when something is already listening
  on the pipeline port (5000) - only one session can run at a time.
- Otherwise runs `python label_marks_complete.py <id>` in THIS console:
  the window opened for the handler becomes the pipeline window, so the
  experience matches running it from cmd (output visible, window stays open
  until Enter is pressed after the session ends).

Set JRPD_PROTOCOL_DRY_RUN=1 to print the command instead of launching it.
"""
import os
import re
import socket
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PIPELINE = BASE_DIR / "label_marks_complete.py"
PORT = 5000
BIND_HOST = "127.0.0.1"


def parse_video_id(raw: str) -> str:
    """Extract a video/session ID from a jrpd:// URL (or accept a bare ID).

    The userscript sends an already-normalized session key ("dQw4...", "BVxxx",
    "BVxxx_pN"), so scheme-stripping is the main job. Full YouTube/Bilibili
    URLs are tolerated with the same rules as audio_utils.video_session_key.
    """
    v = (raw or "").strip()
    if not v:
        return ""
    # Strip the scheme ("jrpd://id", "jrpd:id"), any leading slashes and quotes
    v = re.sub(r"^jrpd:/{0,2}", "", v, flags=re.IGNORECASE).strip().strip("/")
    v = v.strip("\"'")
    try:
        from urllib.parse import unquote
        v = unquote(v)
    except Exception:
        pass
    if v.startswith("http"):
        # Bilibili part URL: .../video/BVxxx?p=2 -> BVxxx_p2
        m = re.search(r"/video/(BV[0-9A-Za-z]+|av\d+|\d+)", v)
        if m:
            base = m.group(1)
            pm = re.search(r"[?&]p=(\d+)", v)
            try:
                n = int(pm.group(1)) if pm else 1
            except ValueError:
                n = 1
            return f"{base}_p{n}" if n > 1 else base
        # YouTube: v= param
        ym = re.search(r"[?&]v=([A-Za-z0-9_-]{11})", v)
        if ym:
            return ym.group(1)
    return v


def port_in_use(port: int = PORT, host: str = BIND_HOST, timeout: float = 0.5) -> bool:
    """True when something already accepts connections on the pipeline port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        return s.connect_ex((host, port)) == 0


def pause(msg: str = "Press Enter to close..."):
    try:
        input(f"\n{msg} ")
    except (EOFError, KeyboardInterrupt):
        pass


def main() -> int:
    raw = sys.argv[1] if len(sys.argv) > 1 else ""
    vid = parse_video_id(raw)

    if os.environ.get("JRPD_PROTOCOL_DRY_RUN"):
        print(f"[DRY RUN] raw={raw!r} -> video_id={vid!r}")
        if vid and PIPELINE.exists() and not port_in_use():
            print(f"[DRY RUN] would run: {sys.executable} {PIPELINE} {vid} (cwd={BASE_DIR})")
        return 0

    if not vid:
        print(f"[JRPD] Could not read a video ID from: {raw!r}")
        print("Expected: jrpd://<video_id>  (sent by the browser panel)")
        pause()
        return 1

    if not PIPELINE.exists():
        print(f"[JRPD] Pipeline not found: {PIPELINE}")
        pause()
        return 1

    if port_in_use():
        print(f"[JRPD] Port {PORT} is already in use - another JRPD session is running.")
        print("Quit that session first (panel Quit button or Ctrl+C in its window),")
        print("then start this video again.")
        pause()
        return 0

    print(f"[JRPD] Starting: python label_marks_complete.py {vid}")
    try:
        proc = subprocess.Popen(
            [sys.executable, str(PIPELINE), vid],
            cwd=str(BASE_DIR),
        )
    except OSError as e:
        print(f"[JRPD] Failed to start the pipeline: {e}")
        pause()
        return 1

    # The child inherits this console: this window IS the pipeline window.
    code = proc.wait()
    print(f"\n[JRPD] Pipeline exited (code {code}).")
    pause()
    return 0


if __name__ == "__main__":
    sys.exit(main())
