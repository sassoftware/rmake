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


from rmake.worker.chroot import rootmanager


class WorkerProxy(object):
    """
        Used by build manager to speak w/ dispatcher + receive updates on 
        troves.
    """
    def __init__(self, cfg, client, logger):
        self.cfg = cfg
        self.client = client
        self.logger = logger
        self.chrootManager = rootmanager.ChrootManager(self.cfg, self.logger)

    def getAdminClient(self):
        from rmake.multinode import admin
        return admin.getAdminClient(self.cfg.getMessageBusHost(),
                self.cfg.messageBusPort)

    def deleteChroot(self, host, chrootPath):
        self.getAdminClient().deleteChroot(host, chrootPath)

    def archiveChroot(self, host, chrootPath, newPath):
        return self.getAdminClient().archiveChroot(host, chrootPath, newPath)

    def listChrootsWithHost(self):
        adminClient = self.getAdminClient()
        nodeIds = adminClient.listNodes()
        localRoots = [('_local_', x) for x in self.chrootManager.listChroots()]
        chroots = []
        nodeNames = adminClient.getDispatcher().getNamesByIds(nodeIds)
        for nodeId in nodeIds:
            nodeClient = adminClient.getNode(nodeId)
            if nodeId not in nodeNames:
                continue
            nodeName = nodeNames[nodeId]
            chroots.extend((nodeName, x) for x in nodeClient.listChroots())
        return chroots + localRoots

    def startSession(self, host, chrootPath, command, superUser=False,
                     buildTrove=None):
        hostname, port = self.getAdminClient().startChrootSession(
                                                host, chrootPath, command,
                                                superUser, buildTrove)
        return True, (hostname, port)


    def buildTrove(self, buildCfg, jobId, buildTrove, eventHandler, 
                   buildReqs, targetLabel):
        buildTrove.disown()
        self.client.buildTrove(buildCfg, jobId, buildTrove,
                               buildReqs, targetLabel)

    def commandErrored(self, commandInfo, failureReason):
        buildTrove = commandInfo.getTrove()
        buildTrove.own()
        buildTrove.troveFailed(failureReason)

    def commandCompleted(self, commandInfo):
        # we'll wait for the "Trove built" message.
        pass

    def stopAllCommands(self):
        self.client.stopAllCommands()

    def hasActiveTroves(self):
        return bool(self.client._commands)

    def _checkForResults(self):
        if self.eventHandler.hadEvent():
            self.eventHandler.reset()
            return True
        return False

    def handleRequestIfReady(self):
        self.client.poll()
