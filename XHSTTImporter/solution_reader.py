import copy
import io
import xmltodict
import math
import uuid
import statistics
import sys
sys.path.append('XHSTTImporter')
sys.path.append('../XHSTTImporter')
import solution_reader
from Instance import Instance
sys.path.append('XHSTTImporter/Constants')
sys.path.append('../XHSTTImporter/Constants')
import XHSTTFileConstants
sys.path.append('SolutionExporter')
sys.path.append('../SolutionExporter')
import SolutionFileConstants
import SolutionDataConstants
sys.path.append('ILP_solver')
sys.path.append('../ILP_solver')
import ILPConstants
import UNTISConstants
from generate_heuristic_solution import HeuristicSolutionGenerator
sys.path.append('validator')
sys.path.append('../validator')
import validator

def read_solution_from_untis_xml(untis_filepath: str, untis_file: str, untis_file_fixed_lessons: str, instance: Instance) -> dict:
    Generator = HeuristicSolutionGenerator(copy.deepcopy(instance), output=False)
    unscheduledEvents = Generator.unscheduledEvents
    eventToHeuristicSubevents = dict()
    for event in unscheduledEvents.keys():
        eventToHeuristicSubevents[event] = set()
        for subevent in unscheduledEvents[event].keys():
            eventToHeuristicSubevents[event].add(subevent)
    returned_solution_dict = dict()
    event_dict = dict()
    xml_file = io.open(f"{untis_filepath}/{untis_file}", "r", encoding="utf8", errors="backslashreplace").read()
    event_id_to_fixed_events = dict()
    try:
        xml_file_fixed_lessons = io.open(f"{untis_filepath}/{untis_file_fixed_lessons}", "r", encoding="utf8", errors="backslashreplace").read()
        xml_file_fixed_lessons = xmltodict.parse(xml_file_fixed_lessons)['document']
        if UNTISConstants.LESSONS not in xml_file_fixed_lessons or UNTISConstants.LESSON not in xml_file_fixed_lessons[UNTISConstants.LESSONS]:
            xml_file_fixed_lessons = None
        elif not isinstance(xml_file_fixed_lessons[UNTISConstants.LESSONS][UNTISConstants.LESSON], list):
            xml_file_fixed_lessons[UNTISConstants.LESSONS][UNTISConstants.LESSON] = [xml_file_fixed_lessons[UNTISConstants.LESSONS][UNTISConstants.LESSON]]

        if xml_file_fixed_lessons is not None:
            for lesson in xml_file_fixed_lessons[UNTISConstants.LESSONS][UNTISConstants.LESSON]:
                lessonId = lesson[UNTISConstants.ID]
                if lessonId not in instance.Events.EventGroups.keys():
                    continue
                if lessonId[-2:] != "00":
                    continue
                lessonsTimesToResources = dict()
                if UNTISConstants.TIMES in lesson and UNTISConstants.TIME in lesson[UNTISConstants.TIMES]:
                    if not isinstance(lesson[UNTISConstants.TIMES][UNTISConstants.TIME], list):
                        lesson[UNTISConstants.TIMES][UNTISConstants.TIME] = [
                            lesson[UNTISConstants.TIMES][UNTISConstants.TIME]]
                    for time in lesson[UNTISConstants.TIMES][UNTISConstants.TIME]:
                        if "assigned_room" in time:
                            rooms = time["assigned_room"]["@id"]
                        else:
                            rooms = "None"
                        instanceTime = instance.Times.Days[time["assigned_day"]].Times[int(time["assigned_period"]) - 1]
                        lessonsTimesToResources[instanceTime] = rooms
                current_duration = 1
                current_start_time = None
                existingSubeventPerDuration = dict()
                durationToPreferedTimes = dict()
                subeventsTimes = dict()
                for timeIndex in range(len(instance.Times.IndividualTimes.keys())):
                    time = list(instance.Times.IndividualTimes.keys())[timeIndex]
                    dayOfTime = [day for day in instance.Times.Days.keys() if time in instance.Times.Days[day].Times][0]
                    timeIsFirstTimeSlotOfDay = instance.Times.Days[dayOfTime].Times[0] == time
                    timeIsLastTimeSlotOfDay = instance.Times.Days[dayOfTime].Times[-1] == time
                    if timeIndex == 0:
                        previousTime = "Does not exist"
                    else:
                        previousTime = list(instance.Times.IndividualTimes.keys())[timeIndex - 1]
                    if timeIndex == len(instance.Times.IndividualTimes.keys()) - 1:
                        nextTime = "Does not exist"
                    else:
                        nextTime = list(instance.Times.IndividualTimes.keys())[timeIndex + 1]
                    if time not in lessonsTimesToResources:
                        continue
                    resources = lessonsTimesToResources[time]
                    if previousTime not in lessonsTimesToResources or lessonsTimesToResources[
                        previousTime] != resources or timeIsFirstTimeSlotOfDay:
                        current_start_time = time
                    if previousTime in lessonsTimesToResources and lessonsTimesToResources[previousTime] == resources and not timeIsFirstTimeSlotOfDay:
                        current_duration += 1
                    if nextTime not in lessonsTimesToResources or lessonsTimesToResources[nextTime] != resources or timeIsLastTimeSlotOfDay:
                        existingSubeventPerDuration.setdefault(current_duration, 0)
                        subeventsTimes[
                            (current_duration, existingSubeventPerDuration[current_duration])] = current_start_time
                        durationToPreferedTimes.setdefault(current_duration, list()).append(current_start_time)
                        existingSubeventPerDuration[current_duration] += 1
                        current_duration = 1
                for duration in durationToPreferedTimes.keys():
                    counter = 0
                    for preferedTime in durationToPreferedTimes[duration]:
                        startTimeIndex = list(instance.Times.IndividualTimes.keys()).index(preferedTime)
                        affectedTimes = list(instance.Times.IndividualTimes.keys())[startTimeIndex: startTimeIndex + duration]
                        event_id_to_fixed_events.setdefault(lessonId, set()).add((f"{lessonId}_{duration}_{counter}", tuple(affectedTimes)))
                        counter += 1
    except:
        xml_file_fixed_lessons = None
    file_as_dict = xmltodict.parse(xml_file)['document']

    removedRoomCounter = dict()
    for lesson_index in range(len(file_as_dict[UNTISConstants.LESSONS][UNTISConstants.LESSON])):
        lesson = file_as_dict[UNTISConstants.LESSONS][UNTISConstants.LESSON][lesson_index]
        lessonDuration = int(lesson[UNTISConstants.PERIODS])
        lessonIDEnding = lesson[UNTISConstants.ID][-2:]
        event_id = lesson[UNTISConstants.ID][:-2] + "00"
        numberOfParallelLessons = len([lesson2 for lesson2 in file_as_dict[UNTISConstants.LESSONS][UNTISConstants.LESSON] if event_id == lesson2[UNTISConstants.ID][:-2] + '00'])
        if event_id not in instance.Events.EventGroups.keys():
            continue
        index_for_combined_events = int(lesson[UNTISConstants.ID][-2:])
        subevent_hours_per_day = dict()
        if lesson[UNTISConstants.TIMES] is not None:
            if not isinstance(lesson[UNTISConstants.TIMES][UNTISConstants.TIME], list):
                lesson[UNTISConstants.TIMES][UNTISConstants.TIME] = [lesson[UNTISConstants.TIMES][UNTISConstants.TIME]]
            for time in lesson[UNTISConstants.TIMES][UNTISConstants.TIME]:
                if UNTISConstants.ASSIGNED_ROOM in time:
                    assignedRoom = time[UNTISConstants.ASSIGNED_ROOM][UNTISConstants.ID]
                else:
                    assignedRoom = None
                subevent_hours_per_day.setdefault(time[UNTISConstants.ASSIGNED_DAY], dict()).setdefault((int(time[UNTISConstants.ASSIGNED_PERIOD]), assignedRoom), list())
                if UNTISConstants.ASSIGNED_ROOM in time.keys():
                    rooms = [f"RM_{room}".strip() for room in time[UNTISConstants.ASSIGNED_ROOM][UNTISConstants.ID].split('RM_') if room != " " and room != ""]

                else:
                    rooms = []
                subevent_hours_per_day[time[UNTISConstants.ASSIGNED_DAY]][(int(time[UNTISConstants.ASSIGNED_PERIOD]), assignedRoom)] += rooms
        else:
            duration = int(instance.Events.IndividualEvents[event_id].Duration)
            subevent = (duration, 0)
            event_dict[event_id, subevent] = dict()
            processed_subevent = event_dict[event_id, subevent]
            processed_subevent[XHSTTFileConstants.DURATION] = duration
            processed_subevent[XHSTTFileConstants.ID] = (event_id, subevent)
            processed_subevent[XHSTTFileConstants.TIME] = ILPConstants.DUMMY_TIME
            processed_subevent[SolutionDataConstants.DELETE_SUBEVENTS] = False
            processed_subevent[XHSTTFileConstants.NAME] = event_id
            processed_subevent[XHSTTFileConstants.RESOURCES] = dict()
            if index_for_combined_events > 0:
                roleAppendix = '_' + str(index_for_combined_events)
            else:
                roleAppendix = ''
            if UNTISConstants.LESSON_STUDENTS in lesson.keys():
                student_list = lesson[UNTISConstants.LESSON_STUDENTS][UNTISConstants.ID].split("ST_")
                max_requirement_counter = 0
                min_requirement_counter = 0
                for student_id in student_list:
                    if student_id == "" or student_id == " " or "ST_" + student_id in processed_subevent[XHSTTFileConstants.RESOURCES].values():
                        continue
                    if student_id.endswith(" "):
                        student_id = student_id[:-1]
                    unassignedRolesOfEvent = [er.Role for er in instance.Events.IndividualEvents[event_id].EventResources.UnassignedResources]
                    if "min_requirement_Lesson Student_" + str(min_requirement_counter) in unassignedRolesOfEvent:
                        student_role_id = "min_requirement_Lesson Student_" + str(min_requirement_counter)
                        processed_subevent[XHSTTFileConstants.RESOURCES][student_role_id] = "ST_" + student_id
                        min_requirement_counter += 1
                    elif "max_requirement_Lesson Student_" + str(max_requirement_counter) in unassignedRolesOfEvent:
                        student_role_id = "max_requirement_Lesson Student_" + str(max_requirement_counter)
                        processed_subevent[XHSTTFileConstants.RESOURCES][student_role_id] = "ST_" + student_id
                        max_requirement_counter += 1
                    else:
                        print(f"TO MANY STUDENTS IN EVENT {event_id}")
                        continue
            if UNTISConstants.LESSON_TEACHER in lesson.keys():
                processed_subevent[XHSTTFileConstants.RESOURCES][UNTISConstants.TEACHER_ROLE + roleAppendix] = lesson[UNTISConstants.LESSON_TEACHER][UNTISConstants.ID]
            else:
                processed_subevent[XHSTTFileConstants.RESOURCES][UNTISConstants.TEACHER_ROLE + roleAppendix] = ILPConstants.DUMMY_RESOURCE
            processed_subevent[XHSTTFileConstants.RESOURCES][UNTISConstants.ROOM_ROLE] = ILPConstants.DUMMY_RESOURCE
            continue
        existing_durations = dict()
        subevents_list = list()
        totalDuration = 0
        for day in subevent_hours_per_day.keys():
            current_duration = 1
            current_start_time = None
            for time in sorted(list(subevent_hours_per_day[day].keys())):
                rooms = subevent_hours_per_day[day][time]
                current_start_time = time[0]
                subevents_list.append((day, current_start_time, current_duration, rooms))
                current_duration = 1
                totalDuration += 1
        if totalDuration < lessonDuration:
            for i in range(lessonDuration - totalDuration):
                rooms = []
                subevents_list.append((0, 0, 1, rooms))
        for sub in subevents_list:
            duration = sub[2]
            existing_durations.setdefault(duration, 0)
            subevent_index = existing_durations[duration]
            subevent = (duration, subevent_index)
            removedRoomCounter.setdefault((event_id, subevent), 0)
            existing_durations[duration] += 1
            if (event_id, subevent) not in event_dict.keys():
                event_dict[event_id, subevent] = dict()
                processed_subevent = event_dict[event_id, subevent]
                processed_subevent[XHSTTFileConstants.DURATION] = duration
                processed_subevent[XHSTTFileConstants.ID] = (event_id, subevent)
                day = sub[0]
                if day == 0:
                    processed_subevent[XHSTTFileConstants.TIME] = ILPConstants.DUMMY_TIME
                else:
                    processed_subevent[XHSTTFileConstants.TIME] = instance.Times.Days[day].Times[sub[1] - 1]
                processed_subevent[SolutionDataConstants.DELETE_SUBEVENTS] = False
                processed_subevent[XHSTTFileConstants.NAME] = event_id
                processed_subevent[XHSTTFileConstants.RESOURCES] = dict()
            else:
                processed_subevent = event_dict[event_id, subevent]
            firstEventOfEventGroup = instance.Events.EventGroups[event_id].Events[0]
            unassignedRolesOfEvent = [er.Role for er in
                                      instance.Events.IndividualEvents[firstEventOfEventGroup].EventResources.UnassignedResources]
            if UNTISConstants.LESSON_STUDENTS in lesson.keys():
                linked_lesson = file_as_dict[UNTISConstants.LESSONS][UNTISConstants.LESSON][lesson_index - 1]
                if index_for_combined_events > 0 and lesson[UNTISConstants.LESSON_STUDENTS][UNTISConstants.ID] == linked_lesson[UNTISConstants.LESSON_STUDENTS][UNTISConstants.ID]:
                    continue
                student_list = lesson[UNTISConstants.LESSON_STUDENTS][UNTISConstants.ID].split("ST_")
                min_requirement_counter = 0
                max_requirement_counter = 0
                while ("min_requirement_Lesson Student_" + str(min_requirement_counter) in unassignedRolesOfEvent and
                       "min_requirement_Lesson Student_" + str(min_requirement_counter) in processed_subevent[XHSTTFileConstants.RESOURCES].keys()):
                    min_requirement_counter += 1
                while ("max_requirement_Lesson Student_" + str(max_requirement_counter) in unassignedRolesOfEvent and
                        "max_requirement_Lesson Student_" + str(max_requirement_counter) in processed_subevent[XHSTTFileConstants.RESOURCES].keys()):
                    max_requirement_counter += 1
                for student_id in student_list:
                    assignedResources = [processed_subevent[XHSTTFileConstants.RESOURCES][role] for role in processed_subevent[XHSTTFileConstants.RESOURCES].keys()]
                    if student_id == "" or student_id == " ":
                        continue
                    if student_id.endswith(" "):
                        student_id = student_id[:-1]
                    if "ST_" + student_id in assignedResources:
                        continue
                    if "min_requirement_Lesson Student_" + str(min_requirement_counter) in unassignedRolesOfEvent:
                        student_role_id = "min_requirement_Lesson Student_" + str(min_requirement_counter)
                        processed_subevent[XHSTTFileConstants.RESOURCES][student_role_id] = "ST_" + student_id
                        min_requirement_counter += 1
                    elif "max_requirement_Lesson Student_" + str(max_requirement_counter) in unassignedRolesOfEvent:
                        student_role_id = "max_requirement_Lesson Student_" + str(max_requirement_counter)
                        processed_subevent[XHSTTFileConstants.RESOURCES][student_role_id] = "ST_" + student_id
                        max_requirement_counter += 1
                    else:
                        print(f"TO MANY STUDENTS IN EVENT {(event_id, subevent)} no space for {'max_requirement_Lesson Student_' + str(max_requirement_counter)} {student_id}")
                        continue
            existingResourcesInSubevent = {resource for resource in
                                           processed_subevent[XHSTTFileConstants.RESOURCES].values()}
            if UNTISConstants.LESSON_TEACHER in lesson.keys() and lesson[UNTISConstants.LESSON_TEACHER][UNTISConstants.ID] not in existingResourcesInSubevent:
                if lessonIDEnding == "00":
                    processed_subevent[XHSTTFileConstants.RESOURCES][f"{UNTISConstants.TEACHER_ROLE}"] = lesson[UNTISConstants.LESSON_TEACHER][UNTISConstants.ID]
                else:
                    if int(lessonIDEnding) < 10:
                        usedRole = f"{UNTISConstants.TEACHER_ROLE}_{lessonIDEnding[1]}"
                    else:
                        usedRole = f"{UNTISConstants.TEACHER_ROLE}_{lessonIDEnding}"
                    processed_subevent[XHSTTFileConstants.RESOURCES][usedRole] = lesson[UNTISConstants.LESSON_TEACHER][UNTISConstants.ID]
            elif UNTISConstants.LESSON_TEACHER not in lesson.keys():
                if lessonIDEnding == "00":
                    if UNTISConstants.TEACHER_ROLE in unassignedRolesOfEvent:
                        processed_subevent[XHSTTFileConstants.RESOURCES][f"{UNTISConstants.TEACHER_ROLE}"] = ILPConstants.DUMMY_RESOURCE
                else:
                    if int(lessonIDEnding) < 10:
                        usedRole = f"{UNTISConstants.TEACHER_ROLE}_{lessonIDEnding[1]}"
                    else:
                        usedRole = f"{UNTISConstants.TEACHER_ROLE}_{lessonIDEnding}"
                    if usedRole in unassignedRolesOfEvent:
                        processed_subevent[XHSTTFileConstants.RESOURCES][usedRole] = ILPConstants.DUMMY_RESOURCE

            for roomIndex in range(len(sub[3])):
                if sub[3][roomIndex] in processed_subevent[XHSTTFileConstants.RESOURCES].values():
                    removedRoomCounter[event_id, subevent] += 1
                    continue
                if lessonIDEnding == "00" and roomIndex == 0:
                    processed_subevent[XHSTTFileConstants.RESOURCES][f"{UNTISConstants.ROOM_ROLE}_{lessonIDEnding}"] = sub[3][roomIndex]
                elif roomIndex == 0:
                    if int(lessonIDEnding) < 10:
                        ending = lessonIDEnding[1]
                    else:
                        ending = lessonIDEnding
                    processed_subevent[XHSTTFileConstants.RESOURCES][f"{UNTISConstants.ROOM_ROLE}_{lessonIDEnding}_{ending}"] = sub[3][roomIndex]
                else:
                    ending = roomIndex + numberOfParallelLessons - removedRoomCounter[event_id, subevent] - 1
                    processed_subevent[XHSTTFileConstants.RESOURCES][f"{UNTISConstants.ROOM_ROLE}_{lessonIDEnding}_{ending}"] = sub[3][roomIndex]

    for subevent in event_dict.keys():
        firstEventOfEventGroup = instance.Events.EventGroups[subevent[0]].Events[0]
        for eventResource in instance.Events.IndividualEvents[firstEventOfEventGroup].EventResources.UnassignedResources:
            if eventResource.Role not in event_dict[subevent][XHSTTFileConstants.RESOURCES]:
                event_dict[subevent][XHSTTFileConstants.RESOURCES][eventResource.Role] = ILPConstants.DUMMY_RESOURCE
        for eventResource in instance.Events.IndividualEvents[firstEventOfEventGroup].EventResources.AssignedResources:
            if eventResource.Role not in event_dict[subevent][XHSTTFileConstants.RESOURCES]:
                event_dict[subevent][XHSTTFileConstants.RESOURCES][eventResource.Role] = eventResource.Reference
    for eventID in instance.Events.IndividualEvents.keys():
        if len(eventID.split('_')) > 2 and f"{eventID.split('_')[0]}_{eventID.split('_')[1]}" in instance.Events.IndividualEvents:
            subevents = [event for event in event_dict.keys() if event[0] == eventID]
            continue
        elif len(eventID.split('_')) > 2:
            subevents = [event for event in event_dict.keys() if event[0] == eventID]
            eventID = f"{eventID.split('_')[0]}_{eventID.split('_')[1]}"
        if eventID in event_id_to_fixed_events:
            fixedEvents = event_id_to_fixed_events[eventID]
        else:
            fixedEvents = set()
        affectedTimesOfFixedEvents = set()
        startTimesOfFixedEvents = set()
        for fixedEvent in fixedEvents:
            affectedTimesOfFixedEvents.update(fixedEvent[1])
            startTimesOfFixedEvents.add(fixedEvent[1][0])
        subevents = [event for event in event_dict.keys() if event[0] == eventID]
        resourceUsagePerTimeNotFixedEvents = dict()
        newSubevents = dict()
        for subevent in subevents:
            time = event_dict[subevent][XHSTTFileConstants.TIME]
            if time == ILPConstants.DUMMY_TIME:
                continue
            if time in startTimesOfFixedEvents:
                pass
                current_duration = [len(fixedEvent[1]) for fixedEvent in fixedEvents if time in fixedEvent[1]][0]
                newFixedEventId = [fixedEvent[0] for fixedEvent in fixedEvents if time in fixedEvent[1]][0]
                subeventDict = copy.deepcopy([event_dict[subevent] for subevent in subevents if
                                              event_dict[subevent][XHSTTFileConstants.TIME] == time][0])
                subeventDict["Duration"] = current_duration
                subeventDict["@Id"] = (newFixedEventId, (current_duration, 0))
                newSubevents[newFixedEventId, (current_duration, 0)] = subeventDict
            elif time not in affectedTimesOfFixedEvents:
                for role in event_dict[subevent][XHSTTFileConstants.RESOURCES].keys():
                    resourceUsagePerTimeNotFixedEvents.setdefault(time, set())
                    resourceUsagePerTimeNotFixedEvents[time].add(event_dict[subevent][XHSTTFileConstants.RESOURCES][role])
        current_duration = 1
        current_start_time = None
        existingSubeventPerDuration = dict()
        for timeIndex in range(len(instance.Times.IndividualTimes.keys())):
            time = list(instance.Times.IndividualTimes.keys())[timeIndex]
            dayOfTime = [day for day in instance.Times.Days.keys() if time in instance.Times.Days[day].Times][0]
            timeIsFirstTimeSlotOfDay = instance.Times.Days[dayOfTime].Times[0] == time
            timeIsLastTimeSlotOfDay = instance.Times.Days[dayOfTime].Times[-1] == time
            if timeIndex == 0:
                previousTime = "Does not exist"
            else:
                previousTime = list(instance.Times.IndividualTimes.keys())[timeIndex - 1]
            if timeIndex == len(instance.Times.IndividualTimes.keys()) - 1:
                nextTime = "Does not exist"
            else:
                nextTime = list(instance.Times.IndividualTimes.keys())[timeIndex + 1]
            if time not in resourceUsagePerTimeNotFixedEvents:
                continue
            resources = resourceUsagePerTimeNotFixedEvents[time]
            if previousTime not in resourceUsagePerTimeNotFixedEvents or resourceUsagePerTimeNotFixedEvents[previousTime] != resources or timeIsFirstTimeSlotOfDay:
                current_start_time = time
            if previousTime in resourceUsagePerTimeNotFixedEvents and resourceUsagePerTimeNotFixedEvents[previousTime] == resources and not timeIsFirstTimeSlotOfDay:
                current_duration += 1
            if nextTime not in resourceUsagePerTimeNotFixedEvents or resourceUsagePerTimeNotFixedEvents[nextTime] != resources or timeIsLastTimeSlotOfDay:
                existingSubeventPerDuration.setdefault(current_duration, 0)
                subeventDict = copy.deepcopy([event_dict[subevent] for subevent in subevents if event_dict[subevent][XHSTTFileConstants.TIME] == current_start_time][0])
                subeventDict["Duration"] = current_duration
                subeventDict["@Id"] = (eventID, (current_duration, existingSubeventPerDuration[current_duration]))
                newSubevents[eventID, (current_duration, existingSubeventPerDuration[current_duration])] = subeventDict
                existingSubeventPerDuration[current_duration] += 1
                current_duration = 1
        for subevent in subevents:
            if event_dict[subevent][XHSTTFileConstants.TIME] != ILPConstants.DUMMY_TIME:
                del event_dict[subevent]
        for subevent in newSubevents.keys():
            event_dict[subevent] = newSubevents[subevent]
    for event in event_dict.values():
        for role in event[XHSTTFileConstants.RESOURCES].keys():
            resource = event[XHSTTFileConstants.RESOURCES][role]
            if 'ä' in resource:
                resource = resource.replace('ä', 'ae')
            if 'ö' in resource:
                resource = resource.replace('ö', 'oe')
            if 'ü' in resource:
                resource = resource.replace('ü', 'ue')
            if 'ß' in resource:
                resource = resource.replace('ß', 'ss')
            event[XHSTTFileConstants.RESOURCES][role] = resource
    returned_solution_dict[XHSTTFileConstants.EVENTS] = event_dict
    return returned_solution_dict

