import math
from numpy.random import choice
import networkx as nx
import sys
sys.path.append('XHSTTImporter/Constants')
sys.path.append('../XHSTTImporter/Constants')
import XHSTTFileConstants
import XHSTTConstraintConstants
sys.path.append('ILP_solver')
sys.path.append('../ILP_solver')
import ILPConstants
sys.path.append('XHSTTImporter')
from Instance import Instance
sys.path.append('../validator')
sys.path.append('validator')
import validator
import itertools
import collections
from collections import defaultdict

hard_constraint_weight = 1
soft_constraint_weight = 1

def create_reource_conflict_graph(instance: Instance):
    conflict_graph = nx.Graph()
    conflict_graph.add_nodes_from(instance.Events.IndividualEvents.keys())

    resource_to_events = defaultdict(list)
    for e_id, e in instance.Events.IndividualEvents.items():
        for res in e.EventResources.AssignedResources:
            if res.Reference:
                resource_to_events[res.Reference].append(e_id)

    for events in resource_to_events.values():
        for u, v in itertools.combinations(events, 2):
            conflict_graph.add_edge(u, v)

    return conflict_graph

def create_time_conflict_graph(instance: Instance):
    time_list = list(instance.Times.IndividualTimes.keys())
    conflict_graph = nx.Graph()
    conflict_graph.add_nodes_from(instance.Events.IndividualEvents.keys())

    time_to_events = defaultdict(list)
    for e_id, e in instance.Events.IndividualEvents.items():
        if e.Time is not None:
            time_index = time_list.index(e.Time)
            for time in time_list[time_index: time_index + int(e.Duration)]:
                time_to_events[time].append(e_id)

    for events in time_to_events.values():
        for u, v in itertools.combinations(events, 2):
            conflict_graph.add_edge(u, v)

    return conflict_graph


