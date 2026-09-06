"""Natural-language setlist assistant, powered by the Google Gemini API.

A prompt like "give me an opening set for a night at the Westerner" is turned
into a real setlist by giving the model the full annotated song catalog
(attributes from the song sheet + play history) plus the band's conventions, and
asking it to return a structured setlist. Follow-up prompts ("swap out Lot of
Leavin") revise the current set because the whole exchange is one ongoing
conversation.

Requires a ``GEMINI_API_KEY`` (env var or Streamlit secret) — free from
https://aistudio.google.com/apikey. The model can be overridden with
``GEMINI_MODEL`` (defaults to ``gemini-3.6-flash``, which is on the free tier).
"""

from __future__ import annotations

import json
import os

import pandas as pd
from rapidfuzz import process, fuzz

from google import genai
from google.genai import types

from .data import Library
from . import sheet

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

# The band's conventions — the domain knowledge the model needs.
SYSTEM_CONTEXT = """You are the setlist assistant for Colt 46, a country cover band.

HOW THE BAND PLAYS:
- Sets named "W#" are at the Westerner; "O#" are at the Outlaw — two clubs the band plays often.
- A night is 3 sets; a weekend is 2 nights (6 sets total). Most historical sets come from these weekends.
- Within a single night the band rarely repeats a song (across its 3 sets). Repeating songs across the two nights of a weekend is fine and common.
- A typical set is about 11-14 songs.

SONG ATTRIBUTES (in the catalog):
- guitar: Dale plays "acoustic", "electric", or "either". Group acoustic songs together and electric songs together to minimize his guitar swaps; "either" songs are flexible and make good transitions between blocks.
- feel: Up / Mid / Slow / Waltz (the groove).
- energy, danceability: 0-100 (from audio analysis). Use for dynamics and dance-floor prompts.
- bpm, key: tempo and musical key.
- crowd_knows: Yes = the audience knows the song (good for engagement/singalongs).
- vocals: who sings lead (Dale, Merrill, Geed).
- genre, tags: style and role tags (e.g. "Set Starter", "Set Ender", dance styles).
- plays: how many times it appears in past sets (higher = crowd-tested favorite).
- rating: the band's internal 1-9 tag — a soft signal only.

HOW TO BUILD A SET:
- Use the song attributes AND the patterns in the historical sets, but do NOT copy a past set verbatim — build a fresh one.
- Respect the prompt (venue, set position, mood, constraints like "only 1 slow song").
- Opening sets: start strong with a crowd-tested, energetic song and build. Closing sets: end big.
- Mind dynamics: vary energy, cluster the acoustic and electric songs, and avoid stacking too many slow songs unless asked.
- Only choose songs from the provided catalog (use the exact "title" values).
- Always return the COMPLETE current setlist, even when the user asks for a small revision.

OUTPUT: respond with ONLY a JSON object, no markdown fences, no prose, in this shape:
{"set_name": "short name", "songs": ["Exact Title", "Exact Title", ...], "notes": "1-2 sentences on your choices"}"""


class AssistantError(RuntimeError):
    """Raised for missing credentials or an unparseable model response."""


# --------------------------------------------------------------------------- #
# Catalog + history context
# --------------------------------------------------------------------------- #
def build_catalog(lib: Library, band: str = "Colt 46") -> list[dict]:
    """The annotated song catalog the model chooses from (song sheet + play counts)."""
    df = sheet.load_song_sheet()
    if df.empty:
        return []

    id_by_name = {str(t).strip(): sid for sid, t in zip(lib.songs["songID"], lib.songs["title"])}
    band_sets = set(lib.sets[lib.sets["band"] == band]["setID"])
    plays = lib.set_songs[lib.set_songs["setID"].isin(band_sets)]["songID"].value_counts().to_dict()

    catalog = []
    for _, r in df.iterrows():
        sid = id_by_name.get(str(r.get("SBP Song Name", "")).strip())
        catalog.append(
            {
                "title": r.get("Song Title", "").strip(),
                "artist": r.get("Artist", "").strip(),
                "vocals": r.get("Lead Vocals", "").strip(),
                "guitar": r.get("Dale Guitar", "").strip().lower(),
                "feel": r.get("Feel", "").strip(),
                "energy": r.get("Energy", "").strip(),
                "danceability": r.get("Danceability", "").strip(),
                "bpm": r.get("BPM", "").strip(),
                "key": r.get("Key", "").strip(),
                "crowd_knows": r.get("Crowd Knows", "").strip(),
                "genre": r.get("Discriminator #1", "").strip(),
                "tags": r.get("Discriminator #2", "").strip(),
                "rating": r.get("Club Rating", "").strip(),
                "runtime": r.get("Runtime", "").strip(),
                "plays": int(plays.get(sid, 0)) if sid is not None else 0,
            }
        )
    return catalog


