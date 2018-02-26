"""
Ansible module for S3 object management.

Requires: Python 3.x

Hint: ansible_python_interpreter=/usr/local/bin/python3
"""
import os
import stat

import botocore
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


S3 = boto3.client('s3')


def bucket_exists(bucket_name):
    """
    Check if S3 bucket with bucket_name already exists.
    """
    buckets = S3.list_buckets()['Buckets']
    return bool([
        bucket['Name'] for bucket in buckets if bucket_name == bucket['Name']
    ])


def object_exists(bucket_name, s3_key, size):
    """
    Check if S3 bucket with bucket_name has object with s3_key, that is size in bytes.
    """
    obj = get_object(bucket_name, s3_key)
    if obj:
        return obj['ContentLength'] == size
    return False


def get_object(bucket_name, object_key):
    """
    Get metadata from S3 object or return None.
    """
    try:
        return S3.get_object(Bucket=bucket_name, Key=object_key)
    except botocore.exceptions.ClientError:
        return None


def create_bucket(bucket_name, aws_region):
    """
    Creates S3 bucket.
    """
    return S3.create_bucket(
        ACL='private',
        Bucket=bucket_name,
        CreateBucketConfiguration={'LocationConstraint': aws_region}
    )


def upload_content(bucket_name, bucket_key, content):
    """
    Upload content (string or file) into bucket_name under bucket_key.
    """
    return S3.put_object(
        ACL='private',
        Bucket=bucket_name,
        Key=bucket_key,
        Body=content,
        ContentLength=len(content)
    )


def main():
    """
    Upload/update content in S3 bucket.
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
    bucket, s3_key = vals['bucket'], vals['key']
    content = vals['content'].encode('utf-8')

    bucket_found = bucket_exists(bucket)
    key_found = None
    if bucket_found:
        if vals['file']:
            key_found = object_exists(bucket, s3_key, os.stat(vals['file'])[stat.ST_SIZE])
        else:
            key_found = object_exists(bucket, s3_key, len(content))
    changed = bool(vals['state'] != 'present' or not (bucket_found and key_found))

    if changed and not module.check_mode:
        if vals['state'] == 'present':
            if not bucket_found:
                create_bucket(bucket, vals['region'])
            if content:
                upload_content(bucket, s3_key, content)
            else:
                upload_content(bucket, s3_key, vals['file'])
        else:
            if key_found:
                S3.delete_object(Bucket=bucket, Key=s3_key)
            if bucket_found:
                S3.delete_bucket(Bucket=bucket)
    module.exit_json(changed=changed)


if __name__ == '__main__':
    main()
