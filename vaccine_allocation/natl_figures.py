import sys
from itertools import chain, islice, product

import epimargin.plots as plt
import geopandas as gpd
import mapclassify
from epimargin.etl.covid19india import state_name_lookup
from studies.vaccine_allocation.commons import *
from studies.vaccine_allocation.epi_simulations import *
from tqdm import tqdm

# data loading
N_jk_dicts = districts_to_run.filter(like = "N_", axis = 1).to_dict()

def parse_tag(tag):
    return tuple(int(_) if _.isnumeric() else _ for _ in tag.split("_", 1))

def load_metrics(filename):
    npz = np.load(filename)
    return {parse_tag(tag): npz[tag] for tag in npz.files}

def map_pop_dict(agebin, state, district):
    return N_jk_dicts[f"N_{agebin_labels.index(agebin)}"][state, district]

# calculations
def get_all_tev(phi = 50, policy = "random", states = "*"):
    if states == "*":
        districts = districts_to_run.index
    else:
        districts = districts_to_run[districts_to_run.index.isin(states, level = 0)].index
    district_tev = { 
        (state, district): np.load(fig_src / f"per_capita_TEV_{state_name_lookup[state]}_{district}_phi{phi}_{policy}.npz")['arr_0']
        for (state, district) in tqdm(districts)
    }
    all_tev = pd.concat([
        pd.DataFrame(np.median(v, axis = 1))\
            .assign(state = state, district = district)\
            .reset_index()\
            .rename(columns = {"index": "t"})\
            .rename(columns = dict(enumerate(agebin_labels)))\
            .set_index(["t", "state", "district"])
        for ((state, district), v) in tqdm(district_tev.items())
    ], axis = 0)\
        .stack()\
        .reset_index()\
        .rename(columns = {"level_3": "agebin", 0: "pc_tev"})
    all_tev["_t"]  = -all_tev["t"]
    all_tev["pop"] = [map_pop_dict(b, s, d) for (b, s, d) in all_tev[["agebin", "state", "district"]].itertuples(index = False)]
    all_tev["pc_tev_usd"] = all_tev["pc_tev"] * USD 
    all_tev.sort_values(["_t", "pc_tev_usd"], ascending = False, inplace = True)
    all_tev.drop(columns = ["_t"], inplace = True) 
    all_tev.set_index("t", inplace = True)
    all_tev["num_vax"] = all_tev["pop"].groupby(level = 0).cumsum()

    return all_tev 

def get_within_state_wtp_ranking(state, district_WTP, phi, vax_policy = "random"):
    all_wtp = pd.concat([
        pd.DataFrame(np.median(v, axis = 1))\
            .assign(district = district)\
            .reset_index()\
            .rename(columns = {"index": "t"})\
            .rename(columns = dict(enumerate(agebin_labels)))\
            .set_index(["t", "district"])
        for ((district, tag), v) in district_WTP.items() 
        if tag == f"{phi}_{vax_policy}"
    ], axis = 0)\
        .stack()\
        .reset_index()\
        .rename(columns = {"level_2": "agebin", 0: "agg_wtp"})

    all_wtp["_t"] = -all_wtp["t"]
    all_wtp["pop"]        = [map_pop_dict(b, (state, d)) for (b, d) in all_wtp[["agebin", "district"]].itertuples(index = False)]
    all_wtp["wtp_pc"]     = all_wtp["agg_wtp"]/all_wtp["pop"]
    all_wtp["wtp_pc_usd"] = all_wtp["wtp_pc"] * USD 

    all_wtp.sort_values(["_t", "wtp_pc_usd"], ascending = False, inplace = True)
    all_wtp.drop(columns = ["_t"], inplace = True) 
    all_wtp.set_index("t", inplace = True)
    all_wtp["num_vax"] = all_wtp["pop"].groupby(level = 0).cumsum()

    return all_wtp

