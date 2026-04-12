import asyncio

from Four.test_soubory.scenario_common import ObjectState, run_scenario


def _lerp(start, end, progress):
    return start + (end - start) * progress


def update_forklift_brake(step_index, objects, dt):
    obj = objects[0]
    phase = step_index % 110

    obj.z = 1.1
    obj.radar_visible = True
    obj.ble_visible = True

    # 0-19: kratka akceleracni cast pred vjezdem do hlavni drahy.
    if phase < 20:
        progress = phase / 20.0
        obj.x = _lerp(0.2, 1.2, progress)
        obj.y = 1.5
    # 20-39: rychly prujezd stredu mistnosti.
    elif phase < 40:
        progress = (phase - 20) / 20.0
        obj.x = _lerp(1.2, 2.35, progress)
        obj.y = 1.5
    # 40-59: okamzite zastaveni, vozik stoji na miste.
    elif phase < 60:
        obj.x = 2.35
        obj.y = 1.5
    # 60-84: stale stoji, aby byl overshoot filtru dobre videt.
    elif phase < 85:
        obj.x = 2.35
        obj.y = 1.5
    # 85-109: navrat pomalou rychlosti zpet doleva pro dalsi cyklus.
    else:
        progress = (phase - 85) / 25.0
        obj.x = _lerp(2.35, 0.2, progress)
        obj.y = 1.5


async def main():
    objects = [ObjectState("FORKLIFT_A", x=0.2, y=1.5, z=1.1)]
    print("Spoustim scenar forklift brake: rychly vjezd a ostre zastaveni uprostred mapy.")
    await run_scenario("forklift_brake", objects, update_forklift_brake)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nScenario stopped.")
