"""
Adds Youtube support to the autotagger.
"""

import collections
import os
import re
import time
from io import BytesIO
from difflib import SequenceMatcher

import requests
from beets import config, importer, ui
from beets.autotag.hooks import AlbumInfo, Distance, TrackInfo
from beets.dbcore import types
from beets.library import DateType
from beets.plugins import BeetsPlugin, get_distance
from PIL import Image
from ytmusicapi import YTMusic


def extend_reimport_fresh_fields_item():
    """Extend the REIMPORT_FRESH_FIELDS_ITEM list so that these fields
    are updated during reimport."""

    importer.REIMPORT_FRESH_FIELDS_ITEM.extend([
        'yt_album_id', 'yt_artist_id', 'yt_track_id',
        'yt_updated', 'yt_views'])


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
            'exclude_fields': [],
        })
        if self.config["exclude_fields"].exists():
            self.exclude_fields = self.config["exclude_fields"].as_str_seq()
        self.yt = YTMusic(os.path.join(config.config_dir(), 'oauth.json'))

    def album_distance(self, items, album_info, mapping):
        """Returns the album distance.
        """
        dist = Distance()
        if album_info.data_source == 'YouTube':
            dist.add('source',
                     float(self.config['source_weight'].get()))
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
            return albums
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
            return tracks
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
        album = item["title"].replace("&quot;", "\"")
        type = item["type"]
        yt_album_id = browseID
        yt_artist_id = item['artists'][0].get('id', '')
        year = item["year"]
        url = item['thumbnails'][-1]['url']
        if 'cover_art_url' not in self.config['exclude_fields'].as_str_seq():
            if self.is_valid_image_url(url):
                cover_art_url = url
            else:
                cover_art_url = None
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
        return AlbumInfo(album=album,
                         album_id=yt_album_id,
                         yt_album_id=yt_album_id,
                         artist=yt_artists,
                         artist_id=yt_artist_id,
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
        yt_track_id = track_data.get('videoId', '')
        views = self.get_yt_views(id)
        # Get track information for YouTube tracks
        return TrackInfo(
            title=track_data.get('title').replace("&quot;", "\""),
            track_id=yt_track_id,
            yt_track_id=yt_track_id,
            artist=track_data.get('artists', '')[0].get('name', ''),
            album=track_data.get('album').replace("&quot;", "\""),
            yt_artist_id=track_data.get('artists', '')[0].get('id', ''),
            length=track_data.get('duration_seconds', 0),
            yt_views=views,
            data_source=self.data_source,
            yt_updated=time.time(),
        )

    def album_for_id(self, browseId):
        """Fetch an album by its YouTube browseID and return an AlbumInfo object
        """
        self._log.debug('Searching for album {0}', browseId)
        if 'OLAK5uy' in browseId:
            if '=' in browseId:
                browseId = browseId.split('=')[1]
            browseId = self.yt.get_album_browse_id(browseId)
            self._log.debug('New browseId {0}', browseId)
        try:
            album_details = self.yt.get_album(browseId)
        except Exception:
            return None
        return self.get_album_info(album_details, 'album')

    # def track_for_id(self, track_id=None):
    #     """Fetches a track by its YouTube ID and returns a TrackInfo object
    #     """
    #     self._log.debug('Searching for track {0}', track_id)
    #     song_details = self.yt.get_song(track_id)
    #     return self._get_track(song_details['videoDetails'])

    def get_yt_song_details(self, track_id):
        """Fetches a track by its YouTube ID and returns a TrackInfo object
        """
        self._log.debug('Searching for track {0}', track_id)
        song_details = self.yt.get_song(track_id)
        return song_details['videoDetails']

    def is_valid_image_url(self, url):
        try:
            response = requests.get(url)
            Image.open(BytesIO(response.content))
            return True
        except Exception:
            return False

    def get_yt_views(self, id):
        try:
            views = self.yt.get_song(id)['videoDetails']['viewCount']
            return views
        except Exception:
            return None

    def import_youtube_playlist(self, url):
        """This function returns a list of tracks in a YouTube playlist."""
        song_list = []
        if "playlist?list=" not in url:
            self._log.error("Invalid YouTube playlist URL: {0}", url)
        else:
            playlist_id = url.split("playlist?list=")[1]
            songs = self.yt.get_playlist(playlist_id)
            for song in songs['tracks']:
                # Find and store the song title
                self._log.debug("Found song: {0}", song)
                title = song['title'].replace("&quot;", "\"")
                artist = song['artists'][0]['name'].replace("&quot;", "\"")
                try:
                    album = song['album']['name'].replace("&quot;", "\"")
                except Exception:
                    album = None
                # Create a dictionary with the song information
                song_dict = {"title": title.strip(),
                             "artist": artist.strip(),
                             "album": album.strip() if album else None}
                # Append the dictionary to the list of songs
                song_list.append(song_dict)
        return song_list

    def _get_match_score(self, title, artist, search_term):
        """Calculate match score based on title and artist similarity.
        Returns a value between 0 and 1."""
        def clean_string(s):
            # Remove punctuation, extra spaces, and convert to lowercase
            s = re.sub(r'[^\w\s]', ' ', s.lower())
            s = re.sub(r'\s+', ' ', s).strip()
            # Remove common filler words
            s = re.sub(r'\b(from|feat|ft|featuring|official|video|audio|lyrics)\b', '', s)
            return s.strip()

        # Split search term into title and artist if possible
        search_parts = search_term.split(' - ', 1)
        if len(search_parts) == 2:
            search_title, search_artist = search_parts
        else:
            search_title = search_term
            search_artist = ''

        # Clean all strings
        title_clean = clean_string(title)
        artist_clean = clean_string(artist)
        search_title_clean = clean_string(search_title)
        search_artist_clean = clean_string(search_artist)

        # Calculate title similarity
        title_score = SequenceMatcher(None, title_clean, search_title_clean).ratio()

        # Length penalty for title mismatch
        len_ratio = min(len(title_clean), len(search_title_clean)) / max(len(title_clean), len(search_title_clean))
        title_score *= len_ratio

        # Exact match bonus for title
        if title_clean == search_title_clean:
            title_score = 1.0

        # If title score is too low, heavily penalize the overall score
        if title_score < 0.5:
            title_score *= 0.5

        # Artist matching only if we have an artist to match
        if search_artist_clean:
            artist_score = SequenceMatcher(None, artist_clean, search_artist_clean).ratio()
            # Exact match bonus for artist
            if artist_clean == search_artist_clean:
                artist_score = 1.0
        else:
            # Don't penalize if no artist in search
            artist_score = 0.5

        # Weight title match much more heavily (80%) than artist match (20%)
        return (title_score * 0.8) + (artist_score * 0.2)

    def import_youtube_search(self, search, limit):
        """This function returns a list of songs sorted by the number
        of views in a YouTube search."""
        song_list = []
        songs = self.yt.search(query=search, filter="songs", limit=int(limit))
        for song in songs:
            # Find and store the song title
            #self._log.debug("Found song: {0}", song)
            song_details = self.yt.get_song(song['videoId'])
            title = song['title'].replace("&quot;", "\"")
            artist = song['artists'][0]['name'].replace("&quot;", "\"")
            views = song_details['videoDetails']['viewCount']
            try:
                album = song['album']['name'].replace("&quot;", "\"")
            except Exception:
                album = None
            # Create a dictionary with the song information
            song_dict = {"title": title.strip(),
                         "artist": artist.strip(),
                         "album": album.strip() if album else None,
                         "views": int(views) if views else None}
            match_score = self._get_match_score(title, artist, search)
            song_dict['match_score'] = match_score
            self._log.debug("Found song: {0}", song_dict)
            # Append the dictionary to the list of songs
            song_list.append(song_dict)
        # Sort the list of songs by the number of views
        song_list = sorted(song_list,
                           key=lambda k: (k['match_score'],
                                          k['views'] if k['views'] else 0),
                           reverse=True)
        return song_list