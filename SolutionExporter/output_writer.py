import copy
import time
import uuid
from xml.dom import minidom
import xmltodict
import os
import io
import sys
from pandas import DataFrame
import SolutionFileConstants
import SolutionDataConstants
sys.path.append('../XHSTTImporter')
sys.path.append('../XHSTTImporter/Constants')
sys.path.append('XHSTTImporter/Constants')
import XHSTTFileConstants
import XHSTTConstraintConstants
import math
import UNTISConstants
sys.path.append('ILP_solver')
sys.path.append('../ILP_solver')
import ILPConstants
sys.path.append('XHSTTImporter')
from Instance import Instance
from filelock import FileLock

def write_instance_as_xhstt(instance: Instance, id: str, includeNewConstraints=True, artifical=False, subdir="", call_from_subdir=False, outputDir: str = None, outputPath: str = None):
    root = minidom.Document()
    xml = root.createElement(XHSTTFileConstants.ARCHIVE)
    root.appendChild(xml)
    instances = root.createElement(XHSTTFileConstants.INSTANCES)
    xml.appendChild(instances)
    solutionGroups = root.createElement("SolutionGroups")
    xml.appendChild(solutionGroups)
    instanceChild = root.createElement(XHSTTFileConstants.INSTANCE)
    clean_id = id.split('.xml')[0]
    instance_id = clean_id if clean_id.startswith("ModularXHSST_") else "ModularXHSST_" + clean_id
    instanceChild.setAttribute("Id", instance_id)
    instances.appendChild(instanceChild)
    metadata = root.createElement("MetaData")
    name = root.createElement("Name")
    name.appendChild(root.createTextNode(clean_id))
    contributor = root.createElement("Contributor")
    contributor.appendChild(root.createTextNode("Data from Untis GmbH (conversion: Andreas Krystallidis)"))
    date = root.createElement("Date")
    date.appendChild(root.createTextNode("March 2024"))
    country = root.createElement("Country")
    country.appendChild(root.createTextNode("Germany"))
    description = root.createElement("Description")
    description.appendChild(root.createTextNode("Modular High School from Germany featuring individual Student Choices"))
    remarks = root.createElement("Remarks")
    metadata.appendChild(name)
    metadata.appendChild(contributor)
    metadata.appendChild(date)
    metadata.appendChild(country)
    metadata.appendChild(description)
    metadata.appendChild(remarks)
    instanceChild.appendChild(metadata)

    times = root.createElement(XHSTTFileConstants.TIMES)
    create_times_for_xhstt_xml(instance, times, root)
    resources = root.createElement(XHSTTFileConstants.RESOURCES)
    create_resources_for_xhstt_xml(instance, resources, root)
    events = root.createElement(XHSTTFileConstants.EVENTS)
    create_events_for_xhstt_xml(instance, events, root)
    constraints = root.createElement(XHSTTFileConstants.CONSTRAINTS)
    create_constraints_for_xhstt_xml(instance, constraints, root, includeNewConstraints)
    instanceChild.appendChild(times)
    instanceChild.appendChild(resources)
    instanceChild.appendChild(events)
    instanceChild.appendChild(constraints)

    if call_from_subdir:
        pathprefix="../"
    else:
        pathprefix = ""

    xml_str_solution = root.toprettyxml(indent="\t")
    if outputPath is not None:
        os.makedirs(os.path.dirname(os.path.abspath(outputPath)), exist_ok=True)
        with open(outputPath, mode="w", encoding="utf-8") as f:
            f.write(xml_str_solution)
        return outputPath
    elif outputDir is not None:
        os.makedirs(outputDir, exist_ok=True)
        target_path = os.path.join(outputDir, f"{clean_id}.xml")
        with open(target_path, mode="w", encoding="utf-8") as f:
            f.write(xml_str_solution)
        return target_path
    elif artifical:
        id = id.split('.xml')[0]
        # if '_' in id:
        #     id = id.split('_')[0]
        if '/' in id:
            id = id.split('/')[1]
        dir_path = f"{pathprefix}data/artificial{subdir}/"
        os.makedirs(dir_path, exist_ok=True)
        with open(f"{pathprefix}data/artificial{subdir}/{id}.xml", mode="x") as f:
            f.write(xml_str_solution)
    elif includeNewConstraints:
        id = id.split('.xml')[0]
        # if '_' in id:
        #     id = id.split('_')[0]
        if '/' in id:
            id = id.split('/')[1]
        if id.endswith('_'):
            id = id[:-1]
        with open(f"{pathprefix}data/untis/{subdir}/{id}.xml", mode="x") as f:
            f.write(xml_str_solution)
    else:
        if '/' in id or '_' in id:
            id = id.split('/')[-1].split('_')[-1]
        id = id.split('.xml')[0]
        if '_' in id:
            id = id.split('_')[0]
        with open(f"{pathprefix}data/untis/{subdir}/old_format_{id}_updated_format.xml", "x") as f:
            f.write(xml_str_solution)

def create_times_for_xhstt_xml(instance: Instance, times: minidom.Element, root: minidom.Document):
    timeGroups = root.createElement(XHSTTFileConstants.TIME_GROUPS)
    times.appendChild(timeGroups)
    for timeGroup in instance.Times.Days.keys():
        day = root.createElement(XHSTTFileConstants.DAY)
        day.setAttribute("Id", timeGroup)
        name = root.createElement("Name")
        if timeGroup == "1":
            name.appendChild(root.createTextNode("Monday"))
        elif timeGroup == "2":
            name.appendChild(root.createTextNode("Tuesday"))
        elif timeGroup == "3":
            name.appendChild(root.createTextNode("Wednesday"))
        elif timeGroup == "4":
            name.appendChild(root.createTextNode("Thursday"))
        elif timeGroup == "5":
            name.appendChild(root.createTextNode("Friday"))
        else:
            name.appendChild(root.createTextNode(instance.Times.Days[timeGroup].Name))
        day.appendChild(name)
        timeGroups.appendChild(day)

    for timeGroup in instance.Times.TimeGroups.keys():
        timeGroupChild = root.createElement(XHSTTFileConstants.TIME_GROUP)
        timeGroupChild.setAttribute("Id", timeGroup)
        name = root.createElement("Name")
        name.appendChild(root.createTextNode(instance.Times.TimeGroups[timeGroup].Name))
        timeGroupChild.appendChild(name)
        timeGroups.appendChild(timeGroupChild)

    for time_id in instance.Times.IndividualTimes.keys():
        timeChild = root.createElement(XHSTTFileConstants.TIME)
        timeChild.setAttribute("Id", time_id)
        name = root.createElement("Name")
        name.appendChild(root.createTextNode(instance.Times.IndividualTimes[time_id].Name))
        day = root.createElement(XHSTTFileConstants.DAY)
        day.setAttribute(XHSTTFileConstants.REFERENCE_NO_AT, instance.Times.IndividualTimes[time_id].Day)
        timeGroups = root.createElement(XHSTTFileConstants.TIME_GROUPS)
        timeChild.appendChild(name)
        timeChild.appendChild(day)
        for timeGroup in instance.Times.TimeGroups.keys():
            if time_id not in instance.Times.TimeGroups[timeGroup].Times:
                continue
            timeGroupChild = root.createElement(XHSTTFileConstants.TIME_GROUP)
            timeGroupChild.setAttribute(XHSTTFileConstants.REFERENCE_NO_AT, timeGroup)
            timeGroups.appendChild(timeGroupChild)
        timeChild.appendChild(timeGroups)
        times.appendChild(timeChild)

