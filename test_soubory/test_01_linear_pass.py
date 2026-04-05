import asyncio

from Four.test_soubory.scenario_common import ObjectState, run_scenario


def update_linear_pass(step_index, objects, dt):
    obj = objects[0]
    obj.x += 0.18 * dt
    obj.y = 1.45
    obj.z = 0.92

    if obj.x > 3.2:
        obj.x = -0.3


async def main():
    objects = [ObjectState("LINEAR_A", x=-0.3, y=1.45)]
    await run_scenario("linear_pass", objects, update_linear_pass)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nScenario stopped.")
