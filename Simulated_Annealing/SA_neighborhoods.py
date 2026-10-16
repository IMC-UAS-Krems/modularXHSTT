import sys
sys.path.append('../XHSTTImporter')
sys.path.append('XHSTTImporter')
from XHSTTImporter.Instance import Instance
sys.path.append('../XHSTTImporter/Constants')
sys.path.append('XHSTTImporter/Constants')
import XHSTTFileConstants
import XHSTTConstraintConstants
sys.path.append('ILP_solver')
sys.path.append('../ILP_solver')
import ILPConstants
import random
from collections import Counter

def swap_resource(instance: Instance, solutionData: dict, event1=None, event2=None, role1=None, role2=None, searchSpace=None, event_role_helper_dict=None):
    if event1 is None and role1 is None and event2 is None and role2 is None:
        resource1 = ILPConstants.DUMMY_RESOURCE
        counter = 0
        while resource1 == ILPConstants.DUMMY_RESOURCE:
            if counter > 10:
                return None, None
            counter += 1
            event1, role1 = random.choice(list(event_role_helper_dict["possible_resources_events"].keys()))
            solution_events_of_event1 = [solution_event for solution_event in event_role_helper_dict["event_to_subevents"][event1] if
                                         solutionData[XHSTTFileConstants.EVENTS][solution_event][XHSTTFileConstants.RESOURCES][role1] != ILPConstants.DUMMY_RESOURCE]
            if len(solution_events_of_event1) == 0:
                continue
            event1 = random.choice(solution_events_of_event1)
            resource1 = solutionData[XHSTTFileConstants.EVENTS][event1][XHSTTFileConstants.RESOURCES][role1]
        counter = 0
        while True:
            if counter > 10:
                return None, None
            counter += 1
            event2, role2 = random.choice(list(event_role_helper_dict["resource_to_possible_roles_events"][resource1]))
            solution_events_of_event2 = [solution_event for solution_event in event_role_helper_dict["event_to_subevents"][event2] if solutionData[XHSTTFileConstants.EVENTS][solution_event][XHSTTFileConstants.RESOURCES][role2] != resource1
                                         and (solutionData[XHSTTFileConstants.EVENTS][solution_event][XHSTTFileConstants.RESOURCES][role2] in event_role_helper_dict["possible_resources_events"][(event1[0], role1)]
                                              or solutionData[XHSTTFileConstants.EVENTS][solution_event][XHSTTFileConstants.RESOURCES][role2] == ILPConstants.DUMMY_RESOURCE)]
            if len(solution_events_of_event2) == 0:
                continue
            event2 = random.choice(solution_events_of_event2)
            resource2 = solutionData[XHSTTFileConstants.EVENTS][event2][XHSTTFileConstants.RESOURCES][role2]
            break
    else:
        resource1 = solutionData[XHSTTFileConstants.EVENTS][event1][XHSTTFileConstants.RESOURCES][role1]
        resource2 = solutionData[XHSTTFileConstants.EVENTS][event2][XHSTTFileConstants.RESOURCES][role2]
    if event_role_helper_dict is not None:
        if resource1 != ILPConstants.DUMMY_RESOURCE and resource1 not in event_role_helper_dict["possible_resources_events"][(event2[0], role2)]:
            return None, None

        if resource2 != ILPConstants.DUMMY_RESOURCE and resource2 not in event_role_helper_dict["possible_resources_events"][(event1[0], role1)]:
            return None, None

    solutionData[XHSTTFileConstants.EVENTS][event2][XHSTTFileConstants.RESOURCES][
        role2] = resource1
    solutionData[XHSTTFileConstants.EVENTS][event1][XHSTTFileConstants.RESOURCES][
        role1] = resource2

    return (event1, event2, role1, role2), (resource1, resource2)

