import xmltodict
import pickle
from Instance import XHSTTInstance, Instance
import sys
sys.path.append('XHSTTImporter')
sys.path.append('../XHSTTImporter')
from Constants import XHSTTFileConstants, XHSTTConstraintConstants
from pathlib import Path


def read_XHSTT_input_file(filepath: str, fileName: str) -> XHSTTInstance:
    file_path = Path(filepath) / fileName
    file_content = file_path.read_text(encoding="utf8", errors="backslashreplace")
    file_as_dict = xmltodict.parse(file_content)
    instance_dict = file_as_dict['HighSchoolTimetableArchive']['Instances']['Instance']
    processedDataDict = _create_processed_data_dict(instance_dict, fileName)

    return XHSTTInstance(processedDataDict)

def load_saved_instance_from_pickle_file(filepath: str, fileName: str) -> Instance:
    return pickle.load(open(f"{filepath}/{fileName}", 'rb'))

def _create_processed_data_dict(instance_dict: dict, fileName: str) -> dict:
    processedDataDict = dict()

    # Initialize Relevant Metadata
    processedDataDict[XHSTTFileConstants.METADATA] = instance_dict['MetaData']
    processedDataDict[XHSTTFileConstants.METADATA][XHSTTFileConstants.FILE_NAME] = fileName
    processedDataDict[XHSTTFileConstants.METADATA][XHSTTFileConstants.FILE_ID] = instance_dict[XHSTTFileConstants.ID]

    _process_resources(processedDataDict, instance_dict)
    _process_times(processedDataDict, instance_dict)
    _process_events(processedDataDict, instance_dict)
    _process_constraints(processedDataDict, instance_dict)

    return processedDataDict

def _process_resources(processedDataDict: dict, instance_dict: dict):
    processedDataDict[XHSTTFileConstants.RESOURCES] = dict()
    processedDataDict[XHSTTFileConstants.RESOURCES][XHSTTFileConstants.RESOURCE_GROUPS_BY_TYPE] = dict()
    processedDataDict[XHSTTFileConstants.RESOURCES][XHSTTFileConstants.INDIVIDUAL_RESOURCES] = dict()

    _create_dicts_resource_types(processedDataDict, instance_dict)

    _create_dicts_resource_groups(processedDataDict, instance_dict)

    _process_individual_resources(processedDataDict, instance_dict)

def _process_individual_resources(processedDataDict: dict, instance_dict: dict):
    processedIndividualResources = processedDataDict[XHSTTFileConstants.RESOURCES][
        XHSTTFileConstants.INDIVIDUAL_RESOURCES]
    for resource in instance_dict[XHSTTFileConstants.RESOURCES][XHSTTFileConstants.RESOURCE]:
        resourceGroupsOfResourcesType = processedDataDict[XHSTTFileConstants.RESOURCES][
            XHSTTFileConstants.RESOURCE_GROUPS_BY_TYPE][resource[XHSTTFileConstants.RESOURCE_TYPE][
            XHSTTFileConstants.REFERENCE_WITH_AT]][
                    XHSTTFileConstants.RESOURCE_GROUPS]
        processedIndividualResources[resource[XHSTTFileConstants.ID]] = dict()
        processedIndividualResources[resource[XHSTTFileConstants.ID]][XHSTTFileConstants.NAME] = resource[
            XHSTTFileConstants.NAME]
        processedIndividualResources[resource[XHSTTFileConstants.ID]][XHSTTFileConstants.TYPE] = resource[
            XHSTTFileConstants.RESOURCE_TYPE][XHSTTFileConstants.REFERENCE_WITH_AT]
        if isinstance(resource[XHSTTFileConstants.RESOURCE_GROUPS][XHSTTFileConstants.RESOURCE_GROUP], list):
            processedIndividualResources[resource[XHSTTFileConstants.ID]][XHSTTFileConstants.RESOURCE_GROUPS] = list()
            for resourceGroup in resource[XHSTTFileConstants.RESOURCE_GROUPS][XHSTTFileConstants.RESOURCE_GROUP]:
                resourceGroupReference = resourceGroup[XHSTTFileConstants.REFERENCE_WITH_AT]
                processedIndividualResources[resource[XHSTTFileConstants.ID]][
                    XHSTTFileConstants.RESOURCE_GROUPS].append(resourceGroupReference)
                resourceGroupsOfResourcesType[resourceGroupReference][XHSTTFileConstants.RESOURCES].append(resource[
                                                                                                               XHSTTFileConstants.ID])
        else:
            resourceGroupReference = resource[XHSTTFileConstants.RESOURCE_GROUPS][XHSTTFileConstants.RESOURCE_GROUP][
                XHSTTFileConstants.REFERENCE_WITH_AT]
            processedIndividualResources[resource[XHSTTFileConstants.ID]][XHSTTFileConstants.RESOURCE_GROUPS] = [resourceGroupReference]
            resourceGroupsOfResourcesType[resourceGroupReference][XHSTTFileConstants.RESOURCES].append(resource[
                                                                                                           XHSTTFileConstants.ID])

