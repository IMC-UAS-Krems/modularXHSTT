import copy
import math
import os
import sys
import random
import time
import numpy as np
import uuid
from ALNS_Config import ALNS_Config
sys.path.append('../XHSTTImporter')
sys.path.append('XHSTTImporter')
from XHSTTImporter.Instance import Instance
sys.path.append('../XHSTTImporter/Constants')
sys.path.append('XHSTTImporter/Constants')
import XHSTTConstraintConstants, XHSTTFileConstants
sys.path.append('../ILP_solver')
sys.path.append('ILP_solver')
sys.path.append('../ILPSolver')
sys.path.append('ILPSolver')
from gurobi_solver import ILPModel
sys.path.append('../validator')
sys.path.append('validator')
import validator
sys.path.append('../Simulated_Annealing')
sys.path.append('Simulated_Annealing')
from SA_Config import SA_Config
from SA import do_n_iterations_of_simulated_annealing_with_cutoff
sys.path.append('../SolutionExporter')
sys.path.append('SolutionExporter')
import SolutionDataConstants
import io
from generate_heuristic_solution import HeuristicSolutionGenerator

class ALNS:
    def __init__(self, model: ILPModel, instance: Instance, neighborhoods: list, best_known_solution: dict, config=ALNS_Config(), stop_event=None):
        self.SA_CONFIG = SA_Config()
        self.config = config
        random.seed(self.config.SEED)
        np.random.seed(self.config.SEED)
        self.solver = config.SOLVER
        self.model = model
        self.instance = instance
        self.log = list()
        self.neighborhoods = neighborhoods
        if self.solver == "ILP" or self.solver == "MIXED":
            self.neighborhood_sizes = [self.config.INITIAL_NEIGHBORHOOD_SIZE for _ in self.neighborhoods]
        else:
            self.neighborhood_sizes = config.FIXED_NEIGHBORHOOD_SIZES
        self.neighborhood_jump_sizes = [self.config.INITIAL_NEIGHBORHOOD_JUMP_SIZE for _ in self.neighborhoods]
        self.improvement_vector_per_neighborhood = [list() for _ in self.neighborhoods]
        self.reward_mean = 0
        self.reward_stddev = 1.0
        self.reward_var = 1.0  # Tracks variance to compute stddev cleanly
        self.reward_vector = list()
        self.alpha_q = 0.15
        self.q_values = [0.0 for _ in self.neighborhoods]
        self._stats_initialized = False
        self.time_vector_per_neighborhood = [list() for _ in self.neighborhoods]
        self.time_vector_per_neighborhood_per_size = [dict() for _ in self.neighborhoods]
        self.added_constraint_sets = list()
        self.best_known_solution = best_known_solution
        self.temporary_best_known_solution = best_known_solution
        self.temperature = self.config.TEMP
        self.current_time_step = 0
        self.last_time_target_change_time_step = 0
        self.last_change_weight_time_step = 0
        self.last_improvement_of_best_known_solution_time_step = 0
        self.last_improvement_of_temporary_best_known_solution_time_step = 0
        self.exploration_rate = self.config.EXPLORATION_RATE
        self.time_target = self.config.INITIAL_TIME_TARGET
        self.stored_time_target = self.config.INITIAL_TIME_TARGET
        self.time_limit_per_neighborhood = self.config.INITIAL_TIME_TARGET * 2
        validatorObjectiveValue = best_known_solution[SolutionDataConstants.VALIDATOR_OBJECTIVE]
        if self.config.OUTPUT_LEVEL >= 1:
            print(f"Initial Validator Objective: {validatorObjectiveValue}")
        self._create_copy_of_weights_for_each_constraint()
        self.imprecision_counter = 0
        if validatorObjectiveValue < 1:
            self.is_feasible = True
            self.model.fix_all_hard_constraints_to_zero()
            self.best_known_objective_value = round(validatorObjectiveValue, 5)
            self.temporary_best_known_objective_value = round(validatorObjectiveValue, 5)
        else:
            self.is_feasible = False
            if self.config.IGNORE_SOFT_CONSTRAINTS_WHEN_INFEASIBLE:
                self._change_weight_of_all_soft_constraints_to_zero()
                self.best_known_objective_value = round(validatorObjectiveValue, 0)
                self.temporary_best_known_objective_value = round(validatorObjectiveValue, 0)
            else:
                self.best_known_objective_value = round(validatorObjectiveValue, 5)
                self.temporary_best_known_objective_value = round(validatorObjectiveValue, 5)
        self.currently_changed_constraint_weight = None
        self.constraint_focus_for_neighborhood = None
        self.taboo_solution_list = list()
        self.dont_count_next_improvement = False
        self.currentConstraints = None
        self.useSoft = True
        self.deltaEvaluator = None

        if config.ACCEPTANCE_FUNCTION == "METROPOLIS":
            self.acceptance_function = self._check_metropolis_acceptance
            self.start_temperature = 144.27
            self.temperature = 144.27
            self.end_temperature = 3.34e-6
        elif config.ACCEPTANCE_FUNCTION == "RRT":
            self.acceptance_function = self._check_rrt_acceptance
            self.deviation_threshold = 10.0
        else:
            self.acceptance_function = self._check_hill_climb_acceptance
        self.stop_event = stop_event
        self.last_neighborhood_that_improved_best_known = -1
        self.last_neighborhood_that_improved_temp = -1
        self.time_penalty_factor = -0.001
        self.iteration_time_history = list()
        self.section_time_measurements = dict()
        self.iteration_start = time.time()

    def execute_random_neighborhoods_till_time_limit_reached(self, totalTimeLimit):
        start_time = time.time()
        solutionData = copy.deepcopy(self.best_known_solution)
        self.added_constraint_sets = self.model.update_constraints_to_fix_variables(solutionData,
                                                                                    self.added_constraint_sets)
        self._optimize_using_current_solution(totalTimeLimit)
        self._update_model_if_solution_becomes_feasible()
        while time.time() - start_time < totalTimeLimit and (self.stop_event is None or not self.stop_event.is_set()):
            self.iteration_start = time.time()
            if self.config.USE_UCB_MULTI_ARMED_BANDIT:
                self.execute_most_promising_neighborhood()
            else:
                self.execute_random_neighborhood()
            self._output_stats_after_neighborhood_executed()
            post_process_start = time.time()
            if self.best_known_objective_value == 0.0:
                break
            self._adapt_time_target()
            self._change_weight_of_random_constraint_if_applicable()
            self.update_acceptance_vars(time.time() - start_time, totalTimeLimit)
            self.section_time_measurements.setdefault("post_process", list()).append(time.time() - post_process_start)
            self.iteration_time_history.append(time.time() - self.iteration_start)
        self._output_final_statistics()
        self.best_known_solution[SolutionDataConstants.OBJECTIVE_VALUE] = self.best_known_objective_value
        emptySolution = dict()
        emptySolution[XHSTTFileConstants.EVENTS] = dict()
        self.model.update_constraints_to_fix_variables(emptySolution, self.added_constraint_sets)
        return self.best_known_solution, self.reward_vector

    def update_acceptance_vars(self, passedTime, totalTimeLimit):
        if self.config.ACCEPTANCE_FUNCTION == "METROPOLIS":
            p = float(passedTime)/float(totalTimeLimit)
            self.temperature = self.start_temperature*math.pow((self.end_temperature/self.start_temperature), p)
        elif self.config.ACCEPTANCE_FUNCTION == "RRT":
            self.deviation_threshold = max(self.best_known_objective_value * 0.1, 10.0)
            if self.config.OUTPUT_LEVEL >= 1:
                print(f"Current deviation threshold: {self.deviation_threshold}")

    def execute_random_neighborhood(self):
        selectedNeighborhoodIndex = random.randint(0, len(self.neighborhoods) - 1)
        self.execute_neighborhood(selectedNeighborhoodIndex)
        self._update_model_if_solution_becomes_feasible()

    def execute_most_promising_neighborhood(self):
        neighborhood_selection_start = time.time()
        averageRewards = []
        for i in range(len(self.improvement_vector_per_neighborhood)):
            moving_avg = self.q_values[i]
            exploration_value = 100 * (self.config.INITIAL_AMOUNT_OF_EXPLORATIONS - len(self.improvement_vector_per_neighborhood[i])) - 50
            if exploration_value > 0:
                averageRewards.append(exploration_value)
            else:
                averageRewards.append(moving_avg)
        actionProbabilites = self.get_softmax_estimates_of_actions(averageRewards, self.temperature)
        selectedNeighborhoodIndex = self.select_action_based_on_probability_distribution(actionProbabilites)
        if self.config.OUTPUT_LEVEL >= 1:
            for neighborhoodIndex in range(len(self.neighborhoods)):
                print(f"{self.neighborhoods[neighborhoodIndex].__name__}: Estimate: {averageRewards[neighborhoodIndex]}, Number of Selections: {len(self.improvement_vector_per_neighborhood[neighborhoodIndex])}, Probability of selection: {actionProbabilites[neighborhoodIndex]} Average Time: {self._get_average_runtime_of_neighborhood(neighborhoodIndex)}, Average Time Current Neighborhood Size: {self._get_average_runtime_of_neighborhood(neighborhoodIndex, neighborhoodSize=self.neighborhood_sizes[neighborhoodIndex])}, Current Size: {self.neighborhood_sizes[neighborhoodIndex]}")
        self.section_time_measurements.setdefault("neighborhood_selection", list()).append(time.time() - neighborhood_selection_start)
        reward = self.execute_neighborhood(selectedNeighborhoodIndex)
        self.reward_vector.append(reward)

        self._update_model_if_solution_becomes_feasible()

    def execute_neighborhood(self, selectedNeighborhoodIndex: int) -> float:
        init_execute_start = time.time()
        solutionData = copy.deepcopy(self.temporary_best_known_solution)
        self.get_objective_values_according_to_validator(self.temporary_best_known_solution, outputObjectives=False)
        real_objective_value = self.temporary_best_known_solution[SolutionDataConstants.VALIDATOR_OBJECTIVE]
        selectedNeighborhood = self.neighborhoods[selectedNeighborhoodIndex]
        selectedNeighborhoodSize = self.neighborhood_sizes[selectedNeighborhoodIndex]
        if self.config.OUTPUT_LEVEL >= 1:
            print(f"Selected Neighborhood {selectedNeighborhood.__name__} with size {selectedNeighborhoodSize}")
        self.section_time_measurements.setdefault("init_execute", list()).append(
            time.time() - init_execute_start)
        neighborhood_start_time = time.time()
        neighborhoodExecutedDeletion = selectedNeighborhood(self.instance, solutionData, selectedNeighborhoodSize, not self.config.USE_DEVIATION_INFORMATION, not self.is_feasible, self.constraint_focus_for_neighborhood, self.deltaEvaluator)
        if self.config.OUTPUT_LEVEL >= 1:
            print(f"Neighborhood execution took {time.time() - neighborhood_start_time}")
        neighborhoodExecutedDeletion = self._update_taboo_list(solutionData, neighborhoodExecutedDeletion)
        self.section_time_measurements.setdefault("delete_execute", list()).append(
            time.time() - neighborhood_start_time)
        if neighborhoodExecutedDeletion:
            self.current_time_step += 1
            runtime, reward = self._optimize_and_return_runtime(selectedNeighborhoodIndex, solutionData)
            self._change_neighborhood_size_based_on_runtime_and_time_limit(selectedNeighborhoodIndex, runtime)
        else:
            raw_reward = 0.0
            self._update_reward_statistics(raw_reward, alpha=self.alpha_q)
            reward = self.calc_reward(raw_reward)
            if self.config.OUTPUT_LEVEL > 0:
                print(f"Given reward: {reward}")
            self._update_q_values(reward, selectedNeighborhoodIndex)
            self.improvement_vector_per_neighborhood[selectedNeighborhoodIndex].append(raw_reward)

            if real_objective_value < self.best_known_objective_value:
                if self.config.OUTPUT_LEVEL > 0:
                    print("Found new Global Best")
                self._update_global_best_solution(self.temporary_best_known_solution, real_objective_value, selectedNeighborhoodIndex)

            elif real_objective_value < self.temporary_best_known_objective_value:
                if self.config.OUTPUT_LEVEL > 0:
                    print("Found normal local improvement")
                self._update_temporary_best_solution(self.temporary_best_known_solution, real_objective_value)

        return reward

    def _update_taboo_list(self, solutionData, neighborhoodExecutedDeletion) -> bool:
        taboo_start_time = time.time()
        if solutionData in self.taboo_solution_list or neighborhoodExecutedDeletion == False:
            neighborhoodExecutedDeletion = False
            if solutionData in self.taboo_solution_list and self.config.OUTPUT_LEVEL >= 1:
                print("Found TABOO solution")
        else:
            neighborhoodExecutedDeletion = True
            self.taboo_solution_list.append(solutionData)
            if len(self.taboo_solution_list) > self.config.TABOO_LENGTH:
                self.taboo_solution_list = self.taboo_solution_list[-self.config.TABOO_LENGTH:]
            if self.solver == "ILP" or self.solver == "MIXED":
                self.added_constraint_sets = self.model.update_constraints_to_fix_variables(solutionData, self.added_constraint_sets)
        if self.config.OUTPUT_LEVEL >= 1:
            print(f"Taboo update took {time.time() - taboo_start_time}")
        return neighborhoodExecutedDeletion

    def _execute_solver(self, solutionData: dict) -> tuple:
        """Dispatches processing logic to the active solver algorithm."""
        randomValue = random.random()
        if self.solver == "ILP" or (self.solver == "MIXED" and randomValue < sum(self.config.SOLVER_PROBS[:-1])):
            self.model.update_constraints_to_fix_variables(solutionData, self.added_constraint_sets)
            self.model.provide_warm_start_solution(self.temporary_best_known_solution)
            return self.model.optimize_model(
                time_limit=self.time_limit_per_neighborhood,
                best_known_objective_value=self.temporary_best_known_objective_value,
                validate_result=False, use_cutoffs=False
            )

        elif self.solver == "SA" or (self.solver == "MIXED" and randomValue < sum(self.config.SOLVER_PROBS[:])):
            new_solution = do_n_iterations_of_simulated_annealing_with_cutoff(self.instance, solutionData, total_iterations=self.SA_CONFIG.ITERATIONS,
                                                               start_acceptance_rate=self.SA_CONFIG.START_ACCEPTANCE_RATE,
                                                               end_acceptance_rate=self.SA_CONFIG.END_ACCEPTANCE_RATE,
                                                               cooling_rate=self.SA_CONFIG.COOLING_RATE,
                                                               cutoff_ratio=self.SA_CONFIG.CUTOFF_RATIO,
                                                               neighborhood_probabilities=self.SA_CONFIG.NEIGHBORHOOD_PROBABILITIES,
                                                               output=self.config.OUTPUT_LEVEL >= 2)
            # new_solution = do_n_iterations_of_simulated_annealing_with_cutoff(
            #     self.instance, solutionData, total_iterations=20000,
            #     start_temp=0.1038145299810059, min_temp=8.993929236699106e-07,
            #     cooling_rate=0.8734697939311208, cutoff_ratio=0.1376629843950715,
            #     reheat_factor=22, reheat_iteration_factor=7, output=True, limit_searchspace=True
            # )
            if new_solution is None:
                return ("Feasible", self.temporary_best_known_solution)

            return ("Feasible", new_solution)

        elif self.solver == "HEURISTIC":
            solutionGenerator = HeuristicSolutionGenerator(self.instance, partial_solution=solutionData, output=False)
            new_solution = solutionGenerator.generate_heuristic_solution()
            self.get_objective_values_according_to_validator(new_solution)
            new_solution[SolutionDataConstants.OBJECTIVE_VALUE] = solutionData[
                SolutionDataConstants.VALIDATOR_OBJECTIVE]
            return ("Feasible", new_solution)

        return None

    def _apply_zero_reward(self, selectedNeighborhoodIndex: int, time_penalty=0.0):
        """Handles updating historical tracking statistics when no improvement is made."""
        raw_reward = time_penalty * self.time_penalty_factor
        self._update_reward_statistics(raw_reward, alpha=self.alpha_q)
        reward = self.calc_reward(raw_reward)
        if self.config.OUTPUT_LEVEL >= 1:
            print(f"Given reward: {reward}")
        self._update_q_values(reward, selectedNeighborhoodIndex)
        self.improvement_vector_per_neighborhood[selectedNeighborhoodIndex].append(raw_reward)
        return reward

    def _handle_validator_mismatch(self, solutionData: dict, objective_value_ilp: float, obj_val_changed_weight: float):
        """Processes discrepancy logs when solver evaluation drifts from standard validation."""
        show_outputs = self.config.OUTPUT_LEVEL >= 1
        validator.get_objective_value(
            self.instance, solutionData,
            useWeightCopy=True,
            outputObjectiveValues=show_outputs,
            hardOnly=not self.useSoft, relevantConstraintTypes=self.currentConstraints
        )
        if show_outputs:
            print(f"Values of ILP and Validator have to match ({objective_value_ilp} vs {obj_val_changed_weight})")
        self.imprecision_counter += 1

    def _apply_improvement_rewards(self, obj_val: float, selectedNeighborhoodIndex: int, reconstruction_time) -> float:
        """Calculates scaling updates and scores adaptive metrics based on improvements."""
        if reconstruction_time == 0.0:
            reconstruction_time = 0.1
        if obj_val == 0.0:
            raw_reward = 50.0
        elif self.best_known_objective_value == 0.0:
            raw_reward = 0.0
        else:
            raw_reward = (math.log(self.temporary_best_known_objective_value) - math.log(obj_val))
            if obj_val < self.best_known_objective_value:
                raw_reward += (math.log(self.best_known_objective_value) - math.log(obj_val)) * 5

        time_penalty = self.time_penalty_factor * reconstruction_time

        shaped_reward = raw_reward + time_penalty
        if self.config.OUTPUT_LEVEL >= 1:
            print(
                f"Shaped reward: {shaped_reward} temporary best obj val: {self.temporary_best_known_objective_value} objVal changed weight: {obj_val}")
        self._update_reward_statistics(shaped_reward, alpha=self.alpha_q)
        reward = self.calc_reward(shaped_reward)
        if self.config.OUTPUT_LEVEL >= 1:
            print(f"Given reward: {reward} (raw reward: {shaped_reward})")

        if not self.dont_count_next_improvement:
            self._update_q_values(reward, selectedNeighborhoodIndex)
            self.improvement_vector_per_neighborhood[selectedNeighborhoodIndex].append(shaped_reward)
            self.dont_count_next_improvement = False

        self.last_neighborhood_that_improved_temp = selectedNeighborhoodIndex

        return reward

    def calc_reward(self, raw_reward):
        return raw_reward
    def _update_global_best_solution(self, solutionData: dict, real_objective_value: float, selectedNeighborhoodIndex: int):
        """Saves historical metrics when an absolute global minimum solution threshold is broken."""
        solutionDif = self._get_solution_difference(solutionData, self.best_known_solution)
        self.log.append((self.best_known_objective_value - real_objective_value, solutionDif))
        if self.config.OUTPUT_LEVEL >= 3:
            print(f"New solution with following differences: {solutionDif}")

        self.best_known_objective_value = real_objective_value
        self.best_known_solution = solutionData
        self.last_neighborhood_that_improved_best_known = selectedNeighborhoodIndex

        self.temporary_best_known_objective_value = real_objective_value
        self.temporary_best_known_solution = solutionData
        self.last_improvement_of_best_known_solution_time_step = self.current_time_step
        self.last_improvement_of_temporary_best_known_solution_time_step = self.current_time_step
        self._reset_change_of_weight_for_violated_constraint()

        self.last_time_target_change_time_step = self.current_time_step
        self._decrease_time_target()

    def _update_temporary_best_solution(self, solutionData: dict, obj_val: float):
        """Mutates current metadata when the internal regional objective metric drops."""
        self.temporary_best_known_objective_value = obj_val
        self.temporary_best_known_solution = solutionData
        self.constraint_focus_for_neighborhood = None
        self.last_improvement_of_temporary_best_known_solution_time_step = self.current_time_step

    def _check_hill_climb_acceptance(self, new_obj: float, current_obj: float) -> bool:
        return new_obj <= current_obj

    def _check_rrt_acceptance(self, new_obj: float, current_obj: float) -> bool:
        return new_obj <= self.best_known_objective_value + getattr(self, 'deviation_threshold', 0)
    def _check_metropolis_acceptance(self, new_obj: float, current_obj: float) -> bool:
        """Determines acceptance based on the Metropolis criterion."""
        # Always accept improvements
        if new_obj <= current_obj:
            return True

        # Metropolis calculation for worse solutions
        delta_e = new_obj - current_obj

        # Guard against division by zero or negative temperatures
        if getattr(self, 'temperature', 0) <= 0:
            return False

        probability = math.exp(-delta_e / self.temperature)
        return random.random() < probability

    def _optimize_and_return_runtime(self, selectedNeighborhoodIndex: int, solutionData: dict) -> (float, float):
        start_time = time.time()

        # 1. Run the configured solver
        result = self._execute_solver(solutionData)

        reward_update_start = time.time()
        reconstruction_time = time.time() - start_time

        if result is None or result[1] is None:
            if self.config.OUTPUT_LEVEL >= 1:
                print("No solution from ILP")
            reward = self._apply_zero_reward(selectedNeighborhoodIndex, time_penalty=reconstruction_time)

            return reconstruction_time, reward

        solutionData = result[1]
        rounding_level = 0 if (self.config.IGNORE_SOFT_CONSTRAINTS_WHEN_INFEASIBLE and not self.is_feasible) else 5

        # --- CHANGED: We no longer reject worse ILP solutions early here ---

        # 2. Evaluate ground-truth objective quality using the validation engine
        self.get_objective_values_according_to_validator(solutionData)
        real_objective_value = round(solutionData[SolutionDataConstants.VALIDATOR_OBJECTIVE], rounding_level)

        # if objective_value_ilp != obj_val_changed_weight:
        #     print("Here 2")
        #     self._handle_validator_mismatch(solutionData, objective_value_ilp, obj_val_changed_weight)

        # 3. CHANGED: Apply Acceptance Function using the true validated weight
        accepted = self.acceptance_function(real_objective_value, self.temporary_best_known_objective_value)

        if not accepted:
            if self.config.OUTPUT_LEVEL >= 1:
                print("Rejected Solution")
            # Sync constraints back to the true best state since this move was discarded
            validator.get_objective_value(
                self.instance, self.temporary_best_known_solution,
                useWeightCopy=True,
                hardOnly=not self.useSoft, relevantConstraintTypes=self.currentConstraints
            )
            reward = self._apply_zero_reward(selectedNeighborhoodIndex, time_penalty=reconstruction_time)
            self.section_time_measurements.setdefault("reward_update", list()).append(
                time.time() - reward_update_start)
            return time.time() - start_time, reward

        #  or self._are_schedules_equal(self.temporary_best_known_solution, solutionData)
        if real_objective_value == self.temporary_best_known_objective_value:
            if self.config.OUTPUT_LEVEL >= 1:
                print("Solution did not change")
            reward = self._apply_zero_reward(selectedNeighborhoodIndex, time_penalty=reconstruction_time)
            self.section_time_measurements.setdefault("reward_update", list()).append(
                time.time() - reward_update_start)
            return time.time() - start_time, reward

        # 4. Process rewards (Note: raw_reward will be negative for worse accepted moves)
        if self.temporary_best_known_objective_value != math.inf:
            reward = self._apply_improvement_rewards(real_objective_value, selectedNeighborhoodIndex, reconstruction_time)
        else:
            reward = self._apply_zero_reward(selectedNeighborhoodIndex, time_penalty=reconstruction_time)

        # 5. Route state mutations for accepted pathways
        if real_objective_value < self.best_known_objective_value:
            if self.config.OUTPUT_LEVEL >= 1:
                print("Found new Global Best")
            self._update_global_best_solution(solutionData, real_objective_value, selectedNeighborhoodIndex)

        elif real_objective_value < self.temporary_best_known_objective_value:
            if self.config.OUTPUT_LEVEL >= 1:
                print("Found normal local improvement")
            self._update_temporary_best_solution(solutionData, real_objective_value)

        else:
            # CHANGED: This handles the "Worse but accepted via Metropolis" state assignment
            if self.config.OUTPUT_LEVEL >= 1:
                print("Accepted move event though it is worse")
            self.temporary_best_known_objective_value = real_objective_value
            self.temporary_best_known_solution = solutionData
            self.constraint_focus_for_neighborhood = None
        self.section_time_measurements.setdefault("reward_update", list()).append(
            time.time() - reward_update_start)
        return time.time() - start_time, reward

    def _are_schedules_equal(self, schedule1, schedule2):
        schedule1Events = schedule1[XHSTTFileConstants.EVENTS]
        schedule2Events = schedule2[XHSTTFileConstants.EVENTS]

        for event in schedule1Events.keys():
            if event not in schedule2Events:
                return False
            solutionEvent1 = schedule1Events[event]
            solutionEvent2 = schedule2Events[event]
            if solutionEvent1[XHSTTFileConstants.TIME] != solutionEvent2[XHSTTFileConstants.TIME]:
                return False
            for resource in solutionEvent1[XHSTTFileConstants.RESOURCES].keys():
                if (resource not in solutionEvent2[XHSTTFileConstants.RESOURCES] or
                    solutionEvent1[XHSTTFileConstants.RESOURCES][resource] != solutionEvent2[XHSTTFileConstants.RESOURCES][resource]):
                    return False
            for resource in solutionEvent2[XHSTTFileConstants.RESOURCES].keys():
                if resource not in solutionEvent2[XHSTTFileConstants.RESOURCES]:
                    return False

        for event in schedule2Events.keys():
            if event not in schedule1Events:
                return False

        return True

    def _update_q_values(self, reward, neighborhood_index):
        old_q = self.q_values[neighborhood_index]
        self.q_values[neighborhood_index] = old_q + self.alpha_q * (reward - old_q)
        # self.pull_counts[neighborhood_index] += 1
    def _update_reward_statistics(self, raw_reward, alpha=0.05):
        if not self._stats_initialized:
            self.reward_mean = float(raw_reward)
            # Keep variance/stddev at 1.0 initially to avoid immediate division by zero
            self.reward_var = 1.0
            self.reward_stddev = 1.0
            self._stats_initialized = True
            return

            # 2. Calculate the difference between the raw reward and the OLD mean
            # (It is critical to use the old mean for the variance update)
        # Clip potentially huge early rewards to not screw later rewards
        raw_reward = min(raw_reward, 100.0)
        delta = raw_reward - self.reward_mean

        # 3. Update the EWMA mean
        self.reward_mean += alpha * delta
        if self.config.OUTPUT_LEVEL >= 1:
            print(f"Current reward mean {self.reward_mean}")
        # 4. Update the EWMA variance
        # Formula: Var_t = (1 - alpha) * (Var_{t-1} + alpha * (x_t - old_mean)^2)
        self.reward_var = (1 - alpha) * (self.reward_var + alpha * (delta ** 2))

        # 5. Update the standard deviation (what you actually care about)
        self.reward_stddev = self.reward_var ** 0.5
    def _optimize_using_current_solution(self, timeLimit: int):
        result = self.model.optimize_model(time_limit=timeLimit,
                                           best_known_objective_value=self.best_known_objective_value, validate_result=True, use_cutoffs=False)
        if result is not None and result[1] is not None:
            solutionData = result[1]
            objectiveValue = round(solutionData[SolutionDataConstants.VALIDATOR_OBJECTIVE], 5)
            if objectiveValue < self.best_known_objective_value and objectiveValue != math.inf:
                self.best_known_objective_value = objectiveValue
                self.best_known_solution = solutionData
                self.temporary_best_known_objective_value = objectiveValue
                self.temporary_best_known_solution = solutionData
            if self.config.OUTPUT_LEVEL >= 1:
                print(f"Initial Objective Value: {self.best_known_objective_value}")
        else:
            if self.config.OUTPUT_LEVEL >= 1:
                print("Initial solution Infeasible")

    def _update_best_known_solution_after_feasiblity_reached(self):
        self.added_constraint_sets = self.model.update_constraints_to_fix_variables(self.best_known_solution,
                                                                                    self.added_constraint_sets)
        result = self.model.optimize_model(validate_result=True, reset=True)
        if result is not None and result[1] is not None:
            solutionData = result[1]
            objectiveValue = round(solutionData[SolutionDataConstants.VALIDATOR_OBJECTIVE], 5)
            if self.config.OUTPUT_LEVEL >= 1:
                print(f"OBJECTIVE VALUE {objectiveValue}")
            self.best_known_objective_value = objectiveValue
            self.best_known_solution = solutionData
            self.temporary_best_known_objective_value = objectiveValue
            self.temporary_best_known_solution = solutionData

    def _calculate_bandit_estimate_for_reward_vector(self, rewards: list, time_step=100, exploration_rate=0.00003):
        c = exploration_rate
        if len(rewards) == 0:
            q = 0
        else:
            q = sum(rewards) / len(rewards)
        if time_step == 0:
            time_step = 1
        if len(rewards) >= self.config.INITIAL_AMOUNT_OF_EXPLORATIONS:
            estimate = q + c * math.sqrt(math.log(time_step, math.e) / len(rewards))
        else:
            # Execute each neighborhood 10 times before using bandit algorithm to get better initial estimates
            estimate = 1000000 * (self.config.INITIAL_AMOUNT_OF_EXPLORATIONS - len(rewards) + 1)
        return estimate

    def get_softmax_estimates_of_actions(self, meansList: list[float], temperature: float) -> list[float]:
        max_mean = max(meansList)

        bolzmanExpValueList = []
        for q in meansList:
            # 2. Subtract the max to guarantee numerical stability (no OverflowErrors)
            safe_exp = math.exp((q - max_mean) / temperature)
            bolzmanExpValueList.append(safe_exp)

        if self.config.OUTPUT_LEVEL >= 1:
            print(f"Mean List: {meansList}, Safe Exp Values: {bolzmanExpValueList}")

        sumOfBolzmanExpValues = sum(bolzmanExpValueList)

        # 3. Calculate final probabilities
        pValuesOfActions = [val / sumOfBolzmanExpValues for val in bolzmanExpValueList]

        return pValuesOfActions

    def get_Boltzman_exp_value(self, currentMean: float, temperature: float) -> float:
        try:
            ans = math.exp(currentMean / temperature)
        except OverflowError:
            ans = sys.float_info.max
        return ans
    def select_action_based_on_probability_distribution(self, probabilities) -> int:
        return random.choices(range(len(probabilities)), weights=probabilities, k=1)[0]

    def _change_neighborhood_size_based_on_runtime_and_time_limit(self, selectedNeighborhoodIndex, runtime):
        timeTolerance = self.config.TIME_TOLERANCE
        selected_neighborhood_size = self.neighborhood_sizes[selectedNeighborhoodIndex]
        self.time_vector_per_neighborhood[selectedNeighborhoodIndex].append(runtime)
        self.time_vector_per_neighborhood_per_size[selectedNeighborhoodIndex].setdefault(selected_neighborhood_size, list()).append(runtime)
        average_time_of_neighborhood_using_current_size = self._get_average_runtime_of_neighborhood(selectedNeighborhoodIndex, selected_neighborhood_size)
        jump_size_of_neighborhood = self.neighborhood_jump_sizes[selectedNeighborhoodIndex]
        for i in range(max(0, selected_neighborhood_size - jump_size_of_neighborhood), selected_neighborhood_size + jump_size_of_neighborhood + 1):
            self.time_vector_per_neighborhood_per_size[selectedNeighborhoodIndex].setdefault(i, list())

        timesInSmallerNeighborhoods = list()
        for size in range(max(0, selected_neighborhood_size - jump_size_of_neighborhood), max(0, selected_neighborhood_size)):
            timesInSmallerNeighborhoods += self.time_vector_per_neighborhood_per_size[selectedNeighborhoodIndex][size]
        timesInBigerNeighborhoods = list()
        for size in range(selected_neighborhood_size + 1, selected_neighborhood_size + jump_size_of_neighborhood + 1):
            timesInBigerNeighborhoods += self.time_vector_per_neighborhood_per_size[selectedNeighborhoodIndex][size]
        if self.config.OUTPUT_LEVEL >= 2:
            print(f"Bigger Times {timesInBigerNeighborhoods}")
            print(f"Smaller Times {timesInSmallerNeighborhoods}")
            print(f"Jump Size: {jump_size_of_neighborhood}")
            print(f"Current size for selected neighborhood ({selectedNeighborhoodIndex}): {self.neighborhood_sizes[selectedNeighborhoodIndex]} current runtime: {runtime} time vector for size: {self.time_vector_per_neighborhood_per_size[selectedNeighborhoodIndex]} (Avg: {average_time_of_neighborhood_using_current_size}) ")
        if average_time_of_neighborhood_using_current_size > self.time_target * (1.0 + timeTolerance) and self.neighborhood_sizes[selectedNeighborhoodIndex] > 0 and (self.solver == "ILP" or self.solver == "MIXED"):
            previous_neighborhood_size = self.neighborhood_sizes[selectedNeighborhoodIndex]
            if len(timesInSmallerNeighborhoods) == 0:
                self.neighborhood_sizes[selectedNeighborhoodIndex] -= jump_size_of_neighborhood
            else:
                self.neighborhood_jump_sizes[selectedNeighborhoodIndex] = max(
                    self.neighborhood_jump_sizes[selectedNeighborhoodIndex] // 2, 1)
                self.neighborhood_sizes[selectedNeighborhoodIndex] -= self.neighborhood_jump_sizes[
                                                                          selectedNeighborhoodIndex]
            self.neighborhood_sizes[selectedNeighborhoodIndex] = max(self.neighborhood_sizes[selectedNeighborhoodIndex], 2)
            # If we go to a neighborhood with size 1 the jump was likely smaller than the current jump size and the next jump should not increase the neighborhood size to be larger than what we just saw was to big
            if (previous_neighborhood_size - self.neighborhood_sizes[selectedNeighborhoodIndex]) == 0:
                self.neighborhood_jump_sizes[selectedNeighborhoodIndex] = 1
            elif self.neighborhood_sizes[selectedNeighborhoodIndex] == 2 and self.neighborhood_jump_sizes[selectedNeighborhoodIndex] > 1 and (previous_neighborhood_size - self.neighborhood_sizes[selectedNeighborhoodIndex]) != 0:
                self.neighborhood_jump_sizes[selectedNeighborhoodIndex] = math.floor(math.log2(previous_neighborhood_size - self.neighborhood_sizes[selectedNeighborhoodIndex]))
            if self.config.OUTPUT_LEVEL >= 2:
                print("Decrease size")
        elif average_time_of_neighborhood_using_current_size < self.time_target * (1.0 - timeTolerance) and (self.solver == "ILP" or self.solver == "MIXED"):
            if len(timesInBigerNeighborhoods) == 0:
                self.neighborhood_sizes[selectedNeighborhoodIndex] += jump_size_of_neighborhood
            else:
                self.neighborhood_jump_sizes[selectedNeighborhoodIndex] = max(
                    self.neighborhood_jump_sizes[selectedNeighborhoodIndex] // 2, 1)
                self.neighborhood_sizes[selectedNeighborhoodIndex] += self.neighborhood_jump_sizes[
                                                                          selectedNeighborhoodIndex]
            if self.config.OUTPUT_LEVEL >= 2:
                print("Increase size")
        else:
            self.neighborhood_jump_sizes[selectedNeighborhoodIndex] = 1
            if self.config.OUTPUT_LEVEL >= 2:
                print("No change to size")

        # For fairness once we found the neighborhood size that fits the time target reset rewards
        # if jump_size_of_neighborhood > 1 and self.neighborhood_jump_sizes[selectedNeighborhoodIndex] == 1:
        #     self.improvement_vector_per_neighborhood[selectedNeighborhoodIndex] = list()
    def _update_model_if_solution_becomes_feasible(self):
        if not self.is_feasible and self.best_known_objective_value < 1:
            self.is_feasible = True
            self.model.fix_all_hard_constraints_to_zero()
            if self.config.IGNORE_SOFT_CONSTRAINTS_WHEN_INFEASIBLE:
                self._change_weight_of_all_soft_constraints_to_original_weight()
                self._update_best_known_solution_after_feasiblity_reached()
            # for neighborhoodIndex in range(len(self.time_vector_per_neighborhood)):
            #     self.time_vector_per_neighborhood[neighborhoodIndex] = list()
            #     self.time_vector_per_neighborhood_per_size[neighborhoodIndex] = dict()
            #     # condense reward vector into reward vectors of equal size so that exploration temporarily increases with new
            #     # constraint focuses without completly invalidating the previously established best neighborhoods
            #     rewards = self.improvement_vector_per_neighborhood[neighborhoodIndex]
            #     if len(rewards) > 0:
            #         self.improvement_vector_per_neighborhood[neighborhoodIndex] = [sum(rewards)/len(rewards) for _ in range(self.config.REWARD_VECTOR_LENGTH_AFTER_FEASIBILITY)]
            self.neighborhood_sizes = [self.config.INITIAL_NEIGHBORHOOD_SIZE for _ in self.neighborhoods]
            self.neighborhood_jump_sizes = [self.config.INITIAL_NEIGHBORHOOD_JUMP_SIZE for _ in self.neighborhoods]
            self.time_target = self.config.MIN_TIME


    def _output_stats_after_neighborhood_executed(self):
        if self.config.OUTPUT_LEVEL >= 1:
            print(f"Current best known objective value: {self.best_known_objective_value}")
            print(f"Current temporary best known objective value: {self.temporary_best_known_objective_value}")
        if self.config.OUTPUT_LEVEL >= 4:
            for constraintType in self.instance.Constraints.keys():
                for constraint in self.instance.Constraints[constraintType]:
                    if not constraint[XHSTTConstraintConstants.IS_FULFILLED] and constraint[XHSTTConstraintConstants.REQUIRED] != self.is_feasible:
                        print(f"{constraintType}: Number of deviation events {len(constraint[XHSTTConstraintConstants.DEVIATION_EVENTS])}, Number of deviations {constraint[XHSTTConstraintConstants.DEVIATION_AMOUNT]}, {constraint[XHSTTConstraintConstants.DEVIATION_EVENTS]}")
        elif self.config.OUTPUT_LEVEL >= 3:
            for constraintType in self.instance.Constraints.keys():
                for constraint in self.instance.Constraints[constraintType]:
                    if not constraint[XHSTTConstraintConstants.IS_FULFILLED] and constraint[XHSTTConstraintConstants.REQUIRED] != self.is_feasible:
                        print(f"{constraintType}: Number of deviation events {len(constraint[XHSTTConstraintConstants.DEVIATION_EVENTS])}, Number of deviations {constraint[XHSTTConstraintConstants.DEVIATION_AMOUNT]}")

    def _output_final_statistics(self):
        os.makedirs('data/solution_logs', exist_ok=True)
        if '/' in self.instance.Metadata[XHSTTFileConstants.FILE_NAME]:
            log_file = io.open(f'data/solution_logs/{self.instance.Metadata[XHSTTFileConstants.FILE_NAME].split("/")[1].split(".")[0] + str(uuid.uuid4()) + ".txt"}', 'w')
        else:
            log_file = io.open(f'data/solution_logs/{self.instance.Metadata[XHSTTFileConstants.FILE_NAME].split(".")[0] + str(uuid.uuid4()) + ".txt"}', 'w')
        for neighborhoodIndex in range(len(self.neighborhoods)):
            log_file.write(self.neighborhoods[neighborhoodIndex].__name__ + "\n")
            log_file.write(str([str(step_idx) + ": " + str(self.improvement_vector_per_neighborhood[neighborhoodIndex][step_idx]) for step_idx in range(len(self.improvement_vector_per_neighborhood[neighborhoodIndex]))]) + "\n")
            if self.config.OUTPUT_LEVEL >= 1:
                print(self.neighborhoods[neighborhoodIndex].__name__)
                print([str(step_idx) + ": " + str(self.improvement_vector_per_neighborhood[neighborhoodIndex][step_idx]) for step_idx in range(len(self.improvement_vector_per_neighborhood[neighborhoodIndex]))])
        log_file.write(f"Total number of imprecise iterations: {self.imprecision_counter} \n")
        log_file.write(f"Improvement log: {self.log} \n")
        if self.config.OUTPUT_LEVEL >= 3:
            print(f"Total number of imprecise iterations: {self.imprecision_counter} \n")
            print("Improvement log: \n")
            log_file.write("Improvement log: \n")
            for entry in self.log:
                if self.config.OUTPUT_LEVEL >= 1:
                    print(f"{entry} \n")
                log_file.write(f"{entry} \n")
        log_file.close()


    def _get_average_runtime_of_neighborhood(self, selectedNeighborhoodIndex, neighborhoodSize=None):
        averagedLength = self.config.AVERAGED_LENGTH_FOR_TIMES
        if neighborhoodSize is None:
            timeVector = self.time_vector_per_neighborhood[selectedNeighborhoodIndex]
        elif neighborhoodSize in self.time_vector_per_neighborhood_per_size[selectedNeighborhoodIndex].keys():
            timeVector = self.time_vector_per_neighborhood_per_size[selectedNeighborhoodIndex][neighborhoodSize]
        else:
            return 0
        if len(timeVector) == 0:
            return 0
        else:
            timeVector = timeVector[-min(len(timeVector), averagedLength):]
            return sum(timeVector)/(len(timeVector))

    def _decrease_time_target(self):
        if self.time_target > self.config.MIN_TIME:
            self.time_target = self.time_target * self.config.TIME_DECREASE_FACTOR
            if self.time_target < self.config.MIN_TIME:
                self.time_target = self.config.MIN_TIME

            self.time_limit_per_neighborhood = self.time_target * 2
    def _adapt_time_target(self):
        if self.current_time_step - self.last_time_target_change_time_step > self.config.TIME_STEPS_TILL_INCREASE and self.time_target < self.config.MAX_TIME:
            self.time_target = self.time_target * self.config.TIME_INCREASE_FACTOR
            if self.time_target > self.config.MAX_TIME:
                self.time_target = self.config.MAX_TIME
            self.time_limit_per_neighborhood = self.time_target * 2
            self.last_time_target_change_time_step = self.current_time_step

        if self.config.OUTPUT_LEVEL >= 1:
            print(f"Current Time Target: {self.time_target}")

    def _change_weight_of_random_constraint_if_applicable(self):
        if self.config.OUTPUT_LEVEL >= 1:
            print(f"Time since last weight change: {self.current_time_step - self.last_change_weight_time_step}")
            print(f"Time since last improvement of best known solution: {self.current_time_step - self.last_improvement_of_best_known_solution_time_step}")
            print(f"Time since last improvement of temporary best known solution: {self.current_time_step - self.last_improvement_of_temporary_best_known_solution_time_step}")
            print(f"Constraint weight is changed: {self.currently_changed_constraint_weight is not None}")
            if self.currently_changed_constraint_weight is not None:
                print(f"Weight before: {self.currently_changed_constraint_weight[XHSTTConstraintConstants.WEIGHT_COPY]}, Weight after: {self.currently_changed_constraint_weight[XHSTTConstraintConstants.WEIGHT]}")
        if self.config.OUTPUT_LEVEL >= 1:
            if self.currently_changed_constraint_weight is not None:
                print(f"Changed Constraint Name: {self.currently_changed_constraint_weight[XHSTTConstraintConstants.ID]}, Events: {[event[XHSTTConstraintConstants.NAME] for event in self.currently_changed_constraint_weight[XHSTTConstraintConstants.DEVIATION_EVENTS]]}, Times: {[event[XHSTTFileConstants.TIME] for event in self.currently_changed_constraint_weight[XHSTTConstraintConstants.DEVIATION_EVENTS]]}, Resources: {[event[XHSTTFileConstants.RESOURCES] for event in self.currently_changed_constraint_weight[XHSTTConstraintConstants.DEVIATION_EVENTS]]}")
            else:
                print("No changed Constraint")
        # Change weight initially after n iterations without improvement
        if self.currently_changed_constraint_weight is None and self.current_time_step - self.last_improvement_of_best_known_solution_time_step >= self.config.TIME_STEPS_TILL_WEIGHT_CHANGE:
            if self.config.OUTPUT_LEVEL >= 1:
                print("CHANGED CONSTRAINT WEIGHT OF RANDOM CONSTRAINT BECAUSE WE HAVE NOT FOUND AN IMPROVEMENT IN A WHILE")
            self._change_weight_of_random_violated_constraint()
        # weight is changed and since weight change temporary best known solution has not changed and we already tried for a bit
        if self.currently_changed_constraint_weight is not None and self.last_change_weight_time_step == self.last_improvement_of_temporary_best_known_solution_time_step and self.current_time_step - self.last_change_weight_time_step >= self.config.MAXIMUM_TIME_STEPS_WITHOUT_CHANGE_WHEN_WEIGHT_CHANGED:
            if self.config.OUTPUT_LEVEL >= 1:
                print("CHANGED DIFFERENT CONSTRAINT BECAUSE THIS ONE DID NOT LEAD TO ANY CHANGE")
            self._change_weight_of_random_violated_constraint()
        # weight is changed and no improvement happened in a while
        elif self.currently_changed_constraint_weight is not None and self.current_time_step - self.last_improvement_of_temporary_best_known_solution_time_step >= self.config.MAXIMUM_TIME_STEPS_WITHOUT_CHANGE_WHEN_WEIGHT_CHANGED:
            if self.config.OUTPUT_LEVEL >= 1:
                print("CHANGED DIFFERENT CONSTRAINT BECAUSE WE EXPLORED THIS ONE FOR LONG ENOUGH")
            self._change_weight_of_random_violated_constraint()
        # weight is changed for long enough in total to move on to different weight
        elif self.currently_changed_constraint_weight is not None and self.current_time_step - self.last_change_weight_time_step >= self.config.TIME_STEPS_TILL_RETURN_TO_BEST_KNOWN_SOLUTION:
            if self.config.OUTPUT_LEVEL >= 1:
                print("CHANGED DIFFERENT CONSTRAINT BECAUSE WE EXPLORED THIS ONE FOR LONG ENOUGH")
            self._change_weight_of_random_violated_constraint()
        # weight is changed for a while and we reset the weight change but not yet the solution
        elif (self.currently_changed_constraint_weight is not None and self.current_time_step - self.last_change_weight_time_step >= self.config.TIME_STEPS_TILL_WEIGHT_CHANGE_RESET and
              self.currently_changed_constraint_weight[XHSTTConstraintConstants.WEIGHT] != self.currently_changed_constraint_weight[XHSTTConstraintConstants.WEIGHT_COPY]):
            if self.config.OUTPUT_LEVEL >= 1:
                print("CHANGED BACK WEIGHT WITHOUT RESETING TO BEST KNOWN SOLUTION")
            # self.dont_count_next_improvement = True
            self.currently_changed_constraint_weight[XHSTTConstraintConstants.WEIGHT] = \
            self.currently_changed_constraint_weight[XHSTTConstraintConstants.WEIGHT_COPY]
            self.model._add_objective_function()
        # we arrived at the same solution as before the weight change so we choose a different weight
        elif self.currently_changed_constraint_weight is not None and self.current_time_step - self.last_change_weight_time_step >= self.config.TIME_STEPS_TILL_WEIGHT_CHANGE_RESET and self._are_schedules_equal(self.best_known_solution, self.temporary_best_known_solution):
            if self.config.OUTPUT_LEVEL >= 1:
                print("CHANGE DIFFERENT CONSTRAINT BECAUSE WE REACHED EXACT SAME SOLUTION")
            self._change_weight_of_random_violated_constraint()

    def _create_copy_of_weights_for_each_constraint(self):
        for constraintType in self.instance.Constraints.keys():
            for constraint in self.instance.Constraints[constraintType]:
                constraint[XHSTTConstraintConstants.WEIGHT_COPY] = int(constraint[XHSTTConstraintConstants.WEIGHT])

    def _change_weight_of_random_violated_constraint(self):
        self._reset_change_of_weight_for_violated_constraint()
        relevant_violated_constraints = list()
        if self.currentConstraints is not None:
            eligibleConstraintTypes = self.currentConstraints
        else:
            eligibleConstraintTypes = self.instance.Constraints.keys()
        for constraintType in eligibleConstraintTypes:
            if constraintType not in self.instance.Constraints:
                continue
            for constraint in self.instance.Constraints[constraintType]:
                if XHSTTConstraintConstants.IS_FULFILLED not in constraint:
                    raise ValueError(f"Constraint is missing fulfilled property: {constraint}")
                if not constraint[XHSTTConstraintConstants.IS_FULFILLED] and constraint[
                    XHSTTConstraintConstants.REQUIRED] != self.is_feasible:
                    relevant_violated_constraints.append(constraint)
        if len(relevant_violated_constraints) == 0:
            print("There are no relevant violated constraints (which should never be the case)")
            return
        chosen_violated_constraint = random.choice(relevant_violated_constraints)
        maximum_constraint_weight = max([int(constraint[XHSTTConstraintConstants.WEIGHT_COPY]) for constraintType in self.instance.Constraints.keys()
                                         for constraint in self.instance.Constraints[constraintType]
                                         if constraint[XHSTTConstraintConstants.REQUIRED] != self.is_feasible])
        # chosen_violated_constraint[XHSTTConstraintConstants.WEIGHT] = min(maximum_constraint_weight*10 // int(chosen_violated_constraint[XHSTTConstraintConstants.DEVIATION_AMOUNT]), int(chosen_violated_constraint[XHSTTConstraintConstants.WEIGHT_COPY])*10)
        if self.config.OUTPUT_LEVEL >= 1:
            print(f"MAX CONSTRAINT WEIGHT: {maximum_constraint_weight}")
        chosen_violated_constraint[XHSTTConstraintConstants.WEIGHT] = max((maximum_constraint_weight * 3) //
                                            int(chosen_violated_constraint[XHSTTConstraintConstants.DEVIATION_AMOUNT]),
                                            (int(chosen_violated_constraint[XHSTTConstraintConstants.WEIGHT_COPY]) * 5) //
                                            int(chosen_violated_constraint[XHSTTConstraintConstants.DEVIATION_AMOUNT]),
                                            maximum_constraint_weight,
                                            chosen_violated_constraint[XHSTTConstraintConstants.WEIGHT_COPY] * 2)
        validator.get_objective_value(self.instance, self.best_known_solution, useWeightCopy=False, hardOnly=not self.useSoft, relevantConstraintTypes=self.currentConstraints)
        # self.temporary_best_known_objective_value = round(newObjectiveValue, 5)
        # self.temporary_best_known_solution = self.best_known_solution
        self.currently_changed_constraint_weight = chosen_violated_constraint
        self.constraint_focus_for_neighborhood = chosen_violated_constraint[XHSTTConstraintConstants.ID]
        # self.stored_time_target = self.time_target
        # self.time_target = self.config.MIN_TIME
        self.model._add_objective_function()

    def _reset_change_of_weight_for_violated_constraint(self):
        if self.config.OUTPUT_LEVEL >= 1:
            print("Resetting changed weight")
        if self.currently_changed_constraint_weight is not None:
            self.currently_changed_constraint_weight[XHSTTConstraintConstants.WEIGHT] = self.currently_changed_constraint_weight[XHSTTConstraintConstants.WEIGHT_COPY]
            self.currently_changed_constraint_weight = None
            self.constraint_focus_for_neighborhood = None
            self.model._add_objective_function()
        # self.temporary_best_known_objective_value = self.best_known_objective_value
        self.last_improvement_of_temporary_best_known_solution_time_step = self.current_time_step
        # self.temporary_best_known_solution = self.best_known_solution
        self.last_change_weight_time_step = self.current_time_step
        # self.time_target = self.stored_time_target

    def get_objective_values_according_to_validator(self, solutionData, outputObjectives=True):
        if outputObjectives:
            outputObjectives = self.config.OUTPUT_LEVEL >= 1
        solutionData[SolutionDataConstants.VALIDATOR_OBJECTIVE] = validator.get_objective_value(self.instance,
                                                                                                solutionData,
                                                                                                useWeightCopy=True,
                                                                                                outputObjectiveValues=outputObjectives,
                                                                                                hardOnly=not self.useSoft,
                                                                                                relevantConstraintTypes=self.currentConstraints)
        if self.currently_changed_constraint_weight is None:
            solutionData[SolutionDataConstants.VALIDATOR_OBJECTIVE_CHANGED_WEIGHT] = solutionData[
                SolutionDataConstants.VALIDATOR_OBJECTIVE]
        else:
            solutionData[SolutionDataConstants.VALIDATOR_OBJECTIVE_CHANGED_WEIGHT] = validator.get_objective_value(
                self.instance, solutionData, useWeightCopy=False, hardOnly=not self.useSoft, relevantConstraintTypes=self.currentConstraints)

    def _change_weight_of_all_soft_constraints_to_zero(self):
        for constraintType in self.instance.Constraints.keys():
            for constraint in self.instance.Constraints[constraintType]:
                if not constraint[XHSTTConstraintConstants.REQUIRED]:
                    constraint[XHSTTConstraintConstants.WEIGHT] = 0
        self.model._add_objective_function()
    def _change_weight_of_all_soft_constraints_to_original_weight(self):
        for constraintType in self.instance.Constraints.keys():
            for constraint in self.instance.Constraints[constraintType]:
                if not constraint[XHSTTConstraintConstants.REQUIRED]:
                    constraint[XHSTTConstraintConstants.WEIGHT] = constraint[XHSTTConstraintConstants.WEIGHT_COPY]
        self.model._add_objective_function()

    def _get_solution_difference(self, old_solution: dict, new_solution: dict) -> dict:
        resource_changes = list()
        time_changes = list()
        new_events = list()
        removed_events = list()
        for event in new_solution[XHSTTFileConstants.EVENTS].keys():
            newSolutionEvent = new_solution[XHSTTFileConstants.EVENTS][event]
            if event in old_solution[XHSTTFileConstants.EVENTS]:
                oldSolutionEvent = old_solution[XHSTTFileConstants.EVENTS][event]
            else:
                new_events.append({"event": newSolutionEvent['@Id'], "time": newSolutionEvent[XHSTTFileConstants.TIME], "resources": newSolutionEvent[XHSTTFileConstants.RESOURCES]})
                continue

            if newSolutionEvent[XHSTTFileConstants.TIME] != oldSolutionEvent[XHSTTFileConstants.TIME]:
                if newSolutionEvent[XHSTTFileConstants.TIME] == "dummyTime":
                    removed_events.append({"event": oldSolutionEvent['@Id'], "time": oldSolutionEvent[XHSTTFileConstants.TIME], "resources": oldSolutionEvent[XHSTTFileConstants.RESOURCES]})
                    continue
                elif oldSolutionEvent[XHSTTFileConstants.TIME] == "dummyTime":
                    new_events.append({"event": newSolutionEvent['@Id'], "time": newSolutionEvent[XHSTTFileConstants.TIME], "resources": newSolutionEvent[XHSTTFileConstants.RESOURCES]})
                    continue

                time_changes.append({"event": event, "oldAssignment": oldSolutionEvent[XHSTTFileConstants.TIME], "newAssignment": newSolutionEvent[XHSTTFileConstants.TIME]})

            for role in newSolutionEvent[XHSTTFileConstants.RESOURCES].keys():
                if role not in oldSolutionEvent[XHSTTFileConstants.RESOURCES].keys():
                    if newSolutionEvent[XHSTTFileConstants.RESOURCES][role] != "dummyResource":
                        resource_changes.append({"event": event, "role": role,
                                                 "oldAssignment": "dummyResource",
                                                 "newAssignment": newSolutionEvent[XHSTTFileConstants.RESOURCES][role]})
                elif newSolutionEvent[XHSTTFileConstants.RESOURCES][role] != oldSolutionEvent[XHSTTFileConstants.RESOURCES][role]:
                    resource_changes.append({"event": event, "role": role, "oldAssignment": oldSolutionEvent[XHSTTFileConstants.RESOURCES][role], "newAssignment": newSolutionEvent[XHSTTFileConstants.RESOURCES][role]})


        # for event in self.instance.Events.IndividualEvents.keys():
        #     print(f"Previous: {[(subevent['@Id'], subevent['Time']) for subevent in old_solution[XHSTTFileConstants.EVENTS].values() if subevent['@Id'][0] == event]}")
        #     print(f"Now: {[(subevent['@Id'], subevent['Time']) for subevent in new_solution[XHSTTFileConstants.EVENTS].values() if subevent['@Id'][0] == event]}")
        #
        # for event in events_with_removed_subevents:
        #     print(f"Old: {[(subevent['@Id'], subevent['Time']) for subevent in old_solution[XHSTTFileConstants.EVENTS].values() if subevent['@Id'][0] == event]}")
        #     print(f"New: {[(subevent['@Id'], subevent['Time']) for subevent in new_solution[XHSTTFileConstants.EVENTS].values() if subevent['@Id'][0] == event]}")

        return {"ResourceChanges": resource_changes, "TimeChanges": time_changes, "NewEvents": new_events, "RemovedEvents": removed_events}
