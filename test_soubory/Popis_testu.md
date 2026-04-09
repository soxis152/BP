# Testovací scénáře sledování pohybu (IMPLEMENTAČNÍ VERZE)

## 1. Lineární průchod (Linear Pass)

**Popis:**  
Objekt se pohybuje konstantní rychlostí v ose X zleva doprava (~0.18 m/s), s fixní pozicí Y a Z. Po dosažení hranice prostoru (x > 3.2) je resetován zpět na začátek.

**Co to testuje:**
- Stabilitu trackingu při konstantním pohybu
- Predikční schopnost Kalmanova filtru (lineární model)
- Chování systému při resetu pozice (edge case)
- Robustnost vůči opakovanému spawn/despawn cyklu

**Očekávaný výsledek:**
- Hladká lineární trajektorie bez jitteru
- Konzistentní ID během průchodu
- Žádné „ghost objekty“ po resetu

---

## 2. Kruhový pohyb (Circular Motion)

**Popis:**  
Objekt se pohybuje po eliptické trajektorii kolem středu (1.5, 1.5) pomocí funkcí cos/sin. V ose Z je malá sinusová oscilace.

**Co to testuje:**
- Nelineární pohyb (změna směru v každém kroku)
- Schopnost Kalman filtru aproximovat zakřivené trajektorie
- Stabilitu fúze dat při změně orientace vůči senzorům
- Přesnost v ose Z

**Očekávaný výsledek:**
- Plynulá eliptická trajektorie
- Minimální deformace trajektorie
- Stabilní ID bez výpadků

---

## 3. Stop & Go v trojúhelníku (Triangle Stop-Go)

**Popis:**  
Objekt se pohybuje mezi třemi body (trojúhelník). V každém vrcholu se zastaví (čekání), poté pokračuje lineární interpolací k dalšímu bodu.

**Co to testuje:**
- Stabilitu systému při nulové rychlosti
- DBSCAN clustering při nehybném objektu
- Přechody mezi pohybem a zastavením
- Chování při waypoint-based pohybu

**Očekávaný výsledek:**
- Stabilní pozice během zastavení (bez driftu)
- Plynulé přechody mezi body
- Konzistentní ID po celou dobu

---

## 4. Křížení drah (X-Pattern)

**Popis:**  
Dva objekty se pohybují diagonálně proti sobě a kříží se uprostřed prostoru. Po dosažení hranice se resetují na výchozí pozice.

**Co to testuje:**
- Separaci objektů při minimální vzdálenosti
- Data association (přiřazení měření ke tracku)
- Prevence ID switch
- Stabilitu při symetrickém pohybu

**Očekávaný výsledek:**
- Dva oddělené objekty po celou dobu
- Konzistentní ID pro oba objekty
- Žádné prohození ID při křížení

---

## 5. Dynamický stress test (ZigZag + změny rychlosti)

**Popis:**  
Objekt se pohybuje mezi waypointy s různou rychlostí (0 až ~4 m/s), včetně:
- pomalého pohybu
- náhlého zrychlení
- prudkých změn směru
- úplného zastavení

Používá se inerční model (plynulá změna rychlosti) a odrazy od hranic prostoru.

**Co to testuje:**
- Adaptivitu Kalmanova filtru
- Latenci systému (backend → MQTT → frontend)
- Reakci na náhlé změny pohybu
- Stabilitu při extrémních podmínkách
- Boundary handling (odrazy)

**Očekávaný výsledek:**
- Trajektorie odpovídající waypointům
- Rychlá reakce na změny směru
- Minimální overshoot
- Stabilní ID i při chaotickém pohybu
