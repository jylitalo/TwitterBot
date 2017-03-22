#!/usr/bin/python
# pip install python-twitter
# Created by Juha Ylitalo <juha@ylitalot.net>
# License: MIT

import argparse
import os
import smtplib
import sys
import time
import twitter

from ConfigParser import ConfigParser
from email.mime.text import MIMEText


class TwitterBot:
    def __init__(self, cf_file='.twitter-bot.cf', debug=False):
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
        cf = self._get_config()
        sections = cf.sections()
        # Validate Twitter API section
        if 'api' in sections:
            for key in ['access_token_key', 'access_token_secret',
                        'consumer_key', 'consumer_secret']:
                if not cf.has_option('api', key):
                    errors += [key + ' is missing from api section.']
            sections.remove('api')
        else:
            errors += ['api section missing from configuration file']

        # Validate feeds
        api = self._get_api()
        for section in sections:
            for key in ['from', 'mailto', 'subject', 'users']:
                if not cf.has_option(section, key):
                    errors += [section + " doesn't have " + key]
            if cf.has_option(section, 'users'):
                for user in cf.get(section, 'users').split(','):
                    try:
                        api.GetUserTimeline(screen_name=user, count=1)
                    except twitter.error.TwitterError, e:
                        msg = "[%s,users] %s => %s"
                        errors += [msg % (section, user, str(e))]
        return errors

    def _get_api(self):
        """
        Get handler for Twitter API.
        """
        if not self._api:
            cf = self._get_config()
            self._api = twitter.Api(
                access_token_key=cf.get('api', 'access_token_key'),
                access_token_secret=cf.get('api', 'access_token_secret'),
                consumer_key=cf.get('api', 'consumer_key'),
                consumer_secret=cf.get('api', 'consumer_secret'))
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
            screen_name=user, count=self.__max_items,
            include_rts=False, exclude_replies=True)
        uniq_text = set()
        for stat in stats:
            t = stat.created_at_in_seconds
            if t < timespan:
                break
            full_text = stat.text
            full_text = full_text.replace('\n', ' ')
            if remove:
                full_text = full_text.replace(remove, '').replace('  ', ' ')
            text = full_text.split('https://t.co/')[0].strip()
            if text and text[-1] == '.':
                text = text[-1]
            if text in uniq_text:
                skipped_items += 1
            else:
                uniq_text.add(text)
                report.append((t, full_text))
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
            text += ['No new tweets found.', '']
        text += ['Generated by jylitalo/TwitterBot']
        return '\n'.join(text)

    def _send_report(self, topic, text):
        """
        Send report as e-mail.
        """
        cf = self._get_config()
        me = cf.get(topic, 'from')
        you = cf.get(topic, 'mailto')
        msg = MIMEText(text)
        msg['Subject'] = cf.get(topic, 'subject')

        msg['From'] = me
        msg['To'] = you
        if self.debug:
            print(msg.as_string())
        else:
            s = smtplib.SMTP('localhost')
            s.sendmail(me, you.split(','), msg.as_string())
            s.quit()

    def make_reports(self):
        cf = self._get_config()
        topics = cf.sections()
        topics.remove('api')
        for topic in topics:
            report = {}
            users = cf.get(topic, 'users').split(',')
            remove = None
            if cf.has_option(topic, 'remove'):
                remove = cf.get(topic, 'remove')
            for user in users:
                report[user] = self._get_report(user, remove)
            self._send_report(topic, self._make_text(report))
            time.sleep(2)


def cmdArgs():
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
    cmdline = cmdArgs()
    args = cmdline.parse_args(sys.argv[1:])
    tb = TwitterBot(args.config, args.debug)
    if args.validate:
        errors = tb.validate_config()
        if errors:
            print('Following errors found from configuration:')
            print('\n'.join(errors))
            sys.exit(1)
        print('No errors found in configuration.')
    else:
        tb.make_reports()
    sys.exit(0)
