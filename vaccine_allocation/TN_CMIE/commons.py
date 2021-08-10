from pathlib import Path

import flat_table
import numpy as np
import pandas as pd
from epimargin.estimators import analytical_MPVS
from epimargin.etl.commons import download_data
from epimargin.etl.covid19india import data_path, get_time_series, load_all_data
from epimargin.smoothing import notched_smoothing

""" Common data loading/cleaning functions and constants """

data = (Path(__file__).parent/"../data").resolve()
print(data)

USD = 1/72

age_bin_labels = ["0-17", "18-29","30-39", "40-49", "50-59", "60-69","70+"]

# Rt estimation parameters
CI = 0.95
window = 14
gamma = 0.2
infectious_period = 5
smooth = notched_smoothing(window)

# simulation parameters
simulation_start = pd.Timestamp("Jan 1, 2021")
num_sims = 10000

# common vaccination parameters
immunity_threshold = 0.75
Rt_threshold = 0.2

# misc
state = "TN"
survey_date = "October 23, 2020"

# palette 
TN_color = "firebrick"
IN_color = "#292f36" #"slategrey"

no_vax_color          = "black"
contactrate_vax_color = "darkorange"
random_vax_color      = "royalblue"
mortality_vax_color   = "forestgreen"

# age_group_colors = ["cb3bbf","7b4edc","3984db","3ccaa6","5dca49","cabd49","ca444b"]
# age_group_colors = ["db57c0","956edf","579bdb","59dbab","75db57","dbd057","db5f57"]
age_group_colors = [ "#05668d", "#427aa1", "#679436", "#a5be00", "#ffcb77", "#d0393b", "#7a306c"]

#################################################################


# load covid19 india data 
def load_national_timeseries(download: bool = False) -> pd.DataFrame:
    print(":: loading case timeseries data")
    if download:
        download_data(data, 'timeseries.json', "https://api.covid19india.org/v3/")
    with (data/'timeseries.json').open("rb") as fp:
        df = flat_table.normalize(pd.read_json(fp)).fillna(0)
    df.columns = df.columns.str.split('.', expand = True)
    dates = np.squeeze(df["index"][None].values)
    return df.drop(columns = "index", level = 0).set_index(dates).stack([1, 2]).drop("UN", axis = 1)


print(":: loading admin data")
# load admin data on population
IN_age_structure = { # WPP2019_POP_F01_1_POPULATION_BY_AGE_BOTH_SEXES
    "0-17":   116880 + 117982 + 126156 + 126046,
    "18-29":  122505 + 117397,
    "30-39":  112176 + 103460,
    "40-49":   90220 +  79440,
    "50-59":   68876 +  59256,
    "60-69":   48891 +  38260,
    "70+":     24091 +  15084 +   8489 +   3531 + 993 + 223 + 48,
}

TN_age_structure = { 
    "0-17" : 15581526,
    "18-29": 15674833,
    "30-39": 11652016,
    "40-49":  9777265,
    "50-59":  6804602,
    "60-69":  4650978,
    "70+":    2858780,
}

N_j = np.array([20504724, 15674833, 11875848, 9777265, 6804602, 4650978, 2858780])

TN_IFRs = { 
    "0-17" : 0.00003,
    "18-29": 0.00003,
    "30-39": 0.00010,
    "40-49": 0.00032,
    "50-59": 0.00111,
    "60-69": 0.00264,
    "70+"  : 0.00588,
}

median_ages = { 
    "0-17" : 8.5,
    "18-29": 23.5,
    "30-39": 34.5,
    "40-49": 44.5,
    "50-59": 54.5,
    "60-69": 64.5,
    "70+"  : 85,
}

age_bins = list(median_ages.keys())

district_IFR = pd.read_csv(data/"district_estimates.csv").set_index("district")
district_IFR.drop(columns = [_ for _ in district_IFR.columns if "Unnamed" in _], inplace = True)

YLLs = pd.read_stata(data/"life_expectancy_2009_2013_collapsed.dta")\
    .set_index("state").loc["Tamil Nadu"]\
    .rename(lambda row: age_bins[int(row[-1]) - 1])

