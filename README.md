# SetListMaker
An app to generate setlists for your band.

Takes data from [Songbook Pro](https://www.songbookapp.com/) (SBP) backup exports, parses the JSON, and builds DataFrames for songs, sets, and set memberships to analyze setlist data.

## Setup

### Prerequisites
- Python 3.14+ (tested with 3.14.0 on macOS; earlier versions 3.11+ may work)
- Virtual environment support

### 1. Create a Virtual Environment (outside the repo)

```bash
# Create a new venv outside the repo (recommended)
python3 -m venv ~/.venv-setlistmaker

# Activate it
source ~/.venv-setlistmaker/bin/activate
```

### 2. Install Dependencies

For **Python 3.14+** (recommended, modern dependencies):
```bash
pip install -r requirements-3.14.txt
```

For **Python 3.11–3.12** (legacy, original pinned versions):
```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables (if using Google Sheets integration)

If you plan to use the `gsheet.ipynb` notebook (which syncs with Google Sheets), set up your credentials:

1. Copy the template file:
   ```bash
   cp .env.example .env
   ```

2. Fill in your Google API credentials in `.env`:
   ```
   GOOGLE_SHEETS_ID=your_sheets_id_here
   GOOGLE_API_KEY=your_api_key_here
   ```

   To get these values:
   - Visit [Google Cloud Console](https://console.cloud.google.com/)
   - Create a new project or select an existing one
   - Enable the Google Sheets API
   - Create an API key credential
   - Get your Google Sheets ID from the URL: `https://docs.google.com/spreadsheets/d/{SHEETS_ID}/edit`

**Note:** `.env` is listed in `.gitignore` and will never be committed to the repo, keeping your credentials safe.

### 4. Verify Installation

Run the smoke-check script to confirm everything is working:

```bash
python scripts/inspect_backup.py
```

Expected output shows summary counts:
```
✓ Successfully imported Songs module
✓ Successfully loaded all DataFrames

--- Summary ---
Songs:       76 records
Sets:        70 records
Set Songs:   770 records

✓ All checks passed!
```

### Compatibility Notes

- **`requirements-3.14.txt`**: Updated for Python 3.14+. Uses `RapidFuzz` instead of `python-Levenshtein` (deprecated, incompatible with Python 3.14).
- **`requirements.txt`**: Original pinned versions from Python 3.12 environment. Use only with Python 3.11–3.12.

## Project Structure

- **`Songs.py`** – Core extraction module. Loads SBP backup JSON and exposes three accessor functions:
  - `getSongs()` – returns DataFrame of all songs (id, artist, title)
  - `getSets()` – returns DataFrame of all sets (id, name, date)
  - `getSetSongs()` – returns DataFrame of set memberships (setID, songID, songOrder)

- **`Songs.ipynb`** – Notebook where the SBP parsing logic was first explored; shows how DataFrames are built and joined.

- **`gsheet.ipynb`** – Notebook that experiments with fuzzy-matching SBP songs to a Google Sheets list (requires Google API credentials in `.env`; see Setup section).

- **`SBPBackup20241223.json`** – Sample SBP backup export (JSON format).

- **`scripts/inspect_backup.py`** – Smoke-check script that validates the environment and data loading.

## How to Use

### In a Notebook or Script

```python
import Songs

songs_df = Songs.getSongs()
sets_df = Songs.getSets()
set_songs_df = Songs.getSetSongs()

# Example: merge to get all details
set_details = set_songs_df.merge(sets_df, on='setID').merge(songs_df, on='songID')
print(set_details)
```

### Data from SBP Backup

To create a fresh SBP backup:
1. Open **SBP Manager** in your browser
2. Click the **?** icon (top right) → **BACKUP LIBRARY**
3. Rename the downloaded file to add `.zip` extension
4. Extract and find `dataFile.txt`
5. Remove the leading version string (e.g., `1.0`) and format as JSON
6. Save as `SBPBackupYYYYMMDD.json` in the repo root

## Notes

- The venv is stored outside the repo (e.g., `~/.venv-setlistmaker`) to keep the repo clean.
- See `Notes.md` for additional process notes on creating SBP exports.
- Requires Python 3.12.4+ (from system python3).