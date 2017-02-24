TwitterBot
==========

Digest twitter feeds (eliminate duplicates) Edit

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

License
-------

MIT

Author Information
------------------

An optional section for the role authors to include contact information, or a website (HTML is not allowed).