def read_solution(filepath: str, fileName: str, solutionName: str, instance: Instance, original_instance: Instance = None, solution_index=None, addMissingEvents=False) -> dict:
    if original_instance is None:
        original_instance = instance
    file = io.open(f"{filepath}/{fileName}", "r", encoding="utf8", errors="backslashreplace").read()
    file_as_dict = xmltodict.parse(file)
    returned_solution_dict = dict()
    event_dict = dict()
    if SolutionFileConstants.HIGH_SCHOOL_TIMETABLE_ARCHIVE in file_as_dict:
        solutionGroups = file_as_dict[SolutionFileConstants.HIGH_SCHOOL_TIMETABLE_ARCHIVE][SolutionFileConstants.SOLUTION_GROUPS][SolutionFileConstants.SOLUTION_GROUP]
    elif SolutionFileConstants.SOLUTION_GROUPS in file_as_dict:
        solutionGroups = file_as_dict[SolutionFileConstants.SOLUTION_GROUPS][SolutionFileConstants.SOLUTION_GROUP]
    elif SolutionFileConstants.SOLUTION_GROUP in file_as_dict:
        solutionGroups = file_as_dict[SolutionFileConstants.SOLUTION_GROUP]
    else:
        raise ValueError(f"Could not find SolutionGroups in {filepath}/{fileName}")
    if not isinstance(solutionGroups, list):
        solutionGroups = [solutionGroups]
    for solutionGroup in solutionGroups:
        if solution_index is None and (solutionGroup[SolutionFileConstants.SOLUTION][XHSTTFileConstants.REFERENCE_WITH_AT] == solutionName or solutionGroup["@Id"] == solutionName):
            solution_input_dict = solutionGroup
        elif solution_index is not None and (solutionGroup[SolutionFileConstants.SOLUTION][solution_index][XHSTTFileConstants.REFERENCE_WITH_AT] == solutionName or solutionGroup["@Id"] == solutionName):
            solution_input_dict = solutionGroup
    if solution_index is None:
        solution_events = solution_input_dict[SolutionFileConstants.SOLUTION][XHSTTFileConstants.EVENTS][XHSTTFileConstants.EVENT]
    else:
        solution_events = solution_input_dict[SolutionFileConstants.SOLUTION][solution_index][XHSTTFileConstants.EVENTS][
            XHSTTFileConstants.EVENT]
    for event in solution_events:
        event_id = event[XHSTTFileConstants.REFERENCE_WITH_AT]
        if XHSTTFileConstants.DURATION not in event.keys():
            event[XHSTTFileConstants.DURATION] = instance.Events.IndividualEvents[event_id].Duration
        subeventCounter = 0
        while (event_id, (int(event[XHSTTFileConstants.DURATION]), subeventCounter)) in event_dict.keys():
            subeventCounter += 1
        subevent = (int(event[XHSTTFileConstants.DURATION]), subeventCounter)
        event_dict[event_id, subevent] = dict()
        currently_processed_subevent = event_dict[event_id, subevent]
        currently_processed_subevent[XHSTTFileConstants.DURATION] = event[XHSTTFileConstants.DURATION]
        currently_processed_subevent[XHSTTFileConstants.ID] = (event[XHSTTFileConstants.REFERENCE_WITH_AT], subevent)
        if XHSTTFileConstants.TIME in event.keys():
            currently_processed_subevent[XHSTTFileConstants.TIME] = event[XHSTTFileConstants.TIME][XHSTTFileConstants.REFERENCE_WITH_AT]
        elif instance.Events.IndividualEvents[event_id].Time is not None:
            currently_processed_subevent[XHSTTFileConstants.TIME] = instance.Events.IndividualEvents[event_id].Time
        else:
            currently_processed_subevent[XHSTTFileConstants.TIME] = ILPConstants.DUMMY_TIME
        currently_processed_subevent[SolutionDataConstants.DELETE_SUBEVENTS] = False
        currently_processed_subevent[XHSTTFileConstants.NAME] = event_id
        currently_processed_subevent[XHSTTFileConstants.RESOURCES] = dict()
        if XHSTTFileConstants.RESOURCES in event.keys() and event[XHSTTFileConstants.RESOURCES] is not None and XHSTTFileConstants.RESOURCE in event[XHSTTFileConstants.RESOURCES].keys():
            resources = event[XHSTTFileConstants.RESOURCES][XHSTTFileConstants.RESOURCE]
            if not isinstance(resources, list):
                resources = [resources]
            for resource in resources:
                currently_processed_subevent[XHSTTFileConstants.RESOURCES][resource[XHSTTFileConstants.ROLE]] = resource[XHSTTFileConstants.REFERENCE_WITH_AT]

        for resource in instance.Events.IndividualEvents[
            event[XHSTTFileConstants.REFERENCE_WITH_AT]].EventResources.AssignedResources:
            resourceID = resource.Reference
            if resource.Role is not None:
                currently_processed_subevent[XHSTTFileConstants.RESOURCES][
                    resource.Role] = resourceID
            else:
                role = "NoRole" + str(uuid.uuid4())
                resource.Role = role
                currently_processed_subevent[XHSTTFileConstants.RESOURCES][role] = resourceID
        for resource in original_instance.Events.IndividualEvents[event[XHSTTFileConstants.REFERENCE_WITH_AT]].EventResources.UnassignedResources:
            if resource.Role in currently_processed_subevent[XHSTTFileConstants.RESOURCES]:
                continue
            if resource.Reference is None:
                resourceID = ILPConstants.DUMMY_RESOURCE
            else:
                resourceID = resource.Reference
            if resource.Role is not None:
                if resource.Role not in currently_processed_subevent[XHSTTFileConstants.RESOURCES].keys():
                    currently_processed_subevent[XHSTTFileConstants.RESOURCES][resource.Role] = resourceID

    for event_id in instance.Events.IndividualEvents.keys():
        event = instance.Events.IndividualEvents[event_id]
        if event.Time is None or (event_id, (int(event.Duration), 0)) in event_dict:
            continue
        subevent = (int(event.Duration), 0)
        event_dict[event_id, subevent] = dict()
        currently_processed_subevent = event_dict[event_id, subevent]
        currently_processed_subevent[XHSTTFileConstants.DURATION] = int(event.Duration)
        currently_processed_subevent[XHSTTFileConstants.ID] = (event_id, subevent)
        currently_processed_subevent[XHSTTFileConstants.TIME] = event.Time
        currently_processed_subevent[SolutionDataConstants.DELETE_SUBEVENTS] = False
        currently_processed_subevent[XHSTTFileConstants.NAME] = event_id
        currently_processed_subevent[XHSTTFileConstants.RESOURCES] = dict()
        for resource in event.EventResources.AssignedResources:
            resourceID = resource.Reference
            if resource.Role is not None:
                currently_processed_subevent[XHSTTFileConstants.RESOURCES][
                    resource.Role] = resourceID
            else:
                role = "NoRole" + str(uuid.uuid4())
                resource.Role = role
                currently_processed_subevent[XHSTTFileConstants.RESOURCES][role] = resourceID
        for resource in original_instance.Events.IndividualEvents[event_id].EventResources.UnassignedResources:
            if resource.Role in currently_processed_subevent[XHSTTFileConstants.RESOURCES]:
                continue
            resourceID = ILPConstants.DUMMY_RESOURCE
            if resource.Role is not None:
                if resource.Role not in currently_processed_subevent[XHSTTFileConstants.RESOURCES].keys():
                    currently_processed_subevent[XHSTTFileConstants.RESOURCES][resource.Role] = resourceID

    generateSplitEvents = False
    for event in instance.Events.IndividualEvents.keys():
        subevents = [e[1] for e in event_dict.keys() if e[0] == event]
        durationOfSubevents = sum([subevent[0] for subevent in subevents])
        if durationOfSubevents < int(instance.Events.IndividualEvents[event].Duration):
            generateSplitEvents = True
    if generateSplitEvents and addMissingEvents:
        heuristicSolutionGenerator = HeuristicSolutionGenerator(instance)
        splitEvents = heuristicSolutionGenerator.unscheduledEventsCopy
    else:
        returned_solution_dict[XHSTTFileConstants.EVENTS] = event_dict
        returned_solution_dict[SolutionDataConstants.VALIDATOR_OBJECTIVE] = math.inf
        if SolutionDataConstants.DESCRIPTION in solution_input_dict[SolutionFileConstants.SOLUTION]:
            returned_solution_dict[SolutionDataConstants.DESCRIPTION] = solution_input_dict[SolutionFileConstants.SOLUTION][
                SolutionDataConstants.DESCRIPTION]
        else:
            returned_solution_dict[SolutionDataConstants.DESCRIPTION] = ""
        if "RunningTime" in solution_input_dict[SolutionFileConstants.SOLUTION]:
            returned_solution_dict["RunningTime"] = solution_input_dict[SolutionFileConstants.SOLUTION]["RunningTime"]
        else:
            returned_solution_dict["RunningTime"] = ""
        return returned_solution_dict
    for event_id in instance.Events.IndividualEvents.keys():
        event = instance.Events.IndividualEvents[event_id]
        subevents = [e[1] for e in event_dict.keys() if e[0] == event_id]
        durationOfSubevents = sum([subevent[0] for subevent in subevents])
        if durationOfSubevents < instance.Events.IndividualEvents[event_id].Duration:
            subeventsInHeuristicSplit = set(splitEvents[event_id].keys())
            alreadyExistingSubevents = set(subevents)
            missingSubevents = subeventsInHeuristicSplit.difference(alreadyExistingSubevents)
            durationMissingEvents = sum([subevent[0] for subevent in missingSubevents])
            if durationMissingEvents + durationOfSubevents == int(instance.Events.IndividualEvents[event_id].Duration):
                for missingSubevent in missingSubevents:
                    event_dict[event_id, missingSubevent] = dict()
                    currently_processed_subevent = event_dict[event_id, missingSubevent]
                    currently_processed_subevent[XHSTTFileConstants.DURATION] = missingSubevent[0]
                    currently_processed_subevent[XHSTTFileConstants.ID] = (event_id, missingSubevent)
                    currently_processed_subevent[XHSTTFileConstants.TIME] = event.Time if event.Time is not None else ILPConstants.DUMMY_TIME
                    currently_processed_subevent[SolutionDataConstants.DELETE_SUBEVENTS] = False
                    currently_processed_subevent[XHSTTFileConstants.NAME] = event_id
                    currently_processed_subevent[XHSTTFileConstants.RESOURCES] = dict()
                    for resource in event.EventResources.AssignedResources:
                        resourceID = resource.Reference
                        if resource.Role is not None:
                            currently_processed_subevent[XHSTTFileConstants.RESOURCES][
                                resource.Role] = resourceID
                        else:
                            role = "NoRole" + str(uuid.uuid4())
                            resource.Role = role
                            currently_processed_subevent[XHSTTFileConstants.RESOURCES][role] = resourceID
                    for resource in original_instance.Events.IndividualEvents[
                        event_id].EventResources.UnassignedResources:
                        if resource.Role in currently_processed_subevent[XHSTTFileConstants.RESOURCES]:
                            continue
                        resourceID = ILPConstants.DUMMY_RESOURCE
                        if resource.Role is not None:
                            if resource.Role not in currently_processed_subevent[XHSTTFileConstants.RESOURCES].keys():
                                currently_processed_subevent[XHSTTFileConstants.RESOURCES][resource.Role] = resourceID
            else:
                print(
                    f"Subevent durations dont add up after fix with heuristic solution for {event} ({durationMissingEvents + durationOfSubevents} vs {int(instance.Events.IndividualEvents[event].Duration)})")

    returned_solution_dict[XHSTTFileConstants.EVENTS] = event_dict
    returned_solution_dict[SolutionDataConstants.VALIDATOR_OBJECTIVE] = math.inf
    returned_solution_dict[SolutionDataConstants.DESCRIPTION] = solution_input_dict[SolutionFileConstants.SOLUTION][
        SolutionDataConstants.DESCRIPTION]
    returned_solution_dict["RunningTime"] = solution_input_dict[SolutionFileConstants.SOLUTION]["RunningTime"]
    return returned_solution_dict

