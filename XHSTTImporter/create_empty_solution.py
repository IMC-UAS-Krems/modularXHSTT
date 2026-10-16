import copy
import io
import random
import networkx as nx
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

def delete_all_time_and_resource_assignments_in_solution(instance: Instance, solutionData: dict):
    eventToSubeventsDict = dict()
    for eventID, subevent in solutionData[XHSTTFileConstants.EVENTS].keys():
        eventToSubeventsDict.setdefault(eventID, set()).add(subevent)

    for eventID, event in instance.Events.IndividualEvents.items():
        for subevent in eventToSubeventsDict.get(eventID, set()):
            if event.Time is None:
                solutionData[XHSTTFileConstants.EVENTS][eventID, subevent][XHSTTFileConstants.TIME] = ILPConstants.DUMMY_TIME
            for resource in event.EventResources.UnassignedResources:
                solutionData[XHSTTFileConstants.EVENTS][eventID, subevent][XHSTTFileConstants.RESOURCES][resource.Role] = ILPConstants.DUMMY_RESOURCE

def create_empty_solution(instance: Instance, seed: int=42) -> dict:
    random.seed(seed)
    returned_solution_dict = dict()
    event_dict = dict()
    eventToDistributeSplitEventsConstraintDict = dict()
    for constraint in instance.Constraints[XHSTTConstraintConstants.DISTRIBUTE_SPLIT_EVENTS_CONSTRAINT]:
        for event in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS]:
            eventToDistributeSplitEventsConstraintDict.setdefault(event, list())
            eventToDistributeSplitEventsConstraintDict[event].append((int(constraint[XHSTTFileConstants.DURATION]),
                                                                      int(constraint[XHSTTConstraintConstants.MINIMUM]),
                                                                      int(constraint[
                                                                              XHSTTConstraintConstants.MAXIMUM])))
    for event_id in instance.Events.IndividualEvents.keys():
        if event_id.endswith('_max_requirement') or event_id.endswith('_min_requirement'):
            mainEventId = event_id.split('_')[0] + '_' + event_id.split('_')[1]
            eventDurationToSubeventAmountDict = dict()
            if mainEventId in eventToDistributeSplitEventsConstraintDict:
                remainingDuration = instance.Events.IndividualEvents[event_id].Duration
                for subeventpossibilities in sorted(eventToDistributeSplitEventsConstraintDict[mainEventId], key=lambda constraint: int(constraint[0]), reverse=True):
                    duration = subeventpossibilities[0]
                    if duration * subeventpossibilities[2] <= remainingDuration:
                        maximumPossibleAmount = subeventpossibilities[2]
                    else:
                        maximumPossibleAmount = remainingDuration // duration
                    eventDurationToSubeventAmountDict[duration] = maximumPossibleAmount
                    remainingDuration -= duration * maximumPossibleAmount
            elif int(instance.Events.IndividualEvents[mainEventId].Duration) == 2:
                eventDurationToSubeventAmountDict[2] = 1
            elif int(instance.Events.IndividualEvents[mainEventId].Duration) == 1:
                eventDurationToSubeventAmountDict[1] = 1
            else:
                print("Attempted to process event with duration more than 2 that is not split into subevents")
            for duration in eventDurationToSubeventAmountDict.keys():
                for i in range(eventDurationToSubeventAmountDict[duration]):
                    event = dict()
                    event[XHSTTFileConstants.DURATION] = int(instance.Events.IndividualEvents[event_id].Duration)
                    subevent = (duration, i)
                    event_dict[event_id, subevent] = dict()
                    currently_processed_subevent = event_dict[event_id, subevent]
                    currently_processed_subevent[XHSTTFileConstants.DURATION] = duration
                    currently_processed_subevent[XHSTTFileConstants.ID] = (event_id, subevent)
                    currently_processed_subevent[XHSTTFileConstants.TIME] = list(instance.Times.IndividualTimes.keys())[0]
                    currently_processed_subevent[SolutionDataConstants.DELETE_SUBEVENTS] = False
                    currently_processed_subevent[XHSTTFileConstants.NAME] = event_id
                    currently_processed_subevent[XHSTTFileConstants.RESOURCES] = dict()
        else:
            eventDurationToSubeventAmountDict = dict()
            if event_id in eventToDistributeSplitEventsConstraintDict:
                remainingDuration = instance.Events.IndividualEvents[event_id].Duration
                for subeventpossibilities in sorted(eventToDistributeSplitEventsConstraintDict[event_id],
                                                    key=lambda constraint: int(constraint[0]), reverse=True):
                    duration = subeventpossibilities[0]
                    if duration * subeventpossibilities[2] <= remainingDuration:
                        maximumPossibleAmount = subeventpossibilities[2]
                    else:
                        maximumPossibleAmount = remainingDuration // duration
                    eventDurationToSubeventAmountDict[duration] = maximumPossibleAmount
                    remainingDuration -= duration * maximumPossibleAmount
            elif int(instance.Events.IndividualEvents[event_id].Duration) == 2:
                eventDurationToSubeventAmountDict[2] = 1
            elif int(instance.Events.IndividualEvents[event_id].Duration) == 1:
                eventDurationToSubeventAmountDict[1] = 1
            else:
                print("Attempted to process event with duration more than 2 that is not split into subevents")
            for duration in eventDurationToSubeventAmountDict.keys():
                for i in range(eventDurationToSubeventAmountDict[duration]):
                    event = dict()
                    event[XHSTTFileConstants.DURATION] = int(instance.Events.IndividualEvents[event_id].Duration)
                    subevent = (duration, i)
                    event_dict[event_id, subevent] = dict()
                    currently_processed_subevent = event_dict[event_id, subevent]
                    currently_processed_subevent[XHSTTFileConstants.DURATION] = duration
                    currently_processed_subevent[XHSTTFileConstants.ID] = (event_id, subevent)
                    currently_processed_subevent[XHSTTFileConstants.TIME] = list(instance.Times.IndividualTimes.keys())[
                        0]
                    currently_processed_subevent[SolutionDataConstants.DELETE_SUBEVENTS] = False
                    currently_processed_subevent[XHSTTFileConstants.NAME] = event_id
                    currently_processed_subevent[XHSTTFileConstants.RESOURCES] = dict()

                # for eventResource in instance.Events.IndividualEvents[event_id].EventResources.UnassignedResources:
                #     currently_processed_subevent[XHSTTFileConstants.RESOURCES][eventResource.Role] = ILPConstants.DUMMY_RESOURCE
                # for eventResource in instance.Events.IndividualEvents[event_id].EventResources.AssignedResources:
                #     currently_processed_subevent[XHSTTFileConstants.RESOURCES][eventResource.Role] = eventResource.Reference


    returned_solution_dict[XHSTTFileConstants.EVENTS] = event_dict
    returned_solution_dict[SolutionDataConstants.VALIDATOR_OBJECTIVE] = math.inf
    return returned_solution_dict
