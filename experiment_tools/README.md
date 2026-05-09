# Experiment Tools

Prehled pomocnych skriptu pro zaznam, replay a offline vyhodnoceni.

## Hlavni Casti

- `record_experiment.py`
  - recorder MQTT topicu do `runs/experiment/<run>/`
- `replay_raw.py`
  - prehrani `raw.ndjson` zpet do MQTT
- `replay_compare.py`
  - wrapper pro replay s OptiTrack referenci
- `optitrack_replay.py`
  - samostatny replay OptiTrack dat

## Scenario Pipeline

Offline pipeline pro porovnani kombinaci senzoru proti OptiTracku:

1. `split_scenarios.py`
2. `run_offline_fusion.py`
3. `evaluate_all.py`

Aktualni sada scenaru:

- `ble1`
- `ble2`
- `radar1`
- `radar2`
- `radar1_ble1`
- `radar2_ble2`
- `2x_radar`
- `2x_radar_ble1`
- `2x_radar_ble2`
- `2x_ble`
- `radar1_2x_ble`
- `radar2_2x_ble`
- `fusion`

Jednim prikazem:

```powershell
.\experiment_tools\run_scenario_pipeline.ps1 `
  -RunDir .\runs\experiment\20260507_104346_Dronarena_04
```

Po krocich:

```powershell
python .\experiment_tools\split_scenarios.py `
  --run-dir .\runs\experiment\20260507_104346_Dronarena_04

python .\experiment_tools\run_offline_fusion.py `
  --run-dir .\runs\experiment\20260507_104346_Dronarena_04

python .\experiment_tools\evaluate_all.py `
  --run-dir .\runs\experiment\20260507_104346_Dronarena_04
```

Poznamka:

- `scenario_splits/` je vystup teto pipeline
- neni to soucast puvodniho experimentu
- lze ho kdykoliv znovu vygenerovat

## Co Ktery Soubor Dela

- `scenario_pipeline_common.py`
  - sdilene definice scenaru, topicu a pomocnych cest
- `split_scenarios.py`
  - vytvori `scenario_splits/<scenario>/raw.ndjson`
- `run_offline_fusion.py`
  - spusti stavajici `fusion.py` offline nad kazdym scenarem
- `evaluate_all.py`
  - vytvori per-scenario grafy, statistiky a souhrny
- `run_scenario_pipeline.ps1`
  - wrapper pro split -> fusion -> evaluate

## Kde Hledat Vystupy

- detail scenare:
  - `runs/experiment/<run>/scenario_splits/<scenario>/`
- 3D vyhodnoceni:
  - `<scenario>/position_eval/`
- single-anchor radar+BLE vyhodnoceni:
  - `<scenario>/single_anchor_eval/`
- BLE-only vyhodnoceni:
  - `<scenario>/ble_only_eval/`
- souhrny:
  - `runs/experiment/<run>/scenario_splits/_summary/`

Prvni soubor, ktery ma smysl otevrit po dobehu pipeline:

- `runs/experiment/<run>/scenario_splits/_summary/README.txt`

## Aktualni Hotovy Priklad

V repozitari je uz hotovy prepocitany a vyhodnoceny beh:

- `runs/experiment/20260507_104346_Dronarena_04/`

Souhrny:

- `runs/experiment/20260507_104346_Dronarena_04/scenario_splits/_summary/`

Nejkratsi cesta:

1. `_summary/README.txt`
2. `position/tables/summary_table_Phantom4.csv`
3. `position/tables/summary_table_Vysavac3.csv`
4. `ble_only/tables/summary_table_ble_only_Phantom4.csv`
5. `ble_only/tables/summary_table_ble_only_Vysavac3.csv`

## Souvisejici Dokumentace

- `../docs/evaluation/SCENARIO_EVALUATION.md`
- `../docs/operations/ARENA_CHECKLIST.md`
- `../README.md`