district_populations = { 
    'Ariyalur'       :   754_894, # 'Ariyalur'
    'Chengalpattu'   : 2_556_244, # 'Chengalpattu'
    'Chennai'        : 4_646_732, # 'Chennai'
    'Coimbatore'     : 3_458_045, # 'Coimbatore'
    'Cuddalore'      : 2_605_914, # 'Cuddalore'
    'Dharmapuri'     : 1_506_843, # 'Dharmapuri'
    'Dindigul'       : 2_159_775, # 'Dindigul'
    'Erode'          : 2_251_744, # 'Erode'
    'Kallakurichi'   : 1_370_281, # 'Kallakurichi'
    'Kancheepuram'   : 1_166_401, # 'Kanchipuram'
    'Kanyakumari'    : 1_870_374, # 'Kanniyakumari'
    'Karur'          : 1_064_493, # 'Karur'
    'Krishnagiri'    : 1_879_809, # 'Krishnagiri'
    'Madurai'        : 3_038_252, # 'Madurai'
 #  'Mayiladuthurai' :   918_356, # 'Mayiladuthurai'
    'Nagapattinam'   :   697_069, # 'Nagapattinam'
    'Namakkal'       : 1_726_601, # 'Namakkal'
    'Nilgiris'       :   735_394, # 'Nilgiris'
    'Perambalur'     :   565_223, # 'Perambalur'
    'Pudukkottai'    : 1_618_345, # 'Pudukkottai'
    'Ramanathapuram' : 1_353_445, # 'Ramanathapuram'
    'Ranipet'        : 1_210_277, # 'Ranipet'
    'Salem'          : 3_482_056, # 'Salem'
    'Sivaganga'      : 1_339_101, # 'Sivagangai'
    'Tenkasi'        : 1_407_627, # 'Tenkasi'
    'Thanjavur'      : 2_405_890, # 'Thanjavur'
    'Theni'          : 1_245_899, # 'Theni'
    'Thiruvallur'    : 3_728_104, # 'Tiruvallur'
    'Thiruvarur'     : 1_264_277, # 'Tiruvarur'
    'Thoothukkudi'   : 1_750_176, # 'Thoothukudi'
    'Tiruchirappalli': 2_722_290, # 'Tiruchirappalli'
    'Tirunelveli'    : 1_665_253, # 'Tirunelveli'
    'Tirupathur'     : 1_111_812, # 'Tirupattur'
    'Tiruppur'       : 2_479_052, # 'Tiruppur'
    'Tiruvannamalai' : 2_464_875, # 'Tiruvannamalai'
    'Vellore'        : 1_614_242, # 'Vellore'
    'Viluppuram'     : 2_093_003, # 'Viluppuram'
    'Virudhunagar'   : 1_942_288, # 'Virudhunagar'
}

district_codes = { 
    "Chennai"        :  92,
    "Coimbatore"     : 103,
    "Cuddalore"      : 104,
    "Dharmapuri"     : 123,
    "Dindigul"       : 130,
    "Erode"          : 140,
    "Kancheepuram"   : 234,
    "Kanyakumari"    : 238,
    "Krishnagiri"    : 276,
    "Madurai"        : 290,
    "Nagapattinam"   : 325,
    "Perambalur"     : 365,
    "Pudukkottai"    : 371,
    "Ramanathapuram" : 389,
    "Salem"          : 410,
    "Sivaganga"      : 443,
    "Thanjavur"      : 472,
    "Theni"          : 473,
    "Thiruvallur"    : 474,
    "Thiruvarur"     : 476,
    "Thoothukkudi"   : 477,
    "Tiruchirappalli": 479,
    "Tirunelveli"    : 480,
    "Tiruppur"       : 481,
    "Tiruvannamalai" : 482,
    "Vellore"        : 501,
    "Viluppuram"     : 503,
    "Virudhunagar"   : 504,
}

