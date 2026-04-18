# Four

Projekt pro sber, fuzi a vizualizaci dat z radaru a BLE kotev.

Datovy tok:

```text
radar/BLE senzory -> ingestion.py -> MQTT -> fusion.py -> MQTT -> app.py -> WebSocket -> index.html
```

## Pozadavky

- Python 3.11 nebo novejsi
- MQTT broker dostupny na `127.0.0.1:1883`
- PostgreSQL dostupny na `127.0.0.1:5432`
- Databaze `sensor_data`
- Databazovy uzivatel `postgres` s heslem `postgres`
- Pro ostry beh fyzicke senzory na COM portech nastavenych v `ingestion.py`

Projekt aktualne pouziva lokalni konfiguraci natvrdo ve zdrojovych souborech. Hlavni mista:

- `db_handler.py`: pripojeni k PostgreSQL
- `app.py`: pripojeni k PostgreSQL pro webovou vrstvu
- `ingestion.py`: COM porty radaru, BLE kotev a cesta k radarovemu profilu
- `fusion.py`: MQTT host a parametry parovani/fuze

## Instalace

Z korenove slozky projektu:

```powershell
cd C:\Users\kabup\OneDrive\Plocha\BP_\KOD\four
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Poznamka: skutecna cesta v tomto workspace obsahuje znak s diakritikou ve slozce `KOD`. Pokud prikaz kopirujes, uprav cestu podle realneho nazvu slozky ve Windows.

## Databaze

Aplikace ocekava databazi `sensor_data`. Tabulky a indexy se vytvori automaticky pri startu DB workeru.

Priklad vytvoreni databaze pres `psql`:

```powershell
psql -U postgres -h 127.0.0.1 -c "CREATE DATABASE sensor_data;"
```

Pokud databaze uz existuje, tento krok neni potreba.

## MQTT

System ocekava MQTT broker na `127.0.0.1:1883`.

Pouzivane topicy:

```text
sensors/raw/radar_1
sensors/raw/radar_2
sensors/raw/ble_1
sensors/raw/ble_2
sensors/fused
```

`ingestion.py` publikuje syrova data do `sensors/raw/#`. `fusion.py` je cte, vytvori fused snapshot a publikuje ho do `sensors/fused`. `app.py` fused data preposila pres WebSocket dashboardu.

## Spusteni ostreho behu

Pred spustenim musi bezet PostgreSQL a MQTT broker. Take musi odpovidat COM porty v `ingestion.py`.

```powershell
cd C:\Users\kabup\OneDrive\Plocha\BP_\KOD\four
.\.venv\Scripts\Activate.ps1
python main.py
```

Dashboard potom otevri v prohlizeci:

```text
http://127.0.0.1:8000
```

`main.py` spousti tri casti v jednom procesu:

- ingestion worker pro radar/BLE vstupy a zapis do DB
- fusion loop pro clustering a parovani radar/BLE dat
- FastAPI server s dashboardem

## Samostatne spusteni casti

Fusion:

```powershell
python fusion.py
```

Web/API:

```powershell
uvicorn app:app --host 127.0.0.1 --port 8000
```

Ingestion:

```powershell
python ingestion.py
```

## Testovaci scenare

Ve slozce `test_soubory` jsou simulacni scenare, ktere generuji synteticka radarova a BLE mereni a posilaji je do stejneho MQTT rozhrani jako ostry system.

Aktualni scenare jsou popsane v `test_soubory/Popis_testu.md`.

Poznamka: testovaci helper aktualne pouziva importy ve tvaru `Four...`, zatimco slozka v tomto workspace je `four`. Na Windows to muze projit diky case-insensitive filesystemu, ale pro prenositelnost je vhodne importy pozdeji sjednotit.

Priklad spusteni prvniho scenare z nadrazene slozky projektu:

```powershell
cd C:\Users\kabup\OneDrive\Plocha\BP_\KOD
python -m four.test_soubory.test_01_linear_pass
```

Pro vyhodnoceni scenare musi bezet MQTT broker, PostgreSQL a idealne i `fusion.py` + `app.py`.

## Overeni syntaxe

Rychla kontrola, ze se vsechny Python soubory parsuji:

```powershell
python -c "import ast, pathlib; [ast.parse(p.read_text(encoding='utf-8'), filename=str(p)) for p in pathlib.Path('four').rglob('*.py')]; print('OK')"
```

## Zname technicke dluhy

- `kalman_filter.py` existuje, ale hlavni fusion vrstva ho zatim nepouziva.
- Nektere chyby ve fusion vrstve se pouze spolknou bez logovani.
- Konfigurace je zatim natvrdo ve zdrojacich misto `.env` nebo konfiguracniho souboru.
