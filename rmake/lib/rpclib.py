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


"""
Classes for extracting and examining authentification methods passed from 
external servers
"""
import base64
import fcntl
import IN
import pwd
import sys
import os
from SimpleXMLRPCServer import (SimpleXMLRPCServer, SimpleXMLRPCRequestHandler,
                                SimpleXMLRPCDispatcher)
import xmlrpclib
import socket
import SocketServer
import struct
import urllib

from rmake.lib import localrpc
from rmake.lib import xmlrpc_null


# Secure server support
try:
    open_https = urllib.URLopener.open_https
    try:
        from M2Crypto import SSL
        from M2Crypto.SSL import SSLError
    finally:
        # M2Crypto calls it "minor brain surgery" to replace this fn behind
        # people's backs.  I call it brain dead library behavior.
        urllib.URLopener.open_https = open_https
except ImportError:
    SSLError = None.__class__
    SSL = None


class AuthObject(object):
    __slots__ = ['headers']

    def __init__(self, request):
        self.headers = None

    def setHeaders(self, headers):
        self.headers = headers

    def getSocketUser(self):
        return None

    def getCertificateUser(self):
        return None

    def getUser(self):
        return None

    def getPassword(self):
        return None


class HttpAuth(AuthObject):

    __slots__ = [ 'user', 'password', 'ip_address' ]

    def __init__(self, request, client_address):
        AuthObject.__init__(self, request)
        self.user = None
        self.password = None
        self.ip_address = client_address[0]

    def setHeaders(self, headers):
        self.headers = headers
        if 'Authorization' in self.headers:
            userInfo = self.headers['Authorization']
            userPass = base64.b64decode(userInfo[6:])
            if userPass.count(":") > 1:
                raise RuntimeError('Password may not contain colons')
            user, password = userPass.split(':')
            self.user = user
            self.password = password
        self.headers = headers

    def getIP(self):
        return self.ip_address

    def getUser(self):
        return self.user

    def getPassword(self):
        return self.password

    def __repr__(self):
        if self.user:
            return 'HttpAuth(user=%s)' % self.user
        else:
            return 'HttpAuth()'


class SocketAuth(HttpAuth):
    __slots__ = ['pid', 'uid', 'gid', 'socketUser']

    def __init__(self, request, client_address):
        # get the peer credentials
        buf = request.getsockopt(socket.SOL_SOCKET, IN.SO_PEERCRED, 12)
        creds = struct.unpack('iii', buf)
        self.pid = creds[0]
        self.uid = creds[1]
        self.gid = creds[2]
        HttpAuth.__init__(self, request, ('127.0.0.1', None))

    def getSocketUser(self):
        return pwd.getpwuid(self.uid).pw_name

    getUser = getSocketUser

    def getIP(self):
        return '127.0.0.1'

    def __repr__(self):
        return 'SocketAuth(pid=%s, uid=%s, gid=%s)' % (self.pid, self.uid,
                                                       self.gid)


class QuietXMLRPCRequestHandler(SimpleXMLRPCRequestHandler):
    def __init__(self, *args, **kw):
        self.verbose = False
        SimpleXMLRPCRequestHandler.__init__(self, *args, **kw)

    def setVerbose(self, b=True):
        self.verbose = b

    def log_message(self, format, *args):
        if self.verbose:
            SimpleXMLRPCServer.log_message(self, format, *args)


class AuthenticatedXMLRPCRequestHandler(QuietXMLRPCRequestHandler):

    def do_POST(self):
        # reads in from self.rfile.
        # gets response from self.server._marshaled_dispatch
        # we need to break in here and say if response is None, send
        # no response.
        # possibly send in requestHandler to allow user
        # to send response later.
        # sends response back.
        try:
            # get arguments
            data = self.rfile.read(int(self.headers["content-length"]))
            # In previous versions of SimpleXMLRPCServer, _dispatch
            # could be overridden in this class, instead of in
            # SimpleXMLRPCDispatcher. To maintain backwards compatibility,
            # check to see if a subclass implements _dispatch and dispatch
            # using that method if present.
            self.server._marshaled_dispatch(data,
                                        StreamXMLRPCResponseHandler(self),
                                        self.headers)
        except: # This should only happen if the module is buggy
            # internal error, report as HTTP server error
            self.send_response(500)
            self.end_headers()