def get_avg_objective_values(instance, filepath: str, fileName: str, sol_substrings: list, includeTime=False):
    solutionGroups = get_all_solution_groups(filepath, fileName)
    filteredSolutionGroups = dict()
    objectiveValues = dict()
    times = dict()
    for sol_substr in sol_substrings:
        filteredSolutionGroups[sol_substr] = {int(solGroup[SolutionFileConstants.SOLUTION]['@Reference'].split('_')[-1]): solGroup for solGroup in list(solutionGroups.values())[0] if sol_substr in solGroup[SolutionFileConstants.SOLUTION]['@Reference']}
        objectiveValues[sol_substr] = list()
        times[sol_substr] = list()
    for i in range(1, 11):
        for sol_substr in filteredSolutionGroups.keys():
            if len(filteredSolutionGroups[sol_substr]) < 10:
                continue
            current_solution = solution_reader.read_solution(filepath, fileName, filteredSolutionGroups[sol_substr][i][SolutionFileConstants.SOLUTION]['@Reference'],
                                                         instance)
            obj_val = validator.get_objective_value(instance, current_solution, outputObjectiveValues=False, outputDetailedObjectiveValues=False, evaluateHardAndSoftSeparatly=False)
            objectiveValues[sol_substr].append(obj_val)
            if includeTime:
                time = float(filteredSolutionGroups[sol_substr][i]['Solution']['RunningTime'].split('s')[0])
                times[sol_substr].append(time)

    for sol_substr in filteredSolutionGroups.keys():
        if len(filteredSolutionGroups[sol_substr]) < 10:
            continue
        if includeTime:
            print(f"{fileName} & {sol_substr} & {round(statistics.mean(objectiveValues[sol_substr]), 5)} & {round(statistics.stdev(objectiveValues[sol_substr]), 5)} & {int(statistics.mean(times[sol_substr]))} \\\\")
        else:
            print(f"{fileName} & {sol_substr} & {round(statistics.mean(objectiveValues[sol_substr]), 5)} & {round(statistics.stdev(objectiveValues[sol_substr]), 5)}")



