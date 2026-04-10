import asyncio

from Four.test_soubory.scenario_common import ObjectState, run_scenario


def _lerp(start, end, progress):
    return start + (end - start) * progress


def update_id_recovery(step_index, objects, dt):
    obj = objects[0]
    phase = step_index % 100

    obj.radar_visible = True
    obj.ble_visible = True
    obj.z = 0.92

    # 0-29: objekt je plne viditelny a jede zleva doprava do stredu prostoru.
    if phase < 35:
        progress = phase / 35.0
        obj.x = _lerp(0.35, 1.35, progress)
        obj.y = _lerp(0.9, 1.2, progress)
    # 35-54: objekt se fyzicky posouva dal, ale oba senzory ho ztrati.
    elif phase < 55:
        obj.radar_visible = False
        obj.ble_visible = False
        progress = (phase - 35) / 20.0
        obj.x = _lerp(1.35, 1.95, progress)
        obj.y = _lerp(1.2, 1.75, progress)
    # 55-79: objekt se vraci do plne viditelnosti a pokracuje se stejnym tag_id.
    elif phase < 80:
        progress = (phase - 55) / 25.0
        obj.x = _lerp(1.95, 2.6, progress)
        obj.y = _lerp(1.75, 1.15, progress)
    # 80-99: navrat po spodni hrane zpet na start dalsiho cyklu.
    else:
        progress = (phase - 80) / 20.0
        obj.x = _lerp(2.6, 0.35, progress)
        obj.y = _lerp(1.15, 0.9, progress)


async def main():
    objects = [ObjectState("RECOVERY_TAG_A", x=0.35, y=0.9)]
    print("Spoustim scenar ID recovery: objekt zmizi a vrati se se stejnym tag_id.")
    await run_scenario("id_recovery_same_tag", objects, update_id_recovery)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nScenario stopped.")
