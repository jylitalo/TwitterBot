#!/usr/bin/python
"""
pip install python-twitter
Created by Juha Ylitalo <juha@ylitalot.net>
License: MIT
"""
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
        tweets = api.GetUserTimeline(
            screen_name=user, count=self.__max_items, trim_user=True,
            include_rts=False, exclude_replies=True)
        uniq_text = set()
        for tweet in tweets:
            tweet_time = tweet.created_at_in_seconds
            if tweet_time < timespan:
                break
            full_text = clean_tweet(tweet, remove)
            text = full_text.strip()
            if text.endswith('.'):
                text = text[:-1]
            if text in uniq_text:
                skipped_items += 1
            else:
                uniq_text.add(full_text)
                report.append((tweet_time, full_text))
        report.append((len(uniq_text), skipped_items))
        return report

    def _make_summary(self, found, skipped):
        """
        Statistics about how many tweets were found, skipped as duplicate, etc.
        """
        total_items = found + skipped
        msg = []
        if self.__max_items == total_items:
            msg += ['Max number of tweets (%d) fetched.' % (total_items)]
        msg += ['Summary: %d tweets found' % (total_items)]
        if skipped:
            msg[-1] += ': %d unique and %d duplicates.' % (found, skipped)
        return '\n'.join(msg)

    def _make_text(self, report):
        """
        Format tweets into nice text.
        """
        users, text = make_heading(report.keys())
        tweets_found = False
        for user in users:
            found, skipped = report[user].pop(-1)
            if not found:
                continue
            text += ['%s - https://www.twitter.com/%s:' % (user, user)]
            text += ['*'*len(text[-1])]
            for tweet in report[user]:
                text += [time.asctime(time.localtime(tweet[0]))]
                text += [' '*5 + tweet[1].encode('utf-8')]
            text += [self._make_summary(found, skipped), '']
            tweets_found = True
        if not tweets_found:
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
            remove = {'query_string': "", 'text': ""}
            for key in ['query_string', 'text']:
                if config.has_option(topic, 'remove_' + key):
                    remove[key] = config.get(topic, 'remove_' + key)
            remove['query_string'] = remove['query_string'].lower() in ['yes', 'true']
            for user in users:
                report[user] = self._get_report(user, remove)
            msg = self._make_text(report)
            if msg:
                self._send_report(topic, msg)
            time.sleep(2)


def make_heading(users):
    """
    Make nice heading for e-mails (if needed) and sort users.
    """
    text = []
    if len(users) > 1:
        users.sort()
        text += ['Twitter report on: ' + ', '.join(users), '']
    return (users, text)


def is_status_photo(tweet, word, url):
    """
    Check if URL is embedded photo/video.

    >>> id_str = '920718089037254657'
    >>> word = url = 'https://twitter.com/Google/status/%s/photo/1' % (id_str)
    >>> class Tweet:
    ...     pass
    >>>
    >>> tweet = Tweet()
    >>> tweet.id_str, tweet.full_text = id_str, word
    >>> is_status_photo(tweet, word, url)
    True
    >>> tweet.full_text = word + " test"
    >>> is_status_photo(tweet, word, url)
    False
    >>> word = url = tweet.full_text = 'https://www.youtube.com/watch?v=PIbeiddq_CQ'
    >>> is_status_photo(tweet, word, url)
    False
    """
    id_str = tweet.id_str
    text = tweet.full_text
    if not text.endswith(word) or not url.startswith('https://twitter.com/'):
        return False
    return url.endswith("status/%s/photo/1" % (id_str))


def is_http_link(url):
    """
    is url is valid http or https link?
    """
    return url.startswith('http://') or url.startswith('https://')


def log_error(problem, text, word, url):
    """
    Log error from clean_tweet.
    """
    print("Unexpected exception error: " + str(problem))
    print("Tweet was " + text)
    print("Word was " + word)
    print("URL was " + url)


def sanitize_text(text, remove_text):
    """
    If tweets has some phrase that we want removed, it is done here.
    We also replace any newlines with space.
    """
    if remove_text:
        text = text.replace(remove_text, '')
    return text.replace('\n', ' ')


def extend_url(word, text):
    """
    Take shorten url and go through all redirects to find final destination.
    """
    # pylint: disable=broad-except
    url = word
    try:
        for _ in range(10):
            headers = requests.head(url, allow_redirects=False).headers
            if 'location' in headers and is_http_link(headers['location']):
                url = headers['location']
            else:
                break
    except Exception as problem:
        log_error(problem, text, word, url)
    return url


def clean_tweet(tweet, remove):
    """
    Clean unnecessary stuff out from tweet and
    dig final destination of URLs.
    """
    text = sanitize_text(tweet.full_text, remove['text'])
    ret = []
    has_links = False
    for word in text.split(' '):
        if is_http_link(word):
            url = extend_url(word, text)
            if has_links and is_status_photo(tweet, word, url):
                continue
            if remove['query_string'] and '?' in url:
                url = url[:url.find('?')]
            ret += [url]
            has_links = True
        elif word:
            ret += [word]
    return " ".join(ret)


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