def create_resources_for_xhstt_xml(instance: Instance, resources: minidom.Element, root: minidom.Document):
    resourceTypes = root.createElement(XHSTTFileConstants.RESOURCE_TYPES)
    resourceGroups = root.createElement(XHSTTFileConstants.RESOURCE_GROUPS)
    resources.appendChild(resourceTypes)
    resources.appendChild(resourceGroups)
    for type in instance.Resources.ResourceGroupsByType.keys():
        resourceType = root.createElement(XHSTTFileConstants.RESOURCE_TYPE)
        resourceType.setAttribute("Id", type)
        name = root.createElement("Name")
        name.appendChild(root.createTextNode(type))
        resourceType.appendChild(name)
        resourceTypes.appendChild(resourceType)
        for resourceGroup in instance.Resources.ResourceGroupsByType[type].ResourceGroups.keys():
            resourceGroupChild = root.createElement(XHSTTFileConstants.RESOURCE_GROUP)
            resourceGroupChild.setAttribute("Id", resourceGroup)
            name = root.createElement("Name")
            name.appendChild(root.createTextNode(resourceGroup))
            resourceGroupChild.appendChild(name)
            typeChild = root.createElement("ResourceType")
            typeChild.setAttribute(XHSTTFileConstants.REFERENCE_NO_AT, type)
            resourceGroupChild.appendChild(typeChild)
            resourceGroups.appendChild(resourceGroupChild)
    for resourceID, resourceObject in instance.Resources.IndividualResources.items():
        resourceChild = root.createElement(XHSTTFileConstants.RESOURCE)
        resourceChild.setAttribute("Id", resourceID)
        name = root.createElement("Name")
        name.appendChild(root.createTextNode(resourceID))
        resourceChild.appendChild(name)
        resourceType = root.createElement(XHSTTFileConstants.RESOURCE_TYPE)
        resourceType.setAttribute(XHSTTFileConstants.REFERENCE_NO_AT, resourceObject.Type)
        resourceChild.appendChild(resourceType)
        resourceGroups = root.createElement(XHSTTFileConstants.RESOURCE_GROUPS)
        resourceChild.appendChild(resourceGroups)
        for resourceGroup in instance.Resources.IndividualResources[resourceID].ResourceGroups:
            resourceGroupChild = root.createElement(XHSTTFileConstants.RESOURCE_GROUP)
            resourceGroupChild.setAttribute(XHSTTFileConstants.REFERENCE_NO_AT, resourceGroup)
            resourceGroups.appendChild(resourceGroupChild)
        resources.appendChild(resourceChild)
def create_events_for_xhstt_xml(instance: Instance, events: minidom.Element, root: minidom.Document):
    eventGroups = root.createElement(XHSTTFileConstants.EVENT_GROUPS)
    events.appendChild(eventGroups)
    for eventGroup in instance.Events.EventGroups.keys():
        eventGroupChild = root.createElement(XHSTTFileConstants.EVENT_GROUP)
        eventGroupChild.setAttribute("Id", eventGroup)
        name = root.createElement("Name")
        name.appendChild(root.createTextNode(eventGroup))
        eventGroupChild.appendChild(name)
        eventGroups.appendChild(eventGroupChild)
    for event in instance.Events.IndividualEvents.keys():
        eventChild = root.createElement(XHSTTFileConstants.EVENT)
        events.appendChild(eventChild)
        eventChild.setAttribute("Id", event)
        name = root.createElement("Name")
        name.appendChild(root.createTextNode(event))
        eventChild.appendChild(name)
        duration = root.createElement("Duration")
        duration.appendChild(root.createTextNode(str(instance.Events.IndividualEvents[event].Duration)))
        eventChild.appendChild(duration)
        if instance.Events.IndividualEvents[event].Time is not None:
            time = root.createElement("Time")
            time.setAttribute(XHSTTFileConstants.REFERENCE_NO_AT, str(instance.Events.IndividualEvents[event].Time))
            eventChild.appendChild(time)
        eventResources = root.createElement(XHSTTFileConstants.RESOURCES)
        eventChild.appendChild(eventResources)
        for resource in (instance.Events.IndividualEvents[event].EventResources.AssignedResources + instance.Events.IndividualEvents[event].EventResources.UnassignedResources):
            eventResource = root.createElement(XHSTTFileConstants.RESOURCE)
            eventResources.appendChild(eventResource)
            if resource.Reference is not None:
                eventResource.setAttribute(XHSTTFileConstants.REFERENCE_NO_AT, resource.Reference)
            if resource.Role is not None:
                resourceRole = root.createElement(XHSTTFileConstants.ROLE)
                resourceRole.appendChild(root.createTextNode(resource.Role))
                eventResource.appendChild(resourceRole)
            if resource.ResourceType is not None:
                resourceType = root.createElement("ResourceType")
                resourceType.setAttribute(XHSTTFileConstants.REFERENCE_NO_AT, resource.ResourceType)
                eventResource.appendChild(resourceType)
            if resource.Workload != 0 and resource.Workload is not None:
                resourceWorkload = root.createElement(XHSTTFileConstants.WORKLOAD)
                resourceWorkload.appendChild(root.createTextNode(str(resource.Workload)))
                eventResource.appendChild(resourceWorkload)
        eventGroups = root.createElement(XHSTTFileConstants.EVENT_GROUPS)
        eventChild.appendChild(eventGroups)
        for eventGroup in instance.Events.IndividualEvents[event].EventGroups:
            eventGroupChild = root.createElement(XHSTTFileConstants.EVENT_GROUP)
            eventGroups.appendChild(eventGroupChild)
            eventGroupChild.setAttribute(XHSTTFileConstants.REFERENCE_NO_AT, eventGroup)
