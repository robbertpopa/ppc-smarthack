# Audit ML: modelul de limită sigură de export (safe-cap) și prognoza PV/consum

Auditor: `ml-pv-auditor` (`.claude/agents/ml-pv-auditor.md`), rulat pe 2026-11-08.
Branch: `audit/ml-pv-auditor`, pornit din `fix/p2-review-comments` @ `16f8d30` (cel mai nou cod ML; `main` e în urmă cu fixurile din review-ul P2).
Codul existent nu a fost modificat. Scripturile de verificare sunt în `audit/`, se rulează din rădăcina repo-ului cu `.venv/bin/python -m audit.<nume>`.

Interpretări alese (sarcina era ambiguă în aceste puncte):
- „Datele meteo” = `data/weather_hourly.parquet` (NASA POWER, orar, per cod poștal). Repo-ul le descarcă, dar niciun model nu le folosește (vezi M5).
- „Modelul” = `safe-cap-qgb-v1` (cuantile, `src/ml/train.py`) și secundar `pv-load-qgb-v1` (`src/ml/forecast_pv_load.py`).
- Anul 2012-13 (setul de test) e sigilat: nu l-am deschis și nu am rulat nimic pe perioada de test. Am verificat doar că nu apare în datele de lucru.

---

## 1. Planul

**Ce prezice modelul.** La momentul `t`, cota sigură de export (`safe_share`, 0..1 din kWp instalat) pentru intervalul de 30 min care începe la `T = t + 60 min`, pentru un post de transformare (PT) cu 30 de case. Ținta vine dintr-un calcul de power flow (pandapower) pe o rețea sintetică, alimentat cu profilele Ausgrid. Cinci cuantile (q05…q90); planner-ul aplică q05, iar dacă `q90 - q05 > tau` revine la limita fixă de 0,36 și trimite cazul la un om.
**Rezoluție:** 30 min. **Orizont:** 60 min (safe-cap); 60/180/360 min (PV și consum).
**Date:** Ausgrid Solar Home 2010-11 și 2011-12 (300 de case, kWh pe jumătate de oră, ora locală Sydney cu DST), etichete în `data/labels/A`, NASA POWER (neutilizat).
**Split:** train până la 2012-03-31, validare apr.–iun. 2012, test iul. 2012 – iun. 2013 (`src/ml/split.py:14-16`).

**Ordinea verificărilor:**
- [x] 1. Inventar: ce date, ce etichete, ce modele salvate există și pe ce au fost antrenate
- [x] 2. Date: curățare, DST, valori lipsă, senzori blocați, valori peste kWp, noapte (`audit/check_data.py`)
- [x] 3. Timp: UTC vs. ora locală, aliniere meteo ↔ poziția soarelui (`audit/check_data.py`)
- [x] 4. Features: look-ahead, paritate train ↔ inferență (`audit/check_features.py`)
- [x] 5. Etichete: generatorul real vs. schema pe care o citește ML (`audit/check_label_schema.py`)
- [x] 6. Split, tuning, prag de abstenție: ce se alege pe ce date
- [x] 7. Modelul salvat pe validare: calibrare, baseline, încălcări pe ore (`audit/check_model.py`)
- [x] 8. Reproductibilitate: două antrenări cu același seed (`audit/check_repro.py`)
- [x] 9. Evaluare: metrici, baseline, sezoane, cer senin vs. înnorat (citire cod `src/eval/`)
- [x] 10. Inferență: ce face agentul cu modelul salvat

Ce **nu** am verificat: perioada de test (sigilată), etichete reale (nu există în repo), rularea completă `src.eval.run` (nu are date de test), rețeaua din `src/grid/twin.py` în detaliu (în afara ML).

---

## 2. Parcurgerea pipeline-ului

### Pas 1: inventar (făcut)
- `data/labels/A/labels.parquet`: 17.518 rânduri, `source_ref = "mock"`, interval 2010-07-01 → 2012-06-30. **Zero rânduri în perioada de test** (`check_model`).
- Ambele modele din `artifacts/models/` au `is_mock_labels: true` (`metadata.json`).
- Ținta mock e o formulă liniară: `clip(0.9 - 0.6·pv/kWp + 0.3·load/kWp + N(0, 0.03), 0.05, 1)` (`src/ml/labels.py:190`). Pe mock, `safe_share` nu coboară niciodată sub 0,36, deci limita fixă nu încalcă niciodată nimic.
- README-ul spune deja că modelul real și tabelul de evaluare nu există încă. Auditul confirmă asta.

