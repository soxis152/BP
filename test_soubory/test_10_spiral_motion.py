"""Scenar 10: prostorova spirala.

Kombinuje kruhovy pohyb v X/Y a plynulou zmenu vysky. Je to kompaktni test
3D trajektorie, kde se soucasne meni smer i Z souradnice.
"""

import asyncio
import math

from Four.test_soubory.scenario_common import ObjectState, run_scenario

# Prostorová spirála kombinuje kroužení v XY a souběžnou změnu výšky Z.
# Scénář je náročnější než čistě 2D kružnice a dobře odhalí nestabilitu ve 3D pohybu.


def update_spiral_motion(step_index, objects, dt):
    obj = objects[0]
    angle = step_index * 0.16
    radius = 0.35 + 0.0045 * (step_index % 140)

    obj.x = 1.5 + radius * math.cos(angle)
    obj.y = 1.5 + radius * math.sin(angle)
    obj.z = 0.45 + 0.009 * (step_index % 140)

    if step_index % 140 == 139:
        obj.z = 0.45


async def main():
    objects = [ObjectState("SPIRAL_3D_A", x=1.85, y=1.5, z=0.45)]
    print("Spoustim 3D spiral motion: spirala v XY se soucasnym rustem v ose Z.")
    await run_scenario("spiral_motion_3d", objects, update_spiral_motion)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nScenario stopped.")
