#
# Copyright (c) SAS Institute Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import logging
import os
import socket
import sys
from conary.lib import util
from rmake import errors

log = logging.getLogger(__name__)


class LogFile(object):

    def __init__(self, pathOrLogData):
        self.file_out = None
        self.stdout = None
        self.stderr = None
        self.redirected = False
        if isinstance(pathOrLogData, (list, tuple)):
            self.logToPort(*pathOrLogData)
        elif isinstance(pathOrLogData, basestring):
            self.open(pathOrLogData)
        else:
            raise TypeError

    def open(self, path):
        util.mkdirChain(os.path.dirname(path))
        self.file_out = open(path, 'a')

    def write(self, data):
        self.file_out.write(data)

    def close(self):
        if self.stdout:
            self.restoreOutput()
        if self.file_out:
            self.file_out.close()
            self.file_out = None

    def redirectOutput(self, close=False):
        if self.redirected:
            return
        sys.stdout.flush()
        sys.stderr.flush()
        if not close:
            self.stdout = os.dup(sys.stdout.fileno())
            self.stderr = os.dup(sys.stderr.fileno())
        os.dup2(self.file_out.fileno(), sys.stdout.fileno())
        os.dup2(self.file_out.fileno(), sys.stderr.fileno())
        self.redirected = True

    def logToPort(self, host, port, key=None):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((host, port))
        if key:
            s.send(key + '\n')
            status = s.recv(3)
            if status != 'OK\n':
                raise errors.ServerError("Could not connect to socket")
        self.sock = s
        self.file_out = os.fdopen(s.fileno(), 'w', 1)
        self.redirectOutput()

    def restoreOutput(self):
        if not self.redirected:
            return
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(self.stdout, sys.stdout.fileno())
        os.dup2(self.stderr, sys.stderr.fileno())
        os.close(self.stdout)
        os.close(self.stderr)
        self.stdout = None
        self.stderr = None
        self.redirected = False