# laxminarayan contact matrix 
laxminarayan_contact_matrix = np.array([
    [4391, 9958, 8230, 5904, 6002, 2173, 664],
    [1882 + 11179, 41980, 29896, 23127, 22914, 7663, 1850+228],
    [2196 + 13213, 35625, 31752, 21777, 22541, 7250, 1796+226],
    [1097 + 9768, 27701, 23371, 18358, 17162, 6040, 1526+214],
    [1181 + 8314, 26992, 22714, 17886, 18973, 6173, 1633+217],
    [358 + 2855, 7479, 6539, 5160, 5695, 2415, 597+82],
    [75+15 + 693+109, 2001+282, 1675+205, 1443+178, 1482+212, 638+72, 211+18+15+7]
])

# normalize
IN_age_structure_norm = sum(IN_age_structure.values())
IN_age_ratios = np.array([v/IN_age_structure_norm for v in IN_age_structure.values()])

TN_age_structure_norm = sum(TN_age_structure.values())
TN_age_ratios = np.array([v/TN_age_structure_norm for v in TN_age_structure.values()])
split_by_age = lambda v: (v * TN_age_ratios).astype(int)

TN_IFR_norm = sum(TN_IFRs.values())
TN_IFR_ratios = np.array([v/TN_IFR_norm for v in TN_IFRs.values()])
split_by_IFR = lambda v: (v * TN_IFR_ratios).astype(int)

# redefined estimators
TN_death_structure = pd.Series({ 
    "0-17" : 32,
    "18-29": 121,
    "30-39": 368,
    "40-49": 984,
    "50-59": 2423,
    "60-69": 3471,
    "70+"  : 4339,
})


TN_recovery_structure = pd.Series({ 
    "0-17": 5054937,
    "18-29": 4819218,
    "30-39": 3587705,
    "40-49": 3084814,
    "50-59": 2178817,
    "60-69": 1313049,
    "70+": 738095,
})

TN_infection_structure = TN_death_structure + TN_recovery_structure
fS = pd.Series(TN_age_ratios)[:, None]
fD = (TN_death_structure     / TN_death_structure    .sum())[:, None]
fR = (TN_recovery_structure  / TN_recovery_structure .sum())[:, None]
fI = (TN_infection_structure / TN_infection_structure.sum())[:, None]

india_pop = pd.read_csv(data/"india_pop.csv", names = ["state", "population"], index_col = "state").to_dict()["population"]

# download district-level data 
def get_state_timeseries(states = ["Tamil Nadu"], download: bool = False) -> pd.DataFrame:
    paths = {"v3": [data_path(i) for i in (1, 2)], "v4": [data_path(i) for i in range(3, 25)]}
    if download:
        for target in paths['v3'] + paths['v4']: 
            download_data(data, target)
    return load_all_data(v3_paths = [data/filepath for filepath in paths['v3']],  v4_paths = [data/filepath for filepath in paths['v4']])\
        .query("detected_state in @states" if states != "*" else "detected_state != 'NULL'", engine = "python")\
        .pipe(lambda _: get_time_series(_, ["detected_state", "detected_district"]))\
        .drop(columns = ["date", "time", "delta", "logdelta"])\
        .rename(columns = {
            "Deceased":     "dD",
            "Hospitalized": "dT",
            "Recovered":    "dR"
        })


def case_death_timeseries(states = ["Tamil Nadu", "Punjab", "Maharashtra", "Bihar", "Assam"], download = False):
    ts = get_state_timeseries(states, download)
    ts_index = pd.date_range(start = ts.index.get_level_values(-1).min(), end = ts.index.get_level_values(-1).max(), freq = "D")

    return ts.unstack(-1)\
        .fillna(0)\
        .stack()\
        .swaplevel(-1, 0)\
        .reindex(ts_index, level = 0, fill_value = 0)\
        .swaplevel(-1, 0)


