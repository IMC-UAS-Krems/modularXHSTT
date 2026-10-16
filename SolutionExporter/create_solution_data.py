import sys
import os
import io
import xmltodict
sys.path.append('SolutionExporter')
import SolutionFileConstants
sys.path.append('../XHSTTImporter')
sys.path.append('../XHSTTImporter/Constants')
import XHSTTFileConstants
def read_all_XHSTT_solutions_id_containing_substring(id_substring: str = ""):
    rootdir = '../data/artificial/latin_hypercube_sample'
    for subdir, dirs, files in os.walk(rootdir):
        winningCounts = dict()
        filesWithoutSolutions = list()
        for file in files:
            if not file.endswith('.xml'):
                continue
            objective_value_list = list()
            solution_names = list()
            xml_file = io.open(f"{subdir}/{file}", "r", encoding="utf8", errors="backslashreplace").read()
            print(f"{subdir}/{file}")
            file_as_dict = xmltodict.parse(xml_file)
            if SolutionFileConstants.SOLUTION_GROUPS not in file_as_dict[SolutionFileConstants.HIGH_SCHOOL_TIMETABLE_ARCHIVE] or \
                file_as_dict[SolutionFileConstants.HIGH_SCHOOL_TIMETABLE_ARCHIVE][SolutionFileConstants.SOLUTION_GROUPS] is None or \
                SolutionFileConstants.SOLUTION_GROUP not in file_as_dict[SolutionFileConstants.HIGH_SCHOOL_TIMETABLE_ARCHIVE][SolutionFileConstants.SOLUTION_GROUPS]:
                filesWithoutSolutions.append(file)
                continue
            solutionGroups = file_as_dict[SolutionFileConstants.HIGH_SCHOOL_TIMETABLE_ARCHIVE][SolutionFileConstants.SOLUTION_GROUPS][SolutionFileConstants.SOLUTION_GROUP]

            if not isinstance(solutionGroups, list):
                solutionGroups = [solutionGroups]

            for solution in solutionGroups:
                if id_substring in solution[XHSTTFileConstants.ID]:
                    objective_value = float(solution[SolutionFileConstants.METADATA]["Description"].split(": ")[1])
                    objective_value_list.append(objective_value)
                    solution_names.append(solution[SolutionFileConstants.SOLUTION]["@Reference"])
            if len(objective_value_list) > 0:
                min_objective_value = min(objective_value_list)
                for i in range(len(objective_value_list)):
                    solutionName = solution_names[i].split('_')[2]
                    if objective_value_list[i] == min_objective_value:
                        winningCounts.setdefault(solutionName, 0)
                        winningCounts[solutionName] += 1
                        print(f"Winning solution with objective value {objective_value_list[i]} is {solutionName}")
                    else:
                        print(f"Solution with objective value {objective_value_list[i]} from {solutionName}")
        print(f"Files without solution: {filesWithoutSolutions}")
        for solutionName in winningCounts.keys():
            print(f"{solutionName} has won {winningCounts[solutionName]} times")

if __name__ == "__main__":
    read_all_XHSTT_solutions_id_containing_substring(id_substring="")