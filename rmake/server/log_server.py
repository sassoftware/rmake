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

import asyncore
import logging
import os
import socket
from rmake.lib import logger as logger_


class LogServer(asyncore.dispatcher):

    def __init__(self, cfg, db, map=None, fork=None, logger=None):
        self.logStore = db.logStore
        if not fork:
            fork = lambda name: os.fork()
        self.fork = fork
        if logger is None:
            logger = logger_.Logger()
        self._logger = logger
        asyncore.dispatcher.__init__(self, map=map)
        self.create_socket(socket.AF_INET6, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.bind(('', cfg.logServerPort))
        # in case the port was set to 0
        cfg.logServerPort = self.socket.getsockname()[1]
        self.listen(5)

    def handle_accept(self):
        sock, addr = self.accept()
        LogClient(sock, self._map, self)


class LogClient(asyncore.dispatcher):

    def __init__(self, sock, map, server):
        asyncore.dispatcher.__init__(self, sock, map)
        self.server = server
        self._logger = server._logger
        self.buf = ''

    def writable(self):
        return False

    def handle_read(self):
        data = self.recv(1024)
        self.buf += data
        if len(self.buf) > 1024:
            self._logger.warning("Bogus logger auth from %s", self.addr)
            self.close()
            return
        if '\n' not in self.buf:
            return
        line = self.buf.split('\n')[0]
        if line.count(' ') < 2:
            self._logger.warning("Bogus logger auth from %s", self.addr)
            self.close()
            return
        logHash, authKey, name = line.split(' ', 2)
        authKey2 = self.server.logStore.getLogAuth(logHash)
        if authKey != authKey2:
            self._logger.warning("HMAC mismatch from logger client %s", self.addr)
            self.close()
            return
        name = name[:64]
        self._logger.debug("Accepted logger connection from %s for %s: %s",
                self.addr, logHash[:12], name)
        f_out = self.server.logStore.openForWriting(logHash)
        f_out.beforeFork()
        pid = self.server.fork("Build logger %s" % name)
        if pid:
            f_out.afterFork()
            self.close()
            return
        try:
            try:
                self._closeFds(f_out.filenos() + [self.socket.fileno()])
                # No more need for asyncore, just do a blocking copy
                self.socket.setblocking(1)
                self.socket.sendall('OK\n')
                while True:
                    try:
                        d = self.socket.recv(16384)
                    except socket.error:
                        break
                    if not d:
                        break
                    f_out.write(d)
                f_out.close()
                try:
                    self.socket.close()
                except (socket.error, OSError):
                    pass
                os._exit(0)
            except:
                import traceback
                traceback.print_exc()
                self._logger.exception("Unhandled error in log recorder:")
        finally:
            os._exit(70)

    def handle_close(self):
        self.close()

    def handle_error(self):
        self._logger.exception("Unhandled error in log recorder:")
        self.close()

    def _closeFds(self, keep=()):
        keep = set(keep)
        for handler in logging.root.handlers:
            if hasattr(handler, 'stream'):
                keep.add(handler.stream.fileno())
        for n in range(3, 256):
            if n not in keep:
                try:
                    os.close(n)
                except OSError as err:
                    pass