def get_TN_scaling_ratio(df, state = "TN", survey_date = "October 23, 2020"):
    print(":: seroprevalence scaling")
    TN_pop = india_pop["Tamil Nadu"]
    TN_sero_breakdown = np.array([0.311, 0.311, 0.320, 0.333, 0.320, 0.272, 0.253]) # from TN sero, assume 0-18 sero = 18-30 sero
    TN_seropos = split_by_age(TN_pop) @ TN_sero_breakdown/TN_pop

    # scaling
    dT_conf = df[state].loc[:, "delta", "confirmed"] 
    dT_conf_smooth = pd.Series(smooth(dT_conf), index = dT_conf.index)
    T_conf_smooth = dT_conf_smooth.cumsum().astype(int)
    T = T_conf_smooth[survey_date]
    T_sero = (TN_pop * TN_seropos)
    T_ratio = T_sero/T
    return T_ratio

def assemble_TN_simulation_initial_conditions():
    ts = get_state_timeseries()
    rows = []
    district_age_pop = pd.read_csv(data/"district_age_estimates_padded.csv").dropna().set_index("district")
    for (district, sero_0, N_0, sero_1, N_1, sero_2, N_2, sero_3, N_3, sero_4, N_4, sero_5, N_5, sero_6, N_6, N_tot) in district_age_pop.filter(items = list(district_codes.keys()), axis = 0).itertuples():
        dT_conf = ts.loc[district].dT
        dT_conf = dT_conf.reindex(pd.date_range(dT_conf.index.min(), dT_conf.index.max()), fill_value = 0)
        dT_conf_smooth = pd.Series(smooth(dT_conf), index = dT_conf.index).clip(0).astype(int)
        T_conf_smooth  = dT_conf_smooth.cumsum().astype(int)
        T_conf = T_conf_smooth[survey_date]
        
        dR_conf = ts.loc[district].dR
        dR_conf = dR_conf.reindex(pd.date_range(dR_conf.index.min(), dR_conf.index.max()), fill_value = 0)
        dR_conf_smooth = pd.Series(smooth(dR_conf), index = dR_conf.index).clip(0).astype(int)
        R_conf_smooth  = dR_conf_smooth.cumsum().astype(int)
        R_conf = R_conf_smooth[survey_date]
        R_sero = (sero_0*N_0 + sero_1*N_1 + sero_2*N_2 + sero_3*N_3 + sero_4*N_4 + sero_5*N_5 + sero_6*N_6)
        R_ratio = R_sero/R_conf 
        R0 = R_conf_smooth[simulation_start] * R_ratio

        dD_conf = ts.loc[district].dD
        dD_conf = dD_conf.reindex(pd.date_range(dD_conf.index.min(), dD_conf.index.max()), fill_value = 0)
        dD_conf_smooth = pd.Series(smooth(dD_conf), index = dD_conf.index).clip(0).astype(int)
        D_conf_smooth  = dD_conf_smooth.cumsum().astype(int)
        D0 = D_conf_smooth[simulation_start]
        
        T_sero = R_sero + D0 
        T_ratio = T_sero/T_conf
        T0 = T_conf_smooth[simulation_start] * T_ratio

        S0 = N_tot - T0
        dD0 = dD_conf_smooth[simulation_start]
        dT0 = dT_conf_smooth[simulation_start] * T_ratio
        I0 = max(0, (T0 - R0 - D0))

        (Rt_dates, Rt_est, *_) = analytical_MPVS(T_ratio * dT_conf_smooth, CI = CI, smoothing = lambda _:_, totals = False)
        Rt = dict(zip(Rt_dates, Rt_est))

        rows.append((district, sero_0, N_0, sero_1, N_1, sero_2, N_2, sero_3, N_3, sero_4, N_4, sero_5, N_5, sero_6, N_6, N_tot, Rt[simulation_start], S0, I0, R0, D0, dT0, dD0))
    
    pd.DataFrame(
        rows, 
        columns = ["district", "sero_0", "N_0", "sero_1", "N_1", "sero_2", "N_2", "sero_3", "N_3", "sero_4", "N_4", "sero_5", "N_5", "sero_6", "N_6", "N_tot", "Rt", "S0", "I0", "R0", "D0", "dT0", "dD0"]
    ).to_csv(data/"simulation_initial_conditions.csv")