def aggregate_static_percentiles(src, pattern, sum_axis = 0, pct_axis = 0, lim = None, drop = None):
    predicate = (lambda _: True) if not drop else (lambda _: all(d not in str(_) for d in drop))
    total = np.array(0)
    for npz in tqdm(islice(filter(predicate, src.glob(pattern)), lim)):
        total = total + np.load(npz)['arr_0']
    return np.percentile(total, [50, 5, 95], axis = pct_axis)

def aggregate_dynamic_percentiles(src, pattern, sum_axis = 1, pct_axis = 0, t = 0, lim = None, drop = None):
    predicate = (lambda _: True) if not drop else (lambda _: all(d not in str(_) for d in drop))
    total = np.array(0)
    for npz in tqdm(islice(filter(predicate, src.glob(pattern)), lim)):
        total = total + np.load(npz)['arr_0'][t].sum(axis = sum_axis)
    return np.percentile(total, [50, 5, 95], axis = pct_axis)

def aggregate_dynamic_percentiles_by_age(src, pattern, sum_axis = 1, pct_axis = 0, t = 0, lim = None, drop = None):
    predicate = (lambda _: True) if not drop else (lambda _: all(d not in str(_) for d in drop))
    total = np.array(0)
    for npz in tqdm(islice(filter(predicate, src.glob(pattern)), lim)):
        total = total + np.load(npz)['arr_0'][t]
    return np.percentile(total, [50, 5, 95], axis = pct_axis)

# plotting functions
def outcomes_per_policy(percentiles, metric_label, fmt, 
    phis            = [25, 50, 100, 200], 
    reference       = (25, "no_vax"), 
    reference_color = no_vax_color,
    vax_policies    =  ["contact", "random", "mortality"],
    policy_colors   = [contactrate_vax_color, random_vax_color, mortality_vax_color],
    policy_labels   = ["contact rate priority", "random assignment", "mortality priority"],
    spacing = 0.2):
    fig = plt.figure()

    md, lo, hi = percentiles[reference]
    *_, bars = plt.errorbar(x = [0], y = [md], yerr = [[md - lo], [hi - md]], figure = fig,
        fmt = fmt, color = reference_color, label = "no vaccination", ms = 12, elinewidth = 5)
    [_.set_alpha(0.5) for _ in bars]
    plt.hlines(md, xmin = -1, xmax = len(phis) + 0.5, linestyles = "dotted", colors = reference_color)

    for (i, phi) in enumerate(phis, start = 1):
        for (j, (vax_policy, color, label)) in enumerate(zip(vax_policies, policy_colors, policy_labels)):
            md, lo, hi = percentiles[phi, vax_policy]
            *_, bars = plt.errorbar(
                x = [i + spacing * (j - 1)], 
                y = [md], yerr = [[md - lo], [hi - md]], 
                figure = fig,
                fmt = fmt, 
                color = color, 
                label = label if i == 1 else None, 
                ms = 12, elinewidth = 5,
            )
            [_.set_alpha(0.5) for _ in bars]

    plt.legend(ncol = 1 + len(vax_policies), fontsize = "20", loc = "lower center", bbox_to_anchor = (0.5, 1))
    # plt.xticks(range(len(phis) + 1), [f"$\phi = {phi}$%" for phi in ([0] + phis)], fontsize = "20")
    plt.xticks(range(len(phis) + 1), [f"$phi = {phi}$%" for phi in ([0] + phis)], fontsize = "20")
    plt.yticks(fontsize = "20")
    plt.PlotDevice().ylabel(f"{metric_label}\n")
    plt.gca().grid(False, axis = "x")
    ymin, ymax = plt.ylim()
    plt.vlines(x = [0.5 + _ for _ in range(len(phis))], ymin = ymin, ymax = ymax, color = "gray", alpha = 0.5, linewidths = 2)
    plt.ylim(ymin, ymax)
    plt.xlim(-0.5, len(phis) + 0.5)