def _create_dicts_resource_groups(processedDataDict: dict, instance_dict: dict):
    for resourceGroup in instance_dict[XHSTTFileConstants.RESOURCES][XHSTTFileConstants.RESOURCE_GROUPS][
        XHSTTFileConstants.RESOURCE_GROUP]:
        resourceGroupsOfMatchingTypeDict = processedDataDict[XHSTTFileConstants.RESOURCES][
            XHSTTFileConstants.RESOURCE_GROUPS_BY_TYPE][resourceGroup[XHSTTFileConstants.RESOURCE_TYPE][
            XHSTTFileConstants.REFERENCE_WITH_AT]][
            XHSTTFileConstants.RESOURCE_GROUPS]
        resourceGroupsOfMatchingTypeDict[resourceGroup[XHSTTFileConstants.ID]] = dict()
        resourceGroupsOfMatchingTypeDict[resourceGroup[XHSTTFileConstants.ID]][XHSTTFileConstants.NAME] = resourceGroup[
            XHSTTFileConstants.NAME]
        resourceGroupsOfMatchingTypeDict[resourceGroup[XHSTTFileConstants.ID]][XHSTTFileConstants.RESOURCES] = list()

def _create_dicts_resource_types(processedDataDict: dict, instance_dict: dict):
    for resourceType in [resourceType[XHSTTFileConstants.ID] for resourceType in instance_dict[
        XHSTTFileConstants.RESOURCES][XHSTTFileConstants.RESOURCE_TYPES][XHSTTFileConstants.RESOURCE_TYPE]]:
        processedDataDict[XHSTTFileConstants.RESOURCES][
            XHSTTFileConstants.RESOURCE_GROUPS_BY_TYPE][resourceType] = dict()
        processedDataDict[XHSTTFileConstants.RESOURCES][XHSTTFileConstants.RESOURCE_GROUPS_BY_TYPE][resourceType][
            XHSTTFileConstants.RESOURCE_GROUPS] = dict()
def _process_times(processedDataDict: dict, instance_dict: dict):
    processedDataDict[XHSTTFileConstants.TIMES] = dict()
    processedDataDict[XHSTTFileConstants.TIMES][XHSTTFileConstants.DAYS] = dict()
    processedDataDict[XHSTTFileConstants.TIMES][XHSTTFileConstants.TIME_GROUPS] = dict()
    processedDataDict[XHSTTFileConstants.TIMES][XHSTTFileConstants.INDIVIDUAL_TIMES] = dict()

    _create_time_groups_dicts(processedDataDict, instance_dict)

    _process_individual_times(processedDataDict, instance_dict)


def _process_individual_times(processedDataDict: dict, instance_dict: dict):
    processedIndividualTimes = processedDataDict[XHSTTFileConstants.TIMES][XHSTTFileConstants.INDIVIDUAL_TIMES]
    processedTimeGroups = processedDataDict[XHSTTFileConstants.TIMES][XHSTTFileConstants.TIME_GROUPS]
    processedDays = processedDataDict[XHSTTFileConstants.TIMES][XHSTTFileConstants.DAYS]
    for time in instance_dict[XHSTTFileConstants.TIMES][XHSTTFileConstants.TIME]:
        processedIndividualTimes[time[XHSTTFileConstants.ID]] = dict()
        processedIndividualTimes[time[XHSTTFileConstants.ID]][XHSTTFileConstants.NAME] = time[XHSTTFileConstants.NAME]
        processedIndividualTimes[time[XHSTTFileConstants.ID]][XHSTTFileConstants.DAY] = time[XHSTTFileConstants.DAY][
            XHSTTFileConstants.REFERENCE_WITH_AT]
        if XHSTTFileConstants.TIME_GROUPS not in time.keys() or time[XHSTTFileConstants.TIME_GROUPS] is None:
            processedIndividualTimes[time[XHSTTFileConstants.ID]][XHSTTFileConstants.TIME_GROUPS] = list()
        elif isinstance(time[XHSTTFileConstants.TIME_GROUPS][XHSTTFileConstants.TIME_GROUP], list):
            processedIndividualTimes[time[XHSTTFileConstants.ID]][XHSTTFileConstants.TIME_GROUPS] = list()
            for timeGroup in time[XHSTTFileConstants.TIME_GROUPS][XHSTTFileConstants.TIME_GROUP]:
                processedIndividualTimes[time[XHSTTFileConstants.ID]][XHSTTFileConstants.TIME_GROUPS].append(timeGroup[
                                                                                                                 XHSTTFileConstants.REFERENCE_WITH_AT])
                processedTimeGroups[timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]][XHSTTFileConstants.TIMES].append(time[
                                                                                                                          XHSTTFileConstants.ID])
        else:
            processedIndividualTimes[time[XHSTTFileConstants.ID]][XHSTTFileConstants.TIME_GROUPS] = [time[
                                                                                                         XHSTTFileConstants.TIME_GROUPS][
                                                                                                         XHSTTFileConstants.TIME_GROUP][
                                                                                                         XHSTTFileConstants.REFERENCE_WITH_AT]]
            processedTimeGroups[time[XHSTTFileConstants.TIME_GROUPS][XHSTTFileConstants.TIME_GROUP][
                XHSTTFileConstants.REFERENCE_WITH_AT]][XHSTTFileConstants.TIMES].append(time[XHSTTFileConstants.ID])

        processedDays[time[XHSTTFileConstants.DAY][XHSTTFileConstants.REFERENCE_WITH_AT]][XHSTTFileConstants.TIMES].append(time[
                                                                                                                               XHSTTFileConstants.ID])

        if XHSTTFileConstants.WEEK in time.keys():
            processedTimeGroups[time[XHSTTFileConstants.WEEK][XHSTTFileConstants.REFERENCE_WITH_AT]][
                XHSTTFileConstants.TIMES].append(time[XHSTTFileConstants.ID])