def swap_resource_for_all_subevents(instance: Instance, solutionData: dict, event_group1=None, event_group2=None, role1=None, role2=None, searchSpace=None, event_role_helper_dict=None):
    if event_group1 is None and role1 is None and event_group2 is None and role2 is None:
        resource1 = ILPConstants.DUMMY_RESOURCE
        counter = 0
        while resource1 == ILPConstants.DUMMY_RESOURCE:
            if counter > 10:
                return None, None
            counter += 1
            event_group1, role1 = random.choice(list(event_role_helper_dict["possible_resources_event_groups"].keys()))
            solution_events_of_event_group1 = [subevent for event in
                                              instance.Events.EventGroups[event_group1].Events for subevent in
                                              event_role_helper_dict["event_to_subevents"][event]]
            resourcesUsedForRoleInEventGroup = set()
            for solution_event in solution_events_of_event_group1:
                resourcesUsedForRoleInEventGroup.add(solutionData[XHSTTFileConstants.EVENTS][solution_event][XHSTTFileConstants.RESOURCES][role1])
            if len(resourcesUsedForRoleInEventGroup) == 1 and list(resourcesUsedForRoleInEventGroup)[0] != ILPConstants.DUMMY_RESOURCE:
                resource1 = list(resourcesUsedForRoleInEventGroup)[0]

        foundFittingEvent2 = False
        counter = 0
        eligibleChoices = [(eg, r) for (eg, r) in event_role_helper_dict["resource_to_possible_roles_event_groups"][resource1] if eg != event_group1]
        if len(eligibleChoices) == 0:
            return None, None
        while not foundFittingEvent2:
            if counter > 10:
                return None, None
            counter += 1
            event_group2, role2 = random.choice(eligibleChoices)
            solution_events_of_event_group2 = [subevent for event in
                                              instance.Events.EventGroups[event_group2].Events for subevent in
                                              event_role_helper_dict["event_to_subevents"][event]]
            resourcesUsedForRoleInEventGroup = set()
            for solution_event in solution_events_of_event_group2:
                resourcesUsedForRoleInEventGroup.add(
                    solutionData[XHSTTFileConstants.EVENTS][solution_event][XHSTTFileConstants.RESOURCES][role2])
            if len(resourcesUsedForRoleInEventGroup) == 1:
                resource2 = list(resourcesUsedForRoleInEventGroup)[0]
            else:
                continue
            if (resource2 in event_role_helper_dict["possible_resources_event_groups"][(event_group1, role1)] or resource2 == ILPConstants.DUMMY_RESOURCE) and resource1 != resource2:
                foundFittingEvent2 = True
    else:
        firstEventOfEventGroup1 = instance.Events.EventGroups[event_group1].Events[0]
        first_solution_event_of_first_event_of_event_group1 = [solution_event for solution_event in
                                           event_role_helper_dict["event_to_subevents"][firstEventOfEventGroup1]][0]
        solution_events_of_event_group1 = [subevent for event in
                                              instance.Events.EventGroups[event_group1].Events for subevent in
                                              event_role_helper_dict["event_to_subevents"][event]]
        resource1 = solutionData[XHSTTFileConstants.EVENTS][first_solution_event_of_first_event_of_event_group1][XHSTTFileConstants.RESOURCES][role1]
        firstEventOfEventGroup2 = instance.Events.EventGroups[event_group2].Events[0]
        first_solution_event_of_first_event_of_event_group2 = [solution_event for solution_event in
                                                               solutionData[XHSTTFileConstants.EVENTS].keys() if
                                                               solution_event[0] == firstEventOfEventGroup2][0]
        solution_events_of_event_group2 = [subevent for event in
                                              instance.Events.EventGroups[event_group2].Events for subevent in
                                              event_role_helper_dict["event_to_subevents"][event]]
        resource2 = solutionData[XHSTTFileConstants.EVENTS][first_solution_event_of_first_event_of_event_group2][XHSTTFileConstants.RESOURCES][role2]
    if event_role_helper_dict is not None:
        if resource1 != ILPConstants.DUMMY_RESOURCE and resource1 not in event_role_helper_dict["possible_resources_event_groups"][(event_group2, role2)]:
            return None, None

        if resource2 != ILPConstants.DUMMY_RESOURCE and resource2 not in event_role_helper_dict["possible_resources_event_groups"][(event_group1, role1)]:
            return None, None

    for solution_event_of_event_group1 in solution_events_of_event_group1:
        solutionData[XHSTTFileConstants.EVENTS][solution_event_of_event_group1][XHSTTFileConstants.RESOURCES][
            role1] = resource2
    for solution_event_of_event_group2 in solution_events_of_event_group2:
        solutionData[XHSTTFileConstants.EVENTS][solution_event_of_event_group2][XHSTTFileConstants.RESOURCES][
            role2] = resource1

    return (event_group1, event_group2, role1, role2), (solution_events_of_event_group1, solution_events_of_event_group2, resource1, resource2)

