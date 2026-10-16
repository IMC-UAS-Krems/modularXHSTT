import random

class ALNS_Config:
    def __init__(self):
        self.SEED = random.randint(1, 100000)
        self.OUTPUT_LEVEL = 1
        # previously 2
        # self.SOLVER = "ILP"
        self.SOLVER = "ILP"
        self.SOLVER_PROBS = [0.9, 0.1]
        self.EXPLORATION_RATE = 3
        self.AVERAGED_LENGTH_FOR_TIMES = 100
        self.TIME_TOLERANCE = 0.2
        self.TIME_STEPS_TILL_INCREASE = 170
        self.TIME_STEPS_TILL_WEIGHT_CHANGE = 5
        self.TIME_STEPS_TILL_RETURN_TO_BEST_KNOWN_SOLUTION = 10
        self.MAXIMUM_TIME_STEPS_WITHOUT_CHANGE_WHEN_WEIGHT_CHANGED = 5
        self.TIME_STEPS_TILL_WEIGHT_CHANGE_RESET = 5
        # self.TIME_STEPS_TILL_WEIGHT_CHANGE = 34
        # self.TIME_STEPS_TILL_RETURN_TO_BEST_KNOWN_SOLUTION = 35
        # self.MAXIMUM_TIME_STEPS_WITHOUT_CHANGE_WHEN_WEIGHT_CHANGED = 10
        # self.TIME_STEPS_TILL_WEIGHT_CHANGE_RESET = 17
        # 120.0 works good for big instances
        self.INITIAL_TIME_TARGET = 5.0
        self.MIN_TIME = self.INITIAL_TIME_TARGET
        self.MAX_TIME = self.INITIAL_TIME_TARGET * 16
        self.TIME_INCREASE_FACTOR = 1.29
        self.TIME_DECREASE_FACTOR = 0.78
        self.REWARD_VECTOR_LENGTH_AFTER_FEASIBILITY = 2
        self.INITIAL_NEIGHBORHOOD_SIZE = 5
        # self.FIXED_NEIGHBORHOOD_SIZES = [10, 27, 292, 5, 10, 389]
        # self.FIXED_NEIGHBORHOOD_SIZES = [3, 5, 30, 5, 3, 30]
        self.FIXED_NEIGHBORHOOD_SIZES = [5, 5, 5, 5, 5, 5]
        # usually 10
        self.TEMP = 0.2
        self.INITIAL_AMOUNT_OF_EXPLORATIONS = 3
        self.INITIAL_NEIGHBORHOOD_JUMP_SIZE = 64
        self.USE_UCB_MULTI_ARMED_BANDIT = True
        # reset
        self.USE_DEVIATION_INFORMATION = False
        self.TABOO_LENGTH = 173
        self.IGNORE_SOFT_CONSTRAINTS_WHEN_INFEASIBLE = False
        self.ACCEPTANCE_FUNCTION = "RRT"
        # self.ACCEPTANCE_FUNCTION = "METROPOLIS"

        self.INITIAL_TIME_TARGET = 16
        self.MIN_TIME = 16
        self.MAX_TIME = 16 * 16
        # self.EXPLORATION_RATE = config["exploration_rate"]
        self.TIME_INCREASE_FACTOR = 1.47
        self.TIME_DECREASE_FACTOR = 0.98
        self.TIME_STEPS_TILL_WEIGHT_CHANGE = 43
        self.TIME_STEPS_TILL_WEIGHT_CHANGE_RESET = 35
        self.TIME_STEPS_TILL_INCREASE = 27
        self.TIME_STEPS_TILL_RETURN_TO_BEST_KNOWN_SOLUTION = 95
        self.MAXIMUM_TIME_STEPS_WITHOUT_CHANGE_WHEN_WEIGHT_CHANGED = 61

