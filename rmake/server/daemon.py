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

from conary.lib import options, util
from conary import command

from rmake import compat
from rmake import constants
from rmake import plugins
from rmake.lib import daemon
from rmake.multinode import admin
from rmake.server import repos
from rmake.server import servercfg
from rmake.server import server
# needed for deleting chroots upon "reset"
from rmake.worker.chroot import rootmanager


_commands = []
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
        reposPid = None
        proxyPid = None

        rMakeServer = None
        try:
            if not cfg.isExternalRepos():
                reposPid = repos.startRepository(cfg, fork=True, 
                                                 logger=self.logger)
            if cfg.proxyUrl and not cfg.isExternalProxy():
                proxyPid = repos.startProxy(cfg, fork=True,
                                            logger=self.logger)
            if cfg.getSocketPath():
                util.removeIfExists(cfg.getSocketPath())
            rMakeServer = server.rMakeServer(cfg.getServerUri(), cfg,
                                             repositoryPid=reposPid,
                                             proxyPid=proxyPid,
                                             pluginMgr=self.plugins)
            rMakeServer._installSignalHandlers()
            rMakeServer.serve_forever()
        finally:
            if rMakeServer:
                if rMakeServer.repositoryPid:
                    self.killRepos(reposPid)
                if rMakeServer.proxyPid:
                    self.killRepos(proxyPid, 'proxy')
            else:
                # rmake server failed to start
                if reposPid:
                    self.killRepos(reposPid)
                if proxyPid:
                    self.killRepos(proxyPid, 'proxy')


    def killRepos(self, pid, name='repository'):
        self.logger.info('killing %s at %s' % (name, pid))
        try:
            os.kill(pid, signal.SIGKILL)
        except Exception, e:
            self.logger.warning(
            'Could not kill %s at pid %s: %s' % (name, pid, e))

    def runCommand(self, *args, **kw):
        return daemon.Daemon.runCommand(self, *args, **kw)

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
