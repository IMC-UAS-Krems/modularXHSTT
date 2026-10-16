import copy
import random
import sys

sys.path.append('../XHSTTImporter')
sys.path.append('XHSTTImporter')
import create_relation_graphs
from XHSTTImporter.Instance import Instance
sys.path.append('../XHSTTImporter/Constants')
sys.path.append('XHSTTImporter/Constants')
import XHSTTFileConstants
import XHSTTConstraintConstants
sys.path.append('ILP_solver')
sys.path.append('../ILP_solver')
import ILPConstants
sys.path.append('SolutionExporter')
sys.path.append('../SolutionExporter')
import SolutionDataConstants


def create_list_containing_ISA_paper_neighborhoods() -> list:
    return [
        delete_n_dummy_resources,
        delete_n_dummy_times,
        delete_all_resources_based_on_time_graph,
        delete_all_times_based_on_resource_graph,
        delete_event_times_based_on_n_events_of_event_graph,
        delete_n_random_solutionevents
    ]


def delete_n_dummy_resources(instance: Instance, solutionData: dict, numberOfEvents: int, randomSelection=True, hardConstraintFocus=False, constraintIDFocus=None, deltaEvaluator=None):
    # No reason to select in any other way than random
    numberOfEvents = 5
    eventsWithDummyResources = _get_n_random_events_with_unassigned_resources(solutionData, numberOfEvents)
    if len(eventsWithDummyResources) == 0:
        return False
    events = eventsWithDummyResources + _get_n_events_out_of_list_containing_all_events_except_already_used_events(instance,
                                                                                                  numberOfEvents - len(eventsWithDummyResources),
                                                                                                  eventsWithDummyResources)
    _delete_resource_assignment_for_given_events(solutionData, events, deltaEvaluator)
    return True


def delete_n_dummy_times(instance: Instance, solutionData: dict, numberOfEvents: int, randomSelection=True, hardConstraintFocus=False, constraintIDFocus=None, deltaEvaluator=None):
    # No reason to select in any other way than random
    eventsWithDummyTimes = _get_n_random_events_with_unassigned_times(solutionData, numberOfEvents)
    if len(eventsWithDummyTimes) == 0:
        return False
    events = eventsWithDummyTimes + _get_n_events_out_of_list_containing_all_events_except_already_used_events(
        instance,
        numberOfEvents*2 - len(eventsWithDummyTimes),
        eventsWithDummyTimes)
    _delete_time_assignment_of_given_events(instance, solutionData, events, deltaEvaluator)
    return True


def delete_all_resources_based_on_time_graph(instance: Instance, solutionData: dict, numberOfTimeSlots: int, randomSelection=True, hardConstraintFocus=False, constraintIDFocus=None, deltaEvaluator=None):
    if not _is_any_constraint_violated_that_can_be_solved_through_resource_changes(instance):
        return False
    times = create_relation_graphs.select_n_times(instance, solutionData, numberOfTimeSlots, overwrite_constraint_weights=randomSelection, constraintIDFocus=constraintIDFocus)
    if len(times) == 0:
        return False
    _delete_resource_assignment_of_events_overlapping_with_given_times(instance, solutionData, times, deltaEvaluator)
    return True


def delete_all_times_based_on_resource_graph(instance: Instance, solutionData: dict, numberOfResources: int, randomSelection=True, hardConstraintFocus=False, constraintIDFocus=None, deltaEvaluator=None):
    if not _is_any_constraint_violated_that_can_be_solved_through_time_changes(instance):
        return False
    resources = create_relation_graphs.select_n_resources(instance, solutionData, numberOfResources, overwrite_constraint_weights=randomSelection, constraintIDFocus=constraintIDFocus)
    if len(resources) == 0:
        return False
    _delete_time_assignment_for_events_of_given_resources(instance, solutionData, resources, deltaEvaluator)
    return True


