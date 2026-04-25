# Arena Checklist

Checklist pro mereni v Dronarene. Cilem je odvezt si kazdy beh tak, aby sel
doma prehrat a vyhodnotit proti OptiTracku bez dalsiho dohadovani.

## Co Se Spousti

V rezimu single-node:

- `main.py` spustis jednou a nechas bezet

V rezimu `2x UP Board`:

- na `central` spustis `./scripts/start_up_central.sh`
- na `edge` spustis `./scripts/start_up_edge.sh <IP_centralu>`
- recorder spoustis jen na `central`

Pro kazdy jednotlivi test:

- spustis `record_experiment --label <nazev_testu>`
- po skonceni testu recorder zastavis `Ctrl+C`

`record_experiment` zaroven:

- nahraje MQTT data do `runs\experiment\...`
- prepne aktivni `run_id` pro bezici procesy na stejnem filesystemu

Poznamka pro `2x UP Board`:

- recorder na `centralu` korektne nahraje `raw` i `fused` MQTT data z celeho systemu
- recorder na `centralu` ale automaticky neprepina edge diagnostiku v `runs\diagnostic`, pokud edge bezi na vlastnim filesystemu

## Pred Odjezdem

- [ ] Otestovat, ze na centralnim nodu bezi MQTT broker.
- [ ] Otestovat, ze na centralnim nodu bezi PostgreSQL a aplikace se do ni pripoji.
- [ ] Otestovat start ve stejnem rezimu, ve kterem pojedu v arene.
- [ ] Pro `2x UP Board` otestovat `./scripts/start_up_central.sh` i `./scripts/start_up_edge.sh <IP_centralu>`.
- [ ] Otestovat `python -m Four.experiment_tools.record_experiment --label test --duration 10`.
- [ ] Otestovat, ze se vytvori `runs\experiment\...`.
- [ ] Pokud chci hlubsi diagnostiku, nechat zapnute `FOUR_CAPTURE_RAW_SERIAL=1`.
- [ ] Otestovat, ze se pri zapnute diagnostice vytvori `runs\diagnostic\...`.
- [ ] Zkontrolovat `config.py` nebo `FOUR_*` pro aktualni porty senzoru.
- [ ] Pro `2x UP Board` overit skutecne `/dev/ttyACM*` a `/dev/ttyUSB*` na obou nodech.
- [ ] Zkontrolovat `config.py` nebo `FOUR_*` pro pozice a rotace radar/BLE.
- [ ] Pripravit si nazvy testu, napr. `static_01`, `linear_01`, `crossing_01`.
- [ ] Pripravit mapovani `BLE tag -> objekt -> OptiTrack rigid body`.

## Po Prijezdu Do Areny

- [ ] Umistit radary a BLE do finalnich pozic.
- [ ] Zmerit a zapsat skutecne pozice radar/BLE.
- [ ] Zapsat skutecne natoceni radar/BLE.
- [ ] Overit napajeni vsech senzoru.
- [ ] Overit kabelaz a stabilitu portu senzoru.
- [ ] Overit, ze OptiTrack vidi vsechny rigid body.
- [ ] Overit, ze BLE tagy jsou na spravnych objektech.
- [ ] Udelat kratky 20-30 s sanity test.

## Start Dne V Arene

- [ ] Otevrit terminal na `central` a `edge`.
- [ ] Na `central` spustit `./scripts/start_up_central.sh`.
- [ ] Na `edge` spustit `./scripts/start_up_edge.sh <IP_centralu>`.
- [ ] Otevrit dashboard z `centralu` a overit, ze tecou data.
- [ ] Pokud je API port obsazeny, nastavit jiny `FOUR_API_PORT`.
- [ ] Overit, ze `central` i `edge` bezi stabilne aspon kratkou chvili pred prvnim merenim.
- [ ] Overit, ze `central` dostava `sensors/raw/radar_1`, `sensors/raw/radar_2`, `sensors/raw/ble_1`, `sensors/raw/ble_2`.
- [ ] Overit, ze se na `centralu` generuje `sensors/fused`.

## Pred Kazdym Behem

- [ ] Zapsat nazev behu.
- [ ] Zapsat, kdo nebo co se bude pohybovat.
- [ ] Zapsat, ktery BLE tag patri kteremu objektu.
- [ ] Zapsat, ktery OptiTrack rigid body patri kteremu objektu.
- [ ] Zkontrolovat, ze stale bezi `central` i `edge`.
- [ ] Zkontrolovat dashboard a pritok dat na `centralu`.
- [ ] Spustit `record_experiment.py` s jasnym `--label` jen na `centralu`.
- [ ] Overit, ze label odpovida planovanemu nazvu testu.
- [ ] Pokud je potreba hlubsi diagnostika, overit `FOUR_CAPTURE_RAW_SERIAL=1` a vedet, jestli chci i edge diagnostiku.
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
- [ ] Pokud byla zapnuta diagnostika, overit i `runs\diagnostic\<RUN_ID>\...` na `centralu`.
- [ ] Pokud jsem sbiral i edge diagnostiku, pocitat s tim, ze bez synchronizace `run_id` nemusi mit stejny label jako central.
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

1. Na `central` spustit `./scripts/start_up_central.sh`.
2. Na `edge` spustit `./scripts/start_up_edge.sh <IP_centralu>`.
3. Na `central` spustit `python -m Four.experiment_tools.record_experiment --label "static_01"`.
4. Udelat mereni.
5. Zastavit recorder `Ctrl+C`.
6. Pro dalsi test spustit recorder znovu s novym `--label`.
