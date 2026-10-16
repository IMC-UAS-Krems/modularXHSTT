import copy
from prettytable import PrettyTable
import uuid
import time as timer
import math
import sys
sys.path.append('XHSTTImporter')
from Instance import Instance
sys.path.append('XHSTTImporter/Constants')
import XHSTTFileConstants
import XHSTTConstraintConstants
sys.path.append('SolutionExporter')
import SolutionDataConstants
sys.path.append('ILP_solver')
import ILPConstants
sys.path.append('validator')
sys.path.append('../validator')
from validator import DeltaEvaluator
from itertools import product

class HeuristicSolutionGenerator:
    def __init__(self, instance: Instance, partial_solution=None, output=False):
        self.timeMeasurementDict = dict()
        self.output = output
        ignoreSoftStudentChoiceConstraints = False
        self.instance = instance
        self.infeasible_events = set()
        self.allTimes = list(self.instance.Times.IndividualTimes.keys())
        self.unavailableTimesByEventCache = dict()
        self.timesAffectedByIteration = set()
        self.fixedResourcesCache = dict()
        self.timeIndicesCache = dict()
        self.flexibilityScoreCache = dict()
        self.intersectingTimeSlotsCache = dict()
        self.timeToUnavailableResourcesDict = self.create_time_to_unavailable_resources_dict()
        self.eventToLinkedEventsDict = self.create_event_to_linked_event_dict()
        self.resourceToStudentChoiceConstraintsDict = self.create_resource_to_student_choice_constraints(ignoreSoft=ignoreSoftStudentChoiceConstraints)
        self.eventToStudentChoiceConstraintsDict = self.create_event_to_student_choice_constraints(ignoreSoft=ignoreSoftStudentChoiceConstraints)
        self.studentChoiceResourcePairToPossibleEvents = self.create_student_choice_resource_pair_to_possible_events(ignoreSoft=ignoreSoftStudentChoiceConstraints, partial_solution=partial_solution)
        self.studentChoiceResourcePairToPossibleEventGroups = self.create_student_choice_resource_pair_to_possible_event_groups(ignoreSoft=ignoreSoftStudentChoiceConstraints, partial_solution=partial_solution)
        self.excludedStudentChoices = dict()
        self.originalStudentChoiceResourcePairToPossibleEvents = copy.deepcopy(self.studentChoiceResourcePairToPossibleEvents)
        self.originalStudentChoiceResourcePairToPossibleEventGroups = copy.deepcopy(
            self.studentChoiceResourcePairToPossibleEventGroups)
        self.eventsWithStudentAssignments = self.get_events_with_student_assignments()
        self.studentChoiceIdToMinChoices = self.create_student_choice_id_to_min_choices()
        self.eventToBalanceClassSizeConstraintsDict = self.create_event_to_balance_class_constraints()
        self.eventToAssignedResourceConstraintsDict = self.create_event_to_assigned_resource_constraints()
        self.eventToSplitEventsDict = self.create_event_to_split_events_constraints()
        self.eventToDistributeSplitEventsDict = self.create_event_to_distribute_split_events_constraints()
        self.unscheduledEvents = self.create_split_events(partial_solution=partial_solution)
        self.originalPossibleTimes = self.create_original_possible_times()
        self.eventToEventGroups = self.create_event_to_relevant_event_groups_dict()
        self.eventGroupPossibleTimes = self.create_event_group_to_possible_time_dict()
        self.scheduledEvents = dict()
        # used to reset solution
        self.unscheduledEventsCopy = copy.deepcopy(self.unscheduledEvents)
        self.subeventSplitSolution = self.create_split_solution()
        self.deltaEvaluator = DeltaEvaluator(self.instance, self.subeventSplitSolution)

    def get_split_solution(self):
        return self.subeventSplitSolution
    def generate_heuristic_solution(self):
        start = timer.time()
        self.unscheduledEvents = copy.deepcopy(self.unscheduledEventsCopy)
        self.deltaEvaluator = DeltaEvaluator(self.instance, self.subeventSplitSolution)
        completedResources = set()
        self.timeMeasurementDict.setdefault("getNextResourceTime", 0)
        getNextTime = timer.time()
        usedStrategy = "leastRemaining"
        currentResourceToSchedule = self.get_next_resource_to_schedule(completedResources, strategy=usedStrategy)
        self.timeMeasurementDict["getNextResourceTime"] += timer.time() - getNextTime
        while currentResourceToSchedule is not None:
            self.create_schedule_for_resource(currentResourceToSchedule)
            completedResources.add(currentResourceToSchedule)
            getNextTime = timer.time()
            currentResourceToSchedule = self.get_next_resource_to_schedule(completedResources, strategy=usedStrategy)
            self.timeMeasurementDict["getNextResourceTime"] += timer.time() - getNextTime
        self.timeMeasurementDict["Total"] = timer.time() - start
        for event in self.unscheduledEvents:
            for subevent in self.unscheduledEvents[event]:
                if not self.scheduledEvents[event][subevent]:
                    self.timesAffectedByIteration = set()
                    startGetNext = timer.time()
                    self.timeMeasurementDict.setdefault("GetNext", 0)
                    self.timeMeasurementDict["GetNext"] += timer.time() - startGetNext
                    startTimeAssignment = timer.time()
                    self.assign_time_to_event(event, "No_resource", {})
                    self.timeMeasurementDict.setdefault("TimeAssignment", 0)
                    self.timeMeasurementDict["TimeAssignment"] += timer.time() - startTimeAssignment
                    startResourceAssignment = timer.time()
                    self.assign_resources_to_event(event)
                    self.timeMeasurementDict.setdefault("ResourceAssignment", 0)
                    self.timeMeasurementDict["ResourceAssignment"] += timer.time() - startResourceAssignment
                    startUpdatePossibleTimes = timer.time()
                    self.update_possible_times_for_all_events()
                    self.timeMeasurementDict.setdefault("UpdatePossibleTimes", 0)
                    self.timeMeasurementDict["UpdatePossibleTimes"] += timer.time() - startUpdatePossibleTimes
                    self.schedule_all_events_with_only_one_remaining_time_slot()
        remainingStuffTimes = timer.time()
        # This may introduce a clash if we force student assignments to events with fixed time slots (usually we would unassign the time but that is impossible in that case)
        self.fulfill_remaining_student_choices()
        self.timeMeasurementDict.setdefault("RemainingStuffTimes", 0)
        self.timeMeasurementDict["RemainingStuffTimes"] += timer.time() - remainingStuffTimes
        self.set_assigned_times_and_resources_accordingly()
        return self.deltaEvaluator.get_current_solution()

    def set_assigned_times_and_resources_accordingly(self):
        current_solution = self.deltaEvaluator.get_current_solution()
        for event in self.instance.Events.IndividualEvents.keys():
            assignedTime = self.instance.Events.IndividualEvents[event].Time
            if assignedTime is not None:
                eventDuration = int(self.instance.Events.IndividualEvents[event].Duration)
                subevent = (eventDuration, 0)
                lastTimeAssignment = current_solution[XHSTTFileConstants.EVENTS][(event, subevent)][XHSTTFileConstants.TIME]
                if lastTimeAssignment == assignedTime:
                    continue
                else:
                    indexOfTime = self.allTimes.index(assignedTime)
                    usedTimeSlots = set(self.allTimes[indexOfTime: indexOfTime + eventDuration])
                    if lastTimeAssignment is not None and lastTimeAssignment != ILPConstants.DUMMY_TIME:
                        indexOfTime = self.allTimes.index(lastTimeAssignment)
                        previousUsedTimeSlots = set(self.allTimes[indexOfTime: indexOfTime + eventDuration])
                    else:
                        previousUsedTimeSlots = set()
                    self.deltaEvaluator.assign_new_time_to_event((event, subevent), previousUsedTimeSlots, usedTimeSlots,
                                                             [])
                    current_solution[XHSTTFileConstants.EVENTS][(event, subevent)][XHSTTFileConstants.TIME] = assignedTime

            subevents = set(self.unscheduledEvents[event].keys())
            subevents.update(self.scheduledEvents[event].keys())
            for subevent in subevents:
                for assignedResource in self.instance.Events.IndividualEvents[event].EventResources.AssignedResources:
                    lastResourceAssignment = current_solution[XHSTTFileConstants.EVENTS][(event, subevent)][XHSTTFileConstants.RESOURCES][assignedResource.Role]
                    if lastResourceAssignment == assignedResource.Reference:
                        continue
                    self.deltaEvaluator.assign_new_resource_to_event((event, subevent), lastResourceAssignment, assignedResource.Reference)
                    current_solution[XHSTTFileConstants.EVENTS][(event, subevent)][XHSTTFileConstants.RESOURCES][assignedResource.Role] = assignedResource.Reference

    def fulfill_remaining_student_choices(self):
        eventGroupSetToResources = dict()
        resourceToHardUnavailableTimes = dict()
        for event in self.instance.Events.IndividualEvents.keys():
            if self.instance.Events.IndividualEvents[event].Time is None:
                continue
            startTimeIndex = list(self.instance.Times.IndividualTimes).index(self.instance.Events.IndividualEvents[event].Time)
            affectedTimes = list(self.instance.Times.IndividualTimes)[startTimeIndex:startTimeIndex + self.instance.Events.IndividualEvents[event].Duration]
            firstSubevent = list(self.unscheduledEvents[event].keys())[0]
            assignedStudentResources = {list(self.unscheduledEvents[event][firstSubevent]["PossibleResources"][role])[0]
                                        for role in
                                        self.unscheduledEvents[event][firstSubevent]["PossibleResources"].keys() if len(
                    self.unscheduledEvents[event][firstSubevent]["PossibleResources"][role]) == 1}
            for resource in assignedStudentResources:
                resourceToHardUnavailableTimes.setdefault(resource, set()).update(affectedTimes)

        for constraintID, resource in self.originalStudentChoiceResourcePairToPossibleEventGroups.keys():
            for eventGroup in self.originalStudentChoiceResourcePairToPossibleEventGroups[constraintID, resource]:
                for event in self.instance.Events.EventGroups[eventGroup].Events:
                    if self.instance.Events.IndividualEvents[event].Time is None:
                        continue
                    firstSubevent = list(self.unscheduledEvents[event].keys())[0]
                    assignedStudentResources = {
                        list(self.unscheduledEvents[event][firstSubevent]["PossibleResources"][role])[0] for role in
                        self.unscheduledEvents[event][firstSubevent]["PossibleResources"].keys() if len(
                            self.unscheduledEvents[event][firstSubevent]["PossibleResources"][role]) == 1}
                    if resource in assignedStudentResources:
                        continue
                    startTimeIndex = list(self.instance.Times.IndividualTimes).index(
                        self.instance.Events.IndividualEvents[event].Time)
                    affectedTimes = list(self.instance.Times.IndividualTimes)[
                                    startTimeIndex:startTimeIndex + self.instance.Events.IndividualEvents[
                                        event].Duration]
                    if resource not in resourceToHardUnavailableTimes:
                        continue
                    if len(resourceToHardUnavailableTimes[resource].intersection(set(affectedTimes))) > 0:
                        self.excludedStudentChoices.setdefault(resource, set())
                        self.excludedStudentChoices[resource].add(eventGroup)
        for constraintID, resource in self.studentChoiceResourcePairToPossibleEventGroups.keys():
            numberEventGroupsAssigned = 0
            assignedEventGroups = set()
            for eventGroup in self.studentChoiceResourcePairToPossibleEventGroups[constraintID, resource]:
                for event in self.instance.Events.EventGroups[eventGroup].Events:
                    firstSubevent = list(self.unscheduledEvents[event].keys())[0]
                    assignedStudentResources = {list(self.unscheduledEvents[event][firstSubevent]["PossibleResources"][role])[0] for role in self.unscheduledEvents[event][firstSubevent]["PossibleResources"].keys() if len(
                        self.unscheduledEvents[event][firstSubevent]["PossibleResources"][role]) == 1}
                    if resource in assignedStudentResources:
                        numberEventGroupsAssigned += 1
                        assignedEventGroups.add(eventGroup)
                        break
            if numberEventGroupsAssigned < self.studentChoiceIdToMinChoices[constraintID]:
                originalPossibleEventGroups = self.originalStudentChoiceResourcePairToPossibleEventGroups[constraintID, resource]
                if resource in self.excludedStudentChoices:
                    originalPossibleEventsWithoutExcludedEvents = originalPossibleEventGroups - self.excludedStudentChoices[resource]
                else:
                    originalPossibleEventsWithoutExcludedEvents = originalPossibleEventGroups
                if len(originalPossibleEventsWithoutExcludedEvents) == 0:
                    continue
                originalPossibleEventsWithoutExcludedEventsFrozenSet = frozenset(originalPossibleEventsWithoutExcludedEvents)
                eventGroupSetToResources.setdefault(originalPossibleEventsWithoutExcludedEventsFrozenSet, set())
                eventGroupSetToResources[originalPossibleEventsWithoutExcludedEventsFrozenSet].add(resource)

        for eventGroupSet in eventGroupSetToResources.keys():
            for eventGroup in eventGroupSet:
                for event in self.instance.Events.EventGroups[eventGroup].Events:
                    firstSubevent = list(self.unscheduledEvents[event].keys())[0]
                    assignedStudentResources = {list(self.unscheduledEvents[event][firstSubevent]["PossibleResources"][role])[0] for role in self.unscheduledEvents[event][firstSubevent]["PossibleResources"].keys() if len(
                        self.unscheduledEvents[event][firstSubevent]["PossibleResources"][role]) == 1}
                    eventGroupSetToResources[eventGroupSet] = eventGroupSetToResources[eventGroupSet] - assignedStudentResources
            resourcesToAllocate = set(eventGroupSetToResources[eventGroupSet])
            eventGroupToSpaceDict = dict()
            for eventGroup in eventGroupSet:
                firstEventInEventGroup = self.instance.Events.EventGroups[eventGroup].Events[0]
                studentResourcesOfEvent = {resource.Role for resource in
                                           self.instance.Events.IndividualEvents[firstEventInEventGroup
                                               ].EventResources.UnassignedResources if
                                           resource.ResourceType == XHSTTFileConstants.STUDENT}
                firstSubevent = list(self.unscheduledEvents[firstEventInEventGroup].keys())[0]
                unassignedStudentResources = {role for role in studentResourcesOfEvent if len(
                    self.unscheduledEvents[firstEventInEventGroup][firstSubevent]["PossibleResources"][role]) > 1}
                eventGroupToSpaceDict[eventGroup] = len(unassignedStudentResources)
            sortedEventGroups = sorted(eventGroupToSpaceDict.keys(), key=lambda x: (eventGroupToSpaceDict[x], -len(x)), reverse=True)
            totalAssignedResourcesCounter = 0
            for eventGroup in sortedEventGroups:
                if totalAssignedResourcesCounter >= len(eventGroupSetToResources[eventGroupSet]) or len(resourcesToAllocate) == 0:
                    break
                firstEventInEventGroup = self.instance.Events.EventGroups[eventGroup].Events[0]
                studentResourcesOfEvent = {resource.Role for resource in
                                           self.instance.Events.IndividualEvents[firstEventInEventGroup
                                               ].EventResources.UnassignedResources if
                                           resource.ResourceType == XHSTTFileConstants.STUDENT}
                firstSubevent = list(self.unscheduledEvents[firstEventInEventGroup].keys())[0]
                unassignedStudentResources = {role for role in studentResourcesOfEvent if len(
                    self.unscheduledEvents[firstEventInEventGroup][firstSubevent]["PossibleResources"][role]) > 1}
                currentSpace = len(unassignedStudentResources)
                while currentSpace > 0:
                    if totalAssignedResourcesCounter >= len(eventGroupSetToResources[eventGroupSet]) or len(resourcesToAllocate) == 0:
                        break
                    nextResourceToAssign = list(resourcesToAllocate)[0]
                    resourcesToAllocate.remove(nextResourceToAssign)
                    self.assign_student_resource_to_event_group_with_multiple_student_roles(eventGroup, nextResourceToAssign)
                    firstEventInEventGroup = self.instance.Events.EventGroups[eventGroup].Events[0]
                    studentResourcesOfEvent = {resource.Role for resource in
                                               self.instance.Events.IndividualEvents[firstEventInEventGroup
                                               ].EventResources.UnassignedResources if
                                               resource.ResourceType == XHSTTFileConstants.STUDENT}
                    firstSubevent = list(self.unscheduledEvents[firstEventInEventGroup].keys())[0]
                    unassignedStudentResources = {role for role in studentResourcesOfEvent if len(
                        self.unscheduledEvents[firstEventInEventGroup][firstSubevent]["PossibleResources"][role]) > 1}
                    currentSpace = len(unassignedStudentResources)
                    for eventGroup2 in eventGroupSet:
                        for event in self.instance.Events.EventGroups[eventGroup2].Events:
                            firstSubevent = list(self.unscheduledEvents[event].keys())[0]
                            assignedStudentResources = {
                                list(self.unscheduledEvents[event][firstSubevent]["PossibleResources"][role])[0] for
                                role in self.unscheduledEvents[event][firstSubevent]["PossibleResources"].keys() if len(
                                    self.unscheduledEvents[event][firstSubevent]["PossibleResources"][role]) == 1}
                            resourcesToAllocate = resourcesToAllocate - assignedStudentResources
    def create_time_to_unavailable_resources_dict(self) -> dict:
        self.timeToUnavailableResourcesDict = dict()
        for time in self.instance.Times.IndividualTimes.keys():
            self.timeToUnavailableResourcesDict[time] = set()
        for constraint in self.instance.Constraints[XHSTTConstraintConstants.AVOID_UNAVAILABLE_TIMES_CONSTRAINT]:
            if not constraint[XHSTTConstraintConstants.REQUIRED]:
                continue
            constraintResources = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCES])
            for resourceGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCE_GROUPS]:
                for resourceType in self.instance.Resources.ResourceGroupsByType.keys():
                    if resourceGroup in self.instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups:
                        constraintResources.update(
                            set(self.instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups[
                                    resourceGroup].Resources))
            if XHSTTFileConstants.TIMES in constraint.keys():
                constraintTimes = set(constraint[XHSTTFileConstants.TIMES])
            else:
                constraintTimes = set()
            if XHSTTFileConstants.TIME_GROUPS in constraint.keys():
                for timeGroup in constraint[XHSTTFileConstants.TIME_GROUPS]:
                    if timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT] in self.instance.Times.TimeGroups.keys():
                        constraintTimes.update(
                            set(self.instance.Times.TimeGroups[timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]].Times))
                    elif timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT] in self.instance.Times.Days.keys():
                        constraintTimes.update(
                            set(self.instance.Times.Days[timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]].Times))
            for time in constraintTimes:
                self.timeToUnavailableResourcesDict[time].update(constraintResources)
        # These are basically avoid unavailable times constraints
        for constraint in self.instance.Constraints[XHSTTConstraintConstants.LIMIT_BUSY_TIMES_CONSTRAINT]:
            if not constraint[XHSTTConstraintConstants.REQUIRED] or int(constraint[XHSTTConstraintConstants.MAXIMUM]) != 0:
                continue
            constraintResources = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCES])
            for resourceGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCE_GROUPS]:
                for resourceType in self.instance.Resources.ResourceGroupsByType.keys():
                    if resourceGroup in self.instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups:
                        constraintResources.update(
                            set(self.instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups[
                                    resourceGroup].Resources))
            constraintTimes = set()
            for timeGroup in constraint[XHSTTFileConstants.TIME_GROUPS]:
                if timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT] in self.instance.Times.TimeGroups.keys():
                    constraintTimes.update(
                        set(self.instance.Times.TimeGroups[timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]].Times))
                elif timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT] in self.instance.Times.Days.keys():
                    constraintTimes.update(
                        set(self.instance.Times.Days[timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]].Times))

            for time in constraintTimes:
                self.timeToUnavailableResourcesDict[time].update(constraintResources)
        # This will be taken care of later automatically
        return self.timeToUnavailableResourcesDict

    def create_event_to_relevant_event_groups_dict(self) -> dict:
        eventToRelevantEventGroups = dict()
        for event in self.instance.Events.IndividualEvents.keys():
            eventToRelevantEventGroups[event] = set()
        if XHSTTConstraintConstants.STUDENT_CHOICE_CONSTRAINT not in self.instance.Constraints:
            return eventToRelevantEventGroups
        for constraint in self.instance.Constraints[XHSTTConstraintConstants.STUDENT_CHOICE_CONSTRAINT]:
            for eventGroup in constraint[XHSTTFileConstants.EVENT_GROUPS]:
                for event in self.instance.Events.EventGroups[eventGroup].Events:
                    eventToRelevantEventGroups[event].add(eventGroup)
        return eventToRelevantEventGroups
    def create_event_group_to_possible_time_dict(self) -> dict:
        relevantEventGroups = set()
        for event in self.eventToEventGroups.keys():
            relevantEventGroups.update(self.eventToEventGroups[event])
        eventGroupToPossibleTimesDict = dict()
        for eventGroup in relevantEventGroups:
            possibleTimesPerSubvent = dict()
            for event in self.instance.Events.EventGroups[eventGroup].Events:
                for subevent in self.unscheduledEvents[event].keys():
                    possibleTimesPerSubvent.setdefault(subevent, list()).append(self.unscheduledEvents[event][subevent]["PossibleTimes"])
            for subevent in possibleTimesPerSubvent:
                possibleTimesPerSubvent[subevent] = set.intersection(*possibleTimesPerSubvent[subevent])
            eventGroupToPossibleTimesDict[eventGroup] = possibleTimesPerSubvent
        return eventGroupToPossibleTimesDict
    def create_original_possible_times(self) -> dict:
        originalPossibleTimes = dict()
        for event in self.instance.Events.IndividualEvents.keys():
            originalPossibleTimes[event] = dict()
            for subevent in self.unscheduledEvents[event].keys():
                originalPossibleTimes[event][subevent] = set(self.unscheduledEvents[event][subevent]["PossibleTimes"])
        return originalPossibleTimes
    def create_split_events(self, partial_solution=None) -> dict:
        split_events = self.create_split_events_subroutine(treatSoftConstraintsAsHard=True, treatHardConstraintsAsHard=True, partial_solution=partial_solution)
        if split_events is None:
            split_events = self.create_split_events_subroutine(treatSoftConstraintsAsHard=False,
                                                               treatHardConstraintsAsHard=True, partial_solution=partial_solution)
        if split_events is None:
            split_events = self.create_split_events_subroutine(treatSoftConstraintsAsHard=False,
                                                               treatHardConstraintsAsHard=False, partial_solution=partial_solution)
        return split_events
    def create_split_events_subroutine(self, treatSoftConstraintsAsHard=True, treatHardConstraintsAsHard=True, partial_solution=None) -> dict:
        unscheduledEvents = dict()
        eventToPossibleSubeventsByDurationDict = dict()

        if partial_solution is not None:
            for event in partial_solution[XHSTTFileConstants.EVENTS].keys():
                event_id = event[0]
                subevent = event[1]
                unscheduledEvents.setdefault(event[0], dict())
                solutionEvent = partial_solution[XHSTTFileConstants.EVENTS][event]
                unscheduledEvents[event[0]][subevent] = dict()
                if solutionEvent[XHSTTFileConstants.TIME] is not None and solutionEvent[XHSTTFileConstants.TIME] != ILPConstants.DUMMY_TIME:
                    unscheduledEvents[event_id][subevent]["PossibleTimes"] = {solutionEvent[XHSTTFileConstants.TIME]}
                elif solutionEvent[XHSTTFileConstants.TIME] == ILPConstants.DUMMY_TIME:
                    unscheduledEvents[event_id][subevent]["PossibleTimes"] = set()
                else:
                    if self.instance.Events.IndividualEvents[event_id].Time is None:
                        unscheduledEvents[event_id][subevent]["PossibleTimes"] = set(
                            self.instance.Times.IndividualTimes.keys())
                    else:
                        unscheduledEvents[event_id][subevent]["PossibleTimes"] = {self.instance.Events.IndividualEvents[event_id].Time}
                unscheduledEvents[event_id][subevent]["PossibleResources"] = dict()
                assignedResourceRoles = [role.Role for role in self.instance.Events.IndividualEvents[event_id].EventResources.AssignedResources]
                roleToResourceDict = dict()
                for assignedResource in self.instance.Events.IndividualEvents[event_id].EventResources.AssignedResources:
                    roleToResourceDict[assignedResource.Role] = assignedResource.Reference
                roleToResourceType = dict()
                for unassignedResource in self.instance.Events.IndividualEvents[event_id].EventResources.UnassignedResources:
                    roleToResourceType[unassignedResource.Role] = unassignedResource.ResourceType
                for role in solutionEvent[XHSTTFileConstants.RESOURCES].keys():
                    if solutionEvent[XHSTTFileConstants.RESOURCES][role] is not None and solutionEvent[XHSTTFileConstants.RESOURCES][role] != ILPConstants.DUMMY_RESOURCE:
                        unscheduledEvents[event_id][subevent]["PossibleResources"][role] = {solutionEvent[XHSTTFileConstants.RESOURCES][role]}
                    elif solutionEvent[XHSTTFileConstants.RESOURCES][role] == ILPConstants.DUMMY_RESOURCE:
                        unscheduledEvents[event_id][subevent]["PossibleResources"][role] = set()
                    else:
                        if role in assignedResourceRoles:
                            unscheduledEvents[event_id][subevent]["PossibleResources"][role] = {roleToResourceDict[role]}
                        else:
                            unscheduledEvents[event_id][subevent]["PossibleResources"][role] = {resource
                                                                                                              for
                                                                                                              resource
                                                                                                              in
                                                                                                              self.instance.Resources.IndividualResources.keys()
                                                                                                              if
                                                                                                              self.instance.Resources.IndividualResources[
                                                                                                                  resource].Type == roleToResourceType[role]}

                            hardAssignResourceConstraintsForRole = list()
                            for constraint in self.instance.Constraints[
                                XHSTTConstraintConstants.ASSIGN_RESOURCE_CONSTRAINT]:
                                if event_id in constraint[XHSTTConstraintConstants.APPLIES_TO][
                                    XHSTTFileConstants.EVENTS] \
                                        and constraint[XHSTTConstraintConstants.REQUIRED] and constraint[
                                    XHSTTConstraintConstants.ROLE] == roleToResourceType[role]:
                                    hardAssignResourceConstraintsForRole.append(constraint)

        for event in self.instance.Events.IndividualEvents.keys():
            if event in unscheduledEvents:
                continue
            for ar in self.instance.Events.IndividualEvents[event].EventResources.AssignedResources:
                if ar.Role is None:
                    ar.Role = "NoRole" + str(uuid.uuid4())
        fixed_events = list()
        for event_id in self.instance.Events.IndividualEvents.keys():
            if event_id in unscheduledEvents:
                continue
            event = self.instance.Events.IndividualEvents[event_id]
            eventToPossibleSubeventsByDurationDict.setdefault(event_id, dict())
            if event.Time is not None:
                eventToPossibleSubeventsByDurationDict[event_id][int(event.Duration)] = (1, 1)
                fixed_events.append(event_id)
                for duration in range(1, int(event.Duration)):
                    eventToPossibleSubeventsByDurationDict[event_id][duration] = (0, 0)

        restricted_events = list()
        for constraint in self.instance.Constraints[XHSTTConstraintConstants.SPLIT_EVENTS_CONSTRAINT]:
            events = constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS]
            for event_group in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
                events += self.instance.Events.EventGroups[event_group].Events
            if not treatHardConstraintsAsHard:
                continue
            if not constraint[XHSTTConstraintConstants.REQUIRED] and not treatSoftConstraintsAsHard:
                continue
            for event_id in events:
                if event_id in unscheduledEvents:
                    continue
                restricted_events.append(event_id)
                event = self.instance.Events.IndividualEvents[event_id]
                if event_id in fixed_events:
                    continue
                eventToPossibleSubeventsByDurationDict.setdefault(event_id, dict())
                for duration in range(1, int(constraint[XHSTTConstraintConstants.MAXIMUM_DURATION]) + 1):
                    if (duration >= int(constraint[XHSTTConstraintConstants.MINIMUM_DURATION]) and
                            duration <= int(constraint[XHSTTConstraintConstants.MAXIMUM_DURATION])):
                        # Min amount is not applied to every duration but to the overall event
                        min_amount = 0
                        max_amount = min(int(constraint[XHSTTConstraintConstants.MAXIMUM_AMOUNT]),
                                         int(event.Duration) // duration)
                        if duration not in eventToPossibleSubeventsByDurationDict[event_id].keys():
                            eventToPossibleSubeventsByDurationDict[event_id][duration] = (min_amount, max_amount)
                        else:
                            old_restrictions = eventToPossibleSubeventsByDurationDict[event_id][duration]
                            eventToPossibleSubeventsByDurationDict[event_id][duration] = (
                            max(old_restrictions[0], min_amount), min(old_restrictions[1], max_amount))
                            if eventToPossibleSubeventsByDurationDict[event_id][duration][0] > \
                                    eventToPossibleSubeventsByDurationDict[event_id][duration][1]:
                                eventToPossibleSubeventsByDurationDict[event_id][duration] = (0, 0)
                    else:
                        eventToPossibleSubeventsByDurationDict[event_id][duration] = (0, 0)
        infeasible_events_this_iteration = set()
        for event_id in self.instance.Events.IndividualEvents.keys():
            if event_id in unscheduledEvents:
                continue
            if event_id in fixed_events or event_id in restricted_events:
                continue
            event = self.instance.Events.IndividualEvents[event_id]
            for duration in range(1, 3):
                min_amount = 0
                max_amount = int(event.Duration) // duration
                eventToPossibleSubeventsByDurationDict[event_id][duration] = (min_amount, max_amount)
        for constraint in self.instance.Constraints[XHSTTConstraintConstants.DISTRIBUTE_SPLIT_EVENTS_CONSTRAINT]:
            events = constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS]
            for event_group in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
                events += self.instance.Events.EventGroups[event_group].Events
            for event_id in events:
                if event_id in unscheduledEvents:
                    continue
                if not treatHardConstraintsAsHard and event_id in self.infeasible_events:
                    continue
                if not constraint[
                    XHSTTConstraintConstants.REQUIRED] and not treatSoftConstraintsAsHard and event_id in self.infeasible_events:
                    continue
                eventToPossibleSubeventsByDurationDict.setdefault(event_id, dict())
                duration = int(constraint[XHSTTFileConstants.DURATION])
                min_amount = int(constraint[XHSTTConstraintConstants.MINIMUM])
                max_amount = int(constraint[XHSTTConstraintConstants.MAXIMUM])
                if duration in eventToPossibleSubeventsByDurationDict[event_id]:
                    old_restrictions = eventToPossibleSubeventsByDurationDict[event_id][duration]
                    eventToPossibleSubeventsByDurationDict[event_id][duration] = (
                        max(old_restrictions[0], min_amount), min(old_restrictions[1], max_amount))
                else:
                    eventToPossibleSubeventsByDurationDict[event_id][duration] = (min_amount, max_amount)
                if eventToPossibleSubeventsByDurationDict[event_id][duration][0] > \
                        eventToPossibleSubeventsByDurationDict[event_id][duration][1]:
                    self.infeasible_events.add(event_id)
                    infeasible_events_this_iteration.add(event_id)
                    if self.output:
                        print(f"INFEASIBLE TO FULFILL ALL SPLIT CONSTRAINTS RESTART WITH RELAXED SOFT CONSTRAINTS {event_id}")
        for constraint in self.instance.Constraints[XHSTTConstraintConstants.PREFER_TIMES_CONSTRAINT]:
            events = constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS]
            for event_group in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
                events += self.instance.Events.EventGroups[event_group].Events
            if XHSTTFileConstants.TIMES in constraint.keys():
                constraintTimes = set(constraint[XHSTTFileConstants.TIMES])
                for timeGroup in constraint[XHSTTFileConstants.TIME_GROUPS]:
                    if timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT] in self.instance.Times.TimeGroups.keys():
                        constraintTimes.update(
                            set(self.instance.Times.TimeGroups[timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]].Times))
                    elif timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT] in self.instance.Times.Days.keys():
                        constraintTimes.update(
                            set(self.instance.Times.Days[timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]].Times))
            else:
                constraintTimes = set()
            for event_id in events:
                if event_id in unscheduledEvents:
                    continue
                if not treatHardConstraintsAsHard and event_id in self.infeasible_events:
                    continue
                if not constraint[XHSTTConstraintConstants.REQUIRED] and not treatSoftConstraintsAsHard and event_id in self.infeasible_events:
                    continue
                if XHSTTFileConstants.DURATION not in constraint:
                    durations = [1, 2]
                else:
                    durations = [int(constraint[XHSTTFileConstants.DURATION])]
                for duration in durations:
                    min_amount = 0
                    max_amount = len(constraintTimes)
                    eventToPossibleSubeventsByDurationDict.setdefault(event_id, dict())
                    if duration in eventToPossibleSubeventsByDurationDict[event_id]:
                        old_restrictions = eventToPossibleSubeventsByDurationDict[event_id][duration]
                        eventToPossibleSubeventsByDurationDict[event_id][duration] = (
                            max(old_restrictions[0], min_amount), min(old_restrictions[1], max_amount))
                    else:
                        continue
                    if eventToPossibleSubeventsByDurationDict[event_id][duration][0] > \
                            eventToPossibleSubeventsByDurationDict[event_id][duration][1]:
                        self.infeasible_events.add(event_id)
                        infeasible_events_this_iteration.add(event_id)
                        if self.output:
                            print(f"INFEASIBLE TO FULFILL ALL PREFER CONSTRAINTS RESTART WITH RELAXED SOFT CONSTRAINTS {event_id}")
        if len(infeasible_events_this_iteration) > 0:
            return None
        optimalSubeventDistributions = self.find_optimal_subevent_distributions(eventToPossibleSubeventsByDurationDict, considerSoftConstraints=not treatSoftConstraintsAsHard, considerHardConstraints=not treatHardConstraintsAsHard)
        if optimalSubeventDistributions is None:
            return None
        for event_id in self.instance.Events.IndividualEvents.keys():
            if event_id in unscheduledEvents:
                continue
            unscheduledEvents[event_id] = dict()
            subEventDurations = sorted(optimalSubeventDistributions[event_id])
            subeventIndex = 0
            for subeventDurationIndex in range(len(subEventDurations)):
                if subeventDurationIndex == 0 or subEventDurations[subeventDurationIndex] != subEventDurations[
                    subeventDurationIndex - 1]:
                    subeventIndex = 0
                subevent = (subEventDurations[subeventDurationIndex], subeventIndex)
                unscheduledEvents[event_id][subevent] = dict()
                # Initialize Time and Resources with all possiblites. They will later be refined
                if self.instance.Events.IndividualEvents[event_id].Time is None:
                    unscheduledEvents[event_id][subevent]["PossibleTimes"] = set(self.instance.Times.IndividualTimes.keys())
                else:
                    unscheduledEvents[event_id][subevent]["PossibleTimes"] = {self.instance.Events.IndividualEvents[event_id].Time}
                unscheduledEvents[event_id][subevent]["PossibleResources"] = dict()
                for eventResource in self.instance.Events.IndividualEvents[event_id].EventResources.UnassignedResources:
                    unscheduledEvents[event_id][subevent]["PossibleResources"][eventResource.Role] = {resource for
                                                                                                      resource in
                                                                                                      self.instance.Resources.IndividualResources.keys()
                                                                                                      if
                                                                                                      self.instance.Resources.IndividualResources[
                                                                                                          resource].Type == eventResource.ResourceType}

                    hardAssignResourceConstraintsForRole = list()
                    for constraint in self.instance.Constraints[XHSTTConstraintConstants.ASSIGN_RESOURCE_CONSTRAINT]:
                        if event_id in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS] \
                                and constraint[XHSTTConstraintConstants.REQUIRED] and constraint[
                            XHSTTConstraintConstants.ROLE] == eventResource.Role:
                            hardAssignResourceConstraintsForRole.append(constraint)
                for eventResource in self.instance.Events.IndividualEvents[event_id].EventResources.AssignedResources:
                    unscheduledEvents[event_id][subevent]["PossibleResources"][eventResource.Role] = {eventResource.Reference}
                subeventIndex += 1
        timepreferencesBySubeventsDict = dict()
        for constraint in self.instance.Constraints[XHSTTConstraintConstants.PREFER_TIMES_CONSTRAINT]:
            if not constraint[XHSTTConstraintConstants.REQUIRED]:
                continue
            consideredEvents = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS])
            for eventGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
                consideredEvents.update(set(self.instance.Events.EventGroups[eventGroup].Events))
            preferedTimes = set(constraint[XHSTTFileConstants.TIMES])
            for timeGroup in constraint[XHSTTFileConstants.TIME_GROUPS]:
                if timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT] in self.instance.Times.TimeGroups.keys():
                    preferedTimes.update(
                        set(self.instance.Times.TimeGroups[timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]].Times))
                elif timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT] in self.instance.Times.Days.keys():
                    preferedTimes.update(
                        set(self.instance.Times.Days[timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]].Times))
            for event_id in consideredEvents:
                for subevent in unscheduledEvents[event_id].keys():
                    if XHSTTFileConstants.DURATION in constraint.keys() and int(constraint[XHSTTFileConstants.DURATION]) != subevent[0]:
                        continue
                    timepreferencesBySubeventsDict.setdefault((event_id, subevent), list())
                    if len(preferedTimes) > 0:
                        timepreferencesBySubeventsDict[(event_id, subevent)].append(preferedTimes)

        resourcepreferencesByRoleDict = dict()
        for constraint in self.instance.Constraints[XHSTTConstraintConstants.PREFER_RESOURCES_CONSTRAINT]:
            if not constraint[XHSTTConstraintConstants.REQUIRED]:
                continue
            role = constraint[XHSTTConstraintConstants.ROLE]
            consideredEvents = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS])
            for eventGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
                consideredEvents.update(set(self.instance.Events.EventGroups[eventGroup].Events))
            preferedResources = set(constraint[XHSTTFileConstants.RESOURCES])
            for resource_group in constraint[XHSTTFileConstants.RESOURCE_GROUPS]:
                for resourceType in self.instance.Resources.ResourceGroupsByType.keys():
                    if resource_group in self.instance.Resources.ResourceGroupsByType[
                        resourceType].ResourceGroups:
                        preferedResources.update(
                            set(self.instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups[
                                    resource_group].Resources))
            for event_id in consideredEvents:
                for subevent in unscheduledEvents[event_id].keys():
                    if role in unscheduledEvents[event_id][subevent]["PossibleResources"].keys():
                        resourcepreferencesByRoleDict.setdefault((event_id, subevent, role), list())
                        resourcepreferencesByRoleDict[(event_id, subevent, role)].append(preferedResources)

        for event_id in self.instance.Events.IndividualEvents.keys():
            for subevent in unscheduledEvents[event_id].keys():
                if (event_id, subevent) in timepreferencesBySubeventsDict:
                    hard_time_preferences_for_event = timepreferencesBySubeventsDict[(event_id, subevent)]
                else:
                    hard_time_preferences_for_event = list()
                if len(unscheduledEvents[event_id][subevent]["PossibleTimes"]) > 0:
                    hard_time_preferences_for_event.append(unscheduledEvents[event_id][subevent]["PossibleTimes"])
                if len(hard_time_preferences_for_event) > 0:
                    times_fulfilling_all_hard_constraints = set.intersection(*hard_time_preferences_for_event)
                else:
                    times_fulfilling_all_hard_constraints = set()
                if len(times_fulfilling_all_hard_constraints) <= subevent[1]:
                    continue
                unscheduledEvents[event_id][subevent]["PossibleTimes"] = times_fulfilling_all_hard_constraints
        for event_id in self.instance.Events.IndividualEvents.keys():
            for subevent in unscheduledEvents[event_id].keys():
                for role in unscheduledEvents[event_id][subevent]["PossibleResources"].keys():
                    if (event_id, subevent, role) in resourcepreferencesByRoleDict:
                        hard_resource_preferences_for_role = resourcepreferencesByRoleDict[(event_id, subevent, role)]
                    else:
                        hard_resource_preferences_for_role = list()
                    hard_resource_preferences_for_role.append(unscheduledEvents[event_id][subevent]["PossibleResources"][role])
                    if len(hard_resource_preferences_for_role) == 0:
                        continue
                    resources_fulfilling_all_hard_constraints = set.intersection(*hard_resource_preferences_for_role)
                    unscheduledEvents[event_id][subevent]["PossibleResources"][role] = resources_fulfilling_all_hard_constraints

        eventSubeventPairsWithFixedTime = set()
        someChangesHappened = True
        while someChangesHappened:
            someChangesHappened = False
            # use timeToUnavailableResources to further reduce set of possible event times
            madeChanges = True
            counter = 0
            while madeChanges:
                counter += 1
                madeChanges = False
                for event_id in self.instance.Events.IndividualEvents.keys():
                    for subevent in unscheduledEvents[event_id].keys():
                        if (event_id, subevent) in eventSubeventPairsWithFixedTime:
                            continue
                        fixed_resources = set()
                        for role in unscheduledEvents[event_id][subevent]["PossibleResources"].keys():
                            if len(unscheduledEvents[event_id][subevent]["PossibleResources"][role]) == 1:
                                if list(unscheduledEvents[event_id][subevent]["PossibleResources"][role])[0] in fixed_resources:
                                    unscheduledEvents[event_id][subevent]["PossibleResources"][role] = {}
                                else:
                                    fixed_resources.update(unscheduledEvents[event_id][subevent]["PossibleResources"][role])
                        removedTimes = set()
                        for time in unscheduledEvents[event_id][subevent]["PossibleTimes"]:
                            if len(fixed_resources.intersection(self.timeToUnavailableResourcesDict[time])) > 0:
                                removedTimes.add(time)
                                unscheduledEvents[event_id][subevent]["PossibleTimes"] = unscheduledEvents[event_id][subevent]["PossibleTimes"] - self.get_timeslots_intersection_based_on_event_length(
                            unscheduledEvents[event_id][subevent]["PossibleTimes"], removedTimes, subevent[0])
                        if len(unscheduledEvents[event_id][subevent]["PossibleTimes"]) == 1:
                            madeChanges = True
                            eventSubeventPairsWithFixedTime.add((event_id, subevent))
                            selectedTime = list(unscheduledEvents[event_id][subevent]["PossibleTimes"])[0]
                            indexOfTime = self.allTimes.index(selectedTime)
                            usedTimeSlots = set(self.allTimes[indexOfTime: indexOfTime + subevent[0]])
                            for time in usedTimeSlots:
                                self.timeToUnavailableResourcesDict[time].update(fixed_resources)
                            chosenDay = [day for day in self.instance.Times.Days.keys() if
                                         selectedTime in self.instance.Times.Days[day].Times][0]

                            for otherSubevent in unscheduledEvents[event_id].keys():
                                if otherSubevent != subevent:
                                    unscheduledEvents[event_id][otherSubevent]["PossibleTimes"] = \
                                        unscheduledEvents[event_id][otherSubevent]["PossibleTimes"] - set(
                                            self.instance.Times.Days[chosenDay].Times)
                if madeChanges:
                    someChangesHappened = True

            madeChangesInIteration = True
            attemptedPairs = set()
            while madeChangesInIteration:
                madeChangesInIteration = False
                for studentChoiceResourcePair in self.studentChoiceResourcePairToPossibleEventGroups.keys():
                    removedEventGroups = set()
                    for eventGroup in self.studentChoiceResourcePairToPossibleEventGroups[studentChoiceResourcePair]:
                        firstEventOfEventGroup = self.instance.Events.EventGroups[eventGroup].Events[0]
                        firstSubevent = list(unscheduledEvents[firstEventOfEventGroup].keys())[0]
                        resourcesOfEvent = {list(unscheduledEvents[firstEventOfEventGroup][firstSubevent]["PossibleResources"][role])[0]
                                            for
                                            role
                                            in
                                            unscheduledEvents[firstEventOfEventGroup][firstSubevent]["PossibleResources"].keys() if
                                            len(unscheduledEvents[firstEventOfEventGroup][firstSubevent]["PossibleResources"][
                                                    role]) == 1}
                        if studentChoiceResourcePair[1] in resourcesOfEvent:
                            continue
                        for event in self.instance.Events.EventGroups[eventGroup].Events:
                            possibleTimeSlotsBySubevent = dict()
                            firstSubevent = list(unscheduledEvents[event].keys())[0]
                            for subevent in unscheduledEvents[event]:
                                removedTimes = {time for time in self.allTimes if
                                                studentChoiceResourcePair[1] in self.timeToUnavailableResourcesDict[time]}
                                removedTimesFrozenSet = frozenset(removedTimes)
                                if (subevent[0], removedTimesFrozenSet) not in self.intersectingTimeSlotsCache.keys():
                                    self.intersectingTimeSlotsCache[(
                                        subevent[0],
                                        removedTimesFrozenSet)] = self.get_timeslots_intersection_based_on_event_length(
                                        set(self.allTimes),
                                        removedTimes,
                                        subevent[0])
                                possibleTimeSlotsBySubevent[subevent] = unscheduledEvents[event][subevent][
                                                                            "PossibleTimes"] - \
                                                                        self.intersectingTimeSlotsCache[
                                                                            (subevent[0], removedTimesFrozenSet)]

                            dummyResourcesOfEvent = {role for
                                                     role
                                                     in
                                                     unscheduledEvents[event][firstSubevent]["PossibleResources"].keys() if
                                                     len(unscheduledEvents[event][firstSubevent]["PossibleResources"][
                                                             role]) > 1}
                            if len(dummyResourcesOfEvent) == 0:
                                removedEventGroups.add(eventGroup)
                                madeChangesInIteration = True
                            if not self.is_event_schedulable(possibleTimeSlotsBySubevent):
                                removedEventGroups.add(eventGroup)
                                madeChangesInIteration = True
                    self.studentChoiceResourcePairToPossibleEventGroups[studentChoiceResourcePair] = \
                    self.studentChoiceResourcePairToPossibleEventGroups[studentChoiceResourcePair] - removedEventGroups
                sortedStudentChoiceResourcePairs = sorted(self.studentChoiceResourcePairToPossibleEventGroups.keys(),
                                                          key=lambda x: len(
                                                              self.studentChoiceResourcePairToPossibleEventGroups[x]))
                for studentChoiceResourcePair in sortedStudentChoiceResourcePairs:
                    resource = studentChoiceResourcePair[1]
                    if studentChoiceResourcePair in attemptedPairs:
                        continue
                    if len(self.studentChoiceResourcePairToPossibleEventGroups[studentChoiceResourcePair]) > \
                            self.studentChoiceIdToMinChoices[studentChoiceResourcePair[0]]:
                        continue
                    unsuccessfulAssignments = set()
                    for eventGroup in self.studentChoiceResourcePairToPossibleEventGroups[studentChoiceResourcePair]:
                        attemptedPairs.add(studentChoiceResourcePair)
                        firstEventOfEventGroup = self.instance.Events.EventGroups[eventGroup].Events[0]
                        firstSubevent = list(unscheduledEvents[firstEventOfEventGroup].keys())[0]
                        if resource in {list(unscheduledEvents[firstEventOfEventGroup][firstSubevent]["PossibleResources"][role])[0] for
                                        role
                                        in
                                        unscheduledEvents[firstEventOfEventGroup][firstSubevent]["PossibleResources"].keys() if
                                        len(unscheduledEvents[firstEventOfEventGroup][firstSubevent]["PossibleResources"][role]) == 1}:
                            continue
                        assignmentSuccessful = self.assign_student_resource_to_event_group_with_multiple_student_roles_before_solution_exists(
                            eventGroup, resource, unscheduledEvents)
                        madeChangesInIteration = True
                        if not assignmentSuccessful:
                            unsuccessfulAssignments.add(eventGroup)
                    for eventGroup in unsuccessfulAssignments:
                        self.studentChoiceResourcePairToPossibleEventGroups[studentChoiceResourcePair].remove(eventGroup)
                if madeChangesInIteration:
                    someChangesHappened = True


        # update possible Times based on linked Events
        for event_id in self.eventToLinkedEventsDict.keys():
            for subevent in unscheduledEvents[event_id].keys():
                possibleTimes = unscheduledEvents[event_id][subevent]["PossibleTimes"]
                for linked_event in self.eventToLinkedEventsDict[event_id]:
                    possibleTimes = possibleTimes.intersection(
                        unscheduledEvents[linked_event][subevent]["PossibleTimes"])
                unscheduledEvents[event_id][subevent]["PossibleTimes"] = possibleTimes
        return unscheduledEvents

    def create_event_to_linked_event_dict(self) -> dict:
        eventToLinkedEventsDict = dict()
        for event_id in self.instance.Events.IndividualEvents.keys():
            eventToLinkedEventsDict[event_id] = set()

        for constraint in self.instance.Constraints[XHSTTConstraintConstants.LINK_EVENTS_CONSTRAINT]:
            for eventGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
                for event_id in self.instance.Events.EventGroups[eventGroup].Events:
                    eventToLinkedEventsDict[event_id].update(self.instance.Events.EventGroups[eventGroup].Events)
        return eventToLinkedEventsDict
    def create_split_solution(self) -> dict:
        solutionEvents = dict()
        subeventSplitSolution = dict()

        for event in self.unscheduledEvents.keys():
            self.scheduledEvents.setdefault(event, dict())
            for subevent in self.unscheduledEvents[event].keys():
                solutionEvents[event, subevent] = dict()
                currently_processed_subevent = solutionEvents[event, subevent]
                currently_processed_subevent[XHSTTFileConstants.DURATION] = subevent[0]
                currently_processed_subevent[XHSTTFileConstants.ID] = (event, subevent)

                if len(self.unscheduledEvents[event][subevent]["PossibleTimes"]) == 1:
                    currently_processed_subevent[XHSTTFileConstants.TIME] = \
                        list(self.unscheduledEvents[event][subevent]["PossibleTimes"])[0]
                    self.scheduledEvents[event][subevent] = True
                else:
                    currently_processed_subevent[XHSTTFileConstants.TIME] = ILPConstants.DUMMY_TIME
                    self.scheduledEvents[event][subevent] = False
                currently_processed_subevent[SolutionDataConstants.DELETE_SUBEVENTS] = False
                currently_processed_subevent[XHSTTFileConstants.NAME] = event
                currently_processed_subevent[XHSTTFileConstants.RESOURCES] = dict()
                for role in self.unscheduledEvents[event][subevent]["PossibleResources"].keys():
                    if len(self.unscheduledEvents[event][subevent]["PossibleResources"][role]) == 1:
                        currently_processed_subevent[XHSTTFileConstants.RESOURCES][role] = \
                            list(self.unscheduledEvents[event][subevent]["PossibleResources"][role])[0]
                    else:
                        currently_processed_subevent[XHSTTFileConstants.RESOURCES][role] = ILPConstants.DUMMY_RESOURCE
        subeventSplitSolution[XHSTTFileConstants.EVENTS] = solutionEvents
        return subeventSplitSolution

    def create_resource_to_student_choice_constraints(self, ignoreSoft=False) -> dict:
        resourceToStudentChoiceConstraintsDict = dict()
        for resource in self.instance.Resources.IndividualResources.keys():
            resourceToStudentChoiceConstraintsDict[resource] = list()

        if XHSTTConstraintConstants.STUDENT_CHOICE_CONSTRAINT in self.instance.Constraints.keys():
            for constraint in self.instance.Constraints[XHSTTConstraintConstants.STUDENT_CHOICE_CONSTRAINT]:
                if not constraint[XHSTTConstraintConstants.REQUIRED] and ignoreSoft:
                    continue
                consideredResources = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCES])
                for resourceGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][
                    XHSTTFileConstants.RESOURCE_GROUPS]:
                    for resourceType in self.instance.Resources.ResourceGroupsByType.keys():
                        if resourceGroup in self.instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups:
                            consideredResources.update(set(
                                self.instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups[
                                    resourceGroup].Resources))
                for resource in consideredResources:
                    resourceToStudentChoiceConstraintsDict[resource].append(constraint)
        return resourceToStudentChoiceConstraintsDict

    def create_student_choice_resource_pair_to_possible_event_groups(self, ignoreSoft=False, partial_solution=None) -> dict:
        studentChoiceResourcePairToPossibleEventGroupsDict = dict()
        resourceToAssignedEventGroups = dict()
        if partial_solution is not None:
            for event in partial_solution[XHSTTFileConstants.EVENTS].keys():
                solutionEvent = partial_solution[XHSTTFileConstants.EVENTS][event]
                event_id = event[0]
                for role in solutionEvent[XHSTTFileConstants.RESOURCES].keys():
                    if solutionEvent[XHSTTFileConstants.RESOURCES][role] is None or \
                            solutionEvent[XHSTTFileConstants.RESOURCES][role] == ILPConstants.DUMMY_RESOURCE:
                        continue
                    resourceToAssignedEventGroups.setdefault(solutionEvent[XHSTTFileConstants.RESOURCES][role], set())
                    for eventGroup in self.instance.Events[event_id].EventGroups:
                        resourceToAssignedEventGroups[solutionEvent[XHSTTFileConstants.RESOURCES][role]].add(eventGroup)

        if XHSTTConstraintConstants.STUDENT_CHOICE_CONSTRAINT in self.instance.Constraints.keys():
            for constraint in self.instance.Constraints[XHSTTConstraintConstants.STUDENT_CHOICE_CONSTRAINT]:
                if not constraint[XHSTTConstraintConstants.REQUIRED] and ignoreSoft:
                    continue
                consideredResources = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCES])
                for resourceGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][
                    XHSTTFileConstants.RESOURCE_GROUPS]:
                    for resourceType in self.instance.Resources.ResourceGroupsByType.keys():
                        if resourceGroup in self.instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups:
                            consideredResources.update(set(
                                self.instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups[
                                    resourceGroup].Resources))
                possibleEventGroups = set()
                for eventGroup in constraint[XHSTTFileConstants.EVENT_GROUPS]:
                    possibleEventGroups.add(eventGroup)
                for resource in consideredResources:
                    if resource in resourceToAssignedEventGroups and len(
                            possibleEventGroups.intersection(resourceToAssignedEventGroups[resource])) > 0:
                        possibleEventGroupsForResource = possibleEventGroups.intersection(resourceToAssignedEventGroups[resource])
                    else:
                        possibleEventGroupsForResource = set(possibleEventGroups)

                    studentChoiceResourcePairToPossibleEventGroupsDict[
                        (constraint[XHSTTConstraintConstants.ID], resource)] = possibleEventGroupsForResource

        return studentChoiceResourcePairToPossibleEventGroupsDict
    def create_student_choice_resource_pair_to_possible_events(self, ignoreSoft=False, partial_solution=None) -> dict:
        studentChoiceResourcePairToPossibleEventsDict = dict()
        resourceToAssignedEvents = dict()
        if partial_solution is not None:
            for event in partial_solution[XHSTTFileConstants.EVENTS].keys():
                solutionEvent = partial_solution[XHSTTFileConstants.EVENTS][event]
                event_id = event[0]
                for role in solutionEvent[XHSTTFileConstants.RESOURCES].keys():
                    if solutionEvent[XHSTTFileConstants.RESOURCES][role] is None or solutionEvent[XHSTTFileConstants.RESOURCES][role] == ILPConstants.DUMMY_RESOURCE:
                        continue
                    resourceToAssignedEvents.setdefault(solutionEvent[XHSTTFileConstants.RESOURCES][role], set()).add(event_id)

        if XHSTTConstraintConstants.STUDENT_CHOICE_CONSTRAINT in self.instance.Constraints.keys():
            for constraint in self.instance.Constraints[XHSTTConstraintConstants.STUDENT_CHOICE_CONSTRAINT]:
                if not constraint[XHSTTConstraintConstants.REQUIRED] and ignoreSoft:
                    continue
                consideredResources = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCES])
                for resourceGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][
                    XHSTTFileConstants.RESOURCE_GROUPS]:
                    for resourceType in self.instance.Resources.ResourceGroupsByType.keys():
                        if resourceGroup in self.instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups:
                            consideredResources.update(set(
                                self.instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups[
                                    resourceGroup].Resources))
                possibleEvents = set()
                for eventGroup in constraint[XHSTTFileConstants.EVENT_GROUPS]:
                    possibleEvents.update(self.instance.Events.EventGroups[eventGroup].Events)
                for resource in consideredResources:
                    if resource in resourceToAssignedEvents and len(possibleEvents.intersection(resourceToAssignedEvents[resource])) > 0:
                        possibleEventsForResource = possibleEvents.intersection(resourceToAssignedEvents[resource])
                    else:
                        possibleEventsForResource = set(possibleEvents)

                    studentChoiceResourcePairToPossibleEventsDict[(constraint[XHSTTConstraintConstants.ID], resource)] = possibleEventsForResource

        return studentChoiceResourcePairToPossibleEventsDict

    def get_events_with_student_assignments(self):
        eventsWithStudentAssignments = set()
        if XHSTTConstraintConstants.STUDENT_CHOICE_CONSTRAINT in self.instance.Constraints.keys():
            for constraint in self.instance.Constraints[XHSTTConstraintConstants.STUDENT_CHOICE_CONSTRAINT]:
                for eventGroup in constraint[XHSTTFileConstants.EVENT_GROUPS]:
                    eventsWithStudentAssignments.update(self.instance.Events.EventGroups[eventGroup].Events)
        return eventsWithStudentAssignments

    def create_student_choice_id_to_min_choices(self):
        constraintIdToMinChoicesDict = dict()
        if XHSTTConstraintConstants.STUDENT_CHOICE_CONSTRAINT in self.instance.Constraints:
            for constraint in self.instance.Constraints[XHSTTConstraintConstants.STUDENT_CHOICE_CONSTRAINT]:
                constraintIdToMinChoicesDict[constraint[XHSTTConstraintConstants.ID]] = int(constraint[XHSTTConstraintConstants.MINIMUM])
        return constraintIdToMinChoicesDict
    def create_event_to_student_choice_constraints(self, ignoreSoft=False) -> dict:
        eventToStudentChoiceConstraintsDict = dict()
        for event in self.instance.Events.IndividualEvents.keys():
            eventToStudentChoiceConstraintsDict[event] = list()

        if XHSTTConstraintConstants.STUDENT_CHOICE_CONSTRAINT in self.instance.Constraints.keys():
            for constraint in self.instance.Constraints[XHSTTConstraintConstants.STUDENT_CHOICE_CONSTRAINT]:
                if not constraint[XHSTTConstraintConstants.REQUIRED] and ignoreSoft:
                    continue
                consideredEventGroups = set(constraint[XHSTTFileConstants.EVENT_GROUPS])
                individualEvents = set()
                for eventGroup in consideredEventGroups:
                    individualEvents.update(self.instance.Events.EventGroups[eventGroup].Events)
                for event in individualEvents:
                    eventToStudentChoiceConstraintsDict[event].append(constraint)

        return eventToStudentChoiceConstraintsDict

    def create_event_to_balance_class_constraints(self) -> dict:
        eventToBalanceClassSizeConstraintsDict = dict()
        for event in self.instance.Events.IndividualEvents.keys():
            eventToBalanceClassSizeConstraintsDict[event] = list()

        if XHSTTConstraintConstants.BALANCE_CLASS_SIZE_CONSTRAINT in self.instance.Constraints.keys():
            for constraint in self.instance.Constraints[XHSTTConstraintConstants.BALANCE_CLASS_SIZE_CONSTRAINT]:
                consideredEventGroups = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS])
                for eventGroup in consideredEventGroups:
                    if eventGroup in self.instance.Events.EventGroups:
                        for event in self.instance.Events.EventGroups[eventGroup].Events:
                            eventToBalanceClassSizeConstraintsDict[event].append(constraint)
        return eventToBalanceClassSizeConstraintsDict

    def create_event_to_assigned_resource_constraints(self):
        eventToAssignedResourceConstraintsDict = dict()
        for event in self.instance.Events.IndividualEvents.keys():
            eventToAssignedResourceConstraintsDict[event] = list()

        if XHSTTConstraintConstants.ASSIGN_RESOURCE_CONSTRAINT in self.instance.Constraints.keys():
            for constraint in self.instance.Constraints[XHSTTConstraintConstants.ASSIGN_RESOURCE_CONSTRAINT]:
                consideredEvents = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS])
                for eventGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
                    consideredEvents.update(set(self.instance.Events.EventGroups[eventGroup].Events))
                for event in consideredEvents:
                    eventToAssignedResourceConstraintsDict[event].append(constraint)
        return eventToAssignedResourceConstraintsDict

    def create_event_to_split_events_constraints(self):
        eventToSplitEventsConstraintsDict = dict()
        for event in self.instance.Events.IndividualEvents.keys():
            eventToSplitEventsConstraintsDict[event] = list()

        if XHSTTConstraintConstants.SPLIT_EVENTS_CONSTRAINT in self.instance.Constraints.keys():
            for constraint in self.instance.Constraints[XHSTTConstraintConstants.SPLIT_EVENTS_CONSTRAINT]:
                consideredEvents = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS])
                for eventGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
                    consideredEvents.update(set(self.instance.Events.EventGroups[eventGroup].Events))
                for event in consideredEvents:
                    if event in eventToSplitEventsConstraintsDict:
                        eventToSplitEventsConstraintsDict[event].append(constraint)
        return eventToSplitEventsConstraintsDict

    def create_event_to_distribute_split_events_constraints(self):
        eventToDistributeSplitEventsConstraintsDict = dict()
        for event in self.instance.Events.IndividualEvents.keys():
            eventToDistributeSplitEventsConstraintsDict[event] = list()

        if XHSTTConstraintConstants.DISTRIBUTE_SPLIT_EVENTS_CONSTRAINT in self.instance.Constraints.keys():
            for constraint in self.instance.Constraints[XHSTTConstraintConstants.DISTRIBUTE_SPLIT_EVENTS_CONSTRAINT]:
                consideredEvents = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS])
                for eventGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
                    consideredEvents.update(set(self.instance.Events.EventGroups[eventGroup].Events))
                for event in consideredEvents:
                    if event in eventToDistributeSplitEventsConstraintsDict:
                        eventToDistributeSplitEventsConstraintsDict[event].append(constraint)
        return eventToDistributeSplitEventsConstraintsDict

    def print_unavailable_times_for_resource_as_timetable(self, resource_id: str):
        solutionEventsOfResourceByTime = self.deltaEvaluator.get_resource_to_solution_events_by_time_dict()[resource_id]
        maxDayLength = max([len(self.instance.Times.Days[day].Times) for day in self.instance.Times.Days])
        t = PrettyTable([resource_id] + [str(i) for i in range(1, maxDayLength + 1)])
        row = [resource_id] + [str(i) for i in range(1, maxDayLength + 1)]
        for day in self.instance.Times.Days.keys():
            planOfDay = list()
            planOfDay.append(day)
            for time in self.instance.Times.Days[day].Times:
                if time in solutionEventsOfResourceByTime and len(solutionEventsOfResourceByTime[time]) > 0:
                    planOfDay.append(solutionEventsOfResourceByTime[time][0][XHSTTFileConstants.ID])
                elif resource_id in self.timeToUnavailableResourcesDict[time]:
                    planOfDay.append("Unavailable")
                else:
                    planOfDay.append("Free")
            while len(planOfDay) < len(row):
                planOfDay.append("----")
            t.add_row(planOfDay)
        if self.output:
            print(t)

    def print_available_times_for_event_as_timetable(self, event_id: str):
        t = PrettyTable([event_id] + [str(i) for i in range(1, math.ceil(
            len(self.instance.Times.IndividualTimes.keys()) / len(self.instance.Times.Days.keys())) + 1)])
        row = [event_id] + [str(i) for i in range(1, math.ceil(
            len(self.instance.Times.IndividualTimes.keys()) / len(self.instance.Times.Days.keys())) + 1)]
        for day in self.instance.Times.Days.keys():
            planOfDay = list()
            planOfDay.append(day)
            for time in self.instance.Times.Days[day].Times:
                scheduleableSubevents = list()
                for subevent in self.unscheduledEvents[event_id].keys():
                    if time in self.unscheduledEvents[event_id][subevent]["PossibleTimes"]:
                        scheduleableSubevents.append(subevent)
                if len(scheduleableSubevents) == 0:
                    scheduleableSubevents.append("----")
                planOfDay.append(scheduleableSubevents)
            while len(planOfDay) < len(row):
                planOfDay.append("----")
            t.add_row(planOfDay)
        if self.output:
            print(t)

    def create_schedule_for_resource(self, resource_id: str):
        # get list of events we want to schedule for this resource based on assignedEvents and StudentChoiceConstraints/BalanceClassSizeConstraints
        # ideally we would know this for each resource before starting the remaining scheduling but that would probably just lead to a lot of conflicts anyways
        startGetEventList = timer.time()
        eventIdsOfResource = self.get_list_of_events_for_resource(resource_id)
        remainingEventIds = copy.deepcopy(eventIdsOfResource)
        self.timeMeasurementDict.setdefault("EventList", 0)
        self.timeMeasurementDict["EventList"] += timer.time() - startGetEventList
        while len(remainingEventIds) > 0:
            self.timesAffectedByIteration = set()
            startGetNext = timer.time()
            nextEventToSchedule = self.get_next_event_from_list(remainingEventIds)
            self.timeMeasurementDict.setdefault("GetNext", 0)
            self.timeMeasurementDict["GetNext"] += timer.time() - startGetNext
            startTimeAssignment = timer.time()
            self.assign_time_to_event(nextEventToSchedule, resource_id, remainingEventIds)
            self.timeMeasurementDict.setdefault("TimeAssignment", 0)
            self.timeMeasurementDict["TimeAssignment"] += timer.time() - startTimeAssignment
            startResourceAssignment = timer.time()
            self.assign_resources_to_event(nextEventToSchedule)
            remainingEventIds.remove(nextEventToSchedule)
            self.timeMeasurementDict.setdefault("ResourceAssignment", 0)
            self.timeMeasurementDict["ResourceAssignment"] += timer.time() - startResourceAssignment
            startUpdatePossibleTimes = timer.time()
            self.update_possible_times_for_all_events()
            self.timeMeasurementDict.setdefault("UpdatePossibleTimes", 0)
            self.timeMeasurementDict["UpdatePossibleTimes"] += timer.time() - startUpdatePossibleTimes
            self.schedule_all_events_with_only_one_remaining_time_slot()
            self.print_unavailable_times_for_resource_as_timetable(resource_id)

    def print_possible_times_for_student_choice_events(self):
        for event in self.eventsWithStudentAssignments:
            self.print_available_times_for_event_as_timetable(event)

    def recalculate_possible_times_for_events_including_resource(self, resources):
        for event in self.instance.Events.IndividualEvents.keys():
            for subevent in self.unscheduledEvents[event].keys():
                if self.scheduledEvents[event][subevent]:
                    continue
                eventIncludesResource = False
                for role in self.unscheduledEvents[event][subevent]["PossibleResources"].keys():
                    if len(self.unscheduledEvents[event][subevent]["PossibleResources"][role]) == 1 and list(self.unscheduledEvents[event][subevent]["PossibleResources"][role])[0] in resources:
                        eventIncludesResource = True
                        break
                if eventIncludesResource:
                    self.unscheduledEvents[event][subevent]["PossibleTimes"] = self.originalPossibleTimes[event][subevent]
                    possible_resources = self.unscheduledEvents[event][subevent]["PossibleResources"]
                    unavailable_resources = self.timeToUnavailableResourcesDict
                    fixed_resources = {
                        res for role, resources in possible_resources.items() if len(resources) == 1 for res in
                        resources
                    }
                    removedTimes = {time for time in self.allTimes if
                                    fixed_resources & unavailable_resources[time]}
                    for role, resources in possible_resources.items():
                        if len(resources) > 1:
                            removedTimes.update({
                                time for time in self.allTimes
                                if resources.issubset(unavailable_resources[time])
                            })
                    removedTimesFrozenSet = frozenset(removedTimes)
                    if (subevent[0], removedTimesFrozenSet) not in self.intersectingTimeSlotsCache.keys():
                        self.intersectingTimeSlotsCache[(
                            subevent[0],
                            removedTimesFrozenSet)] = self.get_timeslots_intersection_based_on_event_length(
                            set(self.allTimes),
                            removedTimes,
                            subevent[0])
                    self.unscheduledEvents[event][subevent]["PossibleTimes"] = self.unscheduledEvents[event][subevent]["PossibleTimes"] - \
                                                                                  self.intersectingTimeSlotsCache[(
                                                                                  subevent[0], removedTimesFrozenSet)]

    def update_possible_times_for_all_events(self):
        currentSolution = self.deltaEvaluator.get_current_solution()
        modifiedEvents = set()
        startUpdatePossibleTimesGeneral = timer.time()
        self.timeMeasurementDict.setdefault("PossibleTimesGeneral", 0)
        self.timeMeasurementDict.setdefault("PossibleTimesGeneralGetEventsWithoutDummyTime", 0)
        self.timeMeasurementDict.setdefault("PossibleTimesGeneralInit", 0)
        self.timeMeasurementDict.setdefault("PossibleTimesGeneralUnassignedResource", 0)
        self.timeMeasurementDict.setdefault("PossibleTimesGeneralRemove", 0)
        startUpdatePossibleTimesGeneralGetEvents = timer.time()
        eventSubeventPairsWithDummyTime = [(event_id, subevent) for event_id in self.instance.Events.IndividualEvents.keys() for subevent in self.unscheduledEvents[event_id].keys()
                                              if currentSolution[XHSTTFileConstants.EVENTS][(event_id, subevent)][XHSTTFileConstants.TIME] == ILPConstants.DUMMY_TIME]
        self.timeMeasurementDict["PossibleTimesGeneralGetEventsWithoutDummyTime"] += timer.time() - startUpdatePossibleTimesGeneralGetEvents
        timesAffectedByIterationFrozenSet = frozenset(self.timesAffectedByIteration)
        for event_id, subevent in eventSubeventPairsWithDummyTime:
            possible_times = self.unscheduledEvents[event_id][subevent]["PossibleTimes"]
            if len(possible_times) == 0:
                continue
            startUpdatePossibleTimesGeneralInitDicts = timer.time()
            if (subevent[0], timesAffectedByIterationFrozenSet) not in self.intersectingTimeSlotsCache.keys():
                self.intersectingTimeSlotsCache[(
                subevent[0], timesAffectedByIterationFrozenSet)] = self.get_timeslots_intersection_based_on_event_length(
                    set(self.allTimes),
                    self.timesAffectedByIteration,
                    subevent[0])
            relevantTimesForSubeventLength = self.intersectingTimeSlotsCache[(subevent[0], timesAffectedByIterationFrozenSet)]
            timesWithPossibleChanges = relevantTimesForSubeventLength.intersection(possible_times)
            if len(timesWithPossibleChanges) == 0:
                self.timeMeasurementDict[
                    "PossibleTimesGeneralInit"] += timer.time() - startUpdatePossibleTimesGeneralInitDicts
                continue
            possible_resources = self.unscheduledEvents[event_id][subevent]["PossibleResources"]
            unavailable_resources = self.timeToUnavailableResourcesDict
            fixed_resources = {
                res for role, resources in possible_resources.items() if len(resources) == 1 for res in resources
            }
            self.timeMeasurementDict[
                "PossibleTimesGeneralInit"] += timer.time() - startUpdatePossibleTimesGeneralInitDicts
            startUpdatePossibleTimesGeneralUnassignedResource = timer.time()
            removedTimes = set()
            for time in relevantTimesForSubeventLength:
                if fixed_resources & unavailable_resources[time]:
                    removedTimes.add(time)
                    continue
                for role, resources in possible_resources.items():
                    if len(resources) > 1:
                        if resources.issubset(unavailable_resources[time]):
                            removedTimes.add(time)
                            break
            self.timeMeasurementDict[
                "PossibleTimesGeneralUnassignedResource"] += timer.time() - startUpdatePossibleTimesGeneralUnassignedResource
            startUpdatePossibleTimesGeneralRemove = timer.time()
            self.unavailableTimesByEventCache.setdefault((event_id, subevent), set())
            removedTimesFrozenSet = frozenset(removedTimes)
            if (subevent[0], removedTimesFrozenSet) not in self.intersectingTimeSlotsCache.keys():
                self.intersectingTimeSlotsCache[(
                    subevent[0],
                    removedTimesFrozenSet)] = self.get_timeslots_intersection_based_on_event_length(
                    set(self.allTimes),
                    removedTimes,
                    subevent[0])
            possibleTimesBefore = set(self.unscheduledEvents[event_id][subevent]["PossibleTimes"])
            possibleTimesSet = possible_times
            self.unscheduledEvents[event_id][subevent]["PossibleTimes"] = possibleTimesSet - self.intersectingTimeSlotsCache[(subevent[0], removedTimesFrozenSet)]
            if possibleTimesBefore != self.unscheduledEvents[event_id][subevent]["PossibleTimes"]:
                modifiedEvents.add((event_id, subevent))
            if len(self.unscheduledEvents[event_id][subevent]["PossibleTimes"]) == 0:
                self.scheduledEvents[event_id][subevent] = True
            self.timeMeasurementDict["PossibleTimesGeneralRemove"] += timer.time() - startUpdatePossibleTimesGeneralRemove

        self.timeMeasurementDict["PossibleTimesGeneral"] += timer.time() - startUpdatePossibleTimesGeneral
        startUpdatePossibleTimesLinked = timer.time()
        updatedLinkedEvents = set()
        for event in modifiedEvents:
            if self.scheduledEvents[event[0]][event[1]]:
                continue
            possibleTimesBefore = set(self.unscheduledEvents[event[0]][event[1]]["PossibleTimes"])
            possibleTimes = self.unscheduledEvents[event[0]][event[1]]["PossibleTimes"]
            for linked_event in self.eventToLinkedEventsDict[event[0]]:
                possibleTimes &= self.unscheduledEvents[linked_event][event[1]]["PossibleTimes"]
                updatedLinkedEvents.add((linked_event, event[1]))
            self.unscheduledEvents[event[0]][event[1]]["PossibleTimes"] = possibleTimes
            if len(self.unscheduledEvents[event[0]][event[1]]["PossibleTimes"]) == 0:
                self.scheduledEvents[event[0]][event[1]] = True

        modifiedEvents.update(updatedLinkedEvents)
        self.timeMeasurementDict.setdefault("PossibleTimesLinked", 0)
        self.timeMeasurementDict["PossibleTimesLinked"] += timer.time() - startUpdatePossibleTimesLinked

        startUpdatePossibleTimesRest = timer.time()
        self.timeMeasurementDict.setdefault("TimePossible1", 0)
        self.timeMeasurementDict.setdefault("TimePossible2", 0)
        resourceToUnavailableTimes = dict()
        for timeOfDict in self.timeToUnavailableResourcesDict.keys():
            for resource in self.timeToUnavailableResourcesDict[timeOfDict]:
                resourceToUnavailableTimes.setdefault(resource, set()).add(timeOfDict)
        for constraintID, resource in self.studentChoiceResourcePairToPossibleEventGroups.keys():
            time1 = timer.time()
            if resource in resourceToUnavailableTimes:
                unavailableTimesOfResource = resourceToUnavailableTimes[resource]
            else:
                unavailableTimesOfResource = set()
            removedTimes = unavailableTimesOfResource
            removedTimesFrozenSet = frozenset(removedTimes)
            modifiedEventGroups = set()
            for event in modifiedEvents:
                modifiedEventGroups.update(self.eventToEventGroups[event[0]])
            relevantEventGroups = modifiedEventGroups.intersection(set(self.studentChoiceResourcePairToPossibleEventGroups[constraintID, resource]))
            removedEventGroups = set()
            time2 = timer.time()
            self.timeMeasurementDict["TimePossible1"] += time2 - time1
            for studentChoiceEventGroup in relevantEventGroups:
                firstEventOfEventGroup = self.instance.Events.EventGroups[studentChoiceEventGroup].Events[0]
                firstSubevent = list(self.unscheduledEvents[firstEventOfEventGroup].keys())[0]
                resourcesOfEvent = {
                    next(iter(possibleResources)) for
                    possibleResources
                    in
                    self.unscheduledEvents[firstEventOfEventGroup][firstSubevent]["PossibleResources"].values() if
                    len(possibleResources) == 1}
                if resource in resourcesOfEvent:
                    continue
                for event in self.instance.Events.EventGroups[studentChoiceEventGroup].Events:
                    possibleTimeSlotsBySubevent = dict()
                    for subevent in self.unscheduledEvents[event]:
                        if (subevent[0], removedTimesFrozenSet) not in self.intersectingTimeSlotsCache.keys():
                            self.intersectingTimeSlotsCache[(
                                subevent[0],
                                removedTimesFrozenSet)] = self.get_timeslots_intersection_based_on_event_length(
                                set(self.allTimes),
                                removedTimes,
                                subevent[0])
                        possibleTimeSlotsBySubevent[subevent] = self.unscheduledEvents[event][subevent][
                                                                    "PossibleTimes"] - self.intersectingTimeSlotsCache[
                                                                    (subevent[0], removedTimesFrozenSet)]

                    if not self.is_event_schedulable(possibleTimeSlotsBySubevent):
                        removedEventGroups.add(studentChoiceEventGroup)
            time3 = timer.time()
            self.timeMeasurementDict["TimePossible2"] += time3 - time2
            for removedEventGroup in removedEventGroups:
                self.studentChoiceResourcePairToPossibleEventGroups[constraintID, resource].remove(removedEventGroup)
            if len(removedEventGroups) == 0:
                continue
            if len(self.studentChoiceResourcePairToPossibleEventGroups[constraintID, resource]) <= \
                    self.studentChoiceIdToMinChoices[constraintID]:
                copyOfPossibleEventGroups = set(self.studentChoiceResourcePairToPossibleEventGroups[constraintID, resource])
                for assignedEventGroup in copyOfPossibleEventGroups:
                    self.assign_student_resource_to_event_group_with_multiple_student_roles(assignedEventGroup,
                                                                                      resource)
                resourceToUnavailableTimes = dict()
                for timeOfDict in self.timeToUnavailableResourcesDict.keys():
                    for resource in self.timeToUnavailableResourcesDict[timeOfDict]:
                        resourceToUnavailableTimes.setdefault(resource, set()).add(timeOfDict)
        self.timeMeasurementDict.setdefault("PossibleTimesRest", 0)
        self.timeMeasurementDict["PossibleTimesRest"] += timer.time() - startUpdatePossibleTimesRest

    def schedule_all_events_with_only_one_remaining_time_slot(self):
        eventsWithOneRemainingTimeSlot = {(event, subevent) for event in self.unscheduledEvents.keys() for subevent in self.unscheduledEvents[event].keys() if not self.scheduledEvents[event][subevent] and len(self.unscheduledEvents[event][subevent]["PossibleTimes"]) == 1}
        sortedEventsWithOneRemainingTimeSlot = sorted(eventsWithOneRemainingTimeSlot, key= lambda event: len([role for role in self.unscheduledEvents[event[0]][event[1]]["PossibleResources"].keys() if len(self.unscheduledEvents[event[0]][event[1]]["PossibleResources"][role]) == 1]))
        currentSolution = self.deltaEvaluator.get_current_solution()
        while len(sortedEventsWithOneRemainingTimeSlot) > 0:
            for event, subevent in eventsWithOneRemainingTimeSlot:
                if len(self.unscheduledEvents[event][subevent]["PossibleTimes"]) == 0:
                    continue
                assignedResources = {eventResource.Reference for eventResource in
                                     self.instance.Events.IndividualEvents[event].EventResources.AssignedResources}
                assignedResources.update(
                    list(self.unscheduledEvents[event][subevent]["PossibleResources"][eventResource.Role])[0]
                    for eventResource in
                    self.instance.Events.IndividualEvents[event].EventResources.UnassignedResources if
                    len(self.unscheduledEvents[event][subevent]["PossibleResources"][eventResource.Role]) == 1)
                bestTime = list(self.unscheduledEvents[event][subevent]["PossibleTimes"])[0]
                indexOfTime = self.allTimes.index(bestTime)
                usedTimeSlots = set(self.allTimes[indexOfTime: indexOfTime + subevent[0]])
                for timeSlot in usedTimeSlots:
                    self.timeToUnavailableResourcesDict[timeSlot].update(assignedResources)
                self.timesAffectedByIteration.update(usedTimeSlots)
                chosenDay = [day for day in self.instance.Times.Days.keys() if bestTime in self.instance.Times.Days[day].Times][0]
                for updatedSubevent in self.unscheduledEvents[event].keys():
                    if updatedSubevent == subevent:
                        self.unscheduledEvents[event][updatedSubevent]["PossibleTimes"] = {bestTime}
                    else:
                        self.unscheduledEvents[event][updatedSubevent]["PossibleTimes"] = \
                        self.unscheduledEvents[event][updatedSubevent]["PossibleTimes"] - set(self.instance.Times.Days[chosenDay].Times)
                currentSolution[XHSTTFileConstants.EVENTS][(event, subevent)][XHSTTFileConstants.TIME] = bestTime
                self.deltaEvaluator.assign_new_time_to_event((event, subevent), set(), usedTimeSlots,
                                                             [])
                self.scheduledEvents[event][subevent] = True
                if event in self.eventToLinkedEventsDict.keys():
                    for linked_event_id in self.eventToLinkedEventsDict[event]:
                        self.unscheduledEvents[linked_event_id][subevent]["PossibleTimes"] = copy.deepcopy(
                            self.unscheduledEvents[event][subevent]["PossibleTimes"])
                self.update_possible_times_for_all_events()

            eventsWithOneRemainingTimeSlot = {(event, subevent) for event in self.unscheduledEvents.keys() for subevent
                                              in self.unscheduledEvents[event].keys() if
                                              not self.scheduledEvents[event][subevent] and len(
                                                  self.unscheduledEvents[event][subevent]["PossibleTimes"]) == 1}
            sortedEventsWithOneRemainingTimeSlot = sorted(eventsWithOneRemainingTimeSlot,
                                                          key=lambda event: len([role for role in
                                                                                           self.unscheduledEvents[
                                                                                               event[0]][event[1]][
                                                                                               "PossibleResources"].keys()
                                                                                           if len(
                                                                  self.unscheduledEvents[event[0]][event[1]][
                                                                      "PossibleResources"][role]) == 1]))
    def assign_resources_to_event(self, event_id: str):
        # for each subevent for each unassigned resource check if any other resource is better
        #  first handle the resources affected by avoidSplitAssignments constraints
        #  than handle resources that can be inconsistent across subevents
        # update timeToUnavailableResourcesDict
        roleToResourcesDict = dict()
        firstSubevent = list(self.unscheduledEvents[event_id].keys())[0]
        rolesWithHardAssignResourceConstraints = set()
        rolesWithAvoidSplitAssignmentConstraints = set()
        currentSolution = self.deltaEvaluator.get_current_solution()
        unassignedResourceRoles = [eventResource.Role for eventResource in
                                   self.instance.Events.IndividualEvents[event_id].EventResources.UnassignedResources]
        for constraint in self.eventToAssignedResourceConstraintsDict[event_id]:
            if constraint[XHSTTConstraintConstants.REQUIRED] and constraint[
                XHSTTConstraintConstants.ROLE] in unassignedResourceRoles:
                rolesWithHardAssignResourceConstraints.add(constraint[XHSTTConstraintConstants.ROLE])


        for constraint in self.instance.Constraints[XHSTTConstraintConstants.AVOID_SPLIT_ASSIGNMENTS_CONSTRAINT]:
            consideredEvents = set()
            for eventGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
                consideredEvents.update(set(self.instance.Events.EventGroups[eventGroup].Events))
            if event_id in consideredEvents \
                    and constraint[XHSTTConstraintConstants.ROLE] in rolesWithHardAssignResourceConstraints:
                rolesWithAvoidSplitAssignmentConstraints.add(constraint[XHSTTConstraintConstants.ROLE])
        rolesWithoutAvoidSplitAssignmentConstraint = rolesWithHardAssignResourceConstraints - rolesWithAvoidSplitAssignmentConstraints


        for role in rolesWithAvoidSplitAssignmentConstraints:
            resourceScores = dict()
            originialResource = \
            currentSolution[XHSTTFileConstants.EVENTS][(event_id, firstSubevent)][XHSTTFileConstants.RESOURCES][role]
            objectiveValueWithoutRoleAssigned = self.deltaEvaluator.get_current_objective_value()
            lastResource = copy.deepcopy(originialResource)
            for resource in self.unscheduledEvents[event_id][firstSubevent]["PossibleResources"][role]:
                if resource == ILPConstants.DUMMY_RESOURCE:
                    continue
                availableTimesOfResource = {time for time in self.timeToUnavailableResourcesDict.keys() if
                                            resource not in self.timeToUnavailableResourcesDict[time]}
                resourceProducesNoClashes = True
                for subevent in self.unscheduledEvents[event_id].keys():
                    startTime = currentSolution[XHSTTFileConstants.EVENTS][(event_id, subevent)][
                        XHSTTFileConstants.TIME]
                    if startTime == ILPConstants.DUMMY_TIME:
                        continue
                    indexOfTime = self.allTimes.index(startTime)
                    timesOfSubevent = set(self.allTimes[indexOfTime: indexOfTime + subevent[0]])
                    if len(timesOfSubevent.intersection(availableTimesOfResource)) != subevent[0]:
                        resourceProducesNoClashes = False
                if not resourceProducesNoClashes:
                    resourceScores[resource] = -1000000
                    continue
                for subevent in self.unscheduledEvents[event_id].keys():
                    currentSolution[XHSTTFileConstants.EVENTS][(event_id, subevent)][XHSTTFileConstants.RESOURCES][
                        role] = resource
                    self.deltaEvaluator.assign_new_resource_to_event((event_id, subevent), lastResource, resource)
                objectiveValueWithResourceAssigned = self.deltaEvaluator.get_current_objective_value()
                resourceScores[resource] = objectiveValueWithoutRoleAssigned - objectiveValueWithResourceAssigned
                lastResource = resource
            if len(resourceScores.keys()) == 0:
                continue
            bestResource = max(resourceScores, key=resourceScores.get)
            for otherRole in rolesWithAvoidSplitAssignmentConstraints:
                if role == otherRole:
                    continue
                for subevent in self.unscheduledEvents[event_id].keys():
                    if bestResource in self.unscheduledEvents[event_id][subevent]["PossibleResources"][otherRole]:
                        self.unscheduledEvents[event_id][subevent]["PossibleResources"][otherRole].remove(bestResource)
            roleToResourcesDict[role] = bestResource
            # assign new best resource
            for subevent in self.unscheduledEvents[event_id].keys():
                startTime = currentSolution[XHSTTFileConstants.EVENTS][(event_id, subevent)][XHSTTFileConstants.TIME]
                if startTime != ILPConstants.DUMMY_TIME:
                    indexOfTime = self.allTimes.index(startTime)
                    timesOfSubevent = set(self.allTimes[indexOfTime: indexOfTime + subevent[0]])
                    for time in timesOfSubevent:
                        self.timeToUnavailableResourcesDict[time].add(bestResource)
                currentSolution[XHSTTFileConstants.EVENTS][(event_id, subevent)][XHSTTFileConstants.RESOURCES][
                    role] = bestResource
                self.deltaEvaluator.assign_new_resource_to_event((event_id, subevent), lastResource, bestResource)
                self.unscheduledEvents[event_id][subevent]["PossibleResources"][role] = {bestResource}

        for role in rolesWithoutAvoidSplitAssignmentConstraint:
            for subevent in self.unscheduledEvents[event_id].keys():
                resourceScores = dict()
                originialResource = \
                    currentSolution[XHSTTFileConstants.EVENTS][(event_id, subevent)][XHSTTFileConstants.RESOURCES][role]
                objectiveValueWithoutRoleAssigned = self.deltaEvaluator.get_current_objective_value()
                lastResource = copy.deepcopy(originialResource)
                startTime = currentSolution[XHSTTFileConstants.EVENTS][(event_id, subevent)][XHSTTFileConstants.TIME]
                if startTime == ILPConstants.DUMMY_TIME:
                    continue
                indexOfTime = self.allTimes.index(startTime)
                timesOfSubevent = set(self.allTimes[indexOfTime: indexOfTime + subevent[0]])
                for resource in self.unscheduledEvents[event_id][subevent]["PossibleResources"][role]:
                    if resource == ILPConstants.DUMMY_RESOURCE:
                        continue
                    availableTimesOfResource = {time for time in self.timeToUnavailableResourcesDict.keys() if
                                                resource not in self.timeToUnavailableResourcesDict[time]}
                    resourceProducesNoClashes = True
                    if len(timesOfSubevent.intersection(availableTimesOfResource)) != subevent[0]:
                        resourceProducesNoClashes = False
                    if not resourceProducesNoClashes:
                        resourceScores[resource] = -1000000
                        continue
                    currentSolution[XHSTTFileConstants.EVENTS][(event_id, subevent)][XHSTTFileConstants.RESOURCES][
                        role] = resource
                    self.deltaEvaluator.assign_new_resource_to_event((event_id, subevent), lastResource, resource)
                    objectiveValueWithResourceAssigned = self.deltaEvaluator.get_current_objective_value()
                    resourceScores[resource] = objectiveValueWithoutRoleAssigned - objectiveValueWithResourceAssigned
                    lastResource = resource
                if len(resourceScores.keys()) == 0:
                    continue
                bestResource = max(resourceScores, key=resourceScores.get)
                for otherRole in rolesWithAvoidSplitAssignmentConstraints:
                    if role == otherRole:
                        continue
                    if bestResource in self.unscheduledEvents[event_id][subevent]["PossibleResources"][otherRole]:
                        self.unscheduledEvents[event_id][subevent]["PossibleResources"][otherRole].remove(bestResource)
                roleToResourcesDict[role] = bestResource
                for time in timesOfSubevent:
                    self.timeToUnavailableResourcesDict[time].add(bestResource)
                currentSolution[XHSTTFileConstants.EVENTS][(event_id, subevent)][XHSTTFileConstants.RESOURCES][
                    role] = bestResource
                self.deltaEvaluator.assign_new_resource_to_event((event_id, subevent), lastResource, bestResource)
                self.unscheduledEvents[event_id][subevent]["PossibleResources"][role] = {bestResource}

        for eventResource in self.instance.Events.IndividualEvents[event_id].EventResources.AssignedResources:
            for subevent in self.unscheduledEvents[event_id].keys():
                startTime = currentSolution[XHSTTFileConstants.EVENTS][(event_id, subevent)][XHSTTFileConstants.TIME]
                if startTime == ILPConstants.DUMMY_TIME:
                    timesOfSubevent = set()
                else:
                    indexOfTime = self.allTimes.index(startTime)
                    timesOfSubevent = set(self.allTimes[indexOfTime: indexOfTime + subevent[0]])
                for time in timesOfSubevent:
                    self.timeToUnavailableResourcesDict[time].add(eventResource.Reference)

    def assign_time_to_event(self, event_id: str, resource_id: str, remainingEventIds: set):
        self.timeMeasurementDict.setdefault("TimeGeneralInit", 0)
        self.timeMeasurementDict.setdefault("TimeSubeventInit", 0)
        self.timeMeasurementDict.setdefault("TimeGeneralEval", 0)
        self.timeMeasurementDict.setdefault("TimeBestEval", 0)
        self.timeMeasurementDict.setdefault("TimeBest1", 0)
        self.timeMeasurementDict.setdefault("TimeBest2", 0)
        self.timeMeasurementDict.setdefault("Time1", 0)
        self.timeMeasurementDict.setdefault("Time1_1", 0)
        self.timeMeasurementDict.setdefault("Time1_2", 0)
        self.timeMeasurementDict.setdefault("Time2", 0)
        self.timeMeasurementDict.setdefault("Time2_1", 0)
        self.timeMeasurementDict.setdefault("Time2_2", 0)
        self.timeMeasurementDict.setdefault("Time3", 0)
        self.timeMeasurementDict.setdefault("Time4", 0)
        self.timeMeasurementDict.setdefault("Time5", 0)
        startTime = timer.time()
        allUsedTimeSlots = set()

        sortedUnscheduledSubEvents = sorted(list(self.unscheduledEvents[event_id].keys()), key=lambda subevent: len(self.unscheduledEvents[event_id][subevent]["PossibleTimes"]))
        relevantStudentChoiceConstraintsIds = [(constraint[XHSTTConstraintConstants.ID]) for constraint in self.eventToStudentChoiceConstraintsDict[event_id]]
        # constraints with <= minChoices should be assigned to event already
        eventsAffectedThroughHardSpreadEventsDict = dict()
        for constraint in self.instance.Constraints[XHSTTConstraintConstants.SPREAD_EVENTS_CONSTRAINT]:
            if not constraint[XHSTTConstraintConstants.REQUIRED]:
                continue
            for eventGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
                if event_id in self.instance.Events.EventGroups[eventGroup].Events:
                    for spreadEvent in self.instance.Events.EventGroups[eventGroup].Events:
                        if spreadEvent == event_id:
                            continue
                        eventsAffectedThroughHardSpreadEventsDict.setdefault(spreadEvent, set())
                        eventsAffectedThroughHardSpreadEventsDict[spreadEvent].update(
                            [timegroup[XHSTTFileConstants.REFERENCE_WITH_AT] for timegroup in
                             constraint[XHSTTFileConstants.TIME_GROUPS]])
        currentSolution = self.deltaEvaluator.get_current_solution()
        firstTimeSlotOfDays = [self.instance.Times.Days[day].Times[0] for day in self.instance.Times.Days.keys()]
        lastTimeSlotOfDays = [self.instance.Times.Days[day].Times[-1] for day in self.instance.Times.Days.keys()]
        self.timeMeasurementDict["TimeGeneralInit"] += timer.time() - startTime
        for subevent in sortedUnscheduledSubEvents:
            assignedResources = {eventResource.Reference for eventResource in
                                 self.instance.Events.IndividualEvents[event_id].EventResources.AssignedResources}
            assignedResources.update(
                list(self.unscheduledEvents[event_id][subevent]["PossibleResources"][eventResource.Role])[0] for
                eventResource in
                self.instance.Events.IndividualEvents[event_id].EventResources.UnassignedResources if
                len(self.unscheduledEvents[event_id][subevent]["PossibleResources"][eventResource.Role]) == 1)
            eventGroupsWithEvent = self.eventToEventGroups[event_id]
            relevantEventGroupStudentChoiceResourcePairsIncludingEvent = [(constraintID, resource) for constraintID, resource in
                                                                self.studentChoiceResourcePairToPossibleEventGroups.keys() if
                                                                constraintID in relevantStudentChoiceConstraintsIds and resource not in assignedResources
                                                                and len(self.studentChoiceResourcePairToPossibleEventGroups[
                                                                            (constraintID, resource)]) >
                                                                self.studentChoiceIdToMinChoices[
                                                                    constraintID] and len(eventGroupsWithEvent.intersection(self.studentChoiceResourcePairToPossibleEventGroups[
                                                                    (constraintID, resource)])) > 0]
            relevantEventGroupStudentChoiceResourcePairsWithAssignedResourcesToCurrentEvent = [(constraintID, resource) for
                                                                                     constraintID, resource in
                                                                                     self.studentChoiceResourcePairToPossibleEventGroups.keys()
                                                                                     if resource in assignedResources]
            # We assume that the event is scheduled when it has exactly one possibility for scheduling
            if self.scheduledEvents[event_id][subevent]:
                if len(self.unscheduledEvents[event_id][subevent]["PossibleTimes"]) != 0:
                    assignedTime = list(self.unscheduledEvents[event_id][subevent]["PossibleTimes"])[0]
                    indexOfTime = self.allTimes.index(assignedTime)
                    usedTimeSlots = set(self.allTimes[indexOfTime: indexOfTime + subevent[0]])
                    self.timesAffectedByIteration.update(usedTimeSlots)
                    chosenDay = [day for day in self.instance.Times.Days.keys() if
                                 assignedTime in self.instance.Times.Days[day].Times][
                        0]
                    for updatedSubevent in sortedUnscheduledSubEvents:
                        if updatedSubevent != subevent:
                            self.unscheduledEvents[event_id][updatedSubevent]["PossibleTimes"] = \
                            self.unscheduledEvents[event_id][updatedSubevent]["PossibleTimes"] - set(
                                self.instance.Times.Days[chosenDay].Times)
                else:
                    for eventResource in self.instance.Events.IndividualEvents[
                        event_id].EventResources.AssignedResources:
                        self.print_unavailable_times_for_resource_as_timetable(eventResource.Reference)
                continue
            startSubeventTime = timer.time()
            objectiveValueWithoutTimeAssignment = self.deltaEvaluator.get_current_objective_value()
            lastTime = currentSolution[XHSTTFileConstants.EVENTS][(event_id, subevent)][XHSTTFileConstants.TIME]
            if lastTime == ILPConstants.DUMMY_TIME:
                lastTimeAssignment = list()
            else:
                indexOfLastTimeAssignment = self.allTimes.index(lastTime)
                usedTimeSlotsLastTimeAssignment = set(
                    self.allTimes[indexOfLastTimeAssignment: indexOfLastTimeAssignment + subevent[0]])
                lastTimeAssignment = usedTimeSlotsLastTimeAssignment
            timeToScoreDict = dict()
            timeToRemovedChoices = dict()
            if len(self.unscheduledEvents[event_id][subevent]["PossibleTimes"]) == 0:
                self.scheduledEvents[event_id][subevent] = True
                for eventResource in self.instance.Events.IndividualEvents[event_id].EventResources.AssignedResources:
                    self.print_unavailable_times_for_resource_as_timetable(eventResource.Reference)
                for eventResource in self.instance.Events.IndividualEvents[event_id].EventResources.UnassignedResources:
                    if len(self.unscheduledEvents[event_id][subevent]["PossibleResources"][eventResource.Role]) > 1:
                        continue
                    for unassignedResourcePossibility in self.unscheduledEvents[event_id][subevent]["PossibleResources"][eventResource.Role]:
                        self.print_unavailable_times_for_resource_as_timetable(unassignedResourcePossibility)
                continue

            affectedEvents = set(remainingEventIds)  # Initialize with remainingEventIds

            resource_to_solution_events = self.deltaEvaluator.get_resource_to_solution_events_dict()
            individual_event = self.instance.Events.IndividualEvents[event_id]
            for resource in assignedResources:

                # Use set comprehension directly for efficiency
                if resource in resource_to_solution_events:
                    affectedEvents.update(
                        solutionEvent[XHSTTFileConstants.ID][0] for solutionEvent in
                        resource_to_solution_events[resource]
                    )
            for resource in individual_event.EventResources.UnassignedResources:
                if resource.ResourceType in {XHSTTFileConstants.TEACHER, XHSTTFileConstants.ROOM}:
                    continue
                numberPossibleResources = len(self.unscheduledEvents[event_id][subevent]["PossibleResources"][resource.Role])
                if numberPossibleResources != 1:
                    continue
                resourceReference = list(self.unscheduledEvents[event_id][subevent]["PossibleResources"][resource.Role])[0]
                # Use set comprehension directly for efficiency
                if resourceReference in resource_to_solution_events:
                    affectedEvents.update(
                        solutionEvent[XHSTTFileConstants.ID][0] for solutionEvent in
                        resource_to_solution_events[resourceReference]
                    )
            initSubeventTime = timer.time()
            resourceToUnavailableTimes = dict()
            for timeOfDict in self.timeToUnavailableResourcesDict.keys():
                for resource in self.timeToUnavailableResourcesDict[timeOfDict]:
                    resourceToUnavailableTimes.setdefault(resource, set()).add(timeOfDict)
            for time in self.unscheduledEvents[event_id][subevent]["PossibleTimes"]:
                time1 = timer.time()
                indexOfTime = self.allTimes.index(time)
                usedTimeSlots = set(self.allTimes[indexOfTime: indexOfTime + subevent[0]])
                usedTimeSlotsFrozen = frozenset(usedTimeSlots)
                currentSolution[XHSTTFileConstants.EVENTS][(event_id, subevent)][XHSTTFileConstants.TIME] = time
                self.deltaEvaluator.assign_new_time_to_event((event_id, subevent), lastTimeAssignment, usedTimeSlots, [])
                objectiveValueWithTime = self.deltaEvaluator.get_current_objective_value()
                timeToRemovedChoices[time] = dict()
                timeReductions = 0
                unfulfillableStudentChoiceConstraintsCount = 0
                reducedStudentChoices = 0
                numberOfEventsThatBecomeUnschedulable = 0
                for constraintID, resource in relevantEventGroupStudentChoiceResourcePairsIncludingEvent:
                    if resource in resourceToUnavailableTimes:
                        unavailableTimeOfResource = resourceToUnavailableTimes[resource]
                    else:
                        unavailableTimeOfResource = set()
                    if len(usedTimeSlots.intersection(unavailableTimeOfResource)) > 0:
                        reducedStudentChoices += 1
                        timeToRemovedChoices[time][(constraintID, resource)] = set()
                        timeToRemovedChoices[time][(constraintID, resource)].update(self.eventToEventGroups[event_id])
                    pass
                for constraintID, resource in relevantEventGroupStudentChoiceResourcePairsWithAssignedResourcesToCurrentEvent:
                    timeToRemovedChoices[time][(constraintID, resource)] = set()
                    unscheduleableEvents = 0
                    for studentChoiceEventGroup in self.studentChoiceResourcePairToPossibleEventGroups[(constraintID, resource)]:
                        time1_1 = timer.time()
                        firstEventOfEventGroup = self.instance.Events.EventGroups[studentChoiceEventGroup].Events[0]
                        firstSubevent = list(self.unscheduledEvents[firstEventOfEventGroup].keys())[0]
                        resourcesAssignedToStudentChoiceEvent = {next(iter(possibleResources)) for possibleResources in self.unscheduledEvents[firstEventOfEventGroup][firstSubevent]["PossibleResources"].values() if len(possibleResources) == 1}
                        extraUnavailableTimesIfResourceAssigned = set()
                        if resource not in resourcesAssignedToStudentChoiceEvent and resource in resourceToUnavailableTimes:
                            extraUnavailableTimesIfResourceAssigned.update(resourceToUnavailableTimes[resource])
                        if event_id not in self.instance.Events.EventGroups[studentChoiceEventGroup].Events:
                            extraUnavailableTimesIfResourceAssigned.update(usedTimeSlots)
                        for studentChoiceEvent in self.instance.Events.EventGroups[studentChoiceEventGroup].Events:
                            possibleTimeSlotsBySubevent = dict()
                            for subeventStudentChoiceEvent in self.unscheduledEvents[studentChoiceEvent].keys():
                                unavailableTimeFrozenSet = frozenset(extraUnavailableTimesIfResourceAssigned)
                                if (subeventStudentChoiceEvent[0], unavailableTimeFrozenSet) not in self.intersectingTimeSlotsCache.keys():
                                    self.intersectingTimeSlotsCache[(subeventStudentChoiceEvent[0],
                                                                     unavailableTimeFrozenSet)] = self.get_timeslots_intersection_based_on_event_length(
                                        set(self.allTimes),
                                        extraUnavailableTimesIfResourceAssigned,
                                        subeventStudentChoiceEvent[0])
                                possibleTimeSlotsForRemainingEvent = self.unscheduledEvents[studentChoiceEvent][subeventStudentChoiceEvent]["PossibleTimes"]
                                intersectingTimeslots = possibleTimeSlotsForRemainingEvent.intersection(self.intersectingTimeSlotsCache[(subeventStudentChoiceEvent[0], unavailableTimeFrozenSet)])
                                possibleTimeSlotsBySubevent[subeventStudentChoiceEvent] = possibleTimeSlotsForRemainingEvent - intersectingTimeslots
                                timeReductions += len(intersectingTimeslots) * (len(self.allTimes) - len(possibleTimeSlotsBySubevent[subeventStudentChoiceEvent]))
                            time1_2 = timer.time()
                            if not self.is_event_schedulable(possibleTimeSlotsBySubevent):
                                timeToRemovedChoices[time][(constraintID, resource)].update(self.eventToEventGroups[studentChoiceEvent])
                                if resource in resourcesAssignedToStudentChoiceEvent:
                                    numberOfEventsThatBecomeUnschedulable += 1
                                unscheduleableEvents += 1
                            time1_3 = timer.time()
                            self.timeMeasurementDict["Time1_1"] += time1_2 - time1_1
                            self.timeMeasurementDict["Time1_2"] += time1_3 - time1_2
                    reducedStudentChoices += unscheduleableEvents
                    amountOfPossibleChoicesWithoutTimeAssignment = len(self.studentChoiceResourcePairToPossibleEventGroups[(constraintID, resource)])
                    amountOfPossibleChoicesWithTimeAssignment = amountOfPossibleChoicesWithoutTimeAssignment - unscheduleableEvents
                    if amountOfPossibleChoicesWithTimeAssignment < self.studentChoiceIdToMinChoices[constraintID]:
                        unfulfillableStudentChoiceConstraintsCount += (self.studentChoiceIdToMinChoices[constraintID] - amountOfPossibleChoicesWithTimeAssignment)




                time2 = timer.time()
                # pre compute for each possible length all affected time slots so that we call get_timeslots_intersection_based_on_event_length
                #  only once per length with allTimes instead of possibleTimeSlotsForRemainingEvent and intersect the result with remaining PossibleTimes
                minPossibleTimesForAnySubeventOfAffectedEvent = math.inf
                for affectedEvent in affectedEvents:
                    time2_1 = timer.time()
                    possibleTimeSlotsBySubevent = dict()
                    for subeventAffectedEvent in self.unscheduledEvents[affectedEvent].keys():
                        if (affectedEvent, subeventAffectedEvent) == (event_id, subevent):
                            continue
                        if (subeventAffectedEvent[0], usedTimeSlotsFrozen) not in self.intersectingTimeSlotsCache.keys():
                            self.intersectingTimeSlotsCache[(subeventAffectedEvent[0], usedTimeSlotsFrozen)] = self.get_timeslots_intersection_based_on_event_length(set(self.allTimes),
                                                                                                 usedTimeSlots,
                                                                                                 subeventAffectedEvent[0])
                        possibleTimeSlotsForRemainingEvent = self.unscheduledEvents[affectedEvent][subeventAffectedEvent]["PossibleTimes"]
                        intersectingTimeslots = possibleTimeSlotsForRemainingEvent.intersection(self.intersectingTimeSlotsCache[(subeventAffectedEvent[0], usedTimeSlotsFrozen)])
                        possibleTimeSlotsBySubevent[subeventAffectedEvent] = possibleTimeSlotsForRemainingEvent - intersectingTimeslots
                        if len(possibleTimeSlotsBySubevent[subeventAffectedEvent]) < minPossibleTimesForAnySubeventOfAffectedEvent:
                            minPossibleTimesForAnySubeventOfAffectedEvent = len(possibleTimeSlotsBySubevent[subeventAffectedEvent])
                        timeReductions += len(intersectingTimeslots) * (
                                    len(self.allTimes) - len(possibleTimeSlotsBySubevent[subeventAffectedEvent]))
                    time2_2 = timer.time()
                    if not self.is_event_schedulable(possibleTimeSlotsBySubevent):
                        numberOfEventsThatBecomeUnschedulable += 1
                    time2_3 = timer.time()
                    self.timeMeasurementDict["Time2_1"] += time2_2 - time2_1
                    self.timeMeasurementDict["Time2_2"] += time2_3 - time2_2
                time3 = timer.time()
                for spreadEvent in eventsAffectedThroughHardSpreadEventsDict.keys():
                    possibleTimeSlotsBySubevent = dict()
                    for SubeventSpreadEvent in self.unscheduledEvents[spreadEvent].keys():
                        possibleTimeSlotsForRemainingEvent = self.unscheduledEvents[spreadEvent][SubeventSpreadEvent]["PossibleTimes"]
                        removedTimeSlotsByEventAssignment = set()
                        for timeGroup in eventsAffectedThroughHardSpreadEventsDict[spreadEvent]:
                            if timeGroup in self.instance.Times.Days and time in self.instance.Times.Days[timeGroup].Times:
                                removedTimeSlotsByEventAssignment.update(self.instance.Times.Days[timeGroup].Times)
                            elif timeGroup in self.instance.Times.TimeGroups and time in self.instance.Times.TimeGroups[
                                timeGroup].Times:
                                removedTimeSlotsByEventAssignment.update(self.instance.Times.TimeGroups[timeGroup].Times)
                        # correct since spread events only concerns start times so event length should not matter here
                        intersectingTimeslots = possibleTimeSlotsForRemainingEvent.intersection(
                            removedTimeSlotsByEventAssignment)
                        possibleTimeSlotsForRemainingEvent = possibleTimeSlotsForRemainingEvent - removedTimeSlotsByEventAssignment
                        possibleTimeSlotsBySubevent[SubeventSpreadEvent] = possibleTimeSlotsForRemainingEvent
                        timeReductions += len(intersectingTimeslots) * (len(self.allTimes) - len(possibleTimeSlotsBySubevent[SubeventSpreadEvent]))

                    if not self.is_event_schedulable(possibleTimeSlotsBySubevent):
                        numberOfEventsThatBecomeUnschedulable += 1
                time4 = timer.time()
                gapFillingScoreFactor = 0
                timeSlotBefore = self.allTimes[indexOfTime - 1]
                timeSlotAfter = self.allTimes[(indexOfTime + subevent[0] + 1) % len(self.allTimes)]
                if resource_id in self.timeToUnavailableResourcesDict[
                    timeSlotBefore] or timeSlotBefore in lastTimeSlotOfDays:
                    timeSlotBeforeBusy = True
                else:
                    timeSlotBeforeBusy = False
                if resource_id in self.timeToUnavailableResourcesDict[timeSlotAfter] or timeSlotAfter in firstTimeSlotOfDays:
                    timeSlotAfterBusy = True
                else:
                    timeSlotAfterBusy = False
                if timeSlotBeforeBusy and timeSlotAfterBusy:
                    gapFillingScoreFactor = 0.15
                elif timeSlotBeforeBusy:
                    gapFillingScoreFactor = 0.08
                elif timeSlotAfterBusy:
                    gapFillingScoreFactor = 0.05
                evenFillScore = 0
                for assignedResource in assignedResources:
                    if assignedResource in resourceToUnavailableTimes:
                        unavailableTimeOfResource = resourceToUnavailableTimes[assignedResource]
                    else:
                        unavailableTimeOfResource = set()
                    possibleTimesOfResourceId = set(self.allTimes) - unavailableTimeOfResource
                    possibleTimesOfResourceId = possibleTimesOfResourceId - usedTimeSlots
                    possibleResourceIdTimesPerDay = self.get_time_indices_by_day(possibleTimesOfResourceId)
                    maxBusyTimesOnAnyDayForResource = max(
                        [len(possibleResourceIdTimesPerDay[day]) for day in possibleResourceIdTimesPerDay.keys()])
                    for day in possibleResourceIdTimesPerDay.keys():
                        evenFillScore += math.pow(maxBusyTimesOnAnyDayForResource - len(possibleResourceIdTimesPerDay[day]),
                                                  2)
                time5 = timer.time()
                timeToScoreDict[time] = 10 * (objectiveValueWithoutTimeAssignment - objectiveValueWithTime)
                timeToScoreDict[time] += gapFillingScoreFactor * abs(
                    objectiveValueWithoutTimeAssignment - objectiveValueWithTime)
                timeToScoreDict[time] -= 10000 * numberOfEventsThatBecomeUnschedulable
                timeToScoreDict[time] -= 10000 * unfulfillableStudentChoiceConstraintsCount
                timeToScoreDict[time] -= 1000 * timeReductions
                timeToScoreDict[time] -= 500 * reducedStudentChoices
                timeToScoreDict[time] -= 1 * evenFillScore
                lastTimeAssignment = usedTimeSlots
                time6 = timer.time()
                self.timeMeasurementDict["Time1"] += time2 - time1
                self.timeMeasurementDict["Time2"] += time3 - time2
                self.timeMeasurementDict["Time3"] += time4 - time3
                self.timeMeasurementDict["Time4"] += time5 - time4
                self.timeMeasurementDict["Time5"] += time6 - time5
            evalSubeventTime = timer.time()
            bestTime = max(timeToScoreDict, key=timeToScoreDict.get)
            indexOfTime = self.allTimes.index(bestTime)
            usedTimeSlots = set(self.allTimes[indexOfTime: indexOfTime + subevent[0]])
            allUsedTimeSlots.update(usedTimeSlots)
            for timeSlot in usedTimeSlots:
                self.timeToUnavailableResourcesDict[timeSlot].update(assignedResources)
            self.timesAffectedByIteration.update(usedTimeSlots)
            chosenDay = [day for day in self.instance.Times.Days.keys() if bestTime in self.instance.Times.Days[day].Times][0]
            for updatedSubevent in sortedUnscheduledSubEvents:
                if updatedSubevent == subevent:
                    self.unscheduledEvents[event_id][updatedSubevent]["PossibleTimes"] = {bestTime}
                else:
                    self.unscheduledEvents[event_id][updatedSubevent]["PossibleTimes"] = self.unscheduledEvents[event_id][updatedSubevent]["PossibleTimes"] - set(self.instance.Times.Days[chosenDay].Times)
            currentSolution[XHSTTFileConstants.EVENTS][(event_id, subevent)][XHSTTFileConstants.TIME] = bestTime
            self.deltaEvaluator.assign_new_time_to_event((event_id, subevent), lastTimeAssignment, usedTimeSlots, [])
            self.scheduledEvents[event_id][subevent] = True
            if event_id in self.eventToLinkedEventsDict.keys():
                for linked_event_id in self.eventToLinkedEventsDict[event_id]:
                    self.unscheduledEvents[linked_event_id][subevent]["PossibleTimes"] = set(self.unscheduledEvents[event_id][subevent]["PossibleTimes"])
            for constraintID, resource in timeToRemovedChoices[bestTime].keys():
                for eventGroup in timeToRemovedChoices[bestTime][(constraintID, resource)]:
                    if eventGroup in self.studentChoiceResourcePairToPossibleEventGroups[(constraintID, resource)]:
                        self.studentChoiceResourcePairToPossibleEventGroups[(constraintID, resource)].remove(eventGroup)
                if len(self.studentChoiceResourcePairToPossibleEventGroups[(constraintID, resource)]) <= self.studentChoiceIdToMinChoices[constraintID] and len(timeToRemovedChoices[bestTime][(constraintID, resource)]) > 0:
                    eventGroupsCopy = set(self.studentChoiceResourcePairToPossibleEventGroups[(constraintID, resource)])
                    for eventGroup in eventGroupsCopy:
                        if eventGroup not in self.studentChoiceResourcePairToPossibleEventGroups[(constraintID, resource)]:
                            continue
                        time1 = timer.time()
                        self.assign_student_resource_to_event_group_with_multiple_student_roles(eventGroup, resource)
                        time2 = timer.time()
                        unavailableTimeOfResourceAfter = {time for time in self.allTimes if
                                                     resource in self.timeToUnavailableResourcesDict[time]}
                        self.timesAffectedByIteration.update(unavailableTimeOfResourceAfter)
                        time3 = timer.time()
                        self.timeMeasurementDict["TimeBest1"] += time2 - time1
                        self.timeMeasurementDict["TimeBest2"] += time3 - time2
            evalBestTime = timer.time()
            self.timeMeasurementDict["TimeSubeventInit"] += initSubeventTime - startSubeventTime
            self.timeMeasurementDict["TimeGeneralEval"] += evalSubeventTime - initSubeventTime
            self.timeMeasurementDict["TimeBestEval"] += evalBestTime - evalSubeventTime
            # get score of that time assignment based on:
            #  objective value change
            #  if event is adjacent to other event of resource (for efficient block building)?
            #  reduction of timeslots for other events of this resource -> less reductions is better
            #  very hard punishment if one of the other events becomes unscheduleable with a certain choice
            # reduce possible timeslots for remaining subevents

    def get_timeslots_intersection_based_on_event_length(self, eventTimes: set, prohibitedTimes: set, eventLength: int):
        start_time_indices = {startTime: self.allTimes.index(startTime) for startTime in eventTimes if startTime != ILPConstants.DUMMY_TIME}

        intersectingStartTimes = {
            startTime for startTime, startTimeIndex in start_time_indices.items()
            if not set(self.allTimes[startTimeIndex: startTimeIndex + eventLength]).isdisjoint(prohibitedTimes)
        }
        return intersectingStartTimes

    def is_event_schedulable(self, remainingTimesSlotsBySubevent: dict) -> bool:
        self.timeMeasurementDict.setdefault("InitRemainingTimeslots", 0)
        self.timeMeasurementDict.setdefault("CalcFlexibility", 0)
        time1 = timer.time()
        availableTimeIndicesByDayBySubevent = dict()
        availableTimeIndices = set()
        for subevent, remainingTimeSlots in remainingTimesSlotsBySubevent.items():
            remainingTimesSlotsFrozenSet = frozenset(remainingTimeSlots)
            if remainingTimesSlotsFrozenSet not in self.timeIndicesCache:
                self.timeIndicesCache[remainingTimesSlotsFrozenSet] = self.get_time_indices_by_day(remainingTimeSlots)
            availableTimeIndicesByDayBySubevent[subevent] = self.timeIndicesCache[remainingTimesSlotsFrozenSet]
            availableTimeIndices.add(frozenset(
                (subevent, frozenset(availableTimeIndicesOnDay)) for day, availableTimeIndicesOnDay in
                 availableTimeIndicesByDayBySubevent[subevent].items()))
        time2 = timer.time()
        availableTimeIndices = frozenset(availableTimeIndices)
        if availableTimeIndices not in self.flexibilityScoreCache:
            self.flexibilityScoreCache[availableTimeIndices] = self.check_flexibility_of_schedule(availableTimeIndicesByDayBySubevent,
                                                             list(remainingTimesSlotsBySubevent.keys()))
        flexibilityScore = self.flexibilityScoreCache[availableTimeIndices]
        time3 = timer.time()
        self.timeMeasurementDict["InitRemainingTimeslots"] += time2 - time1
        self.timeMeasurementDict["CalcFlexibility"] += time3 - time2
        return flexibilityScore >= 0

    def get_next_event_from_list(self, remainingEventIds: set) -> str:
        eventToSolutionEventsDict = self.deltaEvaluator.get_event_to_solution_events_dict()
        eventsWithTimeAssignment = [eventId for eventId in remainingEventIds if
                                    eventId in eventToSolutionEventsDict.keys() and len(
                                        eventToSolutionEventsDict[eventId]) > 0 and
                                    eventToSolutionEventsDict[eventId][0][
                                        XHSTTFileConstants.TIME] != ILPConstants.DUMMY_TIME]
        eventsWithoutTimeAssignment = [eventId for eventId in remainingEventIds if
                                       eventId not in eventsWithTimeAssignment]
        currentSolution = self.deltaEvaluator.get_current_solution()
        if len(eventsWithTimeAssignment) != 0:
            # those events are basically scheduled already so the order between them should not matter
            return eventsWithTimeAssignment[0]
        else:
            eventToScoreDict = dict()
            eventToResourceAssignments = dict()
            eventToPossibleTimesAfterResourceAssignments = dict()
            for event in eventsWithoutTimeAssignment:
                lengthOfEvent = self.instance.Events.IndividualEvents[event].Duration
                numberOfSubevents = len(self.unscheduledEvents[event].keys())
                roleToResourcesDict = dict()
                firstSubevent = list(self.unscheduledEvents[event].keys())[0]
                unassignedResourceRoles = {eventResource for eventResource in
                                           self.instance.Events.IndividualEvents[event].EventResources.UnassignedResources}
                rolesWithHardAssignResourceConstraints = {
                    constraint[XHSTTConstraintConstants.ROLE]
                    for constraint in self.eventToAssignedResourceConstraintsDict[event]
                    if constraint[XHSTTConstraintConstants.REQUIRED] and
                       constraint[XHSTTConstraintConstants.ROLE] in unassignedResourceRoles
                }
                totalNumberOfResourcesScheduledWithEvent = len(
                    self.instance.Events.IndividualEvents[event].EventResources.AssignedResources) + len(
                    rolesWithHardAssignResourceConstraints)
                availableTimesOfEventBySubevent = dict()
                for subevent in self.unscheduledEvents[event].keys():
                    availableTimesOfEventBySubevent[subevent] = self.unscheduledEvents[event][subevent]["PossibleTimes"].copy()
                for role in rolesWithHardAssignResourceConstraints:
                    resourceScores = dict()
                    objectiveValueWithoutRoleAssigned = self.deltaEvaluator.get_current_objective_value()
                    initialResource = \
                    currentSolution[XHSTTFileConstants.EVENTS][(event, firstSubevent)][XHSTTFileConstants.RESOURCES][
                        role]
                    lastResource = initialResource
                    for resource in self.unscheduledEvents[event][firstSubevent]["PossibleResources"][role]:
                        unavailableTimesOfResource = {time for time in self.timeToUnavailableResourcesDict.keys() if
                                                      resource in self.timeToUnavailableResourcesDict[time]}
                        unavailableTimesOfResourceFrozen = frozenset(unavailableTimesOfResource)
                        availableTimeIndicesBySubeventByDay = dict()
                        for subevent in self.unscheduledEvents[event].keys():
                            if (subevent[0], unavailableTimesOfResourceFrozen) not in self.intersectingTimeSlotsCache:
                                self.intersectingTimeSlotsCache[(subevent[0], unavailableTimesOfResourceFrozen)] = self.get_timeslots_intersection_based_on_event_length(
                                                                        set(self.allTimes),
                                                                        unavailableTimesOfResource, subevent[0])
                            intersectingTimeSlots = self.unscheduledEvents[event][subevent]["PossibleTimes"].intersection(self.intersectingTimeSlotsCache[(subevent[0], unavailableTimesOfResourceFrozen)])
                            availableTimesOfEventIfResourceChosen = self.unscheduledEvents[event][subevent]["PossibleTimes"] - intersectingTimeSlots
                            availableTimeIndicesBySubeventByDay[subevent] = self.get_time_indices_by_day(availableTimesOfEventIfResourceChosen)
                        flexibilityScore = self.check_flexibility_of_schedule(availableTimeIndicesBySubeventByDay,
                                                                         list(self.unscheduledEvents[event].keys()))
                        if flexibilityScore == -1:
                            resourceScores[resource] = -1
                            continue
                        for subevent in self.unscheduledEvents[event].keys():
                            currentSolution[XHSTTFileConstants.EVENTS][(event, subevent)][XHSTTFileConstants.RESOURCES][
                                role] = resource
                            self.deltaEvaluator.assign_new_resource_to_event((event, subevent), lastResource, resource)
                        objectiveValueWithResourceAssigned = self.deltaEvaluator.get_current_objective_value()
                        resourceScores[resource] = (objectiveValueWithResourceAssigned - objectiveValueWithoutRoleAssigned) * 10 + flexibilityScore
                        lastResource = resource
                    if len(resourceScores.keys()) == 0:
                        continue
                    bestResource = max(resourceScores, key=resourceScores.get)
                    roleToResourcesDict[role] = bestResource
                    # reset assignment since we don't know if this event will be chosen in the end
                    for subevent in self.unscheduledEvents[event].keys():
                        currentSolution[XHSTTFileConstants.EVENTS][(event, subevent)][XHSTTFileConstants.RESOURCES][
                            role] = initialResource
                        self.deltaEvaluator.assign_new_resource_to_event((event, subevent), lastResource, initialResource)

                    unavailableTimesOfBestResource = {time for time in self.timeToUnavailableResourcesDict.keys() if
                                                      bestResource in self.timeToUnavailableResourcesDict[time]}
                    unavailableTimesOfBestResourceFrozen = frozenset(unavailableTimesOfBestResource)
                    for subevent in self.unscheduledEvents[event].keys():
                        if (subevent[0], unavailableTimesOfBestResourceFrozen) not in self.intersectingTimeSlotsCache:
                            self.intersectingTimeSlotsCache[(subevent[0],
                                                        unavailableTimesOfBestResourceFrozen)] = self.get_timeslots_intersection_based_on_event_length(
                                set(self.allTimes),
                                unavailableTimesOfBestResource, subevent[0])
                        intersectingTimeSlots = self.unscheduledEvents[event][subevent]["PossibleTimes"].intersection(
                            self.intersectingTimeSlotsCache[(subevent[0], unavailableTimesOfBestResourceFrozen)])
                        availableTimesOfEventBySubevent[subevent] = self.unscheduledEvents[event][subevent]["PossibleTimes"] - intersectingTimeSlots
                eventToResourceAssignments[event] = roleToResourcesDict
                eventToPossibleTimesAfterResourceAssignments[event] = availableTimesOfEventBySubevent
                availableTimeIndicesBySubeventByDay = dict()
                for subevent in self.unscheduledEvents[event].keys():
                    availableTimeIndicesBySubeventByDay[subevent] = self.get_time_indices_by_day(
                                                                                            availableTimesOfEventBySubevent[
                                                                                                subevent])

                flexibilityScore = self.check_flexibility_of_schedule(availableTimeIndicesBySubeventByDay,
                                                                 list(self.unscheduledEvents[event].keys()))
                # Probably a good metric would be based on:
                eventToScoreDict[
                    event] = -flexibilityScore + lengthOfEvent + numberOfSubevents - totalNumberOfResourcesScheduledWithEvent
                # how many possible times are maximally still left for this event under most favorable resource assignment -> less times = more important
                # how long is this event -> longer = more important to scheduler early
                # how many subevents does this event have -> more subevents = more important to schedule early
                # how many resources have to attend this event -> more resources = more important (but also may be a better option for an unscheduled event if we cant schedule everything anyways)
                # possibly some other important constraints
            bestEvent = max(eventToScoreDict, key=eventToScoreDict.get)
            for role in eventToResourceAssignments[bestEvent].keys():
                resource = eventToResourceAssignments[bestEvent][role]
                for subevent in self.unscheduledEvents[bestEvent].keys():
                    initialResource = \
                        currentSolution[XHSTTFileConstants.EVENTS][(bestEvent, subevent)][XHSTTFileConstants.RESOURCES][
                            role]
                    currentSolution[XHSTTFileConstants.EVENTS][(bestEvent, subevent)][XHSTTFileConstants.RESOURCES][
                        role] = resource
                    self.deltaEvaluator.assign_new_resource_to_event((bestEvent, subevent), initialResource, resource)
                    self.unscheduledEvents[bestEvent][subevent]["PossibleTimes"] = \
                    eventToPossibleTimesAfterResourceAssignments[bestEvent][subevent]
            return bestEvent

    def get_time_options_for_subevent(self, availableTimeIndicesByDay: dict, required_length):
        """
        Given a sorted list of timeslots for one day and a required consecutive length,
        get the valid start positions.
        """
        possibleTimeSlots = set()
        for day in availableTimeIndicesByDay:
            current_length = 1
            slots = availableTimeIndicesByDay[day]
            for i in range(1, len(slots)):
                if slots[i] == slots[i - 1] + 1:
                    current_length += 1
                else:
                    current_length = 1
                if current_length >= required_length:
                    possibleTimeSlots.add(self.instance.Times.Days[day].Times[slots[i - required_length]])
            if len(slots) >= 1 and required_length == 1:
                possibleTimeSlots.add(self.instance.Times.Days[day].Times[slots[-1]])
        return possibleTimeSlots

    # returns a numeric value that is higher the more options remain to schedule the subevents returns -1 if impossible to schedule
    def check_flexibility_of_schedule(self, availableTimeIndicesByDayBySubevent: dict, subevents: list):
        subeventToPossibleDays = {}
        daysToPossibleSubevents = {}
        degreeOfFreedom = 0

        for subevent in subevents:
            availableTimeIndicesByDay = availableTimeIndicesByDayBySubevent[subevent]
            possible_days = set()

            for day, available_times in availableTimeIndicesByDay.items():
                if day not in daysToPossibleSubevents:
                    daysToPossibleSubevents[day] = set()

                options_on_day = len(available_times)
                degreeOfFreedom += options_on_day

                if options_on_day > 0:
                    possible_days.add(day)
                    daysToPossibleSubevents[day].add(subevent)

            subeventToPossibleDays[subevent] = possible_days
        while subeventToPossibleDays:
            # Select the subevent with the fewest possible days
            nextSubevent = min(subeventToPossibleDays, key=lambda k: len(subeventToPossibleDays[k]))

            if not subeventToPossibleDays[nextSubevent]:
                return -1  # No valid schedule possible
            elif len(subeventToPossibleDays[nextSubevent]) > len(subeventToPossibleDays.keys()):
                return degreeOfFreedom # save to return if the subevent with the least remaining days has more days left than remaining subevents to schedule

            # Select the day with the fewest assigned subevents
            selectedDay = min(subeventToPossibleDays[nextSubevent], key=lambda k: len(daysToPossibleSubevents[k]))

            # Remove the selected subevent
            del subeventToPossibleDays[nextSubevent]
            # Remove the selected day from all other subevents' possibilities
            for subevent, possible_days in subeventToPossibleDays.items():
                possible_days.discard(selectedDay)
        return degreeOfFreedom

    def get_subevents_by_length(self, subevents: list):
        lengthToNumberOfSubevents = dict()
        for subevent in subevents:
            lengthToNumberOfSubevents.setdefault(subevent[0], 0)
            lengthToNumberOfSubevents[subevent[0]] += 1
        return lengthToNumberOfSubevents

    def get_time_indices_by_day(self, times: set):
        timeIndicesByDayDict = {
            day: [i for i, time in enumerate(self.instance.Times.Days[day].Times) if time in times]
            for day in self.instance.Times.Days
        }
        return timeIndicesByDayDict

    def count_contiguous_options(self, slots, required_length):
        """
        Given a sorted list of timeslots for one day and a required consecutive length,
        count the number of valid start positions.
        """
        if not slots:
            return 0
        count = 0
        current_length = 1
        for i in range(1, len(slots)):
            if slots[i] == slots[i - 1] + 1:
                current_length += 1
            else:
                if current_length >= required_length:
                    count += current_length - required_length + 1
                current_length = 1
        if current_length >= required_length:
            count += current_length - required_length + 1
        return count

    # select the events so that there are initially no conflicts in times especially if we select to be part of an event that is already scheduled
    # preferably choose already scheduled events if it is possible
    # if not possible based on how full events are/class Size Balance
    def get_list_of_events_for_resource(self, resource_id: str):
        eventToSolutionEventsDict = self.deltaEvaluator.get_event_to_solution_events_dict()
        resourceToSolutionEventsDict = self.deltaEvaluator.get_resource_to_solution_events_dict()
        if resource_id in resourceToSolutionEventsDict:
            solutionEventsOfResource = self.deltaEvaluator.get_resource_to_solution_events_dict()[resource_id]
        else:
            solutionEventsOfResource = []
        eventIdsOfResource = {solutionEvent[XHSTTFileConstants.ID][0] for solutionEvent in solutionEventsOfResource}
        sortedStudentChoiceConstraints = self.sort_student_choice_constraints(
            self.resourceToStudentChoiceConstraintsDict[resource_id])
        for constraint in sortedStudentChoiceConstraints:
            chosenEventGroups = set()
            min_selections = int(constraint[XHSTTConstraintConstants.MINIMUM])
            remainingPossibleEventGroups = list(self.studentChoiceResourcePairToPossibleEventGroups[constraint[XHSTTConstraintConstants.ID], resource_id])
            eventGroupsAsEventsList = [self.instance.Events.EventGroups[eventGroup].Events for eventGroup in
                                       remainingPossibleEventGroups]
            if len(eventGroupsAsEventsList) == 0:
                continue
            isAssignedIndicator = [False for _ in eventGroupsAsEventsList]
            possibleEventsToSelect = [eventGroup for eventGroup in eventGroupsAsEventsList]
            assignmentCounter = 0
            # check if any of the student choices are already fulfilled
            for eventGroupIndex in range(len(eventGroupsAsEventsList)):
                if isAssignedIndicator[eventGroupIndex]:
                    continue
                eventGroupAsIndividualEventsList = eventGroupsAsEventsList[eventGroupIndex]
                for event in eventGroupAsIndividualEventsList:
                    firstSubevent = list(self.unscheduledEvents[event].keys())[0]
                    for role in self.unscheduledEvents[event][firstSubevent]["PossibleResources"].keys():
                        if len(self.unscheduledEvents[event][firstSubevent]["PossibleResources"][role]) != 1:
                            continue
                        if list(self.unscheduledEvents[event][firstSubevent]["PossibleResources"][role])[0] == resource_id:
                            isAssignedIndicator[eventGroupIndex] = True
                            assignmentCounter += 1
                            chosenEventGroups.add(remainingPossibleEventGroups[eventGroupIndex])
            if assignmentCounter >= min_selections:
                continue
            while assignmentCounter < min_selections:
                eventTuplesWithWeightInfo = [(event, 1, 1) for event in
                                             possibleEventsToSelect if
                                             not isAssignedIndicator[possibleEventsToSelect.index(event)]]
                best_events = self.select_best_events_from_list_for_resource(resource_id, eventTuplesWithWeightInfo, doAssign=True)
                if best_events is None:
                    break
                isAssignedIndicator[possibleEventsToSelect.index(best_events[0])] = True
                assignmentCounter += 1
                eventIdsOfResource.update(best_events[0])
                chosesEventGroup = remainingPossibleEventGroups[possibleEventsToSelect.index(best_events[0])]
                chosenEventGroups.add(chosesEventGroup)

            self.studentChoiceResourcePairToPossibleEventGroups[constraint[XHSTTConstraintConstants.ID], resource_id] = chosenEventGroups

        for event_id in eventIdsOfResource:
            relevantStudentChoiceConstraints = self.eventToStudentChoiceConstraintsDict[event_id]
            for constraint in relevantStudentChoiceConstraints:
                consideredResources = set(
                    constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCES])
                for resourceGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][
                    XHSTTFileConstants.RESOURCE_GROUPS]:
                    for resourceType in self.instance.Resources.ResourceGroupsByType.keys():
                        if resourceGroup in self.instance.Resources.ResourceGroupsByType[
                            resourceType].ResourceGroups:
                            consideredResources.update(set(
                                self.instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups[
                                    resourceGroup].Resources))
                resourcesOfEvent = {eventToSolutionEventsDict[event_id][0][XHSTTFileConstants.RESOURCES][role] for role in
                                         eventToSolutionEventsDict[event_id][0][XHSTTFileConstants.RESOURCES]}
                consideredResources = consideredResources - resourcesOfEvent
                eventGroupsOfEventId = self.eventToEventGroups[event_id]
                resourcesWithMultipleChoicesLeftOrCantChooseEvent = {resource for resource in consideredResources if len(self.studentChoiceResourcePairToPossibleEventGroups[constraint[XHSTTConstraintConstants.ID], resource]) > int(constraint[XHSTTConstraintConstants.MINIMUM]) or len(eventGroupsOfEventId.intersection(self.studentChoiceResourcePairToPossibleEventGroups[constraint[XHSTTConstraintConstants.ID], resource])) == 0}
                consideredResources = consideredResources - resourcesWithMultipleChoicesLeftOrCantChooseEvent
                for resource in consideredResources:
                    possibleTimeSlotsBySubevent = dict()
                    for subevent in self.unscheduledEvents[event_id]:
                        removedTimes = {time for time in self.allTimes if
                                        resource_id in self.timeToUnavailableResourcesDict[time]}
                        removedTimesFrozenSet = frozenset(removedTimes)
                        if (subevent[0], removedTimesFrozenSet) not in self.intersectingTimeSlotsCache.keys():
                            self.intersectingTimeSlotsCache[(
                                subevent[0],
                                removedTimesFrozenSet)] = self.get_timeslots_intersection_based_on_event_length(
                                set(self.allTimes),
                                removedTimes,
                                subevent[0])
                        possibleTimeSlotsBySubevent[subevent] = self.unscheduledEvents[event_id][subevent][
                                                                    "PossibleTimes"] - self.intersectingTimeSlotsCache[
                                                                    (subevent[0], removedTimesFrozenSet)]
                    self.assign_student_resource_to_event_with_multiple_student_roles(event_id, resource)
        return eventIdsOfResource

    def assign_student_resource_to_event_group_with_multiple_student_roles(self, eventGroup, resource):
        for event in self.instance.Events.EventGroups[eventGroup].Events:
            self.assign_student_resource_to_event_with_multiple_student_roles(event, resource)

    def assign_student_resource_to_event_group_with_multiple_student_roles_before_solution_exists(self, eventGroup, resource,
                                                                                            unscheduledEvents) -> bool:
        for event in self.instance.Events.EventGroups[eventGroup].Events:
            success = self.assign_student_resource_to_event_with_multiple_student_roles_before_solution_exists(event, resource, unscheduledEvents)
            if not success:
                return False
        return True
    def assign_student_resource_to_event_with_multiple_student_roles_before_solution_exists(self, event, resource, unscheduledEvents) -> bool:
        studentResourcesOfEvent = {resource.Role for resource in
                                   self.instance.Events.IndividualEvents[
                                       event].EventResources.UnassignedResources if
                                   resource.ResourceType == XHSTTFileConstants.STUDENT}
        firstSubevent = list(unscheduledEvents[event].keys())[0]
        dummyResourcesOfEvent = {role for role in
                                 unscheduledEvents[event][firstSubevent]["PossibleResources"].keys() if
                                 len(unscheduledEvents[event][firstSubevent]["PossibleResources"][role]) != 0 and
                                 (len(unscheduledEvents[event][firstSubevent]["PossibleResources"][role]) > 1 or
                                 list(unscheduledEvents[event][firstSubevent]["PossibleResources"][role])[0] == resource)}
        unassignedStudentResourceRoles = studentResourcesOfEvent.intersection(dummyResourcesOfEvent)
        if len(unassignedStudentResourceRoles) == 0:
            return False
        unassignedStudentResourceRoles = sorted(unassignedStudentResourceRoles,
                                                key=lambda role: 1 if role.startswith("min_requirement") else 0)
        roleForResourceInEvent = unassignedStudentResourceRoles[0]
        # update structures in delta eval and modify current solution
        for subevent in unscheduledEvents[event].keys():
            unscheduledEvents[event][subevent]["PossibleResources"][roleForResourceInEvent] = {resource}
            removedTimes = {time for time in self.allTimes if resource in self.timeToUnavailableResourcesDict[time]}
            removedTimesFrozenSet = frozenset(removedTimes)
            if (subevent[0], removedTimesFrozenSet) not in self.intersectingTimeSlotsCache.keys():
                self.intersectingTimeSlotsCache[(
                    subevent[0],
                    removedTimesFrozenSet)] = self.get_timeslots_intersection_based_on_event_length(
                    set(self.allTimes),
                    removedTimes,
                    subevent[0])
            unscheduledEvents[event][subevent]["PossibleTimes"] = unscheduledEvents[event][subevent][
                                                                           "PossibleTimes"] - \
                                                                       self.intersectingTimeSlotsCache[
                                                                           (subevent[0], removedTimesFrozenSet)]
            if len(unscheduledEvents[event][subevent]["PossibleTimes"]) == 1:
                rolesOfAssignedResources = {role for role in
                                            unscheduledEvents[event][subevent]["PossibleResources"].keys() if
                                            (len(unscheduledEvents[event][subevent]["PossibleResources"][role]) != 0 and
                                            role not in dummyResourcesOfEvent) or role == roleForResourceInEvent}
                indexOfTime = self.allTimes.index(list(unscheduledEvents[event][subevent]["PossibleTimes"])[0])
                usedTimeSlots = set(self.allTimes[indexOfTime: indexOfTime + subevent[0]])
                for role in rolesOfAssignedResources:
                    for time in usedTimeSlots:
                        self.timeToUnavailableResourcesDict[time].add(list(unscheduledEvents[event][subevent]["PossibleResources"][role])[0])

        possiblyAffectedStudentChoiceResourcePairs = {studentChoiceResourcePair for studentChoiceResourcePair in
                                                      self.studentChoiceResourcePairToPossibleEventGroups.keys() if
                                                      (studentChoiceResourcePair[1] == resource)}
        eventGroupsToRemoveFromSelections = set()
        for constraintID, constraintResource in possiblyAffectedStudentChoiceResourcePairs:
            selectedEventGroups = set()
            for studentChoiceEventGroup in self.studentChoiceResourcePairToPossibleEventGroups[constraintID, constraintResource]:
                firstEventOfEventGroup = self.instance.Events.EventGroups[studentChoiceEventGroup].Events[0]
                firstSubevent = list(unscheduledEvents[firstEventOfEventGroup].keys())[0]
                resourcesOfEvent = {
                    list(unscheduledEvents[firstEventOfEventGroup][firstSubevent]["PossibleResources"][role])[0] for
                    role
                    in
                    unscheduledEvents[firstEventOfEventGroup][firstSubevent]["PossibleResources"].keys() if
                    len(unscheduledEvents[firstEventOfEventGroup][firstSubevent]["PossibleResources"][role]) == 1}
                if constraintResource in resourcesOfEvent:
                    selectedEventGroups.add(studentChoiceEventGroup)
                    continue
            if len(selectedEventGroups) >= self.studentChoiceIdToMinChoices[constraintID]:
                if resource == constraintResource:
                    potentialToRemove = set(self.originalStudentChoiceResourcePairToPossibleEventGroups[
                                                constraintID, constraintResource]) - selectedEventGroups
                    eventGroupsToRemoveFromSelections.update(potentialToRemove)
        if len(eventGroupsToRemoveFromSelections) > 0:
            self.excludedStudentChoices.setdefault(resource, set())
            self.excludedStudentChoices[resource].update(eventGroupsToRemoveFromSelections)
        for constraintID, constraintResource in possiblyAffectedStudentChoiceResourcePairs:
            if constraintResource != resource or len(eventGroupsToRemoveFromSelections.intersection(
                    self.studentChoiceResourcePairToPossibleEventGroups[constraintID, constraintResource])) == 0:
                continue
            removedEventGroups = eventGroupsToRemoveFromSelections.intersection(
                self.studentChoiceResourcePairToPossibleEventGroups[constraintID, constraintResource])
            for removedEventGroup in removedEventGroups:
                self.studentChoiceResourcePairToPossibleEventGroups[constraintID, constraintResource].remove(removedEventGroup)
            if len(removedEventGroups) == 0:
                continue
        return True
    def assign_student_resource_to_event_with_multiple_student_roles(self, event, resource):
        self.timeMeasurementDict.setdefault("TimeMult1", 0)
        self.timeMeasurementDict.setdefault("TimeMult2", 0)
        eventsInSameEventGroup = self.eventToEventGroups[event]
        time1 = timer.time()
        studentResourcesOfEvent = {resource.Role for resource in
                                   self.instance.Events.IndividualEvents[
                                       event].EventResources.UnassignedResources if
                                   resource.ResourceType == XHSTTFileConstants.STUDENT}
        firstSubevent = list(self.unscheduledEvents[event].keys())[0]
        resourceToSolutionEventsDict = self.deltaEvaluator.get_resource_to_solution_events_dict()
        dummyResourcesOfEvent = dict()
        for eventGroup in eventsInSameEventGroup:
            for eventOfSameEventGroup in self.instance.Events.EventGroups[eventGroup].Events:
                firstSubeventOfSameEventGroup = list(self.unscheduledEvents[eventOfSameEventGroup].keys())[0]
                dummyResourcesOfEvent[eventOfSameEventGroup] = {role for role in
                                         self.unscheduledEvents[eventOfSameEventGroup][firstSubeventOfSameEventGroup]["PossibleResources"].keys() if
                                         len(self.unscheduledEvents[eventOfSameEventGroup][firstSubeventOfSameEventGroup]["PossibleResources"][role]) > 1 or len(self.unscheduledEvents[eventOfSameEventGroup][firstSubeventOfSameEventGroup]["PossibleResources"][role]) == 0 or list(self.unscheduledEvents[eventOfSameEventGroup][firstSubeventOfSameEventGroup]["PossibleResources"][role])[0] == resource}
        resourcesAlreadyInEvent = {list(self.unscheduledEvents[event][firstSubevent]["PossibleResources"][role])[0] for role in
                                 self.unscheduledEvents[event][firstSubevent]["PossibleResources"].keys() if
                                 len(self.unscheduledEvents[event][firstSubevent]["PossibleResources"][role]) == 1}
        resourcesWronglyMarkedAsPartOfEvent = set()
        for resource_id in resourcesAlreadyInEvent:
            if resource_id not in resourceToSolutionEventsDict or event not in {solutionEvent[XHSTTFileConstants.ID][0] for solutionEvent in resourceToSolutionEventsDict[resource_id]}:
                resourcesWronglyMarkedAsPartOfEvent.add(resource_id)
        if len(resourcesWronglyMarkedAsPartOfEvent) > 0:
            resourcesAlreadyInEvent = resourcesAlreadyInEvent - resourcesWronglyMarkedAsPartOfEvent
        if resource in resourcesAlreadyInEvent:
            return
        unassignedStudentResourceRoles = studentResourcesOfEvent
        for dummyResources in dummyResourcesOfEvent.values():
            unassignedStudentResourceRoles = unassignedStudentResourceRoles.intersection(dummyResources)
        if len(unassignedStudentResourceRoles) == 0:
            return
        time2 = timer.time()
        self.update_possible_times_for_all_events()
        addedUnavailableTimesPerResource = dict()
        currentSolution = self.deltaEvaluator.get_current_solution()
        unassignedStudentResourceRoles = sorted(unassignedStudentResourceRoles,
                                                key=lambda role: 1 if role.startswith("min_requirement") else 0)
        alreadyUsedRolesForEventGroup = set()
        for eventGroup in eventsInSameEventGroup:
            for eventInSameEventGroup in self.instance.Events.EventGroups[eventGroup].Events:
                for subevent in self.unscheduledEvents[eventInSameEventGroup].keys():
                    alreadyUsedRolesForEventGroup.update([role for role in
                                               self.unscheduledEvents[eventInSameEventGroup][subevent]["PossibleResources"].keys() if
                                               len(self.unscheduledEvents[eventInSameEventGroup][subevent]["PossibleResources"][
                                                       role]) == 1 and list(self.unscheduledEvents[eventInSameEventGroup][subevent]["PossibleResources"][
                                                       role])[0] == resource])
        if len(alreadyUsedRolesForEventGroup) == 0:
            roleForResourceInEvent = unassignedStudentResourceRoles[0]
        else:
            roleForResourceInEvent = list(alreadyUsedRolesForEventGroup)[0]
        # update structures in delta eval and modify current solution
        for subevent in self.unscheduledEvents[event].keys():

            currentSolution[XHSTTFileConstants.EVENTS][(event, subevent)][XHSTTFileConstants.RESOURCES][
                roleForResourceInEvent] = resource
            self.deltaEvaluator.assign_new_resource_to_event((event, subevent), ILPConstants.DUMMY_RESOURCE,
                                                                 resource)
            self.unscheduledEvents[event][subevent]["PossibleResources"][roleForResourceInEvent] = {resource}
            removedTimes = {time for time in self.allTimes if resource in self.timeToUnavailableResourcesDict[time]}
            removedTimesFrozenSet = frozenset(removedTimes)
            if (subevent[0], removedTimesFrozenSet) not in self.intersectingTimeSlotsCache.keys():
                self.intersectingTimeSlotsCache[(
                    subevent[0],
                    removedTimesFrozenSet)] = self.get_timeslots_intersection_based_on_event_length(
                    set(self.allTimes),
                    removedTimes,
                    subevent[0])
            wasScheduled = self.scheduledEvents[event][subevent] and len(self.unscheduledEvents[event][subevent]["PossibleTimes"]) == 1
            if wasScheduled:
                scheduledTime = list(self.unscheduledEvents[event][subevent]["PossibleTimes"])[0]
            self.unscheduledEvents[event][subevent]["PossibleTimes"] = self.unscheduledEvents[event][subevent]["PossibleTimes"] - \
                                                                          self.intersectingTimeSlotsCache[
                                                                              (subevent[0], removedTimesFrozenSet)]

            if wasScheduled and len(self.unscheduledEvents[event][subevent]["PossibleTimes"]) == 0:
                indexOfTime = self.allTimes.index(scheduledTime)
                usedTimeSlots = set(self.allTimes[indexOfTime: indexOfTime + subevent[0]])
                currentSolution[XHSTTFileConstants.EVENTS][(event, subevent)][XHSTTFileConstants.TIME] = ILPConstants.DUMMY_TIME
                self.deltaEvaluator.assign_new_time_to_event((event, subevent), usedTimeSlots, set(), [])
                for existingResource in resourcesAlreadyInEvent:
                    if existingResource == resource:
                        continue
                    for usedTime in usedTimeSlots:
                        if existingResource in self.timeToUnavailableResourcesDict[usedTime]:
                            self.timeToUnavailableResourcesDict[usedTime].remove(existingResource)
                self.recalculate_possible_times_for_events_including_resource(resourcesAlreadyInEvent)

            if len(self.unscheduledEvents[event][subevent]["PossibleTimes"]) == 1:
                scheduledTime = list(self.unscheduledEvents[event][subevent]["PossibleTimes"])[0]
                indexOfTime = self.allTimes.index(scheduledTime)
                usedTimeSlots = set(self.allTimes[indexOfTime: indexOfTime + subevent[0]])
                if not wasScheduled:
                    currentSolution[XHSTTFileConstants.EVENTS][(event, subevent)][XHSTTFileConstants.TIME] = scheduledTime
                    self.deltaEvaluator.assign_new_time_to_event((event, subevent), set(),
                                                                 usedTimeSlots, [])
                    self.scheduledEvents[event][subevent] = True
                    self.timesAffectedByIteration.update(usedTimeSlots)
                    affectedResources = set(resourcesAlreadyInEvent)
                    affectedResources.add(resource)
                    for time in usedTimeSlots:
                        for resource_id in affectedResources:
                            self.timeToUnavailableResourcesDict[time].add(resource_id)
                            addedUnavailableTimesPerResource.setdefault(resource_id, set())
                            addedUnavailableTimesPerResource[resource_id].add(time)
                else:
                    self.timesAffectedByIteration.update(usedTimeSlots)
                    for time in usedTimeSlots:
                        resourcesWithAddedUnavailableTime = resource
                        self.timeToUnavailableResourcesDict[time].add(resourcesWithAddedUnavailableTime)
                        addedUnavailableTimesPerResource.setdefault(resourcesWithAddedUnavailableTime, set())
                        addedUnavailableTimesPerResource[resourcesWithAddedUnavailableTime].add(time)
            elif len(self.unscheduledEvents[event][subevent]["PossibleTimes"]) == 0 and not self.scheduledEvents[event][subevent]:
                self.scheduledEvents[event][subevent] = True
        time3 = timer.time()
        self.timeMeasurementDict["TimeMult1"] += time2 - time1
        self.timeMeasurementDict["TimeMult2"] += time3 - time2
        self.update_possible_times_for_all_events()
        eventGroupsOfEvent = self.eventToEventGroups[event]
        possiblyAffectedStudentChoiceResourcePairs = {studentChoiceResourcePair for studentChoiceResourcePair in
                                                      self.studentChoiceResourcePairToPossibleEventGroups.keys() if
                                                      (studentChoiceResourcePair[1] == resource) or (studentChoiceResourcePair[1] != resource
                                                                                          and len(eventGroupsOfEvent.intersection(self.studentChoiceResourcePairToPossibleEventGroups[
                                                          studentChoiceResourcePair])) > 0)}

        eventGroupsToRemoveFromSelections = set()
        for constraintID, constraintResource in possiblyAffectedStudentChoiceResourcePairs:
            removedEventGroups = set()
            selectedEventGroups = set()
            for studentChoiceEventGroup in self.studentChoiceResourcePairToPossibleEventGroups[constraintID, constraintResource]:
                firstEventOfEventGroup = self.instance.Events.EventGroups[studentChoiceEventGroup].Events[0]
                firstSubevent = list(self.unscheduledEvents[firstEventOfEventGroup].keys())[0]
                resourcesOfEvent = {
                    next(iter(possibleResources)) for
                    possibleResources
                    in
                    self.unscheduledEvents[firstEventOfEventGroup][firstSubevent]["PossibleResources"].values() if
                    len(possibleResources) == 1}
                if constraintResource in resourcesOfEvent:
                    if event in self.instance.Events.EventGroups[studentChoiceEventGroup].Events:
                        selectedEventGroups.add(studentChoiceEventGroup)
                        continue
                    selectedEventGroups.add(studentChoiceEventGroup)
                    if constraintResource in addedUnavailableTimesPerResource:
                        removedTimes = addedUnavailableTimesPerResource[constraintResource]
                        removedTimesFrozenSet = frozenset(removedTimes)
                    else:
                        continue
                else:
                    unavailableTimesOfResource = {time for time in self.allTimes if
                                                  constraintResource in self.timeToUnavailableResourcesDict[time]}
                    removedTimes = unavailableTimesOfResource
                    removedTimesFrozenSet = frozenset(removedTimes)
                if event not in self.instance.Events.EventGroups[studentChoiceEventGroup].Events and constraintResource not in resourcesAlreadyInEvent and constraintResource != resource:
                    continue
                for eventOfEventGroup in self.instance.Events.EventGroups[studentChoiceEventGroup].Events:
                    possibleTimeSlotsBySubevent = dict()
                    oldPossibleTimeSlotsBySubevent = dict()
                    for subevent in self.unscheduledEvents[eventOfEventGroup]:
                        if (subevent[0], removedTimesFrozenSet) not in self.intersectingTimeSlotsCache.keys():
                            self.intersectingTimeSlotsCache[(
                                subevent[0],
                                removedTimesFrozenSet)] = self.get_timeslots_intersection_based_on_event_length(
                                set(self.allTimes),
                                removedTimes,
                                subevent[0])
                        oldPossibleTimeSlotsBySubevent[subevent] = self.unscheduledEvents[eventOfEventGroup][subevent][
                                                                    "PossibleTimes"]
                        possibleTimeSlotsBySubevent[subevent] = self.unscheduledEvents[eventOfEventGroup][subevent][
                                                                    "PossibleTimes"] - self.intersectingTimeSlotsCache[
                                                                    (subevent[0], removedTimesFrozenSet)]
                        if constraintResource in resourcesOfEvent:
                            if len(possibleTimeSlotsBySubevent[subevent]) == 0 and len(self.unscheduledEvents[eventOfEventGroup][subevent]["PossibleTimes"]) > 0:
                                wasScheduled = self.scheduledEvents[eventOfEventGroup][subevent] and len(
                                    self.unscheduledEvents[eventOfEventGroup][subevent]["PossibleTimes"]) == 1
                                if wasScheduled:
                                    scheduledTime = list(self.unscheduledEvents[eventOfEventGroup][subevent]["PossibleTimes"])[0]
                                    indexOfTime = self.allTimes.index(scheduledTime)
                                    usedTimeSlots = set(self.allTimes[indexOfTime: indexOfTime + subevent[0]])
                                    currentSolution[XHSTTFileConstants.EVENTS][(eventOfEventGroup, subevent)][
                                        XHSTTFileConstants.TIME] = ILPConstants.DUMMY_TIME
                                    self.deltaEvaluator.assign_new_time_to_event((eventOfEventGroup, subevent), usedTimeSlots, set(),
                                                                                 [])
                                    for existingResource in resourcesAlreadyInEvent:
                                        if existingResource == resource:
                                            continue
                                        for usedTime in usedTimeSlots:
                                            if existingResource in self.timeToUnavailableResourcesDict[usedTime]:
                                                self.timeToUnavailableResourcesDict[usedTime].remove(existingResource)
                                    self.recalculate_possible_times_for_events_including_resource(resourcesAlreadyInEvent)
                            self.unscheduledEvents[eventOfEventGroup][subevent]["PossibleTimes"] = possibleTimeSlotsBySubevent[subevent]

                    if not self.is_event_schedulable(possibleTimeSlotsBySubevent):
                        if constraintResource not in resourcesOfEvent:
                            removedEventGroups.add(studentChoiceEventGroup)
                if len(selectedEventGroups) >= self.studentChoiceIdToMinChoices[constraintID]:
                    if resource == constraintResource:
                        potentialToRemove = set(self.originalStudentChoiceResourcePairToPossibleEventGroups[
                                                    constraintID, constraintResource]) - selectedEventGroups
                        eventGroupsToRemoveFromSelections.update(potentialToRemove)
            for removedEventGroup in removedEventGroups:
                self.studentChoiceResourcePairToPossibleEventGroups[constraintID, constraintResource].remove(removedEventGroup)
            if len(removedEventGroups) == 0:
                continue
            if len(self.studentChoiceResourcePairToPossibleEventGroups[constraintID, constraintResource]) <= \
                    self.studentChoiceIdToMinChoices[constraintID]:
                setForIterator = set(self.studentChoiceResourcePairToPossibleEventGroups[constraintID, constraintResource])
                for assignedEventGroup in setForIterator:
                    if assignedEventGroup not in self.studentChoiceResourcePairToPossibleEventGroups[constraintID, constraintResource]:
                        continue
                    self.assign_student_resource_to_event_group_with_multiple_student_roles(assignedEventGroup,
                                                                                      constraintResource)
        if len(eventGroupsToRemoveFromSelections) > 0:
            self.excludedStudentChoices.setdefault(resource, set())
            self.excludedStudentChoices[resource].update(eventGroupsToRemoveFromSelections)

        for constraintID, constraintResource in possiblyAffectedStudentChoiceResourcePairs:
            if constraintResource != resource or len(eventGroupsToRemoveFromSelections.intersection(self.studentChoiceResourcePairToPossibleEventGroups[constraintID, constraintResource])) == 0:
                continue
            removedEventGroups = eventGroupsToRemoveFromSelections.intersection(self.studentChoiceResourcePairToPossibleEventGroups[constraintID, constraintResource])
            for removedEventGroup in removedEventGroups:
                self.studentChoiceResourcePairToPossibleEventGroups[constraintID, constraintResource].remove(removedEventGroup)
            if len(removedEventGroups) == 0:
                continue
            if len(self.studentChoiceResourcePairToPossibleEventGroups[constraintID, constraintResource]) <= \
                    self.studentChoiceIdToMinChoices[constraintID]:
                setForIterator = set(self.studentChoiceResourcePairToPossibleEventGroups[constraintID, constraintResource])
                for assignedEventGroup in setForIterator:
                    if assignedEventGroup not in self.studentChoiceResourcePairToPossibleEventGroups[constraintID, constraintResource]:
                        continue
                    self.assign_student_resource_to_event_group_with_multiple_student_roles(assignedEventGroup,
                                                                                      constraintResource)
        # We filled the last possible role for this event
        if len(unassignedStudentResourceRoles) == 1:
            sortedStudentChoiceResourcePairToPossibleEventGroups = sorted(self.studentChoiceResourcePairToPossibleEventGroups.keys(), key=lambda x: len(self.studentChoiceResourcePairToPossibleEventGroups[x]))
            for constraintID, constraintResource in sortedStudentChoiceResourcePairToPossibleEventGroups:
                if resource == constraintResource:
                    continue
                eventGroupsOfEvent = self.eventToEventGroups[event]
                if len(eventGroupsOfEvent.intersection(self.studentChoiceResourcePairToPossibleEventGroups[constraintID, constraintResource])) > 0:
                    if not constraintResource in resourcesAlreadyInEvent:
                        for eventGroup in eventGroupsOfEvent:
                            self.studentChoiceResourcePairToPossibleEventGroups[constraintID, constraintResource].remove(eventGroup)
                    else:
                        continue
                    if 0 < len(self.studentChoiceResourcePairToPossibleEventGroups[constraintID, constraintResource]) <= self.studentChoiceIdToMinChoices[constraintID]:
                        mandatoryEventGroupSet = set(self.studentChoiceResourcePairToPossibleEventGroups[constraintID, constraintResource])
                        for mandatoryEventGroup in mandatoryEventGroupSet:
                            if mandatoryEventGroup not in self.studentChoiceResourcePairToPossibleEventGroups[constraintID, constraintResource]:
                                continue
                            self.assign_student_resource_to_event_group_with_multiple_student_roles(mandatoryEventGroup, constraintResource)


    def sort_student_choice_constraints(self, studentChoiceConstraints: list) -> list:
        if len(studentChoiceConstraints) == 0:
            return list()
        preSortedList = sorted(studentChoiceConstraints, key=lambda constraint: (
        len(constraint[XHSTTFileConstants.EVENT_GROUPS]), int(constraint[XHSTTConstraintConstants.MINIMUM])))
        return preSortedList

    def select_best_events_from_list_for_resource(self, resource_id, groupsOfEvents: list, doAssign=False):
        eligibleEvents = set()
        eventGroupsOfEligibleEvents = set()
        for eventGroup in groupsOfEvents:
            eligibleEvents.update(set(eventGroup[0]))
        for event in eligibleEvents:
            eventGroupsOfEligibleEvents.update(self.eventToEventGroups[event])
        eventChoiceToRemovedChoices = dict()
        eventToSolutionEventsDict = self.deltaEvaluator.get_event_to_solution_events_dict()
        unavailableTimesOfResource = {time for time in self.allTimes if
                                      resource_id in self.timeToUnavailableResourcesDict[time]}
        listOfTimes = list(self.instance.Times.IndividualTimes.keys())
        relevant_student_choices_without_resource = {studentChoiceResourcePair for studentChoiceResourcePair in self.studentChoiceResourcePairToPossibleEventGroups.keys() if studentChoiceResourcePair[1] != resource_id
                                                     and len(eventGroupsOfEligibleEvents.intersection(self.studentChoiceResourcePairToPossibleEventGroups[studentChoiceResourcePair])) >= 1}
        # events in that list can a) be completely unscheduled b) be scheduled already but have available space for resource c) be scheduled and fully booked
        eventToScoreDict = dict()
        for event_id in eligibleEvents:
            eventGroupsOfEventID = self.eventToEventGroups[event_id]
            relevant_student_choices_with_resource = {studentChoiceResourcePair for
                                                                          studentChoiceResourcePair in
                                                                          self.studentChoiceResourcePairToPossibleEventGroups.keys()
                                                                          if
                                                                          studentChoiceResourcePair[
                                                                              1] == resource_id}
            relevant_student_choices_with_resource_with_event = {studentChoiceResourcePair for
                                                                          studentChoiceResourcePair in
                                                                          self.studentChoiceResourcePairToPossibleEventGroups.keys()
                                                                          if
                                                                          studentChoiceResourcePair[
                                                                              1] == resource_id and len(eventGroupsOfEventID.intersection(self.studentChoiceResourcePairToPossibleEventGroups[
                                                                                  studentChoiceResourcePair])) > 0}
            relevant_student_choices_with_resource_without_event_overlaps = {studentChoiceResourcePair for
                                                                          studentChoiceResourcePair in
                                                                          self.studentChoiceResourcePairToPossibleEventGroups.keys()
                                                                          if
                                                                          studentChoiceResourcePair[
                                                                              1] == resource_id and len(eventGroupsOfEventID.intersection(self.studentChoiceResourcePairToPossibleEventGroups[
                                                                                  studentChoiceResourcePair])) == 0}
            balanceClassSizeConstraints = list()
            weightOfChoice = 1
            eventToScoreDict[event_id] = weightOfChoice * 1000
            isUnscheduled = True
            timeSlotsOccupiedByEvent = set()
            unscheduleableSubeventLength = 0
            for subevent in self.unscheduledEvents[event_id].keys():
                if self.scheduledEvents[event_id][subevent]:
                    isUnscheduled = False
                    if len(self.unscheduledEvents[event_id][subevent]["PossibleTimes"]) == 0:
                        continue
                    indexOfSolutionEventStartTime = listOfTimes.index(list(self.unscheduledEvents[event_id][subevent]["PossibleTimes"])[0])
                    timesInWhichSolutionEventIsActive = listOfTimes[indexOfSolutionEventStartTime:indexOfSolutionEventStartTime + subevent[0]]
                    timeSlotsOccupiedByEvent.update(timesInWhichSolutionEventIsActive)
                else:
                    if len(self.unscheduledEvents[event_id][subevent]["PossibleTimes"]) == 0:
                        continue
                    indexOfSolutionEventStartTime = listOfTimes.index(list(self.unscheduledEvents[event_id][subevent]["PossibleTimes"])[0])
                    timesInWhichSolutionEventIsActive = listOfTimes[indexOfSolutionEventStartTime:indexOfSolutionEventStartTime + subevent[0]]
                    timeSlotsOccupiedByEvent.update(timesInWhichSolutionEventIsActive)

            possibleTimeSlotsBySubevent = dict()
            for subevent in self.unscheduledEvents[event_id]:
                removedTimes = {time for time in self.allTimes if
                                resource_id in self.timeToUnavailableResourcesDict[time]}
                removedTimesFrozenSet = frozenset(removedTimes)
                if (subevent[0], removedTimesFrozenSet) not in self.intersectingTimeSlotsCache.keys():
                    self.intersectingTimeSlotsCache[(
                        subevent[0],
                        removedTimesFrozenSet)] = self.get_timeslots_intersection_based_on_event_length(
                        set(self.allTimes),
                        removedTimes,
                        subevent[0])
                possibleTimeSlotsBySubevent[subevent] = self.unscheduledEvents[event_id][subevent]["PossibleTimes"] - self.intersectingTimeSlotsCache[
                    (subevent[0], removedTimesFrozenSet)]
                if len(possibleTimeSlotsBySubevent[subevent]) == 0:
                    unscheduleableSubeventLength += subevent[0]
            studentResourcesOfEvent = {resource.Role for resource in
                                       self.instance.Events.IndividualEvents[event_id].EventResources.UnassignedResources if
                                       resource.ResourceType == XHSTTFileConstants.STUDENT}

            if not isUnscheduled:
                # score for being a scheduled event
                eventToScoreDict[event_id] += 500
                eventChoiceToRemovedChoices[event_id] = dict()
                # calculate score based on available student resources in event (e.g. choose the one with least resources assigned)
                noneDummyResourcesOfEvent = {role for role in
                                             eventToSolutionEventsDict[event_id][0][XHSTTFileConstants.RESOURCES] if
                                             eventToSolutionEventsDict[event_id][0][XHSTTFileConstants.RESOURCES][
                                                 role] != ILPConstants.DUMMY_RESOURCE}
                dummyResourcesOfEvent = {role for role in
                                         eventToSolutionEventsDict[event_id][0][XHSTTFileConstants.RESOURCES] if
                                         eventToSolutionEventsDict[event_id][0][XHSTTFileConstants.RESOURCES][
                                             role] == ILPConstants.DUMMY_RESOURCE}
                unassignedStudentResourceRoles = studentResourcesOfEvent.intersection(dummyResourcesOfEvent)
                assignedStudentResourceRoles = studentResourcesOfEvent.intersection(noneDummyResourcesOfEvent)
                # if no balance class size constraint exists an event that has more space for resources is preferable otherwise and event with least resources is preferable
                eventToScoreDict[event_id] -= unscheduleableSubeventLength * 1000

                for studentChoiceResourcePair in relevant_student_choices_with_resource_without_event_overlaps:
                    numberOfRemainingEventsInChoice = len(self.studentChoiceResourcePairToPossibleEventGroups[studentChoiceResourcePair])
                    unscheduleableEvents = 0
                    constraintID = studentChoiceResourcePair[0]
                    resource = studentChoiceResourcePair[1]
                    eventChoiceToRemovedChoices[event_id][(constraintID, resource)] = set()
                    for studentChoiceEventGroup in self.studentChoiceResourcePairToPossibleEventGroups[studentChoiceResourcePair]:
                        firstEventOfEventGroup = self.instance.Events.EventGroups[studentChoiceEventGroup].Events[0]
                        firstSubevent = list(self.unscheduledEvents[firstEventOfEventGroup].keys())[0]
                        resourcesAssignedToStudentChoiceEvent = {list(
                            self.unscheduledEvents[firstEventOfEventGroup][firstSubevent]["PossibleResources"][role])[0]
                                                                 for role in
                                                                 self.unscheduledEvents[firstEventOfEventGroup][
                                                                     firstSubevent]["PossibleResources"].keys() if
                                                                 len(self.unscheduledEvents[firstEventOfEventGroup][
                                                                         firstSubevent]["PossibleResources"][
                                                                         role]) == 1}
                        extraUnavailableTimesIfResourceAssigned = set()
                        if resource not in resourcesAssignedToStudentChoiceEvent:
                            extraUnavailableTimesIfResourceAssigned.update({time for time in self.allTimes if
                                                                            resource in
                                                                            self.timeToUnavailableResourcesDict[
                                                                                time]})
                        if event_id not in self.instance.Events.EventGroups[studentChoiceEventGroup].Events:
                            extraUnavailableTimesIfResourceAssigned.update(timeSlotsOccupiedByEvent)
                        for studentChoiceEvent in self.instance.Events.EventGroups[studentChoiceEventGroup].Events:
                            possibleTimeSlotsBySubeventForStudentChoiceEvent = dict()
                            for subeventStudentChoiceEvent in self.unscheduledEvents[studentChoiceEvent].keys():
                                unavailableTimeFrozenSet = frozenset(extraUnavailableTimesIfResourceAssigned)
                                if (subeventStudentChoiceEvent[0],
                                    unavailableTimeFrozenSet) not in self.intersectingTimeSlotsCache.keys():
                                    self.intersectingTimeSlotsCache[(subeventStudentChoiceEvent[0],
                                                                     unavailableTimeFrozenSet)] = self.get_timeslots_intersection_based_on_event_length(
                                        set(self.allTimes),
                                        extraUnavailableTimesIfResourceAssigned,
                                        subeventStudentChoiceEvent[0])
                                possibleTimeSlotsForRemainingEvent = \
                                    self.unscheduledEvents[studentChoiceEvent][subeventStudentChoiceEvent][
                                        "PossibleTimes"]
                                intersectingTimeslots = possibleTimeSlotsForRemainingEvent.intersection(
                                    self.intersectingTimeSlotsCache[
                                        (subeventStudentChoiceEvent[0], unavailableTimeFrozenSet)])
                                possibleTimeSlotsBySubeventForStudentChoiceEvent[
                                    subeventStudentChoiceEvent] = possibleTimeSlotsForRemainingEvent - intersectingTimeslots
                            if not self.is_event_schedulable(possibleTimeSlotsBySubeventForStudentChoiceEvent):
                                eventChoiceToRemovedChoices[event_id][(constraintID, resource)].add(studentChoiceEventGroup)
                                studentRoles = {resource.Role for resource in
                                           self.instance.Events.IndividualEvents[studentChoiceEvent].EventResources.UnassignedResources if
                                           resource.ResourceType == XHSTTFileConstants.STUDENT}
                                totalStudentResourcesOfEvent = len(studentRoles)
                                firstSubevent = list(self.unscheduledEvents[studentChoiceEvent].keys())[0]
                                studentsAlreadyAssignedToEvent = {
                                    list(self.unscheduledEvents[studentChoiceEvent][firstSubevent]["PossibleResources"][role])[0] for
                                    role in studentRoles if len(self.unscheduledEvents[studentChoiceEvent][firstSubevent]["PossibleResources"][role]) == 1}
                                resourcesInterestedInEventButNotAssignedYet = 0
                                for studentChoiceResourcePairWithoutResource in relevant_student_choices_without_resource:
                                    if studentChoiceResourcePairWithoutResource[1] in studentsAlreadyAssignedToEvent:
                                        continue
                                    if studentChoiceEventGroup not in self.studentChoiceResourcePairToPossibleEventGroups[
                                        studentChoiceResourcePairWithoutResource]:
                                        continue
                                    resourcesInterestedInEventButNotAssignedYet += 1
                                oversubscribedAmount = max(resourcesInterestedInEventButNotAssignedYet - (
                                            totalStudentResourcesOfEvent - len(studentsAlreadyAssignedToEvent)), 0)
                                eventToScoreDict[event_id] -= max(10000 - 100*oversubscribedAmount, 0)
                                unscheduleableEvents += 1
                    remainingChoicesIfUnschedulableAreRemoved = numberOfRemainingEventsInChoice - unscheduleableEvents
                    if remainingChoicesIfUnschedulableAreRemoved < self.studentChoiceIdToMinChoices[constraintID]:
                        eventToScoreDict[event_id] -= 1000000
                    else:
                        eventToScoreDict[event_id] -= 1000 * math.pow(2, max(1, 6 - remainingChoicesIfUnschedulableAreRemoved))
                removedEventGroups = set()
                for studentChoiceResourcePair in relevant_student_choices_with_resource_with_event:
                    removedEventGroups.update(self.originalStudentChoiceResourcePairToPossibleEventGroups[studentChoiceResourcePair] - self.eventToEventGroups[event_id])
                for studentChoiceResourcePair in relevant_student_choices_with_resource:
                    unscheduleableEvents = 0
                    numberOfRemainingEventsInChoice = len(self.studentChoiceResourcePairToPossibleEventGroups[studentChoiceResourcePair])
                    overlappingEventGroups = set(self.studentChoiceResourcePairToPossibleEventGroups[studentChoiceResourcePair]).intersection(removedEventGroups)
                    for studentChoiceEventGroup in overlappingEventGroups:
                        firstEventOfEventGroup = self.instance.Events.EventGroups[studentChoiceEventGroup].Events[0]
                        studentRoles = {resource.Role for resource in
                                        self.instance.Events.IndividualEvents[
                                            firstEventOfEventGroup].EventResources.UnassignedResources if
                                        resource.ResourceType == XHSTTFileConstants.STUDENT}
                        totalStudentResourcesOfEvent = len(studentRoles)
                        firstSubevent = list(self.unscheduledEvents[firstEventOfEventGroup].keys())[0]
                        studentsAlreadyAssignedToEvent = {
                            list(self.unscheduledEvents[firstEventOfEventGroup][firstSubevent]["PossibleResources"][role])[
                                0] for
                            role in studentRoles if len(
                                self.unscheduledEvents[firstEventOfEventGroup][firstSubevent]["PossibleResources"][
                                    role]) == 1}
                        resourcesInterestedInEventButNotAssignedYet = 0
                        for studentChoiceResourcePairWithoutResource in relevant_student_choices_without_resource:
                            if studentChoiceResourcePairWithoutResource[1] in studentsAlreadyAssignedToEvent:
                                continue
                            if firstEventOfEventGroup not in self.studentChoiceResourcePairToPossibleEventGroups[
                                studentChoiceResourcePairWithoutResource]:
                                continue
                            resourcesInterestedInEventButNotAssignedYet += 1
                        oversubscribedAmount = max(resourcesInterestedInEventButNotAssignedYet - (
                                totalStudentResourcesOfEvent - len(studentsAlreadyAssignedToEvent)), 0)
                        eventToScoreDict[event_id] -= max(10000 - 100 * oversubscribedAmount, 0)
                    unscheduleableEventGroups = len(overlappingEventGroups)
                    constraintID = studentChoiceResourcePair[0]
                    resource = studentChoiceResourcePair[1]
                    eventChoiceToRemovedChoices[event_id].setdefault((constraintID, resource), set())
                    eventChoiceToRemovedChoices[event_id][(constraintID, resource)].update(overlappingEventGroups)
                    for studentChoiceEventGroup in self.studentChoiceResourcePairToPossibleEventGroups[studentChoiceResourcePair]:
                        if studentChoiceEventGroup in overlappingEventGroups:
                            continue
                        firstEventOfEventGroup = self.instance.Events.EventGroups[studentChoiceEventGroup].Events[0]
                        firstSubevent = list(self.unscheduledEvents[firstEventOfEventGroup].keys())[0]
                        resourcesAssignedToStudentChoiceEvent = {list(
                            self.unscheduledEvents[firstEventOfEventGroup][firstSubevent]["PossibleResources"][role])[0]
                                                                 for role in
                                                                 self.unscheduledEvents[firstEventOfEventGroup][
                                                                     firstSubevent]["PossibleResources"].keys() if
                                                                 len(self.unscheduledEvents[firstEventOfEventGroup][
                                                                         firstSubevent]["PossibleResources"][
                                                                         role]) == 1}
                        extraUnavailableTimesIfResourceAssigned = set()
                        if resource not in resourcesAssignedToStudentChoiceEvent:
                            extraUnavailableTimesIfResourceAssigned.update({time for time in self.allTimes if
                                                                            resource in
                                                                            self.timeToUnavailableResourcesDict[
                                                                                time]})
                        if event_id not in self.instance.Events.EventGroups[studentChoiceEventGroup].Events:
                            extraUnavailableTimesIfResourceAssigned.update(timeSlotsOccupiedByEvent)
                        for studentChoiceEvent in self.instance.Events.EventGroups[studentChoiceEventGroup].Events:
                            possibleTimeSlotsBySubeventForStudentChoiceEvent = dict()
                            for subeventStudentChoiceEvent in self.unscheduledEvents[studentChoiceEvent].keys():
                                unavailableTimeFrozenSet = frozenset(extraUnavailableTimesIfResourceAssigned)
                                if (subeventStudentChoiceEvent[0],
                                    unavailableTimeFrozenSet) not in self.intersectingTimeSlotsCache.keys():
                                    self.intersectingTimeSlotsCache[(subeventStudentChoiceEvent[0],
                                                                     unavailableTimeFrozenSet)] = self.get_timeslots_intersection_based_on_event_length(
                                        set(self.allTimes),
                                        extraUnavailableTimesIfResourceAssigned,
                                        subeventStudentChoiceEvent[0])
                                possibleTimeSlotsForRemainingEvent = \
                                    self.unscheduledEvents[studentChoiceEvent][subeventStudentChoiceEvent][
                                        "PossibleTimes"]
                                intersectingTimeslots = possibleTimeSlotsForRemainingEvent.intersection(
                                    self.intersectingTimeSlotsCache[
                                        (subeventStudentChoiceEvent[0], unavailableTimeFrozenSet)])
                                possibleTimeSlotsBySubeventForStudentChoiceEvent[
                                    subeventStudentChoiceEvent] = possibleTimeSlotsForRemainingEvent - intersectingTimeslots
                            if not self.is_event_schedulable(possibleTimeSlotsBySubeventForStudentChoiceEvent):
                                eventChoiceToRemovedChoices[event_id][(constraintID, resource)].add(studentChoiceEventGroup)
                                studentRoles = {resource.Role for resource in
                                           self.instance.Events.IndividualEvents[studentChoiceEvent].EventResources.UnassignedResources if
                                           resource.ResourceType == XHSTTFileConstants.STUDENT}
                                totalStudentResourcesOfEvent = len(studentRoles)
                                firstSubevent = list(self.unscheduledEvents[studentChoiceEvent].keys())[0]
                                studentsAlreadyAssignedToEvent = {
                                    list(self.unscheduledEvents[studentChoiceEvent][firstSubevent]["PossibleResources"][role])[0] for
                                    role in studentRoles if len(self.unscheduledEvents[studentChoiceEvent][firstSubevent]["PossibleResources"][role]) == 1}
                                resourcesInterestedInEventButNotAssignedYet = 0
                                for studentChoiceResourcePairWithoutResource in relevant_student_choices_without_resource:
                                    if studentChoiceResourcePairWithoutResource[1] in studentsAlreadyAssignedToEvent:
                                        continue
                                    if studentChoiceEventGroup not in self.studentChoiceResourcePairToPossibleEventGroups[
                                        studentChoiceResourcePairWithoutResource]:
                                        continue
                                    resourcesInterestedInEventButNotAssignedYet += 1
                                oversubscribedAmount = max(resourcesInterestedInEventButNotAssignedYet - (
                                            totalStudentResourcesOfEvent - len(studentsAlreadyAssignedToEvent)), 0)
                                eventToScoreDict[event_id] -= max(10000 - 100*oversubscribedAmount, 0)
                                unscheduleableEvents += 1
                    remainingChoicesIfUnschedulableAreRemoved = numberOfRemainingEventsInChoice - unscheduleableEvents
                    if numberOfRemainingEventsInChoice - unscheduleableEvents < self.studentChoiceIdToMinChoices[constraintID]:
                        eventToScoreDict[event_id] -= 1000000
                    else:
                        eventToScoreDict[event_id] -= 1000 * math.pow(2, max(1, 6 - remainingChoicesIfUnschedulableAreRemoved))

                totalStudentResourcesOfEvent = len(studentResourcesOfEvent)
                firstSubevent = list(self.unscheduledEvents[event_id].keys())[0]
                studentsAlreadyAssignedToEvent = {list(self.unscheduledEvents[event_id][firstSubevent]["PossibleResources"][role])[0] for role in assignedStudentResourceRoles}
                resourcesInterestedInEventButNotAssignedYet = 0
                for studentChoiceResourcePairWithoutResource in relevant_student_choices_without_resource:
                    if studentChoiceResourcePairWithoutResource[1] in studentsAlreadyAssignedToEvent:
                        continue
                    eventGroupsOfEventID = self.eventToEventGroups[event_id]
                    if len(eventGroupsOfEventID.intersection(self.studentChoiceResourcePairToPossibleEventGroups[studentChoiceResourcePairWithoutResource])) == 0:
                        continue
                    resourcesInterestedInEventButNotAssignedYet += 1
                oversubscribedAmount = max(resourcesInterestedInEventButNotAssignedYet - (totalStudentResourcesOfEvent - len(studentsAlreadyAssignedToEvent)), 0)
                eventToScoreDict[event_id] -= 100 * oversubscribedAmount
                if len(unassignedStudentResourceRoles) == 0:
                    del eventToScoreDict[event_id]
                elif not self.is_event_schedulable(possibleTimeSlotsBySubevent):
                    eventToScoreDict[event_id] -= 1000000
                elif len(balanceClassSizeConstraints) == 0:
                    eventToScoreDict[event_id] += len(unassignedStudentResourceRoles)
                else:
                    eventToScoreDict[event_id] += 60 - len(assignedStudentResourceRoles)
            elif isUnscheduled:
                # check that each unscheduled subevent has some available timeslots that intersect with available timeslots of resource
                sortedUnscheduledSubEvents = sorted(list(self.unscheduledEvents[event_id].keys()),
                                                    key=lambda subevent: subevent[0], reverse=True)
                possibleTimeSlotsBySubevent = dict()
                unavailableTimesOfResourceFrozen = frozenset(unavailableTimesOfResource)
                for subevent in sortedUnscheduledSubEvents:
                    if (subevent[0], unavailableTimesOfResourceFrozen) not in self.intersectingTimeSlotsCache.keys():
                        self.intersectingTimeSlotsCache[(subevent[0],
                                                         unavailableTimesOfResourceFrozen)] = self.get_timeslots_intersection_based_on_event_length(
                            set(self.allTimes),
                            unavailableTimesOfResource,
                            subevent[0])
                    possibleTimeSlotsBySubevent[subevent] = self.unscheduledEvents[event_id][subevent]["PossibleTimes"] - self.intersectingTimeSlotsCache[(subevent[0], unavailableTimesOfResourceFrozen)]

                    # check that there are enough consecutive times available
                noneDummyResourcesOfEvent = {role for role in
                                             eventToSolutionEventsDict[event_id][0][XHSTTFileConstants.RESOURCES] if
                                             eventToSolutionEventsDict[event_id][0][XHSTTFileConstants.RESOURCES][
                                                 role] != ILPConstants.DUMMY_RESOURCE}
                dummyResourcesOfEvent = {role for role in
                                         eventToSolutionEventsDict[event_id][0][XHSTTFileConstants.RESOURCES] if
                                         eventToSolutionEventsDict[event_id][0][XHSTTFileConstants.RESOURCES][
                                             role] == ILPConstants.DUMMY_RESOURCE}
                unassignedStudentResourceRoles = studentResourcesOfEvent.intersection(dummyResourcesOfEvent)
                assignedStudentResourceRoles = studentResourcesOfEvent.intersection(noneDummyResourcesOfEvent)
                eventChoiceToRemovedChoices.setdefault(event_id, dict())
                removedEventGroups = set()
                for studentChoiceResourcePair in relevant_student_choices_with_resource_with_event:
                    removedEventGroups.update(
                        self.originalStudentChoiceResourcePairToPossibleEventGroups[studentChoiceResourcePair] - {event_id})
                # includes those with and without event
                for studentChoiceResourcePair in relevant_student_choices_with_resource:
                    numberOfRemainingEventsInChoice = len(
                        self.studentChoiceResourcePairToPossibleEventGroups[studentChoiceResourcePair])
                    overlappingEventGroups = set(
                        self.studentChoiceResourcePairToPossibleEventGroups[studentChoiceResourcePair]).intersection(
                        removedEventGroups)
                    for studentChoiceEventGroup in overlappingEventGroups:
                        firstEventOfEventGroup = self.instance.Events.EventGroups[studentChoiceEventGroup].Events[0]
                        studentRoles = {resource.Role for resource in
                                        self.instance.Events.IndividualEvents[
                                            firstEventOfEventGroup].EventResources.UnassignedResources if
                                        resource.ResourceType == XHSTTFileConstants.STUDENT}
                        totalStudentResourcesOfEvent = len(studentRoles)
                        firstSubevent = list(self.unscheduledEvents[firstEventOfEventGroup].keys())[0]
                        studentsAlreadyAssignedToEvent = {
                            list(self.unscheduledEvents[firstEventOfEventGroup][firstSubevent]["PossibleResources"][role])[
                                0] for
                            role in studentRoles if len(
                                self.unscheduledEvents[firstEventOfEventGroup][firstSubevent]["PossibleResources"][
                                    role]) == 1}
                        resourcesInterestedInEventButNotAssignedYet = 0
                        for studentChoiceResourcePairWithoutResource in relevant_student_choices_without_resource:
                            if studentChoiceResourcePairWithoutResource[1] in studentsAlreadyAssignedToEvent:
                                continue
                            if studentChoiceEventGroup not in self.studentChoiceResourcePairToPossibleEventGroups[
                                studentChoiceResourcePairWithoutResource]:
                                continue
                            resourcesInterestedInEventButNotAssignedYet += 1
                        oversubscribedAmount = max(resourcesInterestedInEventButNotAssignedYet - (
                                totalStudentResourcesOfEvent - len(studentsAlreadyAssignedToEvent)), 0)
                        eventToScoreDict[event_id] -= max(10000 - 100 * oversubscribedAmount, 0)
                    unscheduleableEventGroups = len(overlappingEventGroups)
                    constraintID = studentChoiceResourcePair[0]
                    resource = studentChoiceResourcePair[1]
                    eventChoiceToRemovedChoices[event_id].setdefault((constraintID, resource), set())
                    eventChoiceToRemovedChoices[event_id][(constraintID, resource)].update(overlappingEventGroups)

                    remainingChoicesIfUnschedulableAreRemoved = numberOfRemainingEventsInChoice - unscheduleableEventGroups
                    if numberOfRemainingEventsInChoice - unscheduleableEventGroups < self.studentChoiceIdToMinChoices[constraintID]:
                        eventToScoreDict[event_id] -= 1000000
                    else:
                        eventToScoreDict[event_id] -= 1000 * math.pow(2, max(1, 6 - remainingChoicesIfUnschedulableAreRemoved))


                totalStudentResourcesOfEvent = len(studentResourcesOfEvent)
                firstSubevent = list(self.unscheduledEvents[event_id].keys())[0]
                studentsAlreadyAssignedToEvent = {
                    list(self.unscheduledEvents[event_id][firstSubevent]["PossibleResources"][role])[0] for role in
                    assignedStudentResourceRoles}
                resourcesInterestedInEventButNotAssignedYet = 0
                for studentChoiceResourcePairWithoutResource in relevant_student_choices_without_resource:
                    if studentChoiceResourcePairWithoutResource[1] in studentsAlreadyAssignedToEvent:
                        continue
                    eventGroupsOfEventID = self.eventToEventGroups[event_id]
                    if len(eventGroupsOfEventID.intersection(self.studentChoiceResourcePairToPossibleEventGroups[studentChoiceResourcePairWithoutResource])) == 0:
                        continue
                    resourcesInterestedInEventButNotAssignedYet += 1
                oversubscribedAmount = max(resourcesInterestedInEventButNotAssignedYet - (
                            totalStudentResourcesOfEvent - len(studentsAlreadyAssignedToEvent)), 0)
                eventToScoreDict[event_id] -= 100 * oversubscribedAmount
                # cant choose this event_id since one of the subevents is not schedulable (unless no event can be scheduled clash free anyways)
                eventToScoreDict[event_id] -= unscheduleableSubeventLength * 1000
                if not self.is_event_schedulable(possibleTimeSlotsBySubevent):
                    eventToScoreDict[event_id] -= 1000000
                if len(balanceClassSizeConstraints) == 0:
                    eventToScoreDict[event_id] += len(studentResourcesOfEvent)
                else:
                    eventToScoreDict[event_id] += 60
            else:
                del eventToScoreDict[event_id]
        if len(eventToScoreDict.keys()) == 0:
            return None

        eventGroupToScoreDict = dict()
        eventGroupIndicesToRemove = set()
        for eventGroupIndex in range(len(groupsOfEvents)):
            eventGroupToScoreDict[eventGroupIndex] = 0
            for event in groupsOfEvents[eventGroupIndex][0]:
                if event not in eventToScoreDict:
                    eventGroupIndicesToRemove.add(eventGroupIndex)
                    break
                eventGroupToScoreDict[eventGroupIndex] += eventToScoreDict[event] * self.instance.Events.IndividualEvents[event].Duration
        groupsOfEventsAsDict = dict()
        for i in range(len(groupsOfEvents)):
            groupsOfEventsAsDict[i] = groupsOfEvents[i]
        for i in range(len(eventGroupToScoreDict) - 1, -1, -1):
            if i in eventGroupIndicesToRemove:
                del eventGroupToScoreDict[i]
                del groupsOfEventsAsDict[i]
        if len(eventGroupToScoreDict) == 0:
            return None
        bestEventGroupIndex = max(eventGroupToScoreDict, key=eventGroupToScoreDict.get)
        for bestEvent in groupsOfEventsAsDict[bestEventGroupIndex][0]:
            if doAssign and bestEvent is not None:
                self.assign_student_resource_to_event_with_multiple_student_roles(bestEvent, resource_id)
            if bestEvent in eventChoiceToRemovedChoices:
                for constraintID, resource in eventChoiceToRemovedChoices[bestEvent].keys():
                    if len(eventChoiceToRemovedChoices[bestEvent][(constraintID, resource)]) == 0:
                        continue
                    for eventGroup in eventChoiceToRemovedChoices[bestEvent][(constraintID, resource)]:
                        if eventGroup in self.studentChoiceResourcePairToPossibleEventGroups[(constraintID, resource)]:
                            self.studentChoiceResourcePairToPossibleEventGroups[(constraintID, resource)].remove(eventGroup)
                    if len(self.studentChoiceResourcePairToPossibleEventGroups[(constraintID, resource)]) <= self.studentChoiceIdToMinChoices[constraintID]:
                        for eventGroup in set(self.studentChoiceResourcePairToPossibleEventGroups[(constraintID, resource)]):
                            self.assign_student_resource_to_event_group_with_multiple_student_roles(eventGroup, resource)
        return groupsOfEvents[bestEventGroupIndex]

    def get_next_resource_to_schedule(self, completedResources: set, strategy="leastRemaining") -> str:
        currentSelectedResource = None
        resourceToSolutionEventsDict = self.deltaEvaluator.get_resource_to_solution_events_dict()
        totalTimes = len(self.instance.Times.IndividualTimes.keys())
        if strategy == "leastRemaining":
            currentLeastRemaining = math.inf
        elif strategy == "mostRestrictedEvent":
            currentMostRestricted = math.inf
        elif strategy == "mostRestrictedStudentChoices":
            currentMostRestricted = 0
            resourceToStudentChoiceScore = dict()
            for (constraintID, resource) in self.studentChoiceResourcePairToPossibleEventGroups.keys():
                resourceToStudentChoiceScore.setdefault(resource, 0)
                resourceToStudentChoiceScore[resource] += math.pow(2, max(1, 6 - len(self.studentChoiceResourcePairToPossibleEventGroups[(constraintID, resource)])))
        for resource_id in self.instance.Resources.IndividualResources.keys():
            resource = self.instance.Resources.IndividualResources[resource_id]
            if resource_id in completedResources or resource.Type == "EventGroupTokens":
                continue
            if strategy == "leastRemaining":
                totalAvailableHours = totalTimes - len([time for time in self.timeToUnavailableResourcesDict.keys() if
                                                        resource_id in self.timeToUnavailableResourcesDict[time]])
                if totalAvailableHours < currentLeastRemaining:
                    currentSelectedResource = resource_id
                    currentLeastRemaining = totalAvailableHours
            elif strategy == "mostRestrictedEvent":
                if resource_id in resourceToSolutionEventsDict.keys():
                    for solutionEvent in resourceToSolutionEventsDict[resource_id]:
                        event = solutionEvent[XHSTTFileConstants.ID]
                        score = float(len(self.unscheduledEvents[event[0]][event[1]]["PossibleTimes"])) + 0.5 * float(len([role for role in self.unscheduledEvents[event[0]][event[1]]["PossibleResources"].keys() if len(self.unscheduledEvents[event[0]][event[1]]["PossibleResources"][role]) == 1]))
                        if len(self.unscheduledEvents[event[0]][event[1]]["PossibleTimes"]) > 1 and score < currentMostRestricted:
                            currentSelectedResource = resource_id
                            currentMostRestricted = score
                        elif len(self.unscheduledEvents[event[0]][event[1]]["PossibleTimes"]) <= 1 and currentMostRestricted == math.inf:
                            currentSelectedResource = resource_id
                else:
                    if currentMostRestricted == math.inf:
                        currentSelectedResource = resource_id
            elif strategy == "mostRestrictedStudentChoices":
                if resource_id in resourceToStudentChoiceScore.keys():
                    if resourceToStudentChoiceScore[resource_id] > currentMostRestricted:
                        currentMostRestricted = resourceToStudentChoiceScore[resource_id]
                        currentSelectedResource = resource_id
                else:
                    if currentMostRestricted == 0:
                        currentSelectedResource = resource_id

        return currentSelectedResource

    def find_optimal_subevent_distributions(self, eventToPossibleSubeventsByDurationDict, considerSoftConstraints=False, considerHardConstraints=False) -> dict:
        solution_cache = dict()
        eventIDToSolutionEventLengths = dict()
        found_infeasible_event = False
        for event_id in self.instance.Events.IndividualEvents.keys():
            if event_id not in eventToPossibleSubeventsByDurationDict:
                continue
            relevantSplitEventsConstraints = [constraint for constraint in self.eventToSplitEventsDict[event_id]]
            if event_id not in self.infeasible_events or not considerSoftConstraints and not considerHardConstraints:
                relevantDistributeSplitEventsConstraints = []
            elif considerSoftConstraints and not considerHardConstraints:
                relevantDistributeSplitEventsConstraints = [constraint for constraint in self.eventToDistributeSplitEventsDict[event_id] if not constraint[XHSTTConstraintConstants.REQUIRED]]
            elif not considerSoftConstraints and considerHardConstraints:
                relevantDistributeSplitEventsConstraints = [constraint for constraint in self.eventToDistributeSplitEventsDict[event_id] if constraint[XHSTTConstraintConstants.REQUIRED]]

            else:
                relevantDistributeSplitEventsConstraints = [constraint for constraint in self.eventToDistributeSplitEventsDict[event_id]]
            for constraint in self.instance.Constraints[XHSTTConstraintConstants.PREFER_TIMES_CONSTRAINT]:
                if not constraint[XHSTTConstraintConstants.REQUIRED] and not considerSoftConstraints:
                    continue
                if constraint[XHSTTConstraintConstants.REQUIRED] and not considerHardConstraints:
                    continue
                events = constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS]
                for event_group in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
                    events += self.instance.Events.EventGroups[event_group].Events
                if event_id not in events:
                    continue
                if XHSTTFileConstants.TIMES in constraint.keys():
                    constraintTimes = set(constraint[XHSTTFileConstants.TIMES])
                    for timeGroup in constraint[XHSTTFileConstants.TIME_GROUPS]:
                        if timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT] in self.instance.Times.TimeGroups.keys():
                            constraintTimes.update(
                                set(self.instance.Times.TimeGroups[
                                        timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]].Times))
                        elif timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT] in self.instance.Times.Days.keys():
                            constraintTimes.update(
                                set(self.instance.Times.Days[timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]].Times))
                else:
                    constraintTimes = set()
                constraint_copy = copy.deepcopy(constraint)
                constraint_copy[XHSTTConstraintConstants.MINIMUM] = 0
                constraint_copy[XHSTTConstraintConstants.MAXIMUM] = len(constraintTimes)
                relevantDistributeSplitEventsConstraints.append(constraint_copy)

            event = self.instance.Events.IndividualEvents[event_id]
            durations = [d for d in eventToPossibleSubeventsByDurationDict[event_id].keys() if eventToPossibleSubeventsByDurationDict[event_id][d][0] + eventToPossibleSubeventsByDurationDict[event_id][d][1] != 0]
            min_counts = [eventToPossibleSubeventsByDurationDict[event_id][d][0] for d in durations if eventToPossibleSubeventsByDurationDict[event_id][d][0] + eventToPossibleSubeventsByDurationDict[event_id][d][1] != 0]
            max_counts = [eventToPossibleSubeventsByDurationDict[event_id][d][1] for d in durations if eventToPossibleSubeventsByDurationDict[event_id][d][0] + eventToPossibleSubeventsByDurationDict[event_id][d][1] != 0]

            splitEventIDs = [(constraint[XHSTTConstraintConstants.WEIGHT], constraint[XHSTTConstraintConstants.REQUIRED], constraint[XHSTTConstraintConstants.MINIMUM_DURATION], constraint[XHSTTConstraintConstants.MAXIMUM_DURATION], constraint[XHSTTConstraintConstants.MINIMUM_AMOUNT], constraint[XHSTTConstraintConstants.MAXIMUM_AMOUNT]) for constraint in relevantSplitEventsConstraints]
            distributeSplitEventIDs = [(constraint[XHSTTConstraintConstants.WEIGHT], constraint[XHSTTConstraintConstants.REQUIRED], constraint[XHSTTFileConstants.DURATION], constraint[XHSTTConstraintConstants.MINIMUM], constraint[XHSTTConstraintConstants.MAXIMUM]) for constraint in relevantDistributeSplitEventsConstraints]
            if (tuple(min_counts), tuple(max_counts), frozenset(splitEventIDs), frozenset(distributeSplitEventIDs)) in solution_cache:
                eventIDToSolutionEventLengths[event_id] = solution_cache[(tuple(min_counts), tuple(max_counts), frozenset(splitEventIDs), frozenset(distributeSplitEventIDs))]
                continue
            # Generate all possible combinations of event counts within the given bounds
            possible_combinations = [
                range(min_counts[i], max_counts[i] + 1) for i in range(len(durations))
            ]
            best_combination = None
            min_score = math.inf
            for combination in product(*possible_combinations):
                if sum(d * count for d, count in zip(durations, combination)) == int(event.Duration):
                    score = 0
                    for constraint in relevantSplitEventsConstraints:
                        addedScore = 0
                        totalCount = 0
                        for d, count in zip(durations, combination):
                            totalCount += count
                            if d > int(constraint[XHSTTConstraintConstants.MAXIMUM_DURATION]) or d < int(constraint[XHSTTConstraintConstants.MINIMUM_DURATION]):
                                addedScore += count
                        addedScore += (max(int(constraint[XHSTTConstraintConstants.MINIMUM_AMOUNT]) - totalCount, 0) +
                             max(totalCount - int(constraint[XHSTTConstraintConstants.MAXIMUM_AMOUNT]), 0))
                        addedScore *= int(constraint[XHSTTConstraintConstants.WEIGHT])
                        if constraint[XHSTTConstraintConstants.REQUIRED]:
                            addedScore *= 10000
                        score += addedScore

                    for constraint in relevantDistributeSplitEventsConstraints:
                        for d, count in zip(durations, combination):
                            if d != int(constraint[XHSTTFileConstants.DURATION]):
                                continue
                            if count < int(constraint[XHSTTConstraintConstants.MINIMUM]):
                                addedScore = (int(constraint[XHSTTConstraintConstants.MINIMUM]) - count) * int(constraint[XHSTTConstraintConstants.WEIGHT])
                                if constraint[XHSTTConstraintConstants.REQUIRED]:
                                    addedScore *= 10000
                                score += addedScore
                            elif count > int(constraint[XHSTTConstraintConstants.MAXIMUM]):
                                addedScore = (count - int(constraint[XHSTTConstraintConstants.MAXIMUM])) * int(constraint[XHSTTConstraintConstants.WEIGHT])
                                if constraint[XHSTTConstraintConstants.REQUIRED]:
                                    addedScore *= 10000
                                score += addedScore

                    square_sum = sum((d ** 2) * count for d, count in zip(durations, combination)) * 0.00001
                    minimizeSquareLengthOfSubevents = False
                    if minimizeSquareLengthOfSubevents:
                        score += square_sum
                    else:
                        score -= square_sum
                    if score < min_score:
                        min_score = score
                        best_combination = combination

            if best_combination is None:
                if self.output:
                    print("NO VALID DISTRIBUTION FOUND TRY AGAIN WITH SOFT CONSTRAINTS RELAXED")
                self.infeasible_events.add(event_id)
                found_infeasible_event = True

                # Build result as a list of event durations
            if best_combination is not None:
                result = []
                for d, count in zip(durations, best_combination):
                    result.extend([d] * count)
                eventIDToSolutionEventLengths[event_id] = result
                solution_cache[(tuple(min_counts), tuple(max_counts))] = result
        if found_infeasible_event:
            return None
        return eventIDToSolutionEventLengths