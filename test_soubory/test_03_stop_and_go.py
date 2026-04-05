import asyncio

from Four.test_soubory.scenario_common import ObjectState, run_scenario


def update_stop_and_go(step_index, objects, dt):
    obj = objects[0]
    phase = step_index % 28

    if phase < 8:
        obj.x += 0.24 * dt
        obj.y = 1.2
    elif phase < 18:
        obj.x += 0.0
        obj.y = 1.2
    else:
        obj.x += 0.12 * dt
        obj.y += 0.14 * dt

    if obj.x > 2.8 or obj.y > 2.6:
        obj.x = 0.5
        obj.y = 1.2


async def main():
    objects = [ObjectState("STOPGO_A", x=0.5, y=1.2)]
    await run_scenario("stop_and_go", objects, update_stop_and_go)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nScenario stopped.")