def change_resource_for_all_subevents(instance: Instance, solutionData: dict, eventGroup=None, role=None, resources=None, searchSpace=None, event_role_helper_dict=None):
    if eventGroup is None and role is None:
        eventGroup, role = random.choice(list(event_role_helper_dict["possible_resources_event_groups"].keys()))
        solution_events_of_event_group = [subevent for event in instance.Events.EventGroups[eventGroup].Events for subevent in event_role_helper_dict["event_to_subevents"][event]]
        if len(solution_events_of_event_group) == 0:
            return None, None
        randomSolutionEventFromEvent1 = random.choice(solution_events_of_event_group)
        previousResource = solutionData[XHSTTFileConstants.EVENTS][randomSolutionEventFromEvent1][XHSTTFileConstants.RESOURCES][role]
        possibilitiesForResource2 = list(event_role_helper_dict["possible_resources_event_groups"][eventGroup, role])
        possibilitiesForResource2.append(ILPConstants.DUMMY_RESOURCE)
        if previousResource in possibilitiesForResource2:
            possibilitiesForResource2.remove(previousResource)
        if len(possibilitiesForResource2) == 0:
            return None, None
        newResource = random.choice(possibilitiesForResource2)
        chosen_random_resources = [newResource for _ in range(len(solution_events_of_event_group))]
    else:
        solution_events_of_event_group = [subevent for event in instance.Events.EventGroups[eventGroup].Events for subevent in event_role_helper_dict["event_to_subevents"][event]]
        chosen_random_resources = resources



    prev_resources = [solutionData[XHSTTFileConstants.EVENTS][solution_event][XHSTTFileConstants.RESOURCES][role] for
                      solution_event in solution_events_of_event_group]
    for i in range(len(solution_events_of_event_group)):
        solutionData[XHSTTFileConstants.EVENTS][solution_events_of_event_group[i]][XHSTTFileConstants.RESOURCES][role] = chosen_random_resources[i]

    return (eventGroup, role, prev_resources), (solution_events_of_event_group, prev_resources, chosen_random_resources)

def change_resource(instance: Instance, solutionData: dict, event=None, role=None, resource=None, searchSpace=None, event_role_helper_dict=None):
    if event is None and role is None:
        event, role = random.choice(list(event_role_helper_dict["possible_resources_events"].keys()))
        solution_events_of_event = [solution_event for solution_event in
                                    event_role_helper_dict["event_to_subevents"][event]]
        if len(solution_events_of_event) == 0:
            return None, None
        randomSolutionEventFromEvent1 = random.choice(solution_events_of_event)
        prev_resource = \
        solutionData[XHSTTFileConstants.EVENTS][randomSolutionEventFromEvent1][XHSTTFileConstants.RESOURCES][role]
        possibilitiesForResource2 = list(event_role_helper_dict["possible_resources_events"][event, role])
        possibilitiesForResource2.append(ILPConstants.DUMMY_RESOURCE)
        if prev_resource in possibilitiesForResource2:
            possibilitiesForResource2.remove(prev_resource)
        if len(possibilitiesForResource2) == 0:
            return None, None
        chosen_random_resource = random.choice(possibilitiesForResource2)
    else:
        randomSolutionEventFromEvent1 = event
        prev_resource = \
            solutionData[XHSTTFileConstants.EVENTS][randomSolutionEventFromEvent1][XHSTTFileConstants.RESOURCES][role]
        chosen_random_resource = resource


    solutionData[XHSTTFileConstants.EVENTS][randomSolutionEventFromEvent1][XHSTTFileConstants.RESOURCES][role] = chosen_random_resource
    return (randomSolutionEventFromEvent1, role, prev_resource), (prev_resource, chosen_random_resource)