### Pas 2: date (făcut)
Rezultatul `check_data` pe `profiles.parquet` (10,5 mil. rânduri, 300 de case):
- 0 rânduri în anul de test, 0 duplicate, 0 valori negative, kWp constant per casă.
- DST e tratat corect: centrul de masă al PV-ului e la 11,8–12,0 h (ora standard) și la 12,6–13,05 h (ora de vară), adică amiaza solară plus 1 h. Asta confirmă `src/ml/DATA.md:65-71`.
- 172 de citiri PV > 0,05 kW noaptea (soare < −6°), toate de la o singură casă.
- 97 de serii „blocate” (aceeași valoare PV nenulă de ≥ 5 ori la rând, cu soarele > 10°).
- **2.614 zile-casă cu PV exact 0 toată ziua, deși soarele trece de 30°, la 112 case.** Nu sunt filtrate.
- 5.207 citiri între 1,0 și 1,2 × kWp sunt păstrate ca valide, iar peste 1,2 × kWp se pun pe null. Peste kWp e fizic suspect (capacitate declarată greșit sau clipping lipsă).

### Pas 3: timp (făcut)
- `src/ml/sun.py` corespunde cu `90 − SZA` din NASA POWER cu o eroare medie de **0,22°**, dacă eticheta orară e citită ca început de oră plus 30 min. Deci: marcajele NASA sunt în UTC, la începutul orei, iar valoarea e media orei. Poziția soarelui e corectă.
- Etichetele și features lucrează în UTC, split-ul pe data locală din Sydney (`split.py:19-21`). E corect.
- Coloanele Ausgrid sunt etichetate la sfârșitul intervalului; `src/ml/ausgrid.py` și `src/grid/labels.py:37` le tratează ca index de început (`i·30 min`). E consecvent.

### Pas 4: features (făcut)
`check_features`, pe perioada de train:
- Paritatea `build()` (inferență) ↔ `build_frame()` (antrenare) e exactă: diferența maximă e 0 pe 300 de momente.
- Look-ahead: dacă stric tot ce devine disponibil după `t`, features nu se schimbă (0/100), nici pe calea de antrenare (diferență 0,0).
- **12,3 % din rândurile cu țintă nu au `net_now` / `share_last`**, pentru că etichetele există doar ziua. Prima oră după răsărit nu are niciodată istoric (vezi M3).

### Pas 5: etichete reale (făcut)
`check_label_schema`: generatorul real (`src/grid/labels.py`) scrie alte coloane decât cele pe care le cere `src/ml/labels.validate`. Fișierul lui e respins (vezi C2). Pe deasupra, generatorul pornește implicit pe anul de test (vezi C3).

### Pas 6: split și alegeri pe validare (făcut)
- Split-ul e cronologic și fix, nu aleator. Nu există early stopping ascuns (`train.py:54`). Testul nu e citit la antrenare. Toate bune.
- Pe aceeași validare de 3 luni se aleg hiper-parametrii (`train.py:122-138`), pragul `tau` (`train.py:151-152`) și se raportează cifrele. Există un `holdout_check` (jumătate/jumătate), care e o idee bună.
- Validarea acoperă doar aprilie–iunie: toamnă și iarnă în emisfera sudică, cu PV slab și zile scurte (vezi M1).

### Pas 7: modelul salvat pe validare (făcut, pe etichete mock)
`check_model` (`ARTIFACT_URI=artifacts`):

| Ce | Valoare | Ar trebui |
|---|---|---|
| Acoperire q05 / q50 / q90 | 0,067 / 0,427 / 0,723 | 0,05 / 0,50 / 0,90 |
| Încălcări cu q05 ca limită | 6,7 % (8,6 % când limita contează, `y < 1`) | ≤ 2 % |
| Abstenție necesară pentru 2 % | **76,7 %** din intervale | mică |
| Abstenție doar din verificările de input | 14,4 % (toate din lipsa `net_now`) | ~0 |
| nMAE q50 / persistență / ieri | 0,039 / 0,085 / 0,073 | – |
| Încălcări q05 la 6 h și 17 h | 11,5 % și 10,7 %, cu spread 0,02–0,05 | – |
| Holdout: prag ales pe prima jumătate | 1,9 % → **2,9 %** pe a doua jumătate | ≤ 2 % |

Skill-ul de 0,54 față de persistență nu are valoare: ținta mock e o funcție liniară de valorile din același interval.

### Pas 8: reproductibilitate (făcut)
`check_repro`: două antrenări cu același seed dau rapoarte identice. Seed-ul 0 și seed-ul 1 dau același model: `HistGradientBoosting` fără subsampling e determinist, deci seed-ul din metadata nu schimbă nimic. Antrenarea durează ~10 s pentru un set de parametri.
Dependențe: doar `pyarrow`, `scikit-learn`, `matplotlib` și `pandapower` sunt fixate. `numpy` și `pandas` au doar limită inferioară (`pyproject.toml:11-12`) și nu există lockfile.
Testele: `pytest tests/ml tests/eval` → 193 trec.

