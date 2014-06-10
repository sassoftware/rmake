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


import itertools
from conary.deps import deps
from conary.local import deptable

from conary.repository import resolvemethod
from conary.repository import trovesource

from rmake.lib import flavorutil

class TroveSourceMesh(trovesource.SearchableTroveSource):
    def __init__(self, extraSource, mainSource, repos):
        trovesource.SearchableTroveSource.__init__(self)
        self.extraSource = extraSource
        self.mainSource = mainSource
        self.repos = repos
        trovesource.SearchableTroveSource.__init__(self)
        self.searchAsRepository()
        for source in self.mainSource, self.repos, self.extraSource:
            if not source:
                continue
            self._allowNoLabel = source._allowNoLabel
            self._bestFlavor = source._bestFlavor
            self._getLeavesOnly = source._getLeavesOnly
            self._flavorCheck = source._flavorCheck
            break
        self.sources = [ self.extraSource]
        if self.mainSource:
            self.sources.append(self.mainSource)
        if self.repos:
            self.sources.append(self.repos)

    def __getattr__(self, key):
        if self.repos:
            return getattr(self.repos, key)
        return getattr(self.mainSource, key)

    def getFileVersions(self, *args, **kw):
        if self.repos:
            return self.repos.getFileVersions(*args, **kw)
        return self.mainSource.getFileVersions(*args, **kw)

    def close(self):
        pass

    def hasTroves(self, troveList):
        if self.repos:
            results = self.repos.hasTroves(troveList)
            if isinstance(results, dict):
                results = [ results[x] for x in troveList ]
        else:
            results = [ False for x in troveList ]
        if self.extraSource:
            hasTroves = self.extraSource.hasTroves(troveList)
            results = [ x[0] or x[1] for x in itertools.izip(results,
                                                                hasTroves) ]
        if self.mainSource:
            hasTroves = self.mainSource.hasTroves(troveList)
            results = [ x[0] or x[1] for x in itertools.izip(results,
                                                             hasTroves) ]
        return dict(itertools.izip(troveList, results))

    def trovesByName(self, name):
        if self.mainSource:
            return list(set(self.mainSource.trovesByName(name)) 
                        | set(self.extraSource.trovesByName(name)))
        else:
            return self.extraSource.trovesByName(name)

    def getTroves(self, troveList, *args, **kw):
        if self.repos:
            return self.repos.getTroves(troveList, *args, **kw)
        else:
            return self.mainSource.getTroves(troveList, *args, **kw)

    def _mergeTroveQuery(self, resultD, response):
        if isinstance(resultD, dict):
            for troveName, troveVersions in response.iteritems():
                if not resultD.has_key(troveName):
                    resultD[troveName] = {}
                versionDict = resultD[troveName]
                for version, flavors in troveVersions.iteritems():
                    if version not in versionDict:
                        versionDict[version] = []
                    resultD[troveName][version].extend(flavors)
        else:
            if not resultD:
                for resultList in response:
                    resultD.append(list(resultList))
            else:
                for idx, resultList in enumerate(response):
                    resultD[idx].extend(resultList)
        return resultD

    def _mergeListTroveQuery(self, resultList, result2, altFlavors, altFlavors2,
                            map, query):
        newMap = []
        newQuery = []
        for idx, items in enumerate(result2):
            if not items:
                newMap.append(map[idx])
                newQuery.append(query[idx])
                if altFlavors2:
                    altFlavors[map[idx]].extend(altFlavors2[idx])
            else:
                resultList[map[idx]].extend(items)
                altFlavors[map[idx]] = []
        return newMap, newQuery


    def _call(self, fn, query, *args, **kw):
        if not isinstance(query, dict):
            query = list(query)
            result, altFlavors = getattr(self.extraSource, fn)(query,
                                                               *args, **kw)
            map = []
            newQuery = []
            for idx, item in enumerate(result):
                if not item:
                    map.append(idx)
                    newQuery.append(query[idx])
            if self.mainSource:
                result2, altFlavors2 = getattr(self.mainSource, fn)(newQuery,
                                                                   *args, **kw)
                newQuery, map = self._mergeListTroveQuery(result, result2,
                                                          altFlavors,
                                                          altFlavors2,
                                                          map, newQuery)
            if self.repos:
                result3, altFlavors3 = getattr(self.repos, fn)(newQuery, 
                                                               *args, **kw)
                newQuery, map = self._mergeListTroveQuery(result, result3,
                                                          altFlavors,
                                                          altFlavors3,
                                                          map, newQuery)
            result = result, altFlavors
        else:
            query = dict(query)
            d1 = getattr(self.extraSource, fn)(query, *args, **kw)
            result = {}
            self._mergeTroveQuery(result, d1)
            for name in result:
                query.pop(name)
            if self.mainSource:
                d2 = getattr(self.mainSource, fn)(query, *args, **kw)
                self._mergeTroveQuery(result, d2)
            if self.repos:
                d3 = getattr(self.repos, fn)(query, *args, **kw)
                self._mergeTroveQuery(result, d3)
        return result

    def _addLabelsToQuery(self, query):
        if isinstance(query, dict):
            newQuery = query.copy()
            names = query
            for name in query:
                labels = set(x[1].trailingLabel() for x in
                             self.extraSource.trovesByName(name))
                #asserts there is only one flavorList
                flavorList, = set(x and tuple(x) for x in query[name].values())
                for label in labels:
                    if label not in query[name]:
                        newQuery[name][label] = flavorList
            map = None
        else:
            map = {}
            newQuery = list(query)
            names = [(x[0], x[1][0], x[1][2]) for x in enumerate(query)]
            for idx, name, flavor in names:
                labels = set(x[1].trailingLabel() for x in
                             self.extraSource.trovesByName(name))
                for label in labels:
                    map[len(newQuery)] = idx
                    newQuery.append((name, label, flavor))
        return newQuery, map

    def _compressResults(self, results, map):
        if map is None:
            return results
        results, altFlavors = results
        finalResults = []
        for idx, result  in enumerate(results):
            if idx in map:
                if result:
                    finalResults[map[idx]].extend(result)
                    altFlavors[map[idx]] = []
                else:
                    altFlavors[map[idx]].extend(altFlavors)
            else:
                finalResults.append(result)
        return finalResults, altFlavors

    def getTroveLatestByLabel(self, query, *args, **kw):
        map = None
        if self.expandLabelQueries:
            query, map = self._addLabelsToQuery(query)
        results = self._call('getTroveLatestByLabel', query, *args, **kw)
        return self._compressResults(results, map)

    def getTroveLeavesByLabel(self, query, *args, **kw):
        map = None
        if self.expandLabelQueries:
            query, map = self._addLabelsToQuery(query)
        results = self._call('getTroveLeavesByLabel', query, *args, **kw)
        return self._compressResults(results, map)

    def getTroveVersionsByLabel(self, query, *args, **kw):
        map = None
        if self.expandLabelQueries:
            query, map = self._addLabelsToQuery(query)
        results = self._call('getTroveVersionsByLabel', query, *args, **kw)
        return self._compressResults(results, map)

    def getTroveLeavesByBranch(self, query, *args, **kw):
        return self._call('getTroveLeavesByBranch', query, *args, **kw)

    def getTroveVersionsByBranch(self, query, *args, **kw):
        return self._call('getTroveVersionsByBranch', query, *args, **kw)

    def getTroveVersionFlavors(self, query, *args, **kw):
        return self._call('getTroveVersionFlavors', query, *args, **kw)

    def findTroves(self, labelPath, troveSpecs, defaultFlavor=None,
                   acrossLabels=False, acrossFlavors=False,
                   affinityDatabase=None, allowMissing=False,
                   bestFlavor=None, getLeaves=None,
                   troveTypes=trovesource.TROVE_QUERY_PRESENT, 
                   exactFlavors=False,
                   **kw):
        if self.mainSource is None:
            return trovesource.SearchableTroveSource.findTroves(self,
                                            labelPath, troveSpecs,
                                            defaultFlavor=defaultFlavor,
                                            acrossLabels=acrossLabels,
                                            acrossFlavors=acrossFlavors,
                                            affinityDatabase=affinityDatabase,
                                            troveTypes=troveTypes,
                                            exactFlavors=exactFlavors,
                                            allowMissing=True,
                                            **kw)
        results = {}
        if bestFlavor is not None:
            kw.update(bestFlavor=bestFlavor)
        if getLeaves is not None:
            kw.update(getLeaves=getLeaves)

        for source in self.sources:
            if source == self.repos:
                # we need the labelPath for repos, otherwise
                # we allow other algorithms to determine which 
                # version of a particular trove to use - the same ones
                # used during dep resolution.  Sometimes this will not 
                # be a package on the ILP.
                searchLabelPath = labelPath
            else:
                searchLabelPath = None
            foundTroves = source.findTroves(searchLabelPath, troveSpecs,
                                            defaultFlavor=defaultFlavor,
                                            acrossLabels=acrossLabels,
                                            acrossFlavors=acrossFlavors,
                                            affinityDatabase=affinityDatabase,
                                            troveTypes=troveTypes,
                                            exactFlavors=exactFlavors,
                                            allowMissing=True,
                                            **kw)
            for troveSpec, troveTups in foundTroves.iteritems():
                results.setdefault(troveSpec, []).extend(troveTups)
        if not allowMissing:
            for troveSpec in troveSpecs:
                assert(troveSpec in results)
        return results

    def resolveDependencies(self, label, depList, *args, **kw):
        sugg = self.extraSource.resolveDependencies(label, depList, *args, **kw)
        sugg2 = self.repos.resolveDependencies(label, depList, *args, **kw)
        for depSet, trovesByDep in sugg.iteritems():
            for idx, troveList in enumerate(trovesByDep):
                if not troveList:
                    troveList.extend(sugg2[depSet][idx])
        return sugg

    def resolveDependenciesByGroups(self, troveList, depList):
        sugg = self.extraSource.resolveDependencies(None, depList)
        sugg2 = self.repos.resolveDependenciesByGroups(troveList, depList)
        for depSet, trovesByDep in sugg.iteritems():
            for idx, troveList in enumerate(trovesByDep):
                if not troveList:
                    troveList.extend(sugg2[depSet][idx])
        return sugg




