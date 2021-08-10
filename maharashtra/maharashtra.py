from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from tqdm import tqdm

import etl
from epimargin.estimators import rollingOLS
from epimargin.model  import Model, ModelUnit, gravity_matrix
from epimargin.plots  import gantt_chart, plot_simulation_range
from epimargin.policy import simulate_adaptive_control, simulate_lockdown
from epimargin.utils  import cwd, days, weeks, fmt_params


def model(districts, populations, cases, seed) -> Model:
    max_ts = max([ts.index.max() for ts in cases.values()]).isoformat()
    units = [
        ModelUnit(district, populations[i], 
        I0 = cases[district].loc[max_ts].Infected if district in cases.keys() and max_ts in cases[district].index else 0, 
        R0 = cases[district].loc[max_ts].Recovered    if district in cases.keys() and max_ts in cases[district].index else 0, 
        D0 = cases[district].loc[max_ts].Deceased     if district in cases.keys() and max_ts in cases[district].index else 0)
        for (i, district) in enumerate(districts)
    ]
    return Model(units, random_seed=seed)

def run_policies(
        district_cases: Dict[str, pd.DataFrame], # timeseries for each district 
        populations:    pd.Series,               # population for each district
        districts:      Sequence[str],           # list of district names 
        migrations:     np.matrix,               # O->D migration matrix, normalized
        gamma:          float,                   # 1/infectious period 
        Rmw:            Dict[str, float],        # mandatory regime R
        Rvw:            Dict[str, float],        # voluntary regime R
        total:          int   = 90*days,         # how long to run simulation
        eval_period:    int   = 2*weeks,         # adaptive evaluation perion
        beta_scaling:   float = 1.0,             # robustness scaling: how much to shift empirical beta by 
        seed:           int   = 0                # random seed for simulation
    ):
    lockdown = np.zeros(migrations.shape)

    # lockdown 1
    model_A = model(districts, populations, district_cases, seed)
    simulate_lockdown(model_A, 5*days, total, Rmw, Rvw, lockdown, migrations)

    # lockdown 2
    model_B = model(districts, populations, district_cases, seed)
    simulate_lockdown(model_B, 35*days, total, Rmw, Rvw, lockdown, migrations)

    # 9 day lockdown + adaptive controls
    model_C = model(districts, populations, district_cases, seed)
    simulate_adaptive_control(model_C, 5*days, total, lockdown, migrations, Rmw,
        {district: beta_scaling * Rv * gamma for (district, Rv) in Rvw.items()},
        {district: beta_scaling * Rm * gamma for (district, Rm) in Rmw.items()},
        evaluation_period=eval_period
    )

    return model_A, model_B, model_C

def estimate(district, ts, default = 1.5, window = 5, use_last = False):
    try:
        regressions = rollingOLS(etl.log_delta_smoothed(ts), window = window, infectious_period = 1/gamma)[["R", "Intercept", "gradient", "gradient_stderr"]]
        if use_last:
            return next((x for x in regressions.R.iloc[-3:-1] if not np.isnan(x) and x > 0), default)
        return regressions
    except (ValueError, IndexError):
        return default

def gantt_seed(seed, note = ""):
    _, _, mc = run_policies(district_ts, pops, districts, migrations, gamma, R_mandatory, R_voluntary, seed = seed) 
    gantt_chart(mc.gantt)\
        .title(f"Maharashtra: Example Adaptive Lockdown Mobility Regime Scenario {note if note else str(seed)}")\
        .show()

def project(p: pd.Series):
    t = (p.R - p.Intercept)/p.gradient
    return (max(0, p.R), max(0, p.Intercept + p.gradient*(t + 7)), max(0, p.Intercept + p.gradient*(t + 14)), np.sqrt(p.gradient_stderr))

if __name__ == "__main__":
    root = cwd()
    data = root/"data"
    figs = root/"figs"
    
    gamma  = 0.2
    window = 5

    new_state_data_paths = { 
        "Maharashtra": (data/"maharashtra.json", data/"maharashtra_pop.csv")
    }

    state_cases    = etl.load_cases(data/"Maharashtra_cases_districts_date_May27.csv")
    district_cases = etl.split_cases_by_district(state_cases)
    district_ts    = {district: etl.get_time_series(cases) for (district, cases) in district_cases.items()}
    R_mandatory    = {district: estimate(district, ts, use_last = True) for (district, ts) in district_ts.items()}
    # districts, pops, migrations = etl.district_migration_matrix(data/"Migration Matrix - District.csv")
    districts, pops, migrations = gravity_matrix(*new_state_data_paths["Maharashtra"])
    
    # handling differences in spelling of districts between data sources - need to change
    districts.remove("AMRAVATI")
    districts.append("AMARAVATI")

    for district in districts:
        if district not in R_mandatory.keys():
            R_mandatory[district] = 1.5
    
    R_voluntary    = {district: 1.5*R for (district, R) in R_mandatory.items()}

    si, sf = 0, 5

    simulation_results = [ 
        run_policies(district_ts, pops, districts, migrations, gamma, R_mandatory, R_voluntary, seed = seed)
        for seed in tqdm(range(si, sf))
    ]

    state_ts = etl.get_time_series(state_cases)
    smoothed = etl.lowess(state_ts["Infected"], state_ts.index)

    plot_simulation_range(
        simulation_results, 
        ["31 May Release", "30 June Release", "Adaptive Control"], 
        historical = state_ts["Infected"], 
        smoothing = smoothed)\
        .title("Maharashtra Policy Scenarios: Projected Infections over Time")\
        .xlabel("Date")\
        .ylabel("Number of Infections")\
        .annotate(f"stochastic parameter range: ({si}, {sf}), infectious period: {1/gamma} days, smoothing window: {window}")\
        .show()

    # projections
    estimates = {district: estimate(district, ts, default = -1) for (district, ts) in district_ts.items()}
    index = {k: v.last_valid_index() if v is not -1 else v for (k, v) in estimates.items()}
    projections = []
    for district, estimate in estimates.items():
        if estimate is -1:
            projections.append((district, None, None, None, None))
        else:
            idx = index[district]
            if idx is None or idx is -1:
                projections.append((district, None, None, None, None))
            else: 
                projections.append((district, *project(estimate.loc[idx])))
    projdf = pd.DataFrame(data = projections, columns = ["district", "current R", "1 week projection", "2 week projection", "stderr"])
    projdf = projdf.drop(columns = ["2 week projection"])
    print(projdf)

       
 
