"""
Adds Youtube support to the autotagger.
"""

import collections
import os
import re
import time
from io import BytesIO

import requests
from beets import config, ui
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
        'yt_artist_id': types.STRING,
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
        self.exclude_fields = self.config["exclude_fields"].as_str_seq()
        self.yt = YTMusic(os.path.join(config.config_dir(), 'oauth.json'))

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

    def commands(self):
        """Add beet UI commands to interact with Youtube."""
        ytupdate_cmd = ui.Subcommand(
            'ytupdate', help=f'Update {self.data_source} views')

        def func(lib, opts, args):
            items = lib.items(ui.decargs(args))
            self._ytupdate(items, ui.should_write())

        ytupdate_cmd.func = func

        return [ytupdate_cmd]

    def _ytupdate(self, items, write):
        """Obtain view count from Youtube."""
        for index, item in enumerate(items, start=1):
            self._log.info('Processing {}/{} tracks - {} ',
                           index, len(items), item)
            try:
                yt_track_id = item.yt_track_id
            except AttributeError:
                self._log.debug('No yt_track_id present for: {}', item)
                continue
            try:
                yt_track_id = item.yt_track_id
            except AttributeError:
                self._log.debug('No yt_track_id present for: {}', item)
            try:
                views = self.get_yt_views(yt_track_id)
                views = self.get_yt_views(yt_track_id)
                self._log.debug('YouTube videoId: {} has {} views',
                                yt_track_id, views)
            except Exception as e:
                self._log.debug('Invalid YouTube videoId: {}', e)
                continue
            item.yt_views = views
            item.yt_updated = time.time()
            item.store()
            if write:
                item.try_write()

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
        self._log.debug('Searching Youtube for album: {}', query)
        try:
            data = self.yt.search(query, 'albums', limit=5)
        except Exception as e:
            self._log.debug('Invalid Search Error: {}'.format(e))
        for album in data:
            self._log.debug('Found album: {} with browseID: {}',
                            album['title'], album['browseId'])
            id = album['browseId']
            album_details = self.yt.get_album(id)
            album_info = self.get_album_info(album_details, id)
            albums.append(album_info)
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
        self._log.debug('Searching YouTube for track: {}', query)
        try:
            data = self.yt.search(query, 'songs', limit=5)
        except Exception as e:
            self._log.debug('Invalid Search Error: {}'.format(e))
        for track in data:
            id = track["videoId"]
            song_details = self.yt.get_song(id)
            song_info = self._get_track(song_details['videoDetails'])
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
        yt_album_id = browseID
        yt_artist_id = item['artists'][0].get('id', '')
        year = item["year"]
        url = item['thumbnails'][-1]['url']
        if self.is_valid_image_url(url) and \
            'cover_art_url' not in self.exclude_fields:
            cover_art_url = url
        else:
            cover_art_url = None
        yt_artists = item['artists'][0].get('name', '')
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
        if 'album_id' not in self.exclude_fields:
            album_id = yt_album_id
        else:
            album_id = None
        if 'artist_id' not in self.exclude_fields:
            artist_id = yt_artist_id
        else:
            artist_id = None
        if 'artist' not in self.exclude_fields:
            artists = yt_artists
        else:
            artists = None            
        return AlbumInfo(album=album,
                         album_id=album_id,
                         yt_album_id=yt_album_id,
                         artist=artists,
                         artist_id=artist_id,
                         yt_artist_id=yt_artist_id,
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
        self._log.debug('track_data: {}', track_data)
        id = track_data.get('videoId', '')
        self._log.debug('id: {}', id)
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

    # def track_for_id(self, track_id=None):
    #     """Fetches a track by its YouTube ID and returns a TrackInfo object
    #     """
    #     self._log.debug('Searching for track {0}', track_id)
    #     song_details = self.yt.get_song(track_id)
    #     return self._get_track(song_details['videoDetails'])

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
