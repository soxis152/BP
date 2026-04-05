# Testovací scénáře sledování pohybu

## 1. Průchod napříč místností (Lineární pohyb)

**Popis:**
Objekt (člověk) vstoupí do sledovaného prostoru z levé strany, pohybuje se rovnoměrně po přímce a opustí prostor na pravé straně.

**Co to testuje:**
- Základní funkčnost systému (detekce a přiřazení unikátního ID)
- Stabilitu Kalmanova filtru (konstantní rychlost a směr)
- Chování na okrajích zorného pole (vznik a zánik detekce)

**Očekávaný výsledek:**
- Jedna souvislá trajektorie bez skoků
- Jedno konzistentní ID po celou dobu průchodu

---

## 2. Chůze dokola (Kruhová trajektorie)

**Popis:**
Objekt se pohybuje po kružnici nebo elipse kolem středu místnosti.

**Co to testuje:**
- Schopnost systému reagovat na neustálou změnu směru
- Robustnost Kalmanova filtru (korekce nelineárního pohybu)
- Stabilitu fúze dat při změně orientace vůči senzorům
- Přechody mezi radary a BLE kotvami

**Očekávaný výsledek:**
- Plynulá kruhová trajektorie (bez ostrých lomů)
- Stabilní ID po celou dobu pohybu

---

## 3. Stop and Go (Pohyb s přestávkami)

**Popis:**
Objekt ujde přibližně 2 metry, zastaví se na 5 sekund a poté pokračuje (případně jiným směrem).

**Co to testuje:**
- Odolnost vůči mikropohybům a šumu radaru
- Stabilitu DBSCAN clusteringu při nehybném objektu
- Chování Kalmanova filtru při nulové rychlosti
- Udržení ID při krátkodobé neaktivitě

**Očekávaný výsledek:**
- Objekt zůstane vizuálně stabilní během zastavení
- Nedochází k "poskakování" bodu
- Po rozchodu systém plynule naváže se stejným ID

---

## 4. Křížení drah dvou osob (X-Pattern)

**Popis:**
Dvě osoby (A a B) jdou proti sobě z různých rohů místnosti. Uprostřed se těsně minou a pokračují dál.

**Co to testuje:**
- Schopnost oddělení blízkých shluků (DBSCAN)
- Stabilitu trackingu při minimální vzdálenosti objektů
- Prevence přepnutí ID (ID switch)

**Očekávaný výsledek:**
- Dva oddělené objekty po celou dobu
- Konzistentní ID pro oba objekty
- Po křížení si objekty nevymění ID

---

## 5. Cik-cak a náhlá změna rychlosti (Dynamický pohyb)

**Popis:**
Objekt se pohybuje nepravidelně – pomalá chůze, náhlé zrychlení, úskoky do stran, ostré zastavení a otočka o 180°.

**Co to testuje:**
- Latenci systému (frontend + WebSocket)
- Schopnost reagovat na náhlé změny směru a rychlosti
- Nastavení Kalmanova filtru (setrvačnost vs. adaptivita)

**Očekávaný výsledek:**
- Rychlá reakce systému na změny pohybu
- Minimální "přestřelování" trajektorie
- Trajektorie odpovídá reálnému pohybu bez výrazného zpoždění
