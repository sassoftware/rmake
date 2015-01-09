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

import errno
import gzip
import hashlib
import hmac
import os
from conary.lib import sha1helper
from conary.lib import util


class LogStore(object):

    def __init__(self, path):
        util.mkdirChain(path)
        self.top = path
        # This changes every instance and is only used to authenticate
        # connections from a worker to the log store.
        self.logKey = os.urandom(20)

    def hashTrove(self, trove):
        return sha1helper.sha1ToString(
                sha1helper.sha1String('%s %s=%s[%s]' % (trove.jobId,
                      trove.getName(), trove.getVersion(), trove.getFlavor())))

    def _hashToPath(self, logHash):
        assert len(logHash) >= 20
        return os.path.join(self.top, logHash[:2], logHash[2:4], logHash[4:])

    def getLogAuth(self, logHash):
        return hmac.new(self.logKey, logHash, hashlib.sha1).hexdigest()

    def openForWriting(self, logHash):
        if self.hasTroveLog(logHash):
            raise RuntimeError("Tried to open duplicate build log")
        path = self._hashToPath(logHash)
        util.mkdirChain(os.path.dirname(path))
        return CompressedLogWriter(path)

    def hasTroveLog(self, logHash):
        if not logHash:
            return False
        path = self._hashToPath(logHash)
        return os.path.exists(path) or os.path.exists(path + '.gz')

    def openTroveLog(self, logHash):
        if not logHash:
            raise KeyError
        path = self._hashToPath(logHash)
        try:
            return open(path)
        except IOError as err:
            if err.args[0] != errno.ENOENT:
                raise
        try:
            return gzip.GzipFile(path + '.gz')
        except IOError as err:
            if err.args[0] != errno.ENOENT:
                raise
        raise KeyError(logHash)

    def deleteLogs(self, logHashes):
        for logHash in logHashes:
            path = self._hashToPath(logHash)
            util.removeIfExists(path)
            util.removeIfExists(path + '.gz')


class CompressedLogWriter(object):
    """
    Simultaneously write to a plaintext log file and to a gzipped log file.
    When the log is closed, both are flushed and then the plaintext file is
    unlinked.

    This allows clients to tail the plaintext log while efficiently storing a
    compressed log to reference when the build is complete.
    """

    def __init__(self, path):
        self.path = path
        self.f_plain = open(path, 'w', buffering=0)
        self.f_gz = gzip.GzipFile(path + '.gz.new', 'w')

    def write(self, data):
        self.f_plain.write(data)
        self.f_gz.write(data)

    def close(self):
        """Flush the gzipped log and unlink the plaintext log"""
        self.f_plain.close()
        self.f_gz.close()
        try:
            os.rename(self.path + '.gz.new', self.path + '.gz')
            os.unlink(self.path)
        except OSError as err:
            if err.args[0] != errno.ENOENT:
                raise

    def beforeFork(self):
        self.f_gz.fileobj.flush()

    def afterFork(self):
        self.f_plain.close()
        self.f_gz.fileobj.close()
        self.f_gz.fileobj = None

    def filenos(self):
        return [self.f_plain.fileno(), self.f_gz.fileno()]
