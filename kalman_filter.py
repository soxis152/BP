"""Jednoduchy Kalmanuv filtr pro budouci tracking objektu.

Hlavni `fusion.py` ted pouziva clustering a parovaci heuristiku. Tento modul je
pripraveny jako samostatny stavebni blok pro pozdejsi rozsireni na skutecny
tracker.

Model sleduje stav `[x, y, vx, vy]`. Osa Z se zatim nefiltruje maticove, protoze
pro aktualni dashboard je nejdulezitejsi stabilni pudorysna poloha v X/Y.
"""

import numpy as np


class KalmanObject:
    """Jedna sledovana stopa s modelem konstantni rychlosti."""

    def __init__(
        self,
        tag_id,
        x0,
        y0,
        z0,
        dt=0.1,
        process_noise=0.01,
        measurement_noise=1.5,
        initial_covariance=1.0,
        z_smoothing_alpha=0.35,
    ):
        self.tag_id = tag_id
        self.state = np.array([x0, y0, 0, 0], dtype=float)
        self.z = z0
        self.z_smoothing_alpha = float(z_smoothing_alpha)

        self.P = np.eye(4) * float(initial_covariance)
        self.F = np.array([
            [1, 0, dt, 0],
            [0, 1, 0, dt],
            [0, 0, 1, 0],
            [0, 0, 0, 1],
        ])
        self.H = np.array([
            [1, 0, 0, 0],
            [0, 1, 0, 0],
        ])

        # Q urcuje, jak moc pripoustim necekane zmeny pohybu.
        self.Q = np.eye(4) * float(process_noise)

        # R urcuje, jak moc verim jednomu mereni proti predikci.
        self.R = np.eye(2) * float(measurement_noise)

        self.missed_frames = 0
        self.update_count = 1

    @property
    def x(self):
        return self.state[0]

    @property
    def y(self):
        return self.state[1]

    def set_process_noise(self, process_noise):
        self.Q = np.eye(4) * float(process_noise)

    def set_measurement_noise(self, measurement_noise):
        self.R = np.eye(2) * float(measurement_noise)

    def predict(self, dt=0.1):
        """Predikuje dalsi stav bez noveho mereni."""
        self.F[0, 2] = dt
        self.F[1, 3] = dt

        self.state = self.F @ self.state
        self.P = self.F @ self.P @ self.F.T + self.Q

        self.missed_frames += 1
        return float(self.x), float(self.y)

    def update(self, meas_x, meas_y, meas_z):
        """Opravi predikovany stav podle noveho mereni."""
        if self.update_count <= 1:
            self.z = meas_z
        else:
            alpha = self.z_smoothing_alpha
            self.z = (self.z * (1.0 - alpha)) + (meas_z * alpha)
        z_meas = np.array([meas_x, meas_y])

        innovation = z_meas - (self.H @ self.state)
        innovation_covariance = self.H @ self.P @ self.H.T + self.R
        kalman_gain = self.P @ self.H.T @ np.linalg.inv(innovation_covariance)

        self.state = self.state + (kalman_gain @ innovation)
        identity = np.eye(self.P.shape[0])
        self.P = (identity - kalman_gain @ self.H) @ self.P
        self.missed_frames = 0
        self.update_count += 1
        return float(self.x), float(self.y), float(self.z)