def create_full_instance_graph(instance: Instance):
    G = nx.MultiDiGraph()

    # -------------------------------------------------------------------------
    # 1. Base Nodes (Prefixed IDs to prevent NetworkX namespace collisions)
    # -------------------------------------------------------------------------
    resourceToAssignedWorkload = dict()
    for event in instance.Events.IndividualEvents.values():
        for resource in event.EventResources.AssignedResources:
            resourceToAssignedWorkload.setdefault(resource.Reference, 0)
            resourceToAssignedWorkload[resource.Reference] += int(event.Duration)

    resourceNodes = []
    for resourceID, resource in instance.Resources.IndividualResources.items():
        resourceToAssignedWorkload.setdefault(resourceID, 0)
        resourceDict = {
            "NodeType": "Resource",
            "Type": resource.Type,
            "PreAssignedHours": resourceToAssignedWorkload[resourceID]
        }
        resourceNodes.append((f"Resource_{resourceID}", resourceDict))

    timeNodes = []
    timeList = list(instance.Times.IndividualTimes.keys())
    dayTimeLists = {dayID: list(day.Times) for dayID, day in instance.Times.Days.items()}

    for timeID, time in instance.Times.IndividualTimes.items():
        timeDict = {
            "NodeType": "Time",
            "Day": time.Day,
            "TotalIndex": timeList.index(timeID),
            "DayIndex": dayTimeLists[time.Day].index(timeID)
        }
        timeNodes.append((f"Time_{timeID}", timeDict))

    constraintNodes = []
    for constraintType in instance.Constraints.keys():
        for constraint in instance.Constraints[constraintType]:
            constraintID = constraint[XHSTTFileConstants.ID]
            constraintDict = {
                "NodeType": "Constraint",
                "ConstraintType": constraintType,
                "Weight": int(constraint[XHSTTConstraintConstants.WEIGHT]),
                "Hard": constraint[XHSTTConstraintConstants.REQUIRED],
                "CostFunction": constraint[XHSTTConstraintConstants.COST_FUNCTION],
                "Role": constraint.get(XHSTTConstraintConstants.ROLE, "NoRole"),
                "ConsiderUnassignedResources": constraint.get(XHSTTConstraintConstants.CONSIDER_UNASSIGNED_RESOURCES,
                                                              False),
                "Minimum": constraint.get(XHSTTConstraintConstants.MINIMUM, -1),
                "Maximum": constraint.get(XHSTTConstraintConstants.MAXIMUM, -1),
                "MinimumAmount": constraint.get(XHSTTConstraintConstants.MINIMUM_AMOUNT, -1),
                "MaximumAmount": constraint.get(XHSTTConstraintConstants.MAXIMUM_AMOUNT, -1),
                "MinimumDuration": constraint.get(XHSTTConstraintConstants.MINIMUM_DURATION, -1),
                "MaximumDuration": constraint.get(XHSTTConstraintConstants.MAXIMUM_DURATION, -1),
                "MaximumDifference": constraint.get(XHSTTConstraintConstants.MAXIMUM_DIFFERENCE, -1),
                "Duration": constraint.get(XHSTTConstraintConstants.DURATION, -1)
            }
            constraintNodes.append((f"Constraint_{constraintID}", constraintDict))

    eventNodes = []
    for eventID, event in instance.Events.IndividualEvents.items():
        eventDict = {
            "NodeType": "Event",
            "Duration": event.Duration,
            "NumberOfAssignedResources": len(event.EventResources.AssignedResources),
            "NumberOfUnassignedResources": len(event.EventResources.UnassignedResources)
        }
        eventNodes.append((f"Event_{eventID}", eventDict))

    G.add_nodes_from(resourceNodes)
    G.add_nodes_from(timeNodes)
    G.add_nodes_from(constraintNodes)
    G.add_nodes_from(eventNodes)

    # -------------------------------------------------------------------------
    # 2. Virtual Group Hub Nodes (Prefixed IDs)
    # -------------------------------------------------------------------------
    # Resource Groups
    for resourceType in instance.Resources.ResourceGroupsByType.keys():
        for resourceGroupID, resourceGroup in instance.Resources.ResourceGroupsByType[
            resourceType].ResourceGroups.items():
            virtual_rg_id = f"ResourceGroup_{resourceGroupID}"
            G.add_node(virtual_rg_id, NodeType="ResourceGroup", ResourceGroup=resourceGroupID,
                       ResourceType=resourceType)

            for r in resourceGroup.Resources:
                r_node = f"Resource_{r}"
                G.add_edge(r_node, virtual_rg_id, EdgeType="ResourceToGroup", ResourceGroup=resourceGroupID,
                           ResourceType=resourceType)
                G.add_edge(virtual_rg_id, r_node, EdgeType="GroupToResource", ResourceGroup=resourceGroupID,
                           ResourceType=resourceType)

    # Event Groups
    for eventGroupID, eventGroup in instance.Events.EventGroups.items():
        virtual_eg_id = f"EventGroup_{eventGroupID}"
        G.add_node(virtual_eg_id, NodeType="EventGroup", EventGroup=eventGroupID)

        for e in eventGroup.Events:
            e_node = f"Event_{e}"
            G.add_edge(e_node, virtual_eg_id, EdgeType="EventToGroup", EventGroup=eventGroupID)
            G.add_edge(virtual_eg_id, e_node, EdgeType="GroupToEvent", EventGroup=eventGroupID)

    # Time Groups
    for timeGroupID, timeGroup in instance.Times.TimeGroups.items():
        virtual_tg_id = f"TimeGroup_{timeGroupID}"
        G.add_node(virtual_tg_id, NodeType="TimeGroup", TimeGroup=timeGroupID)

        for t in timeGroup.Times:
            t_node = f"Time_{t}"
            G.add_edge(t_node, virtual_tg_id, EdgeType="TimeToGroup", TimeGroup=timeGroupID)
            G.add_edge(virtual_tg_id, t_node, EdgeType="GroupToTime", TimeGroup=timeGroupID)

    # Days
    for dayID, dayGroup in instance.Times.Days.items():
        virtual_day_id = f"DayGroup_{dayID}"
        G.add_node(virtual_day_id, NodeType="DayGroup", TimeGroup=dayID)

        for t in dayGroup.Times:
            t_node = f"Time_{t}"
            G.add_edge(t_node, virtual_day_id, EdgeType="TimeToDay", TimeGroup=dayID)
            G.add_edge(virtual_day_id, t_node, EdgeType="DayToTime", TimeGroup=dayID)

    # -------------------------------------------------------------------------
    # 3. Structural Edges
    # -------------------------------------------------------------------------
    # Consecutive Timeslots
    for timeIndex in range(len(timeList) - 1):
        t1 = f"Time_{timeList[timeIndex]}"
        t2 = f"Time_{timeList[timeIndex + 1]}"
        G.add_edge(t1, t2, EdgeType="ConsecutiveTimeslot")
        G.add_edge(t2, t1, EdgeType="PreviousTimeslot")

    # Time-Event Pre-Assignments
    for eventID, event in instance.Events.IndividualEvents.items():
        if event.Time is None:
            continue
        event_node = f"Event_{eventID}"
        start_idx = timeList.index(event.Time)
        affectedTimes = timeList[start_idx: start_idx + int(event.Duration)]
        for affectedTime in affectedTimes:
            t_node = f"Time_{affectedTime}"
            G.add_edge(t_node, event_node, EdgeType="PreAssignedEventForTime")
            G.add_edge(event_node, t_node, EdgeType="PreAssignedTime")

    # Resource-Event Pre-Assignments
    for eventID, event in instance.Events.IndividualEvents.items():
        event_node = f"Event_{eventID}"
        preAssignedResources = [resource.Reference for resource in event.EventResources.AssignedResources]
        for preAssignedResource in preAssignedResources:
            r_node = f"Resource_{preAssignedResource}"
            G.add_edge(r_node, event_node, EdgeType="PreAssignedEventForResource")
            G.add_edge(event_node, r_node, EdgeType="PreAssignedResource")

    # Constraint Scopes
    for constraintType in instance.Constraints.keys():
        for constraint in instance.Constraints[constraintType]:
            constraint_node = f"Constraint_{constraint[XHSTTFileConstants.ID]}"

            affectedTimes = set()
            if XHSTTFileConstants.TIMES in constraint:
                for time in constraint[XHSTTFileConstants.TIMES]:
                    affectedTimes.add((time, -1, -1, "None"))
            if XHSTTFileConstants.TIME_GROUPS in constraint:
                for timeGroup in constraint[XHSTTFileConstants.TIME_GROUPS]:
                    if isinstance(timeGroup, dict):
                        ref = timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]
                        min_v = timeGroup.get(XHSTTConstraintConstants.MINIMUM, -1)
                        max_v = timeGroup.get(XHSTTConstraintConstants.MAXIMUM, -1)
                        if ref in instance.Times.TimeGroups:
                            for time in instance.Times.TimeGroups[ref].Times:
                                affectedTimes.add((time, min_v, max_v, ref))
                        elif ref in instance.Times.Days:
                            for time in instance.Times.Days[ref].Times:
                                affectedTimes.add((time, min_v, max_v, ref))
                    else:
                        if timeGroup in instance.Times.TimeGroups:
                            for time in instance.Times.TimeGroups[timeGroup].Times:
                                affectedTimes.add((time, -1, -1, timeGroup))
                        elif timeGroup in instance.Times.Days:
                            for time in instance.Times.Days[timeGroup].Times:
                                affectedTimes.add((time, -1, -1, timeGroup))

            affectedResources = set()
            if XHSTTFileConstants.RESOURCES in constraint:
                affectedResources.update(constraint[XHSTTFileConstants.RESOURCES])
            if XHSTTFileConstants.RESOURCE_GROUPS in constraint:
                for rg in constraint[XHSTTFileConstants.RESOURCE_GROUPS]:
                    for r_type in instance.Resources.ResourceGroupsByType.keys():
                        if rg in instance.Resources.ResourceGroupsByType[r_type].ResourceGroups:
                            affectedResources.update(
                                instance.Resources.ResourceGroupsByType[r_type].ResourceGroups[rg].Resources)

            applies = constraint.get(XHSTTConstraintConstants.APPLIES_TO, {})
            if XHSTTFileConstants.RESOURCES in applies:
                affectedResources.update(applies[XHSTTFileConstants.RESOURCES])
            if XHSTTFileConstants.RESOURCE_GROUPS in applies:
                for rg in applies[XHSTTFileConstants.RESOURCE_GROUPS]:
                    for r_type in instance.Resources.ResourceGroupsByType.keys():
                        if rg in instance.Resources.ResourceGroupsByType[r_type].ResourceGroups:
                            affectedResources.update(
                                instance.Resources.ResourceGroupsByType[r_type].ResourceGroups[rg].Resources)

            affectedEvents = set()
            if XHSTTFileConstants.EVENTS in constraint:
                for e in constraint[XHSTTFileConstants.EVENTS]:
                    affectedEvents.add((e, "None"))
            if XHSTTFileConstants.EVENT_GROUPS in constraint:
                for eg in constraint[XHSTTFileConstants.EVENT_GROUPS]:
                    for e in instance.Events.EventGroups[eg].Events:
                        affectedEvents.add((e, eg))
            if XHSTTFileConstants.EVENTS in applies:
                for e in applies[XHSTTFileConstants.EVENTS]:
                    affectedEvents.add((e, "None"))
            if XHSTTFileConstants.EVENT_GROUPS in applies:
                for eg in applies[XHSTTFileConstants.EVENT_GROUPS]:
                    for e in instance.Events.EventGroups[eg].Events:
                        affectedEvents.add((e, eg))

            for time in affectedTimes:
                t_node = f"Time_{time[0]}"
                e_attr1 = {"EdgeType": "ConstraintAffectsTime", "MinRequirement": time[1], "MaxRequirement": time[2],
                           "AffectedTimeGroup": time[3]}
                e_attr2 = {"EdgeType": "TimeAffectedByConstraint", "MinRequirement": time[1], "MaxRequirement": time[2],
                           "AffectedTimeGroup": time[3]}
                G.add_edge(constraint_node, t_node, **e_attr1)
                G.add_edge(t_node, constraint_node, **e_attr2)

            for resource in affectedResources:
                r_node = f"Resource_{resource}"
                G.add_edge(constraint_node, r_node, EdgeType="ConstraintAffectsResource")
                G.add_edge(r_node, constraint_node, EdgeType="ResourceAffectedByConstraint")

            for event in affectedEvents:
                e_node = f"Event_{event[0]}"
                e_attr5 = {"EdgeType": "ConstraintAffectsEvent", "AffectedEventGroup": event[1]}
                e_attr6 = {"EdgeType": "EventAffectedByConstraint", "AffectedEventGroup": event[1]}
                G.add_edge(constraint_node, e_node, **e_attr5)
                G.add_edge(e_node, constraint_node, **e_attr6)

    return G


