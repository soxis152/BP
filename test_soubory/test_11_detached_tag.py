"""Scenar 11: odlozeny BLE tag.

Simuluje situaci, kdy osoba odlozi tag a pokracuje dal bez nej. Dulezite je,
aby system nespojoval odchazejici radarovy track s BLE tagem, ktery zustal
staticky na puvodnim miste.
"""

import asyncio

from Four.test_soubory.scenario_common import ObjectState, run_scenario

# Simulace "zahozeného tagu":
# BLE tag zůstane na místě, ale radarový objekt odchází pryč.
# Testuje se, zda systém oddělí identitu tagu od fyzické radarové hmoty.


def _lerp(start, end, progress):
    return start + (end - start) * progress


def update_detached_tag(step_index, objects, dt):
    person, hanging_tag = objects
    phase = step_index % 100

    # hanging_tag reprezentuje samotný BLE tag ponechaný na věšáku.
    # Radar ho proto nikdy nevidí jako fyzický objekt.
    hanging_tag.x = 0.9
    hanging_tag.y = 1.2
    hanging_tag.z = 0.92
    hanging_tag.radar_visible = False
    hanging_tag.ble_visible = True

    person.z = 0.92
    person.radar_visible = True
    person.ble_visible = True

    # 0-29: člověk s tagem přichází k věšáku.
    if phase < 30:
        progress = phase / 30.0
        person.x = _lerp(0.25, 0.9, progress)
        person.y = _lerp(2.4, 1.2, progress)
    # 30-49: člověk stojí u věšáku, tag je stále na něm.
    elif phase < 50:
        person.x = 0.9
        person.y = 1.2
    # 50-79: tag zůstává na věšáku, člověk odchází bez BLE identity.
    elif phase < 80:
        progress = (phase - 50) / 30.0
        person.x = _lerp(0.9, 2.6, progress)
        person.y = _lerp(1.2, 2.15, progress)
        person.ble_visible = False
    # 80-99: člověk se vrací k okraji scény, tag stále visí na místě.
    else:
        progress = (phase - 80) / 20.0
        person.x = _lerp(2.6, 0.25, progress)
        person.y = _lerp(2.15, 2.4, progress)
        person.ble_visible = False


async def main():
    objects = [
        ObjectState("TAG_DROP_PERSON", x=0.25, y=2.4),
        ObjectState("TAG_DROP_PERSON", x=0.9, y=1.2),
    ]

    # Oba simulované objekty mají stejné tag_id záměrně:
    # jeden je fyzická osoba, druhý odložený tag na pevném místě.
    print("Spoustim scenar detached tag: BLE tag zustava na vesaku, radarova osoba odchazi pryc.")
    await run_scenario("detached_tag", objects, update_detached_tag)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nScenario stopped.")
