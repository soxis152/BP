# Documentation Index

Rozcestnik k dokumentaci projektu `Four`.

## Co Otevrit Jako Prvni

- `ARENA_CHECKLIST.md`
  - operativni checklist pro mereni v Dronarene
- `SCENARIO_EVALUATION.md`
  - jak spustit offline pipeline nad jednim experimentem
- `UPBOARD_START.md`
  - start systemu ve variante `central` + `edge`

## Doporucene Cteni Podle Situace

Kdyz jedu merit:

1. `ARENA_CHECKLIST.md`
2. `UPBOARD_START.md`

Kdyz uz mam data a chci je vyhodnotit:

1. `SCENARIO_EVALUATION.md`
2. `../experiment_tools/README.md`
3. `../README.md`

## Kde Je Co Vystupem

- live system a recorder:
  - `runs/experiment/<run>/`
- scenario evaluace:
  - `runs/experiment/<run>/scenario_splits/`
- souhrny evaluace:
  - `runs/experiment/<run>/scenario_splits/_summary/`

## Poznamka

Dokumentace v `docs/` popisuje provoz a workflow.
Detail jednotlivych evaluacnich skriptu je v `experiment_tools/README.md`.