def _create_time_groups_dicts(processedDataDict: dict, instance_dict: dict):
    instanceTimeGroups = instance_dict[XHSTTFileConstants.TIMES][XHSTTFileConstants.TIME_GROUPS]
    processedDays = processedDataDict[XHSTTFileConstants.TIMES][XHSTTFileConstants.DAYS]
    processedTimeGroups = processedDataDict[XHSTTFileConstants.TIMES][XHSTTFileConstants.TIME_GROUPS]
    if XHSTTFileConstants.DAY in instanceTimeGroups.keys():
        if not isinstance(instance_dict[XHSTTFileConstants.TIMES][XHSTTFileConstants.TIME_GROUPS][
                              XHSTTFileConstants.DAY], list):
            instanceTimeGroups[XHSTTFileConstants.DAY] = [instanceTimeGroups[XHSTTFileConstants.DAY]]
        for day in instance_dict[XHSTTFileConstants.TIMES][XHSTTFileConstants.TIME_GROUPS][XHSTTFileConstants.DAY]:
            processedDays[day[XHSTTFileConstants.ID]] = dict()
            processedDays[day[XHSTTFileConstants.ID]][XHSTTFileConstants.NAME] = day[XHSTTFileConstants.NAME]
            processedDays[day[XHSTTFileConstants.ID]][XHSTTFileConstants.TIMES] = list()

    if XHSTTFileConstants.TIME_GROUP in instanceTimeGroups.keys():
        if not isinstance(instanceTimeGroups[XHSTTFileConstants.TIME_GROUP], list):
            instanceTimeGroups[XHSTTFileConstants.TIME_GROUP] = [instanceTimeGroups[XHSTTFileConstants.TIME_GROUP]]
        for timeGroup in instance_dict[XHSTTFileConstants.TIMES][XHSTTFileConstants.TIME_GROUPS][
            XHSTTFileConstants.TIME_GROUP]:
            processedTimeGroups[timeGroup[XHSTTFileConstants.ID]] = dict()
            processedTimeGroups[timeGroup[XHSTTFileConstants.ID]][XHSTTFileConstants.NAME] = timeGroup[
                XHSTTFileConstants.NAME]
            processedTimeGroups[timeGroup[XHSTTFileConstants.ID]][XHSTTFileConstants.TIMES] = list()

    if XHSTTFileConstants.WEEK in instanceTimeGroups.keys():
        if not isinstance(instanceTimeGroups[XHSTTFileConstants.WEEK], list):
            instanceTimeGroups[XHSTTFileConstants.WEEK] = [instanceTimeGroups[XHSTTFileConstants.WEEK]]
        for week in instanceTimeGroups[XHSTTFileConstants.WEEK]:
            processedTimeGroups[week[XHSTTFileConstants.ID]] = dict()
            processedTimeGroups[week[XHSTTFileConstants.ID]][XHSTTFileConstants.NAME] = week[XHSTTFileConstants.NAME]
            processedTimeGroups[week[XHSTTFileConstants.ID]][XHSTTFileConstants.TIMES] = list()

def _process_events(processedDataDict: dict, instance_dict: dict):
    processedDataDict[XHSTTFileConstants.EVENTS] = dict()
    processedDataDict[XHSTTFileConstants.EVENTS][XHSTTFileConstants.EVENT_GROUPS] = dict()
    processedDataDict[XHSTTFileConstants.EVENTS][XHSTTFileConstants.INDIVIDUAL_EVENTS] = dict()

    _make_courses_a_list_in_instance_for_later_processing(instance_dict)

    _create_dicts_for_event_groups_and_courses(processedDataDict, instance_dict)

    _process_individual_events(processedDataDict, instance_dict)

def _make_courses_a_list_in_instance_for_later_processing(instance_dict: dict):
    instanceEventGroups = instance_dict[XHSTTFileConstants.EVENTS][XHSTTFileConstants.EVENT_GROUPS]
    if XHSTTFileConstants.COURSE not in instanceEventGroups.keys() or instanceEventGroups[XHSTTFileConstants.COURSE] is None:
        instanceEventGroups[XHSTTFileConstants.COURSE] = []
    elif not isinstance(instanceEventGroups[XHSTTFileConstants.COURSE], list):
        instanceEventGroups[XHSTTFileConstants.COURSE] = [instanceEventGroups[XHSTTFileConstants.COURSE]]

def _create_dicts_for_event_groups_and_courses(processedDataDict: dict, instance_dict: dict):
    instanceEventGroups = instance_dict[XHSTTFileConstants.EVENTS][XHSTTFileConstants.EVENT_GROUPS]
    processedEventGroups = processedDataDict[XHSTTFileConstants.EVENTS][XHSTTFileConstants.EVENT_GROUPS]
    if XHSTTFileConstants.EVENT_GROUP not in instanceEventGroups.keys() or instanceEventGroups[
        XHSTTFileConstants.EVENT_GROUP] is None:
        instanceEventGroups[XHSTTFileConstants.EVENT_GROUP] = []
    elif not isinstance(instance_dict[XHSTTFileConstants.EVENTS][XHSTTFileConstants.EVENT_GROUPS][
                            XHSTTFileConstants.EVENT_GROUP], list):
        instanceEventGroups[XHSTTFileConstants.EVENT_GROUP] = [instanceEventGroups[XHSTTFileConstants.EVENT_GROUP]]

    for eventGroup in instanceEventGroups[XHSTTFileConstants.COURSE] + instanceEventGroups[
        XHSTTFileConstants.EVENT_GROUP]:
        processedEventGroups[eventGroup[XHSTTFileConstants.ID]] = dict()
        processedEventGroups[eventGroup[XHSTTFileConstants.ID]][XHSTTFileConstants.NAME] = eventGroup[
            XHSTTFileConstants.NAME]
        processedEventGroups[eventGroup[XHSTTFileConstants.ID]][XHSTTFileConstants.EVENTS] = list()

