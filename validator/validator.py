import copy
import math
import sys
sys.path.append('XHSTTImporter')
from Instance import XHSTTInstance, Instance
sys.path.append('XHSTTImporter/Constants')
import XHSTTConstraintConstants
import XHSTTFileConstants
sys.path.append('ILP_solver')
import ILPConstants
import time as stopwatch
from DeltaSolution import DeltaSolution


class DeltaEvaluator:

    def __init__(self, instance: XHSTTInstance, solutionData: dict, ALNS_version=False, usedConstraintTypes=None, hardConstraintsOnly=False):
        self.instance = instance
        self.solution = solutionData
        self.ALNS_version = ALNS_version
        if usedConstraintTypes is None:
            self.usedConstraintTypes = {XHSTTConstraintConstants.AVOID_CLASHES_CONSTRAINT, XHSTTConstraintConstants.AVOID_UNAVAILABLE_TIMES_CONSTRAINT,
                                      XHSTTConstraintConstants.LIMIT_IDLE_TIMES_CONSTRAINT, XHSTTConstraintConstants.CLUSTER_BUSY_TIMES_CONSTRAINT,
                                      XHSTTConstraintConstants.LIMIT_BUSY_TIMES_CONSTRAINT, XHSTTConstraintConstants.LIMIT_WORKLOAD_CONSTRAINT,
                                      XHSTTConstraintConstants.STUDENT_CHOICE_CONSTRAINT, XHSTTConstraintConstants.ORDER_EVENTS_CONSTRAINT,
                                      XHSTTConstraintConstants.ASSIGN_RESOURCE_CONSTRAINT, XHSTTConstraintConstants.ASSIGN_TIME_CONSTRAINT,
                                      XHSTTConstraintConstants.SPLIT_EVENTS_CONSTRAINT, XHSTTConstraintConstants.PREFER_RESOURCES_CONSTRAINT,
                                      XHSTTConstraintConstants.DISTRIBUTE_SPLIT_EVENTS_CONSTRAINT, XHSTTConstraintConstants.PREFER_TIMES_CONSTRAINT,
                                      XHSTTConstraintConstants.SPREAD_EVENTS_CONSTRAINT, XHSTTConstraintConstants.AVOID_SPLIT_ASSIGNMENTS_CONSTRAINT,
                                      XHSTTConstraintConstants.LINK_EVENTS_CONSTRAINT, XHSTTConstraintConstants.BALANCE_CLASS_SIZE_CONSTRAINT}
        else:
            self.usedConstraintTypes = usedConstraintTypes

        self.useConstraintsAsSoftConstraintsForPreviousStages = True

        self.hardConstraintsOnly = hardConstraintsOnly
        if self.ALNS_version:
            self.reset_delta_solution()
        self.constraints_to_update = list()
        self.affectedTimes = set()
        self.affectedEvents = set()
        self.affectedEventGroups = set()
        self.eventToSolutionEventsDict = _create_event_to_solution_events_dict(self.instance, self.solution)
        self.resourceToSolutionEventsByTimeDict = _create_resource_to_solution_events_by_time_dict(self.instance, self.solution)
        self.resourceToSolutionEventsDict = _create_resource_to_solution_events_dict(self.solution)
        self.objectiveValue = get_objective_value(instance, self.solution)
        self.resoureToConstraintDict = self.create_resource_to_constraint_dict(instance)
        self.eventToConstraintDict = self.create_event_to_constraint_dict(instance)
        self.eventGroupToConstraintDict = self.create_event_group_to_constraint_dict(instance)
        self.eventToEventGroup = self.create_event_to_event_group_dict(instance)
        self.resourcesByType = self.get_resources_by_type()
        self.time_dict = dict()
        self.DEBUG_OUTPUT = False

    def update_delta_solution_after_neighborhood_deletions(self):
        unique_list_of_constraints_to_update = list({d[1][XHSTTConstraintConstants.ID]: d for d in self.constraints_to_update}.values())

        self.deltaSolution.setRelevantConstraints(unique_list_of_constraints_to_update)
        self.deltaSolution.addRelevantTimesAndTimeGroupsBasedOnTimeSet(self.affectedTimes)
    def set_delta_solution(self, solution=None):
        if solution is None:
            self.deltaSolution.solution = self.solution
        else:
            self.solution = solution
            self.deltaSolution.solution = solution
            self.recalc_dicts()

    def recalc_dicts(self):
        self.eventToSolutionEventsDict = _create_event_to_solution_events_dict(self.instance, self.solution)
        # self.originalEventToSolutionEventsDict = copy.deepcopy(self.eventToSolutionEventsDict)
        self.resourceToSolutionEventsByTimeDict = _create_resource_to_solution_events_by_time_dict(self.instance,
                                                                                                   self.solution)
        self.resourceToSolutionEventsDict = _create_resource_to_solution_events_dict(self.solution)
    def reset_delta_solution(self):
        self.deltaSolution = DeltaSolution(self.instance)
        self.set_delta_solution(self.solution)
    def get_event_to_solution_events_dict(self):
        return self.eventToSolutionEventsDict
    def get_resource_to_solution_events_by_time_dict(self):
        return self.resourceToSolutionEventsByTimeDict

    def get_resource_to_solution_events_dict(self):
        return self.resourceToSolutionEventsDict

    def get_current_solution(self):
        return self.solution
    def get_current_objective_value(self) -> float:
        return round(self.objectiveValue, 5)

    def print_objective_per_constraint_type(self):
        total = 0
        for constraint_type in self.instance.Constraints.keys():
            sumOfObjective = 0
            for constraint in self.instance.Constraints[constraint_type]:
                sumOfObjective += constraint[XHSTTConstraintConstants.OBJECTIVE_VALUE]
            print(f"{constraint_type}: {sumOfObjective}")
            total += sumOfObjective
        print(f"Total: {total}")
        print(f"Times for each constraint eval: {self.time_dict}")
        print(f"Total Time for constraint eval: {sum(list(self.time_dict.values()))}")

    def get_resources_by_type(self):
        resourcesByType = dict()
        for resourceID, resource in self.instance.Resources.IndividualResources.items():
            resourcesByType.setdefault(resource.Type, set()).add(resourceID)
        return resourcesByType
    def create_resource_to_constraint_dict(self, instance: XHSTTInstance) -> dict:
        resource_to_constraint_dict = dict()
        for resource in instance.Resources.IndividualResources.keys():
            resource_to_constraint_dict[resource] = list()
        for constraintType in [XHSTTConstraintConstants.AVOID_CLASHES_CONSTRAINT, XHSTTConstraintConstants.AVOID_UNAVAILABLE_TIMES_CONSTRAINT,
                                  XHSTTConstraintConstants.LIMIT_IDLE_TIMES_CONSTRAINT, XHSTTConstraintConstants.CLUSTER_BUSY_TIMES_CONSTRAINT,
                                  XHSTTConstraintConstants.LIMIT_BUSY_TIMES_CONSTRAINT, XHSTTConstraintConstants.LIMIT_WORKLOAD_CONSTRAINT,
                                  XHSTTConstraintConstants.STUDENT_CHOICE_CONSTRAINT]:
            if constraintType not in self.usedConstraintTypes and not self.useConstraintsAsSoftConstraintsForPreviousStages:
                continue
            if constraintType in instance.Constraints.keys():
                for constraint in instance.Constraints[constraintType]:
                    if not self.useConstraintsAsSoftConstraintsForPreviousStages and self.hardConstraintsOnly and not constraint[XHSTTConstraintConstants.REQUIRED]:
                        continue


                    if constraint[XHSTTConstraintConstants.REQUIRED] and constraintType not in self.usedConstraintTypes and self.useConstraintsAsSoftConstraintsForPreviousStages:
                        usedConstraint = copy.deepcopy(constraint)
                        usedConstraint[XHSTTConstraintConstants.REQUIRED] = False
                    else:
                        usedConstraint = constraint
                    for resource in usedConstraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCES]:
                        resource_to_constraint_dict[resource].append((constraintType, usedConstraint))
                    for resourceGroup in usedConstraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCE_GROUPS]:
                        for resourceType in instance.Resources.ResourceGroupsByType.keys():
                            if resourceGroup in instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups:
                                for resource in instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups[resourceGroup].Resources:
                                    if (constraintType, usedConstraint) not in resource_to_constraint_dict[resource]:
                                        resource_to_constraint_dict[resource].append((constraintType, usedConstraint))

        return resource_to_constraint_dict

    def create_event_to_constraint_dict(self, instance: XHSTTInstance) -> dict:
        event_to_constraint_dict = dict()
        for event in instance.Events.IndividualEvents.keys():
            event_to_constraint_dict[event] = list()
        for constraintType in [XHSTTConstraintConstants.ASSIGN_RESOURCE_CONSTRAINT, XHSTTConstraintConstants.ASSIGN_TIME_CONSTRAINT,
                               XHSTTConstraintConstants.SPLIT_EVENTS_CONSTRAINT, XHSTTConstraintConstants.PREFER_RESOURCES_CONSTRAINT,
                                  XHSTTConstraintConstants.DISTRIBUTE_SPLIT_EVENTS_CONSTRAINT, XHSTTConstraintConstants.PREFER_TIMES_CONSTRAINT,
                               XHSTTConstraintConstants.ORDER_EVENTS_CONSTRAINT]:
            if constraintType not in self.usedConstraintTypes and not self.useConstraintsAsSoftConstraintsForPreviousStages:
                continue
            if constraintType in instance.Constraints.keys():
                for constraint in instance.Constraints[constraintType]:
                    if not self.useConstraintsAsSoftConstraintsForPreviousStages and self.hardConstraintsOnly and not constraint[XHSTTConstraintConstants.REQUIRED]:
                        continue

                    if constraint[XHSTTConstraintConstants.REQUIRED] and constraintType not in self.usedConstraintTypes and self.useConstraintsAsSoftConstraintsForPreviousStages:
                        usedConstraint = copy.deepcopy(constraint)
                        usedConstraint[XHSTTConstraintConstants.REQUIRED] = False
                    else:
                        usedConstraint = constraint
                    if XHSTTFileConstants.EVENTS in usedConstraint[XHSTTConstraintConstants.APPLIES_TO]:
                        for event in usedConstraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS]:
                            event_to_constraint_dict[event].append(
                                (constraintType, usedConstraint))
                    if XHSTTFileConstants.EVENT_GROUPS in usedConstraint[XHSTTConstraintConstants.APPLIES_TO]:
                        for eventGroup in usedConstraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
                            for event in instance.Events.EventGroups[eventGroup].Events:
                                if (constraintType, usedConstraint) not in event_to_constraint_dict[event]:
                                    event_to_constraint_dict[event].append(
                                        (constraintType, usedConstraint))
                    if XHSTTFileConstants.EVENT_PAIRS in usedConstraint[XHSTTConstraintConstants.APPLIES_TO]:
                        for eventPair in usedConstraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_PAIRS]:
                            event_to_constraint_dict[eventPair[XHSTTFileConstants.FIRST_EVENT]].append(
                                (constraintType, usedConstraint))
                            event_to_constraint_dict[eventPair[XHSTTFileConstants.SECOND_EVENT]].append(
                                (constraintType, usedConstraint))


        return event_to_constraint_dict

    def create_event_group_to_constraint_dict(self, instance: XHSTTInstance) -> dict:
        event_group_to_constraint_dict = dict()
        for event_group in instance.Events.EventGroups.keys():
            event_group_to_constraint_dict[event_group] = list()
        for constraintType in [XHSTTConstraintConstants.SPREAD_EVENTS_CONSTRAINT, XHSTTConstraintConstants.AVOID_SPLIT_ASSIGNMENTS_CONSTRAINT,
                                  XHSTTConstraintConstants.LINK_EVENTS_CONSTRAINT, XHSTTConstraintConstants.BALANCE_CLASS_SIZE_CONSTRAINT]:
            if constraintType not in self.usedConstraintTypes and not self.useConstraintsAsSoftConstraintsForPreviousStages:
                continue
            if constraintType in instance.Constraints.keys():
                for constraint in instance.Constraints[constraintType]:
                    if not self.useConstraintsAsSoftConstraintsForPreviousStages and self.hardConstraintsOnly and not constraint[XHSTTConstraintConstants.REQUIRED]:
                        continue

                    if constraint[XHSTTConstraintConstants.REQUIRED] and constraintType not in self.usedConstraintTypes and self.useConstraintsAsSoftConstraintsForPreviousStages:
                        usedConstraint = copy.deepcopy(constraint)
                        usedConstraint[XHSTTConstraintConstants.REQUIRED] = False
                    else:
                        usedConstraint = constraint
                    for event_group in usedConstraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
                        if event_group not in event_group_to_constraint_dict:
                            continue
                        event_group_to_constraint_dict[event_group].append(
                            (constraintType, usedConstraint))

        return event_group_to_constraint_dict

    def create_event_to_event_group_dict(self, instance) -> dict:
        event_to_to_event_group_dict = dict()
        for event in instance.Events.IndividualEvents.keys():
            event_to_to_event_group_dict[event] = instance.Events.IndividualEvents[event].EventGroups

        return event_to_to_event_group_dict

    def add_event(self, event, newTimes, newResources):
        self.affectedTimes.update(set(newTimes))
        self.affectedEvents.add(event[0])
        self.affectedEventGroups.update(set(self.eventToEventGroup[event[0]]))
        solutionEvent = self.solution[XHSTTFileConstants.EVENTS][event]
        self.eventToSolutionEventsDict[event[0]].append(solutionEvent)
        if self.DEBUG_OUTPUT:
            print(f"Adding {event} at {newTimes} with {newResources} {self.solution[XHSTTFileConstants.EVENTS][event]}")
        for resource in newResources:
            if resource == ILPConstants.DUMMY_RESOURCE:
                continue
            for time in newTimes:
                self.resourceToSolutionEventsByTimeDict.setdefault(resource, dict()).setdefault(time, list()).append(solutionEvent)
                if self.DEBUG_OUTPUT:
                    print(f"Add Resource to solution events by time for resource {resource} at time {time} with event {event}: {self.resourceToSolutionEventsByTimeDict[resource][time]}")
            self.resourceToSolutionEventsDict.setdefault(resource, list()).append(solutionEvent)
            if resource in self.resoureToConstraintDict:
                self.constraints_to_update += self.resoureToConstraintDict[resource]
        for event_group in self.eventToEventGroup[event[0]]:
            self.constraints_to_update += self.eventGroupToConstraintDict[event_group]
        self.constraints_to_update += self.eventToConstraintDict[event[0]]
        if not self.ALNS_version:
            self.reevaluate_constraints()


    def delete_event(self, event, oldTimes, oldResources, keepResourceAssignments=False):
        self.affectedTimes.update(set(oldTimes))
        self.affectedEvents.add(event[0])
        self.affectedEventGroups.update(set(self.eventToEventGroup[event[0]]))
        solutionEvent = [solEvent for solEvent in self.eventToSolutionEventsDict[event[0]] if solEvent[XHSTTFileConstants.ID] == event][0]
        self.eventToSolutionEventsDict[event[0]].remove(solutionEvent)
        if self.DEBUG_OUTPUT:
            print(f"Removing {event} at {oldTimes} with {oldResources} {solutionEvent}")
        for resource in oldResources:
            if resource == ILPConstants.DUMMY_RESOURCE:
                continue
            for time in oldTimes:
                try:
                    self.resourceToSolutionEventsByTimeDict.setdefault(resource, dict()).setdefault(time, list()).remove(
                        solutionEvent)
                except:
                    if self.DEBUG_OUTPUT:
                        print("solutionevent was already removed")
                if self.DEBUG_OUTPUT:
                    print(f"Del Resource to solution events by time for resource {resource} at time {time} with event {event}: {self.resourceToSolutionEventsByTimeDict[resource][time]}")
            try:
                self.resourceToSolutionEventsDict.setdefault(resource, list()).remove(solutionEvent)
            except:
                if self.DEBUG_OUTPUT:
                    print("solutionevent was already removed")
            if resource in self.resoureToConstraintDict:
                self.constraints_to_update += self.resoureToConstraintDict[resource]
        for event_group in self.eventToEventGroup[event[0]]:
            self.constraints_to_update += self.eventGroupToConstraintDict[event_group]
        self.constraints_to_update += self.eventToConstraintDict[event[0]]
        if not self.ALNS_version:
            self.reevaluate_constraints()
        else:
            addedRelevantResources = set()
            for eventResource in self.instance.Events.IndividualEvents[event[0]].EventResources.UnassignedResources:
                self.deltaSolution.relevantEventResources.add(eventResource)
                if eventResource.Role.startswith('max_requirement_') or eventResource.Role.startswith('min_requirement_'):
                    relevantConstraints = [constraint for constraint in
                                           self.instance.Constraints[XHSTTConstraintConstants.PREFER_RESOURCES_CONSTRAINT]
                                           if event[0] in constraint[XHSTTConstraintConstants.APPLIES_TO][
                                               XHSTTFileConstants.EVENTS] and constraint[
                                               XHSTTConstraintConstants.ROLE] == eventResource.Role]
                    if len(relevantConstraints) > 0:
                        relevantConstraint = relevantConstraints[0]
                        if not keepResourceAssignments:
                            addedRelevantResources.update(relevantConstraint[XHSTTFileConstants.RESOURCES])
                            self.deltaSolution.relevantResources.update(relevantConstraint[XHSTTFileConstants.RESOURCES])

                else:
                    if not keepResourceAssignments:
                        if eventResource.ResourceType in self.resourcesByType:
                            addedRelevantResources.update(self.resourcesByType[eventResource.ResourceType])
                            self.deltaSolution.relevantResources.update(self.resourcesByType[eventResource.ResourceType])
            for eventResource in self.instance.Events.IndividualEvents[event[0]].EventResources.AssignedResources:
                self.deltaSolution.relevantEventResources.add(eventResource)
                addedRelevantResources.add(eventResource.Reference)
                self.deltaSolution.relevantResources.add(eventResource.Reference)
            if keepResourceAssignments:
                for resource in oldResources:
                    if resource != ILPConstants.DUMMY_RESOURCE:
                        addedRelevantResources.add(resource)
                        self.deltaSolution.relevantResources.add(resource)
            for resource in addedRelevantResources:
                if resource in self.resoureToConstraintDict:
                    self.constraints_to_update += self.resoureToConstraintDict[resource]
            self.affectedTimes.update(self.instance.Times.IndividualTimes)
            self.deltaSolution.relevantEvents.add(event[0])
            self.deltaSolution.relevantEventGroups.update(self.eventToEventGroup[event[0]])

    def assign_new_time_to_event(self, event, oldTimes, newTimes, common_resources):
        start = stopwatch.time()
        self.affectedTimes.update(set(oldTimes).union(set(newTimes)))
        self.affectedEvents.add(event[0])
        self.affectedEventGroups.update(set(self.eventToEventGroup[event[0]]))
        if self.DEBUG_OUTPUT:
            print(f"Assign new times {newTimes} remove old times {oldTimes} (common resources: {common_resources}) for event {self.solution[XHSTTFileConstants.EVENTS][event]}")
        affectedResources = set()
        for role in self.solution[XHSTTFileConstants.EVENTS][event][XHSTTFileConstants.RESOURCES].keys():
            resource = self.solution[XHSTTFileConstants.EVENTS][event][XHSTTFileConstants.RESOURCES][role]
            if resource == ILPConstants.DUMMY_RESOURCE:
                continue
            affectedResources.add(resource)
            for time in oldTimes:
                self.resourceToSolutionEventsByTimeDict[resource][time].remove(self.solution[XHSTTFileConstants.EVENTS][event])
                if self.DEBUG_OUTPUT:
                    print(f"TimeAss1 Resource to solution events by time for resource {resource} at time {time} with event {event}: {self.resourceToSolutionEventsByTimeDict[resource][time]}")
            for time in newTimes:
                self.resourceToSolutionEventsByTimeDict[resource].setdefault(time, list()).append(self.solution[XHSTTFileConstants.EVENTS][event])
                if self.DEBUG_OUTPUT:
                    print(f"TimeAss2 Resource to solution events by time for resource {resource} at time {time} with event {event}: {self.resourceToSolutionEventsByTimeDict[resource][time]}")
            self.resourceToSolutionEventsDict.setdefault(resource, list())
            if len(oldTimes) == 0 and len(newTimes) > 0 and self.solution[XHSTTFileConstants.EVENTS][event] not in self.resourceToSolutionEventsDict[resource]:
                self.resourceToSolutionEventsDict[resource].append(self.solution[XHSTTFileConstants.EVENTS][event])
            if resource not in common_resources and resource in self.resoureToConstraintDict.keys():
                self.constraints_to_update += self.resoureToConstraintDict[resource]
        for event_group in self.eventToEventGroup[event[0]]:
            for constraint in self.eventGroupToConstraintDict[event_group]:
                if constraint[0] in [XHSTTConstraintConstants.LINK_EVENTS_CONSTRAINT,
                                     XHSTTConstraintConstants.SPREAD_EVENTS_CONSTRAINT]:
                    self.constraints_to_update.append(constraint)
        for constraint in self.eventToConstraintDict[event[0]]:
            if constraint[0] not in [XHSTTConstraintConstants.ASSIGN_RESOURCE_CONSTRAINT,
                                     XHSTTConstraintConstants.PREFER_RESOURCES_CONSTRAINT]:
                self.constraints_to_update.append(constraint)

        self.time_dict.setdefault("overhead", 0)
        self.time_dict["overhead"] += stopwatch.time() - start
        if not self.ALNS_version:
            self.reevaluate_constraints()
        else:
            self.deltaSolution.relevantResources.update(affectedResources)
            self.affectedTimes.update(self.instance.Times.IndividualTimes)
            self.deltaSolution.relevantEvents.add(event[0])
            self.deltaSolution.relevantEventGroups.update(self.eventToEventGroup[event[0]])

    def assign_new_resource_to_event(self, event, old_resource, new_resource, role=None):
        start = stopwatch.time()
        self.affectedEvents.add(event[0])
        self.affectedEventGroups.update(set(self.eventToEventGroup[event[0]]))
        event_start_time = self.solution[XHSTTFileConstants.EVENTS][event][XHSTTFileConstants.TIME]
        if event_start_time is None or event_start_time == "dummyTime":
            start_time_index = None
        else:
            start_time_index = list(self.instance.Times.IndividualTimes.keys()).index(event_start_time)
        event_length = event[1][0]
        if old_resource != ILPConstants.DUMMY_RESOURCE:
            try:
                self.resourceToSolutionEventsDict[old_resource].remove(self.solution[XHSTTFileConstants.EVENTS][event])
            except:
                if self.DEBUG_OUTPUT:
                    print(f"Resource {old_resource} was already removed")
        if new_resource != ILPConstants.DUMMY_RESOURCE:
            self.resourceToSolutionEventsDict.setdefault(new_resource, list()).append(self.solution[XHSTTFileConstants.EVENTS][event])
        if start_time_index is not None:
            addedAffectedTimes = set(list(self.instance.Times.IndividualTimes.keys())[start_time_index: start_time_index + event_length])
            self.affectedTimes.update(addedAffectedTimes)
            for time in addedAffectedTimes:
                if old_resource != ILPConstants.DUMMY_RESOURCE:
                    try:
                        self.resourceToSolutionEventsByTimeDict[old_resource][time].remove(
                            self.solution[XHSTTFileConstants.EVENTS][event])
                    except:
                        if self.DEBUG_OUTPUT:
                            print(f"Solutionevent was already removed from resource {old_resource}")
                    if self.DEBUG_OUTPUT:
                        print(f"ResAss1 Resource to solution events by time for resource {old_resource} at time {time} with event {event}: {self.resourceToSolutionEventsByTimeDict[old_resource][time]}")
                if new_resource != ILPConstants.DUMMY_RESOURCE:
                    self.resourceToSolutionEventsByTimeDict[new_resource].setdefault(time, list()).append(
                        self.solution[XHSTTFileConstants.EVENTS][event])
                    if self.DEBUG_OUTPUT:
                        print(f"ResAss2 Resource to solution events by time for resource {new_resource} at time {time} with event {event}: {self.resourceToSolutionEventsByTimeDict[new_resource][time]}")
        else:
            addedAffectedTimes = set()

        if self.DEBUG_OUTPUT:
            print(f"Assign new Resources {new_resource} remove old resources {old_resource} at {addedAffectedTimes} for {self.solution[XHSTTFileConstants.EVENTS][event]}")

        if old_resource != ILPConstants.DUMMY_RESOURCE:
            self.constraints_to_update += self.resoureToConstraintDict[old_resource]
        if new_resource != ILPConstants.DUMMY_RESOURCE:
            self.constraints_to_update += self.resoureToConstraintDict[new_resource]

        for event_group in self.eventToEventGroup[event[0]]:
            for constraint in self.eventGroupToConstraintDict[event_group]:
                if constraint[0] in [XHSTTConstraintConstants.BALANCE_CLASS_SIZE_CONSTRAINT,
                                     XHSTTConstraintConstants.AVOID_SPLIT_ASSIGNMENTS_CONSTRAINT]:
                    self.constraints_to_update.append(constraint)
        for constraint in self.eventToConstraintDict[event[0]]:
            if constraint[0] in [XHSTTConstraintConstants.ASSIGN_RESOURCE_CONSTRAINT,
                                     XHSTTConstraintConstants.PREFER_RESOURCES_CONSTRAINT]:
                self.constraints_to_update.append(constraint)
        self.time_dict.setdefault("overhead", 0)
        self.time_dict["overhead"] += stopwatch.time() - start
        if not self.ALNS_version:
            self.reevaluate_constraints()
        else:
            addedRelevantResources = set()
            for eventResource in self.instance.Events.IndividualEvents[event[0]].EventResources.UnassignedResources:
                if eventResource.Role == role:
                    self.deltaSolution.relevantEventResources.add(eventResource)
                    if eventResource.Role.startswith('max_requirement_') or eventResource.Role.startswith(
                            'min_requirement_'):
                        relevantConstraints = [constraint for constraint in
                                               self.instance.Constraints[
                                                   XHSTTConstraintConstants.PREFER_RESOURCES_CONSTRAINT]
                                               if event[0] in constraint[XHSTTConstraintConstants.APPLIES_TO][
                                                   XHSTTFileConstants.EVENTS] and constraint[
                                                   XHSTTConstraintConstants.ROLE] == eventResource.Role]
                        if len(relevantConstraints) > 0:
                            relevantConstraint = relevantConstraints[0]
                            addedRelevantResources.update(relevantConstraint[XHSTTFileConstants.RESOURCES])
                            self.deltaSolution.relevantResources.update(
                                relevantConstraint[XHSTTFileConstants.RESOURCES])

                    else:
                        if eventResource.ResourceType in self.resourcesByType:
                            addedRelevantResources.update(self.resourcesByType[eventResource.ResourceType])
                            self.deltaSolution.relevantResources.update(self.resourcesByType[eventResource.ResourceType])
            for eventResource in self.instance.Events.IndividualEvents[event[0]].EventResources.AssignedResources:
                if eventResource.Role == role:
                    self.deltaSolution.relevantEventResources.add(eventResource)
                    addedRelevantResources.add(eventResource.Reference)
                    self.deltaSolution.relevantResources.add(eventResource.Reference)
            for resource in addedRelevantResources:
                self.constraints_to_update += self.resoureToConstraintDict[resource]
            self.deltaSolution.relevantEvents.add(event[0])
            self.deltaSolution.relevantEventGroups.update(self.eventToEventGroup[event[0]])
    def reevaluate_constraints(self):
        objective_value_change = 0
        for constraint in self.constraints_to_update:
            start = stopwatch.time()
            objective_value_change -= constraint[1][XHSTTConstraintConstants.OBJECTIVE_VALUE]
            if constraint[0] == XHSTTConstraintConstants.ASSIGN_RESOURCE_CONSTRAINT:
                _get_objective_value_assign_resources_constraints(self.instance, self.eventToSolutionEventsDict, False, constraints=[constraint[1]], excludeDeviationInfo=True)
            elif constraint[0] == XHSTTConstraintConstants.ASSIGN_TIME_CONSTRAINT:
                _get_objective_value_assign_times_constraints(self.instance, self.eventToSolutionEventsDict, False, constraints=[constraint[1]], excludeDeviationInfo=True)
            elif constraint[0] == XHSTTConstraintConstants.SPLIT_EVENTS_CONSTRAINT:
                _get_objective_value_split_events_constraints(self.instance, self.eventToSolutionEventsDict, False, constraints=[constraint[1]], excludeDeviationInfo=True)
            elif constraint[0] == XHSTTConstraintConstants.DISTRIBUTE_SPLIT_EVENTS_CONSTRAINT:
                _get_objective_value_distribute_split_events_constraints(self.instance, self.eventToSolutionEventsDict, False, constraints=[constraint[1]], excludeDeviationInfo=True)
            elif constraint[0] == XHSTTConstraintConstants.PREFER_TIMES_CONSTRAINT:
                _get_objective_value_prefer_times_constraints(self.instance, self.eventToSolutionEventsDict, False, constraints=[constraint[1]], excludeDeviationInfo=True)
            elif constraint[0] == XHSTTConstraintConstants.PREFER_RESOURCES_CONSTRAINT:
                _get_objective_value_prefer_resources_constraints(self.instance, self.eventToSolutionEventsDict, False, constraints=[constraint[1]], excludeDeviationInfo=True)
            elif constraint[0] == XHSTTConstraintConstants.AVOID_SPLIT_ASSIGNMENTS_CONSTRAINT:
                _get_objective_value_avoid_split_assignments_constraints(self.instance, self.eventToSolutionEventsDict, False, constraints=[constraint[1]], excludeDeviationInfo=True)
            elif constraint[0] == XHSTTConstraintConstants.SPREAD_EVENTS_CONSTRAINT:
                _get_objective_value_spread_events_constraints(self.instance, self.eventToSolutionEventsDict, False, constraints=[constraint[1]], excludeDeviationInfo=True)
            elif constraint[0] == XHSTTConstraintConstants.LINK_EVENTS_CONSTRAINT:
                _get_objective_value_link_events_constraints(self.instance, self.eventToSolutionEventsDict, False, constraints=[constraint[1]], excludeDeviationInfo=True)
            elif constraint[0] == XHSTTConstraintConstants.ORDER_EVENTS_CONSTRAINT:
                _get_objective_value_order_events_constraints(self.instance, self.eventToSolutionEventsDict, False, constraints=[constraint[1]], excludeDeviationInfo=True)
            elif constraint[0] == XHSTTConstraintConstants.AVOID_CLASHES_CONSTRAINT:
                _get_objective_value_avoid_clashes_constraints(self.instance, self.resourceToSolutionEventsByTimeDict, False, constraints=[constraint[1]], excludeDeviationInfo=True, outputObjective=True, affectedTimes=self.affectedTimes)
            elif constraint[0] == XHSTTConstraintConstants.AVOID_UNAVAILABLE_TIMES_CONSTRAINT:
                _get_objective_value_avoid_unavailable_times_constraints(self.instance, self.resourceToSolutionEventsByTimeDict, False, constraints=[constraint[1]], excludeDeviationInfo=True, affectedTimes=self.affectedTimes)
            elif constraint[0] == XHSTTConstraintConstants.LIMIT_IDLE_TIMES_CONSTRAINT:
                _get_objective_value_limit_idle_times_constraints(self.instance, self.resourceToSolutionEventsByTimeDict, self.resourceToSolutionEventsDict, False, constraints=[constraint[1]], excludeDeviationInfo=True, affectedTimes=self.affectedTimes)
            elif constraint[0] == XHSTTConstraintConstants.CLUSTER_BUSY_TIMES_CONSTRAINT:
                _get_objective_value_cluster_busy_times_constraints(self.instance, self.resourceToSolutionEventsByTimeDict, self.resourceToSolutionEventsDict, False, constraints=[constraint[1]], excludeDeviationInfo=True)
            elif constraint[0] == XHSTTConstraintConstants.LIMIT_BUSY_TIMES_CONSTRAINT:
                _get_objective_value_limit_busy_times_constraints(self.instance, self.resourceToSolutionEventsByTimeDict, self.resourceToSolutionEventsDict, False, constraints=[constraint[1]], excludeDeviationInfo=True, affectedTimes=self.affectedTimes)
            elif constraint[0] == XHSTTConstraintConstants.LIMIT_WORKLOAD_CONSTRAINT:
                _get_objective_value_limit_workload_constraints(self.instance, self.resourceToSolutionEventsDict, False, constraints=[constraint[1]], excludeDeviationInfo=True)
            elif constraint[0] == XHSTTConstraintConstants.BALANCE_CLASS_SIZE_CONSTRAINT:
                _get_objective_value_balance_class_size_constraints(self.instance, self.eventToSolutionEventsDict, False, constraints=[constraint[1]], excludeDeviationInfo=True, affectedEventGroups=self.affectedEventGroups)
            elif constraint[0] == XHSTTConstraintConstants.STUDENT_CHOICE_CONSTRAINT:
                _get_objective_value_student_choice_constraints(self.instance, self.resourceToSolutionEventsDict, False, constraints=[constraint[1]], excludeDeviationInfo=True, affectedEventGroups=self.affectedEventGroups)
            objective_value_change += constraint[1][XHSTTConstraintConstants.OBJECTIVE_VALUE]
            end = stopwatch.time()
            self.time_dict.setdefault(constraint[0], 0)
            self.time_dict[constraint[0]] += end - start
        self.constraints_to_update = list()
        self.affectedTimes = set()
        self.affectedEventGroups = set()
        self.objectiveValue += objective_value_change


