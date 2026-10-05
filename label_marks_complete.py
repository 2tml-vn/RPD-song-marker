"""
JRPD Live Marker - Main Entry Point
Coordinates song identification for YouTube videos.

Usage: python label_marks_complete.py [VIDEO_ID]
"""
import asyncio
import sys
import os
import json
import subprocess
from pathlib import Path
import logging
import threading

# Setup logging FIRST before any other imports
from config import setup_logging
logger = setup_logging()

# Muffle internal decoder and network logs AFTER our setup
logging.getLogger("shazamio").setLevel(logging.WARNING)
logging.getLogger("shazamio.request").setLevel(logging.WARNING)
logging.getLogger("shazamio_core").setLevel(logging.WARNING)
logging.getLogger("aiohttp.client").setLevel(logging.WARNING)
logging.getLogger("symphonia_bundle_mp3").setLevel(logging.WARNING)
logging.getLogger("symphonia_bundle_mp4").setLevel(logging.WARNING)

# Force UTF-8 for Windows Console
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', line_buffering=True)

from shazamio import Shazam

# Import our modules
from config import PORT, RUNS_DIR, runtime
import shared_utils
from audio_utils import ensure_audio, format_timestamp_for_youtube
from song_db import (
    load_all_databases, save_missed_songs,
    MISSED_SONGS, auto_register_song, get_missed_candidates, format_missed_entry
)
from identifier import identify_song
from server import start_server
import server


def parse_args():
    """Parse command line arguments."""
    args = sys.argv[1:]
    if args:
        runtime.VIDEO_ID = args[0]
    else:
        runtime.VIDEO_ID = "default"