def _process_individual_events(processedDataDict: dict, instance_dict: dict):
    for event in instance_dict[XHSTTFileConstants.EVENTS][XHSTTFileConstants.EVENT]:
        _init_dict_for_individual_event(processedDataDict, event)

        _set_event_groups_for_individual_event(processedDataDict, event)

        _set_event_resources_for_individual_event(processedDataDict, event)

        _set_event_resource_groups_for_individual_event(processedDataDict, event)

def _init_dict_for_individual_event(processedDataDict: dict, event: dict):
    processedIndividualEvents = processedDataDict[XHSTTFileConstants.EVENTS][XHSTTFileConstants.INDIVIDUAL_EVENTS]
    processedIndividualEvents[event[XHSTTFileConstants.ID]] = dict()
    processedIndividualEvents[event[XHSTTFileConstants.ID]][XHSTTFileConstants.NAME] = event[XHSTTFileConstants.NAME]
    processedIndividualEvents[event[XHSTTFileConstants.ID]][XHSTTConstraintConstants.DURATION] = int(event[
                                                                                                         XHSTTConstraintConstants.DURATION])
    if XHSTTFileConstants.TIME in event:
        processedIndividualEvents[event[XHSTTFileConstants.ID]][XHSTTFileConstants.TIME] = event[XHSTTFileConstants.TIME][XHSTTFileConstants.REFERENCE_WITH_AT]
    else:
        processedIndividualEvents[event[XHSTTFileConstants.ID]][XHSTTFileConstants.TIME] = None
    processedIndividualEvents[event[XHSTTFileConstants.ID]][XHSTTFileConstants.RESOURCES] = dict()
    processedIndividualEvents[event[XHSTTFileConstants.ID]][XHSTTFileConstants.RESOURCES][
        XHSTTFileConstants.ASSIGNED_RESOURCES] = list()
    processedIndividualEvents[event[XHSTTFileConstants.ID]][XHSTTFileConstants.RESOURCES][
        XHSTTFileConstants.UNASSIGNED_RESOURCES] = list()
    processedIndividualEvents[event[XHSTTFileConstants.ID]][XHSTTFileConstants.EVENT_GROUPS] = list()


def _set_event_groups_for_individual_event(processedDataDict: dict, event: dict):
    processedEventGroups = processedDataDict[XHSTTFileConstants.EVENTS][XHSTTFileConstants.EVENT_GROUPS]
    processedIndividualEvents = processedDataDict[XHSTTFileConstants.EVENTS][XHSTTFileConstants.INDIVIDUAL_EVENTS]
    eventGroupList = list()
    if XHSTTFileConstants.COURSE in event.keys():
        courseReference = event[XHSTTFileConstants.COURSE][XHSTTFileConstants.REFERENCE_WITH_AT]
        if event[XHSTTFileConstants.ID] not in processedEventGroups[courseReference][XHSTTFileConstants.EVENTS]:
            processedEventGroups[courseReference][XHSTTFileConstants.EVENTS].append(event[XHSTTFileConstants.ID])
        if courseReference not in eventGroupList:
            eventGroupList.append(courseReference)

    if XHSTTFileConstants.EVENT_GROUPS not in event.keys() or event[XHSTTFileConstants.EVENT_GROUPS] is None:
        pass
    elif isinstance(event[XHSTTFileConstants.EVENT_GROUPS][XHSTTFileConstants.EVENT_GROUP], list):
        for eventGroup in event[XHSTTFileConstants.EVENT_GROUPS][XHSTTFileConstants.EVENT_GROUP]:
            eventGroupReference = eventGroup[XHSTTFileConstants.REFERENCE_WITH_AT]
            if eventGroupReference not in eventGroupList:
                eventGroupList.append(eventGroupReference)
            if event[XHSTTFileConstants.ID] not in processedEventGroups[eventGroupReference][XHSTTFileConstants.EVENTS]:
                processedEventGroups[eventGroupReference][XHSTTFileConstants.EVENTS].append(event[
                                                                                                XHSTTFileConstants.ID])
    else:
        eventGroupReference = event[XHSTTFileConstants.EVENT_GROUPS][XHSTTFileConstants.EVENT_GROUP][
            XHSTTFileConstants.REFERENCE_WITH_AT]
        if eventGroupReference not in eventGroupList:
            eventGroupList.append(eventGroupReference)
        if event[XHSTTFileConstants.ID] not in processedEventGroups[eventGroupReference][XHSTTFileConstants.EVENTS]:
            processedEventGroups[eventGroupReference][XHSTTFileConstants.EVENTS].append(event[XHSTTFileConstants.ID])
    processedIndividualEvents[event[XHSTTFileConstants.ID]][XHSTTFileConstants.EVENT_GROUPS] = eventGroupList


def _set_event_resources_for_individual_event(processedDataDict: dict, event: dict):
    if XHSTTFileConstants.RESOURCES not in event.keys() or event[XHSTTFileConstants.RESOURCES] is None:
        pass
    elif isinstance(event[XHSTTFileConstants.RESOURCES][XHSTTFileConstants.RESOURCE], list):
        for resource in event[XHSTTFileConstants.RESOURCES][XHSTTFileConstants.RESOURCE]:
            _process_individual_event_resource(processedDataDict, event, resource)
    else:
        # There are probably no instances where an event only requires a single resource but added this just to be safe
        resource = event[XHSTTFileConstants.RESOURCES][XHSTTFileConstants.RESOURCE]
        _process_individual_event_resource(processedDataDict, event, resource)


