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


import inspect
import os
import socket

from conary.deps import arch
from conary.deps import deps
from conary.lib.cfgtypes import CfgPath, CfgList, CfgString, CfgType
from conary.lib.cfgtypes import CfgBool, CfgEnum, CfgLineList
from conary.conarycfg import CfgFlavor, ParseError

from rmake.server import servercfg

class CfgFloat(CfgType):
    def parseString(self, val):
        try:
            return float(val)
        except ValueError, msg:
            raise ParseError, 'expected float'

class CfgSet(CfgList):

    def __init__(self, valueType, listType=set, default=set()):
        if inspect.isclass(valueType) and issubclass(valueType, CfgType):
            valueType = valueType()

        self.valueType = valueType
        self.listType = listType
        self.default = default

    def updateFromString(self, val, str):
        val.update(self.parseString(str))
        return val

    def toStrings(self, value, displayOptions=None):
        if displayOptions is None:
            displayOptions = {}
        if not value:
            yield '[]'
        else:
            for val in sorted(value):
                for str in self.valueType.toStrings(val, displayOptions):
                    yield str

class CfgJobType(CfgEnum):
    validValues = {'BUILD'   : 'BUILD',
                   'RESOLVE' : 'RESOLVE'}

class NodeConfiguration(servercfg.rMakeBuilderConfiguration):
    logDir            = (CfgPath, '/var/log/rmake')
    lockDir           = (CfgPath, '/var/run/rmake')
    serverUri         = (CfgString, None)
    useTmpfs          = (CfgBool, False)
    name              = None
    hostName          = None

    # job configuration
    rmakeUrl          = (CfgString,   'unix:///var/lib/rmake/socket')
    jobTypes          = CfgLineList(CfgJobType), ['BUILD']
    buildFlavors      = CfgSet(CfgFlavor)
    loadThreshold     = (CfgFloat, 2) # multiplied by the number of cpus

    def __init__(self, readConfigFiles = False, ignoreErrors = False):
        self.setIgnoreErrors(ignoreErrors)
        servercfg.rMakeBuilderConfiguration.__init__(self)

        if readConfigFiles:
            self.readFiles()
        if not self.hostName:
            self.hostName = socket.getfqdn()
        if not self.name:
            self.name = self.hostName.split('.')[0]
        if not self.buildFlavors:
            insSet = deps.DependencySet()
            for depList in arch.currentArch:
                for dep in depList:
                    flags = dep.getFlags()[0]
                    # don't include "prefers" flags.
                    flags = [ (x[0], x[1]) for x in flags if
                    x[1] in (deps.FLAG_SENSE_REQUIRED,
                    deps.FLAG_SENSE_DISALLOWED) ]
                    newDep = deps.Dependency(dep.name, flags)
                    insSet.addDep(deps.InstructionSetDependency, newDep)
            self.buildFlavors.add(insSet)

    def getName(self):
        return self.name

    def readFiles(self):
        # we often start the node in /etc/rmake, which makes it read its
        # default configuration file twice if we don't dedup.  This is
        # relatively harmless but does lead to duplicate entries in the 
        # buildFlavors list.
        readPaths = []
        for path in ['/etc/rmake/noderc', 'noderc']:
            if os.path.realpath(path) not in readPaths:
                self.read(path, False)
                readPaths.append(os.path.realpath(path))

    def sanityCheck(self):
        pass
