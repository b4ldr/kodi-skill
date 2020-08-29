#!/usr/bin/env python3

from kodictl import KodiCtl

from adapt.intent import IntentBuilder
from mycroft import intent_handler, MycroftSkill


class KodiSkill(MycroftSkill):

    def initialize(self):
        """initialise kodictl object"""
        self.kctl = KodiCtl(
            self.settings.get('hostiname', '127.0.0.1'),
            self.settings.get('port', 8080),
            self.settings.get('username'),
            self.settings.get('password'),
            self.settings.get('tls', False))

    @intent_handler(IntentBuilder("PauseIntent")
                    .require("PauseKeyword")
                    .one_of("FilmKeyword", "KodiKeyword", "YoutubeKeyword", "MusicKeyword")
                    .build())
    def handle_pause_intent(self, message):
        self.kctl.pause = True

    @intent_handler(IntentBuilder('SubtitlesOnIntent')
                    .require('SubtitlesKeyword').require('OnKeyword')
                    .build())
    def handle_subs_on(self, message):
        self.kctl.subtitles = True

    @intent_handler(IntentBuilder('SubtitlesOffIntent')
                    .require('SubtitlesKeyword').require('OffKeyword')
                    .build())
    def handle_subs_off(self, message):
        self.kctl.subtitles = False

    def stop(self):
        pass


def create_skill():
    return KodiSkill()
