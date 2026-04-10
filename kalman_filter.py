import numpy as np


class KalmanObject:
    def __init__(self, x, y, dt=0.15):
        # Stavový vektor [x, y, vx, vy] - pozice a rychlost
        self.state = np.array([x, y, 0, 0], dtype=float)
        # Matice kovariance (důvěra v aktuální odhad)
        self.P = np.eye(4) * 1.0
        # Matice přechodu stavu (F) - fyzikální model (posun o rychlost za čas dt)
        self.dt = dt
        self.F = np.array([
            [1, 0, self.dt, 0],
            [0, 1, 0, self.dt],
            [0, 0, 1, 0],
            [0, 0, 0, 1]
        ])
        # Matice měření (H) - říkáme, že z radaru dostáváme jen X a Y
        self.H = np.array([
            [1, 0, 0, 0],
            [0, 1, 0, 0]
        ])

        # --- ZMĚNĚNÉ NASTAVENÍ PRO STRESS TEST ---
        # Šum procesu (jak moc se může měnit rychlost sama od sebe)
        # Zvýšeno na 0.05 - filtr nyní bleskově reaguje na změny rychlosti a směru
        self.Q = np.eye(4) * 0.001

        # Šum měření (jak moc věříme radaru - menší číslo = větší důvěra)
        # Zvýšeno na 0.05 - kompromis pro vyhlazení drobných chyb radaru
        self.R = np.eye(2) * 0.02

        # Sledování "věku" stopy (jak dlouho nedostala reálná data)
        self.age = 0.0

    def predict(self):
        """Předpoví polohu objektu v příštím kroku."""
        self.state = self.F @ self.state
        self.P = self.F @ self.P @ self.F.T + self.Q
        return self.state[0], self.state[1]

    def update(self, meas_x, meas_y):
        """Opraví předpověď podle skutečného měření z radaru."""
        z = np.array([meas_x, meas_y])
        y = z - self.H @ self.state
        S = self.H @ self.P @ self.H.T + self.R
        K = self.P @ self.H.T @ np.linalg.inv(S)
        self.state = self.state + K @ y
        self.P = (np.eye(4) - K @ self.H) @ self.P

        self.age = 0.0  # Reset věku, stopa byla právě viděna