def swap_times(instance: Instance, solutionData: dict, event1=None, event2=None, searchSpace=None, event_role_helper_dict=None):
    if event1 is None:
        first_random_event = random.choice(event_role_helper_dict["events_without_fixed_time"])
    else:
        first_random_event = event1

    if event2 is None:
        resources_part_of_first_event = set(solutionData[XHSTTFileConstants.EVENTS][first_random_event][XHSTTFileConstants.RESOURCES].values())
        possible_events = [event for event in event_role_helper_dict["events_without_fixed_time"] if not
                                             set(solutionData[XHSTTFileConstants.EVENTS][event][XHSTTFileConstants.RESOURCES].values()).isdisjoint(resources_part_of_first_event)]

        if len(possible_events) == 0:
            return None, None
        second_random_event = random.choice(possible_events)
    else:
        second_random_event = event2

    first_time = solutionData[XHSTTFileConstants.EVENTS][first_random_event][XHSTTFileConstants.TIME]
    second_time = solutionData[XHSTTFileConstants.EVENTS][second_random_event][XHSTTFileConstants.TIME]
    if first_time == ILPConstants.DUMMY_TIME:
        first_time_index = None
    else:
        first_time_index = list(instance.Times.IndividualTimes).index(first_time)
    if second_time == ILPConstants.DUMMY_TIME:
        second_time_index = None
    else:
        second_time_index = list(instance.Times.IndividualTimes).index(second_time)
    first_event_length = first_random_event[1][0]
    second_event_length = second_random_event[1][0]
    if first_time_index is not None:
        old_times_first_event = list(instance.Times.IndividualTimes)[first_time_index: first_time_index + first_event_length]
        new_times_second_event = list(instance.Times.IndividualTimes)[
                                 first_time_index: first_time_index + second_event_length]
    else:
        old_times_first_event = list()
        new_times_second_event = list()
    if second_time_index is not None:
        new_times_first_event = list(instance.Times.IndividualTimes)[
                                second_time_index: second_time_index + first_event_length]
        old_times_second_event = list(instance.Times.IndividualTimes)[
                                second_time_index: second_time_index + second_event_length]
    else:
        new_times_first_event = list()
        old_times_second_event = list()
    solutionData[XHSTTFileConstants.EVENTS][first_random_event][XHSTTFileConstants.TIME] = second_time
    solutionData[XHSTTFileConstants.EVENTS][second_random_event][XHSTTFileConstants.TIME] = first_time
    first_event_resource_counts = Counter(
        solutionData[XHSTTFileConstants.EVENTS][first_random_event][XHSTTFileConstants.RESOURCES].values())
    second_event_resource_counts = Counter(
        solutionData[XHSTTFileConstants.EVENTS][second_random_event][XHSTTFileConstants.RESOURCES].values())
    common_resources = set()
    for resource in first_event_resource_counts.keys():
        if resource in second_event_resource_counts and second_event_resource_counts[resource] == first_event_resource_counts[resource]:
            common_resources.add(resource)
    if first_event_length != second_event_length:
        common_resources = set()
    return (first_random_event, second_random_event), ((old_times_first_event, new_times_first_event), (old_times_second_event, new_times_second_event), common_resources)


def block_swap_times(instance: Instance, solutionData: dict, event1=None, event2=None, searchSpace=None, event_role_helper_dict=None):
    if event1 is None:
        first_random_event = random.choice(event_role_helper_dict["events_without_fixed_time"])
    else:
        first_random_event = event1
    first_event_length = first_random_event[1][0]
    first_time = solutionData[XHSTTFileConstants.EVENTS][first_random_event][XHSTTFileConstants.TIME]
    if first_time == ILPConstants.DUMMY_TIME:
        return None, None
    first_time_index = list(instance.Times.IndividualTimes.keys()).index(first_time)
    if first_time_index >= len(instance.Times.IndividualTimes.keys()) - first_event_length:
        return None, None
    following_time_slot = list(instance.Times.IndividualTimes.keys())[first_time_index + first_event_length]
    old_second_event_index = list(instance.Times.IndividualTimes.keys()).index(following_time_slot)
    if event2 is None:
        resources_part_of_first_event = set(
            solutionData[XHSTTFileConstants.EVENTS][first_random_event][XHSTTFileConstants.RESOURCES].values())

        events_starting_directly_after_first = [event for event in event_role_helper_dict["events_without_fixed_time"] if
                                                solutionData[XHSTTFileConstants.EVENTS][event][
                                                    XHSTTFileConstants.TIME] == following_time_slot and not
                                                set(solutionData[XHSTTFileConstants.EVENTS][event][XHSTTFileConstants.RESOURCES].values()).isdisjoint(resources_part_of_first_event)]

        if len(events_starting_directly_after_first) == 0:
            return None, None
        second_random_event = random.choice(events_starting_directly_after_first)
    else:
        second_random_event = event2
    second_event_length = second_random_event[1][0]
    if first_time_index + second_event_length + first_event_length > len(instance.Times.IndividualTimes.keys()):
        return None, None
    new_time_for_first_event = list(instance.Times.IndividualTimes.keys())[first_time_index + second_event_length]
    second_time_index = list(instance.Times.IndividualTimes.keys()).index(new_time_for_first_event)
    old_times_first_event = list(instance.Times.IndividualTimes)[
                            first_time_index: first_time_index + first_event_length]
    new_times_first_event = list(instance.Times.IndividualTimes)[
                            second_time_index: second_time_index + first_event_length]
    old_times_second_event = list(instance.Times.IndividualTimes)[
                             old_second_event_index: old_second_event_index + second_event_length]
    new_times_second_event = list(instance.Times.IndividualTimes)[
                             first_time_index: first_time_index + second_event_length]
    solutionData[XHSTTFileConstants.EVENTS][second_random_event][XHSTTFileConstants.TIME] = first_time
    solutionData[XHSTTFileConstants.EVENTS][first_random_event][XHSTTFileConstants.TIME] = new_time_for_first_event
    first_event_resource_counts = Counter(solutionData[XHSTTFileConstants.EVENTS][first_random_event][XHSTTFileConstants.RESOURCES].values())
    second_event_resource_counts = Counter(
        solutionData[XHSTTFileConstants.EVENTS][second_random_event][XHSTTFileConstants.RESOURCES].values())
    common_resources = set()
    for resource in first_event_resource_counts.keys():
        if resource in second_event_resource_counts and second_event_resource_counts[resource] == first_event_resource_counts[resource]:
            common_resources.add(resource)
    if first_event_length != second_event_length:
        common_resources = set()
    return (second_random_event, first_random_event), ((old_times_first_event, new_times_first_event), (old_times_second_event, new_times_second_event), common_resources)


