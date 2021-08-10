from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple, Callable
from tqdm import tqdm
from io import StringIO

from epimargin.utils import cwd
from epimargin.estimators import analytical_MPVS
from epimargin.smoothing import convolution

from etl import import_and_clean_cases
from etl import get_adaptive_estimates, get_new_rt_live_estimates, get_old_rt_live_estimates, get_cori_estimates, get_luis_estimates
from rtlive_old_model import get_delay_distribution, create_and_run_model, df_from_model
from luis_model import run_luis_model

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import subprocess


# PARAMETERS
CI               = 0.95
smoothing_window = 15
rexepath         = 'C:\\Program Files\\R\\R-3.6.1\\bin\\'


def run_adaptive_model(df:pd.DataFrame, CI:float,
                       smoothing:Callable, filepath:Path) -> None:
    '''
    Runs adaptive control model of Rt and smoothed case counts based on what is currently in the 
    analytical_MPVS module. Takes in dataframe of cases and saves to csv a dataframe of results.
    '''
    # Initialize results df
    res_full = pd.DataFrame()
    
    # Loop through each state
    print("Estimating state Rt values...")
    for state in tqdm(df['state'].unique()):
                
        # Calculate Rt for that state
        state_df = df[df['state'] == state].set_index('date')
        (
        dates, RR_pred, RR_CI_upper, RR_CI_lower,
        T_pred, T_CI_upper, T_CI_lower,
        total_cases, new_cases_ts,
        _, anomaly_dates
        ) = analytical_MPVS(state_df[state_df['positive'] > 0]['positive'], 
                        CI=CI, smoothing=smoothing)
        assert(len(dates) == len(RR_pred))
        
        # Save results
        res = pd.DataFrame({'state':state,
                            'date':dates,
                            'RR_pred':RR_pred,
                            'RR_CI_upper':RR_CI_upper,
                            'RR_CI_lower':RR_CI_lower,
                            'T_pred':T_pred,
                            'T_CI_upper':T_CI_upper,
                            'T_CI_lower':T_CI_lower,
                            'new_cases_ts':new_cases_ts,
                            'total_cases':total_cases[2:],
                            'anamoly':dates.isin(set(anomaly_dates))})
        res_full = pd.concat([res_full,res], axis=0)
    
    # Merge results back onto input df and return
    merged_df = df.merge(res_full, how='outer', on=['state','date'])
    merged_df.to_csv(filepath/"adaptive_estimates.csv")


def run_rtlive_old_model(df:pd.DataFrame, filepath:Path) -> None:
    '''
    Runs old rt.live model of Rt. Takes in dataframe of case data and
    saves out a CSV of results.
    '''
    # Get delay empirical distribution
    p_delay = get_delay_distribution(file_path=filepath, force_update=True)

    # Run model for each state
    models = {}
    for state in df['state'].unique():
        
        if state in models:
            print(f"Skipping {state}, already in cache")
            continue
        print(f'Working on {state}')
        state_df = df[df['state'] == state].set_index('date')
        models[state] = create_and_run_model(state, state_df, p_delay)
                
    # Check to see if there were divergences
    n_diverging = lambda x: x.trace['diverging'].nonzero()[0].size
    divergences = pd.Series([n_diverging(m) for m in models.values()], index=models.keys())
    has_divergences = divergences.gt(0)

    # Rerun states with divergences
    for state, n_divergences in divergences[has_divergences].items():
        models[state].run()

    # Build df of results
    results = None
    for state, model in models.items():
        dfres = df_from_model(model)
        if results is None:
            results = dfres
        else:
            results = pd.concat([results, dfres], axis=0)
            
    # Save results
    results.reset_index(inplace=True)
    results.to_csv(filepath/'rtlive_old_estimates.csv', index=False)


def run_cori_model(filepath:Path, rexepath:Path) -> None:
    '''
    Runs R script that runs Cori model estimates. Saves results in
    a CSV file.
    '''
    subprocess.call([rexepath/"Rscript.exe", filepath/"cori_model.R"], shell=True)
    return


