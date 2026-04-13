import numpy as np

# Tento modul obsahuje jednoduchý Kalmanův filtr pro sledování pohybu v rovině X-Y.
#
# Proč filtrujeme jen X a Y:
# - v aktuální architektuře je nejdůležitější stabilní poloha objektu v mapě místnosti,
# - osa Z se v fusion vrstvě drží odděleně jako poslední známá výška radarového clusteru,
# - model tak zůstává jednoduchý, rychlý a dobře laditelný.
#
# Stav objektu je:
#   [x, y, vx, vy]
# tedy:
# - x, y ... poloha
# - vx, vy ... rychlost


class KalmanObject:
    """Jedna sledovaná stopa s modelem konstantní rychlosti."""

    def __init__(self, x, y, dt=0.15):
        # Stavový vektor [x, y, vx, vy].
        # Nový objekt vzniká na známé poloze, ale s nulovou počáteční rychlostí.
        self.state = np.array([x, y, 0, 0], dtype=float)

        # Kovarianční matice P vyjadřuje naši nejistotu o aktuálním stavu.
        # Na začátku ji nastavujeme na jednotkovou matici, tedy střední výchozí nejistotu.
        self.P = np.eye(4) * 1.0

        # dt je délka jednoho fusion kroku.
        # V projektu odpovídá zhruba periodě, s jakou běží fusion smyčka.
        self.dt = dt

        # Přechodová matice F popisuje model konstantní rychlosti:
        # x_{k+1} = x_k + vx_k * dt
        # y_{k+1} = y_k + vy_k * dt
        # rychlosti zůstávají mezi kroky stejné, pokud nepřijde korekce měřením.
        self.F = np.array(
            [
                [1, 0, self.dt, 0],
                [0, 1, 0, self.dt],
                [0, 0, 1, 0],
                [0, 0, 0, 1],
            ]
        )

        # Měřicí matice H říká, že z radaru dostáváme pouze polohu X a Y.
        # Radar v tomto modelu přímo neměří rychlost.
        self.H = np.array(
            [
                [1, 0, 0, 0],
                [0, 1, 0, 0],
            ]
        )

        # Q = procesní šum.
        #
        # Vyjadřuje, jak moc připouštíme, že se objekt mezi kroky mohl začít chovat jinak,
        # než předpokládá model konstantní rychlosti.
        #
        # Vyšší Q:
        # - filtr rychleji reaguje na prudké změny směru a rychlosti,
        # - ale je méně hladký.
        self.Q = np.eye(4) * 0.05

        # R = měřicí šum.
        #
        # Vyjadřuje, jak moc věříme samotnému radarovému měření.
        # Vyšší R znamená:
        # - větší vyhlazení,
        # - menší ochotu "skočit" za každým novým bodem radaru.
        self.R = np.eye(2) * 0.05

        # age je pomocná hodnota fusion vrstvy:
        # kolik sekund uplynulo od posledního skutečného měření radarem.
        self.age = 0.0

    def predict(self):
        """Provede predikci stavu do dalšího kroku.

        Tato část běží i tehdy, když zrovna nepřišlo nové radarové měření.
        Díky tomu umí stopa krátkodobě pokračovat plynule po trajektorii.
        """
        self.state = self.F @ self.state
        self.P = self.F @ self.P @ self.F.T + self.Q
        return self.state[0], self.state[1]

    def update(self, meas_x, meas_y):
        """Opraví predikovaný stav podle skutečného radarového měření.

        Postup:
        1. spočítáme inovační chybu mezi měřením a predikcí,
        2. spočítáme Kalmanův zisk,
        3. upravíme stav i kovarianci.
        """
        z = np.array([meas_x, meas_y])
        y = z - self.H @ self.state
        S = self.H @ self.P @ self.H.T + self.R
        K = self.P @ self.H.T @ np.linalg.inv(S)

        self.state = self.state + K @ y
        self.P = (np.eye(4) - K @ self.H) @ self.P

        # Jakmile přišlo reálné radarové měření, stopa je znovu "čerstvá".
        self.age = 0.0
