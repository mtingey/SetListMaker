"""Generate new setlists from a band's playing history.

The generator learns two things from past sets:

- **how often** each song is played (a weight for selection), and
- **where** in a set each song tends to land (its average normalized position),

then samples a fresh setlist and orders it to mirror that historical shape.

An optional ``instrument_by_song`` mapping lets us group songs by instrument
(e.g. Dale's acoustic songs together, electric together). That mapping will
come from the Google Sheet; until then the grouping is simply skipped.
"""

from __future__ import annotations

import random

import pandas as pd

from .data import Library
from . import analytics

# Fallback per-song length (seconds) when a song has no duration recorded.
DEFAULT_SONG_SECONDS = 210

# Folders whose songs belong to the other band (MM6) and must never be offered
# for a setlist. Songs shared with Colt 46 are kept; only MM6-exclusive ones drop.
MM6_FOLDERS = {"MM6", "MM6 XMAS"}


def _is_mm6_only(band_names) -> bool:
    names = set(band_names or [])
    return bool(names & MM6_FOLDERS) and "Colt 46" not in names


def _song_history(lib: Library, band: str | None) -> pd.DataFrame:
    """Per-song play_count and average normalized position within the band's sets."""
    sets = lib.sets if band is None else lib.sets[lib.sets["band"] == band]
    set_ids = set(sets["setID"])
    plays = lib.set_songs[lib.set_songs["setID"].isin(set_ids)].copy()

    if plays.empty:
        return pd.DataFrame(columns=["songID", "play_count", "avg_position"])

    # Normalize song order to 0..1 within each set (0 = opener, 1 = closer).
    set_len = plays.groupby("setID")["songID"].transform("size")
    plays["norm_pos"] = plays["songOrder"] / (set_len - 1).clip(lower=1)

    stats = plays.groupby("songID").agg(
        play_count=("songID", "size"),
        avg_position=("norm_pos", "mean"),
    ).reset_index()
    return stats


def _band_song_pool(lib: Library, band: str | None) -> pd.DataFrame:
    """Songs eligible for a band: those in its library or seen in its sets."""
    if band is None:
        pool = lib.songs.copy()
    else:
        in_library = lib.songs["band_names"].apply(lambda n: band in (n or []))
        pool = lib.songs[in_library].copy()

    # Never offer MM6-exclusive songs (this is a Colt 46 app).
    pool = pool[~pool["band_names"].apply(_is_mm6_only)]

    history = _song_history(lib, band)
    pool = pool.merge(history, on="songID", how="left")
    pool["play_count"] = pool["play_count"].fillna(0).astype(int)
    pool["avg_position"] = pool["avg_position"].fillna(0.5)

    # Include songs played for the band even if not tagged into its library folder.
    if band is not None:
        seen_ids = set(history["songID"])
        missing = seen_ids - set(pool["songID"])
        if missing:
            extra = lib.songs[lib.songs["songID"].isin(missing)].merge(
                history, on="songID", how="left"
            )
            extra = extra[~extra["band_names"].apply(_is_mm6_only)]
            pool = pd.concat([pool, extra], ignore_index=True)
    return pool


def generate_setlist(
    lib: Library,
    band: str | None = None,
    n_songs: int | None = 20,
    target_minutes: int | None = None,
    favor: str = "popular",
    avoid_song_ids: set | None = None,
    instrument_by_song: dict | None = None,
    instrument_order: list[str] | None = None,
    seed: int | None = None,
) -> pd.DataFrame:
    """Build a setlist for ``band``.

    Parameters
    ----------
    n_songs : target number of songs (ignored if ``target_minutes`` is set).
    target_minutes : if set, add songs until the estimated runtime is reached.
    favor : selection bias --
        ``"popular"``  weight by historical play count (default),
        ``"balanced"`` roughly uniform across the library,
        ``"fresh"``    favor songs played least (rotate deep cuts back in).
    avoid_song_ids : songs to exclude (e.g. played at the last gig).
    instrument_by_song : optional {songID: instrument} to group the result by
        instrument (e.g. all acoustic together, then electric).
    instrument_order : preferred order of instrument blocks, e.g.
        ``["acoustic", "electric"]``. Unlisted instruments follow, then unknown.
    seed : set for reproducible output.
    """
    rng = random.Random(seed)
    pool = _band_song_pool(lib, band)
    avoid = avoid_song_ids or set()
    pool = pool[~pool["songID"].isin(avoid)]
    if pool.empty:
        return pd.DataFrame(
            columns=["position", "songID", "artist", "title", "instrument", "duration_sec", "play_count"]
        )

    # --- selection weights ---------------------------------------------------
    counts = pool["play_count"].astype(float)
    if favor == "popular":
        weights = counts + 1.0                    # +1 smoothing keeps deep cuts possible
    elif favor == "fresh":
        weights = 1.0 / (counts + 1.0)
    else:  # balanced
        weights = pd.Series(1.0, index=pool.index)

    # --- how many songs to pick ---------------------------------------------
    ids = pool["songID"].tolist()
    wlist = weights.tolist()
    chosen: list = []

    def _median_duration() -> float:
        known = pool["duration"].dropna()
        return float(known.median()) if not known.empty else DEFAULT_SONG_SECONDS

    med = _median_duration()
    dur_by_id = dict(zip(pool["songID"], pool["duration"]))

    if target_minutes:
        target_sec = target_minutes * 60
        running = 0
        remaining_ids, remaining_w = ids[:], wlist[:]
        while remaining_ids and running < target_sec:
            pick = rng.choices(range(len(remaining_ids)), weights=remaining_w, k=1)[0]
            sid = remaining_ids.pop(pick)
            remaining_w.pop(pick)
            chosen.append(sid)
            d = dur_by_id.get(sid)
            running += int(d) if d and not pd.isna(d) else med
    else:
        k = min(int(n_songs or 20), len(ids))
        remaining_ids, remaining_w = ids[:], wlist[:]
        for _ in range(k):
            pick = rng.choices(range(len(remaining_ids)), weights=remaining_w, k=1)[0]
            chosen.append(remaining_ids.pop(pick))
            remaining_w.pop(pick)

    result = pool[pool["songID"].isin(chosen)].copy()
    result["instrument"] = result["songID"].map(instrument_by_song or {})

    # --- ordering ------------------------------------------------------------
    # Base order mirrors how songs historically sit in a set (opener -> closer).
    result = result.sort_values("avg_position")

    if instrument_by_song:
        order = instrument_order or ["acoustic", "electric"]
        rank = {name: i for i, name in enumerate(order)}
        # Unlisted instruments go after listed ones; unknown/None last.
        result["_grp"] = result["instrument"].map(
            lambda x: rank.get(x, len(order)) if x else len(order) + 1
        )
        result = result.sort_values(["_grp", "avg_position"]).drop(columns="_grp")

    result = result.reset_index(drop=True)
    result.insert(0, "position", range(1, len(result) + 1))
    result["duration_sec"] = result["duration"]
    return result[
        ["position", "songID", "artist", "title", "instrument", "duration_sec", "play_count"]
    ]


def estimate_runtime_minutes(setlist: pd.DataFrame, default_seconds: int = DEFAULT_SONG_SECONDS) -> float:
    """Estimated runtime for a generated setlist, filling unknown durations."""
    secs = setlist["duration_sec"].apply(
        lambda d: int(d) if d and not pd.isna(d) else default_seconds
    ).sum()
    return round(secs / 60.0, 1)