def create_constraints_for_xhstt_xml(instance: Instance, constraints: minidom.Element, root: minidom.Document, includeNewConstraints: bool):
    for constraintType in instance.Constraints.keys():
        if not includeNewConstraints and (constraintType == XHSTTConstraintConstants.STUDENT_CHOICE_CONSTRAINT or constraintType == XHSTTConstraintConstants.BALANCE_CLASS_SIZE_CONSTRAINT):
            continue
        for constraint in instance.Constraints[constraintType]:
            constraintChild = root.createElement(constraintType)
            constraints.appendChild(constraintChild)
            constraintChild.setAttribute("Id", constraint[XHSTTFileConstants.ID])
            name = root.createElement("Name")
            name.appendChild(root.createTextNode(constraint[XHSTTFileConstants.NAME]))
            constraintChild.appendChild(name)
            required = root.createElement("Required")
            if constraint[XHSTTConstraintConstants.REQUIRED]:
                required.appendChild(root.createTextNode("true"))
            else:
                required.appendChild(root.createTextNode("false"))
            constraintChild.appendChild(required)
            if XHSTTConstraintConstants.CONSIDER_UNASSIGNED_RESOURCES in constraint:
                considerUnassignedResources = root.createElement(XHSTTConstraintConstants.CONSIDER_UNASSIGNED_RESOURCES)
                if constraint[XHSTTConstraintConstants.CONSIDER_UNASSIGNED_RESOURCES]:
                    considerUnassignedResources.appendChild(root.createTextNode("true"))
                else:
                    considerUnassignedResources.appendChild(root.createTextNode("false"))
                constraintChild.appendChild(considerUnassignedResources)
            weight = root.createElement("Weight")
            weight.appendChild(root.createTextNode(str(constraint[XHSTTConstraintConstants.WEIGHT])))
            constraintChild.appendChild(weight)
            costFunction = root.createElement("CostFunction")
            costFunction.appendChild(root.createTextNode(constraint[XHSTTConstraintConstants.COST_FUNCTION]))
            constraintChild.appendChild(costFunction)
            if XHSTTConstraintConstants.APPLIES_TO in constraint.keys():
                appliesTo = root.createElement("AppliesTo")
                constraintChild.appendChild(appliesTo)

                if XHSTTFileConstants.EVENT_GROUPS in constraint[XHSTTConstraintConstants.APPLIES_TO].keys():
                    eventGroups = root.createElement("EventGroups")
                    appliesTo.appendChild(eventGroups)
                    for eventGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
                        eventGroupChild = root.createElement("EventGroup")
                        eventGroupChild.setAttribute(XHSTTFileConstants.REFERENCE_NO_AT, eventGroup)
                        eventGroups.appendChild(eventGroupChild)

                if XHSTTFileConstants.EVENT_PAIRS in constraint[XHSTTConstraintConstants.APPLIES_TO].keys():
                    eventPairs = root.createElement("EventPairs")
                    appliesTo.appendChild(eventPairs)
                    for eventPair in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_PAIRS]:
                        eventPairChild = root.createElement("EventPair")
                        eventPairs.appendChild(eventPairChild)
                        firstEventChild = root.createElement("FirstEvent")
                        firstEventChild.setAttribute(XHSTTFileConstants.REFERENCE_NO_AT, eventPair[XHSTTFileConstants.FIRST_EVENT])
                        secondEventChild = root.createElement("SecondEvent")
                        secondEventChild.setAttribute(XHSTTFileConstants.REFERENCE_NO_AT,
                                                     eventPair[XHSTTFileConstants.SECOND_EVENT])
                        minimum = root.createElement("MinSeparation")
                        minimum.appendChild(root.createTextNode(str(eventPair["MinSeparation"])))
                        maximum = root.createElement("MaxSeparation")
                        maximum.appendChild(root.createTextNode(str(eventPair["MaxSeparation"])))
                        eventPairChild.appendChild(firstEventChild)
                        eventPairChild.appendChild(secondEventChild)
                        eventPairChild.appendChild(minimum)
                        eventPairChild.appendChild(maximum)


                if (XHSTTFileConstants.EVENTS in constraint[XHSTTConstraintConstants.APPLIES_TO].keys() and
                        constraintType != XHSTTConstraintConstants.AVOID_SPLIT_ASSIGNMENTS_CONSTRAINT and
                        constraintType != XHSTTConstraintConstants.SPREAD_EVENTS_CONSTRAINT and
                        constraintType != XHSTTConstraintConstants.LINK_EVENTS_CONSTRAINT):
                    events = root.createElement("Events")
                    appliesTo.appendChild(events)
                    for event in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS]:
                        eventChild = root.createElement("Event")
                        eventChild.setAttribute(XHSTTFileConstants.REFERENCE_NO_AT, event)
                        events.appendChild(eventChild)

                if XHSTTFileConstants.RESOURCE_GROUPS in constraint[XHSTTConstraintConstants.APPLIES_TO].keys():
                    resourceGroups = root.createElement("ResourceGroups")
                    appliesTo.appendChild(resourceGroups)
                    for resourceGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCE_GROUPS]:
                        resourceGroupChild = root.createElement("ResourceGroup")
                        resourceGroupChild.setAttribute(XHSTTFileConstants.REFERENCE_NO_AT, resourceGroup)
                        resourceGroups.appendChild(resourceGroupChild)

                if XHSTTFileConstants.RESOURCES in constraint[XHSTTConstraintConstants.APPLIES_TO].keys():
                    resources = root.createElement("Resources")
                    appliesTo.appendChild(resources)
                    for resource in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCES]:
                        resourceChild = root.createElement("Resource")
                        resourceChild.setAttribute(XHSTTFileConstants.REFERENCE_NO_AT, resource)
                        resources.appendChild(resourceChild)

            if XHSTTFileConstants.EVENT_GROUPS in constraint.keys():
                eventGroups = root.createElement("EventGroups")
                constraintChild.appendChild(eventGroups)
                for eventGroup in constraint[XHSTTFileConstants.EVENT_GROUPS]:
                    eventGroupChild = root.createElement("EventGroup")
                    eventGroupChild.setAttribute(XHSTTFileConstants.REFERENCE_NO_AT, eventGroup)
                    eventGroups.appendChild(eventGroupChild)

            if XHSTTFileConstants.EVENTS in constraint.keys():
                events = root.createElement("Events")
                constraintChild.appendChild(events)
                for event in constraint[XHSTTFileConstants.EVENTS]:
                    eventChild = root.createElement("Event")
                    eventChild.setAttribute(XHSTTFileConstants.REFERENCE_NO_AT, event)
                    events.appendChild(eventChild)

            if XHSTTFileConstants.RESOURCE_GROUPS in constraint.keys():
                resourceGroups = root.createElement("ResourceGroups")
                constraintChild.appendChild(resourceGroups)
                for resourceGroup in constraint[XHSTTFileConstants.RESOURCE_GROUPS]:
                    resourceGroupChild = root.createElement("ResourceGroup")
                    resourceGroupChild.setAttribute(XHSTTFileConstants.REFERENCE_NO_AT, resourceGroup)
                    resourceGroups.appendChild(resourceGroupChild)

            if XHSTTFileConstants.RESOURCES in constraint.keys():
                resources = root.createElement("Resources")
                constraintChild.appendChild(resources)
                for resource in constraint[XHSTTFileConstants.RESOURCES]:
                    resourceChild = root.createElement("Resource")
                    resourceChild.setAttribute(XHSTTFileConstants.REFERENCE_NO_AT, resource)
                    resources.appendChild(resourceChild)

            if XHSTTFileConstants.TIME_GROUPS in constraint.keys():
                timeGroups = root.createElement("TimeGroups")
                constraintChild.appendChild(timeGroups)
                for timeGroup in constraint[XHSTTFileConstants.TIME_GROUPS]:
                    if isinstance(timeGroup, dict):
                        timeGroupChild = root.createElement("TimeGroup")
                        timeGroupChild.setAttribute(XHSTTFileConstants.REFERENCE_NO_AT, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT])
                        timeGroups.appendChild(timeGroupChild)
                        if XHSTTConstraintConstants.MINIMUM in timeGroup.keys():
                            minimum = root.createElement("Minimum")
                            minimum.appendChild(root.createTextNode(str(timeGroup[XHSTTConstraintConstants.MINIMUM])))
                            timeGroupChild.appendChild(minimum)
                        if XHSTTConstraintConstants.MAXIMUM in timeGroup.keys():
                            maximum = root.createElement("Maximum")
                            maximum.appendChild(root.createTextNode(str(timeGroup[XHSTTConstraintConstants.MAXIMUM])))
                            timeGroupChild.appendChild(maximum)
                    else:
                        timeGroupChild = root.createElement("TimeGroup")
                        timeGroupChild.setAttribute(XHSTTFileConstants.REFERENCE_NO_AT, timeGroup)
                        timeGroups.appendChild(timeGroupChild)

            if XHSTTFileConstants.TIMES in constraint.keys() and (constraintType != XHSTTConstraintConstants.SPREAD_EVENTS_CONSTRAINT and
                constraintType != XHSTTConstraintConstants.LIMIT_IDLE_TIMES_CONSTRAINT and
                constraintType != XHSTTConstraintConstants.CLUSTER_BUSY_TIMES_CONSTRAINT and
                constraintType != XHSTTConstraintConstants.LIMIT_BUSY_TIMES_CONSTRAINT):
                times = root.createElement("Times")
                constraintChild.appendChild(times)
                for t in constraint[XHSTTFileConstants.TIMES]:
                    timeChild = root.createElement("Time")
                    timeChild.setAttribute(XHSTTFileConstants.REFERENCE_NO_AT, t)
                    times.appendChild(timeChild)

            if XHSTTConstraintConstants.DURATION in constraint.keys():
                duration = root.createElement("Duration")
                duration.appendChild(root.createTextNode(str(constraint[XHSTTConstraintConstants.DURATION])))
                constraintChild.appendChild(duration)

            if XHSTTConstraintConstants.MINIMUM in constraint.keys():
                minimum = root.createElement("Minimum")
                minimum.appendChild(root.createTextNode(str(constraint[XHSTTConstraintConstants.MINIMUM])))
                constraintChild.appendChild(minimum)
            if XHSTTConstraintConstants.MAXIMUM in constraint.keys():
                maximum = root.createElement("Maximum")
                maximum.appendChild(root.createTextNode(str(constraint[XHSTTConstraintConstants.MAXIMUM])))
                constraintChild.appendChild(maximum)

            if XHSTTConstraintConstants.MINIMUM_DURATION in constraint.keys():
                minimumDuration = root.createElement("MinimumDuration")
                minimumDuration.appendChild(root.createTextNode(str(constraint[XHSTTConstraintConstants.MINIMUM_DURATION])))
                constraintChild.appendChild(minimumDuration)
            if XHSTTConstraintConstants.MAXIMUM_DURATION in constraint.keys():
                maximumDuration = root.createElement("MaximumDuration")
                maximumDuration.appendChild(root.createTextNode(str(constraint[XHSTTConstraintConstants.MAXIMUM_DURATION])))
                constraintChild.appendChild(maximumDuration)
            if XHSTTConstraintConstants.MINIMUM_AMOUNT in constraint.keys():
                minimumAmount = root.createElement("MinimumAmount")
                minimumAmount.appendChild(root.createTextNode(str(constraint[XHSTTConstraintConstants.MINIMUM_AMOUNT])))
                constraintChild.appendChild(minimumAmount)
            if XHSTTConstraintConstants.MAXIMUM_AMOUNT in constraint.keys():
                maximumAmount = root.createElement("MaximumAmount")
                maximumAmount.appendChild(root.createTextNode(str(constraint[XHSTTConstraintConstants.MAXIMUM_AMOUNT])))
                constraintChild.appendChild(maximumAmount)
            if XHSTTConstraintConstants.MAXIMUM_DIFFERENCE in constraint.keys():
                maximumDifference = root.createElement("MaximumDifference")
                maximumDifference.appendChild(root.createTextNode(str(constraint[XHSTTConstraintConstants.MAXIMUM_DIFFERENCE])))
                constraintChild.appendChild(maximumDifference)

            if XHSTTConstraintConstants.TYPE in constraint.keys():
                type = root.createElement("Type")
                type.appendChild(root.createTextNode(str(constraint[XHSTTConstraintConstants.TYPE])))
                constraintChild.appendChild(type)

            if XHSTTConstraintConstants.ROLE in constraint.keys():
                role = root.createElement("Role")
                role.appendChild(root.createTextNode(str(constraint[XHSTTConstraintConstants.ROLE])))
                constraintChild.appendChild(role)

