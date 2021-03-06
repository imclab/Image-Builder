# vim: tabstop=4 shiftwidth=4 softtabstop=4

#    Copyright (C) 2012 Yahoo! Inc. All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from StringIO import StringIO

import contextlib
import errno
import hashlib
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
import types
import urllib2

import progressbar
import termcolor
import yaml

COLORS = termcolor.COLORS.keys()


class ProcessExecutionError(IOError):

    MESSAGE_TMPL = ('%(description)s\n'
                    'Command: %(cmd)s\n'
                    'Exit code: %(exit_code)s\n'
                    'Reason: %(reason)s\n'
                    'Stdout: %(stdout)r\n'
                    'Stderr: %(stderr)r')

    def __init__(self, stdout=None, stderr=None,
                 exit_code=None, cmd=None,
                 description=None, reason=None):
        if not cmd:
            self.cmd = '-'
        else:
            self.cmd = cmd

        if not description:
            self.description = 'Unexpected error while running command.'
        else:
            self.description = description

        if not isinstance(exit_code, (long, int)):
            self.exit_code = '-'
        else:
            self.exit_code = exit_code

        if not stderr:
            self.stderr = ''
        else:
            self.stderr = stderr

        if not stdout:
            self.stdout = ''
        else:
            self.stdout = stdout

        if reason:
            self.reason = reason
        else:
            self.reason = '-'

        message = self.MESSAGE_TMPL % {
            'description': self.description,
            'cmd': self.cmd,
            'exit_code': self.exit_code,
            'stdout': self.stdout,
            'stderr': self.stderr,
            'reason': self.reason,
        }
        IOError.__init__(self, message)


def is_terminal():
    return sys.stdout.isatty()


def quote(data, quote_color='green'):
    if not is_terminal():
        return "'%s'" % (data)
    else:
        text = str(data)
        if len(text) == 0:
            text = "''"
        if not quote_color:
            quote_color = random.choice(COLORS)
        return color(text, quote_color)


def color(data, color, bold=False, underline=False, blink=False):
    text = str(data)
    text_attrs = list()
    if bold:
        text_attrs.append('bold')
    if underline:
        text_attrs.append('underline')
    if blink:
        text_attrs.append('blink')
    if is_terminal() and color in COLORS:
        return termcolor.colored(text, color, attrs=text_attrs)
    else:
        return text


def find_file(name, path):
    for (root, _dirs, files) in os.walk(path):
        if name in files:
            return os.path.join(root, name)
    return None


def download_url(url, where_to, timeout=5):
    with contextlib.closing(urllib2.urlopen(url, timeout=timeout)) as rh:
        status = rh.getcode()
        if status not in xrange(200, 300):
            raise RuntimeError("Fetch failed due to status %s" % (status))
        headers = rh.headers
        clen = headers.get('Content-Length')
        try:
            clen = int(clen)
        except:
            clen = -1
        pbar = None
        if clen > 0:
            widgets = [
                'Fetching: ', progressbar.Percentage(),
                ' ', progressbar.Bar(),
                ' ', progressbar.ETA(),
                ' ', progressbar.FileTransferSpeed(),
            ]
            pbar = progressbar.ProgressBar(maxval=clen, widgets=widgets)
            pbar.start()

        def call_cb(byte_down, _chunk):
            if pbar:
                pbar.update(byte_down)

        try:
            with open(where_to, 'w') as wh:
                pipe_in_out(rh, wh, chunk_cb=call_cb)
        finally:
            if pbar:
                pbar.finish()


def pretty_transfer(in_fh, out_fh, quiet=False, 
                    max_size=None, name=None, chunk_cb=None):
    pbar = None
    if not quiet and max_size is not None:
        if name:
            title = "%s: " % (name)
        else:
            title = ''
        widgets = [
            title,
            progressbar.Percentage(),
            ' ', progressbar.Bar(),
            ' ', progressbar.ETA(),
            ' ', progressbar.FileTransferSpeed(),
        ]
        pbar = progressbar.ProgressBar(maxval=max_size, widgets=widgets)
        pbar.start() 

    def progress_cb(tran_byte_am, chunk):
        if pbar:
            pbar.update(tran_byte_am)
        if chunk_cb:
            chunk_cb(tran_byte_am, chunk)

    try:
        pipe_in_out(in_fh, out_fh, chunk_cb=progress_cb)
    finally:
        if pbar:
            pbar.finish()