def _process_individual_event_resource(processedDataDict: dict, event: dict, resource: dict):
    assignedResourcesOfEvent = processedDataDict[XHSTTFileConstants.EVENTS][XHSTTFileConstants.INDIVIDUAL_EVENTS][event[
        XHSTTFileConstants.ID]][XHSTTFileConstants.RESOURCES][XHSTTFileConstants.ASSIGNED_RESOURCES]
    unassignedResourcesOfEvent = processedDataDict[XHSTTFileConstants.EVENTS][XHSTTFileConstants.INDIVIDUAL_EVENTS][event[
        XHSTTFileConstants.ID]][XHSTTFileConstants.RESOURCES][XHSTTFileConstants.UNASSIGNED_RESOURCES]
    if XHSTTFileConstants.REFERENCE_WITH_AT in resource:
        resourceReferance = resource[XHSTTFileConstants.REFERENCE_WITH_AT]
        if XHSTTConstraintConstants.WORKLOAD in resource:
            if XHSTTConstraintConstants.ROLE in resource:
                assignedResourcesOfEvent.append(
                    {XHSTTConstraintConstants.WORKLOAD: resource[XHSTTConstraintConstants.WORKLOAD],
                     XHSTTConstraintConstants.ROLE: resource[XHSTTConstraintConstants.ROLE],
                     XHSTTFileConstants.REFERENCE_NO_AT: resourceReferance})
            else:
                assignedResourcesOfEvent.append(
                    {XHSTTConstraintConstants.WORKLOAD: resource[XHSTTConstraintConstants.WORKLOAD],
                     XHSTTConstraintConstants.ROLE: None,
                     XHSTTFileConstants.REFERENCE_NO_AT: resourceReferance})
        else:
            if XHSTTConstraintConstants.ROLE in resource:
                assignedResourcesOfEvent.append(
                    {XHSTTConstraintConstants.WORKLOAD: None,
                     XHSTTConstraintConstants.ROLE: resource[XHSTTConstraintConstants.ROLE],
                     XHSTTFileConstants.REFERENCE_NO_AT: resourceReferance})
            else:
                assignedResourcesOfEvent.append(
                    {XHSTTConstraintConstants.WORKLOAD: None,
                     XHSTTConstraintConstants.ROLE: None,
                     XHSTTFileConstants.REFERENCE_NO_AT: resourceReferance})
    else:
        resourceType = resource[XHSTTFileConstants.RESOURCE_TYPE][XHSTTFileConstants.REFERENCE_WITH_AT]
        resourceRole = resource[XHSTTConstraintConstants.ROLE]
        if XHSTTConstraintConstants.WORKLOAD in resource:
            unassignedResourcesOfEvent.append({XHSTTFileConstants.RESOURCE_TYPE: resourceType,
                                               XHSTTConstraintConstants.WORKLOAD: int(resource[
                                                                                          XHSTTConstraintConstants.WORKLOAD]), XHSTTConstraintConstants.ROLE: resourceRole})
        else:
            unassignedResourcesOfEvent.append({
                XHSTTFileConstants.RESOURCE_TYPE: resourceType, XHSTTConstraintConstants.WORKLOAD: None, XHSTTConstraintConstants.ROLE: resourceRole})

def _set_event_resource_groups_for_individual_event(processedDataDict: dict, event: dict):
    if XHSTTFileConstants.RESOURCE_GROUPS not in event.keys() or event[XHSTTFileConstants.RESOURCE_GROUPS] is None:
        return
    eventResourceGroup = event[XHSTTFileConstants.RESOURCE_GROUPS][XHSTTFileConstants.RESOURCE_GROUP]
    if isinstance(eventResourceGroup, list):
        for resourceGroup in eventResourceGroup:
            _process_individual_event_resource_group(processedDataDict, event, resourceGroup)
    else:
        resourceGroup = eventResourceGroup[XHSTTFileConstants.REFERENCE_WITH_AT]
        _process_individual_event_resource_group(processedDataDict, event, resourceGroup)


def _process_individual_event_resource_group(processedDataDict: dict, event: dict, resourceGroup: dict):
    processedResoureGroupsByType = processedDataDict[XHSTTFileConstants.RESOURCES][
        XHSTTFileConstants.RESOURCE_GROUPS_BY_TYPE]
    processedIndividualEvents = processedDataDict[XHSTTFileConstants.EVENTS][XHSTTFileConstants.INDIVIDUAL_EVENTS]
    for type in processedResoureGroupsByType.keys():
        resourceGroupsOfEvent = processedResoureGroupsByType[type][XHSTTFileConstants.RESOURCE_GROUPS]
        if resourceGroup in resourceGroupsOfEvent.keys():
            for resource in resourceGroupsOfEvent[resourceGroup][XHSTTFileConstants.RESOURCES]:
                processedIndividualEvents[event[XHSTTFileConstants.ID]][XHSTTFileConstants.RESOURCES][
                    XHSTTFileConstants.ASSIGNED_RESOURCES].append(
                    {XHSTTConstraintConstants.WORKLOAD: None, XHSTTFileConstants.REFERENCE_NO_AT: resource})

def _process_constraints(processedDataDict: dict, instance_dict: dict):
    _init_constraint_dict_with_list_of_constraints(processedDataDict, instance_dict)
    processedConstraints = processedDataDict[XHSTTFileConstants.CONSTRAINTS]
    for constraintType in processedConstraints.keys():
        if not isinstance(processedConstraints[constraintType], list):
            processedConstraints[constraintType] = [processedConstraints[constraintType]]
        for constraint in processedConstraints[constraintType]:
            _process_individual_constraint(constraint)

