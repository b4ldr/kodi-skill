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

    @intent_handler('pause.intent')
    def handle_pause_intent(self, message):
        pause = self.kctl.pause
        if 'pause' in message.data.get('utterance'):
            pause = True
        elif 'unpause' in message.data.get('utterance'):
            pause = False
        else:
            pause = not self.kctl.pause
        self.log.debug('update pause to: %s', pause)
        self.kctl.pause = pause

    @intent_handler('subtitles.intent')
    def handle_subtitles_intent(self, message):
        subtitles = self.kctl.subtitles
        if re.search(r'\bon|enable\b', message.data.get('utterance')):
            subtitles = True
        elif re.search(r'\boff|disable\b', message.data.get('utterance')):
            subtitles = False
        else:
            subtitles = not self.kctl.subtitles
        self.log.debug('update subtitles to: %s', subtitles)
        self.kctl.subtitles = subtitles

    def stop(self):
        pass


def create_skill():
    return KodiSkill()
