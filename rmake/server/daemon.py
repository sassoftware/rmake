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
rMake server daemon
"""
import os
import shutil
import signal
import sys
import traceback

from conary.lib import options, util
from conary import command

from rmake import compat
from rmake import constants
from rmake import plugins
from rmake.build import builder
from rmake.build import buildjob
from rmake.build import subscriber as build_subscriber
from rmake.db import database
from rmake.lib import daemon
from rmake.lib import server as server_mod
from rmake.lib import subscriber as subscriber_mod
from rmake.multinode import admin
from rmake.multinode.server import dispatcher
from rmake.multinode.server import messagebus
from rmake.multinode.server import subscriber as mn_subscriber
from rmake.server import log_server
from rmake.server import repos
from rmake.server import servercfg
from rmake.server import server
from rmake.server import wsgi_simple
# needed for deleting chroots upon "reset"
from rmake.worker.chroot import rootmanager


_commands = [daemon.ReloadCommand]
def register(cmd):
    _commands.append(cmd)


class ResetCommand(daemon.DaemonCommand):
    commands = ['reset']

    help = 'Remove all job data from rmake'

    def runCommand(self, daemon, cfg, argSet, args):
        for dir in (cfg.getReposDir(), cfg.getBuildLogDir(),
                    cfg.getDbContentsPath(), cfg.getProxyDir(),
                    cfg.getResolverCachePath()):
            if os.path.exists(dir):
                print "Deleting %s" % dir
                shutil.rmtree(dir)

        for dir in (cfg.getCacheDir(),):
            if os.path.exists(dir):
                print "Deleting subdirectories of %s" % dir
                for subDir in os.listdir(dir):
                    shutil.rmtree(dir + '/' + subDir)
        for path in (cfg.getDbPath()[1],):
            if os.path.exists(path):
                print "Deleting %s" % path
                os.remove(path)
        rootManager = rootmanager.ChrootManager(cfg)
        chroots = rootManager.listChroots()
        print "Deleting %s chroots" % len(chroots)
        for chroot in chroots:
            rootManager.deleteChroot(chroot)
register(ResetCommand)


class AdminCommand(daemon.DaemonCommand):

    def _getAdminClient(self, cfg):
        return admin.getAdminClient(cfg.getMessageBusHost(), cfg.messageBusPort)


class StatusCommand(AdminCommand):
    """
        Give status information about internal rMake pieces

        Example:
            status dispatcher - displays current state of dispatcher
            status node <nodeId> - displays current state of node
            status messagebus - displays current status of messagebus

        These commands are used mostly for debugging
    """
    commands = ['status']
    help = 'List various internal state for this rmake server'

    def runCommand(self, daemon, cfg, argSet, args):
        adminClient = self._getAdminClient(cfg)
        command, subCommand, extra = self.requireParameters(args, 'server',
                                                            allowExtra=True)
        if subCommand == 'messagebus':
            print "Connected clients: Messages Queued"
            queueLens = adminClient.listMessageBusQueueLengths()
            for sessionId in sorted(adminClient.listMessageBusClients()):
                print '%s: %s' % (sessionId, queueLens[sessionId])
        if subCommand == 'dispatcher':
            print "Nodes:"
            print '\n'.join(adminClient.listNodes())
            print "Queued commands:"
            print '\n'.join(adminClient.listQueuedCommands())
            print "Assigned commands:"
            for command, nodeId in adminClient.listAssignedCommands():
                print "%s: %s" % (command, nodeId)
        if subCommand == 'node':
            subCommand, nodeId = self.requireParameters(args[1:], 'nodeId')
            print "Node %s" % nodeId
            (queued, active) = adminClient.listNodeCommands(nodeId)
            if queued:
                print " Queued Commands: "
                for command in queued:
                    print "   %s" % command
            if active:
                print " Active Commands: "
                for command, pid in active:
                    print "   %s (pid %s)" % (command, pid)
            if not (queued or active):
                print " (No commands running)"
register(StatusCommand)


class SuspendCommand(AdminCommand):
    commands = ['suspend']
    help = "Suspend a node from receiving further jobs."

    _suspend = True

    def runCommand(self, daemon, cfg, argSet, args):
        if len(args) < 3:
            sys.exit("Expected one or more node session IDs")
        adminClient = self._getAdminClient(cfg)
        adminClient.suspendNodes(args[2:], suspend=self._suspend)
        action = self._suspend and 'Suspended' or 'Resumed'
        print "%s %d node(s)" % (action, len(args) - 2)
register(SuspendCommand)


class ResumeCommand(SuspendCommand):
    commands = ['resume']
    help = "Resume a node for receiving further jobs."
    _suspend = False
register(ResumeCommand)


class HelpCommand(daemon.DaemonCommand, command.HelpCommand):
    commands = ['help']

    def runCommand(self, daemon, cfg, argSet, args):
        command.HelpCommand.runCommand(self, cfg, argSet, args)
register(ResetCommand)


class rMakeDaemon(daemon.Daemon):
    name = 'rmake-server'
    commandName = 'rmake-server'
    version = constants.version
    configClass = servercfg.rMakeConfiguration
    loggerClass = server.ServerLogger
    user = constants.rmakeUser
    groups = [constants.chrootUser]
    capabilities = 'cap_sys_chroot+ep'
    commandList = list(daemon.Daemon.commandList) + _commands

    def getConfigFile(self, argv):
        p = plugins.getPluginManager(argv, servercfg.rMakeConfiguration)
        p.callServerHook('server_preInit', self, argv)
        self.plugins = p
        cfg = daemon.Daemon.getConfigFile(self, argv)
        cfg.sanityCheck()
        return cfg

    def doWork(self):
        cfg = self.cfg
        try:
            cfg.sanityCheckForStart()
        except Exception, e:
            self.logger.error(e)
            sys.exit(1)

        self.proc = RmakeServerProc(cfg, self.plugins, logger=self.logger)
        signal.signal(signal.SIGHUP, self._reload)
        signal.signal(signal.SIGUSR2, self._rotateLogs)
        self.proc.serve_forever()

    def runCommand(self, *args, **kw):
        return daemon.Daemon.runCommand(self, *args, **kw)

    def _reload(self, signum, sigtb):
        self.proc.reload()

    def _rotateLogs(self, signum, sigtb):
        self.proc.rotateLogs()

    @classmethod
    def reloadConfig(cls):
        # Have to rerun the entire command framework to parse config-related
        # cmdline options.
        cfg = []
        def runCommand(thisCommand, cfg_, *args, **kwargs):
            cfg[:] = [cfg_]
            return 0
        d = cls()
        d.runCommand = runCommand
        d.setSysExcepthook = False
        try:
            d.main(sys.argv)
        except SystemExit:
            pass
        assert cfg and cfg[0]
        return cfg[0]


class RmakeServerProc(server_mod.Server):

    def __init__(self, cfg, pluginMgr, logger):
        self.cfg = cfg
        self.buildPids = {}
        self.criticalPids = {}
        self.rpcPid = None
        self.db = None
        self.plugins = pluginMgr
        self.nodeClient = None
        self.eventHandler = EventHandler(self)
        self._subscribers = []
        self._jobsPending = False
        self._reloadPending = False
        server_mod.Server.__init__(self, logger=logger)

    def serve_forever(self):
        try:
            self._installSignalHandlers()
            self._startRepository()
            self._startProxy()
            self._startMessageBus()
            self._connectDatabase()
            self._connectBus()
            self._postStartupTasks()
            self._startRPC()
            self._startDispatcher()
            self._startLogServer()
            self.plugins.callServerHook('server_postInit', self)
        except Exception:
            self.exception("Fatal error during rMake startup:")
            try:
                self._killAllPids()
            finally:
                os._exit(70)
        server_mod.Server.serve_forever(self)
        self.plugins.callServerHook('server_shutDown', self)

    # Server/PID management

    def reload(self):
        self._reloadPending = True
        if self.rpcPid:
            os.kill(self.rpcPid, signal.SIGHUP)

    def rotateLogs(self):
        if self.rpcPid:
            os.kill(self.rpcPid, signal.SIGUSR1)

    def _close(self):
        if self.db:
            self.db.close()
        if self.nodeClient:
            self.nodeClient.postFork()
            self.nodeClient = None
        server_mod.Server._close(self)

    def _fork(self, name, close=False, criticalLogPath=None):
        pid = server_mod.Server._fork(self, name)
        if pid:
            if criticalLogPath:
                self.criticalPids[pid] = criticalLogPath
            return pid
        self._close()
        self._resetSignalHandlers()
        if self.db and not close:
            self.db.reopen()
        return pid

    def _pidDied(self, pid, status, name=None):
        name = self._getPidName(pid, name)
        criticalLogPath = self.criticalPids.pop(pid, None)
        if criticalLogPath and not self._halt:
            self.error("""
