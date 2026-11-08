# Următorii pași: cum rezolvăm cele 10 probleme

Acoperă cele 5 probleme din top (C1, C2, C3, M1, M3+M4, plus M2) și cele 5 probleme de structură (S1–S5) din [AUDIT.md](AUDIT.md).

**Cum am înțeles „pași care să nu ducă nicăieri, dar să-i testezi”:** fiecare reparație există deja ca prototip în `audit/proposals/`, **neconectat la `src/`**. Nimic din aplicație nu se schimbă și nimic nu ajunge în producție. Fiecare prototip are un test în `audit/tests/` care arată că reparația funcționează pe datele locale. Un pas din lista de mai jos înseamnă „mută prototipul în `src/`, păstrează testul”.

```bash
.venv/bin/python -m pytest audit/tests -q -s
```

Rezultat la scriere: **43 de teste trec în ~7 s**. Testele care au nevoie de date locale (`data/`, `artifacts/`) se sar singure dacă datele lipsesc. Niciunul nu citește anul de test 2012-13.

---

## Ordinea de lucru

| # | Pas | Problemă | Cine | Depinde de | Prototip | Test |
|---|---|---|---|---|---|---|
| 1 | Sigilează anul de test în generator | C3 | P3 | – | `sealed_period.py` | `test_c3_sealed_period.py` |
| 2 | Contract comun pentru etichete | S4, C2 | P2 + P3 | – | `label_contract.py` | `test_s4_label_contract.py` |
| 3 | Adaptor: generatorul scrie schema ML | C2 | P3 | 2 | `label_adapter.py` | `test_c1_c2_label_adapter.py` |
| 4 | Un singur cititor Ausgrid | S1 | P3 | 3 | `parser_parity.py` | `test_s1_parser_parity.py` |
| 5 | O singură definiție a domeniului | S5 | P2 + P3 | 4 | `scoring_domain.py` | `test_s5_scoring_domain.py` |
| 6 | Net pe toată ziua | M3 | P2 | 4 | `full_day_net.py` | `test_m3_full_day_net.py` |
| 7 | Generează etichete reale 2010-07 → 2012-06 | C1 | P3 | 1–6 | – | testele 1–6 pe fișierul real |
| 8 | Descâlcește `ml` ↔ `eval` | S2 | P2 | – | `import_graph.py` | `test_s2_import_graph.py` |
| 9 | Metrici de încălcare nediluate | M2 | P2 | 8 | `metrics_ext.py` | `test_m2_metrics_ext.py` |
| 10 | Validare walk-forward + prag robust | M1 | P2 | 7 | `walk_forward.py` | `test_m1_walk_forward.py` |
| 11 | Calibrare conformală a lui q05 | M4 | P2 | 10 | `conformal.py` | `test_m4_conformal.py` |
| 12 | Locația postului ca date | S3 | P2 | – (înainte de orice PT din România) | `station_geo.py` | `test_s3_station_geo.py` |
| 13 | Reantrenare, `schema_version`, evaluare finală | C1, C4 | P2 | 7–11 | – | `src.eval.run` o singură dată |

Pașii 1, 2, 8 și 12 nu depind de nimic și pot porni în paralel. Pasul 7 e singurul lung (power flow pe doi ani) și are nevoie de extra-ul `sim` (pandapower).

---

## Pașii, pe rând

### 1. Sigilează anul de test (C3)
- **Ce:** `src/grid/labels.py` nu mai are valoare implicită pentru `--start` și refuză orice fereastră care ajunge la 2012-07-01, precum și fișierul `Solar home 2012-2013.csv`, fără `--final-eval`.
- **Cum:** în `generate()` apelezi `check_window(start, days, final_eval)` și `check_source(source, final_eval)` din `audit/proposals/sealed_period.py`. Scoți `"source": "Ausgrid 2012-2013; …"`, care e fix în cod, și schimbi exemplul din `README.md:34` pe `Solar home 2011-2012.csv`.
- **Testul arată:** valoarea implicită de azi (`2013-01-01`) e refuzată; marginile sunt corecte (2012-06-30 + 1 zi trece, + 2 zile nu); `--final-eval` deschide anul; fișierul din README e refuzat.
- **Gata când:** comanda din README rulează fără să atingă 2012-13, iar testul e în `tests/test_grid_labels.py`.

