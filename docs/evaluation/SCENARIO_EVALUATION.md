# Scenario Evaluation

Tento dokument popisuje offline pipeline pro porovnani jednotlivych kombinaci
senzoru proti OptiTracku.

Strucny prehled souboru je take v `../../experiment_tools/README.md`.

## Co pipeline dela

Pipeline ma tri kroky:

1. `split_scenarios.py`
   - vezme jeden hlavni `raw.ndjson`
   - vytvori 13 scenaru
   - do kazde slozky ulozi filtrovanou verzi `raw.ndjson`

2. `run_offline_fusion.py`
   - pro kazdy scenar pusti existujici fusion logiku offline
   - ulozi `fused.ndjson`

3. `evaluate_all.py`
   - porovna fused vystupy s OptiTrack CSV
   - vygeneruje per-scenario grafy a souhrny

`scenario_splits/` je generovany vystup pipeline. Nejsou to puvodni namerena
data a lze ho kdykoliv znovu vytvorit.

## Scenare

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

## Jednim prikazem

Z korene projektu `Four`:

```powershell
.\experiment_tools\run_scenario_pipeline.ps1 `
  -RunDir .\runs\experiment\20260507_104346_Dronarena_04
```

Kdyz PowerShell blokuje lokalni skripty:

```powershell
powershell -ExecutionPolicy Bypass -File .\experiment_tools\run_scenario_pipeline.ps1 `
  -RunDir .\runs\experiment\20260507_104346_Dronarena_04
```

## Po krocich

```powershell
python .\experiment_tools\split_scenarios.py `
  --run-dir .\runs\experiment\20260507_104346_Dronarena_04

python .\experiment_tools\run_offline_fusion.py `
  --run-dir .\runs\experiment\20260507_104346_Dronarena_04

python .\experiment_tools\evaluate_all.py `
  --run-dir .\runs\experiment\20260507_104346_Dronarena_04 `
  --optitrack-csv .\data\optitrack\Take_2026-05-07_12.43.55_PM_Final.csv
```

## Jak se hodnoti scenare

### Position scenare

Do hlavni 3D evaluace patri:

- `radar1`
- `radar2`
- `2x_radar`
- `2x_ble`
- `radar1_2x_ble`
- `radar2_2x_ble`
- `fusion`

Tyto scenare se hodnoti klasickymi 3D metrikami:

- `mean_error_3d_m`
- `median_error_3d_m`
- `p95_error_3d_m`
- `max_error_3d_m`
- `rmse_3d_m`
- `mean_error_xy_m`
- `median_error_xy_m`
- `mean_abs_error_z_m`
- `median_abs_error_z_m`

Poznamka:

- `radar1`, `radar2`, `2x_radar` nevytvareji tagovane objekty
- evaluator proto sparuje anonymni radar track/clustery na GT cile v case

### Radar + single BLE anchor

Do samostatne evaluace patri:

- `radar1_ble1`
- `radar2_ble2`
- `2x_radar_ble1`
- `2x_radar_ble2`

Tyto scenare se nehodnoti pres hlavni fusion vystup, protoze aktualni online
fusion logika z `1x radar + 1x BLE` nevytvari tagovanou 3D pozici.

Misto toho evaluator offline:

- vezme BLE paprsek odpovidajici danemu tagu
- vezme radar clustery ve stejnem case
- vybere radar cluster nejblizsi BLE paprsku
- ten porovna proti OptiTracku stejnymi 3D metrikami

Proto jsou tyto scenare v samostatne summary sekci
`radar_ble_single_anchor/` a ne v hlavni `position/`.

### BLE-only scenare

Do BLE-only evaluace patri:

- `ble1`
- `ble2`

Tyto scenare se nehodnoti 3D RMSE, protoze jedna BLE kotva sama nevytvari plnou
3D pozici cile.

Pouzite BLE-only metriky:

- `ray distance`
  - kolma vzdalenost ground-truth bodu od BLE paprsku
- `angle error`
  - uhlova chyba mezi BLE paprskem a smerem od kotvy ke ground-truth bodu

## Struktura vystupu

Po dokonceni pipeline vznikne:

```text
scenario_splits/
+- <scenario>/
|  +- raw.ndjson
|  +- fused.ndjson
|  +- metadata.json
|  +- position_eval/
|  +- single_anchor_eval/
|  \- ble_only_eval/
\- _summary/
   +- README.txt
   +- evaluation_summary.json
   +- position/
   |  +- tables/
   |  \- boxplots/
   +- radar_ble_single_anchor/
   |  +- tables/
   |  \- boxplots/
   \- ble_only/
      +- tables/
      \- boxplots/
```

## Referencni Priklad

Aktualne je v repozitari hotove vyhodnoceni pro:

- run dir:
  - `runs/experiment/20260507_104346_Dronarena_04/`
- OptiTrack CSV:
  - `data/optitrack/Take_2026-05-07_12.43.55_PM_Final.csv`
- souhrny:
  - `runs/experiment/20260507_104346_Dronarena_04/scenario_splits/_summary/`

Strucny vysledek:

- `Phantom4`
  - nejlepsi 3D scenar: `2x_radar`, `rmse_3d_m = 0.397`
  - nejlepsi BLE-only scenar: `ble2`, `rmse_ray_distance_m = 0.375`
- `Vysavac3`
  - nejlepsi 3D scenar: `radar1`, `rmse_3d_m = 0.234`
  - nejlepsi BLE-only scenar: `ble1`, `rmse_ray_distance_m = 0.331`

## Co otevrit jako prvni

1. `_summary/position/tables/summary_table_Phantom4.jpg`
2. `_summary/position/tables/summary_table_Vysavac3.jpg`
3. `_summary/position/boxplots/`
4. `_summary/ble_only/tables/`
5. konkretni `<scenario>/position_eval/` nebo `<scenario>/ble_only_eval/`

## Doporuceni k interpretaci

- neporovnavej `ble1` a `ble2` primo ve stejne tabulce s 3D fusion scenari
- `position` a `ble_only` jsou dve ruzne metodiky
- pokud potrebujes hlavni poradi variant pro diplomku nebo report, ber jako
  primarni:
  - `_summary/position/tables/summary_table_[Objekt].csv`
  - `_summary/ble_only/tables/summary_table_ble_only_[Objekt].csv`
