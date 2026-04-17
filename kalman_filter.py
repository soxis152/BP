import numpy as np


# Tento modul obsahuje jednoduchý Kalmanův filtr pro sledování pohybu v rovině X-Y.
#
# Proč filtrujeme jen X a Y:
# - v aktuální architektuře je nejdůležitější stabilní poloha objektu v mapě místnosti,
# - osa Z se ve fusion vrstvě drží odděleně jako poslední známá výška radarového clusteru,
# - model tak zůstává jednoduchý, rychlý a dobře laditelný.
#
# Stav objektu je:
#   [x, y, vx, vy]

class KalmanObject:
    """Jedna sledovaná stopa s modelem konstantní rychlosti."""

    def __init__(self, tag_id, x0, y0, z0, dt=0.1):
        self.tag_id = tag_id

        # Stavový vektor [x, y, vx, vy].
        # Nový objekt vzniká na známé poloze, ale s nulovou počáteční rychlostí.
        self.state = np.array([x0, y0, 0, 0], dtype=float)
        self.z = z0  # Výšku si držíme mimo matice

        # Kovarianční matice P vyjadřuje naši nejistotu o aktuálním stavu.
        self.P = np.eye(4) * 1.0

        # Transformační matice F (model konstantní rychlosti).
        self.F = np.array([
            [1, 0, dt, 0],
            [0, 1, 0, dt],
            [0, 0, 1, 0],
            [0, 0, 0, 1]
        ])

        # Matice pozorování H (měříme pouze polohu x a y, rychlost ne).
        self.H = np.array([
            [1, 0, 0, 0],
            [0, 1, 0, 0]
        ])

        # Q = procesní šum. (Jak moc může objekt nečekaně změnit směr).
        # ZMĚNA: Velmi nízká hodnota (0.01). Tečka nebude tolik uskakovat do stran.
        self.Q = np.eye(4) * 0.01

        # R = měřicí šum. (Jak moc věříme samotnému radarovému měření).
        # ZMĚNA: Vysoká hodnota (1.5). Filtr bude silně vyhlazovat skákání těžiště
        # a povede tečku raději setrvačností.
        self.R = np.eye(2) * 1.5

        # Počítadlo pro detekci "ztráty" objektu
        self.missed_frames = 0
        self.update_count = 1

    @property
    def x(self):
        return self.state[0]

    @property
    def y(self):
        return self.state[1]

    def predict(self, dt=0.1):
        """Provede predikci stavu do dalšího kroku (Coasting)."""
        # Aktualizace časového kroku v matici F
        self.F[0, 2] = dt
        self.F[1, 3] = dt

        self.state = self.F @ self.state
        self.P = self.F @ self.P @ self.F.T + self.Q

        self.missed_frames += 1
        return float(self.x), float(self.y)

    def update(self, meas_x, meas_y, meas_z):
        """Opraví predikovaný stav podle skutečného radarového měření."""
        self.z = meas_z  # Aktualizace výšky
        z_meas = np.array([meas_x, meas_y])

        # Inovace (rozdíl mezi měřením a predikcí)
        y = z_meas - (self.H @ self.state)

        # Inovační kovariance
        S = self.H @ self.P @ self.H.T + self.R

        # Kalmanův zisk
        K = self.P @ self.H.T @ np.linalg.inv(S)

        # Aktualizace stavu a kovariance
        self.state = self.state + (K @ y)
        I = np.eye(self.P.shape[0])
        self.P = (I - K @ self.H) @ self.P