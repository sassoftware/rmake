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


from rmake.build.subscriber import _RmakePublisherProxy


from rmake.multinode import messages
from rmake.multinode import nodetypes
from rmake.multinode import nodeclient


class _ServerNodeClient(nodeclient.NodeClient):
    name = 'rmake-server'

    def __init__(self, cfg, server):
        node = nodetypes.Server()
        nodeclient.NodeClient.__init__(self, cfg.getMessageBusHost(),
                cfg.messageBusPort, cfg, server, node)

    def emitEvents(self, jobId, eventList):
        self.bus.sendSynchronousMessage('/event',
                messages.EventList(jobId, eventList))


class RPCNodeClient(_ServerNodeClient):
    """Node client for RPC workers"""
    sessionClass = 'RPC'

    def stopJob(self, jobId):
        self.bus.sendSynchronousMessage('/stopJob',
                messages.StopJobRequest(jobId))

    def disconnect(self):
        if self.bus.isConnected():
            self.bus.disconnect()


class rMakeServerNodeClient(_ServerNodeClient):
    """Node client for main server process"""
    sessionClass = 'SRV'
    subscriptions = [
            '/event',
            '/stopJob',
            ]

    def messageReceived(self, m):
        _ServerNodeClient.messageReceived(self, m)
        if isinstance(m, messages.EventList):
            self.server.eventsReceived(*m.getEventList())
        if isinstance(m, messages.StopJobRequest):
            self.server.stopJob(m.getJobId())


class _RmakeBusPublisher(_RmakePublisherProxy):
    """
        Class that transmits events from internal build process -> rMake server.
    """

    # we override the _receiveEvents method to just pass these
    # events on, thus we just use listeners as a list of states we subscribe to
    listeners = set([
        'JOB_STATE_UPDATED',
        'JOB_LOG_UPDATED',
        'JOB_TROVES_SET',
        'JOB_COMMITTED',
        'JOB_LOADED',
        'JOB_FAILED',
        'TROVE_BUILDING',
        'TROVE_BUILT',
        'TROVE_FAILED',
        'TROVE_STATE_UPDATED',
        'TROVE_LOG_UPDATED',
        'TROVE_PREPARING_CHROOT',
        ])

    def __init__(self, client):
        self.client = client
        _RmakePublisherProxy.__init__(self)

    def attachToBuild(self, build):
        self.client = build.getWorker().client
        self.attach(build.getJob())

    def _freezeTroveEvent(self, event, buildTrove, *args, **kw):
        if buildTrove.amOwner():
             _RmakePublisherProxy._freezeTroveEvent(self, event, buildTrove,
                                                    *args, **kw)

    def _freezeJobEvent(self, event, job, *args, **kw):
        if job.amOwner():
             _RmakePublisherProxy._freezeJobEvent(self, event, job, *args, **kw)

    def _emitEvents(self, jobId, eventList):
        self.client.emitEvents(jobId, eventList)
