import json

# Load the JSON data from the file
with open('SBPBackup20241223.json', 'r') as file:
    data = json.load(file)

my_songs =[]

for song in data['songs']:
    my_songs.append(dict(
                         id=song['Id']
                        ,artist=song['author']
                        ,title=song['name']
                        )
                    )
    
my_sets = []

for set in data['sets']:
    my_sets.append(dict(
                         id=set['details']['Id']
                        ,name=set['details']['name']
                        ,date=set['details']['date']
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
                                ,setName = detailSetName
                                ,songOrder=song['Order']
                                ,songID=song['SongId']                        
                                )
                            )
        
import pandas as pd

songs_df = pd.DataFrame(my_songs)
sets_df = pd.DataFrame(my_sets)
set_songs_df = pd.DataFrame(my_set_songs)

def getSongs():
    return songs_df

def getSets():
    return sets_df

def getSetSongs():
    return set_songs_df