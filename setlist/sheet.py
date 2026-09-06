"""Match a per-band song-detail sheet (CSV export of the Google Sheet) to the
SBP song library, so we can enrich songs with data SBP doesn't carry — most
importantly Dale's guitar (acoustic/electric), used to group setlists.

The sheet's ``ID`` is its own, not the SBP song id, so rows are matched to SBP
songs by fuzzy title comparison (RapidFuzz, mirroring ``gsheet.ipynb``). When a
row has an explicit ``SBP Song Name`` that value is used for matching instead.
"""

from __future__ import annotations

import glob
import os
import re

import pandas as pd
from rapidfuzz import process, fuzz

from .data import Library

REPO_ROOT = os.path.dirname(os.path.dirname(__file__))

# Column names as they appear in the exported CSV.
COL_TITLE = "Song Title"
COL_SBP_NAME = "SBP Song Name"
COL_INSTRUMENT = "Dale Guitar"

# Normalize the sheet's instrument labels to lowercase tokens the generator uses.
_INSTRUMENT_MAP = {"acoustic": "acoustic", "electric": "electric", "either": "either"}


def find_song_sheet() -> str | None:
    """Locate a song-detail CSV in the repo (band sheets export)."""
    candidates = (
        glob.glob(os.path.join(REPO_ROOT, "gsheet_exports", "*.csv"))
        + glob.glob(os.path.join(REPO_ROOT, "*SongList*.csv"))
        + glob.glob(os.path.join(REPO_ROOT, "*.csv"))
    )
    # De-dupe preserving order.
    seen, out = set(), []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out[0] if out else None


def _normalize_title(text: str) -> str:
    """Strip key/capo suffixes and punctuation for robust title matching.

    e.g. "Drink In My Hand (C)" / "7 & 7 (-1)" / "Coast +4" -> comparable stems.
    """
    if not text:
        return ""
    t = text.lower()
    t = re.sub(r"\([^)]*\)", " ", t)           # drop parenthetical (key/capo) notes
    t = re.sub(r"[+\-]\s*\d+", " ", t)          # drop trailing +2 / -1 markers
    t = re.sub(r"[^a-z0-9 ]+", " ", t)          # drop punctuation/emoji
    t = re.sub(r"\s+", " ", t).strip()
    return t


def load_song_sheet(csv_path: str | None = None) -> pd.DataFrame:
    """Load the song-detail CSV as-is (UTF-8), with a normalized-title column."""
    if csv_path is None:
        csv_path = find_song_sheet()
    if csv_path is None:
        return pd.DataFrame()

    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False, encoding="utf-8")
    df.columns = [c.strip() for c in df.columns]

    match_source = df[COL_SBP_NAME].where(
        df.get(COL_SBP_NAME, pd.Series("", index=df.index)).str.strip() != "",
        df[COL_TITLE],
    ) if COL_SBP_NAME in df.columns else df[COL_TITLE]
    df["_match_title"] = match_source.map(_normalize_title)
    return df


def match_to_library(
    lib: Library, csv_path: str | None = None, threshold: int = 80
) -> pd.DataFrame:
    """Match each SBP song to its best sheet row.

    Returns one row per SBP song with columns:
    songID, title, matched_title, score, instrument, feel, crowd_knows, sheet_rank.
    ``instrument`` is None when there is no confident match or the sheet value is
    blank. Rows with score < ``threshold`` are kept but their instrument is None
    (so a weak match never mislabels a song).
    """
    sheet = load_song_sheet(csv_path)
    if sheet.empty:
        return pd.DataFrame(
            columns=["songID", "title", "matched_title", "score", "instrument",
                     "feel", "crowd_knows", "sheet_rank"]
        )

    sheet_titles = sheet["_match_title"].tolist()
    rows = []
    for song in lib.songs.itertuples():
        norm = _normalize_title(song.title)
        best = process.extractOne(norm, sheet_titles, scorer=fuzz.token_sort_ratio) if norm else None
        instrument = feel = crowd = rank = None
        matched_title = None
        score = 0
        if best:
            matched_title, score, idx = best
            if score >= threshold:
                srow = sheet.iloc[idx]
                raw_instr = str(srow.get(COL_INSTRUMENT, "")).strip().lower()
                instrument = _INSTRUMENT_MAP.get(raw_instr)
                feel = (srow.get("Feel") or "").strip() or None
                crowd = (srow.get("Crowd Knows") or "").strip() or None
                rank = (srow.get("Rank") or "").strip() or None
        rows.append(
            {
                "songID": song.songID,
                "title": song.title,
                "matched_title": matched_title if score >= threshold else None,
                "score": int(score),
                "instrument": instrument,
                "feel": feel,
                "crowd_knows": crowd,
                "sheet_rank": rank,
            }
        )
    return pd.DataFrame(rows)


def instrument_map(lib: Library, csv_path: str | None = None, threshold: int = 80) -> dict:
    """{sbp_songID: 'acoustic'|'electric'|'either'} for confidently matched songs."""
    matched = match_to_library(lib, csv_path, threshold)
    return {
        int(r.songID): r.instrument
        for r in matched.itertuples()
        if r.instrument
    }