def create_independent_set_instance(instance: Instance, solutionWithUnassaginedResourcesAssigned: dict, seed: int=42) -> dict:
    random.seed(seed)
    returned_solution_dict = dict()
    event_dict = dict()
    possible_times_by_event_length = dict()
    eventToDistributeSplitEventsConstraintDict = dict()
    g = nx.Graph()
    nodeCount = 1
    for constraint in instance.Constraints[XHSTTConstraintConstants.DISTRIBUTE_SPLIT_EVENTS_CONSTRAINT]:
        for event in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS]:
            eventToDistributeSplitEventsConstraintDict.setdefault(event, list())
            eventToDistributeSplitEventsConstraintDict[event].append((int(constraint[XHSTTFileConstants.DURATION]),
                                                                      int(constraint[XHSTTConstraintConstants.MINIMUM]),
                                                                      int(constraint[XHSTTConstraintConstants.MAXIMUM])))
    for day in instance.Times.Days.keys():
        for i in range(1, 6):
            possible_times_by_event_length.setdefault(i, list())
            if i == 1:
                possible_times_by_event_length[i] += instance.Times.Days[day].Times
                # possible_times_by_event_length[i].append(instance.Times.Days[day].Times[0])
            else:
                possible_times_by_event_length[i] += instance.Times.Days[day].Times[:-(i-1)]
                # possible_times_by_event_length[i].append(instance.Times.Days[day].Times[0])
    for event_id in instance.Events.IndividualEvents.keys():
        if event_id.endswith('_max_requirement') or event_id.endswith('_min_requirement'):
            durationOfMainEvent = int(instance.Events.IndividualEvents[event_id[:-16]].Duration)
            durationOfRequEvent = int(instance.Events.IndividualEvents[event_id].Duration)
            amountOfEventsRequ = durationOfRequEvent // durationOfMainEvent
            for i in range(amountOfEventsRequ):
                event = dict()
                event[XHSTTFileConstants.DURATION] = durationOfMainEvent
                subevent = (durationOfMainEvent, i)
                event_dict[event_id, subevent] = dict()
                currently_processed_subevent = event_dict[event_id, subevent]
                currently_processed_subevent[XHSTTFileConstants.DURATION] = durationOfMainEvent
                currently_processed_subevent[XHSTTFileConstants.ID] = (event_id, subevent)
                # currently_processed_subevent[XHSTTFileConstants.TIME] = None
                # currently_processed_subevent[XHSTTFileConstants.TIME] = list(instance.Times.IndividualTimes.keys())[0]
                if (event_id[:-16] + '_max_requirement', (subevent[0], 0)) in event_dict.keys() and XHSTTFileConstants.TIME in event_dict[event_id[:-16] + '_max_requirement', (subevent[0], 0)].keys():
                    currently_processed_subevent[XHSTTFileConstants.TIME] = event_dict[event_id[:-16] + '_max_requirement', (subevent[0], 0)][XHSTTFileConstants.TIME]
                elif (event_id[:-16] + '_min_requirement', (subevent[0], 0)) in event_dict.keys() and XHSTTFileConstants.TIME in event_dict[event_id[:-16] + '_min_requirement', (subevent[0], 0)].keys():
                    currently_processed_subevent[XHSTTFileConstants.TIME] = \
                    event_dict[event_id[:-16] + '_min_requirement', (subevent[0], 0)][XHSTTFileConstants.TIME]
                elif (event_id[:-16], (event_id[:-16], subevent)) in event_dict.keys() and XHSTTFileConstants.TIME in event_dict[event_id[:-16], subevent].keys():
                    currently_processed_subevent[XHSTTFileConstants.TIME] = \
                    event_dict[event_id[:-16], subevent][XHSTTFileConstants.TIME]
                else:
                    fixedResourcesOfEvent = {eventResource.Reference for eventResource in instance.Events.IndividualEvents[event_id[:-16]].EventResources.AssignedResources}
                    possibleTimesWithoutClashes = copy.deepcopy(possible_times_by_event_length[int(event[XHSTTFileConstants.DURATION])])
                    clashesByTime = dict()
                    for otherEvent in event_dict.keys():
                        if otherEvent == (event_id, subevent) or XHSTTFileConstants.TIME not in event_dict[otherEvent].keys():
                            continue
                        fixedResourcesOfOtherEvent = {eventResource.Reference for eventResource in instance.Events.IndividualEvents[otherEvent[0]].EventResources.AssignedResources}
                        if fixedResourcesOfEvent.isdisjoint(fixedResourcesOfOtherEvent):
                            continue
                        commonResourceAmount = len(fixedResourcesOfEvent.intersection(fixedResourcesOfOtherEvent))
                        indexOfStartTimeOfOtherEvent = list(instance.Times.IndividualTimes.keys()).index(event_dict[otherEvent][XHSTTFileConstants.TIME])
                        durationOfOtherEvent = int(instance.Events.IndividualEvents[otherEvent[0]].Duration)
                        for time in list(instance.Times.IndividualTimes.keys())[indexOfStartTimeOfOtherEvent - int(event[XHSTTFileConstants.DURATION]) + 1:indexOfStartTimeOfOtherEvent + durationOfOtherEvent]:
                            if time not in possible_times_by_event_length[int(event[XHSTTFileConstants.DURATION])]:
                                continue
                            clashesByTime.setdefault(time, 0)
                            if (time == list(instance.Times.IndividualTimes.keys())[indexOfStartTimeOfOtherEvent-1] or
                                    time == list(instance.Times.IndividualTimes.keys())[indexOfStartTimeOfOtherEvent +
                                    durationOfOtherEvent-1] and int(event[XHSTTFileConstants.DURATION]) == 2) or int(event[XHSTTFileConstants.DURATION]) == 1:
                                clashesByTime[time] += commonResourceAmount
                            else:
                                clashesByTime[time] += commonResourceAmount*2
                            if time in possibleTimesWithoutClashes:
                                possibleTimesWithoutClashes.remove(time)
                    # if len(possibleTimesWithoutClashes) > 0:
                    #     currently_processed_subevent[XHSTTFileConstants.TIME] = random.choice(
                    #         possibleTimesWithoutClashes)
                    # else:
                    #     minAddedClashes = min(clashesByTime.values())
                    #     timesWithMinimumClashes = [time for time in clashesByTime.keys() if
                    #                                clashesByTime[time] == minAddedClashes]
                    #     minClashesCounter += minAddedClashes
                    #     currently_processed_subevent[XHSTTFileConstants.TIME] = random.choice(timesWithMinimumClashes)
                currently_processed_subevent[SolutionDataConstants.DELETE_SUBEVENTS] = False
                currently_processed_subevent[XHSTTFileConstants.NAME] = event_id
                currently_processed_subevent[XHSTTFileConstants.RESOURCES] = dict()
                # for eventResource in instance.Events.IndividualEvents[event_id].EventResources.UnassignedResources:
                #     currently_processed_subevent[XHSTTFileConstants.RESOURCES][eventResource.Role] = ILPConstants.DUMMY_RESOURCE
                # for eventResource in instance.Events.IndividualEvents[event_id].EventResources.AssignedResources:
                #     currently_processed_subevent[XHSTTFileConstants.RESOURCES][eventResource.Role] = eventResource.Reference
        else:
            if event_id in eventToDistributeSplitEventsConstraintDict:
                eventsOfDurationTwo = [subeventpossibilities[2] for subeventpossibilities in
                                       eventToDistributeSplitEventsConstraintDict[event_id] if
                                       subeventpossibilities[0] == 2][0]
                eventsOfDurationOne = [subeventpossibilities[1] for subeventpossibilities in
                                       eventToDistributeSplitEventsConstraintDict[event_id] if
                                       subeventpossibilities[0] == 1][0]
            elif int(instance.Events.IndividualEvents[event_id].Duration) == 2:
                eventsOfDurationTwo = 1
                eventsOfDurationOne = 0
            elif int(instance.Events.IndividualEvents[event_id].Duration) == 1:
                eventsOfDurationTwo = 0
                eventsOfDurationOne = 1
            else:
                print("Attempted to process event with duration more than 2 that is not split into subevents")
                eventsOfDurationTwo = 0
                eventsOfDurationOne = 0
            for i in range(eventsOfDurationTwo):
                event = dict()
                event[XHSTTFileConstants.DURATION] = instance.Events.IndividualEvents[event_id].Duration
                subevent = (2, i)
                event_dict[event_id, subevent] = dict()
                currently_processed_subevent = event_dict[event_id, subevent]
                currently_processed_subevent[XHSTTFileConstants.DURATION] = event[XHSTTFileConstants.DURATION]
                currently_processed_subevent[XHSTTFileConstants.ID] = (event_id, subevent)
                startNodeCount = nodeCount
                for time_id in range(len(possible_times_by_event_length[2])):
                    time = possible_times_by_event_length[2][time_id]
                    for preferResourceConstraint in instance.Constraints[XHSTTConstraintConstants.PREFER_RESOURCES_CONSTRAINT]:
                        if not (preferResourceConstraint['@Id'].endswith('_roomCapacityRequirement') and event_id in preferResourceConstraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS]):
                            continue
                        otherPreferResourcesConstraints = [constraint for constraint in instance.Constraints[XHSTTConstraintConstants.PREFER_RESOURCES_CONSTRAINT]
                                                           if event_id in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS]
                                                               and constraint['@Id'].endswith('_roomPreference')]
                        otherPreferResourcesConstraints += [constraint for constraint in instance.Constraints[
                            XHSTTConstraintConstants.PREFER_RESOURCES_CONSTRAINT]
                                                            if len(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]) > 0
                                                            and event_id in instance.Events.EventGroups[constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS][0]].Events and
                                                           constraint['@Id'].endswith('_roomPreference')]
                        roomsMentionedInAllRelevantPreferResourceConstraints = set(preferResourceConstraint[XHSTTFileConstants.RESOURCES])
                        for constraint in otherPreferResourcesConstraints:
                            roomsMentionedInAllRelevantPreferResourceConstraints.intersection_update(set(constraint[XHSTTFileConstants.RESOURCES]))
                        for room in roomsMentionedInAllRelevantPreferResourceConstraints:
                            g.add_node(nodeCount, event=event_id, subevent=subevent, length=2, time=time, room=room)
                            for previousNodeId in range(startNodeCount, nodeCount):
                                g.add_edge(previousNodeId, nodeCount)
                            nodeCount += 1
                    if nodeCount - time_id == startNodeCount:
                        g.add_node(nodeCount, event=event_id, subevent=subevent, length=2, time=time, room=None)
                        for previousNodeId in range(startNodeCount, nodeCount):
                            g.add_edge(previousNodeId, nodeCount)
                        nodeCount += 1
                if (event_id + '_max_requirement', subevent) in event_dict.keys() and XHSTTFileConstants.TIME in event_dict[event_id + '_max_requirement', subevent].keys():
                    currently_processed_subevent[XHSTTFileConstants.TIME] = event_dict[event_id + '_max_requirement', subevent][XHSTTFileConstants.TIME]
                elif (event_id + '_min_requirement', subevent) in event_dict.keys() and XHSTTFileConstants.TIME in event_dict[event_id + '_min_requirement', subevent].keys():
                    currently_processed_subevent[XHSTTFileConstants.TIME] = \
                    event_dict[event_id + '_min_requirement', subevent][XHSTTFileConstants.TIME]
                else:
                    fixedResourcesOfEvent = {eventResource.Reference for eventResource in
                                             instance.Events.IndividualEvents[event_id].EventResources.AssignedResources}
                    possibleTimesWithoutClashes = copy.deepcopy(
                        possible_times_by_event_length[int(event[XHSTTFileConstants.DURATION])])
                    clashesByTime = dict()
                    for otherEvent in event_dict.keys():
                        if otherEvent == (event_id, subevent) or XHSTTFileConstants.TIME not in event_dict[
                            otherEvent].keys():
                            continue
                        fixedResourcesOfOtherEvent = {eventResource.Reference for eventResource in
                                                      instance.Events.IndividualEvents[
                                                          otherEvent[0]].EventResources.AssignedResources}
                        if fixedResourcesOfEvent.isdisjoint(fixedResourcesOfOtherEvent):
                            continue
                        commonResourceAmount = len(fixedResourcesOfEvent.intersection(fixedResourcesOfOtherEvent))
                        indexOfStartTimeOfOtherEvent = list(instance.Times.IndividualTimes.keys()).index(
                            event_dict[otherEvent][XHSTTFileConstants.TIME])
                        durationOfOtherEvent = int(instance.Events.IndividualEvents[otherEvent[0]].Duration)
                        for time in list(instance.Times.IndividualTimes.keys())[
                                    indexOfStartTimeOfOtherEvent-1:indexOfStartTimeOfOtherEvent + durationOfOtherEvent]:
                            if time not in possible_times_by_event_length[int(event[XHSTTFileConstants.DURATION])]:
                                continue
                            clashesByTime.setdefault(time, 0)
                            if time == list(instance.Times.IndividualTimes.keys())[indexOfStartTimeOfOtherEvent-1] or \
                                time == list(instance.Times.IndividualTimes.keys())[indexOfStartTimeOfOtherEvent + durationOfOtherEvent-1]:
                                clashesByTime[time] += commonResourceAmount
                            else:
                                clashesByTime[time] += commonResourceAmount*2
                            if time in possibleTimesWithoutClashes:
                                possibleTimesWithoutClashes.remove(time)
                    if len(possibleTimesWithoutClashes) > 0:
                        pass
                        # currently_processed_subevent[XHSTTFileConstants.TIME] = random.choice(
                        #     possibleTimesWithoutClashes)
                    else:
                        pass
                        # minAddedClashes = min(clashesByTime.values())
                        # timesWithMinimumClashes = [time for time in clashesByTime.keys() if clashesByTime[time] == minAddedClashes]
                        # minClashesCounter += minAddedClashes
                        # currently_processed_subevent[XHSTTFileConstants.TIME] = random.choice(timesWithMinimumClashes)
                currently_processed_subevent[SolutionDataConstants.DELETE_SUBEVENTS] = False
                currently_processed_subevent[XHSTTFileConstants.NAME] = event_id
                currently_processed_subevent[XHSTTFileConstants.RESOURCES] = dict()
                # for eventResource in instance.Events.IndividualEvents[event_id].EventResources.UnassignedResources:
                #     currently_processed_subevent[XHSTTFileConstants.RESOURCES][eventResource.Role] = ILPConstants.DUMMY_RESOURCE
                # for eventResource in instance.Events.IndividualEvents[event_id].EventResources.AssignedResources:
                #     currently_processed_subevent[XHSTTFileConstants.RESOURCES][eventResource.Role] = eventResource.Reference
            for i in range(eventsOfDurationOne):
                event = dict()
                event[XHSTTFileConstants.DURATION] = instance.Events.IndividualEvents[event_id].Duration
                subevent = (1, i)
                event_dict[event_id, subevent] = dict()
                currently_processed_subevent = event_dict[event_id, subevent]
                currently_processed_subevent[XHSTTFileConstants.DURATION] = event[XHSTTFileConstants.DURATION]
                currently_processed_subevent[XHSTTFileConstants.ID] = (event_id, subevent)
                startNodeCount = nodeCount
                for time_id in range(len(possible_times_by_event_length[1])):
                    time = possible_times_by_event_length[1][time_id]
                    for preferResourceConstraint in instance.Constraints[
                        XHSTTConstraintConstants.PREFER_RESOURCES_CONSTRAINT]:
                        if not (preferResourceConstraint['@Id'].endswith('_roomCapacityRequirement') and event_id in
                                preferResourceConstraint[XHSTTConstraintConstants.APPLIES_TO][
                                    XHSTTFileConstants.EVENTS]):
                            continue
                        otherPreferResourcesConstraints = [constraint for constraint in instance.Constraints[
                            XHSTTConstraintConstants.PREFER_RESOURCES_CONSTRAINT]
                                                           if
                                                           event_id in constraint[XHSTTConstraintConstants.APPLIES_TO][
                                                               XHSTTFileConstants.EVENTS]
                                                           and constraint['@Id'].endswith('_roomPreference')]
                        otherPreferResourcesConstraints += [constraint for constraint in instance.Constraints[
                            XHSTTConstraintConstants.PREFER_RESOURCES_CONSTRAINT]
                                                            if len(constraint[XHSTTConstraintConstants.APPLIES_TO][
                                                                           XHSTTFileConstants.EVENT_GROUPS]) > 0
                                                            and event_id in instance.Events.EventGroups[
                                                                constraint[XHSTTConstraintConstants.APPLIES_TO][
                                                                    XHSTTFileConstants.EVENT_GROUPS][0]].Events and
                                                            constraint['@Id'].endswith('_roomPreference')]
                        roomsMentionedInAllRelevantPreferResourceConstraints = set(
                            preferResourceConstraint[XHSTTFileConstants.RESOURCES])
                        for constraint in otherPreferResourcesConstraints:
                            roomsMentionedInAllRelevantPreferResourceConstraints.intersection_update(
                                set(constraint[XHSTTFileConstants.RESOURCES]))
                        for room in roomsMentionedInAllRelevantPreferResourceConstraints:
                            g.add_node(nodeCount, event=event_id, subevent=subevent, length=1, time=time, room=room)
                            for previousNodeId in range(startNodeCount, nodeCount):
                                g.add_edge(previousNodeId, nodeCount)
                            nodeCount += 1
                    if nodeCount - time_id == startNodeCount:
                        g.add_node(nodeCount, event=event_id, subevent=subevent, length=1, time=time, room=None)
                        for previousNodeId in range(startNodeCount, nodeCount):
                            g.add_edge(previousNodeId, nodeCount)
                        nodeCount += 1
                if (event_id + '_max_requirement', subevent) in event_dict.keys() and XHSTTFileConstants.TIME in \
                        event_dict[event_id + '_max_requirement', subevent].keys():
                    currently_processed_subevent[XHSTTFileConstants.TIME] = \
                    event_dict[event_id + '_max_requirement', subevent][XHSTTFileConstants.TIME]
                elif (event_id + '_min_requirement', subevent) in event_dict.keys() and XHSTTFileConstants.TIME in \
                        event_dict[event_id + '_min_requirement', subevent].keys():
                    currently_processed_subevent[XHSTTFileConstants.TIME] = \
                        event_dict[event_id + '_min_requirement', subevent][XHSTTFileConstants.TIME]
                else:
                    fixedResourcesOfEvent = {eventResource.Reference for eventResource in
                                             instance.Events.IndividualEvents[
                                                 event_id].EventResources.AssignedResources}
                    possibleTimesWithoutClashes = copy.deepcopy(
                        possible_times_by_event_length[int(event[XHSTTFileConstants.DURATION])])
                    clashesByTime = dict()
                    for otherEvent in event_dict.keys():
                        if otherEvent == (event_id, subevent) or XHSTTFileConstants.TIME not in event_dict[
                            otherEvent].keys():
                            continue
                        fixedResourcesOfOtherEvent = {eventResource.Reference for eventResource in
                                                      instance.Events.IndividualEvents[
                                                          otherEvent[0]].EventResources.AssignedResources}
                        if fixedResourcesOfEvent.isdisjoint(fixedResourcesOfOtherEvent):
                            continue
                        commonResourceAmount = len(fixedResourcesOfEvent.intersection(fixedResourcesOfOtherEvent))
                        indexOfStartTimeOfOtherEvent = list(instance.Times.IndividualTimes.keys()).index(
                            event_dict[otherEvent][XHSTTFileConstants.TIME])
                        durationOfOtherEvent = int(instance.Events.IndividualEvents[otherEvent[0]].Duration)
                        for time in list(instance.Times.IndividualTimes.keys())[
                                    indexOfStartTimeOfOtherEvent:indexOfStartTimeOfOtherEvent + durationOfOtherEvent]:
                            if time not in possible_times_by_event_length[int(event[XHSTTFileConstants.DURATION])]:
                                continue
                            clashesByTime.setdefault(time, 0)
                            clashesByTime[time] += commonResourceAmount
                            if time in possibleTimesWithoutClashes:
                                possibleTimesWithoutClashes.remove(time)
                    # if len(possibleTimesWithoutClashes) > 0:
                    #     currently_processed_subevent[XHSTTFileConstants.TIME] = random.choice(
                    #         possibleTimesWithoutClashes)
                    # else:
                    #     minAddedClashes = min(clashesByTime.values())
                    #     timesWithMinimumClashes = [time for time in clashesByTime.keys() if
                    #                                clashesByTime[time] == minAddedClashes]
                    #     minClashesCounter += minAddedClashes
                    #     currently_processed_subevent[XHSTTFileConstants.TIME] = random.choice(timesWithMinimumClashes)
                currently_processed_subevent[SolutionDataConstants.DELETE_SUBEVENTS] = False
                currently_processed_subevent[XHSTTFileConstants.NAME] = event_id
                currently_processed_subevent[XHSTTFileConstants.RESOURCES] = dict()
                # for eventResource in instance.Events.IndividualEvents[event_id].EventResources.UnassignedResources:
                #     currently_processed_subevent[XHSTTFileConstants.RESOURCES][eventResource.Role] = ILPConstants.DUMMY_RESOURCE
                # for eventResource in instance.Events.IndividualEvents[event_id].EventResources.AssignedResources:
                #     currently_processed_subevent[XHSTTFileConstants.RESOURCES][eventResource.Role] = eventResource.Reference
    resourceToEventsDict = dict()
    for event_id in instance.Events.IndividualEvents.keys():
        if event_id.endswith('_max_requirement') or event_id.endswith('_min_requirement'):
            continue
        eventAssignedResources = [resource.Reference for resource in instance.Events.IndividualEvents[event_id].EventResources.AssignedResources]

        while ILPConstants.DUMMY_RESOURCE in eventAssignedResources:
            eventAssignedResources.remove(ILPConstants.DUMMY_RESOURCE)
        for eventResource in eventAssignedResources:
            resourceToEventsDict.setdefault(eventResource, list())
            resourceToEventsDict[eventResource].append(event_id)

    edgeSet = set()
    for events in resourceToEventsDict.values():
        for time_id in range(len(instance.Times.IndividualTimes.keys())):
            time = list(instance.Times.IndividualTimes.keys())[time_id]
            if time_id != 0:
                previousTime = list(instance.Times.IndividualTimes.keys())[time_id - 1]
            else:
                previousTime = None
            relevantNodes = list()
            for event in events:
                relevantNodes += [x for x,y in g.nodes(data=True) if y['length'] == 1 and y['time'] == time and y['event'] == event]
                relevantNodes += [x for x,y in g.nodes(data=True) if
                                  y['length'] == 2 and y['time'] == time and y['event'] == event]
                if previousTime is not None:
                    relevantNodes += [x for x, y in g.nodes(data=True) if
                                      y['length'] == 2 and y['time'] == previousTime and y['event'] == event]
            relevantNodes = list(dict.fromkeys(relevantNodes))
            relevantNodes.sort(key=int)
            newEdges = [(relevantNodes[node1Index], relevantNodes[node2Index]) for node1Index in range(len(relevantNodes)) for node2Index in range(node1Index + 1, len(relevantNodes))]
            edgeSet.update(newEdges)
    for room in instance.Resources.ResourceGroupsByType[XHSTTFileConstants.ROOM].ResourceGroups[XHSTTFileConstants.ALL_ROOMS].Resources:
        events = instance.Events.IndividualEvents.keys()
        for time_id in range(len(instance.Times.IndividualTimes.keys())):
            time = list(instance.Times.IndividualTimes.keys())[time_id]
            if time_id != 0:
                previousTime = list(instance.Times.IndividualTimes.keys())[time_id - 1]
            else:
                previousTime = None
            relevantNodes = list()
            for event in events:
                relevantNodes += [x for x,y in g.nodes(data=True) if y['length'] == 1 and y['time'] == time and y['event'] == event and y['room'] == room]
                relevantNodes += [x for x,y in g.nodes(data=True) if
                                  y['length'] == 2 and y['time'] == time and y['event'] == event and y['room'] == room]
                if previousTime is not None:
                    relevantNodes += [x for x, y in g.nodes(data=True) if
                                      y['length'] == 2 and y['time'] == previousTime and y['event'] == event and y['room'] == room]
            relevantNodes = list(dict.fromkeys(relevantNodes))
            relevantNodes.sort(key=int)
            newEdges = [(relevantNodes[node1Index], relevantNodes[node2Index]) for node1Index in range(len(relevantNodes)) for node2Index in range(node1Index + 1, len(relevantNodes))]
            edgeSet.update(newEdges)
    g.add_edges_from(edgeSet)
    maximum_independent_set = _get_nodes_from_IS_file("independent_set_teachers.txt")
    dimacs_filename = "graph.dimacs"

    with open(dimacs_filename, "w") as f:
        # write the header
        f.write("p {} {}\n".format(g.number_of_nodes(), g.number_of_edges()))
        # now write all edges
        for u, v in g.edges():
            f.write("e {} {}\n".format(u, v))

    assingmentData = [y for x, y in g.nodes(data=True) if x in maximum_independent_set]
    for assignment in assingmentData:
        event_dict[assignment["event"], assignment["subevent"]][XHSTTFileConstants.TIME] = assignment["time"]

    for event_id in instance.Events.IndividualEvents.keys():
        if event_id.endswith('_max_requirement') or event_id.endswith('_min_requirement'):
            durationOfMainEvent = int(instance.Events.IndividualEvents[event_id[:-16]].Duration)
            durationOfRequEvent = int(instance.Events.IndividualEvents[event_id].Duration)
            amountOfEventsRequ = durationOfRequEvent // durationOfMainEvent
            for i in range(amountOfEventsRequ):
                event = dict()
                event[XHSTTFileConstants.DURATION] = durationOfMainEvent
                subevent = (durationOfMainEvent, i)
                currently_processed_subevent = event_dict[event_id, subevent]
                currently_processed_subevent[XHSTTFileConstants.DURATION] = durationOfMainEvent
                currently_processed_subevent[XHSTTFileConstants.ID] = (event_id, subevent)
                # currently_processed_subevent[XHSTTFileConstants.TIME] = None
                # currently_processed_subevent[XHSTTFileConstants.TIME] = list(instance.Times.IndividualTimes.keys())[0]
                if (event_id[:-16] + '_max_requirement', (subevent[0], 0)) in event_dict.keys() and XHSTTFileConstants.TIME in event_dict[event_id[:-16] + '_max_requirement', (subevent[0], 0)].keys():
                    currently_processed_subevent[XHSTTFileConstants.TIME] = event_dict[event_id[:-16] + '_max_requirement', (subevent[0], 0)][XHSTTFileConstants.TIME]
                elif (event_id[:-16] + '_min_requirement', (subevent[0], 0)) in event_dict.keys() and XHSTTFileConstants.TIME in event_dict[event_id[:-16] + '_min_requirement', (subevent[0], 0)].keys():
                    currently_processed_subevent[XHSTTFileConstants.TIME] = \
                    event_dict[event_id[:-16] + '_min_requirement', (subevent[0], 0)][XHSTTFileConstants.TIME]
                elif (event_id[:-16], (subevent[0], 0)) in event_dict.keys() and XHSTTFileConstants.TIME in event_dict[event_id[:-16], (subevent[0], 0)].keys():
                    currently_processed_subevent[XHSTTFileConstants.TIME] = \
                    event_dict[event_id[:-16], subevent][XHSTTFileConstants.TIME]
    returned_solution_dict[XHSTTFileConstants.EVENTS] = event_dict
    returned_solution_dict[SolutionDataConstants.VALIDATOR_OBJECTIVE] = math.inf
    return returned_solution_dict

