#
# Copyright (c) 2006 rPath, Inc.
#
# This program is distributed under the terms of the Common Public License,
# version 1.0. A copy of this license should have been distributed with this
# source file in a file called LICENSE. If it is not present, the license
# is always available at http://www.opensource.org/licenses/cpl.php.
#
# This program is distributed in the hope that it will be useful, but
# without any warranty; without even the implied warranty of merchantability
# or fitness for a particular purpose. See the Common Public License for
# full details.
#
"""
Cache of changesets.  
"""
import errno
import os
import tempfile

from conary.lib import sha1helper
from conary.lib import util
from conary.repository import changeset
from conary.repository import datastore

class ChangeSetCache(object):
    """
        We cache changeset files by component.  When conary is fixed, we'll
        be able to combine the download of these troves.
    """
    def __init__(self, cacheDir):
        self.store = ChangeSetStore(cacheDir)

    def hashTrove(self, name, version, flavor):
        # we add extra delimiters here because we can be sure they they
        # will result in a unique string for each n,v,f
        return sha1helper.sha1ToString(
                sha1helper.sha1String('%s=%s[%s]' % (name, version, flavor)))

    def getChangeSetsForTroves(self, repos, troveList):
        return self.getChangeSets(repos,
                                  [(x[0], (None, None), (x[1], x[2]), False) 
                                   for x in troveList ])

    def getChangeSets(self, repos, jobList, callback=None):
        for job in jobList:
            if job[1][0]:
                raise CacheError('can only cache install,'
                                 ' not update changesets')
            if job[3]:
                raise CacheError('Cannot cache absolute changesets')

        changesets = []
        needed = []
        for job in jobList:
            csHash = str(self.hashTrove(job[0], *job[2]))
            if self.store.hasFile(csHash):
                outFile = self.store.openRawFile(csHash)
                changesets.append(changeset.ChangeSetFromFile(outFile))
            else:
                needed.append((job, csHash))


        total = len(needed)
        for idx, (job, csHash) in enumerate(needed):
            if callback:
                callback.setChangesetHunk(idx + 1, total)

            cs = repos.createChangeSet([job], recurse=False,
                                       callback=callback)

            tmpFd, tmpName = tempfile.mkstemp()
            os.close(tmpFd)
            cs.writeToFile(tmpName)
            # we could use this changeset, but 
            # cs.reset() is not necessarily reliable,
            # so instead we re-read from disk
            self.store.addFileFromTemp(csHash, tmpName)

            outFile = self.store.openRawFile(csHash)
            changesets.append(changeset.ChangeSetFromFile(outFile))

        return changesets


class ChangeSetStore(datastore.DataStore):
    def addFileFromTemp(self, hash, tmpPath):
        """
            Method to insert data into a datastore from a temporary file.
            The file is renamed to be in the datastore.
        """
        path = self.hashToPath(hash)
        self.makeDir(path)
        if os.path.exists(path): return

        try:
            util.rename(tmpPath, path)
        except OSError, err:
            if err.errno != errno.EXDEV:
                raise
            else:
                util.copyfile(tmpPath, path)
                util.removeIfExists(tmpPath)

class CacheError(Exception):
    pass