def delete_event_times_based_on_n_events_of_event_graph(instance: Instance, solutionData: dict, numberOfTimeSlots: int, randomSelection=True, hardConstraintFocus=False, constraintIDFocus=None, deltaEvaluator=None):
    if not _is_any_constraint_violated_that_can_be_solved_through_time_changes(instance):
        return False
    events = create_relation_graphs.select_n_events(instance, solutionData, numberOfTimeSlots, overwrite_constraint_weights=randomSelection, constraintIDFocus=constraintIDFocus)
    if len(events) == 0:
        return False
    _delete_time_assignment_of_given_events(instance, solutionData, events, deltaEvaluator)
    return True


def delete_n_random_solutionevents(instance: Instance, solutionData: dict, numberOfEvents: int, randomSelection=True, hardConstraintFocus=False, constraintIDFocus=None, deltaEvaluator=None):
    if randomSelection:
        allSolutionEvents = list(solutionData[XHSTTFileConstants.EVENTS].keys())
        events = random.sample(allSolutionEvents, k=min(len(allSolutionEvents), numberOfEvents))
    else:
        selectedEventNumber, events = _select_n_random_events_from_a_random_violated_subevent_based_constraint(instance,
                                                                                                           numberOfEvents, hardOnly=hardConstraintFocus, specificConstraint=constraintIDFocus, useSolutionEvents=True)
        if selectedEventNumber == 0:
            return False
        events += _get_n_solutionevents_out_of_list_containing_all_solutionevents_except_already_used_solutionevents(instance, solutionData,
                                                                                             numberOfEvents - selectedEventNumber,
                                                                                             events)
    _delete_given_solutionevents(instance, solutionData, events, deltaEvaluator)
    return True


def _delete_given_solutionevents(instance: Instance, solutionData: dict, deletedEvents: list, deltaEvaluator=None):
    for deletedEvent in deletedEvents:
        if deltaEvaluator is not None:
            resourcesOfDeletedEvent = [solutionData[XHSTTFileConstants.EVENTS][deletedEvent][XHSTTFileConstants.RESOURCES][role] for role in solutionData[XHSTTFileConstants.EVENTS][deletedEvent][XHSTTFileConstants.RESOURCES].keys()]
            timesOfDeletedEvent = _get_times_at_which_solution_event_is_running(instance, solutionData[XHSTTFileConstants.EVENTS][deletedEvent])
            deltaEvaluator.delete_event(deletedEvent, timesOfDeletedEvent, resourcesOfDeletedEvent)
        del solutionData[XHSTTFileConstants.EVENTS][deletedEvent]


def _delete_resource_assignment_for_given_events(solutionData: dict, events: list, deltaEvaluator=None):
    for event in solutionData[XHSTTFileConstants.EVENTS].keys():
        solutionEvent = solutionData[XHSTTFileConstants.EVENTS][event]
        if event[0] in events:
            for role in solutionEvent[XHSTTFileConstants.RESOURCES].keys():
                if deltaEvaluator is not None:
                    if solutionEvent[XHSTTFileConstants.RESOURCES][role] is not None:
                        deltaEvaluator.assign_new_resource_to_event(event,
                                                                    solutionEvent[XHSTTFileConstants.RESOURCES][role],
                                                                    ILPConstants.DUMMY_RESOURCE, role=role)
                solutionEvent[XHSTTFileConstants.RESOURCES][role] = None


