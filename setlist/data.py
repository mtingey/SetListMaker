"""Load and normalize SongBook Pro (SBP) backup exports into tidy DataFrames.

An SBP backup is JSON with three top-level keys:

- ``songs``   : the song library
- ``sets``    : each set has ``details`` (metadata) + ``contents`` (ordered songs)
- ``folders`` : SBP folders, which we treat as *bands*

Songs link to bands through a ``_folders`` field that SBP stores as a JSON
*string* (e.g. the literal text ``"[1,5]"``), so it needs a second parse.

Nothing here depends on Streamlit, so the same functions back a CLI, an API,
or a notebook.
"""

from __future__ import annotations

import json
import glob
import os
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

# Directory holding SBP backup exports, relative to the repo root.
BACKUPS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "SBPBackups")


# --------------------------------------------------------------------------- #
# Low-level parsing helpers
# --------------------------------------------------------------------------- #
def _parse_json_string_list(value) -> list:
    """SBP stores some list fields as a JSON-encoded string (e.g. '[1,5]').

    Return a real Python list. Accepts already-parsed lists, JSON strings,
    ``None``, and empty strings.
    """
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else [parsed]
        except (json.JSONDecodeError, ValueError):
            return []
    return [value]


def _is_deleted(record: dict) -> bool:
    """SBP marks tombstoned rows with ``Deleted`` as True/1 (or "True")."""
    flag = record.get("Deleted", 0)
    if isinstance(flag, str):
        return flag.strip().lower() in {"true", "1"}
    return bool(flag)