Internal %s died - shutting down rMake.
The %s can die on startup due to an earlier unclean shutdown of
rMake.  Check for orphaned processes running under the '%s' user,
and check the log file at %s for detailed diagnostics.
""" % (name, name, constants.rmakeUser, criticalLogPath))
            self._halt = True
        jobId = self.buildPids.pop(pid, None)
        if jobId and not self._halt:
            if status:
                msg = self._getExitMessage(pid, status, name)
                self.error("Builder for job %s died: %s", jobId, msg)
                job = self.db.getJob(jobId)
                if job.isBuilding():
                    self.subscribeToJob(job)
                    job.jobFailed(msg)
            else:
                # A job just finished so check if there is another in the queue
                # waiting for free slots.
                self.startJob()
        self.plugins.callServerHook('server_pidDied', self, pid, status)
        self._pids.pop(pid, None)

    # Startup

    def _startMessageBus(self):
        if self.cfg.messageBusHost is not None:
            return
        logPath = self.cfg.getMessageBusLogPath()
        messages = self.cfg.logDir + '/messages/messagebus.log'
        util.mkdirChain(os.path.dirname(messages))
        bus = messagebus.MessageBus('', self.cfg.messageBusPort, logPath,
                messages)
        pid = self._fork('messagebus', close=True, criticalLogPath=logPath)
        if pid:
            bus._close()
            return
        try:
            bus._installSignalHandlers()
            bus.serve_forever()
            os._exit(0)
        except SystemExit as err:
            os._exit(err.args[0])
        except Exception:
            bus.exception("Failed to start messagebus:")
        finally:
            os._exit(70)

    def _startRepository(self):
        if self.cfg.isExternalRepos():
            return
        pid = self._fork('repository', close=True,
                criticalLogPath=self.cfg.getReposLogPath())
        if pid:
            repos.pingServer(self.cfg)
            return
        try:
            repos.startRepository(self.cfg, fork=False, logger=self._logger)
            os._exit(0)
        except SystemExit as err:
            os._exit(err.args[0])
        except Exception:
            self.exception("Error starting repository:")
        finally:
            os._exit(70)

    def _startProxy(self):
        if self.cfg.isExternalProxy():
            return
        pid = self._fork('proxy', close=True,
                criticalLogPath=self.cfg.getProxyLogPath())
        if pid:
            repos.pingServer(self.cfg, proxyUrl=self.cfg.getProxyUrl())
            return
        try:
            repos.startProxy(self.cfg, fork=False, logger=self._logger)
            os._exit(0)
        except SystemExit as err:
            os._exit(err.args[0])
        except Exception:
            self.exception("Error starting proxy:")
        finally:
            self._exit(70)

    def _connectDatabase(self):
        self.db = database.Database(self.cfg.getDbPath(),
                self.cfg.getDbContentsPath(),
                memCache=self.cfg.memCache)
        self._subscribers.append(build_subscriber._JobDbLogger(self.db))

    def _connectBus(self):
        self.nodeClient = mn_subscriber.rMakeServerNodeClient(self.cfg, self)
        self.nodeClient.connect()
        self._subscribers.append(mn_subscriber._RmakeBusPublisher(self.nodeClient))

    def _startDispatcher(self):
        pid = self._fork('dispatcher', close=False,
                criticalLogPath=self.cfg.getDispatcherLogPath())
        if pid:
            return
        try:
            disp = dispatcher.DispatcherServer(self.cfg, self.db)
            disp._installSignalHandlers()
            disp.serve_forever()
            os._exit(0)
        except SystemExit as err:
            os._exit(err.args[0])
        except Exception:
            disp.exception("Failed to start dispatcher:")
        finally:
            os._exit(70)

    def _startRPC(self):
        if self.cfg.useGunicorn():
            try:
                from rmake.server import wsgi_gunicorn
            except ImportError:
                self.error("gunicorn must be installed if rpcWorkers is > 1")
                sys.exit(70)
        pid = self._fork('rpc', close=True,
                criticalLogPath=self.cfg.getServerLogPath())
        if pid:
            self.rpcPid = pid
            return
        try:
            if self.cfg.useGunicorn():
                configFunc = rMakeDaemon.reloadConfig
                wsgi = wsgi_gunicorn.GunicornServer(configFunc)
                wsgi.run()
            else:
                wsgi_simple.run_simple(self.cfg)
        except SystemExit as err:
            os._exit(err.args[0])
        except Exception:
            self.exception("Failed to start RPC server:")
        finally:
            os._exit(70)

    def _startLogServer(self):
        log_server.LogServer(self.cfg, self.db,
                map=self.nodeClient.getMap(),
                fork=lambda name: self._fork(name, close=True),
                logger=self._logger,
                )

    def _postStartupTasks(self):
        """Normalize the state of things on startup"""
        self.db.deactivateAllNodes()
        while True:
            job = self.db.popJobFromQueue()
            if job is None:
                break
            if job.isFailed():
                continue
            self.subscribeToJob(job)
            job.jobFailed('Server was stopped')
        for state in buildjob.ACTIVE_STATES:
            for job in self.db.getJobsByState(state):
                self.subscribeToJob(job)
                job.jobFailed('Server was stopped')

    # Main loop

    def _serveLoopHook(self):
        self._collectChildren()
        if self._reloadPending:
            self._reloadPending = False
            try:
                cfg = rMakeDaemon.reloadConfig()
                self.cfg.updateFromReloaded(cfg, log=self)
            except Exception:
                self.exception("Unable to reload configuration:")
        self.startJob()
        self.plugins.callServerHook('server_loop', self)
        self.db.commit()

    def handleRequestIfReady(self, sleepTime=0.1):
        if self._jobsPending:
            # If there may be more jobs in the queue, sleep a short time.
            timeout = 0.1
        else:
            # Otherwise when a new job is queued an event will arrive from the
            # nodeclient, so sleeping longer is okay.
            timeout = 10.0
        self.nodeClient.poll(timeout=timeout, maxIterations=1)

    # Job processing

    def subscribeToJob(self, job):
        """Take ownership of a job and forward changes to subscribers"""
        for sub in self._subscribers:
            sub.attach(job)
        job.own()

    def eventsReceived(self, jobId, eventList):
        self.eventHandler._receiveEvents(self.eventHandler.apiVersion,
                eventList)

    def startJob(self):
        """Pop one job from the queue and start it"""
        if not self.db.getEmptySlots():
            self._jobsPending = False
            return
        job = self.db.popJobFromQueue()
        if job is None:
            self._jobsPending = False
            return
        self._jobsPending = True
        if job.isFailed():
            return
        try:
            self._startBuild(job)
        except Exception:
            self.exception("Failed to start job %d:", job.jobId)
            self.subscribeToJob(job)
            job.exceptionOccurred('Failed while starting job',
                    traceback.format_exc())

    def getBuilder(self, job):
        """Create a Builder instance to build the given job"""
        return builder.Builder(self.cfg, job, db=self.db)

    def _startBuild(self, job):
        """Spawn a builder process to build the given job"""
        pid = self._fork('Job %s' % job.jobId)
        if pid:
            self.buildPids[pid] = job.jobId
            return
        try:
            buildMgr = self.getBuilder(job)
            for sub in self._subscribers:
                if hasattr(sub, 'attachToBuild'):
                    # This replaces the now-closed server nodeclient with the
                    # builder's nodeclient.
                    sub.attachToBuild(buildMgr)
                else:
                    sub.attach(job)
            job.own()
            buildMgr._installSignalHandlers()
            buildMgr.buildAndExit()
        except Exception, err:
            buildMgr.logger.exception("Build initialization failed:")
            job.exceptionOccurred(err, traceback.format_exc())
            os._exit(2)
        finally:
            os._exit(70)

    def stopJob(self, jobId):
        job = self.db.getJob(jobId)
        for pid, jobId in self.buildPids.items():
            if jobId == job.jobId:
                del self.buildPids[pid]
                self._killPid(pid, hook=self.handleRequestIfReady)
        if not job.isFinished() and not job.isCommitting():
            self.subscribeToJob(job)
            job.jobStopped("User requested stop")


class EventHandler(subscriber_mod.StatusSubscriber):
    listeners = {
            'JOB_STATE_UPDATED': 'jobStateUpdated',
            }

    def __init__(self, server):
        self.server = server
        subscriber_mod.StatusSubscriber.__init__(self, None, None)

    def jobStateUpdated(self, jobId, state, status):
        if state == buildjob.JOB_STATE_QUEUED:
            self.server.startJob()


def main(argv):
    d = rMakeDaemon()
    if '--debug-all' or '-d' in argv:
        sys.excepthook = util.genExcepthook(debug=True, debugCtrlC=True)
    try:
        compat.checkRequiredVersions()
        rc = d.mainWithExceptionHandling(argv)
        return rc
    except options.OptionError, err:
        d.usage()
        d.logger.error(err)
        return 1
