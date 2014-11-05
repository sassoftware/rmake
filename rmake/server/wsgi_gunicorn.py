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


import os
import socket
import urllib
from gunicorn.app import base
from gunicorn.workers import sync
from rmake.server.wsgi_server import WSGIApplication


class GunicornServer(base.BaseApplication):

    appClass = WSGIApplication

    def __init__(self, configFunc):
        self.configFunc = configFunc
        self.serverCfg = None
        super(GunicornServer, self).__init__()

    def load_config(self):
        if self.serverCfg:
            self.serverCfg.updateFromReloaded(self.configFunc(), log=None)
        else:
            self.serverCfg = self.configFunc()
        self.cfg.set('proc_name', 'rmake rpc')
        self.cfg.set('workers', self.serverCfg.rpcWorkers)
        self.cfg.set('timeout', 3600) # FIXME
        # The config defaults might have been initialized as root so reset
        # uid/gid to the current user
        self.cfg.set('user', os.geteuid())
        self.cfg.set('group', os.getegid())
        worker = SyncWorker
        self.cfg.set('worker_class',
                '%s.%s' % (worker.__module__, worker.__name__))

        bind = []
        for uri in self.serverCfg.getServerUris():
            scheme, url = urllib.splittype(uri)
            if scheme == 'unix':
                bind.append('unix:' + url)
            elif scheme in ('http', 'https'):
                host, path = urllib.splithost(url)
                if ':' in host:
                    host, port = urllib.splitport(host)
                    port = int(port)
                else:
                    port = 9999
                bind.append('[::]:%d' % port)
                if scheme == 'https':
                    self.cfg.set('certfile',
                            self.serverCfg.getSslCertificatePath())
            else:
                raise ValueError("Invalid rmakeUrl %s" % (uri,))
        self.cfg.set('bind', bind)

    def load(self):
        return self.appClass(self.serverCfg)


class SyncWorker(sync.SyncWorker):

    def handle(self, listener, client, addr):
        orig_certfile = self.cfg.certfile
        if client.family == socket.AF_UNIX:
            # Disable SSL for local sockets
            self.cfg.set('certfile', None)
        try:
            return sync.SyncWorker.handle(self, listener, client, addr)
        finally:
            self.cfg.set('certfile', orig_certfile)
