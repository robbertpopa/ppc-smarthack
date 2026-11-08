# Data and sources

Hackathon rule: data must be public, synthetic, or collected by the team, **with sources stated**. The datasets below were downloaded **locally** for exploration and are **not committed** to the repository (size and licences).

## Datasets and tools used
| Dataset | Content | Role | Notes |
|---|---|---|---|
| **Ausgrid "Solar home electricity data"** (Sydney, 2010–2013) | 300 homes with panels, 30-minute: consumption, generation, export | Real consumption and generation profiles | The original was withdrawn by Ausgrid; we used an unofficial copy (pierreh.eu). Verified: 3 years, 300 homes, different format in 2010–2011 |
| **NASA POWER** (hourly weather and solar radiation, 2010–2013) | 13 parameters per hour for the 100 postcodes of the houses: irradiance (all-sky, clear-sky, diffuse, direct), cloud, temperature, humidity, wind, pressure, rain | Weather inputs for the PV forecast | CC BY 4.0. Coarse grid (about 0.5° to 1°): the 100 postcodes share 6–7 distinct series. Details: `src/ml/DATA.md` |
| **SimBench** (German test grids) | Realistic LV/MV grids in pandapower format | Grids on which we run the power flow | Open licence; cables and transformers are German, not Romanian |
| **pandapower** | AC power flow | Computes the "ground truth": highest safe limit | Open source |

## Links
- Ausgrid (unofficial copy used): https://pierreh.eu/downloads/Ausgrid_solar_home_data.zip (page: https://pierreh.eu/ausgrid-solar-data/)
- Ausgrid, original page (withdrawn): https://www.ausgrid.com.au/Industry/Our-Research/Data-to-share/Solar-home-electricity-data
- Ausgrid, archived page: http://web.archive.org/web/20240721012112/https://www.ausgrid.com.au/Industry/Our-Research/Data-to-share/Solar-home-electricity-data
- NASA POWER: https://power.larc.nasa.gov/ (hourly API: https://power.larc.nasa.gov/api/temporal/hourly/point ; licence CC BY 4.0 ; how to cite: https://power.larc.nasa.gov/docs/referencing/)
- SimBench: https://github.com/e2nIEE/simbench (docs: https://simbench.readthedocs.io/)

Links were extracted from the exploration session and not re-checked. The README inside the Ausgrid copy states a Creative Commons Attribution 3.0 Australia licence; we have not verified that with Ausgrid. Details: `src/ml/DATA.md`.

## Load and generation data: Ausgrid only
Ausgrid "Solar home electricity data" is the **only** consumption and generation dataset we use. No other prosumer or load dataset is used, and none is needed to train or evaluate the model.

## Not available
- **Real PPC / Rețele Electrice data:** we have none; to request in the first hour (see [07](07-next-steps.md)).

## What we validated on the data
- **Ausgrid:** a fixed limit of 36% of kWp clips 20.6% of the exportable surplus (9.3% of production); 50% → 7.3%; 25% → 37.3%. Homes with large panels relative to consumption: 29.6%.
- **SimBench:** the safe limit computed with pandapower is monotonic in the percentage of kWp (found by bisection) and varies strongly between grids.
- **Power-flow verification:** agreement 250/250 and 248/250 on samples, including cases that are analytically violations.
- **Time split:** training until 31 March 2012, validation April–June 2012, test 1 July 2012 – 30 June 2013 (8,244 daylight intervals, one-hour horizon).

## Data pitfalls found
- The format differs between the Ausgrid files of 2010–2011 and 2012–2013 (date `1-Jul-10`, no quality column); double parsing was needed.
- Ausgrid data is Australian (southern hemisphere, summer in December): seasonality must be handled correctly if we mix it with a European grid.
- Consumption visible at the meter is **net** (consumption minus generation): curtailed production is not visible.
- Missing data and noise: tested synthetically (20% missing readings, 30% noise), with small degradation.

## To remember for the presentation
- State the sources and licences exactly.
- Say openly that the grid is German and the data Australian (synthetic, but realistic per component).
- Do not commit the large datasets; document how to download them.
