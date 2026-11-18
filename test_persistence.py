"""
Persistence/resume regression tests.

Covers the crash-safety fixes:
- save_progress_file() commits results + row-key bindings atomically, so panel
  edits survive a quit at any moment;
- merge_results_txt() adopts results.txt rows newer than progress.json on
  resume (the "added song reverts to old song" desync), while keeping
  auto-"Unidentified" rows labeled and never adopting stale data backwards;
- blank (cleared) row text is distinct from "Unidentified" in file space,
  so cleared rows can stay blank after resume.
"""
import json
import os
import time
from pathlib import Path

import pytest

import server


@pytest.fixture(autouse=True)
def reset_state(tmp_path):
    server.state.results_file_path = None
    server.state.results = {}
    server.state.results_keys = {}
    server.state.flagged_ts.clear()
    yield
    server.state.results_file_path = None
    server.state.results = {}
    server.state.results_keys = {}
    server.state.flagged_ts.clear()


def _make_outputs(tmp_path: Path, results: dict, keys: dict, results_txt: str,
                  progress_age=True):
    """Create a run-dir pair (progress.json + results.txt) with given content."""
    server.state.results_file_path = str(tmp_path / "results.txt")
    server.state.results = dict(results)
    server.state.results_keys = dict(keys)

    progress = tmp_path / "progress.json"
    progress.write_text(
        json.dumps({"results": results, "keys": keys}, ensure_ascii=False),
        encoding="utf-8",
    )
    youtube = tmp_path / "results.txt"
    youtube.write_text(results_txt, encoding="utf-8")

    if progress_age:
        # results.txt written AFTER progress.json (panel edit committed to the
        # txt first), simulating a quit before the next save_state().
        past = time.time() - 1000
        now = time.time()
        os.utime(progress, (past, past))
        os.utime(youtube, (now, now))
    return progress, youtube


def test_save_progress_file_commits_results_and_keys(tmp_path):
    server.state.results_file_path = str(tmp_path / "results.txt")
    server.state.results = {"0:29": "Happy Halloween - Junky", "1:08": "Processing..."}
    server.state.results_keys = {"0:29": "Happy Halloween"}

    assert server.save_progress_file() is True

    data = json.loads((tmp_path / "progress.json").read_text(encoding="utf-8"))
    assert data["results"]["0:29"] == "Happy Halloween - Junky"
    assert data["results"]["1:08"] == "Processing..."
    assert data["keys"]["0:29"] == "Happy Halloween"


def test_save_progress_file_without_results_path():
    server.state.results_file_path = None
    assert server.save_progress_file() is False


def test_merge_adopts_newer_txt_rows(tmp_path):
    # The BV12xxn6KEDM desync: progress says Unidentified / Processing...,
    # results.txt carries the songs that a panel edit produced afterwards.
    progress, youtube = _make_outputs(
        tmp_path,
        results={"1:33:54": "Unidentified", "1:35:29": "Processing..."},
        keys={},
        results_txt=(
            "1:33:54 恋になりたいAQUARIUM (Koi ni Naritai AQUARIUM) - Aqours\n"
            "1:35:29 ころしちゃった! (Koroshichatta!) - 夏山よつぎ\n"
        ),
    )
    merged = server.merge_results_txt(progress, youtube)
    assert merged == 2
    assert server.state.results["1:33:54"] == "恋になりたいAQUARIUM (Koi ni Naritai AQUARIUM) - Aqours"
    assert server.state.results["1:35:29"] == "ころしちゃった! (Koroshichatta!) - 夏山よつぎ"


def test_merge_skips_in_sync_rows(tmp_path):
    song = "Overdose - なとり"
    progress, youtube = _make_outputs(
        tmp_path,
        results={"1:49": song},
        keys={"1:49": "Overdose"},
        results_txt=f"1:49 {song}\n",
    )
    assert server.merge_results_txt(progress, youtube) == 0


def test_merge_never_adopts_older_txt_backwards(tmp_path):
    # progress.json contains a NEWER identification that results.txt lacks
    # (txt older): adopting the txt row would throw away good data.
    new_song = "Newer Identification - Artist"
    progress, youtube = _make_outputs(
        tmp_path,
        results={"1:49": new_song},
        keys={},
        results_txt="1:49 \n",
        progress_age=False,
    )
    old = time.time() - 1000
    os.utime(youtube, (old, old))
    assert server.merge_results_txt(progress, youtube) == 0
    assert server.state.results["1:49"] == new_song


def test_merge_keeps_unidentified_label_for_blank_row(tmp_path):
    # A blank results.txt line is also how an auto-"Unidentified" row renders;
    # the label must survive for the review flow.
    progress, youtube = _make_outputs(
        tmp_path,
        results={"10:34": "Unidentified"},
        keys={},
        results_txt="10:34 \n",
    )
    assert server.merge_results_txt(progress, youtube) == 0
    assert server.state.results["10:34"] == "Unidentified"


def test_merge_adopts_unknown_nonblank_row_and_skips_blank(tmp_path):
    progress, youtube = _make_outputs(
        tmp_path,
        results={},
        keys={},
        results_txt="0:29 Happy Halloween - Junky\n0:40 \n",
    )
    merged = server.merge_results_txt(progress, youtube)
    assert merged == 1
    assert server.state.results["0:29"] == "Happy Halloween - Junky"
    assert "0:40" not in server.state.results


def test_merge_rebuilds_row_key_binding(tmp_path):
    progress, youtube = _make_outputs(
        tmp_path,
        results={"1:49": "Unidentified"},
        keys={},
        results_txt="1:49 CRAZY - UMETORA\n",
    )
    # songs.json entry feeding the exact display rebuild (artist included,
    # the way an add-song edit registers it)
    server.SONG_OVERRIDES["CRAZY"] = {"artist_orig": "UMETORA"}
    merged = server.merge_results_txt(progress, youtube)
    assert merged == 1
    assert server.state.results_keys.get("1:49") == "CRAZY"
    server.SONG_OVERRIDES.pop("CRAZY", None)


def test_to_results_file_text_mapping():
    assert server.to_results_file_text("Unidentified") == ""
    assert server.to_results_file_text(None) == ""
    assert server.to_results_file_text("Processing...") == "Processing..."
    assert server.to_results_file_text("Song - Artist") == "Song - Artist"
    assert server.to_results_file_text("") == ""


def test_merge_flagged_row_compared_without_marker(tmp_path):
    progress, youtube = _make_outputs(
        tmp_path,
        results={"2:00": "MOTTAI - P丸様。"},
        keys={},
        results_txt="2:00 MOTTAI - P丸様。 🚩\n",
    )
    # Same canonical text (only the flag marker differs): the flag is state
    # tracked via flagged_ts, not row text — must be a no-op.
    assert server.merge_results_txt(progress, youtube) == 0