def update_graph_assignments(G: nx.MultiDiGraph, eventDict: dict, instance: Instance):
    """
    Dynamically updates the base graph with temporary subevent time and resource assignments.
    """
    # 1. Clear existing temporary assignment edges
    edges_to_remove = [(u, v, key) for u, v, key, data in G.edges(keys=True, data=True) if
                       data.get("IsTemporary", False)]
    G.remove_edges_from(edges_to_remove)

    # 2. Extract ordered time nodes using TotalIndex
    time_nodes = [n for n, attr in G.nodes(data=True) if attr.get("NodeType") == "Time"]
    time_list = sorted(time_nodes, key=lambda n: G.nodes[n]["TotalIndex"])

    # 3. Apply new assignments with prefixed node IDs
    for (eventID, subeventID), assignment in eventDict.items():
        subeventLength, subeventCounter = subeventID
        event_node = f"Event_{eventID}"

        if not G.has_node(event_node):
            print(f"Warning: missing event node {event_node} for graph update")
            continue

        # Handle Time Assignment
        assignedTime = assignment.get(XHSTTFileConstants.TIME, ILPConstants.DUMMY_TIME)
        assignedTime_node = f"Time_{assignedTime}"
        if assignedTime != ILPConstants.DUMMY_TIME and assignedTime_node in G:
            try:
                start_idx = time_list.index(assignedTime_node)
                affected_times = time_list[start_idx: start_idx + int(subeventLength)]

                for t_node in affected_times:
                    G.add_edge(
                        t_node, event_node,
                        EdgeType="AssignedTimeForEvent",
                        SubeventLength=subeventLength,
                        SubeventCounter=subeventCounter,
                        IsTemporary=True
                    )
                    G.add_edge(
                        event_node, t_node,
                        EdgeType="EventAssignedToTime",
                        SubeventLength=subeventLength,
                        SubeventCounter=subeventCounter,
                        IsTemporary=True
                    )
            except ValueError:
                pass

        # Handle Resource Assignments
        resources_mapping = assignment.get(XHSTTFileConstants.RESOURCES, {})
        for role, resourceID in resources_mapping.items():
            resource_node = f"Resource_{resourceID}"
            if resourceID != ILPConstants.DUMMY_RESOURCE and resource_node in G:
                G.add_edge(
                    resource_node, event_node,
                    EdgeType="AssignedResourceForEvent",
                    Role=role,
                    SubeventLength=subeventLength,
                    SubeventCounter=subeventCounter,
                    IsTemporary=True
                )
                G.add_edge(
                    event_node, resource_node,
                    EdgeType="EventAssignedToResource",
                    Role=role,
                    SubeventLength=subeventLength,
                    SubeventCounter=subeventCounter,
                    IsTemporary=True
                )

    # 4. Update Constraint fulfillment state
    for constraintType, constraints in instance.Constraints.items():
        for constraint in constraints:
            constraint_node = f"Constraint_{constraint[XHSTTFileConstants.ID]}"

            if G.has_node(constraint_node):
                if (XHSTTConstraintConstants.IS_FULFILLED in constraint and
                        XHSTTConstraintConstants.DEVIATION_AMOUNT in constraint and
                        XHSTTConstraintConstants.OBJECTIVE_VALUE in constraint and
                        XHSTTConstraintConstants.WEIGHT in constraint):

                    G.nodes[constraint_node]["IsFulfilled"] = constraint[XHSTTConstraintConstants.IS_FULFILLED]
                    G.nodes[constraint_node]["DeviationAmount"] = int(
                        constraint[XHSTTConstraintConstants.DEVIATION_AMOUNT])
                    G.nodes[constraint_node]["ObjectiveValue"] = float(
                        constraint[XHSTTConstraintConstants.OBJECTIVE_VALUE])
                    G.nodes[constraint_node]["Weight"] = int(constraint[XHSTTConstraintConstants.WEIGHT])
                else:
                    raise ValueError(f"Constraint {constraint} missing required evaluation properties.")

    return G

def select_n_resources_with_possible_assignment_changes(instance: Instance, solution: dict, numberSelectedElements: int, overwrite_constraint_weights=False, constraintIDFocus=None) -> list[str]:
    overwrite_constraint_weights = False
    G_resource = create_resource_relation_graph(instance, solution, overwrite_hard_constraint_weights=overwrite_constraint_weights)
    return select_n_nodes_from_graph(G_resource, numberSelectedElements)

def select_n_resources(instance: Instance, solution: dict, numberSelectedElements: int, type=None, overwrite_constraint_weights=False, constraintIDFocus=None) -> list[str]:
    overwrite_constraint_weights = False
    G_resource = create_resource_relation_graph(instance, solution, type, remove_fixed_resources=False, overwrite_hard_constraint_weights=overwrite_constraint_weights, constraintIDFocus=constraintIDFocus)
    return select_n_nodes_from_graph(G_resource, numberSelectedElements)

def select_n_times(instance: Instance, solution: dict, numberSelectedElements: int, overwrite_constraint_weights=False, constraintIDFocus=None) -> list[str]:
    overwrite_constraint_weights = False
    G_time = create_time_relation_graph(instance, solution, overwrite_hard_constraint_weights=overwrite_constraint_weights, constraintIDFocus=constraintIDFocus)
    return select_n_nodes_from_graph(G_time, numberSelectedElements)

def select_n_events(instance: Instance, solution: dict, numberSelectedElements: int, overwrite_constraint_weights=False, constraintIDFocus=None) -> list[str]:
    overwrite_constraint_weights = False
    G_event = create_event_relation_graph(instance, solution, overwrite_hard_constraint_weights=overwrite_constraint_weights, constraintIDFocus=constraintIDFocus)
    return select_n_nodes_from_graph(G_event, numberSelectedElements)