def _to_int(value, default=None):
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_date(value):
    """Parse an SBP ISO date/datetime string into a ``date``; ``None`` on failure."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "")).date()
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# Backup discovery
# --------------------------------------------------------------------------- #
def list_backups(backups_dir: str = BACKUPS_DIR) -> list[str]:
    """Return backup ``.json`` file paths, newest-named first."""
    paths = sorted(glob.glob(os.path.join(backups_dir, "*.json")), reverse=True)
    return paths


def default_backup(backups_dir: str = BACKUPS_DIR) -> str | None:
    backups = list_backups(backups_dir)
    return backups[0] if backups else None


# --------------------------------------------------------------------------- #
# Main loader
# --------------------------------------------------------------------------- #
@dataclass
class Library:
    """A fully parsed, cross-referenced SBP backup."""

    songs: pd.DataFrame       # songID, artist, title, duration, key, tempo, band_ids, band_names
    sets: pd.DataFrame        # setID, setName, setDate, pinned, band, band_dist, n_songs, runtime_sec
    set_songs: pd.DataFrame   # setID, songID, songOrder
    bands: pd.DataFrame       # bandID, bandName
    source_file: str

    @property
    def band_names(self) -> list[str]:
        return self.bands["bandName"].tolist()


def load_library(backup_file: str | None = None) -> Library:
    """Parse a backup file into a :class:`Library`."""
    if backup_file is None:
        backup_file = default_backup()
    if backup_file is None:
        raise FileNotFoundError(f"No backup .json files found in {BACKUPS_DIR}")

    with open(backup_file, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    bands_df = _build_bands(data.get("folders", []))
    band_name_by_id = dict(zip(bands_df["bandID"], bands_df["bandName"]))

    songs_df = _build_songs(data.get("songs", []), band_name_by_id)
    sets_df, set_songs_df = _build_sets(data.get("sets", []))

    # Drop set memberships that point at non-songs: SBP markers (filtered above)
    # and songs deleted from the library but still referenced in old sets.
    valid_ids = set(songs_df["songID"])
    set_songs_df = set_songs_df[set_songs_df["songID"].isin(valid_ids)].reset_index(drop=True)

    # Attribute each set to a band based on the folder membership of its songs.
    sets_df = _attribute_sets_to_bands(sets_df, set_songs_df, songs_df)

    # Add a runtime estimate per set (sum of known song durations).
    sets_df = _add_set_runtime(sets_df, set_songs_df, songs_df)

    # Hide bands that shouldn't appear anywhere in the app (MM6 is a separate band).
    songs_df, sets_df, set_songs_df, bands_df = _hide_bands(
        songs_df, sets_df, set_songs_df, bands_df
    )

    return Library(
        songs=songs_df,
        sets=sets_df,
        set_songs=set_songs_df,
        bands=bands_df,
        source_file=backup_file,
    )


# Bands to hide from the entire app (branded as Colt 46). Songs shared with
# Colt 46 are kept; only the hidden band's exclusive songs/sets are removed.
HIDDEN_BANDS = {"MM6", "MM6 XMAS"}
PRIMARY_BAND = "Colt 46"


def _hide_bands(songs_df, sets_df, set_songs_df, bands_df):
    """Remove hidden bands, their exclusive songs, and their sets, everywhere."""
    def _hidden_only(names) -> bool:
        s = set(names or [])
        return bool(s & HIDDEN_BANDS) and PRIMARY_BAND not in s

    songs_df = songs_df[~songs_df["band_names"].apply(_hidden_only)].reset_index(drop=True)
    # Scrub hidden band tags from the songs that remain (those shared with Colt 46),
    # so "MM6" never shows up in the Bands column etc.
    songs_df = songs_df.copy()
    songs_df["band_names"] = songs_df["band_names"].apply(
        lambda names: [n for n in (names or []) if n not in HIDDEN_BANDS]
    )
    bands_df = bands_df[~bands_df["bandName"].isin(HIDDEN_BANDS)].reset_index(drop=True)
    sets_df = sets_df[~sets_df["band"].isin(HIDDEN_BANDS)].reset_index(drop=True)

    valid_songs = set(songs_df["songID"])
    valid_sets = set(sets_df["setID"])
    set_songs_df = set_songs_df[
        set_songs_df["songID"].isin(valid_songs) & set_songs_df["setID"].isin(valid_sets)
    ].reset_index(drop=True)
    return songs_df, sets_df, set_songs_df, bands_df


def _build_bands(folders: list[dict]) -> pd.DataFrame:
    rows = [
        {"bandID": _to_int(f.get("Id")), "bandName": f.get("Name", "").strip()}
        for f in folders
        if not _is_deleted(f)
    ]
    df = pd.DataFrame(rows, columns=["bandID", "bandName"])
    return df.sort_values("bandName").reset_index(drop=True)


def _build_songs(songs: list[dict], band_name_by_id: dict) -> pd.DataFrame:
    rows = []
    for s in songs:
        if _is_deleted(s):
            continue
        # Skip SBP marker/placeholder items (e.g. "Change Pitch", "Set Separator").
        # Real songs always carry an author; these markers never do.
        if not (s.get("author") or "").strip():
            continue
        band_ids = [_to_int(x) for x in _parse_json_string_list(s.get("_folders"))]
        band_ids = [b for b in band_ids if b is not None]
        band_names = [band_name_by_id.get(b) for b in band_ids if b in band_name_by_id]
        # SBP stores 0 for songs whose length was never entered; treat as unknown.
        duration = _to_int(s.get("Duration"))
        if not duration or duration <= 0:
            duration = None
        rows.append(
            {
                "songID": _to_int(s.get("Id")),
                "artist": (s.get("author") or "").strip(),
                "title": (s.get("name") or "").strip(),
                "duration": duration,   # seconds, None when unknown
                "key": s.get("key"),
                "tempo": _to_int(s.get("TempoInt")),
                "band_ids": band_ids,
                "band_names": band_names,
            }
        )
    return pd.DataFrame(
        rows,
        columns=["songID", "artist", "title", "duration", "key", "tempo", "band_ids", "band_names"],
    )


def _build_sets(sets: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame]:
    set_rows = []
    membership_rows = []
    for st in sets:
        details = st.get("details", {})
        if _is_deleted(details):
            continue
        set_id = _to_int(details.get("Id"))
        set_rows.append(
            {
                "setID": set_id,
                "setName": (details.get("name") or "").strip() or "(untitled)",
                "setDate": _parse_date(details.get("date")),
                "pinned": bool(details.get("pinned", 0)),
            }
        )
        for item in st.get("contents", []):
            if _is_deleted(item):
                continue
            membership_rows.append(
                {
                    "setID": set_id,
                    "songID": _to_int(item.get("SongId")),
                    "songOrder": _to_int(item.get("Order"), default=0),
                }
            )

    sets_df = pd.DataFrame(set_rows, columns=["setID", "setName", "setDate", "pinned"])
    set_songs_df = pd.DataFrame(membership_rows, columns=["setID", "songID", "songOrder"])
    return sets_df, set_songs_df


def _attribute_sets_to_bands(
    sets_df: pd.DataFrame, set_songs_df: pd.DataFrame, songs_df: pd.DataFrame
) -> pd.DataFrame:
    """Assign each set a primary band = the band most of its songs belong to.

    Adds two columns: ``band`` (best guess, may be None) and ``band_dist``
    (dict of band_name -> count, for transparency / debugging).
    """
    band_names_by_song = dict(zip(songs_df["songID"], songs_df["band_names"]))

    primary, dist = [], []
    grouped = set_songs_df.groupby("setID")["songID"].apply(list)
    dist_by_set = {}
    for set_id, song_ids in grouped.items():
        counter: dict[str, int] = {}
        for sid in song_ids:
            for band in band_names_by_song.get(sid, []) or []:
                counter[band] = counter.get(band, 0) + 1
        dist_by_set[set_id] = counter

    for set_id in sets_df["setID"]:
        counter = dist_by_set.get(set_id, {})
        primary.append(max(counter, key=counter.get) if counter else None)
        dist.append(counter)

    out = sets_df.copy()
    out["band"] = primary
    out["band_dist"] = dist
    return out


def _add_set_runtime(
    sets_df: pd.DataFrame, set_songs_df: pd.DataFrame, songs_df: pd.DataFrame
) -> pd.DataFrame:
    """Add per-set song count, runtime (sum of known durations), and coverage."""
    dur_by_song = dict(zip(songs_df["songID"], songs_df["duration"]))

    n_songs, runtime, covered = {}, {}, {}
    for set_id, group in set_songs_df.groupby("setID"):
        song_ids = group["songID"].tolist()
        durs = [dur_by_song.get(sid) for sid in song_ids]
        known = [d for d in durs if d]
        n_songs[set_id] = len(song_ids)
        runtime[set_id] = sum(known)
        covered[set_id] = len(known)

    out = sets_df.copy()
    out["n_songs"] = out["setID"].map(n_songs).fillna(0).astype(int)
    out["runtime_sec"] = out["setID"].map(runtime).fillna(0).astype(int)
    out["duration_coverage"] = out["setID"].map(covered).fillna(0).astype(int)
    return out
