import sys
sys.path.append('XHSTTImporter')
from generate_heuristic_solution import HeuristicSolutionGenerator
import xhstt_input_reader
import time
sys.path.append('ILPSolver')
from split_constraints import split_constraints_into_smaller_constraints
import solution_reader
sys.path.append('SolutionExporter')
import output_writer
import argparse
sys.path.append('Simulated_Annealing')
from SA import do_n_iterations_of_simulated_annealing_with_cutoff
from SA_Config import SA_Config
sys.path.append('validator')
import validator


def main(args, config=SA_Config(), output=True, input_solution_nr = None):
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
    starttime = time.time()

    solution = do_n_iterations_of_simulated_annealing_with_cutoff(instance, solution, total_iterations=config.ITERATIONS,
                                                                  start_acceptance_rate=config.START_ACCEPTANCE_RATE, end_acceptance_rate=config.END_ACCEPTANCE_RATE, cooling_rate=config.COOLING_RATE,
                                                                  cutoff_ratio=config.CUTOFF_RATIO, neighborhood_probabilities=config.NEIGHBORHOOD_PROBABILITIES,
                                                                  output=output)
    solution["Description"] = "Created at IMC Krems through simulated annealing"
    solution["InstanceId"] = args.file.split(".xml")[0] + "_3MSA_solution_" + str(args.number)
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

    args = parser.parse_args()
    main(args)