def plot_component_breakdowns(color, white, colorlabel, whitelabel, semilogy = False, ylabel = "WTP (USD)"):
    fig, ax = plt.subplots()
    ax.bar(range(7), white * USD, bottom = color * USD, color = "white",       edgecolor = agebin_colors, linewidth = 2, figure = fig)
    ax.bar(range(7), color * USD,                       color = agebin_colors, edgecolor = agebin_colors, linewidth = 2, figure = fig)
    ax.bar(range(7), [0], label = whitelabel, color = "white", edgecolor = "black", linewidth = 2)
    ax.bar(range(7), [0], label = colorlabel, color = "black", edgecolor = "black", linewidth = 2)

    plt.xticks(range(7), agebin_labels, fontsize = "20")
    plt.yticks(fontsize = "20")
    plt.legend(ncol = 4, fontsize = "20", loc = "lower center", bbox_to_anchor = (0.5, 1))
    plt.PlotDevice().ylabel(f"{ylabel}\n")
    if semilogy: plt.semilogy()

def plot_state_age_distribution(percentiles, ylabel, fmt, district_spacing = 1.5, n = 5, age_spacing = 0.1, rotation = 0, ymin = 0, ymax = 1000):
    fig = plt.figure()
    state_ordering = list(sorted(
        percentiles.keys(), 
        key = lambda k: percentiles[k][0].max(), 
        reverse = True)
    )
    for (i, state) in enumerate(state_ordering[:n]):
        ylls = percentiles[state]
        for j in range(7):
            plt.errorbar(
                x = [district_spacing * i + age_spacing * (j - 3)],
                y = ylls[0, 6-j],
                yerr = [
                    [(ylls[0, 6-j] - ylls[1, 6-j])],
                    [(ylls[2, 6-j] - ylls[0, 6-j])]
                ], 
                fmt = fmt,
                color = agebin_colors[6-j],
                figure = fig,
                label = None if i > 0 else agebin_labels[6-j],
                ms = 12, elinewidth = 5
            )
    plt.xticks(
        [1.5 * _ for _ in range(n)],
        state_ordering,
        rotation = rotation,
        fontsize = "20"
    )
    plt.yticks(fontsize = "20")
    # plt.legend(title = "age bin", title_fontsize = "20", fontsize = "20", ncol = 7, 
    plt.legend(fontsize = "20", ncol = 7, 
        loc = "lower center", bbox_to_anchor = (0.5, 1))
    plt.vlines(x = [0.75 + 1.5 * _ for _ in range(n-1)], ymin = ymin, ymax = ymax, color = "gray", alpha = 0.5, linewidths = 4)
    plt.ylim(ymin, ymax)
    plt.gca().grid(False, axis = "x")
    plt.PlotDevice().ylabel(f"{ylabel}\n")

