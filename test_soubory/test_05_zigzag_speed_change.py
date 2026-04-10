import asyncio
from Four.test_soubory.scenario_common import ObjectState, run_scenario

# Definujeme body (waypoints), mezi kterými bude objekt létat
WAYPOINTS = [
    (1.5, 1.5, 0.5),  # 1. Pomalu do středu (x, y, rychlost v m/s)
    (2.5, 2.5, 3.0),  # 2. Sprint do pravého horního rohu
    (2.5, 0.5, 4.0),  # 3. Extrémní úskok dolů
    (2.5, 0.5, 0.0),  # 4. Tvrdé zastavení na místě (pauza)
    (0.5, 2.5, 2.5),  # 5. Rychlý přesun do levého horního
    (0.5, 0.5, 1.5),  # 6. Přesun do levého dolního
]


def update_dynamic_stress_test(step_index, objects, dt):
    obj = objects[0]

    # Fáze se mění každých 15 kroků simulace (7.5 vteřiny)
    phase = (step_index // 15) % len(WAYPOINTS)

    target_x, target_y, target_speed = WAYPOINTS[phase]

    # Vypočítáme vektor k cíli
    dx = target_x - obj.x
    dy = target_y - obj.y
    distance = (dx ** 2 + dy ** 2) ** 0.5

    if distance > 0.1:
        # Normalizujeme vektor a vynásobíme cílovou rychlostí
        tvx = (dx / distance) * target_speed
        tvy = (dy / distance) * target_speed
    else:
        # Jsme v cíli, zastavíme
        tvx = 0.0
        tvy = 0.0

    # Aplikace setrvačnosti (aby to Kalman filtr zvládl "chytit")
    # Změna rychlosti není okamžitá, ale plynulá
    obj.vx = obj.vx * 0.6 + tvx * 0.4
    obj.vy = obj.vy * 0.6 + tvy * 0.4

    # Ochrana proti vyletění mimo mapu 3x3 metry (náraz do zdi)
    next_x = obj.x + obj.vx * dt
    next_y = obj.y + obj.vy * dt

    if next_x < 0.1 or next_x > 2.9:
        obj.vx *= -0.5  # Odraz a zpomalení
    if next_y < 0.1 or next_y > 2.9:
        obj.vy *= -0.5

    obj.x += obj.vx * dt
    obj.y += obj.vy * dt


async def main():
    objects = [ObjectState("STRESS_TEST_OBJ", x=0.5, y=0.5)]
    print("Spouštím Vyladěný Stress Test: Waypointy a limity.")
    await run_scenario("dynamic_stress_v2", objects, update_dynamic_stress_test)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nTest ukončen.")
