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


from rmake_test import rmakehelp


class Databasetest(rmakehelp.RmakeHelper):

    def testJobConfig(self):
        db = self.openRmakeDatabase()
        db.jobStore.addJobConfig(1, '', self.buildCfg)
        db.commit()
        bc2 = db.jobStore.getJobConfig(1)
        assert(bc2.targetLabel == self.buildCfg.targetLabel)
        assert(bc2.resolveTroves == self.buildCfg.resolveTroves)