def write_output(dataFilePath: str, solutionData: dict, instance: Instance, directory="xhstt"):
    if directory.startswith('data/'):
        directory = directory[5:]
    solutionFilename = f"{dataFilePath}/solution_files/{directory}/{solutionData[XHSTTFileConstants.FILE_NAME]}_{uuid.uuid4()}"
    problemFilename = f"{dataFilePath}/{directory}/{solutionData[XHSTTFileConstants.FILE_NAME]}"

    root = minidom.Document()
    xml = root.createElement(SolutionFileConstants.SOLUTION_GROUP)
    xml.setAttribute(SolutionFileConstants.ID, solutionData[SolutionDataConstants.ID])
    root.appendChild(xml)

    metadata = _create_metadata_XML_element(root, solutionData)
    xml.appendChild(metadata)

    solution = root.createElement(SolutionFileConstants.SOLUTION)
    solution.setAttribute(XHSTTFileConstants.REFERENCE_NO_AT, solutionData[SolutionDataConstants.INSTANCE_ID])
    xml.appendChild(solution)
    description = root.createElement(SolutionDataConstants.DESCRIPTION)
    description.appendChild(root.createTextNode(solutionData[SolutionDataConstants.DESCRIPTION]))
    solution.appendChild(description)
    runningTime = root.createElement(SolutionDataConstants.RUNNING_TIME)
    runningTime.appendChild(root.createTextNode(solutionData[SolutionDataConstants.RUNNING_TIME]))
    solution.appendChild(runningTime)

    events = _create_events_XML_element(root, solutionData)
    solution.appendChild(events)

    report = root.createElement(SolutionFileConstants.REPORT)
    solution.appendChild(report)


    resourceDataFrames = _create_resource_dataframe(instance, solutionData)
    xml_str_solution = root.toprettyxml(indent="\t")
    os.makedirs(os.path.dirname(solutionFilename), exist_ok=True)
    _write_solution_to_excel_file(resourceDataFrames, solutionFilename)
    _write_solution_to_xml_file(solutionData, xml, xml_str_solution, solutionFilename,
                                modifyProblemInstance=True, problemFilename=problemFilename)