if __name__ == "__main__":
    figs_to_run = set(sys.argv[1:])
    run_all = len(figs_to_run) == 0 # if none specified, run all
    src = fig_src
    phis = [int(_ * 365 * 100) for _ in phi_points]
    params = list(chain([(phis[0], "novax",)], product(phis, ["contact", "random", "mortality"])))
    recalculate = False
    # policy outcomes
    # 2A: deaths
    if "2A" in figs_to_run or "deaths" in figs_to_run or run_all:
        death_percentiles = {
            p: aggregate_static_percentiles(src, f"deaths*phi{'_'.join(map(str, p))}.npz")
            for p in params 
        }
        outcomes_per_policy(death_percentiles, "deaths", "o", 
            reference = (25, "novax"), 
            phis = [25, 50, 100, 200], 
            vax_policies = ["contact", "random", "mortality"], 
            policy_colors = [contactrate_vax_color, random_vax_color, mortality_vax_color], 
            policy_labels = ["contact rate", "random", "mortality"]
        )
        plt.show()

    ## 2B: VSLY
    if "2B" in figs_to_run or "VSLY" in figs_to_run or run_all:
        VSLY_percentiles = {
            p: aggregate_dynamic_percentiles(src, f"total_VSLY_*phi{'_'.join(map(str, p))}.npz", drop = ["_SK_", "_NL_"])
            for p in tqdm(params)
        }

        outcomes_per_policy(
            {k: v * USD/(1e9) for (k, v) in VSLY_percentiles.items()}, "VSLY (USD, billions)", "D",
            reference = (25, "novax"), 
            phis = [25, 50, 100, 200], 
            vax_policies = ["contact", "random", "mortality"], 
            policy_colors = [contactrate_vax_color, random_vax_color, mortality_vax_color], 
            policy_labels = ["contact rate", "random", "mortality"]
        )
        plt.show()

    ## 2C: TEV
    if "2C" in figs_to_run or "TEV" in figs_to_run or "WTP" in figs_to_run or run_all:
        TEV_percentiles = {
            p: aggregate_dynamic_percentiles(src, f"total_TEV*phi{'_'.join(map(str, p))}.npz", drop = ["_SK_", "_NL_"])
            for p in tqdm(params)
        }

        outcomes_per_policy({k: v * USD/(1e9) for (k, v) in TEV_percentiles.items()}, "TEV (USD, billions)", "D", 
            reference = (25, "novax"), 
            phis = [25, 50, 100, 200], 
            vax_policies = ["contact", "random", "mortality"], 
            policy_colors = [contactrate_vax_color, random_vax_color, mortality_vax_color], 
            policy_labels = ["contact rate", "random", "mortality"]
        ) 
        plt.gca().ticklabel_format(axis = "y", useOffset = False)
        plt.show()

    ## 2D: state x age 
    if "2D" in figs_to_run or "TEV_state_age" in figs_to_run or run_all:
        # focus_state_TEV = { 
        #     state: aggregate_dynamic_percentiles_by_age(src, f"total_TEV_{state}*phi50_random.npz", sum_axis = 0, pct_axis = 0)
        #     for state in tqdm([state_name_lookup[_] for _ in  focus_states])
        # }
        focus_state_TEV = {state: np.array(0) for state in focus_states}
        focus_state_agepop = districts_to_run.loc[focus_states].filter(regex = "N_[0-6]", axis = 1).sum(level = 0)
        for (state, district) in districts_to_run.loc[focus_states].index:
            state_code = state_name_lookup[state]
            state_age_weight = districts_to_run.loc[state, district].filter(regex = "N_[0-6]", axis = 0)/focus_state_agepop.loc[state]
            median_tev = np.load(fig_src / f"per_capita_TEV_{state_code}_{district}_phi50_random.npz")['arr_0'][0]
            focus_state_TEV[state] = focus_state_TEV[state] + state_age_weight.values * median_tev

        plot_state_age_distribution({k: v * USD for k, v in focus_state_TEV.items()}, "per capita TEV (USD)", "D", ymin = 0, ymax = 1000)
        plt.show()

    # appendix: YLL
    if "YLL" in figs_to_run or run_all:
        YLL_percentiles = {
            p: aggregate_static_percentiles(src, f"YLL_*phi{'_'.join(map(str, p))}.npz")
            for p in tqdm(params)
        }
        outcomes_per_policy({k: v/1e6 for (k, v) in YLL_percentiles.items()}, "YLL (millions)", "o", 
            reference = (25, "novax"), 
            phis = [25, 50, 100, 200], 
            vax_policies = ["contact", "random", "mortality"], 
            policy_colors = [contactrate_vax_color, random_vax_color, mortality_vax_color], 
            policy_labels = ["contact rate", "random", "mortality"]
        )
        plt.show()

    if "VSL" in figs_to_run or run_all:
        VSL_percentiles = {
            p: aggregate_static_percentiles(src, f"VSL_*phi{'_'.join(map(str, p))}.npz")
            for p in tqdm(list(product([25, 50, 100, 200], ["contact", "random", "mortality"])))
        }
        VSL_percentiles[25, "novax"] = np.array([0, 0, 0])
        outcomes_per_policy({k: v * USD/(1e6) for (k, v) in VSL_percentiles.items()}, "VSL (USD, millions)", "D", 
            reference = (25, "novax"), 
            phis = [25, 50, 100, 200], 
            vax_policies = ["contact", "random", "mortality"], 
            policy_colors = [contactrate_vax_color, random_vax_color, mortality_vax_color], 
            policy_labels = ["contact rate", "random", "mortality"]
        )
        plt.show()

    # 3A: health/consumption
    if "3A" in figs_to_run or run_all:
        summed_TEV_hlth = np.median(np.nansum([np.load(s)['arr_0'] for s in tqdm(src.glob("dTEV_health*"), total = len(districts_to_run))], axis = 0), axis = 0)
        summed_TEV_cons = np.median(np.nansum([np.load(s)['arr_0'] for s in tqdm(src.glob("dTEV_cons*"),   total = len(districts_to_run))], axis = 0), axis = 0)
        plot_component_breakdowns(summed_TEV_hlth, summed_TEV_cons, "health", "consumption", semilogy = True, ylabel = "age-weighted TEV (USD)")
        plt.show()

        summed_TEV_priv = np.median(np.nansum([np.load(s)['arr_0'] for s in tqdm(src.glob("dTEV_priv*"), total = len(districts_to_run))], axis = 0), axis = 0)
        summed_TEV_extn = np.median(np.nansum([np.load(s)['arr_0'] for s in tqdm(src.glob("dTEV_extn*"), total = len(districts_to_run))], axis = 0), axis = 0)
        plot_component_breakdowns(summed_TEV_priv, summed_TEV_extn, "private", "external", semilogy = False, ylabel = "age-weighted TEV (USD)")
        plt.show()

    if "3B" in figs_to_run or run_all:
        vax_policy = "mortality"
        if recalculate:
            print(25)
            all_tev_25  = get_all_tev(phi = 25, policy = vax_policy)
            all_tev_25.to_csv(data / f"all_tev_25_{vax_policy}.csv")
            print(50)
            all_tev_50  = get_all_tev(phi = 50, policy = vax_policy)
            all_tev_50.to_csv(data / f"all_tev_50_{vax_policy}.csv")
            print(100)
            all_tev_100 = get_all_tev(phi = 100, policy = vax_policy)
            all_tev_100.to_csv(data / f"all_tev_100_{vax_policy}.csv")
            print(200)
            all_tev_200 = get_all_tev(phi = 200, policy = vax_policy)
            all_tev_200.to_csv(data / f"all_tev_200_{vax_policy}.csv")
        else:
            all_tev_25  = pd.read_csv(data / f"all_tev_25_{vax_policy}.csv").set_index("t")
            all_tev_50  = pd.read_csv(data / f"all_tev_50_{vax_policy}.csv").set_index("t")
            all_tev_100 = pd.read_csv(data / f"all_tev_100_{vax_policy}.csv").set_index("t")
            all_tev_200 = pd.read_csv(data / f"all_tev_200_{vax_policy}.csv").set_index("t")

        # plot static benchmark
        N_natl = districts_to_run.N_tot.sum()
        figure = plt.figure()
        x_pop = list(chain(*zip(all_tev_50.loc[0]["num_vax"].shift(1).fillna(0) * 100/N_natl, all_tev_50.loc[0]["num_vax"] * 100/N_natl)))
        y_tev = list(chain(*zip(all_tev_50.loc[0]["pc_tev_usd"], all_tev_50.loc[0]["pc_tev_usd"])))
        static, = plt.plot(x_pop, y_tev, figure = figure, color = "grey", linewidth = 2)
        lines = [static]
        plt.xticks(fontsize = "20")
        plt.yticks(fontsize = "20")
        plt.PlotDevice().ylabel("TEV (USD)\n").xlabel("\npercentage of country vaccinated")
        # plt.ylim(0, 1600)
        # plt.xlim(left = 0, right = 100)

        lines.append(plt.plot(0, 0, color = "white")[0])

        # plot dynamic curve 
        phis = [25, 50, 100, 200]
        for (phi, all_tev) in zip(phis, [all_tev_25, all_tev_50, all_tev_100, all_tev_200]):
            daily_doses = phi * percent * annually * N_natl
            distributed_doses = 0
            x_pop = []
            y_tev = []
            t_vax = []
            ranking = 0
            for t in range(simulation_range):
                tev = all_tev.loc[t].reset_index()
                ranking = tev[(tev.index >= ranking) & (tev.num_vax > distributed_doses)].index.min()
                if np.isnan(ranking):
                    break
                x_pop += [100 * (distributed_doses)/N_natl, 100 * (distributed_doses + daily_doses)/N_natl]
                t_vax += [t, t+1]
                y_tev += [tev.iloc[ranking].pc_tev_usd]*2
                distributed_doses += daily_doses
            # lines += [plt.plot(x_pop, y_tev, label = f"dynamic, {vax_policy}, $\phi = ${phi}%", figure = figure)[0]]
            lines += [plt.plot(x_pop, y_tev, label = f"dynamic, {vax_policy}, $phi = ${phi}%", figure = figure)[0]]
        plt.legend(
            lines,
            # ["static, t = 0, $\phi = $50%", ""]  + [f"dynamic, {vax_policy}, $\phi = ${phi}%" for phi in phis],
            ["static, t = 0, $phi = $50%", ""]  + [f"dynamic, {vax_policy}, $phi = ${phi}%" for phi in phis],
            title = "allocation", title_fontsize = "24", fontsize = "20")
        plt.xticks(fontsize = "20")
        plt.yticks(fontsize = "20")
        plt.PlotDevice().ylabel("TEV (USD)\n").xlabel("\npercentage of country vaccinated")
        plt.ylim(0, 1600)
        plt.xlim(left = 0, right = 100)
        plt.show()

    # 3C: YLL per million choropleth
    if "3C" in figs_to_run or run_all:
        india = gpd.read_file(data/"india.geojson")\
            .drop(columns = ["id", "dt_code", "st_code", "year"])\
            .rename(columns = {"st_nm": "state"})\
            .set_index(["state", "district"])\
            .rename(index = lambda s: s.replace(" and ", " And "))\
            .assign(
                dissolve_state    = lambda _:_.index.get_level_values(0), 
                dissolve_district = lambda _:np.where(
                    _.index.isin(coalesce_states, level = 0),
                    _.index.get_level_values(0), 
                    _.index.get_level_values(1)))\
            .dissolve(["dissolve_state", "dissolve_district"])\
            .pipe(lambda _:_.reindex(_.index.set_names(["state", "district"])))\
            .sort_index()
        def load_median_YLL(state_district, phi = 50, vax_policy = "random", src = src):
            state, district = state_district
            state = state_name_lookup[state]
            try:
                return np.median(np.load(src/f"YLL_{state}_{district}_phi{phi}_{vax_policy}.npz")['arr_0'])
            except FileNotFoundError:
                # return np.nan
                return 0

        districts = districts_to_run.copy()\
            .assign(YLL = districts_to_run.index.map(load_median_YLL))\
            .assign(YLL_per_mn = lambda df: df["YLL"]/(df["N_tot"]/1e6))

        fig, ax = plt.subplots(1, 1)
        scheme = mapclassify.UserDefined(districts.YLL_per_mn, [0, 125, 250, 400, 600, 900, 1200, 1600, 2500, 5000, 7500])  # ~deciles
        scheme = mapclassify.UserDefined(districts.YLL_per_mn, [0, 600, 1200, 2000, 2400, 3000, 3600, 4000, 4500, 5550, 9000])  # ~deciles
        districts["category"] = scheme.yb
        india.join(districts["category"].astype(int))\
            .drop(labels = "Andaman And Nicobar Islands")\
            .plot(
            column = "category", 
            linewidth = 0.1,
            edgecolor = "k",
            ax = ax, 
            legend = True,
            categorical = True,
            cmap = "plasma",
            missing_kwds = { 
                "color": "lightgrey",
                "label": "not available"
            }, 
            legend_kwds = { 
                "title": "YLL per million",
                "title_fontsize": "20", 
                "fontsize": "20",
                "ncol": 3
            }
        )
        plt.gca().axis("off")
        plt.subplots_adjust(left=0, bottom=0, right=1, top=1)
        texts = plt.gca().get_legend().texts
        lc = scheme.get_legend_classes()
        print(scheme)
        print(texts)
        texts[0].set_text("0")
        for (i, txt) in enumerate(texts[1:-1]):
            idx = int(txt.get_text().replace(".0", ""))
            txt.set_text(lc[idx].replace(".00", ""))
        fig.set_size_inches((16.8 ,  9.92*2))
        plt.show()

    # consumption graph
    if "consumption" in figs_to_run:
        c_p0v0_200_mortality = np.mean(sum(np.load(_)['arr_0'] for _ in src.glob("age_weight_c_p0v0*phi200_mortality*")), axis = 1)
        c_p1v0_200_mortality = np.mean(sum(np.load(_)['arr_0'] for _ in src.glob("age_weight_c_p1v0*phi200_mortality*")), axis = 1)
        c_p1v1_200_mortality = np.mean(sum(np.load(_)['arr_0'] for _ in src.glob("age_weight_c_p1v1*phi200_mortality*")), axis = 1)

        fig = plt.figure()
        for (i, (color, label)) in enumerate(zip(agebin_colors, agebin_labels)):
            plt.plot(c_p0v0_200_mortality[:, i], color = color, figure = fig, label = label)
        plt.title("c_p0v0", loc = "left", fontsize = 20)
        plt.legend()

        fig = plt.figure()
        for (i, (color, label)) in enumerate(zip(agebin_colors, agebin_labels)):
            plt.plot(c_p1v0_200_mortality[:, i], color = color, figure = fig, label = label)
        plt.title("c_p1v0", loc = "left", fontsize = 20)
        plt.legend()
        
        fig = plt.figure()
        for (i, (color, label)) in enumerate(zip(agebin_colors, agebin_labels)):
            plt.plot(c_p1v1_200_mortality[:, i], color = color, figure = fig, label = label)
        plt.title("c_p1v1", loc = "left", fontsize = 20)
        plt.legend()
        plt.show()

    # per state supplements:
    if "focus-states" in figs_to_run:
        vax_policy = "mortality"
        all_tev_25  = pd.read_csv(data / f"all_tev_25_{vax_policy}.csv").set_index("t")
        all_tev_50  = pd.read_csv(data / f"all_tev_50_{vax_policy}.csv").set_index("t")
        all_tev_100 = pd.read_csv(data / f"all_tev_100_{vax_policy}.csv").set_index("t")
        all_tev_200 = pd.read_csv(data / f"all_tev_200_{vax_policy}.csv").set_index("t")

        for state in focus_states:
            print(state)
            state_code = state_name_lookup[state]
            
            # district_TEV = {district: np.array(0) for district in districts_to_run.loc[state].index}
            # focus_state_agepop = districts_to_run.loc[state].filter(regex = "N_[0-6]", axis = 1).sum(axis = 0)
            # for district in districts_to_run.loc[state].index:
            #     district_age_weight = districts_to_run.loc[state, district].filter(regex = "N_[0-6]")/focus_state_agepop
            #     median_tev = np.load(fig_src / f"per_capita_TEV_{state_code}_{district}_phi50_random.npz")['arr_0'][0]
            #     district_TEV[district] = district_TEV[district] + state_age_weight.values * median_tev

            # print()
            # plot_state_age_distribution({k: v * USD for k, v in district_TEV.items()}, "per capita TEV (USD)", "D", n = 5, ymin = 0, ymax = 50)
            # plt.show()

            # plot static benchmark
            N_state = districts_to_run.loc[state].N_tot.sum()
            figure = plt.figure()
            all_tev_50_state = all_tev_50.query("state == @state")
            x_pop = list(chain(*zip(all_tev_50_state.loc[0]["num_vax"].shift(1).fillna(0) * 100/N_state, all_tev_50_state.loc[0]["num_vax"] * 100/N_state)))
            y_tev = list(chain(*zip(all_tev_50_state.loc[0]["pc_tev_usd"], all_tev_50_state.loc[0]["pc_tev_usd"])))
            static, = plt.plot(x_pop, y_tev, figure = figure, color = "grey", linewidth = 2)
            lines = [static]
            plt.xticks(fontsize = "20")
            plt.yticks(fontsize = "20")
            plt.PlotDevice().ylabel("TEV (USD)\n").xlabel("\npercentage of state vaccinated")
            # plt.ylim(0, 1600)
            # plt.xlim(left = 0, right = 100)

            lines.append(plt.plot(0, 0, color = "white")[0])

            # plot dynamic curve 
            phis = [25, 50, 100, 200]
            for (phi, _all_tev) in zip(phis, [all_tev_25, all_tev_50, all_tev_100, all_tev_200]):
                all_tev = _all_tev.query("state == @state")
                daily_doses = phi * percent * annually * N_state
                distributed_doses = 0
                x_pop = []
                y_tev = []
                t_vax = []
                ranking = 0
                for t in range(simulation_range):
                    tev = all_tev.loc[t].reset_index()
                    ranking = tev[(tev.index >= ranking) & (tev.num_vax > distributed_doses)].index.min()
                    if np.isnan(ranking):
                        break
                    x_pop += [100 * (distributed_doses)/N_state, 100 * (distributed_doses + daily_doses)/N_state]
                    t_vax += [t, t+1]
                    y_tev += [tev.iloc[ranking].pc_tev_usd]*2
                    distributed_doses += daily_doses
                # lines += [plt.plot(x_pop, y_tev, label = f"dynamic, {vax_policy}, $\phi = ${phi}%", figure = figure)[0]]
                lines += [plt.plot(x_pop, y_tev, label = f"dynamic, {vax_policy}, $phi = ${phi}%", figure = figure)[0]]
            plt.legend(
                lines,
                # ["static, t = 0, $\phi = $50%", ""]  + [f"dynamic, {vax_policy}, $\phi = ${phi}%" for phi in phis],
                ["static, t = 0, $phi = $50%", ""]  + [f"dynamic, {vax_policy}, $phi = ${phi}%" for phi in phis],
                title = "allocation", title_fontsize = "24", fontsize = "20")
            plt.xticks(fontsize = "20")
            plt.yticks(fontsize = "20")
            plt.PlotDevice().ylabel("TEV (USD)\n").xlabel("\npercentage of state vaccinated")
            plt.ylim(0, 1600)
            plt.xlim(left = 0, right = 100)
            plt.show()

            summed_TEV_hlth = np.median(np.nansum([np.load(s)['arr_0'] for s in tqdm(src.glob(f"dTEV_health*{state_code}*"))], axis = 0), axis = 0)
            summed_TEV_cons = np.median(np.nansum([np.load(s)['arr_0'] for s in tqdm(src.glob(f"dTEV_cons*{state_code}*"))],   axis = 0), axis = 0)
            plot_component_breakdowns(summed_TEV_hlth, summed_TEV_cons, "health", "consumption", semilogy = True, ylabel = "national age-weighted TEV (USD)")
            plt.show()