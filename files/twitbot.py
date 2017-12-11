#!/usr/bin/python
"""
pip install python-twitter
Created by Juha Ylitalo <juha@ylitalot.net>
License: MIT
"""
# pylint: disable=superfluous-parens

import argparse
import json
import os
import smtplib
import sys
import time
import traceback
import unicodedata

from ConfigParser import ConfigParser
from email.mime.text import MIMEText

import requests
import twitter
import urllib3


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
        # Validate Twitter API section
        if config.has_section('api'):
            errors = validate_api_config(config.options('api'))
        else:
            errors = ['api section missing from configuration file']
        if errors:
            return errors
        # Validate feeds
        for topic in get_topics(config.sections()):
            errors.extend(self.validate_topic_config(topic))
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

    def _get_tweets(self, twitter_user, remove):
        """
        Fetch unique tweets from single Twitter account.
        """
        report = []
        if self.debug:
            print("Fetching %s timeline." % (twitter_user))
        # 86400s => 1 day
        tweet_filter = TweetFilter(remove, self._started - 86400)
        tweets = self._get_api().GetUserTimeline(
            screen_name=twitter_user, count=self.__max_items, trim_user=True,
            include_rts=False, exclude_replies=True)
        for tweet in tweets:
            text = tweet_filter.clean_tweet(tweet)
            if tweet_filter.is_unique(text):
                report += [(tweet.created_at_in_seconds, text)]
        report += [(tweet_filter.uniques(), tweet_filter.duplicates())]
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

    def _make_email_text(self, report):
        """
        Format tweets into nice text.
        """
        users, text = make_email_heading(report.keys())
        tweets_found = False
        for user in users:
            found, skipped = report[user].pop(-1)
            if not found:
                continue
            text += make_user_heading(user)
            for tweet in report[user]:
                text += make_tweet_message(tweet[0], tweet[1])
            text += [self._make_summary(found, skipped), '']
            tweets_found = True
        if not tweets_found:
            return None
        text += ['Generated by jylitalo/TwitterBot']
        return '\n'.join(text)

    def _send_email(self, sender, topic, text):
        """
        Send report as e-mail.
        """
        config = self._get_config()
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
        # pylint: disable=broad-except
        config = self._get_config()
        sender = config.get('api', 'mail_from')
        for topic in get_topics(config.sections()):
            try:
                report = {}
                remove = filters(topic, config)
                for twitter_user in config.get(topic, 'users').split(','):
                    report[twitter_user] = self._get_tweets(twitter_user, remove)
                msg = self._make_email_text(report)
                if msg:
                    self._send_email(sender, topic, msg)
                time.sleep(2)
            except Exception as problem:
                log_error("Problem with %s topic. Details are:\n%s" % (topic, str(problem)))

    def validate_topic_config(self, topic):
        """
        Validate twitbot.cf config on single topic
        """
        errors = []
        config = self._get_config()
        mandatory = set(['mailto', 'subject', 'users'])
        missing_options = list(set(config.options(topic)) - mandatory)
        missing_options.sort()
        for missing in missing_options:
            errors += [topic + " doesn't have " + missing]
        if 'users' in missing_options:
            return errors
        api = self._get_api()
        for user in config.get(topic, 'users').split(','):
            try:
                api.GetUserTimeline(screen_name=user, count=1)
            except twitter.error.TwitterError, twit_error:
                msg = "[%s,users] %s => %s"
                errors += [msg % (topic, user, str(twit_error))]
        return errors


class TweetFilter(object):
    """
    Filter tweets.
    """
    def __init__(self, remove, timespan):
        """
        Set instances variables for filtering actions.
        """
        self._uniq_text = set()
        self.remove = remove
        self.timespan = timespan
        self._duplicates = 0

    def clean_tweet(self, tweet):
        """
        Clean unnecessary stuff out from tweet and
        dig final destination of URLs.
        """
        if tweet.created_at_in_seconds < self.timespan:
            return ''
        text = sanitize_text(tweet.full_text, self.remove['text'])
        for spam in self.remove['tweets']:
            if sanitize_text(spam, '') in text:
                return ''
        ret = []
        has_links = False
        for word in text.split(' '):
            if is_http_link(word):
                url = extend_url(word, text)
                if has_links and is_status_media(tweet, word, url):
                    continue
                if self.remove['query_string'] and '?' in url:
                    url = url[:url.find('?')]
                ret += [url]
                has_links = True
            elif word:
                ret += [word]
        return ' '.join(ret)

    def duplicates(self):
        """
        Getter
        """
        return self._duplicates

    def uniques(self):
        """
        Getter
        """
        return len(self._uniq_text)

    def is_unique(self, text):
        """
        Check if text is unique tweet or not.
        """
        text = text.strip()
        if text.endswith('.'):
            text = text[:-1]
        if text:
            if text in self._uniq_text:
                self._duplicates += 1
            else:
                self._uniq_text.add(text)
                return True
        return False


