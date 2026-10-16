import argparse
import os
import sys

sys.path.append('XHSTTImporter')
sys.path.append('XHSTTImporter/Constants')
import xhstt_input_reader
import solution_reader
from create_instance_for_khe import transform_instance_to_old_format_using_solution_with_student_assignments

sys.path.append('SolutionExporter')
from output_writer import write_instance_as_xhstt


def create_khe_instance(directory: str, file: str, solution_name: str, outputdir: str, solution_file: str = None, solution_directory: str = None) -> str:
    # Determine instance filename and base name
    if not file.endswith(".xml"):
        instance_filename = f"{file}.xml"
        base_name = file
    else:
        instance_filename = file
        base_name = file[:-4]

    # Read the instance
    print(f"Reading instance '{instance_filename}' from '{directory}'...")
    instance = xhstt_input_reader.read_XHSTT_input_file(directory, instance_filename)

    # Determine solution directory and file
    sol_dir = solution_directory if solution_directory is not None else directory
    sol_file = solution_file if solution_file is not None else instance_filename
    if not sol_file.endswith(".xml"):
        sol_file = f"{sol_file}.xml"

    # Read the solution
    print(f"Reading solution '{solution_name}' from '{sol_dir}/{sol_file}'...")
    solution = solution_reader.read_solution(str(sol_dir), str(sol_file), solution_name, instance, addMissingEvents=True)

    # Transform instance to KHE format using student assignments from solution
    print("Transforming instance to KHE format...")
    khe_instance = transform_instance_to_old_format_using_solution_with_student_assignments(instance, solution)

    # Output file and instance name with _khe appendix
    khe_name = f"{base_name}_khe"
    os.makedirs(outputdir, exist_ok=True)
    output_path = os.path.join(outputdir, f"{khe_name}.xml")

    # Save transformed instance
    print(f"Saving KHE instance to '{output_path}'...")
    write_instance_as_xhstt(khe_instance, id=khe_name, includeNewConstraints=False, outputPath=output_path)
    print(f"Successfully created KHE instance: '{output_path}'")

    return output_path


def main(args):
    return create_khe_instance(
        directory=args.directory,
        file=args.file,
        solution_name=args.solution,
        outputdir=args.outputdir,
        solution_file=getattr(args, 'solution_file', None),
        solution_directory=getattr(args, 'solution_directory', None),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Transform an instance to KHE format using student assignments from a solution.")
    parser.add_argument("-dir", "--directory", required=True, help="Directory in which the instance file lies")
    parser.add_argument("-fi", "--file", required=True, help="Instance XML file name")
    parser.add_argument("-sol", "--solution", required=True, help="Name/ID of the solution to read")
    parser.add_argument("-out", "--outputdir", required=True, help="Output directory where the transformed instance will be saved")
    parser.add_argument("-sf", "--solution_file", default=None, help="File containing the solution (defaults to --file if not specified)")
    parser.add_argument("-sd", "--solution_directory", default=None, help="Directory containing the solution file (defaults to --directory if not specified)")

    args = parser.parse_args()
    main(args)