def _get_nodes_from_IS_file(filename: str) -> list:
    fileAsList = io.open(f"{filename}", "r", encoding="utf8", errors="backslashreplace").read()
    fileAsList = fileAsList.split('\n')
    nodeList = [node + 1 for node in range(len(fileAsList)) if fileAsList[node] == "1"]
    return nodeList
def get_time_with_most_total_assigned_resources_from_list_of_times(time_list, event_dict, instance: Instance, processedEvent):
    time_to_assigned_resources = dict()
    for time in time_list:
        time_to_assigned_resources[time] = set()
    for event in event_dict.keys():
        if event == processedEvent or XHSTTFileConstants.TIME not in event_dict[
            event].keys():
            continue
        fixedResourcesOfEvent = {eventResource.Reference for eventResource in
                                      instance.Events.IndividualEvents[
                                          event[0]].EventResources.AssignedResources}
        indexOfStartTimeOfEvent = list(instance.Times.IndividualTimes.keys()).index(
            event_dict[event][XHSTTFileConstants.TIME])
        durationOfEvent = int(instance.Events.IndividualEvents[event[0]].Duration)
        for time in list(instance.Times.IndividualTimes.keys())[
                    indexOfStartTimeOfEvent:indexOfStartTimeOfEvent + durationOfEvent]:
            if time in time_list:
                time_to_assigned_resources[time].update(fixedResourcesOfEvent)
    maximumResources = max([len(resources) for resources in time_to_assigned_resources.values()])
    timesWithMaximumResources = [time for time in time_to_assigned_resources.keys() if len(time_to_assigned_resources[time]) == maximumResources]
    return random.choice(timesWithMaximumResources)
