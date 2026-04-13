import asyncio
import math
from Four.test_soubory.scenario_common import ObjectState, run_scenario

# Objekt se pohybuje po trojúhelníku a v každém vrcholu zastaví.
# Testuje se hlavně přechod mezi klidem a pohybem a stabilita tracku v rozích trajektorie.


def update_triangle_stop(step_index, objects, dt):
    obj = objects[0]

    # Definice vrcholů trojúhelníku (x, y)
    points = [
        (0.5, 1.2),  # Bod A (Start)
        (2.5, 1.2),  # Bod B (Vpravo)
        (1.5, 2.8)  # Bod C (Nahoře)
    ]

    # Nastavení časování: 20 kroků pohyb, 10 kroků čekání v rohu
    # Celý cyklus na jednu stranu trojúhelníku je 30 kroků
    steps_per_side = 60
    wait_steps = 30
    total_cycle = steps_per_side * len(points)

    current_cycle_step = step_index % total_cycle
    side_index = current_cycle_step // steps_per_side
    step_in_side = current_cycle_step % steps_per_side

    # 1. FÁZE: Čekání v rohu
    if step_in_side < wait_steps:
        # Objekt stojí v aktuálním vrcholu
        target_pt = points[side_index]
        obj.x, obj.y = target_pt

    # 2. FÁZE: Pohyb k dalšímu vrcholu
    else:
        start_pt = points[side_index]
        end_pt = points[(side_index + 1) % len(points)]

        # Výpočet postupu (0.0 až 1.0) mezi body
        # (step_in_side - wait_steps) jde od 0 do 19
        move_progress = (step_in_side - wait_steps) / (steps_per_side - wait_steps)

        # Lineární interpolace pozice
        obj.x = start_pt[0] + (end_pt[0] - start_pt[0]) * move_progress
        obj.y = start_pt[1] + (end_pt[1] - start_pt[1]) * move_progress


async def main():
    # Počáteční stav objektu
    objects = [ObjectState("TRIANGLE_BOT", x=0.5, y=1.2)]
    print("Spouštím scénář: Pohyb do trojúhelníku se zastávkami v rozích.")
    await run_scenario("triangle_stop_go", objects, update_triangle_stop)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nScénář ukončen.")
