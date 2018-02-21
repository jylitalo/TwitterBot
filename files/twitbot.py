#!/usr/bin/python3
"""
pip install python-twitter
Created by Juha Ylitalo <juha@ylitalot.net>
License: MIT
"""

import argparse
import json
import os
import smtplib
import sys
import time
import traceback

from configparser import ConfigParser
from email.mime.text import MIMEText
from multiprocessing import Process

import requests
import twitter
import urllib3


class TwitterBot(object):
    """
    Fetches tweets through Twitter API, filter them and
    send them to recipients.
    """
    def __init__(self, config):
        """
        Init instance variables.
        """
        self.__api = None
        self._cf = config
        self.debug = config.getboolean('api', 'debug', fallback=False)
        self._started = time.time()
        self.__max_items = 100

    def validate_config(self):
        """
        Validate TwitterBot configuration.
        Return empty list, if configuration is valid.
        If errors were found, return list of findings
        """
        errors = []
        # Validate Twitter API section
        if self._cf.has_section('api'):
            errors = validate_api_config(self._cf.options('api'))
        else:
            errors = ['api section missing from configuration file']
        if errors:
            return errors
        # Validate feeds
        for topic in topics(self._cf.sections()):
            errors.extend(self.validate_topic_config(topic))
        return errors

    def _api(self):
        """
        Get handler for Twitter API.
        """
        if not self.__api:
            self.__api = twitter.Api(
                access_token_key=self._cf.get('api', 'access_token_key'),
                access_token_secret=self._cf.get('api', 'access_token_secret'),
                consumer_key=self._cf.get('api', 'consumer_key'),
                consumer_secret=self._cf.get('api', 'consumer_secret'),
                tweet_mode='extended')
        return self.__api

    def _tweets(self, twitter_user, remove):
        """
        Fetch unique tweets from single Twitter account.
        """
        report = []
        if self.debug:
            print("Fetching %s timeline." % (twitter_user))
        # 86400s => 1 day
        tweet_filter = TweetFilter(remove, self._started - 86400)
        tweets = self._api().GetUserTimeline(
            screen_name=twitter_user, count=self.__max_items, trim_user=True,
            include_rts=False, exclude_replies=True)
        for tweet in tweets:
            text = tweet_filter.clean_tweet(tweet)
            if tweet_filter.is_unique(text):
                report += [(tweet.created_at_in_seconds, text)]
        report += [(tweet_filter.uniques(), tweet_filter.duplicates())]
        return report

    def _twitter_user_summary(self, found, skipped):
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

    def _email_text(self, report):
        """
        Format tweets into nice text.
        """
        users, text = email_heading(list(report.keys()))
        tweets_found = False
        for user in users:
            found, skipped = report[user].pop(-1)
            if not found:
                continue
            text += twitter_user_heading(user)
            for tweet in report[user]:
                text += tweet_message(tweet[0], tweet[1])
            text += [self._twitter_user_summary(found, skipped), '']
            tweets_found = True
        if not tweets_found:
            return None
        text += ['Generated by jylitalo/TwitterBot']
        return '\n'.join(text)

    def _send_email(self, sender, topic, text):
        """
        Send report as e-mail.
        """
        you = self._cf.get(topic, 'mailto')
        msg = MIMEText(text)
        msg['Subject'] = self._cf.get(topic, 'subject')

        msg['From'] = sender
        msg['To'] = you
        if self.debug:
            print(msg.as_string())
        else:
            smtp = smtplib.SMTP(self._cf.get('api', 'smtp_host'),
                                self._cf.get('api', 'smtp_port'))
            if self._cf.has_option('api', 'smtp_user'):
                smtp.login(self._cf.get('api', 'smtp_user'),
                           self._cf.get('api', 'smtp_password'))
            smtp.sendmail(sender, you.split(','), msg.as_string())
            smtp.quit()

    def _handle_topic(self, topic):
        """
        Handle topic from configuration file.
        """
        # pylint: disable=broad-except
        try:
            start_time = time.time()
            report = {}
            remove = filters(topic, self._cf)
            for twitter_user in self._cf.get(topic, 'users').split(','):
                report[twitter_user] = self._tweets(twitter_user, remove)
            msg = self._email_text(report)
            if msg:
                sender = self._cf.get('api', 'mail_from')
                self._send_email(sender, topic, msg)
            end_time = time.time()
            log("%s topic took %.1f seconds" % (topic, end_time - start_time))
        except Exception as problem:
            log_error_with_stack(
                "Problem with %s topic. Details are:\n%s" %
                (topic, str(problem))
            )

    def make_reports(self):
        """
        Main method.
        Read config, fetch tweets, form report and send it to recipients.
        """
        # pylint: disable=broad-except
        pids = []
        for topic in topics(self._cf.sections()):
            try:
                pid = Process(target=self._handle_topic, args=(topic,))
                pids += [pid]
                pid.start()
            except Exception as problem:
                log_error_with_stack(
                    "Problem with starting on %s topic. Details are:\n%s" %
                    (topic, str(problem))
                )
        for pid in pids:
            try:
                pid.join()
            except Exception as problem:
                log_error_with_stack(
                    "Problem with joining. Details are:\n%s" % str(problem)
                )

    def validate_topic_config(self, topic):
        """
        Validate twitbot.cf config on single topic
        """
        errors = []
        mandatory = set(['mailto', 'subject', 'users'])
        missing_options = list(mandatory - set(self._cf.options(topic)))
        missing_options.sort()
        for missing in missing_options:
            errors += [topic + " doesn't have " + missing]
        if 'users' in missing_options:
            return errors
        for user in self._cf.get(topic, 'users').split(','):
            try:
                self._api().GetUserTimeline(screen_name=user, count=1)
            except twitter.error.TwitterError as twit_error:
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
        text = tweet.full_text
        text = text.replace('\n', '').replace(self.remove['text'], '')
        for spam in self.remove['tweets']:
            if spam in text:
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
            headers = requests.head(
                url, allow_redirects=False, verify=False, timeout=5).headers
            if 'location' in headers and is_http_link(headers['location']):
                url = headers['location']
            else:
                break
    except requests.exceptions.ConnectionError as problem:
        log_error("""ConnectionError:
Tweet was %s
Word was %s
URL was %s""" % (text, word, url))
    except requests.exceptions.ReadTimeout:
        pass
    except Exception as problem:
        log_error_with_stack("""Unexpected exception error: %s
Tweet was %s
Word was %s
URL was %s""" % (str(problem), text, word, url))
    return url


