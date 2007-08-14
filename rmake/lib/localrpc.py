#
# Copyright (c) 2006-2007 rPath, Inc.  All Rights Reserved.
#

# XML-RPC transport over unix domain sockets

import os
import httplib
import xmlrpclib
import socket
import BaseHTTPServer
import SocketServer
import SimpleXMLRPCServer
import urllib
import IN
import struct

BUFSIZE = 1024 * 2

# client implementation
class UnixDomainHTTPConnection(httplib.HTTPConnection):
    def _set_hostport(self, path, port=None):
        # set the host, which in our case is a path to the unix domain socket
        userinfo, rest = urllib.splituser(path)
        self.path = rest

    def connect(self):
        try:
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.setsockopt(IN.PF_UNIX, IN.SO_PASSCRED, 1)
            if self.debuglevel > 0:
                print "connect: %s" % self.path
            self.sock.connect(self.path)
        except socket.error, msg:
            if self.debuglevel > 0:
                print 'connect fail:', self.path
            if self.sock:
                self.sock.close()
            raise

class UnixDomainHTTP(httplib.HTTP):
    _connection_class = UnixDomainHTTPConnection

    def __init__(self, path):
        self._setup(self._connection_class(path))

class UnixDomainTransport(xmlrpclib.Transport):
    def make_connection(self, path):
        return UnixDomainHTTP(path)

class ShimTransport(xmlrpclib.Transport):
    """
    Transport that simply unfreezes the data and passes it to the
    shimmed object.
    """
    def request(self, host, handler, request_body, verbose=0):
        params, method = xmlrpclib.loads(request_body)
        host._dispatch(method, (None, self, params))
        return (self._response,)

    def forkResponseFn(self, _forkFn, fn, *args, **kw):
        self._response = fn(*args, **kw)

    def callResponseFn(self, fn, *args, **kw):
        self._response = fn(*args, **kw)

    def sendResponse(self, response):
        self._response = response


class ServerProxy(xmlrpclib.ServerProxy):
    def __init__(self, uri, transport=None, encoding=None, verbose=0,
                 allow_none=0):
        if isinstance(uri, str):
            type, url = urllib.splittype(uri)
            # if we're using a protocol that xmlrpclib.ServerProxy supports,
            # simply fall back to it.
            if type in ('http', 'https'):
                xmlrpclib.ServerProxy.__init__(self, uri, transport, encoding,
                                               verbose, allow_none)
                return
            if type != 'unix':
                raise IOError, 'unsupported XML-RPC protocol'

            if transport is None:
                transport = UnixDomainTransport()
            # __host is the path to the unix domain socket
            # we were passed in unix:///var/lib/rmake/socket,
            # switch to /var/lib/rmake/socket.  This will make
            # the parts foo:bar@/var/lib/rmake
            self.__host = url[2:]
        elif isinstance(uri, tuple):
            self.__host, transport = uri
        elif transport is None:
            transport = ShimTransport()
            # __host is the server object
            self.__host = uri

        self.__handler = None
        self.__transport = transport
        self.__encoding = encoding
        self.__verbose = verbose
        self.__allow_none = allow_none

# server implementation

class UnixDomainHTTPRequestHandler(BaseHTTPServer.BaseHTTPRequestHandler):
    def address_string(self):
        return self.client_address

    def log_request(self, *args, **kw):
        if self.server.logRequests:
            BaseHTTPServer.BaseHTTPRequestHandler.log_request(self, *args, **kw)

class UnixDomainXMLRPCRequestHandler(UnixDomainHTTPRequestHandler,
                                 SimpleXMLRPCServer.SimpleXMLRPCRequestHandler):
    pass

class UnixDomainXMLRPCServer(SimpleXMLRPCServer.SimpleXMLRPCDispatcher,
                             SocketServer.UnixStreamServer):
    def __init__(self, path,
                 requestHandler=UnixDomainXMLRPCRequestHandler,
                 logRequests=1):
        self.logRequests = logRequests
        SimpleXMLRPCServer.SimpleXMLRPCDispatcher.__init__(self)
        umask = os.umask(0)
        SocketServer.UnixStreamServer.__init__(self, path, requestHandler)
        os.umask(umask)

    #def server_bind(self):
    #    SocketServer.UnixStreamServer.server_bind(self)
    #    os.chmod(self.server_address, 0777)