def recent_sets_context(lib: Library, band: str = "Colt 46", n: int = 6) -> list[dict]:
    """A few recent sets (ordered song titles) as reference for flow — not to copy."""
    sets = lib.sets[(lib.sets["band"] == band) & lib.sets["setDate"].notna()]
    sets = sets.sort_values("setDate", ascending=False).head(n)
    title_by_id = {sid: t for sid, t in zip(lib.songs["songID"], lib.songs["title"])}

    out = []
    for _, s in sets.iterrows():
        songs = lib.set_songs[lib.set_songs["setID"] == s["setID"]].sort_values("songOrder")
        titles = [title_by_id.get(sid) for sid in songs["songID"] if title_by_id.get(sid)]
        if titles:
            out.append({"set": s["setName"], "date": str(s["setDate"]), "songs": titles})
    return out


def _system_text(lib: Library, band: str = "Colt 46") -> str:
    """System instruction = conventions + catalog + recent-set examples."""
    catalog = build_catalog(lib, band)
    recent = recent_sets_context(lib, band)
    return (
        SYSTEM_CONTEXT
        + "\n\nSONG CATALOG (JSON):\n"
        + json.dumps(catalog, ensure_ascii=False)
        + "\n\nRECENT SETS (reference for flow — do NOT copy verbatim):\n"
        + json.dumps(recent, ensure_ascii=False)
    )


# --------------------------------------------------------------------------- #
# The Gemini call
# --------------------------------------------------------------------------- #
def _client() -> genai.Client:
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key:
        raise AssistantError(
            "No Gemini API key found. Get a free key at https://aistudio.google.com/apikey "
            "and set GEMINI_API_KEY in your environment or in .streamlit/secrets.toml."
        )
    return genai.Client(api_key=key)


def _to_contents(messages: list[dict]) -> list[dict]:
    """Convert the app's user/assistant history to Gemini's user/model contents."""
    return [
        {"role": "model" if m["role"] == "assistant" else "user",
         "parts": [{"text": m["content"]}]}
        for m in messages
    ]


def _parse_set(text: str) -> dict:
    """Pull the JSON object out of the model's reply."""
    try:
        start, end = text.index("{"), text.rindex("}") + 1
        return json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError) as exc:
        raise AssistantError(f"Could not parse the assistant's response as a setlist.\n\n{text[:400]}") from exc


def run_turn(lib: Library, messages: list[dict], band: str = "Colt 46") -> tuple[dict, str]:
    """Send the conversation so far; return (parsed_set, raw_assistant_text).

    ``messages`` is the running message list (user/assistant turns). The returned
    raw text should be appended as the assistant turn by the caller so the current
    set stays in context for follow-up revisions.
    """
    client = _client()
    resp = client.models.generate_content(
        model=MODEL,
        contents=_to_contents(messages),
        config=types.GenerateContentConfig(
            system_instruction=_system_text(lib, band),
            response_mime_type="application/json",
            temperature=0.7,
            # Generous ceiling: Gemini 3.x spends part of the budget on reasoning
            # tokens, so a low cap can truncate the JSON mid-set.
            max_output_tokens=8192,
            # We use no tools; disabling AFC silences a noisy SDK warning.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        ),
    )
    raw = resp.text or ""
    return _parse_set(raw), raw


def resolve_titles(lib: Library, titles: list[str], band: str = "Colt 46") -> pd.DataFrame:
    """Map the model's chosen titles to full catalog rows (fuzzy-safe), in order."""
    catalog = {c["title"]: c for c in build_catalog(lib, band)}
    keys = list(catalog.keys())
    rows = []
    for t in titles:
        if t in catalog:
            rows.append(catalog[t])
            continue
        match = process.extractOne(t, keys, scorer=fuzz.token_sort_ratio)
        rows.append(catalog[match[0]] if match and match[1] >= 80 else {"title": t, "artist": "(not found)"})
    return pd.DataFrame(rows)


def _runtime_to_sec(mmss: str) -> int:
    try:
        m, s = mmss.split(":")
        return int(m) * 60 + int(s)
    except (ValueError, AttributeError):
        return 0


def estimate_runtime_min(setlist: pd.DataFrame, default_sec: int = 210) -> float:
    if "runtime" not in setlist.columns:
        return 0.0
    total = sum(_runtime_to_sec(r) or default_sec for r in setlist["runtime"])
    return round(total / 60.0, 1)