def _delete_resource_assignment_of_events_overlapping_with_given_times(instance: Instance, solutionData: dict, times: list, deltaEvaluator=None):
    for event in solutionData[XHSTTFileConstants.EVENTS].keys():
        assignedResourceRoles = [eventResource.Role for eventResource in instance.Events.IndividualEvents[event[0]].EventResources.AssignedResources]
        solutionEvent = solutionData[XHSTTFileConstants.EVENTS][event]
        timesInWhichSolutionEventIsRunning = _get_times_at_which_solution_event_is_running(instance, solutionEvent)
        for time in timesInWhichSolutionEventIsRunning:
            if time in times:
                for role in solutionEvent[XHSTTFileConstants.RESOURCES].keys():
                    if role in assignedResourceRoles:
                        continue
                    if deltaEvaluator is not None:
                        if solutionEvent[XHSTTFileConstants.RESOURCES][role] is not None:
                            deltaEvaluator.assign_new_resource_to_event(event, solutionEvent[XHSTTFileConstants.RESOURCES][role], ILPConstants.DUMMY_RESOURCE, role=role)
                    solutionEvent[XHSTTFileConstants.RESOURCES][role] = None
                continue


def _delete_time_assignment_for_events_of_given_resources(instance: Instance, solutionData: dict, resources: list, deltaEvaluator=None):
    for event in solutionData[XHSTTFileConstants.EVENTS].keys():
        solutionEvent = solutionData[XHSTTFileConstants.EVENTS][event]
        for role in solutionEvent[XHSTTFileConstants.RESOURCES].keys():
            if solutionEvent[XHSTTFileConstants.RESOURCES][role] in resources:
                solutionEvent[XHSTTFileConstants.TIME] = None
                timesInWhichSolutionEventIsRunning = _get_times_at_which_solution_event_is_running(instance,
                                                                                                   solutionEvent)
                if deltaEvaluator is not None:
                    deltaEvaluator.assign_new_time_to_event(event, timesInWhichSolutionEventIsRunning, list(), list())


def _delete_time_assignment_of_given_events(instance: Instance, solutionData: dict, events: list, deltaEvaluator=None):
    for event in solutionData[XHSTTFileConstants.EVENTS].keys():
        solutionEvent = solutionData[XHSTTFileConstants.EVENTS][event]
        if event[0] in events:
            solutionEvent[XHSTTFileConstants.TIME] = None
            timesInWhichSolutionEventIsRunning = _get_times_at_which_solution_event_is_running(instance, solutionEvent)
            if deltaEvaluator is not None:
                deltaEvaluator.assign_new_time_to_event(event, timesInWhichSolutionEventIsRunning, list(), list())


def _get_individual_events_from_list_of_deviation_events(constraintDeviationEvents: list, useSolutionEvents=False) -> list:
    if useSolutionEvents:
        return list({deviationEvent[XHSTTFileConstants.ID] for deviationEvent in constraintDeviationEvents
                     if deviationEvent[XHSTTFileConstants.TIME] != ILPConstants.DUMMY_TIME})
    else:
        return list({deviationEvent[XHSTTFileConstants.NAME] for deviationEvent in constraintDeviationEvents
                     if deviationEvent[XHSTTFileConstants.TIME] != ILPConstants.DUMMY_TIME})


def _get_n_events_out_of_list_containing_all_events_except_already_used_events(instance: Instance, numberOfEvents: int, usedEvents: list, onlyEventsWithUnassignedResources=False):
    eventListCopy = copy.deepcopy(list(instance.Events.IndividualEvents.keys()))
    for event in usedEvents:
        if event in eventListCopy:
            eventListCopy.remove(event)

    if onlyEventsWithUnassignedResources:
        _remove_events_with_no_unassigned_resources_from_list_of_events(instance, eventListCopy)
    addititionalEvents = random.sample(eventListCopy, k=min(numberOfEvents, len(eventListCopy)))
    return addititionalEvents


def _get_n_random_events_with_unassigned_resources(solutionData: dict, numberOfEvents: int):
    events_with_unassigned_resources = set()

    for solutionevent in solutionData[XHSTTFileConstants.EVENTS].values():
        for role in solutionevent[XHSTTFileConstants.RESOURCES].keys():
            if solutionevent[XHSTTFileConstants.RESOURCES][role] == ILPConstants.DUMMY_RESOURCE:
                events_with_unassigned_resources.update([solutionevent[SolutionDataConstants.NAME]])

    return random.sample(list(events_with_unassigned_resources), k=min(len(events_with_unassigned_resources), numberOfEvents))


