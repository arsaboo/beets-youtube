"""
Adds Youtube support to the autotagger.
"""

import collections
import os
import re
import time
from io import BytesIO

import requests
from beets import config
from beets.autotag.hooks import AlbumInfo, Distance, TrackInfo
from beets.dbcore import types
from beets.library import DateType
from beets.plugins import BeetsPlugin, get_distance
from PIL import Image
from ytmusicapi import YTMusic


class YouTubePlugin(BeetsPlugin):
    data_source = 'YouTube'

    item_types = {
        'yt_album_id': types.STRING,
        'yt_artist_id': types.INTEGER,
        'yt_track_id': types.STRING,
        'yt_updated': DateType(),
        'yt_views': types.INTEGER,
        'cover_art_url': types.STRING,
    }

    def __init__(self):
        super().__init__()
        self.config.add({
            'source_weight': 0.5,
        })
        #self.config_dir = config.config_dir()

    def album_distance(self, items, album_info, mapping):

        """Returns the album distance.
        """
        dist = Distance()
        if album_info.data_source == 'YouTube':
            dist.add('source', self.config['source_weight'].as_number())
        return dist

    def track_distance(self, item, track_info):

        """Returns the Youtube source weight and the maximum source weight
        for individual tracks.
        """
        return get_distance(
            data_source=self.data_source,
            info=track_info,
            config=self.config
        )

    yt = YTMusic(os.path.join(config.config_dir(), 'oauth.json'))
    # yt = YTMusic('oauth.json')

    def get_albums(self, query):
        """Returns a list of AlbumInfo objects for a Youtube search query.
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
        self._log.debug('Searching Youtube for: {}', query)
        try:
            data = self.yt.search(query, 'albums', limit=5)
        except Exception as e:
            self._log.debug('Invalid Search Error: {}'.format(e))
        for album in data:
            self._log.debug('Found album: {} with browseID: {}',
                            album['title'], album['browseId'])
            id = album['browseId']
            album_details = self.yt.get_album(id)
            # add browseID to album_details
            album_details['browseId'] = id
            album_info = self.get_album_info(album_details, id)
            albums.append(album_info)
            self._log.debug('returned album: {}', album_info)
        return albums

    def get_tracks(self, query):
        """Returns a list of TrackInfo objects for a YouTube search query.
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
        self._log.debug('Searching YouTube for: {}', query)
        try:
            data = self.yt.search(query, 'songs', limit=5)
        except Exception as e:
            self._log.debug('Invalid Search Error: {}'.format(e))
        for track in data:
            id = track["videoId"]
            song_details = self.yt.get_song(id)
            song_info = self._get_track(song_details)
            tracks.append(song_info)
        return tracks

    def candidates(self, items, artist, release, va_likely, extra_tags=None):
        """Returns a list of AlbumInfo objects for YouTube search results
        matching release and artist (if not various).
        """
        if va_likely:
            query = release
        else:
            query = f'{release} {artist}'
        try:
            return self.get_albums(query)
        except Exception as e:
            self._log.debug('YouTube Search Error: {}'.format(e))
            return []

    def item_candidates(self, item, artist, title):
        """Returns a list of TrackInfo objects for YouTube search results
        matching title and artist.
        """
        query = f'{title} {artist}'
        try:
            return self.get_tracks(query)
        except Exception as e:
            self._log.debug('YouTube track Search Error: {}'.format(e))
            return []

    def get_album_info(self, item, browseID):
        """Returns an AlbumInfo object for a YouTube album.
        """
        self._log.debug('item: {}', item)
        album = item["title"].replace("&quot;", "\"")
        type = item["type"]
        #yt_album_id = browseID
        yt_album_id = item["browseID"]
        artist_id = item['artists'][0].get('id', '')
        year = item["year"]
        url = item['thumbnails'][-1]['url']
        if self.is_valid_image_url(url):
            cover_art_url = url
        artists = item['artists'][0].get('name', '')
        self._log.debug('artists: {}', artists)
        songs = item["tracks"]
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
                         album_id=yt_album_id,
                         yt_album_id=yt_album_id,
                         artist=artists,
                         artist_id=artist_id,
                         yt_artist_id=artist_id,
                         tracks=tracks,
                         albumtype=type,
                         year=year,
                         mediums=max(medium_totals.keys()),
                         data_source=self.data_source,
                         cover_art_url=cover_art_url,
                         yt_updated=time.time()
                         )

    def _get_track(self, track_data):
        """Convert a Youtube song object to a TrackInfo object.
        """
        id = track_data.get('videoId', '')
        views = self.get_yt_views(id)
        # Get track information for YouTube tracks
        return TrackInfo(
            title=track_data.get('title').replace("&quot;", "\""),
            track_id=id,
            yt_track_id=id,
            artist=track_data.get('artists', '')[0].get('name', ''),
            album=track_data.get('album').replace("&quot;", "\""),
            yt_artist_id=track_data.get('artists', '')[0].get('id', ''),
            length=track_data.get('duration_seconds', 0),
            yt_views=views,
            data_source=self.data_source,
            yt_updated=time.time(),
        )

    def album_for_id(self, browseId):
        """Fetches an album by its YouTube browseID and returns an AlbumInfo object
        """
        self._log.debug('Searching for album {0}', browseId)
        album_details = self.yt.get_album(browseId)
        return self.get_album_info(album_details, 'album')

    def track_for_id(self, track_id=None):
        """Fetches a track by its YouTube ID and returns a TrackInfo object
        """
        self._log.debug('Searching for track {0}', track_id)
        song_details = self.yt.get_song(track_id)
        return self._get_track(song_details)

    def is_valid_image_url(self, url):
        try:
            response = requests.get(url)
            Image.open(BytesIO(response.content))
            return True
        except:
            return False

    def get_yt_views(self, id):
        try:
            views = self.yt.get_song(id)['videoDetails']['viewCount']
            return views
        except:
            return None
