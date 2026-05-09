# Documentation Index

Rozcestnik k dokumentaci projektu `Four`.

Struktura:

```text
docs/
+- README.md
+- operations/
|  +- README.md
|  +- ARENA_CHECKLIST.md
|  \- UPBOARD_START.md
\- evaluation/
|  +- README.md
|  \- SCENARIO_EVALUATION.md
```

## Co Otevrit Jako Prvni

- `operations/ARENA_CHECKLIST.md`
  - operativni checklist pro mereni v Dronarene
- `evaluation/SCENARIO_EVALUATION.md`
  - jak spustit offline pipeline nad jednim experimentem
- `operations/UPBOARD_START.md`
  - start systemu ve variante `central` + `edge`
- `operations/README.md`
  - rozcestnik provozni dokumentace
- `evaluation/README.md`
  - rozcestnik evaluacni dokumentace

## Doporucene Cteni Podle Situace

Kdyz jedu merit:

1. `operations/README.md`
2. `operations/ARENA_CHECKLIST.md`
3. `operations/UPBOARD_START.md`

Kdyz uz mam data a chci je vyhodnotit:

1. `evaluation/README.md`
2. `evaluation/SCENARIO_EVALUATION.md`
3. `../experiment_tools/README.md`
4. `../README.md`

## Kde Je Co Vystupem

- live system a recorder:
  - `runs/experiment/<run>/`
- scenario evaluace:
  - `runs/experiment/<run>/scenario_splits/`
- souhrny evaluace:
  - `runs/experiment/<run>/scenario_splits/_summary/`

## Hotovy Priklad V Repozitari

Aktualne je hotove vyhodnoceni pro:

- `runs/experiment/20260507_104346_Dronarena_04/`

Nejkratsi cesta k vysledkum:

1. `../runs/experiment/20260507_104346_Dronarena_04/scenario_splits/_summary/README.txt`
2. `../runs/experiment/20260507_104346_Dronarena_04/scenario_splits/_summary/position/tables/`
3. `../runs/experiment/20260507_104346_Dronarena_04/scenario_splits/_summary/ble_only/tables/`

## Poznamka

Dokumentace v `docs/` popisuje provoz a workflow.
Detail jednotlivych evaluacnich skriptu je v `experiment_tools/README.md`.
Nove dokumenty davej prednostne do podslozek `operations/` a `evaluation/`
misto dalsiho zaplnovani rootu `docs/`.