def get_objective_value(instance: XHSTTInstance, solutionData: dict, outputObjectiveValues: bool = False, useWeightCopy: bool = False, outputDetailedObjectiveValues: bool = False, evaluateHardAndSoftSeparatly = False, hardOnly = False, relevantConstraintTypes=None) -> float:
    eventToSolutionEventsDict = _create_event_to_solution_events_dict(instance, solutionData)
    resourceToSolutionEventsByTimeDict = _create_resource_to_solution_events_by_time_dict(instance, solutionData)
    resourceToSolutionEventsDict = _create_resource_to_solution_events_dict(solutionData)
    if evaluateHardAndSoftSeparatly and hardOnly:
        raise Exception("These two arguments are not supposed to be used together (evaluateHardAndSoftSeparatly and hardOnly)")
    if evaluateHardAndSoftSeparatly or hardOnly:
        print(f"Inside evaluation: hardOnly: {hardOnly} Current Constraint Types: {relevantConstraintTypes}")
        copy_instance_hard_constraints_only = copy.deepcopy(instance)
        copy_instance_soft_constraints_only = copy.deepcopy(instance)
        hardConstraintsById = dict()
        softConstraintsById = dict()
        for constraintType in copy_instance_hard_constraints_only.Constraints:
            if evaluateHardAndSoftSeparatly or relevantConstraintTypes is None or constraintType in relevantConstraintTypes:
                newConstraintsHard = [constraint for constraint in copy_instance_hard_constraints_only.Constraints[constraintType] if constraint[XHSTTConstraintConstants.REQUIRED]]
                hardConstraintsById = hardConstraintsById | {constraint[XHSTTFileConstants.ID]: constraint for constraint in newConstraintsHard}
                copy_instance_hard_constraints_only.Constraints[constraintType] = newConstraintsHard
            else:
                copy_instance_hard_constraints_only.Constraints[constraintType] = list()
            if evaluateHardAndSoftSeparatly or (not hardOnly and (relevantConstraintTypes is None or constraintType in relevantConstraintTypes)):
                newConstraintsSoft = [constraint for constraint in
                                      copy_instance_soft_constraints_only.Constraints[constraintType] if
                                      not constraint[XHSTTConstraintConstants.REQUIRED]]
                softConstraintsById = softConstraintsById | {constraint[XHSTTFileConstants.ID]: constraint for constraint in
                                       newConstraintsSoft}
                copy_instance_soft_constraints_only.Constraints[constraintType] = newConstraintsSoft
            else:
                copy_instance_soft_constraints_only.Constraints[constraintType] = list()

            for constraintID in hardConstraintsById.keys():
                if constraintID in softConstraintsById:
                    print(f"Duplicate constraintID {constraintID}")
        constraintsById = hardConstraintsById | softConstraintsById
        hardObjective_assign_resources_constraints = _get_objective_value_assign_resources_constraints(copy_instance_hard_constraints_only, eventToSolutionEventsDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
        hardObjective_assign_times_constraints = _get_objective_value_assign_times_constraints(copy_instance_hard_constraints_only, eventToSolutionEventsDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
        hardObjective_split_events_constraints = _get_objective_value_split_events_constraints(copy_instance_hard_constraints_only, eventToSolutionEventsDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
        hardObjective_distribute_split_events_constraints = _get_objective_value_distribute_split_events_constraints(copy_instance_hard_constraints_only, eventToSolutionEventsDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
        hardObjective_prefer_times_constraints = _get_objective_value_prefer_times_constraints(copy_instance_hard_constraints_only, eventToSolutionEventsDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
        hardObjective_prefer_resources_constraints = _get_objective_value_prefer_resources_constraints(copy_instance_hard_constraints_only, eventToSolutionEventsDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
        hardObjective_avoid_split_assignments_constraints = _get_objective_value_avoid_split_assignments_constraints(copy_instance_hard_constraints_only, eventToSolutionEventsDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
        hardObjective_spread_events_constraints = _get_objective_value_spread_events_constraints(copy_instance_hard_constraints_only, eventToSolutionEventsDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
        hardObjective_link_events_constraints = _get_objective_value_link_events_constraints(copy_instance_hard_constraints_only,eventToSolutionEventsDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
        hardObjective_order_events_constraints = _get_objective_value_order_events_constraints(
            copy_instance_hard_constraints_only, eventToSolutionEventsDict, useWeightCopy,
            outputObjective=outputDetailedObjectiveValues)
        hardObjective_avoid_clashes_constraints = _get_objective_value_avoid_clashes_constraints(copy_instance_hard_constraints_only, resourceToSolutionEventsByTimeDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
        hardObjective_avoid_unavailable_times_constraints = _get_objective_value_avoid_unavailable_times_constraints(copy_instance_hard_constraints_only, resourceToSolutionEventsByTimeDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
        hardObjective_limit_idle_times_constraints = _get_objective_value_limit_idle_times_constraints(copy_instance_hard_constraints_only, resourceToSolutionEventsByTimeDict, resourceToSolutionEventsDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
        hardObjective_cluster_busy_times_constraints = _get_objective_value_cluster_busy_times_constraints(copy_instance_hard_constraints_only, resourceToSolutionEventsByTimeDict, resourceToSolutionEventsDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
        hardObjective_limit_busy_times_constraints = _get_objective_value_limit_busy_times_constraints(copy_instance_hard_constraints_only, resourceToSolutionEventsByTimeDict, resourceToSolutionEventsDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
        hardObjective_limit_workload_constraints = _get_objective_value_limit_workload_constraints(copy_instance_hard_constraints_only,resourceToSolutionEventsDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
        hardObjective_balance_class_size_constraints = _get_objective_value_balance_class_size_constraints(copy_instance_hard_constraints_only, eventToSolutionEventsDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
        hardObjective_student_choice_constraints = _get_objective_value_student_choice_constraints(copy_instance_hard_constraints_only,resourceToSolutionEventsDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)

        hardObjective = hardObjective_assign_resources_constraints + hardObjective_assign_times_constraints + hardObjective_split_events_constraints +\
        hardObjective_distribute_split_events_constraints + hardObjective_prefer_times_constraints + hardObjective_prefer_resources_constraints +\
        hardObjective_avoid_split_assignments_constraints + hardObjective_spread_events_constraints + hardObjective_link_events_constraints +\
        hardObjective_avoid_clashes_constraints + hardObjective_avoid_unavailable_times_constraints + hardObjective_limit_idle_times_constraints +\
        hardObjective_cluster_busy_times_constraints + hardObjective_limit_busy_times_constraints + hardObjective_limit_workload_constraints +\
        hardObjective_balance_class_size_constraints + hardObjective_student_choice_constraints + hardObjective_order_events_constraints

        softObjective_assign_resources_constraints = _get_objective_value_assign_resources_constraints(copy_instance_soft_constraints_only, eventToSolutionEventsDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
        softObjective_assign_times_constraints = _get_objective_value_assign_times_constraints(copy_instance_soft_constraints_only, eventToSolutionEventsDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
        softObjective_split_events_constraints = _get_objective_value_split_events_constraints(copy_instance_soft_constraints_only, eventToSolutionEventsDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
        softObjective_distribute_split_events_constraints = _get_objective_value_distribute_split_events_constraints(copy_instance_soft_constraints_only, eventToSolutionEventsDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
        softObjective_prefer_times_constraints = _get_objective_value_prefer_times_constraints(copy_instance_soft_constraints_only, eventToSolutionEventsDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
        softObjective_prefer_resources_constraints = _get_objective_value_prefer_resources_constraints(copy_instance_soft_constraints_only, eventToSolutionEventsDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
        softObjective_avoid_split_assignments_constraints = _get_objective_value_avoid_split_assignments_constraints(copy_instance_soft_constraints_only, eventToSolutionEventsDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
        softObjective_spread_events_constraints = _get_objective_value_spread_events_constraints(copy_instance_soft_constraints_only, eventToSolutionEventsDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
        softObjective_link_events_constraints = _get_objective_value_link_events_constraints(copy_instance_soft_constraints_only,eventToSolutionEventsDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
        softObjective_order_events_constraints = _get_objective_value_order_events_constraints(copy_instance_soft_constraints_only, eventToSolutionEventsDict, useWeightCopy,outputObjective=outputDetailedObjectiveValues)
        softObjective_avoid_clashes_constraints = _get_objective_value_avoid_clashes_constraints(copy_instance_soft_constraints_only, resourceToSolutionEventsByTimeDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
        softObjective_avoid_unavailable_times_constraints = _get_objective_value_avoid_unavailable_times_constraints(copy_instance_soft_constraints_only, resourceToSolutionEventsByTimeDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
        softObjective_limit_idle_times_constraints = _get_objective_value_limit_idle_times_constraints(copy_instance_soft_constraints_only, resourceToSolutionEventsByTimeDict, resourceToSolutionEventsDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
        softObjective_cluster_busy_times_constraints = _get_objective_value_cluster_busy_times_constraints(copy_instance_soft_constraints_only, resourceToSolutionEventsByTimeDict, resourceToSolutionEventsDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
        softObjective_limit_busy_times_constraints = _get_objective_value_limit_busy_times_constraints(copy_instance_soft_constraints_only, resourceToSolutionEventsByTimeDict, resourceToSolutionEventsDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
        softObjective_limit_workload_constraints = _get_objective_value_limit_workload_constraints(copy_instance_soft_constraints_only,resourceToSolutionEventsDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
        softObjective_balance_class_size_constraints = _get_objective_value_balance_class_size_constraints(copy_instance_soft_constraints_only, eventToSolutionEventsDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
        softObjective_student_choice_constraints = _get_objective_value_student_choice_constraints(copy_instance_soft_constraints_only,resourceToSolutionEventsDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)

        softObjective = softObjective_assign_resources_constraints + softObjective_assign_times_constraints + softObjective_split_events_constraints + \
                        softObjective_distribute_split_events_constraints + softObjective_prefer_times_constraints + softObjective_prefer_resources_constraints + \
                        softObjective_avoid_split_assignments_constraints + softObjective_spread_events_constraints + softObjective_link_events_constraints + \
                        softObjective_avoid_clashes_constraints + softObjective_avoid_unavailable_times_constraints + softObjective_limit_idle_times_constraints + \
                        softObjective_cluster_busy_times_constraints + softObjective_limit_busy_times_constraints + softObjective_limit_workload_constraints + \
                        softObjective_balance_class_size_constraints + softObjective_student_choice_constraints + softObjective_order_events_constraints

        if outputObjectiveValues and not evaluateHardAndSoftSeparatly:
            print(f"assign_resources_constraints: {hardObjective_assign_resources_constraints + softObjective_assign_resources_constraints}")
            print(f"assign_times_constraints: {hardObjective_assign_times_constraints + softObjective_assign_times_constraints}")
            print(f"split_events_constraints: {hardObjective_split_events_constraints + softObjective_split_events_constraints}")
            print(f"distribute_split_events_constraints: {hardObjective_distribute_split_events_constraints + softObjective_distribute_split_events_constraints}")
            print(f"prefer_times_constraints: {hardObjective_prefer_times_constraints + softObjective_prefer_times_constraints}")
            print(f"prefer_resources_constraints: {hardObjective_prefer_resources_constraints + softObjective_prefer_resources_constraints}")
            print(f"avoid_split_assignments_constraints: {hardObjective_avoid_split_assignments_constraints + softObjective_avoid_split_assignments_constraints}")
            print(f"spread_events_constraints: {hardObjective_spread_events_constraints + softObjective_spread_events_constraints}")
            print(f"link_events_constraints: {hardObjective_link_events_constraints + softObjective_link_events_constraints}")
            print(f"avoid_clashes_constraints: {hardObjective_avoid_clashes_constraints + softObjective_avoid_clashes_constraints}")
            print(f"avoid_unavailable_times_constraints: {hardObjective_avoid_unavailable_times_constraints + softObjective_avoid_unavailable_times_constraints}")
            print(f"limit_idle_times_constraints: {hardObjective_limit_idle_times_constraints + softObjective_limit_idle_times_constraints}")
            print(f"cluster_busy_times_constraints: {hardObjective_cluster_busy_times_constraints + softObjective_cluster_busy_times_constraints}")
            print(f"limit_busy_times_constraints: {hardObjective_limit_busy_times_constraints + softObjective_limit_busy_times_constraints}")
            print(f"limit_workload_constraints: {hardObjective_limit_workload_constraints + softObjective_limit_workload_constraints}")
            print(f"balance_class_size_constraints: {hardObjective_balance_class_size_constraints + softObjective_balance_class_size_constraints}")
            print(f"student_choice_constraints: {hardObjective_student_choice_constraints + softObjective_student_choice_constraints}")
            print(f"Total Objective: {hardObjective + softObjective}")



        if not evaluateHardAndSoftSeparatly:

            for constraintType in instance.Constraints.keys():
                for constraint in instance.Constraints[constraintType]:
                    if constraint[XHSTTFileConstants.ID] not in constraintsById:
                        constraint[XHSTTConstraintConstants.IS_FULFILLED] = True
                        constraint[XHSTTConstraintConstants.DEVIATION_EVENTS] = list()
                        constraint[XHSTTConstraintConstants.DEVIATION_AMOUNT] = 0
                    else:
                        referenceConstraint = constraintsById[constraint[XHSTTFileConstants.ID]]
                        constraint[XHSTTConstraintConstants.IS_FULFILLED] = referenceConstraint[XHSTTConstraintConstants.IS_FULFILLED]
                        constraint[XHSTTConstraintConstants.DEVIATION_EVENTS] = referenceConstraint[XHSTTConstraintConstants.DEVIATION_EVENTS]
                        constraint[XHSTTConstraintConstants.DEVIATION_AMOUNT] = referenceConstraint[XHSTTConstraintConstants.DEVIATION_AMOUNT]

            return hardObjective + softObjective

    if outputObjectiveValues:
        print("Evaluating without separation so constraints fulfill status updates naturally")
    objective_value_from_assign_resources_constraints = _get_objective_value_assign_resources_constraints(instance, eventToSolutionEventsDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
    objective_value_from_assign_times_constraints = _get_objective_value_assign_times_constraints(instance, eventToSolutionEventsDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
    objective_value_from_split_events_constraints = _get_objective_value_split_events_constraints(instance, eventToSolutionEventsDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
    objective_value_from_distribute_split_events_constraints = _get_objective_value_distribute_split_events_constraints(instance, eventToSolutionEventsDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
    objective_value_from_prefer_times_constraints = _get_objective_value_prefer_times_constraints(instance, eventToSolutionEventsDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
    objective_value_from_prefer_resources_constraints = _get_objective_value_prefer_resources_constraints(instance, eventToSolutionEventsDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
    objective_value_from_avoid_split_assignments_constraints = _get_objective_value_avoid_split_assignments_constraints(instance, eventToSolutionEventsDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
    objective_value_from_spread_events_constraints = _get_objective_value_spread_events_constraints(instance, eventToSolutionEventsDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
    objective_value_from_link_events_constraints = _get_objective_value_link_events_constraints(instance, eventToSolutionEventsDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
    objective_value_from_order_events_constraints = _get_objective_value_order_events_constraints(instance, eventToSolutionEventsDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
    objective_value_from_avoid_clashes_constraints = _get_objective_value_avoid_clashes_constraints(instance, resourceToSolutionEventsByTimeDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
    objective_value_from_avoid_unavailable_times_constraints = _get_objective_value_avoid_unavailable_times_constraints(instance, resourceToSolutionEventsByTimeDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
    objective_value_from_limit_idle_times_constraints = _get_objective_value_limit_idle_times_constraints(instance, resourceToSolutionEventsByTimeDict, resourceToSolutionEventsDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
    objective_value_from_cluster_busy_times_constraints = _get_objective_value_cluster_busy_times_constraints(instance, resourceToSolutionEventsByTimeDict, resourceToSolutionEventsDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
    objective_value_from_limit_busy_times_constraints = _get_objective_value_limit_busy_times_constraints(instance, resourceToSolutionEventsByTimeDict, resourceToSolutionEventsDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
    objective_value_from_limit_workload_constraints = _get_objective_value_limit_workload_constraints(instance, resourceToSolutionEventsDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)

    objective_value_from_balance_class_size_constraints = _get_objective_value_balance_class_size_constraints(instance, eventToSolutionEventsDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
    objective_value_from_student_choice_constraints = _get_objective_value_student_choice_constraints(instance, resourceToSolutionEventsDict, useWeightCopy, outputObjective=outputDetailedObjectiveValues)
    if outputObjectiveValues:
        print(f"assign_resources_constraints: {objective_value_from_assign_resources_constraints}")
        print(f"assign_times_constraints: {objective_value_from_assign_times_constraints}")
        print(f"split_events_constraints: {objective_value_from_split_events_constraints}")
        print(f"distribute_split_events_constraints: {objective_value_from_distribute_split_events_constraints}")
        print(f"prefer_times_constraints: {objective_value_from_prefer_times_constraints}")
        print(f"prefer_resources_constraints: {objective_value_from_prefer_resources_constraints}")
        print(f"avoid_split_assignments_constraints: {objective_value_from_avoid_split_assignments_constraints}")
        print(f"spread_events_constraints: {objective_value_from_spread_events_constraints}")
        print(f"link_events_constraints: {objective_value_from_link_events_constraints}")
        print(f"order_events_constraints: {objective_value_from_order_events_constraints}")
        print(f"avoid_clashes_constraints: {objective_value_from_avoid_clashes_constraints}")
        print(f"avoid_unavailable_times_constraints: {objective_value_from_avoid_unavailable_times_constraints}")
        print(f"limit_idle_times_constraints: {objective_value_from_limit_idle_times_constraints}")
        print(f"cluster_busy_times_constraints: {objective_value_from_cluster_busy_times_constraints}")
        print(f"limit_busy_times_constraints: {objective_value_from_limit_busy_times_constraints}")
        print(f"limit_workload_constraints: {objective_value_from_limit_workload_constraints}")
        print(f"balance_class_size_constraints: {objective_value_from_balance_class_size_constraints}")
        print(f"student_choice_constraints: {objective_value_from_student_choice_constraints}")
    objective_value = (objective_value_from_assign_resources_constraints + objective_value_from_assign_times_constraints +
                       objective_value_from_split_events_constraints + objective_value_from_distribute_split_events_constraints +
                       objective_value_from_prefer_times_constraints + objective_value_from_prefer_resources_constraints +
                       objective_value_from_avoid_split_assignments_constraints + objective_value_from_spread_events_constraints +
                       objective_value_from_link_events_constraints + objective_value_from_avoid_clashes_constraints +
                       objective_value_from_avoid_unavailable_times_constraints + objective_value_from_limit_idle_times_constraints +
                       objective_value_from_cluster_busy_times_constraints + objective_value_from_limit_busy_times_constraints +
                       objective_value_from_limit_workload_constraints + objective_value_from_balance_class_size_constraints +
                       objective_value_from_student_choice_constraints + objective_value_from_order_events_constraints)
    if outputObjectiveValues:
        if evaluateHardAndSoftSeparatly:
            print(f"Total Objective: {objective_value}, Hard/Soft: {(int(hardObjective), int(softObjective*100000))}")
        else:
            print(f"Total Objective: {objective_value}")
    if evaluateHardAndSoftSeparatly:
        return objective_value, (int(hardObjective), int(softObjective*100000))

    return objective_value

def _get_objective_value_partial_solution(instance: XHSTTInstance, partialSolutionData: dict, newlyScheduledEvent: (str, str), outputObjectiveValues: bool = False, evaluateTime=True, evaluateResources=True, existingDicts=None, restoreDictsAfterExecution=False):
    times = list()
    times.append(("", stopwatch.time()))
    newEventFixedResources = list()
    for role in partialSolutionData[newlyScheduledEvent[0]][newlyScheduledEvent[1]]["PossibleResources"].keys():
        if len(partialSolutionData[newlyScheduledEvent[0]][newlyScheduledEvent[1]]["PossibleResources"][role]) == 1:
            newEventFixedResources.append(
                partialSolutionData[newlyScheduledEvent[0]][newlyScheduledEvent[1]]["PossibleResources"][role][0])
    dictModifications = [list() for _ in range(3)]
    if existingDicts is not None:
        eventToSolutionEventsDict = _create_event_to_solution_events_dict_from_partial_solution(partialSolutionData, existingDict=existingDicts[0], newEvent=newlyScheduledEvent, modifications=dictModifications[0])
        resourceToSolutionEventsByTimeDict = _create_resource_to_solution_events_by_time_dict_from_partial_solution(
            instance, partialSolutionData, existingDict=existingDicts[1], newEvent=newlyScheduledEvent, modifications=dictModifications[1])
        resourceToSolutionEventsDict = _create_resource_to_solution_events_dict_from_partial_solution(
            partialSolutionData, existingDict=existingDicts[2], newEvent=newlyScheduledEvent, modifications=dictModifications[2])
    else:
        eventToSolutionEventsDict = _create_event_to_solution_events_dict_from_partial_solution(partialSolutionData, modifications=dictModifications[0])
        resourceToSolutionEventsByTimeDict = _create_resource_to_solution_events_by_time_dict_from_partial_solution(instance, partialSolutionData, modifications=dictModifications[1])
        resourceToSolutionEventsDict = _create_resource_to_solution_events_dict_from_partial_solution(partialSolutionData, modifications=dictModifications[2])
    createdPartialSolutionDicts = [eventToSolutionEventsDict, resourceToSolutionEventsByTimeDict, resourceToSolutionEventsDict]
    times.append(("dict_creation", stopwatch.time()))
    if evaluateTime:
        objective_value_from_prefer_times_constraints = _get_objective_value_prefer_times_constraints(instance,
                                                                                                      eventToSolutionEventsDict,
                                                                                                      False,
                                                                                                      focusEvent=newlyScheduledEvent)
    else:
        objective_value_from_prefer_times_constraints = 0.0
    times.append(("prefer_times_constraints", stopwatch.time()))
    if evaluateResources:
        objective_value_from_prefer_resources_constraints = _get_objective_value_prefer_resources_constraints(instance,
                                                                                                              eventToSolutionEventsDict,
                                                                                                              False,
                                                                                                              focusEvent=newlyScheduledEvent)
    else:
        objective_value_from_prefer_resources_constraints = 0.0
    times.append(("prefer_resources_constraints", stopwatch.time()))
    if evaluateResources:
        objective_value_from_avoid_split_assignments_constraints = _get_objective_value_avoid_split_assignments_constraints(
            instance, eventToSolutionEventsDict, False, focusEvent=newlyScheduledEvent, outputObjective=False)
    else:
        objective_value_from_avoid_split_assignments_constraints = 0.0
    times.append(("avoid_split_assignments_constraints", stopwatch.time()))
    if evaluateTime:
        objective_value_from_spread_events_constraints = _get_objective_value_spread_events_constraints(instance,
                                                                                                        eventToSolutionEventsDict,
                                                                                                        False,
                                                                                                        focusEvent=newlyScheduledEvent)
    else:
        objective_value_from_spread_events_constraints = 0.0

    times.append(("spread_events_constraints", stopwatch.time()))

    objective_value_from_avoid_clashes_constraints = _get_objective_value_avoid_clashes_constraints(instance,
                                                                                                    resourceToSolutionEventsByTimeDict,
                                                                                                    False,
                                                                                                    focusEventResources=newEventFixedResources,
                                                                                                    outputObjective=outputObjectiveValues)
    objective_value_from_avoid_clashes_constraints *= 10000
    times.append(("avoid_clashes_constraints", stopwatch.time()))

    objective_value_from_avoid_unavailable_times_constraints = _get_objective_value_avoid_unavailable_times_constraints(
        instance, resourceToSolutionEventsByTimeDict, False, focusEventResources=newEventFixedResources)

    times.append(("avoid_unavailable_times_constraints", stopwatch.time()))

    objective_value_from_limit_idle_times_constraints = _get_objective_value_limit_idle_times_constraints(instance,
                                                                                                          resourceToSolutionEventsByTimeDict,
                                                                                                          resourceToSolutionEventsDict,
                                                                                                          False,
                                                                                                          focusEventResources=newEventFixedResources
                                                                                                          )
    times.append(("limit_idle_times_constraints", stopwatch.time()))

    objective_value_from_cluster_busy_times_constraints = _get_objective_value_cluster_busy_times_constraints(instance,
                                                                                                              resourceToSolutionEventsByTimeDict,
                                                                                                              resourceToSolutionEventsDict,
                                                                                                              False,
                                                                                                              focusEventResources=newEventFixedResources
                                                                                                              )

    times.append(("cluster_busy_times_constraints", stopwatch.time()))
    objective_value_from_limit_busy_times_constraints = _get_objective_value_limit_busy_times_constraints(instance,
                                                                                                          resourceToSolutionEventsByTimeDict,
                                                                                                          resourceToSolutionEventsDict,
                                                                                                          False,
                                                                                                          focusEventResources=newEventFixedResources
                                                                                                          )
    times.append(("limit_busy_times_constraints", stopwatch.time()))
    if evaluateResources:
        objective_value_from_limit_workload_constraints = _get_objective_value_limit_workload_constraints(instance,
                                                                                                          resourceToSolutionEventsDict,
                                                                                                          False,
                                                                                                          focusEventResources=newEventFixedResources
                                                                                                          )
    else:
        objective_value_from_limit_workload_constraints = 0.0

    times.append(("limit_workload_constraints", stopwatch.time()))

    if evaluateResources:
        objective_value_from_balance_class_size_constraints = _get_objective_value_balance_class_size_constraints(instance,
                                                                                                                  eventToSolutionEventsDict,
                                                                                                                  False,
                                                                                                                  focusEvent=newlyScheduledEvent)
    else:
        objective_value_from_balance_class_size_constraints = 0.0

    times.append(("balance_class_size_constraints", stopwatch.time()))

    if evaluateResources:
        objective_value_from_student_choice_constraints = _get_objective_value_student_choice_constraints(instance,
                                                                                                          resourceToSolutionEventsDict,
                                                                                                          False,
                                                                                                          focusEventResources=newEventFixedResources,
                                                                                                          outputObjective=False)
    else:
        objective_value_from_student_choice_constraints = 0.0
    # objective_value_from_student_choice_constraints *= 10000
    times.append(("student_choice_constraints", stopwatch.time()))

    if outputObjectiveValues:
        print(f"prefer_times_constraints: {objective_value_from_prefer_times_constraints}")
        print(f"prefer_resources_constraints: {objective_value_from_prefer_resources_constraints}")
        print(f"avoid_split_assignments_constraints: {objective_value_from_avoid_split_assignments_constraints}")
        print(f"spread_events_constraints: {objective_value_from_spread_events_constraints}")
        print(f"avoid_clashes_constraints: {objective_value_from_avoid_clashes_constraints}")
        print(f"avoid_unavailable_times_constraints: {objective_value_from_avoid_unavailable_times_constraints}")
        print(f"limit_idle_times_constraints: {objective_value_from_limit_idle_times_constraints}")
        print(f"cluster_busy_times_constraints: {objective_value_from_cluster_busy_times_constraints}")
        print(f"limit_busy_times_constraints: {objective_value_from_limit_busy_times_constraints}")
        print(f"limit_workload_constraints: {objective_value_from_limit_workload_constraints}")
        print(f"balance_class_size_constraints: {objective_value_from_balance_class_size_constraints}")
        print(f"student_choice_constraints: {objective_value_from_student_choice_constraints}")
    objective_value = (objective_value_from_prefer_times_constraints + objective_value_from_prefer_resources_constraints +
                       objective_value_from_avoid_split_assignments_constraints + objective_value_from_spread_events_constraints +
                       objective_value_from_avoid_clashes_constraints +
                       objective_value_from_avoid_unavailable_times_constraints + objective_value_from_limit_idle_times_constraints +
                       objective_value_from_cluster_busy_times_constraints + objective_value_from_limit_busy_times_constraints +
                       objective_value_from_limit_workload_constraints + objective_value_from_balance_class_size_constraints +
                       objective_value_from_student_choice_constraints)
    if outputObjectiveValues:
        print(f"Total Objective: {objective_value}")

    if existingDicts is not None and restoreDictsAfterExecution:
        for modification in dictModifications[0]:
            eventToSolutionEventsDict[modification[0]].remove(modification[1])
            if len(modification) == 3:
                eventToSolutionEventsDict[modification[0]].append(modification[2])
            if len(eventToSolutionEventsDict[modification[0]]) == 0:
                del eventToSolutionEventsDict[modification[0]]
        for modification in dictModifications[1]:
            resourceToSolutionEventsByTimeDict[modification[0]][modification[1]].remove(modification[2])
            if len(modification) == 4:
                resourceToSolutionEventsByTimeDict[modification[0]][modification[1]].append(modification[3])
            if len(resourceToSolutionEventsByTimeDict[modification[0]][modification[1]]) == 0:
                del resourceToSolutionEventsByTimeDict[modification[0]][modification[1]]
        for modification in dictModifications[2]:
            resourceToSolutionEventsDict[modification[0]].remove(modification[1])
            if len(modification) == 3:
                resourceToSolutionEventsDict[modification[0]].append(modification[2])
            if len(resourceToSolutionEventsDict[modification[0]]) == 0:
                del resourceToSolutionEventsDict[modification[0]]
    return objective_value, createdPartialSolutionDicts

def _create_event_to_solution_events_dict(instance: Instance, solutionData: dict) -> dict:
    eventToSolutionEventsDict = dict()
    eventToAllSolutionEventsDict = dict()
    eventToAddedSubeventDuration = dict()
    for event in solutionData[XHSTTFileConstants.EVENTS].keys():
        eventToAddedSubeventDuration.setdefault(event[0], 0)
        eventToAllSolutionEventsDict.setdefault(event[0], list()).append(solutionData[XHSTTFileConstants.EVENTS][event])
        addedToList = False
        if XHSTTFileConstants.RESOURCES not in solutionData[XHSTTFileConstants.EVENTS][event].keys():
            solutionData[XHSTTFileConstants.EVENTS][event][XHSTTFileConstants.RESOURCES] = dict()
        for role in solutionData[XHSTTFileConstants.EVENTS][event][XHSTTFileConstants.RESOURCES].keys():
            if solutionData[XHSTTFileConstants.EVENTS][event][XHSTTFileConstants.RESOURCES][role] != ILPConstants.DUMMY_RESOURCE and XHSTTFileConstants.NO_ROLE not in role:
                eventToSolutionEventsDict.setdefault(event[0], list()).append(solutionData[XHSTTFileConstants.EVENTS][event])
                eventToAddedSubeventDuration[event[0]] += event[1][0]
                addedToList = True
                break
        if solutionData[XHSTTFileConstants.EVENTS][event][XHSTTFileConstants.TIME] != ILPConstants.DUMMY_TIME and not addedToList:
            eventToSolutionEventsDict.setdefault(event[0], list()).append(solutionData[XHSTTFileConstants.EVENTS][event])
            eventToAddedSubeventDuration[event[0]] += event[1][0]

    for event_id, solutionEventList in eventToAllSolutionEventsDict.items():
        if eventToAddedSubeventDuration[event_id] == int(instance.Events.IndividualEvents[event_id].Duration):
            continue
        missingDuration = int(instance.Events.IndividualEvents[event_id].Duration) - eventToAddedSubeventDuration[event_id]
        solutionEventsByDurationDict = dict()
        for solEvent in solutionEventList:
            solutionEventsByDurationDict.setdefault(solEvent[XHSTTFileConstants.ID][1][0], list()).append(solEvent)

        durations_desc = sorted(solutionEventsByDurationDict.keys(), reverse=True)

        for duration in durations_desc:
            if missingDuration <= 0:
                break

            if duration > missingDuration:
                continue

            for solEvent in solutionEventsByDurationDict[duration]:
                if missingDuration <= 0 or duration > missingDuration:
                    break

                # avoid adding duplicates
                if solEvent in eventToSolutionEventsDict.get(event_id, []):
                    continue

                eventToSolutionEventsDict.setdefault(event_id, []).append(solEvent)
                missingDuration -= duration

        # safety check (should always hold by your structural guarantee)
        if missingDuration != 0:
            allSubeventsInSolutionDict = [solEvent for eventID, solEvent in solutionData[XHSTTFileConstants.EVENTS].items() if eventID[0] == event_id]
            raise ValueError(
                f"Could not reconstruct duration for event {event_id} with duration {int(instance.Events.IndividualEvents[event_id].Duration)}. "
                f"Remaining duration: {missingDuration}\n"
                f"Solution events: {eventToSolutionEventsDict[event_id]}\n"
                f"All solution events: {allSubeventsInSolutionDict}\n"
            )



    return eventToSolutionEventsDict

def _create_event_to_solution_events_dict_from_partial_solution(partialSolutionData: dict, includePseudo=True, existingDict=None, newEvent=None, modifications=None) -> dict:
    if existingDict is None:
        eventToSolutionEventsDict = dict()
        for event in partialSolutionData.keys():
            for subevent in partialSolutionData[event].keys():
                addedToList = False
                for role in partialSolutionData[event][subevent]["PossibleResources"].keys():
                    if role is not None and role.startswith("Pseudo") and not includePseudo:
                        continue
                    if len(partialSolutionData[event][subevent]["PossibleResources"][role]) == 1:
                        solutionEvent = _create_solution_event_from_partial_assignment(partialSolutionData[event][subevent], (event, subevent))
                        eventToSolutionEventsDict.setdefault(event, list()).append(solutionEvent)
                        modifications.append((event, solutionEvent))
                        addedToList = True
                        break
                if len(partialSolutionData[event][subevent]["PossibleTimes"]) == 1 and not addedToList:
                    solutionEvent = _create_solution_event_from_partial_assignment(partialSolutionData[event][subevent], (event, subevent))
                    eventToSolutionEventsDict.setdefault(event, list()).append(solutionEvent)
                    modifications.append((event, solutionEvent))
    else:
        eventToSolutionEventsDict = existingDict
        event = newEvent[0]
        subevent = newEvent[1]
        eventToSolutionEventsDict[event] = list()
        addedToList = False
        for role in partialSolutionData[event][subevent]["PossibleResources"].keys():
            if role is not None and role.startswith("Pseudo") and not includePseudo:
                continue
            if len(partialSolutionData[event][subevent]["PossibleResources"][role]) == 1:
                solutionEvent = _create_solution_event_from_partial_assignment(partialSolutionData[event][subevent],
                                                                               (event, subevent))
                eventToSolutionEventsDict.setdefault(event, list())
                if solutionEvent[XHSTTFileConstants.ID] not in [se[XHSTTFileConstants.ID] for se in eventToSolutionEventsDict[event]]:
                    eventToSolutionEventsDict[event].append(solutionEvent)
                    modifications.append((event, solutionEvent))
                addedToList = True
                break
        if len(partialSolutionData[event][subevent]["PossibleTimes"]) == 1 and not addedToList:
            solutionEvent = _create_solution_event_from_partial_assignment(partialSolutionData[event][subevent],
                                                                           (event, subevent))
            eventToSolutionEventsDict.setdefault(event, list())
            if solutionEvent[XHSTTFileConstants.ID] not in [se[XHSTTFileConstants.ID] for se in
                                                            eventToSolutionEventsDict[event]]:
                eventToSolutionEventsDict[event].append(solutionEvent)
                modifications.append((event, solutionEvent))
            else:
                eventToRemove = None
                for se in eventToSolutionEventsDict[event]:
                    if se[XHSTTFileConstants.ID] == solutionEvent[XHSTTFileConstants.ID]:
                        eventToRemove = se
                eventToSolutionEventsDict[event].remove(eventToRemove)
                eventToSolutionEventsDict[event].append(solutionEvent)
                modifications.append((event, solutionEvent, eventToRemove))
    return eventToSolutionEventsDict

def _create_solution_event_from_partial_assignment(partialAssignment: dict, event) -> dict:
    solutionEvent = dict()
    solutionEvent[XHSTTFileConstants.RESOURCES] = dict()
    if len(partialAssignment["PossibleTimes"]) == 1:
        solutionEvent[XHSTTFileConstants.TIME] = partialAssignment["PossibleTimes"][0]

    for role in partialAssignment["PossibleResources"].keys():
        if len(partialAssignment["PossibleResources"][role]) == 1:
            solutionEvent[XHSTTFileConstants.RESOURCES][role] = partialAssignment["PossibleResources"][role][0]
    solutionEvent[XHSTTFileConstants.DURATION] = event[1][0]
    solutionEvent[XHSTTFileConstants.ID] = event
    solutionEvent[XHSTTFileConstants.NAME] = event[0]
    return solutionEvent
def _create_resource_to_solution_events_by_time_dict(instance: XHSTTInstance, solutionData: dict) -> dict:
    listOfTimes = list(instance.Times.IndividualTimes.keys())
    resourceToSolutionEventsByTimeDict = dict()
    for solutioneventKey in solutionData[XHSTTFileConstants.EVENTS].keys():
        solutionevent = solutionData[XHSTTFileConstants.EVENTS][solutioneventKey]
        if solutionevent[XHSTTFileConstants.TIME] == ILPConstants.DUMMY_TIME or solutionevent[XHSTTFileConstants.TIME] is None:
            continue
        indexOfSolutionEventStartTime = listOfTimes.index(solutionevent[XHSTTFileConstants.TIME])
        timesInWhichSolutionEventIsActive = listOfTimes[
                                            indexOfSolutionEventStartTime:indexOfSolutionEventStartTime +
                                                                          int(solutionevent[XHSTTFileConstants.DURATION])]
        for time in timesInWhichSolutionEventIsActive:
            for resourceRole in solutionData[XHSTTFileConstants.EVENTS][solutioneventKey][XHSTTFileConstants.RESOURCES].keys():
                resourceToSolutionEventsByTimeDict.setdefault(solutionData[XHSTTFileConstants.EVENTS][solutioneventKey][XHSTTFileConstants.RESOURCES][resourceRole], dict()).setdefault(time, list()).append(solutionevent)
    for resource in instance.Resources.IndividualResources.keys():
        resourceToSolutionEventsByTimeDict.setdefault(resource, dict())
    return resourceToSolutionEventsByTimeDict

def _create_resource_to_solution_events_by_time_dict_from_partial_solution(instance: XHSTTInstance, partialSolutionData: dict, includePseudo=True, existingDict=None, newEvent=None, modifications=None) -> dict:
    listOfTimes = list(instance.Times.IndividualTimes.keys())
    if existingDict is None:
        resourceToSolutionEventsByTimeDict = dict()
        for event in partialSolutionData.keys():
            for subevent in partialSolutionData[event].keys():
                solutionevent = _create_solution_event_from_partial_assignment(partialSolutionData[event][subevent], (event, subevent))
                if (XHSTTFileConstants.TIME not in solutionevent.keys() or solutionevent[XHSTTFileConstants.TIME] is None or
                        solutionevent[XHSTTFileConstants.TIME] == ILPConstants.DUMMY_TIME):
                    continue
                indexOfSolutionEventStartTime = listOfTimes.index(solutionevent[XHSTTFileConstants.TIME])
                timesInWhichSolutionEventIsActive = listOfTimes[
                                                    indexOfSolutionEventStartTime:indexOfSolutionEventStartTime +
                                                                                  int(subevent[0])]
                for time in timesInWhichSolutionEventIsActive:
                    for role in partialSolutionData[event][subevent]["PossibleResources"].keys():
                        if role is not None and role.startswith("Pseudo") and not includePseudo:
                            continue
                        if len(partialSolutionData[event][subevent]["PossibleResources"][role]) == 1:
                            resource = partialSolutionData[event][subevent]["PossibleResources"][role][0]
                            resourceToSolutionEventsByTimeDict.setdefault(resource, dict()).setdefault(time, list()).append(solutionevent)
                            modifications.append((resource, time, solutionevent))
        for resource in instance.Resources.IndividualResources.keys():
            resourceToSolutionEventsByTimeDict.setdefault(resource, dict())
    else:
        resourceToSolutionEventsByTimeDict = existingDict
        event = newEvent[0]
        subevent = newEvent[1]
        solutionevent = _create_solution_event_from_partial_assignment(partialSolutionData[event][subevent],
                                                                       (event, subevent))
        if (XHSTTFileConstants.TIME not in solutionevent.keys() or solutionevent[XHSTTFileConstants.TIME] is None or solutionevent[XHSTTFileConstants.TIME] == ILPConstants.DUMMY_TIME):
            return resourceToSolutionEventsByTimeDict
        indexOfSolutionEventStartTime = listOfTimes.index(solutionevent[XHSTTFileConstants.TIME])
        timesInWhichSolutionEventIsActive = listOfTimes[
                                            indexOfSolutionEventStartTime:indexOfSolutionEventStartTime +
                                                                          int(subevent[0])]
        for time in timesInWhichSolutionEventIsActive:
            modifiedResources = set()
            resourcesToSkip = set()
            for role in partialSolutionData[event][subevent]["PossibleResources"].keys():
                if role is not None and role.startswith("Pseudo") and not includePseudo:
                    continue
                if len(partialSolutionData[event][subevent]["PossibleResources"][role]) == 1:
                    resource = partialSolutionData[event][subevent]["PossibleResources"][role][0]
                    if resource in resourcesToSkip:
                        continue
                    resourceToSolutionEventsByTimeDict.setdefault(resource, dict()).setdefault(time, list())
                    if solutionevent[XHSTTFileConstants.ID] not in [se[XHSTTFileConstants.ID] for se in resourceToSolutionEventsByTimeDict[resource][time]] or resource in modifiedResources:
                        modifiedResources.add(resource)
                        resourceToSolutionEventsByTimeDict[resource][time].append(solutionevent)
                        modifications.append((resource, time, solutionevent))
                    else:
                        eventsToRemove = list()
                        for se in resourceToSolutionEventsByTimeDict[resource][time]:
                            if se[XHSTTFileConstants.ID] == solutionevent[XHSTTFileConstants.ID]:
                                eventsToRemove.append(se)
                        newEventsCounter = 0
                        for role in partialSolutionData[event][subevent]["PossibleResources"].keys():
                            if role is not None and role.startswith("Pseudo") and not includePseudo:
                                continue
                            if len(partialSolutionData[event][subevent]["PossibleResources"][role]) == 1:
                                res = partialSolutionData[event][subevent]["PossibleResources"][role][0]
                                if res == resource:
                                    newEventsCounter += 1
                        for eventToRemove in eventsToRemove:
                            resourceToSolutionEventsByTimeDict[resource][time].remove(eventToRemove)
                        for i in range(newEventsCounter):
                            resourceToSolutionEventsByTimeDict[resource][time].append(solutionevent)
                        for eventToRemove in eventsToRemove:
                            modifications.append((resource, time, solutionevent, eventToRemove))
                        for i in range(newEventsCounter - len(eventsToRemove)):
                            modifications.append((resource, time, solutionevent))
                        resourcesToSkip.add(resource)
    return resourceToSolutionEventsByTimeDict
def _create_resource_to_solution_events_dict_from_partial_solution(partialSolutionData: dict, includePseudo=True, existingDict=None, newEvent=None, modifications=None) -> dict:
    if existingDict is None:
        resourceToSolutionEventsDict = dict()
        for event in partialSolutionData.keys():
            for subevent in partialSolutionData[event].keys():
                solutionevent = _create_solution_event_from_partial_assignment(partialSolutionData[event][subevent], (event, subevent))
                for role in partialSolutionData[event][subevent]["PossibleResources"].keys():
                    if role is not None and role.startswith("Pseudo") and not includePseudo:
                        continue
                    if len(partialSolutionData[event][subevent]["PossibleResources"][role]) != 1:
                        continue
                    # or
                    # solutionevent[XHSTTFileConstants.TIME] == ILPConstants.DUMMY_TIME)
                    if (XHSTTFileConstants.TIME not in solutionevent.keys() or solutionevent[
                        XHSTTFileConstants.TIME] is None):
                        continue
                    resource = partialSolutionData[event][subevent]["PossibleResources"][role][0]
                    resourceToSolutionEventsDict.setdefault(resource, list()).append(solutionevent)
                    modifications.append((resource, solutionevent))
    else:
        resourceToSolutionEventsDict = existingDict
        event = newEvent[0]
        subevent = newEvent[1]
        solutionevent = _create_solution_event_from_partial_assignment(partialSolutionData[event][subevent],
                                                                       (event, subevent))
        modifiedResources = set()
        resourcesToSkip = set()
        for role in partialSolutionData[event][subevent]["PossibleResources"].keys():
            if role is not None and role.startswith("Pseudo") and not includePseudo:
                continue
            if len(partialSolutionData[event][subevent]["PossibleResources"][role]) != 1:
                continue
            if (XHSTTFileConstants.TIME not in solutionevent.keys() or solutionevent[
                XHSTTFileConstants.TIME] is None):
                continue
            resource = partialSolutionData[event][subevent]["PossibleResources"][role][0]
            if resource in resourcesToSkip:
                continue
            resourceToSolutionEventsDict.setdefault(resource, list())
            if solutionevent[XHSTTFileConstants.ID] not in [se[XHSTTFileConstants.ID] for se in
                                                            resourceToSolutionEventsDict[resource]] or resource in modifiedResources:
                modifiedResources.add(resource)
                resourceToSolutionEventsDict[resource].append(solutionevent)
                modifications.append((resource, solutionevent))
            else:
                eventsToRemove = list()
                for se in resourceToSolutionEventsDict[resource]:
                    if se[XHSTTFileConstants.ID] == solutionevent[XHSTTFileConstants.ID]:
                        eventsToRemove.append(se)
                newEventsCounter = 0
                for role in partialSolutionData[event][subevent]["PossibleResources"].keys():
                    if role is not None and role.startswith("Pseudo") and not includePseudo:
                        continue
                    if len(partialSolutionData[event][subevent]["PossibleResources"][role]) == 1:
                        res = partialSolutionData[event][subevent]["PossibleResources"][role][0]
                        if res == resource:
                            newEventsCounter += 1
                for eventToRemove in eventsToRemove:
                    resourceToSolutionEventsDict[resource].remove(eventToRemove)
                for i in range(newEventsCounter):
                    resourceToSolutionEventsDict[resource].append(solutionevent)
                for eventToRemove in eventsToRemove:
                    modifications.append((resource, solutionevent, eventToRemove))
                for i in range(newEventsCounter - len(eventsToRemove)):
                    modifications.append((resource, solutionevent))
                resourcesToSkip.add(resource)
    return resourceToSolutionEventsDict

def _create_resource_to_solution_events_dict(solutionData: dict) -> dict:
    resourceToSolutionEventsDict = dict()
    for solutioneventKey in solutionData[XHSTTFileConstants.EVENTS].keys():
        solutionevent = solutionData[XHSTTFileConstants.EVENTS][solutioneventKey]
        for resourceRole in solutionData[XHSTTFileConstants.EVENTS][solutioneventKey][XHSTTFileConstants.RESOURCES].keys():
            # if solutionevent[XHSTTFileConstants.TIME] != ILPConstants.DUMMY_TIME:
            resourceToSolutionEventsDict.setdefault(
                solutionData[XHSTTFileConstants.EVENTS][solutioneventKey][XHSTTFileConstants.RESOURCES][resourceRole], list()).append(solutionevent)

    return resourceToSolutionEventsDict
def _get_objective_value_assign_resources_constraints(instance, eventToSolutionEventsDict, useWeightCopy, outputObjective=False, constraints=None, excludeDeviationInfo=False) -> float:
    objective_value = 0.0
    if constraints is None:
        constraints = instance.Constraints[XHSTTConstraintConstants.ASSIGN_RESOURCE_CONSTRAINT]
    for constraint in constraints:
        constraint[XHSTTConstraintConstants.IS_FULFILLED] = True
        constraint[XHSTTConstraintConstants.DEVIATION_EVENTS] = list()
        constraint[XHSTTConstraintConstants.DEVIATION_AMOUNT] = 0
        
        constraint[XHSTTConstraintConstants.OBJECTIVE_VALUE] = 0
        consideredEvents = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS])
        for eventGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
            consideredEvents.update(set(instance.Events.EventGroups[eventGroup].Events))
        for event in consideredEvents:
            if event in eventToSolutionEventsDict.keys():
                totalDurationOfSolutionEventsWithAssignedResource = 0
                if constraint[XHSTTFileConstants.ROLE] not in [eventResource.Role for eventResource in instance.Events.IndividualEvents[event].EventResources.UnassignedResources]:
                    deviation = 0
                else:
                    for solutionevent in eventToSolutionEventsDict[event]:
                        if constraint[XHSTTFileConstants.ROLE] not in solutionevent[XHSTTFileConstants.RESOURCES].keys() or (constraint[XHSTTFileConstants.ROLE] in solutionevent[XHSTTFileConstants.RESOURCES].keys() and solutionevent[XHSTTFileConstants.RESOURCES][constraint[XHSTTFileConstants.ROLE]] != ILPConstants.DUMMY_RESOURCE):
                            totalDurationOfSolutionEventsWithAssignedResource += int(solutionevent[XHSTTFileConstants.DURATION])
                        elif not excludeDeviationInfo:
                            constraint[XHSTTConstraintConstants.DEVIATION_EVENTS].append(solutionevent)
                    deviation = instance.Events.IndividualEvents[event].Duration - totalDurationOfSolutionEventsWithAssignedResource
                if outputObjective and deviation > 0:
                    print(f"Assign Resource Violation (Required: {str(constraint[XHSTTConstraintConstants.REQUIRED])}): Event: {event}, Role: {constraint[XHSTTFileConstants.ROLE]}, Deviation: {deviation}")
            elif constraint[XHSTTFileConstants.ROLE] in [er.Role for er in instance.Events.IndividualEvents[event].EventResources.AssignedResources] + [er.Role for er in instance.Events.IndividualEvents[event].EventResources.UnassignedResources]:
                deviation = instance.Events.IndividualEvents[event].Duration
                if True and deviation > 0:
                    print(f"Assign Resource Violation (Required: {str(constraint[XHSTTConstraintConstants.REQUIRED])})(not in dict): Event: {event}, Role: {constraint[XHSTTFileConstants.ROLE]}, Deviation: {deviation}")
            else:
                deviation = 0
            constraint[XHSTTConstraintConstants.DEVIATION_AMOUNT] += deviation
            
            added_objective_value = _get_added_objective_value(constraint, deviation, useWeightCopy)
            objective_value += added_objective_value
            constraint[XHSTTConstraintConstants.OBJECTIVE_VALUE] += added_objective_value


    return objective_value
def _get_objective_value_assign_times_constraints(instance, eventToSolutionEventsDict, useWeightCopy, outputObjective=False, fullSolution=None, constraints=None, excludeDeviationInfo=False) -> float:
    objective_value = 0.0
    if constraints is None:
        constraints = instance.Constraints[XHSTTConstraintConstants.ASSIGN_TIME_CONSTRAINT]
    for constraint in constraints:
        constraint[XHSTTConstraintConstants.IS_FULFILLED] = True
        constraint[XHSTTConstraintConstants.DEVIATION_EVENTS] = list()
        constraint[XHSTTConstraintConstants.DEVIATION_AMOUNT] = 0
        
        constraint[XHSTTConstraintConstants.OBJECTIVE_VALUE] = 0
        consideredEvents = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS])
        for eventGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
            consideredEvents.update(set(instance.Events.EventGroups[eventGroup].Events))
        for event in consideredEvents:
            totalDurationOfSolutionEvents = 0
            if event in eventToSolutionEventsDict.keys():
                for solutionevent in eventToSolutionEventsDict[event]:
                    if solutionevent[XHSTTFileConstants.TIME] != ILPConstants.DUMMY_TIME:
                        totalDurationOfSolutionEvents += int(solutionevent[XHSTTFileConstants.DURATION])
                    elif not excludeDeviationInfo:
                        constraint[XHSTTConstraintConstants.DEVIATION_EVENTS].append(solutionevent)
                deviation = instance.Events.IndividualEvents[event].Duration - totalDurationOfSolutionEvents
                if deviation > 0 and outputObjective:
                    print(f"1 Assign Times Constraint (Required: {str(constraint[XHSTTConstraintConstants.REQUIRED])}): Event {event} is missing time assignments for {deviation} hours")
            else:
                deviation = instance.Events.IndividualEvents[event].Duration
                if deviation > 0 and outputObjective:
                    print(f"2 Assign Times Constraint (Required: {str(constraint[XHSTTConstraintConstants.REQUIRED])}): Event {event} is missing time assignments for {deviation} hours")
            constraint[XHSTTConstraintConstants.DEVIATION_AMOUNT] += deviation
            
            added_objective_value = _get_added_objective_value(constraint, deviation, useWeightCopy)
            objective_value += added_objective_value
            constraint[XHSTTConstraintConstants.OBJECTIVE_VALUE] += added_objective_value


    return objective_value

def _get_objective_value_split_events_constraints(instance, eventToSolutionEventsDict, useWeightCopy, outputObjective=False, constraints=None, excludeDeviationInfo=False) -> float:
    objective_value = 0.0
    if constraints is None:
        constraints = instance.Constraints[XHSTTConstraintConstants.SPLIT_EVENTS_CONSTRAINT]
    for constraint in constraints:
        constraint[XHSTTConstraintConstants.IS_FULFILLED] = True
        constraint[XHSTTConstraintConstants.DEVIATION_EVENTS] = list()
        constraint[XHSTTConstraintConstants.DEVIATION_AMOUNT] = 0
        
        constraint[XHSTTConstraintConstants.OBJECTIVE_VALUE] = 0
        consideredEvents = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS])
        for eventGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
            consideredEvents.update(set(instance.Events.EventGroups[eventGroup].Events))
        for event in consideredEvents:
            if event in eventToSolutionEventsDict.keys():
                numberOfUniqueSubevents = len(eventToSolutionEventsDict[event])
                deviation = (max(int(constraint[XHSTTConstraintConstants.MINIMUM_AMOUNT]) - numberOfUniqueSubevents, 0) +
                             max(numberOfUniqueSubevents - int(constraint[XHSTTConstraintConstants.MAXIMUM_AMOUNT]), 0))
                if outputObjective and deviation > 0:
                    print(f"Split Events Violation (Required: {str(constraint[XHSTTConstraintConstants.REQUIRED])}) (wrong number events): Range: {(int(constraint[XHSTTConstraintConstants.MINIMUM_AMOUNT]), int(constraint[XHSTTConstraintConstants.MAXIMUM_AMOUNT]))} Amount: {numberOfUniqueSubevents} Deviation Value: {deviation} Events: {eventToSolutionEventsDict[event]}")
                eventsWithDurationViolations = [solutionevent for solutionevent in eventToSolutionEventsDict[event]
                                                if int(solutionevent[XHSTTFileConstants.DURATION]) > int(constraint[XHSTTConstraintConstants.MAXIMUM_DURATION]) or
                                                int(solutionevent[XHSTTFileConstants.DURATION]) < int(constraint[XHSTTConstraintConstants.MINIMUM_DURATION])]
                if not excludeDeviationInfo:
                    constraint[XHSTTConstraintConstants.DEVIATION_EVENTS] += eventsWithDurationViolations
                deviation += len(eventsWithDurationViolations)
                if outputObjective and len(eventsWithDurationViolations) > 0:
                    print(f"Split Events Violation (Required: {str(constraint[XHSTTConstraintConstants.REQUIRED])}) (wrong duration): Range: {(int(constraint[XHSTTConstraintConstants.MINIMUM_DURATION]), int(constraint[XHSTTConstraintConstants.MINIMUM_DURATION]))} Deviation Value: {len(eventsWithDurationViolations)} Events: {eventsWithDurationViolations}")
            else:
                deviation = 0
            constraint[XHSTTConstraintConstants.DEVIATION_AMOUNT] += deviation
            
            added_objective_value = _get_added_objective_value(constraint, deviation, useWeightCopy)
            objective_value += added_objective_value
            constraint[XHSTTConstraintConstants.OBJECTIVE_VALUE] += added_objective_value

    return objective_value
def _get_objective_value_distribute_split_events_constraints(instance, eventToSolutionEventsDict, useWeightCopy, constraints=None, excludeDeviationInfo=False, outputObjective=False) -> float:
    objective_value = 0.0
    if constraints is None:
        constraints = instance.Constraints[XHSTTConstraintConstants.DISTRIBUTE_SPLIT_EVENTS_CONSTRAINT]
    for constraint in constraints:
        constraint[XHSTTConstraintConstants.IS_FULFILLED] = True
        constraint[XHSTTConstraintConstants.DEVIATION_EVENTS] = list()
        constraint[XHSTTConstraintConstants.DEVIATION_AMOUNT] = 0
        
        constraint[XHSTTConstraintConstants.OBJECTIVE_VALUE] = 0
        consideredEvents = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS])
        for eventGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
            consideredEvents.update(set(instance.Events.EventGroups[eventGroup].Events))
        for event in consideredEvents:
            if event in eventToSolutionEventsDict.keys():
                eventsWithConstraintDuration = [solutionevent for solutionevent in eventToSolutionEventsDict[event]
                                                if int(solutionevent[XHSTTFileConstants.DURATION]) == int(constraint[XHSTTFileConstants.DURATION])]
                if not excludeDeviationInfo:
                    if len(eventsWithConstraintDuration) < int(constraint[XHSTTConstraintConstants.MINIMUM]):
                        constraint[XHSTTConstraintConstants.DEVIATION_EVENTS] = [solutionevent for solutionevent in eventToSolutionEventsDict[event]
                                                    if int(solutionevent[XHSTTFileConstants.DURATION]) != int(constraint[XHSTTFileConstants.DURATION])]
                    elif len(eventsWithConstraintDuration) > int(constraint[XHSTTConstraintConstants.MAXIMUM]):
                        constraint[XHSTTConstraintConstants.DEVIATION_EVENTS] = eventsWithConstraintDuration
                deviation = (max(int(int(constraint[XHSTTConstraintConstants.MINIMUM])) - len(eventsWithConstraintDuration), 0) +
                             max(len(eventsWithConstraintDuration) - int(int(constraint[XHSTTConstraintConstants.MAXIMUM])), 0))
                if deviation > 0 and outputObjective:
                    print(f"Distribute Split Events Violations (Required: {str(constraint[XHSTTConstraintConstants.REQUIRED])}): Event of {event} has {deviation} Amount: {len(eventsWithConstraintDuration)} of duration {constraint[XHSTTFileConstants.DURATION]} (Min: {constraint[XHSTTConstraintConstants.MINIMUM]}, Max: {constraint[XHSTTConstraintConstants.MAXIMUM]})")
            else:
                deviation = int(int(constraint[XHSTTConstraintConstants.MINIMUM]))
            constraint[XHSTTConstraintConstants.DEVIATION_AMOUNT] += deviation
            
            added_objective_value = _get_added_objective_value(constraint, deviation, useWeightCopy)
            objective_value += added_objective_value
            constraint[XHSTTConstraintConstants.OBJECTIVE_VALUE] += added_objective_value


    return objective_value

def _get_objective_value_prefer_resources_constraints(instance, eventToSolutionEventsDict, useWeightCopy, focusEvent=None, outputObjective=False, constraints=None, excludeDeviationInfo=False) -> float:
    objective_value = 0.0
    if constraints is None:
        constraints = instance.Constraints[XHSTTConstraintConstants.PREFER_RESOURCES_CONSTRAINT]
    for constraint in constraints:
        constraint[XHSTTConstraintConstants.IS_FULFILLED] = True
        if focusEvent is None:
            constraint[XHSTTConstraintConstants.DEVIATION_EVENTS] = list()
        constraint[XHSTTConstraintConstants.DEVIATION_AMOUNT] = 0
        
        constraint[XHSTTConstraintConstants.OBJECTIVE_VALUE] = 0
        consideredEvents = [(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS][eventindex], eventindex) for eventindex in
                            range(len(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS]))]
        for eventGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
            consideredEvents = consideredEvents + [(event, "Group" + str(eventGroup)) for event in
                                                   instance.Events.EventGroups[eventGroup].Events]
        if focusEvent is not None:
            if focusEvent[0] in consideredEvents:
                consideredEvents = [focusEvent[0]]
            else:
                continue
        if XHSTTFileConstants.RESOURCES in constraint:
            preferredResources = set(constraint[XHSTTFileConstants.RESOURCES])
        else:
            preferredResources = set()
        if XHSTTFileConstants.RESOURCE_GROUPS in constraint:
            for resourceGroup in constraint[XHSTTFileConstants.RESOURCE_GROUPS]:
                for resourceType in instance.Resources.ResourceGroupsByType.keys():
                    if resourceGroup in instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups:
                        preferredResources.update(set(
                            instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups[resourceGroup].Resources))
        violation_resources = set()
        for event in consideredEvents:
            if event[0] in eventToSolutionEventsDict.keys():
                deviation = 0
                for solutionevent in eventToSolutionEventsDict[event[0]]:
                    if constraint[XHSTTFileConstants.ROLE] in solutionevent[XHSTTFileConstants.RESOURCES].keys() and (solutionevent[XHSTTFileConstants.RESOURCES][constraint[XHSTTFileConstants.ROLE]] != ILPConstants.DUMMY_RESOURCE and
                            solutionevent[XHSTTFileConstants.RESOURCES][constraint[XHSTTFileConstants.ROLE]] not in preferredResources):
                        deviation += int(solutionevent[XHSTTFileConstants.DURATION])
                        violation_resources.add(solutionevent[XHSTTFileConstants.RESOURCES][constraint[XHSTTFileConstants.ROLE]])
                        if focusEvent is None and not excludeDeviationInfo:
                            constraint[XHSTTConstraintConstants.DEVIATION_EVENTS].append(solutionevent)
            else:
                deviation = 0
            if deviation > 0 and outputObjective:
                print(f"Resource Preference Constraint (Required: {str(constraint[XHSTTConstraintConstants.REQUIRED])}) violated for role {constraint[XHSTTFileConstants.ROLE]} of event {event} Possible Resources {preferredResources} Wrongly used Resources {list(violation_resources)}")
            constraint[XHSTTConstraintConstants.DEVIATION_AMOUNT] += deviation
            
            added_objective_value = _get_added_objective_value(constraint, deviation, useWeightCopy)
            objective_value += added_objective_value
            constraint[XHSTTConstraintConstants.OBJECTIVE_VALUE] += added_objective_value


    return objective_value
def _get_objective_value_prefer_times_constraints(instance, eventToSolutionEventsDict, useWeightCopy, focusEvent=None, outputObjective=False, constraints=None, excludeDeviationInfo=False) -> float:
    objective_value = 0.0
    if constraints is None:
        constraints = instance.Constraints[XHSTTConstraintConstants.PREFER_TIMES_CONSTRAINT]
    for constraint in constraints:
        constraint[XHSTTConstraintConstants.IS_FULFILLED] = True
        if focusEvent is None:
            constraint[XHSTTConstraintConstants.DEVIATION_EVENTS] = list()
        constraint[XHSTTConstraintConstants.DEVIATION_AMOUNT] = 0
        
        constraint[XHSTTConstraintConstants.OBJECTIVE_VALUE] = 0
        consideredEvents = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS])
        for eventGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
            consideredEvents.update(set(instance.Events.EventGroups[eventGroup].Events))
        if focusEvent is not None:
            if focusEvent[0] in consideredEvents:
                consideredEvents = [focusEvent[0]]
            else:
                continue
        if XHSTTFileConstants.TIMES in constraint.keys():
            constraintTimes = set(constraint[XHSTTFileConstants.TIMES])
            for timeGroup in constraint[XHSTTFileConstants.TIME_GROUPS]:
                if timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT] in instance.Times.TimeGroups.keys():
                    constraintTimes.update(set(instance.Times.TimeGroups[timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]].Times))
                elif timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT] in instance.Times.Days.keys():
                    constraintTimes.update(set(instance.Times.Days[timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]].Times))
        else:
            constraintTimes = set()
        for event in consideredEvents:
            deviation = 0
            violationTimes = set()
            if event in eventToSolutionEventsDict.keys():
                for solutionevent in eventToSolutionEventsDict[event]:
                    if (solutionevent[XHSTTFileConstants.TIME] != ILPConstants.DUMMY_TIME and solutionevent[XHSTTFileConstants.TIME] not in constraintTimes and
                            (XHSTTFileConstants.DURATION not in constraint.keys() or int(constraint[XHSTTFileConstants.DURATION]) == int(solutionevent[XHSTTFileConstants.DURATION]))):
                        violationTimes.add(solutionevent[XHSTTFileConstants.TIME])
                        deviation += int(solutionevent[XHSTTFileConstants.DURATION])
                        if focusEvent is None and not excludeDeviationInfo:
                            constraint[XHSTTConstraintConstants.DEVIATION_EVENTS].append(solutionevent)

            constraint[XHSTTConstraintConstants.DEVIATION_AMOUNT] += deviation
            
            if outputObjective and deviation > 0:
                print(f"Prefer Times Constraint (Required: {str(constraint[XHSTTConstraintConstants.REQUIRED])}): Event {event} has events of duration {deviation} at {violationTimes} that are not scheduled during prefered times {constraintTimes}")
            added_objective_value = _get_added_objective_value(constraint, deviation, useWeightCopy)
            objective_value += added_objective_value
            constraint[XHSTTConstraintConstants.OBJECTIVE_VALUE] += added_objective_value
        if outputObjective and not constraint[XHSTTConstraintConstants.IS_FULFILLED]:
            print(f"Prefer Times Constraint (Required: {str(constraint[XHSTTConstraintConstants.REQUIRED])}): Prefered Times: {sorted(constraintTimes, key=lambda a: int(a.split('_')[-1]))} Violation Subevents: {constraint[XHSTTConstraintConstants.DEVIATION_EVENTS]}")


    return objective_value

def _get_objective_value_avoid_split_assignments_constraints(instance, eventToSolutionEventsDict, useWeightCopy, focusEvent=None, outputObjective=False, constraints=None, excludeDeviationInfo=False) -> float:
    objective_value = 0.0
    if constraints is None:
        constraints = instance.Constraints[XHSTTConstraintConstants.AVOID_SPLIT_ASSIGNMENTS_CONSTRAINT]
    for constraint in constraints:
        constraint[XHSTTConstraintConstants.IS_FULFILLED] = True
        if focusEvent is None:
            constraint[XHSTTConstraintConstants.DEVIATION_EVENTS] = list()
        constraint[XHSTTConstraintConstants.DEVIATION_AMOUNT] = 0
        constraint.setdefault(XHSTTConstraintConstants.DEVIATION_MAP, dict())
        constraint[XHSTTConstraintConstants.OBJECTIVE_VALUE] = 0
        consideredEvents = set()
        for eventGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
            consideredEvents.update(set(instance.Events.EventGroups[eventGroup].Events))
        if focusEvent is not None:
            if focusEvent[0] not in consideredEvents:
                continue
        for eventGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
            setOfResourcesAssignedToRole = set()
            for event in set(instance.Events.EventGroups[eventGroup].Events):
                if event in eventToSolutionEventsDict.keys():
                    for solutionevent in eventToSolutionEventsDict[event]:
                        if XHSTTConstraintConstants.CONSIDER_UNASSIGNED_RESOURCES in constraint and constraint[
                            XHSTTConstraintConstants.CONSIDER_UNASSIGNED_RESOURCES] and constraint[XHSTTFileConstants.ROLE] in solutionevent[XHSTTFileConstants.RESOURCES].keys():
                            setOfResourcesAssignedToRole.add(solutionevent[XHSTTFileConstants.RESOURCES][constraint[XHSTTFileConstants.ROLE]])
                            if focusEvent is None and not excludeDeviationInfo:
                                constraint[XHSTTConstraintConstants.DEVIATION_EVENTS].append(solutionevent)
                        elif (XHSTTConstraintConstants.CONSIDER_UNASSIGNED_RESOURCES not in constraint or not constraint[
                            XHSTTConstraintConstants.CONSIDER_UNASSIGNED_RESOURCES]) and constraint[XHSTTFileConstants.ROLE] in solutionevent[XHSTTFileConstants.RESOURCES].keys() and \
                            solutionevent[XHSTTFileConstants.RESOURCES][constraint[XHSTTFileConstants.ROLE]] != ILPConstants.DUMMY_RESOURCE:
                            setOfResourcesAssignedToRole.add(
                                solutionevent[XHSTTFileConstants.RESOURCES][constraint[XHSTTFileConstants.ROLE]])
                            if focusEvent is None and not excludeDeviationInfo:
                                constraint[XHSTTConstraintConstants.DEVIATION_EVENTS].append(solutionevent)
            deviation = max(len(setOfResourcesAssignedToRole) - 1, 0)
            if deviation > 0 and outputObjective:
                print(f"Avoid split assignments (Required: {str(constraint[XHSTTConstraintConstants.REQUIRED])}) violation for event {eventGroup} has resources {setOfResourcesAssignedToRole} for role {constraint[XHSTTFileConstants.ROLE]}")
            constraint[XHSTTConstraintConstants.DEVIATION_AMOUNT] += deviation
            
            added_objective_value = _get_added_objective_value(constraint, deviation, useWeightCopy)
            objective_value += added_objective_value
            constraint[XHSTTConstraintConstants.OBJECTIVE_VALUE] += added_objective_value


    return objective_value

def _get_objective_value_spread_events_constraints(instance, eventToSolutionEventsDict, useWeightCopy, focusEvent=None, outputObjective=False, constraints=None, excludeDeviationInfo=False) -> float:
    objective_value = 0.0
    if constraints is None:
        constraints = instance.Constraints[XHSTTConstraintConstants.SPREAD_EVENTS_CONSTRAINT]
    for constraint in constraints:
        constraint[XHSTTConstraintConstants.IS_FULFILLED] = True
        if focusEvent is None:
            constraint[XHSTTConstraintConstants.DEVIATION_EVENTS] = list()
        constraint[XHSTTConstraintConstants.DEVIATION_AMOUNT] = 0
        
        constraint[XHSTTConstraintConstants.OBJECTIVE_VALUE] = 0
        for eventGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
            if focusEvent is not None:
                if focusEvent[0] not in instance.Events.EventGroups[eventGroup].Events:
                    continue
            deviation = 0
            for timeGroup in constraint[XHSTTFileConstants.TIME_GROUPS]:
                solutionEventsInTimeGroup = set()
                solutionEventsNotInTimeGroup = set()
                for event in instance.Events.EventGroups[eventGroup].Events:
                    if event in eventToSolutionEventsDict.keys():
                        if timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT] in instance.Times.TimeGroups.keys():
                            solutionEventsInTimeGroup.update(set([solutionevent[XHSTTFileConstants.ID] for solutionevent in eventToSolutionEventsDict[event]
                                                         if solutionevent[XHSTTFileConstants.TIME] in instance.Times.TimeGroups[timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]].Times]))
                            solutionEventsNotInTimeGroup.update(
                                set([solutionevent[XHSTTFileConstants.ID] for solutionevent in eventToSolutionEventsDict[event]
                                     if solutionevent[XHSTTFileConstants.TIME] not in instance.Times.TimeGroups[
                                         timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]].Times]))
                        else:
                            solutionEventsInTimeGroup.update(
                                set([solutionevent[XHSTTFileConstants.ID] for solutionevent in eventToSolutionEventsDict[event]
                                     if solutionevent[XHSTTFileConstants.TIME] in instance.Times.Days[timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]].Times]))
                            solutionEventsNotInTimeGroup.update(
                                set([solutionevent[XHSTTFileConstants.ID] for solutionevent in eventToSolutionEventsDict[event]
                                     if solutionevent[XHSTTFileConstants.TIME] not in instance.Times.Days[
                                         timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]].Times]))
                if focusEvent is None and not excludeDeviationInfo:
                    for event in instance.Events.EventGroups[eventGroup].Events:
                        if event in eventToSolutionEventsDict.keys():
                            if len(solutionEventsInTimeGroup) < int(timeGroup[XHSTTConstraintConstants.MINIMUM]):
                                constraint[XHSTTConstraintConstants.DEVIATION_EVENTS] += [solutionevent for solutionevent in eventToSolutionEventsDict[event] if solutionevent[XHSTTFileConstants.ID] in solutionEventsNotInTimeGroup]
                            elif len(solutionEventsInTimeGroup) > int(timeGroup[XHSTTConstraintConstants.MAXIMUM]):
                                constraint[XHSTTConstraintConstants.DEVIATION_EVENTS] += [solutionevent for solutionevent in eventToSolutionEventsDict[event] if solutionevent[XHSTTFileConstants.ID] in solutionEventsInTimeGroup]
                deviation += (max(int(timeGroup[XHSTTConstraintConstants.MINIMUM]) - len(solutionEventsInTimeGroup), 0) +
                     max(len(solutionEventsInTimeGroup) - int(timeGroup[XHSTTConstraintConstants.MAXIMUM]), 0))
                if (max(int(timeGroup[XHSTTConstraintConstants.MINIMUM]) - len(solutionEventsInTimeGroup), 0) +
                     max(len(solutionEventsInTimeGroup) - int(timeGroup[XHSTTConstraintConstants.MAXIMUM]), 0)) > 0 and outputObjective:
                    print(f"Spread Events Violation (Required: {str(constraint[XHSTTConstraintConstants.REQUIRED])}): Time Group: {timeGroup} Event Group: {eventGroup} Range: {(int(timeGroup[XHSTTConstraintConstants.MINIMUM]), int(timeGroup[XHSTTConstraintConstants.MAXIMUM]))} Number of Events in Time Group: {len(solutionEventsInTimeGroup)} Events in time group: {solutionEventsInTimeGroup}")
            constraint[XHSTTConstraintConstants.DEVIATION_AMOUNT] += deviation
            
            added_objective_value = _get_added_objective_value(constraint, deviation, useWeightCopy)
            objective_value += added_objective_value
            constraint[XHSTTConstraintConstants.OBJECTIVE_VALUE] += added_objective_value


    return objective_value

def _get_objective_value_link_events_constraints(instance, eventToSolutionEventsDict, useWeightCopy, outputObjective=False, constraints=None, excludeDeviationInfo=False) -> float:
    objective_value = 0.0
    listOfTimes = list(instance.Times.IndividualTimes.keys())
    if constraints is None:
        constraints = instance.Constraints[XHSTTConstraintConstants.LINK_EVENTS_CONSTRAINT]
    for constraint in constraints:
        constraint[XHSTTConstraintConstants.IS_FULFILLED] = True
        constraint[XHSTTConstraintConstants.DEVIATION_EVENTS] = list()
        constraint[XHSTTConstraintConstants.DEVIATION_AMOUNT] = 0
        
        constraint[XHSTTConstraintConstants.OBJECTIVE_VALUE] = 0
        for eventGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
            deviation = 0
            timesInWhichAnyEventIsActive = set()
            timesInWhichAllEventsAreActive = set()
            timesInWhichEventIsActive = dict()
            for event in instance.Events.EventGroups[eventGroup].Events:
                if event in eventToSolutionEventsDict.keys():
                    for solutionevent in eventToSolutionEventsDict[event]:
                        if solutionevent[XHSTTFileConstants.TIME] == ILPConstants.DUMMY_TIME:
                            continue
                        indexOfSolutionEventStartTime = listOfTimes.index(solutionevent[XHSTTFileConstants.TIME])
                        timesInWhichSolutionEventIsActive = listOfTimes[indexOfSolutionEventStartTime:indexOfSolutionEventStartTime + int(solutionevent[XHSTTFileConstants.DURATION])]
                        timesInWhichEventIsActive.setdefault(event, set()).update(set(timesInWhichSolutionEventIsActive))
                        timesInWhichAnyEventIsActive.update(set(timesInWhichSolutionEventIsActive))
            timesInWhichAllEventsAreActive = copy.deepcopy(timesInWhichAnyEventIsActive)
            for event in timesInWhichEventIsActive.keys():
                timesInWhichAllEventsAreActive = timesInWhichAllEventsAreActive.intersection(timesInWhichEventIsActive[event])
            for event in instance.Events.EventGroups[eventGroup].Events:
                if event in eventToSolutionEventsDict and not excludeDeviationInfo:
                    constraint[XHSTTConstraintConstants.DEVIATION_EVENTS] += [solutionevent for solutionevent in eventToSolutionEventsDict[event]]
            deviation = len(timesInWhichAnyEventIsActive) - len(timesInWhichAllEventsAreActive)
            if outputObjective and deviation > 0:
                print(f"Link event constraint (Required: {str(constraint[XHSTTConstraintConstants.REQUIRED])}) violated for event group {eventGroup}, deviation: {deviation}")
                print(timesInWhichAnyEventIsActive)
                print(timesInWhichAllEventsAreActive)
            constraint[XHSTTConstraintConstants.DEVIATION_AMOUNT] += deviation
            
            added_objective_value = _get_added_objective_value(constraint, deviation, useWeightCopy)
            objective_value += added_objective_value
            constraint[XHSTTConstraintConstants.OBJECTIVE_VALUE] += added_objective_value


    return objective_value

def _get_objective_value_order_events_constraints(instance, eventToSolutionEventsDict, useWeightCopy, outputObjective=False, constraints=None, excludeDeviationInfo=False) -> float:
    objective_value = 0.0
    listOfTimes = list(instance.Times.IndividualTimes.keys())
    if constraints is None:
        constraints = instance.Constraints[XHSTTConstraintConstants.ORDER_EVENTS_CONSTRAINT]
    for constraint in constraints:
        constraint[XHSTTConstraintConstants.IS_FULFILLED] = True
        constraint[XHSTTConstraintConstants.DEVIATION_EVENTS] = list()
        constraint[XHSTTConstraintConstants.DEVIATION_AMOUNT] = 0

        constraint[XHSTTConstraintConstants.OBJECTIVE_VALUE] = 0
        for eventPair in constraint[XHSTTConstraintConstants.APPLIES_TO]["EventPairs"]:
            firstEventID = eventPair["FirstEvent"]
            secondEventID = eventPair["SecondEvent"]
            minSep = eventPair.get("MinSeparation", 0)
            maxSep = eventPair.get("MaxSeparation", len(instance.Times.IndividualTimes.keys()))
            deviation = 0
            lastTimeFirstEvent = 0
            firstTimeLastEvent = 0
            zeroDeviation = False
            if firstEventID in eventToSolutionEventsDict.keys():
                totalSubeventDuration = 0
                for solutionevent in eventToSolutionEventsDict[firstEventID]:
                    duration = int(solutionevent[XHSTTFileConstants.DURATION])
                    time = solutionevent[XHSTTFileConstants.TIME]
                    totalSubeventDuration += duration
                    if time == ILPConstants.DUMMY_TIME:
                        zeroDeviation = True
                    else:
                        timeIndex = listOfTimes.index(solutionevent[XHSTTFileConstants.TIME])
                        lastTimeFirstEvent = max(lastTimeFirstEvent, timeIndex + duration)
                if totalSubeventDuration < instance.Events.IndividualEvents[firstEventID].Durtation:
                    zeroDeviation = True
            else:
                zeroDeviation = True

            if secondEventID in eventToSolutionEventsDict.keys():
                totalSubeventDuration = 0
                for solutionevent in eventToSolutionEventsDict[secondEventID]:
                    duration = int(solutionevent[XHSTTFileConstants.DURATION])
                    time = solutionevent[XHSTTFileConstants.TIME]
                    totalSubeventDuration += duration
                    if time == ILPConstants.DUMMY_TIME:
                        zeroDeviation = True
                    else:
                        timeIndex = listOfTimes.index(solutionevent[XHSTTFileConstants.TIME])
                        firstTimeLastEvent = min(firstTimeLastEvent, timeIndex)
                if totalSubeventDuration < instance.Events.IndividualEvents[secondEventID].Durtation:
                    zeroDeviation = True
            else:
                zeroDeviation = True

            for event in firstEventID, secondEventID:
                if event in eventToSolutionEventsDict and not excludeDeviationInfo:
                    constraint[XHSTTConstraintConstants.DEVIATION_EVENTS] += [solutionevent for solutionevent in
                                                                              eventToSolutionEventsDict[event]]
            if zeroDeviation:
                deviation = 0
                separation = 0
            else:
                separation = lastTimeFirstEvent - firstTimeLastEvent
                deviation = max(separation - maxSep, minSep - separation, 0)
            if outputObjective and deviation > 0:
                print(
                    f"Order event constraint (Required: {str(constraint[XHSTTConstraintConstants.REQUIRED])}) violated for event pair {eventPair}, deviation: {deviation}, lastTimeFirstEvent: {lastTimeFirstEvent}, firstTimeLastEvent: {firstTimeLastEvent}, separation {separation}, min/max separation {minSep}/{maxSep}")
            constraint[XHSTTConstraintConstants.DEVIATION_AMOUNT] += deviation

            added_objective_value = _get_added_objective_value(constraint, deviation, useWeightCopy)
            objective_value += added_objective_value
            constraint[XHSTTConstraintConstants.OBJECTIVE_VALUE] += added_objective_value

    return objective_value
def _get_objective_value_avoid_clashes_constraints(instance, resourceToSolutionEventsByTimeDict, useWeightCopy, focusEventResources=None, outputObjective=False, constraints=None, excludeDeviationInfo=False, affectedTimes: set=None) -> float:
    objective_value = 0.0
    clashesByResourceDict = dict()
    outputObjective = False
    if constraints is None:
        constraints = instance.Constraints[XHSTTConstraintConstants.AVOID_CLASHES_CONSTRAINT]

    for constraint in constraints:
        constraint[XHSTTConstraintConstants.IS_FULFILLED] = True
        if True:
            constraint[XHSTTConstraintConstants.DEVIATION_EVENTS] = list()
        constraint[XHSTTConstraintConstants.DEVIATION_AMOUNT] = 0
        
        constraint[XHSTTConstraintConstants.OBJECTIVE_VALUE] = 0
        constraint.setdefault(XHSTTConstraintConstants.DEVIATION_MAP, dict())
        if affectedTimes is not None:
            constraintResources = {(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCES][0], None)}
        else:
            constraintResources = set([(resource, None) for resource in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCES]])
            for resourceGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCE_GROUPS]:
                for resourceType in instance.Resources.ResourceGroupsByType.keys():
                    if resourceGroup in instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups:
                        constraintResources.update(
                            set((resource, resourceGroup) for resource in
                                instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups[
                                    resourceGroup].Resources))
            if focusEventResources is not None:
                constraintResourceSet = set([resource[0] for resource in constraintResources])
                if constraintResourceSet.isdisjoint(set(focusEventResources)):
                    continue
                else:
                    intersection = list(constraintResourceSet.intersection(set(focusEventResources)))
                    constraintResources = [resource for resource in constraintResources if resource[0] in intersection]
        for resource in constraintResources:
            constraint[XHSTTConstraintConstants.DEVIATION_MAP].setdefault(resource, dict())
            deviation = 0
            for time in resourceToSolutionEventsByTimeDict[resource[0]].keys():
                if affectedTimes is not None and time not in affectedTimes:
                    deviation += constraint[XHSTTConstraintConstants.DEVIATION_MAP][resource][time]
                    if outputObjective and len(resourceToSolutionEventsByTimeDict[resource[0]][time]) - 1 > 0:
                        print(f"Cached {constraint[XHSTTFileConstants.ID]}: Time: {time}, Resource: {resource}, Deviation: {constraint[XHSTTConstraintConstants.DEVIATION_MAP][resource][time]}")
                        for event in resourceToSolutionEventsByTimeDict[resource[0]][time]:
                            print(f"Event info of clash event: {event}")
                    continue
                if not excludeDeviationInfo:
                    if len(resourceToSolutionEventsByTimeDict[resource[0]][time]) > 1:
                        constraint[XHSTTConstraintConstants.DEVIATION_EVENTS] += resourceToSolutionEventsByTimeDict[resource[0]][time]
                    if len(resourceToSolutionEventsByTimeDict[resource[0]][time]) - 1 > 0:
                        clashesByResourceDict.setdefault(resource, 0)
                        clashesByResourceDict[resource] += len(resourceToSolutionEventsByTimeDict[resource[0]][time]) - 1
                deviation_change = max(0, len(resourceToSolutionEventsByTimeDict[resource[0]][time]) - 1)
                deviation += deviation_change
                constraint[XHSTTConstraintConstants.DEVIATION_MAP][resource][time] = deviation_change
                if outputObjective and len(resourceToSolutionEventsByTimeDict[resource[0]][time]) - 1 > 0:
                    print(f"{constraint[XHSTTFileConstants.ID]}: Time: {time}, Resource: {resource}, Deviation: {deviation_change}")
                    for event in resourceToSolutionEventsByTimeDict[resource[0]][time]:
                        print(f"Event info of clash event: {event}")
            constraint[XHSTTConstraintConstants.DEVIATION_AMOUNT] += deviation
            
            added_objective_value = _get_added_objective_value(constraint, deviation, useWeightCopy)
            objective_value += added_objective_value
            constraint[XHSTTConstraintConstants.OBJECTIVE_VALUE] += added_objective_value
    return objective_value

def _get_objective_value_avoid_unavailable_times_constraints(instance, resourceToSolutionEventsByTimeDict, useWeightCopy, focusEventResources=None, outputObjective=False, constraints=None, excludeDeviationInfo=False, affectedTimes: set = None) -> float:
    objective_value = 0.0

    if constraints is None:
        constraints = instance.Constraints[XHSTTConstraintConstants.AVOID_UNAVAILABLE_TIMES_CONSTRAINT]
    for constraint in constraints:
        constraint[XHSTTConstraintConstants.IS_FULFILLED] = True
        if focusEventResources is None:
            constraint[XHSTTConstraintConstants.DEVIATION_EVENTS] = list()
        constraint.setdefault(XHSTTConstraintConstants.DEVIATION_MAP, dict())
        if affectedTimes is not None and "allTimes" in constraint[XHSTTConstraintConstants.DEVIATION_MAP] and len(constraint[XHSTTConstraintConstants.DEVIATION_MAP]["allTimes"].intersection(affectedTimes)) == 0:
            return constraint[XHSTTConstraintConstants.OBJECTIVE_VALUE]
        constraint[XHSTTConstraintConstants.DEVIATION_AMOUNT] = 0
        constraint[XHSTTConstraintConstants.OBJECTIVE_VALUE] = 0
        constraintResources = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCES])
        for resourceGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCE_GROUPS]:
            for resourceType in instance.Resources.ResourceGroupsByType.keys():
                if resourceGroup in instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups:
                    constraintResources.update(
                        set(instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups[
                                resourceGroup].Resources))
        if focusEventResources is not None:
            constraintResourceSet = set(constraintResources)
            if constraintResourceSet.isdisjoint(set(focusEventResources)):
                continue
            else:
                constraintResources = list(constraintResourceSet.intersection(set(focusEventResources)))
        if "allTimes" not in constraint[XHSTTConstraintConstants.DEVIATION_MAP]:
            if XHSTTFileConstants.TIMES in constraint.keys():
                constraintTimes = set(constraint[XHSTTFileConstants.TIMES])
                for timeGroup in constraint[XHSTTFileConstants.TIME_GROUPS]:
                    if timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT] in instance.Times.TimeGroups.keys():
                        constraintTimes.update(set(instance.Times.TimeGroups[timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]].Times))
                    elif timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT] in instance.Times.Days.keys():
                        constraintTimes.update(set(instance.Times.Days[timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]].Times))
            else:
                constraintTimes = set()
            constraint[XHSTTConstraintConstants.DEVIATION_MAP]["allTimes"] = constraintTimes
        constraintTimes = constraint[XHSTTConstraintConstants.DEVIATION_MAP]["allTimes"]

        for resource in constraintResources:
            undesireableTimesAttended = set()
            for time in resourceToSolutionEventsByTimeDict[resource].keys():
                if len(resourceToSolutionEventsByTimeDict[resource][time]) > 0 and time in constraintTimes:
                    if focusEventResources is None and not excludeDeviationInfo:
                        constraint[XHSTTConstraintConstants.DEVIATION_EVENTS] += resourceToSolutionEventsByTimeDict[resource][time]
                    undesireableTimesAttended.add(time)
            deviation = len(undesireableTimesAttended)
            if deviation > 0 and outputObjective:
                print(f"Avoid Unavailable Times (Required: {str(constraint[XHSTTConstraintConstants.REQUIRED])}) Violation for resource {resource} that has events during the following unavailable times {undesireableTimesAttended} for a total deviation of {deviation}")
            constraint[XHSTTConstraintConstants.DEVIATION_AMOUNT] += deviation
            
            added_objective_value = _get_added_objective_value(constraint, deviation, useWeightCopy)
            objective_value += added_objective_value
            constraint[XHSTTConstraintConstants.OBJECTIVE_VALUE] += added_objective_value


    return objective_value

def _get_objective_value_limit_idle_times_constraints(instance, resourceToSolutionEventsByTimeDict, resourceToSolutionEventsDict, useWeightCopy, focusEventResources=None, outputObjective=False, constraints=None, excludeDeviationInfo=False, affectedTimes: set=None) -> float:
    objective_value = 0.0
    if constraints is None:
        constraints = instance.Constraints[XHSTTConstraintConstants.LIMIT_IDLE_TIMES_CONSTRAINT]
    for constraint in constraints:
        pass
        constraint[XHSTTConstraintConstants.IS_FULFILLED] = True
        if focusEventResources is None and not excludeDeviationInfo:
            constraint[XHSTTConstraintConstants.DEVIATION_EVENTS] = list()
        constraint.setdefault(XHSTTConstraintConstants.DEVIATION_MAP, dict())
        if affectedTimes is not None:
            if "allTimes" in constraint[XHSTTConstraintConstants.DEVIATION_MAP] and len(constraint[XHSTTConstraintConstants.DEVIATION_MAP]["allTimes"].intersection(affectedTimes)) == 0:
                return constraint[XHSTTConstraintConstants.OBJECTIVE_VALUE]
            constraintResources = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCES])
        else:
            constraintResources = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCES])
            for resourceGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCE_GROUPS]:
                for resourceType in instance.Resources.ResourceGroupsByType.keys():
                    if resourceGroup in instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups:
                        constraintResources.update(
                            set(instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups[
                                    resourceGroup].Resources))
        constraint[XHSTTConstraintConstants.DEVIATION_AMOUNT] = 0
        constraint[XHSTTConstraintConstants.OBJECTIVE_VALUE] = 0
        if focusEventResources is not None and not excludeDeviationInfo:
            constraintResourceSet = set(constraintResources)
            if constraintResourceSet.isdisjoint(set(focusEventResources)):
                continue
            else:
                constraintResources = list(constraintResourceSet.intersection(set(focusEventResources)))
        timeGroups = list()
        if "timeGroupHelp" not in constraint[XHSTTConstraintConstants.DEVIATION_MAP]:
            constraint[XHSTTConstraintConstants.DEVIATION_MAP]["allTimes"] = set()
            for originalTimeGroupDict in constraint[XHSTTFileConstants.TIME_GROUPS]:
                timeGroup = originalTimeGroupDict[XHSTTFileConstants.REFERENCE_WITH_AT]
                if timeGroup in instance.Times.TimeGroups.keys():
                    timeGroups.append((instance.Times.TimeGroups[timeGroup].Times, timeGroup))
                    constraint[XHSTTConstraintConstants.DEVIATION_MAP]["allTimes"].update(instance.Times.TimeGroups[timeGroup].Times)
                else:
                    timeGroups.append((instance.Times.Days[timeGroup].Times, timeGroup))
                    constraint[XHSTTConstraintConstants.DEVIATION_MAP]["allTimes"].update(
                        instance.Times.Days[timeGroup].Times)
            constraint[XHSTTConstraintConstants.DEVIATION_MAP]["timeGroupHelp"] = timeGroups
        timeGroups = constraint[XHSTTConstraintConstants.DEVIATION_MAP]["timeGroupHelp"]
        for resource in constraintResources:
            constraint[XHSTTConstraintConstants.DEVIATION_MAP].setdefault(
                resource + constraint[XHSTTConstraintConstants.NAME], dict())
            numberOfIdleTimes = 0
            for timeGroupTimes, timeGroup in timeGroups:
                constraint[XHSTTConstraintConstants.DEVIATION_MAP][
                    resource + constraint[XHSTTConstraintConstants.NAME]].setdefault(timeGroup, 0)
                if affectedTimes is not None and set(timeGroupTimes).isdisjoint(affectedTimes):
                    numberOfIdleTimes += constraint[XHSTTConstraintConstants.DEVIATION_MAP][
                        resource + constraint[XHSTTConstraintConstants.NAME]][timeGroup]
                    continue
                firstTimeGroupFound = False
                firstTimeGroupIndex = 1
                lastTimeGroupIndex = 0
                numberOfBusyTimes = 0
                timeIndex = 0
                for time in timeGroupTimes:
                    if time in resourceToSolutionEventsByTimeDict.get(resource, {}) and len(resourceToSolutionEventsByTimeDict[resource][time]) >= 1:
                        if not firstTimeGroupFound:
                            firstTimeGroupFound = True
                            firstTimeGroupIndex = timeIndex
                        lastTimeGroupIndex = timeIndex
                        numberOfBusyTimes += 1
                    timeIndex += 1
                addedIdleTimes = (lastTimeGroupIndex - firstTimeGroupIndex + 1) - numberOfBusyTimes
                numberOfIdleTimes += addedIdleTimes
                constraint[XHSTTConstraintConstants.DEVIATION_MAP][resource + constraint[XHSTTConstraintConstants.NAME]][timeGroup] = addedIdleTimes

            if focusEventResources is None and not excludeDeviationInfo:
                if numberOfIdleTimes < int(constraint[XHSTTConstraintConstants.MINIMUM]) or numberOfIdleTimes > int(constraint[XHSTTConstraintConstants.MAXIMUM]):
                    if resource in resourceToSolutionEventsDict.keys():
                        for solutionevent in resourceToSolutionEventsDict[resource]:
                            constraint[XHSTTConstraintConstants.DEVIATION_EVENTS].append(solutionevent)
            deviation = max(0, int(constraint[XHSTTConstraintConstants.MINIMUM]) - numberOfIdleTimes) + max(0, numberOfIdleTimes - int(constraint[XHSTTConstraintConstants.MAXIMUM]))
            if deviation > 0 and outputObjective:
                print(f"Idle Times Violation (Required: {str(constraint[XHSTTConstraintConstants.REQUIRED])}) for resource {resource}. Allowed Range: {(int(constraint[XHSTTConstraintConstants.MINIMUM]), int(constraint[XHSTTConstraintConstants.MAXIMUM]))} Number of Idle Times: {numberOfIdleTimes} Considered Time Groups: {constraint[XHSTTFileConstants.TIME_GROUPS]}")
            constraint[XHSTTConstraintConstants.DEVIATION_AMOUNT] += deviation
            
            added_objective_value = _get_added_objective_value(constraint, deviation, useWeightCopy)
            objective_value += added_objective_value
            constraint[XHSTTConstraintConstants.OBJECTIVE_VALUE] += added_objective_value
        if focusEventResources is None and not excludeDeviationInfo:
            deviationEventsCopy = copy.deepcopy(constraint[XHSTTConstraintConstants.DEVIATION_EVENTS])
            constraint[XHSTTConstraintConstants.DEVIATION_EVENTS] = list()
            [constraint[XHSTTConstraintConstants.DEVIATION_EVENTS].append(solutionevent) for solutionevent in deviationEventsCopy if solutionevent not in constraint[XHSTTConstraintConstants.DEVIATION_EVENTS]]


    return objective_value
def _get_objective_value_cluster_busy_times_constraints(instance, resourceToSolutionEventsByTimeDict, resourceToSolutionEventsDict, useWeightCopy, focusEventResources=None, outputObjective=False, constraints=None, excludeDeviationInfo=False) -> float:
    objective_value = 0.0

    if constraints is None:
        constraints = instance.Constraints[XHSTTConstraintConstants.CLUSTER_BUSY_TIMES_CONSTRAINT]
    for constraint in constraints:
        constraint[XHSTTConstraintConstants.IS_FULFILLED] = True
        if focusEventResources is None:
            constraint[XHSTTConstraintConstants.DEVIATION_EVENTS] = list()
        constraint[XHSTTConstraintConstants.DEVIATION_AMOUNT] = 0
        
        constraint[XHSTTConstraintConstants.OBJECTIVE_VALUE] = 0
        constraintResources = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCES])
        for resourceGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCE_GROUPS]:
            for resourceType in instance.Resources.ResourceGroupsByType.keys():
                if resourceGroup in instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups:
                    constraintResources.update(
                        set(instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups[
                                resourceGroup].Resources))
        if focusEventResources is not None:
            constraintResourceSet = set(constraintResources)
            if constraintResourceSet.isdisjoint(set(focusEventResources)):
                continue
            else:
                constraintResources = list(constraintResourceSet.intersection(set(focusEventResources)))
        for resource in constraintResources:
            activeTimeGroups = 0
            for timeGroupDict in constraint[XHSTTFileConstants.TIME_GROUPS]:
                timeGroup = timeGroupDict[XHSTTFileConstants.REFERENCE_WITH_AT]
                timeGroupFound = False
                if timeGroup in instance.Times.TimeGroups.keys():
                    for time in instance.Times.TimeGroups[timeGroup].Times:
                        if time in resourceToSolutionEventsByTimeDict[resource].keys() and len(
                                resourceToSolutionEventsByTimeDict[resource][time]) >= 1:
                            timeGroupFound = True
                            break
                else:
                    for time in instance.Times.Days[timeGroup].Times:
                        if time in resourceToSolutionEventsByTimeDict[resource].keys() and len(
                                resourceToSolutionEventsByTimeDict[resource][time]) >= 1:
                            timeGroupFound = True
                            break
                if timeGroupFound:
                    activeTimeGroups += 1
            if focusEventResources is None and not excludeDeviationInfo:
                if activeTimeGroups < int(constraint[XHSTTConstraintConstants.MINIMUM]) or activeTimeGroups > int(constraint[XHSTTConstraintConstants.MAXIMUM]):
                    if resource in resourceToSolutionEventsDict.keys():
                        for solutionevent in resourceToSolutionEventsDict[resource]:
                            constraint[XHSTTConstraintConstants.DEVIATION_EVENTS].append(solutionevent)
            deviation = max(0, int(constraint[XHSTTConstraintConstants.MINIMUM]) - activeTimeGroups) + max(0, activeTimeGroups - int(constraint[XHSTTConstraintConstants.MAXIMUM]))
            if outputObjective and deviation > 0:
                print(f"Cluster Busy Times (Required: {str(constraint[XHSTTConstraintConstants.REQUIRED])}) Resource {resource}: Minimum: {constraint['Minimum']}, Maximum: {constraint['Maximum']}, Active Time Groups: {activeTimeGroups}")
            constraint[XHSTTConstraintConstants.DEVIATION_AMOUNT] += deviation
            
            added_objective_value = _get_added_objective_value(constraint, deviation, useWeightCopy)
            objective_value += added_objective_value
            constraint[XHSTTConstraintConstants.OBJECTIVE_VALUE] += added_objective_value
        if focusEventResources is None and not excludeDeviationInfo:
            deviationEventsCopy = copy.deepcopy(constraint[XHSTTConstraintConstants.DEVIATION_EVENTS])
            constraint[XHSTTConstraintConstants.DEVIATION_EVENTS] = list()
            [constraint[XHSTTConstraintConstants.DEVIATION_EVENTS].append(solutionevent) for solutionevent in
             deviationEventsCopy if solutionevent not in constraint[XHSTTConstraintConstants.DEVIATION_EVENTS]]

    return objective_value

def _get_objective_value_limit_busy_times_constraints(instance, resourceToSolutionEventsByTimeDict, resourceToSolutionEventsDict, useWeightCopy, focusEventResources=None, outputObjective=False, constraints=None, excludeDeviationInfo=False, affectedTimes: set=None) -> float:
    objective_value = 0.0
    if constraints is None:
        constraints = instance.Constraints[XHSTTConstraintConstants.LIMIT_BUSY_TIMES_CONSTRAINT]
    for constraint in constraints:
        constraint[XHSTTConstraintConstants.IS_FULFILLED] = True
        if focusEventResources is None and not excludeDeviationInfo:
            constraint[XHSTTConstraintConstants.DEVIATION_EVENTS] = list()
        constraint.setdefault(XHSTTConstraintConstants.DEVIATION_MAP, dict())
        if affectedTimes is not None:
            if "allTimes" in constraint[XHSTTConstraintConstants.DEVIATION_MAP] and len(
                    constraint[XHSTTConstraintConstants.DEVIATION_MAP]["allTimes"].intersection(affectedTimes)) == 0:
                return constraint[XHSTTConstraintConstants.OBJECTIVE_VALUE]
            constraintResources = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCES])
        else:
            constraintResources = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCES])
            for resourceGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCE_GROUPS]:
                for resourceType in instance.Resources.ResourceGroupsByType.keys():
                    if resourceGroup in instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups:
                        constraintResources.update(
                            set(instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups[
                                    resourceGroup].Resources))

        constraint[XHSTTConstraintConstants.DEVIATION_AMOUNT] = 0
        constraint[XHSTTConstraintConstants.OBJECTIVE_VALUE] = 0
        if focusEventResources is not None and not excludeDeviationInfo:
            constraintResourceSet = set(constraintResources)
            if constraintResourceSet.isdisjoint(set(focusEventResources)):
                continue
            else:
                constraintResources = list(constraintResourceSet.intersection(set(focusEventResources)))
        timeGroups = list()
        if "timeGroupHelp" not in constraint[XHSTTConstraintConstants.DEVIATION_MAP]:
            constraint[XHSTTConstraintConstants.DEVIATION_MAP]["allTimes"] = set()
            for originalTimeGroupDict in constraint[XHSTTFileConstants.TIME_GROUPS]:
                timeGroup = originalTimeGroupDict[XHSTTFileConstants.REFERENCE_WITH_AT]
                if timeGroup in instance.Times.TimeGroups.keys():
                    timeGroups.append((instance.Times.TimeGroups[timeGroup].Times, timeGroup))
                    constraint[XHSTTConstraintConstants.DEVIATION_MAP]["allTimes"].update(
                        instance.Times.TimeGroups[timeGroup].Times)
                else:
                    timeGroups.append((instance.Times.Days[timeGroup].Times, timeGroup))
                    constraint[XHSTTConstraintConstants.DEVIATION_MAP]["allTimes"].update(
                        instance.Times.Days[timeGroup].Times)
            constraint[XHSTTConstraintConstants.DEVIATION_MAP]["timeGroupHelp"] = timeGroups
        timeGroups = constraint[XHSTTConstraintConstants.DEVIATION_MAP]["timeGroupHelp"]
        for resource in constraintResources:
            constraint[XHSTTConstraintConstants.DEVIATION_MAP].setdefault(resource + constraint[XHSTTConstraintConstants.NAME], dict())
            deviation = 0
            for timeGroupTimes, timeGroup in timeGroups:

                constraint[XHSTTConstraintConstants.DEVIATION_MAP][resource + constraint[XHSTTConstraintConstants.NAME]].setdefault(timeGroup, 0)
                if affectedTimes is not None and set(timeGroupTimes).isdisjoint(affectedTimes):
                    deviation += constraint[XHSTTConstraintConstants.DEVIATION_MAP][resource + constraint[XHSTTConstraintConstants.NAME]][timeGroup]
                    continue
                numberOfBusyTimes = 0
                if focusEventResources is None and not excludeDeviationInfo:
                    solutionEventsOfResourceInTimeGroup = list()
                usedTimes = set()
                for time in timeGroupTimes:
                    if time in resourceToSolutionEventsByTimeDict.get(resource, {}) and len(resourceToSolutionEventsByTimeDict[resource][time]) >= 1:
                        numberOfBusyTimes += 1
                        usedTimes.add(time)
                        if focusEventResources is None and not excludeDeviationInfo:
                            solutionEventsOfResourceInTimeGroup += resourceToSolutionEventsByTimeDict[resource][time]
                if numberOfBusyTimes != 0:
                    if focusEventResources is None and not excludeDeviationInfo:
                        if numberOfBusyTimes < int(constraint[XHSTTConstraintConstants.MINIMUM]):
                            constraint[XHSTTConstraintConstants.DEVIATION_EVENTS] += [solutionevent for solutionevent in resourceToSolutionEventsDict[resource] if solutionevent not in solutionEventsOfResourceInTimeGroup]
                        elif numberOfBusyTimes > int(constraint[XHSTTConstraintConstants.MAXIMUM]):
                            constraint[XHSTTConstraintConstants.DEVIATION_EVENTS] += solutionEventsOfResourceInTimeGroup
                    current_deviation = max(0, int(constraint[XHSTTConstraintConstants.MINIMUM]) - numberOfBusyTimes) + max(0, numberOfBusyTimes - int(constraint[XHSTTConstraintConstants.MAXIMUM]))
                    deviation += current_deviation
                    constraint[XHSTTConstraintConstants.DEVIATION_MAP][resource + constraint[XHSTTConstraintConstants.NAME]][timeGroup] = current_deviation
                    if outputObjective and current_deviation > 0:
                        print(f"Limit Busy Times (Required: {str(constraint[XHSTTConstraintConstants.REQUIRED])}) Violation for Resource {resource}: Allowed Range: {(int(constraint[XHSTTConstraintConstants.MINIMUM]), int(constraint[XHSTTConstraintConstants.MAXIMUM]))} Number of Busy Times: {numberOfBusyTimes} Considered Time Group: {timeGroup} Used Times: {usedTimes}")
                else:
                    constraint[XHSTTConstraintConstants.DEVIATION_MAP][
                        resource + constraint[XHSTTConstraintConstants.NAME]][timeGroup] = 0
            constraint[XHSTTConstraintConstants.DEVIATION_AMOUNT] += deviation
            
            added_objective_value = _get_added_objective_value(constraint, deviation, useWeightCopy)
            objective_value += added_objective_value
            constraint[XHSTTConstraintConstants.OBJECTIVE_VALUE] += added_objective_value
        if focusEventResources is None and not excludeDeviationInfo:
            deviationEventsCopy = copy.deepcopy(constraint[XHSTTConstraintConstants.DEVIATION_EVENTS])
            constraint[XHSTTConstraintConstants.DEVIATION_EVENTS] = list()
            [constraint[XHSTTConstraintConstants.DEVIATION_EVENTS].append(solutionevent) for solutionevent in
             deviationEventsCopy if solutionevent not in constraint[XHSTTConstraintConstants.DEVIATION_EVENTS]]
    return objective_value
def _get_objective_value_limit_workload_constraints(instance, resourceToSolutionEventsDict, useWeightCopy, focusEventResources=None, outputObjective=False, constraints=None, excludeDeviationInfo=False) -> float:
    objective_value = 0.0
    if constraints is None:
        constraints = instance.Constraints[XHSTTConstraintConstants.LIMIT_WORKLOAD_CONSTRAINT]
    for constraint in constraints:
        constraint[XHSTTConstraintConstants.IS_FULFILLED] = True
        if focusEventResources is None:
            constraint[XHSTTConstraintConstants.DEVIATION_EVENTS] = list()
        constraint[XHSTTConstraintConstants.DEVIATION_AMOUNT] = 0
        
        constraint[XHSTTConstraintConstants.OBJECTIVE_VALUE] = 0
        constraintResources = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCES])
        for resourceGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCE_GROUPS]:
            for resourceType in instance.Resources.ResourceGroupsByType.keys():
                if resourceGroup in instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups:
                    constraintResources.update(
                        set(instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups[
                                resourceGroup].Resources))
        if focusEventResources is not None:
            constraintResourceSet = set(constraintResources)
            if constraintResourceSet.isdisjoint(set(focusEventResources)):
                continue
            else:
                constraintResources = list(constraintResourceSet.intersection(set(focusEventResources)))
        for resource in constraintResources:
            resourceWorkload = 0.0
            eventsOfResource = list()
            seenSolEvents = set()
            if resource in resourceToSolutionEventsDict.keys():
                for solutionevent in resourceToSolutionEventsDict[resource]:
                    if solutionevent[XHSTTFileConstants.ID] in seenSolEvents:
                        continue
                    seenSolEvents.add(solutionevent[XHSTTFileConstants.ID])
                    rolesOfResource = [role for role in solutionevent[XHSTTFileConstants.RESOURCES].keys() if solutionevent[XHSTTFileConstants.RESOURCES][role] == resource]
                    for eventResource in (list(instance.Events.IndividualEvents[solutionevent["Name"]].
                                                      EventResources.AssignedResources) +
                                          list(instance.Events.IndividualEvents[solutionevent["Name"]].
                                                      EventResources.UnassignedResources)):
                        if eventResource.Role in rolesOfResource:
                            if eventResource.Workload is None:
                                resourceWorkload += float(solutionevent[XHSTTFileConstants.DURATION])
                                eventsOfResource.append((solutionevent[XHSTTFileConstants.ID], float(solutionevent[XHSTTFileConstants.DURATION]), eventResource.Role, solutionevent[XHSTTFileConstants.TIME]))
                            else:
                                resourceWorkload += ((float(solutionevent[XHSTTFileConstants.DURATION]) * float(eventResource.Workload)) /
                                                     float(instance.Events.IndividualEvents[solutionevent["Name"]].Duration))
                                eventsOfResource.append((solutionevent[XHSTTFileConstants.ID],
                                                         ((float(solutionevent[XHSTTFileConstants.DURATION]) * float(
                                                             eventResource.Workload)) /
                                                          float(instance.Events.IndividualEvents[
                                                                    solutionevent["Name"]].Duration)), eventResource.Role, solutionevent[XHSTTFileConstants.TIME]))
            if focusEventResources is None and not excludeDeviationInfo:
                if resourceWorkload < float(constraint[XHSTTConstraintConstants.MINIMUM]):
                    pass
                elif resourceWorkload > float(constraint[XHSTTConstraintConstants.MINIMUM]):
                    constraint[XHSTTConstraintConstants.DEVIATION_EVENTS] += resourceToSolutionEventsDict[resource]
            EPS = 0.0001
            deviation = max(0, math.ceil((float(constraint[XHSTTConstraintConstants.MINIMUM]) - resourceWorkload) - EPS)) + max(0, math.ceil((resourceWorkload - float(constraint[XHSTTConstraintConstants.MAXIMUM])) - EPS))
            if outputObjective and deviation > 0:
                print(f"Limit Workload (Required: {str(constraint[XHSTTConstraintConstants.REQUIRED])}) ({constraint[XHSTTConstraintConstants.ID]}) for Resource {resource}: Allowed Range {(float(constraint[XHSTTConstraintConstants.MINIMUM]), float(constraint[XHSTTConstraintConstants.MAXIMUM]))}, Actual Workload: {resourceWorkload}, Deviation: {deviation}, Events: {eventsOfResource}")
            constraint[XHSTTConstraintConstants.DEVIATION_AMOUNT] += deviation
            
            added_objective_value = _get_added_objective_value(constraint, deviation, useWeightCopy)
            objective_value += added_objective_value
            constraint[XHSTTConstraintConstants.OBJECTIVE_VALUE] += added_objective_value
        if focusEventResources is None and not excludeDeviationInfo:
            deviationEventsCopy = copy.deepcopy(constraint[XHSTTConstraintConstants.DEVIATION_EVENTS])
            constraint[XHSTTConstraintConstants.DEVIATION_EVENTS] = list()
            [constraint[XHSTTConstraintConstants.DEVIATION_EVENTS].append(solutionevent) for solutionevent in
             deviationEventsCopy if solutionevent not in constraint[XHSTTConstraintConstants.DEVIATION_EVENTS]]
    return objective_value

def _get_objective_value_balance_class_size_constraints(instance, eventToSolutionEventsDict, useWeightCopy, focusEvent=None, constraints=None, excludeDeviationInfo=False, outputObjective=False, affectedEventGroups: set = None) -> float:
    objective_value = 0.0
    if XHSTTConstraintConstants.BALANCE_CLASS_SIZE_CONSTRAINT not in instance.Constraints.keys():
        return objective_value
    if constraints is None:
        constraints = instance.Constraints[XHSTTConstraintConstants.BALANCE_CLASS_SIZE_CONSTRAINT]
    for constraint in constraints:
        constraint[XHSTTConstraintConstants.IS_FULFILLED] = True
        constraint[XHSTTConstraintConstants.DEVIATION_EVENTS] = list()
        constraint[XHSTTConstraintConstants.DEVIATION_AMOUNT] = 0

        consideredEventGroups = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS])
        if affectedEventGroups is not None and len(consideredEventGroups.intersection(affectedEventGroups)) == 0:
            return constraint[XHSTTConstraintConstants.OBJECTIVE_VALUE]
        constraint[XHSTTConstraintConstants.OBJECTIVE_VALUE] = 0
        if focusEvent is not None:
            focusEventAppearsInConstraint = False
            for eventGroup in consideredEventGroups:
                if eventGroup not in instance.Events.EventGroups.keys():
                    continue
                if focusEvent[0] in instance.Events.EventGroups[eventGroup].Events:
                    focusEventAppearsInConstraint = True
            if not focusEventAppearsInConstraint:
                continue
        for eventGroup1 in consideredEventGroups:
            maximumDifference = 0
            resourcesAssignedToEventGroup1 = set()
            if eventGroup1 not in instance.Events.EventGroups.keys():
                continue
            for event1 in instance.Events.EventGroups[eventGroup1].Events:
                if event1 not in eventToSolutionEventsDict.keys():
                    continue
                for solutionevent in eventToSolutionEventsDict[event1]:
                    resourcesAssignedToEventGroup1.update({solutionevent[XHSTTFileConstants.RESOURCES][role]
                                                      for role in solutionevent[XHSTTFileConstants.RESOURCES]
                                                      if solutionevent[XHSTTFileConstants.RESOURCES][role] != ILPConstants.DUMMY_RESOURCE and
                                                           (constraint[XHSTTConstraintConstants.TYPE] is None or instance.Resources.IndividualResources[solutionevent[XHSTTFileConstants.RESOURCES][role]].Type == constraint[XHSTTConstraintConstants.TYPE])})
            resourcesInAnySolutionevents1 = len(resourcesAssignedToEventGroup1)
            for eventGroup2 in consideredEventGroups:
                resourcesAssignedToEvent2 = set()
                if eventGroup2 not in instance.Events.EventGroups.keys():
                    continue
                for event2 in instance.Events.EventGroups[eventGroup2].Events:
                    if event2 not in eventToSolutionEventsDict.keys():
                        continue
                    for solutionevent in eventToSolutionEventsDict[event2]:
                        resourcesAssignedToEvent2.update({solutionevent[XHSTTFileConstants.RESOURCES][role]
                                                          for role in solutionevent[XHSTTFileConstants.RESOURCES]
                                                          if solutionevent[XHSTTFileConstants.RESOURCES][
                                                              role] != ILPConstants.DUMMY_RESOURCE and
                                                          (constraint[XHSTTConstraintConstants.TYPE] is None or instance.Resources.IndividualResources[solutionevent[XHSTTFileConstants.RESOURCES][role]].Type == constraint[XHSTTConstraintConstants.TYPE])})
                resourcesInAnySolutionevents2 = len(resourcesAssignedToEvent2)
                maximumDifference = max(maximumDifference, abs(resourcesInAnySolutionevents2 - resourcesInAnySolutionevents1))
            if maximumDifference > int(constraint["MaximumDifference"]) and not excludeDeviationInfo:
                for eventGroup in consideredEventGroups:
                    if eventGroup not in instance.Events.EventGroups.keys():
                        continue
                    for event in instance.Events.EventGroups[eventGroup].Events:
                        if event not in eventToSolutionEventsDict.keys():
                            continue
                        constraint[XHSTTConstraintConstants.DEVIATION_EVENTS] += eventToSolutionEventsDict[event]
            deviation = max(0, maximumDifference - int(constraint["MaximumDifference"]))
            if deviation > 0 and outputObjective:
                print(f"Balance Class Size (Required: {str(constraint[XHSTTConstraintConstants.REQUIRED])}) Deviation for {eventGroup1}: {deviation} ({constraint[XHSTTFileConstants.ID]})")
            constraint[XHSTTConstraintConstants.DEVIATION_AMOUNT] += deviation
            
            added_objective_value = _get_added_objective_value(constraint, deviation, useWeightCopy)
            objective_value += added_objective_value
            constraint[XHSTTConstraintConstants.OBJECTIVE_VALUE] += added_objective_value


    return objective_value
