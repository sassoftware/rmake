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
import fcntl
import os
from conary.lib.util import statFile


class LockFile(object):
    """
    Protect a code block with an exclusive file lock. Can be used as a context
    manager, or standalone.

    >>> with LockFile(path):
    ...     do_stuff()
    """

    def __init__(self, path, callback=None, share=False):
        self.path = path
        self.callback = callback
        self.share = share
        self.fobj = None

    @staticmethod
    def _lock(fobj, wait, share):
        if share:
            flags = fcntl.LOCK_SH
        else:
            flags = fcntl.LOCK_EX
        if not wait:
            flags |= fcntl.LOCK_NB
        try:
            fcntl.lockf(fobj, flags)
            return True
        except IOError as err:
            if err.args[0] != errno.EAGAIN:
                raise
            assert not wait
            return False
        except:
            raise

    def _acquire_once(self, wait):
        fobj = open(self.path, 'w+')
        try:
            if not self._lock(fobj, wait, self.share):
                fobj.close()
                return False
            if statFile(fobj, True, True) != statFile(self.path, True, True):
                # The file was unlinked and possibly replaced with a different
                # one, so this lock is useless.
                fobj.close()
                return False
        except:
            fobj.close()
            raise
        self.fobj = fobj
        return True

    def acquire(self, wait=True):
        """
        Try to acquire a lock. Returns True if it succeeded, or False if it did
        not.

        @param wait: If True, wait until it is possible to acquire the lock
            before returning. The method will not return False in this mode.
        """
        ok = self._acquire_once(False)
        if ok or not wait:
            return ok
        if self.callback:
            self.callback()
        while True:
            if self._acquire_once(True):
                break
        return True
    __enter__ = acquire

    def release(self):
        """
        Release the lock. Does nothing if no lock was previously acquired.
        """
        fobj = self.fobj
        if not fobj:
            return
        # Try to escalate to an exclusive lock (if it wasn't already); if it
        # works then nobody else is using this lockfile and it can be unlinked.
        if self._lock(fobj, wait=False, share=False):
            os.unlink(self.path)
        self.fobj = None
        fobj.close()

    def __exit__(self, *args):
        self.release()
