#!/usr/bin/env python3
import datetime
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from os.path import dirname

import pafy
import pychromecast
import requests

from adapt.intent import IntentBuilder
from mycroft.audio import wait_while_speaking
from mycroft.skills.core import intent_handler, MycroftSkill
from mycroft.util.log import LOG
from mycroft.util.parse import extract_number
from pychromecast.controllers.youtube import YouTubeController
from word2number import w2n

__author__ = 'PCWii'
# TODO: is this mycroft specific if not should probably be __version__
this_release = '20190519'


def numeric_replace(words):
    """Replace numbers in words"""
    new_words = []
    # FIXME: this would convert the string "count to one hundred"
    # as "count to 1 100"
    for word in words.split():
        try:
            new_words.append(w2n.word_to_num(word))
        # raised if string has no number words
        except ValueError:
            new_words.append(word)
    return ' '.join(str(word) for word in new_words)


def repeat_regex(message):
    """check the cursor control utterance for repeat commands"""
    value = extract_number(message)
    if value:
        return value
    if 'twice' in message:
        return 2
    return 1


# FIXME: This function seems unused
def cast_link(source_link, device_ip):
    """ send a URI to Chromecast and play"""
    cast = pychromecast.Chromecast(device_ip)
    cast.wait()
    media_ctl = cast.media_controller
    LOG.info(source_link)
    media_ctl.play_media(source_link, 'video/mp4')
    time.sleep(7)  # wait for CC to be ready to play
    media_ctl.block_until_active()
    media_ctl.play()
    # media_ctl.stop()


# FIXME: This function seems unused
def cast_youtube(video_id, device_ip):
    """ send a youtube videoID and play"""
    cast = pychromecast.Chromecast(device_ip)
    cast.wait()
    youtube_ctl = YouTubeController()
    cast.register_handler(youtube_ctl)
    youtube_ctl.play_video(video_id)


# FIXME: This function seems unused
def get_yt_audio_url(self, youtube_url):
    base_url = 'https://www.youtube.com'
    abs_url = base_url + youtube_url
    LOG.debug('pafy processing: ' + abs_url)
    streams = pafy.new(abs_url)
    LOG.debug('audiostreams found: %s', streams.audiostreams)
    bestaudio = streams.getbestaudio()
    LOG.debug('audiostream selected: %s', bestaudio)
    return bestaudio.url


