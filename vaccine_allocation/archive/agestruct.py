from pathlib import Path

import epimargin.plots as plt
import numpy as np
import pandas as pd
from epimargin.estimators import analytical_MPVS
from epimargin.models import SIR
from epimargin.smoothing import notched_smoothing
from numpy import diag, eye, tile, vstack
from scipy.stats import binom as Binom
from scipy.stats import poisson as Poisson

# root = Path(__file__).parent
# data = root/"data"

CI = 0.95
window = 10
gamma = 0.2
infectious_period = 5

u = np.array([0.4, 0.38, 0.79,0.86, 0.8, 0.82,0.88, 0.74])

class AgeStructured(SIR):
    def __init__(self, 
        name:       str, 
        population: int,
        dT0:        int, 
        I0:         int,
        rt:         float, 
        contact_structure, 
        age_structure,
        prevalence_structure, 
        num_age_bins = 8,
        infectious_period = 5,
        random_seed = 0
    ):
        self.name = name 
        self.pop0 = population 
        self.N  = (population * age_structure).astype(int)   if isinstance(population, (int, float)) else population
        self.dT = [(dT0 * prevalence_structure).astype(int)] if isinstance(dT, (int, float))         else dT
        self.C  = contact_structure
        self.rt = rt
        self.S  = [((population - I0) * age_structure).astype(int)] if isinstance(dT, (int, float))  else population
        self.I  = [(I0 * prevalence_structure).astype(int)] if isinstance(I0, (int, float))          else I0
        self.num_age_bins = num_age_bins
        self.gamma = 1/infectious_period

    def forward_epi_step(self):
        M = self.rt * self.C / np.linalg.eigvals(self.C).max()
        S, I, N = self.S[-1], self.I[-1], self.N
        dT = Poisson.rvs(M @ (I/N))
        dR = Poisson.rvs(self.gamma * (I + dT))
        self.S.append((S - dT).clip(0))
        self.I.append((I + dT - dR).clip(0))
        self.dT.append(dT)

##############################
# load general purpose data

# # contact matrix from Laxminarayan (Table S8)
C = np.array([
    [89, 452, 1358, 1099, 716, 821, 297, 80+15],
    [431, 3419, 8600, 7131, 5188, 5181, 1876, 502+67],
    [1882, 11179, 41980, 29896, 23127, 22914, 7663, 1850+228],
    [2196, 13213, 35625, 31752, 21777, 22541, 7250, 1796+226],
    [1097, 9768, 27701, 23371, 18358, 17162, 6040, 1526+214],
    [1181, 8314, 26992, 22714, 17886, 18973, 6173, 1633+217],
    [358, 2855, 7479, 6539, 5160, 5695, 2415, 597+82],
    [75+15, 693+109, 2001+282, 1675+205, 1443+178, 1482+212, 638+72, 211+18+15+7]
])

# get age structure
IN_age_structure = { # WPP2019_POP_F01_1_POPULATION_BY_AGE_BOTH_SEXES
    0:  116_880,
    5:  117_982 + 126_156 + 126_046,
    18: 122_505 + 117_397, 
    30: 112_176 + 103_460,
    40: 90_220 + 79_440,
    50: 68_876 + 59_256 + 48_891,
    65: 38_260 + 24_091,
    75: 15_084 + 8_489 + 3_531 +  993 +  223 +  48,
}
# normalize
age_structure_norm = sum(IN_age_structure.values())
IN_age_ratios = np.array([v/age_structure_norm for (k, v) in IN_age_structure.items()])
split_by_age = lambda v: (v * IN_age_ratios).astype(int)

# get age-specific prevalence from KA sero
KA = pd.read_stata("data/ka_cases_deaths_time_newagecat.dta")

KA.agecat = KA.agecat.where(KA.agecat != 85, 75) # we don't have econ data for 85+ so combine 75+ and 85+ categories 
KA_agecases = KA.groupby(["agecat", "date"])["patientcode"]\
    .count().sort_index().rename("cases")\
    .unstack().fillna(0).stack()
KA_ts = KA_agecases.sum(level = 1)
(dates, Rt_pred, Rt_CI_upper, Rt_CI_lower, T_pred, T_CI_upper, T_CI_lower, total_cases, new_cases_ts, anomalies, anomaly_dates) = analytical_MPVS(KA_ts, notched_smoothing(5)) 

COVID_age_ratios = (KA_agecases.sum(level = 0)/KA_agecases.sum()).values
split_by_prevalence = lambda v: (v * IN_age_ratios).astype(int)

for seed in range(10):
    model = AgeStructured("KA", 6.11e7, 857, 915345, 1.826, diag(u) @ C, IN_age_ratios, COVID_age_ratios, seed)
    counter = 0
    while model.dT[-1].sum() > 0:
        model.forward_epi_step()
        counter += 1
    print(seed, counter, model.dT)
    
