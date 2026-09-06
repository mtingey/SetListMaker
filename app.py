"""SetListMaker — a mobile-friendly web app for exploring band data and
generating setlists from SongBook Pro backups.

Run locally:
    streamlit run app.py
"""

from __future__ import annotations

import base64
import os

import pandas as pd
import streamlit as st
from PIL import Image

from setlist.data import load_library, list_backups, Library
from setlist import analytics, generator, sheet, assistant

# Order of instrument blocks when grouping a setlist by Dale's guitar.
INSTRUMENT_ORDER = ["acoustic", "either", "electric"]

# Bands whose songs should never be offered for a Colt 46 setlist.
EXCLUDE_BANDS = {"MM6", "MM6 XMAS"}

LOGO_PATH = os.path.join(os.path.dirname(__file__), "assets", "colt46_logo.jpg")
try:
    _LOGO = Image.open(LOGO_PATH)
except Exception:
    _LOGO = None

st.set_page_config(
    page_title="Colt 46 Setlist Maker",
    page_icon=_LOGO if _LOGO is not None else "🎸",
    layout="wide",
)


@st.cache_data(show_spinner=False)
def _logo_b64(path: str, _mtime: float) -> str:
    with open(path, "rb") as fh:
        return base64.b64encode(fh.read()).decode()