def move_event(instance: Instance, solutionData: dict, event=None, time=None, searchSpace=None, event_role_helper_dict=None):
    if event is None:
        random_event = random.choice(event_role_helper_dict["events_without_fixed_time"])
    else:
        random_event = event
    prev_time = solutionData[XHSTTFileConstants.EVENTS][random_event][XHSTTFileConstants.TIME]
    if prev_time == ILPConstants.DUMMY_TIME:
        prev_time_index = None
    else:
        prev_time_index = list(instance.Times.IndividualTimes.keys()).index(prev_time)
    if time is None:
        if searchSpace is None or searchSpace["possibleTimes"] is None:
            possibleTimes = list(instance.Times.IndividualTimes.keys()) + [ILPConstants.DUMMY_TIME]
            possibleTimes.remove(prev_time)
            solutionData[XHSTTFileConstants.EVENTS][random_event][XHSTTFileConstants.TIME] = random.choice(possibleTimes)
        else:
            solutionData[XHSTTFileConstants.EVENTS][random_event][XHSTTFileConstants.TIME] = random.choice(searchSpace["possibleTimes"])
    else:
        solutionData[XHSTTFileConstants.EVENTS][random_event][XHSTTFileConstants.TIME] = time
    if solutionData[XHSTTFileConstants.EVENTS][random_event][XHSTTFileConstants.TIME] == ILPConstants.DUMMY_TIME:
        new_time_index = None
    else:
        new_time_index = list(instance.Times.IndividualTimes.keys()).index(solutionData[XHSTTFileConstants.EVENTS][random_event][XHSTTFileConstants.TIME])
    event_length = random_event[1][0]
    if prev_time_index is not None:
        old_times = list(instance.Times.IndividualTimes)[
                                prev_time_index: prev_time_index + event_length]
    else:
        old_times = list()
    if new_time_index is not None:
        new_times = list(instance.Times.IndividualTimes)[
                                new_time_index: new_time_index + event_length]
        newStartTime = new_times[0]
    else:
        new_times = list()
        newStartTime = ILPConstants.DUMMY_TIME
    return (random_event, prev_time), (old_times, new_times, newStartTime)