def _create_metadata_XML_element(root: minidom.Document, solutionData: dict) -> minidom.Element:
    metadata = root.createElement(SolutionFileConstants.METADATA)
    metadataContributor = root.createElement(SolutionFileConstants.CONTRIBUTOR)
    metadataContributor.appendChild(root.createTextNode("IMC KREMS"))
    metadataDate = root.createElement(SolutionFileConstants.DATE)
    metadataDate.appendChild(root.createTextNode(SolutionFileConstants.PLACEHOLDER))
    metadataDescription = root.createElement(SolutionDataConstants.DESCRIPTION)
    metadataDescription.appendChild(
        root.createTextNode("Objective Value: {:.5f}".format(solutionData[SolutionDataConstants.OBJECTIVE_VALUE])))
    metadataPublication = root.createElement(SolutionFileConstants.PUBLICATION)
    metadataPublication.appendChild(root.createTextNode(SolutionFileConstants.PLACEHOLDER))
    metadataRemarks = root.createElement(SolutionFileConstants.REMARKS)
    metadataRemarks.appendChild(root.createTextNode(SolutionFileConstants.PLACEHOLDER))
    metadata.appendChild(metadataContributor)
    metadata.appendChild(metadataDate)
    metadata.appendChild(metadataDescription)
    metadata.appendChild(metadataPublication)
    metadata.appendChild(metadataRemarks)

    return metadata

def _create_events_XML_element(root: minidom.Document, solutionData: dict) -> minidom.Element:
    events = root.createElement(XHSTTFileConstants.EVENTS)
    for event in solutionData[XHSTTFileConstants.EVENTS].keys():
        if solutionData[XHSTTFileConstants.EVENTS][event][XHSTTFileConstants.TIME] == ILPConstants.DUMMY_TIME and \
                len([resource for resource in solutionData[XHSTTFileConstants.EVENTS][event][XHSTTFileConstants.RESOURCES].keys()
                     if solutionData[XHSTTFileConstants.EVENTS][event][XHSTTFileConstants.RESOURCES][resource] != ILPConstants.DUMMY_RESOURCE and
                        XHSTTFileConstants.NO_ROLE not in resource]) == 0:
            continue
        eventChild = root.createElement(XHSTTFileConstants.EVENT)
        eventChild.setAttribute(XHSTTFileConstants.REFERENCE_NO_AT, event[0])
        eventChildDuration = root.createElement(XHSTTFileConstants.DURATION)
        eventChildDuration.appendChild(root.createTextNode(str(solutionData[XHSTTFileConstants.EVENTS][event][XHSTTFileConstants.DURATION])))
        eventChildTime = root.createElement(XHSTTFileConstants.TIME)
        eventChildTime.setAttribute(XHSTTFileConstants.REFERENCE_NO_AT, solutionData[XHSTTFileConstants.EVENTS][event][XHSTTFileConstants.TIME])
        eventChildResources = root.createElement(XHSTTFileConstants.RESOURCES)
        for resource in solutionData[XHSTTFileConstants.EVENTS][event][XHSTTFileConstants.RESOURCES].keys():
            if solutionData[XHSTTFileConstants.EVENTS][event][XHSTTFileConstants.RESOURCES][resource] != ILPConstants.DUMMY_RESOURCE and XHSTTFileConstants.NO_ROLE not in resource:
                eventChildResourcesResource = root.createElement(XHSTTFileConstants.RESOURCE)
                eventChildResourcesResource.setAttribute(XHSTTFileConstants.REFERENCE_NO_AT, solutionData[XHSTTFileConstants.EVENTS][event][XHSTTFileConstants.RESOURCES][resource])
                eventChildResourcesResourceRole = root.createElement(XHSTTFileConstants.ROLE)
                eventChildResourcesResourceRole.appendChild(root.createTextNode(resource))
                eventChildResourcesResource.appendChild(eventChildResourcesResourceRole)
                eventChildResources.appendChild(eventChildResourcesResource)
        eventChild.appendChild(eventChildDuration)
        if solutionData[XHSTTFileConstants.EVENTS][event][XHSTTFileConstants.TIME] != ILPConstants.DUMMY_TIME:
            eventChild.appendChild(eventChildTime)
        eventChild.appendChild(eventChildResources)
        events.appendChild(eventChild)

    return events
def _create_resource_dataframe(instance: Instance, solutionData: dict) -> DataFrame:
    resourceTimetables = _create_resource_timetables(instance, solutionData)

    eventsPerTimeDict = _create_events_per_time_dict(solutionData, resourceTimetables)

    resourceDataFrames = DataFrame(index=list(resourceTimetables.keys()), data=eventsPerTimeDict)

    return resourceDataFrames

def _create_resource_timetables(instance: Instance, solutionData: dict) -> dict:
    resourceTimetables = dict()
    for event in solutionData[XHSTTFileConstants.EVENTS].keys():
        for resourceType in instance.Resources.ResourceGroupsByType.keys():
            resourceTimetables.setdefault(resourceType, list())
            for resource in instance.Resources.IndividualResources.keys():
                if instance.Resources.IndividualResources[resource].Type == resourceType:
                    resourceTimetables.setdefault(resource, list())
        for resource in solutionData[XHSTTFileConstants.EVENTS][event][XHSTTFileConstants.RESOURCES].keys():
            if solutionData[XHSTTFileConstants.EVENTS][event][XHSTTFileConstants.RESOURCES][resource] != ILPConstants.DUMMY_RESOURCE and solutionData[XHSTTFileConstants.EVENTS][event][
                XHSTTFileConstants.TIME] != ILPConstants.DUMMY_TIME:
                if solutionData[XHSTTFileConstants.EVENTS][event][XHSTTFileConstants.RESOURCES][resource] in resourceTimetables.keys():
                    resourceTimetables[solutionData[XHSTTFileConstants.EVENTS][event][XHSTTFileConstants.RESOURCES][resource]].append(
                        solutionData[XHSTTFileConstants.EVENTS][event])
                else:
                    print(f"Warning cant add event {event} to timetable of resource {solutionData[XHSTTFileConstants.EVENTS][event][XHSTTFileConstants.RESOURCES][resource]}")

    for resource in resourceTimetables.keys():
        resourceTimetables[resource].sort(key=lambda a: solutionData[SolutionDataConstants.SORTED_TIMES].index(a[XHSTTFileConstants.TIME]))

    return resourceTimetables

