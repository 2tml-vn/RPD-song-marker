"""
Rename-semantics regression tests for /update_song_vars.

When the Edit Song form changes the Song Key (a rename), the server diffs the
posted form values against the OLD entry to detect what the user actually did
(both modals always POST every field, prefilled from the old entry):
  unchanged (or absent) -> fill-empty move (never clobbers a pre-existing
                           value on the target key)
  cleared               -> deliberate delete: nothing carries over (the
                           target's own value stays untouched)
  edited to a new value -> apply the edit on the target
The old key always becomes the pure redirect shell {remap: new_key}.
"""
import asyncio

import pytest

import server
import song_db


class _FakeRequest:
    """Minimal stand-in for aiohttp request: only .post() is needed."""

    def __init__(self, data: dict):
        self._data = dict(data)

    async def post(self):
        return self._data


def _form(old: dict, **changed) -> dict:
    """Build the full field set both modals POST, prefilled from `old`,
    with user edits applied. Mirrors the frontend exactly."""
    old = old or {}
    data = {
        "key": changed.pop("key"),
        "ts": "0:29",
    }
    if "new_key" in changed:
        data["new_key"] = changed.pop("new_key")
    for field in ("intl", "artist_orig", "artist_intl", "info", "remap"):
        data[field] = str(changed.pop(field, old.get(field, "") or ""))
    for field in ("discard", "see_artist", "intl_override"):
        want = changed.pop(field, old.get(field, False))
        data[field] = "1" if want else "0"
    assert not changed, f"unused form fields: {changed}"
    return data


def _post(data: dict):
    return asyncio.run(server.handle_update_song_vars(_FakeRequest(data)))


@pytest.fixture
def overrides(tmp_path, monkeypatch):
    """Isolate SONG_OVERRIDES in memory and redirect the JSON save to tmp."""
    monkeypatch.setattr(song_db, "SONG_OVERRIDES_FILE", tmp_path / "songs.json")
    server.SONG_OVERRIDES.clear()
    server.state.results_keys = {}
    server.state.results_file_path = None
    yield server.SONG_OVERRIDES
    server.SONG_OVERRIDES.clear()


def _resp_json(resp):
    import json
    return json.loads(resp.text)


# --- Example 1: the reported bug — rename + cleared intl -------------------

def test_rename_cleared_intl_not_carried(overrides):
    overrides["A"] = {"intl": "Night Running"}
    resp = _post(_form(overrides["A"], key="A", new_key="B", intl=""))
    assert _resp_json(resp)["status"] == "ok"
    assert overrides["B"] == {}
    assert overrides["A"] == {"remap": "B"}


# --- Example 2: rename only, nothing touched ------------------------------

def test_rename_untouched_fields_move_fill_empty(overrides):
    overrides["A"] = {"intl": "X", "artist_intl": "Y", "see_artist": True}
    resp = _post(_form(overrides["A"], key="A", new_key="B"))
    assert _resp_json(resp)["status"] == "ok"
    assert overrides["B"] == {"intl": "X", "artist_intl": "Y", "see_artist": True}
    assert overrides["A"] == {"remap": "B"}


# --- Example 3: rename onto a key that already exists ---------------------

def test_rename_onto_existing_keeps_target_own_intl(overrides):
    overrides["A"] = {"intl": "Night Running"}
    overrides["B"] = {"intl": "B's own intl"}
    resp = _post(_form(overrides["A"], key="A", new_key="B", intl=""))
    assert _resp_json(resp)["status"] == "ok"
    # Deletion applies to the edited entry only; B's own value is untouched.
    assert overrides["B"] == {"intl": "B's own intl"}
    assert overrides["A"] == {"remap": "B"}


def test_rename_onto_existing_without_intl_gets_nothing(overrides):
    overrides["A"] = {"intl": "Night Running"}
    overrides["B"] = {"artist_intl": "B artist"}
    resp = _post(_form(overrides["A"], key="A", new_key="B", intl=""))
    assert _resp_json(resp)["status"] == "ok"
    # Cleared field must not materialize on the target.
    assert overrides["B"] == {"artist_intl": "B artist"}
    assert overrides["A"] == {"remap": "B"}


# --- Example 4: edit a value while renaming -------------------------------

def test_rename_applies_edited_value(overrides):
    overrides["A"] = {"intl": "Night Running"}
    resp = _post(_form(overrides["A"], key="A", new_key="B",
                       intl="Running in the Night"))
    assert _resp_json(resp)["status"] == "ok"
    assert overrides["B"] == {"intl": "Running in the Night"}
    assert overrides["A"] == {"remap": "B"}


# --- Bool diff semantics ---------------------------------------------------

def test_rename_unchecked_flag_not_carried(overrides):
    overrides["A"] = {"discard": True, "intl": "X"}
    resp = _post(_form(overrides["A"], key="A", new_key="B", discard=False))
    assert _resp_json(resp)["status"] == "ok"
    assert overrides["B"] == {"intl": "X"}
    assert overrides["A"] == {"remap": "B"}


def test_rename_checked_new_flag_applied(overrides):
    overrides["A"] = {"intl": "X"}
    resp = _post(_form(overrides["A"], key="A", new_key="B", see_artist=True))
    assert _resp_json(resp)["status"] == "ok"
    assert overrides["B"] == {"intl": "X", "see_artist": True}
    assert overrides["A"] == {"remap": "B"}


# --- Target was a pure redirect shell -------------------------------------

def test_rename_collapses_target_redirect_shell(overrides):
    overrides["A"] = {"intl": "X"}
    overrides["B"] = {"remap": "C"}
    resp = _post(_form(overrides["A"], key="A", new_key="B"))
    assert _resp_json(resp)["status"] == "ok"
    # B received real fields, so its redirect must be cleared.
    assert overrides["B"] == {"intl": "X"}
    assert overrides["A"] == {"remap": "B"}


# --- Plain (non-rename) edit: unchanged behavior ---------------------------

def test_plain_edit_clear_deletes_field(overrides):
    overrides["A"] = {"intl": "X", "info": "v1"}
    resp = _post(_form(overrides["A"], key="A", intl=""))
    assert _resp_json(resp)["status"] == "ok"
    assert overrides["A"] == {"info": "v1"}


def test_plain_edit_untouched_fields_persist(overrides):
    overrides["A"] = {"intl": "X", "info": "v1"}
    resp = _post(_form(overrides["A"], key="A"))
    assert _resp_json(resp)["status"] == "ok"
    assert overrides["A"] == {"intl": "X", "info": "v1"}