class DepHandlerSource(TroveSourceMesh):
    def __init__(self, builtTroveSource, troveListList, repos=None,
                 useInstallLabelPath=True, expandLabelQueries=False):
        if repos:
            flavorPrefs = repos._flavorPreferences
        else:
            flavorPrefs = []
        stack = trovesource.TroveSourceStack()
        stack.searchWithFlavor()
        stack.setFlavorPreferenceList(flavorPrefs)
        self.setFlavorPreferenceList(flavorPrefs)
        self.expandLabelQueries = expandLabelQueries
        self.resolveTroveSource = None

        if isinstance(troveListList, trovesource.SimpleTroveSource):
            troveListList.setFlavorPreferenceList(flavorPrefs)
            self.stack.addSource(troveListList)
            self.resolveTroveSource = troveListList
        else:
            if troveListList:
                for troveList in troveListList:
                    allTroves = [ x.getNameVersionFlavor() for x in troveList ]
                    childTroves = itertools.chain(*
                                   (x.iterTroveList(weakRefs=True,
                                                    strongRefs=True)
                                    for x in troveList))
                    allTroves.extend(childTroves)
                    source = trovesource.SimpleTroveSource(allTroves)
                    source.searchWithFlavor()
                    source.setFlavorPreferenceList(flavorPrefs)
                    stack.addSource(source)
                self.resolveTroveSource = stack
            if not useInstallLabelPath:
                repos = None
        if not stack.sources:
            stack = None
        TroveSourceMesh.__init__(self, builtTroveSource, stack, repos)

    def __repr__(self):
        return 'DepHandlerSource(%r,%r,%r)' % (self.extraSource, self.mainSource, self.repos)

    def copy(self):
        inst = self.__class__(self.source, None, self.repos)
        inst.repos = self.repos
        return inst