def _init_constraint_dict_with_list_of_constraints(processedDataDict: dict, instance_dict: dict):
    processedDataDict[XHSTTFileConstants.CONSTRAINTS] = instance_dict[XHSTTFileConstants.CONSTRAINTS]
    processedConstraints = processedDataDict[XHSTTFileConstants.CONSTRAINTS]

    for constraintType in [XHSTTConstraintConstants.ASSIGN_RESOURCE_CONSTRAINT, XHSTTConstraintConstants.ASSIGN_TIME_CONSTRAINT, XHSTTConstraintConstants.SPLIT_EVENTS_CONSTRAINT,
                           XHSTTConstraintConstants.DISTRIBUTE_SPLIT_EVENTS_CONSTRAINT, XHSTTConstraintConstants.PREFER_RESOURCES_CONSTRAINT, XHSTTConstraintConstants.PREFER_TIMES_CONSTRAINT,
                           XHSTTConstraintConstants.AVOID_SPLIT_ASSIGNMENTS_CONSTRAINT, XHSTTConstraintConstants.SPREAD_EVENTS_CONSTRAINT, XHSTTConstraintConstants.LINK_EVENTS_CONSTRAINT,
                           XHSTTConstraintConstants.ORDER_EVENTS_CONSTRAINT, XHSTTConstraintConstants.AVOID_CLASHES_CONSTRAINT, XHSTTConstraintConstants.AVOID_UNAVAILABLE_TIMES_CONSTRAINT,
                           XHSTTConstraintConstants.LIMIT_IDLE_TIMES_CONSTRAINT, XHSTTConstraintConstants.CLUSTER_BUSY_TIMES_CONSTRAINT, XHSTTConstraintConstants.LIMIT_BUSY_TIMES_CONSTRAINT,
                           XHSTTConstraintConstants.LIMIT_WORKLOAD_CONSTRAINT]:
        if constraintType not in processedConstraints.keys() or processedConstraints[constraintType] is None:
            processedConstraints[constraintType] = list()
        elif not isinstance(processedConstraints[constraintType], list):
            processedConstraints[constraintType] = [processedConstraints[constraintType]]

def _process_individual_constraint(constraint: dict):
    constraint[XHSTTConstraintConstants.REQUIRED] = constraint[XHSTTConstraintConstants.REQUIRED] == "true" or constraint[
        XHSTTConstraintConstants.REQUIRED] == "True"

    _process_constraint_applications(constraint)

    _process_constraint_times(constraint)

    _process_constraint_time_groups(constraint)

    _process_constraint_resources(constraint)

    _process_constraint_resource_groups(constraint)

    _process_constraint_events(constraint)

    _process_constraint_event_groups(constraint)

    _process_constraint_event_pairs(constraint)