def _create_events_per_time_dict(solutionData: dict, resourceTimetables: dict) -> dict:
    eventsPerTimeDict = dict()
    for time_slot in solutionData[SolutionDataConstants.SORTED_TIMES]:
        eventsPerTimeDict[time_slot] = list()

    for resource in resourceTimetables.keys():
        for time_slot in solutionData[SolutionDataConstants.SORTED_TIMES]:
            listOfEventsAtTimeSlotForResource = list()
            for event in resourceTimetables[resource]:
                eventTimeIndex = solutionData[SolutionDataConstants.SORTED_TIMES].index(event[XHSTTFileConstants.TIME])
                if time_slot in solutionData[SolutionDataConstants.SORTED_TIMES][
                           eventTimeIndex: min(eventTimeIndex + int(event[XHSTTFileConstants.DURATION]), len(solutionData[SolutionDataConstants.SORTED_TIMES]))]:
                    listOfEventsAtTimeSlotForResource.append(event[SolutionDataConstants.NAME])
            eventsPerTimeDict[time_slot].append(" ".join(listOfEventsAtTimeSlotForResource))

    return eventsPerTimeDict

def _write_solution_to_excel_file(resourceDataFrames: DataFrame, solutionFilename: str):
    resourceDataFrames.to_excel(solutionFilename[:-4] + ".xlsx", sheet_name="Timetables", index=True)

def _write_solution_to_xml_file(solutionData: dict, XMLObject: minidom.Element, solutionXMLString: str, solutionFilename: str, modifyProblemInstance=False, problemFilename=None):
    with open(solutionFilename, "w") as f:
        f.write(solutionXMLString)
    if modifyProblemInstance:
        lock_path = problemFilename + ".lock"
        lock = FileLock(lock_path, timeout=120)
        with lock:
            success = False
            counter = 0
            while not success and counter < 100:
                try:
                    problemInstanceXML: minidom.Document = minidom.parse(problemFilename)
                    success = True
                except:
                    time.sleep(2)
                    counter += 1
                    success = False
            if not success:
                print(f"Error: Could not parse {problemFilename}")
                return
            solutionGroups = \
            problemInstanceXML.getElementsByTagName(SolutionFileConstants.HIGH_SCHOOL_TIMETABLE_ARCHIVE)[0].getElementsByTagName(SolutionFileConstants.SOLUTION_GROUPS)[
                0]
            try:
                success = False
                for oldSolutionGroup in solutionGroups.getElementsByTagName(SolutionFileConstants.SOLUTION_GROUP):
                    oldSolutionGroupSolution = oldSolutionGroup.getElementsByTagName("Solution")[-1]
                    if solutionData[SolutionDataConstants.INSTANCE_ID] in dict(oldSolutionGroupSolution.attributes.items()).values():
                        solutionGroups.replaceChild(XMLObject, oldSolutionGroup)
                        success = True
                if not success:
                    solutionGroups.appendChild(XMLObject)
            except:
                solutionGroups.appendChild(XMLObject)
            xml_str_problem = problemInstanceXML.toprettyxml(indent="\t")
            # Remove extra newlines added by toprettyxml
            xml_str_problem = '\n'.join([s for s in xml_str_problem.splitlines() if s.strip()])
            counter = 0
            while counter < 100:
                try:
                    with open(problemFilename, "w") as f:
                        f.write(xml_str_problem)
                    return
                except:
                    time.sleep(2)
                    counter += 1
        print(f"Error: Could not write {problemFilename}")

