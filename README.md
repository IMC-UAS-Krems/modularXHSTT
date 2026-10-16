# modularXHSTT

Code and instances for the extended High School Timetabling Problem (XHSTT) with student sectioning and modular course constraints.

## Requirements & Installation

- **Python**: 3.10 or higher recommended.
- **ILP Solver**: [Gurobi](https://www.gurobi.com/) (required for ALNS via `gurobipy`; free academic licenses available).

Install all dependencies via `pip`:

```bash
pip install -r requirements.txt
```

*(Core dependencies: `gurobipy`, `numpy`, `xmltodict`, `networkx`, `prettytable`, `pandas`, `filelock`)*

---

## Running Example Scripts

Instances are located in `data/RealWorldInstances/`, `data/ArtificialInstances/`, and `data/ArtificiallyModifiedRealWorldInstances/`.

### 1. Adaptive Large Neighborhood Search (ALNS)

Solves an instance using a construction heuristic followed by ALNS with ILP-based destroy and repair neighborhoods (requires an active Gurobi installation):

```bash
python ALNS_example.py -dir data/RealWorldInstances -fi GermanyRHPF1.xml -tl 3600
```

**Parameters:**
- `-dir`, `--directory`: Path to directory containing instance files (e.g. `data/RealWorldInstances`).
- `-fi`, `--file`: Instance XML filename (e.g. `GermanyRHPF1.xml`).
- `-tl`, `--timelimit`: Execution time limit in seconds (default: `10800`).
- `-nr`, `--number`: Instance or run identifier (default: `1`).

### 2. Simulated Annealing (SA)

Solves an instance using a construction heuristic followed by multi-neighborhood Simulated Annealing:

```bash
python SA_example.py -dir data/RealWorldInstances -fi GermanyRHPF1.xml
```

**Parameters:**
- `-dir`, `--directory`: Path to directory containing instance files (e.g. `data/RealWorldInstances`).
- `-fi`, `--file`: Instance XML filename (e.g. `GermanyRHPF1.xml`).
- `-nr`, `--number`: Instance or run identifier (default: `1`).

### 3. KHE Instance Converter

Converts an extended XHSTT instance into the classic KHE format by fixing student course selections from an existing solution:

```bash
python create_khe_instance_example.py -dir data/RealWorldInstances -fi GermanyRHPF1.xml -sol <solution_name> -out converted_instances/
```

The output file is saved as `<input_name>_khe.xml` in the specified output directory.

**Parameters:**
- `-dir`, `--directory`: Directory containing the instance XML file.
- `-fi`, `--file`: Instance XML filename.
- `-sol`, `--solution`: Solution ID/name to extract student assignments from.
- `-out`, `--outputdir`: Directory where the converted `<name>_khe.xml` file will be saved.
- `-sd`, `--solution_directory`: *(Optional)* Directory containing the solution file (defaults to `-dir`).
- `-sf`, `--solution_file`: *(Optional)* Solution file name if stored separately from the instance (defaults to `-fi`).