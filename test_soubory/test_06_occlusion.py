import asyncio

from Four.test_soubory.scenario_common import ObjectState, run_scenario

# Scénář simulující zakrytí objektu:
# - normální průjezd,
# - radar-only occlusion,
# - krátký total dropout,
# - znovuobjevení objektu v další části trasy.


def _lerp(start, end, progress):
    return start + (end - start) * progress


def update_occlusion(step_index, objects, dt):
    obj = objects[0]
    obj.z = 0.92
    phase = step_index % 100

    obj.radar_visible = True
    obj.ble_visible = True

    # 0-24: bezny prijezd z leve dolni casti prostoru smerem ke stredu.
    if phase < 25:
        progress = phase / 25.0
        obj.x = _lerp(0.25, 1.15, progress)
        obj.y = _lerp(0.45, 1.15, progress)
    # 25-44: objekt krizuje stred prostoru, radar je zakryty, BLE stale vidi tag.
    elif phase < 45:
        progress = (phase - 25) / 20.0
        obj.x = _lerp(1.15, 1.75, progress)
        obj.y = _lerp(1.15, 1.75, progress)
        obj.radar_visible = False
    # 45-54: kratky total dropout v horni casti stredove zony.
    elif phase < 55:
        obj.x = 1.75
        obj.y = 1.75
        obj.radar_visible = False
        obj.ble_visible = False
    # 55-79: objekt vyjede do prave horni casti prostoru a senzory ho znovu vidi.
    elif phase < 80:
        progress = (phase - 55) / 25.0
        obj.x = _lerp(1.75, 2.75, progress)
        obj.y = _lerp(1.75, 2.55, progress)
    # 80-99: navrat po spodni hrane pres cely prostor zpet doleva.
    else:
        progress = (phase - 80) / 20.0
        obj.x = _lerp(2.75, 0.25, progress)
        obj.y = _lerp(2.55, 0.45, progress)


async def main():
    objects = [ObjectState("OCCLUSION_A", x=0.25, y=0.45)]
    print("Spoustim scenar occlusion: uzavreny okruh, radar-only zakryti, kratky total dropout a navrat.")
    await run_scenario("occlusion_dropouts", objects, update_occlusion)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nScenario stopped.")