### Pas 9: evaluare (făcut, citire cod)
Puncte bune, pe care le notez ca să fie clar că nu sunt probleme:
- Baseline: limită fixă, `last_known`, `same_hour_yesterday`, oracol.
- Metrica principală e de decizie (export index față de limita fixă, rata de încălcări), nu MAPE.
- Există defalcări pe sezon și pe cer senin vs. înnorat (`error_analysis.py:30,96,142-144`), robustețe la date corupte și drift validare → test.
- Ieșirea e marcată „MOCK” când etichetele sunt mock.

Lipsuri: vezi M2 și m1.

### Pas 10: inferență (făcut)
Agentul cu `SOURCE=model` citește pragul cu `abstention.threshold()`. Modelul salvat nu are cheia `abstention` la rădăcina metadatelor, iar apelul aruncă `ValueError`. Agentul tratează eroarea ca abstenție forțată (`src/agent/service.py:85-88`), adică eșuează în siguranță. Numai că modelul nu decide niciodată nimic (vezi C4).

---

## 3. Probleme

**[CRITIC] C1: Nu există niciun rezultat real: ambele modele sunt antrenate pe etichete mock** — `artifacts/models/safe-cap-qgb-v1/PT-A/metadata.json` (`is_mock_labels: true`), `data/labels/A/labels.parquet` (`source_ref = mock`) — CONFIRMAT
- Ce e greșit: ținta e o formulă inventată (`src/ml/labels.py:190`), nu un power flow. Etichetele mock se opresc la 2012-06, deci nu există date de test.
- Cum se manifestă: orice cifră a modelului (acoperire, export index, skill, „bate ieri”) măsoară cât de bine învață GBM o formulă liniară. Nu spune nimic despre rețea. `src.eval.run` nici nu poate rula: dă „no rows in the test period”. Cifrele din `docs/04-chosen-idea.md:40-46` (131, 1,9 %, 42,5 %) vin din codul de explorare, care nu e în repo (README-ul o recunoaște).
- Cum se repară: generați etichete reale pentru 2010-07 → 2012-06 (train și validare), după C2 și C3. Antrenați pe ele, iar testul îl rulați o singură dată la final. Până atunci, pitch-ul nu folosește nicio cifră de model.

**[CRITIC] C2: Generatorul de etichete reale scrie o schemă pe care ML-ul o respinge** — `src/grid/labels.py:77-87` vs. `src/ml/labels.py:33-36,55-60` — CONFIRMAT (`audit/check_label_schema.py`)
- Ce e greșit: generatorul scrie `safe_cap_share`, `interval_start` ca șir de caractere, `source`, `pv_scale`, `transformer_kva`. ML-ul cere `safe_share`, `converged`, `binding`, `load_kw`, `pv_kw`, `net_kw`, `kwp_total`, `available_at` (UTC), `source_ref`. Nu scrie nici `station_houses.parquet`, care trebuie pentru export.
- Cum se manifestă: `labels.load()` aruncă „missing columns [...]”. Calea „etichete reale → antrenare” n-a funcționat niciodată cap-coadă. De aici și C1.
- Cum se repară: un adaptor în `src/grid/labels.py` care scrie exact schema din `src/ml/labels.py`:
  ```python
  rec = {
      "pt_id": pt_id,
      "interval_start": pd.Timestamp(utc),
      "safe_share": share,
      "converged": share is not None,
      "binding": binding,  # din _share_is_safe
      "load_kw": load[i].sum(),
      "pv_kw": pv[i].sum(),
      "net_kw": load[i].sum() - pv[i].sum(),
      "kwp_total": sum(kwp),
      "n_houses": len(houses),
      "available_at": pd.Timestamp(utc) + pd.Timedelta(minutes=30),
      "provenance": "simulated",
      "source_ref": f"grid/labels.py@{git_sha()}",
  }
  ...
  labels_io.validate(df)  # înainte de to_parquet
  ```
  Plus un test care trece ieșirea lui `generate()` pe o zi prin `labels_io.validate`.

**[CRITIC] C3: Generatorul de etichete și README-ul pornesc implicit pe anul de test sigilat** — `src/grid/labels.py:86,103`, `README.md:34` — CONFIRMAT
- Ce e greșit: `--start` are implicit `2013-01-01`, sursa e trecută fix ca „Ausgrid 2012-2013”, iar exemplul din README folosește `Solar home 2012-2013.csv`. Regula 2 din `docs/tasks/p2/README.md` și `src/ml/DATA.md:11-14` spun că fișierul e sigilat.
- Cum se manifestă: cine rulează exemplul deschide setul de test și se uită la el (distribuții, depanare) înainte de evaluarea finală. Totul se face pe 2012-13, deci nu ai etichete pentru train și validare. Câmpul `source` minte pentru alte fișiere.
- Cum se repară: fără valoare implicită pentru `--start`. Refuzați orice dată ≥ 2012-07-01 fără un flag `--final-eval`. Scoateți `source` din fișierul de intrare. Schimbați exemplul din README pe `Solar home 2011-2012.csv`.

