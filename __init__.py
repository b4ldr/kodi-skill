#!/usr/bin/env python3

import re

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

    @intent_handler(IntentBuilder("PauseIntent").require("PauseKeyword").build())
    def handle_pause_intent(self, message):
        self.kctl.pause = True

    @intent_handler(IntentBuilder("UnPauseIntent").require("UnPauseKeyword").build())
    def handle_unpause_intent(self, message):
        self.kctl.pause = False

    @intent_handler('subtitles.intent')
    def handle_subs(self, message):
        if re.search(r'\bon|enable\b', message.data.get('utterance')):
            self.kctl.subtitles = True
        elif re.search(r'\boff|disable\b', message.data.get('utterance')):
            self.kctl.subtitles = False
        else:
            self.kctl.subtitles = not self.kctl.subtitles

    def stop(self):
        pass


def create_skill():
    return KodiSkill()