def _brand_header() -> None:
    """Logo + Colt 46 wordmark + a green/steel accent rule, plus theme CSS."""
    st.markdown(
        """
        <style>
          h1, h2, h3 { letter-spacing: .4px; }
          [data-testid="stMetricValue"] { color: #1FA83C; }
          hr { border-color: #263230; }
          .c46-brand { display:flex; align-items:center; gap:16px; margin:2px 0 0; }
          .c46-brand .wm .t { font-weight:800; font-size:2.1rem; color:#E9EDEB; letter-spacing:1px; line-height:1; }
          .c46-brand .wm .t .dot { color:#1FA83C; }
          .c46-brand .wm .s { font-size:.8rem; letter-spacing:4px; color:#7C9599; text-transform:uppercase; margin-top:4px; }
          .c46-rule { height:3px; border-radius:2px; margin:10px 0 16px;
                      background:linear-gradient(90deg,#1FA83C 0%,#1FA83C 24%,#40585C 24%,#40585C 100%); }
          .stTabs [data-baseweb="tab-list"] { gap:2px; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    img = ""
    if _LOGO is not None:
        b64 = _logo_b64(LOGO_PATH, os.path.getmtime(LOGO_PATH))
        img = f'<img src="data:image/jpeg;base64,{b64}" width="66" height="66" style="border-radius:8px"/>'
    st.markdown(
        f"""
        <div class="c46-brand">
          {img}
          <div class="wm"><div class="t">COLT<span class="dot">.</span>46</div>
          <div class="s">Setlist Maker</div></div>
        </div>
        <div class="c46-rule"></div>
        """,
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------------- #
# Data loading (cached by file path + modified time)
# --------------------------------------------------------------------------- #
@st.cache_data(show_spinner="Loading backup…")
def _load(path: str, _mtime: float) -> Library:
    return load_library(path)


@st.cache_data(show_spinner=False)
def _load_sheet(csv_path: str | None, _mtime: float, _src: str) -> pd.DataFrame:
    """Match report for the current library + song-detail sheet (cached)."""
    return sheet.match_to_library(_load(_src, os.path.getmtime(_src)))


def get_sheet_match(lib: Library) -> pd.DataFrame:
    csv_path = sheet.find_song_sheet()
    if csv_path is None:
        return pd.DataFrame()
    return _load_sheet(csv_path, os.path.getmtime(csv_path), lib.source_file)


def get_library() -> Library | None:
    backups = list_backups()
    if not backups:
        st.error("No SBP backup files found in `SBPBackups/`. Add a backup `.json` there.")
        return None

    labels = [os.path.basename(b) for b in backups]
    choice = st.sidebar.selectbox("Backup file", labels, index=0)
    path = backups[labels.index(choice)]
    return _load(path, os.path.getmtime(path))


def _ensure_api_key() -> None:
    """Copy the Gemini key/model from Streamlit secrets into the env if present."""
    try:
        for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMINI_MODEL"):
            if not os.getenv(name) and name in st.secrets:
                os.environ[name] = st.secrets[name]
    except Exception:
        pass  # no secrets file configured


def _fmt_minutes(total_sec: int | float | None) -> str:
    if total_sec is None or pd.isna(total_sec) or total_sec <= 0:
        return "—"
    m, s = divmod(int(total_sec), 60)
    return f"{m}:{s:02d}"


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #
def page_overview(lib: Library) -> None:
    st.subheader("Library overview")
    s = analytics.library_summary(lib)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Songs", s["songs"])
    c2.metric("Sets", s["sets"])
    c3.metric("Bands", s["bands"])
    c4.metric("Song appearances", s["song_appearances"])

    st.caption(
        f"Duration data is present for **{s['songs_with_duration']} of {s['songs']} songs "
        f"({s['duration_coverage_pct']:.0f}%)** — runtime figures are a lower bound until "
        "song lengths are filled in (that's where the Google Sheet will help)."
    )

    st.markdown("#### Bands")
    overview = analytics.band_overview(lib)
    st.dataframe(
        overview.rename(
            columns={
                "band": "Band",
                "songs_in_library": "Songs in library",
                "sets_played": "Sets played",
                "avg_songs_per_set": "Avg songs/set",
                "avg_runtime_min": "Avg runtime (min)*",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )
    st.caption(
        "*Avg runtime is computed only from sets that have any song-length data, so it "
        "understates real set length while durations are sparse. Sets are attributed to a "
        "band by the folder membership of the songs they contain."
    )


def page_analytics(lib: Library, band: str | None) -> None:
    st.subheader("Analytics")
    band_label = band or "All bands"

    with st.expander("Filters", expanded=False):
        col1, col2 = st.columns(2)
        months = col1.number_input(
            "Only sets from the last N months (0 = all time)", min_value=0, value=0, step=1
        )
        exclude_raw = col2.text_input(
            "Exclude sets whose name contains (comma-separated)", value=""
        )
    months_back = int(months) or None
    exclude = [x for x in (exclude_raw.split(",") if exclude_raw else []) if x.strip()]

    st.markdown(f"#### Top 50 most-played songs — {band_label}")
    top = analytics.most_played_songs(
        lib, band=band, top_n=50, months_back=months_back, exclude_name_contains=exclude
    )
    if top.empty:
        st.info("No plays found for this filter.")
    else:
        show = top[["rank", "artist", "title", "play_count", "last_played"]].rename(
            columns={
                "rank": "#",
                "artist": "Artist",
                "title": "Title",
                "play_count": "Plays",
                "last_played": "Last played",
            }
        )
        st.dataframe(show, use_container_width=True, hide_index=True, height=520)

    st.markdown(f"#### Deep cuts — least played in {band_label}")
    st.caption("Songs in the library that rarely (or never) make the setlist — candidates to rotate back in.")
    rare = analytics.rarely_played(lib, band=band, bottom_n=25)
    st.dataframe(
        rare.rename(columns={"artist": "Artist", "title": "Title", "play_count": "Plays"}),
        use_container_width=True,
        hide_index=True,
    )


def _render_assistant_set(lib: Library, result: dict) -> None:
    """Show a set produced by the assistant (table, runtime, notes, export)."""
    songs = result.get("songs", [])
    if not songs:
        st.warning("The assistant didn't return any songs.")
        return
    rows = assistant.resolve_titles(lib, songs)
    rows = rows.reset_index(drop=True)
    rows.insert(0, "#", range(1, len(rows) + 1))

    st.markdown(f"### {result.get('set_name', 'Setlist')}")
    est = assistant.estimate_runtime_min(rows)
    c1, c2 = st.columns(2)
    c1.metric("Songs", len(rows))
    c2.metric("Est. runtime", f"~{est:.0f} min")

    cols = [c for c in ["#", "title", "artist", "vocals", "guitar", "feel", "energy", "runtime"] if c in rows.columns]
    disp = rows[cols].rename(columns={
        "title": "Title", "artist": "Artist", "vocals": "Vocals",
        "guitar": "Dale", "feel": "Feel", "energy": "Energy", "runtime": "Length",
    })
    if "Dale" in disp.columns:
        disp["Dale"] = disp["Dale"].astype(str).str.capitalize()
    st.dataframe(disp, use_container_width=True, hide_index=True, height=460)

    if result.get("notes"):
        st.caption(f"💬 {result['notes']}")

    lines = [f"{r['#']}. {r['title']} — {r['artist']}" for _, r in rows.iterrows()]
    st.download_button(
        "⬇️ Download as text", data="\n".join(lines),
        file_name="assistant_setlist.txt", mime="text/plain", use_container_width=True,
    )


def page_assistant(lib: Library) -> None:
    st.subheader("🤖 Setlist assistant")
    st.caption(
        "Ask in plain language, then refine. Examples: *“Give me an opening set for a "
        "night at the Westerner.”* · *“The crowd is dancing tonight — a second set with "
        "danceable, high-energy songs and only one slow one.”* · *“Swap out Lot of Leavin.”*"
    )

    # Session state for the running conversation.
    st.session_state.setdefault("asst_messages", [])
    st.session_state.setdefault("asst_set", None)

    if sheet.find_song_sheet() is None:
        st.info("The assistant uses the C46 song sheet, which isn't loaded.")
        return

    has_set = st.session_state.asst_set is not None
    label = "Revise the set" if has_set else "Describe the set you want"
    placeholder = ("e.g. replace Lot of Leavin with something more upbeat"
                   if has_set else "e.g. an opening set for a night at the Outlaw")

    with st.form("asst_form", clear_on_submit=True):
        prompt = st.text_area(label, placeholder=placeholder, height=80)
        c1, c2 = st.columns([3, 1])
        submitted = c1.form_submit_button(
            "✨ Revise" if has_set else "✨ Generate set", use_container_width=True
        )
        cleared = c2.form_submit_button("🗑️ New", use_container_width=True)

    if cleared:
        st.session_state.asst_messages = []
        st.session_state.asst_set = None
        st.rerun()

    if submitted and prompt.strip():
        st.session_state.asst_messages.append({"role": "user", "content": prompt.strip()})
        try:
            with st.spinner("Thinking about your set…"):
                parsed, raw = assistant.run_turn(lib, st.session_state.asst_messages)
            st.session_state.asst_messages.append({"role": "assistant", "content": raw})
            st.session_state.asst_set = parsed
        except assistant.AssistantError as e:
            # Roll back the user turn so the next attempt is clean.
            st.session_state.asst_messages.pop()
            st.error(str(e))
        except Exception as e:  # API/network errors
            st.session_state.asst_messages.pop()
            st.error(f"Assistant call failed: {e}")

    if st.session_state.asst_set:
        _render_assistant_set(lib, st.session_state.asst_set)

    # Show the prompt history so the conversation context is visible.
    user_turns = [m["content"] for m in st.session_state.asst_messages if m["role"] == "user"]
    if user_turns:
        with st.expander("Conversation so far"):
            for i, t in enumerate(user_turns, 1):
                st.markdown(f"**{i}.** {t}")


def page_generate(lib: Library, band: str | None, match_df: pd.DataFrame) -> None:
    st.subheader("Generate a setlist")
    if band is None:
        st.info("Pick a band in the sidebar to generate a setlist for it.")
        return

    # Instrument data available for this band's songs (from the song sheet).
    instrument_by_song: dict = {}
    if not match_df.empty:
        band_song_ids = set(
            lib.songs[lib.songs["band_names"].apply(lambda n: band in (n or []))]["songID"]
        )
        instrument_by_song = {
            int(r.songID): r.instrument
            for r in match_df.itertuples()
            if r.instrument and int(r.songID) in band_song_ids
        }

    with st.form("gen"):
        col1, col2, col3 = st.columns(3)
        mode = col1.radio("Target by", ["Song count", "Minutes"], horizontal=False)
        n_songs = col2.number_input("Number of songs", min_value=1, max_value=60, value=12)
        target_min = col3.number_input("Target minutes", min_value=5, max_value=240, value=45)

        col4, col5 = st.columns(2)
        favor = col4.selectbox(
            "Song selection",
            ["popular", "balanced", "fresh"],
            format_func={
                "popular": "Favor crowd-tested favorites",
                "balanced": "Balanced across the library",
                "fresh": "Favor deep cuts / rotate in",
            }.get,
        )
        seed_raw = col5.text_input("Seed (optional, for repeatable results)", value="")

        avoid_last = st.checkbox("Avoid songs from the band's most recent set", value=False)
        n_instr = len(instrument_by_song)
        group_by_guitar = st.checkbox(
            f"Group by Dale's guitar — acoustic together, then electric "
            f"({n_instr} songs tagged)",
            value=n_instr > 0,
            disabled=n_instr == 0,
            help="Uses the 'Dale Guitar' column from the song sheet." if n_instr
            else "No guitar data matched for this band's songs.",
        )
        submitted = st.form_submit_button("🎲 Generate", use_container_width=True)

    if not submitted:
        return

    avoid_ids: set = set()
    if avoid_last:
        band_sets = lib.sets[(lib.sets["band"] == band) & lib.sets["setDate"].notna()]
        if not band_sets.empty:
            last_set_id = band_sets.sort_values("setDate").iloc[-1]["setID"]
            avoid_ids = set(lib.set_songs[lib.set_songs["setID"] == last_set_id]["songID"])

    seed = int(seed_raw) if seed_raw.strip().isdigit() else None

    setlist = generator.generate_setlist(
        lib,
        band=band,
        n_songs=int(n_songs) if mode == "Song count" else None,
        target_minutes=int(target_min) if mode == "Minutes" else None,
        favor=favor,
        avoid_song_ids=avoid_ids,
        instrument_by_song=instrument_by_song if group_by_guitar else None,
        instrument_order=INSTRUMENT_ORDER,
        seed=seed,
    )

    if setlist.empty:
        st.warning("Couldn't build a setlist — no eligible songs for this band.")
        return

    est = generator.estimate_runtime_minutes(setlist)
    c1, c2 = st.columns(2)
    c1.metric("Songs", len(setlist))
    c2.metric("Est. runtime", f"~{est:.0f} min")

    cols = ["position", "title", "artist"]
    rename = {"position": "#", "title": "Title", "artist": "Artist"}
    if group_by_guitar and instrument_by_song:
        cols.append("instrument")
        rename["instrument"] = "Dale"
    cols.append("play_count")
    rename["play_count"] = "Plays"
    show = setlist[cols].rename(columns=rename)
    if "Dale" in show.columns:
        show["Dale"] = show["Dale"].fillna("").str.capitalize()
    st.dataframe(show, use_container_width=True, hide_index=True, height=460)

    # Plain-text version for copy/paste to the stage / bandmates.
    def _line(row) -> str:
        tag = ""
        if group_by_guitar and instrument_by_song and row.instrument:
            tag = f"  [{row.instrument}]"
        return f"{row.position}. {row.title} — {row.artist}{tag}"

    lines = [_line(row) for row in setlist.itertuples()]
    st.download_button(
        "⬇️ Download as text",
        data="\n".join(lines),
        file_name=f"{band.replace(' ', '_')}_setlist.txt",
        mime="text/plain",
        use_container_width=True,
    )
    with st.expander("Copy as text"):
        st.code("\n".join(lines), language=None)

    if group_by_guitar and instrument_by_song:
        st.caption(
            "Songs are grouped acoustic → (either) → electric to minimize Dale's "
            "guitar swaps. Songs with no sheet match fall at the end."
        )


def page_browse(lib: Library, band: str | None, match_df: pd.DataFrame) -> None:
    st.subheader("Browse")
    tab_songs, tab_sets = st.tabs(["Songs", "Sets"])

    with tab_songs:
        songs = lib.songs.copy()
        # Attach Dale-guitar + feel from the matched song sheet.
        if not match_df.empty:
            songs = songs.merge(
                match_df[["songID", "instrument", "feel"]], on="songID", how="left"
            )
        else:
            songs["instrument"] = None
            songs["feel"] = None

        if band:
            songs = songs[songs["band_names"].apply(lambda n: band in (n or []))]
        query = st.text_input("Search songs (title or artist)", key="song_search")
        if query:
            q = query.lower()
            songs = songs[
                songs["title"].str.lower().str.contains(q, na=False)
                | songs["artist"].str.lower().str.contains(q, na=False)
            ]
        disp = songs[
            ["artist", "title", "instrument", "feel", "duration", "key", "tempo", "band_names"]
        ].copy()
        disp["duration"] = disp["duration"].apply(_fmt_minutes)
        disp["instrument"] = disp["instrument"].fillna("").str.capitalize()
        disp["feel"] = disp["feel"].fillna("")
        disp["band_names"] = disp["band_names"].apply(lambda n: ", ".join(n) if n else "")
        st.dataframe(
            disp.rename(
                columns={
                    "artist": "Artist",
                    "title": "Title",
                    "instrument": "Dale",
                    "feel": "Feel",
                    "duration": "Length",
                    "key": "Key",
                    "tempo": "BPM",
                    "band_names": "Bands",
                }
            ),
            use_container_width=True,
            hide_index=True,
            height=520,
        )
        st.caption(f"{len(disp)} songs")

    with tab_sets:
        sets = lib.sets.copy()
        if band:
            sets = sets[sets["band"] == band]
        sets = sets.sort_values("setDate", ascending=False, na_position="last")
        disp = sets[["setName", "setDate", "band", "n_songs", "runtime_sec"]].copy()
        disp["runtime_sec"] = disp["runtime_sec"].apply(_fmt_minutes)
        st.dataframe(
            disp.rename(
                columns={
                    "setName": "Set",
                    "setDate": "Date",
                    "band": "Band",
                    "n_songs": "Songs",
                    "runtime_sec": "Runtime*",
                }
            ),
            use_container_width=True,
            hide_index=True,
            height=520,
        )
        st.caption(f"{len(disp)} sets · *Runtime is partial until song lengths are complete.")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> None:
    if _LOGO is not None:
        st.logo(_LOGO)
    _brand_header()
    _ensure_api_key()

    lib = get_library()
    if lib is None:
        return

    st.sidebar.markdown("---")
    selectable = [b for b in lib.band_names if b not in EXCLUDE_BANDS]
    band_options = ["All bands"] + selectable
    default_idx = band_options.index("Colt 46") if "Colt 46" in band_options else 0
    band_choice = st.sidebar.selectbox("Band", band_options, index=default_idx)
    band = None if band_choice == "All bands" else band_choice
    st.sidebar.caption(f"Loaded: `{os.path.basename(lib.source_file)}`")

    match_df = get_sheet_match(lib)
    if not match_df.empty:
        n_instr = int(match_df["instrument"].notna().sum())
        st.sidebar.caption(f"Song sheet matched: **{n_instr}** songs have Dale-guitar data")

    tab_asst, tab_gen, tab_analytics, tab_overview, tab_browse = st.tabs(
        ["🤖 Assistant", "🎲 Generate", "📊 Analytics", "🏠 Overview", "🔎 Browse"]
    )
    with tab_asst:
        page_assistant(lib)
    with tab_gen:
        page_generate(lib, band, match_df)
    with tab_analytics:
        page_analytics(lib, band)
    with tab_overview:
        page_overview(lib)
    with tab_browse:
        page_browse(lib, band, match_df)


if __name__ == "__main__":
    main()