class XMLRPCResponseHandler(object):
    def __init__(self, request, debug=True):
        self.request = request
        self.debug = debug

    def callResponseFn(self, fn, *args, **kw):
        try:
            rv = fn(*args, **kw)
            self.sendResponse(rv)
        except:
            self.sendInternalError()

    def sendInternalError(self, tb):
        pass

    def close(self):
        pass

    def serializeResponse(self, response):
        if isinstance(response, xmlrpclib.Fault):
            response = xmlrpc_null.dumps(response)
        else:
            response = (response,)
            response = xmlrpc_null.dumps(response, methodresponse=1)
        return response

    def sendResponse(self, response):
        try:
            response = self.serializeResponse(response)
            self.transferResponse(response)
            self.close()
        except:
            # internal error, report as HTTP server error
            self.sendInternalError()
            self.close()
            self.request.send_response(500)
            self.request.end_headers()


class StreamXMLRPCResponseHandler(XMLRPCResponseHandler):

    def sendInternalError(self):
        self.request.send_response(500)
        self.request.end_headers()

    def close(self):
        self.request.wfile.flush()
        self.request.wfile.close()
        self.request.rfile.close()
        try:
            self.request.connection.close()
        except socket.error:
            pass

    def transferResponse(self, responseString):
        self.request.send_response(200)
        self.request.send_header("Content-type", "text/xml")
        self.request.send_header("Content-length", str(len(responseString)))
        self.request.end_headers()
        self.request.wfile.write(responseString)


class AuthenticatedXMLRPCDispatcher(SimpleXMLRPCDispatcher):
    def __init__(self):
        if sys.version[0:3] == '2.4':
            SimpleXMLRPCDispatcher.__init__(self)
        else:
            SimpleXMLRPCDispatcher.__init__(self, False, None)
        self.authMethod = None

    def setAuthMethod(self, authMethod):
        self.authMethod = authMethod

    def _getAuth(self, request, client_address):
        if self.authMethod:
            return self.authMethod(request, client_address)
        else:
            return None

    def verify_request(self, request, client_address):
        self.auth = self._getAuth(request, client_address)
        return True

    def _marshaled_dispatch(self, data, responseHandler, headers):
        params, method = xmlrpc_null.loads(data)
        if self.auth:
            self.auth.setHeaders(headers)
        # generate response
        try:
            self._dispatch(method, self.auth, responseHandler, params)
        except xmlrpclib.Fault, fault:
            responseHandler.sendResponse(fault)
        except:
            responseHandler.sendResponse(
                xmlrpclib.Fault(1, "%s:%s" % (sys.exc_type, sys.exc_value)))

    def _dispatch(self, method, auth, response_method, params):
        params = (self.auth, response_method, params)
        SimpleXMLRPCDispatcher._dispatch(self, method, params)


class AuthenticatedXMLRPCServer(AuthenticatedXMLRPCDispatcher, SimpleXMLRPCServer):
    def __init__(self, path, requestHandler=AuthenticatedXMLRPCRequestHandler,
            logRequests=1, ssl=False, sslCert=None):
        self.sslCert = sslCert
        self.ssl = ssl

        SimpleXMLRPCServer.__init__(self, path, requestHandler, logRequests)
        AuthenticatedXMLRPCDispatcher.__init__(self)

    def server_bind(self):
        self.allow_reuse_address = True
        fcntl.fcntl(self.socket.fileno(), fcntl.F_SETFD,
                fcntl.fcntl(self.socket.fileno(), fcntl.F_GETFD)
                | fcntl.FD_CLOEXEC)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR,1)
        SimpleXMLRPCServer.server_bind(self)
        self.port = self.socket.getsockname()[1]
        if self.ssl:
            if SSL is None:
                print "Please install m2crypto"
                sys.exit(1)
            ctx = SSL.Context("sslv23")
            # Server cert + key
            ctx.load_cert_chain(self.sslCert, self.sslCert)

            self.socket = SSL.Connection(ctx, self.socket)

            # Hack to work around SocketServer assumptions in python 2.6
            if not hasattr(self.socket, 'gettimeout'):
                self.socket.gettimeout = lambda: None

    def getPort(self):
        return self.port

    def handle_request(self):
        try:
            return SimpleXMLRPCServer.handle_request(self)
        except SSLError, e:
            return


class UnixDomainAuthenticatedXMLRPCRequestHandler(
                                     localrpc.UnixDomainHTTPRequestHandler,
                                     AuthenticatedXMLRPCRequestHandler):
    pass


class UnixDomainAuthenticatedXMLRPCServer(AuthenticatedXMLRPCDispatcher,
                                      SocketServer.UnixStreamServer):
    def __init__(self, path,
            requestHandler=UnixDomainAuthenticatedXMLRPCRequestHandler,
            logRequests=1):
        self.logRequests = logRequests
        AuthenticatedXMLRPCDispatcher.__init__(self)
        umask = os.umask(0)
        SocketServer.UnixStreamServer.__init__(self, path, requestHandler)
        os.umask(umask)