**[CRITIC] C4: Modelul servit nu se potrivește cu codul: agentul se abține la 100 %** — `artifacts/models/safe-cap-qgb-v1/PT-A/metadata.json` (git `a3d8176`, fără cheia de rădăcină `abstention`), `src/ml/abstention.py:197-199` — CONFIRMAT
- Ce e greșit: modelul a fost salvat de o versiune veche a `train.py`, care punea `abstention` doar sub `validation`. Codul de acum îl caută la rădăcină. Verificarea de compatibilitate din `predict._load` compară doar lista de features.
- Cum se manifestă: `abstention.threshold("PT-A")` dă `ValueError: model PT-A has no abstention threshold`, iar `service.py:85-88` forțează abstenția pe fiecare plan. Demo-ul cu `SOURCE=model` arată doar limita fixă și „trimis la om”. Eșuează în siguranță, dar modelul nu face nimic.
- Cum se repară: reantrenați (`python -m src.ml.train --scenario A`) după C1. Adăugați un `schema_version` în metadata, pe care `predict._load` și `abstention.threshold` îl verifică:
  ```python
  if meta.get("schema_version") != METADATA_SCHEMA:
      raise ValueError("retrain: metadata schema")
  ```

**[MAJOR] M1: Pragul și hiper-parametrii se aleg pe 3 luni de toamnă și iarnă, dar se aplică pe un an întreg** — `src/ml/split.py:14-16`, `src/ml/train.py:122-152` — CONFIRMAT (validarea are doar lunile 4, 5, 6)
- Ce e greșit: în apr.–iun., la Sydney, PV-ul e slab, zilele scurte și supratensiunile rare. Testul include vara, cu PV maxim și riscul cel mai mare. Pe aceleași 1.900 de rânduri se aleg 4 seturi de parametri și `tau`, și tot pe ele se raportează cifrele.
- Cum se manifestă: rata de încălcări aleasă „la țintă” (2 %) derivă pe test. Chiar și pe mock, holdout-ul arată 1,9 % → 2,9 %, iar explorarea raporta 1,8 % → 3,5 % (`docs/04-chosen-idea.md:64`). Pentru PV, cel mai probabil eroarea e mai mare vara.
- Cum se repară: validare walk-forward pe tot anul 2011-12 (de exemplu antrenare pe 2010-07 → luna m−1, validare pe luna m, pentru 12 luni). Alegeți `tau` pe cuantila 98 a încălcărilor *pe lună* sau pe sezon, nu pe medie. Eventual folosiți un `tau` per sezon sau per oră și raportați holdout-ul separat de alegere.

**[MAJOR] M2: Rata de încălcări e diluată de intervale ușoare și ignoră cât de mare e încălcarea** — `src/eval/metrics.py:91-115` — CONFIRMAT (pe mock 21 % din intervale au `safe_share = 1`, unde q05 nu poate încălca nimic)
- Ce e greșit: numitorul cuprinde toate intervalele de zi cu etichetă, inclusiv cele în care rețeaua nu are nicio constrângere. Încălcarea e binară: 0,001 peste limită cântărește cât 0,3 peste.
- Cum se manifestă: „2 % încălcări” poate ascunde 8–10 % pe intervalele care contează (pe mock: 6,7 % în total, 8,6 % când limita contează). O politică care depășește rar, dar cu mult, iese la fel de bine ca una care depășește des și puțin.
- Cum se repară: raportați și `violation_rate | safe_share < 1`, plus energia exportată peste limita sigură (kWh) și cuantila 95 a depășirii (în pu de kWp), pe sezon și pe oră:
  ```python
  excess = (applied - safe).clip(lower=0) * kwp_total * 0.5  # kWh peste limita sigură
  ```

**[MAJOR] M3: Etichetele doar pe zi creează un tipar fals de lipsă și 14 % abstenție structurală** — `src/grid/labels.py:34-35`, `src/ml/labels.py:188`, `src/ml/abstention.py:165-171` — CONFIRMAT (12,3 % din rânduri fără `net_now`, 14,4 % abstenție din verificările de input)
- Ce e greșit: `net_kw` vine din fișierul de etichete, care are doar intervale de zi (și doar cu PV > 0, între 06:00 și 20:00). În realitate contorul măsoară `net` și noaptea. Prima oră după răsărit are mereu `net_now = NaN`, deci flag-ul `missing_net_now` și abstenție.
- Cum se manifestă: în fiecare dimineață modelul se abține din cauza unui artefact de date, nu a unei incertitudini reale. Arborii învață „NaN ↔ dimineață”, dar în producție `net_now` ar exista, deci distribuția de la inferență diferă de cea de la antrenare.
- Cum se repară: construiți `net_*` din `profiles.parquet` pe toate cele 48 de intervale (sau scrieți `net_kw` și noaptea în etichete, cu `safe_share = 1`, `binding = none`) și lăsați lipsă doar `share_last`. Verificarea `missing_share_last` nu are rost noaptea și dimineața devreme.