def select_n_nodes_from_graph(G: nx.Graph, node_number: int) -> list[str]:
    nodeWeightPairs = [(u, d["weight"]) for (u, d) in G.nodes(data=True) if d["weight"] > 0]
    nodes = [pair[0] for pair in nodeWeightPairs]
    sumOfWeights = sum([pair[1] for pair in nodeWeightPairs])
    if sumOfWeights == 0:
        print("The graph has no nodes with weight which indicates it is unlikely to find improvement in this neighborhood")
        nodeWeightPairs = [(u, 1) for (u, d) in G.nodes(data=True)]
        nodes = [pair[0] for pair in nodeWeightPairs]
        sumOfWeights = sum([pair[1] for pair in nodeWeightPairs])
    probabilityDistribution = [pair[1] / sumOfWeights for pair in nodeWeightPairs]
    randomNode = choice(nodes, 1, p=probabilityDistribution)
    selectedNodes = [randomNode[0]]
    while len(selectedNodes) < node_number:
        possibleNodesToWeight = dict()
        for node in selectedNodes:
            for neighbor in G.neighbors(node):
                if neighbor not in selectedNodes:
                    possibleNodesToWeight.setdefault(neighbor, 0)
                    possibleNodesToWeight[neighbor] += G.edges[node, neighbor]["weight"]
        if len(possibleNodesToWeight.keys()) > 1:
            nodes = list(possibleNodesToWeight.keys())
            sumOfWeights = sum(list(possibleNodesToWeight.values()))
            probabilityDistribution = [possibleNodesToWeight[node] / sumOfWeights for node in possibleNodesToWeight.keys()]
            randomNode = choice(nodes, 1, p=probabilityDistribution)
            selectedNodes.append(randomNode[0])
        elif len(possibleNodesToWeight.keys()) == 1:
            selectedNodes.append(list(possibleNodesToWeight.keys())[0])
        else:
            nodes = [pair[0] for pair in nodeWeightPairs if pair[0] not in selectedNodes]
            sumOfWeights = sum([pair[1] for pair in nodeWeightPairs if pair[0] not in selectedNodes])
            if sumOfWeights == 0:
                return selectedNodes
            probabilityDistribution = [pair[1] / sumOfWeights for pair in nodeWeightPairs if pair[0] not in selectedNodes]
            randomNode = choice(nodes, 1, p=probabilityDistribution)
            selectedNodes.append(randomNode[0])
    return selectedNodes


