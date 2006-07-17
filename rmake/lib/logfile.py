#
# Copyright (c) 2006 rPath, Inc.
#
# This program is distributed under the terms of the Common Public License,
# version 1.0. A copy of this license should have been distributed with this
# source file in a file called LICENSE. If it is not present, the license
# is always available at http://www.opensource.org/licenses/cpl.php.
#
# This program is distributed in the hope that it will be useful, but
# without any warranty; without even the implied warranty of merchantability
# or fitness for a particular purpose. See the Common Public License for
# full details.
#
import os
import select
import signal
import sys
import time

from conary.lib import util

class LogFile(object):

    def __init__(self, path, mode='a'):
        self.fd = None
        self.tee = None
        self.stdout = None
        self.open(path, mode)

    def __del__(self):
        if self.fd:
            self.close()

    def open(self, path, mode):
        if isinstance(path, int):
            logfd = path
        else:
            util.mkdirChain(os.path.dirname(path))
            logfd = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY)
        self.fd = logfd

    def write(self, data):
        os.write(self.fd, data)

    def close(self):
        if self.stdout:
            self.restoreOutput()
        if self.fd:
            file = os.fdopen(self.fd, 'w')
            file.flush()
            file.close()
            self.fd = None
        if self.tee:
            self.tee.close()
            self.tee = None

    def teeOutput(self):
        self.tee = Tee()
        outFile = self.tee.tee(self.fd, sys.stdout.fileno())
        os.close(self.fd)
        self.fd = outFile
        self.redirectOutput()

    def redirectOutput(self, close=False):
        sys.stdout.flush()
        sys.stderr.flush()
        if not close:
            self.stdout = os.dup(sys.stdout.fileno())
            self.stderr = os.dup(sys.stderr.fileno())

        os.dup2(self.fd, sys.stdout.fileno())
        os.dup2(self.fd, sys.stderr.fileno())

    def restoreOutput(self):
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(self.stdout, sys.stdout.fileno())
        os.dup2(self.stderr, sys.stderr.fileno())
        os.close(self.stdout)
        os.close(self.stderr)
        self.stdout = None
        self.stderr = None

class Tee(object):
    def __init__(self):
        self.pid = None

    def __del__(self):
        if self.pid:
            self.close()

    def close(self):
        if self.pid:
            pid = self.pid
            self.pid = None
            os.waitpid(pid, 0)

    def tee(self, out1, out2):
        inFile, outFile = os.pipe()
        self.outFile = outFile
        self.pid = os.fork()
        if self.pid:
            os.close(inFile)
            return outFile

        try:
            os.close(outFile)
            BUFFER = 64 * 1024
            while True:
                ready = select.select([inFile], [], [])[0]
                rv = os.read(inFile, BUFFER)
                if not rv:
                    break
                os.write(out1, rv)
                os.write(out2, rv)
        finally:
            os._exit(0)