class BuiltTroveSource(trovesource.SimpleTroveSource):
    """
        Trove source that is used for dep resolution and buildreq satisfaction 
        only - it does not contain references to the changesets that are added
    """
    def __init__(self, troves, repos):
        self.depDb = deptable.DependencyDatabase()
        trovesource.SimpleTroveSource.__init__(self)
        self.setFlavorPreferenceList(repos._flavorPreferences)
        self.idMap = []
        self.idx = 0
        for trove in troves:
            self.addTrove(trove.getNameVersionFlavor(), trove.getProvides(),
                          trove.getRequires())
        self.searchWithFlavor()

    def close(self):
        self.depDb.db.close()

    def __del__(self):
        self.depDb.db.close()

    def addTrove(self, troveTuple, provides, requires):
        self._trovesByName.setdefault(troveTuple[0],set()).add(troveTuple)

        self.idMap.append(troveTuple)
        self.depDb.add(self.idx, provides, requires)
        self.idx += 1

    def addChangeSet(self, cs):
        for idx, trvCs in enumerate(cs.iterNewTroveList()):
            self.addTrove(trvCs.getNewNameVersionFlavor(), trvCs.getProvides(),
                          trvCs.getRequires())

    def resolveDependencies(self, label, depList, leavesOnly=False):
        suggMap = self.depDb.resolve(label, depList)
        for depSet, solListList in suggMap.iteritems():
            newSolListList = []
            for solList in solListList:
                if not self._allowNoLabel and label:
                    newSolListList.append([ self.idMap[x] for x in solList if self.idMap[x][1].trailingLabel == label])
                else:
                    newSolListList.append([ self.idMap[x] for x in solList ])
            suggMap[depSet] = newSolListList
        return suggMap