def create_resource_relation_graph(
        instance: Instance,
        solution: dict,
        resourceType=None,
        remove_fixed_resources=True,
        overwrite_hard_constraint_weights=False,
        constraintIDFocus=None
) -> nx.Graph:
    # --- Inner Helper Functions to eliminate DRY violations ---

    def _get_constraint_weight(c, forNode=False) -> int:
        """Extracts standard hard/soft constraint weights based on configuration."""
        multiplier = 1
        # if constraintIDFocus is not None and c[XHSTTFileConstants.ID] == constraintIDFocus:
        #     multiplier = 1000
        # else:
        #     multiplier = 1
        # if forNode and c[XHSTTConstraintConstants.IS_FULFILLED]:
        #     multiplier = 0
        if c[XHSTTConstraintConstants.REQUIRED]:
            return hard_constraint_weight * multiplier if overwrite_hard_constraint_weights else int(
                c[XHSTTConstraintConstants.WEIGHT]) * multiplier
        return soft_constraint_weight * multiplier

    def _get_constraint_resources(c, as_tuples=False) -> set:
        """Aggregates resources and resource groups targeted by a constraint."""
        applies_to = c[XHSTTConstraintConstants.APPLIES_TO]
        res_set = set()

        if as_tuples:
            res_set.update((r, None) for r in applies_to[XHSTTFileConstants.RESOURCES])
        else:
            res_set.update(applies_to[XHSTTFileConstants.RESOURCES])

        for group in applies_to[XHSTTFileConstants.RESOURCE_GROUPS]:
            for r_type, type_obj in instance.Resources.ResourceGroupsByType.items():
                if group in type_obj.ResourceGroups:
                    group_res = type_obj.ResourceGroups[group].Resources
                    if as_tuples:
                        res_set.update((r, group) for r in group_res)
                    else:
                        res_set.update(group_res)
        return res_set

    def _get_time_group_times(tg_name) -> list:
        """Retrieves times tied to either a TimeGroup or a Day reference."""
        if tg_name in instance.Times.TimeGroups:
            return instance.Times.TimeGroups[tg_name].Times
        return instance.Times.Days[tg_name].Times

    # --- Graph Initialization ---

    G = nx.Graph()
    # Filter and initialize graph nodes directly
    nodes_to_add = [
        res for res, data in instance.Resources.IndividualResources.items()
        if resourceType is None or data.Type != resourceType
    ]
    G.add_nodes_from(nodes_to_add, weight=0)

    # --- Setup Solution & Clash Dictionaries ---

    resourceToSolutionEventsByTimeDict = validator._create_resource_to_solution_events_by_time_dict(instance, solution)
    resourceToSolutionEventsDict = validator._create_resource_to_solution_events_dict(solution)

    resourceToClashesDict = {res: 0 for res in instance.Resources.IndividualResources}
    for resource, times in resourceToSolutionEventsByTimeDict.items():
        if resource == "dummyResource":
            continue
        for time, events in times.items():
            if len(events) > 1:
                resourceToClashesDict[resource] += len(events) - 1

    # --- Constraint Processing ---

    # 1. Avoid Clashes Constraint
    for constraint in instance.Constraints.get(XHSTTConstraintConstants.AVOID_CLASHES_CONSTRAINT, []):
        if constraint[XHSTTConstraintConstants.IS_FULFILLED]:
            continue
        weight = _get_constraint_weight(constraint)
        for resource, _ in _get_constraint_resources(constraint, as_tuples=True):
            if resource in G:
                G.nodes[resource]["weight"] += resourceToClashesDict[resource] * weight

    # 2. Avoid Unavailable Times Constraint
    for constraint in instance.Constraints.get(XHSTTConstraintConstants.AVOID_UNAVAILABLE_TIMES_CONSTRAINT, []):
        if constraint[XHSTTConstraintConstants.IS_FULFILLED]:
            continue
        weight = _get_constraint_weight(constraint)
        constraintTimes = set()
        if XHSTTFileConstants.TIMES in constraint:
            constraintTimes.update(constraint[XHSTTFileConstants.TIMES])
            for tg_dict in constraint[XHSTTFileConstants.TIME_GROUPS]:
                constraintTimes.update(_get_time_group_times(tg_dict[XHSTTFileConstants.REFERENCE_WITH_AT]))

        for resource in _get_constraint_resources(constraint):
            for time, events in resourceToSolutionEventsByTimeDict[resource].items():
                if time in constraintTimes and resource in G:
                    G.nodes[resource]["weight"] += len(events) * weight

    # 3. Limit Idle Times Constraint
    for constraint in instance.Constraints.get(XHSTTConstraintConstants.LIMIT_IDLE_TIMES_CONSTRAINT, []):
        if constraint[XHSTTConstraintConstants.IS_FULFILLED]:
            continue
        weight = _get_constraint_weight(constraint)
        for resource in _get_constraint_resources(constraint):
            numberOfIdleTimes = 0
            for tg_dict in constraint[XHSTTFileConstants.TIME_GROUPS]:
                times_in_group = _get_time_group_times(tg_dict[XHSTTFileConstants.REFERENCE_WITH_AT])

                first_found = False
                first_idx, last_idx = 1, 0
                busy_count = 0

                for idx, time in enumerate(times_in_group):
                    if time in resourceToSolutionEventsByTimeDict[resource] and len(
                            resourceToSolutionEventsByTimeDict[resource][time]) >= 1:
                        if not first_found:
                            first_found = True
                            first_idx = idx
                        last_idx = idx
                        busy_count += 1
                numberOfIdleTimes += (last_idx - first_idx + 1) - busy_count

            deviation = (max(0, int(constraint[XHSTTConstraintConstants.MINIMUM]) - numberOfIdleTimes) +
                         max(0, numberOfIdleTimes - int(constraint[XHSTTConstraintConstants.MAXIMUM])))
            if resource in G:
                G.nodes[resource]["weight"] += deviation * weight

    # 4. Limit Busy Times Constraint
    for constraint in instance.Constraints.get(XHSTTConstraintConstants.LIMIT_BUSY_TIMES_CONSTRAINT, []):
        if constraint[XHSTTConstraintConstants.IS_FULFILLED]:
            continue
        weight = _get_constraint_weight(constraint)
        for resource in _get_constraint_resources(constraint):
            deviation = 0
            for tg_dict in constraint[XHSTTFileConstants.TIME_GROUPS]:
                times_in_group = _get_time_group_times(tg_dict[XHSTTFileConstants.REFERENCE_WITH_AT])

                busy_count = sum(
                    1 for time in times_in_group
                    if time in resourceToSolutionEventsByTimeDict[resource] and len(
                        resourceToSolutionEventsByTimeDict[resource][time]) >= 1
                )
                if busy_count != 0:
                    deviation += (max(0, int(constraint[XHSTTConstraintConstants.MINIMUM]) - busy_count) +
                                  max(0, busy_count - int(constraint[XHSTTConstraintConstants.MAXIMUM])))

            if resource in G:
                G.nodes[resource]["weight"] += deviation * weight

    # 5. Limit Workload Constraint
    for constraint in instance.Constraints.get(XHSTTConstraintConstants.LIMIT_WORKLOAD_CONSTRAINT, []):
        if constraint[XHSTTConstraintConstants.IS_FULFILLED]:
            continue
        weight = _get_constraint_weight(constraint)
        for resource in _get_constraint_resources(constraint):
            resourceWorkload = 0.0
            if resource in resourceToSolutionEventsDict:
                for solevent in resourceToSolutionEventsDict[resource]:
                    rolesOfResource = [role for role, res in solevent[XHSTTFileConstants.RESOURCES].items() if
                                       res == resource]
                    ind_event = instance.Events.IndividualEvents[solevent["Name"]]
                    all_event_resources = list(ind_event.EventResources.AssignedResources) + list(
                        ind_event.EventResources.UnassignedResources)

                    for eventResource in all_event_resources:
                        if eventResource.Role in rolesOfResource:
                            duration = float(solevent[XHSTTFileConstants.DURATION])
                            if eventResource.Workload is None:
                                resourceWorkload += duration
                            else:
                                resourceWorkload += (duration * float(eventResource.Workload)) / float(
                                    ind_event.Duration)

            deviation = (max(0, math.ceil(float(constraint[XHSTTConstraintConstants.MINIMUM]) - resourceWorkload)) +
                         max(0, math.ceil(resourceWorkload - float(constraint[XHSTTConstraintConstants.MAXIMUM]))))
            if resource in G:
                G.nodes[resource]["weight"] += deviation * weight

    # 6. Student Choice Constraint
    if XHSTTConstraintConstants.STUDENT_CHOICE_CONSTRAINT not in instance.Constraints:
        instance.Constraints[XHSTTConstraintConstants.STUDENT_CHOICE_CONSTRAINT] = []

    for constraint in instance.Constraints[XHSTTConstraintConstants.STUDENT_CHOICE_CONSTRAINT]:
        if constraint[XHSTTConstraintConstants.IS_FULFILLED]:
            continue
        weight = _get_constraint_weight(constraint)
        consideredEventGroups = set(constraint[XHSTTFileConstants.EVENT_GROUPS])
        for resource in _get_constraint_resources(constraint):
            if resource in resourceToSolutionEventsDict:
                attended = {
                    eg for eg in consideredEventGroups
                    for solevent in resourceToSolutionEventsDict[resource]
                    if solevent["Name"] in instance.Events.EventGroups[eg].Events
                }
            else:
                attended = set()

            deviation = (max(0, int(constraint[XHSTTConstraintConstants.MINIMUM]) - len(attended)) +
                         max(0, len(attended) - int(constraint[XHSTTConstraintConstants.MAXIMUM])))
            if resource in G:
                G.nodes[resource]["weight"] += deviation * weight

    # 7. Prefer Resources Constraint
    for constraint in instance.Constraints.get(XHSTTConstraintConstants.PREFER_RESOURCES_CONSTRAINT, []):
        applies_to = constraint[XHSTTConstraintConstants.APPLIES_TO]
        consideredEvents = [(applies_to[XHSTTFileConstants.EVENTS][i], i) for i in
                            range(len(applies_to[XHSTTFileConstants.EVENTS]))]
        for eventGroup in applies_to[XHSTTFileConstants.EVENT_GROUPS]:
            consideredEvents.extend(
                (event, f"Group{eventGroup}") for event in instance.Events.EventGroups[eventGroup].Events)

        preferredResources = set(constraint.get(XHSTTFileConstants.RESOURCES, []))
        for group in constraint.get(XHSTTFileConstants.RESOURCE_GROUPS, []):
            for r_type, type_obj in instance.Resources.ResourceGroupsByType.items():
                if group in type_obj.ResourceGroups:
                    preferredResources.update(type_obj.ResourceGroups[group].Resources)

        base_weight = _get_constraint_weight(constraint)
        weight_divisor = len(preferredResources) if preferredResources else 1

        for event in consideredEvents:
            correspondingSolutionEvents = [solevent for solevent in solution[XHSTTFileConstants.EVENTS] if
                                           solevent[0] == event[0]]
            for solevent in correspondingSolutionEvents:
                solutionEvent = solution[XHSTTFileConstants.EVENTS][solevent]
                role = constraint[XHSTTConstraintConstants.ROLE]
                if role not in solutionEvent[XHSTTFileConstants.RESOURCES]:
                    continue
                resource = solutionEvent[XHSTTFileConstants.RESOURCES][role]
                for altResource in preferredResources:
                    if altResource == resource or resource not in G or altResource not in G:
                        continue
                    addedWeight = math.ceil(base_weight / weight_divisor) * solevent[1][0]
                    if G.has_edge(resource, altResource) and not constraint[XHSTTConstraintConstants.IS_FULFILLED]:
                        G.edges[resource, altResource]["weight"] += addedWeight
                    else:
                        G.add_edge(resource, altResource, weight=addedWeight)

    # 8. Link Events Constraint
    for constraint in instance.Constraints.get(XHSTTConstraintConstants.LINK_EVENTS_CONSTRAINT, []):
        for eventGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
            eventGroupResources = set()
            for event in instance.Events.EventGroups[eventGroup].Events:
                correspondingSolutionEvents = [solevent for solevent in solution[XHSTTFileConstants.EVENTS] if
                                               solevent[0] == event]
                for solevent in correspondingSolutionEvents:
                    solutionEvent = solution[XHSTTFileConstants.EVENTS][solevent]
                    for role, resource in solutionEvent[XHSTTFileConstants.RESOURCES].items():
                        eventGroupResources.add((solevent, resource))

            for sol1, r1 in eventGroupResources:
                for sol2, r2 in eventGroupResources:
                    if sol1[0] == sol2[0] or r1 == r2 or sol1[1] != sol2[1]:
                        continue
                    if G.has_edge(r1, r2):
                        G.edges[r1, r2]["weight"] = max(G.edges[r1, r2]["weight"] - sol1[1][0], 0)

    # --- Edge and Node Cleanup ---

    if G.has_node("dummyResource"):
        G.remove_node("dummyResource")

    edges_to_remove = [(u, v) for u, v, d in G.edges(data=True) if d["weight"] == 0]
    G.remove_edges_from(edges_to_remove)

    if remove_fixed_resources:
        resourcesAssigned = {
            res for event in solution[XHSTTFileConstants.EVENTS]
            for res in solution[XHSTTFileConstants.EVENTS][event][XHSTTFileConstants.RESOURCES].values()
            if res != "dummyResource"
        }
        for resource in list(instance.Resources.IndividualResources.keys()):
            if resource not in resourcesAssigned and resource in G:
                G.remove_node(resource)

    return G


