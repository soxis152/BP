"""Scenar 07: ruzne urovne sumu.

Tri objekty maji podobny pohyb, ale rozdilne zasumena mereni. Scenar pomaha
poznat, pri jake urovni sumu se zacne rozpadat clustering nebo parovani.
"""

import asyncio

from Four.test_soubory.scenario_common import ObjectState, run_scenario

# Tři souběžné objekty se stejným typem pohybu, ale s různou úrovní šumu.
# Díky tomu lze ve stejném čase porovnat chování low / mid / high noise varianty.


def _lerp(start, end, progress):
    return start + (end - start) * progress


def update_noise_injection(step_index, objects, dt):
    # Všechny objekty dělají stejný průjezd tam a zpět.
    # Liší se pouze velikostí syntetického šumu přidaného do radarových a BLE dat.
    phase = step_index % 80
    left_to_right = phase < 40
    progress = (phase % 40) / 40.0

    x_start = 0.25 if left_to_right else 2.75
    x_end = 2.75 if left_to_right else 0.25

    # Šum přidělujeme podle tag_id, takže scénář nezávisí na pořadí objektů v seznamu.
    for obj in objects:
        obj.x = _lerp(x_start, x_end, progress)
        obj.z = 0.92

        if obj.tag_id == "NOISE_LOW":
            obj.y = 0.6
            obj.radar_noise_xy = 0.01
            obj.radar_noise_z = 0.005
            obj.ble_azimuth_noise = 0.4
            obj.ble_rssi_noise = 0.5

        elif obj.tag_id == "NOISE_MID":
            obj.y = 1.5
            obj.radar_noise_xy = 0.06
            obj.radar_noise_z = 0.02
            obj.ble_azimuth_noise = 2.0
            obj.ble_rssi_noise = 3.0

        elif obj.tag_id == "NOISE_HIGH":
            obj.y = 2.4
            obj.radar_noise_xy = 0.12
            obj.radar_noise_z = 0.05
            obj.ble_azimuth_noise = 4.0
            obj.ble_rssi_noise = 6.0


async def main():
    objects = [
        ObjectState("NOISE_LOW", x=0.25, y=0.6),
        ObjectState("NOISE_MID", x=0.25, y=1.5),
        ObjectState("NOISE_HIGH", x=0.25, y=2.4),
    ]

    # Tři paralelní "linky" nad sebou umožňují okamžité vizuální porovnání,
    # jak různé úrovně šumu deformují výsledek fusion.
    print("Spoustim scenar noise injection: tri soubezne prujezdy s low, mid a high sumem.")
    await run_scenario("noise_injection_levels", objects, update_noise_injection)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nScenario stopped.")