class KodiSkill(MycroftSkill):
    """
    A Skill to control playback on a Kodi instance via the json-rpc interface.
    """
    def __init__(self):
        super(KodiSkill, self).__init__(name='KodiSkill')
        self.kodi_path = ''
        self.youtube_id = []
        self.youtube_search = ''
        self.notifier_bool = False
        self.movie_list = []
        self.movie_index = 0
        self.cv_request = False
        self.use_cv = False
        self.start_time = ''
        self.end_time = ''
        self.music_dict = []

    def initialize(self):
        """Initialise skill"""
        self.load_data_files(dirname(__file__))
        self.log.info('Running Kodi-Skill Version: ' + str(this_release))
        #  Check and then monitor for credential changes
        self.settings_change_callback = self.on_websettings_changed
        self.on_websettings_changed()
        self.add_event('recognizer_loop:wakeword', self.handle_listen)
        self.add_event('recognizer_loop:utterance', self.handle_utterance)
        self.add_event('speak', self.handle_speak)

    # TODO: seems we could just name this settings_change_callback
    def on_websettings_changed(self):
        """called when updating mycroft home page"""
        self.log.info('Websettings have changed! Updating path data')
        self.kodi_path = 'http://{}:{}@{}:{}/jsonrpc'.format(
            self.settings.get('kodi_user', ''),
            self.settings.get('kodi_pass', ''),
            # TODO: I think localhost might make a better default
            self.settings.get('kodi_ip', '192.168.0.32'),
            self.settings.get('kodi_port', '8080'))
        self.log.debug(self.kodi_path)

    def find_movies_with_filter(self, title=''):
        """find the movies in the library that match the optional search criteria"""
        title = numeric_replace(title)
        found_list = []  # this is a dict
        movie_list = self.list_all_movies()
        title_list = title.replace('-', '').lower().split()
        for each_movie in movie_list:
            movie_name = each_movie['label'].replace('-', '')
            movie_name = numeric_replace(movie_name)
            self.log.debug(movie_name)
            if all(words in movie_name.lower() for words in title_list):
                self.log.info('Found %s : %d ', movie_name, each_movie['movieid'])
                info = {
                    'label': each_movie['label'],
                    'movieid': each_movie['movieid']
                }
                found_list.append(info)
        temp_list = []  # this is a dict ... are you sure?
        for each_movie in found_list:
            movie_title = str(each_movie['label'])
            info = {
                'label': each_movie['label'],
                'movieid': each_movie['movieid']
            }
            if movie_title not in str(temp_list):
                temp_list.append(info)
            else:
                if len(each_movie['label']) == len(movie_title):
                    # FIXME: should this be a warning id so what other info is needed
                    self.log.debug('found duplicate')
                else:
                    temp_list.append(info)
        found_list = temp_list
        # returns a dictionary of matched movies
        return found_list

    def kodi_post(self, method, params=None, api_id=1):
        """Perform a kodi jsonrpc call"""
        # TODO: add better error handeling
        # TODO: prbably use a request.Session object
        payload = {'jsonrpc': '2.0', 'method': method, 'id': api_id}
        if params:
            payload['params'] = params
        try:
            response = requests.post(self.kodi_path, json=payload)
            self.log.debug(response.text)
            return response.json()['result']
        except Exception as e:
            self.log.exception(e)
        return {}

    def is_kodi_playing(self):
        """ check if kodi is currently playing, required for some functions"""
        method = 'Player.GetActivePlayers'
        status = bool(self.kodi_post(method))
        self.log.info('Is Kodi Playing?...%s', status)
        return status

    def list_all_movies(self):
        """List all movies in kodi"""
        method = 'VideoLibrary.GetMovies'
        params = {'properties': []}
        result = self.kodi_post(method, params)
        return result.get('movies', 'NONE')

    # Added Music Functions here 20200514 #
    def add_song_playlist(self, songid):
        """ add the songid to the active playlist songid is an integer"""
        method = 'Playlist.Add'
        params = {'playlistid': 1, 'item': {'songid': songid}}
        self.kodi_post(method, params)

    def list_all_music(self):
        """List all music"""
        self.log.info('Refreshing Music List!...')
        method = 'AudioLibrary.GetSongs'
        params = {'properties': ['artist', 'duration', 'album', 'track']}
        result = self.kodi_post(method, params)
        return result.get('songs', 'NONE')

    def search_music_item(self, search_item, category='label'):
        """category options: label, artist, album"""
        search_item = numeric_replace(search_item)
        found_list = []  # this is a dict of all the items found that match the search
        # Only read the music library if it is empty
        if not self.music_dict:
            self.music_dict = self.list_all_music()
        # self.log.info('Music List: ' + str(self.music_dict))
        search_words = search_item.replace('-', '').lower().split()
        # check each movie in the list for strings that match all the words in the search
        self.start_time = datetime.datetime.now()
        # check each song in the list for the one we are looking for
        for each_song in self.music_dict:
            # artist is an array element so need to specify the index
            if category == 'artist':
                item_name = each_song[category][0].replace('-', '')
            else:
                # self.log.info('Not Filtered by Artist: ' + str(each_song))
                item_name = each_song[category].replace('-', '')
            if item_name:
                item_name = numeric_replace(item_name)
                if all(words in item_name.lower() for words in search_words):
                    info = {
                        'label': each_song['label'],
                        'songid': each_song['songid'],
                        'artist': each_song['artist']
                    }
                    found_list.append(info)
        # TODO: Clarify confuing comment/var name/var type
        # remove duplicates
        temp_list = []  # this is a dict
        for each_song in found_list:
            info = {
                'label': each_song['label'],
                'songid': each_song['songid'],
                'artist': each_song['artist']
            }
            song_title = str(each_song['label'])
            if song_title not in str(temp_list):
                temp_list.append(info)
            else:
                if len(each_song['label']) == len(song_title):
                    self.log.info('found duplicate')
                else:
                    temp_list.append(info)
        found_list = temp_list
        self.end_time = datetime.datetime.now()
        delta_time_s = self.end_time - self.start_time
        self.log.info('Searching and preparing the requested music list took: %d seconds',
                      delta_time_s)
        return found_list  # returns a dictionary of matched movies

    def search_music_library(self, search_string, category='any'):
        """Search for music in the library and return a dictionary of
        all the matchin items found in the library
        """
        found_list = {}
        self.log.info('searching the music library for: %s, %s', search_string, category)
        if category == 'any':
            for cat in ['label', 'artist', 'album']:
                found_list = self.search_music_item(search_string, category=cat)
                if found_list:
                    break
                self.log.info('%s: %s, Not Found!', cat, search_string)
        else:
            found_list = self.search_music_item(search_string, category=str(category))
        return found_list

    def queue_and_play_music(self, music_playlist):
        """Que music and start the music player"""
        self.clear_playlist()
        self.music_dict = []
        for each_song in music_playlist:
            self.log.info('Adding to Kodi Playlist: %s, ID: %d',
                          each_song['label'], each_song['songid'])
            self.add_song_playlist(each_song['songid'])
        self.play_normal()

    def parse_music_utterance(self, message):
        """returns what was spoken in the utterance"""
        return_type = 'any'
        str_request = str(message.data.get('utterance'))
        self.log.info('Parse Music Received: ' + str_request)
        primary_regex = r'((?<=album) (?P<album>.*$))|' \
                        '((?<=artist) (?P<artist>.*$))|' \
                        '((?<=song) (?P<label>.*$))'
        if str_request.find('some') != -1:
            secondary_regex = r'((?<=some) (?P<any>.*$))'
        else:
            secondary_regex = r'((?<=play) (?P<any>.*$))'
        key_found = re.search(primary_regex, str_request)
        if key_found:
            self.log.info('Primary Regex Key Found')
            if key_found.group('label'):
                self.log.info('found label')
                return_item = key_found.group('label')
                return_type = 'label'
            elif key_found.group('artist'):
                self.log.info('found artist')
                return_item = key_found.group('artist')
                return_type = 'artist'
            elif key_found.group('album'):
                self.log.info('found album')
                return_item = key_found.group('album')
                return_type = 'album'
        else:
            self.log.info('Primary Regex Key Not Found')
            key_found = re.search(secondary_regex, str_request)
            if key_found.group('any'):
                self.log.info('Secondary Regex Key Found')
                return_item = key_found.group('any')
                return_type = 'any'
            else:
                self.log.info('Secondary Regex Key Not Found')
                return_item = 'none'
                return_type = 'none'
        # Returns the item that was requested and the type of the requested
        # item ie. artist, album, label
        return return_item, return_type

    # End of Added Music Functions here 20200514 #

    def show_root(self):
        """activate the kodi root menu system"""
        method = 'GUI.ActivateWindow'
        params = {'window': 'videos', 'parameters': ['library://video/']}
        self.kodi_post(method, params)

    def clear_playlist(self):
        """clear any active playlists"""
        method = 'Playlist.Clear'
        params = {'playlistid': 1}
        self.kodi_post(method, params)

    def play_cinemavision(self):
        """play the movie playlist with cinemavision addon,
        assumes the playlist is already populated"""
        method = 'Addons.ExecuteAddon'
        params = {'addonid': 'script.cinemavision', 'params': ['experience', 'nodialog']}
        self.kodi_post(method, params)

    def play_normal(self):
        """play the movie playlist normally without any addons,
        assumes there are movies in the playlist"""
        method = 'player.open'
        params = {'item': {'playlistid': 1}}
        self.kodi_post(method, params)

    def add_movie_playlist(self, movieid):
        """add the movieid to the active playlist movieid is an integer"""
        method = 'Playlist.Add'
        params = {'playlistid': 1, 'item': {'movieid': movieid}}
        self.kodi_post(method, params)

    def pause_all(self):
        """pause any playing movie not youtube"""
        method = 'Player.PlayPause'
        params = {'playerid': 1, 'play': False}
        self.kodi_post(method, params)

    def resume_all(self):
        """resume any paused movies not youtube"""
        method = 'Player.PlayPause'
        params = {'playerid': 1, 'play': True}
        self.kodi_post(method, params)

    def check_plugin_present(self, name, plugin_type=None):
        """check if a specific plugin exists"""
        method = 'Addons.GetAddons'
        params = {'type': plugin_type} if plugin_type else None
        results = self.kodi_post(method, params)
        return bool([result for result in results if result['addonid'] == name])

    def check_youtube_present(self):
        """Check if the youtub plugin is present"""
        return self.check_plugin_present('plugin.video.youtube', 'xbmc.addon.video')

    def check_cinemavision_present(self):
        """Check if the cinemavision addon exists"""
        return self.check_plugin_present('script.cinemavision', 'xbmc.addon.executable')

    def movie_regex(self, message):
        """use regex to find any movie names found in the utterance"""
        film_regex = r'((movie|film) (?P<Film1>.*))|' \
                     '((movie|film) (?P<Film2>.*)(with|using) (cinemavision))'
        utt_str = message
        film_matches = re.finditer(film_regex, utt_str, re.MULTILINE | re.DOTALL)
        for film_match in film_matches:
            group_id = 'Film1'
            my_movie = '{group}'.format(group=film_match.group(group_id))
            self.cv_request = False
            if my_movie == 'None':
                group_id = 'Film2'
                my_movie = '{group}'.format(group=film_match.group(group_id))
                self.cv_request = True
        self.log.info(my_movie)
        my_movie = re.sub(r'\W', ' ', my_movie)
        my_movie = re.sub(' +', ' ', my_movie)
        return my_movie.strip()

    def get_kodi_movie_id(self, movie_name):
        """ return the id of a movie from the kodi library based on its name"""
        found_list = self.find_movies_with_filter(movie_name)
        my_id = found_list[0]['movieid']
        return my_id

    def get_kodi_movie_path(self, movie_name):
        """ returns the full URI of a movie from the kodi library
        possible list of properties:
            title,  trailer,  userrating,  votes,  writer
            art,  cast,  dateadded,  director,  fanart, file,  genre,
            imdbnumber,  lastplayed,  mpaa,  originaltitle,  playcount,
            plot,  plotoutline,  premiered,  rating,  runtime,  resume,
            setid,  sorttitle,  streamdetails,  studio,  tagline,  thumbnail,
        """
        movie_id = self.get_kodi_movie_id(movie_name)
        method = 'VideoLibrary.GetMovieDetails'
        params = {'movieid': movie_id, 'properties': ['file']}
        results = self.kodi_post(method, params)
        try:
            # TODO: reuse self.kodi_path here
            movie_path = results['moviedetails']['file']
            url_path = 'http://{}:{}/vfs/{}'.format(
                self.kodi_ip, self.kodi_port, urllib.parse.quote(movie_path, safe=''))
            self.log.info('Found Kodi Movie Path %s', url_path)
            return url_path
        except Exception as e:
            self.log.info(e)
            return 'NONE'

    def play_youtube_video(self, video_id):
        """play the supplied video_id with the youtube addon"""
        self.log.info('play youtube ID: %d', video_id)
        method = 'Player.Open'
        yt_base = 'plugin://plugin.video.youtube/play/?'
        # Playlist links are longer than individual links
        # individual links are 11 characters long
        if len(video_id) > 11:
            yt_link = '{}playlist_id={}&play=1&order=shuffle'.format(yt_base, video_id)
        else:
            yt_link = '{}video_id={}'.format(yt_base, video_id)
        self.log.debug('youtube link: %s', yt_link)
        params = {'item': {'file': yt_link}}
        self.kodi_post(method, params, 'libPlayer')

    def stop_all(self):
        """stop any playing movie not youtube"""
        method = 'Player.Stop'
        params = {'playerid': 1}
        self.kodi_post(method, params)

    def youtube_query_regex(self, req_string):
        """extract the requested youtube item from the utterance"""
        return_list = []
        pri_regex = re.search(r'play (?P<item1>.*) from youtube', req_string)
        sec_regex = re.search(
            r'play some (?P<item1>.*) from youtube|play the (?P<item2>.*)from youtube',
            req_string)
        if pri_regex:
            if sec_regex:  # more items requested
                temp_results = sec_regex
            else:  # single item requested
                temp_results = pri_regex
        if temp_results:
            item_result = temp_results.group(temp_results.lastgroup)
            return_list = item_result
            self.log.info(return_list)
            return return_list

    def get_youtube_links(self, search_list):
        """ extract the youtube links from the provided search_list"""
        # search_text = str(search_list[0])
        search_text = str(search_list)
        query = urllib.parse.quote(search_text)
        url = 'https://www.youtube.com/results?search_query=' + query
        # TODO: use beutifle soup and requests
        response = urllib.request.urlopen(url)
        html = response.read()
        # Get all video links from page
        temp_links = []
        all_video_links = re.findall(r'href=\'\/watch\?v=(.{11})', html.decode())
        for each_video in all_video_links:
            if each_video not in temp_links:
                temp_links.append(each_video)
        video_links = temp_links
        # Get all playlist links from page
        temp_links = []
        all_playlist_results = re.findall(r'href=\'\/playlist\?list\=(.{34})', html.decode())
        sep = "'"
        for each_playlist in all_playlist_results:
            if each_playlist not in temp_links:
                cleaned_pl = each_playlist.split(sep, 1)[0]  # clean up dirty playlists
                temp_links.append(cleaned_pl)
        playlist_links = temp_links
        yt_links = []
        if video_links:
            yt_links.append(video_links[0])
            self.log.info('Found Single Links: ' + str(video_links))
        if playlist_links:
            yt_links.append(playlist_links[0])
            self.log.info('Found Playlist Links: ' + str(playlist_links))
        return yt_links

    def post_kodi_notification(self, message):
        """push a message to the kodi notification popup"""
        method = 'GUI.ShowNotification'
        display_timeout = 5000
        params = {
            'title': 'Kelsey.AI',
            'message': str(message),
            'displaytime': display_timeout,
        }
        self.kodi_post(method, params)

    def handle_listen(self, message):
        """ listening event used for kodi notifications"""
        # TODO: do we want to use message?
        # voice_payload = message.data.get('utterance')
        voice_payload = 'Listening'
        if self.notifier_bool:
            self.post_kodi_notification(voice_payload)

    def handle_utterance(self, message):
        """utterance event used for kodi notifications"""
        utterance = message.data.get('utterances')
        voice_payload = utterance
        if self.notifier_bool:
            self.post_kodi_notification(voice_payload)

    def handle_speak(self, message):
        """mycroft speaking event used for kodi notificatons"""
        voice_payload = message.data.get('utterance')
        if self.notifier_bool:
            self.post_kodi_notification(voice_payload)

    @intent_handler(IntentBuilder('PlayLocalIntent')
                    .require('AskKeyword').require('KodiKeyword').require('PlayKeyword')
                    .optionally('FilmKeyword').optionally('CinemaVisionKeyword')
                    .optionally('RandomKeyword').build())
    def handle_play_local_intent(self, message):
        """Primary Play Movie request - now handles music and films with optionally"""
        self.log.info('Called Play Film Intent')
        if message.data.get('FilmKeyword'):
            self.log.info('Continue with Play Film intent')
            self.continue_play_film_intent(message)
        else:
            # Play Music Added here
            self.log.info('Continue with Play Music intent')
            self.continue_play_music_intent(message)

    def continue_play_music_intent(self, message):
        """Continue playing music"""
        play_request = self.parse_music_utterance(message)  # get the requested Music Item
        self.log.info('Parse Routine Returned: '+str(play_request))
        # search for the item in the library
        music_playlist = self.search_music_library(play_request[0], category=play_request[1])
        self.speak_dialog('play.music',
                          data={'title': str(play_request[0]), 'category': str(play_request[1])},
                          expect_response=False)
        self.queue_and_play_music(music_playlist)

    def continue_play_film_intent(self, message):
        """Continue playing film"""
        if message.data.get('CinemaVisionKeyword'):
            self.cv_request = True
        else:
            self.cv_request = False
        if message.data.get('RandomKeyword'):
            self.handle_random_movie_select_intent()
        else:
            # Proceed normally
            movie_name = self.movie_regex(message.data.get('utterance'))
            try:
                self.log.info('movie: ' + movie_name)
                self.speak_dialog('please.wait')
                results = self.find_movies_with_filter(movie_name)
                self.movie_list = results
                self.movie_index = 0
                self.log.info('possible movies are: ' + str(results))
                ######
                if len(results) == 1:
                    self.play_film(results[0]['movieid'])
                elif results:
                    self.set_context('NavigateContextKeyword', 'NavigateContext')
                    self.speak_dialog('multiple.results',
                                      data={'result': str(len(results))},
                                      expect_response=True)
                else:
                    self.speak_dialog('no.results',
                                      data={'result': movie_name},
                                      expect_response=False)
                #####
            except Exception as e:
                self.log.info('an error was detected')
                self.log.exception(e)

    @intent_handler(IntentBuilder('StopIntent')
                    .require('StopKeyword')
                    .one_of('FilmKeyword', 'KodiKeyword', 'YoutubeKeyword', 'MusicKeyword')
                    .build())
    def handle_stop_intent(self, message):
        """stop film was requested in the utterance"""
        # TODO: do we want to do anything with message?
        try:
            self.stop_all()
        except Exception as e:
            self.log.exception(e)

    @intent_handler(IntentBuilder('PauseIntent')
                    .require('PauseKeyword')
                    .one_of('FilmKeyword', 'KodiKeyword', 'YoutubeKeyword', 'MusicKeyword')
                    .build())
    def handle_pause_intent(self, message):
        """pause film was requested in the utterance"""
        # TODO: do we want to do anything with message?
        try:
            self.pause_all()
        except Exception as e:
            self.log.exception(e)

    @intent_handler(IntentBuilder('ResumeIntent')
                    .require('ResumeKeyword')
                    .one_of('FilmKeyword', 'KodiKeyword', 'YoutubeKeyword', 'MusicKeyword')
                    .build())
    def handle_resume_intent(self, message):
        """resume the film was requested in the utterance"""
        # TODO: do we want to do anything with message?
        try:
            self.resume_all()
        except Exception as e:
            self.log.error(e)

    @intent_handler(IntentBuilder('NotifyOnIntent')
                    .require('NotificationKeyword').require('OnKeyword').require('KodiKeyword')
                    .build())
    def handle_notification_on_intent(self, message):
        """turn notifications on requested in the utterance"""
        # TODO: do we want to do anything with message?
        self.notifier_bool = True
        self.speak_dialog('notification', data={'result': 'On'})

    @intent_handler(IntentBuilder('NotifyOffIntent')
                    .require('NotificationKeyword').require('OffKeyword').require('KodiKeyword')
                    .build())
    def handle_notification_off_intent(self, message):
        """turn notifications off requested in the utterance"""
        # TODO: do we want to do anything with message?
        self.notifier_bool = False
        self.speak_dialog('notification', data={'result': 'Off'})

    @intent_handler(IntentBuilder('MoveCursorIntent')
                    .require('MoveKeyword').require('CursorKeyword')
                    .one_of('UpKeyword', 'DownKeyword', 'LeftKeyword', 'RightKeyword',
                            'EnterKeyword', 'SelectKeyword', 'BackKeyword').build())
    def handle_move_cursor_intent(self, message):
        """move cursor utterance processing"""
        # in future the user does not have to say the move keyword
        self.set_context('MoveKeyword', 'move')
        # in future the user does not have to say the cursor keyword
        self.set_context('CursorKeyword', 'cursor')
        # direction_kw are required by the KODI API
        if 'UpKeyword' in message.data:
            direction_kw = 'Up'
        if 'DownKeyword' in message.data:
            direction_kw = 'Down'
        if 'LeftKeyword' in message.data:
            direction_kw = 'Left'
        if 'RightKeyword' in message.data:
            direction_kw = 'Right'
        if 'EnterKeyword' in message.data:
            direction_kw = 'Enter'
        if 'SelectKeyword' in message.data:
            direction_kw = 'Select'
        if 'BackKeyword' in message.data:
            direction_kw = 'Back'
        repeat_count = repeat_regex(message.data.get('utterance'))
        self.log.info('utterance: %s', message.data.get('utterance'))
        self.log.info('repeat_count: %d', repeat_count)
        if direction_kw:
            method = 'Input.' + direction_kw
            for _ in range(0, int(repeat_count)):
                self.kodi_post(method)
                self.speak_dialog('direction', data={'result': direction_kw},
                                  expect_response=True)
                time.sleep(1)

    def play_film(self, movieid):
        """play the movie based on movie ID"""
        self.clear_playlist()
        self.add_movie_playlist(movieid)
        if self.check_cinemavision_present():  # Cinemavision is installed
            self.set_context('CinemaVisionContextKeyword', 'CinemaVisionContext')
            self.speak_dialog('cinema.vision', expect_response=True)
        else:  # Cinemavision is NOT installed
            self.play_normal()

    @intent_handler(IntentBuilder('CinemavisionRequestIntent')
                    .require('CinemaVisionContextKeyword')
                    .one_of('YesKeyword', 'NoKeyword').build())
    def handle_cinemavision_request_intent(self, message):
        """execute cinemavision addon decision"""
        self.set_context('CinemaVisionContextKeyword', '')
        if 'YesKeyword' in message.data:  # Yes was spoken to navigate the list
            self.log.info('User responded with: %s', message.data.get('YesKeyword'))
            self.play_cinemavision()
        else:  # No was spoken to navigate the list
            self.log.info('User responded with: %s', message.data.get('NoKeyword'))
            self.play_normal()

    @intent_handler(IntentBuilder('NavigateDecisionIntent')
                    .require('NavigateContextKeyword')
                    .one_of('YesKeyword', 'NoKeyword').build())
    def handle_navigate_decision_intent(self, message):
        """movie list navigation decision utterance"""
        self.set_context('NavigateContextKeyword', '')
        # Yes was spoken to navigate the list, reading the first item
        if 'YesKeyword' in message.data:
            self.log.info('User responded with...%s', message.data.get('YesKeyword'))
            self.set_context('ListContextKeyword', 'ListContext')
            msg_payload = str(self.movie_list[self.movie_index]['label'])
            self.speak_dialog('navigate', data={'result': msg_payload}, expect_response=True)
        else:  # No was spoken to navigate the list, reading the first item
            self.log.info('User responded with...%s', message.data.get('NoKeyword'))
            self.speak_dialog('cancel', expect_response=False)

    @intent_handler(IntentBuilder('NavigatePlayIntent')
                    .require('ListContextKeyword').require('PlayKeyword').build())
    def handle_navigate_play_intent(self, message):
        """the currently listed move was selected to play"""
        self.set_context('ListContextKeyword', '')
        msg_payload = str(self.movie_list[self.movie_index]['label'])
        self.speak_dialog('play.film', data={'result': msg_payload}, expect_response=False)
        try:
            self.play_film(self.movie_list[self.movie_index]['movieid'])
        except Exception as e:
            self.log.exception(e)

    @intent_handler(IntentBuilder('ParseNextIntent')
                    .require('ListContextKeyword').require('NextKeyword').build())
    def handle_parse_next_intent(self, message):
        """ the user has requested to skip the currently listed movie"""
        self.set_context('ListContextKeyword', 'ListContext')
        self.movie_index += 1
        if self.movie_index < len(self.movie_list):
            msg_payload = str(self.movie_list[self.movie_index]['label'])
            self.speak_dialog('context', data={'result': msg_payload}, expect_response=True)
        else:
            self.set_context('ListContextKeyword', '')
            self.speak_dialog('list.end', expect_response=False)

    @intent_handler(IntentBuilder('NavigateStopIntent')
                    .require('NavigateContextKeyword').require('StopKeyword').build())
    def handle_navigate_stop_intent(self, message):
        """The user has requested to stop navigating the list"""
        self.set_context('NavigateContextKeyword', '')
        self.speak_dialog('cancel', expect_response=False)

    @intent_handler(IntentBuilder('ParseCancelIntent')
                    .require('ListContextKeyword').require('StopKeyword').build())
    def handle_parse_cancel_intent(self, message):
        """The user has requested to stop parsing the list"""
        self.set_context('ListContextKeyword', '')
        self.speak_dialog('cancel', expect_response=False)

    @intent_handler(IntentBuilder('CursorCancelIntent')
                    .require('MoveKeyword').require('CursorKeyword').require('StopKeyword')
                    .build())
    def handle_cursor_cancel_intent(self, message):
        """Cancel was spoken, Cancel the list navigation"""
        self.set_context('MoveKeyword', '')
        self.set_context('CursorKeyword', '')
        self.log.info('handle_cursor_cancel_intent')
        self.speak_dialog('cancel', expect_response=False)

    def stop_navigation(self, message):
        """An internal conversational context stoppage was issued"""
        self.speak_dialog('context', data={'result': message}, expect_response=False)

    @intent_handler(IntentBuilder('SetVolumeIntent')
                    .require('SetsKeyword').require('KodiKeyword').require('VolumeKeyword')
                    .build())
    def handle_set_volume_intent(self, message):
        """The movie information dialog was requested in the utterance"""
        str_remainder = str(message.utterance_remainder())
        volume_level = re.findall(r'\d+', str_remainder)
        if volume_level:
            if int(volume_level[0]) < 101:
                new_volume = self.set_volume(int(volume_level[0]))
                self.log.info('Kodi Volume Now: ' + str(new_volume))
                self.speak_dialog('volume.set',
                                  data={'result': str(new_volume)},
                                  expect_response=False)
            else:
                self.speak_dialog('volume.error',
                                  data={'result': int(volume_level[0])},
                                  expect_response=False)

    def set_volume(self, level):
        """Set the Volume"""
        method = 'Application.SetVolume'
        params = {'volume': level}
        return self.kodi_post(method, params)

    @intent_handler(IntentBuilder('ShowMovieInfoIntent')
                    .require('VisibilityKeyword').require('InfoKeyword')
                    .optionally('KodiKeyword').optionally('FilmKeyword').build())
    def handle_show_movie_info_intent(self, message):
        """The movie information dialog was requested in the utterance"""
        method = 'Input.Info'
        self.kodi_post(method)

    @intent_handler(IntentBuilder('SkipMovieIntent')
                    .require('NextKeyword').require('FilmKeyword')
                    .one_of('ForwardKeyword', 'BackwardKeyword')
                    .build())
    def handle_skip_movie_intent(self, message):
        """the user requested to skip the movie timeline forward or backward"""
        method = 'Player.Seek'
        backward_kw = message.data.get('BackwardKeyword')
        if backward_kw:
            dir_skip = 'smallbackward'
        else:
            dir_skip = 'smallforward'
        params = {'playerid': 1, 'value': dir_skip}
        if self.is_kodi_playing():
            self.kodi_post(method, params)
        else:
            self.log.info('There is no movie playing to skip')

    @intent_handler(IntentBuilder('SubtitlesOnIntent')
                    .require('KodiKeyword').require('SubtitlesKeyword').require('OnKeyword')
                    .build())
    def handle_subtitles_on_intent(self, message):
        """ user has requested to turn on the movie subtitles"""
        method = 'Player.SetSubtitle'
        params = {'playerid': 1, 'subtitle': 'on'}
        if self.is_kodi_playing():
            self.kodi_post(method, params)
        else:
            self.log.info('Turning Subtitles On Failed, kodi not playing')

    # user has requested to turn off the movie subtitles
    @intent_handler(IntentBuilder('SubtitlesOffIntent')
                    .require('KodiKeyword').require('SubtitlesKeyword').require('OffKeyword')
                    .build())
    def handle_subtitles_off_intent(self, message):
        method = 'Player.SetSubtitle'
        params = {'playerid': 1, 'subtitle': 'off'}
        if self.is_kodi_playing():
            self.kodi_post(method, params)
        else:
            self.log.info('Turning Subtitles Off Failed, kodi not playing')

    @intent_handler(IntentBuilder('ShowMoviesAddedIntent')
                    .require('ListKeyword').require('RecentKeyword').require('FilmKeyword')
                    .build())
    def handle_show_movies_added_intent(self, message):
        """user has requested to show the recently added movies list"""
        method = 'GUI.ActivateWindow'
        params = {'window': 'videos', 'parameters': ['videodb://recentlyaddedmovies/']}
        self.kodi_post(method, params)
        sort_kw = message.data.get('RecentKeyword')
        self.speak_dialog('sorted.by', data={'result': sort_kw}, expect_response=False)

    @intent_handler(IntentBuilder('ShowMoviesGenresIntent')
                    .require('ListKeyword').require('FilmKeyword').require('GenreKeyword')
                    .build())
    def handle_show_movies_genres_intent(self, message):
        """user has requested to show the movies listed by genres"""
        method = 'GUI.ActivateWindow'
        params = {'window': 'videos', 'parameters': ['videodb://movies/genres/']}
        self.kodi_post(method, params)
        sort_kw = message.data.get('GenreKeyword')
        self.speak_dialog('sorted.by', data={'result': sort_kw}, expect_response=False)

    @intent_handler(IntentBuilder('ShowMoviesActorsIntent')
                    .require('ListKeyword').require('FilmKeyword').require('ActorKeyword')
                    .build())
    def handle_show_movies_actors_intent(self, message):
        """user has requested to show the movies listed by actor"""
        method = 'GUI.ActivateWindow'
        params = {'window': 'videos', 'parameters': ['videodb://movies/actors/']}
        self.kodi_post(method, params)
        sort_kw = message.data.get('ActorKeyword')
        self.speak_dialog('sorted.by', data={'result': sort_kw}, expect_response=False)

    @intent_handler(IntentBuilder('ShowMoviesStudioIntent')
                    .require('ListKeyword').require('FilmKeyword').require('StudioKeyword')
                    .build())
    def handle_show_movies_studio_intent(self, message):
        """user has requested to show the movies listed by studio"""
        method = 'GUI.ActivateWindow'
        params = {'window': 'videos', 'parameters': ['videodb://movies/studios/']}
        self.kodi_post(method, params)
        sort_kw = message.data.get('StudioKeyword')
        self.speak_dialog('sorted.by', data={'result': sort_kw}, expect_response=False)

    @intent_handler(IntentBuilder('ShowMoviesTitleIntent')
                    .require('ListKeyword').require('FilmKeyword').require('TitleKeyword')
                    .build())
    def handle_show_movies_title_intent(self, message):
        """user has requested to show the movies listed by title"""
        method = 'GUI.ActivateWindow'
        params = {'window': 'videos', 'parameters': ['videodb://movies/titles/']}
        self.kodi_post(method, params)
        sort_kw = message.data.get('TitleKeyword')
        self.speak_dialog('sorted.by', data={'result': sort_kw}, expect_response=False)

    @intent_handler(IntentBuilder('ShowMoviesSetsIntent')
                    .require('ListKeyword').require('FilmKeyword').require('SetsKeyword')
                    .build())
    def handle_show_movies_sets_intent(self, message):
        """user has requested to show the movies listed by movie sets"""
        method = 'GUI.ActivateWindow'
        params = {'window': 'videos', 'parameters': ['videodb://movies/sets/']}
        self.kodi_post(method, params)
        sort_kw = message.data.get('SetsKeyword')
        self.speak_dialog('sorted.by', data={'result': sort_kw}, expect_response=False)

    @intent_handler(IntentBuilder('ShowAllMoviesIntent')
                    .require('ListKeyword').require('AllKeyword').require('FilmKeyword')
                    .build())
    def handle_show_all_movies_intent(self, message):
        """user has requested to show the movies listed all movies"""
        self.show_root()
        method = 'GUI.ActivateWindow'
        params = {'window': 'videos', 'parameters': ['videodb://movies/']}
        self.kodi_post(method, params)
        sort_kw = message.data.get('AllKeyword')
        self.speak_dialog('sorted.by', data={'result': sort_kw}, expect_response=False)

    @intent_handler(IntentBuilder('CleanLibraryIntent')
                    .require('CleanKeyword').require('KodiKeyword').require('LibraryKeyword')
                    .build())
    def handle_clean_library_intent(self, message):
        """user has requested to refresh the movie library database"""
        method = 'VideoLibrary.Clean'
        params = {'showdialogs': True}
        self.kodi_post(method, params)
        update_kw = message.data.get('CleanKeyword')
        self.speak_dialog('update.library', data={'result': update_kw}, expect_response=False)

    @intent_handler(IntentBuilder('ScanLibraryIntent')
                    .require('ScanKeyword').require('KodiKeyword').require('LibraryKeyword')
                    .build())
    def handle_scan_library_intent(self, message):
        """user has requested to update the movie database"""
        method = 'VideoLibrary.Scan'
        params = {'showdialogs': True}
        self.kodi_post(method, params)
        update_kw = message.data.get('ScanKeyword')
        self.speak_dialog('update.library', data={'result': update_kw}, expect_response=False)

    # changed this intent to avoid common-play-framework
    @intent_handler(IntentBuilder('PlayYoutubeIntent')
                    .require('AskKeyword').require('KodiKeyword').require('PlayKeyword')
                    .require('FromYoutubeKeyword').build())
    def handle_play_youtube_intent(self, message):
        """user has requested to play a video from youtube"""
        results = self.youtube_query_regex(message.data.get('utterance'))
        self.youtube_id = self.get_youtube_links(results)
        if self.check_youtube_present():
            wait_while_speaking()
            if len(self.youtube_id) > 1:
                self.set_context('PlaylistContextKeyword', 'PlaylistContext')
                self.speak_dialog('youtube.playlist.present', expect_response=True)
            else:
                self.speak_dialog('play.youtube',
                                  data={'result': self.youtube_search},
                                  expect_response=False)
                self.play_youtube_video(self.youtube_id[0])
        else:
            self.speak_dialog('youtube.addon.error', expect_response=False)

    @intent_handler(IntentBuilder('YoutubePlayTypeDecisionIntent')
                    .require('PlaylistContextKeyword')
                    .one_of('YesKeyword', 'NoKeyword').build())
    def handle_youtube_play_type_decision_intent(self, message):
        """user is requested to make a decision to play a single youtube link or
        a playlist link"""
        self.set_context('PlaylistContextKeyword', '')
        self.speak_dialog('play.youtube',
                          data={'result': self.youtube_search},
                          expect_response=False)
        if 'YesKeyword' in message.data:
            self.log.info('Playing youtube id: ' + str(self.youtube_id[1]))
            self.play_youtube_video(self.youtube_id[1])
        else:
            self.log.info('Playing youtube id: ' + str(self.youtube_id[0]))
            self.play_youtube_video(self.youtube_id[0])

    def handle_random_movie_select_intent(self):
        """Play a random film"""
        full_list = self.list_all_movies()
        random_id = random.randint(1, len(full_list))
        selected_entry = full_list[random_id]
        selected_name = selected_entry['label']
        selected_id = selected_entry['movieid']
        self.log.info(selected_name, selected_id)
        self.speak_dialog('play.film', data={'result': selected_name}, expect_response=False)
        self.play_film(selected_id)

    def stop(self):
        """Stop Method"""


def create_skill():
    """Creat the skill"""
    return KodiSkill()