class ResolutionMesh(resolvemethod.BasicResolutionMethod):
    def __init__(self, cfg, extraMethod, mainMethod):
        resolvemethod.BasicResolutionMethod.__init__(self, cfg, None)
        self.extraMethod = extraMethod
        self.mainMethod = mainMethod

    def prepareForResolution(self, depList):
        self.depList = [ x[1] for x in depList]
        self.extraMethod.prepareForResolution(depList)
        return self.mainMethod.prepareForResolution(depList)

    def resolveDependencies(self):
        suggMap = self.extraMethod.resolveDependencies()
        suggMap2 = self.mainMethod.resolveDependencies()
        for depSet in self.depList:
            if depSet not in suggMap:
                suggMap[depSet] = [[] for x in depSet.iterDeps() ]
            if depSet not in suggMap2:
                suggMap2[depSet] = [[] for x in depSet.iterDeps() ]
        for depSet, results in suggMap.iteritems():
            mainResults = suggMap2[depSet]
            for troveList1, troveList2 in itertools.izip(results, mainResults):
                troveList2.extend(troveList1)
        return suggMap2

    def searchLeavesOnly(self):
        self.extraMethod.searchLeavesOnly()
        self.mainMethod.searchLeavesOnly()

    def searchLeavesFirst(self):
        self.extraMethod.searchLeavesFirst()
        self.mainMethod.searchLeavesFirst()

    def searchAllVersions(self):
        self.extraMethod.searchAllVersions()
        self.mainMethod.searchAllVersions()


