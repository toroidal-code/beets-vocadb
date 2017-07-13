"""Adds VocaDB search support to Beets
"""
from beets.autotag.hooks import AlbumInfo, TrackInfo, Distance
from beets.plugins import BeetsPlugin
import requests
import re


class VocaDBPlugin(BeetsPlugin):
    def __init__(self):
        super(VocaDBPlugin, self).__init__()
        self.config.add({
            'source_weight': 0.5,
            'lang-priority': ''  # 'Japanese, Romaji, English'
        })
        self._log.debug('Querying VocaDB')
        self.lang = self.config['lang-priority'].get().split(',')

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
        r = requests.get('http://vocadb.net/api/albums?nameMatchMode=Auto' +
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
        r = requests.get('http://vocadb.net/api/albums/%d?fields=Names,Artists,Discs&lang=%s' % (album_id, lang),
                         headers={'Accept': 'application/json'})
        try:
            item = r.json()
        except:
            self._log.debug('VocaDB JSON Decode Error: (id: %s)' % album_id)
            return None

        return self.get_album_info(item)

    def tracks_for_album_id(self, album_id):
        lang = self.lang[0] or 'Default'
        r = requests.get('http://vocadb.net/api/albums/%d/tracks?fields=Names,Artists&lang=%s' % (album_id, lang),
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
        """"Convert JSON data into a format beets can read."""
        song = item['song']
        title, _ = self.get_preferred_name(item['song'])
        track_id = song['id']
        artist = song['artistString']
        artist_credit = None
        artist_id = None

        length = song['lengthSeconds']

        medium = item['discNumber']
        medium_index = item['trackNumber']
        # TODO: Lyricist, Composer, Arranger

        return TrackInfo(title, track_id, artist=artist, artist_id=artist_id,
                         length=length, medium=medium,
                         medium_index=medium_index, medium_total=None,
                         artist_credit=artist_credit, data_source='VocaDB',
                         lyricist=None, composer=None, arranger=None)

    def get_album_info(self, item):
        """"Convert JSON data into a format beets can read."""
        album_name, language = self.get_preferred_name(item)
        album_id = item['id']
        catalognum = (item['catalogNumber'] if 'catalogNumber' in item else None)
        artist = item['artistString']
        artist_id = None
        artist_credit = None
        va = (artist == 'Various artists')  # if compilation

        # Try to find the producer
        if (not va) and ('artists' in item):
            for _artist in item['artists']:
                if _artist['roles'] == 'Default' and\
                   _artist['categories'] == 'Producer':
                    artist_credit = artist
                    artist = _artist['artist']['name']
                    artist_id = _artist['artist']['id']
                    break

        albumtype = None or item['discType']
        year = item['releaseDate']['year']
        month = item['releaseDate']['month']
        day = item['releaseDate']['day']

        mediums = None
        disctitles = None

        if 'discs' in item:
            mediums = len(item['discs'])
            disctitles = {disc['discNumber']: disc['name'] for disc in item['discs']}

        label = None
        for _artist in item['artists']:
            if _artist['categories'] == 'Label':
                label = _artist['name']
                break

        tracks = self.tracks_for_album_id(album_id)

        track_index = 1
        for track in tracks:
            track.index = track_index
            track_index += 1
            if disctitles and track.medium and (track.medium in disctitles)\
               and disctitles[track.medium]:
                track.disctitle = disctitles[track.medium]

        return AlbumInfo(album_name, album_id, artist, artist_id, tracks,
                         albumtype=albumtype, va=va, year=year, month=month, day=day,
                         label=label, mediums=mediums, artist_sort=None,
                         catalognum=catalognum, script=None,  # utf-8?
                         language=language, country=None,
                         artist_credit=artist_credit, data_source='VocaDB',
                         data_url='http://vocadb.net/albums/%d' % album_id)