def _get_n_random_events_with_unassigned_times(solutionData: dict, numberOfEvents: int):
    events_with_unassigned_times = set()
    for solutionEventID, solutionevent in solutionData[XHSTTFileConstants.EVENTS].items():
        if solutionevent[XHSTTFileConstants.TIME] == ILPConstants.DUMMY_TIME:
            events_with_unassigned_times.update([solutionEventID[0]])

    return random.sample(list(events_with_unassigned_times), k=min(len(events_with_unassigned_times), numberOfEvents))


def _get_n_solutionevents_out_of_list_containing_all_solutionevents_except_already_used_solutionevents(instance: Instance, solutionData, numberOfEvents: int, usedSolutionevents: list, onlyEventsWithUnassignedResources=False):
    eventListCopy = copy.deepcopy(list(solutionData[XHSTTFileConstants.EVENTS].keys()))
    for solutionevent in usedSolutionevents:
        if solutionevent in eventListCopy:
            eventListCopy.remove(solutionevent)
    if onlyEventsWithUnassignedResources:
        _remove_events_with_no_unassigned_resources_from_list_of_events(instance, eventListCopy)
    addititionalSolutionevents = random.sample(eventListCopy, k=min(numberOfEvents, len(eventListCopy)))
    return addititionalSolutionevents


def _get_times_at_which_solution_event_is_running(instance: Instance, solutionEvent):
    if solutionEvent[XHSTTFileConstants.TIME] == ILPConstants.DUMMY_TIME or solutionEvent[XHSTTFileConstants.TIME] is None:
        return list()
    listOfTimes = list(instance.Times.IndividualTimes.keys())
    indexOfTime = listOfTimes.index(solutionEvent[XHSTTFileConstants.TIME])
    return listOfTimes[indexOfTime:indexOfTime + int(solutionEvent[XHSTTFileConstants.DURATION])]


def _is_any_constraint_violated_that_can_be_solved_through_resource_changes(instance: Instance):
    for constraintType in [XHSTTConstraintConstants.ASSIGN_RESOURCE_CONSTRAINT,
                           XHSTTConstraintConstants.PREFER_RESOURCES_CONSTRAINT,
                           XHSTTConstraintConstants.AVOID_SPLIT_ASSIGNMENTS_CONSTRAINT,
                           XHSTTConstraintConstants.AVOID_CLASHES_CONSTRAINT,
                           XHSTTConstraintConstants.AVOID_UNAVAILABLE_TIMES_CONSTRAINT,
                           XHSTTConstraintConstants.LIMIT_IDLE_TIMES_CONSTRAINT,
                           XHSTTConstraintConstants.LIMIT_BUSY_TIMES_CONSTRAINT,
                           XHSTTConstraintConstants.CLUSTER_BUSY_TIMES_CONSTRAINT,
                           XHSTTConstraintConstants.LIMIT_WORKLOAD_CONSTRAINT,
                           XHSTTConstraintConstants.STUDENT_CHOICE_CONSTRAINT,
                           XHSTTConstraintConstants.BALANCE_CLASS_SIZE_CONSTRAINT]:
        for constraint in instance.Constraints.get(constraintType, list()):
            if not constraint[XHSTTConstraintConstants.IS_FULFILLED]:
                return True
    return False


