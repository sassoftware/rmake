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

import os
import subprocess
import tempfile
import time
from rmake.lib import locking
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

    def listCached(self):
        """
        Return a list of tuples (fingerprint, atime, size) of all chroots in
        the cache.
        """
        raise NotImplementedError

    def findPartialMatch(self, manifest):
        """
        Scan through existing cached chroots for one with a subset of the
        needed troves.

        Returns the fingerprint of the partial match that is closest to
        C{manifest} without any extra troves.
        """
        bestScore = -1
        bestFingerprint = None
        for name in os.listdir(self.cacheDir):
            if len(name) != (40 + len(self.suffix)) or not name.endswith(self.suffix):
                continue
            cached = ChrootManifest.read(os.path.join(self.cacheDir, name))
            if not cached:
                continue
            score = manifest.score(cached)
            if score > bestScore:
                bestScore = score
                bestFingerprint = sha1FromString(name[:40])
        return bestFingerprint

    def findOld(self, hours):
        """
        List all chroots that haven't been used in more than the specified
        interval.
        """
        thresh = time.time() - 3600 * hours
        return [fingerprint for (fingerprint, atime, size) in self.listCached()
                if atime < thresh]

    def setLogger(self, logger):
        self.logger = logger


class LocalChrootCache(ChrootCacheInterface):
    """
    The LocalChrootCache class implements a chroot cache that uses the
    local file system to store tar archive of chroots.
    """

    suffix = '.tar.gz'
    compress = 'gzip -1 -'
    decompress = 'zcat'

    def __init__(self, cacheDir, sizeLimit=None, chrootHelperPath=None):
        """
        Instanciate a LocalChrootCache object
        @param cacheDir: The base directory for the chroot cache files
        @type cacheDir: str
        """
        self.cacheDir = cacheDir
        try:
            self.sizeLimit = parseSize(sizeLimit or '0')
        except ValueError:
            raise ValueError("Invalid chrootcache size limit %r. Must be an "
                    "integer number of mebibytes, or an integer suffixed by "
                    "K, M, G, or T." % (sizeLimit,))

    def store(self, chrootFingerprint, root):
        path = self._fingerPrintToPath(chrootFingerprint)
        prefix = sha1ToString(chrootFingerprint) + '.'
        util.mkdirChain(self.cacheDir)
        lock = locking.LockFile(path + '.lock')
        if not lock.acquire(wait=False):
            # Busy, just do nothing
            return
        fd, fn = tempfile.mkstemp(self.suffix, prefix, self.cacheDir)
        os.close(fd)
        try:
            subprocess.call('tar -cC %s . | %s > %s' % (root, self.compress,
                fn), shell=True)
            os.rename(fn, path)
        finally:
            util.removeIfExists(fn)
            lock.release()
        ChrootManifest.store(root, path)
        self.prune()

    def restore(self, chrootFingerprint, root):
        path = self._fingerPrintToPath(chrootFingerprint)
        subprocess.call('%s %s | tar -xmC %s' % (self.decompress, path,
            root), shell=True)

    def remove(self, chrootFingerprint):
        path = self._fingerPrintToPath(chrootFingerprint)
        util.removeIfExists(path + ChrootManifest.AR_SUFFIX)
        util.removeIfExists(path)

    def hasChroot(self, chrootFingerprint):
        path = self._fingerPrintToPath(chrootFingerprint)
        return os.path.isfile(path)

    def _fingerPrintToPath(self, chrootFingerprint):
        tar = sha1ToString(chrootFingerprint) + self.suffix
        return os.path.join(self.cacheDir, tar)

    def listCached(self):
        items = []
        for name in os.listdir(self.cacheDir):
            if len(name) != (40 + len(self.suffix)
                    ) or not name.endswith(self.suffix):
                continue
            fingerprint = sha1FromString(name[:40])
            st = util.lstat(os.path.join(self.cacheDir, name))
            if st:
                items.append((fingerprint, st.st_atime, st.st_size))
        return items

    def prune(self):
        if not self.sizeLimit:
            return
        cached = self.listCached()
        cached.sort(key=lambda x: x[2])
        total = sum(x[2] for x in cached)
        for fingerprint, atime, size in cached:
            if total < self.sizeLimit:
                break
            self.logger.info("Deleting cached chroot %s to meet size limit",
                    sha1ToString(fingerprint))
            self.remove(fingerprint)
            total -= size


class LzopChrootCache(LocalChrootCache):
    suffix = '.tar.lzo'
    compress = 'lzop -c'
    decompress = 'lzop -dc'


class DirBasedChrootCacheInterface(ChrootCacheInterface):
    """
    Base class for chroot caches that look like a directory on disk.
    """
    suffix = ''

    def __init__(self, cacheDir, sizeLimit=None, chrootHelperPath=None):
        if sizeLimit:
            raise RuntimeError("This chrootcache type does not support size limits")
        self.cacheDir = cacheDir

    def _fingerPrintToPath(self, chrootFingerprint):
        basename = sha1ToString(chrootFingerprint) + self.suffix
        return os.path.join(self.cacheDir, basename)

    def listCached(self):
        items = []
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
            size = 0
            items.append((fingerprint, atime, size))
        return items

    def store(self, chrootFingerprint, root):
        path = self._fingerPrintToPath(chrootFingerprint)
        lock = locking.LockFile(path + '.lock')
        if not lock.acquire(wait=False):
            # Busy, just do nothing
            return
        try:
            if not os.path.exists(path):
                self._copy(root, path)
        finally:
            lock.release()

    def restore(self, chrootFingerprint, root):
        path = self._fingerPrintToPath(chrootFingerprint)
        if os.path.isdir(root):
            self._remove(root)
        with locking.LockFile(path + '.lock', share=True):
            open(os.path.join(path, '.used'), 'w').close()
            self._copy(path, root)
            util.removeIfExists(os.path.join(root, '.used'))

    def remove(self, chrootFingerprint):
        path = self._fingerPrintToPath(chrootFingerprint)
        with locking.LockFile(path + '.lock'):
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

    def __init__(self, cacheDir, sizeLimit=None, chrootHelperPath=None):
        super(BtrfsChrootCache, self).__init__(cacheDir, sizeLimit)
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
        tmpdest = '%s.tmp%d' % (dest, os.getpid())
        self._call(['/bin/cp', '-Tal', source, tmpdest])
        os.rename(tmpdest, dest)

    def _remove(self, path):
        tmpdest = '%s.tmp%d' % (path, os.getpid())
        os.rename(path, tmpdest)
        self._call(['/bin/rm', '-rf', tmpdest])


CACHE_TYPES = {
        'btrfs': BtrfsChrootCache,
        'hardlink': HardlinkChrootCache,
        'local': LocalChrootCache,
        'lzop': LzopChrootCache,
        }


def parseSize(val):
    if isinstance(val, (int, long)):
        return val
    val = val.upper()
    if val.endswith('K'):
        return int(val[:-1]) * 1024
    elif val.endswith('M'):
        return int(val[:-1]) * 1024 * 1024
    elif val.endswith('G'):
        return int(val[:-1]) * 1024 * 1024 * 1024
    elif val.endswith('T'):
        return int(val[:-1]) * 1024 * 1024 * 1024 * 1024
    elif not val:
        return 0
    else:
        return int(val) * 1024 * 1024
