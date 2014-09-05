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
import fcntl
import os
import subprocess
import tempfile
import time
from rmake.worker.chroot.rootmanifest import ChrootManifest

from conary.lib import util
from conary.lib.sha1helper import sha1ToString, sha1FromString


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

    def findPartialMatch(self, manifest):
        """
        Scan through existing cached chroots for one with a subset of the
        needed troves.

        Returns the fingerprint of the partial match that is closest to
        C{manifest} without any extra troves.
        """
        return None

    def findOld(self, hours):
        """
        List all chroots that haven't been used in more than the specified
        interval.
        """
        raise NotImplementedError


class LocalChrootCache(ChrootCacheInterface):
    """
    The LocalChrootCache class implements a chroot cache that uses the
    local file system to store tar archive of chroots.
    """
    suffix = '.tar.gz'


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
        fd, fn = tempfile.mkstemp(self.suffix, prefix, self.cacheDir)
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
        util.removeIfExists(path)

    def hasChroot(self, chrootFingerprint):
        path = self._fingerPrintToPath(chrootFingerprint)
        return os.path.isfile(path)

    def _fingerPrintToPath(self, chrootFingerprint):
        tar = sha1ToString(chrootFingerprint) + self.suffix
        return os.path.join(self.cacheDir, tar)

    def findOld(self, hours):
        thresh = time.time() - 3600 * hours
        old = []
        for name in os.listdir(self.cacheDir):
            if len(name) != (40 + len(self.suffix)) or not name.endswith(self.suffix):
                continue
            fingerprint = sha1FromString(name[:40])
            st = util.lstat(os.path.join(self.cacheDir, name))
            if st:
                atime = st.st_mtime
                if atime < thresh:
                    old.append(fingerprint)
        return old


class DirBasedChrootCacheInterface(ChrootCacheInterface):
    """
    Base class for chroot caches that look like a directory on disk.
    """
    suffix = ''

    def __init__(self, cacheDir):
        self.cacheDir = cacheDir

    def _fingerPrintToPath(self, chrootFingerprint):
        basename = sha1ToString(chrootFingerprint) + self.suffix
        return os.path.join(self.cacheDir, basename)

    def findPartialMatch(self, manifest):
        bestScore = -1
        bestFingerprint = None
        for name in os.listdir(self.cacheDir):
            if len(name) != (40 + len(self.suffix)) or not name.endswith(self.suffix):
                continue
            cached = ChrootManifest.read(os.path.join(self.cacheDir, name))
            if not manifest:
                continue
            score = manifest.score(cached)
            if score > bestScore:
                bestScore = score
                bestFingerprint = sha1FromString(name[:40])
        return bestFingerprint

    def findOld(self, hours):
        thresh = time.time() - 3600 * hours
        old = []
        for name in os.listdir(self.cacheDir):
            if len(name) != (40 + len(self.suffix)) or not name.endswith(self.suffix):
                continue
            fingerprint = sha1FromString(name[:40])
            st = util.lstat(os.path.join(self.cacheDir, name, '.used'))
            if st:
                atime = st.st_mtime
            else:
                st = util.lstat(os.path.join(self.cacheDir, name))
                if st:
                    atime = st.st_atime
                else:
                    # Disappeared
                    continue
            if atime < thresh:
                old.append(fingerprint)
        return old

    def store(self, chrootFingerprint, root):
        path = self._fingerPrintToPath(chrootFingerprint)
        lock = open(path + '.lock', 'w+')
        try:
            fcntl.lockf(lock.fileno(), fcntl.LOCK_NB | fcntl.LOCK_EX)
        except IOError, err:
            if err.errno != errno.EAGAIN:
                raise
            # Conflict, just do nothing
            return
        if util.statFile(lock, True, True
                ) != util.statFile(lock.name, True, True):
            # Locked an unlinked file
            return
        if not os.path.exists(path):
            self._copy(root, path)
        os.unlink(lock.name)
        lock.close()

    def restore(self, chrootFingerprint, root):
        path = self._fingerPrintToPath(chrootFingerprint)
        if os.path.isdir(root):
            self._remove(root)
        with util.AtomicFile(os.path.join(path, '.used')):
            pass
        self._copy(path, root)
        util.removeIfExists(os.path.join(root, '.used'))

    def remove(self, chrootFingerprint):
        path = self._fingerPrintToPath(chrootFingerprint)
        self._remove(path)

    def hasChroot(self, chrootFingerprint):
        path = self._fingerPrintToPath(chrootFingerprint)
        return os.path.isdir(path)

    def _call(self, args):
        p = subprocess.Popen(args, shell=False, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE)
        stdout, stderr = p.communicate()
        if p.returncode:
            msg = "Failed to operate on chroot"
            if stdout.strip():
                msg += "\nstdout:\n" + stdout
            if stderr.strip():
                msg += "\nstderr:\n" + stderr
            raise RuntimeError(msg)

    def _copy(self, source, dest):
        raise NotImplementedError

    def _remove(self, path):
        raise NotImplementedError


class BtrfsChrootCache(DirBasedChrootCacheInterface):
    suffix = '.btrfs'

    def __init__(self, cacheDir, chrootHelperPath):
        super(BtrfsChrootCache, self).__init__(cacheDir)
        self.chrootHelperPath = chrootHelperPath

    def createRoot(self, root):
        marker = os.path.join(root, self.suffix)
        if os.path.exists(marker):
            return
        self._call([self.chrootHelperPath, "--btrfs-create", root])
        open(marker, 'w').close()

    def removeRoot(self, root):
        if os.path.exists(os.path.join(root, self.suffix)):
            self._remove(root)
            return True
        else:
            return False

    def _copy(self, source, dest):
        self._call([self.chrootHelperPath, "--btrfs-snapshot", dest, source])

    def _remove(self, path):
        self._call([self.chrootHelperPath, "--btrfs-delete", path])


class HardlinkChrootCache(DirBasedChrootCacheInterface):
    suffix = '.linked'

    def _copy(self, source, dest):
        # -T -- never copy source as a subdir of dest if dest already exists
        # -a -- archive i.e. recurse and don't follow symlinks
        # -l -- hardlink files instead of copying
        self._call(['/bin/cp', '-Tal', source, dest])

    def _remove(self, path):
        os.rename(path, path + '.dead')
        self._call(['/bin/rm', '-rf', path + '.dead'])
