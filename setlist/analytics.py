"""Analytics over a parsed :class:`~setlist.data.Library`.

Play count = number of sets a song appears in (an appearance in a setlist).
Per-band analytics use each set's inferred primary band (see
``setlist.data._attribute_sets_to_bands``).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from .data import Library


def _filter_sets(
    lib: Library,
    band: str | None = None,
    months_back: int | None = None,
    exclude_name_contains: list[str] | None = None,
) -> pd.DataFrame:
    """Return the subset of ``lib.sets`` matching the given filters."""
    sets = lib.sets.copy()

    if band:
        sets = sets[sets["band"] == band]

    if months_back:
        cutoff = datetime.now().date() - timedelta(days=int(months_back * 30.44))
        sets = sets[sets["setDate"].notna() & (sets["setDate"] >= cutoff)]

    if exclude_name_contains:
        for pattern in exclude_name_contains:
            pattern = pattern.strip()
            if pattern:
                sets = sets[~sets["setName"].str.contains(pattern, case=False, na=False)]

    return sets


def most_played_songs(
    lib: Library,
    band: str | None = None,
    top_n: int = 50,
    months_back: int | None = None,
    exclude_name_contains: list[str] | None = None,
) -> pd.DataFrame:
    """Top ``top_n`` songs by play count (appearances across the filtered sets).

    Columns: rank, songID, artist, title, play_count, last_played.
    """
    sets = _filter_sets(lib, band, months_back, exclude_name_contains)
    valid_ids = set(sets["setID"])

    plays = lib.set_songs[lib.set_songs["setID"].isin(valid_ids)].copy()
    if plays.empty:
        return pd.DataFrame(
            columns=["rank", "songID", "artist", "title", "play_count", "last_played"]
        )

    # Last-played date per song within the filtered window.
    date_by_set = dict(zip(sets["setID"], sets["setDate"]))
    plays["setDate"] = plays["setID"].map(date_by_set)
    last_played = plays.groupby("songID")["setDate"].max()

    counts = plays["songID"].value_counts().rename("play_count").reset_index()
    counts.columns = ["songID", "play_count"]

    merged = counts.merge(
        lib.songs[["songID", "artist", "title"]], on="songID", how="left"
    )
    merged["last_played"] = merged["songID"].map(last_played)
    merged = merged.sort_values(
        ["play_count", "title"], ascending=[False, True]
    ).head(top_n)
    merged.insert(0, "rank", range(1, len(merged) + 1))
    return merged.reset_index(drop=True)


def band_overview(lib: Library) -> pd.DataFrame:
    """One row per band: song-library size, sets played, and set averages.

    ``avg_runtime_min`` is based only on sets that have any duration data, so it
    is a lower bound while the SBP library is missing per-song durations.
    """
    rows = []
    for band in lib.band_names:
        band_sets = lib.sets[lib.sets["band"] == band]
        lib_songs = lib.songs[lib.songs["band_names"].apply(lambda names: band in (names or []))]

        sets_with_runtime = band_sets[band_sets["runtime_sec"] > 0]
        avg_runtime_min = (
            round(sets_with_runtime["runtime_sec"].mean() / 60.0, 1)
            if not sets_with_runtime.empty
            else None
        )
        avg_songs = round(band_sets["n_songs"].mean(), 1) if not band_sets.empty else None

        rows.append(
            {
                "band": band,
                "songs_in_library": len(lib_songs),
                "sets_played": len(band_sets),
                "avg_songs_per_set": avg_songs,
                "avg_runtime_min": avg_runtime_min,
            }
        )
    return pd.DataFrame(rows).sort_values("sets_played", ascending=False).reset_index(drop=True)


def library_summary(lib: Library) -> dict:
    """Headline totals for the whole library."""
    n_dur = lib.songs["duration"].notna().sum()
    return {
        "songs": len(lib.songs),
        "sets": len(lib.sets),
        "bands": len(lib.bands),
        "song_appearances": len(lib.set_songs),
        "songs_with_duration": int(n_dur),
        "duration_coverage_pct": round(100 * n_dur / len(lib.songs), 0) if len(lib.songs) else 0,
    }


def rarely_played(lib: Library, band: str | None = None, bottom_n: int = 25) -> pd.DataFrame:
    """Songs in a band's library that show up least often in its sets.

    Includes never-played songs (play_count = 0). Useful for spotting songs to
    rotate back in.
    """
    if band:
        pool = lib.songs[lib.songs["band_names"].apply(lambda n: band in (n or []))]
    else:
        pool = lib.songs

    played = most_played_songs(lib, band=band, top_n=10_000)
    counts = dict(zip(played["songID"], played["play_count"]))

    out = pool[["songID", "artist", "title"]].copy()
    out["play_count"] = out["songID"].map(counts).fillna(0).astype(int)
    out = out.sort_values(["play_count", "title"], ascending=[True, True]).head(bottom_n)
    return out.reset_index(drop=True)
