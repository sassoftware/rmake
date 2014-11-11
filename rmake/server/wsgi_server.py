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
import sys
import webob
from conary.lib import util
from rmake.lib import logger
from rmake.lib import rpclib
from rmake.lib import xmlrpc_null
from rmake.server import server
from webob import exc


class WSGIApplication(object):

    requestFactory = webob.Request
    responseFactory = webob.Response

    def __init__(self, serverCfg):
        self.serverCfg = serverCfg
        self.logger = logger.ServerLogger('rmake-server',
                serverCfg.getServerLogPath())
        self.logger.disableRPCConsole()
        self.logger.logRPCToFile(serverCfg.getXMLRPCLogPath())
        self.server = server.rMakeServer(serverCfg, self.logger)

    def __call__(self, environ, start_response):
        # gunicorn likes to umask(0) when daemonizing, so put back something
        # reasonable if that's the case.
        oldUmask = os.umask(022)
        if oldUmask != 0:
            os.umask(oldUmask)
        request = self.requestFactory(environ)
        try:
            response = self.handleRequest(request)
            if callable(response):
                # Looks like a webob response
                return response(environ, start_response)
            else:
                # Looks like a vanilla WSGI iterable
                return response
        except exc.HTTPException, err:
            # webob exception response
            return err(environ, start_response)
        except:
            exc_info = sys.exc_info()
            return self.handleError(request, exc_info, start_response)

    def handleRequest(self, request):
        auth = self._getAuth(request)
        auth.setHeaders(request.headers)
        request.auth = auth
        if request.method == 'POST' and request.path in ('/', '/RPC2'):
            return self.handleRPC(request)
        else:
            raise exc.HTTPNotFound()

    def _getAuth(self, request):
        auth = None
        if 'gunicorn.socket' in request.environ:
            sock = request.environ['gunicorn.socket']
            if sock.family == socket.AF_UNIX:
                auth = rpclib.SocketAuth(sock, None)
        if not auth:
            auth = rpclib.HttpAuth(None, request.remote_addr)
        return auth

    def handleRPC(self, request):
        if request.content_type != 'text/xml':
            raise exc.HTTPBadRequest("Wrong Content-Type for XMLRPC request")
        method, params = self._parseRPC(self._unwrapRPC(request))
        responseHandler = WSGIResponseHandler(self.responseFactory)
        self.server._dispatch(method, (request.auth, responseHandler, params))
        return responseHandler.getResponse()

    @staticmethod
    def _unwrapRPC(request):
        stream = request.body_file
        encoding = request.headers.get('Content-Encoding', 'identity')
        if encoding == 'deflate':
            stream = util.decompressStream(stream)
            stream.seek(0)
        elif encoding != 'identity':
            raise exc.HTTPBadRequest("Wrong Content-Encoding for XMLRPC request")
        return stream

    @staticmethod
    def _parseRPC(stream):
        parser, unmarshaller = xmlrpc_null.getparser()
        try:
            while True:
                data = stream.read(16384)
                if not data:
                    break
                parser.feed(data)
            parser.close()
            params = unmarshaller.close()
            method = unmarshaller.getmethodname()
        except Exception:
            raise exc.HTTPBadRequest("Malformed XMLRPC request body")
        return method, params

    def _makeError(self, request, status, *lines):
        self.logger.error("[%s]: %s: %s", request.remote_addr, str(status),
                lines[0])
        body = "ERROR: " + '\r\n'.join(lines) + '\r\n'
        return self.responseFactory(body=body, status=status,
                content_type='text/plain')

    def handleError(self, request, exc_info, start_response):
        self.logger.error("Unhandled error in RPC:", exc_info=exc_info)
        response = self.responseFactory(
                "<h1>500 Internal Server Error</h1>\r\n"
                "<p>An unexpected error occurred on the server. Consult the "
                "server error logs for details.\r\n",
            status='500 Internal Server Error',
            content_type='text/html')
        start_response(response.status, response.headerlist, exc_info)
        return [response.body]


class WSGIResponseHandler(rpclib.XMLRPCResponseHandler):

    def __init__(self, responseFactory):
        self.responseFactory = responseFactory
        self._response = None

    def callResponseFn(self, fn, *args, **kwargs):
        rv = fn(*args, **kwargs)
        self.sendResponse(rv)

    def sendResponse(self, rv):
        responseString = self.serializeResponse(rv)
        response = self.responseFactory(body=responseString)
        response.content_type = 'text/xml'
        self._response = response

    def getResponse(self):
        assert self._response is not None
        return self._response