def get_solution_objective_values(filepath: str, fileName: str, sol_substrings: list, returnDict=False):
    solutionGroups = get_all_solution_groups(filepath, fileName)
    if returnDict:
        best_known_solutions = dict()
        best_known_solution_objvals = dict()
        for sol_substring in sol_substrings:
            best_known_solutions[sol_substring] = "None"
            best_known_solution_objvals[sol_substring] = math.inf
    best_known_solution = "None"
    best_known_solution_obj_val = math.inf
    filteredSolutionGroups = dict()
    for sol_substr in sol_substrings:
        filteredSolutionGroups[sol_substr] = {int(solGroup[SolutionFileConstants.SOLUTION]['@Reference'].split('_')[-1]): solGroup for solGroup in list(solutionGroups.values())[0] if sol_substr in solGroup[SolutionFileConstants.SOLUTION]['@Reference']}
    try:
        e_opt_solution = [solGroup for solGroup in list(solutionGroups.values())[0] if "untis_e_opt" in solGroup[SolutionFileConstants.SOLUTION]['@Reference']][0]
        obj_val = float(e_opt_solution['MetaData']['Description'].split(': ')[1])
        print(f"Untis E Optimization Objective Value: {obj_val}")
        best_known_solution = e_opt_solution[SolutionFileConstants.SOLUTION]['@Reference']
        best_known_solution_obj_val = obj_val
        if returnDict:
            best_known_solutions["e_opt_solution"] = e_opt_solution[SolutionFileConstants.SOLUTION]['@Reference']
            best_known_solution_objvals["e_opt_solution"] = obj_val
    except:
        pass
    try:
        pass
        khe_solution = [solGroup for solGroup in list(solutionGroups.values())[0] if "khe" in solGroup[SolutionFileConstants.SOLUTION]['@Reference']][0]
        obj_val = float(khe_solution['MetaData']['Description'].split(': ')[1])
        print(f"KHE Objective Value: {obj_val}")
        if obj_val < best_known_solution_obj_val:
            best_known_solution = khe_solution[SolutionFileConstants.SOLUTION]['@Reference']
            best_known_solution_obj_val = obj_val
        if returnDict:
            best_known_solutions["khe_solution"] = khe_solution[SolutionFileConstants.SOLUTION]['@Reference']
            best_known_solution_objvals["khe_solution"] = obj_val
    except:
        pass
    output = "  "
    for sol_substr in filteredSolutionGroups.keys():
        output += sol_substr + " "
    print(output)
    for i in range(1, 11):
        output = f"{i}: "
        for sol_substr in filteredSolutionGroups.keys():
            obj_val = float(filteredSolutionGroups[sol_substr][i]['MetaData']['Description'].split(': ')[1])
            output += f"{obj_val} "
            if obj_val < best_known_solution_obj_val:
                best_known_solution_obj_val = obj_val
                best_known_solution = filteredSolutionGroups[sol_substr][i][SolutionFileConstants.SOLUTION]['@Reference']
            if returnDict and obj_val < best_known_solution_objvals[sol_substr]:
                best_known_solutions[sol_substr] = filteredSolutionGroups[sol_substr][i][SolutionFileConstants.SOLUTION]['@Reference']
                best_known_solution_objvals[sol_substr] = obj_val
        print(output)
    if returnDict:
        print(best_known_solutions)
        return best_known_solutions

    return best_known_solution
def get_all_solution_group_ids(filepath: str, fileName: str) -> list:
    file = io.open(f"{filepath}/{fileName}", "r", encoding="utf8", errors="backslashreplace").read()
    file_as_dict = xmltodict.parse(file)
    solutionGroups = \
    file_as_dict[SolutionFileConstants.HIGH_SCHOOL_TIMETABLE_ARCHIVE][SolutionFileConstants.SOLUTION_GROUPS][
        SolutionFileConstants.SOLUTION_GROUP]
    return [solutionGroup[XHSTTFileConstants.ID] for solutionGroup in solutionGroups]

def get_all_solution_groups(filepath: str, fileName: str) -> list:
    file = io.open(f"{filepath}/{fileName}", "r", encoding="utf8", errors="backslashreplace").read()
    file_as_dict = xmltodict.parse(file)
    solutionGroups = file_as_dict[SolutionFileConstants.HIGH_SCHOOL_TIMETABLE_ARCHIVE][SolutionFileConstants.SOLUTION_GROUPS]
    return solutionGroups
