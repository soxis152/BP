# Testovací scénáře sledování pohybu

## 1. Lineární průchod (Linear Pass)

**Popis:**  
Objekt se pohybuje konstantní rychlostí v ose X zleva doprava, s fixní pozicí v osách Y a Z. Po dosažení hranice prostoru je resetován na začátek.

**Co to testuje:**
- Základní funkčnost trackingu
- Stabilitu Kalmanova filtru při lineárním pohybu
- Chování při spawn/despawn (reset pozice)

**Očekávaný výsledek:**
- Hladká lineární trajektorie bez jitteru
- Konzistentní ID během průchodu
- Žádné ghost objekty

---

## 2. Kruhový pohyb (Circular Motion)

**Popis:**  
Objekt se pohybuje po eliptické trajektorii pomocí sinusových funkcí. Současně dochází k malé oscilaci v ose Z.

**Co to testuje:**
- Nelineární pohyb
- Schopnost filtru reagovat na změnu směru
- Stabilitu 3D fúze dat

**Očekávaný výsledek:**
- Plynulá trajektorie bez ostrých lomů
- Stabilní ID
- Minimální zkreslení trajektorie

---

## 3. Stop & Go (Trojuhelník)

**Popis:**  
Objekt se pohybuje mezi třemi body (trojúhelník), přičemž v každém bodě se na určitou dobu zastaví.

**Co to testuje:**
- Stabilitu při nulové rychlosti
- Chování clusteringu při statickém objektu
- Přechody mezi pohybem a zastavením

**Očekávaný výsledek:**
- Stabilní pozice během zastavení
- Plynulé přechody mezi body
- Konzistentní ID

---

## 4. Křížení drah (X-Pattern)

**Popis:**  
Dva objekty se pohybují proti sobě diagonálně a kříží se uprostřed prostoru. Po dosažení hranice se resetují.

**Co to testuje:**
- Separaci objektů
- Data association
- Prevence ID switch

**Očekávaný výsledek:**
- Dva oddělené tracky
- Stabilní ID pro oba objekty
- Žádné prohození ID

---

## 5. Dynamický stress test (ZigZag + změny rychlosti)

**Popis:**  
Objekt se pohybuje mezi waypointy s různou rychlostí, včetně náhlých změn směru, zastavení a odrazů od hranic.

**Co to testuje:**
- Adaptivitu Kalmanova filtru
- Reakci na náhlé změny pohybu
- Stabilitu systému při extrémních podmínkách

**Očekávaný výsledek:**
- Plynulá trajektorie odpovídající pohybu
- Minimální overshoot
- Stabilní ID

---

## 6. Occlusion / výpadky senzorů

**Popis:**  
Objekt se pohybuje lineárně, přičemž dochází k:
- výpadku radaru
- krátkému úplnému výpadku (radar + BLE)
- následnému návratu detekce

**Co to testuje:**
- Robustnost při částečné a úplné ztrátě dat
- Predikci bez měření
- Re-identifikaci objektu

**Očekávaný výsledek:**
- Trajektorie pokračuje během výpadku
- Po návratu dat plynulé navázání
- Zachování ID

---

## 7. Noise Injection (Šum v datech)

**Popis:**  
Objekt se pohybuje po stejné trajektorii, ale postupně se zvyšuje úroveň šumu v radarových i BLE datech.

**Co to testuje:**
- Odolnost vůči šumu
- Stabilitu clusteringu
- Vyhlazování trajektorie

**Očekávaný výsledek:**
- Stabilní trajektorie i při vyšším šumu
- Žádný rozpad tracku
- Bez náhodných skoků

---

## 8. ID Recovery (Znovunalezení objektu)

**Popis:**  
Objekt se pohybuje, následně úplně zmizí (výpadek všech senzorů) a po čase se znovu objeví.

**Co to testuje:**
- Re-identifikaci objektu
- Track management (timeouty)
- Data association po výpadku

**Očekávaný výsledek:**
- Krátký výpadek → zachování ID
- Delší výpadek → kontrolované nové ID
- Bez duplicitních tracků

---

## 9. Vertikální pohyb (3D Vertical Motion)

**Popis:**  
Objekt mění pozici nejen v X-Y, ale i v ose Z:
- stoupání
- pohyb ve výšce
- klesání
- návrat

**Co to testuje:**
- Správné zpracování osy Z
- 3D tracking
- Přesnost vertikálního pohybu

**Očekávaný výsledek:**
- Plynulá změna výšky
- Bez skoků v Z
- Stabilní ID

---

## 10. Spirálový pohyb (3D Spiral Motion)

**Popis:**  
Objekt se pohybuje po spirále — kombinace kruhového pohybu v X-Y a lineárního růstu v Z.

**Co to testuje:**
- Plně 3D trajektorii
- Současnou změnu směru i výšky
- Stabilitu trackingu při komplexním pohybu

**Očekávaný výsledek:**
- Plynulá spirálová trajektorie
- Stabilní tracking bez jitteru
- Konzistentní ID