def create_untis_readable_solution(filepath: str, original_untis_xml_file: str, solution_identifier: str, solutionData: dict, instance: Instance, file_unterricht: list):
    exisitingEvents = list(instance.Events.IndividualEvents.keys())
    listOfTimes = list(instance.Times.IndividualTimes.keys())
    original_untis_xml_file_with_umlaut = original_untis_xml_file.split('.xml')[0] + "_with_umlaut.xml"
    xml_file_with_umlaut = io.open(f"{filepath}/{original_untis_xml_file_with_umlaut}", "r", encoding="utf8", errors="backslashreplace").read()
    file_as_dict_with_umlaut = xmltodict.parse(xml_file_with_umlaut)['document']
    noUmlautToUmlautDict = process_nested_dict(file_as_dict_with_umlaut, dict())
    eventToSolutionEventsDict = dict()
    for event in exisitingEvents:
        if len(event.split('_')) > 2:
            eventID = f"{event.split('_')[0]}_{event.split('_')[1]}"
        else:
            eventID = event
        eventToSolutionEventsDict[eventID] = list()
    for event in solutionData[XHSTTFileConstants.EVENTS].keys():
        if len(event[0].split('_')) > 2:
            eventID = f"{event[0].split('_')[0]}_{event[0].split('_')[1]}"
        else:
            eventID = event[0]
        if solutionData[XHSTTFileConstants.EVENTS][event] not in eventToSolutionEventsDict[eventID]:
            eventToSolutionEventsDict[eventID].append(solutionData[XHSTTFileConstants.EVENTS][event])
    timeToTimeIdentifierDict = dict()
    for time_period in file_as_dict_with_umlaut[UNTISConstants.TIMEPERIODS][UNTISConstants.TIMEPERIOD]:
        identifierDict = dict()
        identifierDict["assigned_day"] = time_period["day"]
        identifierDict["assigned_period"] = time_period["period"]
        identifierDict["assigned_starttime"] = time_period["starttime"]
        identifierDict["assigned_endtime"] = time_period["endtime"]
        timeToTimeIdentifierDict[time_period[UNTISConstants.ID]] = identifierDict
    # Untis events may be split into multiple events from our perspective with 01 02 etc suffix
    # we have to correctly assign our solution resources (rooms and students) to the various events
    roomResources = [resource for resource in instance.Resources.IndividualResources.keys() if instance.Resources.IndividualResources[resource].Type == XHSTTFileConstants.ROOM]
    studentResources = [resource for resource in instance.Resources.IndividualResources.keys() if
                        instance.Resources.IndividualResources[resource].Type == XHSTTFileConstants.STUDENT and resource.startswith("ST_")]
    allLessonIDsInUntis = set()
    for lesson in file_as_dict_with_umlaut[UNTISConstants.LESSONS][UNTISConstants.LESSON]:
        allLessonIDsInUntis.add(lesson[UNTISConstants.ID])
    eventsInNewSolution = set()
    idToNumberAppearances = dict()
    lesson_list = list()
    idToGivenRoom = dict()
    idToSeenClassesCombination = dict()
    lessonIDToClassesDict = dict()
    for unterrichtOriginal in file_unterricht:
        unterricht = list(unterrichtOriginal)
        lessonID = unterricht[0]
        if len(unterricht[4]) > 0:
            lessonIDToClassesDict.setdefault(lessonID, set()).add("CL_" + unterricht[4][1:-1])
        else:
            lessonIDToClassesDict.setdefault(lessonID, set())
    for unterricht in file_unterricht:
        lessonID = unterricht[0]
        idToSeenClassesCombination.setdefault(lessonID, set())
        if len(idToSeenClassesCombination[lessonID]) == 0:
            idToSeenClassesCombination[lessonID].add(unterricht[4])
        if unterricht[4] not in idToSeenClassesCombination[lessonID]:
            idToSeenClassesCombination[lessonID].add(unterricht[4])
            continue
        else:
            idToSeenClassesCombination[lessonID] = {unterricht[4]}
        idToNumberAppearances.setdefault(lessonID, 0)
        if idToNumberAppearances[lessonID] < 10:
            eventID = f"LS_{str(lessonID)}0{str(idToNumberAppearances[lessonID])}"
        else:
            eventID = f"LS_{str(lessonID)}{str(idToNumberAppearances[lessonID])}"
        solutionEventID = f"LS_{str(lessonID)}00"
        idToNumberAppearances[lessonID] += 1
        idToGivenRoom.setdefault(lessonID, set())
        if len(unterricht[7]) > 0:
            if unterricht[7] in [pair[1] for pair in idToGivenRoom[lessonID]]:
                roomsToUse = [pair[0] for pair in idToGivenRoom[lessonID] if pair[1] == unterricht[7]][0]
            else:
                roomsToUse = eventID
                idToGivenRoom[lessonID].add((eventID, unterricht[7]))
        else:
            roomsToUse = None
        lesson = dict()
        lesson[UNTISConstants.ID] = eventID
        lesson["periods"] = math.ceil(float(unterricht[1]))
        if len(unterricht[6]) > 0:
            lesson["lesson_subject"] = dict()
            lesson["lesson_subject"][UNTISConstants.ID] = f"SU_{unterricht[6][1:-1]}"
        else:
            lesson["lesson_subject"] = dict()
            lesson["lesson_subject"][UNTISConstants.ID] = ""
        if len(unterricht[5]) > 0:
            lesson["lesson_teacher"] = dict()
            lesson["lesson_teacher"][UNTISConstants.ID] = f"TR_{unterricht[5][1:-1]}"
        else:
            lesson["lesson_teacher"] = dict()
            lesson["lesson_teacher"][UNTISConstants.ID] = ""
        if len(lessonIDToClassesDict[unterricht[0]]) > 0:
            lesson["lesson_classes"] = dict()
            lesson["lesson_classes"][UNTISConstants.ID] = " ".join(lessonIDToClassesDict[unterricht[0]])
        if solutionEventID not in instance.Events.IndividualEvents.keys() or solutionEventID not in eventToSolutionEventsDict or len(eventToSolutionEventsDict[solutionEventID]) == 0:
            if solutionEventID not in instance.Events.IndividualEvents.keys():
                lesson["flags"] = "I"
            lesson["timegrid"] = "Haupt-Zeitraster"
            if len(unterricht[38]) > 0:
                lesson["teacher_value"] = unterricht[38]
            if len(unterricht[41]) > 0:
                lesson["lesson_studentgroups"] = dict()
                lesson["lesson_studentgroups"][UNTISConstants.ID] = " ".join(
                    [f"SG_{studentGroup}" for studentGroup in unterricht[41][1:-1].split('~')])
            if len(unterricht[14]) > 0:
                lesson["effectivebegindate"] = unterricht[14]
            if len(unterricht[15]) > 0:
                lesson["effectiveenddate"] = unterricht[15]
            if len(unterricht[29]) > 0:
                lesson["block"] = unterricht[29]
            elif int(lesson["periods"]) > 1:
                lesson["block"] = "2"
            if len(unterricht[17]) > 0:
                lesson["text"] = unterricht[17][1:-1]
            if len(unterricht[38]) > 0:
                lesson["text2"] = unterricht[38][1:-1]
                lesson["foreignkey"] = unterricht[38][1:-1]
            if eventID not in eventsInNewSolution:
                timeDict = dict()
                timeDict["time"] = list()
                lesson["times"] = timeDict
            else:
                timeDict = lesson["times"]
            lesson_list.append(lesson)
            continue
        firstSolutionEvent = list(eventToSolutionEventsDict[solutionEventID])[0]
        lesson["timegrid"] = "Haupt-Zeitraster"
        if len(unterricht[38]) > 0:
            lesson["teacher_value"] = unterricht[38]
        if len(unterricht[41]) > 0:
            lesson["lesson_studentgroups"] = dict()
            lesson["lesson_studentgroups"][UNTISConstants.ID] = " ".join(
                [f"SG_{studentGroup}" for studentGroup in unterricht[41][1:-1].split('~')])
        if "max_requirement_Lesson Student_0" in firstSolutionEvent[
            XHSTTFileConstants.RESOURCES].keys() or "min_requirement_Lesson Student_0" in firstSolutionEvent[
            XHSTTFileConstants.RESOURCES].keys():
            studentListOfEvent = list()
            for role in firstSolutionEvent[XHSTTFileConstants.RESOURCES].keys():
                if firstSolutionEvent[XHSTTFileConstants.RESOURCES][role] in studentResources:
                    studentListOfEvent.append(firstSolutionEvent[XHSTTFileConstants.RESOURCES][role])
            if "lesson_students" not in lesson:
                lesson["lesson_students"] = dict()
            lesson["lesson_students"][UNTISConstants.ID] = " ".join(studentListOfEvent)
        if len(unterricht[14]) > 0:
            lesson["effectivebegindate"] = unterricht[14]
        if len(unterricht[15]) > 0:
            lesson["effectiveenddate"] = unterricht[14]
        if len(unterricht[29]) > 0:
            lesson["block"] = unterricht[29]
        elif int(lesson["periods"]) > 1:
            lesson["block"] = "2"
        if len(unterricht[17]) > 0:
            lesson["text"] = unterricht[17][1:-1]
        if len(unterricht[38]) > 0:
            lesson["text2"] = unterricht[38][1:-1]
            lesson["foreignkey"] = unterricht[38][1:-1]
        if eventID not in eventsInNewSolution:
            timeDict = dict()
            timeDict["time"] = list()
            lesson["times"] = timeDict
        else:
            timeDict = lesson["times"]
        eventsInNewSolution.add(eventID)
        for solutionEvent in eventToSolutionEventsDict[solutionEventID]:
            if solutionEvent[XHSTTFileConstants.TIME] is None or solutionEvent[
                XHSTTFileConstants.TIME] == ILPConstants.DUMMY_TIME:
                continue
            indexOfTime = listOfTimes.index(solutionEvent[XHSTTFileConstants.TIME])
            usedTimes = listOfTimes[indexOfTime:indexOfTime + int(solutionEvent[XHSTTFileConstants.ID][1][0])]
            for used_time in usedTimes:
                assignedTime = timeToTimeIdentifierDict[used_time].copy()
                usedRooms = list()
                for role in solutionEvent[XHSTTFileConstants.RESOURCES].keys():
                    if solutionEvent[XHSTTFileConstants.RESOURCES][role] in roomResources and role.split('_')[1] == \
                            lesson[UNTISConstants.ID][-2:]:
                        usedRoom = solutionEvent[XHSTTFileConstants.RESOURCES][role]
                        if usedRoom in noUmlautToUmlautDict:
                            usedRooms.append(noUmlautToUmlautDict[usedRoom])
                        else:
                            usedRooms.append(usedRoom)
                if len(usedRooms) != 0 and roomsToUse is not None and roomsToUse == eventID:
                    assignedTime["assigned_room"] = dict()
                    assignedTime["assigned_room"][UNTISConstants.ID] = " ".join(usedRooms)
                elif roomsToUse is not None and roomsToUse != eventID:
                    assignedTime["assigned_room"] = dict()
                    list2 = [lessonObject for lessonObject in lesson_list if lessonObject[UNTISConstants.ID] == roomsToUse and "times" in lessonObject and "time" in lessonObject["times"]]
                    roomList = [timeObject["assigned_room"][UNTISConstants.ID] for lessonObject in list2 for timeObject in lessonObject["times"]["time"] if timeObject["assigned_day"] == assignedTime["assigned_day"] and timeObject["assigned_period"] == assignedTime["assigned_period"] and "assigned_room" in timeObject]
                    if len(roomList) > 0:
                        assignedTime["assigned_room"][UNTISConstants.ID] = roomList[0]
                timeDict["time"].append(assignedTime)
        lesson_list.append(lesson)
    file_unterricht_with_extra_ignore_flags = copy.deepcopy(file_unterricht)
    for unterricht in file_unterricht_with_extra_ignore_flags:
        fixedLessonsStartingWithUnterrichtID = [eventID for eventID in instance.Events.IndividualEvents.keys() if eventID.startswith(f"LS_{unterricht[0]}00_")]
        if f"LS_{unterricht[0]}00" not in instance.Events.IndividualEvents.keys() and len(fixedLessonsStartingWithUnterrichtID) == 0:
            if len(unterricht[23]) == 0:
                unterricht[23] = '"I"'
            else:
                unterricht[23] = f'{unterricht[23][:-1]}I"'
    file_as_dict_with_umlaut[UNTISConstants.LESSONS][UNTISConstants.LESSON] = lesson_list
    output_file = f"{filepath}/{original_untis_xml_file.split('.xml')[0]}{solution_identifier}.xml"
    output_file_GPU002 = f"{filepath}/GPU002{solution_identifier}.txt"
    print(f"Output path: {output_file}")
    file_as_dict_with_single_key = dict()
    file_as_dict_with_single_key["document"] = file_as_dict_with_umlaut
    with open(output_file, "w", encoding='utf-8') as f:
        text = xmltodict.unparse(file_as_dict_with_single_key, encoding='utf-8', pretty=True)
        f.write(text)
    with open(output_file_GPU002, "w", encoding='utf-8') as f:
        for unterricht in file_unterricht_with_extra_ignore_flags:
            f.write(f"{','.join(unterricht)}\n")



