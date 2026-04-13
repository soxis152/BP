import asyncio

from Four.test_soubory.scenario_common import ObjectState, run_scenario

# Pět objektů se sbíhá do malého shluku, chvíli stojí u sebe a potom se rozchází.
# Jde o scénář pro kontrolu stability identity při hustém seskupení a následném rozdělení.


def _lerp(start, end, progress):
    return start + (end - start) * progress


ENTRY_POINTS = [
    (0.2, 0.5),
    (2.8, 0.6),
    (0.3, 2.5),
    (2.7, 2.4),
    (1.5, 0.2),
]

EXIT_POINTS = [
    (0.2, 1.4),
    (2.8, 1.6),
    (0.5, 2.8),
    (2.5, 0.3),
    (1.5, 2.8),
]

MEETING_POINTS = [
    (1.2, 1.2),
    (1.6, 1.15),
    (1.35, 1.45),
    (1.55, 1.55),
    (1.4, 1.3),
]

# ENTRY_POINTS = odkud každý objekt přichází.
# MEETING_POINTS = kde stojí ve středu během srocení.
# EXIT_POINTS = kam se po rozchodu každý objekt vydá.


def update_shift_change_crowd(step_index, objects, dt):
    phase = step_index % 210

    # Každý objekt má vlastní start, vlastní pozici ve shluku i vlastní cíl po rozchodu.
    for index, obj in enumerate(objects):
        obj.z = 0.92
        obj.radar_visible = True
        obj.ble_visible = True

        entry_x, entry_y = ENTRY_POINTS[index]
        meet_x, meet_y = MEETING_POINTS[index]
        exit_x, exit_y = EXIT_POINTS[index]

        # 0-19: všichni stojí na výchozích pozicích.
        if phase < 20:
            obj.x = entry_x
            obj.y = entry_y
        # 20-49: pět lidí se sbíhá do prostoru kolem středu.
        elif phase < 50:
            progress = (phase - 20) / 30.0
            obj.x = _lerp(entry_x, meet_x, progress)
            obj.y = _lerp(entry_y, meet_y, progress)
        # 50-79: všichni stojí namačkaní u sebe.
        elif phase < 80:
            obj.x = meet_x
            obj.y = meet_y
        # 80-119: rozchod do pěti různých směrů.
        elif phase < 120:
            progress = (phase - 80) / 40.0
            obj.x = _lerp(meet_x, exit_x, progress)
            obj.y = _lerp(meet_y, exit_y, progress)
        # 120-149: po rozchodu stojí v cílových bodech.
        elif phase < 150:
            obj.x = exit_x
            obj.y = exit_y
        # 150-179: návrat do výchozích pozic.
        elif phase < 180:
            progress = (phase - 150) / 30.0
            obj.x = _lerp(exit_x, entry_x, progress)
            obj.y = _lerp(exit_y, entry_y, progress)
        # 180-209: delší pauza před dalším opakováním testu.
        else:
            obj.x = entry_x
            obj.y = entry_y


async def main():
    objects = [
        ObjectState("SHIFT_A", x=ENTRY_POINTS[0][0], y=ENTRY_POINTS[0][1]),
        ObjectState("SHIFT_B", x=ENTRY_POINTS[1][0], y=ENTRY_POINTS[1][1]),
        ObjectState("SHIFT_C", x=ENTRY_POINTS[2][0], y=ENTRY_POINTS[2][1]),
        ObjectState("SHIFT_D", x=ENTRY_POINTS[3][0], y=ENTRY_POINTS[3][1]),
        ObjectState("SHIFT_E", x=ENTRY_POINTS[4][0], y=ENTRY_POINTS[4][1]),
    ]

    # Pět samostatných tagů umožní dobře sledovat, zda se po srocení neprohodí identity.
    print("Spoustim scenar shift change: pet lidi se sroti v 1x1 m a pak se rozejde do peti smeru.")
    await run_scenario("shift_change_crowd", objects, update_shift_change_crowd)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nScenario stopped.")
