# Transformer thermal model

`src/grid/thermal.py`, owned by P1. It adds one thing to the grid twin: how hot the transformer gets, not only how loaded it is. A transformer can carry more than its rated current for a short time while it is still cool, and must carry less on a hot afternoon. A fixed 100% limit ignores both.

## What it computes

The exponential equations of IEC 60076-7 (top-oil and hot-spot temperature for a changing load and ambient temperature). `K` is the load ratio (current divided by rated current, `trafo_loading_pct / 100`).

```
top-oil target      θa + Δθor · ((1 + R·K²) / (1 + R))^x      time constant k11 · τo
winding rise target k21 · Δθhr · K^y                          time constant k22 · τw
winding cooling     (k21 − 1) · Δθhr · K^y                    time constant τo / k22
hot-spot            top-oil + winding rise − winding cooling
```

- `steady_state(load_ratio, ambient_c)` is where the temperatures settle for a constant load.
- `step(state, load_ratio, ambient_c, dt_min)` moves the state forward by `dt_min` minutes. Load and ambient are constant within a step; each lag is solved exactly, so two 15-minute steps equal one 30-minute step. The result has `hotspot_c`, which feeds `grid_state.trafo_hotspot_c`.
- `headroom(state, ambient_c, dt_min)` is the highest load ratio for the next step that keeps the hot-spot at or below the limit (and top-oil at or below 105 °C, load ratio at most 1.5). The fixed baseline is 1.0.
- `relative_ageing_rate(hotspot_c)` is `2^((θh − 98) / 6)`, the insulation ageing rate relative to 98 °C (non-thermally-upgraded paper).

## Limits

| Limit | Value | Use |
|---|---|---|
| 98 °C hot-spot | reference temperature: ageing rate 1 | default limit of `headroom`; staying under it ages the transformer no faster than normal |
| 120 °C hot-spot, 105 °C top-oil, 1.5 load ratio | normal cyclic loading of a distribution transformer | top-oil and load-ratio caps; 120 °C can be passed as `hotspot_limit_c` for a short, ageing-aware overload |

Ageing is not accumulated over the day; a model that spends an ageing budget would be the next step.

## Parameters are assumed

We have no data for a real transformer. The defaults are typical values for an ONAN distribution transformer:

| Parameter | Value | Where it comes from |
|---|---|---|
| `x`, `y` | 0.8, 1.6 | typical standard values for ONAN distribution transformers |
| `k11`, `k21`, `k22` | 1.0, 1.0, 2.0 | same |
| `τo`, `τw` | 180 min, 4 min | same |
| `Δθor` (top-oil rise at rated load) | 55 K | **assumed**, chosen so that rated load at 20 °C gives the 98 °C reference hot-spot |
| `Δθhr` (hot-spot gradient, H·gr) | 23 K | **assumed**, same reason |
| `R` (load loss to no-load loss) | 5 | **assumed**, typical order of magnitude |

## What was and was not validated

Done (`tests/test_thermal.py`):
- rated load at 20 °C ambient gives exactly 98 °C, the standard's reference condition;
- top-oil covers 63% of a load step in one oil time constant, and the winding follows its own, shorter, time constant;
- the exact step equals a fine numerical integration of the same equations (a second, independent method);
- a long hold reaches the steady state; splitting a step does not change the result;
- headroom is zero extra at the reference condition, above 100% for a cold unit, and shrinks when it is hot.

Not done:
- the standard's own worked example: IEC 60076-7 is paywalled and we did not have it. The equations were checked against public implementations of the same standard, and the typical parameter values against an open-source implementation's defaults (nothing was copied from its code);
- measured data from a real transformer. The model is a simulation with assumed parameters and says so on screen.

## Sources

- IEC 60076-7:2018, Power transformers, loading guide for mineral-oil-immersed transformers (equations, Table 4 parameters, limits)
- [venu131995/transformer-dynamic-rating](https://github.com/venu131995/transformer-dynamic-rating): the equations written as differential equations, the 98 °C reference check and the 120 °C / 105 °C / 1.5 limits
- [alliander-opensource/transformer-thermal-model](https://github.com/alliander-opensource/transformer-thermal-model): default parameters for a distribution ONAN transformer

## Ambient temperature in the agent
`src/agent/model_wiring.py` (`ambient_at`) gives every step of the hot-spot run the air temperature known at that time: the newest NASA POWER hour with `available_at <= time` (`src.ml.weather.load`). Where no weather file exists, no hour is that old, or the value is missing, the step uses the assumed 20 °C (`AMBIENT_C`), so a data folder without weather gives exactly the earlier numbers.
