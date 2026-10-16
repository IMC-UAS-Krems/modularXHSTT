import copy
import sys
sys.path.append('XHSTTImporter/Constants')
import XHSTTFileConstants
import XHSTTConstraintConstants
sys.path.append('ILP_solver')
sys.path.append('../ILP_solver')
import ILPConstants
sys.path.append('XHSTTImporter')
from Instance import Instance

def transform_instance_to_old_format_using_solution_with_student_assignments(instance: Instance, solution: dict) -> Instance:
    instance_copy = copy.deepcopy(instance)
    if XHSTTConstraintConstants.STUDENT_CHOICE_CONSTRAINT in instance_copy.Constraints:
        del instance_copy.Constraints[XHSTTConstraintConstants.STUDENT_CHOICE_CONSTRAINT]
    if XHSTTConstraintConstants.BALANCE_CLASS_SIZE_CONSTRAINT in instance_copy.Constraints:
        del instance_copy.Constraints[XHSTTConstraintConstants.BALANCE_CLASS_SIZE_CONSTRAINT]

    constraintsToDelete = list()
    for constraint in instance_copy.Constraints[XHSTTConstraintConstants.PREFER_TIMES_CONSTRAINT]:
        consideredEvents = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS])
        for event in consideredEvents:
            if len(event.split('_')) > 2:
                constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS].remove(event)
        if len(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS]) == 0:
            constraintsToDelete.append(constraint)
    for constraint in constraintsToDelete:
        instance_copy.Constraints[XHSTTConstraintConstants.PREFER_TIMES_CONSTRAINT].remove(constraint)
    constraintsToDelete = list()
    for constraint in instance_copy.Constraints[XHSTTConstraintConstants.ASSIGN_TIME_CONSTRAINT]:
        consideredEvents = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS])
        for event in consideredEvents:
            if len(event.split('_')) > 2:
                constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS].remove(event)
        if len(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS]) == 0:
            constraintsToDelete.append(constraint)
    for constraint in constraintsToDelete:
        instance_copy.Constraints[XHSTTConstraintConstants.ASSIGN_TIME_CONSTRAINT].remove(constraint)
    for eventID, event in instance.Events.IndividualEvents.items():
        instance_copy.Events.IndividualEvents[eventID].EventResources.UnassignedResources = [eR for eR in instance.Events.IndividualEvents[eventID].EventResources.UnassignedResources if not (eR.Role.startswith("min_requirement_") or eR.Role.startswith("max_requirement_"))]
        for eventResource in event.EventResources.UnassignedResources:
            if eventResource.Role.startswith("min_requirement_") or eventResource.Role.startswith("max_requirement_"):
                assignedEventResource = copy.deepcopy(eventResource)
                solutionEvents = [event for event in solution[XHSTTFileConstants.EVENTS].keys() if event[0] == eventID]
                if len(solutionEvents) == 0:
                    continue
                firstSolutionEvent = solution[XHSTTFileConstants.EVENTS][solutionEvents[0]]
                if eventResource.Role not in firstSolutionEvent[XHSTTFileConstants.RESOURCES] or firstSolutionEvent[XHSTTFileConstants.RESOURCES][eventResource.Role] == ILPConstants.DUMMY_RESOURCE:
                    continue
                assignedEventResource.Reference = firstSolutionEvent[XHSTTFileConstants.RESOURCES][eventResource.Role]
                instance_copy.Events.IndividualEvents[eventID].EventResources.AssignedResources.append(assignedEventResource)

    instance_copy.Constraints[XHSTTConstraintConstants.ASSIGN_RESOURCE_CONSTRAINT] = [constraint for constraint in instance_copy.Constraints[XHSTTConstraintConstants.ASSIGN_RESOURCE_CONSTRAINT] if not (constraint[XHSTTConstraintConstants.ROLE].startswith("min_requirement_") or constraint[XHSTTConstraintConstants.ROLE].startswith("max_requirement_"))]
    instance_copy.Constraints[XHSTTConstraintConstants.PREFER_RESOURCES_CONSTRAINT] = [constraint for constraint in
                                                                                      instance_copy.Constraints[
                                                                                          XHSTTConstraintConstants.PREFER_RESOURCES_CONSTRAINT]
                                                                                      if not (
                    constraint[XHSTTConstraintConstants.ROLE].startswith("min_requirement_") or constraint[
                XHSTTConstraintConstants.ROLE].startswith("max_requirement_"))]
    instance_copy.Constraints[XHSTTConstraintConstants.AVOID_SPLIT_ASSIGNMENTS_CONSTRAINT] = [constraint for constraint in
                                                                                      instance_copy.Constraints[
                                                                                          XHSTTConstraintConstants.AVOID_SPLIT_ASSIGNMENTS_CONSTRAINT]
                                                                                      if not (
                constraint[XHSTTConstraintConstants.ROLE].startswith("min_requirement_") or constraint[
            XHSTTConstraintConstants.ROLE].startswith("max_requirement_"))]


    for constraintName in instance_copy.Constraints.keys():
        for constraint in instance_copy.Constraints[constraintName]:
            if XHSTTConstraintConstants.DEVIATION_EVENTS in constraint:
                del constraint[XHSTTConstraintConstants.DEVIATION_EVENTS]
            if XHSTTConstraintConstants.DEVIATION_AMOUNT in constraint:
                del constraint[XHSTTConstraintConstants.DEVIATION_AMOUNT]
            if XHSTTConstraintConstants.OBJECTIVE_VALUE in constraint:
                del constraint[XHSTTConstraintConstants.OBJECTIVE_VALUE]

    return instance_copy


