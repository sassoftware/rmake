#!/usr/bin/python
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
rMake Backend server
"""
import itertools
import xmlrpclib

from rmake import errors
from rmake.build import subscriber
from rmake.multinode.server import subscriber as mn_subscriber
from rmake.multinode.server import workerproxy
from rmake.server import auth
from rmake.db import database
from rmake.lib.apiutils import api, api_parameters, api_return, freeze, thaw
from rmake.lib.apiutils import allow_anonymous
from rmake.lib import apirpc
from rmake.lib import logger

# load our messages so that they are understood by the messagebus
import rmake.multinode.messages  # pyflakes=ignore


class ServerLogger(logger.ServerLogger):
    name = 'rmake-server'

class rMakeServer(apirpc.XMLApiServer):
    """
        rMake server.

        See rMake client for documentation of API.
    """

    @api(version=1)
    @api_parameters(1, 'BuildJob')
    @api_return(1, 'int')
    def buildTroves(self, callData, job):
        callData.logger.logRPCDetails('buildTroves')
        for buildCfg in job.iterConfigList():
            self.updateBuildConfig(buildCfg)
        job.uuid = job.getMainConfig().uuid
        authData = callData.getAuth()
        if authData:
            job.owner = authData.getUser()
        self.db.addJob(job)
        self._subscribeToJob(job)
        self.db.queueJob(job)
        queuedIds = self.db.listJobIdsOnQueue()
        job.jobQueued('Job Queued')
        job.disown()
        return job.jobId

    @api(version=1)
    @api_parameters(1, None)
    def stopJob(self, callData, jobId):
        callData.logger.logRPCDetails('stopJob', jobId=jobId)
        jobId = self.db.convertToJobId(jobId)
        job = self.db.getJob(jobId, withTroves=True)
        if job.isCommitting():
            return
        elif not job.isQueued() and not job.isRunning():
            raise errors.RmakeError('Cannot stop job %s - it is'
                                    ' already stopped' % job.jobId)
        self.nodeClient.stopJob(job.jobId)

    @api(version=1)
    @api_parameters(1, None, None)
    @api_return(1, None)
    def listJobs(self, callData, activeOnly, jobLimit):
        return self.db.listJobs(activeOnly=activeOnly, jobLimit=jobLimit)

    @api(version=1)
    @api_parameters(1, None, None)
    @api_return(1, None)
    def listTrovesByState(self, callData, jobId, state):
        jobId = self.db.convertToJobId(jobId)
        if state == '':
            state = None
        data = self.db.listTrovesByState(jobId, state)
        return [(x[0], freeze('troveContextTupleList', x[1])) for x in data.iteritems()]

    @api(version=1)
    @api_parameters(1, None, 'bool', 'bool')
    @api_return(1, None)
    def getJobs(self, callData, jobIds, withTroves=True, withConfigs=True):
        callData.logger.logRPCDetails('getJobs', jobIds=jobIds,
                                      withTroves=withTroves,
                                      withConfigs=withConfigs)
        jobIds = self.db.convertToJobIds(jobIds)
        return [ x.__freeze__(sanitize=True)
                 for x in self.db.getJobs(jobIds, withTroves=withTroves,
                                          withConfigs=withConfigs) ]

    @api(version=1)
    @api_parameters(1, None)
    @api_return(1, 'SanitizedBuildConfiguration')
    def getJobConfig(self, callData, jobId):
        jobId = self.db.convertToJobId(jobId)
        jobCfg = self.db.getJobConfig(jobId)
        return jobCfg

    @api(version=1)
    @api_parameters(1, None, None)
    @api_return(1, None)
    def getJobLogs(self, callData, jobId, mark):
        jobId = self.db.convertToJobId(jobId)
        if not self.db.jobExists(jobId):
            self.warning("%s tried to obtain logs for invlid JobId %s" % (
                        str(callData.auth), jobId))
            return []
        return [ tuple(str(x) for x in data) 
                    for data in self.db.getJobLogs(jobId, mark) ]

    @api(version=1)
    @api_parameters(1, None, 'troveContextTuple', 'int')
    @api_return(1, None)
    def getTroveLogs(self, callData, jobId, troveTuple, mark):
        jobId = self.db.convertToJobId(jobId)
        return [ tuple(str(x) for x in data) for data in self.db.getTroveLogs(jobId, troveTuple, mark) ]

    @api(version=1)
    @api_parameters(1, None, 'troveContextTuple', 'int')
    @api_return(1, None)
    def getTroveBuildLog(self, callData, jobId, troveTuple, mark):
        jobId = self.db.convertToJobId(jobId)
        trove = self.db.getTrove(jobId, *troveTuple)
        if not self.db.hasTroveBuildLog(trove):
            return not trove.isFinished(), xmlrpclib.Binary(''), 0
        f = self.db.openTroveBuildLog(trove)
        if mark < 0:
            f.seek(0, 2)
            end = f.tell()
            f.seek(max(end + mark, 0))
        else:
            f.seek(mark)
        return not trove.isFinished(), xmlrpclib.Binary(f.read()), f.tell()

    @api(version=1)
    @api_parameters(1, None)
    @api_return(1, None)
    def deleteJobs(self, callData, jobIdList):
        jobIdList = self.db.convertToJobIds(jobIdList)
        jobs = self.db.getJobs(jobIdList, withTroves=False)
        for job in jobs:
            if job.isBuilding():
                raise errors.RmakeError('cannot delete active job %s' % job.jobId)
        deletedJobIds = self.db.deleteJobs(jobIdList)
        return deletedJobIds

    @api(version=1)
    @api_parameters(1)
    @api_return(1, None)
    def listChroots(self, callData):
        chroots = self.db.listChroots()
        chrootNames = self.worker.listChrootsWithHost()
        finalChroots = []
        for chroot in chroots:
            if (chroot.host, chroot.path) not in chrootNames:
                # this has been removed from the file system
                self.db.removeChroot(chroot.host, chroot.path)
            else:
                finalChroots.append(chroot)
        return [ freeze('Chroot', x) for x in finalChroots ]

    @api(version=1)
    @api_parameters(1, None, 'troveContextTuple', 'str', 'bool', 'str', 'str')
    @api_return(1, None)
    def startChrootServer(self, callData, jobId, troveTuple, command,
                          superUser, chrootHost, chrootPath):
        jobId = self.db.convertToJobId(jobId)
        trove = self.db.getTrove(jobId, *troveTuple)
        if not chrootHost:
            if not trove.getChrootPath():
                raise errors.RmakeError('Chroot does not exist')
            chrootHost = trove.getChrootHost()
            chrootPath = trove.getChrootPath()
        success, data =  self.worker.startSession(chrootHost,
                                                  chrootPath,
                                                  command,
                                                  superUser=superUser,
                                                  buildTrove=trove)
        if not success:
            raise errors.RmakeError('Chroot failed: %s' % data)
        return data


    @api(version=1)
    @api_parameters(1, 'str', 'str', 'str')
    @api_return(1, None)
    def archiveChroot(self, callData, host, chrootPath, newPath):
        if self.db.chrootIsActive(host, chrootPath):
            raise errors.RmakeError('Chroot is in use!')
        newPath = self.worker.archiveChroot(host, chrootPath, newPath)
        self.db.moveChroot(host, chrootPath, newPath)

    @api(version=1)
    @api_parameters(1, 'str', 'str')
    @api_return(1, None)
    def deleteChroot(self, callData, host, chrootPath):
        if self.db.chrootIsActive(host, chrootPath):
            raise errors.RmakeError('Chroot is in use!')
        self.worker.deleteChroot(host, chrootPath)
        self.db.removeChroot(host, chrootPath)

    @api(version=1)
    @api_parameters(1)
    @api_return(1, None)
    def deleteAllChroots(self, callData):
        chroots = self.db.listChroots()
        for chroot in chroots:
            if chroot.active:
                continue
            self.worker.deleteChroot(chroot.host, chroot.path)
            self.db.removeChroot(chroot.host, chroot.path)

    @api(version=1)
    @api_parameters(1, None)
    def startCommit(self, callData, jobIds):
        jobIds = self.db.convertToJobIds(jobIds)
        jobs = self.db.getJobs(jobIds)
        for job in jobs:
            self._subscribeToJob(job)
            job.jobCommitting()

    @api(version=1)
    @api_parameters(1, None, 'str')
    def commitFailed(self, callData, jobIds, message):
        jobIds = self.db.convertToJobIds(jobIds)
        jobs = self.db.getJobs(jobIds)
        for job in jobs:
            self._subscribeToJob(job)
            job.jobCommitFailed(message)

    @api(version=1)
    @api_parameters(1, None, None)
    def commitSucceeded(self, callData, jobIds, commitMap):
        jobIds = self.db.convertToJobIds(jobIds)
        # split commitMap and recombine
        finalMap = []
        for jobId, troveMap in itertools.izip(jobIds, commitMap):
            troveMap = dict((thaw('troveContextTuple', x[0]),
                            thaw('troveTupleList', x[1])) for x in troveMap)
            finalMap.append((jobId, troveMap))
        jobs = self.db.getJobs(jobIds, withTroves=True)
        for (jobId, troveMap), job in itertools.izip(finalMap, jobs):
            self._subscribeToJob(job)
            job.jobCommitted(troveMap)

    @api(version=1)
    @api_parameters(1)
    @api_return(1, None)
    def getRepositoryInfo(self, callData):
        proxyUrl = self.cfg.getProxyUrl()
        if not proxyUrl:
            proxyUrl = ''
        return (self.cfg.reposName, self.cfg.getRepositoryMap(),
                list(self.cfg.reposUser), proxyUrl)

    # --- these methods used to be part of the multinode extension

    @api(version=1)
    @api_parameters(1)
    @api_return(1, None)
    def listNodes(self, callData):
        return [freeze('Node', x) for x in self.db.listNodes()]

    @api(version=1)
    @api_parameters(1)
    @api_return(1, None)
    @allow_anonymous
    def getMessageBusInfo(self, callData):
        host = self.cfg.getMessageBusHost(qualified=True)
        return dict(host=host, port=self.cfg.messageBusPort)

    # --- internal functions

    #def getBuilder(self, job):
    #    b = builder.Builder(self.cfg, job, db=self.db)
    #    return b

    def updateBuildConfig(self, buildConfig):
        buildConfig.repositoryMap.update(self.cfg.getRepositoryMap())
        for serverName, user, password in self.cfg.getUserGlobs():
            buildConfig.user.addServerGlob(serverName, user, password)
        proxyUrl = self.cfg.getProxyUrl()
        if proxyUrl:
            if hasattr(buildConfig,'proxyMap'):
                buildConfig.proxyMap.clear()
                buildConfig.proxyMap.addStrategy('*', [proxyUrl],
                        replaceScheme='conary')
            else:
                buildConfig.conaryProxy['http'] = proxyUrl
                buildConfig.conaryProxy['https'] = proxyUrl

    def _authCheck(self, callData, fn, *args, **kw):
        if getattr(fn, 'allowAnonymousAccess', None) or callData.auth is None:
            return True
        if (callData.auth.getSocketUser()
          or callData.auth.getCertificateUser()):
            return True
        user, password = (callData.auth.getUser(), callData.auth.getPassword())
        #if (user, password) == self.internalAuth:
        #    return True
        self.auth.authCheck(user, password, callData.auth.getIP())
        return True

    def _subscribeToJob(self, job):
        """Take ownership of a job and forward changes to subscribers"""
        for sub in self._subscribers:
            sub.attach(job)
        job.own()

    #def _setUpInternalUser(self):
    #    user = ''.join([chr(random.randint(ord('a'),
    #                       ord('z'))) for x in range(10)])
    #    password = ''.join([chr(random.randint(ord('a'), 
    #                            ord('z'))) for x in range(10)])
    #    if isinstance(self.uri, str):
    #        schema, url = urllib.splittype(self.uri)
    #        if schema in ('http', 'https'):
    #            host, rest = urllib.splithost(url)
    #            olduser, host = urllib.splituser(host)
    #            uri = '%s://%s:%s@%s%s' % (schema, user, password, host, rest)
    #            self.uri = uri

    #    self.internalAuth = (user, password)

    def __init__(self, cfg, serverLogger):
        self.nodeClient = None
        self.cfg = cfg
        apirpc.XMLApiServer.__init__(self, uri=None, logger=serverLogger)

        self.db = database.Database(cfg.getDbPath(), cfg.getDbContentsPath())
        self.auth = auth.AuthenticationManager(cfg.getAuthUrl(), self.db)
        self.nodeClient = mn_subscriber.RPCNodeClient(self.cfg, self)

        subscriberLog = logger.Logger('susbscriber',
                self.cfg.getSubscriberLogPath())
        self.worker = workerproxy.WorkerProxy(self.cfg, self.nodeClient,
                self._logger)
        dbLogger = subscriber._JobDbLogger(self.db)
        nodesub = mn_subscriber._RmakeBusPublisher(self.nodeClient)
        # note - it's important that the db logger
        # comes first, before the general publisher,
        # so that whatever published is actually 
        # recorded in the DB.
        self._subscribers = [dbLogger, nodesub]
