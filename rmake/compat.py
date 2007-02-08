#
# Copyright (c) 2006-2007 rPath, Inc.  All Rights Reserved.
#
"""
Tracks compatibility with versions of integrated software for backwards 
compatibility checks.
"""
from conary import constants
from conary import state
from conary.lib import log

from rmake import errors

class ConaryVersion(object):
    maxKnownVersion = "1.1.17"
    _warnedUser = False

    def __init__(self, conaryVersion=None):
        if conaryVersion is None:
            conaryVersion = constants.version

        try:
            self.conaryVersion = [int(x) for x in conaryVersion.split('.')]
        except ValueError, err:
            if not self._warnedUser:
                log.warning('nonstandard conary version "%s".  Assuming latest "%s".' % (conaryVersion, self.maxKnownVersion))
                ConaryVersion._warnedUser = True
            self.conaryVersion = [ int(x)
                                    for x in self.maxKnownVersion.split('.') ]

        self.majorVersion = self.conaryVersion[0:2]
        self.minorVersion = self.conaryVersion[2]
        self.isOneOne = self.majorVersion == (1,1)

    def checkRequiredVersion(self):
        oneZeroVersion = 42
        oneOneVersion = 15
        if not self.checkVersion(42, 15):
            raise errors.RmakeError('rMake requires conary version 1.0.%s'
                                    ' or 1.1.%s' % (oneZeroVersion,
                                                    oneOneVersion))

    def stateFileVersion(self):
        if not hasattr(state.ConaryState, 'stateVersion'):
            return 0
        return state.ConaryState.stateVersion

    def ConaryStateFromFile(self, path, repos=None, parseSource=True):
        if self.stateFileVersion() == 0: 
            return state.ConaryStateFromFile(path)
        else: # support added in 1.0.31 and 1.1.4
            return state.ConaryStateFromFile(path, repos=repos,
                                             parseSource=parseSource)


    def supportsCloneCallback(self):
        # support added in 1.0.30 and 1.1.3
        return self.checkVersion(30, 3)

    def supportsCloneNoTracking(self):
        # support added in 1.1.17
        return self.checkVersion(None, 17)

    def supportsConfigIsDefault(self):
        # support added in 1.0.33 and 1.1.6
        return self.checkVersion(33, 6)

    def supportsCloneNonRecursive(self):
        # support added in 1.0.30 and 1.1.3
        return self.checkVersion(30, 3)

    def checkVersion(self, oneZeroVersion, oneOneVersion):
        if self.majorVersion == [1,0]:
            if oneZeroVersion is None:
                return False
            return self.minorVersion >= oneZeroVersion
        elif self.majorVersion == [1,1]:
            if oneOneVersion is None:
                return False
            return self.minorVersion >= oneOneVersion

def checkRequiredVersions():
    ConaryVersion().checkRequiredVersion()
