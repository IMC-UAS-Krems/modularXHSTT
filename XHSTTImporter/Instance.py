import random
import pickle
import sys
sys.path.append('XHSTTImporter')
from Constants import InstanceParameterDictConstants, XHSTTFileConstants, XHSTTConstraintConstants


class XHSTTInstance:
    def __init__(self, processedXHSTTdict: dict):
        self.Metadata = processedXHSTTdict[XHSTTFileConstants.METADATA]
        self.Resources = Resources(processedXHSTTdict[XHSTTFileConstants.RESOURCES])
        self.Times = Times(processedXHSTTdict[XHSTTFileConstants.TIMES])
        self.Events = Events(processedXHSTTdict[XHSTTFileConstants.EVENTS])
        self.Constraints = processedXHSTTdict[XHSTTFileConstants.CONSTRAINTS]


class Instance(XHSTTInstance):
    """
    Instance has the following format:
    Instance
        Metadata (dict)
        Resources
            ResourceGroupsByType (dict of ResourceType)
                ResourceGroups (dict of Resource Group)
                    Name
                    Resources (List of Ids)
            IndividualResources (dict of Resource)
                Name
                Type
                ResourceGroups (list of Ids)
        Times
            Days (dict of TimeGroup)
                Name
                Times (list of Ids)
            TimeGroups (dict of TimeGroup)
                Name
                Times (list of Ids)
            IndividualTimes (dict of Time)
                Name
                Day
                TimeGroups (list of Ids)
        Events
            EventGroups (dict of EventGroup)
                Name
                Events (list of Ids)
            IndividualEvents (dict of Event)
                Name
                Duration
                Time
                EventResources
                    AssignedResources (dict of EventResource)
                        Workload
                        ResourceType
                    UnassignedResources (dict of EventResource)
                        Workload
                        ResourceType
                EventGroups (list of Ids)
        Constraints (dict of ConstrainTypes)
            List of Constraint specific individual dicts (e.g. instance.Constraints[XHSTTConstraintConstants.ASSIGN_RESOURCE_CONSTRAINT][0] would
            be a dict describing an individual AssignResourceConstraint)
    """

    def __init__(self, xhsttInstance: XHSTTInstance, parameterDict: dict, seed: int = 1234):
        self.Metadata = xhsttInstance.Metadata
        self.Resources = xhsttInstance.Resources
        self.Times = xhsttInstance.Times
        self.Events = xhsttInstance.Events
        self.Constraints = xhsttInstance.Constraints
        self._transform_XHSTT_to_our_format(parameterDict, seed)

    def save_to_pickle_file(self, filename: str):
        file = open(f"../data/xhstt/{filename}", 'wb')
        pickle.dump(self, file, pickle.HIGHEST_PROTOCOL)

    def _transform_XHSTT_to_our_format(self, parameterDict: dict, seed: int = 1234):
        minStudentsPerClass = parameterDict[InstanceParameterDictConstants.MIN_STUDENTS_PER_CLASS]
        maxStudentsPerClass = parameterDict[InstanceParameterDictConstants.MAX_STUDENTS_PER_CLASS]
        numberOfClassesWithoutFixedStudentAssignment = parameterDict[
            InstanceParameterDictConstants.NUMBER_CLASSES_NO_FIXED_STUDENT_ASSIGNMENT]
        random.seed(seed)
        self._add_additionally_required_resource_groups()

        totalStudents = self._transform_classes_from_resources_to_resource_groups_return_total_added_students(
            minStudentsPerClass, maxStudentsPerClass)

        # If there are not enough students to fulfill the minimum amount of students per class add extra students
        if totalStudents <= minStudentsPerClass:
            self._add_additionally_required_students(totalStudents, minStudentsPerClass)

        eventsThatNeedStudentAssignment = self._generate_events_for_classes_that_have_no_students_assigned_return_event_list(
            numberOfClassesWithoutFixedStudentAssignment, maxStudentsPerClass)

        self._change_events_to_specify_students_instead_of_classes()

        self._move_classes_from_resources_to_resource_groups_for_all_constraints()

        self._add_basic_constraints_for_newly_created_events()

        self._add_new_constraints_for_modular_events(parameterDict, eventsThatNeedStudentAssignment)

        self._delete_resources_of_type_class()

        self._replace_all_occurances_of_ALL_CLASSES_resource_group()

    def _replace_all_occurances_of_ALL_CLASSES_resource_group(self):
        resourceGroupsByType = self.Resources.ResourceGroupsByType
        if XHSTTFileConstants.ALL_CLASSES in resourceGroupsByType[XHSTTFileConstants.STUDENT].ResourceGroups:
            del resourceGroupsByType[XHSTTFileConstants.STUDENT].ResourceGroups[XHSTTFileConstants.ALL_CLASSES]
            for constraintType in self.Constraints.keys():
                for constraint in self.Constraints[constraintType]:
                    if XHSTTConstraintConstants.APPLIES_TO in constraint.keys():
                        if XHSTTFileConstants.RESOURCE_GROUPS in constraint[XHSTTConstraintConstants.APPLIES_TO].keys():
                            resourceGroupApplications = constraint[XHSTTConstraintConstants.APPLIES_TO][
                                XHSTTFileConstants.RESOURCE_GROUPS]
                            for i in range(len(resourceGroupApplications)):
                                if resourceGroupApplications[i] == XHSTTFileConstants.ALL_CLASSES:
                                    resourceGroupApplications[i] = XHSTTFileConstants.ALL_STUDENTS

    def _delete_resources_of_type_class(self):
        individualResources = self.Resources.IndividualResources
        resourceGroupsByType = self.Resources.ResourceGroupsByType
        for individualClass in [resource for resource in individualResources.keys() if
                                individualResources[resource].Type == XHSTTFileConstants.CLASS]:
            del individualResources[individualClass]
        if XHSTTFileConstants.CLASS in resourceGroupsByType:
            del resourceGroupsByType[XHSTTFileConstants.CLASS]

    def _add_new_constraints_for_modular_events(self, parameterDict,
                                                eventsThatNeedStudentAssignment: list):
        minStudentsPerClass = parameterDict[InstanceParameterDictConstants.MIN_STUDENTS_PER_CLASS]
        maxStudentsPerClass = parameterDict[InstanceParameterDictConstants.MAX_STUDENTS_PER_CLASS]
        numberOfClassesWithoutFixedStudentAssignment = parameterDict[
            InstanceParameterDictConstants.NUMBER_CLASSES_NO_FIXED_STUDENT_ASSIGNMENT]
        balanceClassSizes = parameterDict[InstanceParameterDictConstants.BALANCE_CLASS_SIZES]
        maxClassSizeDifference = parameterDict[InstanceParameterDictConstants.MAX_CLASS_SIZE_DIFFERENCE]
        numberOfNoOverlapConstraints = parameterDict[InstanceParameterDictConstants.NUMBER_OF_NO_OVERLAP_CONSTRAINTS]
        constraintWeights = parameterDict[InstanceParameterDictConstants.CONSTRAINT_WEIGHTS]
        costFunctions = parameterDict[InstanceParameterDictConstants.COST_FUNCTIONS]

        self.Constraints[XHSTTConstraintConstants.STUDENT_ASSIGNMENT_CONSTRAINT] = list()
        self.add_StudentAssignmentConstraint('AssignStudents', False,
                                             constraintWeights[XHSTTConstraintConstants.STUDENT_ASSIGNMENT_CONSTRAINT],
                                             costFunctions[XHSTTConstraintConstants.STUDENT_ASSIGNMENT_CONSTRAINT],
                                             [XHSTTFileConstants.MODULAR_EVENT_GROUP_ID], [], minStudentsPerClass, maxStudentsPerClass)
        self.Constraints[XHSTTConstraintConstants.NO_OVERLAP_CONSTRAINT] = list()
        counter = 0
        for i in range(len(eventsThatNeedStudentAssignment)):
            if counter >= numberOfNoOverlapConstraints:
                break
            for j in range(i + 1, len(eventsThatNeedStudentAssignment)):
                if counter >= numberOfNoOverlapConstraints:
                    break
                self.add_NoOverlapConstraint('NoOverlap' + str(counter), True,
                                             constraintWeights[XHSTTConstraintConstants.NO_OVERLAP_CONSTRAINT],
                                             costFunctions[XHSTTConstraintConstants.NO_OVERLAP_CONSTRAINT],
                                             [], [eventsThatNeedStudentAssignment[i],
                                                  eventsThatNeedStudentAssignment[j]], [
                                                 XHSTTFileConstants.ALL_STUDENTS], [])
                counter += 1

        self.Constraints[XHSTTConstraintConstants.BALANCE_CLASS_SIZE_CONSTRAINT] = list()
        if balanceClassSizes:
            self.add_BalanceClassSizeConstraint('BalanceClassSize0', False,
                                                constraintWeights[XHSTTConstraintConstants.BALANCE_CLASS_SIZE_CONSTRAINT],
                                                costFunctions[XHSTTConstraintConstants.BALANCE_CLASS_SIZE_CONSTRAINT],
                                                [XHSTTFileConstants.MODULAR_EVENT_GROUP_ID], [], maxClassSizeDifference)

        self.Constraints[XHSTTConstraintConstants.STUDENT_CHOICE_CONSTRAINT] = list()
        MINIMUM_FULFILLED_CHOICES = 2
        TOTAL_AMOUNT_STUDENTS_WITH_PREFERENCES = ((numberOfClassesWithoutFixedStudentAssignment *
                                                   (minStudentsPerClass + maxStudentsPerClass) // 2)
                                                  // MINIMUM_FULFILLED_CHOICES)
        for student in self.Resources.ResourceGroupsByType[XHSTTFileConstants.STUDENT].ResourceGroups[
                           XHSTTFileConstants.ALL_STUDENTS].Resources[
                       :TOTAL_AMOUNT_STUDENTS_WITH_PREFERENCES]:
            preferedEvents = random.choices(
                ["modularEvent_" + str(i) for i in range(numberOfClassesWithoutFixedStudentAssignment)], k=3)
            self.add_StudentChoiceConstraint('StudentChoice_' + str(student), False,
                                             constraintWeights[XHSTTConstraintConstants.STUDENT_CHOICE_CONSTRAINT],
                                             costFunctions[XHSTTConstraintConstants.STUDENT_CHOICE_CONSTRAINT], [], preferedEvents, [],
                                             [student], 2, 3)

    def _add_basic_constraints_for_newly_created_events(self):
        self.add_AssignTimeConstraint('AssignTimeModular', True, 10, XHSTTConstraintConstants.LINEAR, [
            XHSTTFileConstants.MODULAR_EVENT_GROUP_ID], [])
        self.add_AssignResourceConstraint('AssignResourceModularTeachers', True, 10, XHSTTConstraintConstants.LINEAR, [
            XHSTTFileConstants.MODULAR_EVENT_GROUP_ID],
                                          [], 'Class_Teacher')
        self.add_AssignResourceConstraint('AssignResourceModularRooms', True, 10, XHSTTConstraintConstants.LINEAR, [
            XHSTTFileConstants.MODULAR_EVENT_GROUP_ID],
                                          [],
                                          'Class_Room')
        self.add_SplitEventsConstraint('DontSplitModular', True, 10, XHSTTConstraintConstants.LINEAR, [
            XHSTTFileConstants.MODULAR_EVENT_GROUP_ID], [], 1, 1, 1, 5)

    def _add_additionally_required_resource_groups(self):
        resourceGroupsByType = self.Resources.ResourceGroupsByType
        individualResources = self.Resources.IndividualResources
        # Create Resource Group that will contain all individual Students
        if XHSTTFileConstants.STUDENT not in resourceGroupsByType.keys():
            resourceGroupsByType[XHSTTFileConstants.STUDENT] = ResourceType({XHSTTFileConstants.RESOURCE_GROUPS:
                                                                               {XHSTTFileConstants.ALL_STUDENTS:
                                                                                    {
                                                                                        XHSTTFileConstants.NAME: XHSTTFileConstants.ALL_STUDENTS,
                                                                                        XHSTTFileConstants.RESOURCES: []}}})
        else:
            resourceGroupsByType[XHSTTFileConstants.STUDENT].ResourceGroups[XHSTTFileConstants.ALL_STUDENTS] = ResourceGroup(
                {
                    XHSTTFileConstants.NAME: XHSTTFileConstants.ALL_STUDENTS,
                    XHSTTFileConstants.RESOURCES: [student for student in individualResources.keys() if
                                                   individualResources[student].Type == XHSTTFileConstants.STUDENT]
                }
            )
            for student in individualResources.keys():
                if individualResources[student].Type == XHSTTFileConstants.STUDENT:
                    individualResources[student].ResourceGroups.append(XHSTTFileConstants.ALL_STUDENTS)

        # Add a resource Group of Students for each Class Resource Group
        if XHSTTFileConstants.CLASS in resourceGroupsByType:
            for resourceGroup in resourceGroupsByType[XHSTTFileConstants.CLASS].ResourceGroups.keys():
                resourceGroupsByType[XHSTTFileConstants.STUDENT].ResourceGroups[resourceGroup] = ResourceGroup(
                    {XHSTTFileConstants.NAME: resourceGroup,
                     XHSTTFileConstants.RESOURCES: []})

    def _add_additionally_required_students(self, totalStudents: int, minStudentsPerClass: int):
        for i in range(totalStudents, minStudentsPerClass):
            studentId = "STUD" + str(totalStudents)
            student = Resource({XHSTTFileConstants.NAME: XHSTTFileConstants.STUDENT + str(totalStudents), XHSTTFileConstants.TYPE: XHSTTFileConstants.STUDENT,
                                XHSTTFileConstants.RESOURCE_GROUPS: [XHSTTFileConstants.ALL_STUDENTS]})
            self.Resources.IndividualResources[studentId] = student
            resourceGroupContainingAllStudents = self.Resources.ResourceGroupsByType[XHSTTFileConstants.STUDENT].ResourceGroups[
                XHSTTFileConstants.ALL_STUDENTS]
            resourceGroupContainingAllStudents.Resources.append(studentId)
            totalStudents += 1

    def _transform_classes_from_resources_to_resource_groups_return_total_added_students(self, minStudentsPerClass: int,
                                                                                         maxStudentsPerClass: int) -> int:
        totalStudents = 0
        individualResources = self.Resources.IndividualResources
        studentResourceGroups = self.Resources.ResourceGroupsByType[XHSTTFileConstants.STUDENT].ResourceGroups
        for individualClass in [resource for resource in individualResources.keys() if
                                individualResources[resource].Type == XHSTTFileConstants.CLASS]:
            studentResourceGroups[individualClass] = ResourceGroup(
                {XHSTTFileConstants.NAME: individualResources[individualClass].Name,
                 XHSTTFileConstants.RESOURCES: []})

            resourceGroupsOfClass = individualResources[individualClass].ResourceGroups

            # Create Individual Student Resources and assign them to XHSTTFileConstants.ALL_STUDENTS Resource Group, Resource Group of
            # the individual Class, and all Resource Groups that the original Class was part of
            for i in range(random.randint(minStudentsPerClass, maxStudentsPerClass)):
                studentId = "STUD" + str(totalStudents)
                student = Resource({XHSTTFileConstants.NAME: XHSTTFileConstants.STUDENT + str(totalStudents), XHSTTFileConstants.TYPE: XHSTTFileConstants.STUDENT,
                                    XHSTTFileConstants.RESOURCE_GROUPS: [XHSTTFileConstants.ALL_STUDENTS, individualClass] + resourceGroupsOfClass})
                individualResources[studentId] = student
                studentResourceGroups[XHSTTFileConstants.ALL_STUDENTS].Resources.append(studentId)
                studentResourceGroups[individualClass].Resources.append(studentId)
                for resourceGroup in resourceGroupsOfClass:
                    studentResourceGroups[resourceGroup].Resources.append(studentId)
                totalStudents += 1
        return totalStudents

    def _generate_events_for_classes_that_have_no_students_assigned_return_event_list(self,
                                                                                      numberOfClassesWithoutFixedStudentAssignment: int,
                                                                                      maxStudentsPerClass) -> list[str]:
        eventsThatNeedStudentAssignment = list()
        self.Events.EventGroups[XHSTTFileConstants.MODULAR_EVENT_GROUP_ID] = EventGroup({
            XHSTTFileConstants.NAME: XHSTTFileConstants.MODULAR_EVENT_GROUP_ID,
            XHSTTFileConstants.EVENTS: []
        })
        for i in range(numberOfClassesWithoutFixedStudentAssignment):
            classId = "modularEvent_" + str(i)
            self.Events.IndividualEvents[classId] = Event({
                XHSTTFileConstants.NAME: "modularEvent_" + str(i),
                XHSTTFileConstants.DURATION: random.randint(1, 2),
                XHSTTFileConstants.TIME: None,
                XHSTTFileConstants.RESOURCES: {
                    XHSTTFileConstants.ASSIGNED_RESOURCES: [],
                    XHSTTFileConstants.UNASSIGNED_RESOURCES: []
                },
                XHSTTFileConstants.EVENT_GROUPS: [XHSTTFileConstants.MODULAR_EVENT_GROUP_ID]
            })
            assignedResourcesOfClass = self.Events.IndividualEvents[classId].EventResources.AssignedResources
            unassignedResourcesOfClass = self.Events.IndividualEvents[classId].EventResources.UnassignedResources
            if XHSTTFileConstants.TEACHER in self.Resources.ResourceGroupsByType.keys():
                assignedResourcesOfClass.append(
                    EventResource({
                        XHSTTFileConstants.REFERENCE_NO_AT: random.choice(
                            self.Resources.ResourceGroupsByType[XHSTTFileConstants.TEACHER].ResourceGroups[
                                XHSTTFileConstants.ALL_TEACHERS].Resources),
                        XHSTTFileConstants.ROLE: "Class_Teacher",
                        XHSTTFileConstants.RESOURCE_TYPE: XHSTTFileConstants.TEACHER
                    })
                )
            if XHSTTFileConstants.ROOM in self.Resources.ResourceGroupsByType.keys():
                unassignedResourcesOfClass.append(
                    EventResource({
                        XHSTTFileConstants.ROLE: "Class_Room",
                        XHSTTFileConstants.RESOURCE_TYPE: XHSTTFileConstants.ROOM
                    })
                )
            for j in range(maxStudentsPerClass):
                unassignedResourcesOfClass.append(
                    EventResource({
                        XHSTTFileConstants.ROLE: "Student_Attendee_" + str(j),
                        XHSTTFileConstants.RESOURCE_TYPE: XHSTTFileConstants.STUDENT
                    })
                )
            self.Events.EventGroups[XHSTTFileConstants.MODULAR_EVENT_GROUP_ID].Events.append(classId)
            eventsThatNeedStudentAssignment.append(classId)
        return eventsThatNeedStudentAssignment

    def _change_events_to_specify_students_instead_of_classes(self):
        studentResourceGroups = self.Resources.ResourceGroupsByType[XHSTTFileConstants.STUDENT].ResourceGroups
        for event in self.Events.IndividualEvents.keys():
            assignedResourcesOfEvent = self.Events.IndividualEvents[event].EventResources.AssignedResources
            eventClassResources: list[EventResource] = [eventResource for eventResource in assignedResourcesOfEvent
                                                        if self.Resources.IndividualResources[
                                                            eventResource.Reference].Type == XHSTTFileConstants.CLASS]

            for eventResource in eventClassResources:
                for student in studentResourceGroups[eventResource.Reference].Resources:
                    assignedResourcesOfEvent.append(
                        EventResource({
                            XHSTTFileConstants.REFERENCE_NO_AT: student,
                            XHSTTFileConstants.WORKLOAD: eventResource.Workload,
                            XHSTTFileConstants.RESOURCE_TYPE: XHSTTFileConstants.STUDENT
                        })
                    )
                self.Events.IndividualEvents[event].EventResources.AssignedResources.remove(eventResource)

    def _move_classes_from_resources_to_resource_groups_for_all_constraints(self):
        for constraintType in self.Constraints.keys():
            for constraint in self.Constraints[constraintType]:
                if XHSTTConstraintConstants.APPLIES_TO in constraint.keys():
                    constraintApplications = constraint[XHSTTConstraintConstants.APPLIES_TO]
                    if XHSTTFileConstants.RESOURCES in constraintApplications.keys():
                        classResources = [resource for resource in constraintApplications[XHSTTFileConstants.RESOURCES] if
                                          self.Resources.IndividualResources[resource].Type == XHSTTFileConstants.CLASS]

                        for resource in classResources:
                            constraintApplications[XHSTTFileConstants.RESOURCES].remove(resource)
                            constraintApplications[XHSTTFileConstants.RESOURCE_GROUPS].append(resource)

    def add_AssignResourceConstraint(self, name: str, required: bool, weight: int, costFunction: str,
                                     eventGroups: list[str], events: list[str], role: str):
        self.Constraints[XHSTTConstraintConstants.ASSIGN_RESOURCE_CONSTRAINT].append({
            XHSTTFileConstants.ID: name,
            XHSTTConstraintConstants.NAME: name,
            XHSTTConstraintConstants.REQUIRED: required,
            XHSTTConstraintConstants.WEIGHT: weight,
            XHSTTConstraintConstants.COST_FUNCTION: costFunction,
            XHSTTConstraintConstants.APPLIES_TO: {
                XHSTTFileConstants.EVENT_GROUPS: eventGroups,
                XHSTTFileConstants.EVENTS: events
            },
            XHSTTFileConstants.ROLE: role
        })

    def add_AssignTimeConstraint(self, name: str, required: bool, weight: int, costFunction: str,
                                 eventGroups: list[str], events: list[str]):
        self.Constraints[XHSTTConstraintConstants.ASSIGN_TIME_CONSTRAINT].append({
            XHSTTFileConstants.ID: name,
            XHSTTConstraintConstants.NAME: name,
            XHSTTConstraintConstants.REQUIRED: required,
            XHSTTConstraintConstants.WEIGHT: weight,
            XHSTTConstraintConstants.COST_FUNCTION: costFunction,
            XHSTTConstraintConstants.APPLIES_TO: {
                XHSTTFileConstants.EVENT_GROUPS: eventGroups,
                XHSTTFileConstants.EVENTS: events
            }
        })

    def add_SplitEventsConstraint(self, name: str, required: bool, weight: int, costFunction: str,
                                  eventGroups: list[str], events: list[str], minAmount: int, maxAmount: int,
                                  minDuration: int, maxDuration: int):
        self.Constraints[XHSTTConstraintConstants.SPLIT_EVENTS_CONSTRAINT].append({
            XHSTTFileConstants.ID: name,
            XHSTTFileConstants.NAME: name,
            XHSTTConstraintConstants.REQUIRED: required,
            XHSTTConstraintConstants.WEIGHT: weight,
            XHSTTConstraintConstants.COST_FUNCTION: costFunction,
            XHSTTConstraintConstants.APPLIES_TO: {
                XHSTTFileConstants.EVENT_GROUPS: eventGroups,
                XHSTTFileConstants.EVENTS: events,
            },
            XHSTTConstraintConstants.MINIMUM_AMOUNT: minAmount,
            XHSTTConstraintConstants.MAXIMUM_AMOUNT: maxAmount,
            XHSTTConstraintConstants.MINIMUM_DURATION: minDuration,
            XHSTTConstraintConstants.MAXIMUM_DURATION: maxDuration
        })

    def add_BalanceClassSizeConstraint(self, name: str, required: bool, weight: int, costFunction: str,
                                       eventGroups: list[str], events: list[str], maxDifference: int):
        self.Constraints[XHSTTConstraintConstants.BALANCE_CLASS_SIZE_CONSTRAINT].append({
            XHSTTFileConstants.ID: name,
            XHSTTFileConstants.NAME: name,
            XHSTTConstraintConstants.REQUIRED: required,
            XHSTTConstraintConstants.WEIGHT: weight,
            XHSTTConstraintConstants.COST_FUNCTION: costFunction,
            XHSTTConstraintConstants.APPLIES_TO: {
                XHSTTFileConstants.EVENT_GROUPS: eventGroups,
                XHSTTFileConstants.EVENTS: events
            },
            XHSTTConstraintConstants.MAXIMUM_DIFFERENCE: maxDifference
        })

    def add_StudentChoiceConstraint(self, name: str, required: bool, weight: int, costFunction: str,
                                    eventGroups: list[str], events: list[str],
                                    resourceGroups: list[str], resources: list[str], minimum: int, maximum: int):
        self.Constraints[XHSTTConstraintConstants.STUDENT_CHOICE_CONSTRAINT].append({
            XHSTTFileConstants.ID: name,
            XHSTTFileConstants.NAME: name,
            XHSTTConstraintConstants.REQUIRED: required,
            XHSTTConstraintConstants.WEIGHT: weight,
            XHSTTConstraintConstants.COST_FUNCTION: costFunction,
            XHSTTConstraintConstants.APPLIES_TO: {
                XHSTTFileConstants.RESOURCE_GROUPS: resourceGroups,
                XHSTTFileConstants.RESOURCES: resources
            },
            XHSTTFileConstants.EVENT_GROUPS: eventGroups,
            XHSTTFileConstants.EVENTS: events,
            XHSTTConstraintConstants.MINIMUM: minimum,
            XHSTTConstraintConstants.MAXIMUM: maximum
        })


class Resources:
    def __init__(self, resourceDict: dict):
        self.ResourceGroupsByType: dict[str, ResourceType] = resourceDict[XHSTTFileConstants.RESOURCE_GROUPS_BY_TYPE]
        for resourceType in self.ResourceGroupsByType.keys():
            self.ResourceGroupsByType[resourceType]: ResourceType = ResourceType(
                self.ResourceGroupsByType[resourceType])
        self.IndividualResources: dict[str, Resource] = resourceDict[XHSTTFileConstants.INDIVIDUAL_RESOURCES]
        for resource in self.IndividualResources.keys():
            self.IndividualResources[resource]: Resource = Resource(self.IndividualResources[resource])


class ResourceType:
    def __init__(self, resourceTypeDict: dict):
        self.ResourceGroups: dict[str, ResourceGroup] = resourceTypeDict[XHSTTFileConstants.RESOURCE_GROUPS]
        for resourceGroup in self.ResourceGroups.keys():
            self.ResourceGroups[resourceGroup] = ResourceGroup(self.ResourceGroups[resourceGroup])


class ResourceGroup:
    def __init__(self, resourceGroupDict: dict):
        if XHSTTFileConstants.TOTAL_STUDENTS in resourceGroupDict:
            self.TotalStudents: int = int(resourceGroupDict[XHSTTFileConstants.TOTAL_STUDENTS])
        else:
            self.TotalStudents: int = 0
        self.Name: str = resourceGroupDict[XHSTTFileConstants.NAME]
        self.Resources: list[str] = resourceGroupDict[XHSTTFileConstants.RESOURCES]


class Resource:
    def __init__(self, resourceDict: dict):
        self.Name: str = resourceDict[XHSTTFileConstants.NAME]
        self.Type: str = resourceDict[XHSTTFileConstants.TYPE]
        self.ResourceGroups: list[str] = resourceDict[XHSTTFileConstants.RESOURCE_GROUPS]


class Times:
    def __init__(self, timesDict: dict):
        self.Days: dict[str, TimeGroup] = timesDict[XHSTTFileConstants.DAYS]
        for day in self.Days.keys():
            self.Days[day]: TimeGroup = TimeGroup(self.Days[day])
        self.TimeGroups: dict[str, TimeGroup] = timesDict[XHSTTFileConstants.TIME_GROUPS]
        for timeGroup in self.TimeGroups.keys():
            self.TimeGroups[timeGroup]: TimeGroup = TimeGroup(self.TimeGroups[timeGroup])
        self.IndividualTimes: dict[str, Time] = timesDict[XHSTTFileConstants.INDIVIDUAL_TIMES]
        for time in self.IndividualTimes.keys():
            self.IndividualTimes[time]: Time = Time(self.IndividualTimes[time])


class TimeGroup:
    def __init__(self, timeGroupDict: dict):
        self.Name: str = timeGroupDict[XHSTTFileConstants.NAME]
        self.Times: list[str] = timeGroupDict[XHSTTFileConstants.TIMES]


class Time:
    def __init__(self, timeDict: dict):
        self.Name: str = timeDict[XHSTTFileConstants.NAME]
        self.Day: str = timeDict[XHSTTFileConstants.DAY]
        self.TimeGroups: list[str] = timeDict[XHSTTFileConstants.TIME_GROUPS]


class Events:
    def __init__(self, eventsDict: dict):
        self.EventGroups: dict[str, EventGroup] = eventsDict[XHSTTFileConstants.EVENT_GROUPS]
        for eventGroup in self.EventGroups.keys():
            self.EventGroups[eventGroup]: EventGroup = EventGroup(self.EventGroups[eventGroup])
        self.IndividualEvents: dict[str, Event] = eventsDict[XHSTTFileConstants.INDIVIDUAL_EVENTS]
        for event in self.IndividualEvents.keys():
            self.IndividualEvents[event]: Event = Event(self.IndividualEvents[event])


class EventGroup:
    def __init__(self, eventGroupDict: dict):
        self.Name: str = eventGroupDict[XHSTTFileConstants.NAME]
        self.Events: list[str] = eventGroupDict[XHSTTFileConstants.EVENTS]


class Event:
    def __init__(self, eventDict: dict):
        self.Name: str = eventDict[XHSTTFileConstants.NAME]
        self.Duration: int = eventDict[XHSTTFileConstants.DURATION]
        self.Time: str = eventDict[XHSTTFileConstants.TIME]
        self.EventResources: EventResources = EventResources(eventDict[XHSTTFileConstants.RESOURCES])
        self.EventGroups: list[str] = eventDict[XHSTTFileConstants.EVENT_GROUPS]


class EventResources:
    def __init__(self, eventResourcesDict: dict):
        self.AssignedResources: list[EventResource] = list()
        for resource in eventResourcesDict[XHSTTFileConstants.ASSIGNED_RESOURCES]:
            self.AssignedResources.append(EventResource(resource))
        self.UnassignedResources: list[EventResource] = list()
        for resource in eventResourcesDict[XHSTTFileConstants.UNASSIGNED_RESOURCES]:
            self.UnassignedResources.append(EventResource(resource))


class EventResource:
    def __init__(self, eventResourcesDict: dict):
        if XHSTTFileConstants.REFERENCE_NO_AT in eventResourcesDict:
            self.Reference: str = eventResourcesDict[XHSTTFileConstants.REFERENCE_NO_AT]
        else:
            self.Reference: str = None
        if XHSTTFileConstants.ROLE in eventResourcesDict:
            self.Role = eventResourcesDict[XHSTTFileConstants.ROLE]
        else:
            self.Role = None
        if XHSTTFileConstants.WORKLOAD in eventResourcesDict:
            self.Workload: int = eventResourcesDict[XHSTTFileConstants.WORKLOAD]
        else:
            self.Workload: int = 0
        if XHSTTFileConstants.RESOURCE_TYPE in eventResourcesDict:
            self.ResourceType = eventResourcesDict[XHSTTFileConstants.RESOURCE_TYPE]
        else:
            self.ResourceType = None