def move_linked_events(instance: Instance, solutionData: dict, events=None, times=None, searchSpace=None, event_role_helper_dict=None):
    if events is None:
        if len(instance.Constraints[XHSTTConstraintConstants.LINK_EVENTS_CONSTRAINT]) == 0:
            return None, None
        else:
            randomLinkEventsConstraint = random.choice(instance.Constraints[XHSTTConstraintConstants.LINK_EVENTS_CONSTRAINT])
            eventGroup = randomLinkEventsConstraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS][0]
            firstEventInEventGroup = instance.Events.EventGroups[eventGroup].Events[0]
            randomSubevent = random.choice([solevent for solevent in event_role_helper_dict["event_to_subevents"][firstEventInEventGroup]])
            events = [(event, randomSubevent[1]) for event in instance.Events.EventGroups[eventGroup].Events]
            if searchSpace is not None and searchSpace["eventsWithFreeTimes"] is not None and not set(events).issubset(set(searchSpace["eventsWithFreeTimes"])):
                return None, None
    prev_times = list()
    old_times = list()
    new_times = list()
    for eventIndex in range(len(events)):
        solutionEvent = events[eventIndex]
        prev_time = solutionData[XHSTTFileConstants.EVENTS][solutionEvent][XHSTTFileConstants.TIME]
        if prev_time == ILPConstants.DUMMY_TIME:
            prev_time_index = None
        else:
            prev_time_index = list(instance.Times.IndividualTimes.keys()).index(prev_time)
        if times is None:
            if searchSpace is None or searchSpace["possibleTimes"] is None:
                solutionData[XHSTTFileConstants.EVENTS][solutionEvent][XHSTTFileConstants.TIME] = random.choice(
                    list(instance.Times.IndividualTimes.keys()))
            else:
                solutionData[XHSTTFileConstants.EVENTS][solutionEvent][XHSTTFileConstants.TIME] = random.choice(
                    searchSpace["possibleTimes"])
        else:
            solutionData[XHSTTFileConstants.EVENTS][solutionEvent][XHSTTFileConstants.TIME] = times[eventIndex]
        if solutionData[XHSTTFileConstants.EVENTS][solutionEvent][XHSTTFileConstants.TIME] == ILPConstants.DUMMY_TIME:
            new_time_index = None
        else:
            new_time_index = list(instance.Times.IndividualTimes.keys()).index(solutionData[XHSTTFileConstants.EVENTS][solutionEvent][XHSTTFileConstants.TIME])
        event_length = solutionEvent[1][0]
        prev_times.append(prev_time)
        if prev_time_index is not None:
            old_times.append(list(instance.Times.IndividualTimes)[
                                    prev_time_index: prev_time_index + event_length])
        else:
            old_times.append(list())
        if new_time_index is not None:
            new_times.append(list(instance.Times.IndividualTimes)[
                                    new_time_index: new_time_index + event_length])
        else:
            new_times.append(list())
    return (events, prev_times), (old_times, new_times)

def combine_subevents(instance: Instance, solutionData: dict, event1=None, event2=None, newEventSubeventIdentifier=None, searchSpace=None, event_role_helper_dict=None):
    if event1 is None and event2 is None:
        possibleEvents = [event for event in event_role_helper_dict["event_to_subevents"] if len(event_role_helper_dict["event_to_subevents"][event]) >= 2]
        if len(possibleEvents) == 0:
            return None, None
        event = random.choice(possibleEvents)
        selectedSubevents = random.sample(list(event_role_helper_dict["event_to_subevents"][event]), 2)
        event1 = selectedSubevents[0]
        event2 = selectedSubevents[1]
        newEventDuration = event1[1][0] + event2[1][0]
        existingSubeventsWithNewEventDuration = {solEvent[1][1] for solEvent in event_role_helper_dict["event_to_subevents"][event] if solEvent[1][0] == newEventDuration}
        newEventSubeventIdentifier = (newEventDuration, get_lowest_missing(existingSubeventsWithNewEventDuration))

    oldTimeOfEvent2 = solutionData[XHSTTFileConstants.EVENTS][event2][XHSTTFileConstants.TIME]
    newEventSubeventTuple = (event1[0], newEventSubeventIdentifier)
    resourceDictEvent1 = solutionData[XHSTTFileConstants.EVENTS][event1][XHSTTFileConstants.RESOURCES]
    resourceDictEvent2 = solutionData[XHSTTFileConstants.EVENTS][event2][XHSTTFileConstants.RESOURCES]
    newEventStartTime = solutionData[XHSTTFileConstants.EVENTS][event1][XHSTTFileConstants.TIME]
    newEvent = dict()
    newEvent[XHSTTFileConstants.TIME] = newEventStartTime
    newEvent[XHSTTFileConstants.RESOURCES] = resourceDictEvent1
    newEvent[XHSTTFileConstants.ID] = newEventSubeventTuple
    newEvent['Name'] = event1[0]
    newEvent['DeleteSubevents'] = False
    newEvent['Duration'] = str(newEventSubeventIdentifier[0])

    allTimes = list(instance.Times.IndividualTimes.keys())
    if solutionData[XHSTTFileConstants.EVENTS][event1][XHSTTFileConstants.TIME] != ILPConstants.DUMMY_TIME:
        event1Index = allTimes.index(solutionData[XHSTTFileConstants.EVENTS][event1][XHSTTFileConstants.TIME])
        timesEvent1 = allTimes[event1Index: event1Index + event1[1][0]]
        newTimes = allTimes[event1Index: event1Index + newEventSubeventTuple[1][0]]
    else:
        timesEvent1 = []
        newTimes = []
    if solutionData[XHSTTFileConstants.EVENTS][event2][XHSTTFileConstants.TIME] != ILPConstants.DUMMY_TIME:
        event2Index = allTimes.index(solutionData[XHSTTFileConstants.EVENTS][event2][XHSTTFileConstants.TIME])
        timesEvent2 = allTimes[event2Index: event2Index + event2[1][0]]
    else:
        timesEvent2 = []
    solutionEvent1 = solutionData[XHSTTFileConstants.EVENTS][event1]
    solutionEvent2 = solutionData[XHSTTFileConstants.EVENTS][event2]
    del solutionData[XHSTTFileConstants.EVENTS][event1]
    del solutionData[XHSTTFileConstants.EVENTS][event2]
    solutionData[XHSTTFileConstants.EVENTS][newEventSubeventTuple] = newEvent
    event_role_helper_dict["events_without_fixed_time"].remove(event1)
    event_role_helper_dict["events_without_fixed_time"].remove(event2)
    event_role_helper_dict["events_without_fixed_time"].append(newEventSubeventTuple)
    event_role_helper_dict["event_to_subevents"][event1[0]].remove(event1)
    event_role_helper_dict["event_to_subevents"][event1[0]] = sorted(event_role_helper_dict["event_to_subevents"][event1[0]])
    event_role_helper_dict["event_to_subevents"][event2[0]].remove(event2)
    event_role_helper_dict["event_to_subevents"][event2[0]] = sorted(event_role_helper_dict["event_to_subevents"][event2[0]])
    event_role_helper_dict["event_to_subevents"][newEventSubeventTuple[0]].append(newEventSubeventTuple)
    event_role_helper_dict["event_to_subevents"][newEventSubeventTuple[0]] = sorted(event_role_helper_dict["event_to_subevents"][newEventSubeventTuple[0]])
    return (newEventSubeventTuple, oldTimeOfEvent2, fast_copy(resourceDictEvent2), event2[1], event1[1]), (list(resourceDictEvent2.values()), list(resourceDictEvent1.values()), timesEvent2, timesEvent1, event2, event1, newTimes, fast_copy(solutionEvent2), fast_copy(solutionEvent1))