def make_state_plots(df:pd.DataFrame, plotspath:Path) -> None:
    '''
    Saves comparison plots of our Rt estimates vs. Rt.live estimates
    into plotspath folder.
    '''
    print("Plotting results...")
    for state in tqdm(df['state'].unique()):
                
        # Get state data
        state_res = df[df['state']==state].sort_values('date')

        # Filter to after 3/15/2020 (earlier estimates vary wildly)
        state_res = state_res[state_res['date'] >= '2020-04-01'] 
        daterange = np.arange(np.datetime64(min(state_res['date'])), 
                              np.datetime64(max(state_res['date'])+np.timedelta64(2,'D')), 
                              np.timedelta64(4,'D')) 
        
        # Set up plot
        fig,ax = plt.subplots(2, 1, figsize=(15,15))

        # Top plot
        ax[0].plot(state_res['date'], state_res['RR_pred'], linewidth=2.5)
        ax[0].plot(state_res['date'], state_res['RR_pred_rtlivenew'], linewidth=2.5)
        ax[0].plot(state_res['date'], state_res['RR_pred_rtliveold'], linewidth=2.5)
        ax[0].plot(state_res['date'], state_res['RR_pred_cori'], linewidth=2.5)
        ax[0].plot(state_res['date'], state_res['RR_pred_luis'], linewidth=2.5)
        ax[0].set_title(f"{state} - Comparing Rt Estimates", fontsize=22)
        ax[0].set_ylabel("Rt Estimate", fontsize=15)
        ax[0].set_xticks(daterange)
        ax[0].set_xticklabels(pd.to_datetime(daterange).strftime("%b %d"), rotation=70)
        ax[0].legend(['Adaptive Control Estimate', 'New rt.live Estimate', 'Old rt.live Estimate', 'Cori Method Estimate', 'Luis Code Estimate'],
                     fontsize=15)

        # Bottom plot
        ax[1].plot(state_res['date'], state_res['new_cases_ts'], linewidth=2.5)
        ax[1].plot(state_res['date'], state_res['adj_positive_rtlivenew'], linewidth=2.5)
        ax[1].plot(state_res['date'], state_res['infections_rtlivenew'], linewidth=2.5)

        ax[1].set_title(f"{state} - Comparing Estimated Daily New Case Count", fontsize=22)
        ax[1].set_ylabel("Estimated Daily New Case Count", fontsize=15)
        ax[1].set_xticks(daterange)
        ax[1].set_xticklabels(pd.to_datetime(daterange).strftime("%b %d"), rotation=70)
        ax[1].legend(['Adaptive Control Smoothed Case Count', 
                      'New rt.live Test-Adjusted Case Estimate', 
                      'New rt.live Infections Estimate'],
                     fontsize=15)

        plt.savefig(plotspath/f"{state} - Rt and Case Count Comparison")
        plt.close()


if __name__ == "__main__":

    # Folder structures and file names
    root    = cwd()
    data     = root/"data"
    plots    = root/"plots"
    if not data.exists():
        data.mkdir()
    if not plots.exists():
        plots.mkdir()

    # Get data case data
    df = import_and_clean_cases(data)

    # Run models for adaptive and rt.live old version
    # run_adaptive_model(df=df, CI=CI, smoothing=convolution(window=smoothing_window), filepath=data)
    # run_rtlive_old_model(df=df, filepath=data)
    # run_luis_model(df=df, filepath=data)
    # run_cori_model(filepath=root, rexepath=rexepath)

    # Pull CSVs of results
    adaptive_df    = get_adaptive_estimates(data)
    rt_live_new_df = get_new_rt_live_estimates(data)
    rt_live_old_df = get_old_rt_live_estimates(data)
    cori_df        = get_cori_estimates(data)
    luis_df        = get_luis_estimates(data)

    # Merge all results together
    merged_df      = adaptive_df.merge(rt_live_new_df, how='outer', on=['state','date'])
    merged_df      = merged_df.merge(rt_live_old_df, how='outer', on=['state','date'])
    merged_df      = merged_df.merge(cori_df, how='outer', on=['state','date'])
    merged_df      = merged_df.merge(luis_df, how='outer', on=['state','date'])

    ### Note - FIRST MERGE IS NOT A PERFECT MERGE
    ### 5777 full match on state-date
    ###  346 only in rt.live data (mostly early dates, < March 5th)
    ###    2 only in our data (West Virginia, 0 observed cases, doesn't matter)

    # Save CSV and plots
    merged_df.to_csv(data/"+rt_estimates_comparison.csv")
    make_state_plots(merged_df, plots)