**[MAJOR] M4: Modelul e cel mai încrezător acolo unde greșește cel mai des (marginile zilei)** — `src/ml/abstention.py:3-4` (abstenție doar pe spread) — CONFIRMAT pe mock, SUSPECT pe etichete reale
- Ce e greșit: la 6 h și 17 h, q05 încalcă limita în 11,5 % și 10,7 % din cazuri, cu spread de doar 0,02–0,05, sub orice `tau`. Acoperirea q90 e 0,72 în loc de 0,90, deci intervalele sunt prea înguste.
- Cum se manifestă: abstenția pe spread nu prinde tocmai erorile sistematice. Pentru 2 % trebuie să se abțină în 77 % din cazuri, adică modelul aproape nu e folosit.
- Cum se repară: calibrare conformală a lui q05 pe validare, per oră sau după elevația soarelui (`q05_cal = q05 - quantile_{0.95}(q05 - y | bin)`), apoi abstenția pe spread-ul calibrat. Raportați acoperirea per oră.

**[MAJOR] M5: Nicio informație meteo în modele, deși datele sunt descărcate** — `src/ml/features.py:38-53`, `src/ml/forecast_pv_load.py:30` — CONFIRMAT (`grep` nu găsește niciun consumator al `weather_hourly.parquet` în `src/`)
- Ce e greșit: modelul PV la 3 h și la 6 h are doar poziția soarelui, lag-uri de 90 de minute și „ieri”. Fără prognoză de nebulozitate, la 6 h înainte nu poate fi mai mult decât un clear-sky scalat.
- Cum se manifestă: banda PV pentru baterii e aproape climatologie, iar plafonul sigur nu are niciun semnal de „vine un front noros”. Atenție la capcană: NASA POWER e reanaliză sau satelit (valori măsurate, publicate cu zile întârziere). Dacă e băgat ca feature la `T`, e **leakage de producție**: în realitate ai avea doar prognoză.
- Cum se repară: dacă se adaugă meteo, doar ca prognoză disponibilă la `t` (de exemplu NWP arhivat, Open-Meteo historical forecast). Altfel folosiți doar valori meteo cu `available_at <= t`, plus întârzierea reală de publicare. Mai trebuie: un indice de senin calculat din `net` (`clear_sky_index_now = pv_est / clearsky`) și GHI clear-sky corect (pvlib Ineichen) în loc de `sin(elev)`. Marcajele NASA sunt la începutul orei, cu media orei (verificat: 0,22° la +30 min).

**[MAJOR] M6: Selecția caselor și capacitatea depind de fereastra rulată** — `src/grid/ausgrid.py:21-39`, `src/grid/labels.py:44-57` — SUSPECT
- Ce e greșit: `select_households` ia primele 30 de clienți după ID care au date complete *în fereastra `--days`*. Rulat pe bucăți (o zi, o lună), postul poate avea altă componență de la o bucată la alta. Nu se scrie nici lista caselor (`station_houses`).
- Cum se manifestă: etichete concatenate din rulări diferite descriu posturi diferite sub același `pt_id`. Modelul ar învăța salturi fără cauză fizică, iar exportul (`surplus_kw`) s-ar calcula pe alte case decât etichetele.
- Cum se repară: fixați lista de case o singură dată (fișier `station_houses.parquet` scris de generator, ales pe train) și refuzați rularea dacă o casă lipsește.

**[MINOR] m1: Comparația PV/consum cu „ieri” e trucată în favoarea modelului** — `src/ml/forecast_pv_load.py:92-98` — CONFIRMAT
- Ce e greșit: baseline-ul „ieri” dă aceeași valoare pentru toate cuantilele (bandă de lățime 0), deci pierderea pinball pe q10 și q90 e penalizată. Acoperirea lui e 0,0005 prin construcție.
- Cum se manifestă: `beats_yesterday: true` peste tot (`metadata.json`), fără să însemne mult.
- Cum se repară: un baseline probabilistic corect, cu cuantile empirice ale „ieri + reziduuri” pe aceeași oră din ultimele N zile sau cuantile clear-sky × index de senin, plus CRPS sau skill score.