def is_true(string):
    """
    Given string is a word yes or true in lowercase, uppercase or mixture.
    """
    return string.lower() in ['yes', 'true']


def filters(topic, config):
    """
    Analyze topic specific filters.
    """
    options = {'query_string': "", 'text': "", 'tweets': "[]"}
    for key in options:
        if config.has_option(topic, 'remove_' + key):
            options[key] = config.get(topic, 'remove_' + key)
    options['query_string'] = is_true(options['query_string'])
    if options['tweets']:
        options['tweets'] = json.loads(options['tweets'])
    return options


def topics(sections):
    """
    Sort possible topics list and remove 'api',
    since it has twitter credentials etc.
    """
    sections.remove('api')
    sections.sort()
    return sections


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
    >>> word = url = tweet.full_text = 'https://www.youtube.com/watch?v=PIq_CQ'
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


def log(message):
    """
    Log non-error message.
    """
    print(message)


def log_error(message):
    """
    Log error message.
    """
    print(message)


def log_error_with_stack(message):
    """
    Log error message with stacktrace.
    """
    print(message)
    traceback.print_exc()


def email_heading(users):
    """
    Make nice heading for e-mails (if needed) and sort users.
    """
    text = []
    if len(users) > 1:
        users.sort()
        text += ['Twitter report on: ' + ', '.join(users), '']
    return (users, text)


def tweet_message(tstamp, text):
    """
    Turn timestamp and text into couple lines in e-mail.
    """
    return [time.asctime(time.localtime(tstamp)), ' '*5 + text]


def twitter_user_heading(user):
    """
    Return username, twitter URL and line below it.
    """
    line = '%s - https://www.twitter.com/%s:' % (user, user)
    return [line, '*'*len(line)]


def validate_api_config(options):
    """
    Validate twitter API configuration (and mail_from option)
    """
    mandatory = ['access_token_key', 'access_token_secret',
                 'consumer_key', 'consumer_secret', 'mail_from',
                 'smtp_host', 'smtp_port']
    missing_options = list(set(mandatory) - set(options))
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
                        default='.twitbot.cf')
    parser.add_argument('--debug', action='store_true',
                        help='print report instead of sending e-mail')
    parser.add_argument('--validate', action='store_true',
                        help='validate configuration file')
    return parser


def get_config(cf_file):
    """
    Read configuration file.
    """
    can_read = os.access(cf_file, os.R_OK)
    assert can_read, 'Unable to open %s for reading.' % (cf_file)
    config = ConfigParser()
    config.read(cf_file)
    assert 'api' in config.sections(), 'API credentials missing.'
    return config


# pylint: disable=unused-argument
def lambda_handler(event, context):
    """
    Main method for Lambda version.
    """
    config = get_config('twitbot.cf')
    config.set('api', 'debug', 'False')
    for key in os.environ:
        if key.startswith('SMTP_'):
            config.set('api', key.lower(), os.environ[key])
        elif key.startswith('TWITTER_'):
            config.set('api', key.lower().split('_', 1)[1], os.environ[key])
        elif key == 'DEBUG':
            config.set('api', key.lower(), os.environ[key])
    TwitterBot(config).make_reports()
    return True


if __name__ == '__main__':
    ARGS = cmd_args().parse_args(sys.argv[1:])
    CONFIG = get_config(ARGS.config)
    if ARGS.debug:
        CONFIG.set('api', 'debug', str(ARGS.debug))
    BOT = TwitterBot(CONFIG)
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
