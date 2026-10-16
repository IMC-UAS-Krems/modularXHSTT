from Instance import Instance
import copy
import sys
sys.path.append('XHSTTImporter')
sys.path.append('../XHSTTImporter')
from Constants import XHSTTFileConstants, XHSTTConstraintConstants


def split_constraints_into_smaller_constraints(instance: Instance):
    for constraintType in instance.Constraints.keys():
        addedConstraints = list()
        removedConstraints = list()
        for constraint in instance.Constraints[constraintType]:
            if constraintType in [XHSTTConstraintConstants.AVOID_CLASHES_CONSTRAINT, XHSTTConstraintConstants.AVOID_UNAVAILABLE_TIMES_CONSTRAINT,
                                  XHSTTConstraintConstants.LIMIT_IDLE_TIMES_CONSTRAINT, XHSTTConstraintConstants.CLUSTER_BUSY_TIMES_CONSTRAINT,
                                  XHSTTConstraintConstants.LIMIT_BUSY_TIMES_CONSTRAINT, XHSTTConstraintConstants.LIMIT_WORKLOAD_CONSTRAINT,
                                  XHSTTConstraintConstants.STUDENT_CHOICE_CONSTRAINT]:
                removedConstraints.append(constraint)
                addedConstraints += create_constraint_for_each_constraint_resource(instance, constraint)
            if constraintType in [XHSTTConstraintConstants.SPREAD_EVENTS_CONSTRAINT, XHSTTConstraintConstants.AVOID_SPLIT_ASSIGNMENTS_CONSTRAINT,
                                  XHSTTConstraintConstants.LINK_EVENTS_CONSTRAINT] and constraint[XHSTTConstraintConstants.COST_FUNCTION] != XHSTTConstraintConstants.QUADRATIC:
                removedConstraints.append(constraint)
                addedConstraints += create_constraint_for_each_event_group(constraint)
            if constraintType in [XHSTTConstraintConstants.ASSIGN_RESOURCE_CONSTRAINT, XHSTTConstraintConstants.PREFER_RESOURCES_CONSTRAINT,
                                  XHSTTConstraintConstants.ASSIGN_TIME_CONSTRAINT, XHSTTConstraintConstants.SPLIT_EVENTS_CONSTRAINT,
                                  XHSTTConstraintConstants.DISTRIBUTE_SPLIT_EVENTS_CONSTRAINT, XHSTTConstraintConstants.PREFER_TIMES_CONSTRAINT] and constraint[XHSTTConstraintConstants.COST_FUNCTION] != XHSTTConstraintConstants.QUADRATIC:
                removedConstraints.append(constraint)
                addedConstraints += create_constraint_for_each_individual_event(instance, constraint)
            if constraintType in [XHSTTConstraintConstants.ORDER_EVENTS_CONSTRAINT]:
                removedConstraints.append(constraint)
                addedConstraints += create_constraint_for_each_event_pair(constraint)
        for constraint in removedConstraints:
            instance.Constraints[constraintType].remove(constraint)
        for constraint in addedConstraints:
            instance.Constraints[constraintType].append(constraint)

def create_constraint_for_each_constraint_resource(instance: Instance, constraint: dict) -> list:
    addedConstraints = list()
    constraintResources = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCES])
    for resourceGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCE_GROUPS]:
        for resourceType in instance.Resources.ResourceGroupsByType.keys():
            if resourceGroup in instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups:
                constraintResources.update(
                    set(instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups[
                            resourceGroup].Resources))
    for resource in constraintResources:
        copyConstraint = copy.deepcopy(constraint)
        copyConstraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCES] = [resource]
        copyConstraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCE_GROUPS] = []
        copyConstraint[XHSTTConstraintConstants.ID] = constraint[XHSTTConstraintConstants.ID] + '_' + str(resource)
        addedConstraints.append(copyConstraint)
    return addedConstraints

def create_constraint_for_each_event_group(constraint: dict) -> list:
    addedConstraints = list()
    constraintEventGroups = constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]
    for eventGroup in constraintEventGroups:
        copyConstraint = copy.deepcopy(constraint)
        copyConstraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS] = [eventGroup]
        copyConstraint[XHSTTConstraintConstants.ID] = constraint[XHSTTConstraintConstants.ID] + '_' + str(eventGroup)
        addedConstraints.append(copyConstraint)
    return addedConstraints

def create_constraint_for_each_event_pair(constraint: dict) -> list:
    addedConstraints = list()
    constraintEventPairs = constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_PAIRS]
    for eventPair in constraintEventPairs:
        copyConstraint = copy.deepcopy(constraint)
        copyConstraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_PAIRS] = [eventPair]
        copyConstraint[XHSTTConstraintConstants.ID] = constraint[XHSTTConstraintConstants.ID] + '_' + str(eventPair[XHSTTFileConstants.FIRST_EVENT]) + '_' + str(eventPair[XHSTTFileConstants.SECOND_EVENT])
        addedConstraints.append(copyConstraint)
    return addedConstraints

def create_constraint_for_each_individual_event(instance: Instance, constraint: dict) -> list:
    addedConstraints = list()
    constraintEvents = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS])
    for eventGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
        constraintEvents.update(set(instance.Events.EventGroups[eventGroup].Events))
    for event in constraintEvents:
        copyConstraint = copy.deepcopy(constraint)
        copyConstraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS] = [event]
        copyConstraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS] = []
        copyConstraint[XHSTTConstraintConstants.ID] = constraint[XHSTTConstraintConstants.ID] + '_' + str(event)
        addedConstraints.append(copyConstraint)
    return addedConstraints