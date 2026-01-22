#!/usr/bin/env python3
"""
Script to analyze the most commonly played songs from SBP backup data.
Usage: python scripts/analyze_songs.py [backup_file.json] [top_n] [months_back] [exclude_set_names]
"""

import sys
import os

# Add parent directory to path so we can import Songs
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Parse command line arguments
backup_file = sys.argv[1] if len(sys.argv) > 1 else 'SBPBackup20241223.json'
top_n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
months_back = int(sys.argv[3]) if len(sys.argv) > 3 else None
exclude_set_names = sys.argv[4].split(',') if len(sys.argv) > 4 else None

try:
    import Songs
    if backup_file != 'SBPBackup20241223.json':
        Songs.reload_data(backup_file)
    print(f"✓ Successfully loaded data from {backup_file}")
except ImportError as e:
    print(f"✗ Failed to import Songs: {e}")
    sys.exit(1)

try:
    most_played = Songs.getMostPlayedSongs(top_n, months_back, exclude_set_names)
    filter_parts = []
    if months_back:
        filter_parts.append(f"last {months_back} months")
    if exclude_set_names:
        filter_parts.append(f"excluding sets with: {', '.join(exclude_set_names)}")
    filter_desc = f" ({', '.join(filter_parts)})" if filter_parts else ""
    print(f"✓ Successfully computed top {top_n} most played songs{filter_desc}")
except Exception as e:
    print(f"✗ Failed to compute most played songs: {e}")
    sys.exit(1)

filter_desc = ""
if months_back or exclude_set_names:
    filter_parts = []
    if months_back:
        filter_parts.append(f"filtered to last {months_back} months")
    if exclude_set_names:
        filter_parts.append(f"excluding sets containing: {', '.join(exclude_set_names)}")
    filter_desc = f" ({', '.join(filter_parts)})"

print(f"\n--- Most Commonly Played Songs (Top {top_n}){filter_desc} ---")
print(f"{'Rank':<5} {'Play Count':<12} {'Artist':<20} {'Title'}")
print("-" * 60)

for i, row in most_played.iterrows():
    rank = i + 1
    print(f"{rank:<5} {int(row['play_count']):<12} {row['artist'][:19]:<20} {row['title']}")

print("\n✓ Analysis complete!")