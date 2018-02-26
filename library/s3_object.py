"""
Ansible module for S3 object management.

Requires: Python 3.x

Hint: ansible_python_interpreter=/usr/local/bin/python3
"""
import os
import stat

import boto3
from ansible.module_utils.basic import AnsibleModule

ANSIBLE_METADATA = {
    'metadata_version': '0.1',
    'status': ['preview'],
    'supported_by': 'community'
}

DOCUMENTATION = '''
---
module: s3_object
short_description: Sync s3 object into bucket (and create bucket if needed)
'''

EXAMPLES = '''
- name: Update configuration
  s3_object:
    bucket: "twitbot-user"
    key: "twitbot.cf"
    content: "{{ lookup('template', './template.j2') }}"
    state: present
'''

RETURNS = '''
'''


def scan(paginator, field, target):
    for page in paginator:
        for object in page:
            if object[field] == target:
                return object
    return None


def get_bucket(s3, bucket_name):
    buckets = s3.list_buckets()['Buckets']
    return [bucket['Name'] for bucket in buckets if bucket_name == bucket['Name']]


def get_object(s3, bucket_name, object_key, content):
    paginator = s3.get_paginator('list_objects').paginate(
        Bucket=bucket_name,
        Prefix=object_key
    )
    return scan(paginator, 'Key', object_key)


def create_bucket(s3, bucket_name, aws_region):
    s3.create_bucket(
        ACL='private',
        Bucket=bucket_name,
        CreateBucketConfiguration={'LocationConstraint': aws_region}
    )


def upload_content(s3, bucket_name, bucket_key, content):
    s3.put_object(
        ACL='private',
        Bucket=bucket_name,
        Key=bucket_key,
        Body=content,
        ContentLenght=len(content)
    )


def main():
    """
    Implement postmap for Ansible.
    """
    args = {
        'bucket': {'required': True, 'type': 'str'},
        'key': {'required': True, 'type': 'str'},
        'file': {'type': 'str', 'default': ''},
        'content': {'type': 'str', 'default': ''},
        'region': {'type': 'str', 'default': 'eu-west-1'},
        'state': {'type': 'str', 'default': 'present'}
    }
    module = AnsibleModule(argument_spec=args, supports_check_mode=True)
    vals = {key: module.params[key] for key in args}
    content = vals['content'].encode('utf-8')

    s3 = boto3.client('s3')
    bucket_found = get_bucket(s3, vals['bucket'])
    object_found = None
    if bucket_found:
        print("bucket_found=%s" %(bucket_found))
        obj = get_object(s3, vals['bucket'], vals['key'], content)
        if vals['file']:
            object_found = obj['Size'] == os.path.stat(vals['file'])[stat.ST_SIZE]
        else:
            object_found = obj['Size'] == len(content)
    changed = vals['state'] != 'present' or (bucket_found and object_found)

    if changed and not module.check_mode:
        if vals['state'] == 'present':
            if not bucket_found:
                create_bucket(s3, vals['bucket'], vals['region'])
            upload_content(s3, vals['bucket'], vals['key'], content)
        else:
            s3.delete_object(Bucket=vals['bucket'], Key=vals['key'])
            s3.delete_bucket(Bucket=vals['bucket'])
    module.exit_json(changed=changed)


if __name__ == '__main__':
    main()
