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
import SocketServer
import urllib
from wsgiref import handlers
from wsgiref import simple_server
from rmake.server.wsgi_server import WSGIApplication

log = logging.getLogger(__name__)


class ServerHandler(handlers.SimpleHandler):
    error_status = '500 Internal Server Error'

    def __init__(self, stdin, stdout, stderr, environ):
        handlers.SimpleHandler.__init__(self, stdin, stdout, stderr, environ,
                multithread=False, multiprocess=False)


class UnixRequestHandler(simple_server.WSGIRequestHandler):

    def get_environ(self):
        self.client_address = (self.client_address, '')
        env = simple_server.WSGIRequestHandler.get_environ(self)
        env['gunicorn.socket'] = self.connection
        return env

    def log_request(self, *args, **kwargs):
        pass

    def log_message(self, fmt, *args):
        log.error(fmt, *args)


class UnixDomainHTTPServer(
        SocketServer.UnixStreamServer,
        simple_server.WSGIServer,
        ):

    def server_bind(self):
        SocketServer.UnixStreamServer.server_bind(self)
        self.server_name = socket.gethostname()
        self.server_port = ''
        self.setup_environ()


def run_simple(cfg):
    app = WSGIApplication(cfg)
    uris = cfg.getServerUris()
    assert len(uris) == 1
    scheme, path = urllib.splittype(uris[0])
    if scheme != 'unix':
        raise ValueError("Unsupported URL type for single-process server: " +
                uris[0])
    path = '/' + path.lstrip('/')
    if os.path.exists(path):
        os.unlink(path)
    umask = os.umask(0)
    server = UnixDomainHTTPServer(path, UnixRequestHandler)
    os.umask(umask)
    server.set_app(app)
    server.serve_forever()
