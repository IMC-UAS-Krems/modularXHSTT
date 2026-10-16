import copy
import math
import sys
sys.path.append('../ILP_solver')
sys.path.append('ILP_solver')
from ILP_solver import ILPConstants
sys.path.append('../XHSTTImporter')
sys.path.append('XHSTTImporter')
from XHSTTImporter.Instance import Instance
sys.path.append('../XHSTTImporter/Constants')
sys.path.append('XHSTTImporter/Constants')
import XHSTTFileConstants
import XHSTTConstraintConstants
sys.path.append('../validator')
sys.path.append('validator')
import validator
import SA_neighborhoods
import random
import time
def do_n_iterations_of_simulated_annealing_with_cutoff(instance: Instance, initial_solution: dict, total_iterations: int = 1000000, start_acceptance_rate: float = 0.1, end_acceptance_rate: float = 0.0001, cooling_rate: float = 0.955, cutoff_ratio: float = 0.16, neighborhood_probabilities: list = None, limit_searchspace=False, output=True):
    instance = copy.deepcopy(instance)
    for constraintType in instance.Constraints.keys():
        for constraint in instance.Constraints[constraintType]:
            constraint[XHSTTConstraintConstants.WEIGHT_COPY] = float(constraint[XHSTTConstraintConstants.WEIGHT])
            constraint[XHSTTConstraintConstants.WEIGHT] = float(constraint[XHSTTConstraintConstants.WEIGHT])
    allTimes = list(instance.Times.IndividualTimes.keys())
    events_with_free_resources = list()
    events_with_free_times = list()
    if limit_searchspace:
        allTimes = list(instance.Times.IndividualTimes.keys())
        if "possibleTimes" in initial_solution:
            possibleTimes = initial_solution["possibleTimes"]
        else:
            possibleTimes = allTimes
        if "dummyTime" in possibleTimes:
            possibleTimes.remove("dummyTime")
        for event in initial_solution[XHSTTFileConstants.EVENTS].keys():
            solutionEvent = initial_solution[XHSTTFileConstants.EVENTS][event]
            if XHSTTFileConstants.TIME not in solutionEvent.keys() or XHSTTFileConstants.RESOURCES not in solutionEvent.keys():
                continue
            resourcesWithoutFixation = [resource for resource in solutionEvent[XHSTTFileConstants.RESOURCES].keys()
                                     if solutionEvent[XHSTTFileConstants.RESOURCES][resource] is None]
            for resource in resourcesWithoutFixation:
                solutionEvent[XHSTTFileConstants.RESOURCES][resource] = "dummyResource"
            for resource in instance.Events.IndividualEvents[event[0]].EventResources.AssignedResources:
                solutionEvent[XHSTTFileConstants.RESOURCES][resource.Role] = resource.Reference
                if resource.Role in resourcesWithoutFixation:
                    resourcesWithoutFixation.remove(resource.Role)
            if len(resourcesWithoutFixation) > 0:
                events_with_free_resources.append(event)
            if solutionEvent[XHSTTFileConstants.TIME] is None:
                solutionEvent[XHSTTFileConstants.TIME] = "dummyTime"
                events_with_free_times.append(event)
    else:
        events_with_free_resources = initial_solution[XHSTTFileConstants.EVENTS].keys()
        events_with_free_times = initial_solution[XHSTTFileConstants.EVENTS].keys()
        possibleTimes = allTimes
    searchspace = {"eventsWithFreeTimes": events_with_free_times, "eventsWithFreeResources": events_with_free_resources, "possibleTimes": possibleTimes}
    if XHSTTConstraintConstants.ASSIGN_RESOURCE_CONSTRAINT in instance.Constraints.keys():
        neighborhoods = [SA_neighborhoods.swap_resource,
                         SA_neighborhoods.swap_resource_for_all_subevents,
                         SA_neighborhoods.change_resource_for_all_subevents,
                         SA_neighborhoods.change_resource, SA_neighborhoods.swap_times,
                         SA_neighborhoods.block_swap_times, SA_neighborhoods.move_event,
                         SA_neighborhoods.combine_subevents, SA_neighborhoods.split_subevent]
        if neighborhood_probabilities is None:
            probabilities = [0.2, 0.1, 0.1, 0.1, 0.15, 0.1, 0.25]
        else:
            probabilities = neighborhood_probabilities
    else:
        neighborhoods = [SA_neighborhoods.swap_times,
                         SA_neighborhoods.block_swap_times, SA_neighborhoods.move_event, SA_neighborhoods.move_linked_events]
        if neighborhood_probabilities is None:
            probabilities = [0.3, 0.2, 0.4, 0.1]
        else:
            probabilities = neighborhood_probabilities
    if output:
        print(f"neighborhoods: {neighborhoods}")
    best_known_solution = copy.deepcopy(initial_solution)
    current_solution = copy.deepcopy(initial_solution)
    start_solution = copy.deepcopy(initial_solution)
    for event in best_known_solution[XHSTTFileConstants.EVENTS].keys():
        if best_known_solution[XHSTTFileConstants.EVENTS][event][XHSTTFileConstants.TIME] is None:
            best_known_solution[XHSTTFileConstants.EVENTS][event][XHSTTFileConstants.TIME] = ILPConstants.DUMMY_TIME
            current_solution[XHSTTFileConstants.EVENTS][event][XHSTTFileConstants.TIME] = ILPConstants.DUMMY_TIME
            start_solution[XHSTTFileConstants.EVENTS][event][XHSTTFileConstants.TIME] = ILPConstants.DUMMY_TIME
        for role in best_known_solution[XHSTTFileConstants.EVENTS][event][XHSTTFileConstants.RESOURCES].keys():
            if best_known_solution[XHSTTFileConstants.EVENTS][event][XHSTTFileConstants.RESOURCES][role] is None:
                best_known_solution[XHSTTFileConstants.EVENTS][event][XHSTTFileConstants.RESOURCES][role] = ILPConstants.DUMMY_RESOURCE
                current_solution[XHSTTFileConstants.EVENTS][event][XHSTTFileConstants.RESOURCES][
                    role] = ILPConstants.DUMMY_RESOURCE
                start_solution[XHSTTFileConstants.EVENTS][event][XHSTTFileConstants.RESOURCES][
                    role] = ILPConstants.DUMMY_RESOURCE
    try:
        best_known_objective_value = validator.get_objective_value(instance, best_known_solution, outputObjectiveValues=output)
    except ValueError:
        print("Invalid Starting solution provided")
        return None
    if output:
        print(best_known_objective_value)
    deltaEvalInstance = copy.deepcopy(instance)
    eval_time = 0
    move_time = dict()
    for neighborhood in neighborhoods:
        move_time[neighborhood.__name__] = 0
    overhead_time = 0
    last_temp_change = 0
    accepted_counter = 0
    event_role_to_possible_resources_dict = dict()
    event_group_role_to_possible_resources_dict = dict()
    resourceToRolesDict = dict()
    resourceToEventGroupRolesDict = dict()
    events_with_flexible_subevents = set()
    eventToCurrentSubevents = dict()
    for constraint in instance.Constraints[XHSTTConstraintConstants.PREFER_RESOURCES_CONSTRAINT]:
        if not constraint[XHSTTConstraintConstants.REQUIRED]:
            continue
        consideredEvents = [
            (constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS][eventindex], eventindex) for
            eventindex in
            range(len(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS]))]
        for eventGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
            consideredEvents = consideredEvents + [(event, "Group" + str(eventGroup)) for event in
                                                   instance.Events.EventGroups[eventGroup].Events]
        preferredResources = set(constraint[XHSTTFileConstants.RESOURCES])
        for resourceGroup in constraint[XHSTTFileConstants.RESOURCE_GROUPS]:
            for resourceType in instance.Resources.ResourceGroupsByType.keys():
                if resourceGroup in instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups:
                    preferredResources.update(set(
                        instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups[resourceGroup].Resources))
        for event in consideredEvents:
            rolesOfEvent = [eventResource.Role for eventResource in instance.Events.IndividualEvents[event[0]].EventResources.UnassignedResources]
            if constraint[XHSTTFileConstants.ROLE] not in rolesOfEvent:
                continue
            event_role_to_possible_resources_dict.setdefault((event[0], constraint[XHSTTFileConstants.ROLE]),
                                                             preferredResources)
            event_role_to_possible_resources_dict[(event[0], constraint[XHSTTFileConstants.ROLE])] = \
            event_role_to_possible_resources_dict[(event[0], constraint[XHSTTFileConstants.ROLE])].intersection(
                preferredResources)
    for event in instance.Events.IndividualEvents.keys():
        if instance.Events.IndividualEvents[event].Time is None and instance.Events.IndividualEvents[event].Duration >= 2:
            events_with_flexible_subevents.add(event)
        for eventResource in instance.Events.IndividualEvents[event].EventResources.UnassignedResources:
            resourcesWithSameType = {resource for resource in instance.Resources.IndividualResources.keys() if
                                     instance.Resources.IndividualResources[
                                         resource].Type == eventResource.ResourceType}
            event_role_to_possible_resources_dict.setdefault((event, eventResource.Role), resourcesWithSameType)
            event_role_to_possible_resources_dict[(event, eventResource.Role)] = list(event_role_to_possible_resources_dict[(event, eventResource.Role)])
            for resource in event_role_to_possible_resources_dict[(event, eventResource.Role)]:
                resourceToRolesDict.setdefault(resource, set()).add((event, eventResource.Role))
    for constraint in instance.Constraints[XHSTTConstraintConstants.AVOID_SPLIT_ASSIGNMENTS_CONSTRAINT]:
        for eventGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
            possibleResourcesForEventGroup = set(instance.Resources.IndividualResources.keys())
            for event in instance.Events.EventGroups[eventGroup].Events:
                possibleResourcesForEventGroup = possibleResourcesForEventGroup.intersection(set(event_role_to_possible_resources_dict[(event, constraint[XHSTTFileConstants.ROLE])]))
            event_group_role_to_possible_resources_dict[(eventGroup, constraint[XHSTTFileConstants.ROLE])] = list(possibleResourcesForEventGroup)
            for resource in event_group_role_to_possible_resources_dict[(eventGroup, constraint[XHSTTFileConstants.ROLE])]:
                resourceToEventGroupRolesDict.setdefault(resource, set()).add((eventGroup, constraint[XHSTTFileConstants.ROLE]))
    for solEvent in initial_solution[XHSTTFileConstants.EVENTS].keys():
        eventToCurrentSubevents.setdefault(solEvent[0], list()).append(solEvent)

    for event in instance.Events.IndividualEvents.keys():
        if event not in eventToCurrentSubevents:
            print("Invalid Starting solution provided")
            return None

    eventRoleHelperDict = dict()
    eventRoleHelperDict["event_to_subevents"] = eventToCurrentSubevents
    eventRoleHelperDict["events_with_flexible_subevents"] = events_with_flexible_subevents
    eventRoleHelperDict["possible_resources_events"] = event_role_to_possible_resources_dict
    eventRoleHelperDict["resource_to_possible_roles_events"] = resourceToRolesDict
    eventRoleHelperDict["possible_resources_event_groups"] = event_group_role_to_possible_resources_dict
    eventRoleHelperDict["resource_to_possible_roles_event_groups"] = resourceToEventGroupRolesDict
    if searchspace["eventsWithFreeTimes"] is not None:
        eventRoleHelperDict["events_without_fixed_time"] = [solevent for solevent in current_solution[XHSTTFileConstants.EVENTS].keys() if instance.Events.IndividualEvents[solevent[0]].Time is None]
    else:
        eventRoleHelperDict["events_without_fixed_time"] = [solevent for solevent in
                                                            searchspace["eventsWithFreeTimes"] if
                                                            instance.Events.IndividualEvents[solevent[0]].Time is None]
    deltaEvaluator = validator.DeltaEvaluator(deltaEvalInstance, current_solution)
    randomWalkDeltaEvaluator = copy.deepcopy(deltaEvaluator)
    current_solution_delta_eval = randomWalkDeltaEvaluator.get_current_solution()
    current_solution_objective_value = deltaEvaluator.get_current_objective_value()
    current_solution_objective_value_delta_eval = randomWalkDeltaEvaluator.get_current_objective_value()
    best_known_objective_value = validator.get_objective_value(instance, best_known_solution,
                                                               outputObjectiveValues=False)
    totalCopyTime1 = 0.0
    totalCopyTime2 = 0.0
    totalWeightChangeTimeBestKnown = 0.0
    totalWeightChangeTimeCurrent = 0.0

    solutionDifList = list()
    worseningSolutionDifList = list()
    helperDictStart = copy.deepcopy(eventRoleHelperDict)
    helperDictCopy = copy.deepcopy(eventRoleHelperDict)
    for i in range(5000):
        random_neighborhood = random.choices(neighborhoods, weights=probabilities, k=1)[0]
        restore_params, extra_info = random_neighborhood(instance, current_solution_delta_eval, searchSpace=None,
                                                         event_role_helper_dict=helperDictCopy)
        if restore_params is not None:
            if random_neighborhood == SA_neighborhoods.swap_resource:
                randomWalkDeltaEvaluator.assign_new_resource_to_event(restore_params[0], extra_info[0], extra_info[1])
                randomWalkDeltaEvaluator.assign_new_resource_to_event(restore_params[1], extra_info[1], extra_info[0])
            elif random_neighborhood == SA_neighborhoods.swap_resource_for_all_subevents:
                for j in range(len(extra_info[0])):
                    randomWalkDeltaEvaluator.assign_new_resource_to_event(extra_info[0][j], extra_info[2], extra_info[3])
                for j in range(len(extra_info[1])):
                    randomWalkDeltaEvaluator.assign_new_resource_to_event(extra_info[1][j], extra_info[3], extra_info[2])
            elif random_neighborhood == SA_neighborhoods.change_resource_for_all_subevents:
                for j in range(len(extra_info[0])):
                    randomWalkDeltaEvaluator.assign_new_resource_to_event(extra_info[0][j], extra_info[1][j], extra_info[2][j])
            elif random_neighborhood == SA_neighborhoods.change_resource:
                randomWalkDeltaEvaluator.assign_new_resource_to_event(restore_params[0], extra_info[0], extra_info[1])
            elif random_neighborhood == SA_neighborhoods.swap_times:
                randomWalkDeltaEvaluator.assign_new_time_to_event(restore_params[0], extra_info[0][0], extra_info[0][1],
                                                        extra_info[2])
                randomWalkDeltaEvaluator.assign_new_time_to_event(restore_params[1], extra_info[1][0], extra_info[1][1],
                                                        extra_info[2])
            elif random_neighborhood == SA_neighborhoods.block_swap_times:
                randomWalkDeltaEvaluator.assign_new_time_to_event(restore_params[0], extra_info[1][0], extra_info[1][1],
                                                        extra_info[2])
                randomWalkDeltaEvaluator.assign_new_time_to_event(restore_params[1], extra_info[0][0], extra_info[0][1],
                                                        extra_info[2])
            elif random_neighborhood == SA_neighborhoods.move_event:
                randomWalkDeltaEvaluator.assign_new_time_to_event(restore_params[0], extra_info[0], extra_info[1], set())
            elif random_neighborhood == SA_neighborhoods.move_linked_events:
                for eventIndex in range(len(restore_params[0])):
                    randomWalkDeltaEvaluator.assign_new_time_to_event(restore_params[0][eventIndex], extra_info[0][eventIndex],
                                                            extra_info[1][eventIndex], set())
            elif random_neighborhood == SA_neighborhoods.combine_subevents:
                randomWalkDeltaEvaluator.delete_event(extra_info[4], extra_info[2], extra_info[0])
                randomWalkDeltaEvaluator.delete_event(extra_info[5], extra_info[3], extra_info[1])
                randomWalkDeltaEvaluator.add_event(restore_params[0], extra_info[6], extra_info[1])
            elif random_neighborhood == SA_neighborhoods.split_subevent:
                randomWalkDeltaEvaluator.delete_event(restore_params[2], extra_info[4], extra_info[0])
                randomWalkDeltaEvaluator.add_event(restore_params[0], extra_info[2], extra_info[0])
                randomWalkDeltaEvaluator.add_event(restore_params[1], extra_info[3], extra_info[1])
        new_objective_value = randomWalkDeltaEvaluator.get_current_objective_value()
        if output:
            print(f"Random Walk Obj Value: {new_objective_value}")
        solution_diff = current_solution_objective_value_delta_eval - new_objective_value
        solutionDifList.append(abs(solution_diff))
        if solution_diff < 0:
            worseningSolutionDifList.append(abs(solution_diff))
        current_solution_objective_value_delta_eval = new_objective_value
    percentile_sol_dif = sorted(worseningSolutionDifList)[math.floor(len(worseningSolutionDifList) * start_acceptance_rate)]
    min_sol_dif = min([sol for sol in solutionDifList if sol > 0])
    start = time.time()
    current_temp = abs(percentile_sol_dif/math.log(0.5))
    min_temp = abs(min_sol_dif/math.log(end_acceptance_rate))
    iterations_before_temperature_reduced = math.ceil(
        total_iterations / (math.log(min_temp / current_temp, math.e) / math.log(cooling_rate, math.e)))
    success_iterations_before_temperature_reduced = math.ceil(iterations_before_temperature_reduced * cutoff_ratio)
    if output:
        print(f"Chosen Start Temperature: {current_temp}")
        print(f"Chosen End Temperature: {min_temp}")
        print(f"Total iterations before temp reduced: {iterations_before_temperature_reduced} total success operation required: {success_iterations_before_temperature_reduced}")
    record = list()
    best_known_solution_iter = 0
    last_change = 0
    for i in range(total_iterations):
        if output and i % 1000 == 0:
            print(f"{i} iterations complete")
        if output and i % 10000 == 0:
            deltaEvaluator.print_objective_per_constraint_type()
        start_overhead = time.time()
        random_neighborhood = random.choices(neighborhoods, weights=probabilities, k=1)[0]
        overhead_time += time.time() - start_overhead
        start_move = time.time()
        restore_params, extra_info = random_neighborhood(instance, current_solution, searchSpace=None, event_role_helper_dict=eventRoleHelperDict)
        move_time[random_neighborhood.__name__] += time.time() - start_move
        start_eval = time.time()
        if restore_params is not None:
            if random_neighborhood == SA_neighborhoods.swap_resource:
                deltaEvaluator.assign_new_resource_to_event(restore_params[0], extra_info[0], extra_info[1])
                deltaEvaluator.assign_new_resource_to_event(restore_params[1], extra_info[1], extra_info[0])
            elif random_neighborhood == SA_neighborhoods.swap_resource_for_all_subevents:
                for j in range(len(extra_info[0])):
                    deltaEvaluator.assign_new_resource_to_event(extra_info[0][j], extra_info[2], extra_info[3])
                for j in range(len(extra_info[1])):
                    deltaEvaluator.assign_new_resource_to_event(extra_info[1][j], extra_info[3], extra_info[2])
            elif random_neighborhood == SA_neighborhoods.change_resource_for_all_subevents:
                for j in range(len(extra_info[0])):
                    deltaEvaluator.assign_new_resource_to_event(extra_info[0][j], extra_info[1][j], extra_info[2][j])
            elif random_neighborhood == SA_neighborhoods.change_resource:
                deltaEvaluator.assign_new_resource_to_event(restore_params[0], extra_info[0], extra_info[1])
            elif random_neighborhood == SA_neighborhoods.swap_times:
                deltaEvaluator.assign_new_time_to_event(restore_params[0], extra_info[0][0], extra_info[0][1], extra_info[2])
                deltaEvaluator.assign_new_time_to_event(restore_params[1], extra_info[1][0], extra_info[1][1], extra_info[2])
            elif random_neighborhood == SA_neighborhoods.block_swap_times:
                deltaEvaluator.assign_new_time_to_event(restore_params[0], extra_info[1][0], extra_info[1][1], extra_info[2])
                deltaEvaluator.assign_new_time_to_event(restore_params[1], extra_info[0][0], extra_info[0][1], extra_info[2])
            elif random_neighborhood == SA_neighborhoods.move_event:
                deltaEvaluator.assign_new_time_to_event(restore_params[0], extra_info[0], extra_info[1], set())
            elif random_neighborhood == SA_neighborhoods.move_linked_events:
                for eventIndex in range(len(restore_params[0])):
                    deltaEvaluator.assign_new_time_to_event(restore_params[0][eventIndex], extra_info[0][eventIndex], extra_info[1][eventIndex], set())
            elif random_neighborhood == SA_neighborhoods.combine_subevents:
                deltaEvaluator.delete_event(extra_info[4], extra_info[2], extra_info[0])
                deltaEvaluator.delete_event(extra_info[5], extra_info[3], extra_info[1])
                deltaEvaluator.add_event(restore_params[0], extra_info[6], extra_info[1])
            elif random_neighborhood == SA_neighborhoods.split_subevent:
                deltaEvaluator.delete_event(restore_params[2], extra_info[4], extra_info[0])
                deltaEvaluator.add_event(restore_params[0], extra_info[2], extra_info[0])
                deltaEvaluator.add_event(restore_params[1], extra_info[3], extra_info[1])
        new_objective_value = deltaEvaluator.get_current_objective_value()
        eval_time += time.time() - start_eval
        start_overhead = time.time()
        solution_diff = current_solution_objective_value - new_objective_value
        if solution_diff >= 0 or math.exp(solution_diff/current_temp) > random.random():
            if restore_params is not None:
                if i - last_change > 5000 and i % 100 == 0:
                    pass
                record.append((i, random_neighborhood, restore_params, extra_info, new_objective_value))
            if abs(solution_diff) >= 0.00001:
                last_change = i
                if output:
                    print(f"Iteration {i}: Current temp: {current_temp}, Accepted (Old: {current_solution_objective_value}, New: {new_objective_value}), Neighborhood: {random_neighborhood.__name__}")
                current_solution_objective_value = new_objective_value
                accepted_counter += 1
                overhead_time += time.time() - start_overhead
        else:
            if restore_params is not None:
                overhead_time += time.time() - start_overhead
                start_move = time.time()
                if random_neighborhood == SA_neighborhoods.combine_subevents:
                    random_neighborhood = SA_neighborhoods.split_subevent
                    restore_params, extra_info = random_neighborhood(instance, current_solution, restore_params[0], restore_params[1], restore_params[2], restore_params[3], restore_params[4], event_role_helper_dict=eventRoleHelperDict)
                elif random_neighborhood == SA_neighborhoods.split_subevent:
                    random_neighborhood = SA_neighborhoods.combine_subevents
                    restore_params, extra_info = random_neighborhood(instance, current_solution, restore_params[0], restore_params[1], restore_params[2][1], event_role_helper_dict=eventRoleHelperDict)
                elif len(restore_params) == 2:
                    restore_params, extra_info = random_neighborhood(instance, current_solution, restore_params[0], restore_params[1], event_role_helper_dict=eventRoleHelperDict)
                elif len(restore_params) == 3:
                    restore_params, extra_info = random_neighborhood(instance, current_solution, restore_params[0], restore_params[1], restore_params[2], event_role_helper_dict=eventRoleHelperDict)
                elif len(restore_params) == 4:
                    restore_params, extra_info = random_neighborhood(instance, current_solution, restore_params[0], restore_params[1], restore_params[2], restore_params[3], event_role_helper_dict=eventRoleHelperDict)
                else:
                    if output:
                        print("Something went wrong")
                move_time[random_neighborhood.__name__] += time.time() - start_move
                start_eval = time.time()
                if random_neighborhood == SA_neighborhoods.swap_resource:
                    if extra_info is not None:
                        deltaEvaluator.assign_new_resource_to_event(restore_params[0], extra_info[0], extra_info[1])
                        deltaEvaluator.assign_new_resource_to_event(restore_params[1], extra_info[1], extra_info[0])
                elif random_neighborhood == SA_neighborhoods.swap_resource_for_all_subevents:
                    if extra_info is not None:
                        for j in range(len(extra_info[0])):
                            deltaEvaluator.assign_new_resource_to_event(extra_info[0][j], extra_info[2], extra_info[3])
                        for j in range(len(extra_info[1])):
                            deltaEvaluator.assign_new_resource_to_event(extra_info[1][j], extra_info[3], extra_info[2])
                elif random_neighborhood == SA_neighborhoods.change_resource_for_all_subevents:
                    for j in range(len(extra_info[0])):
                        deltaEvaluator.assign_new_resource_to_event(extra_info[0][j], extra_info[1][j],
                                                                    extra_info[2][j])
                elif random_neighborhood == SA_neighborhoods.change_resource:
                    deltaEvaluator.assign_new_resource_to_event(restore_params[0], extra_info[0], extra_info[1])
                elif random_neighborhood == SA_neighborhoods.swap_times:
                    deltaEvaluator.assign_new_time_to_event(restore_params[0], extra_info[0][0], extra_info[0][1], extra_info[2])
                    deltaEvaluator.assign_new_time_to_event(restore_params[1], extra_info[1][0], extra_info[1][1], extra_info[2])
                elif random_neighborhood == SA_neighborhoods.block_swap_times:
                    deltaEvaluator.assign_new_time_to_event(restore_params[0], extra_info[1][0], extra_info[1][1], extra_info[2])
                    deltaEvaluator.assign_new_time_to_event(restore_params[1], extra_info[0][0], extra_info[0][1], extra_info[2])
                elif random_neighborhood == SA_neighborhoods.move_event:
                    deltaEvaluator.assign_new_time_to_event(restore_params[0], extra_info[0], extra_info[1], set())
                elif random_neighborhood == SA_neighborhoods.move_linked_events:
                    for eventIndex in range(len(restore_params[0])):
                        deltaEvaluator.assign_new_time_to_event(restore_params[0][eventIndex],
                                                                extra_info[0][eventIndex], extra_info[1][eventIndex],
                                                                set())
                elif random_neighborhood == SA_neighborhoods.combine_subevents:
                    deltaEvaluator.delete_event(extra_info[4], extra_info[2], extra_info[0])
                    deltaEvaluator.delete_event(extra_info[5], extra_info[3], extra_info[1])
                    deltaEvaluator.add_event(restore_params[0], extra_info[6], extra_info[1])
                elif random_neighborhood == SA_neighborhoods.split_subevent:
                    deltaEvaluator.delete_event(restore_params[2], extra_info[4], extra_info[0])
                    deltaEvaluator.add_event(restore_params[0], extra_info[2], extra_info[0])
                    deltaEvaluator.add_event(restore_params[1], extra_info[3], extra_info[1])
                eval_time += time.time() - start_eval
        start_overhead = time.time()
        if new_objective_value < best_known_objective_value:
            best_known_solution_iter = i
            best_known_objective_value = new_objective_value
        if accepted_counter >= success_iterations_before_temperature_reduced or (i - last_temp_change) >= iterations_before_temperature_reduced:
            current_temp = current_temp * cooling_rate
            last_temp_change = i
            accepted_counter = 0
        overhead_time += time.time() - start_overhead
    if output:
        print("Delta Eval objective value:")
        deltaEvaluator.print_objective_per_constraint_type()
    if output:
        print("Current Solution Before reconstruct of best known:")
    start_overhead = time.time()
    if output:
        print(f"Total record length: {len(record)}")
        print("Start of record:")
    for move in record:
        if move[0] > best_known_solution_iter:
            break
        random_neighborhood = move[1]
        restore_params = fast_copy(move[2])
        extra_info = fast_copy(move[3])
        if random_neighborhood == SA_neighborhoods.swap_resource:
            random_neighborhood(instance, start_solution, restore_params[0], restore_params[1], restore_params[2], restore_params[3], event_role_helper_dict=helperDictStart)
        elif random_neighborhood == SA_neighborhoods.swap_resource_for_all_subevents:
            random_neighborhood(instance, start_solution, restore_params[0], restore_params[1], restore_params[2], restore_params[3], event_role_helper_dict=helperDictStart)
        elif random_neighborhood == SA_neighborhoods.change_resource_for_all_subevents:
            random_neighborhood(instance, start_solution, restore_params[0], restore_params[1], extra_info[2], event_role_helper_dict=helperDictStart)
        elif random_neighborhood == SA_neighborhoods.change_resource:
            random_neighborhood(instance, start_solution, restore_params[0], restore_params[1], extra_info[1], event_role_helper_dict=helperDictStart)
        elif random_neighborhood == SA_neighborhoods.swap_times:
            random_neighborhood(instance, start_solution, restore_params[0], restore_params[1], event_role_helper_dict=helperDictStart)
        elif random_neighborhood == SA_neighborhoods.block_swap_times:
            random_neighborhood(instance, start_solution, restore_params[1], restore_params[0], event_role_helper_dict=helperDictStart)
        elif random_neighborhood == SA_neighborhoods.move_event:
            random_neighborhood(instance, start_solution, restore_params[0], extra_info[2], event_role_helper_dict=helperDictStart)
        elif random_neighborhood == SA_neighborhoods.combine_subevents:
            random_neighborhood(instance, start_solution, extra_info[5], extra_info[4], restore_params[0][1], event_role_helper_dict=helperDictStart)
        elif random_neighborhood == SA_neighborhoods.split_subevent:
            random_neighborhood(instance, start_solution, restore_params[2], extra_info[7], extra_info[6], restore_params[1][1], restore_params[0][1], event_role_helper_dict=helperDictStart)

    overhead_time += time.time() - start_overhead
    best_known_solution = start_solution
    totalTime = time.time() - start

    if output:
        print("Delta after reconstruct:")
        deltaEvaluator.print_objective_per_constraint_type()

    if output:
        print("Current Solution after reconstruct of best known:")
    validator.get_objective_value(instance, current_solution, outputObjectiveValues=output, outputDetailedObjectiveValues=False)
    if output:
        print("Best known Solution:")
    best_known_solution['ObjectiveValue'] = validator.get_objective_value(instance, best_known_solution, outputObjectiveValues=True)
    print(f"SA produced solution with objective value: {best_known_solution['ObjectiveValue']} in {totalTime} seconds")
    if output:
        print(f"Best known objective value for instance {instance.Metadata[XHSTTFileConstants.FILE_NAME]}: {best_known_objective_value}")
        print(f"Total copy times: 1: {totalCopyTime1} 2: {totalCopyTime2} together {totalCopyTime1 + totalCopyTime2}")
        print(f"Total weight change time: Best known {totalWeightChangeTimeBestKnown} current {totalWeightChangeTimeCurrent}")
        print(f"Best known objective value: {best_known_objective_value}")
        print(f"Total time: {totalTime}")
        print(f"Time spend evaluating: {eval_time}")
        print(f"Time spend on moves: {sum(move_time.values())} ({move_time})")
        print(f"Time spend on overhead: {overhead_time}")
    return best_known_solution


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