**[MINOR] m2: Defecte de date nefiltrate: zile cu PV mort, serii blocate, generare noaptea, PV peste kWp** — `src/ml/data.py` (regulile de curățare din `src/ml/DATA.md:94-101`) — CONFIRMAT (`audit/check_data.py`)
- Ce e greșit: 2.614 zile-casă cu PV = 0 la soare > 30° (112 case), 97 de serii blocate, 172 de citiri nocturne (o casă) și 5.207 citiri între 1,0 și 1,2 × kWp sunt tratate ca valide.
- Cum se manifestă: o zi cu invertorul căzut arată ca o zi foarte înnorată pentru post. Ținta (`safe_share`) iese prea optimistă în acele zile, iar exportul e subestimat.
- Cum se repară: marcați ca lipsă zilele cu `max(gg) == 0` la soare > 30°, seriile cu ≥ 4 valori identice nenule la soare > 10° și `gg > 0` noaptea. Raportați câte rânduri prinde fiecare regulă în `DATA.md`.

**[MINOR] m3: Datele meteo din anul de test stau în datele de lucru** — `data/weather_hourly.parquet` (1.318.600 de rânduri ≥ 2012-07-01) — CONFIRMAT
- Ce e greșit: regula de sigilare acoperă fișierul Ausgrid, dar meteo pentru iul. 2012 – dec. 2013 e lângă datele de lucru.
- Cum se manifestă: dacă se adaugă features meteo (vezi M5), analizele exploratorii vor atinge anul de test fără să-și dea seama.
- Cum se repară: tăiați fișierul la 2012-06-30 pentru lucru și păstrați restul separat, cu același regim ca 2012-13.

**[MINOR] m4: `share_last` presupune un power flow în timp real** — `src/ml/features.py:15,85` — SUSPECT
- Ce e greșit: feature-ul e eticheta (power flow pe contoarele fiecărei case) din intervalul care tocmai s-a încheiat. În producție ai nevoie de contoare inteligente pe toate casele și de un twin calibrat care rulează la fiecare 30 de minute. Docstring-ul spune „only net values are used”, dar `share_last` e mai mult decât net.
- Cum se manifestă: dacă în producție feature-ul vine dintr-o estimare (twin necalibrat, lipsă contoare), modelul primește altă distribuție decât la antrenare.
- Cum se repară: documentați dependența și testați robustețea cu `share_last` zgomotos sau lipsă în `src/eval/robustness.py`.

**[MINOR] m5: Dependențe nefixate și seed fără efect** — `pyproject.toml:11-12`, `src/ml/train.py:46-57` — CONFIRMAT
- Ce e greșit: `numpy>=2.0` și `pandas>=2.2` nu au limită superioară și nu există lockfile. Seed-ul nu schimbă modelul (`check_repro`: seed 0 = seed 1).
- Cum se manifestă: o versiune nouă de pandas poate schimba reindexarea pe timp sau DST, iar artefactele nu se mai pot reproduce. Seed-ul din metadata sugerează o variabilitate care nu există.
- Cum se repară: un lockfile (`uv pip compile` sau `pip freeze > requirements.lock`) folosit în CI și Docker. Fie scoateți seed-ul din metadata, fie îl faceți să conteze (subsampling) și raportați media pe 3–5 seed-uri.

**[MINOR] m6: Scriptul de demo alege 10:00 UTC, adică noapte la Sydney** — `pitch/demo-script.md:19` — SUSPECT
- Ce e greșit: 10:00 UTC înseamnă 20:00 sau 21:00 la Sydney. Cu modelul real, intervalul are flag-ul `night` și se abține.
- Cum se manifestă: demo-ul „spread mic, modelul decide” merge doar pe forecast-ul mock.
- Cum se repară: folosiți 02:00 UTC (12:00 sau 13:00 local), sau afișați ora locală a PT-ului.

### Probleme de structură (a doua trecere)
Aici nu e vorba de un bug într-un calcul, ci de felul în care e împărțit codul: din cauza asta au apărut C1–C4 și vor mai apărea. Fiecare are un prototip de reparație în `audit/proposals/` și un test în `audit/tests/` (`.venv/bin/python -m pytest audit/tests -q -s`: 43 de teste trec). Pașii de rezolvare sunt în [NEXT_STEPS.md](NEXT_STEPS.md).

**[MAJOR] S1: Două cititoare Ausgrid, cu curățare diferită; power flow-ul primește citirile pe care ML le-a eliminat** — `src/grid/ausgrid.py:6-14,42-53` vs. `src/ml/ausgrid.py:143-194` — CONFIRMAT (`audit/tests/test_s1_parser_parity.py`)
- Ce e greșit: generatorul de etichete recitește CSV-ul brut și nu aplică regulile din `src/ml/DATA.md:94-101` (PV > 1,2 × kWp, ora dublată la fall-back, `Row Quality`). Casele au alte ID-uri: `"3"` la grid, `"AG-0003"` la ML.
- Cum se manifestă: doar în 2011-12, 1.111 citiri pe care ML le pune pe null intră în power flow. De exemplu, AG-0112 pe 2011-12-03 are 2,37 kW pe 1,92 kWp. Eticheta (`safe_share`) și exportul (`surplus_kw`) se calculează astfel pe date diferite. Într-o zi normală cele două căi dau exact aceleași valori (diferență 0 pe 48 × 30 de celule), deci curățarea e singura diferență.
- Cum se repară: generatorul citește `profiles.parquet` prin `day_from_profiles` (`audit/proposals/parser_parity.py`), care returnează aceleași tablouri `(48, n)` ca `day_profiles`, și folosește ID-urile `AG-xxxx` peste tot.

