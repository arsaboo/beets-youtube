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
from beets.autotag.hooks import AlbumInfo, TrackInfo, Distance
from beets.dbcore import types
from beets.library import DateType
from beets.plugins import BeetsPlugin, get_distance
from PIL import Image
from ytmusicapi import YTMusic, OAuthCredentials


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
            'client_id': '',
            'client_secret': '',
        })
        if self.config["exclude_fields"].exists():
            self.exclude_fields = self.config["exclude_fields"].as_str_seq()

        client_id = self.config['client_id'].get()
        client_secret = self.config['client_secret'].get()
        oauth_credentials = None

        if client_id and client_secret:
            oauth_credentials = OAuthCredentials(
                client_id=client_id,
                client_secret=client_secret
            )

        # Try to initialize with OAuth first, fall back to no auth
        oauth_path = os.path.join(config.config_dir(), 'oauth.json')
        try:
            if os.path.exists(oauth_path) and oauth_credentials:
                self.yt = YTMusic(oauth_path, oauth_credentials=oauth_credentials)
            elif os.path.exists(oauth_path):
                self.yt = YTMusic(oauth_path)
            else:
                # Fall back to no authentication
                self.yt = YTMusic()
        except Exception as e:
            self._log.warning('Failed to initialize YTMusic with OAuth, trying without auth: {}', e)
            try:
                self.yt = YTMusic()
            except Exception as e2:
                self._log.error('Failed to initialize YTMusic: {}', e2)
                raise

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
        if "playlist?list=" not in url:
            self._log.error("Invalid YouTube playlist URL: {0}", url)
            return []

        playlist_id = url.split("playlist?list=")[1]
        # Remove any additional parameters from the playlist ID
        if "&" in playlist_id:
            playlist_id = playlist_id.split("&")[0]

        self._log.debug("Attempting to get playlist with ID: {0}", playlist_id)

        try:
            # Create a fresh YTMusic instance for this call to avoid state issues
            fresh_yt = YTMusic()
            playlist_data = fresh_yt.get_playlist(playlist_id)

            if playlist_data is None:
                self._log.error("YouTube API returned None for playlist ID: {0}", playlist_id)
                return []

            if 'tracks' not in playlist_data:
                self._log.error("No tracks found in playlist response for ID: {0}", playlist_id)
                return []

            songs = playlist_data['tracks']
            self._log.info("Found {0} tracks in playlist", len(songs))

        except Exception as e:
            self._log.error("Failed to get YouTube playlist {0}: {1}", playlist_id, str(e))
            return []

        song_list = []
        for song in songs:
            title = song.get('title', '').replace("&quot;", "\"")

            # Handle artists list safely
            artists = song.get('artists', [])
            if artists and len(artists) > 0:
                artist = artists[0].get('name', '').replace("&quot;", "\"")
            else:
                artist = ''

            try:
                album = song.get('album', {})
                if album and 'name' in album:
                    album_name = album['name'].replace("&quot;", "\"")
                else:
                    album_name = None
            except Exception:
                album_name = None

            # Create a dictionary with the song information
            song_dict = {"title": title.strip(),
                         "artist": artist.strip(),
                         "album": album_name.strip() if album_name else None}
            song_list.append(song_dict)

        return song_list

    def import_yt_playlist(self, url):
        """Alias for import_youtube_playlist to match plexsync expectations."""
        return self.import_youtube_playlist(url)

    def import_youtube_search(self, search, limit):
        """Returns the top N songs from YouTube search."""
        try:
            songs = self.yt.search(query=search, filter="songs", limit=int(limit))
        except Exception as e:
            self._log.error("Failed to search YouTube for '{0}': {1}", search, str(e))
            return []

        if not songs:
            self._log.warning("No songs found for search query: {0}", search)
            return []

        song_list = []
        for song in songs:
            try:
                # Get basic song info
                title = song.get('title', '').replace("&quot;", "\"")

                # Handle artists list safely
                artists = song.get('artists', [])
                if artists and len(artists) > 0:
                    artist = artists[0].get('name', '').replace("&quot;", "\"")
                else:
                    artist = ''

                # Handle album safely
                try:
                    album = song.get('album', {})
                    if album and 'name' in album:
                        album_name = album['name'].replace("&quot;", "\"")
                    else:
                        album_name = None
                except Exception:
                    album_name = None

                # Try to get detailed song info for view count
                views = None
                try:
                    video_id = song.get('videoId')
                    if video_id:
                        song_details = self.yt.get_song(video_id)
                        views = song_details.get('videoDetails', {}).get('viewCount')
                        views = int(views) if views else None
                except Exception as e:
                    self._log.debug("Could not get view count for {0}: {1}", title, e)
                    views = None

                # Create a dictionary with the song information
                song_dict = {
                    "title": title.strip(),
                    "artist": artist.strip(),
                    "album": album_name.strip() if album_name else None,
                    "views": views
                }
                song_list.append(song_dict)

            except Exception as e:
                self._log.debug("Error processing song {0}: {1}", song, e)
                continue

        # Limit the number of songs to the specified limit
        return song_list[:int(limit)]

    def import_yt_search(self, search, limit):
        """Alias for import_youtube_search to match plexsync expectations."""
        return self.import_youtube_search(search, limit)