### 2. Contract comun pentru etichete (S4)
- **Ce:** `LabelRow` din `audit/proposals/label_contract.py` se mută în `src/common/contract.py`, iar secțiunea „Label file” intră în `docs/09-contract.md`.
- **Cum:** `src/ml/labels.validate` rămâne pentru verificările pe tot tabelul (duplicate, tipuri). Ambele echipe validează rândurile cu `LabelRow`. Testul de contract trăiește în `tests/test_contract.py`, **fără pandapower**, ca să ruleze și în jobul `test` din CI.
- **Testul arată:** câmpurile `LabelRow` sunt exact `labels_io.COLUMNS`; etichetele de azi trec; rândurile inconsistente (`converged` fără cotă, `available_at` greșit) și forma scrisă de grid sunt prinse; azi `src.common.contract` nu are niciun tip pentru etichete.
- **Gata când:** o schimbare de schemă pe oricare parte pică un test din CI.

### 3. Adaptor de schemă în generator (C2)
- **Ce:** `src/grid/labels.py` scrie `labels.parquet` în schema ML și scrie și `station_houses.parquet`.
- **Cum:** generatorul păstrează citirile pe casă ale fiecărui interval (le are deja în `_jobs`) și la final apelează `to_ml_labels(records, readings, kwp_by_house, pt_id, source_ref)` și `station_houses(...)` din `audit/proposals/label_adapter.py`. `source_ref = f"grid/labels.py@{git_sha()}"`. `binding` rămâne null până când `safe_share()` spune ce limită a legat; `"none"` se pune doar la cota 1,0.
- **Testul arată:** forma de azi e respinsă de `validate`; ieșirea adaptorului trece și de `validate`, și de `LabelRow`; cotele `None` devin `converged = False`; etichetele adaptate ajung până la `train.training_rows` cu toate features calculate; ID-urile `AG-xxxx` există în `profiles.parquet`.
- **Gata când:** `python -m src.grid.labels --start 2011-01-01 --days 1` urmat de `labels_io.load` funcționează cap-coadă.

### 4. Un singur cititor Ausgrid (S1)
- **Ce:** generatorul citește `profiles.parquet` (curățat), nu CSV-ul brut.
- **Cum:** `day_profiles` din `src/grid/ausgrid.py` se înlocuiește cu `day_from_profiles(profiles, date, customers)` din `audit/proposals/parser_parity.py`, care dă aceleași tablouri `(48, n)`. Citirile curățate rămân NaN: power flow-ul le sare (`converged = False`), nu le pune pe 0. Zilele cu schimbare de oră (46 sau 50 de intervale) trebuie tratate explicit; prototipul le refuză.
- **Testul arată:** într-o zi normală, diferența dintre cele două căi e 0 pe 48 × 30 de celule (înlocuirea e directă); azi grid-ul trimite în power flow 1.111 citiri pe care ML le-a eliminat (de exemplu 2,37 kW pe 1,92 kWp); ID-urile diferă (`"3"` față de `"AG-0003"`).
- **Gata când:** `src/grid/ausgrid.py` nu mai citește CSV-ul brut.

### 5. O singură definiție a domeniului (S5)
- **Ce:** o funcție `domain(interval_start, pv_kw)` (soarele sus sau PV > 0), folosită și de generator în locul lui `6 <= h < 20 and pv > 0`, și de `split.daylight`.
- **Cum:** funcția stă în `src/ml/split.py` (sau în `src/common/`, după pasul 8), iar `src/grid/labels.py:37` o importă.
- **Testul arată:** azi pe PT-A rămân neetichetate 56 de intervale de zi cu PV (ora 5 vara, 0,001 % din energie); `domain()` le acoperă pe toate și include definiția ML.
- **Gata când:** testul trece cu filtrul real al generatorului, nu cu copia din prototip.

