import asyncio
from Four.test_soubory.scenario_common import ObjectState, run_scenario

def update_dynamic_stress_test(step_index, objects, dt):
    obj = objects[0]
    # Celý cyklus má 60 kroků pro komplexnější manévry
    phase = step_index % 60

    if phase < 15:
        # 1. POMALÁ CHŮZE: Lineární pohyb vpřed (středem)
        obj.x += 0.3 * dt
        obj.y += 0.1 * dt
    elif phase < 20:
        # 2. NÁHLÉ ZRYCHLENÍ: Sprint směrem k pravému hornímu rohu
        obj.x += 2.5 * dt
        obj.y += 1.8 * dt
    elif phase < 25:
        # 3. ÚSKOK DO STRANY: Prudká změna v ose X, osa Y stojí
        obj.x -= 2.0 * dt
        obj.y += 0.0
    elif phase < 35:
        # 4. OSTRÉ ZASTAVENÍ: Objekt stojí na místě (testuje latenci a klidovou polohu)
        pass
    elif phase < 45:
        # 5. OTOČKA O 180° A RYCHLÝ NÁVRAT: Pohyb přímo zpět k počátku
        obj.x -= 1.5 * dt
        obj.y -= 1.5 * dt
    else:
        # 6. DOJEZD: Pomalé srovnání do výchozí pozice
        obj.x = obj.x * 0.9 + 0.5 * 0.1
        obj.y = obj.y * 0.9 + 0.5 * 0.1

    # --- HRANICE 3x3m S RESETEM ---
    if obj.x < 0.1 or obj.x > 2.9 or obj.y < 0.1 or obj.y > 2.9:
        obj.x = 0.5
        obj.y = 0.5

async def main():
    # Začínáme v dolní části, aby bylo místo na "sprint" nahoru
    objects = [ObjectState("STRESS_TEST_OBJ", x=0.5, y=0.5)]
    print("Spouštím Dynamický Stress Test: Cik-cak, zrychlení a stop.")
    await run_scenario("dynamic_stress_v1", objects, update_dynamic_stress_test)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nTest ukončen.")