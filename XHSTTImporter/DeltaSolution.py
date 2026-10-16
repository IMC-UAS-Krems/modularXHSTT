import sys
sys.path.append('XHSTTImporter')
from Instance import Instance

class DeltaSolution:

    def __init__(self, instance: Instance, solution: dict = None, relevantResources: set = None, relevantEventResources: set = None,
                 relevantEvents: set = None, relevantEventGroups: set = None, relevantTimes: set = None, 
                 relevantTimeGroups: set = None, relevantConstraints: dict = None):
        self.instance = instance
        if solution is None:
            self.solution = dict()
        else:
            self.solution = solution
        if relevantResources is None:
            self.relevantResources = set()
        else:
            self.relevantResources = relevantResources
        if relevantEvents is None:
            self.relevantEvents = set()
        else:
            self.relevantEvents = relevantEvents
        if relevantEventGroups is None:
            self.relevantEventGroups = set()
        else:
            self.relevantEventGroups = relevantEventGroups
        if relevantEventResources is None:
            self.relevantEventResources = set()
        else:
            self.relevantEventResources = relevantEventResources

        if relevantTimes is None:
            self.relevantTimes = set()
        else:
            self.relevantTimes = relevantTimes
        if relevantTimeGroups is None:
            self.relevantTimeGroups = set()
        else:
            self.relevantTimeGroups = relevantTimeGroups
        if relevantConstraints is None:
            self.relevantConstraints = dict()
        else:
            self.relevantConstraints = relevantConstraints

    def addRelevantTimesAndTimeGroupsBasedOnTimeSet(self, addedTimes):
        self.relevantTimes.update(addedTimes)
        for time in addedTimes:
            self.relevantTimeGroups.update(set(self.instance.Times.IndividualTimes[time].TimeGroups))
            self.relevantTimeGroups.add(self.instance.Times.IndividualTimes[time].Day)

    def setRelevantConstraints(self, relevantConstraintList):
        for constraint in relevantConstraintList:
            self.relevantConstraints.setdefault(constraint[0], list()).append(constraint[1])