def _get_objective_value_student_choice_constraints(instance, resourceToSolutionEventsDict, useWeightCopy, focusEventResources=None, outputObjective=False, constraints=None, excludeDeviationInfo=False, affectedEventGroups: set = None) -> float:
    objective_value = 0.0
    if XHSTTConstraintConstants.STUDENT_CHOICE_CONSTRAINT not in instance.Constraints.keys():
        return objective_value
    if constraints is None:
        constraints = instance.Constraints[XHSTTConstraintConstants.STUDENT_CHOICE_CONSTRAINT]
    for constraint in constraints:
        constraint[XHSTTConstraintConstants.IS_FULFILLED] = True
        if focusEventResources is None:
            constraint[XHSTTConstraintConstants.DEVIATION_EVENTS] = list()
        resourcesWithoutEnoughEvents = list()
        potentialDeviationEvents = list()
        consideredEventGroups = set(constraint[XHSTTFileConstants.EVENT_GROUPS])
        if affectedEventGroups is not None and len(consideredEventGroups.intersection(affectedEventGroups)) == 0:
            return constraint[XHSTTConstraintConstants.OBJECTIVE_VALUE]
        constraint[XHSTTConstraintConstants.DEVIATION_AMOUNT] = 0
        constraint.setdefault(XHSTTConstraintConstants.DEVIATION_MAP, dict())
        constraint[XHSTTConstraintConstants.OBJECTIVE_VALUE] = 0
        consideredResources = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCES])
        for resourceGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCE_GROUPS]:
            for resourceType in instance.Resources.ResourceGroupsByType.keys():
                if resourceGroup in instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups:
                    consideredResources.update(set(
                        instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups[
                            resourceGroup].Resources))
        if focusEventResources is not None:
            constraintResourceSet = set(consideredResources)
            if constraintResourceSet.isdisjoint(set(focusEventResources)):
                continue
            else:
                consideredResources = list(constraintResourceSet.intersection(set(focusEventResources)))
        for resource in consideredResources:
            constraint[XHSTTConstraintConstants.DEVIATION_MAP].setdefault(resource, set())
            if resource in resourceToSolutionEventsDict.keys():
                resourceEventNames = {solutionevent["@Id"][0] for solutionevent in
                                      resourceToSolutionEventsDict[resource]}
                constraintEventGroupsAttendedByResource = {eventGroup for eventGroup in consideredEventGroups
                                                      if resourceEventNames & set(instance.Events.EventGroups[eventGroup].Events)}
            else:
                constraintEventGroupsAttendedByResource = set()
            constraint[XHSTTConstraintConstants.DEVIATION_MAP][resource] = constraintEventGroupsAttendedByResource
            if focusEventResources is None and not excludeDeviationInfo:
                if len(constraintEventGroupsAttendedByResource) < int(constraint[XHSTTConstraintConstants.MINIMUM]):
                    resourcesWithoutEnoughEvents.append(resource)
                    if resource in resourceToSolutionEventsDict.keys():
                        constraint[XHSTTConstraintConstants.DEVIATION_EVENTS] += resourceToSolutionEventsDict[resource]
                elif len(constraintEventGroupsAttendedByResource) > int(constraint[XHSTTConstraintConstants.MAXIMUM]):
                    if resource in resourceToSolutionEventsDict.keys():
                        constraint[XHSTTConstraintConstants.DEVIATION_EVENTS] += resourceToSolutionEventsDict[resource]
                elif len(constraintEventGroupsAttendedByResource) > int(constraint[XHSTTConstraintConstants.MINIMUM]):
                    if resource in resourceToSolutionEventsDict.keys():
                        potentialDeviationEvents += resourceToSolutionEventsDict[resource]
            deviation = max(0, int(constraint[XHSTTConstraintConstants.MINIMUM]) - len(constraintEventGroupsAttendedByResource)) + max(0, len(constraintEventGroupsAttendedByResource) - int(constraint[XHSTTConstraintConstants.MAXIMUM]))
            if deviation > 0 and outputObjective:
                print(f"Violation of Student Choice (Required: {str(constraint[XHSTTConstraintConstants.REQUIRED])}) constraint for resource {resource} resource attends the following event groups {constraintEventGroupsAttendedByResource} of the considered event groups {consideredEventGroups}")
            constraint[XHSTTConstraintConstants.DEVIATION_AMOUNT] += deviation
            
            added_objective_value = _get_added_objective_value(constraint, deviation, useWeightCopy)
            objective_value += added_objective_value
            constraint[XHSTTConstraintConstants.OBJECTIVE_VALUE] += added_objective_value
        if focusEventResources is None and len(resourcesWithoutEnoughEvents) > 0 and not excludeDeviationInfo:
            constraint[XHSTTConstraintConstants.DEVIATION_EVENTS] += potentialDeviationEvents




    return objective_value

def _get_added_objective_value(constraint: dict, deviation: int, useWeightCopy: bool = False):
    softReductionFactor = 1.0 if constraint[XHSTTConstraintConstants.REQUIRED] else 0.00001
    weight_key = XHSTTConstraintConstants.WEIGHT_COPY if useWeightCopy else XHSTTConstraintConstants.WEIGHT
    weight = float(constraint[weight_key])  # Reduce dictionary lookups

    deviation_factor = deviation if constraint[
                                        XHSTTConstraintConstants.COST_FUNCTION] == XHSTTConstraintConstants.LINEAR else deviation * deviation
    objective_value = deviation_factor * weight * softReductionFactor

    if objective_value > 0:
        constraint[XHSTTConstraintConstants.IS_FULFILLED] = False

    return objective_value