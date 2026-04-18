"""Jednoducha matplotlib vizualizace pro samostatne testovani radaru.

Dashboard v `index.html` je hlavni vizualizace celeho systemu. Tohle okno je
spis laboratorni pomucka pro rychlou kontrolu, ze radar vraci body a parser
vraci souradnice v ocekavanem formatu.
"""

import matplotlib.pyplot as plt
import matplotlib

matplotlib.use('TkAgg')


class RadarUI:
    # Změněné výchozí limity na 3x3 metry (X je poloměr, takže 1.5 znamená 3m šířku)
    def __init__(self, x_scale=1.5, y_scale=3.0, z_scale=2.0):
        self.x_scale = x_scale
        self.y_scale = y_scale
        self.z_scale = z_scale

        self.fig = plt.figure(figsize=(12, 8))
        self.ax = self.fig.add_subplot(111, projection='3d')
        self.ax.view_init(elev=25, azim=-45)
        self.ax.set_facecolor('#fafafa')

        # Limity os přesně na vaše pole
        self.ax.set_xlim(-self.x_scale, self.x_scale)
        self.ax.set_ylim(0, self.y_scale)
        self.ax.set_zlim(-self.z_scale, self.z_scale)

        self.ax.set_title("3D Radar - Testovací pole 3x3m", fontsize=14, fontweight='bold')
        self.ax.set_xlabel("X - Šířka (m)")
        self.ax.set_ylabel("Y - Hloubka (m)")
        self.ax.set_zlabel("Z - Výška (m)")

        self.ax.scatter([0], [0], [0], c='black', marker='X', s=150, label="Radar (0,0,0)")
        self.scatter = self.ax.scatter([], [], [], c='red', marker='o', s=60, edgecolors='black', label="Cíle")
        self.shadows = self.ax.scatter([], [], [], c='gray', marker='o', s=30, alpha=0.3)
        self.frame_text = self.ax.text2D(0.02, 0.98, '', transform=self.ax.transAxes, fontsize=12, fontweight='bold',
                                         verticalalignment='top')
        self.ax.legend(loc="upper right")
        self.texts = []

    def update(self, parsed_data):
        # Parser vraci dlouhou n-tici hodnot. Pro rychle zobrazeni me zajima
        # hlavne cislo frame a pole souradnic detekovanych bodu.
        (
            _, _, _, frame_number, num_det_obj, _, _,
            detected_x_array, detected_y_array, detected_z_array, *_
        ) = parsed_data

        for txt in self.texts:
            txt.remove()
        self.texts.clear()

        # FILTR: Ponecháme jen body, které leží čistě uvnitř našeho pole 3x3 metry
        # Filtr ponecha jen body uvnitr testovaciho pole. Bez toho graf snadno
        # zaplni odrazy od sten nebo veci mimo sledovany prostor.
        valid_x, valid_y, valid_z = [], [], []

        if num_det_obj > 0:
            for x, y, z in zip(detected_x_array, detected_y_array, detected_z_array):
                # Zkontrolujeme, zda bod leží v našem 3x3 boxu (Y do 3m, X od -1.5 do 1.5m)
                if (-self.x_scale <= x <= self.x_scale) and (0 <= y <= self.y_scale):
                    valid_x.append(x)
                    valid_y.append(y)
                    valid_z.append(z)

        # Skutečný počet cílů po vyfiltrování hluku ze zdí a okolí
        filtered_count = len(valid_x)

        if filtered_count > 0:
            self.scatter._offsets3d = (valid_x, valid_y, valid_z)
            z_shadows = [-self.z_scale] * filtered_count
            self.shadows._offsets3d = (valid_x, valid_y, z_shadows)

            for x, y, z in zip(valid_x, valid_y, valid_z):
                label = f"[{x:.2f}, {y:.2f}, {z:.2f}]"
                txt = self.ax.text(x, y, z + 0.15, label, size=8, color='darkblue', zorder=10)
                self.texts.append(txt)
        else:
            self.scatter._offsets3d = ([], [], [])
            self.shadows._offsets3d = ([], [], [])

        self.frame_text.set_text(f"Snímek: {frame_number}\nObjekty v poli 3x3m: {filtered_count}")
        plt.pause(0.01)

    def show(self):
        plt.ion()
        plt.show()