async def main():
    """Main entry point."""
    parse_args()
    load_all_databases()

    video_dir = RUNS_DIR / runtime.VIDEO_ID
    video_dir.mkdir(parents=True, exist_ok=True)
    progress_file = video_dir / "progress.json"
    youtube_out = video_dir / "results.txt"
    server.state.results_file_path = str(youtube_out)
    snippets_dir = video_dir / "snippets"
    if not snippets_dir.exists():
        snippets_dir.mkdir()

    # Start HTTP server in thread
    server.state.main_loop = asyncio.get_running_loop()
    server.state.review_done_event = asyncio.Event()
    MARK_QUEUE = asyncio.Queue()
    SELECTION_QUEUE = asyncio.Queue()
    server.state.mark_queue = MARK_QUEUE
    server.state.selection_queue = SELECTION_QUEUE

    threading.Thread(target=start_server, daemon=True).start()

    logger.info(f"[START] Video ID: {runtime.VIDEO_ID}")
    logger.info(f"Files stored in: {video_dir}")
    logger.info(f"Server listening on port {PORT}. YOU CAN START MARKING NOW.")

    insertion_order = []

    if progress_file.exists():
        with progress_file.open("r", encoding="utf-8") as f:
            raw_results = json.load(f)
        server.state.results = {format_timestamp_for_youtube(shared_utils.parse_ts(k)): v for k, v in raw_results.items()}
        insertion_order = sorted(server.state.results.keys(), key=shared_utils.parse_ts)
        for m in server.state.results:
            if server.state.results[m] == "" or server.state.results[m] is None:
                server.state.results[m] = "Processing..."

    shazam = Shazam(language='ja-JP', endpoint_country='JP')
    shazam_en = Shazam(language='en-US', endpoint_country='US')
    audio_path = ensure_audio(runtime.VIDEO_ID, video_dir)
    if not audio_path:
        logger.error("Failed to download/locate audio file. Exiting.")
        return

    def save_state():
        """Save current progress to disk."""
        try:
            with progress_file.open("w", encoding="utf-8") as f:
                json.dump(server.state.results, f, ensure_ascii=False, indent=2)
            with youtube_out.open("w", encoding="utf-8", newline='') as f:
                for m in sorted(server.state.results.keys(), key=shared_utils.parse_ts):
                    val = shared_utils.format_song_entry(server.state.results[m])
                    if val == "Unidentified":
                        val = ""
                    f.write(f"{m} {val}\n")
        except OSError as e:
            logger.error(f"Error saving state: {e}")
        except Exception as e:
            logger.error(f"Unexpected error saving state: {e}")

    async def queue_worker():
        """Process mark queue."""
        while True:
            ts = await MARK_QUEUE.get()
            try:
                if ts == "[FINISH]":
                    server.state.is_finished = True
                    continue
                if ts == "[UNDO]":
                    if insertion_order:
                        last_added = insertion_order.pop()
                        logger.info(f"[UNDO] Removed: {last_added}")
                        if last_added in server.state.results:
                            del server.state.results[last_added]
                    else:
                        logger.warning("[UNDO] Requested but no markers to remove.")
                    save_state()
                    continue
                ts_formatted = format_timestamp_for_youtube(ts)
                logger.info(f"[MARKER] Received: {ts_formatted}")
                if ts_formatted not in server.state.results:
                    server.state.results[ts_formatted] = "Processing..."
                    insertion_order.append(ts_formatted)
                save_state()
            except Exception as e:
                logger.error(f"Error processing mark: {e}")
            finally:
                MARK_QUEUE.task_done()

    worker_task = asyncio.create_task(queue_worker())

    # Cache video duration once at the start of the main loop (avoid redundant ffprobe calls)
    video_duration = 0
    try:
        probe_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)]
        video_duration = float(subprocess.check_output(probe_cmd).decode('utf-8').strip())
        logger.debug(f"[INIT] Cached video duration: {video_duration:.1f}s")
    except subprocess.CalledProcessError as e:
        logger.warning(f"Failed to get video duration: {e}")
    except Exception as e:
        logger.warning(f"Unexpected error getting duration: {e}")

    while True:
        sorted_keys = sorted(server.state.results.keys(), key=shared_utils.parse_ts)
        target = None
        for i, m in enumerate(sorted_keys):
            if server.state.results[m] == "Processing...":
                if i + 2 < len(sorted_keys) or server.state.is_finished:
                    target = m
                    break

        if target:
            idx = sorted_keys.index(target)
            current_sec = shared_utils.parse_ts(target)

            gap = (shared_utils.parse_ts(sorted_keys[idx + 1]) - current_sec) if idx + 1 < len(sorted_keys) else (video_duration - current_sec if video_duration > current_sec else 120.0)
            logger.info(f"[TARGET] {target} (Gap: {gap:.1f}s)")
            found_name = await identify_song(shazam, shazam_en, audio_path, current_sec, gap, snippets_dir, (idx + 1 == len(sorted_keys)), target)
            if target in server.state.results:
                server.state.results[target] = shared_utils.format_song_entry(found_name) if found_name != "Unidentified" else "Unidentified"
                save_state()
        elif server.state.is_finished and not any(res == "Processing..." for res in server.state.results.values()):
            worker_task.cancel()
            try:
                await worker_task
            except asyncio.CancelledError:
                pass

            unidentified_keys = [k for k in sorted(server.state.results.keys(), key=shared_utils.parse_ts) if server.state.results[k] == "Unidentified"]
            if MISSED_SONGS and unidentified_keys:
                candidate_pairs = get_missed_candidates()
                server.state.cleanup_candidates = [display for display, key in candidate_pairs]

                quit_cleanup = False
                for k in unidentified_keys:
                    if quit_cleanup:
                        break
                    start_sec = shared_utils.parse_ts(k)
                    logger.info(f"[CLEANUP] Current Gap: {k}")
                    server.state.current_seek_ts = int(start_sec)
                    choice = await SELECTION_QUEUE.get()
                    if choice == 'q':
                        quit_cleanup = True
                        break
                    if choice == 's':
                        continue
                    try:
                        if str(choice).startswith('+'):
                            raw = str(choice)[1:].strip()
                            try:
                                add_data = json.loads(raw)
                                song_key = add_data.get('key', '').strip()
                                if song_key:
                                    entry = {}
                                    if add_data.get('intl', '').strip():
                                        entry['intl'] = add_data['intl'].strip()
                                    if add_data.get('artist_orig', '').strip():
                                        entry['artist_orig'] = add_data['artist_orig'].strip()
                                    if add_data.get('artist_intl', '').strip():
                                        entry['artist_intl'] = add_data['artist_intl'].strip()
                                    MISSED_SONGS[song_key] = entry
                                    save_missed_songs()
                                    auto_register_song(song_key, entry.get('intl'), entry.get('artist_orig'), entry.get('artist_intl'))
                                    display = format_missed_entry(song_key, entry)
                                    server.state.results[k] = display
                                    logger.info(f"✓ Added & Assigned: {display}")
                                    candidate_pairs = get_missed_candidates()
                                    server.state.cleanup_candidates = [d for d, _ in candidate_pairs]
                                    save_state()
                                    continue
                            except json.JSONDecodeError:
                                logger.warning(f"[CLEANUP] Invalid JSON in add: {raw}")
                                continue
                        val = int(choice)
                        if 0 <= val < len(candidate_pairs):
                            display, song_key = candidate_pairs[val]
                            server.state.results[k] = display
                            data = MISSED_SONGS.get(song_key, {})
                            auto_register_song(song_key, data.get('intl'), data.get('artist_orig'), data.get('artist_intl'))
                            logger.info(f"✓ Assigned: {display}")
                            save_state()
                    except Exception as e:
                        logger.error(f"Error during cleanup selection: {e}")

                server.state.cleanup_candidates = []
                server.state.current_seek_ts = -1

            unidentified_data = {}
            sorted_keys = sorted(server.state.results.keys(), key=shared_utils.parse_ts)
            for i, m in enumerate(sorted_keys):
                if server.state.results[m] == "Unidentified":
                    next_m = sorted_keys[i+1] if i+1 < len(sorted_keys) else "END"
                    unidentified_data[m] = {"end": next_m, "name": ""}
            if unidentified_data:
                unidentified_file = video_dir / "unidentified.json"
                with unidentified_file.open("w", encoding="utf-8") as f:
                    json.dump(unidentified_data, f, ensure_ascii=False, indent=2)
                logger.info(f"[EXPORT] Created {unidentified_file.name}")
            else:
                if audio_path and audio_path.exists():
                    try:
                        audio_path.unlink()
                        logger.info(f"[CLEANUP] Deleted audio file: {audio_path.name}")
                    except OSError as e:
                        logger.warning(f"Could not delete audio file: {e}")
                    except Exception as e:
                        logger.warning(f"Unexpected error deleting audio: {e}")

            logger.info("=" * 60)
            logger.info(" SESSION COMPLETE - ENTERING REVIEW MODE")
            logger.info("=" * 60)
            logger.info("[REVIEW] Results panel active in browser. Server staying alive.")
            logger.info("[REVIEW] Press Ctrl+C or click Done in panel to exit.")
            server.state.is_session_done = True
            server.state.current_seek_ts = -1

            await server.state.review_done_event.wait()
            logger.info("[REVIEW] Review done. Exiting.")
            break
        else:
            await asyncio.sleep(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user. Exiting.")
    except Exception as e:
        logger.critical(f"Fatal error: {e}")
        raise