def _is_any_constraint_violated_that_can_be_solved_through_time_changes(instance: Instance):
    for constraintType in [XHSTTConstraintConstants.ASSIGN_TIME_CONSTRAINT, XHSTTConstraintConstants.PREFER_TIMES_CONSTRAINT,
                           XHSTTConstraintConstants.SPREAD_EVENTS_CONSTRAINT, XHSTTConstraintConstants.LINK_EVENTS_CONSTRAINT,
                           XHSTTConstraintConstants.AVOID_CLASHES_CONSTRAINT, XHSTTConstraintConstants.AVOID_UNAVAILABLE_TIMES_CONSTRAINT,
                           XHSTTConstraintConstants.LIMIT_IDLE_TIMES_CONSTRAINT, XHSTTConstraintConstants.LIMIT_BUSY_TIMES_CONSTRAINT,
                           XHSTTConstraintConstants.CLUSTER_BUSY_TIMES_CONSTRAINT]:
        for constraint in instance.Constraints.get(constraintType, list()):
            if not constraint[XHSTTConstraintConstants.IS_FULFILLED]:
                return True
    return False


def _remove_events_with_no_unassigned_resources_from_list_of_events(instance: Instance, eventList):
    deletedEvents = list()
    for event in eventList:
        if type(event) is tuple:
            eventId = event[0]
        else:
            eventId = event
        if len(instance.Events.IndividualEvents[eventId].EventResources.UnassignedResources) == 0:
            deletedEvents.append(event)
    for event in deletedEvents:
        eventList.remove(event)


def _select_n_random_events_from_a_list_of_deviation_events(instance: Instance, numberOfEvents: int, constraintDeviationEvents: list, useSolutionEvents=False, onlyEventsWithUnassignedResources=False) -> (int, list):
    deviationEvents = _get_individual_events_from_list_of_deviation_events(constraintDeviationEvents, useSolutionEvents)
    if onlyEventsWithUnassignedResources:
        _remove_events_with_no_unassigned_resources_from_list_of_events(instance, deviationEvents)
    if len(deviationEvents) == 0:
        return 0, list()
    numberOfSelectionsFromDeviationEvents = min(numberOfEvents, len(deviationEvents))
    events = random.sample(deviationEvents, k=numberOfSelectionsFromDeviationEvents)
    return len(events), events


def _select_n_random_events_from_a_random_violated_subevent_based_constraint(instance: Instance, numberOfEvents: int, hardOnly=False, specificConstraint=None, useSolutionEvents=False) -> (int, list):
    selectedConstraint = _select_random_subevent_based_violated_constraint(instance, hardOnly=hardOnly, selectIfExists=specificConstraint)
    if selectedConstraint is None:
        return 0, list()
    constraintDeviationEvents = selectedConstraint[XHSTTConstraintConstants.DEVIATION_EVENTS]
    return _select_n_random_events_from_a_list_of_deviation_events(instance, numberOfEvents, constraintDeviationEvents, useSolutionEvents)


def _select_random_resource_based_violated_constraint(instance: Instance, hardOnly=False, selectIfExists=None) -> dict:
    listOfResourceBasedConstraints = list()
    for constraintType in instance.Constraints.keys():
        if constraintType in [XHSTTConstraintConstants.ASSIGN_RESOURCE_CONSTRAINT, XHSTTConstraintConstants.PREFER_RESOURCES_CONSTRAINT,
                              XHSTTConstraintConstants.AVOID_SPLIT_ASSIGNMENTS_CONSTRAINT, XHSTTConstraintConstants.AVOID_CLASHES_CONSTRAINT,
                              XHSTTConstraintConstants.AVOID_UNAVAILABLE_TIMES_CONSTRAINT, XHSTTConstraintConstants.LIMIT_IDLE_TIMES_CONSTRAINT,
                              XHSTTConstraintConstants.CLUSTER_BUSY_TIMES_CONSTRAINT, XHSTTConstraintConstants.LIMIT_BUSY_TIMES_CONSTRAINT,
                              XHSTTConstraintConstants.LIMIT_WORKLOAD_CONSTRAINT, XHSTTConstraintConstants.BALANCE_CLASS_SIZE_CONSTRAINT,
                              XHSTTConstraintConstants.STUDENT_CHOICE_CONSTRAINT]:
            for constraint in instance.Constraints[constraintType]:
                if hardOnly and not constraint[XHSTTConstraintConstants.REQUIRED]:
                    continue
                if not constraint[XHSTTConstraintConstants.IS_FULFILLED] and len(constraint[XHSTTConstraintConstants.DEVIATION_EVENTS]) > 0:
                    hasDeviationEventWithAnUnassignedResource = False
                    for deviationEvent in constraint[XHSTTConstraintConstants.DEVIATION_EVENTS]:
                        for role in deviationEvent[XHSTTFileConstants.RESOURCES]:
                            if XHSTTFileConstants.NO_ROLE not in role:
                                hasDeviationEventWithAnUnassignedResource = True
                    if hasDeviationEventWithAnUnassignedResource:
                        listOfResourceBasedConstraints.append(constraint)

    if len(listOfResourceBasedConstraints) == 0:
        return None
    else:
        if selectIfExists is None or selectIfExists not in [constraint[XHSTTConstraintConstants.ID] for constraint in
                                                            listOfResourceBasedConstraints]:
            chosen_constraint = random.choice(listOfResourceBasedConstraints)
        else:
            chosen_constraint = [constraint for constraint in listOfResourceBasedConstraints if
                                 constraint[XHSTTConstraintConstants.ID] == selectIfExists][0]
        return chosen_constraint


