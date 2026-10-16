import argparse
import sys
import time

sys.path.append('XHSTTImporter')
from generate_heuristic_solution import HeuristicSolutionGenerator
from split_constraints import split_constraints_into_smaller_constraints
import solution_reader
import xhstt_input_reader

sys.path.append('ILP_solver')
sys.path.append('ILPSolver')
from gurobi_solver import ILPModel

sys.path.append('SolutionExporter')
import output_writer

sys.path.append('ALNS')
from ALNS import ALNS
from ALNS_Config import ALNS_Config
from neighborhoods import create_list_containing_ISA_paper_neighborhoods

sys.path.append('validator')
import validator

TIME_LIMIT = 3 * 60 * 60

def main(args, config=ALNS_Config(), output=True, input_solution_nr=None):
    instance = xhstt_input_reader.read_XHSTT_input_file(args.directory, args.file)
    split_constraints_into_smaller_constraints(instance)
    start = time.time()
    useExistingSolution = False
    writeOutput = False
    if input_solution_nr is None:
        input_solution_nr = args.number
    if not useExistingSolution:
        args.solver = "None"
        solutionGenerator = HeuristicSolutionGenerator(instance, output=output)
        solution = solutionGenerator.generate_heuristic_solution()
        solution["RunningTime"] = str(time.time() - start)
        validator.get_objective_value(instance, solution, outputObjectiveValues=output, outputDetailedObjectiveValues=False)
    else:
        solution_name = args.file.split(".xml")[0] + "_heuristic_solution_" + str(input_solution_nr)
        instance_to_read = instance
        solution = solution_reader.read_solution(str(args.directory), str(args.file), solution_name,
                                                 instance_to_read, addMissingEvents=True)
        solution["RunningTime"] = "Not measured"
    solution["InstanceId"] = args.file.split(".xml")[0] + "_heuristic_solution_" + str(args.number)
    solution["Description"] = "Created at IMC Krems through Construction Heuristic"
    solution['ValidatorObjective'] = validator.get_objective_value(instance, solution, outputObjectiveValues=output, outputDetailedObjectiveValues=False)
    solution['ObjectiveValue'] = solution['ValidatorObjective']
    solution["FileName"] = args.file
    solution["ID"] = args.file
    solution["SortedTimes"] = list(instance.Times.IndividualTimes.keys())

    model = ILPModel(instance, outputFlag=1 if output else 0, clash_free=False, optimize_splitting=False)
    model.create_model(outputFlag=1 if output else 0, existingSolution=solution)

    neighborhoods = create_list_containing_ISA_paper_neighborhoods()
    alns = ALNS(model, instance, neighborhoods, solution, config=config)

    total_time_limit = getattr(args, 'timelimit', None) or TIME_LIMIT
    starttime = time.time()
    solution, _ = alns.execute_random_neighborhoods_till_time_limit_reached(total_time_limit)

    solution["Description"] = "Created at IMC Krems through adaptive large neighborhood search"
    solution["InstanceId"] = args.file.split(".xml")[0] + "_ALNS_solution_" + str(args.number)
    solution["RunningTime"] = str(round(time.time() - starttime)) + "s"

    solution['ValidatorObjective'] = validator.get_objective_value(instance, solution,
                                                                   outputObjectiveValues=output, outputDetailedObjectiveValues=False)
    solution['ObjectiveValue'] = solution['ValidatorObjective']
    solution["FileName"] = args.file
    solution["ID"] = args.file
    solution["SortedTimes"] = list(instance.Times.IndividualTimes.keys())
    if writeOutput:
        output_writer.write_output('data', solution, instance, directory=args.directory)
        print(f"Returned objective Value: {solution['ValidatorObjective']}")

    return solution['ValidatorObjective']


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-fi", "--file", help="File to read from (In case of untis file this refers to the XML file)")
    parser.add_argument("-dir", "--directory", help="Directory in which the files associated with an Untis instance lie")
    parser.add_argument("-nr", "--number", default="1", help="Instance or solution number")
    parser.add_argument("-tl", "--timelimit", type=int, default=TIME_LIMIT, help="Total time limit in seconds")

    args = parser.parse_args()
    main(args)