def create_time_relation_graph(
        instance: Instance,
        solution: dict,
        overwrite_hard_constraint_weights=False,
        constraintIDFocus=None
) -> nx.Graph:
    # --- Performance Maps & Lookups ---
    # Cache times array and create an O(1) index map to replace costly .index() scans
    times_list = list(instance.Times.IndividualTimes.keys())
    time_to_idx = {t: i for i, t in enumerate(times_list)}

    # --- Inner Helper Functions ---

    def _get_constraint_weight(c, forNode=False) -> int:
        """Extracts standard hard/soft constraint weights based on configuration."""
        multiplier = 1
        # if constraintIDFocus is not None and c[XHSTTFileConstants.ID] == constraintIDFocus:
        #     multiplier = 1000
        # else:
        #     multiplier = 1
        # if forNode and c[XHSTTConstraintConstants.IS_FULFILLED]:
        #     multiplier = 0
        if c[XHSTTConstraintConstants.REQUIRED]:
            return hard_constraint_weight * multiplier if overwrite_hard_constraint_weights else int(
                c[XHSTTConstraintConstants.WEIGHT]) * multiplier
        return soft_constraint_weight * multiplier

    def _get_constraint_resources(c) -> set:
        """Aggregates resources and resource groups targeted by a constraint."""
        applies_to = c[XHSTTConstraintConstants.APPLIES_TO]
        res_set = set(applies_to[XHSTTFileConstants.RESOURCES])
        for group in applies_to[XHSTTFileConstants.RESOURCE_GROUPS]:
            for r_type, type_obj in instance.Resources.ResourceGroupsByType.items():
                if group in type_obj.ResourceGroups:
                    res_set.update(type_obj.ResourceGroups[group].Resources)
        return res_set

    def _get_time_group_times(tg_name) -> list:
        """Retrieves times tied to either a TimeGroup or a Day reference."""
        if tg_name in instance.Times.TimeGroups:
            return instance.Times.TimeGroups[tg_name].Times
        return instance.Times.Days[tg_name].Times

    def _add_or_increment_edge(u, v, weight):
        """Safely updates or initializes edge weights in the graph."""
        if G.has_edge(u, v):
            G.edges[u, v]["weight"] += weight
        else:
            G.add_edge(u, v, weight=weight)

    # --- Graph Initialization ---

    G = nx.Graph()
    G.add_nodes_from(times_list, weight=0)

    # --- Setup Solution & Clash Dictionaries ---

    resourceToSolutionEventsByTimeDict = validator._create_resource_to_solution_events_by_time_dict(instance, solution)

    resourceToClashesByTimeDict = {
        res: {t: 0 for t in times_list}
        for res in instance.Resources.IndividualResources
    }

    for resource, times in resourceToSolutionEventsByTimeDict.items():
        if resource == "dummyResource":
            continue
        for time, events in times.items():
            if len(events) > 1 and resource in resourceToClashesByTimeDict:
                resourceToClashesByTimeDict[resource][time] += len(events) - 1

    # --- Constraint Processing ---

    # 1. Avoid Clashes Constraint
    for constraint in instance.Constraints.get(XHSTTConstraintConstants.AVOID_CLASHES_CONSTRAINT, []):
        if constraint[XHSTTConstraintConstants.IS_FULFILLED]:
            continue
        weight = _get_constraint_weight(constraint)
        # Reusing resource extraction logic (ignoring groups tuple conversion context here as it's unneeded)
        for resource in _get_constraint_resources(constraint):
            if resource in resourceToClashesByTimeDict:
                for time, clash_count in resourceToClashesByTimeDict[resource].items():
                    G.nodes[time]["weight"] += clash_count * weight

    # 2. Prefer Times Constraint
    for constraint in instance.Constraints.get(XHSTTConstraintConstants.PREFER_TIMES_CONSTRAINT, []):
        applies_to = constraint[XHSTTConstraintConstants.APPLIES_TO]
        consideredEvents = set(applies_to[XHSTTFileConstants.EVENTS])
        for eventGroup in applies_to[XHSTTFileConstants.EVENT_GROUPS]:
            consideredEvents.update(instance.Events.EventGroups[eventGroup].Events)

        constraintTimes = set()
        if XHSTTFileConstants.TIMES in constraint:
            constraintTimes.update(constraint[XHSTTFileConstants.TIMES])
            for tg_dict in constraint[XHSTTFileConstants.TIME_GROUPS]:
                constraintTimes.update(_get_time_group_times(tg_dict[XHSTTFileConstants.REFERENCE_WITH_AT]))

        has_duration_restriction = XHSTTConstraintConstants.DURATION in constraint and constraint[
            XHSTTConstraintConstants.DURATION] is not None
        target_duration = int(constraint[XHSTTConstraintConstants.DURATION]) if has_duration_restriction else None

        base_weight = _get_constraint_weight(constraint)
        weight_divisor = len(constraintTimes) if constraintTimes else 1

        for event in consideredEvents:
            correspondingSolutionEvents = [
                solevent for solevent in solution[XHSTTFileConstants.EVENTS]
                if solevent[0] == event and (not has_duration_restriction or int(solevent[1][0]) == target_duration)
            ]

            for solevent in correspondingSolutionEvents:
                solutionEvent = solution[XHSTTFileConstants.EVENTS][solevent]
                time = solutionEvent[XHSTTFileConstants.TIME]
                duration_factor = solevent[1][0]

                if time not in constraintTimes and time != "dummyTime" and not constraint[XHSTTConstraintConstants.IS_FULFILLED]:
                    G.nodes[time]["weight"] += _get_constraint_weight(constraint) * duration_factor

                for altTime in constraintTimes:
                    if altTime == time:
                        continue
                    addedWeight = math.ceil(base_weight / weight_divisor) * duration_factor
                    _add_or_increment_edge(time, altTime, addedWeight)

    # 3. Limit Idle Times Constraint
    for constraint in instance.Constraints.get(XHSTTConstraintConstants.LIMIT_IDLE_TIMES_CONSTRAINT, []):
        if constraint[XHSTTConstraintConstants.IS_FULFILLED]:
            continue
        weight = _get_constraint_weight(constraint)
        max_idle = int(constraint[XHSTTConstraintConstants.MAXIMUM])
        min_idle = int(constraint[XHSTTConstraintConstants.MINIMUM])

        for resource in _get_constraint_resources(constraint):
            numberOfIdleTimes = 0
            timeGroupToFirstAndLastSlot = {}

            for tg_dict in constraint[XHSTTFileConstants.TIME_GROUPS]:
                tg_name = tg_dict[XHSTTFileConstants.REFERENCE_WITH_AT]
                times_in_group = _get_time_group_times(tg_name)

                first_found = False
                first_idx, last_idx = 1, 0
                busy_count = 0

                for idx, time in enumerate(times_in_group):
                    if time in resourceToSolutionEventsByTimeDict[resource] and len(
                            resourceToSolutionEventsByTimeDict[resource][time]) >= 1:
                        if not first_found:
                            first_found = True
                            first_idx = idx
                        last_idx = idx
                        busy_count += 1

                timeGroupToFirstAndLastSlot[tg_name] = (first_idx, last_idx)
                numberOfIdleTimes += (last_idx - first_idx + 1) - busy_count

            if numberOfIdleTimes > max_idle:
                for tg_name, (f_idx, l_idx) in timeGroupToFirstAndLastSlot.items():
                    times_in_group = _get_time_group_times(tg_name)
                    for timeIndex in range(f_idx, l_idx):
                        time = times_in_group[timeIndex]
                        if time not in resourceToSolutionEventsByTimeDict[resource] or len(
                                resourceToSolutionEventsByTimeDict[resource][time]) == 0:
                            G.nodes[time]["weight"] += weight

            elif numberOfIdleTimes < min_idle:
                for tg_name, (f_idx, l_idx) in timeGroupToFirstAndLastSlot.items():
                    times_in_group = _get_time_group_times(tg_name)
                    for timeIndex in range(f_idx, l_idx):
                        time = times_in_group[timeIndex]
                        if time in resourceToSolutionEventsByTimeDict[resource] and len(
                                resourceToSolutionEventsByTimeDict[resource][time]) >= 1:
                            G.nodes[time]["weight"] += weight

    # 4. Limit Busy Times Constraint
    for constraint in instance.Constraints.get(XHSTTConstraintConstants.LIMIT_BUSY_TIMES_CONSTRAINT, []):
        if constraint[XHSTTConstraintConstants.IS_FULFILLED]:
            continue
        weight = _get_constraint_weight(constraint)
        max_busy = int(constraint[XHSTTConstraintConstants.MAXIMUM])
        min_busy = int(constraint[XHSTTConstraintConstants.MINIMUM])

        for resource in _get_constraint_resources(constraint):
            numberOfBusyTimes = 0
            for tg_dict in constraint[XHSTTFileConstants.TIME_GROUPS]:
                times_in_group = _get_time_group_times(tg_dict[XHSTTFileConstants.REFERENCE_WITH_AT])
                numberOfBusyTimes += sum(
                    1 for t in times_in_group
                    if t in resourceToSolutionEventsByTimeDict[resource] and len(
                        resourceToSolutionEventsByTimeDict[resource][t]) >= 1
                )

            if numberOfBusyTimes > max_busy:
                for tg_dict in constraint[XHSTTFileConstants.TIME_GROUPS]:
                    for time in _get_time_group_times(tg_dict[XHSTTFileConstants.REFERENCE_WITH_AT]):
                        if time in resourceToSolutionEventsByTimeDict[resource] and len(
                                resourceToSolutionEventsByTimeDict[resource][time]) >= 1:
                            G.nodes[time]["weight"] += weight
            elif numberOfBusyTimes < min_busy:
                for tg_dict in constraint[XHSTTFileConstants.TIME_GROUPS]:
                    for time in _get_time_group_times(tg_dict[XHSTTFileConstants.REFERENCE_WITH_AT]):
                        if time not in resourceToSolutionEventsByTimeDict[resource] or len(
                                resourceToSolutionEventsByTimeDict[resource][time]) == 1:
                            G.nodes[time]["weight"] += weight

    # 5. Structural Edge Weight Modifications (Idle / Busy Groups)
    for constraint_type in [XHSTTConstraintConstants.LIMIT_IDLE_TIMES_CONSTRAINT,
                            XHSTTConstraintConstants.LIMIT_BUSY_TIMES_CONSTRAINT]:
        for constraint in instance.Constraints.get(constraint_type, []):
            edge_weight = _get_constraint_weight(constraint)
            for tg_dict in constraint[XHSTTFileConstants.TIME_GROUPS]:
                timesOfTimeGroup = _get_time_group_times(tg_dict[XHSTTFileConstants.REFERENCE_WITH_AT])
                for time1 in timesOfTimeGroup:
                    for time2 in timesOfTimeGroup:
                        if time1 != time2:
                            _add_or_increment_edge(time1, time2, edge_weight)

    # 6. Avoid Unavailable Times Constraint
    for constraint in instance.Constraints.get(XHSTTConstraintConstants.AVOID_UNAVAILABLE_TIMES_CONSTRAINT, []):
        if constraint[XHSTTConstraintConstants.IS_FULFILLED]:
            continue
        weight = _get_constraint_weight(constraint)
        constraintTimes = set()
        if XHSTTFileConstants.TIMES in constraint:
            constraintTimes.update(constraint[XHSTTFileConstants.TIMES])
            for tg_dict in constraint[XHSTTFileConstants.TIME_GROUPS]:
                constraintTimes.update(_get_time_group_times(tg_dict[XHSTTFileConstants.REFERENCE_WITH_AT]))

        for resource in _get_constraint_resources(constraint):
            for time, events in resourceToSolutionEventsByTimeDict[resource].items():
                if time in constraintTimes:
                    G.nodes[time]["weight"] += len(events) * weight

    # --- Overlapping Active Times Edge Multipliers (Optimized Section) ---

    # Optimization: Invert solution index maps to avoid massive nested O(N*M) lookups
    event_to_sol_events = collections.defaultdict(list)
    resource_to_sol_events = collections.defaultdict(list)

    for solevent, sol_data in solution[XHSTTFileConstants.EVENTS].items():
        event_to_sol_events[solevent[0]].append(solevent)
        for res in sol_data[XHSTTFileConstants.RESOURCES].values():
            resource_to_sol_events[res].append(solevent)

    # Process Individual Events Connected Times
    for event in instance.Events.IndividualEvents:
        activeTimesOfSolutionEvents = set()
        for solevent in event_to_sol_events[event]:
            startTime = solution[XHSTTFileConstants.EVENTS][solevent][XHSTTFileConstants.TIME]
            if startTime in ("dummyTime", None):
                continue
            # O(1) interval extraction using precalculated mappings
            start_idx = time_to_idx[startTime]
            activeTimesOfSolutionEvents.update(times_list[start_idx: start_idx + solevent[1][0]])

        for time1 in activeTimesOfSolutionEvents:
            for time2 in activeTimesOfSolutionEvents:
                if time1 != time2:
                    _add_or_increment_edge(time1, time2, 1)

    # Process Individual Resources Connected Times
    for resource in instance.Resources.IndividualResources:
        activeTimesOfSolutionEvents = set()
        for solevent in resource_to_sol_events[resource]:
            startTime = solution[XHSTTFileConstants.EVENTS][solevent][XHSTTFileConstants.TIME]
            if startTime in ("dummyTime", None):
                continue
            start_idx = time_to_idx[startTime]
            activeTimesOfSolutionEvents.update(times_list[start_idx: start_idx + solevent[1][0]])

        for time1 in activeTimesOfSolutionEvents:
            for time2 in activeTimesOfSolutionEvents:
                if time1 != time2:
                    _add_or_increment_edge(time1, time2, 1)

    # --- Final Graph Cleanup ---
    if G.has_node("dummyTime"):
        G.remove_node("dummyTime")

    edges_to_remove = [(u, v) for u, v, d in G.edges(data=True) if d["weight"] == 0]
    G.remove_edges_from(edges_to_remove)

    return G


