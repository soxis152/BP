import asyncio

from Four.test_soubory.scenario_common import ObjectState, run_scenario


def _lerp(start, end, progress):
    return start + (end - start) * progress


def update_vertical_motion(step_index, objects, dt):
    obj = objects[0]
    phase = step_index % 120

    if phase < 30:
        progress = phase / 30.0
        obj.x = _lerp(0.5, 1.5, progress)
        obj.y = 1.5
        obj.z = _lerp(0.5, 1.5, progress)
    elif phase < 60:
        progress = (phase - 30) / 30.0
        obj.x = _lerp(1.5, 2.0, progress)
        obj.y = 1.5
        obj.z = 1.5
    elif phase < 90:
        progress = (phase - 60) / 30.0
        obj.x = _lerp(2.0, 2.5, progress)
        obj.y = 1.5
        obj.z = _lerp(1.5, 0.5, progress)
    else:
        progress = (phase - 90) / 30.0
        obj.x = _lerp(2.5, 0.5, progress)
        obj.y = 1.5
        obj.z = 0.5


async def main():
    objects = [ObjectState("VERTICAL_3D_A", x=0.5, y=1.5, z=0.5)]
    print("Spoustim 3D vertical motion: stoupani, let ve vysce, klesani a navrat.")
    await run_scenario("vertical_motion_3d", objects, update_vertical_motion)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nScenario stopped.")