def _select_random_subevent_based_violated_constraint(instance: Instance, hardOnly=False, selectIfExists=None) -> dict:
    listOfSubeventBasedConstraints = list()
    for constraintType in instance.Constraints.keys():
        if constraintType in [XHSTTConstraintConstants.SPLIT_EVENTS_CONSTRAINT,
                              XHSTTConstraintConstants.DISTRIBUTE_SPLIT_EVENTS_CONSTRAINT,
                              XHSTTConstraintConstants.SPREAD_EVENTS_CONSTRAINT,
                              XHSTTConstraintConstants.LIMIT_IDLE_TIMES_CONSTRAINT,
                              XHSTTConstraintConstants.CLUSTER_BUSY_TIMES_CONSTRAINT,
                              XHSTTConstraintConstants.LINK_EVENTS_CONSTRAINT]:
            for constraint in instance.Constraints[constraintType]:
                if hardOnly and not constraint[XHSTTConstraintConstants.REQUIRED]:
                    continue
                if not constraint[XHSTTConstraintConstants.IS_FULFILLED] and len(constraint[XHSTTConstraintConstants.DEVIATION_EVENTS]) > 0:
                    listOfSubeventBasedConstraints.append(constraint)

    if len(listOfSubeventBasedConstraints) == 0:
        return _select_random_time_and_resource_based_violated_constraint(instance, hardOnly, selectIfExists)
    else:
        if selectIfExists is None or selectIfExists not in [constraint[XHSTTConstraintConstants.ID] for constraint in
                                                            listOfSubeventBasedConstraints]:
            selectedConstraint = random.choice(listOfSubeventBasedConstraints)
        else:
            selectedConstraint = [constraint for constraint in listOfSubeventBasedConstraints if
                                  constraint[XHSTTConstraintConstants.ID] == selectIfExists][0]
        return selectedConstraint


