#!/usr/bin/env python3
"""
Smoke-check script: validates environment and loads SBP backup data.
Run this to confirm that Songs.py can load the backup JSON correctly.
"""

import sys
import os

# Add parent directory to path so we can import Songs
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import Songs
    print("✓ Successfully imported Songs module")
except ImportError as e:
    print(f"✗ Failed to import Songs: {e}")
    sys.exit(1)

try:
    songs_df = Songs.getSongs()
    sets_df = Songs.getSets()
    set_songs_df = Songs.getSetSongs()
    print("✓ Successfully loaded all DataFrames")
except Exception as e:
    print(f"✗ Failed to load DataFrames: {e}")
    sys.exit(1)

# Print summary
print("\n--- Summary ---")
print(f"Songs:       {len(songs_df)} records")
print(f"Sets:        {len(sets_df)} records")
print(f"Set Songs:   {len(set_songs_df)} records")

if len(songs_df) > 0:
    print(f"\nFirst song: {songs_df.iloc[0]['artist']} - {songs_df.iloc[0]['title']}")

if len(sets_df) > 0:
    print(f"First set: {sets_df.iloc[0]['setName']} ({sets_df.iloc[0]['setDate']})")

print("\n✓ All checks passed!")