def _process_constraint_applications(constraint: dict):
    if XHSTTConstraintConstants.APPLIES_TO in constraint.keys():
        if constraint[XHSTTConstraintConstants.APPLIES_TO] is None:
            constraint[XHSTTConstraintConstants.APPLIES_TO] = dict()
        constraintApplications = constraint[XHSTTConstraintConstants.APPLIES_TO]
        if XHSTTFileConstants.RESOURCES in constraintApplications.keys() and constraintApplications[XHSTTFileConstants.RESOURCES] is not None:
            constraintApplicationResource = constraintApplications[XHSTTFileConstants.RESOURCES][
                XHSTTFileConstants.RESOURCE]
            if isinstance(constraintApplicationResource, list):
                resourceList = constraintApplicationResource
            else:
                resourceList = [constraintApplicationResource]

            constraintApplications[XHSTTFileConstants.RESOURCES] = [resource[XHSTTFileConstants.REFERENCE_WITH_AT] for resource in resourceList]
            if XHSTTFileConstants.RESOURCE_GROUPS not in constraint[XHSTTConstraintConstants.APPLIES_TO].keys() or constraintApplications[
                XHSTTFileConstants.RESOURCE_GROUPS] is None:
                constraintApplications[XHSTTFileConstants.RESOURCE_GROUPS] = dict()
                constraintApplications[XHSTTFileConstants.RESOURCE_GROUPS][XHSTTFileConstants.RESOURCE_GROUP] = list()

        if XHSTTFileConstants.RESOURCE_GROUPS in constraint[XHSTTConstraintConstants.APPLIES_TO].keys():
            constraintApplicationResourceGroups = constraintApplications[XHSTTFileConstants.RESOURCE_GROUPS]
            if constraintApplicationResourceGroups is None:
                resourceGroupList = []
            elif isinstance(constraintApplicationResourceGroups[XHSTTFileConstants.RESOURCE_GROUP], list):
                resourceGroupList = constraintApplicationResourceGroups[XHSTTFileConstants.RESOURCE_GROUP]
            else:
                resourceGroupList = [constraintApplicationResourceGroups[XHSTTFileConstants.RESOURCE_GROUP]]

            constraintApplications[XHSTTFileConstants.RESOURCE_GROUPS] = [resourceGroup[
                                                                              XHSTTFileConstants.REFERENCE_WITH_AT] for resourceGroup in
                                                                          resourceGroupList]
            if XHSTTFileConstants.RESOURCES not in constraintApplications.keys() or constraintApplications[
                XHSTTFileConstants.RESOURCES] is None:
                constraintApplications[XHSTTFileConstants.RESOURCES] = list()

        if (XHSTTFileConstants.EVENTS in constraintApplications.keys() and constraintApplications[XHSTTFileConstants.EVENTS] is not None and
                XHSTTFileConstants.EVENT in constraintApplications[XHSTTFileConstants.EVENTS].keys()):
            constraintApplicationEvent = constraintApplications[XHSTTFileConstants.EVENTS][XHSTTFileConstants.EVENT]
            if isinstance(constraintApplicationEvent, list):
                eventList = constraintApplicationEvent
            else:
                eventList = [constraintApplicationEvent]

            constraintApplications[XHSTTFileConstants.EVENTS] = [event[XHSTTFileConstants.REFERENCE_WITH_AT] for event in eventList]
            if XHSTTFileConstants.EVENT_GROUPS not in constraintApplications.keys() or constraintApplications[
                XHSTTFileConstants.EVENT_GROUPS] is None:
                constraintApplications[XHSTTFileConstants.EVENT_GROUPS] = dict()
                constraintApplications[XHSTTFileConstants.EVENT_GROUPS][XHSTTFileConstants.EVENT_GROUP] = list()

        if XHSTTFileConstants.EVENT_GROUPS in constraintApplications.keys():
            constraintApplicationEventGroup = constraintApplications[XHSTTFileConstants.EVENT_GROUPS][
                XHSTTFileConstants.EVENT_GROUP]
            if isinstance(constraintApplicationEventGroup, list):
                eventGroupList = constraintApplicationEventGroup
            else:
                eventGroupList = [constraintApplicationEventGroup]

            constraintApplications[XHSTTFileConstants.EVENT_GROUPS] = [eventGroup[XHSTTFileConstants.REFERENCE_WITH_AT] for eventGroup in
                                                                       eventGroupList]
            if XHSTTFileConstants.EVENTS not in constraintApplications.keys() or constraintApplications[
                XHSTTFileConstants.EVENTS] is None:
                constraintApplications[XHSTTFileConstants.EVENTS] = list()

        if XHSTTFileConstants.EVENT_PAIRS in constraintApplications.keys():
            constraintApplicationEventPair = constraintApplications[XHSTTFileConstants.EVENT_PAIRS][XHSTTFileConstants.EVENT_PAIR]
            if isinstance(constraintApplicationEventPair, list):
                eventPairList = constraintApplicationEventPair
            else:
                eventPairList = [constraintApplicationEventPair]

            constraintApplications[XHSTTFileConstants.EVENT_PAIRS] = [eventPair for eventPair in eventPairList]
            for eventPair in constraintApplications[XHSTTFileConstants.EVENT_PAIRS]:
                eventPair[XHSTTFileConstants.FIRST_EVENT] = eventPair[XHSTTFileConstants.FIRST_EVENT][
                    XHSTTFileConstants.REFERENCE_WITH_AT]
                eventPair[XHSTTFileConstants.SECOND_EVENT] = eventPair[XHSTTFileConstants.SECOND_EVENT][
                    XHSTTFileConstants.REFERENCE_WITH_AT]

def _process_constraint_times(constraint: dict):
    if XHSTTFileConstants.TIMES in constraint.keys() and constraint[XHSTTFileConstants.TIMES] is not None:
        constraintTime = constraint[XHSTTFileConstants.TIMES][XHSTTFileConstants.TIME]
        if isinstance(constraintTime, list):
            timeList = constraintTime
        else:
            timeList = [constraintTime]

        constraint[XHSTTFileConstants.TIMES] = [time[XHSTTFileConstants.REFERENCE_WITH_AT] for time in timeList]
        # If Times are given the solver expects the existence of a time group field in the constraints so we add
        # it if it does not yet exist
        if XHSTTFileConstants.TIME_GROUPS not in constraint.keys() or constraint[XHSTTFileConstants.TIME_GROUPS] is None:
            constraint[XHSTTFileConstants.TIME_GROUPS] = dict()
            constraint[XHSTTFileConstants.TIME_GROUPS][XHSTTFileConstants.TIME_GROUP] = list()
    elif (XHSTTFileConstants.TIMES in constraint.keys() and constraint[XHSTTFileConstants.TIMES] is None) or (XHSTTFileConstants.TIMES not in constraint.keys() and constraint[XHSTTConstraintConstants.ID].startswith('PreferTimes')):
        constraint[XHSTTFileConstants.TIMES] = list()
        if XHSTTFileConstants.TIME_GROUPS not in constraint.keys() or constraint[XHSTTFileConstants.TIME_GROUPS] is None:
            constraint[XHSTTFileConstants.TIME_GROUPS] = dict()
            constraint[XHSTTFileConstants.TIME_GROUPS][XHSTTFileConstants.TIME_GROUP] = list()

def _process_constraint_time_groups(constraint: dict):
    if XHSTTFileConstants.TIME_GROUPS in constraint.keys() and constraint[XHSTTFileConstants.TIME_GROUPS] is not None:
        constraintTimeGroup = constraint[XHSTTFileConstants.TIME_GROUPS][XHSTTFileConstants.TIME_GROUP]
        if isinstance(constraintTimeGroup, list):
            timeGroupList = constraintTimeGroup
        else:
            timeGroupList = [constraintTimeGroup]

        constraint[XHSTTFileConstants.TIME_GROUPS] = timeGroupList
        if XHSTTFileConstants.TIMES not in constraint.keys() or constraint[XHSTTFileConstants.TIMES] is None:
            constraint[XHSTTFileConstants.TIMES] = list()
    elif XHSTTFileConstants.TIME_GROUPS in constraint.keys() and constraint[XHSTTFileConstants.TIME_GROUPS] is None:
        constraint[XHSTTFileConstants.TIME_GROUPS] = list()
        if XHSTTFileConstants.TIMES not in constraint.keys() or constraint[XHSTTFileConstants.TIMES] is None:
            constraint[XHSTTFileConstants.TIMES] = list()

