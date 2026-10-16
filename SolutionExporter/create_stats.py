import os
import sys
sys.path.append('../XHSTTImporter')
from Instance import Instance
import xhstt_input_reader
import solution_reader
from XHSTTImporter.Constants import XHSTTFileConstants
from XHSTTImporter.Constants import XHSTTConstraintConstants
sys.path.append('../validator')
import validator
from split_constraints import split_constraints_into_smaller_constraints

instanceIDToNameDict = dict()
instanceIDToNameDict["test1_Ungerade_Halbjahr1.xml"] = "GermanyRHPF1"
instanceIDToNameDict["test2_Ungerade_Halbjahr1.xml"] = "GermanyHAMB1"
instanceIDToNameDict["test3_Ungerade.xml"] = "GermanyNRWE1"
instanceIDToNameDict["test4_Ungerade.xml"] = "GermanyHAMB2"
instanceIDToNameDict["test5_Ungerade.xml"] = "GermanyNRWE2"
instanceIDToNameDict["test6_Halbjahr1.xml"] = "GermanyRHPF2"
instanceIDToNameDict["test7_Halbjahr1.xml"] = "GermanyRHPF3"
instanceIDToNameDict["test8_Ungerade.xml"] = "GermanyNRWE3"
instanceIDToNameDict["test9.xml"] = "GermanyNRWE4"
instanceIDToNameDict["test10.xml"] = "GermanyRHPF4"
instanceIDToNameDict["test11.xml"] = "GermanySAAR1"
instanceIDToNameDict["test12_Ungerade.xml"] = "GermanyRHPF5"
instanceIDToNameDict["test13.xml"] = "GermanyRHPF6"
instanceIDToNameDict["test14_Ungerade_Halbjahr1.xml"] = "GermanyBAWU1"
instanceIDToNameDict["test15_Ungerade_Halbjahr1.xml"] = "GermanyBAWU2"
instanceIDToNameDict["test16_Ungerade_Halbjahr1.xml"] = "GermanyBAWU3"
instanceIDToNameDict["test17_Ungerade_Halbjahr1.xml"] = "GermanyBAWU4"
instanceIDToNameDict["test18_Ungerade_Halbjahr1.xml"] = "GermanyHESS1"
def write_stats(instanceName: str, instance: Instance):
    numberOfEvents = len([event for event in instance.Events.IndividualEvents.keys() if not event.endswith('_requirement')])
    totalEventDuration = sum([int(instance.Events.IndividualEvents[event].Duration) for event in instance.Events.IndividualEvents.keys()])
    totalEventDurationTimesAssignablesResources = sum([int(instance.Events.IndividualEvents[event].Duration) * (len(instance.Events.IndividualEvents[event].EventResources.AssignedResources) + len(instance.Events.IndividualEvents[event].EventResources.UnassignedResources)) for event in instance.Events.IndividualEvents.keys()])
    if XHSTTFileConstants.STUDENT not in instance.Resources.ResourceGroupsByType:
        numberOfStudents = 0
    else:
        numberOfStudents = len([student for student in instance.Resources.ResourceGroupsByType[XHSTTFileConstants.STUDENT].ResourceGroups[XHSTTFileConstants.ALL_STUDENTS].Resources if not "PseudoStudent" in student])
    if XHSTTFileConstants.TEACHER not in instance.Resources.ResourceGroupsByType:
        numberOfTeachers = 0
    else:
        numberOfTeachers = len([teacher for teacher in
                            instance.Resources.ResourceGroupsByType[XHSTTFileConstants.TEACHER].ResourceGroups[
                                XHSTTFileConstants.ALL_TEACHERS].Resources])
    if XHSTTFileConstants.STUDENT not in instance.Resources.ResourceGroupsByType:
        numberOfClasses = 0
    else:
        numberOfClasses = len([student for student in
                                instance.Resources.ResourceGroupsByType[XHSTTFileConstants.STUDENT].ResourceGroups[
                                    XHSTTFileConstants.ALL_STUDENTS].Resources if "PseudoStudent" in student])
    if XHSTTFileConstants.CLASS in instance.Resources.ResourceGroupsByType:
        numberOfClasses += len([resource for resource in instance.Resources.IndividualResources.keys() if instance.Resources.IndividualResources[resource].Type == XHSTTFileConstants.CLASS])

    if XHSTTFileConstants.ROOM not in instance.Resources.ResourceGroupsByType:
        numberOfRooms = 0
    else:
        numberOfRooms = len([resource for resource in instance.Resources.IndividualResources.keys() if instance.Resources.IndividualResources[resource].Type == XHSTTFileConstants.ROOM])

    if XHSTTConstraintConstants.STUDENT_CHOICE_CONSTRAINT in instance.Constraints:
        numberOfStudentChoices = len([constraint for constraint in instance.Constraints[XHSTTConstraintConstants.STUDENT_CHOICE_CONSTRAINT]])
        eventsWithStudentAssignments = {eventGroup for constraint in instance.Constraints[XHSTTConstraintConstants.STUDENT_CHOICE_CONSTRAINT] for eventGroup in constraint[XHSTTFileConstants.EVENT_GROUPS]}
    else:
        numberOfStudentChoices = 0
        eventsWithStudentAssignments = {}
    if XHSTTConstraintConstants.BALANCE_CLASS_SIZE_CONSTRAINT not in instance.Constraints.keys():
        numberOfBalanceConstraints = 0
    else:
        numberOfBalanceConstraints = len(
            [constraint for constraint in instance.Constraints[XHSTTConstraintConstants.BALANCE_CLASS_SIZE_CONSTRAINT]])
    numberOfEventsWithStudentAssignments = len(eventsWithStudentAssignments)
    numberOfRolesForStudentAssignments = len([eventResource for event in instance.Events.IndividualEvents.keys() for eventResource in instance.Events.IndividualEvents[event].EventResources.UnassignedResources if 'requirement' in eventResource.Role])
    if instanceName in instanceIDToNameDict.keys():
        instanceName = instanceIDToNameDict[instanceName]
    print(f"{instanceName} & {numberOfEvents} & {numberOfStudents} & {numberOfClasses} & {numberOfTeachers} & {numberOfRooms} \\\\")
    print(f"{instanceName} & {totalEventDuration} & {totalEventDurationTimesAssignablesResources}")
    print(f"{instanceName} & {numberOfStudentChoices} & {numberOfBalanceConstraints} & {numberOfEventsWithStudentAssignments} & {numberOfRolesForStudentAssignments} \\\\")