class rMakeResolveSource(ResolutionMesh):
    """ 
        Resolve by trove list first and then resort back to label
        path.  Also respects intra-trove deps.  If foo:runtime
        requires foo:lib, it requires exactly the same version of foo:lib.
    """

    def __init__(self, cfg, builtTroveSource, resolveTroveSource,
                 troveLists, repos):
        self.removeFileDependencies = False
        self.builtTroveSource = builtTroveSource
        self.troveLists = troveLists
        self.resolveTroveSource = resolveTroveSource
        self.repos = repos
        self.cfg = cfg
        self.repos = repos
        self.flavor = cfg.flavor
        sources = []
        builtResolveSource = resolvemethod.BasicResolutionMethod(cfg, None)
        builtResolveSource.setTroveSource(builtTroveSource)

        sources = []
        if troveLists:
            troveListSources = [resolvemethod.DepResolutionByTroveList(cfg, None, x)
                                 for x in troveLists]
            [ x.setTroveSource(self.repos) for x in troveListSources ]
            sources.extend(troveListSources)

        mainMethod = resolvemethod.ResolutionStack(*sources)
        flavorPreferences = self.repos._flavorPreferences
        for source in sources:
            source.setFlavorPreferences(flavorPreferences)
        ResolutionMesh.__init__(self, cfg, builtResolveSource, mainMethod)
        self.setFlavorPreferences(flavorPreferences)

    def close(self):
        self.builtTroveSource.close()

    def setLabelPath(self, labelPath):
        if labelPath:
            source = resolvemethod.DepResolutionByLabelPath(self.cfg, None, labelPath)
            source.setTroveSource(self.repos)
            self.mainMethod.addSource(source)

    def prepareForResolution(self, depList):
        # need to get intratrove deps while we still have the full dependency
        # request information - including what trove the dep arises from.
        intraDeps = self._getIntraTroveDeps(depList)
        self.intraDeps = intraDeps
        return ResolutionMesh.prepareForResolution(self, depList)

    def _resolveIntraTroveDeps(self, intraDeps):
        trovesToGet = []
        for depSet, _deps in intraDeps.iteritems():
            for dep, troveTups in _deps.iteritems():
                trovesToGet.extend(troveTups)
        hasTroves = self.troveSource.hasTroves(trovesToGet)
        if isinstance(hasTroves, list):
            hasTroves = dict(itertools.izip(trovesToGet, hasTroves))

        results = {}
        for depSet, _deps in intraDeps.iteritems():
            d = {}
            results[depSet] = d
            for dep, troveTups in _deps.iteritems():
                d[dep] = [ x for x in troveTups if hasTroves[x] ]
        return results

    def resolveDependencies(self):
        sugg = ResolutionMesh.resolveDependencies(self)
        intraDepSuggs = self._resolveIntraTroveDeps(self.intraDeps)
        for depSet, intraDeps in self.intraDeps.iteritems():
            for idx, (depClass, dep) in enumerate(depSet.iterDeps(sort=True)):
                if depClass.tag == deps.DEP_CLASS_TROVES:
                    if (dep in intraDepSuggs[depSet]
                        and intraDepSuggs[depSet][dep]):
                        sugg[depSet][idx] = intraDepSuggs[depSet][dep]
        return sugg

    def _getIntraTroveDeps(self, depList):
        suggsByDep = {}
        intraDeps = {}
        for troveTup, depSet in depList:
            pkgName = troveTup[0].split(':', 1)[0]
            for dep in depSet.iterDepsByClass(deps.TroveDependencies):
                if (dep.name.startswith(pkgName) 
                    and dep.name.split(':', 1)[0] == pkgName):
                    troveToGet = (dep.name, troveTup[1], troveTup[2])
                    l = suggsByDep.setdefault(dep, [])
                    l.append(troveToGet)
                    intraDeps.setdefault(depSet, {}).setdefault(dep, l)
        return intraDeps

    def filterDependencies(self, depList):
        if self.removeFileDependencies:
            depList = [(x[0], flavorutil.removeFileDeps(x[1]))
                       for x in depList ]
            return [ x for x in depList if not x[1].isEmpty() ]
        return depList


    def _selectMatchingResolutionTrove(self, requiredBy, dep, depClass,
                                       flavoredList):
        # if all packages are the same and only their flavor score or timestamp
        # is keeping one from being picked over the other, prefer the
        # newly built package.
        builtTroves = []
        resolveTroves = []
        newList = flavoredList
        if self.resolveTroveSource:
            minResolveIdx = len(self.resolveTroveSource.sources)
        ilp = self.cfg.installLabelPath
        for installFlavor, troveTup in flavoredList:
            if self.extraMethod.troveSource.hasTrove(*troveTup):
                branch = troveTup[1].branch()
                if branch.hasParentBranch():
                    label = branch.parentBranch().label()
                else:
                    label = branch.label()
                list = builtTroves
            elif (self.resolveTroveSource
                  and self.resolveTroveSource.hasTrove(*troveTup)):
                # if a package is both in the resolveTroves list
                # and found via ILP, it might be in this list even
                # though it was not found via resolveTroves.  So we
                # limit results to ones found as early as possible
                # in the resolveTroves list
                for resolveIdx, source in enumerate(self.resolveTroveSource.sources):
                    if source.hasTrove(*troveTup):
                        if resolveIdx < minResolveIdx:
                            resolveTroves = []
                            minResolveIdx = resolveIdx
                        break
                if resolveIdx > minResolveIdx:
                    continue
                list = resolveTroves
                label = troveTup[1].trailingLabel()
            else:
                continue

            if label in ilp:
                index = ilp.index(label)
            else:
                index = len(ilp)
            list.append((index, (installFlavor, troveTup)))

        if builtTroves:
            minIndex = sorted(builtTroves, key=lambda x: x[0])[0][0]
            newList = [ x[1] for x in builtTroves if x[0] == minIndex ]
        elif resolveTroves:
            minIndex = sorted(resolveTroves, key=lambda x: x[0])[0][0]
            newList = [ x[1] for x in resolveTroves if x[0] == minIndex ]
        return ResolutionMesh._selectMatchingResolutionTrove(self, requiredBy,
                                                             dep,
                                                             depClass, newList)
