"""
Ansible module for building zip files.

Requires: Python 3.x

Hint: ansible_python_interpreter=/usr/local/bin/python3
"""
import os
import tempfile
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
  build_zip:
    source: "twitbot-user"
    command: "twitbot.cf"
    files: ""{{ lookup('template', './template.j2') }}""
    zip_file: present
'''

RETURNS = '''
'''


def normalize_path(filename, root_dir):
    if filename[0] == '/':
        return filename
    return root_dir + os.sep + filename


def main():
    """
    Implement postmap for Ansible.
    """
    args = {
        'source': {'required': True, 'type': 'str'},
        'command': {'type': 'str', 'default': ''},
        'files': {'type': 'str', 'default': '.'},
        'zip_file': {'type': 'str', 'default': 'build.zip'}
    }
    module = AnsibleModule(argument_spec=args, supports_check_mode=False)
    vals = {key: module.params[key] for key in args}
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp_dir:
        os.chdir(tmp_dir)
        abs_source = normalize_path(vals['source'], cwd)
        zip_file = normalize_path(vals['zip_file'], cwd)
        os.system("rsync -avH %s ./" % (abs_source))
        if vals['command']:
            os.system(vals['command'])
        if os.access(zip_file, os.F_OK):
            os.unlink(zip_file)
        # TODO: Build with python's ZipFile
        files = [line.strip() for line in os.popen(vals['files'], 'r').readlines()]
        os.system("zip %s -X %s" % (zip_file, ' '.join(files)))
    os.chdir(cwd)
    module.exit_json()


if __name__ == '__main__':
    main()