def write_stats_for_all_test_instances():
    rootdir = 'data/untis/untisXHSTTFinalInstances'
    filesToUse = list()
    for subdir, dirs, files in os.walk(rootdir):
        for file in files:
            if file.endswith('.xml'):
                instance = xhstt_input_reader.read_XHSTT_input_file(subdir, file)
                split_constraints_into_smaller_constraints(instance)
                filesToUse.append((str(file), instance))

    sorted_FilesToUse = sorted(filesToUse, key=lambda x: int(x[0].split('_')[0].split('test')[1].split('.xml')[0]))
    for file in sorted_FilesToUse:
        write_stats(file[0], file[1])

def output_objective_value_for_all_solution_groups(filename):
    if 'untis' in str(filename):
        instanceOldFormat = xhstt_input_reader.read_XHSTT_input_file('../data/untis', filename)
        solutions = solution_reader.get_all_solution_group_ids('../data/untis', filename)
    else:
        instanceOldFormat = xhstt_input_reader.read_XHSTT_input_file('../data/xhstt', filename)
        solutions = solution_reader.get_all_solution_group_ids('../data/xhstt', filename)
    for solution in solutions:
        if 'untis' in str(filename):
            read_solution = solution_reader.read_solution('../data/untis', str(filename), solution,
                                                          instanceOldFormat)
        else:
            read_solution = solution_reader.read_solution('../data/xhstt', str(filename), solution,
                                                          instanceOldFormat)
        print("Solution Group " + solution + ":")
        validator.get_objective_value(instanceOldFormat, read_solution, outputObjectiveValues=True)

if __name__ == "__main__":
    write_stats_for_all_test_instances()