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
Local configuration for rMake.

The information held in this configuration object should be all the required 
local setup needed to use rMake.
"""
import os
import pwd
import socket
import sys
import subprocess
import urllib
import urllib2
from StringIO import StringIO

from conary import dbstore
from conary.lib import log, cfg, util
from conary.lib.cfgtypes import CfgPath, CfgString, CfgInt, CfgLineList
from conary.lib.cfgtypes import CfgBool, CfgPathList, CfgDict, CfgList, ParseError
from conary.conarycfg import CfgUserInfo

from rmake import constants
from rmake import errors
from rmake.lib import chrootcache
from rmake.lib import daemon
from rmake.lib import procutil


class CfgChrootCache(cfg.CfgType):
    def parseString(self, str):
        s = str.split()
        if len(s) < 2 or len(s) > 3:
            raise ParseError("chroot cache type and path expected")
        return tuple(s)

    def format(self, val, displayOptions = None):
        return ' '.join(str(x) for x in val)


class CfgPortRange(cfg.CfgType):

    def parseString(self, val):
        parts = val.replace('-', ' ').split()
        if len(parts) == 1:
            raise ParseError("Expected two port numbers for range")
        start, end = parts
        try:
            start = int(start)
            end = int(end)
        except ValueError:
            raise ParseError("Port is not a number")
        if not 1024 < start < 65535:
            raise ParseError("Starting port is out of range 1024-65535")
        if not 1024 < end < 65535:
            raise ParseError("Ending port is out of range 1024-65535")
        if end < start:
            start, end = end, start
        return (start, end)

    def format(self, val, displayOptions=None):
        return "%s %s" % val


class rMakeBuilderConfiguration(daemon.DaemonConfig):
    buildDir          = (CfgPath, '/var/rmake')
    helperDir         = (CfgPath, "/usr/libexec/rmake")
    slots             = (CfgInt, 1)
    useCache          = (CfgBool, False)
    useTmpfs          = (CfgBool, False)
    pluginDirs        = (CfgPathList, ['/usr/share/rmake/plugins'])
    usePlugins        = (CfgBool, True)
    usePlugin         = CfgDict(CfgBool)
    chrootLimit       = (CfgInt, 4)
    chrootCache       = CfgChrootCache
    chrootCaps        = (CfgBool, False,
            "Set capability masks as directed by chroot contents. "
            "This has the potential to be unsafe.")
    chrootServerPorts = (CfgPortRange, (63000, 64000),
            "Port range to be used for 'rmake chroot' sessions.")
    chrootExtraMounts = CfgList(CfgString)
    hostName          = (CfgString, 'localhost')
    verbose           = False
    chrootUser        = (CfgString, constants.chrootUser)

    def getCommandSocketDir(self):
        return self.buildDir + '/tmp/'

    def getName(self):
        return '_local_'

    def getCacheDir(self):
        return self.buildDir + '/cscache'

    def getChrootDir(self):
        return self.buildDir + '/chroots'

    def getChrootArchiveDir(self):
        return self.buildDir + '/archive'

    def getBuildLogDir(self, jobId=None):
        if jobId:
            return self.logDir + '/buildlogs/%d/' % jobId
        return self.logDir + '/buildlogs/'

    def getBuildLogPath(self, jobId):
        return self.logDir + '/buildlogs/%d.log' % jobId

    def getChrootHelper(self):
        return self.helperDir + '/chroothelper'

    def getChrootCache(self):
        if not self.chrootCache:
            return None
        cls = chrootcache.CACHE_TYPES.get(self.chrootCache[0])
        if not cls:
            raise errors.RmakeError("Unknown chroot cache type of '%s' "
                    "specified. Valid types are: " % (self.chrootCache[0],)
                    + " ".join(chrootcache.CACHE_TYPES))
        cacheDir = self.chrootCache[1]
        if len(self.chrootCache) > 2:
            sizeLimit = self.chrootCache[2]
        else:
            sizeLimit = None
        return cls(cacheDir, sizeLimit, self.getChrootHelper())

    def _getChrootCacheDir(self):
        if not self.chrootCache:
            return None
        return self.chrootCache[1]

    def _checkDir(self, name, path, requiredOwner=None,
                   requiredMode=None):
        if not os.path.exists(path):
            raise errors.RmakeError('%s does not exist, expected at %s - cannot start server' % (name, path))
            sys.exit(1)
        if not (requiredOwner or requiredMode):
            return
        statInfo = os.stat(path)
        if requiredMode and statInfo.st_mode & 0777 != requiredMode:
            raise errors.RmakeError('%s (%s) must have mode %o' % (path, name, requiredMode))
        if requiredOwner:
            ownerName = pwd.getpwuid(statInfo.st_uid).pw_name
            if ownerName != requiredOwner:
                raise errors.RmakeError('%s (%s) must have owner %s' % (
                                            path, name, requiredOwner))

    def getMessageBusHost(self, qualified=False):
        host = self.messageBusHost
        if host in (None, 'LOCAL'):
            if qualified:
                return procutil.getNetName()
            else:
                return 'localhost'
        else:
            return host

    def checkBuildSanity(self):
        rmakeUser = constants.rmakeUser
        if pwd.getpwuid(os.getuid()).pw_name == rmakeUser:
            self._checkDir('buildDir', self.buildDir)
            self._checkDir('chroot dir (subdirectory of buildDir)',
                            self.getChrootDir(),
                            rmakeUser, 0700)
            self._checkDir('chroot archive dir (subdirectory of buildDir)',
                            self.getChrootArchiveDir(),
                            rmakeUser, 0700)
            chrootCacheDir = self._getChrootCacheDir()
            if chrootCacheDir:
                self._checkDir('chroot cache dir (subdirectory of buildDir)',
                               chrootCacheDir, rmakeUser, 0700)

class rMakeConfiguration(rMakeBuilderConfiguration):
    logDir            = (CfgPath, '/var/log/rmake')
    lockDir           = (CfgPath, '/var/run/rmake')
    serverDir         = (CfgPath, '/srv/rmake')
    proxyUrl          = (CfgString, 'http://LOCAL:7778') # local here means
                                                         # managed by rMake
    reposUrl          = (CfgString, 'http://LOCAL:7777')
    reposName         = socket.gethostname()
    sslCertPath       = (CfgPath, '/srv/rmake/certs/rmake-server-cert.pem')
    reposUser         = CfgUserInfo
    useResolverCache  = (CfgBool, True)
    dbPath            = dbstore.CfgDriver
    rmakeUrl        = (CfgLineList(CfgString), [])
    rbuilderUrl     = (CfgString, None)
    rpcWorkers      = (CfgInt, 1)
    # if None, start one locally
    # if "LOCAL", don't start one but still use localhost
    messageBusHost  = (CfgString, None)
    messageBusPort  = (CfgInt, 50900)
    logServerPort   = (CfgInt, 50901)
    memCache        = CfgString
    # DEPRECATED
    caCertPath        = None

    _default_unix_socket = 'unix:///var/lib/rmake/socket'
    _default_https_socket = 'https://localhost:9999'

    _cfg_aliases = [
            ('proxy',       'proxyUrl'),
            ('serverUrl',   'reposUrl'),
            ('serverName',  'reposName'),
            ('user',        'reposUser'),
            ]

    _reloadable = [
            'reposName',
            'reposUrl',
            'reposUser',
            'rmakeUrl',
            'rpcWorkers',
            'sslCertPath',
            ]

    def __init__(self, readConfigFiles = False, ignoreErrors=False):
        daemon.DaemonConfig.__init__(self)
        self.setIgnoreErrors(ignoreErrors)
        if hasattr(self, 'addAlias'):
            # Conary < 2.5
            for old, new in self._cfg_aliases:
                self.addAlias(old, new)
        if readConfigFiles:
            self.readFiles()

    def setServerName(self, serverName):
        for x in list(self.reposUser):
            if x[0] == self.reposName:
                self.reposUser.remove(x)
        if not self.reposUser.find(serverName):
            self.reposUser.addServerGlob(serverName, 'rmake', 'rmake')
        self.reposName = serverName

    def readFiles(self):
        for path in ['/etc/rmake/serverrc', 'serverrc']:
            self.read(path, False)

    def getAuthUrl(self):
        if self.rbuilderUrl:
            return self.translateUrl(self.rbuilderUrl)
        else:
            return None

    def getServerUris(self):
        if self.rmakeUrl:
            return self.rmakeUrl
        uris = [self._default_unix_socket]
        # Only enable remote access by default if auth is configured
        if self.getAuthUrl():
            uris.append(self._default_https_socket)
        return uris

    def useGunicorn(self):
        if self.rpcWorkers > 1:
            return True
        if any(x.startswith('http') for x in self.getServerUris()):
            return True
        if len(self.getServerUris()) > 1:
            return True
        return False

    def getDbPath(self):
        if not self.dbPath:
            return ('sqlite', self.serverDir + '/jobs.db')
        else:
            return self.dbPath

    def getDbContentsPath(self):
        return self.serverDir + '/jobcontents'

    def getServerLogPath(self):
        return self.logDir + '/rmake-server.log'

    def getXMLRPCLogPath(self):
        return self.logDir + '/xmlrpc.log'

    def getContentsPath(self):
        return self.serverDir + '/repos/contents'

    def getProxyDir(self):
        return self.serverDir + '/proxy'

    def getProxyContentsPath(self):
        return self.getProxyDir() + '/contents'

    def getProxyChangesetPath(self):
        return self.getProxyDir() + '/changesets'

    def getProxyPath(self):
        return self.getProxyDir() + '/sqldb'

    def getProxyConfigPath(self):
        return self.getProxyDir() + '/serverrc'

    def getProxyLogPath(self):
        return self.logDir + '/proxy.log'

    def getReposDir(self):
        return self.serverDir + '/repos'

    def getReposDbPath(self):
        return self.serverDir + '/repos/sqldb'

    def getReposConfigPath(self):
        return self.serverDir + '/repos/serverrc'

    def getReposCachePath(self):
        return self.serverDir + '/repos/cachedb'

    def getReposLogPath(self):
        return self.logDir + '/repos.log'

    def getSubscriberLogPath(self):
        return self.logDir + '/subscriber.log'

    def getMessageBusLogPath(self):
        return self.logDir + '/messagebus.log'

    def getDispatcherLogPath(self):
        return self.logDir + '/dispatcher.log'

    def getResolverCachePath(self):
        return self.serverDir + '/resolvercache'

    def getRepositoryMap(self):
        url = self.translateUrl(self.reposUrl)
        return { self.reposName : url }

    def getRepositoryUrl(self):
        return self.translateUrl(self.reposUrl)

    def translateUrl(self, url):
        type, host = urllib.splittype(url)
        host, rest = urllib.splithost(host)
        host, port = urllib.splitport(host)
        if host in ('LOCAL', 'localhost', ''):
            host = self.hostName
            if port:
                host = '%s:%s' % (host, port)
            return '%s://%s%s' % (type, host, rest)
        else:
            return url

    def getUrlInfo(self, url):
        host = urllib.splithost(urllib.splittype(url)[1])[0]
        host, port = urllib.splitport(host)
        if port:
            port = int(port)
        return host, port

    def getProxyInfo(self):
        if not self.proxyUrl:
            return None
        return self.getUrlInfo(self.proxyUrl)

    def getReposInfo(self):
        if not self.reposUrl:
            return None
        return self.getUrlInfo(self.reposUrl)

    def isExternalProxy(self):
        return self.proxyUrl and self.getProxyInfo()[0] != 'LOCAL'

    def isExternalRepos(self):
        return self.getReposInfo()[0] != 'LOCAL'

    def getProxyUrl(self):
        if not self.proxyUrl:
            return None
        # need to have the proxy url be a fqdn so that it can
        # be used by rmake nodes
        return self.translateUrl(self.proxyUrl)

    def getUserGlobs(self):
        return self.reposUser

    def getSslCertificatePath(self):
        return self.sslCertPath

    def getSslCertificateGenerator(self):
        return self.helperDir + '/gen-cert.sh'

    def sanityCheck(self):
        pass

    def checkBuildSanity(self):
        #cancel out build sanity check - this is not a build node.
        return True

    def sanityCheckForStart(self):
        if self.proxyUrl is None and self.rbuilderUrl:
            self.proxyUrl = self.rbuilderUrl
        if self.hostName == 'localhost':
            self.hostName = procutil.getNetName()
        currUser = pwd.getpwuid(os.getuid()).pw_name
        cfgPaths = ['logDir', 'lockDir', 'serverDir']
        for uri in self.getServerUris():
            if not uri.startswith('unix://'):
                continue
            socketPath = uri[7:]
            if not os.access(os.path.dirname(socketPath), os.W_OK):
                log.error('cannot write to socketPath directory at %s - cannot start server' % os.path.dirname(socketPath))
                sys.exit(1)

        ret = self._sanityCheckForSSL()
        if ret:
            sys.exit(ret)

        cfgPaths = ['buildDir', 'logDir', 'lockDir', 'serverDir']
        for path in cfgPaths:
            if not os.path.exists(self[path]):
                log.error('%s does not exist, expected at %s - cannot start server' % (path, self[path]))
                sys.exit(1)
            if not os.access(self[path], os.W_OK):
                log.error('user "%s" cannot write to %s at %s - cannot start server' % (currUser, path, self[path]))
                sys.exit(1)
        if self.useResolverCache:
            util.mkdirChain(self.getResolverCachePath())
        if self.rbuilderUrl:
            try:
                try:
                    urllib2.urlopen(self.rbuilderUrl).read(1024)
                except urllib2.HTTPError, err:
                    if 200 <= err.code < 400:
                        # Something benign like a redirect
                        pass
                    else:
                        raise
            except Exception, err:
                raise errors.RmakeError('Could not access rbuilder at %s.  '
                        'Please ensure you have a line "rbuilderUrl '
                        'https://<yourRbuilder>" set correctly in your serverrc '
                        'file.  Error: %s' % (self.rbuilderUrl, err))
        elif any(x.startswith('http') for x in self.getServerUris()):
            log.warning("HTTP(S) is enabled but rbuilderUrl is not set. "
                "Incoming HTTP requests will not be authenticated.")

    def reposRequiresSsl(self):
        return urllib.splittype(self.reposUrl)[0] == 'https'

    def proxyRequiresSsl(self):
        return (self.proxyUrl
                and urllib.splittype(self.proxyUrl)[0] == 'https')

    def requiresSsl(self):
        """
            Return True if any service run by rMake requires ssl certificates
        """
        if not self.isExternalRepos() and self.reposRequiresSsl():
            return True
        if not self.isExternalProxy() and self.proxyRequiresSsl():
            return True
        for uri in self.getServerUris():
            if uri.startswith('https://'):
                return True
        return False

    def _sanityCheckForSSL(self):
        """Check SSL settings, create SSL certificate if missing.
        Returns 0 if everything is OK, or an exit code otherwise"""
        if not self.requiresSsl():
            return 0

        if not self.sslCertPath:
            log.error("sslCertPath to be set - cannot start server")
            return 1
        try:
            util.mkdirChain(os.path.dirname(self.sslCertPath))
        except OSError, err:
            log.error("Could not access sslCert dir %s: %s" % os.path.dirname(self.sslCertPath), err)

        if self.caCertPath:
            log.warning("The caCertPath option is deprecated")
        return self.makeCertificate()

    def makeCertificate(self):
        certfiles = set([self.getSslCertificatePath()])
        missing = [ x for x in certfiles if not os.access(x, os.R_OK) ]
        if not missing:
            return 0

        # At least one of the certificates doesn't exist, let's recreate them
        # both
        if not self.getSslCertificateGenerator():
            log.error("sslGenCertPath is not set - "
                      "cannot start server")
            return 1
        genCertPath = self.getSslCertificateGenerator()
        if not os.access(genCertPath, os.X_OK):
            log.error("Unable to run %s to generate SSL certificate - "
                      "cannot start server" % genCertPath)
            return 1

        cmd = [ genCertPath ]
        certfname = certfiles.pop()
        util.mkdirChain(os.path.dirname(certfname))
        certf = open(certfname, "w+")
        p = subprocess.Popen(cmd, stdout=certf)
        p.communicate()
        if p.returncode:
            log.error("Error executing %s - cannot start server" % genCertPath)
            return p.returncode
        # Sanity check
        certf.seek(0)
        data = certf.read()
        certf.close()
        if not data:
            log.error("Invalid certificate produced - cannot start server")
            return 1
        if certfiles:
            certfname = certfiles.pop()
            open(certfname, "w+").write(data)
        return 0

    def updateFromReloaded(self, newCfg, log):
        """Copy updateable options from a newly reloaded config"""
        newCfg.sanityCheck()
        newCfg.sanityCheckForStart()
        for option in self.keys():
            if self[option] == newCfg[option]:
                continue
            if option not in self._reloadable:
                if log:
                    log.warning("Change of option %s requires a restart", option)
                continue
            self[option] = newCfg[option]
            sio = StringIO()
            self.displayKey(option, sio)
            if log:
                log.info("Configuration changed: %s", sio.getvalue().rstrip())
