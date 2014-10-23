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

import cPickle
import os
from conary.lib import digestlib
from conary.lib import util


class ChrootManifest(object):

    FILENAME = 'rmake.manifest'
    AR_SUFFIX = '.manifest'

    def __init__(self, jobFingerprints, bootstrapFingerprints,
            crossFingerprints, rpmRequirements):
        self.jobFingerprints = set(jobFingerprints)
        self.bootstrapFingerprints = set(bootstrapFingerprints)
        self.crossFingerprints = set(crossFingerprints)
        self.rpmRequirements = set(rpmRequirements)

    @classmethod
    def read(cls, root_or_path):
        if os.path.isdir(root_or_path):
            path = os.path.join(root_or_path, cls.FILENAME)
        else:
            path = root_or_path + cls.AR_SUFFIX
        try:
            return cPickle.load(open(path))
        except:
            return None

    def write(self, root):
        with util.AtomicFile(os.path.join(root, self.FILENAME)) as fobj:
            cPickle.dump(self, fobj)

    @classmethod
    def store(cls, root, archive):
        """
        Copy a manifest from inside a chroot to adjacent to a file archive
        """
        f_in = open(os.path.join(root, cls.FILENAME))
        with util.AtomicFile(archive + cls.AR_SUFFIX) as f_out:
            util.copyfileobj(f_in, f_out)
        f_in.close()

    def score(self, cached):
        if self.bootstrapFingerprints != cached.bootstrapFingerprints:
            # Can't go back and install a different bootstrap trove once the
            # main install has run, so bootstrapFingerprints has to match
            # exactly.
            return None
        score = 0
        for key in ['jobFingerprints', 'crossFingerprints']:
            mine = getattr(self, key)
            theirs = getattr(cached, key)
            if theirs - mine:
                # Only installs are permitted, so anything 'extra' disqualifies
                # the cached chroot.
                return None
            score += len(mine & theirs)
        return score

    def getFingerprint(self):
        d = digestlib.sha1()
        for fplist in [
                self.jobFingerprints,
                self.bootstrapFingerprints,
                self.crossFingerprints,
                ]:
            d.update(''.join(sorted(fplist)) + '\0\0')
        d.update('\0'.join(x.freeze() for x in sorted(self.rpmRequirements)))
        return d.digest()