def _select_random_time_and_resource_based_violated_constraint(instance: Instance, hardOnly=False, selectIfExists=None) -> dict:
    listOfTimeAndResourceBasedConstraints = list()
    for constraintType in instance.Constraints.keys():
        if constraintType in [XHSTTConstraintConstants.AVOID_CLASHES_CONSTRAINT,
                              XHSTTConstraintConstants.AVOID_UNAVAILABLE_TIMES_CONSTRAINT,
                              XHSTTConstraintConstants.LIMIT_IDLE_TIMES_CONSTRAINT,
                              XHSTTConstraintConstants.CLUSTER_BUSY_TIMES_CONSTRAINT,
                              XHSTTConstraintConstants.LIMIT_BUSY_TIMES_CONSTRAINT,
                              XHSTTConstraintConstants.BALANCE_CLASS_SIZE_CONSTRAINT,
                              XHSTTConstraintConstants.STUDENT_CHOICE_CONSTRAINT]:
            for constraint in instance.Constraints[constraintType]:
                if hardOnly and not constraint[XHSTTConstraintConstants.REQUIRED]:
                    continue
                if not constraint[XHSTTConstraintConstants.IS_FULFILLED] and len(constraint[XHSTTConstraintConstants.DEVIATION_EVENTS]) > 0:
                    hasDeviationEventWithAnUnassignedResource = False
                    for deviationEvent in constraint[XHSTTConstraintConstants.DEVIATION_EVENTS]:
                        for role in deviationEvent[XHSTTFileConstants.RESOURCES]:
                            if XHSTTFileConstants.NO_ROLE not in role:
                                hasDeviationEventWithAnUnassignedResource = True
                    if hasDeviationEventWithAnUnassignedResource:
                        listOfTimeAndResourceBasedConstraints.append(constraint)

    if len(listOfTimeAndResourceBasedConstraints) == 0:
        chosen_constraint = _select_random_time_based_violated_constraint(instance, hardOnly, selectIfExists)
        if chosen_constraint is None:
            chosen_constraint = _select_random_resource_based_violated_constraint(instance, hardOnly, selectIfExists)
        return chosen_constraint
    else:
        if selectIfExists is None or selectIfExists not in [constraint[XHSTTConstraintConstants.ID] for constraint in
                                                            listOfTimeAndResourceBasedConstraints]:
            chosen_constraint = random.choice(listOfTimeAndResourceBasedConstraints)
        else:
            chosen_constraint = [constraint for constraint in listOfTimeAndResourceBasedConstraints if
                                 constraint[XHSTTConstraintConstants.ID] == selectIfExists][0]
        return chosen_constraint


def _select_random_time_based_violated_constraint(instance: Instance, hardOnly=False, selectIfExists=None) -> dict:
    listOfTimeBasedConstraints = list()
    for constraintType in instance.Constraints.keys():
        if constraintType in [XHSTTConstraintConstants.ASSIGN_TIME_CONSTRAINT, XHSTTConstraintConstants.PREFER_TIMES_CONSTRAINT,
                              XHSTTConstraintConstants.SPREAD_EVENTS_CONSTRAINT, XHSTTConstraintConstants.LINK_EVENTS_CONSTRAINT,
                              XHSTTConstraintConstants.AVOID_CLASHES_CONSTRAINT, XHSTTConstraintConstants.AVOID_UNAVAILABLE_TIMES_CONSTRAINT,
                              XHSTTConstraintConstants.LIMIT_IDLE_TIMES_CONSTRAINT, XHSTTConstraintConstants.CLUSTER_BUSY_TIMES_CONSTRAINT,
                              XHSTTConstraintConstants.LIMIT_BUSY_TIMES_CONSTRAINT]:
            for constraint in instance.Constraints[constraintType]:
                if hardOnly and not constraint[XHSTTConstraintConstants.REQUIRED]:
                    continue
                if not constraint[XHSTTConstraintConstants.IS_FULFILLED] and len(constraint[XHSTTConstraintConstants.DEVIATION_EVENTS]) > 0:
                    listOfTimeBasedConstraints.append(constraint)
    if len(listOfTimeBasedConstraints) == 0:
        return None
    else:
        if selectIfExists is None or selectIfExists not in [constraint[XHSTTConstraintConstants.ID] for constraint in listOfTimeBasedConstraints]:
            chosen_constraint = random.choice(listOfTimeBasedConstraints)
        else:
            chosen_constraint = [constraint for constraint in listOfTimeBasedConstraints if constraint[XHSTTConstraintConstants.ID] == selectIfExists][0]
        return chosen_constraint