def extend_url(word, text):
    """
    Take shorten url and go through all redirects to find final destination.
    """
    # pylint: disable=broad-except
    url = word
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    try:
        for _ in range(10):
            headers = requests.head(url, allow_redirects=False, verify=False).headers
            if 'location' in headers and is_http_link(headers['location']):
                url = headers['location']
            else:
                break
    except Exception as problem:
        log_error("""Unexpected exception error: %s
Tweet was %s
Word was %s
URL was %s""" % (str(problem), text, word, url))
    return url


def filters(topic, config):
    """
    Analyze topic specific filters.
    """
    options = {'query_string': "", 'text': "", 'tweets': "[]"}
    for key in options:
        if config.has_option(topic, 'remove_' + key):
            options[key] = config.get(topic, 'remove_' + key)
    options['query_string'] = options['query_string'].lower() in ['yes', 'true']
    if options['tweets']:
        options['tweets'] = json.loads(options['tweets'])
    return options


def get_topics(topics):
    """
    Sort possible topics and remove 'api', since it has twitter credentials etc.
    """
    topics.remove('api')
    topics.sort()
    return topics

def is_http_link(url):
    """
    is url is valid http or https link?
    """
    return url.startswith('http://') or url.startswith('https://')


def is_status_media(tweet, word, url):
    """
    Check if URL is embedded photo/video.

    >>> id_str = '920718089037254657'
    >>> word = url = 'https://twitter.com/Google/status/%s/photo/1' % (id_str)
    >>> class Tweet:
    ...     pass
    >>>
    >>> tweet = Tweet()
    >>> tweet.id_str, tweet.full_text = id_str, word
    >>> is_status_media(tweet, word, url)
    True
    >>> tweet.full_text = word + " test"
    >>> is_status_media(tweet, word, url)
    False
    >>> word = url = 'https://twitter.com/Google/status/%s/video/1' % (id_str)
    >>> is_status_media(tweet, word, url)
    True
    >>> word = url = tweet.full_text = 'https://www.youtube.com/watch?v=PIbeiddq_CQ'
    >>> is_status_media(tweet, word, url)
    False
    """
    id_str = tweet.id_str
    text = tweet.full_text
    is_media = False
    if not text.endswith(word) or not url.startswith('https://twitter.com/'):
        return False
    for media in ['photo', 'video']:
        is_media |= url.endswith("status/%s/%s/1" % (id_str, media))
    return is_media


def log_error(message):
    """
    Log error message.
    """
    print(message)
    traceback.print_exc()


def make_email_heading(users):
    """
    Make nice heading for e-mails (if needed) and sort users.
    """
    text = []
    if len(users) > 1:
        users.sort()
        text += ['Twitter report on: ' + ', '.join(users), '']
    return (users, text)


def make_tweet_message(tstamp, text):
    """
    Turn timestamp and text into couple lines in e-mail.
    """
    return [time.asctime(time.localtime(tstamp)), ' '*5 + text]


def make_user_heading(user):
    """
    Return username, twitter URL and line below it.
    """
    line = '%s - https://www.twitter.com/%s:' % (user, user)
    return [line, '*'*len(line)]


def sanitize_text(text, remove_text):
    """
    If tweets has some phrase that we want removed, it is done here.
    We also replace any newlines with space.
    """
    text = unicodedata.normalize('NFKC', text).encode('utf-8')
    if remove_text:
        text = text.replace(remove_text, '')
    return text.replace('\n', ' ')


def validate_api_config(options):
    """
    Validate twitter API configuration (and mail_from option)
    """
    mandatory = ['access_token_key', 'access_token_secret',
                 'consumer_key', 'consumer_secret', 'mail_from']
    missing_options = list(set(options) - set(mandatory))
    missing_options.sort()
    errors = []
    for option in missing_options:
        errors += [option + ' is missing from api section.']
    return errors

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
