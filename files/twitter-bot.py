#!/usr/bin/python
# pip install python-twitter
# Created by Juha Ylitalo <juha@ylitalot.net>
# License: MIT
# pylint: disable=superfluous-parens

import argparse
import os
import smtplib
import sys
import time

from ConfigParser import ConfigParser
from email.mime.text import MIMEText

import requests
import twitter


class TwitterBot(object):
    """
    Fetches tweets through Twitter API, filter them and
    send them to recipients.
    """
    def __init__(self, cf_file='.twitter-bot.cf', debug=False):
        """
        Init instance variables.
        """
        self._api = None
        self._cf = None
        self.cf_file = cf_file
        self.debug = debug
        self._started = time.time()
        self.__max_items = 100

    def _get_config(self):
        """
        Read configuration file.
        """
        can_read = os.access(self.cf_file, os.R_OK)
        assert can_read, 'Unable to open %s for reading.' % (self.cf_file)
        if not self._cf:
            self._cf = ConfigParser()
            self._cf.read(self.cf_file)
            api_found = 'api' in self._cf.sections()
            assert api_found, 'Twitter API credentials missing.'
        return self._cf

    def validate_config(self):
        """
        Validate TwitterBot configuration.
        Return empty list, if configuration is valid.
        If errors were found, return list of findings
        """
        errors = []
        config = self._get_config()
        sections = config.sections()
        # Validate Twitter API section
        if 'api' in sections:
            for key in ['access_token_key', 'access_token_secret',
                        'consumer_key', 'consumer_secret']:
                if not config.has_option('api', key):
                    errors += [key + ' is missing from api section.']
            sections.remove('api')
        else:
            errors += ['api section missing from configuration file']

        # Validate feeds
        api = self._get_api()
        for section in sections:
            for key in ['from', 'mailto', 'subject', 'users']:
                if not config.has_option(section, key):
                    errors += [section + " doesn't have " + key]
            if config.has_option(section, 'users'):
                for user in config.get(section, 'users').split(','):
                    try:
                        api.GetUserTimeline(screen_name=user, count=1)
                    except twitter.error.TwitterError, twit_error:
                        msg = "[%s,users] %s => %s"
                        errors += [msg % (section, user, str(twit_error))]
        return errors

    def _get_api(self):
        """
        Get handler for Twitter API.
        """
        if not self._api:
            config = self._get_config()
            self._api = twitter.Api(
                access_token_key=config.get('api', 'access_token_key'),
                access_token_secret=config.get('api', 'access_token_secret'),
                consumer_key=config.get('api', 'consumer_key'),
                consumer_secret=config.get('api', 'consumer_secret'),
                tweet_mode='extended')
        return self._api

    def _get_report(self, user, remove):
        """
        Fetch unique tweets from single Twitter account.
        """
        report = []
        days = 1
        timespan = self._started - (days*86400)
        api = self._get_api()
        skipped_items = 0
        if self.debug:
            print("Fetching %s timeline." % (user))
        stats = api.GetUserTimeline(
            screen_name=user, count=self.__max_items, trim_user=True,
            include_rts=False, exclude_replies=True)
        uniq_text = set()
        for stat in stats:
            tweet_time = stat.created_at_in_seconds
            if tweet_time < timespan:
                break
            full_text = clean_tweet(stat.full_text, remove)
            text = full_text.strip()
            if text and text[-1] == '.':
                text = text[-1]
            if text in uniq_text:
                skipped_items += 1
            else:
                uniq_text.add(full_text)
                report.append((tweet_time, full_text))
        report.append((len(uniq_text), skipped_items))
        return report

    def _make_text(self, report):
        """
        Format tweets into nice text.
        """
        users = report.keys()
        users.sort()
        text = ['Twitter report on: ' + ', '.join(users), '']
        for user in users:
            found, skipped = report[user].pop(-1)
            if not found:
                continue
            text += ['%s:\n%s' % (user, '='*(len(user)+1))]
            for tweet in report[user]:
                text += [time.asctime(time.localtime(tweet[0]))]
                text += [' '*5 + tweet[1].encode('utf-8')]
            total_items = found + skipped
            if self.__max_items == total_items:
                text += ['Max number of tweets (%d) fetched.' % (total_items)]
            msg = 'Summary: %d tweets found' % (total_items)
            if skipped:
                msg += ': %d unique and %d duplicates.' % (found, skipped)
            text += [msg, '']
        if len(text) == 2:
            return None
        text += ['Generated by jylitalo/TwitterBot']
        return '\n'.join(text)

    def _send_report(self, topic, text):
        """
        Send report as e-mail.
        """
        config = self._get_config()
        sender = config.get(topic, 'from')
        you = config.get(topic, 'mailto')
        msg = MIMEText(text)
        msg['Subject'] = config.get(topic, 'subject')

        msg['From'] = sender
        msg['To'] = you
        if self.debug:
            print(msg.as_string())
        else:
            smtp = smtplib.SMTP('localhost')
            smtp.sendmail(sender, you.split(','), msg.as_string())
            smtp.quit()

    def make_reports(self):
        """
        Main method.
        Read config, fetch tweets, form report and send it to recipients.
        """
        config = self._get_config()
        topics = config.sections()
        topics.remove('api')
        for topic in topics:
            report = {}
            users = config.get(topic, 'users').split(',')
            remove = None
            if config.has_option(topic, 'remove'):
                remove = config.get(topic, 'remove')
            for user in users:
                report[user] = self._get_report(user, remove)
            msg = self._make_text(report)
            if msg:
                self._send_report(topic, msg)
            time.sleep(2)


def clean_tweet(text, remove):
    """
    Clean unnecessary stuff out from tweet and
    dig final destination of URLs.
    """
    text = text.replace('\n', ' ')
    if remove:
        text = text.replace(remove, '').replace('  ', ' ')
    for word in text.split(' '):
        if word.startswith('http://') or word.startswith('https://'):
            url = word
            count = 0
            while url and count < 10:
              count += 1
              response = requests.get(url, allow_redirects=False)
              if 'location' not in response.headers:
                  break
              elif not response.headers['location'].startswith('http'):
                  break
              else: 
                  url = response.headers['location']
            text = text.replace(word, url)
    return text


def cmd_args():
    """
    Command line arguments for TwitterBot
    """
    parser = argparse.ArgumentParser(description='TwitterBot for digests')
    parser.add_argument('--config', help='configuration file',
                        default='.twitter-bot.cf')
    parser.add_argument('--debug', action='store_true',
                        help='print report instead of sending e-mail')
    parser.add_argument('--validate', action='store_true',
                        help='validate configuration file')
    return parser


if __name__ == '__main__':
    ARGS = cmd_args().parse_args(sys.argv[1:])
    BOT = TwitterBot(ARGS.config, ARGS.debug)
    if ARGS.validate:
        ERRORS = BOT.validate_config()
        if ERRORS:
            print('Following errors found from configuration:')
            print('\n'.join(ERRORS))
            sys.exit(1)
        print('No errors found in configuration.')
    else:
        BOT.make_reports()
    sys.exit(0)