### 6. Net pe toată ziua (M3)
- **Ce:** features primesc `net_kw` măsurat și noaptea, astfel încât prima oră după răsărit să nu mai fie mereu „lipsă”.
- **Cum:** variantă curată: în `src/ml/features.py` net-ul vine dintr-un tabel separat (telemetrie din `profiles.parquet`, toate cele 48 de intervale), iar `safe_share` din etichete. Variantă rapidă, cea din `audit/proposals/full_day_net.py`: se adaugă rânduri `provenance = "measured"` cu net-ul măsurat; unde PV = 0 se pune `safe_share = 1` (fără PV nu se poate exporta nimic), iar unde PV > 0 cota rămâne necunoscută.
- **Testul arată:** totalurile din profiluri sunt identice cu cele din etichete acolo unde există ambele. **Pe rândurile cu țintă din T1 2011:**

  | | înainte | după |
  |---|---|---|
  | `net_now` lipsă | 11,6 % | 0,1 % |
  | `share_last` lipsă | 11,6 % | 3,9 % |
  | abstenție din verificările de input | 11,6 % | 3,9 % |

  Rândurile adăugate nu pun niciodată o cotă acolo unde s-a produs PV.
- **Gata când:** `share_flagged_by_input_checks` din metadata scade sub 5 %.

### 7. Etichete reale (C1)
- **Ce:** un singur fișier pentru 2010-07-01 → 2012-06-30 (train și validare), cu pașii 1–6 aplicați.
- **Cum:** în containerul `test` (are `sim`) sau cu `pip install -e ".[sim]"`, rulezi `python -m src.grid.labels --source data/raw/ausgrid --start 2010-07-01 --days 731 --workers 8 --output data/labels/A/labels.parquet`. Lista de case e fixată o dată, în `station_houses.parquet` (M6). Apoi `python -m src.grid.audit_labels` pe un eșantion.
- **Testul:** testele 2–6 rulate pe fișierul real, nu pe mock. `labels_io.is_mock(labels)` trebuie să fie `False`.
- **Gata când:** `python -m src.ml.train --scenario A` scrie `is_mock_labels: false`.

### 8. Descâlcește `ml` ↔ `eval` (S2)
- **Ce:** `src/eval/metrics.py` → `src/ml/metrics.py`; `QUANTILES`, `rearrange`, `predict_quantiles`, `fit_quantile` și `BASE_PARAMS` → `src/ml/quantiles.py`.
- **Cum:** muți fișierele, lași în locurile vechi re-exporturi cu `DeprecationWarning` pentru o versiune, apoi copiezi `test_s2_import_graph.py` în `tests/` ca test permanent.
- **Testul arată:** azi `src.ml` și `src.eval` formează un ciclu, iar `predict` ajunge la 16 module, printre care `train` și `src.eval.metrics`. După mutarea simulată ciclul dispare și `predict` nu mai ajunge la `train` și nici la `src.eval.*`. Graful prinde și importurile din interiorul funcțiilor.
- **Gata când:** testul `test_the_proposed_moves_remove_both_problems` trece pe `src/` real, fără `rewire`.

### 9. Metrici nediluate (M2)
- **Ce:** `evaluate` mai raportează `rate_binding`, `excess_kwh` și `excess_p95_share`.
- **Cum:** apelezi `violation_report(applied, safe, kwp_total)` din `audit/proposals/metrics_ext.py` în `evaluate`, cu coloane noi în `table.md` și `summary.json`, plus defalcările pe sezon și oră din `error_analysis`.
- **Testul arată:** când jumătate din intervale nu sunt constrânse, rata de azi e jumătate din cea reală (0,2 față de 0,4); energia de depășire e calculată exact; o politică sigură are depășire 0.
- **Gata când:** tabelul final are coloanele noi, iar pitch-ul citează rata pe intervalele constrânse.