def split_subevent(instance: Instance, solutionData: dict, event_to_split=None, movedTime=None, movedResources=None, movedSubevent=None, keptSubevent=None, searchSpace=None, event_role_helper_dict=None):
    allTimes = list(instance.Times.IndividualTimes.keys())
    if event_to_split is None:
        possibleChoices = [solutionEvent for event in event_role_helper_dict["events_with_flexible_subevents"] for solutionEvent in event_role_helper_dict["event_to_subevents"][event] if solutionEvent[1][0] >= 2]
        if len(possibleChoices) == 0:
            return None, None
        event_to_split = random.choice(possibleChoices)
        movedDuration = random.randint(1, event_to_split[1][0] - 1)
        movedResources = fast_copy(solutionData[XHSTTFileConstants.EVENTS][event_to_split][XHSTTFileConstants.RESOURCES])
        possibleTimes = allTimes + [ILPConstants.DUMMY_TIME]
        if solutionData[XHSTTFileConstants.EVENTS][event_to_split][XHSTTFileConstants.TIME] != ILPConstants.DUMMY_TIME:
            oldStartTimeIndex = allTimes.index(solutionData[XHSTTFileConstants.EVENTS][event_to_split][XHSTTFileConstants.TIME])
            usedTimesByOriginalEvent = allTimes[oldStartTimeIndex: oldStartTimeIndex + event_to_split[1][0]]
            for time in usedTimesByOriginalEvent:
                possibleTimes.remove(time)
        else:
            usedTimesByOriginalEvent = list()
        movedTime = random.choice(possibleTimes)
        existingSubeventsWithMovedEventDuration = {solEvent[1][1] for solEvent in event_role_helper_dict["event_to_subevents"][event_to_split[0]] if solEvent[1][0] == movedDuration}
        movedIndex = get_lowest_missing(existingSubeventsWithMovedEventDuration)
        keptDuration = event_to_split[1][0] - movedDuration
        if keptDuration == movedDuration:
            existingSubeventsWithKeptEventDuration = set(existingSubeventsWithMovedEventDuration)
            existingSubeventsWithKeptEventDuration.add(movedIndex)
        else:
            existingSubeventsWithKeptEventDuration = {solEvent[1][1] for solEvent in event_role_helper_dict["event_to_subevents"][event_to_split[0]] if solEvent[1][0] == keptDuration}
        keptIndex = get_lowest_missing(existingSubeventsWithKeptEventDuration)
        movedSubevent = (movedDuration, movedIndex)
        keptSubevent = (keptDuration, keptIndex)

    if solutionData[XHSTTFileConstants.EVENTS][event_to_split][XHSTTFileConstants.TIME] != ILPConstants.DUMMY_TIME:
        oldStartTimeIndex = allTimes.index(
            solutionData[XHSTTFileConstants.EVENTS][event_to_split][XHSTTFileConstants.TIME])
        usedTimesByOriginalEvent = allTimes[oldStartTimeIndex: oldStartTimeIndex + event_to_split[1][0]]
    else:
        usedTimesByOriginalEvent = list()
    keptResources = solutionData[XHSTTFileConstants.EVENTS][event_to_split][XHSTTFileConstants.RESOURCES]
    keptTime = solutionData[XHSTTFileConstants.EVENTS][event_to_split][XHSTTFileConstants.TIME]
    keptEvent = dict()
    keptEvent[XHSTTFileConstants.TIME] = keptTime
    keptEvent[XHSTTFileConstants.RESOURCES] = keptResources
    if keptTime != ILPConstants.DUMMY_TIME:
        timeIndexKeptEvent = allTimes.index(keptTime)
        usedTimesKeptEvent = allTimes[timeIndexKeptEvent: timeIndexKeptEvent + keptSubevent[0]]
    else:
        usedTimesKeptEvent = []
    movedEvent= dict()
    movedEvent[XHSTTFileConstants.TIME] = movedTime
    movedEvent[XHSTTFileConstants.RESOURCES] = movedResources
    if movedTime != ILPConstants.DUMMY_TIME:
        timeIndexMovedEvent = allTimes.index(movedTime)
        usedTimesMovedEvent = allTimes[timeIndexMovedEvent: timeIndexMovedEvent + movedSubevent[0]]
    else:
        usedTimesMovedEvent = []
    originalSolutionEvent = solutionData[XHSTTFileConstants.EVENTS][event_to_split]
    del solutionData[XHSTTFileConstants.EVENTS][event_to_split]
    movedEventSubeventPair = (event_to_split[0], movedSubevent)
    keptEventSubeventPair = (event_to_split[0], keptSubevent)
    movedEvent[XHSTTFileConstants.ID] = movedEventSubeventPair
    movedEvent['Name'] = event_to_split[0]
    movedEvent['DeleteSubevents'] = False
    movedEvent['Duration'] = str(movedSubevent[0])
    keptEvent[XHSTTFileConstants.ID] = keptEventSubeventPair
    keptEvent['Name'] = event_to_split[0]
    keptEvent['DeleteSubevents'] = False
    keptEvent['Duration'] = str(keptSubevent[0])
    solutionData[XHSTTFileConstants.EVENTS][movedEventSubeventPair] = movedEvent
    solutionData[XHSTTFileConstants.EVENTS][keptEventSubeventPair] = keptEvent
    event_role_helper_dict["events_without_fixed_time"].append(movedEventSubeventPair)
    event_role_helper_dict["events_without_fixed_time"].append(keptEventSubeventPair)
    event_role_helper_dict["events_without_fixed_time"].remove(event_to_split)
    event_role_helper_dict["event_to_subevents"][movedEventSubeventPair[0]].append(movedEventSubeventPair)
    event_role_helper_dict["event_to_subevents"][movedEventSubeventPair[0]] = sorted(event_role_helper_dict["event_to_subevents"][movedEventSubeventPair[0]])
    event_role_helper_dict["event_to_subevents"][keptEventSubeventPair[0]].append(keptEventSubeventPair)
    event_role_helper_dict["event_to_subevents"][keptEventSubeventPair[0]] = sorted(event_role_helper_dict["event_to_subevents"][keptEventSubeventPair[0]])
    event_role_helper_dict["event_to_subevents"][event_to_split[0]].remove(event_to_split)
    event_role_helper_dict["event_to_subevents"][event_to_split[0]] = sorted(event_role_helper_dict["event_to_subevents"][event_to_split[0]])
    return (keptEventSubeventPair, movedEventSubeventPair, event_to_split), (list(keptResources.values()), list(movedResources.values()), usedTimesKeptEvent, usedTimesMovedEvent, usedTimesByOriginalEvent, originalSolutionEvent, fast_copy(movedResources), movedTime)

def fast_copy(obj):
    if isinstance(obj, dict):
        return {k: fast_copy(v) for k, v in obj.items()}
    elif isinstance(obj, set):
        return {fast_copy(x) for x in obj}
    elif isinstance(obj, list):
        return [fast_copy(x) for x in obj]
    elif isinstance(obj, tuple):
        return tuple(fast_copy(x) for x in obj)
    else:
        return obj  # immutable, safe to reuse

def get_lowest_missing(num_set):
    i = 0
    while i in num_set:
        i += 1
    return i