import json
import pandas as pd
from datetime import datetime


def load_data(backup_file=None):
    if backup_file is None:
        # Try to find a backup file
        import os
        possible_files = ['SBPBackup20260121.json', 'SBPBackup20241223.json', 'SBPBackups/SBPBackup20260121.json']
        for f in possible_files:
            if os.path.exists(f):
                backup_file = f
                break
        if backup_file is None:
            backup_file = 'SBPBackup20241223.json'  # fallback
    # Load the JSON data from the file
    with open(backup_file, 'r') as file:
        data = json.load(file)
    return data


# Load the JSON data from the file
data = load_data()

my_songs =[]

for song in data['songs']:
    my_songs.append(dict(
                         songID=song['Id']
                        ,artist=song['author']
                        ,title=song['name']
                        )
                    )
    
my_sets = []

for set in data['sets']:
    my_sets.append(dict(
                         setID=set['details']['Id']
                        ,setName=set['details']['name']
                        ,setDate=datetime.fromisoformat(set['details']['date'].replace('Z', '')).date()
                        )
                    )
    
my_set_songs = []
song_i =0

for set in data['sets']:
    detailSetID = set['details']['Id']
    detailSetName = set['details']['name']
    song_i = 0    
    for song in set['contents']:
        song_i += 1
        my_set_songs.append(dict(
                                # setID=song['SetId']
                                 setID = detailSetID
                                # ,setName = detailSetName
                                ,songOrder=song['Order']
                                ,songID=song['SongId']                        
                                )
                            ) 
        
def reload_data(backup_file):
    global data, my_songs, my_sets, my_set_songs, songs_df, sets_df, set_songs_df
    data = load_data(backup_file)
    
    my_songs = []
    for song in data['songs']:
        my_songs.append(dict(
                             songID=song['Id']
                            ,artist=song['author']
                            ,title=song['name']
                            )
                        )
    
    my_sets = []
    for set in data['sets']:
        my_sets.append(dict(
                             setID=set['details']['Id']
                            ,setName=set['details']['name']
                            ,setDate=datetime.fromisoformat(set['details']['date'].replace('Z', '')).date()
                            )
                        )
    
    my_set_songs = []
    for set in data['sets']:
        detailSetID = set['details']['Id']
        song_i = 0    
        for song in set['contents']:
            song_i += 1
            my_set_songs.append(dict(
                                    setID = detailSetID
                                    ,songOrder=song['Order']
                                    ,songID=song['SongId']                        
                                    )
                                ) 
        
    songs_df = pd.DataFrame(my_songs)
    sets_df = pd.DataFrame(my_sets)
    set_songs_df = pd.DataFrame(my_set_songs)

def getSongs():
    return songs_df

def getSets():
    return sets_df

def getSetSongs():
    return set_songs_df

def getMostPlayedSongs(top_n=10, months_back=None, exclude_set_names=None):
    # Filter sets by date if months_back is specified
    filtered_sets_df = sets_df.copy()
    
    if months_back is not None:
        from datetime import datetime, timedelta
        cutoff_date = datetime.now().date() - timedelta(days=months_back * 30)  # Approximate months
        filtered_sets_df = filtered_sets_df[filtered_sets_df['setDate'] >= cutoff_date]
    
    # Exclude sets by name if specified
    if exclude_set_names:
        for exclude_name in exclude_set_names:
            filtered_sets_df = filtered_sets_df[~filtered_sets_df['setName'].str.contains(exclude_name, case=False, na=False)]
    
    # Get setIDs that pass all filters
    valid_set_ids = filtered_sets_df['setID']
    filtered_set_songs_df = set_songs_df[set_songs_df['setID'].isin(valid_set_ids)]
    
    # Count occurrences of each songID in sets
    song_counts = filtered_set_songs_df['songID'].value_counts().reset_index()
    song_counts.columns = ['songID', 'play_count']
    
    # Merge with songs_df to get titles and artists
    most_played = song_counts.merge(songs_df, on='songID')
    
    # Sort by play_count descending
    most_played = most_played.sort_values('play_count', ascending=False)
    
    return most_played.head(top_n)