### 10. Validare walk-forward și prag robust (M1)
- **Ce:** 12 folduri lunare (2011-07 → 2012-06, fiecare antrenat pe tot ce e înainte), hiper-parametri aleși pe media pinball pe folduri, `tau` ales cu `robust_tau(..., quantile=1.0)`, adică ținta respectată în fiecare lună.
- **Cum:** `train.train` primește `folds=walk_forward.monthly_folds()`. Antrenarea finală se face pe tot 2010-07 → 2012-06. Metadata păstrează ratele pe fiecare fold. Cost: ~12 × 10 s pentru un set de parametri.
- **Testul arată:** 12 folduri cronologice care se termină exact la începutul testului; fiecare are rânduri de train și de validare, fără suprapunere, iar validarea acoperă toate cele 4 anotimpuri (azi doar toamna și iarna); pragul robust ține și în luna cea mai proastă, unde alegerea pe medie ar depăși ținta; split-ul folosește datele din Sydney.
- **Gata când:** `abstention.holdout` dispare, înlocuit de ratele pe folduri, iar luna cea mai proastă e sub țintă.

### 11. Calibrare conformală (M4)
- **Ce:** `q05_cal = q05 - shift[ora locală]`, cu shift-ul învățat pe validare (pe folduri, după pasul 10), salvat în metadata și aplicat în `predict`.
- **Cum:** folosești `fit_shift` / `apply_shift` din `audit/proposals/conformal.py`. Grupele cu sub 30 de rânduri folosesc shift-ul global. Spread-ul pentru abstenție se calculează după calibrare.
- **Testul arată:** pe date sintetice supra-încrezătoare la marginile zilei (violări > 15 %), după calibrare fiecare oră ajunge la 5 % ± 2 %. Pe modelul salvat (mock), a doua jumătate a validării trece de la 5,3 % la 4,9 %.
- **Gata când:** acoperirea pe ore din validare e în [3 %, 7 %] la fiecare oră.

### 12. Locația postului ca date (S3)
- **Ce:** `StationGeo(lat, lon, tz)` în `StationConfig`, transmis la `features`, `split`, `metrics` și `sun`. Fără literalul `"Australia/Sydney"` în cod.
- **Cum:** `time_features(target, horizon, geo)` din `audit/proposals/station_geo.py` înlocuiește coloanele de timp și soare din `features._compute`. Pentru Ausgrid, `from_postcodes` dă centrul postului (PT-A: −33,44°, 151,39°).
- **Testul arată:** azi `features.build` și `build_frame` nu au cum să primească o locație; la amiaza din București codul de azi vede soarele sub orizont, iar prototipul îl vede la peste 60°; pentru Sydney prototipul dă exact features de azi; răsăritul variază cu 5 minute în Ausgrid.
- **Gata când:** un `StationConfig` cu `tz="Europe/Bucharest"` produce features corecte, fără nicio altă schimbare de cod.

### 13. Reantrenare și evaluarea finală (C1, C4)
- **Ce:** reantrenezi pe etichetele reale; adaugi `schema_version` în metadata, verificat de `predict._load` și de `abstention.threshold`; abia apoi rulezi evaluarea, **o singură dată**.
- **Cum:**

  ```bash
  python -m src.ml.train --scenario A
  python -c "from src.ml.abstention import threshold; print(threshold('PT-A'))"
  ```

  A doua comandă trebuie să dea un număr, nu `ValueError`. Apoi rulezi `python -m src.ml.data download --include-held-out`, `... profiles` și `python -m src.eval.run --error-analysis`.
- **Gata când:** `summary.json` are `mock: false`, iar cifrele din pitch vin doar din el.

---

## Ce nu acoperă prototipurile
- **Pasul 7** (etichetele reale) nu poate fi testat aici: pandapower nu e instalat în `.venv`. Testele 2–6 verifică totul în afară de power flow-ul propriu-zis.
- **Calibrarea (pasul 11)** e testată pe etichete mock: câștigul real se vede doar pe etichete reale.
- **Meteo (M5)**, **selecția fixă a caselor (M6)** și problemele minore (m1–m6) au reparații descrise în `AUDIT.md`, dar nu au prototip.
