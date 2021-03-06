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


from rmake import constants


class Subscriber(object):

    listeners = {}

    def __init__(self):
        self.events = {}

    def _receiveEvents(self, apiVersion, eventList):
        for event, data in eventList:
            if event[0] not in self.listeners:
                continue
            getattr(self, self.listeners[event[0]])(*data)

    def watchEvent(self, state, substates=set()):
        self.events.setdefault(state, set()).update(substates)

class _AbstractStatusSubscriber(Subscriber):

    fields = {}

    def __init__(self, subscriberId, uri):
        Subscriber.__init__(self)
        self.subscriberId = subscriberId
        self.uri = uri
        self.apiVersion = constants.subscriberApiVersion
        self._state = {}
        for field, default in self.fields.iteritems():
            self[field] = default

    def __getitem__(self, key):
        return self._state[key]

    def __setitem__(self, key, val):
        self._state[key] = val

    def iteritems(self):
        return self._state.iteritems()

    def iterEvents(self):
        if not self.events:
            return ((x, []) for x in self.listeners)
        return self.events.iteritems()

    def matches(self, event, subState=None):
        if event in self.events:
            subEvent = self.events[event]
            if not subState or not subEvent or (subState in subEvent):
                return True
        return False


class StatusSubscriber(_AbstractStatusSubscriber):

    def parse(self, field, data):
        if field not in self.fields:
            getattr(self, 'parse_' + field)(data)
        else:
            self[field] = data

    def parse_apiVersion(self, data):
        self.apiVersion = data

    def parse_event(self, data):
        event = data.split(None)
        for event in data.split():
            fields = event.split('+', 1)
            if len(fields) == 1:
                self.watchEvent(event)
            else:
                self.watchEvent(fields[0], fields[1].split(','))

    def __deepcopy__(self, memo):
        s = self.__class__(self.subscriberId, self.uri)
        [ s.parse(*x.split(None, 1)) for x in self.freezeData()[1:] ]
        return s