def _process_constraint_resources(constraint: dict):
    if XHSTTFileConstants.RESOURCES in constraint.keys() and constraint[XHSTTFileConstants.RESOURCES] is not None:
        constraintResource = constraint[XHSTTFileConstants.RESOURCES][XHSTTFileConstants.RESOURCE]
        if isinstance(constraintResource, list):
            resourceList = constraintResource
        else:
            resourceList = [constraintResource]

        constraint[XHSTTFileConstants.RESOURCES] = [resource[XHSTTFileConstants.REFERENCE_WITH_AT] for resource in resourceList]
        if XHSTTFileConstants.RESOURCE_GROUPS not in constraint.keys() or constraint[XHSTTFileConstants.RESOURCE_GROUPS] is None:
            constraint[XHSTTFileConstants.RESOURCE_GROUPS] = dict()
            constraint[XHSTTFileConstants.RESOURCE_GROUPS][XHSTTFileConstants.RESOURCE_GROUP] = list()

def _process_constraint_resource_groups(constraint: dict):
    if XHSTTFileConstants.RESOURCE_GROUPS in constraint.keys():
        constraintResourceGroups = constraint[XHSTTFileConstants.RESOURCE_GROUPS]
        if constraintResourceGroups is None:
            resourceGroupList = []
        elif isinstance(constraintResourceGroups[XHSTTFileConstants.RESOURCE_GROUP], list):
            resourceGroupList = constraintResourceGroups[XHSTTFileConstants.RESOURCE_GROUP]
        else:
            resourceGroupList = [constraintResourceGroups[XHSTTFileConstants.RESOURCE_GROUP]]

        constraint[XHSTTFileConstants.RESOURCE_GROUPS] = [resourceGroup[XHSTTFileConstants.REFERENCE_WITH_AT] for resourceGroup in
                                                          resourceGroupList]
        if XHSTTFileConstants.RESOURCES not in constraint.keys() or constraint[XHSTTFileConstants.RESOURCES] is None:
            constraint[XHSTTFileConstants.RESOURCES] = list()
    elif XHSTTFileConstants.RESOURCES in constraint.keys():
        if XHSTTFileConstants.RESOURCE_GROUPS not in constraint.keys() or constraint[XHSTTFileConstants.RESOURCE_GROUPS] is None:
            constraint[XHSTTFileConstants.RESOURCE_GROUPS] = list()


def _process_constraint_events(constraint: dict):
    if XHSTTFileConstants.EVENTS in constraint.keys() and constraint[XHSTTFileConstants.EVENTS] is not None:
        constraintEvent = constraint[XHSTTFileConstants.EVENTS][XHSTTFileConstants.EVENT]
        if isinstance(constraintEvent, list):
            eventList = constraintEvent
        else:
            eventList = [constraintEvent]

        constraint[XHSTTFileConstants.EVENTS] = [event[XHSTTFileConstants.REFERENCE_WITH_AT] for event in eventList]
        if XHSTTFileConstants.EVENT_GROUPS not in constraint.keys() or constraint[XHSTTFileConstants.TIME_GROUPS] is None:
            constraint[XHSTTFileConstants.EVENT_GROUPS] = dict()
            constraint[XHSTTFileConstants.EVENT_GROUPS][XHSTTFileConstants.EVENT_GROUP] = list()

def _process_constraint_event_groups(constraint: dict):
    if XHSTTFileConstants.EVENT_GROUPS in constraint.keys():
        constraintEventGroup = constraint[XHSTTFileConstants.EVENT_GROUPS][XHSTTFileConstants.EVENT_GROUP]
        if isinstance(constraintEventGroup, list):
            eventGroupList = constraintEventGroup
        else:
            eventGroupList = [constraintEventGroup]

        constraint[XHSTTFileConstants.EVENT_GROUPS] = [eventGroup[XHSTTFileConstants.REFERENCE_WITH_AT] for eventGroup in eventGroupList]
        if XHSTTFileConstants.EVENTS not in constraint.keys() or constraint[XHSTTFileConstants.EVENTS] is None:
            constraint[XHSTTFileConstants.EVENTS] = list()

def _process_constraint_event_pairs(constraint: dict):
    if XHSTTFileConstants.EVENT_PAIRS in constraint.keys():
        constraintEventPair = constraint[XHSTTFileConstants.EVENT_PAIRS][XHSTTFileConstants.EVENT_PAIR]
        if isinstance(constraintEventPair, list):
            eventPairList = constraintEventPair
        else:
            eventPairList = [constraintEventPair]

        constraint[XHSTTFileConstants.EVENT_PAIRS] = [eventPair for eventPair in eventPairList]
        for eventPair in constraint[XHSTTFileConstants.EVENT_PAIRS]:
            eventPair[XHSTTFileConstants.FIRST_EVENT] = eventPair[XHSTTFileConstants.FIRST_EVENT][XHSTTFileConstants.REFERENCE_WITH_AT]
            eventPair[XHSTTFileConstants.SECOND_EVENT] = eventPair[XHSTTFileConstants.SECOND_EVENT][XHSTTFileConstants.REFERENCE_WITH_AT]