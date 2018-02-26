TwitterBot
==========

Digest twitter feeds (eliminate duplicates)

![Build status](https://travis-ci.org/jylitalo/TwitterBot.svg?branch=master) 

Requirements
------------

python-twitter python module and personal keys to Twitter API.

Role Variables
--------------

From Twitter API:

  * twitter_consumer_key: invalid
  * twitter_consumer_secret: invalid
  * twitter_access_token_key: invalid
  * twitter_access_token_secret: invalid

Twitter Accounts you want to track:

  * twitter_users: jylitalo

Delivery address for report:

  * mail_from: bot@twitbot.invalid
  * mail_to: one@twitbot.invalid,second@twitbot.invalid
  * mail_subject: Twitter feed from ...

Dependencies
------------

None

Example Playbook
----------------

    - hosts: server
      roles:
         - { role: TwitterBot, twitbot_cf: "{{ playbook_dir }}/files/twitter-bot.cf" }

Example Configuration File
--------------------------

```
[api]
access_token_key=...
access_token_secret=...
consumer_key=...
consumer_secret=...

[topic1]
from=...
mailto=...
users=...
subject=...
```

License
-------

MIT

Author Information
------------------

Juha Ylitalo, juha.ylitalo@gmail.com, http://www.ylitalot.com/
