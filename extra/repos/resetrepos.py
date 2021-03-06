#!/usr/bin/python
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


import os
import pwd
import random
import sys

from conary import dbstore
from conary.repository import errors
from conary.repository.netrepos import netauth
from conary.server import schema

def main(argv):
    if len(argv) < 2:
        dbPath = '/srv/rmake-repos/db/sqldb'
    else:
        dbPath = sys.argv[1]

    db = getDb(path=dbPath)
    addUser(db, 'anonymous', 'anonymous')
    newPassword = ''.join([chr(random.randint(ord('A'), ord('z'))) for x in range(10)])
    newPassword = 'rmake'

    passwordPath = '/etc/rmake/server.d/repospassword'
    open(passwordPath, 'w').write('')
    os.chmod(passwordPath, 0700)
    os.chown(passwordPath, pwd.getpwnam('rmake').pw_uid,
                           pwd.getpwnam('rmake').pw_gid)
    open(passwordPath, 'w').write('user localhost rmake %s\n' % newPassword)
    addUser(db, 'rmake', newPassword, write=True)

    print "New password stored in database and at %s" % passwordPath
    return 0

def getDb(path):
    if os.path.exists(path):
        print "Deleting database"
        os.remove(path)
    if os.listdir("/srv/rmake-repos/contents/"):
        print "Deleting contents..."
        os.system("rm -rf /srv/rmake-repos/contents/*")
    open(path, 'w')
    os.chown(path, pwd.getpwnam('apache').pw_uid,
                   pwd.getpwnam('apache').pw_gid)

    db = dbstore.connect(path, driver='sqlite')
    schema.loadSchema(db, True)
    schema.setupTempTables(db)
    return db

def addUser(db, name, password=None, write=False):
    auth = netauth.NetworkAuthorization(db, [])
    try:
        auth.userAuth.getUserIdByName(name)
    except errors.UserNotFound: # yuck, we need a hasUser interface
        pass
    else:
        auth.deleteUserByName(name)

    auth.addUser(name, password)
    auth.addRole(name)
    auth.addRoleMember(name, name)
    auth.addAcl(name, None, None, write, False)

if __name__ == '__main__':
    sys.exit(main(sys.argv))