**[MAJOR] S2: `src.ml` și `src.eval` se importă reciproc, iar calea de servire trage după ea codul de antrenare** — `src/ml/train.py:23`, `src/ml/abstention.py:22`, `src/ml/baselines.py:21` ↔ `src/eval/metrics.py:15-16`; `src/ml/predict.py:88`, `src/ml/forecast_pv_load.py:27` — CONFIRMAT (`audit/tests/test_s2_import_graph.py`)
- Ce e greșit: metrica „oficială” stă în `eval`, dar `ml` are nevoie de ea la antrenare, iar `eval` are nevoie de `ml`. `predict` importă `train` ca să ia `QUANTILES` și `predict_quantiles`.
- Cum se manifestă: `src.ml.predict` ajunge la 16 module, printre care `train`, `abstention`, `baselines`, `explain`, `labels` și `src.eval.metrics`. O schimbare în evaluare poate strica API-ul, iar orice modificare din `train` atinge calea de servire. Pachetele nu pot fi testate sau livrate separat.
- Cum se repară: `src/eval/metrics.py` → `src/ml/metrics.py` și un modul mic `src/ml/quantiles.py` (`QUANTILES`, `rearrange`, `predict_quantiles`, `fit_quantile`, `BASE_PARAMS`). Testul simulează mutarea (`rewire`): ciclul dispare, iar `predict` nu mai ajunge nici la `train`, nici la `src.eval.*`. Un test de import-graph în `tests/` blochează revenirea.

**[MAJOR] S3: Locul și fusul orar al postului sunt constante în cod; un PT din România ar primi soarele de la Sydney** — `src/ml/sun.py:11-12`, `src/ml/config.py:12`, plus literalul `"Australia/Sydney"` în `src/eval/plots.py:66`, `src/grid/labels.py:39`, `src/grid/audit_labels.py:16,35` — CONFIRMAT (`audit/tests/test_s3_station_geo.py`)
- Ce e greșit: `features.build` și `build_frame` nu au cum să primească o locație. Ora, ziua din an, weekendul, split-ul și metricile folosesc toate fusul orar al Sydney-ului.
- Cum se manifestă: la amiaza din București (21 iunie, 09:00 UTC), codul de azi calculează soarele sub orizont, deci flag-ul `night` și abstenție. Pentru Ausgrid efectul e mic: centrul PT-A e la −33,44°, 151,39°, iar răsăritul variază cu 5 minute între codurile poștale. Pentru produsul propus (PPC, România), modelul ar fi greșit în fiecare interval.
- Cum se repară: `StationGeo(lat, lon, tz)` în configurația postului (`StationConfig`) și `time_features(target, horizon, geo)` (`audit/proposals/station_geo.py`). Testul arată că pentru Sydney prototipul dă exact coloanele de azi, deci înlocuirea nu schimbă nimic pe datele existente.

**[MAJOR] S4: Schema fișierului de etichete nu face parte din contractul comun, iar granița P3 → P2 nu e testată nicăieri** — `src/common/contract.py` (nu are tip pentru etichete), `docs/09-contract.md:138`, `tests/test_grid_labels.py:6-7`, `.github/workflows/ci.yml:21` — CONFIRMAT (`audit/tests/test_s4_label_contract.py`)
- Ce e greșit: schema există doar în docstring-ul și în `validate` din `src/ml/labels.py`. Contractul din docs îi dă lui P3 doar `safe_share(grid, injections) -> float`. Testele grid se sar singure fără pandapower: local se sar, iar jobul `test` din CI instalează `dev,ml,report`, fără `sim`. Niciun test nu trece ieșirea generatorului prin loader-ul ML.
- Cum se manifestă: așa a apărut C2. Fiecare echipă și-a scris schema ei, testele fiecăreia trec, iar integrarea nu a rulat niciodată.
- Cum se repară: modelul `LabelRow` (`audit/proposals/label_contract.py`) mutat în `src/common/contract.py`. Câmpurile lui sunt exact `labels_io.COLUMNS` (testat). Adăugați un test de contract fără pandapower, care construiește rânduri în forma pe care o scrie generatorul și le trece prin adaptor (`audit/proposals/label_adapter.py`) și prin `LabelRow`.

