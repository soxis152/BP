"""Scenar 02: kruhovy/elipticky pohyb.

Tento test je uzitecny pro kontrolu, jestli se odhad polohy nerozpada pri
plynule zmene smeru. Na rozdil od linearniho pruchodu tu objekt porad zataci.
"""

import asyncio
import math

from Four.test_soubory.scenario_common import ObjectState, run_scenario

# Objekt obíhá kolem středu po hladké křivce.
# Scénář je vhodný pro ověření, že filtr zvládá plynulou změnu směru bez lomené trajektorie.


def update_circular_motion(step_index, objects, dt):
    obj = objects[0]
    angle = step_index * 0.11
    obj.x = 1.5 + 0.8 * math.cos(angle)
    obj.y = 1.5 + 0.6 * math.sin(angle)
    obj.z = 0.92 + 0.01 * math.sin(angle * 0.5)


async def main():
    objects = [ObjectState("CIRCLE_A", x=2.3, y=1.5)]
    await run_scenario("circular_motion", objects, update_circular_motion)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nScenario stopped.")
