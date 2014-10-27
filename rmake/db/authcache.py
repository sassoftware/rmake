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

import hashlib
import hmac
import os
import time

from conary.dbstore.sqlerrors import DatabaseLocked, ColumnNotUnique


CACHE_TIMEOUT = 15 * 60 # timeout after 15 mins

class BaseAuthenticationCache(object):

    def __init__(self):
        self.key = os.urandom(20)

    def _makeSessionId(self, authItemList):
        blob = '\0'.join([str(x) for x in authItemList])
        return hmac.new(self.key, blob, hashlib.sha1).hexdigest()

    def cache(self, authItemList):
        pass

    def checkCache(self, authItemList):
        return False


class AuthenticationCache(BaseAuthenticationCache):

    def __init__(self, db):
        self.db = db
        self.lastPurge = 0
        BaseAuthenticationCache.__init__(self)

    def cache(self, authItemList):
        sessionId =  self._makeSessionId(authItemList)
        timeStamp = time.time() + CACHE_TIMEOUT
        cu = self.db.cursor()
        for x in range(3):
            try:
                cu.execute("DELETE FROM AuthCache WHERE sessionId = ?",
                        cu.binary(sessionId))
                cu.execute("INSERT INTO AuthCache (sessionid, timestamp) "
                        "VALUES (?, ?)", cu.binary(sessionId), timeStamp)
            except (DatabaseLocked, ColumnNotUnique):
                # Race condition -- someone inserted a conflicting value
                # between our statements. Try again.
                self.db.rollback()
            else:
                # Success
                break
        else:
            raise
        self._deleteOld(cu)
        self.db.commit()

    def _deleteOld(self, cu):
        now = time.time()
        if now - self.lastPurge < 5:
            return
        cu.execute('DELETE FROM AuthCache WHERE timeStamp < ?', time.time())
        self.lastPurge = now

    def checkCache(self, authItemList):
        cu = self.db.cursor()
        sessionId = self._makeSessionId(authItemList)
        self._deleteOld(cu)
        match = False
        result = cu.execute('SELECT timeStamp FROM AuthCache WHERE sessionId=?',
                cu.binary(sessionId))
        if result.fetchall():
            match = True
            cu.execute('UPDATE AuthCache SET timeStamp=? WHERE sessionId=?',
                    time.time() + CACHE_TIMEOUT, cu.binary(sessionId))
        self.db.commit()
        return match


class AuthenticationMemcache(BaseAuthenticationCache):

    def __init__(self, memCache, memCachePrefix=''):
        self.memCache = memCache
        self.memCachePrefix = memCachePrefix
        BaseAuthenticationCache.__init__(self)

    def _cache(self, sessionId):
        self.memCache.set(self.memCachePrefix + sessionId,
                str(time.time()), CACHE_TIMEOUT)

    def cache(self, authItemList):
        sessionId = self._makeSessionId(authItemList)
        self._cache(sessionId)
        print 'SAVE', authItemList

    def checkCache(self, authItemList):
        sessionId = self._makeSessionId(authItemList)
        if self.memCache.get(self.memCachePrefix + sessionId):
            self._cache(sessionId)
            print 'HIT', authItemList
            return True
        else:
            print 'MISS', authItemList
            return False
