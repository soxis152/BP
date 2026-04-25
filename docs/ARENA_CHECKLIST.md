# Arena Checklist

Checklist pro mereni v Dronarene. Cilem je odvezt si kazdy beh tak, aby sel
doma prehrat a vyhodnotit proti OptiTracku bez dalsiho dohadovani.

## Co Se Spousti

Na zacatku dne:

- `main.py` spustis jednou a nechas bezet

Pro kazdy jednotlivi test:

- spustis `record_experiment --label <nazev_testu>`
- po skonceni testu recorder zastavis `Ctrl+C`

`record_experiment` zaroven:

- nahraje MQTT data do `runs\experiment\...`
- prepne aktivni `run_id` pro bezici `main.py`

## Pred Odjezdem

- [ ] Otestovat, ze na notebooku bezi MQTT broker.
- [ ] Otestovat, ze bezi PostgreSQL a aplikace se do ni pripoji.
- [ ] Otestovat `python main.py` v laboratornim prostredi.
- [ ] Otestovat `python -m Four.experiment_tools.record_experiment --label test --duration 10`.
- [ ] Otestovat, ze se vytvori `runs\experiment\...`.
- [ ] Pokud chci hlubsi diagnostiku, nechat zapnute `FOUR_CAPTURE_RAW_SERIAL=1`.
- [ ] Otestovat, ze se pri zapnute diagnostice vytvori `runs\diagnostic\...`.
- [ ] Zkontrolovat `config.py` nebo `FOUR_*` pro aktualni COM porty.
- [ ] Zkontrolovat `config.py` nebo `FOUR_*` pro pozice a rotace radar/BLE.
- [ ] Pripravit si nazvy testu, napr. `static_01`, `linear_01`, `crossing_01`.
- [ ] Pripravit mapovani `BLE tag -> objekt -> OptiTrack rigid body`.

## Po Prijezdu Do Areny

- [ ] Umistit radary a BLE do finalnich pozic.
- [ ] Zmerit a zapsat skutecne pozice radar/BLE.
- [ ] Zapsat skutecne natoceni radar/BLE.
- [ ] Overit napajeni vsech senzoru.
- [ ] Overit kabelaz a stabilitu COM portu.
- [ ] Overit, ze OptiTrack vidi vsechny rigid body.
- [ ] Overit, ze BLE tagy jsou na spravnych objektech.
- [ ] Udelat kratky 20-30 s sanity test.

## Start Dne V Arene

- [ ] Otevrit PowerShell v `Four`.
- [ ] Spustit `main.py`.
- [ ] Otevrit dashboard a overit, ze tecou data.
- [ ] Pokud je API port obsazeny, nastavit jiny `FOUR_API_PORT`.
- [ ] Overit, ze system bezi stabilne aspon kratkou chvili pred prvnim merenim.

## Pred Kazdym Behem

- [ ] Zapsat nazev behu.
- [ ] Zapsat, kdo nebo co se bude pohybovat.
- [ ] Zapsat, ktery BLE tag patri kteremu objektu.
- [ ] Zapsat, ktery OptiTrack rigid body patri kteremu objektu.
- [ ] Zkontrolovat, ze stale bezi `main.py`.
- [ ] Zkontrolovat dashboard a pritok dat.
- [ ] Spustit `record_experiment.py` s jasnym `--label`.
- [ ] Overit, ze label odpovida planovanemu nazvu testu.
- [ ] Pokud je potreba hlubsi diagnostika, overit `FOUR_CAPTURE_RAW_SERIAL=1`.
- [ ] Nechat recorder bezet jeste pred prvnim pohybem aspon 3-5 s.

## Doporucene Scenare

- [ ] Staticky objekt na nekolika bodech.
- [ ] Pomaly primy pruchod.
- [ ] Rychlejsi primy pruchod.
- [ ] Stop and go.
- [ ] Zmena vysky.
- [ ] Pohyb u hran a v rozich.
- [ ] Dva objekty krizem.
- [ ] Dva objekty blizko sebe.
- [ ] Kratke zakryti nebo dropout.
- [ ] Problemovy beh zamereny jen na BLE.
- [ ] Problemovy beh zamereny jen na radar.

## Po Skonceni Kazdeho Behu

- [ ] Nechat recorder bezet jeste 3-5 s po poslednim pohybu.
- [ ] Zastavit `record_experiment.py`.
- [ ] Zapsat poznamky: co se povedlo, co se nepovedlo, vypadky, kolize, zakryti.
- [ ] Overit, ze vznikla nova slozka v `runs\experiment\...`.
- [ ] Pokud byla zapnuta diagnostika, overit i `runs\diagnostic\<RUN_ID>\...`.
- [ ] Poznamenat si, ktery OptiTrack export patri ke kteremu behu.

## Co Si Odvezt Domu

- [ ] Slozku z `runs\experiment`.
- [ ] Slozku z `runs\diagnostic`, pokud byla zapnuta diagnostika.
- [ ] OptiTrack `.xlsx` export pro kazdy beh.
- [ ] Poznamky k behum.
- [ ] Finalni zamerene pozice a rotace senzoru.
- [ ] Fotku nebo nacrt rozmisteni senzoru v arene.

## Doma

- [ ] Vybrat jeden konkretni beh.
- [ ] Upravit parametry ve `fusion.py`.
- [ ] Spustit replay `raw.ndjson`.
- [ ] Ziskat novy fused vystup.
- [ ] Pustit evaluator proti OptiTrack `.xlsx`.
- [ ] Zapsat si zmenu parametru a vysledne metriky.
- [ ] Nemenit zaroven geometrii senzoru a fusion parametry bez zapisu.

## Minimalni Prakticky Postup

1. V jednom okne spustit `main.py`.
2. Pro test spustit `python -m Four.experiment_tools.record_experiment --label "static_01"`.
3. Udelat mereni.
4. Zastavit recorder `Ctrl+C`.
5. Pro dalsi test spustit recorder znovu s novym `--label`.
