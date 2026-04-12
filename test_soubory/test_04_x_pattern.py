import asyncio

from Four.test_soubory.scenario_common import ObjectState, run_scenario


def update_x_pattern(step_index, objects, dt):
    obj_a, obj_b = objects

    obj_a.x += 0.22 * dt
    obj_a.y += 0.22 * dt

    obj_b.x -= 0.22 * dt
    obj_b.y -= 0.22 * dt

    if obj_a.x > 3.0 or obj_a.y > 3.0:
        obj_a.x = 0.2
        obj_a.y = 0.2
        obj_b.x = 2.8
        obj_b.y = 2.8


async def main():
    objects = [
        ObjectState("CROSS_A", x=0.2, y=0.2),
        ObjectState("CROSS_B", x=2.8, y=2.8),
    ]
    await run_scenario("x_pattern", objects, update_x_pattern)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nScenario stopped.")
