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
Cache of chroots.
"""

import errno
import os
import subprocess
import tempfile

from conary.lib import sha1helper, util
sha1ToString = sha1helper.sha1ToString

class ChrootCacheInterface(object):
    """
    ChrootCacheInterface defines the standard interface for a chroot
    cache.  It should never be instantiated.
    """
    def store(self, chrootFingerprint, root):
        """
        Store the chroot currently located at C{root} in the
        filesystem using the given chroot fingerprint.

        @param chrootFingerprint: The fingerprint (a SHA1 sum) to use
        when storing the chroot
        @type chrootFingerprint: str of length 20
        @param root: The location of the chroot in the filesystem
        @type root: str
        @return: None
        """
        raise NotImplementedError

    def restore(self, chrootFingerprint, root):
        """
        Return the cached chroot with the given chroot fingerprint to
        the directory specified by C{root}

        @param chrootFingerprint: The fingerprint (a SHA1 sum) to use
        when restoring the chroot
        @type chrootFingerprint: str of length 20
        @param root: The location to restore the chroot in the filesystem
        @type root: str
        @return: None
        """
        raise NotImplementedError

    def remove(self, chrootFingerprint):
        """
        Delete a cached chroot archive.

        @param chrootFingerprint: The fingerprint (a SHA1 sum) to delete
        @type  chrootFingerprint: str of length 20
        """
        raise NotImplementedError

    def hasChroot(self, chrootFingerprint):
        """
        Check to see if the chroot cache contains an entry for the given
        chroot fingerprint

        @param chrootFingerprint: The fingerprint (a SHA1 sum) to check
        @type chrootFingerprint: str of length 20
        @return: bool
        """
        raise NotImplementedError

    def createRoot(self, root):
        """
        Prepare a working chroot directory for install.
        """
        pass

    def removeRoot(self, root):
        """
        Attempt to delete a working chroot directory.

        Returns C{True} if the directory was removed, or C{False} if the caller
        should clean it up.
        """
        return False


class LocalChrootCache(ChrootCacheInterface):
    """
    The LocalChrootCache class implements a chroot cache that uses the
    local file system to store tar archive of chroots.
    """
    def __init__(self, cacheDir):
        """
        Instanciate a LocalChrootCache object
        @param cacheDir: The base directory for the chroot cache files
        @type cacheDir: str
        """
        self.cacheDir = cacheDir

    def store(self, chrootFingerprint, root):
        path = self._fingerPrintToPath(chrootFingerprint)
        prefix = sha1ToString(chrootFingerprint) + '.'
        util.mkdirChain(self.cacheDir)
        fd, fn = tempfile.mkstemp('.tar.gz', prefix, self.cacheDir)
        os.close(fd)
        try:
            subprocess.call('tar cSpf - -C %s . | gzip -1 - > %s' %(root, fn),
                            shell=True)
            os.rename(fn, path)
        finally:
            util.removeIfExists(fn)

    def restore(self, chrootFingerprint, root):
        path = self._fingerPrintToPath(chrootFingerprint)
        subprocess.call('zcat %s | tar xSpf - -C %s' %(path, root),
                        shell=True)

    def remove(self, chrootFingerprint):
        path = self._fingerPrintToPath(chrootFingerprint)
        try:
            os.unlink(path)
        except OSError, err:
            if err.errno != errno.ENOENT:
                raise

    def hasChroot(self, chrootFingerprint):
        path = self._fingerPrintToPath(chrootFingerprint)
        return os.path.isfile(path)

    def _fingerPrintToPath(self, chrootFingerprint):
        tar = sha1ToString(chrootFingerprint) + '.tar.gz'
        return os.path.join(self.cacheDir, tar)


class BtrfsChrootCache(ChrootCacheInterface):

    def __init__(self, cacheDir, chrootHelperPath):
        self.cacheDir = cacheDir
        self.chrootHelperPath = chrootHelperPath

    def _callHelper(self, args):
        args = [self.chrootHelperPath] + list(args)
        p = subprocess.Popen(args, shell=False, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE)
        stdout, stderr = p.communicate()
        if p.returncode:
            msg = "Failed to invoke btrfs helper"
            if stdout.strip():
                msg += "\nstdout:\n" + stdout
            if stderr.strip():
                msg += "\nstderr:\n" + stderr
            raise RuntimeError(msg)

    def store(self, chrootFingerprint, root):
        path = self._fingerPrintToPath(chrootFingerprint)
        self._callHelper(["--btrfs-snapshot", path, root])

    def restore(self, chrootFingerprint, root):
        path = self._fingerPrintToPath(chrootFingerprint)
        if os.path.isdir(root):
            self._callHelper(["--btrfs-delete", root])
        self._callHelper(["--btrfs-snapshot", root, path])

    def remove(self, chrootFingerprint):
        path = self._fingerPrintToPath(chrootFingerprint)
        self._callHelper(["--btrfs-delete", path])

    def hasChroot(self, chrootFingerprint):
        path = self._fingerPrintToPath(chrootFingerprint)
        return os.path.isdir(path)

    def createRoot(self, root):
        marker = os.path.join(root, '.btrfs')
        if os.path.exists(marker):
            return
        self._callHelper(["--btrfs-create", root])
        open(marker, 'w').close()

    def removeRoot(self, root):
        if os.path.exists(os.path.join(root, '.btrfs')):
            self._callHelper(["--btrfs-delete", root])
            return True
        else:
            return False

    def _fingerPrintToPath(self, chrootFingerprint):
        basename = sha1ToString(chrootFingerprint) + '.btrfs'
        return os.path.join(self.cacheDir, basename)