def obj_name(obj):
    if isinstance(obj, (types.TypeType,
                        types.ModuleType,
                        types.FunctionType,
                        types.LambdaType)):
        return str(obj.__name__)
    return obj_name(obj.__class__)


@contextlib.contextmanager
def tempdir(**kwargs):
    # This seems like it was only added in python 3.2
    # Make it since its useful...
    # See: http://bugs.python.org/file12970/tempdir.patch
    tdir = tempfile.mkdtemp(**kwargs)
    try:
        yield tdir
    finally:
        del_dir(tdir)


def del_dir(path):
    shutil.rmtree(path)


def load_file(fname, read_cb=None, quiet=False):
    contents = None
    try:
        with open(fname, 'rb') as ifh:
            ofh = StringIO()
            pipe_in_out(ifh, ofh, chunk_cb=read_cb)
            contents = ofh.getvalue()
    except IOError as e:
        if not quiet:
            if e.errno != errno.ENOENT:
                raise
    return contents


def pipe_in_out(in_fh, out_fh, chunk_size=1024, chunk_cb=None):
    bytes_piped = 0
    while True:
        data = in_fh.read(chunk_size)
        if data == '':
            break
        else:
            out_fh.write(data)
            bytes_piped += len(data)
            if chunk_cb:
                chunk_cb(bytes_piped, data)
    out_fh.flush()
    return bytes_piped


def print_iterable(to_log, header=None, do_color=True):
    if not to_log:
        return
    if header:
        if not header.endswith(":"):
            header += ":"
        print(header)
    for c in to_log:
        if do_color:
            c = color(c, 'blue')
        print("|-- %s" % (c))


def hash_blob(blob, routine):
    hasher = hashlib.new(routine)
    hasher.update(blob)
    return hasher.hexdigest()


def ensure_dirs(dirlist, mode=0755):
    for d in dirlist:
        ensure_dir(d, mode)


def load_yaml(blob):
    return yaml.safe_load(str(blob))


def ensure_dir(path, mode=None):
    if not os.path.isdir(path):
        os.makedirs(path)
        chmod(path, mode)
    else:
        chmod(path, mode)


def del_file(path):
    try:
        os.unlink(path)
    except OSError as e:
        if e.errno != errno.ENOENT:
            raise e


def copy(src, dest):
    shutil.copy(src, dest)


def time_rfc2822():
    try:
        ts = time.strftime("%a, %d %b %Y %H:%M:%S %z", time.gmtime())
    except:
        ts = "??"
    return ts


def ensure_file(path, mode=0644):
    write_file(path, content='', omode="ab", mode=mode)


def chmod(path, mode):
    real_mode = None
    try:
        real_mode = int(mode)
    except (ValueError, TypeError):
        pass
    if path and real_mode:
        os.chmod(path, real_mode)


def write_file(filename, content, mode=0644, omode="wb"):
    ensure_dir(os.path.dirname(filename))
    with open(filename, omode) as fh:
        fh.write(content)
        fh.flush()
    chmod(filename, mode)


def subp(args, data=None, rcs=None, env=None, capture=True, shell=False):
    if rcs is None:
        rcs = [0]
    try:
        print(("++ Running command %s with allowed return codes %s"
               " (shell=%s, capture=%s)") % (args, rcs, shell, capture))
        if not capture:
            stdout = None
            stderr = None
        else:
            stdout = subprocess.PIPE
            stderr = subprocess.PIPE
        stdin = subprocess.PIPE
        sp = subprocess.Popen(args, stdout=stdout,
                        stderr=stderr, stdin=stdin,
                        env=env, shell=shell)
        (out, err) = sp.communicate(data)
    except OSError as e:
        raise ProcessExecutionError(cmd=args, reason=e)
    rc = sp.returncode
    if rc not in rcs:
        raise ProcessExecutionError(stdout=out, stderr=err,
                                    exit_code=rc,
                                    cmd=args)
    # Just ensure blank instead of none?? (iff capturing)
    if not out and capture:
        out = ''
    if not err and capture:
        err = ''
    return (out, err)


def abs_join(*paths):
    return os.path.abspath(os.path.join(*paths))
