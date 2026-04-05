import asyncio

from Four.test_soubory.scenario_common import ObjectState, run_scenario


def update_zigzag(step_index, objects, dt):
    obj = objects[0]
    phase = step_index % 24

    if phase < 6:
        obj.x += 0.12 * dt
        obj.y += 0.02 * dt
    elif phase < 9:
        obj.x += 0.08 * dt
        obj.y += 0.40 * dt
    elif phase < 13:
        obj.x += 0.45 * dt
        obj.y -= 0.10 * dt
    elif phase < 16:
        obj.x += 0.03 * dt
        obj.y += 0.00
    else:
        obj.x -= 0.30 * dt
        obj.y -= 0.22 * dt

    if obj.x < 0.3 or obj.x > 2.8 or obj.y < 0.3 or obj.y > 2.8:
        obj.x = 0.7
        obj.y = 0.9


async def main():
    objects = [ObjectState("ZIGZAG_A", x=0.7, y=0.9)]
    await run_scenario("zigzag_speed_change", objects, update_zigzag)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nScenario stopped.")