def create_event_relation_graph(
        instance: Instance,
        solution: dict,
        overwrite_hard_constraint_weights=False,
        constraintIDFocus=None
) -> nx.Graph:
    G = nx.Graph()
    G.add_nodes_from(list(instance.Events.IndividualEvents.keys()), weight=0)

    # --- Inner Helper Functions ---

    def _get_constraint_weight(c, forNode=False) -> int:
        """Extracts standard hard/soft constraint weights based on configuration."""
        multiplier = 1
        # if constraintIDFocus is not None and c[XHSTTFileConstants.ID] == constraintIDFocus:
        #     multiplier = 1000
        # else:
        #     multiplier = 1
        # if forNode and c[XHSTTConstraintConstants.IS_FULFILLED]:
        #     multiplier = 0
        if c[XHSTTConstraintConstants.REQUIRED]:
            return hard_constraint_weight * multiplier if overwrite_hard_constraint_weights else int(
                c[XHSTTConstraintConstants.WEIGHT]) * multiplier
        return soft_constraint_weight * multiplier

    def _add_or_increment_edge(u, v, weight):
        """Safely updates or initializes edge weights in the graph."""
        if G.has_edge(u, v):
            G.edges[u, v]["weight"] += weight
        else:
            G.add_edge(u, v, weight=weight)

    # --- Node Weights Section ---

    # 1. Node Weights Group 1 (With Multipliers)
    multiplier_constraints = {
        XHSTTConstraintConstants.ASSIGN_RESOURCE_CONSTRAINT,
        XHSTTConstraintConstants.ASSIGN_TIME_CONSTRAINT,
        XHSTTConstraintConstants.PREFER_RESOURCES_CONSTRAINT,
        XHSTTConstraintConstants.PREFER_TIMES_CONSTRAINT,
        XHSTTConstraintConstants.AVOID_CLASHES_CONSTRAINT,
        XHSTTConstraintConstants.AVOID_UNAVAILABLE_TIMES_CONSTRAINT
    }

    for constraint_type in multiplier_constraints:
        for constraint in instance.Constraints.get(constraint_type, []):
            if XHSTTConstraintConstants.DEVIATION_EVENTS not in constraint or constraint[
                XHSTTConstraintConstants.IS_FULFILLED]:
                continue

            weight = _get_constraint_weight(constraint)
            for event in constraint[XHSTTConstraintConstants.DEVIATION_EVENTS]:
                event_id = event[XHSTTFileConstants.ID][0]
                multiplier = event[XHSTTFileConstants.ID][1][0]
                G.nodes[event_id]["weight"] += multiplier * weight

    # 2. Node Weights Group 2 (Unique/Cap per event per constraint)
    unique_constraints = {
        XHSTTConstraintConstants.SPLIT_EVENTS_CONSTRAINT,
        XHSTTConstraintConstants.DISTRIBUTE_SPLIT_EVENTS_CONSTRAINT,
        XHSTTConstraintConstants.AVOID_SPLIT_ASSIGNMENTS_CONSTRAINT,
        XHSTTConstraintConstants.SPREAD_EVENTS_CONSTRAINT,
        XHSTTConstraintConstants.LINK_EVENTS_CONSTRAINT,
        XHSTTConstraintConstants.BALANCE_CLASS_SIZE_CONSTRAINT,
        XHSTTConstraintConstants.STUDENT_CHOICE_CONSTRAINT
    }

    for constraint_type in unique_constraints:
        for constraint in instance.Constraints.get(constraint_type, []):
            if XHSTTConstraintConstants.DEVIATION_EVENTS not in constraint or constraint[
                XHSTTConstraintConstants.IS_FULFILLED]:
                continue

            weight = _get_constraint_weight(constraint)
            events_already_considered = set()

            for event in constraint[XHSTTConstraintConstants.DEVIATION_EVENTS]:
                event_id = event[XHSTTFileConstants.ID][0]
                if event_id not in events_already_considered:
                    G.nodes[event_id]["weight"] += weight
                    events_already_considered.add(event_id)

    # --- Edge Weights Section ---

    # 3. Resource Shared-Event Edges (Optimized Indexing Lookup)
    # Replaces deep O(N * M) nested scanning with a lightweight inverted hash-map index
    resource_to_events = collections.defaultdict(set)
    for solevent, sol_data in solution[XHSTTFileConstants.EVENTS].items():
        event_id = solevent[0]
        for resource in sol_data[XHSTTFileConstants.RESOURCES].values():
            resource_to_events[resource].add(event_id)

    for resource in instance.Resources.IndividualResources:
        events_of_resource = resource_to_events.get(resource, set())
        for event1 in events_of_resource:
            for event2 in events_of_resource:
                if event1 != event2:
                    _add_or_increment_edge(event1, event2, 1)

    # 4. Relational Structural Constraints (Link, Spread, Avoid Split Assignments)
    relational_constraints = [
        XHSTTConstraintConstants.LINK_EVENTS_CONSTRAINT,
        XHSTTConstraintConstants.SPREAD_EVENTS_CONSTRAINT,
        XHSTTConstraintConstants.AVOID_SPLIT_ASSIGNMENTS_CONSTRAINT
    ]

    for constraint_type in relational_constraints:
        for constraint in instance.Constraints.get(constraint_type, []):
            edge_weight = _get_constraint_weight(constraint)

            for event_group in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
                group_events = instance.Events.EventGroups[event_group].Events
                for event1 in group_events:
                    for event2 in group_events:
                        if event1 != event2:
                            _add_or_increment_edge(event1, event2, edge_weight)

    return G