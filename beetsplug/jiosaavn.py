"""
Adds JioSaavn support to the autotagger.
"""

import collections
import re
import time
from io import BytesIO

import requests
from beets.autotag.hooks import AlbumInfo, Distance, TrackInfo
from beets.dbcore import types
from beets.library import DateType
from beets.plugins import BeetsPlugin, get_distance
from musicapy.saavn_api.api import SaavnAPI
from PIL import Image


class JioSaavnPlugin(BeetsPlugin):
    data_source = 'JioSaavn'

    item_types = {
        'jiosaavn_album_id': types.INTEGER,
        'jiosaavn_artist_id': types.INTEGER,
        'jiosaavn_track_id': types.STRING,
        'jiosaavn_starring': types.STRING,
        'jiosaavn_perma_url': types.STRING,
        'jiosaavn_updated': DateType(),
        'cover_art_url': types.STRING,
    }

    def __init__(self):
        super().__init__()
        self.config.add({
            'source_weight': 0.5,
        })

    def album_distance(self, items, album_info, mapping):

        """Returns the album distance.
        """
        dist = Distance()
        if album_info.data_source == 'JioSaavn':
            dist.add('source', self.config['source_weight'].as_number())
        return dist

    def track_distance(self, item, track_info):

        """Returns the JioSaavn source weight and the maximum source weight
        for individual tracks.
        """
        return get_distance(
            data_source=self.data_source,
            info=track_info,
            config=self.config
        )

    jiosaavn = SaavnAPI()

    def get_albums(self, query):
        """Returns a list of AlbumInfo objects for a JioSaavn search query.
        """
        # Strip non-word characters from query. Things like "!" and "-" can
        # cause a query to return no results, even if they match the artist or
        # album title. Use `re.UNICODE` flag to avoid stripping non-english
        # word characters.
        query = re.sub(r'(?u)\W+', ' ', query)
        # Strip medium information from query, Things like "CD1" and "disk 1"
        # can also negate an otherwise positive result.
        query = re.sub(r'(?i)\b(CD|disc)\s*\d+', '', query)
        albums = []
        self._log.debug('Searching JioSaavn for: {}', query)
        try:
            data = self.jiosaavn.search_album(query)
        except Exception as e:
            self._log.debug('Invalid Search Error: {}'.format(e))
        for album in data["results"]:
            id = self.jiosaavn.create_identifier(album["perma_url"], 'album')
            album_details = self.jiosaavn.get_album_details(id)
            album_info = self.get_album_info(album_details, album["type"])
            albums.append(album_info)
        return albums

    def get_tracks(self, query):
        """Returns a list of TrackInfo objects for a JioSaavn search query.
        """
        # Strip non-word characters from query. Things like "!" and "-" can
        # cause a query to return no results, even if they match the artist or
        # album title. Use `re.UNICODE` flag to avoid stripping non-english
        # word characters.
        query = re.sub(r'(?u)\W+', ' ', query)
        # Strip medium information from query, Things like "CD1" and "disk 1"
        # can also negate an otherwise positive result.
        query = re.sub(r'(?i)\b(CD|disc)\s*\d+', '', query)
        tracks = []
        self._log.debug('Searching JioSaavn for: {}', query)
        try:
            data = self.jiosaavn.search_song(query)
        except Exception as e:
            self._log.debug('Invalid Search Error: {}'.format(e))
        for track in data["results"]:
            id = self.jiosaavn.create_identifier(track["perma_url"], 'song')
            song_details = self.jiosaavn.get_song_details(id)
            song_info = self._get_track(song_details["songs"][0])
            tracks.append(song_info)
        return tracks

    def candidates(self, items, artist, release, va_likely, extra_tags=None):
        """Returns a list of AlbumInfo objects for JioSaavn search results
        matching release and artist (if not various).
        """
        if va_likely:
            query = release
        else:
            query = f'{release} {artist}'
        try:
            return self.get_albums(query)
        except Exception as e:
            self._log.debug('JioSaavn Search Error: {}'.format(e))
            return []

    def item_candidates(self, item, artist, title):
        """Returns a list of TrackInfo objects for JioSaavn search results
        matching title and artist.
        """
        query = f'{title} {artist}'
        try:
            return self.get_tracks(query)
        except Exception as e:
            self._log.debug('JioSaavn Search Error: {}'.format(e))
            return []

    def get_album_info(self, item, type):
        """Returns an AlbumInfo object for a JioSaavn album.
        """
        album = item["title"].replace("&quot;", "\"")
        jiosaavn_album_id = item["albumid"]
        perma_url = item["perma_url"]
        artist_id = item["primary_artists_id"]
        year = item["year"]
        url = item["image"].replace("150x150", "500x500")
        if self.is_valid_image_url(url):
            cover_art_url = url
        if item["songs"][0]["label"] is not None:
            label = item["songs"][0]["label"]
        if item["release_date"] is not None:
            releasedate = item["release_date"].split("-")
            year = int(releasedate[0])
            month = int(releasedate[1])
            day = int(releasedate[2])
        artists = item["primary_artists"]
        songs = item["songs"]
        tracks = []
        medium_totals = collections.defaultdict(int)
        for i, song in enumerate(songs, start=1):
            track = self._get_track(song)
            track.index = i
            medium_totals[track.medium] += 1
            tracks.append(track)
        for track in tracks:
            track.medium_total = medium_totals[track.medium]
        return AlbumInfo(album=album,
                         album_id=jiosaavn_album_id,
                         jiosaavn_album_id=jiosaavn_album_id,
                         artist=artists,
                         artist_id=artist_id,
                         jiosaavn_artist_id=artist_id,
                         tracks=tracks,
                         albumtype=type,
                         year=year,
                         month=month,
                         day=day,
                         mediums=max(medium_totals.keys()),
                         data_source=self.data_source,
                         jiosaavn_perma_url=perma_url,
                         data_url=perma_url,
                         cover_art_url=cover_art_url,
                         label=label,
                         )

    def _get_track(self, track_data):
        """Convert a JioSaavn song object to a TrackInfo object.
        """
        if track_data['duration']:
            length = int(track_data['duration'].strip())
        elif track_data['more_info']['duration']:
            length = int(track_data['more_info']['duration'].strip())
        if track_data['singers'] == "":
            artist = track_data['music']
        else:
            artist = track_data['singers']
        if not track_data['starring'] == "":
            starring = track_data['starring']
        else:
            starring = None
        # Get album information for JioSaavn tracks
        return TrackInfo(
            title=track_data['song'].replace("&quot;", "\""),
            track_id=track_data['id'],
            jiosaavn_track_id=track_data['id'],
            artist=artist,
            album=track_data['album'].replace("&quot;", "\""),
            jiosaavn_artist_id=track_data["music_id"],
            length=length,
            data_source=self.data_source,
            jiosaavn_perma_url=track_data['perma_url'],
            jiosaavn_starring=starring,
            data_url=track_data['perma_url'],
            jiosaavn_updated=time.time(),
        )

    def album_for_id(self, release_id):
        """Fetches an album by its JioSaavn ID and returns an AlbumInfo object
        """
        if 'jiosaavn.com/album/' not in release_id:
            return None
        self._log.debug('Searching for album {0}', release_id)
        id = self.jiosaavn.create_identifier(release_id, 'album')
        album_details = self.jiosaavn.get_album_details(id)
        return self.get_album_info(album_details, 'album')

    def track_for_id(self, track_id=None):
        """Fetches a track by its JioSaavn ID and returns a TrackInfo object
        """
        if 'jiosaavn.com/song/' not in track_id:
            return None
        self._log.debug('Searching for track {0}', track_id)
        id = self.jiosaavn.create_identifier(track_id, 'song')
        song_details = self.jiosaavn.get_song_details(id)
        return self._get_track(song_details["songs"][0])

    def is_valid_image_url(sef, url):
        try:
            response = requests.get(url)
            Image.open(BytesIO(response.content))
            return True
        except:
            return False
