# -*- coding: utf-8 -*-
"""Adds VocaDB search support to Beets
"""
from beets.autotag.hooks import AlbumInfo, TrackInfo, Distance
from beets.plugins import BeetsPlugin
from beetsplug import lastgenre
import requests
import re


class VocaDBPlugin(BeetsPlugin):
    def __init__(self):
        super(VocaDBPlugin, self).__init__()
        self.base_url = 'http://vocadb.net'
        self.lg = lastgenre.LastGenrePlugin()
        self.config.add({
            'source_weight': 0.0,
            'canonical_artists': True,
            'separator': ', ',
            'whitelist': True,
            'artist_priority': ['producers', 'circles'],
            'circles_exclude': [],
            'genres': True,
            'lang-priority': 'English'  # 'Japanese, Romaji, English'
        })
        self._log.debug('Querying VocaDB')
        self.lang = self.config['lang-priority'].get().split(',')
        if self.config['genres'].get():
            self.import_stages = [self.imported]

    def album_distance(self, items, album_info, mapping):
        """Returns the album distance."""
        dist = Distance()
        if album_info.data_source == 'VocaDB':
            dist.add('source', self.config['source_weight'].as_number())
        return dist

    def candidates(self, items, artist, album, va_likely):
        """Return a list of AlbumInfo objects from the search results
        matching an album and artist (if not various)."""
        query = album
        try:
            return self.get_albums(query, va_likely)
        except:
            self._log.debug('VocaDB Search Error: (query: %s)' % query)
            return []

    def get_albums(self, query, va_likely):
        """Returns a list of AlbumInfo objects for a VocaDB album-name query.
        """
        # Strip non-word characters from query. Things like "!" and "-" can
        # cause a query to return no results, even if they match the artist or
        # album title. Use `re.UNICODE` flag to avoid stripping non-english
        # word characters.
        query = re.sub(r'(?u)\W+', ' ', query)
        # Strip medium information from query, Things like "CD1" and "disk 1"
        # can also negate an otherwise positive result.
        query = re.sub(r'(?i)\b(CD|disc)\s*\d+', '', query)

        lang = self.lang[0] or 'Default'

        # Query VocaDB
        r = requests.get(self.base_url + '/api/albums?nameMatchMode=Auto' +
                         '&preferAccurateMatches=true' +
                         '&fields=Names,Artists,Discs' +
                         '&query=%s&lang=%s' % (query, lang),
                         headers={'Accept': 'application/json'})

        # Decode reponse content
        try:
            item = r.json()
        except:
            self._log.debug('VocaDB JSON Decode Error: (query: %s)' % query)
            return []

        self._log.debug('get_albums Querying VocaDB for release %s' % query)
        return [self.get_album_info(album) for album in item['items']]

    def item_candidates(self, item, artist, album):
        return []

    def album_for_id(self, album_id):
        lang = self.lang[0] or 'Default'
        r = requests.get(self.base_url + '/api/albums/%s?fields=Names,Artists,Discs&lang=%s' % (str(album_id), lang),
                         headers={'Accept': 'application/json'})
        try:
            item = r.json()
        except:
            self._log.debug('VocaDB JSON Decode Error: (id: %s)' % album_id)
            return None

        return self.get_album_info(item)

    def tracks_for_album_id(self, album_id):
        lang = self.lang[0] or 'Default'
        url = self.base_url + '/api/albums/%d/tracks?fields=Names,Artists&lang=%s' % (album_id, lang)
        self._log.debug(f"Url to access album: {url}")
        r = requests.get(url,
                         headers={'Accept': 'application/json'})
        try:
            tracks = r.json()
        except:
            self._log.debug('VocaDB JSON Decode Error: (id: %s)' % album_id)
            return None

        return [self.get_track_info(track) for track in tracks]

    def get_preferred_name(self, item):
        """Retrieve the item's name in the preferred language."""
        item_name = ''
        if self.lang and self.lang[0] and 'names' in item:
            for lang in self.lang:          # for our list of preferred languages
                for name in item['names']:  # loop through the list of names
                    if name['language'] == lang:  # and check if it matches
                        language = name['language']
                        item_name = name['value']
                        break
                if item_name:
                    break

        # if there was no matching name for the preferred languages
        if not item_name:
            language = item['defaultNameLanguage']
            item_name = item['defaultName']

        return (item_name, language)

    def get_track_info(self, item):
        # This try-except is necessary because of albums like https://vocadb.net/Al/18564, that have songs with very little info
        # You can probably improve this a lot by still providing the track title, but I spent way too much time debuggint this as it is
        try:
            """"Convert JSON data into a format beets can read."""
            song = item['song']
            self._log.debug(f"after song")
        except:
            return TrackInfo("dummy_title", 0, medium_index=0, medium_total=None, data_source='VocaDB',)

        title, _ = self.get_preferred_name(item['song'])
        track_id = song['id']
        artist = song['artistString']
        artist_credit = None
        artist_id = None

        length = song['lengthSeconds']

        medium = item['discNumber']
        medium_index = item['trackNumber']

        lyricist = self.config['separator'].get().join(
            [(_artist['artist']['name'] if 'artist' in _artist else _artist['name'])
             for _artist in song['artists']
             if 'Lyricist' in _artist['roles'].split(', ')]
        ) or None

        composer = self.config['separator'].get().join(
            [(_artist['artist']['name'] if 'artist' in _artist else _artist['name'])
             for _artist in song['artists']
             if 'Composer' in _artist['roles'].split(', ')]
        ) or None

        arranger = self.config['separator'].get().join(
            [(_artist['artist']['name'] if 'artist' in _artist else _artist['name'])
             for _artist in song['artists']
             if 'Arranger' in _artist['roles'].split(', ')]
        ) or None

        return TrackInfo(title, track_id, artist=artist, artist_id=artist_id,
                         length=length, medium=medium,
                         medium_index=medium_index, medium_total=None,
                         artist_credit=artist_credit, data_source='VocaDB',
                         lyricist=lyricist, composer=composer,
                         arranger=arranger)

    def get_album_info(self, item):
        """"Convert JSON data into a format beets can read."""
        album_name, language = self.get_preferred_name(item)
        album_id = item['id']
        catalognum = (item['catalogNumber'] if 'catalogNumber' in item else None)
        artist = item['artistString']
        artist_id = None
        artist_credit = None
        va = (artist == 'Various artists' or item['discType'] == 'Compilation') # if compilation
        
        # More detailed artist information
        if 'artists' in item and not self.config['canonical_artists'].get():
            orig_artist = artist # the original artist before we start trying to find better ones
            artist_corrected = False
            producers = [_artist for _artist in item['artists'] if 'Producer' in _artist['categories'].split(', ') and not _artist['isSupport']]
            circles = [_artist for _artist in item['artists'] if 'Circle' in _artist['categories'].split(', ') and not _artist['isSupport']]

            for val in self.config['artist_priority'].as_str_seq():
                if val == 'circles':
                    for _artist in circles:
                        if 'artist' in _artist:
                            if (_artist['artist']['name'] in self.config['circles_exclude'].as_str_seq()\
                                and not len(producers) > 1): # Use a circle, even if it's excluded, when there are multiple primary producers
                                break
                            
                            if ('Default' in _artist['roles'].split(', ') or orig_artist == 'Various artists'):
                                artist_credit = orig_artist
                                artist = _artist['artist']['name']
                                artist_id = _artist['artist']['id']
                                artist_corrected = True
                                break
                        else:
                             artist = _artist['name']

                elif val == 'producers':
                    if len(producers) == 1:
                        _artist = producers[0]
                        artist_credit = orig_artist
                        artist = _artist['artist']['name'] if 'artist' in _artist else _artist['name']
                        artist_id = _artist['artist']['id'] if 'artist' in _artist else None
                        artist_corrected = True

                if artist_corrected:
                    break

        albumtype = None or item['discType']
        year = item['releaseDate']['year'] if 'year' in item['releaseDate'] else None
        month = item['releaseDate']['month'] if 'month' in item['releaseDate'] else None
        day = item['releaseDate']['day'] if 'day' in item['releaseDate'] else None

        mediums = 0
        disctitles = None

        if 'discs' in item:
            mediums = len(item['discs'])
            disctitles = {disc['discNumber']: disc['name'] for disc in item['discs']}

        label = None
        for _artist in item['artists']:
            if 'Label' in _artist['categories'].split(', '):
                label = _artist['name']
                break

        tracks = self.tracks_for_album_id(album_id)

        track_index = 1
        for track in tracks:
            if track.medium_index > track_index:
                track_index = track.medium_index
            track.index = track_index
            track_index += 1
            if disctitles and track.medium and (track.medium in disctitles)\
               and disctitles[track.medium]:
                track.disctitle = disctitles[track.medium]


        self._log.debug(f"old artist: {artist}")
        try:
            artist = re.search(r'(^.*)(\s+feat\.)', artist).group(1)
            self._log.debug(f"new artist: {artist}")
            artist = artist.replace(",", ";")
        except:
            pass

        if artist == "Various artists":
            artist = "Various Artists"
            self._log.debug(f"various artist?: {artist}")

        return AlbumInfo(album_name, album_id, artist, artist_id, tracks,
                         albumtype=albumtype, va=va, year=year, month=month, day=day,
                         label=label, mediums=mediums, artist_sort=None,
                         catalognum=catalognum, script='utf-8',  # VocaDB's JSON responses are encoded in UTF-8
                         language=language, country=None,
                         artist_credit=artist_credit, data_source='VocaDB',
                         data_url=(self.base_url + '/AL/%d' % album_id))

    def add_genre_to_item(self, item, is_album):
        lang = self.lang[0] or 'Default'
        if is_album:
            url = self.base_url + '/api/albums/%s?fields=Tags&lang=%s' % (item.mb_albumid, lang)
        else:
            url = self.base_url + '/api/songs/%s?fields=Tags&lang=%s' % (item.mb_trackid, lang)

        r = requests.get(url, headers={'Accept': 'application/json'})

        try:
            obj = r.json()
        except:
            self._log.debug('VocaDB JSON Decode Error: (id: %s)' % item.id)
            return None

        # Try to find the tags
        genre = ''
        if 'tags' in obj and obj['tags']:
            tags = [_tag['tag']['name'].lower() for _tag in obj['tags']]

            if self.config['whitelist'].get():
                genre = self.lg._resolve_genres(tags)
            else:
                genre = self.config['separator'].get().join(tags)

        item.genre = genre
        item.store()

        if is_album:
            for track in item.items():
                self.add_genre_to_item(track, False)

    def imported(self, session, task):
        """Event hook called when an import task finishes."""
        if task.is_album and 'data_source' in task.items[0] and \
           task.items[0].data_source == 'VocaDB':
            self._log.debug("VocaDB: Fetching tags for %s - %s" % (task.album.albumartist, task.album.album))
            self.add_genre_to_item(task.album, True)

# The UtaiteDB uses the same backend code and is run by the same team as VocaDB
class UtaiteDBPlugin(VocaDBPlugin):
    def __init__(self):
        super(UtaiteDBPlugin, self).__init__()
        self.base_url = 'http://utaitedb.net'