def process_nested_dict(file_as_dict_with_umlaut: dict, noUmlautToUmlautDict: dict) -> dict:
    """
    Recursively processes a nested dictionary.
    Applies german letter transformation to string values and creates dict between umlaut words and non umlaut words.
    """
    replacements = {
        'ä': 'ae',
        'ö': 'oe',
        'ü': 'ue',
        'ß': 'ss',
    }
    for key, value in file_as_dict_with_umlaut.items():
        if isinstance(value, dict):
            process_nested_dict(value, noUmlautToUmlautDict)
        elif isinstance(value, list):
            for element in value:
                process_nested_dict(element, noUmlautToUmlautDict)
        elif isinstance(value, str):
            if any(char in value for char in replacements):
                valueCopy = str(value)
                for original, replacement in replacements.items():
                    valueCopy = valueCopy.replace(original, replacement)
                noUmlautToUmlautDict[valueCopy] = value
    return noUmlautToUmlautDict


def update_file_with_filtered_solutions(filepath: str, fileName: str):
    file_path = os.path.join(filepath, fileName)

    with io.open(file_path, "r", encoding="utf8", errors="backslashreplace") as f:
        file_content = f.read()

    file_as_dict = xmltodict.parse(file_content)
    archive = file_as_dict.get(SolutionFileConstants.HIGH_SCHOOL_TIMETABLE_ARCHIVE, {})
    solution_groups_container = archive.get(SolutionFileConstants.SOLUTION_GROUPS, {})

    solutionGroupIdentifiers = ["_SA_", "_khe", "_3MSA_", "_e_opt"]

    # xmltodict parses single elements as dicts and multiple as lists
    raw_groups = solution_groups_container.get(SolutionFileConstants.SOLUTION_GROUP, [])
    groups = [raw_groups] if isinstance(raw_groups, dict) else raw_groups

    filtered_groups = []
    for solution_group in groups:
        # Retrieve the solution element(s)
        solution = solution_group.get(SolutionFileConstants.SOLUTION, {})
        solutions = [solution] if isinstance(solution, dict) else solution

        # Check if any reference contains an identifier to filter out
        should_remove = False
        for sol in solutions:
            ref = sol.get(XHSTTFileConstants.REFERENCE_WITH_AT, "") if isinstance(sol, dict) else ""
            if any(identifier in ref for identifier in solutionGroupIdentifiers):
                should_remove = True
                break

        if not should_remove:
            filtered_groups.append(solution_group)

    # Update solution groups in dictionary
    solution_groups_container[SolutionFileConstants.SOLUTION_GROUP] = filtered_groups

    # Save file overwriting the old one
    xml_output = xmltodict.unparse(file_as_dict, pretty=True)
    with io.open(file_path, "w", encoding="utf8") as f:
        f.write(xml_output)