**[MINOR] S5: Două definiții pentru „intervalele etichetate și punctate”** — `src/ml/split.py:37-40` (soarele peste orizont) vs. `src/grid/labels.py:37` (ora locală în [6, 20) și PV > 0) — CONFIRMAT, impact mic (`audit/tests/test_s5_scoring_domain.py`)
- Ce e greșit: `evaluate` punctează doar intervalele care au etichetă, deci domeniul evaluării îl stabilește filtrul din grid, nu regula documentată de ML. Cele două pot diverge la orice schimbare (DST, altă țară, alt fus).
- Cum se manifestă: pe PT-A, 56 de intervale de zi cu PV (0,32 %, toate la ora 5 locală, vara) nu primesc niciodată etichetă, adică 0,001 % din energia PV. Azi e neglijabil. Cu S3 reparat (alt fus orar), filtrul fix „6–20 h” ar tăia ore întregi.
- Cum se repară: o singură funcție, `domain()` (`audit/proposals/scoring_domain.py`: soarele sus sau PV > 0), folosită și de generator, și de `split.daylight`.

---

## 4. Ce funcționează (ca să nu fie confundat cu problemele)
- Split cronologic pe dată locală, fără shuffle și fără early stopping ascuns. Testul nu e citit la antrenare.
- Features fără look-ahead și cu paritate exactă între antrenare și inferență (verificat empiric, nu doar din cod).
- DST și UTC sunt tratate corect în profiluri; poziția soarelui e corectă la 0,2°.
- Metricile sunt de decizie (export față de limita fixă și încălcări), nu MAPE. Baseline-urile sunt corecte. Există defalcări pe sezon și pe tip de cer, robustețe și drift.
- Antrenarea e deterministă, iar ieșirile marcate „MOCK” sunt bine separate.

---

## 5. Final

### Verdict
Rezultatele **nu sunt credibile, pentru că nu există**: singurele modele din repo sunt antrenate pe o țintă inventată (formulă liniară), iar etichetele reale nu pot ajunge la modele, fiindcă generatorul scrie altă schemă și pornește implicit pe anul de test sigilat. Codul ML din jur e scris îngrijit: features fără leakage, split cronologic, metrici de decizie, abstenție cu fallback. Totuși, chiar și pe mock modelul e prost calibrat (q90 acoperă 72 % în loc de 90 %) și are nevoie de 77 % abstenție ca să ajungă la 2 % încălcări. Pragul e ales pe trei luni de iarnă și va deriva vara. În producție modelul nu ar rezista în forma actuală: ar fi fie inutil (abstenție aproape totală), fie, cu un prag relaxat, ar depăși limita exact la marginile zilei, unde e cel mai sigur pe el.

### Top 5 probleme, după impact
1. **C1**: modele antrenate doar pe etichete mock; nu există niciun rezultat real și nu există date de test.
2. **C2**: schema generatorului de etichete reale e incompatibilă cu loader-ul ML.
3. **C3**: generatorul și README-ul folosesc implicit anul de test sigilat 2012-13.
4. **M1**: pragul de abstenție și hiper-parametrii se aleg pe apr.–iun., iar ținta de 2 % derivă (1,9 → 2,9 % chiar pe mock).
5. **M3 + M4**: etichetele doar pe zi forțează 14 % abstenție structurală, iar modelul e supra-încrezător la marginile zilei (11 % încălcări la spread mic).

### Plan de remediere (în ordine)
1. Sigilați din nou: scoateți valoarea implicită `2013-01-01` și exemplul cu 2012-13 din `src/grid/labels.py` și din README. Tăiați `weather_hourly.parquet` la 2012-06-30.
2. Aliniați schema: generatorul scrie exact `src/ml/labels.COLUMNS` plus `station_houses.parquet`, cu o listă fixă de case. Adăugați un test care trece o zi generată prin `labels_io.validate`.
3. Generați etichete reale pentru 2010-07 → 2012-06, cu `net_kw` și noaptea (sau `net_*` din profiluri). Curățați înainte zilele cu PV mort și seriile blocate.
4. Treceți la validare walk-forward pe tot anul 2011-12. Alegeți `tau` pe încălcări pe lună sau sezon și raportați holdout-ul separat.
5. Calibrați conformal q05 per oră sau elevație solară. Raportați acoperirea pe ore, plus încălcările doar pe intervalele în care limita contează și energia exportată peste limită.
6. Reantrenați, adăugați `schema_version` în metadata și verificați că `abstention.threshold()` merge pe modelul servit.
7. Abia apoi, o singură dată: `download --include-held-out`, `profiles`, `src.eval.run`. Cifrele din pitch vin doar din acest `summary.json`.
8. Opțional, după ce restul e stabil: features meteo **doar din prognoze** disponibile la `t`, un baseline probabilistic corect pentru PV și consum, și un lockfile pentru dependențe.
