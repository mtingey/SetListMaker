# Fuzzy Matching Migration: fuzzyset → RapidFuzz

## Why the Change?

- **fuzzyset** depends on `python-Levenshtein`, which doesn't compile on Python 3.14+
- **RapidFuzz** is faster, actively maintained, and has no C extension issues
- Both use Levenshtein distance under the hood, but RapidFuzz is more modern

## API Differences

### Old Code (fuzzyset)
```python
import fuzzyset as fs

# Create a fuzzy set (pre-indexed)
song_set = fs.FuzzySet(song_titles)

# Query with single result
result = song_set.get('7+7')  # Returns: [(score, 'matched_string')]
score, matched = result[0] if result else (0, None)
```

### New Code (RapidFuzz)
```python
from rapidfuzz import process, fuzz

# No pre-indexing needed; query directly against list
songs_list = song_titles  # same list

# Query with best match
result = process.extractOne('7+7', songs_list, scorer=fuzz.token_sort_ratio)
# Returns: ('matched_string', score, index)
matched, score, index = result if result else (None, 0, -1)
```

## Migration Steps

### Simple Case: Get Best Match
**Before:**
```python
match = song_set.get(query)
if match:
    score, matched_song = match[0]
else:
    score, matched_song = 0, None
```

**After:**
```python
match = process.extractOne(query, songs_list, scorer=fuzz.token_sort_ratio)
if match:
    matched_song, score, index = match
else:
    matched_song, score = None, 0
```

### Performance Case: Get Top-N Matches
**Before:**
```python
results = song_set.get(query)  # Returns all matches, sorted by score
```

**After:**
```python
results = process.extract(query, songs_list, limit=10, scorer=fuzz.token_sort_ratio)
# Returns: [('match1', score1, index1), ('match2', score2, index2), ...]
```

## Scoring Considerations

RapidFuzz offers multiple scorers (choose one):
- **`fuzz.ratio`** – Direct Levenshtein distance (0–100)
- **`fuzz.partial_ratio`** – Best match within substring
- **`fuzz.token_sort_ratio`** – Sorts tokens before comparison (recommended for song titles with reordered words)
- **`fuzz.token_set_ratio`** – Handles duplicate tokens

For song titles, **`token_sort_ratio`** usually works best.

## Updated gsheet.ipynb

See the refactored cell in `gsheet.ipynb` that uses RapidFuzz instead of fuzzyset.
