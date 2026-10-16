import time
import gurobipy as gp
from gurobipy import GRB
import sys
sys.path.append('validator')
sys.path.append('../validator')
import validator
import math
import uuid
import ILPConstants
sys.path.append('../XHSTTImporter')
from Instance import Instance
import XHSTTConstraintConstants
import XHSTTFileConstants
sys.path.append('../SolutionExporter')
import SolutionDataConstants
from generate_heuristic_solution import HeuristicSolutionGenerator

class ILPModel:
    def __init__(self, instance: Instance, outputFlag: int = 0, clash_free=False, optimize_splitting=False):
        self.optimizeSplitting = optimize_splitting
        self.env = gp.Env(empty=True)
        self.env.setParam('OutputFlag', 0)
        self.env.start()
        self.model = gp.Model(env=self.env)
        self.instance = instance
        self.restict_model_to_distribution_constraints = True
        self.enforce_hard_prefer_times = True
        self.model_is_clash_free = clash_free
        possiblyQuadraticEffects = [len(self.instance.Times.IndividualTimes.keys())]
        for event in self.instance.Events.IndividualEvents.keys():
            studentResources = [resource for resource in self.instance.Events.IndividualEvents[event].EventResources.AssignedResources + self.instance.Events.IndividualEvents[event].EventResources.UnassignedResources if resource.ResourceType == XHSTTFileConstants.STUDENT]
            possiblyQuadraticEffects.append(len(studentResources))
        self._quadratic_range = max(possiblyQuadraticEffects)
        self.bestKnownSolution = None

    def computeTheIIS(self):
        iis = self.model.computeIIS()
        print(iis)
    def create_model(self, outputFlag: int = 0, existingSolution: dict = None, fixTimes=False, fixResources=False, hardAssignTimes=False):
        # some parameters to control Gurobi's output and other aspects in the solution process
        self.model.Params.OutputFlag = outputFlag
        self.model.Params.MIPFocus = 2
        # self.model.Params.MIPGap = 0.01
        # self.model.Params.Presolve = 1
        self.model.Params.Threads = 1
        # self.model.Params.MemLimit = 32
        # self.model.Params.PrePasses = 1
        # self.model.Params.SolutionLimit = 1
        # self.model.Params.TimeLimit = 300
        start = time.time()
        MAX_EVENT_LENGTH = 2
        if self.model.Params.OutputFlag > 0:
            print(f"Max event length: {MAX_EVENT_LENGTH}")

        self.hardAvoidClashes = self.model_is_clash_free
        if self.model.Params.OutputFlag > 0:
            print(f"hardAvoidClashes: {self.hardAvoidClashes}")
        self._initialize_possible_start_time_by_event_duration_dict(max_event_length=MAX_EVENT_LENGTH)
        self._initialize_events_to_subevents_dict(max_event_length=MAX_EVENT_LENGTH, existingSolution=existingSolution)
        self._initialize_event_resources_to_possible_resources_dict(existingSolution=existingSolution,
                                                                    fixResources=fixResources)
        if self.model.Params.OutputFlag > 0:
            print(f"Initialized dicts after {time.time() - start} seconds")
        try:
            self._initialize_variables(existingSolution=existingSolution, onlyAllowExistingTimes=fixTimes, onlyAllowCurrentResources=fixResources)
        except gp.GurobiError as e:
            print(e.message)
            print(e.errno)
        if self.model.Params.OutputFlag > 0:
            print(f"Initialized variables after {time.time() - start} seconds")
        if self.model.Params.OutputFlag > 0:
            print(f"Initialized resources dict after {time.time() - start} seconds")

        deviationVariableSet = self._add_deviation_related_variables()
        self.variableDict["s"] = deviationVariableSet[0]
        self.variableDict["s_i"] = deviationVariableSet[1]
        if self.model.Params.OutputFlag > 0:
            print(f"Initialized deviation variables after {time.time() - start} seconds")
        skipConstraints = fixResources
        self._add_general_constraints(skipSome=skipConstraints)
        if self.model.Params.OutputFlag > 0:
            print(f"Initialized general constraints after {time.time() - start} seconds")
        self._add_xhstt_specific_constraints(hardAssignTimes)
        if self.model.Params.OutputFlag > 0:
            print(f"Initialized xhstt constraints after {time.time() - start} seconds")
        self._add_constraints_new_in_our_format()
        if self.model.Params.OutputFlag > 0:
            print(f"Initialized new constraints after {time.time() - start} seconds")
        self._add_objective_function()
        if self.model.Params.OutputFlag > 0:
            print(f"Initialized objective function after {time.time() - start} seconds")

        # write model to file in readable format (useful for debugging)
        self.model.write("model.lp")
        if self.model.Params.OutputFlag > 0:
            print(f"Finished writing model after {time.time() - start} seconds")

    def close_model_and_environment(self):
        self.model.close()
        self.env.close()

    def optimize_model(self, solution_limit: int = -1, time_limit: int = -1, best_known_objective_value: int = math.inf, validate_result=True, reset=False, use_cutoffs=True, mip_gap=None) -> (int, dict):
        try:
            if reset:
                print("RESET MODEL")
                self.model.reset()
            if solution_limit > 0:
                self.model.Params.SolutionLimit = solution_limit
            if time_limit > 0:
                self.model.Params.TimeLimit = time_limit
            else:
                self.model.Params.TimeLimit = math.inf
            if mip_gap is not None:
                self.model.Params.MIPGap = mip_gap
            if use_cutoffs:
                self.model.Params.BestBdStop = best_known_objective_value
                self.model.Params.Cutoff = best_known_objective_value - 0.00001
            else:
                self.model.Params.BestBdStop = math.inf
                self.model.Params.Cutoff = math.inf
            self.model.optimize()

            start = time.time()
            if self.model.Params.OutputFlag > 0:
                solutionEvents = self._create_solution_events_dict(outputDeviations=True)
            else:
                solutionEvents = self._create_solution_events_dict(outputDeviations=False)

            if self.model.Params.OutputFlag > 0:
                print(f"Creating solution events took: {time.time() - start} seconds")
            if validate_result and solutionEvents[XHSTTFileConstants.EVENTS] != dict():
                start = time.time()
                if self.model.Params.OutputFlag > 0:
                    objectiveValueAccordingToValidator = validator.get_objective_value(self.instance, solutionEvents, outputObjectiveValues=True)
                else:
                    objectiveValueAccordingToValidator = validator.get_objective_value(self.instance, solutionEvents,
                                                                                       outputObjectiveValues=False)
                solutionEvents[SolutionDataConstants.VALIDATOR_OBJECTIVE] = objectiveValueAccordingToValidator
                if self.model.Params.OutputFlag > 0:
                    print(f"Validation Took: {time.time() - start} seconds")

            return self.model.Status, solutionEvents

        except gp.GurobiError as e:
            print(f"Error code {e.errno}: {e}")
        except AttributeError as e:
            if "ObjVal" not in str(e):
                print(f"Encountered an attribute error: {e}")

    def provide_warm_start_solution(self, solutionData: dict):
        allTimes = [ILPConstants.DUMMY_TIME] + list(self.instance.Times.IndividualTimes.keys())
        possibleTimes = allTimes

        for var in self.variableDict["y"].values():
            var.Start = GRB.UNDEFINED

        for var in self.variableDict["d"].values():
            var.Start = GRB.UNDEFINED

        for var in self.variableDict["w"].values():
            var.Start = GRB.UNDEFINED

        for event in solutionData[XHSTTFileConstants.EVENTS].keys():
            solutionEvent = solutionData[XHSTTFileConstants.EVENTS][event]
            if XHSTTFileConstants.TIME not in solutionEvent.keys() or XHSTTFileConstants.RESOURCES not in solutionEvent.keys():
                continue
            resourcesWithFixation = [resource for resource in solutionEvent[XHSTTFileConstants.RESOURCES].keys()
                         if solutionEvent[XHSTTFileConstants.RESOURCES][resource] is not None]
            if solutionEvent[XHSTTFileConstants.TIME] is None and len(resourcesWithFixation) == 0 and not solutionEvent[SolutionDataConstants.DELETE_SUBEVENTS] and len(set(allTimes).symmetric_difference(set(possibleTimes))) == 0:
                continue
            eventTime = solutionEvent[XHSTTFileConstants.TIME]
            if solutionEvent[XHSTTFileConstants.TIME] is not None:
                self.variableDict["y"][event[0], event[1], eventTime].Start = 1
            for role in solutionEvent[XHSTTFileConstants.RESOURCES].keys():
                resource = solutionEvent[XHSTTFileConstants.RESOURCES][role]
                if solutionEvent[XHSTTFileConstants.RESOURCES][role] is None:
                    continue
                if solutionEvent[SolutionDataConstants.DELETE_SUBEVENTS]:
                    self.variableDict["d"][event[0], role, resource].Start = 1
                else:
                    self.variableDict["w"][event[0], event[1], role, resource].Start = 1

    def update_constraints_to_fix_variables(self, solutionData: dict, constraintSets: list) -> list:
        allTimes = [ILPConstants.DUMMY_TIME] + list(self.instance.Times.IndividualTimes.keys())
        if "possibleTimes" in solutionData:
            possibleTimes = solutionData["possibleTimes"]
        else:
            possibleTimes = None
        if possibleTimes is None:
            possibleTimes = allTimes
        impossibleTimes = [t for t in allTimes if t not in possibleTimes]
        fixedSubeventTimeConstraints = dict()
        fixedSubeventResourcesConstraints = dict()
        fixedEventResourcesConstraints = dict()
        if len(constraintSets) == 3:
            oldFixedSubeventTimeConstraints = constraintSets[0]
            oldFixedSubeventResourcesConstraints = constraintSets[1]
            oldFixedEventResourcesConstraints = constraintSets[2]
        else:
            oldFixedSubeventTimeConstraints = dict()
            oldFixedSubeventResourcesConstraints = dict()
            oldFixedEventResourcesConstraints = dict()

        for event in solutionData[XHSTTFileConstants.EVENTS].keys():
            solutionEvent = solutionData[XHSTTFileConstants.EVENTS][event]
            if XHSTTFileConstants.TIME not in solutionEvent.keys() or XHSTTFileConstants.RESOURCES not in solutionEvent.keys():
                continue
            resourcesWithFixation = [resource for resource in solutionEvent[XHSTTFileConstants.RESOURCES].keys()
                         if solutionEvent[XHSTTFileConstants.RESOURCES][resource] is not None]
            if solutionEvent[XHSTTFileConstants.TIME] is None and len(resourcesWithFixation) == 0 and not solutionEvent[SolutionDataConstants.DELETE_SUBEVENTS] and len(set(allTimes).symmetric_difference(set(possibleTimes))) == 0:
                continue
            eventTime = solutionEvent[XHSTTFileConstants.TIME]
            if solutionEvent[XHSTTFileConstants.TIME] is not None and (event[0], event[1], eventTime, 1) not in oldFixedSubeventTimeConstraints.keys():
                self.variableDict["y"][event[0], event[1], eventTime].LB = 1
                self.variableDict["y"][event[0], event[1], eventTime].UB = 1
                fixedSubeventTimeConstraints[event[0], event[1], eventTime, 1] = 1
            elif solutionEvent[XHSTTFileConstants.TIME] is not None:
                fixedSubeventTimeConstraints[event[0], event[1], eventTime, 1] = oldFixedSubeventTimeConstraints[event[0], event[1], eventTime, 1]
            else:
                for imp_time in impossibleTimes:
                    if (event[0], event[1], imp_time, 0) not in oldFixedSubeventTimeConstraints.keys():
                        self.variableDict["y"][event[0], event[1], imp_time].LB = 0
                        self.variableDict["y"][event[0], event[1], imp_time].UB = 0
                        fixedSubeventTimeConstraints[event[0], event[1], imp_time, 0] = 0
                    else:
                        fixedSubeventTimeConstraints[event[0], event[1], imp_time, 0] = oldFixedSubeventTimeConstraints[event[0], event[1], imp_time, 0]
            for role in solutionEvent[XHSTTFileConstants.RESOURCES].keys():
                resource = solutionEvent[XHSTTFileConstants.RESOURCES][role]
                if solutionEvent[XHSTTFileConstants.RESOURCES][role] is None:
                    continue
                if solutionEvent[SolutionDataConstants.DELETE_SUBEVENTS] and (event[0], role, resource) not in oldFixedEventResourcesConstraints.keys():
                    self.variableDict["d"][event[0], role, resource].LB = 1
                    self.variableDict["d"][event[0], role, resource].UB = 1
                    fixedEventResourcesConstraints[event[0], role, resource] = 1
                elif solutionEvent[SolutionDataConstants.DELETE_SUBEVENTS] and (event[0], resource) in oldFixedEventResourcesConstraints.keys():
                    fixedEventResourcesConstraints[event[0], resource] = oldFixedEventResourcesConstraints[event[0], resource]
                elif (event[0], event[1], role, resource) not in oldFixedSubeventResourcesConstraints.keys():
                    if (event[0], event[1], role, resource) not in self.variableDict["w"].keys():
                        print(f"key: {(event[0], event[1], role, resource)}")
                        print(f"Existing keys for event: {[resourceRole for resourceRole in self.variableDict['w'].keys() if resourceRole[0] == event[0]]}")

                    self.variableDict["w"][event[0], event[1], role, resource].LB = 1
                    self.variableDict["w"][event[0], event[1], role, resource].UB = 1
                    fixedSubeventResourcesConstraints[event[0], event[1], role, resource] = 1
                else:
                    fixedSubeventResourcesConstraints[event[0], event[1], role, resource] = oldFixedSubeventResourcesConstraints[event[0], event[1], role, resource]

        for constraint in oldFixedSubeventTimeConstraints.keys():
            if constraint not in fixedSubeventTimeConstraints.keys():
                self.variableDict["y"][constraint[0], constraint[1], constraint[2]].LB = 0
                self.variableDict["y"][constraint[0], constraint[1], constraint[2]].UB = 1

        for constraint in oldFixedEventResourcesConstraints.keys():
            if constraint not in fixedEventResourcesConstraints.keys():
                self.variableDict["d"][constraint[0], constraint[1], constraint[2]].LB = 0
                self.variableDict["d"][constraint[0], constraint[1], constraint[2]].UB = 1

        for constraint in oldFixedSubeventResourcesConstraints.keys():
            if constraint not in fixedSubeventResourcesConstraints.keys():
                self.variableDict["w"][constraint[0], constraint[1], constraint[2], constraint[3]].LB = 0
                self.variableDict["w"][constraint[0], constraint[1], constraint[2], constraint[3]].UB = 1

        # self.model.Params.Presolve = 1
        newConstraintSets = [fixedSubeventTimeConstraints, fixedSubeventResourcesConstraints, fixedEventResourcesConstraints]
        if self.model.Params.OutputFlag > 0:
            print(f"Time: {len(newConstraintSets[0])}, Subevent Resources: {len(newConstraintSets[1])}, Event Resources: {len(newConstraintSets[2])}")
        solutionData["possibleTimes"] = None
        return newConstraintSets
    
    def remove_constraints_to_fix_variables(self, constraintSets: list):
        for constraintSet in constraintSets:
            self.model.remove(constraintSet)

    def fix_all_hard_constraints_to_zero(self):
        constraintIdToConstraintDict = dict()

        for constraintType in self.instance.Constraints.keys():
            for constraint in self.instance.Constraints[constraintType]:
                constraintIdToConstraintDict[constraint[XHSTTFileConstants.ID]] = constraint

        for deviationConstraintType in self.variableDict["s"].keys():
            for deviationVariableKey in self.variableDict["s"][deviationConstraintType].keys():
                if constraintIdToConstraintDict[deviationVariableKey[0]][XHSTTConstraintConstants.REQUIRED]:
                    self.model.addConstr(self.variableDict["s"][deviationConstraintType][deviationVariableKey] == 0,
                                         str(deviationConstraintType) + "_" + str(deviationVariableKey) + "_fix_solved_hard_constraint")
    
    
    def _add_general_constraints(self, skipSome=False):
        substart = time.time()
        self._add_link_deviation_variables_with_deviation_binary_indicator_variables()
        if self.model.Params.OutputFlag > 0:
            print(f"Constraint set 1 added after {time.time() - substart} seconds")
        self._add_subevent_has_exactly_one_start_time_constraints()
        if self.model.Params.OutputFlag > 0:
            print(f"Constraint set 2 added after {time.time() - substart} seconds")
        self._add_number_of_resource_assignments_must_equal_number_of_event_resources_constraints()
        if self.model.Params.OutputFlag > 0:
            print(f"Constraint set 3 added after {time.time() - substart} seconds")
        if not self.hardAvoidClashes:
            self._add_resource_usage_per_time_to_solution_constraints()
            if self.model.Params.OutputFlag > 0:
                print(f"Constraint set 4 added after {time.time() - substart} seconds")
        self._add_link_subevent_resource_assignments_to_solution_constraints()
        if self.model.Params.OutputFlag > 0:
            print(f"Constraint set 5 added after {time.time() - substart} seconds")
        self._add_link_resource_assignments_between_events_and_subevents_constraitns()
        self._add_link_resource_assignments_between_events_and_event_groups()
        if self.model.Params.OutputFlag > 0:
            print(f"Constraint set 6 added after {time.time() - substart} seconds")

        if self.model.Params.OutputFlag > 0:
            print(f"Constraint set 7 added after {time.time() - substart} seconds")

        self._add_sum_of_subevent_durations_equals_event_duration_constraints()
        if self.model.Params.OutputFlag > 0:
            print(f"Constraint set 8 added after {time.time() - substart} seconds")
        self._add_subevent_usage_indicator_variables_constraints()
        if self.model.Params.OutputFlag > 0:
            print(f"Constraint set 9 added after {time.time() - substart} seconds")
        self._add_link_busy_indicator_variables()
        if self.model.Params.OutputFlag > 0:
            print(f"Constraint set 10 added after {time.time() - substart} seconds")
        self._add_events_with_given_start_time_are_scheduled_at_given_start_time_constraints()
        if self.model.Params.OutputFlag > 0:
            print(f"Constraint set 11 added after {time.time() - substart} seconds")
        self._add_assigned_resources_inactive_if_subevent_inactive_constraints()
        if self.model.Params.OutputFlag > 0:
            print(f"Constraint set 12 added after {time.time() - substart} seconds")

        if self.model.Params.OutputFlag > 0:
            print(f"Constraint set 13 added after {time.time() - substart} seconds")

        if self.model.Params.OutputFlag > 0:
            print(f"Constraint set 14 added after {time.time() - substart} seconds")
    
    def _add_xhstt_specific_constraints(self, hardAssignTimes: bool):
        substart = time.time()
        if XHSTTConstraintConstants.ASSIGN_RESOURCE_CONSTRAINT in self.instance.Constraints and len(self.instance.Constraints[XHSTTConstraintConstants.ASSIGN_RESOURCE_CONSTRAINT]) > 0:
            self._add_assign_resource_constraints()
        if self.model.Params.OutputFlag > 0:
            print(f"Constraint set 1 added after {time.time() - substart} seconds")
        if XHSTTConstraintConstants.ASSIGN_TIME_CONSTRAINT in self.instance.Constraints and len(self.instance.Constraints[XHSTTConstraintConstants.ASSIGN_TIME_CONSTRAINT]) > 0:
            self._add_assign_time_constraints(hardAssignTimes)
        if self.model.Params.OutputFlag > 0:
            print(f"Constraint set 2 added after {time.time() - substart} seconds")
        if XHSTTConstraintConstants.SPLIT_EVENTS_CONSTRAINT in self.instance.Constraints and len(self.instance.Constraints[XHSTTConstraintConstants.SPLIT_EVENTS_CONSTRAINT]) > 0:
            self._add_split_events_constraints()
        if self.model.Params.OutputFlag > 0:
            print(f"Constraint set 3 added after {time.time() - substart} seconds")
        if XHSTTConstraintConstants.DISTRIBUTE_SPLIT_EVENTS_CONSTRAINT in self.instance.Constraints and len(self.instance.Constraints[XHSTTConstraintConstants.DISTRIBUTE_SPLIT_EVENTS_CONSTRAINT]) > 0:
            self._add_distribute_split_events_constraints()
        if self.model.Params.OutputFlag > 0:
            print(f"Constraint set 4 added after {time.time() - substart} seconds")
        if XHSTTConstraintConstants.PREFER_RESOURCES_CONSTRAINT in self.instance.Constraints and len(self.instance.Constraints[XHSTTConstraintConstants.PREFER_RESOURCES_CONSTRAINT]) > 0:
            self._add_prefer_resource_constraints()
        if self.model.Params.OutputFlag > 0:
            print(f"Constraint set 5 added after {time.time() - substart} seconds")
        if XHSTTConstraintConstants.PREFER_TIMES_CONSTRAINT in self.instance.Constraints and len(self.instance.Constraints[XHSTTConstraintConstants.PREFER_TIMES_CONSTRAINT]) > 0:
            self._add_prefer_time_constraints()
        if self.model.Params.OutputFlag > 0:
            print(f"Constraint set 6 added after {time.time() - substart} seconds")
        if XHSTTConstraintConstants.AVOID_SPLIT_ASSIGNMENTS_CONSTRAINT in self.instance.Constraints and len(self.instance.Constraints[XHSTTConstraintConstants.AVOID_SPLIT_ASSIGNMENTS_CONSTRAINT]) > 0:
            self._add_avoid_split_assignments_constraints()
        if self.model.Params.OutputFlag > 0:
            print(f"Constraint set 7 added after {time.time() - substart} seconds")
        if XHSTTConstraintConstants.SPREAD_EVENTS_CONSTRAINT in self.instance.Constraints and len(self.instance.Constraints[XHSTTConstraintConstants.SPREAD_EVENTS_CONSTRAINT]) > 0:
            self._add_spread_events_constraints()
        if self.model.Params.OutputFlag > 0:
            print(f"Constraint set 8 added after {time.time() - substart} seconds")
        if XHSTTConstraintConstants.LINK_EVENTS_CONSTRAINT in self.instance.Constraints and len(self.instance.Constraints[XHSTTConstraintConstants.LINK_EVENTS_CONSTRAINT]) > 0:
            self._add_link_events_constraints()
        if self.model.Params.OutputFlag > 0:
            print(f"Constraint set 9 added after {time.time() - substart} seconds")
        if XHSTTConstraintConstants.AVOID_CLASHES_CONSTRAINT in self.instance.Constraints and len(self.instance.Constraints[XHSTTConstraintConstants.AVOID_CLASHES_CONSTRAINT]) > 0:
            self._add_avoid_clashes_constraints()
        if self.model.Params.OutputFlag > 0:
            print(f"Constraint set 10 added after {time.time() - substart} seconds")
        if XHSTTConstraintConstants.AVOID_UNAVAILABLE_TIMES_CONSTRAINT in self.instance.Constraints and len(self.instance.Constraints[XHSTTConstraintConstants.AVOID_UNAVAILABLE_TIMES_CONSTRAINT]) > 0:
            self._add_avoid_unavailable_times_constraints()
        if self.model.Params.OutputFlag > 0:
            print(f"Constraint set 11 added after {time.time() - substart} seconds")
        if XHSTTConstraintConstants.LIMIT_IDLE_TIMES_CONSTRAINT in self.instance.Constraints and len(self.instance.Constraints[XHSTTConstraintConstants.LIMIT_IDLE_TIMES_CONSTRAINT]) > 0:
            self._add_limit_idle_times_constraints()
        if self.model.Params.OutputFlag > 0:
            print(f"Constraint set 12 added after {time.time() - substart} seconds")
        if XHSTTConstraintConstants.CLUSTER_BUSY_TIMES_CONSTRAINT in self.instance.Constraints and len(self.instance.Constraints[XHSTTConstraintConstants.CLUSTER_BUSY_TIMES_CONSTRAINT]) > 0:
            self._add_cluster_busy_times_constraints()
        if self.model.Params.OutputFlag > 0:
            print(f"Constraint set 13 added after {time.time() - substart} seconds")
        if XHSTTConstraintConstants.LIMIT_BUSY_TIMES_CONSTRAINT in self.instance.Constraints and len(self.instance.Constraints[XHSTTConstraintConstants.LIMIT_BUSY_TIMES_CONSTRAINT]) > 0:
            self._add_limit_busy_times_constraints()
        if self.model.Params.OutputFlag > 0:
            print(f"Constraint set 14 added after {time.time() - substart} seconds")
        if XHSTTConstraintConstants.LIMIT_WORKLOAD_CONSTRAINT in self.instance.Constraints and len(self.instance.Constraints[XHSTTConstraintConstants.LIMIT_WORKLOAD_CONSTRAINT]) > 0:
            self._add_limit_workload_constraints()
        if self.model.Params.OutputFlag > 0:
            print(f"Constraint set 15 added after {time.time() - substart} seconds")

    def _add_constraints_new_in_our_format(self):
        if XHSTTConstraintConstants.BALANCE_CLASS_SIZE_CONSTRAINT in self.instance.Constraints and len(self.instance.Constraints[XHSTTConstraintConstants.BALANCE_CLASS_SIZE_CONSTRAINT]) > 0:
            self._add_balance_class_size_constraints()
        if XHSTTConstraintConstants.STUDENT_CHOICE_CONSTRAINT in self.instance.Constraints and len(self.instance.Constraints[XHSTTConstraintConstants.STUDENT_CHOICE_CONSTRAINT]) > 0:
            self._add_student_choice_constraints()

    def _add_objective_function(self):
    
        constraintIdToConstraintDict = dict()
    
        for constraintType in self.instance.Constraints.keys():
            for constraint in self.instance.Constraints[constraintType]:
                constraintIdToConstraintDict[constraint[XHSTTFileConstants.ID]] = constraint
        # Currently we multiply Soft Constraints by 10^-5 but we can also think about doing it differently
        # We ignore "Step" cost function because it does not exist in any of the instances
        self.model.setObjective(gp.quicksum([int(constraintIdToConstraintDict[deviationVariableKey[0]][XHSTTConstraintConstants.WEIGHT]) *
                                        self.variableDict["s"][deviationConstraintType][deviationVariableKey]
                                        for deviationConstraintType in self.variableDict["s"].keys()
                                        for deviationVariableKey in self.variableDict["s"][deviationConstraintType].keys()
                                        if (constraintIdToConstraintDict[deviationVariableKey[0]][XHSTTConstraintConstants.COST_FUNCTION] == XHSTTConstraintConstants.LINEAR) and
                                        constraintIdToConstraintDict[deviationVariableKey[0]][XHSTTConstraintConstants.REQUIRED]]) +
                           gp.quicksum([int(constraintIdToConstraintDict[deviationVariableKey[0]][XHSTTConstraintConstants.WEIGHT]) *
                                        i*i*self.variableDict["s_i"][deviationConstraintType][deviationVariableKey + (i,)]
                                        for deviationConstraintType in self.variableDict["s"].keys()
                                        for deviationVariableKey in self.variableDict["s"][deviationConstraintType].keys()
                                        for i in range(self._quadratic_range)
                                        if
                                        (constraintIdToConstraintDict[deviationVariableKey[0]][XHSTTConstraintConstants.COST_FUNCTION] == XHSTTConstraintConstants.QUADRATIC) and
                                        constraintIdToConstraintDict[deviationVariableKey[0]][XHSTTConstraintConstants.REQUIRED] and
                                        deviationConstraintType != ILPConstants.SPLIT_EVENT_AMOUNT and
                                        deviationConstraintType != ILPConstants.SPLIT_EVENT_DURATION]) +
                           gp.quicksum([int(constraintIdToConstraintDict[deviationVariableKey[0]][XHSTTConstraintConstants.WEIGHT]) *
                                        (i+j) * (i+j) * self.variableDict["s_i"][deviationConstraintType][deviationVariableKey + (i,)] *
                                                         self.variableDict["s_i"][ILPConstants.SPLIT_EVENT_DURATION][deviationVariableKey + (j,)]
                                        for deviationConstraintType in self.variableDict["s"].keys()
                                        for deviationVariableKey in self.variableDict["s"][deviationConstraintType].keys()
                                        for i in range(self._quadratic_range)
                                        for j in range(self._quadratic_range)
                                        if
                                        (constraintIdToConstraintDict[deviationVariableKey[0]][XHSTTConstraintConstants.COST_FUNCTION] == XHSTTConstraintConstants.QUADRATIC) and
                                        constraintIdToConstraintDict[deviationVariableKey[0]][XHSTTConstraintConstants.REQUIRED] and
                                        deviationConstraintType == ILPConstants.SPLIT_EVENT_AMOUNT]) +
                           0.00001 * gp.quicksum([int(constraintIdToConstraintDict[deviationVariableKey[0]][XHSTTConstraintConstants.WEIGHT]) *
                                        self.variableDict["s"][deviationConstraintType][deviationVariableKey]
                                        for deviationConstraintType in self.variableDict["s"].keys()
                                        for deviationVariableKey in self.variableDict["s"][deviationConstraintType].keys()
                                        if (constraintIdToConstraintDict[deviationVariableKey[0]][
                                                XHSTTConstraintConstants.COST_FUNCTION] == XHSTTConstraintConstants.LINEAR) and
                                        not constraintIdToConstraintDict[deviationVariableKey[0]][XHSTTConstraintConstants.REQUIRED]]) +
                           0.00001 * gp.quicksum([int(constraintIdToConstraintDict[deviationVariableKey[0]][XHSTTConstraintConstants.WEIGHT]) *
                                        i * i * self.variableDict["s_i"][deviationConstraintType][deviationVariableKey + (i,)]
                                        for deviationConstraintType in self.variableDict["s"].keys()
                                        for deviationVariableKey in self.variableDict["s"][deviationConstraintType].keys()
                                        for i in range(self._quadratic_range)
                                        if
                                        (constraintIdToConstraintDict[deviationVariableKey[0]][
                                             XHSTTConstraintConstants.COST_FUNCTION] == XHSTTConstraintConstants.QUADRATIC) and
                                        not constraintIdToConstraintDict[deviationVariableKey[0]][XHSTTConstraintConstants.REQUIRED] and
                                        deviationConstraintType != ILPConstants.SPLIT_EVENT_AMOUNT and
                                        deviationConstraintType != ILPConstants.SPLIT_EVENT_DURATION]) +
                           0.00001 * gp.quicksum([int(constraintIdToConstraintDict[deviationVariableKey[0]][XHSTTConstraintConstants.WEIGHT]) *
                                        (i + j) * (i + j) * self.variableDict["s_i"][deviationConstraintType][
                                            deviationVariableKey + (i,)] *
                                        self.variableDict["s_i"][ILPConstants.SPLIT_EVENT_DURATION][deviationVariableKey + (j,)]
                                        for deviationConstraintType in self.variableDict["s"].keys()
                                        for deviationVariableKey in self.variableDict["s"][deviationConstraintType].keys()
                                        for i in range(self._quadratic_range)
                                        for j in range(self._quadratic_range)
                                        if
                                        (constraintIdToConstraintDict[deviationVariableKey[0]][
                                             XHSTTConstraintConstants.COST_FUNCTION] == XHSTTConstraintConstants.QUADRATIC) and
                                        not constraintIdToConstraintDict[deviationVariableKey[0]][XHSTTConstraintConstants.REQUIRED] and
                                        deviationConstraintType == ILPConstants.SPLIT_EVENT_AMOUNT])
                           ,
                           GRB.MINIMIZE
                           )

    def _add_deviation_related_variables(self) -> (gp.tupledict, gp.tupledict):
        deviationVariableDict = dict()
        deviationVariableBinaryIndicatorDict = dict()

        self._add_assign_resource_deviation_variables(deviationVariableDict, deviationVariableBinaryIndicatorDict)
        self._add_assign_time_deviation_variables(deviationVariableDict, deviationVariableBinaryIndicatorDict)
        self._add_split_events_deviation_variables(deviationVariableDict, deviationVariableBinaryIndicatorDict)
        self._add_distribute_split_events_deviation_variables(deviationVariableDict, deviationVariableBinaryIndicatorDict)
        self._add_prefer_resource_deviation_variables(deviationVariableDict, deviationVariableBinaryIndicatorDict)
        self._add_prefer_time_deviation_variables(deviationVariableDict, deviationVariableBinaryIndicatorDict)
        self._add_avoid_split_assignment_deviation_variables(deviationVariableDict, deviationVariableBinaryIndicatorDict)
        self._add_spread_events_deviation_variables(deviationVariableDict, deviationVariableBinaryIndicatorDict)
        self._add_link_events_deviation_variables(deviationVariableDict, deviationVariableBinaryIndicatorDict)
        self._add_avoid_clashes_deviation_variables(deviationVariableDict, deviationVariableBinaryIndicatorDict)
        self._add_avoid_unavailable_times_deviation_variables(deviationVariableDict, deviationVariableBinaryIndicatorDict)
        self._add_limit_idle_times_deviation_variables(deviationVariableDict, deviationVariableBinaryIndicatorDict)
        self._add_cluster_busy_times_deviation_variables(deviationVariableDict, deviationVariableBinaryIndicatorDict)
        self._add_limit_busy_times_deviation_variables(deviationVariableDict, deviationVariableBinaryIndicatorDict)
        self._add_limit_workload_deviation_variables(deviationVariableDict, deviationVariableBinaryIndicatorDict)
        self._add_balance_class_size_deviation_variables(deviationVariableDict, deviationVariableBinaryIndicatorDict)
        self._add_student_choice_deviation_variables(deviationVariableDict, deviationVariableBinaryIndicatorDict)
    
        deviationVariable = dict()
        deviationBinaryIndicatorVariable = dict()
        for key in deviationVariableDict.keys():
            deviationVariable[key] = self.model.addVars(deviationVariableDict[key].keys(), vtype=GRB.INTEGER, name="s_" + key, lb=0)
            deviationBinaryIndicatorVariable[key] = self.model.addVars(deviationVariableBinaryIndicatorDict[key].keys(),
                                                             vtype=GRB.BINARY, name="s_i_" + key, lb=0)
    
        return deviationVariable, deviationBinaryIndicatorVariable
    
    def _add_assign_resource_deviation_variables(self, deviationVariableDict: dict, deviationVariableBinaryIndicatorDict: dict):
        deviationVariableDict[ILPConstants.ASSIGN_RESOURCE] = dict()
        deviationVariableBinaryIndicatorDict[ILPConstants.ASSIGN_RESOURCE] = dict()
        for constraint in self.instance.Constraints[XHSTTConstraintConstants.ASSIGN_RESOURCE_CONSTRAINT]:
            consideredEvents = set([(event, None) for event in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS]])
            for eventGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
                consideredEvents.update(
                    set([(event, eventGroup) for event in self.instance.Events.EventGroups[eventGroup].Events]))
            for event in consideredEvents:
                eventResources = (self.instance.Events.IndividualEvents[event[0]].EventResources.AssignedResources +
                                  self.instance.Events.IndividualEvents[event[0]].EventResources.UnassignedResources)
                for eventResource in eventResources:
                    deviationVariableDict[ILPConstants.ASSIGN_RESOURCE][constraint[XHSTTFileConstants.ID], event, eventResource.Role] = 0
                    if constraint[XHSTTConstraintConstants.COST_FUNCTION] == XHSTTConstraintConstants.QUADRATIC:
                        for i in range(self._quadratic_range):
                            deviationVariableBinaryIndicatorDict[ILPConstants.ASSIGN_RESOURCE][
                                constraint[XHSTTFileConstants.ID], event, eventResource.Role, i] = 0
    
    
    def _add_assign_time_deviation_variables(self, deviationVariableDict: dict, deviationVariableBinaryIndicatorDict: dict):
        deviationVariableDict[ILPConstants.ASSIGN_TIME] = dict()
        deviationVariableBinaryIndicatorDict[ILPConstants.ASSIGN_TIME] = dict()
        for constraint in self.instance.Constraints[XHSTTConstraintConstants.ASSIGN_TIME_CONSTRAINT]:
            consideredEvents = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS])
            for eventGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
                consideredEvents.update(set(self.instance.Events.EventGroups[eventGroup].Events))
            for event in consideredEvents:
                deviationVariableDict[ILPConstants.ASSIGN_TIME][constraint[XHSTTFileConstants.ID], event] = 0
                if constraint[XHSTTConstraintConstants.COST_FUNCTION] == XHSTTConstraintConstants.QUADRATIC:
                    for i in range(self._quadratic_range):
                        deviationVariableBinaryIndicatorDict[ILPConstants.ASSIGN_TIME][constraint[XHSTTFileConstants.ID], event, i] = 0
    
    
    def _add_split_events_deviation_variables(self, deviationVariableDict: dict, deviationVariableBinaryIndicatorDict: dict):
        deviationVariableDict[ILPConstants.SPLIT_EVENT_AMOUNT] = dict()
        deviationVariableBinaryIndicatorDict[ILPConstants.SPLIT_EVENT_AMOUNT] = dict()
        deviationVariableDict[ILPConstants.SPLIT_EVENT_DURATION] = dict()
        deviationVariableBinaryIndicatorDict[ILPConstants.SPLIT_EVENT_DURATION] = dict()
        for constraint in self.instance.Constraints[XHSTTConstraintConstants.SPLIT_EVENTS_CONSTRAINT]:
            consideredEvents = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS])
            for eventGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
                consideredEvents.update(set(self.instance.Events.EventGroups[eventGroup].Events))
            for event in consideredEvents:
                deviationVariableDict[ILPConstants.SPLIT_EVENT_AMOUNT][constraint[XHSTTFileConstants.ID], event] = 0
    
                if constraint[XHSTTConstraintConstants.COST_FUNCTION] == XHSTTConstraintConstants.QUADRATIC:
                    for i in range(self._quadratic_range):
                        deviationVariableBinaryIndicatorDict[ILPConstants.SPLIT_EVENT_AMOUNT][constraint[XHSTTFileConstants.ID], event, i] = 0
    
                deviationVariableDict[ILPConstants.SPLIT_EVENT_DURATION][constraint[XHSTTFileConstants.ID], event] = 0
    
                if constraint[XHSTTConstraintConstants.COST_FUNCTION] == XHSTTConstraintConstants.QUADRATIC:
                    for i in range(self._quadratic_range):
                        deviationVariableBinaryIndicatorDict[ILPConstants.SPLIT_EVENT_DURATION][constraint[XHSTTFileConstants.ID], event, i] = 0
    
    
    def _add_distribute_split_events_deviation_variables(self, deviationVariableDict: dict, deviationVariableBinaryIndicatorDict: dict):
        deviationVariableDict[ILPConstants.DIST_SPLIT_EVENT] = dict()
        deviationVariableBinaryIndicatorDict[ILPConstants.DIST_SPLIT_EVENT] = dict()
        for constraint in self.instance.Constraints[XHSTTConstraintConstants.DISTRIBUTE_SPLIT_EVENTS_CONSTRAINT]:
            consideredEvents = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS])
            for eventGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
                consideredEvents.update(set(self.instance.Events.EventGroups[eventGroup].Events))
            for event in consideredEvents:
                deviationVariableDict[ILPConstants.DIST_SPLIT_EVENT][constraint[XHSTTFileConstants.ID], event, int(constraint[XHSTTFileConstants.DURATION])] = 0
                if constraint[XHSTTConstraintConstants.COST_FUNCTION] == XHSTTConstraintConstants.QUADRATIC:
                    for i in range(self._quadratic_range):
                        deviationVariableBinaryIndicatorDict[ILPConstants.DIST_SPLIT_EVENT][
                            constraint[XHSTTFileConstants.ID], event, int(constraint[XHSTTFileConstants.DURATION]), i] = 0
    
    
    def _add_prefer_resource_deviation_variables(self, deviationVariableDict: dict, deviationVariableBinaryIndicatorDict: dict):
        deviationVariableDict[ILPConstants.PREFER_RESOURCE] = dict()
        deviationVariableBinaryIndicatorDict[ILPConstants.PREFER_RESOURCE] = dict()
        for constraint in self.instance.Constraints[XHSTTConstraintConstants.PREFER_RESOURCES_CONSTRAINT]:
            consideredEvents = [(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS][eventindex], eventindex) for eventindex in
                                range(len(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS]))]
            for eventGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
                consideredEvents = consideredEvents + [(event, "Group" + str(eventGroup)) for event in
                                                       self.instance.Events.EventGroups[eventGroup].Events]
    
            for event in consideredEvents:
                for eventResource in self.instance.Events.IndividualEvents[event[0]].EventResources.UnassignedResources:
                    deviationVariableDict[ILPConstants.PREFER_RESOURCE][constraint[XHSTTFileConstants.ID], event, eventResource.Role] = 0
                    if constraint[XHSTTConstraintConstants.COST_FUNCTION] == XHSTTConstraintConstants.QUADRATIC:
                        for i in range(self._quadratic_range):
                            deviationVariableBinaryIndicatorDict[ILPConstants.PREFER_RESOURCE][
                                constraint[XHSTTFileConstants.ID], event, eventResource.Role, i] = 0
    
    
    def _add_prefer_time_deviation_variables(self, deviationVariableDict: dict, deviationVariableBinaryIndicatorDict: dict):
        deviationVariableDict[ILPConstants.PREFER_TIME] = dict()
        deviationVariableBinaryIndicatorDict[ILPConstants.PREFER_TIME] = dict()
        for constraint in self.instance.Constraints[XHSTTConstraintConstants.PREFER_TIMES_CONSTRAINT]:
            consideredEvents = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS])
            for eventGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
                consideredEvents.update(set(self.instance.Events.EventGroups[eventGroup].Events))
            for event in consideredEvents:
                deviationVariableDict[ILPConstants.PREFER_TIME][constraint[XHSTTFileConstants.ID], event] = 0
                if constraint[XHSTTConstraintConstants.COST_FUNCTION] == XHSTTConstraintConstants.QUADRATIC:
                    for i in range(self._quadratic_range):
                        deviationVariableBinaryIndicatorDict[ILPConstants.PREFER_TIME][constraint[XHSTTFileConstants.ID], event, i] = 0
    
    
    def _add_avoid_split_assignment_deviation_variables(self, deviationVariableDict: dict, deviationVariableBinaryIndicatorDict: dict):
        deviationVariableDict[ILPConstants.AVOID_SPLIT] = dict()
        deviationVariableBinaryIndicatorDict[ILPConstants.AVOID_SPLIT] = dict()
        for constraint in self.instance.Constraints[XHSTTConstraintConstants.AVOID_SPLIT_ASSIGNMENTS_CONSTRAINT]:
            for eventGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
                deviationVariableDict[ILPConstants.AVOID_SPLIT][constraint[XHSTTFileConstants.ID], eventGroup] = 0
                if constraint[XHSTTConstraintConstants.COST_FUNCTION] == XHSTTConstraintConstants.QUADRATIC:
                    for i in range(self._quadratic_range):
                        deviationVariableBinaryIndicatorDict[ILPConstants.AVOID_SPLIT][constraint[XHSTTFileConstants.ID], eventGroup, i] = 0
    
    
    def _add_spread_events_deviation_variables(self, deviationVariableDict: dict, deviationVariableBinaryIndicatorDict: dict):
        deviationVariableDict[ILPConstants.SPREAD_EVENT] = dict()
        deviationVariableBinaryIndicatorDict[ILPConstants.SPREAD_EVENT] = dict()
        for constraint in self.instance.Constraints[XHSTTConstraintConstants.SPREAD_EVENTS_CONSTRAINT]:
            for eventGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
                for timeGroup in constraint[XHSTTFileConstants.TIME_GROUPS]:
                    deviationVariableDict[ILPConstants.SPREAD_EVENT][constraint[XHSTTFileConstants.ID], eventGroup, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] = 0
                    if constraint[XHSTTConstraintConstants.COST_FUNCTION] == XHSTTConstraintConstants.QUADRATIC:
                        for i in range(self._quadratic_range):
                            deviationVariableBinaryIndicatorDict[ILPConstants.SPREAD_EVENT][
                                constraint[XHSTTFileConstants.ID], eventGroup, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT], i] = 0
    
    
    def _add_link_events_deviation_variables(self, deviationVariableDict: dict, deviationVariableBinaryIndicatorDict: dict):
        timesWithoutDummyTime = list(self.instance.Times.IndividualTimes.keys())
    
        deviationVariableDict[ILPConstants.LINK_EVENT] = dict()
        deviationVariableBinaryIndicatorDict[ILPConstants.LINK_EVENT] = dict()
        for constraint in self.instance.Constraints[XHSTTConstraintConstants.LINK_EVENTS_CONSTRAINT]:
            for eventGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
                for t in timesWithoutDummyTime:
                    deviationVariableDict[ILPConstants.LINK_EVENT][constraint[XHSTTFileConstants.ID], eventGroup, t] = 0
                    if constraint[XHSTTConstraintConstants.COST_FUNCTION] == XHSTTConstraintConstants.QUADRATIC:
                        for i in range(self._quadratic_range):
                            deviationVariableBinaryIndicatorDict[ILPConstants.LINK_EVENT][constraint[XHSTTFileConstants.ID], eventGroup, t, i] = 0
    
    
    def _add_avoid_clashes_deviation_variables(self, deviationVariableDict: dict, deviationVariableBinaryIndicatorDict: dict):
        timesWithoutDummyTime = list(self.instance.Times.IndividualTimes.keys())
    
        deviationVariableDict[ILPConstants.AVOID_CLASHES] = dict()
        deviationVariableBinaryIndicatorDict[ILPConstants.AVOID_CLASHES] = dict()
        for constraint in self.instance.Constraints[XHSTTConstraintConstants.AVOID_CLASHES_CONSTRAINT]:
            constraintResources = set([(resource, None) for resource in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCES]])
            for resourceGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCE_GROUPS]:
                for resourceType in self.instance.Resources.ResourceGroupsByType.keys():
                    if resourceGroup in self.instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups:
                        constraintResources.update(
                            set((resource, resourceGroup) for resource in
                                self.instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups[
                                    resourceGroup].Resources))
            for resource in constraintResources:
                for t in timesWithoutDummyTime:
                    deviationVariableDict[ILPConstants.AVOID_CLASHES][constraint[XHSTTFileConstants.ID], resource, t] = 0
                    if constraint[XHSTTConstraintConstants.COST_FUNCTION] == XHSTTConstraintConstants.QUADRATIC:
                        for i in range(self._quadratic_range):
                            deviationVariableBinaryIndicatorDict[ILPConstants.AVOID_CLASHES][constraint[XHSTTFileConstants.ID], resource, t, i] = 0
    
    
    def _add_avoid_unavailable_times_deviation_variables(self, deviationVariableDict: dict, deviationVariableBinaryIndicatorDict: dict):
        deviationVariableDict[ILPConstants.AVOID_UNAVAILABLE_TIMES] = dict()
        deviationVariableBinaryIndicatorDict[ILPConstants.AVOID_UNAVAILABLE_TIMES] = dict()
        for constraint in self.instance.Constraints[XHSTTConstraintConstants.AVOID_UNAVAILABLE_TIMES_CONSTRAINT]:
            constraintResources = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCES])
            for resourceGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCE_GROUPS]:
                for resourceType in self.instance.Resources.ResourceGroupsByType.keys():
                    if resourceGroup in self.instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups:
                        constraintResources.update(
                            set(self.instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups[
                                    resourceGroup].Resources))
            for resource in constraintResources:
                deviationVariableDict[ILPConstants.AVOID_UNAVAILABLE_TIMES][constraint[XHSTTFileConstants.ID], resource] = 0
                if constraint[XHSTTConstraintConstants.COST_FUNCTION] == XHSTTConstraintConstants.QUADRATIC:
                    for i in range(self._quadratic_range):
                        deviationVariableBinaryIndicatorDict[ILPConstants.AVOID_UNAVAILABLE_TIMES][constraint[XHSTTFileConstants.ID], resource, i] = 0
    
    
    def _add_limit_idle_times_deviation_variables(self, deviationVariableDict: dict, deviationVariableBinaryIndicatorDict: dict):
        deviationVariableDict[ILPConstants.IDLE_TIMES] = dict()
        deviationVariableBinaryIndicatorDict[ILPConstants.IDLE_TIMES] = dict()
        for constraint in self.instance.Constraints[XHSTTConstraintConstants.LIMIT_IDLE_TIMES_CONSTRAINT]:
            constraintResources = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCES])
            for resourceGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCE_GROUPS]:
                for resourceType in self.instance.Resources.ResourceGroupsByType.keys():
                    if resourceGroup in self.instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups:
                        constraintResources.update(
                            set(self.instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups[
                                    resourceGroup].Resources))
            for resource in constraintResources:
                deviationVariableDict[ILPConstants.IDLE_TIMES][constraint[XHSTTFileConstants.ID], resource] = 0
                if constraint[XHSTTConstraintConstants.COST_FUNCTION] == XHSTTConstraintConstants.QUADRATIC:
                    for i in range(self._quadratic_range):
                        deviationVariableBinaryIndicatorDict[ILPConstants.IDLE_TIMES][constraint[XHSTTFileConstants.ID], resource, i] = 0
    
    
    def _add_cluster_busy_times_deviation_variables(self, deviationVariableDict: dict, deviationVariableBinaryIndicatorDict: dict):
        deviationVariableDict[ILPConstants.CLUSTER_BUSY] = dict()
        deviationVariableBinaryIndicatorDict[ILPConstants.CLUSTER_BUSY] = dict()
        for constraint in self.instance.Constraints[XHSTTConstraintConstants.CLUSTER_BUSY_TIMES_CONSTRAINT]:
            constraintResources = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCES])
            for resourceGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCE_GROUPS]:
                for resourceType in self.instance.Resources.ResourceGroupsByType.keys():
                    if resourceGroup in self.instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups:
                        constraintResources.update(
                            set(self.instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups[
                                    resourceGroup].Resources))
            for resource in constraintResources:
                deviationVariableDict[ILPConstants.CLUSTER_BUSY][constraint[XHSTTFileConstants.ID], resource] = 0
                if constraint[XHSTTConstraintConstants.COST_FUNCTION] == XHSTTConstraintConstants.QUADRATIC:
                    for i in range(self._quadratic_range):
                        deviationVariableBinaryIndicatorDict[ILPConstants.CLUSTER_BUSY][constraint[XHSTTFileConstants.ID], resource, i] = 0
    
    
    def _add_limit_busy_times_deviation_variables(self, deviationVariableDict: dict, deviationVariableBinaryIndicatorDict: dict):
        deviationVariableDict[ILPConstants.LIMIT_BUSY] = dict()
        deviationVariableBinaryIndicatorDict[ILPConstants.LIMIT_BUSY] = dict()
        for constraint in self.instance.Constraints[XHSTTConstraintConstants.LIMIT_BUSY_TIMES_CONSTRAINT]:
            constraintResources = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCES])
            for resourceGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCE_GROUPS]:
                for resourceType in self.instance.Resources.ResourceGroupsByType.keys():
                    if resourceGroup in self.instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups:
                        constraintResources.update(
                            set(self.instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups[
                                    resourceGroup].Resources))
            for resource in constraintResources:
                deviationVariableDict[ILPConstants.LIMIT_BUSY][constraint[XHSTTFileConstants.ID], resource] = 0
                if constraint[XHSTTConstraintConstants.COST_FUNCTION] == XHSTTConstraintConstants.QUADRATIC:
                    for i in range(self._quadratic_range):
                        deviationVariableBinaryIndicatorDict[ILPConstants.LIMIT_BUSY][constraint[XHSTTFileConstants.ID], resource, i] = 0
    
    
    def _add_limit_workload_deviation_variables(self, deviationVariableDict: dict, deviationVariableBinaryIndicatorDict: dict):
        deviationVariableDict[ILPConstants.LIMIT_WORKLOAD] = dict()
        deviationVariableBinaryIndicatorDict[ILPConstants.LIMIT_WORKLOAD] = dict()
        for constraint in self.instance.Constraints[XHSTTConstraintConstants.LIMIT_WORKLOAD_CONSTRAINT]:
            constraintResources = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCES])
            for resourceGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCE_GROUPS]:
                for resourceType in self.instance.Resources.ResourceGroupsByType.keys():
                    if resourceGroup in self.instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups:
                        constraintResources.update(
                            set(self.instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups[
                                    resourceGroup].Resources))
            for resource in constraintResources:
                deviationVariableDict[ILPConstants.LIMIT_WORKLOAD][constraint[XHSTTFileConstants.ID], resource] = 0
                if constraint[XHSTTConstraintConstants.COST_FUNCTION] == XHSTTConstraintConstants.QUADRATIC:
                    for i in range(self._quadratic_range):
                        deviationVariableBinaryIndicatorDict[ILPConstants.LIMIT_WORKLOAD][constraint[XHSTTFileConstants.ID], resource, i] = 0

    
    def _add_balance_class_size_deviation_variables(self, deviationVariableDict: dict, deviationVariableBinaryIndicatorDict: dict):
        deviationVariableDict[ILPConstants.BALANCE_CLASS] = dict()
        deviationVariableBinaryIndicatorDict[ILPConstants.BALANCE_CLASS] = dict()
        if XHSTTConstraintConstants.BALANCE_CLASS_SIZE_CONSTRAINT in self.instance.Constraints.keys():
            for constraint in self.instance.Constraints[XHSTTConstraintConstants.BALANCE_CLASS_SIZE_CONSTRAINT]:
                consideredEventGroups = constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]
    
                for eventGroup in consideredEventGroups:
                    deviationVariableDict[ILPConstants.BALANCE_CLASS][constraint[XHSTTFileConstants.ID], eventGroup] = 0
                    if constraint[XHSTTConstraintConstants.COST_FUNCTION] == XHSTTConstraintConstants.QUADRATIC:
                        for i in range(self._quadratic_range):
                            deviationVariableBinaryIndicatorDict[ILPConstants.BALANCE_CLASS][constraint[XHSTTFileConstants.ID], eventGroup, i] = 0
    
    
    def _add_student_choice_deviation_variables(self, deviationVariableDict: dict, deviationVariableBinaryIndicatorDict: dict):
        deviationVariableDict[ILPConstants.STUDENT_CHOICE] = dict()
        deviationVariableBinaryIndicatorDict[ILPConstants.STUDENT_CHOICE] = dict()
        if XHSTTConstraintConstants.STUDENT_CHOICE_CONSTRAINT in self.instance.Constraints.keys():
            for constraint in self.instance.Constraints[XHSTTConstraintConstants.STUDENT_CHOICE_CONSTRAINT]:
                consideredResources = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCES])
                for resourceGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCE_GROUPS]:
                    for resourceType in self.instance.Resources.ResourceGroupsByType.keys():
                        if resourceGroup in self.instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups:
                            consideredResources.update(set(
                                self.instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups[
                                    resourceGroup].Resources))
                for resource in consideredResources:
                    deviationVariableDict[ILPConstants.STUDENT_CHOICE][constraint[XHSTTFileConstants.ID], resource] = 0
                    if constraint[XHSTTConstraintConstants.COST_FUNCTION] == XHSTTConstraintConstants.QUADRATIC:
                        for i in range(self._quadratic_range):
                            deviationVariableBinaryIndicatorDict[ILPConstants.STUDENT_CHOICE][constraint[XHSTTFileConstants.ID], resource, i] = 0
    
    def _add_link_deviation_variables_with_deviation_binary_indicator_variables(self):
        for deviationVariableType in self.variableDict["s"].keys():
            for deviationVariable in self.variableDict["s"][deviationVariableType].keys():
                if deviationVariable + (0,) in self.variableDict["s_i"][deviationVariableType].keys():
                    self.model.addConstr(gp.quicksum([i * self.variableDict["s_i"][deviationVariableType][deviationVariable + (i,)] for i in range(self._quadratic_range)]) ==
                                    self.variableDict["s"][deviationVariableType][deviationVariable], str(deviationVariable) + "_link_s_s_i")
                    self.model.addConstr(
                        gp.quicksum([self.variableDict["s_i"][deviationVariableType][deviationVariable + (i,)] for i in range(self._quadratic_range)]) == 1,
                        str(deviationVariable) + "_s_i_only_one_value")
    def _add_subevent_has_exactly_one_start_time_constraints(self):
        events = list(self.instance.Events.IndividualEvents.keys())
        timesWithDummyTime = [ILPConstants.DUMMY_TIME] + list(self.instance.Times.IndividualTimes.keys())
        for event in events:
            if event not in self.eventToSubEventListDict:
                continue
            for subevent in self.eventToSubEventListDict[event]:
                eventResources = (self.instance.Events.IndividualEvents[event].EventResources.AssignedResources +
                                  self.instance.Events.IndividualEvents[event].EventResources.UnassignedResources)
                for eventResource in eventResources:
                    self.model.addConstr(gp.quicksum([self.variableDict["x"][event, subevent, t, eventResource.Role, r]
                                                 for t in timesWithDummyTime for r in self.eventResourceToPossibleResourcesDict[event, eventResource.Role] if (event, subevent, t, eventResource.Role, r) in self.variableDict["x"].keys()]) == 1,
                                                 str(event) + "_" + str(subevent) + "_" + str(eventResource) + "_one_start_time")
    def _add_number_of_resource_assignments_must_equal_number_of_event_resources_constraints(self):
        events = list(self.instance.Events.IndividualEvents.keys())
        timesWithDummyTime = [ILPConstants.DUMMY_TIME] + list(self.instance.Times.IndividualTimes.keys())
        for event in events:
            if event not in self.eventToSubEventListDict:
                continue
            eventResources = (self.instance.Events.IndividualEvents[event].EventResources.AssignedResources +
                              self.instance.Events.IndividualEvents[event].EventResources.UnassignedResources)
            for subevent in self.eventToSubEventListDict[event]:
                for t in timesWithDummyTime:
                    if (event, subevent, t) not in self.variableDict["y"].keys():
                        continue
                    self.model.addConstr(gp.quicksum([self.variableDict["x"][event, subevent, t, er.Role, r] for er in eventResources
                                                 for r in self.eventResourceToPossibleResourcesDict[event, er.Role] if (event, subevent, t, er.Role, r) in self.variableDict["x"].keys()]) ==
                                    len(eventResources) * self.variableDict["y"][event, subevent, t],
                                    str(event) + "_" + str(subevent) + "_" + str(t) + "_correct_assigned_resource_amount")
    def _add_resource_usage_per_time_to_solution_constraints(self):
        events = list(self.instance.Events.IndividualEvents.keys())
        timesWithoutDummyTime = list(self.instance.Times.IndividualTimes.keys())
        resourcesWithoutDummyResource = list(self.instance.Resources.IndividualResources.keys())

        self.eventResourceContainmentDict = dict()
        for event in events:
            for resource in resourcesWithoutDummyResource:
                key = (event, resource)
                eventResources = (self.instance.Events.IndividualEvents[event].EventResources.AssignedResources +
                                  self.instance.Events.IndividualEvents[event].EventResources.UnassignedResources)
                roles = [er.Role for er in eventResources if
                         resource in self.eventResourceToPossibleResourcesDict[event, er.Role]]
                self.eventResourceContainmentDict[key] = roles

        listOfTimes = list(self.instance.Times.IndividualTimes.keys())
        indexByTime = {t: i for i, t in enumerate(listOfTimes)}
        self.possibleStartTimesDict = dict()

        for t in timesWithoutDummyTime:
            for subevent in set(se for e in events for se in self.eventToSubEventListDict.get(e, [])):
                duration = subevent[0]  # Assuming duration is first element
                idx = indexByTime[t]
                start_range = listOfTimes[max(0, idx - duration + 1): idx + 1]
                self.possibleStartTimesDict[(t, duration)] = start_range

        for t in timesWithoutDummyTime:
            for resource in resourcesWithoutDummyResource:
                self.model.addConstr(gp.quicksum([self.variableDict["x"][event, subevent, start_t, er, resource] for event in events if event in self.eventToSubEventListDict.keys() for subevent in self.eventToSubEventListDict[event]
                                             for er in self.eventResourceContainmentDict[event, resource]
                                             for start_t in self.possibleStartTimesDict[t, subevent[0]]
                                                  if (event, subevent, start_t, er, resource) in self.variableDict["x"].keys()]) ==
                                self.variableDict["v"][t, resource], str(t) + "_" + str(resource) + "_link_v_x")
    
    def _add_link_subevent_resource_assignments_to_solution_constraints(self):
        events = list(self.instance.Events.IndividualEvents.keys())
        timesWithDummyTime = [ILPConstants.DUMMY_TIME] + list(self.instance.Times.IndividualTimes.keys())
        for event in events:
            if event not in self.eventToSubEventListDict:
                continue
            eventResources = (self.instance.Events.IndividualEvents[event].EventResources.AssignedResources +
                              self.instance.Events.IndividualEvents[event].EventResources.UnassignedResources)
            for subevent in self.eventToSubEventListDict[event]:
                for er in eventResources:
                    for r in self.eventResourceToPossibleResourcesDict[event, er.Role]:
                        if (event, subevent, er.Role, r) not in self.variableDict["w"].keys():
                            continue
                        self.model.addConstr(gp.quicksum([self.variableDict["x"][event, subevent, t, er.Role, r] for t in timesWithDummyTime
                                                          if (event, subevent, t, er.Role, r) in self.variableDict["x"].keys()]) == self.variableDict["w"][event, subevent, er.Role, r], str(event) + "_" + str(subevent) + "_" + str(er)+ "_" + str(r) + "_link_w_x")
    
    def _add_link_resource_assignments_between_events_and_subevents_constraitns(self):
        events = list(self.instance.Events.IndividualEvents.keys())
        resourcesWithDummyResource = [ILPConstants.DUMMY_RESOURCE] + list(self.instance.Resources.IndividualResources.keys())
        for event in events:
            eventResources = (self.instance.Events.IndividualEvents[event].EventResources.AssignedResources +
                              self.instance.Events.IndividualEvents[event].EventResources.UnassignedResources)
            if event not in self.eventToSubEventListDict:
                continue
            for subevent in self.eventToSubEventListDict[event]:
                for er in eventResources:
                    for r in self.eventResourceToPossibleResourcesDict[event, er.Role]:
                        if  (event, subevent, er.Role, r) not in self.variableDict["w"].keys():
                            continue
                        self.model.addConstr(self.variableDict["w"][event, subevent, er.Role, r] <= self.variableDict["b"][event, r], str(event) + "_" + str(subevent) + "_" + str(er)+ "_" + str(r) + "_link_w_b1")
                        self.model.addConstr(
                            self.variableDict["w"][event, subevent, er.Role, r] <= self.variableDict["d"][event, er.Role, r],
                            str(event) + "_" + str(subevent) + "_" + str(er) + "_" + str(r) + "_link_w_d1")
            for r in resourcesWithDummyResource:
                if r not in [resource for eventResource in eventResources
                             for resource in self.eventResourceToPossibleResourcesDict[event, eventResource.Role]]:
                    continue
                self.model.addConstr(gp.quicksum([self.variableDict["w"][event, se, er.Role, r]
                                             for se in self.eventToSubEventListDict[event]
                                             for er in eventResources
                                             if r in self.eventResourceToPossibleResourcesDict[event, er.Role] and (event, se, er.Role, r) in self.variableDict["w"].keys()]) >= self.variableDict["b"][event, r],
                                str(event) + "_" + str(r) + "_link_w_b2")
                for er in eventResources:
                    if r not in self.eventResourceToPossibleResourcesDict[event, er.Role]:
                        continue
                    self.model.addConstr(gp.quicksum([self.variableDict["w"][event, se, er.Role, r]
                                                      for se in self.eventToSubEventListDict[event]
                                                      if
                                                      r in self.eventResourceToPossibleResourcesDict[event, er.Role] and (
                                                      event, se, er.Role, r) in self.variableDict["w"].keys()]) >=
                                         self.variableDict["d"][event, er.Role, r],
                                         str(event) + "_" + str(r) + "_link_w_d2")

    def _add_link_resource_assignments_between_events_and_event_groups(self):
        eventGroups = self.instance.Events.EventGroups.keys()
        resourcesWithDummyResource = [ILPConstants.DUMMY_RESOURCE] + list(self.instance.Resources.IndividualResources.keys())
        for eventGroupId in eventGroups:
            eventGroup = self.instance.Events.EventGroups[eventGroupId]
            for event in eventGroup.Events:
                eventResources = (self.instance.Events.IndividualEvents[event].EventResources.AssignedResources +
                                  self.instance.Events.IndividualEvents[event].EventResources.UnassignedResources)
                for er in eventResources:
                    for r in self.eventResourceToPossibleResourcesDict[event, er.Role]:
                        self.model.addConstr(self.variableDict["b"][event, r] <= self.variableDict["c"][eventGroupId, r],
                                             str(event) + "_" + str(eventGroupId) + "_" + str(r) + "_Link_Event_With_Event_Group_resource_Usage1")
            for r in resourcesWithDummyResource:
                if (eventGroupId, r) not in self.variableDict["c"].keys():
                    continue
                self.model.addConstr(gp.quicksum([self.variableDict["b"][e, r] for e in self.instance.Events.EventGroups[eventGroupId].Events if (e, r) in self.variableDict["b"].keys()]) >=
                                     self.variableDict["c"][eventGroupId, r], str(eventGroupId) + "_" + str(r) + "_Link_Event_With_Event_Group_resource_Usage2")
    def _add_subevents_cant_extend_beyond_last_time_slot_of_day_constraints(self):
        events = list(self.instance.Events.IndividualEvents.keys())
        timesWithoutDummyTime = list(self.instance.Times.IndividualTimes.keys())

        for event in events:
            if event not in self.eventToSubEventListDict:
                continue
            for subevent in self.eventToSubEventListDict[event]:
                for t in timesWithoutDummyTime:
                    if t not in self.possibleStartTimesByEventDurationDict[subevent[0]]:
                        if (event, subevent, t) not in self.variableDict["y"]:
                            continue
                        self.model.addConstr(self.variableDict["y"][event, subevent, t] == 0,
                                        str(event) + "_" + str(subevent) + "_" + str(t) + "_impossible_start")
    
    def _add_subevent_usage_indicator_variables_constraints(self):
        events = list(self.instance.Events.IndividualEvents.keys())
        timesWithoutDummyTime = list(self.instance.Times.IndividualTimes.keys())
        # A subevent is considered active if it has a starting time or resource assigned:
        for event in events:
            if event not in self.eventToSubEventListDict:
                continue
            eventResources = self.instance.Events.IndividualEvents[event].EventResources.UnassignedResources + self.instance.Events.IndividualEvents[event].EventResources.AssignedResources
            for subevent in self.eventToSubEventListDict[event]:
                for eventResource in eventResources:
                    self.model.addConstr(gp.quicksum([self.variableDict["w"][event, subevent, eventResource.Role, r]
                                                 for r in self.eventResourceToPossibleResourcesDict[event, eventResource.Role]
                                                 if r != ILPConstants.DUMMY_RESOURCE and (event, subevent, eventResource.Role, r) in self.variableDict["w"].keys()]) <=
                                    self.variableDict["u_se"][event, subevent], str(event) + "_" + str(subevent) + "_" + str(eventResource) + "_event_active_if_resource_assigned")
    
        for event in events:
            if event not in self.eventToSubEventListDict:
                continue
            for subevent in self.eventToSubEventListDict[event]:
                self.model.addConstr(gp.quicksum([self.variableDict["y"][event, subevent, t] for t in timesWithoutDummyTime if (event, subevent, t) in self.variableDict["y"].keys()]) <= self.variableDict["u_se"][event, subevent],
                                str(event) + "_" + str(subevent) + "_event_active_if_time_assigned")
    
        # for event in events:
    def _add_sum_of_subevent_durations_equals_event_duration_constraints(self):
        events = list(self.instance.Events.IndividualEvents.keys())
        totalDurationDict = dict()
        for event in events:
            if event not in self.eventToSubEventListDict:
                continue
            totalDurationDict[event] = 0
        durationVars = self.model.addVars(totalDurationDict.keys(), vtype=GRB.INTEGER, name="wrongDur_")
        self.variableDict["DurationVars"] = durationVars
        for event in events:
            if event not in self.eventToSubEventListDict:
                continue
            self.model.addConstr(gp.quicksum([se[0] * self.variableDict["u_se"][event, se] for se in self.eventToSubEventListDict[event]]) ==
                            int(self.instance.Events.IndividualEvents[event].Duration),
                            str(event) + "_subevent_duration_equals_duration")

    def _add_link_busy_indicator_variables(self):
        events = list(self.instance.Events.IndividualEvents.keys())
        timesWithoutDummyTime = list(self.instance.Times.IndividualTimes.keys())
        resourcesWithDummyResource = [ILPConstants.DUMMY_RESOURCE] + list(self.instance.Resources.IndividualResources.keys())

        for resource in resourcesWithDummyResource:
            if not self.hardAvoidClashes:
                for t in timesWithoutDummyTime:
                    totalNumberOfSubevents = 0
                    for event in events:
                        if event not in self.eventToSubEventListDict:
                            continue
                        totalNumberOfSubevents += len(self.eventToSubEventListDict[event])

                    self.model.addConstr(totalNumberOfSubevents * self.variableDict["q"][resource, t] >= self.variableDict["v"][t, resource], str(resource) + "_" + str(t) + "_link_q_v_1")
                    self.model.addConstr(self.variableDict["q"][resource, t] <= self.variableDict["v"][t, resource], str(resource) + "_" + str(t) + "_link_q_v_2")

            for timeGroup in self.instance.Times.TimeGroups.keys():
                for t in self.instance.Times.TimeGroups[timeGroup].Times:
                    self.model.addConstr(self.variableDict["p"][resource, timeGroup] >= self.variableDict["q"][resource, t],
                                    str(resource) + "_" + str(timeGroup) + "_" + str(t) + "_link_p_q_1")
                self.model.addConstr(self.variableDict["p"][resource, timeGroup] <= gp.quicksum([self.variableDict["q"][resource, t] for t in self.instance.Times.TimeGroups[timeGroup].Times]),
                                str(resource) + "_" + str(timeGroup) + "_link_p_q_2")

            for timeGroup in self.instance.Times.Days.keys():
                for t in self.instance.Times.Days[timeGroup].Times:
                    self.model.addConstr(self.variableDict["p"][resource, timeGroup] >= self.variableDict["q"][resource, t],
                                    str(resource) + "_" + str(timeGroup) + "_" + str(t) + "_link_p_q_1")
                self.model.addConstr(self.variableDict["p"][resource, timeGroup] <= gp.quicksum([self.variableDict["q"][resource, t] for t in self.instance.Times.Days[timeGroup].Times]),
                                str(resource) + "_" + str(timeGroup) + "_link_p_q_2")
    def _add_events_with_given_start_time_are_scheduled_at_given_start_time_constraints(self):
        events = list(self.instance.Events.IndividualEvents.keys())
        for event in events:
            if event not in self.eventToSubEventListDict:
                continue
            eventObject = self.instance.Events.IndividualEvents[event]
            if eventObject.Time is not None:
                if (event, (eventObject.Duration, 0), eventObject.Time) not in self.variableDict["y"].keys():
                    continue
                self.model.addConstr(self.variableDict["y"][event, (eventObject.Duration, 0), eventObject.Time] == 1, str(event) + "_fixedTime")
    def _add_assigned_resources_inactive_if_subevent_inactive_constraints(self):
        # Note that it would not be "wrong" if an inactive event has a resource assignment as long as you would filter them
        # in the end and not add them to the solution, but it is more convenient to not allow this from the beginning
        events = list(self.instance.Events.IndividualEvents.keys())
        for event in events:
            if event not in self.eventToSubEventListDict:
                continue
            eventResources = self.instance.Events.IndividualEvents[event].EventResources.AssignedResources
            for subevent in self.eventToSubEventListDict[event]:
                for eventResource in eventResources:
                    if (event, subevent, eventResource.Role, self.eventResourceToPossibleResourcesDict[event, eventResource.Role][0]) not in self.variableDict["w"].keys():
                        continue
                    self.model.addConstr(self.variableDict["w"][event, subevent, eventResource.Role,
                    self.eventResourceToPossibleResourcesDict[event, eventResource.Role][0]] ==
                                    self.variableDict["u_se"][event, subevent], str(event) + "_" + str(subevent) +  "_" + str(eventResource) + "_noResourcesInNotActiveSubevents")
            # No need to deal with unassigned resources since if they are anything but dummyResource u_se must be 1 due to different constraints

    def _add_create_mandatory_links_to_student_events(self):
        events = list(self.instance.Events.IndividualEvents.keys())
        timesWithDummyTime = list(self.instance.Times.IndividualTimes.keys()) + [ILPConstants.DUMMY_TIME]
        for event in events:
            if event not in self.eventToSubEventListDict:
                continue
            if event.endswith('_min_requirement') or event.endswith('_max_requirement'):
                for subevent in self.eventToSubEventListDict[event]:
                    for t in timesWithDummyTime:
                        mainEvent = event.split('_')[0] + '_' + event.split('_')[1]
                        if (event, subevent, t) not in self.variableDict["y"].keys() or (mainEvent, subevent, t) not in self.variableDict["y"].keys():
                            continue
                        self.model.addConstr(self.variableDict["y"][event, subevent, t] == self.variableDict["y"][mainEvent, subevent, t])

    def add_hard_time_preferences(self):
        for event_id in self.instance.Events.IndividualEvents.keys():
            hard_time_preferences_for_event = [(constraint[XHSTTConstraintConstants.DURATION], pref_time) for constraint in self.instance.Constraints[XHSTTConstraintConstants.PREFER_TIMES_CONSTRAINT]
                                               if constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS] == [event_id]
                                               and constraint[XHSTTConstraintConstants.ID].startswith('PreferTimes_' + event_id)
                                               for pref_time in constraint[XHSTTFileConstants.TIMES]]
            subevent_counter_dict = dict()
            for pref in hard_time_preferences_for_event:
                subevent_counter_dict.setdefault(int(pref[0]), -1)
                subevent_counter_dict[int(pref[0])] = subevent_counter_dict[int(pref[0])] + 1
                subevent = (int(pref[0]), subevent_counter_dict[int(pref[0])])
                self.model.addConstr(self.variableDict["y"][event_id, subevent, pref[1]] == 1, "fix_start_time_" + str(event_id) + "_" + str(subevent) + "_" + str(pref[1]))

    def _add_same_student_assignments_for_all_student_events(self):
        events = list(self.instance.Events.IndividualEvents.keys())
        studentEvents = [event for event in events if event.endswith('_min_requirement') or event.endswith('_max_requirement')]
        for event in studentEvents:
            for subevent1Index in range(len(self.eventToSubEventListDict[event])):
                subevent1 = self.eventToSubEventListDict[event][subevent1Index]
                for subevent2 in self.eventToSubEventListDict[event][subevent1Index:]:
                    for resource in self.eventResourceToPossibleResourcesDict[event, 'Lesson Student']:
                        if resource == ILPConstants.DUMMY_RESOURCE or (event, subevent1, 'Lesson Student', resource) not in self.variableDict["w"].keys() or \
                            (event, subevent2, 'Lesson Student', resource) not in self.variableDict["w"].keys():
                            continue
                        self.model.addConstr(self.variableDict["w"][event, subevent1, 'Lesson Student', resource] ==
                                             self.variableDict["w"][event, subevent2, 'Lesson Student', resource] +
                                             self.variableDict["w"][event, subevent2, 'Lesson Student', ILPConstants.DUMMY_RESOURCE],
                                             str(subevent1) + "_" + str(subevent2) + "_" + str(event) + "_" + str(
                                                 resource) + "_LinkStudentResources")

    def _add_prevent_student_multi_assignments(self):
        eventGroupWithStudentEvents = [eventGroup for eventGroup in self.instance.Events.EventGroups.keys() if eventGroup.startswith('LS_') and len(eventGroup.split('_')) == 2]
        if XHSTTFileConstants.STUDENT in self.instance.Resources.ResourceGroupsByType.keys():
            studentResourcesWithoutDummyResource = [student for student in self.instance.Resources.ResourceGroupsByType[XHSTTFileConstants.STUDENT].ResourceGroups[XHSTTFileConstants.ALL_STUDENTS].Resources if not student.startswith('CL_')]
        else:
            studentResourcesWithoutDummyResource = list()
        for eventGroup in eventGroupWithStudentEvents:
            for r in studentResourcesWithoutDummyResource:
                self.model.addConstr(gp.quicksum([self.variableDict["b"][event, r] for event in self.instance.Events.EventGroups[eventGroup].Events if (event, r) in self.variableDict["b"].keys()])
                                     <= 1 + ILPConstants.EPS, str(eventGroup) + "_" + str(r) + "_studentOnlyAttendsOneSlot")

    def _add_prevent_resource_assignment_to_multiple_roles(self):
        for event in self.instance.Events.IndividualEvents.keys():
            eventResources = (self.instance.Events.IndividualEvents[event].EventResources.AssignedResources +
                              self.instance.Events.IndividualEvents[event].EventResources.UnassignedResources)
            possibleResources = set()
            for eventResource in eventResources:
                possibleResources.update(self.eventResourceToPossibleResourcesDict[event, eventResource.Role])
            for subevent in self.eventToSubEventListDict[event]:
                for resource in possibleResources:
                    if resource == ILPConstants.DUMMY_RESOURCE:
                        continue
                    self.model.addConstr(gp.quicksum([self.variableDict["w"][event, subevent, er.Role, resource] for er in eventResources if (event, subevent, er.Role, resource) in self.variableDict["w"].keys()]) <= 1, "NoAssignmentsToMultipleRolesForSingleResource_" + str(event) + "_" + str(subevent) + "_"+ str(resource))


    def _add_assign_resource_constraints(self):
        for constraint in self.instance.Constraints[XHSTTConstraintConstants.ASSIGN_RESOURCE_CONSTRAINT]:
            consideredEvents = set([(event, None) for event in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS]])
            for eventGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
                consideredEvents.update(
                    set([(event, eventGroup) for event in self.instance.Events.EventGroups[eventGroup].Events]))
            for event in consideredEvents:
                eventResources = (self.instance.Events.IndividualEvents[event[0]].EventResources.AssignedResources +
                                  self.instance.Events.IndividualEvents[event[0]].EventResources.UnassignedResources)
                for eventResource in eventResources:
                    if eventResource.Role == constraint[XHSTTFileConstants.ROLE]:
                        self.model.addConstr(self.instance.Events.IndividualEvents[event[0]].Duration - gp.quicksum(
                            [self.variableDict["w"][event[0], se, eventResource.Role, r] * se[0] for se in self.eventToSubEventListDict[event[0]]
                             for r in self.eventResourceToPossibleResourcesDict[event[0], eventResource.Role]
                             if r != ILPConstants.DUMMY_RESOURCE and (event[0], se, eventResource.Role, r) in self.variableDict["w"].keys()])
                                        == self.variableDict["s"][ILPConstants.ASSIGN_RESOURCE][constraint[XHSTTFileConstants.ID], event, eventResource.Role],
                                        str(constraint[XHSTTFileConstants.ID]) + "_" + str(event) + "_" + str(
                                            eventResource.Role) + "_assignRes")
    
    
    def _add_assign_time_constraints(self, hardAssignTimes: bool):
        timesWithoutDummyTime = list(self.instance.Times.IndividualTimes.keys())
        for constraint in self.instance.Constraints[XHSTTConstraintConstants.ASSIGN_TIME_CONSTRAINT]:
            consideredEvents = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS])
            for eventGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
                consideredEvents.update(set(self.instance.Events.EventGroups[eventGroup].Events))

            eventDict = dict()
            eventDurationHelper = dict()
            for event in consideredEvents:
                eventDict[event] = 0
                for se in self.eventToSubEventListDict[event]:
                    for t in timesWithoutDummyTime:
                        if (event, se, t) in self.variableDict["y"].keys():
                            eventDurationHelper[event, se, t] = 0

            durationVars = self.model.addVars(eventDict.keys(), vtype=GRB.INTEGER, name="dur_", lb=0)
            durationHelperVars = self.model.addVars(eventDurationHelper.keys(), vtype=GRB.INTEGER, name="help_dur_", lb=0)
            for event in consideredEvents:
                self.model.addConstr(durationHelperVars.sum(event, '*', '*') == durationVars[event], "AssignedDuration_" + str(event))


                if hardAssignTimes:
                    self.model.addConstr(self.instance.Events.IndividualEvents[event].Duration - durationVars[event]
                    == 0,
                    str(constraint[XHSTTFileConstants.ID]) + "_" + str(event) + "_assignTimeHard")
                else:
                    self.model.addConstr(
                        self.instance.Events.IndividualEvents[event].Duration - durationVars[event]
                        == self.variableDict["s"][ILPConstants.ASSIGN_TIME][constraint[XHSTTFileConstants.ID], event],
                        str(constraint[XHSTTFileConstants.ID]) + "_" + str(event) + "_assignTime")

                for se in self.eventToSubEventListDict[event]:
                    for t in timesWithoutDummyTime:
                        if (event, se, t) in self.variableDict["y"].keys():
                            self.model.addConstr(self.variableDict["y"][event, se, t] * se[0] == durationHelperVars[event, se, t], "DurationHelp_" + str((event, se, t)))
    
    def _add_split_events_constraints(self):
    
        for constraint in self.instance.Constraints[XHSTTConstraintConstants.SPLIT_EVENTS_CONSTRAINT]:
            consideredEvents = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS])
            for eventGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
                consideredEvents.update(set(self.instance.Events.EventGroups[eventGroup].Events))
    
            splitEventVariableDict = dict()
            maxEventLength = 0
            for event in consideredEvents:
                maxEventLength = max(maxEventLength, self.instance.Events.IndividualEvents[event].Duration)
                splitEventVariableDict[constraint[XHSTTFileConstants.ID], event] = 0
    
            localM = max(maxEventLength, int(constraint[XHSTTConstraintConstants.MINIMUM_AMOUNT]), int(constraint[XHSTTConstraintConstants.MAXIMUM_AMOUNT])) + 1
            splitEventVars = self.model.addVars(splitEventVariableDict.keys(), vtype=GRB.INTEGER, name="splitEventValue", lb=0)
            splitEventMin = self.model.addVars(splitEventVariableDict.keys(), vtype=GRB.BINARY, name="splitEventMin", lb=0)
            splitEventMax = self.model.addVars(splitEventVariableDict.keys(), vtype=GRB.BINARY, name="splitEventMax", lb=0)
    
            for event in consideredEvents:
                self.model.addConstr(splitEventVars[constraint[XHSTTFileConstants.ID], event] ==
                                gp.quicksum([self.variableDict["u_se"][event, se] for se in self.eventToSubEventListDict[event]]),
                                str(constraint[XHSTTFileConstants.ID]) + "_" + str(event) + "_splitEventLinkVar")
    
                self.model.addConstr(splitEventVars[constraint[XHSTTFileConstants.ID], event] >=
                                int(constraint[XHSTTConstraintConstants.MAXIMUM_AMOUNT]) + ILPConstants.EPS - localM *
                                (1 - splitEventMax[constraint[XHSTTFileConstants.ID], event]),
                                str(constraint[XHSTTFileConstants.ID]) + "_" + str(event) + "_linkSplitEventVarsMax1")

                self.model.addConstr(splitEventVars[constraint[XHSTTFileConstants.ID], event] <=
                                int(constraint[XHSTTConstraintConstants.MAXIMUM_AMOUNT]) + localM *
                                (splitEventMax[constraint[XHSTTFileConstants.ID], event]),
                                str(constraint[XHSTTFileConstants.ID]) + "_" + str(event) + "_linkSplitEventVarsMax2")

                self.model.addConstr(int(constraint[XHSTTConstraintConstants.MINIMUM_AMOUNT]) >=
                                splitEventVars[constraint[XHSTTFileConstants.ID], event] + ILPConstants.EPS - localM *
                                (1 - splitEventMin[constraint[XHSTTFileConstants.ID], event]),
                                str(constraint[XHSTTFileConstants.ID]) + "_" + str(event) + "_linkSplitEventVarsMin1")

                self.model.addConstr(int(constraint[XHSTTConstraintConstants.MINIMUM_AMOUNT]) <=
                                splitEventVars[constraint[XHSTTFileConstants.ID], event] + localM *
                                (splitEventMin[constraint[XHSTTFileConstants.ID], event]),
                                str(constraint[XHSTTFileConstants.ID]) + "_" + str(event) + "_linkSplitEventVarsMin2")
    
    
                self.model.addConstr((splitEventMax[constraint[XHSTTFileConstants.ID], event] == 1) >>
                                (splitEventVars[constraint[XHSTTFileConstants.ID], event] - int(constraint[XHSTTConstraintConstants.MAXIMUM_AMOUNT]) ==
                                self.variableDict["s"][ILPConstants.SPLIT_EVENT_AMOUNT][constraint[XHSTTFileConstants.ID], event]), str(constraint[XHSTTFileConstants.ID]) + "_" + str(event) +
                                "_splitEventAmountUpper")
                self.model.addConstr((splitEventMin[constraint[XHSTTFileConstants.ID], event] == 1) >>
                                (int(constraint[XHSTTConstraintConstants.MINIMUM_AMOUNT]) - splitEventVars[constraint[XHSTTFileConstants.ID], event] ==
                                self.variableDict["s"][ILPConstants.SPLIT_EVENT_AMOUNT][constraint[XHSTTFileConstants.ID], event]), str(constraint[XHSTTFileConstants.ID]) + "_" + str(event) +
                                "_splitEventAmountLower")

                self.model.addConstr(gp.quicksum([self.variableDict["u_se"][event, se] for se in self.eventToSubEventListDict[event]
                                            if se[0] > int(constraint[XHSTTConstraintConstants.MAXIMUM_DURATION]) or
                                            se[0] < int(constraint[XHSTTConstraintConstants.MINIMUM_DURATION])]) ==
                                self.variableDict["s"][ILPConstants.SPLIT_EVENT_DURATION][constraint[XHSTTFileConstants.ID], event], str(constraint[XHSTTFileConstants.ID]) + "_" + str(event) +
                                "_splitEventDuration")
    
    
    def _add_distribute_split_events_constraints(self):
    
        for constraint in self.instance.Constraints[XHSTTConstraintConstants.DISTRIBUTE_SPLIT_EVENTS_CONSTRAINT]:
            consideredEvents = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS])
            for eventGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
                consideredEvents.update(set(self.instance.Events.EventGroups[eventGroup].Events))
    
            distributeSplitEventVariableDict = dict()
            maxEventLength = 0
            for event in consideredEvents:
                maxEventLength = max(maxEventLength, self.instance.Events.IndividualEvents[event].Duration)
                distributeSplitEventVariableDict[constraint[XHSTTFileConstants.ID], event] = 0
    
            localM = max(maxEventLength, int(constraint[XHSTTConstraintConstants.MINIMUM]), int(constraint[XHSTTConstraintConstants.MAXIMUM])) + 1
            distributeSplitEventVars = self.model.addVars(distributeSplitEventVariableDict.keys(), vtype=GRB.INTEGER, name="distSplitEventValue", lb=0)
            distributeSplitEventMin = self.model.addVars(distributeSplitEventVariableDict.keys(), vtype=GRB.BINARY, name="distSplitEventMin", lb=0)
            distributeSplitEventMax = self.model.addVars(distributeSplitEventVariableDict.keys(), vtype=GRB.BINARY, name="distSplitEventMax", lb=0)
    
            for event in consideredEvents:
                self.model.addConstr(distributeSplitEventVars[constraint[XHSTTFileConstants.ID], event] ==
                                gp.quicksum([self.variableDict["u_se"][event, se]
                                             for se in self.eventToSubEventListDict[event] if se[0] == int(constraint[XHSTTFileConstants.DURATION])]),
                                str(constraint[XHSTTFileConstants.ID]) + "_" + str(event) + "_distributeSplitEventLinkVar")
    
                self.model.addConstr(distributeSplitEventVars[constraint[XHSTTFileConstants.ID], event] >=
                                int(constraint[XHSTTConstraintConstants.MAXIMUM]) + ILPConstants.EPS - localM *
                                (1 - distributeSplitEventMax[constraint[XHSTTFileConstants.ID], event]),
                                str(constraint[XHSTTFileConstants.ID]) + "_" + str(event) + "_linkDistributeSplitEventVarsMax1")
    
                self.model.addConstr(distributeSplitEventVars[constraint[XHSTTFileConstants.ID], event] <=
                                int(constraint[XHSTTConstraintConstants.MAXIMUM]) + localM *
                                (distributeSplitEventMax[constraint[XHSTTFileConstants.ID], event]),
                                str(constraint[XHSTTFileConstants.ID]) + "_" + str(event) + "_linkDistributeSplitEventVarsMax2")
    
                self.model.addConstr(int(constraint[XHSTTConstraintConstants.MINIMUM]) >=
                                distributeSplitEventVars[constraint[XHSTTFileConstants.ID], event] + ILPConstants.EPS - localM *
                                (1 - distributeSplitEventMin[constraint[XHSTTFileConstants.ID], event]),
                                str(constraint[XHSTTFileConstants.ID]) + "_" + str(event) + "_linkDistributeSplitEventVarsMin1")
    
                self.model.addConstr(int(constraint[XHSTTConstraintConstants.MINIMUM]) <=
                                distributeSplitEventVars[constraint[XHSTTFileConstants.ID], event] + localM *
                                (distributeSplitEventMin[constraint[XHSTTFileConstants.ID], event]),
                                str(constraint[XHSTTFileConstants.ID]) + "_" + str(event) + "_linkDistributeSplitEventVarsMin2")
    
                self.model.addConstr((distributeSplitEventMax[constraint[XHSTTFileConstants.ID], event] == 1) >>
                                (distributeSplitEventVars[constraint[XHSTTFileConstants.ID], event] - int(constraint[XHSTTConstraintConstants.MAXIMUM]) ==
                                self.variableDict["s"][ILPConstants.DIST_SPLIT_EVENT][constraint[XHSTTFileConstants.ID], event, int(constraint[XHSTTFileConstants.DURATION])]), str(constraint[XHSTTFileConstants.ID]) + "_" + str(event) +
                                "_" + str(constraint[XHSTTFileConstants.DURATION]) + "_distSplitEventUpper")
                self.model.addConstr((distributeSplitEventMin[constraint[XHSTTFileConstants.ID], event] == 1) >>
                                (int(constraint[XHSTTConstraintConstants.MINIMUM]) - distributeSplitEventVars[constraint[XHSTTFileConstants.ID], event] ==
                    self.variableDict["s"][ILPConstants.DIST_SPLIT_EVENT][constraint[XHSTTFileConstants.ID], event, int(constraint[XHSTTFileConstants.DURATION])]), str(constraint[XHSTTFileConstants.ID]) + "_" + str(event) + "_" +
                                str(constraint[XHSTTFileConstants.DURATION]) + "_distSplitEventLower")
    
    def _add_prefer_resource_constraints(self):
    
        for constraint in self.instance.Constraints[XHSTTConstraintConstants.PREFER_RESOURCES_CONSTRAINT]:
            consideredEvents = [(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS][eventindex], eventindex) for eventindex in range(len(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS]))]
            for eventGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
                consideredEvents = consideredEvents + [(event, "Group" + str(eventGroup)) for event in self.instance.Events.EventGroups[eventGroup].Events]

            if XHSTTFileConstants.RESOURCES in constraint:
                preferredResources = set(constraint[XHSTTFileConstants.RESOURCES])
            else:
                preferredResources = set()
            if XHSTTFileConstants.RESOURCE_GROUPS in constraint:
                for resourceGroup in constraint[XHSTTFileConstants.RESOURCE_GROUPS]:
                    for resourceType in self.instance.Resources.ResourceGroupsByType.keys():
                        if resourceGroup in self.instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups:
                            preferredResources.update(set(self.instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups[resourceGroup].Resources))
    
            for event in consideredEvents:
                for eventResource in self.instance.Events.IndividualEvents[event[0]].EventResources.UnassignedResources:
                    if eventResource.Role == constraint[XHSTTFileConstants.ROLE]:
                        self.model.addConstr(gp.quicksum([se[0] * self.variableDict["w"][event[0], se, eventResource.Role, r] for se in self.eventToSubEventListDict[event[0]]
                                                     for r in self.eventResourceToPossibleResourcesDict[event[0], eventResource.Role]
                                                     if r not in preferredResources and r != ILPConstants.DUMMY_RESOURCE and (event[0], se, eventResource.Role, r) in self.variableDict["w"].keys()]) ==
                                        self.variableDict["s"][ILPConstants.PREFER_RESOURCE][constraint[XHSTTFileConstants.ID], event, eventResource.Role], str(constraint[XHSTTFileConstants.ID]) + "_" +
                                        str(event) + "_" + str(eventResource.Role) + "_preferRes")
    
    
    def _add_prefer_time_constraints(self):
        timesWithoutDummyTime = list(self.instance.Times.IndividualTimes.keys())
    
        for constraint in self.instance.Constraints[XHSTTConstraintConstants.PREFER_TIMES_CONSTRAINT]:
            consideredEvents = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS])
            for eventGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
                consideredEvents.update(set(self.instance.Events.EventGroups[eventGroup].Events))
    
            # Note that we ensured that Times and TimeGroups are either both present or None of them is
            if XHSTTFileConstants.TIMES in constraint.keys():
                constraintTimes = set(constraint[XHSTTFileConstants.TIMES])
                for timeGroup in constraint[XHSTTFileConstants.TIME_GROUPS]:
                    if timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT] in self.instance.Times.TimeGroups.keys():
                        constraintTimes.update(set(self.instance.Times.TimeGroups[timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]].Times))
                    elif timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT] in self.instance.Times.Days.keys():
                        constraintTimes.update(set(self.instance.Times.Days[timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]].Times))
            else:
                constraintTimes = set()
    
            for event in consideredEvents:
                self.model.addConstr(
                    gp.quicksum([self.variableDict["y"][event, se, t] * se[0] for se in self.eventToSubEventListDict[event]
                                                 for t in timesWithoutDummyTime if t not in constraintTimes and (event, se, t) in self.variableDict["y"].keys()
                                                 and (XHSTTFileConstants.DURATION not in constraint.keys() or int(constraint[XHSTTFileConstants.DURATION]) == se[0])])
                    == self.variableDict["s"][ILPConstants.PREFER_TIME][constraint[XHSTTFileConstants.ID], event],
                    str(constraint[XHSTTFileConstants.ID]) + "_" + str(event) + "_preferTime")
    
    def _add_avoid_split_assignments_constraints(self):
        resourcesWithDummyResource = [ILPConstants.DUMMY_RESOURCE] + list(self.instance.Resources.IndividualResources.keys())
        resourcesWithoutDummyResource = list(self.instance.Resources.IndividualResources.keys())
        eventGroupHasZeroAssignments = dict()
        eventResourceToResourceAssignmentDict = dict()
        for constraint in self.instance.Constraints[XHSTTConstraintConstants.AVOID_SPLIT_ASSIGNMENTS_CONSTRAINT]:
            for eventGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
                eventGroupHasZeroAssignments[constraint[XHSTTFileConstants.ROLE], eventGroup] = 0
                for resource in resourcesWithDummyResource:
                    eventResourceToResourceAssignmentDict[constraint[XHSTTFileConstants.ROLE], eventGroup, resource] = 0

        k = self.model.addVars(eventResourceToResourceAssignmentDict.keys(), vtype=GRB.BINARY, name="k", lb=0)
        zeroAssignmentsVars = self.model.addVars(eventGroupHasZeroAssignments, vtype=GRB.BINARY,
                                                 name="eventGroupHasZeroAssignments", lb=0)
        for constraint in self.instance.Constraints[XHSTTConstraintConstants.AVOID_SPLIT_ASSIGNMENTS_CONSTRAINT]:
            if XHSTTConstraintConstants.CONSIDER_UNASSIGNED_RESOURCES in constraint and constraint[XHSTTConstraintConstants.CONSIDER_UNASSIGNED_RESOURCES]:
                consideredResources = resourcesWithDummyResource
            else:
                consideredResources = resourcesWithoutDummyResource
            for eventGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
                # print(f"Avoid Split: {eventGroup} {constraint[XHSTTFileConstants.ROLE]}")
                possibleResources = set()
                for event in self.instance.Events.EventGroups[eventGroup].Events:
                    for subevent in self.eventToSubEventListDict[event]:
                        for r in self.eventResourceToPossibleResourcesDict[event, constraint[XHSTTFileConstants.ROLE]]:
                            possibleResources.update([r])
                            if (event, subevent, constraint[XHSTTFileConstants.ROLE], r) in self.variableDict[
                                "w"].keys():
                                self.model.addConstr(self.variableDict["w"][event, subevent, constraint[XHSTTFileConstants.ROLE], r] - (1 - self.variableDict["u_se"][event, subevent]) <=
                                                k[constraint[XHSTTFileConstants.ROLE], eventGroup, r], str(constraint[XHSTTFileConstants.ROLE]) + "_" +
                                                str(eventGroup) + "_" + str(resource) + "_link_w_k1")
                for resource in possibleResources:
                    if resource == ILPConstants.DUMMY_RESOURCE:
                        self.model.addConstr(gp.quicksum([self.variableDict["w"][event, subevent, constraint[XHSTTFileConstants.ROLE], r]
                                                     for event in self.instance.Events.EventGroups[eventGroup].Events
                                                     for subevent in self.eventToSubEventListDict[event]
                                                     for r in self.eventResourceToPossibleResourcesDict[event, constraint[XHSTTFileConstants.ROLE]]
                                                     if r == resource and (event, subevent, constraint[XHSTTFileConstants.ROLE], r) in self.variableDict["w"].keys()]) - (-1 * gp.quicksum([(1 - self.variableDict["u_se"][event, subevent])
                                                     for event in self.instance.Events.EventGroups[eventGroup].Events
                                                     for subevent in self.eventToSubEventListDict[event]])) >=
                                                    k[constraint[XHSTTFileConstants.ROLE], eventGroup, resource], str(constraint[XHSTTFileConstants.ROLE]) + "_" +
                                                    str(eventGroup) + "_" + str(resource) + "_link_w_k2")
                    else:
                        self.model.addConstr(
                            gp.quicksum([self.variableDict["w"][event, subevent, constraint[XHSTTFileConstants.ROLE], r]
                                         for event in self.instance.Events.EventGroups[eventGroup].Events
                                         for subevent in self.eventToSubEventListDict[event]
                                         for r in self.eventResourceToPossibleResourcesDict[
                                             event, constraint[XHSTTFileConstants.ROLE]]
                                         if
                                         r == resource and (event, subevent, constraint[XHSTTFileConstants.ROLE], r) in
                                         self.variableDict["w"].keys()]) >=
                            k[constraint[XHSTTFileConstants.ROLE], eventGroup, resource],
                            str(constraint[XHSTTFileConstants.ROLE]) + "_" +
                            str(eventGroup) + "_" + str(resource) + "_link_w_k2")

            for eventGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
                localM = 1
                for event in self.instance.Events.EventGroups[eventGroup].Events:
                    localM += len(self.eventToSubEventListDict[event])
                self.model.addConstr(
                    gp.quicksum([k[constraint[XHSTTFileConstants.ROLE], eventGroup, r] for r in consideredResources]) >= ILPConstants.EPS -
                    localM * (1 - zeroAssignmentsVars[constraint[XHSTTFileConstants.ROLE], eventGroup]),
                    str(constraint[XHSTTFileConstants.ROLE]) + "_" +
                    str(eventGroup) + "_linkZeroIndicator")
                self.model.addConstr(
                    gp.quicksum([k[constraint[XHSTTFileConstants.ROLE], eventGroup, r] for r in consideredResources]) <=
                    localM * (zeroAssignmentsVars[constraint[XHSTTFileConstants.ROLE], eventGroup]),
                    str(constraint[XHSTTFileConstants.ROLE]) + "_" +
                    str(eventGroup) + "_linkZeroIndicator")

                self.model.addConstr((zeroAssignmentsVars[constraint[XHSTTFileConstants.ROLE], eventGroup] == 1) >>
                                     (gp.quicksum(
                        [k[constraint[XHSTTFileConstants.ROLE], eventGroup, r] for r in consideredResources]) - 1 ==
                    self.variableDict["s"][ILPConstants.AVOID_SPLIT][constraint[XHSTTFileConstants.ID], eventGroup]),
                    str(constraint[XHSTTFileConstants.ID]) + "_" +
                    str(eventGroup) + "_avoidSplit")
                self.model.addConstr((zeroAssignmentsVars[constraint[XHSTTFileConstants.ROLE], eventGroup] == 0) >>
                                     (0 == self.variableDict["s"][ILPConstants.AVOID_SPLIT][
                                          constraint[XHSTTFileConstants.ID], eventGroup]),
                                     str(constraint[XHSTTFileConstants.ROLE]) + "_" +
                                     str(eventGroup) + "_avoidSplit")
    
    
    def _add_spread_events_constraints(self):
    
        spreadVariableDict = dict()
        for constraint in self.instance.Constraints[XHSTTConstraintConstants.SPREAD_EVENTS_CONSTRAINT]:
            for eventGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
                for timeGroup in constraint[XHSTTFileConstants.TIME_GROUPS]:
                    spreadVariableDict[constraint[XHSTTFileConstants.ID], eventGroup, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] = 0

        spreadVars = self.model.addVars(spreadVariableDict.keys(), vtype=GRB.INTEGER, name="spreadValue", lb=0)
        spreadVarsMin = self.model.addVars(spreadVariableDict.keys(), vtype=GRB.BINARY, name="spreadMin", lb=0)
        spreadVarsMax = self.model.addVars(spreadVariableDict.keys(), vtype=GRB.BINARY, name="spreadMax", lb=0)
    
        for constraint in self.instance.Constraints[XHSTTConstraintConstants.SPREAD_EVENTS_CONSTRAINT]:
            # print(f"Constraint ID: {constraint[XHSTTFileConstants.ID]}")
            for eventGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
                # print(f"Event Group {eventGroup}: Events: {self.instance.Events.EventGroups[eventGroup].Events}")
                for timeGroup in constraint[XHSTTFileConstants.TIME_GROUPS]:
                    if timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT] in self.instance.Times.TimeGroups.keys():
                        relevantTimes = set(self.instance.Times.TimeGroups[timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]].Times)
                    elif timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT] in self.instance.Times.Days.keys():
                        relevantTimes = set(self.instance.Times.Days[timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]].Times)
                    # print(f"TIME GROUP: {timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]}: {relevantTimes}")

                    self.model.addConstr(spreadVars[constraint[XHSTTFileConstants.ID], eventGroup, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] ==
                                    gp.quicksum([self.variableDict["y"][e, se, t]
                                                 for e in self.instance.Events.EventGroups[eventGroup].Events
                                        for se in self.eventToSubEventListDict[e]
                                     for t in relevantTimes if (e, se, t) in self.variableDict["y"].keys()]), str(constraint[XHSTTFileConstants.ID]) +
                        "_EG" + str(eventGroup) + "_TG" + str(timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]) + "_linkJJ")
                    localM = sum([int(self.instance.Events.IndividualEvents[event].Duration) for event in self.instance.Events.EventGroups[eventGroup].Events]) + 1 + max(int(timeGroup[XHSTTConstraintConstants.MAXIMUM]), int(timeGroup[XHSTTConstraintConstants.MINIMUM]))
                    self.model.addConstr(spreadVars[constraint[XHSTTFileConstants.ID], eventGroup, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] >=
                                    int(timeGroup[XHSTTConstraintConstants.MAXIMUM]) + ILPConstants.EPS - localM *
                                    (1 - spreadVarsMax[constraint[XHSTTFileConstants.ID], eventGroup, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]]),
                                    str(constraint[XHSTTFileConstants.ID]) + "_EG" + str(eventGroup) + "_TG" + str(timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT])
                                    + "_linkSpreadMax1")
    
                    self.model.addConstr(spreadVars[constraint[XHSTTFileConstants.ID], eventGroup, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] <=
                                    int(timeGroup[XHSTTConstraintConstants.MAXIMUM]) + localM *
                                    (spreadVarsMax[constraint[XHSTTFileConstants.ID], eventGroup, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]]),
                                    str(constraint[XHSTTFileConstants.ID]) + "_EG" + str(eventGroup) + "_TG" + str(timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT])
                                    + "_linkSpreadMax2")
    
                    self.model.addConstr(int(timeGroup[XHSTTConstraintConstants.MINIMUM]) >=
                                    spreadVars[constraint[XHSTTFileConstants.ID], eventGroup, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] + ILPConstants.EPS - localM *
                                    (1 - spreadVarsMin[constraint[XHSTTFileConstants.ID], eventGroup, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]]),
                                    str(constraint[XHSTTFileConstants.ID]) + "_EG" + str(eventGroup) + "_TG" + str(timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT])
                                    + "_linkSpreadMin1")
    
                    self.model.addConstr(int(timeGroup[XHSTTConstraintConstants.MINIMUM]) <=
                                    spreadVars[constraint[XHSTTFileConstants.ID], eventGroup, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] + localM *
                                    (spreadVarsMin[constraint[XHSTTFileConstants.ID], eventGroup, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]]),
                                    str(constraint[XHSTTFileConstants.ID]) + "_EG" + str(eventGroup) + "_TG" + str(timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT])
                                    + "_linkSpreadMin2")
    
                    self.model.addConstr((spreadVarsMax[constraint[XHSTTFileConstants.ID], eventGroup, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] == 1) >>
                                    (spreadVars[constraint[XHSTTFileConstants.ID], eventGroup, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] - int(timeGroup[XHSTTConstraintConstants.MAXIMUM]) ==
                        self.variableDict["s"][ILPConstants.SPREAD_EVENT][constraint[XHSTTFileConstants.ID], eventGroup, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]]),
                        str(constraint[XHSTTFileConstants.ID]) +
                        "_EG" + str(eventGroup) + "_TG" + str(timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]) + "_spreadEventAmountUpper")
                    self.model.addConstr((spreadVarsMin[constraint[XHSTTFileConstants.ID], eventGroup, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] == 1) >>
                                    (int(timeGroup[XHSTTConstraintConstants.MINIMUM]) - spreadVars[constraint[XHSTTFileConstants.ID], eventGroup, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] ==
                        self.variableDict["s"][ILPConstants.SPREAD_EVENT][constraint[XHSTTFileConstants.ID], eventGroup, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]]),
                        str(constraint[XHSTTFileConstants.ID]) +
                        "_EG" + str(eventGroup) + "_TG" + str(timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]) + "_spreadEventAmountLower")
    
    def _add_link_events_constraints(self):
        timesWithoutDummyTime = list(self.instance.Times.IndividualTimes.keys())

        if len(self.instance.Constraints[XHSTTConstraintConstants.LINK_EVENTS_CONSTRAINT]) == 0:
            return

        eventsAppearingInLinkEventConstraints = set()

        for constraint in self.instance.Constraints[XHSTTConstraintConstants.LINK_EVENTS_CONSTRAINT]:

            for eventGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
                group_events = self.instance.Events.EventGroups[eventGroup].Events
                eventsAppearingInLinkEventConstraints.update(set(group_events))

        event_at_time = self.model.addVars(eventsAppearingInLinkEventConstraints, timesWithoutDummyTime, vtype=GRB.BINARY, name="event_at_time")

        event_is_unscheduled = self.model.addVars(eventsAppearingInLinkEventConstraints, vtype=GRB.BINARY, name="event_is_scheduled")

        for e in eventsAppearingInLinkEventConstraints:
            if e not in self.eventToSubEventListDict:
                continue

            subevents = self.eventToSubEventListDict[e]
            self.model.addConstr(
                event_is_unscheduled[e] == gp.min_([
                    (self.variableDict["y"][e, se, ILPConstants.DUMMY_TIME])
                    for se in subevents
                ]), name=f"sched_{e}"
            )

            for t in timesWithoutDummyTime:
                covering_vars = []
                for se in subevents:
                    duration = se[0]
                    possible_starts = self._get_possible_start_times_of_event_running_at_duration_t(t, duration)
                    for ts in possible_starts:
                        covering_vars.append(self.variableDict["y"][e, se, ts])

                if covering_vars:
                    self.model.addConstr(event_at_time[e, t] == gp.max_(covering_vars), name=f"occ_{e}_{t}")
                else:
                    self.model.addConstr(event_at_time[e, t] == 0)

        # 3. Apply Constraints
        for constraint in self.instance.Constraints[XHSTTConstraintConstants.LINK_EVENTS_CONSTRAINT]:
            c_id = constraint[XHSTTFileConstants.ID]

            for eventGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS]:
                group_events = self.instance.Events.EventGroups[eventGroup].Events

                for t in timesWithoutDummyTime:
                    u = self.model.addVar(vtype=GRB.BINARY, name=f"union_{eventGroup}_{t}")
                    self.model.addConstr(u == gp.max_([event_at_time[e, t] for e in group_events]))

                    i = self.model.addVar(vtype=GRB.BINARY, name=f"inter_{eventGroup}_{t}")

                    temp_checks = []
                    for e in group_events:
                        tc = self.model.addVar(vtype=GRB.BINARY)
                        self.model.addConstr(tc == event_at_time[e, t] + (event_is_unscheduled[e]))
                        temp_checks.append(tc)

                    self.model.addConstr(i == gp.min_(temp_checks))

                    dev_t = self.model.addVar(vtype=GRB.BINARY, name=f"dev_{eventGroup}_{t}")

                    group_all_unscheduled = self.model.addVar(vtype=GRB.BINARY)
                    self.model.addConstr(group_all_unscheduled == gp.min_([event_is_unscheduled[e] for e in group_events]))

                    self.model.addConstr(dev_t >= u - i)
                    self.model.addConstr(dev_t <= 1 - group_all_unscheduled)
                    self.model.addConstr(dev_t <= u)

                    self.model.addConstr(
                        self.variableDict["s"][ILPConstants.LINK_EVENT][c_id, eventGroup, t] == dev_t)
    
    def _add_avoid_clashes_constraints(self):
        timesWithoutDummyTime = list(self.instance.Times.IndividualTimes.keys())
        resourcesWithoutDummyResource = list(self.instance.Resources.IndividualResources.keys())
        events = list(self.instance.Events.IndividualEvents.keys())
        if self.hardAvoidClashes:
            for resource in resourcesWithoutDummyResource:
                for t in timesWithoutDummyTime:
                    self.model.addConstr(gp.quicksum(self.variableDict["x"][e, se, start_t, er, resource] for e in events for se in self.eventToSubEventListDict[e]
                                                     for er in self._get_eventResources_of_event_that_contain_resource(e, resource)
                                                    for start_t in self._get_possible_start_times_of_event_running_at_duration_t(t, se[0])
                                                     if (e, se, start_t, er, resource) in self.variableDict["x"].keys()) == self.variableDict["q"][resource, t], str(resource) + "_" + str(t) + "_hardClash")
        for constraint in self.instance.Constraints[XHSTTConstraintConstants.AVOID_CLASHES_CONSTRAINT]:
            constraintResources = set([(resource, None) for resource in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCES]])
            for resourceGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCE_GROUPS]:
                for resourceType in self.instance.Resources.ResourceGroupsByType.keys():
                    if resourceGroup in self.instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups:
                        constraintResources.update(
                            set((resource, resourceGroup) for resource in
                                self.instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups[
                                    resourceGroup].Resources))
            for resource in constraintResources:
                for t in timesWithoutDummyTime:
                    if not self.hardAvoidClashes:
                        localM = len(self.instance.Times.IndividualTimes.keys())
                        isBiggerOne = self.model.addVar(vtype=GRB.BINARY,
                                                        name=str(constraint[XHSTTFileConstants.ID]) + "_" + str(
                                                            resource) + "_" + str(t) + "_avoidClashesBinaryHelper")
                        self.model.addConstr(self.variableDict["v"][t, resource[0]] >=
                                        1 + ILPConstants.EPS - localM *
                                        (1 - isBiggerOne),
                                        str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_" + str(t) + "_avoidClashesActivate1")

                        self.model.addConstr(self.variableDict["v"][t, resource[0]] <=
                                        1 + localM *
                                        isBiggerOne,
                                        str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_" + str(t) + "_avoidClashesActivate2")
                        self.model.addConstr((isBiggerOne == 1) >>
                                        (self.variableDict["v"][t, resource[0]] - 1 == self.variableDict["s"][ILPConstants.AVOID_CLASHES][
                            constraint[XHSTTFileConstants.ID], resource, t]),
                                        str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_" + str(t) + "_avoidClashes")
                    else:
                        self.model.addConstr(self.variableDict["s"][ILPConstants.AVOID_CLASHES][
                                                 constraint[XHSTTFileConstants.ID], resource, t] == 0,
                                             str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_" + str(
                                                 t) + "_hardNoClashes")
    
    def _add_avoid_unavailable_times_constraints(self):
    
        for constraint in self.instance.Constraints[XHSTTConstraintConstants.AVOID_UNAVAILABLE_TIMES_CONSTRAINT]:
            constraintResources = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCES])
            for resourceGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCE_GROUPS]:
                for resourceType in self.instance.Resources.ResourceGroupsByType.keys():
                    if resourceGroup in self.instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups:
                        constraintResources.update(
                            set(self.instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups[resourceGroup].Resources))
    
            if XHSTTFileConstants.TIMES in constraint.keys():
                constraintTimes = set(constraint[XHSTTFileConstants.TIMES])
                for timeGroup in constraint[XHSTTFileConstants.TIME_GROUPS]:
                    if timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT] in self.instance.Times.TimeGroups.keys():
                        constraintTimes.update(set(self.instance.Times.TimeGroups[timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]].Times))
                    elif timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT] in self.instance.Times.Days.keys():
                        constraintTimes.update(set(self.instance.Times.Days[timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]].Times))
            else:
                constraintTimes = set()
            for resource in constraintResources:
                self.model.addConstr(gp.quicksum([self.variableDict["q"][resource, t] for t in constraintTimes]) ==
                                self.variableDict["s"][ILPConstants.AVOID_UNAVAILABLE_TIMES][constraint[XHSTTFileConstants.ID], resource], str(constraint[XHSTTFileConstants.ID]) + "_" +
                                str(resource) + "_unavailableTimes")
    
    
    def _add_limit_idle_times_constraints(self):
        resourcesWithDummyResource = [ILPConstants.DUMMY_RESOURCE] + list(self.instance.Resources.IndividualResources.keys())
    
        ordinalNumberOfResourceInTimeGroupDict = dict()
        ordinalNumberOfResourceInTimeGroupTimesDict = dict()
        for resource in resourcesWithDummyResource:
            for timeGroup in self.instance.Times.TimeGroups.keys():
                for t in self.instance.Times.TimeGroups[timeGroup].Times:
                    ordinalNumberOfResourceInTimeGroupTimesDict[resource, timeGroup, t] = 0
                ordinalNumberOfResourceInTimeGroupDict[resource, timeGroup] = 0
            for timeGroup in self.instance.Times.Days.keys():
                for t in self.instance.Times.Days[timeGroup].Times:
                    ordinalNumberOfResourceInTimeGroupTimesDict[resource, timeGroup, t] = 0
                ordinalNumberOfResourceInTimeGroupDict[resource, timeGroup] = 0
        h_times = self.model.addVars(ordinalNumberOfResourceInTimeGroupTimesDict.keys(), vtype=GRB.BINARY,
                                name="h_time", lb=0)
        h_times_before = self.model.addVars(ordinalNumberOfResourceInTimeGroupTimesDict.keys(), vtype=GRB.BINARY,
                                       name="h_time_before", lb=0)
        h_times_after = self.model.addVars(ordinalNumberOfResourceInTimeGroupTimesDict.keys(), vtype=GRB.BINARY,
                                       name="h_time_after", lb=0)
        h = self.model.addVars(ordinalNumberOfResourceInTimeGroupDict.keys(), vtype=GRB.INTEGER, name="h", lb=0)
    
        for constraint in self.instance.Constraints[XHSTTConstraintConstants.LIMIT_IDLE_TIMES_CONSTRAINT]:
            constraintResources = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCES])
            for resourceGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCE_GROUPS]:
                for resourceType in self.instance.Resources.ResourceGroupsByType.keys():
                    if resourceGroup in self.instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups:
                        constraintResources.update(
                            set(self.instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups[
                                    resourceGroup].Resources))
            idleVariableDict = dict()
            for resource in constraintResources:
                idleVariableDict[constraint[XHSTTFileConstants.ID], resource] = 0
    
            localM = len(self.instance.Times.IndividualTimes.keys()) - (len(self.instance.Times.Days) * 2) + 1
            idleVars = self.model.addVars(idleVariableDict.keys(), vtype=GRB.INTEGER, name="idleValue", lb=0)
            idleMin = self.model.addVars(idleVariableDict.keys(), vtype=GRB.BINARY, name="idleMin", lb=0)
            idleMax = self.model.addVars(idleVariableDict.keys(), vtype=GRB.BINARY, name="idleMax", lb=0)
    
            for resource in constraintResources:
                for timeGroupDict in constraint[XHSTTFileConstants.TIME_GROUPS]:
                    timeGroup = timeGroupDict[XHSTTFileConstants.REFERENCE_WITH_AT]
                    if timeGroup in self.instance.Times.TimeGroups.keys():
                        timeGroupLength = len(self.instance.Times.TimeGroups[timeGroup].Times)
                        timeGroupTimesList = self.instance.Times.TimeGroups[timeGroup].Times
                        for time_idx in range(timeGroupLength):
                            timeRef = self.instance.Times.TimeGroups[timeGroup].Times[time_idx]
                            for time2Ref in timeGroupTimesList[:time_idx]:
                                self.model.addConstr(
                                    self.variableDict["q"][resource, time2Ref] <= h_times_before[resource, timeGroup, timeRef],
                                str(resource) + "_" + str(timeGroup) + "_" + str(timeRef) + "_" + str(time2Ref) + "_linkBefore1")
    
                            self.model.addConstr(
                                gp.quicksum(self.variableDict["q"][resource, time2Ref] for time2Ref in timeGroupTimesList[:time_idx]) >=
                                h_times_before[resource, timeGroup, timeRef],
                            str(resource) + "_" + str(timeGroup) + "_" + str(timeRef) + "_linkBefore2")
    
                            for time2Ref in timeGroupTimesList[time_idx + 1:]:
                                self.model.addConstr(
                                    self.variableDict["q"][resource, time2Ref] <= h_times_after[resource, timeGroup, timeRef],
                                    str(resource) + "_" + str(timeGroup) + "_" + str(timeRef) + "_" + str(time2Ref) + "_linkAfter1")
    
                            self.model.addConstr(
                                gp.quicksum(self.variableDict["q"][resource, time2Ref] for time2Ref in timeGroupTimesList[time_idx + 1:]) >=
                                h_times_after[resource, timeGroup, timeRef],
                                str(resource) + "_" + str(timeGroup) + "_" + str(timeRef) + "_linkAfter2")
    
                            self.model.addConstr(
                                h_times_before[resource, timeGroup, timeRef] - self.variableDict["q"][resource, timeRef] +
                                h_times_after[resource, timeGroup, timeRef] - 1 <= h_times[resource, timeGroup, timeRef],
                                str(resource) + "_" + str(timeGroup) + "_" + str(timeRef) + "_linkHTimes"
                            )
    
                            self.model.addConstr(
                                -1 * self.variableDict["q"][resource, timeRef] + 1 >= h_times[resource, timeGroup, timeRef],
                                str(resource) + "_" + str(timeGroup) + "_" + str(timeRef) + "_notIdleIfActive")
    
                            self.model.addConstr(h_times_before[resource, timeGroup, timeRef]
                                            >= h_times[resource, timeGroup, timeRef],
                                            str(resource) + "_" + str(timeGroup) + "_" + str(
                                                timeRef) + "_notIdleIfNoPreviousActivity")
                            self.model.addConstr(h_times_after[resource, timeGroup, timeRef]
                                            >= h_times[resource, timeGroup, timeRef],
                                            str(resource) + "_" + str(timeGroup) + "_" + str(
                                                timeRef) + "_notIdleIfNoFollowingActivity")
    
                            self.model.addConstr(gp.quicksum([h_times[resource, timeGroup, t]
                                                         for t in self.instance.Times.TimeGroups[timeGroup].Times
                                                         if self.instance.Times.TimeGroups[timeGroup].Times.index(t) != 0 and
                                                         self.instance.Times.TimeGroups[timeGroup].Times.index(t) !=
                                                         timeGroupLength - 1]) ==
                                            h[resource, timeGroup], str(resource) + "_" + str(timeGroup) + "_linkH")
                    if timeGroup in self.instance.Times.Days.keys():
                        timeGroupLength = len(self.instance.Times.Days[timeGroup].Times)
                        timeGroupTimesList = self.instance.Times.Days[timeGroup].Times
                        for time_idx in range(timeGroupLength):
                            timeRef = self.instance.Times.Days[timeGroup].Times[time_idx]
                            self.model.addConstr(
                                gp.quicksum(self.variableDict["q"][resource, time2Ref] for time2Ref in timeGroupTimesList[:time_idx]) <=
                                h_times_before[resource, timeGroup, timeRef] * timeGroupLength,
                                str(resource) + "_" + str(timeGroup) + "_" + str(timeRef) + "_linkBefore1")
                            self.model.addConstr(
                                gp.quicksum(self.variableDict["q"][resource, time2Ref] for time2Ref in timeGroupTimesList[:time_idx]) >=
                                h_times_before[resource, timeGroup, timeRef],
                                str(resource) + "_" + str(timeGroup) + "_" + str(timeRef) + "_linkBefore2")
                            self.model.addConstr(
                                gp.quicksum(self.variableDict["q"][resource, time2Ref] for time2Ref in timeGroupTimesList[time_idx + 1:]) <=
                                h_times_after[resource, timeGroup, timeRef] * timeGroupLength,
                                str(resource) + "_" + str(timeGroup) + "_" + str(timeRef) + "_linkAfter1")
                            self.model.addConstr(
                                gp.quicksum(self.variableDict["q"][resource, time2Ref] for time2Ref in timeGroupTimesList[time_idx + 1:]) >=
                                h_times_after[resource, timeGroup, timeRef],
                                str(resource) + "_" + str(timeGroup) + "_" + str(timeRef) + "_linkAfter2")
                            self.model.addConstr(
                                h_times_before[resource, timeGroup, timeRef] - self.variableDict["q"][resource, timeRef] +
                                h_times_after[resource, timeGroup, timeRef] - 1 <= h_times[resource, timeGroup, timeRef],
                                str(resource) + "_" + str(timeGroup) + "_" + str(timeRef) + "_linkHTimes"
                            )
    
                            self.model.addConstr(
                                -1 * self.variableDict["q"][resource, timeRef] + 1 >= h_times[resource, timeGroup, timeRef],
                                str(resource) + "_" + str(timeGroup) + "_" + str(timeRef) + "_notIdleIfActive")
    
                            self.model.addConstr(h_times_before[resource, timeGroup, timeRef]
                                            >= h_times[resource, timeGroup, timeRef],
                                            str(resource) + "_" + str(timeGroup) + "_" + str(
                                                timeRef) + "_notIdleIfNoPreviousActivity")
                            self.model.addConstr(h_times_after[resource, timeGroup, timeRef]
                                            >= h_times[resource, timeGroup, timeRef],
                                            str(resource) + "_" + str(timeGroup) + "_" + str(
                                                timeRef) + "_notIdleIfNoFollowingActivity")
    
                            self.model.addConstr(gp.quicksum([h_times[resource, timeGroup, t]
                                                         for t in self.instance.Times.Days[timeGroup].Times
                                                         if self.instance.Times.Days[timeGroup].Times.index(t) != 0 and
                                                         self.instance.Times.Days[timeGroup].Times.index(t) !=
                                                         timeGroupLength - 1
                                                         ]) ==
                                            h[resource, timeGroup], str(resource) + "_" + str(timeGroup) + "_linkH")
    
    
            for resource in constraintResources:
                self.model.addConstr(idleVars[constraint[XHSTTFileConstants.ID], resource] == gp.quicksum([h[resource, tg[XHSTTFileConstants.REFERENCE_WITH_AT]]
                                                                                      for tg in constraint[XHSTTFileConstants.TIME_GROUPS]]),
                                str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_limitIdleVarsLink")

                self.model.addConstr(idleVars[constraint[XHSTTFileConstants.ID], resource] >=
                                int(constraint[XHSTTConstraintConstants.MAXIMUM]) + ILPConstants.EPS - localM *
                                (1 - idleMax[constraint[XHSTTFileConstants.ID], resource]),
                                str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_linkIdleVarsMax1")

                self.model.addConstr(idleVars[constraint[XHSTTFileConstants.ID], resource] <=
                                int(constraint[XHSTTConstraintConstants.MAXIMUM]) + localM *
                                (idleMax[constraint[XHSTTFileConstants.ID], resource]),
                                str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_linkIdleVarsMax2")

                self.model.addConstr(int(constraint[XHSTTConstraintConstants.MINIMUM]) >=
                                idleVars[constraint[XHSTTFileConstants.ID], resource] + ILPConstants.EPS - localM *
                                (1 - idleMin[constraint[XHSTTFileConstants.ID], resource]),
                                str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_linkIdleVarsMin1")

                self.model.addConstr(int(constraint[XHSTTConstraintConstants.MINIMUM]) <=
                                idleVars[constraint[XHSTTFileConstants.ID], resource] + localM *
                                (idleMin[constraint[XHSTTFileConstants.ID], resource]),
                                str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_linkIdleVarsMin2")

                self.model.addConstr((idleMax[constraint[XHSTTFileConstants.ID], resource] == 1) >>
                                (idleVars[constraint[XHSTTFileConstants.ID], resource] - int(constraint[XHSTTConstraintConstants.MAXIMUM]) ==
                    self.variableDict["s"][ILPConstants.IDLE_TIMES][constraint[XHSTTFileConstants.ID], resource]),
                    str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) +
                    "_idleTimesUpper")
                self.model.addConstr((idleMin[constraint[XHSTTFileConstants.ID], resource] == 1) >>
                                (int(constraint[XHSTTConstraintConstants.MINIMUM]) - idleVars[constraint[XHSTTFileConstants.ID], resource] ==
                    self.variableDict["s"][ILPConstants.IDLE_TIMES][constraint[XHSTTFileConstants.ID], resource]),
                    str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) +
                    "_idleTimesLower")
    
    def _add_cluster_busy_times_constraints(self):
    
        for constraint in self.instance.Constraints[XHSTTConstraintConstants.CLUSTER_BUSY_TIMES_CONSTRAINT]:
            constraintResources = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCES])
            for resourceGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCE_GROUPS]:
                for resourceType in self.instance.Resources.ResourceGroupsByType.keys():
                    if resourceGroup in self.instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups:
                        constraintResources.update(
                            set(self.instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups[
                                    resourceGroup].Resources))
    
            clusterBusyVariableDict = dict()
            for resource in constraintResources:
                clusterBusyVariableDict[constraint[XHSTTFileConstants.ID], resource] = 0
    
            localM = max(len(constraint[XHSTTFileConstants.TIME_GROUPS]), int(constraint[XHSTTConstraintConstants.MAXIMUM]), int(constraint[XHSTTConstraintConstants.MINIMUM])) + 1
            clusterBusyVars = self.model.addVars(clusterBusyVariableDict.keys(), vtype=GRB.INTEGER, name="clusterBusyValue", lb=0)
            clusterBusyVarsMin = self.model.addVars(clusterBusyVariableDict.keys(), vtype=GRB.BINARY, name="clusterBusyMin", lb=0)
            clusterBusyVarsMax = self.model.addVars(clusterBusyVariableDict.keys(), vtype=GRB.BINARY, name="clusterBusyMax", lb=0)
    
            for resource in constraintResources:
                self.model.addConstr(clusterBusyVars[constraint[XHSTTFileConstants.ID], resource] ==
                                gp.quicksum([self.variableDict["p"][resource, tg[XHSTTFileConstants.REFERENCE_WITH_AT]] for tg in constraint[XHSTTFileConstants.TIME_GROUPS]]),
                                str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_limitClusterBusyLink")
    
                self.model.addConstr(clusterBusyVars[constraint[XHSTTFileConstants.ID], resource] >=
                                int(constraint[XHSTTConstraintConstants.MAXIMUM]) + ILPConstants.EPS - localM *
                                (1 - clusterBusyVarsMax[constraint[XHSTTFileConstants.ID], resource]),
                                str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_linkClusterBusyMax1")
    
                self.model.addConstr(clusterBusyVars[constraint[XHSTTFileConstants.ID], resource] <=
                                int(constraint[XHSTTConstraintConstants.MAXIMUM]) + localM *
                                (clusterBusyVarsMax[constraint[XHSTTFileConstants.ID], resource]),
                                str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_linkClusterBusyMax2")
    
                self.model.addConstr(int(constraint[XHSTTConstraintConstants.MINIMUM]) >=
                                clusterBusyVars[constraint[XHSTTFileConstants.ID], resource] + ILPConstants.EPS - localM *
                                (1 - clusterBusyVarsMin[constraint[XHSTTFileConstants.ID], resource]),
                                str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_linkClusterBusyMin1")
    
                self.model.addConstr(int(constraint[XHSTTConstraintConstants.MINIMUM]) <=
                                clusterBusyVars[constraint[XHSTTFileConstants.ID], resource] + localM *
                                (clusterBusyVarsMin[constraint[XHSTTFileConstants.ID], resource]),
                                str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_linkClusterBusyMin2")
    
                self.model.addConstr((clusterBusyVarsMax[constraint[XHSTTFileConstants.ID], resource] == 1) >>
                                (clusterBusyVars[constraint[XHSTTFileConstants.ID], resource] - int(constraint[XHSTTConstraintConstants.MAXIMUM]) ==
                    self.variableDict["s"][ILPConstants.CLUSTER_BUSY][constraint[XHSTTFileConstants.ID], resource]), str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) +
                    "_clusterBusyUpper")
                self.model.addConstr((clusterBusyVarsMin[constraint[XHSTTFileConstants.ID], resource] == 1) >>
                                (int(constraint[XHSTTConstraintConstants.MINIMUM]) - clusterBusyVars[constraint[XHSTTFileConstants.ID], resource] ==
                    self.variableDict["s"][ILPConstants.CLUSTER_BUSY][constraint[XHSTTFileConstants.ID], resource]), str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) +
                    "_clusterBusyLower")
    
    def _add_limit_busy_times_constraints(self):
        limitBusyVariableDict = dict()
        for constraint in self.instance.Constraints[XHSTTConstraintConstants.LIMIT_BUSY_TIMES_CONSTRAINT]:
            constraintResources = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCES])
            for resourceGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCE_GROUPS]:
                for resourceType in self.instance.Resources.ResourceGroupsByType.keys():
                    if resourceGroup in self.instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups:
                        constraintResources.update(
                            set(self.instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups[
                                    resourceGroup].Resources))
    
            for resource in constraintResources:
                for timeGroup in constraint[XHSTTFileConstants.TIME_GROUPS]:
                    if timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT] in self.instance.Times.TimeGroups.keys():
                        limitBusyVariableDict[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] = 0
                    if timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT] in self.instance.Times.Days.keys():
                        limitBusyVariableDict[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] = 0

        limitBusyVars = self.model.addVars(limitBusyVariableDict, vtype=GRB.INTEGER, name="busyTimesValues", lb=0)
        limitBusyVarsLocalDeviation = self.model.addVars(limitBusyVariableDict, vtype=GRB.INTEGER, name="busyTimesLocalDeviation", lb=0)
        limitBusyVarsMin = self.model.addVars(limitBusyVariableDict, vtype=GRB.BINARY, name="busyTimesMin", lb=0)
        limitBusyVarsMinIndicator = self.model.addVars(limitBusyVariableDict, vtype=GRB.BINARY, name="busyTimesMinIndicator", lb=0)
        limitBusyVarsMax = self.model.addVars(limitBusyVariableDict, vtype=GRB.BINARY, name="busyTimesMax", lb=0)
        limitBusyVarsMaxIndicator = self.model.addVars(limitBusyVariableDict, vtype=GRB.BINARY, name="busyTimesMaxIndicator",
                                                  lb=0)
        limitBusyVarsZeroIndicator = self.model.addVars(limitBusyVariableDict, vtype=GRB.BINARY, name="busyTimesZeroIndicator",
                                                  lb=0)
    
        for constraint in self.instance.Constraints[XHSTTConstraintConstants.LIMIT_BUSY_TIMES_CONSTRAINT]:
            localM = max(len(self.instance.Times.IndividualTimes.keys()),
                         int(constraint[XHSTTConstraintConstants.MAXIMUM]),
                         int(constraint[XHSTTConstraintConstants.MINIMUM])) + 1
            constraintResources = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCES])
            for resourceGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCE_GROUPS]:
                for resourceType in self.instance.Resources.ResourceGroupsByType.keys():
                    if resourceGroup in self.instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups:
                        constraintResources.update(
                            set(self.instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups[
                                    resourceGroup].Resources))
    
            for resource in constraintResources:
                for timeGroup in constraint[XHSTTFileConstants.TIME_GROUPS]:
                    if timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT] in self.instance.Times.TimeGroups.keys():
    
                        self.model.addConstr(limitBusyVars[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] ==
                                        gp.quicksum([self.variableDict["q"][resource, t]
                                                     for t in self.instance.Times.TimeGroups[timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]].Times]),
                                        str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_" + str(timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]) +
                                        "_limitBusyValue")
    
                        self.model.addConstr(limitBusyVars[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] >=
                                        int(constraint[XHSTTConstraintConstants.MAXIMUM]) + ILPConstants.EPS - localM *
                                        (1 - limitBusyVarsMax[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]]),
                                        str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_" + str(timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]) + "_linkLimitBusyMax1")
    
                        self.model.addConstr(limitBusyVars[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] <=
                                        int(constraint[XHSTTConstraintConstants.MAXIMUM]) + localM *
                                        (limitBusyVarsMax[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]]),
                                        str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_" + str(timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]) + "_linkLimitBusyMax2")
    
                        self.model.addConstr(limitBusyVarsMax[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] +
                                        self.variableDict["p"][resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] - 1 <=
                                        limitBusyVarsMaxIndicator[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]],
                                        str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_" + str(
                                            timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]) + "_linkLimitBusyMax3")
    
                        self.model.addConstr(limitBusyVarsMax[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] +
                                        self.variableDict["p"][resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] >=
                                        limitBusyVarsMaxIndicator[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] * 2,
                                        str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_" + str(
                                            timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]) + "_linkLimitBusyMax4")
    
                        self.model.addConstr(int(constraint[XHSTTConstraintConstants.MINIMUM]) >=
                                        limitBusyVars[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] + ILPConstants.EPS - localM *
                                        (1 - limitBusyVarsMin[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]]),
                                        str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_" + str(timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]) + "_linkLimitBusyMin1")
    
                        self.model.addConstr(int(constraint[XHSTTConstraintConstants.MINIMUM]) <=
                                        limitBusyVars[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] + localM *
                                        (limitBusyVarsMin[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]]),
                                        str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_" + str(timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]) + "_linkLimitBusyMin2")
    
                        self.model.addConstr(limitBusyVarsMin[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] +
                                        self.variableDict["p"][resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] - 1 <=
                                        limitBusyVarsMinIndicator[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]],
                                        str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_" + str(timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]) + "_linkLimitBusyMin3")
    
                        self.model.addConstr(limitBusyVarsMin[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] +
                                        self.variableDict["p"][resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] >=
                                        limitBusyVarsMinIndicator[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] * 2,
                                        str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_" + str(
                                            timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]) + "_linkLimitBusyMin4")
    
                        self.model.addConstr((1 - limitBusyVarsMaxIndicator[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]]) +
                                        (1 - limitBusyVarsMinIndicator[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]]) - 1 <=
                                        limitBusyVarsZeroIndicator[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]],
                                        str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_" + str(
                                            timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]) + "_linkLimitBusyZero2")
    
                        self.model.addConstr((1 - limitBusyVarsMaxIndicator[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]]) +
                                        (1 - limitBusyVarsMinIndicator[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]]) >=
                                        limitBusyVarsZeroIndicator[
                                            constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] * 2,
                                        str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_" + str(
                                            timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]) + "_linkLimitBusyZero1")
    
                        self.model.addConstr((limitBusyVarsZeroIndicator[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] == 1) >>
                                        (limitBusyVarsLocalDeviation[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] == 0),
                                        str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_" + str(timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]) +
                                        "_limitBusyZero")
                        self.model.addConstr((limitBusyVarsMaxIndicator[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] == 1) >>
                                        (limitBusyVars[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] -
                                        int(constraint[XHSTTConstraintConstants.MAXIMUM]) ==
                                        limitBusyVarsLocalDeviation[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]]),
                                        str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_" + str(timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]) +
                                        "_limitBusyLower")
                        self.model.addConstr((limitBusyVarsMinIndicator[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] == 1) >>
                                        (int(constraint[XHSTTConstraintConstants.MINIMUM]) - limitBusyVars[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]]
                                         == limitBusyVarsLocalDeviation[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]]),
                                        str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_" + str(timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]) + "_limitBusyUpper")
                    if timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT] in self.instance.Times.Days.keys():
                        self.model.addConstr(limitBusyVars[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] ==
                                        gp.quicksum([self.variableDict["q"][resource, t]
                                                     for t in self.instance.Times.Days[timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]].Times]),
                                        str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_" + str(timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]) +
                                        "_limitBusyValue")
    
                        self.model.addConstr(limitBusyVars[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] >=
                                        int(constraint[XHSTTConstraintConstants.MAXIMUM]) + ILPConstants.EPS - localM *
                                        (1 - limitBusyVarsMax[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]]),
                                        str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_" + str(
                                            timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]) + "_linkLimitBusyMax1")
    
                        self.model.addConstr(limitBusyVars[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] <=
                                        int(constraint[XHSTTConstraintConstants.MAXIMUM]) + localM *
                                        (limitBusyVarsMax[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]]),
                                        str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_" + str(
                                            timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]) + "_linkLimitBusyMax2")
    
                        self.model.addConstr(limitBusyVarsMax[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] +
                                        self.variableDict["p"][resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] - 1 <=
                                        limitBusyVarsMaxIndicator[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]],
                                        str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_" + str(
                                            timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]) + "_linkLimitBusyMax3")
    
                        self.model.addConstr(limitBusyVarsMax[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] +
                                        self.variableDict["p"][resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] >=
                                        limitBusyVarsMaxIndicator[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] * 2,
                                        str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_" + str(
                                            timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]) + "_linkLimitBusyMax4")
    
                        self.model.addConstr(int(constraint[XHSTTConstraintConstants.MINIMUM]) >=
                                        limitBusyVars[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] + ILPConstants.EPS - localM *
                                        (1 - limitBusyVarsMin[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]]),
                                        str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_" + str(
                                            timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]) + "_linkLimitBusyMin1")
    
                        self.model.addConstr(int(constraint[XHSTTConstraintConstants.MINIMUM]) <=
                                        limitBusyVars[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] + localM *
                                        (limitBusyVarsMin[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]]),
                                        str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_" + str(
                                            timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]) + "_linkLimitBusyMin2")
    
                        self.model.addConstr(limitBusyVarsMin[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] +
                                        self.variableDict["p"][resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] - 1 <=
                                        limitBusyVarsMinIndicator[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]],
                                        str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_" + str(
                                            timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]) + "_linkLimitBusyMin3")
    
                        self.model.addConstr(limitBusyVarsMin[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] +
                                        self.variableDict["p"][resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] >=
                                        limitBusyVarsMinIndicator[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] * 2,
                                        str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_" + str(
                                            timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]) + "_linkLimitBusyMin4")
    
                        self.model.addConstr(
                            (1 - limitBusyVarsMaxIndicator[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]]) +
                            (1 - limitBusyVarsMinIndicator[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]]) - 1 <=
                            limitBusyVarsZeroIndicator[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]],
                            str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_" + str(
                                timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]) + "_linkLimitBusyZero2")
    
                        self.model.addConstr(
                            (1 - limitBusyVarsMaxIndicator[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]]) +
                            (1 - limitBusyVarsMinIndicator[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]]) >=
                            limitBusyVarsZeroIndicator[
                                constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] * 2,
                            str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_" + str(
                                timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]) + "_linkLimitBusyZero1")
    
                        self.model.addConstr(
                            (limitBusyVarsZeroIndicator[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] == 1) >>
                            (limitBusyVarsLocalDeviation[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] == 0),
                            str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_" + str(timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]) +
                            "_limitBusyZero")
    
                        self.model.addConstr((limitBusyVarsMaxIndicator[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] == 1) >>
                                        (limitBusyVars[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] -
                                        int(constraint[XHSTTConstraintConstants.MAXIMUM]) ==
                                         limitBusyVarsLocalDeviation[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]]),
                                        str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_" + str(timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]) + "_limitBusyLower")
                        self.model.addConstr((limitBusyVarsMinIndicator[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]] == 1) >>
                                        (int(constraint[XHSTTConstraintConstants.MINIMUM]) - limitBusyVars[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]]
                                        == limitBusyVarsLocalDeviation[constraint[XHSTTFileConstants.ID], resource, timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]]),
                                        str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_" + str(timeGroup[XHSTTFileConstants.REFERENCE_WITH_AT]) + "_limitBusyUpper")
                self.model.addConstr(gp.quicksum([limitBusyVarsLocalDeviation[constraint[XHSTTFileConstants.ID], resource, tg[XHSTTFileConstants.REFERENCE_WITH_AT]]
                                             for tg in constraint[XHSTTFileConstants.TIME_GROUPS]]) ==
                                self.variableDict["s"][ILPConstants.LIMIT_BUSY][constraint[XHSTTFileConstants.ID], resource],
                                str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_limitBusyLinkToDeviation")
    
    def _add_limit_workload_constraints(self):
        events = list(self.instance.Events.IndividualEvents.keys())
        timesWithDummyTime = list(self.instance.Times.IndividualTimes.keys()) + [ILPConstants.DUMMY_TIME]
    
        for constraint in self.instance.Constraints[XHSTTConstraintConstants.LIMIT_WORKLOAD_CONSTRAINT]:
            constraintResources = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCES])
            for resourceGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCE_GROUPS]:
                for resourceType in self.instance.Resources.ResourceGroupsByType.keys():
                    if resourceGroup in self.instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups:
                        constraintResources.update(
                            set(self.instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups[
                                    resourceGroup].Resources))
    
            workloadVariableDict = dict()
            for resource in constraintResources:
                workloadVariableDict[constraint[XHSTTFileConstants.ID], resource] = 0
    
            localM = max(len(self.instance.Times.IndividualTimes.keys()), int(constraint[XHSTTConstraintConstants.MAXIMUM]), int(constraint[XHSTTConstraintConstants.MINIMUM])) * 2
            worklaodVars = self.model.addVars(workloadVariableDict.keys(), vtype=GRB.INTEGER, name="workloadValue", lb=0)
            worklaodVarsMin = self.model.addVars(workloadVariableDict.keys(), vtype=GRB.BINARY, name="workloadMin", lb=0)
            worklaodVarsMax = self.model.addVars(workloadVariableDict.keys(), vtype=GRB.BINARY, name="workloadMax", lb=0)
            for resource in constraintResources:
    
                self.model.addConstr(worklaodVars[constraint[XHSTTFileConstants.ID], resource] ==
                                gp.quicksum([(se[0] * float(er.Workload) / float(
                                    self.instance.Events.IndividualEvents[e].Duration)) * self.variableDict["x"][
                                                 e, se, t, er.Role, resource] for e in events for se in self.eventToSubEventListDict[e]
                                             for er in
                                             list(self.instance.Events.IndividualEvents[e].EventResources.AssignedResources) +
                                             list(self.instance.Events.IndividualEvents[e].EventResources.UnassignedResources)
                                             for t in timesWithDummyTime if
                                             (e, se, t, er.Role, resource) in self.variableDict["x"].keys()
                                             if er.Workload is not None]) +
                                gp.quicksum([se[0] * self.variableDict["x"][
                                    e, se, t, er.Role, resource] for e in events for se in self.eventToSubEventListDict[e]
                                             for er in
                                             list(self.instance.Events.IndividualEvents[e].EventResources.AssignedResources) +
                                             list(self.instance.Events.IndividualEvents[e].EventResources.UnassignedResources)
                                             for t in timesWithDummyTime if
                                             (e, se, t, er.Role, resource) in self.variableDict["x"].keys()
                                             if er.Workload is None]),
                                str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_limitWorkloadLink")
    
                self.model.addConstr(worklaodVars[constraint[XHSTTFileConstants.ID], resource] >=
                                int(constraint[XHSTTConstraintConstants.MAXIMUM]) + ILPConstants.EPS - localM *
                                (1 - worklaodVarsMax[constraint[XHSTTFileConstants.ID], resource]),
                                str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_linkWorkloadMax1")
    
                self.model.addConstr(worklaodVars[constraint[XHSTTFileConstants.ID], resource] <=
                                int(constraint[XHSTTConstraintConstants.MAXIMUM]) + localM *
                                (worklaodVarsMax[constraint[XHSTTFileConstants.ID], resource]),
                                str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_linkWorkloadMax2")
    
                self.model.addConstr(int(constraint[XHSTTConstraintConstants.MINIMUM]) >=
                                worklaodVars[constraint[XHSTTFileConstants.ID], resource] + ILPConstants.EPS - localM *
                                (1 - worklaodVarsMin[constraint[XHSTTFileConstants.ID], resource]),
                                str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_linkWorkloadMin1")
    
                self.model.addConstr(int(constraint[XHSTTConstraintConstants.MINIMUM]) <=
                                worklaodVars[constraint[XHSTTFileConstants.ID], resource] + localM *
                                (worklaodVarsMin[constraint[XHSTTFileConstants.ID], resource]),
                                str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_linkWorkloadMin2")
    
                self.model.addConstr((worklaodVarsMax[constraint[XHSTTFileConstants.ID], resource] == 1) >>
                    (worklaodVars[constraint[XHSTTFileConstants.ID], resource] - float(constraint[XHSTTConstraintConstants.MAXIMUM]) ==
                    self.variableDict["s"][ILPConstants.LIMIT_WORKLOAD][constraint[XHSTTFileConstants.ID], resource]), str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) +
                    "_limitWorkloadUpper")
                self.model.addConstr((worklaodVarsMin[constraint[XHSTTFileConstants.ID], resource] == 1) >>
                    (float(constraint[XHSTTConstraintConstants.MINIMUM]) - worklaodVars[constraint[XHSTTFileConstants.ID], resource]
                    ==
                    self.variableDict["s"][ILPConstants.LIMIT_WORKLOAD][constraint[XHSTTFileConstants.ID], resource]), str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) +
                    "_limitWorkloadLower")
    
    def _add_balance_class_size_constraints(self):
        resourcesWithoutDummyResource = self.instance.Resources.IndividualResources.keys()
        if XHSTTConstraintConstants.BALANCE_CLASS_SIZE_CONSTRAINT not in self.instance.Constraints.keys():
            return
        for constraint in self.instance.Constraints[XHSTTConstraintConstants.BALANCE_CLASS_SIZE_CONSTRAINT]:
            consideredEventGroups = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENT_GROUPS])
            resourceAssignmentsPerEventGroupDict = dict()
            for eventGroup in consideredEventGroups:
                resourceAssignmentsPerEventGroupDict[constraint[XHSTTFileConstants.ID], eventGroup] = 0
    
            mr = self.model.addVars(resourceAssignmentsPerEventGroupDict.keys(), vtype=GRB.INTEGER, name="mr", lb=0)
            maxResources = 0
            for eventGroup in consideredEventGroups:
                totalResourcesOfConsideredTypeInEventGroup = 0
                for event in self.instance.Events.EventGroups[eventGroup].Events:
                    eventResources = self.instance.Events.IndividualEvents[event].EventResources.UnassignedResources + self.instance.Events.IndividualEvents[event].EventResources.AssignedResources
                    totalResourcesOfConsideredTypeInEventGroup += len([resource for resource in eventResources if resource.ResourceType == constraint[XHSTTConstraintConstants.TYPE]])
                maxResources = max(maxResources, totalResourcesOfConsideredTypeInEventGroup)
                self.model.addConstr(gp.quicksum([self.variableDict["c"][eventGroup, r]
                                             for r in resourcesWithoutDummyResource
                                             if (eventGroup, r) in self.variableDict["c"].keys() and
                                                  (XHSTTConstraintConstants.TYPE not in constraint.keys() or
                                                   constraint[XHSTTConstraintConstants.TYPE] is None or
                                                   self.instance.Resources.IndividualResources[r].Type ==
                                                   constraint[XHSTTConstraintConstants.TYPE])]) == mr[constraint[XHSTTFileConstants.ID], eventGroup],
                                str(constraint[XHSTTFileConstants.ID]) + "_" + str(eventGroup) + "_link_mr")
    
    
            balanceClassVariableDict = dict()
            balanceClassCombinationVariableDict = dict()
            for eventGroup1 in consideredEventGroups:
                balanceClassVariableDict[constraint[XHSTTFileConstants.ID], eventGroup1] = 0
                for eventGroup2 in consideredEventGroups:
                    balanceClassCombinationVariableDict[constraint[XHSTTFileConstants.ID], eventGroup1, eventGroup2] = 0

            localM = max(maxResources, int(constraint['MaximumDifference'])) + 1
            balanceClassVars = self.model.addVars(balanceClassVariableDict.keys(), vtype=GRB.INTEGER, name="balanceClassValue", lb=0)
            balanceClassBiggerMaxDifIndicator = self.model.addVars(balanceClassVariableDict.keys(), vtype=GRB.BINARY,
                                                              name="balanceClassValueMaxDif", lb=0)
            balanceClassCombinationVars1 = self.model.addVars(balanceClassCombinationVariableDict.keys(), vtype=GRB.INTEGER, name="balanceClassCombinationValue1", lb=-100)
            balanceClassCombinationVars2 = self.model.addVars(balanceClassCombinationVariableDict.keys(), vtype=GRB.INTEGER, name="balanceClassCombinationValue2", lb=-100)


            for eventGroup1 in consideredEventGroups:
                for eventGroup2 in consideredEventGroups:
                    self.model.addConstr(balanceClassCombinationVars1[constraint[XHSTTFileConstants.ID], eventGroup1, eventGroup2] ==
                                    mr[constraint[XHSTTFileConstants.ID], eventGroup1] - mr[constraint[XHSTTFileConstants.ID], eventGroup2], str(constraint[XHSTTFileConstants.ID]) +
                                    "_" + str(eventGroup1) + "_" + str(eventGroup2) + "_linkBalanceClassSizeValues1")
                    self.model.addConstr(balanceClassCombinationVars2[constraint[XHSTTFileConstants.ID], eventGroup1, eventGroup2] ==
                                    mr[constraint[XHSTTFileConstants.ID], eventGroup2] - mr[constraint[XHSTTFileConstants.ID], eventGroup1], str(constraint[XHSTTFileConstants.ID]) +
                                    "_" + str(eventGroup1) + "_" + str(eventGroup2) + "_linkBalanceClassSizeValues2")
                self.model.addConstr(balanceClassVars[constraint[XHSTTFileConstants.ID], eventGroup1] == gp.max_(
                    [balanceClassCombinationVars1[constraint[XHSTTFileConstants.ID], eventGroup1, eg2] for eg2 in consideredEventGroups] +
                [balanceClassCombinationVars2[constraint[XHSTTFileConstants.ID], eventGroup1, eg2] for eg2 in consideredEventGroups]),
                                str(constraint[XHSTTFileConstants.ID]) + "_" + str(eventGroup1) + "_linkBalanceClassSizeMaxValues")

                self.model.addConstr(balanceClassVars[constraint[XHSTTFileConstants.ID], eventGroup1] >=
                                int(constraint['MaximumDifference']) + ILPConstants.EPS - localM *
                                (1 - balanceClassBiggerMaxDifIndicator[constraint[XHSTTFileConstants.ID], eventGroup1]),
                                str(constraint[XHSTTFileConstants.ID]) + "_" + str(eventGroup1) + "_balanceClassSizeIndicator1")

                self.model.addConstr(balanceClassVars[constraint[XHSTTFileConstants.ID], eventGroup1] <=
                                int(constraint['MaximumDifference']) + localM *
                                balanceClassBiggerMaxDifIndicator[constraint[XHSTTFileConstants.ID], eventGroup1],
                                str(constraint[XHSTTFileConstants.ID]) + "_" + str(eventGroup1) + "_balanceClassSizeIndicator2")
    
                self.model.addConstr((balanceClassBiggerMaxDifIndicator[constraint[XHSTTFileConstants.ID], eventGroup1] == 1) >>
                                (balanceClassVars[constraint[XHSTTFileConstants.ID], eventGroup1] - int(constraint['MaximumDifference']) ==
                                self.variableDict["s"][ILPConstants.BALANCE_CLASS][constraint[XHSTTFileConstants.ID], eventGroup1]),
                                str(constraint[XHSTTFileConstants.ID]) + "_" + str(eventGroup1) + "_balanceClassSize")

                self.model.addConstr((balanceClassBiggerMaxDifIndicator[constraint[XHSTTFileConstants.ID], eventGroup1] == 0) >>
                                (0 == self.variableDict["s"][ILPConstants.BALANCE_CLASS][constraint[XHSTTFileConstants.ID], eventGroup1]),
                                str(constraint[XHSTTFileConstants.ID]) + "_" + str(eventGroup1) + "_balanceClassSize")
    
    def _add_student_choice_constraints(self):
        if XHSTTConstraintConstants.STUDENT_CHOICE_CONSTRAINT not in self.instance.Constraints.keys():
            return
        for constraint in self.instance.Constraints[XHSTTConstraintConstants.STUDENT_CHOICE_CONSTRAINT]:
            consideredEventGroups = set(constraint[XHSTTFileConstants.EVENT_GROUPS])
            consideredResources = set(constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCES])
            for resourceGroup in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.RESOURCE_GROUPS]:
                for resourceType in self.instance.Resources.ResourceGroupsByType.keys():
                    if resourceGroup in self.instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups:
                        consideredResources.update(set(
                            self.instance.Resources.ResourceGroupsByType[resourceType].ResourceGroups[
                                resourceGroup].Resources))
    
            studentChoiceVariableDict = dict()
            for resource in consideredResources:
                studentChoiceVariableDict[constraint[XHSTTFileConstants.ID], resource] = 0
    
            localM = max(len(consideredEventGroups), int(constraint[XHSTTConstraintConstants.MINIMUM]), int(constraint[XHSTTConstraintConstants.MAXIMUM])) + 1
            studentChoiceVars = self.model.addVars(studentChoiceVariableDict.keys(), vtype=GRB.INTEGER, name="studentChoiceValue", lb=0)
            studentChoiceVarsMin = self.model.addVars(studentChoiceVariableDict.keys(), vtype=GRB.BINARY, name="studentChoiceMin", lb=0)
            studentChoiceVarsMax = self.model.addVars(studentChoiceVariableDict.keys(), vtype=GRB.BINARY, name="studentChoiceMax", lb=0)

            for resource in consideredResources:
                self.model.addConstr(studentChoiceVars[constraint[XHSTTFileConstants.ID], resource] ==
                                gp.quicksum([self.variableDict["c"][eg, resource] for eg in consideredEventGroups if (eg, resource) in self.variableDict["c"].keys()]),
                                str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_studentChoiceLink")
    
                self.model.addConstr(studentChoiceVars[constraint[XHSTTFileConstants.ID], resource] >=
                                int(constraint[XHSTTConstraintConstants.MAXIMUM]) + ILPConstants.EPS - localM *
                                (1 - studentChoiceVarsMax[constraint[XHSTTFileConstants.ID], resource]),
                                str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_linkStudentChoiceMax1")
    
                self.model.addConstr(studentChoiceVars[constraint[XHSTTFileConstants.ID], resource] <=
                                int(constraint[XHSTTConstraintConstants.MAXIMUM]) + localM *
                                (studentChoiceVarsMax[constraint[XHSTTFileConstants.ID], resource]),
                                str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_linkStudentChoiceMax2")
    
                self.model.addConstr(int(constraint[XHSTTConstraintConstants.MINIMUM]) >=
                                studentChoiceVars[constraint[XHSTTFileConstants.ID], resource] + ILPConstants.EPS - localM *
                                (1 - studentChoiceVarsMin[constraint[XHSTTFileConstants.ID], resource]),
                                str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_linkStudentChoiceMin1")
    
                self.model.addConstr(int(constraint[XHSTTConstraintConstants.MINIMUM]) <=
                                studentChoiceVars[constraint[XHSTTFileConstants.ID], resource] + localM *
                                (studentChoiceVarsMin[constraint[XHSTTFileConstants.ID], resource]),
                                str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_linkStudentChoiceMin2")

    
    
                self.model.addConstr((studentChoiceVarsMax[constraint[XHSTTFileConstants.ID], resource] == 1) >>
                                (studentChoiceVars[constraint[XHSTTFileConstants.ID], resource] - int(constraint[XHSTTConstraintConstants.MAXIMUM]) ==
                                self.variableDict["s"][ILPConstants.STUDENT_CHOICE][constraint[XHSTTFileConstants.ID], resource]),
                                str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_studentChoice")
                self.model.addConstr((studentChoiceVarsMin[constraint[XHSTTFileConstants.ID], resource] == 1) >>
                                (int(constraint[XHSTTConstraintConstants.MINIMUM]) - studentChoiceVars[constraint[XHSTTFileConstants.ID], resource] ==
                                self.variableDict["s"][ILPConstants.STUDENT_CHOICE][constraint[XHSTTFileConstants.ID], resource]),
                                str(constraint[XHSTTFileConstants.ID]) + "_" + str(resource) + "_studentChoice")
    
    
    def _get_possible_start_times_of_event_running_at_duration_t(self, timeID, eventDuration):
        listOfTimes = list(self.instance.Times.IndividualTimes.keys())
        indexOfTime = listOfTimes.index(timeID)
        return listOfTimes[max(0, indexOfTime-eventDuration + 1):indexOfTime + 1]
    
    def _get_eventResources_of_event_that_contain_resource(self, event, resource):
        eventResourcesThatContainResource = list()
        eventResources = (self.instance.Events.IndividualEvents[event].EventResources.AssignedResources +
                          self.instance.Events.IndividualEvents[event].EventResources.UnassignedResources)
        for eventResource in eventResources:
            if resource in self.eventResourceToPossibleResourcesDict[event, eventResource.Role]:
                eventResourcesThatContainResource.append(eventResource.Role)
        return eventResourcesThatContainResource
    
    def _create_solution_events_dict(self, outputDeviations: bool = True) -> dict:
        solutionEvents = dict()
        deviationsDict = dict()
        individualResources = set(self.instance.Resources.IndividualResources.keys())
        individualResources.add(ILPConstants.DUMMY_RESOURCE)
        solutionEvents[SolutionDataConstants.INSTANCE_ID] = self.instance.Metadata[XHSTTFileConstants.FILE_ID]
        solutionEvents[XHSTTFileConstants.FILE_NAME] = self.instance.Metadata[XHSTTFileConstants.FILE_NAME]
        solutionEvents[SolutionDataConstants.DESCRIPTION] = "Objective Value: {:.5f}".format(self.model.ObjVal)
        solutionEvents[SolutionDataConstants.RUNNING_TIME] = str(self.model.Runtime)
        solutionEvents[SolutionDataConstants.ID] = self.instance.Metadata[XHSTTFileConstants.FILE_ID]
        solutionEvents[SolutionDataConstants.SORTED_TIMES] = list(self.instance.Times.IndividualTimes.keys())
        solutionEvents[XHSTTFileConstants.EVENTS] = dict()
        solutionEvents[SolutionDataConstants.OBJECTIVE_VALUE] = float(self.model.ObjVal)
        constraintIdToConstraintDict = dict()
        for constraintType in self.instance.Constraints.keys():
            for constraint in self.instance.Constraints[constraintType]:
                constraintIdToConstraintDict[constraint[XHSTTFileConstants.ID]] = constraint
        if self.model.SolCount > 0:
            all_vars = self.model.getVars()
            values = self.model.getAttr('X', all_vars)
            names = self.model.getAttr('VarName', all_vars)
            non_zero_variables = [(names[i], round(values[i])) for i in range(len(values)) if round(values[i]) > 0]
            for v in non_zero_variables:
                if str(v[0]).startswith("x") and int(v[1]) > 0:
                    variable_key = str(v[0]).split('[')[1][:-1]
                    if len(variable_key.split('(')) == 2:
                        event = variable_key.split('(')[0][:-1]
                        subeventIndexDurationPair = variable_key.split('(')[1].split(')')[0]
                        subeventIndexDurationPair = subeventIndexDurationPair.replace(" ", "")
                        subevent = (int(subeventIndexDurationPair.split(',')[0]), int(subeventIndexDurationPair.split(',')[1]))
                        starttime = variable_key.split(')')[1].split(',')[1]
                        eventResourceRole = variable_key.split(')')[1].split(',')[2]
                        if variable_key.split(')')[-1] == '' or variable_key.split(')')[-1] == ' ':
                            resource = variable_key.split(')')[1].split(',')[3] + ')'
                        else:
                            resource = variable_key.split(')')[1].split(',')[3]
                    else:
                        if len(variable_key.split('(')[-1]) < len(variable_key.split(',')[-1]):
                            event = variable_key.split('(')[0][:-1]
                            subeventIndexDurationPair = variable_key.split('(')[1].split(')')[0]
                            subeventIndexDurationPair = subeventIndexDurationPair.replace(" ", "")
                            subevent = (
                            int(subeventIndexDurationPair.split(',')[0]), int(subeventIndexDurationPair.split(',')[1]))
                            starttime = variable_key.split(')')[1].split(',')[1]
                            eventResourceRole = variable_key.split(')')[1].split(',')[2]
                            if variable_key.split(')')[-1] == '' or variable_key.split(')')[-1] == ' ':
                                resource = variable_key.split(')')[1].split(',')[3] + ')'
                            else:
                                resource = variable_key.split(')')[1].split(',')[3]
                        else:
                            event = variable_key.split('(')[0] + "(" + variable_key.split('(')[1][:-1]
                            subeventIndexDurationPair = variable_key.split('(')[2].split(')')[0]
                            subeventIndexDurationPair = subeventIndexDurationPair.replace(" ", "")
                            try:
                                subevent = (int(subeventIndexDurationPair.split(',')[0]), int(subeventIndexDurationPair.split(',')[1]))
                            except:
                                raise ValueError(f"Error with splitting {variable_key}")
                            starttime = variable_key.split(')')[2].split(',')[1]
                            eventResourceRole = variable_key.split(')')[2].split(',')[2]
                            if variable_key.split(')')[-1] == '' or variable_key.split(')')[-1] == ' ':
                                resource = variable_key.split(')')[2].split(',')[3] + ')'
                            else:
                                resource = variable_key.split(')')[2].split(',')[3]
                            if resource not in individualResources:
                                raise ValueError(f"Error with splitting {variable_key} resource {resource} does not exist")
                    eventDict = solutionEvents[XHSTTFileConstants.EVENTS].setdefault((event, subevent), dict())
                    eventDict[XHSTTFileConstants.DURATION] = subevent[0]
                    eventDict[XHSTTFileConstants.ID] = (event, subevent)
                    eventDict[XHSTTFileConstants.TIME] = starttime
                    eventDict[SolutionDataConstants.DELETE_SUBEVENTS] = False
                    eventDict[XHSTTFileConstants.NAME] = event
                    eventDict.setdefault(XHSTTFileConstants.RESOURCES, dict())[eventResourceRole] = resource
                elif str(v[0]).startswith("s_") and int(v[1]) > 0 and not str(v[0]).startswith("s_i_"):
                    # if str(v[0]).startswith(f"s_{ILPConstants.LIMIT_WORKLOAD}"):
                    #     print(f"Variable name: {v[0]} {v[1]}")
                    constraintID = v[0].split('[')[1].split(',')[0]
                    if constraintID not in constraintIdToConstraintDict.keys():
                        print(f"Error with constraintID {constraintID} of variable {v[0]}")
                    constraint = constraintIdToConstraintDict[constraintID]
                    constrainttype = v[0].split('[')[0][2:]
                    if constrainttype not in deviationsDict.keys():
                        deviationsDict[constrainttype] = 0
                    if constrainttype + "_soft" not in deviationsDict.keys():
                        deviationsDict[constrainttype + "_soft"] = 0
                    if constraint[XHSTTConstraintConstants.REQUIRED]:
                        if constraint[XHSTTConstraintConstants.COST_FUNCTION] == XHSTTConstraintConstants.LINEAR:
                            deviationsDict[constrainttype] += int(v[1]) * int(constraint[XHSTTConstraintConstants.WEIGHT])
                        else:
                            deviationsDict[constrainttype] += int(v[1]) * int(v[1]) * int(constraint[XHSTTConstraintConstants.WEIGHT])
                    else:
                        if constraint[XHSTTConstraintConstants.COST_FUNCTION] == XHSTTConstraintConstants.LINEAR:
                            deviationsDict[constrainttype + "_soft"] += int(v[1]) * int(constraint[XHSTTConstraintConstants.WEIGHT])
                        else:
                            deviationsDict[constrainttype + "_soft"] += int(v[1]) * int(v[1]) * int(constraint[XHSTTConstraintConstants.WEIGHT])
                elif str(v[0]).startswith("y") and int(v[1]) > 0:
                    variable_key = str(v[0]).split('[')[1][:-1]
                    if len(variable_key.split('(')) == 2:
                        event = variable_key.split('(')[0][:-1]
                        subeventIndexDurationPair = variable_key.split('(')[1].split(')')[0]
                        subeventIndexDurationPair = subeventIndexDurationPair.replace(" ", "")
                        subevent = (int(subeventIndexDurationPair.split(',')[0]), int(subeventIndexDurationPair.split(',')[1]))
                        starttime = variable_key.split(')')[1].split(',')[1]
                    else:
                        event = variable_key.split('(')[0] + "(" + variable_key.split('(')[1][:-1]
                        subeventIndexDurationPair = variable_key.split('(')[2].split(')')[0]
                        subeventIndexDurationPair = subeventIndexDurationPair.replace(" ", "")
                        try:
                            subevent = (int(subeventIndexDurationPair.split(',')[0]), int(subeventIndexDurationPair.split(',')[1]))
                        except:
                            raise ValueError(f"Error with splitting {variable_key}")
                        starttime = variable_key.split(')')[2].split(',')[1]
                    if len(self.instance.Events.IndividualEvents[event].EventResources.UnassignedResources +
                           self.instance.Events.IndividualEvents[event].EventResources.AssignedResources) == 0:
                        eventDict = solutionEvents[XHSTTFileConstants.EVENTS].setdefault((event, subevent), dict())
                        eventDict[XHSTTFileConstants.DURATION] = subevent[0]
                        eventDict[XHSTTFileConstants.ID] = (event, subevent)
                        eventDict[XHSTTFileConstants.TIME] = starttime
                        eventDict[SolutionDataConstants.DELETE_SUBEVENTS] = False
                        eventDict[XHSTTFileConstants.NAME] = event
                        eventDict[XHSTTFileConstants.RESOURCES] = dict()
                elif str(v[0]).startswith("u_se") and int(v[1]) > 0:
                    variable_key = str(v[0]).split('[')[1][:-1]
                    if len(variable_key.split('(')) == 2:
                        event = variable_key.split('(')[0][:-1]
                        subeventIndexDurationPair = variable_key.split('(')[1].split(')')[0]
                        subeventIndexDurationPair = subeventIndexDurationPair.replace(" ", "")
                        subevent = (int(subeventIndexDurationPair.split(',')[0]), int(subeventIndexDurationPair.split(',')[1]))
                    else:
                        event = variable_key.split('(')[0] + "(" + variable_key.split('(')[1][:-1]
                        subeventIndexDurationPair = variable_key.split('(')[2].split(')')[0]
                        subeventIndexDurationPair = subeventIndexDurationPair.replace(" ", "")
                        try:
                            subevent = (int(subeventIndexDurationPair.split(',')[0]), int(subeventIndexDurationPair.split(',')[1]))
                        except:
                            raise ValueError(f"Error with splitting {variable_key}")
                    eventDict = solutionEvents[XHSTTFileConstants.EVENTS].setdefault((event, subevent), dict())
                    eventDict[XHSTTFileConstants.DURATION] = subevent[0]
                    eventDict[XHSTTFileConstants.ID] = (event, subevent)
                    eventDict.setdefault(XHSTTFileConstants.TIME, ILPConstants.DUMMY_TIME)
                    eventDict[SolutionDataConstants.DELETE_SUBEVENTS] = False
                    eventDict[XHSTTFileConstants.NAME] = event
                    eventDict.setdefault(XHSTTFileConstants.RESOURCES, dict())
            if outputDeviations:
                for constrainttype in deviationsDict.keys():
                    if deviationsDict[constrainttype] > 0:
                        print(f"{constrainttype}: {deviationsDict[constrainttype]}")
        return solutionEvents
    
    def _initialize_events_to_subevents_dict(self, max_event_length: int = 2, existingSolution=None) -> dict:
        fixBlocks = True
        self.eventToSubEventListDict = dict()
        eventToPossibleSubeventsDict = dict()
        fixed_events = list()
        if existingSolution is not None:
            for event in existingSolution[XHSTTFileConstants.EVENTS]:
                self.eventToSubEventListDict.setdefault(event[0], list()).append(event[1])
            for event in self.instance.Events.IndividualEvents.keys():
                if event in self.eventToSubEventListDict.keys():
                    continue
                print(f"Event {event} has no subevents assigned")
                subevent = (self.instance.Events.IndividualEvents[event].Duration, 0)
                self.eventToSubEventListDict.setdefault(event, list()).append(subevent)
                existingSolution[XHSTTFileConstants.EVENTS][(event, subevent)] = dict()
                existingSolution[XHSTTFileConstants.EVENTS][(event, subevent)][XHSTTFileConstants.TIME] = ILPConstants.DUMMY_TIME
            if self.optimizeSplitting:
                for event in self.eventToSubEventListDict.keys():
                    eventDuration = self.instance.Events.IndividualEvents[event].Duration
                    for dur in range(1, max_event_length + 1):
                        numberOfPossibleSubeventsOfDuration = eventDuration // dur
                        for i in range(numberOfPossibleSubeventsOfDuration):
                            if (dur, i) not in self.eventToSubEventListDict[event]:
                                self.eventToSubEventListDict[event].append((dur, i))

            generateSplitEvents = False
            for event in self.instance.Events.IndividualEvents.keys():
                subevents = self.eventToSubEventListDict[event]
                durationOfSubevents = sum([subevent[0] for subevent in subevents])
                if durationOfSubevents < int(self.instance.Events.IndividualEvents[event].Duration):
                    generateSplitEvents = True
                    if self.model.Params.OutputFlag > 0:
                        print(f"Event {event} has not enough subevents assigned")
            if generateSplitEvents:
                heuristicSolutionGenerator = HeuristicSolutionGenerator(self.instance)
                splitEvents = heuristicSolutionGenerator.unscheduledEventsCopy
            else:
                return self.eventToSubEventListDict
            for event in self.instance.Events.IndividualEvents.keys():
                subevents = self.eventToSubEventListDict[event]
                durationOfSubevents = sum([subevent[0] for subevent in subevents])
                if durationOfSubevents < self.instance.Events.IndividualEvents[event].Duration:
                    subeventsInHeuristicSplit = set(splitEvents[event].keys())
                    alreadyExistingSubevents = set(subevents)
                    missingSubevents = subeventsInHeuristicSplit.difference(alreadyExistingSubevents)
                    durationMissingEvents = sum([subevent[0] for subevent in missingSubevents])
                    if durationMissingEvents + durationOfSubevents == int(self.instance.Events.IndividualEvents[event].Duration):
                        for missingSubevent in missingSubevents:
                            self.eventToSubEventListDict.setdefault(event, list()).append(missingSubevent)
                    else:
                        print(f"Subevent durations dont add up after fix with heuristic solution for {event} ({durationMissingEvents + durationOfSubevents} vs {int(self.instance.Events.IndividualEvents[event].Duration)})")
            return self.eventToSubEventListDict
        for event_id in self.instance.Events.IndividualEvents.keys():
            hard_time_preferences_for_event = [(constraint[XHSTTConstraintConstants.DURATION], t) for constraint in self.instance.Constraints[XHSTTConstraintConstants.PREFER_TIMES_CONSTRAINT]
                                               if constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS] == [event_id]
                                               and constraint[XHSTTConstraintConstants.ID].startswith('PreferTimes_' + event_id)
                                               for t in constraint[XHSTTFileConstants.TIMES]]
            subevent_counter_dict = dict()
            for pref_duration_time in hard_time_preferences_for_event:
                subevent_counter_dict.setdefault(int(pref_duration_time[0]), 0)
                subevent_counter_dict[int(pref_duration_time[0])] = subevent_counter_dict[int(pref_duration_time[0])] + 1

            totalDuration = 0
            for duration in subevent_counter_dict.keys():
                totalDuration += int(duration) * int(subevent_counter_dict[duration])
            if totalDuration == self.instance.Events.IndividualEvents[event_id].Duration:
                fixed_events.append(event_id)
                for duration in subevent_counter_dict.keys():
                    eventToPossibleSubeventsDict.setdefault(event_id, list())
                    eventToPossibleSubeventsDict[event_id].append((duration,
                                                                   subevent_counter_dict[duration],
                                                                   subevent_counter_dict[duration]))

        for constraint in self.instance.Constraints[XHSTTConstraintConstants.DISTRIBUTE_SPLIT_EVENTS_CONSTRAINT]:
            if not constraint[XHSTTConstraintConstants.REQUIRED]:
                continue
            for event in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS]:
                if event in fixed_events:
                    continue
                eventToPossibleSubeventsDict.setdefault(event, list())
                eventToPossibleSubeventsDict[event].append((constraint[XHSTTFileConstants.DURATION], constraint[XHSTTConstraintConstants.MINIMUM], constraint[XHSTTConstraintConstants.MAXIMUM]))
        for constraint in self.instance.Constraints[XHSTTConstraintConstants.SPLIT_EVENTS_CONSTRAINT]:
            for event in constraint[XHSTTConstraintConstants.APPLIES_TO][XHSTTFileConstants.EVENTS]:
                if event in fixed_events:
                    continue
                if event in eventToPossibleSubeventsDict:
                    continue
                eventToPossibleSubeventsDict.setdefault(event, list())
                maxDurationOfPreassignedEvents = max([2] + [int(constraint[XHSTTConstraintConstants.DURATION]) for constraint
                                                   in self.instance.Constraints[
                                                       XHSTTConstraintConstants.PREFER_TIMES_CONSTRAINT]
                                                   if constraint[XHSTTConstraintConstants.APPLIES_TO][
                                                       XHSTTFileConstants.EVENTS] == [event]
                                                   and constraint[XHSTTConstraintConstants.ID].startswith('PreferTimes_' + event)])
                maxDuration = max(int(constraint[XHSTTConstraintConstants.MAXIMUM_DURATION]), maxDurationOfPreassignedEvents)
                for duration in range(int(constraint[XHSTTConstraintConstants.MINIMUM_DURATION]), maxDuration + 1):
                    amount = min(int(self.instance.Events.IndividualEvents[event].Duration) // duration, int(constraint[XHSTTConstraintConstants.MAXIMUM_AMOUNT]))
                    if int(constraint[XHSTTConstraintConstants.MAXIMUM_AMOUNT]) == 1 and duration < int(self.instance.Events.IndividualEvents[event].Duration):
                        continue
                    eventToPossibleSubeventsDict[event].append((duration, amount, amount))
        for event in self.instance.Events.IndividualEvents.keys():
            possibleSubEventDurations = list()
            if event in eventToPossibleSubeventsDict.keys():
                possibleDurations = list({int(subeventpossibilities[0]) for subeventpossibilities in eventToPossibleSubeventsDict[event]})
                possibleDurations = sorted(possibleDurations, key=int, reverse=True)
            else:
                possibleDurations = list()
            if event.endswith('_max_requirement') or event.endswith('_min_requirement'):
                mainEventID = event.split('_')[0] + '_' + event.split('_')[1]
                remainingDuration = int(self.instance.Events.IndividualEvents[event].Duration)
                for subeventpossibilities in sorted(eventToPossibleSubeventsDict[mainEventID], key=lambda constraint: int(constraint[0]), reverse=True):
                    if fixBlocks:
                        duration = int(subeventpossibilities[0])
                        if duration * int(subeventpossibilities[2]) <= remainingDuration:
                            maximumPossibleAmount = int(subeventpossibilities[2])
                        else:
                            maximumPossibleAmount = remainingDuration // duration
                        remainingDuration -= duration * maximumPossibleAmount
                    else:
                        duration = int(subeventpossibilities[0])
                        maximumPossibleAmount = int(subeventpossibilities[2])
                    for j in range(maximumPossibleAmount):
                        possibleSubEventDurations.append((duration, j))
            elif event + '_student_1_min_requirement' in self.instance.Events.IndividualEvents.keys() or event + '_student_1_max_requirement' in self.instance.Events.IndividualEvents.keys():
                remainingDuration = int(self.instance.Events.IndividualEvents[event].Duration)
                for subeventpossibilities in sorted(eventToPossibleSubeventsDict[event],
                                                    key=lambda constraint: int(constraint[0]), reverse=True):
                    if fixBlocks:
                        duration = int(subeventpossibilities[0])
                        if duration * int(subeventpossibilities[2]) <= remainingDuration:
                            maximumPossibleAmount = int(subeventpossibilities[2])
                        else:
                            maximumPossibleAmount = remainingDuration // duration
                        remainingDuration -= duration * maximumPossibleAmount
                    else:
                        duration = int(subeventpossibilities[0])
                        maximumPossibleAmount = int(subeventpossibilities[2])
                    for j in range(maximumPossibleAmount):
                        possibleSubEventDurations.append((duration, j))
            elif len(possibleDurations) > 0 and self.restict_model_to_distribution_constraints:
                remainingDuration = int(self.instance.Events.IndividualEvents[event].Duration)
                for subeventpossibilities in sorted(eventToPossibleSubeventsDict[event],
                                                    key=lambda constraint: int(constraint[0]), reverse=True):
                    if fixBlocks:
                        duration = int(subeventpossibilities[0])
                        if duration * int(subeventpossibilities[2]) <= remainingDuration:
                            maximumPossibleAmount = int(subeventpossibilities[2])
                        else:
                            maximumPossibleAmount = remainingDuration // duration
                        remainingDuration -= duration * maximumPossibleAmount
                    else:
                        duration = int(subeventpossibilities[0])
                        maximumPossibleAmount = int(subeventpossibilities[2])
                    for j in range(maximumPossibleAmount):
                        possibleSubEventDurations.append((duration, j))
            else:
                eventObj = self.instance.Events.IndividualEvents[event]
                if fixBlocks:
                    for i in range(int(eventObj.Duration) // 2):
                        possibleSubEventDurations.append((2, i))
                    if int(eventObj.Duration) % 2 == 1:
                        possibleSubEventDurations.append((1, 0))
                else:
                    for i in range(1, min(int(self.instance.Events.IndividualEvents[event].Duration) + 1, max_event_length + 1)):
                        for j in range(self.instance.Events.IndividualEvents[event].Duration // i):
                            possibleSubEventDurations.append((i, j))
            durationOfAssignedSubevents = sum([subevent[0] for subevent in possibleSubEventDurations])
            if durationOfAssignedSubevents != self.instance.Events.IndividualEvents[event].Duration:
                print(f"{event} {durationOfAssignedSubevents} vs {self.instance.Events.IndividualEvents[event].Duration}: {possibleSubEventDurations}")
            self.eventToSubEventListDict[event] = possibleSubEventDurations

        return self.eventToSubEventListDict
    
    def _initialize_event_resources_to_possible_resources_dict(self, existingSolution=None, fixResources=False) -> dict:
        self.eventResourceToPossibleResourcesDict = dict()

        resourcesWithDummyResource = [ILPConstants.DUMMY_RESOURCE] + list(self.instance.Resources.IndividualResources.keys())
        for event in self.instance.Events.IndividualEvents.keys():
            if fixResources:
                for eventResource in self.instance.Events.IndividualEvents[event].EventResources.AssignedResources + self.instance.Events.IndividualEvents[event].EventResources.UnassignedResources:
                    resourcesUsedForEvent = list({existingSolution[XHSTTFileConstants.EVENTS][subevent][XHSTTFileConstants.RESOURCES][eventResource.Role] for subevent in existingSolution[XHSTTFileConstants.EVENTS].keys() if subevent[0] == event and eventResource.Role in existingSolution[XHSTTFileConstants.EVENTS][subevent][XHSTTFileConstants.RESOURCES].keys()} | {ILPConstants.DUMMY_RESOURCE for subevent in existingSolution[XHSTTFileConstants.EVENTS].keys() if subevent[0] == event and eventResource.Role not in existingSolution[XHSTTFileConstants.EVENTS][subevent][XHSTTFileConstants.RESOURCES].keys()})
                    self.eventResourceToPossibleResourcesDict[event, eventResource.Role] = resourcesUsedForEvent
            else:
                for eventResource in self.instance.Events.IndividualEvents[event].EventResources.AssignedResources:
                    if eventResource.Role is None and (existingSolution is None or len(
                            [e for e in existingSolution[XHSTTFileConstants.EVENTS].values() if
                              e[XHSTTFileConstants.NAME] == event]) == 0):
                        eventResource.Role = "NoRole" + str(uuid.uuid4())
                    elif eventResource.Role is None:
                        eventInExistingSolution = [e for e in existingSolution[XHSTTFileConstants.EVENTS].values() if
                                                   e[XHSTTFileConstants.NAME] == event][0]
                        eventResource.Role = [r for r in eventInExistingSolution[XHSTTFileConstants.RESOURCES].keys()
                                              if eventInExistingSolution[XHSTTFileConstants.RESOURCES][
                                                  r] == eventResource.Reference][0]
                    if self.optimizeSplitting:
                        self.eventResourceToPossibleResourcesDict[event, eventResource.Role] = [eventResource.Reference, ILPConstants.DUMMY_RESOURCE]
                    else:
                        self.eventResourceToPossibleResourcesDict[event, eventResource.Role] = [eventResource.Reference]
                for eventResource in self.instance.Events.IndividualEvents[event].EventResources.UnassignedResources:
                    self.eventResourceToPossibleResourcesDict[event, eventResource.Role] = list()
                    if event.endswith('_max_requirement') or event.endswith('_min_requirement') or eventResource.Role.startswith('max_requirement_') or eventResource.Role.startswith('min_requirement_'):
                        relevantConstraints = [constraint for constraint in self.instance.Constraints[
                            XHSTTConstraintConstants.PREFER_RESOURCES_CONSTRAINT]
                                               if event in constraint[XHSTTConstraintConstants.APPLIES_TO][
                                                    XHSTTFileConstants.EVENTS] and constraint[XHSTTConstraintConstants.ROLE] == eventResource.Role]
                        if len(relevantConstraints) > 0:
                            relevantConstraint = relevantConstraints[0]
                            for resource in relevantConstraint[XHSTTFileConstants.RESOURCES] + [ILPConstants.DUMMY_RESOURCE]:
                                if resource not in self.eventResourceToPossibleResourcesDict[event, eventResource.Role]:
                                    self.eventResourceToPossibleResourcesDict[event, eventResource.Role].append(resource)
                        else:
                            if ILPConstants.DUMMY_RESOURCE not in self.eventResourceToPossibleResourcesDict[event, eventResource.Role]:
                                self.eventResourceToPossibleResourcesDict[event, eventResource.Role].append(ILPConstants.DUMMY_RESOURCE)
                    else:
                        for resource in resourcesWithDummyResource:
                            if resource == ILPConstants.DUMMY_RESOURCE or self.instance.Resources.IndividualResources[
                                resource].Type == eventResource.ResourceType:
                                self.eventResourceToPossibleResourcesDict[event, eventResource.Role].append(resource)
        return self.eventResourceToPossibleResourcesDict
    def _initialize_variables(self, existingSolution: dict = None, onlyAllowExistingTimes=False, onlyAllowCurrentResources=False) -> dict:
        # Returned Dict
        self.variableDict = dict()

        # Helper Dicts for initializing variable dict
        solutionEventVariablesHelperDict = dict()
        subEventStartTimeVariablesHelperDict = dict()
        resourceUsagePerTimeHelperDict = dict()
        subEventResourceAssignmentVariablesHelperDict = dict()
        activeSubEventVariablesHelperDict = dict()
        eventAssignedResourcesDict = dict()
        eventAssignedResourcesWithRoleDict = dict()
        eventGroupAssignedResourcesDict = dict()
        busyResourceIndicatorForTimeVariablesHelperDict = dict()
        busyResourceIndicatorForTimeGroupVariablesHelperDict = dict()
        timesWithDummyTime = [ILPConstants.DUMMY_TIME] + list(self.instance.Times.IndividualTimes.keys())
        resourcesWithDummyResource = [ILPConstants.DUMMY_RESOURCE] + list(self.instance.Resources.IndividualResources.keys())
        for event in self.instance.Events.IndividualEvents.keys():
            if event not in self.eventToSubEventListDict:
                continue
            for subevent in self.eventToSubEventListDict[event]:
                activeSubEventVariablesHelperDict[event, subevent] = 0
                for t in timesWithDummyTime:
                    if onlyAllowExistingTimes and existingSolution[XHSTTFileConstants.EVENTS][(event, subevent)][XHSTTFileConstants.TIME] != t:
                        continue
                    subEventStartTimeVariablesHelperDict[event, subevent, t] = 0
                    for eventResource in self.instance.Events.IndividualEvents[event].EventResources.AssignedResources:
                        if eventResource.Role is None and (existingSolution is None or len([e for e in existingSolution[XHSTTFileConstants.EVENTS].values() if e[XHSTTFileConstants.NAME] == event]) == 0):
                            eventResource.Role = "NoRole" + str(uuid.uuid4())
                        elif eventResource.Role is None:
                            eventInExistingSolution = [e for e in existingSolution[XHSTTFileConstants.EVENTS].values() if e[XHSTTFileConstants.NAME] == event][0]
                            eventResource.Role = [r for r in eventInExistingSolution[XHSTTFileConstants.RESOURCES].keys()
                                                  if eventInExistingSolution[XHSTTFileConstants.RESOURCES][r] == eventResource.Reference
                                                  and (event, subevent, r, eventResource.Reference) not in subEventResourceAssignmentVariablesHelperDict.keys()][0]
                        if onlyAllowCurrentResources:
                            possibilities = [existingSolution[XHSTTFileConstants.EVENTS][(event, subevent)][XHSTTFileConstants.RESOURCES][eventResource.Role]]
                        else:
                            if self.optimizeSplitting:
                                possibilities = [eventResource.Reference, ILPConstants.DUMMY_RESOURCE]
                            else:
                                possibilities = [eventResource.Reference]
                        for resource in possibilities:
                            eventAssignedResourcesDict[event, resource] = 0
                            eventAssignedResourcesWithRoleDict[event, eventResource.Role, resource] = 0
                            subEventResourceAssignmentVariablesHelperDict[event, subevent, eventResource.Role,
                            resource] = 0
                            solutionEventVariablesHelperDict[event, subevent, t, eventResource.Role,
                            resource] = 0
                    for eventResource in self.instance.Events.IndividualEvents[event].EventResources.UnassignedResources:
                        if onlyAllowCurrentResources:
                            if eventResource.Role not in existingSolution[XHSTTFileConstants.EVENTS][(event, subevent)][
                                                 XHSTTFileConstants.RESOURCES].keys():
                                possibilities = [ILPConstants.DUMMY_RESOURCE]
                            else:
                                possibilities = [existingSolution[XHSTTFileConstants.EVENTS][(event, subevent)][
                                                     XHSTTFileConstants.RESOURCES][eventResource.Role]]
                        else:
                            possibilities = self.eventResourceToPossibleResourcesDict[event, eventResource.Role]
                        for resource in possibilities:
                            eventAssignedResourcesDict[event, resource] = 0
                            eventAssignedResourcesWithRoleDict[event, eventResource.Role, resource] = 0
                            solutionEventVariablesHelperDict[event, subevent, t, eventResource.Role,
                            resource] = 0
                            subEventResourceAssignmentVariablesHelperDict[event, subevent, eventResource.Role,
                            resource] = 0

        for t in timesWithDummyTime:
            for resource in resourcesWithDummyResource:
                resourceUsagePerTimeHelperDict[t, resource] = 0
                busyResourceIndicatorForTimeVariablesHelperDict[resource, t] = 0

        for timeGroup in self.instance.Times.TimeGroups.keys():
            for resource in resourcesWithDummyResource:
                busyResourceIndicatorForTimeGroupVariablesHelperDict[resource, timeGroup] = 0

        for timeGroup in self.instance.Times.Days.keys():
            for resource in resourcesWithDummyResource:
                busyResourceIndicatorForTimeGroupVariablesHelperDict[resource, timeGroup] = 0

        for eventGroup in self.instance.Events.EventGroups.keys():
            for event in self.instance.Events.EventGroups[eventGroup].Events:
                for eventResource in self.instance.Events.IndividualEvents[event].EventResources.AssignedResources:
                    eventGroupAssignedResourcesDict[eventGroup, eventResource.Reference] = 0
                    eventGroupAssignedResourcesDict[eventGroup, ILPConstants.DUMMY_RESOURCE] = 0
                for eventResource in self.instance.Events.IndividualEvents[event].EventResources.UnassignedResources:
                    for resource in resourcesWithDummyResource:
                        if resource == ILPConstants.DUMMY_RESOURCE or self.instance.Resources.IndividualResources[
                            resource].Type == eventResource.ResourceType:
                            eventGroupAssignedResourcesDict[eventGroup, resource] = 0

        numberOfTimeSlots = len(self.instance.Times.IndividualTimes.keys())
        self.variableDict["x"] = self.model.addVars(solutionEventVariablesHelperDict.keys(), vtype=GRB.BINARY,
                                          name="x", lb=0)
        self.variableDict["y"] = self.model.addVars(subEventStartTimeVariablesHelperDict.keys(), vtype=GRB.BINARY,
                                          name="y", lb=0)
        self.variableDict["v"] = self.model.addVars(resourceUsagePerTimeHelperDict.keys(), vtype=GRB.INTEGER,
                                          name="v", lb=0, ub=numberOfTimeSlots)
        self.variableDict["w"] = self.model.addVars(subEventResourceAssignmentVariablesHelperDict.keys(),
                                          vtype=GRB.BINARY, name="w", lb=0)
        self.variableDict["b"] = self.model.addVars(eventAssignedResourcesDict.keys(), vtype=GRB.BINARY, name="b", lb=0)
        self.variableDict["d"] = self.model.addVars(eventAssignedResourcesWithRoleDict.keys(), vtype=GRB.BINARY, name="d", lb=0)
        self.variableDict["c"] = self.model.addVars(eventGroupAssignedResourcesDict.keys(), vtype=GRB.BINARY, name="c", lb=0)
        self.variableDict["u_se"] = self.model.addVars(activeSubEventVariablesHelperDict.keys(),
                                             vtype=GRB.BINARY, name="u_se", lb=0)
        self.variableDict["q"] = self.model.addVars(busyResourceIndicatorForTimeVariablesHelperDict.keys(),
                                          vtype=GRB.BINARY, name="q", lb=0)
        self.variableDict["p"] = self.model.addVars(busyResourceIndicatorForTimeGroupVariablesHelperDict.keys(),
                                          vtype=GRB.BINARY, name="p", lb=0)
        return self.variableDict
    
    def _initialize_possible_start_time_by_event_duration_dict(self, max_event_length: int = 3):
        timesWithDummyTime = [ILPConstants.DUMMY_TIME] + list(self.instance.Times.IndividualTimes.keys())
    
        self.possibleStartTimesByEventDurationDict = dict()
    
        self.possibleStartTimesByEventDurationDict[1] = list(timesWithDummyTime)
        for i in range(2, max_event_length + 1):
            self.possibleStartTimesByEventDurationDict[i] = list()
            self.possibleStartTimesByEventDurationDict[i].append(ILPConstants.DUMMY_TIME)
            for day in self.instance.Times.Days.keys():
                for t in self.instance.Times.Days[day].Times[:(-i + 1)]:
                    self.possibleStartTimesByEventDurationDict[i].append(t)