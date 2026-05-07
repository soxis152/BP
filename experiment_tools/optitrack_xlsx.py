"""Nacitani OptiTrack XLSX exportu bez externich zavislosti.

OptiTrack export je obycejny XLSX (ZIP + XML). Projekt uz ma vlastni
testovaci pipeline nad MQTT a nechci kvuli jednomu importeru tahat dalsi
zavislost typu openpyxl. Proto parser pouziva jen standardni knihovnu.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Dict, Iterable, List, Tuple
import xml.etree.ElementTree as ET
import zipfile


XML_NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
WORKBOOK_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
CELL_REF_PATTERN = re.compile(r"([A-Z]+)(\d+)")
AXIS_TO_INDEX = {"x": 0, "y": 1, "z": 2}


@dataclass(frozen=True)
class OptiTrackRigidBody:
    name: str
    source_id: str
    position_columns: Dict[str, int]


@dataclass(frozen=True)
class OptiTrackFrame:
    frame_number: int
    time_seconds: float
    bodies: Dict[str, Tuple[float, float, float]]


@dataclass(frozen=True)
class OptiTrackTake:
    path: Path
    sheet_name: str
    metadata: Dict[str, str]
    rigid_bodies: List[OptiTrackRigidBody]
    frames: List[OptiTrackFrame]
    capture_frame_rate: float
    export_frame_rate: float
    frame_period_seconds: float


def column_letter_to_index(column_letters: str) -> int:
    index = 0
    for char in column_letters:
        index = (index * 26) + (ord(char) - 64)
    return index


def parse_cell_reference(cell_ref: str) -> Tuple[int, int]:
    match = CELL_REF_PATTERN.fullmatch(cell_ref)
    if not match:
        raise ValueError(f"Unsupported Excel cell reference: {cell_ref}")
    column_letters, row_number = match.groups()
    return int(row_number), column_letter_to_index(column_letters)


def parse_axis_mapping(token: str) -> Tuple[int, float]:
    normalized = token.strip().lower()
    sign = -1.0 if normalized.startswith("-") else 1.0
    axis_name = normalized[1:] if normalized.startswith("-") else normalized
    if axis_name not in AXIS_TO_INDEX:
        raise ValueError(f"Unsupported axis mapping '{token}'. Pouzij x, y, z nebo -x, -y, -z.")
    return AXIS_TO_INDEX[axis_name], sign


def read_shared_strings(archive: zipfile.ZipFile) -> List[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []

    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    shared_strings = []
    for item in root.findall("a:si", XML_NS):
        text = "".join(node.text or "" for node in item.iterfind(".//a:t", XML_NS))
        shared_strings.append(text)
    return shared_strings


def read_workbook_sheet_targets(archive: zipfile.ZipFile) -> Dict[str, str]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    relationship_targets = {
        rel.attrib["Id"]: "xl/" + rel.attrib["Target"].lstrip("/")
        for rel in relationships
    }
    return {
        sheet.attrib["name"]: relationship_targets[sheet.attrib[WORKBOOK_REL_NS]]
        for sheet in workbook.find("a:sheets", XML_NS)
    }


def read_sheet_cells(
    archive: zipfile.ZipFile,
    sheet_target: str,
    shared_strings: List[str],
) -> Dict[Tuple[int, int], str]:
    root = ET.fromstring(archive.read(sheet_target))
    table = {}

    for row in root.findall(".//a:sheetData/a:row", XML_NS):
        for cell in row.findall("a:c", XML_NS):
            row_number, column_number = parse_cell_reference(cell.attrib["r"])
            value_node = cell.find("a:v", XML_NS)
            if value_node is None:
                value = ""
            elif cell.attrib.get("t") == "s":
                value = shared_strings[int(value_node.text)]
            else:
                value = value_node.text or ""
            table[(row_number, column_number)] = value

    return table


def parse_metadata(cells: Dict[Tuple[int, int], str]) -> Dict[str, str]:
    metadata = {}
    for column_number in range(1, 40, 2):
        key = cells.get((1, column_number), "").strip()
        value = cells.get((1, column_number + 1), "").strip()
        if key:
            metadata[key] = value
    return metadata


def find_rigid_bodies(cells: Dict[Tuple[int, int], str]) -> List[OptiTrackRigidBody]:
    rigid_bodies = []
    row_type = 3
    row_name = 4
    row_id = 5
    row_kind = 6
    row_axis = 7

    for start_column in range(3, 400, 6):
        body_type = cells.get((row_type, start_column), "").strip()
        body_name = cells.get((row_name, start_column), "").strip()
        body_id = cells.get((row_id, start_column), "").strip()
        if not body_type and not body_name:
            break
        if body_type != "Rigid Body":
            continue

        position_columns = {}
        for column_number in range(start_column, start_column + 6):
            kind = cells.get((row_kind, column_number), "").strip()
            axis = cells.get((row_axis, column_number), "").strip().lower()
            if kind == "Position" and axis in {"x", "y", "z"}:
                position_columns[axis] = column_number

        if {"x", "y", "z"} <= set(position_columns):
            rigid_bodies.append(
                OptiTrackRigidBody(
                    name=body_name,
                    source_id=body_id,
                    position_columns=position_columns,
                )
            )

    if not rigid_bodies:
        raise ValueError("V XLSX exportu jsem nenasel zadne rigid body s Position X/Y/Z.")
    return rigid_bodies


def iter_frame_rows(cells: Dict[Tuple[int, int], str]) -> Iterable[int]:
    row_number = 8
    while True:
        frame_value = cells.get((row_number, 1), "").strip()
        time_value = cells.get((row_number, 2), "").strip()
        if not frame_value and not time_value:
            break
        yield row_number
        row_number += 1


def transform_position(
    point_meters: Tuple[float, float, float],
    axis_x: str,
    axis_y: str,
    axis_z: str,
    offset_x: float,
    offset_y: float,
    offset_z: float,
) -> Tuple[float, float, float]:
    mapping_x = parse_axis_mapping(axis_x)
    mapping_y = parse_axis_mapping(axis_y)
    mapping_z = parse_axis_mapping(axis_z)

    values = []
    for axis_index, sign in (mapping_x, mapping_y, mapping_z):
        values.append(point_meters[axis_index] * sign)

    return (
        values[0] + offset_x,
        values[1] + offset_y,
        values[2] + offset_z,
    )


def load_optitrack_take(
    path: str | Path,
    *,
    sheet_name: str | None = None,
    axis_x: str = "x",
    axis_y: str = "-z",
    axis_z: str = "y",
    offset_x: float = 0.0,
    offset_y: float = 0.0,
    offset_z: float = 0.0,
    selected_bodies: Iterable[str] | None = None,
) -> OptiTrackTake:
    """Nacte OptiTrack XLSX/CSV export a vrati trajektorie uz prevedene do metru."""
    take_path = Path(path).resolve()
    if not take_path.exists():
        raise FileNotFoundError(f"OptiTrack export nebyl nalezen: {take_path}")

    suffix = take_path.suffix.lower()
    if suffix == ".csv":
        return load_optitrack_take_from_csv(
            take_path,
            axis_x=axis_x,
            axis_y=axis_y,
            axis_z=axis_z,
            offset_x=offset_x,
            offset_y=offset_y,
            offset_z=offset_z,
            selected_bodies=selected_bodies,
        )
    if suffix != ".xlsx":
        raise ValueError(f"Nepodporovany format '{take_path.suffix}'. Pouzij .xlsx nebo .csv.")

    selected_set = {name.strip() for name in (selected_bodies or []) if name.strip()}

    with zipfile.ZipFile(take_path) as archive:
        shared_strings = read_shared_strings(archive)
        sheet_targets = read_workbook_sheet_targets(archive)
        chosen_sheet_name = sheet_name or next(iter(sheet_targets))
        if chosen_sheet_name not in sheet_targets:
            raise ValueError(
                f"Sheet '{chosen_sheet_name}' v XLSX neexistuje. Dostupne sheets: {', '.join(sheet_targets)}"
            )

        cells = read_sheet_cells(archive, sheet_targets[chosen_sheet_name], shared_strings)

    metadata = parse_metadata(cells)
    rigid_bodies = find_rigid_bodies(cells)
    if selected_set:
        rigid_bodies = [body for body in rigid_bodies if body.name in selected_set]
        if not rigid_bodies:
            raise ValueError(
                "Po filtrovani nezustal zadny rigid body. "
                f"Dostupne nazvy: {', '.join(body.name for body in find_rigid_bodies(cells))}"
            )

    frames = []
    for row_number in iter_frame_rows(cells):
        bodies = {}
        for body in rigid_bodies:
            x_mm = cells.get((row_number, body.position_columns["x"]), "").strip()
            y_mm = cells.get((row_number, body.position_columns["y"]), "").strip()
            z_mm = cells.get((row_number, body.position_columns["z"]), "").strip()
            if not x_mm or not y_mm or not z_mm:
                continue

            point_meters = (
                float(x_mm) / 1000.0,
                float(y_mm) / 1000.0,
                float(z_mm) / 1000.0,
            )
            bodies[body.name] = transform_position(
                point_meters,
                axis_x=axis_x,
                axis_y=axis_y,
                axis_z=axis_z,
                offset_x=offset_x,
                offset_y=offset_y,
                offset_z=offset_z,
            )

        frames.append(
            OptiTrackFrame(
                frame_number=int(float(cells[(row_number, 1)])),
                time_seconds=float(cells[(row_number, 2)]),
                bodies=bodies,
            )
        )

    if not frames:
        raise ValueError("V OptiTrack exportu nejsou zadne datove radky.")

    capture_frame_rate = float(metadata.get("Capture Frame Rate", "0") or 0.0)
    export_frame_rate = float(metadata.get("Export Frame Rate", "0") or 0.0)
    if len(frames) >= 2:
        frame_period_seconds = max(0.0001, frames[1].time_seconds - frames[0].time_seconds)
    elif export_frame_rate > 0:
        frame_period_seconds = 1.0 / export_frame_rate
    elif capture_frame_rate > 0:
        frame_period_seconds = 1.0 / capture_frame_rate
    else:
        frame_period_seconds = 0.1

    return OptiTrackTake(
        path=take_path,
        sheet_name=chosen_sheet_name,
        metadata=metadata,
        rigid_bodies=rigid_bodies,
        frames=frames,
        capture_frame_rate=capture_frame_rate,
        export_frame_rate=export_frame_rate,
        frame_period_seconds=frame_period_seconds,
    )


def load_optitrack_take_from_csv(
    take_path: Path,
    *,
    axis_x: str,
    axis_y: str,
    axis_z: str,
    offset_x: float,
    offset_y: float,
    offset_z: float,
    selected_bodies: Iterable[str] | None,
) -> OptiTrackTake:
    selected_set = {name.strip() for name in (selected_bodies or []) if name.strip()}

    with take_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))

    if len(rows) < 7:
        raise ValueError("OptiTrack CSV nema ocekavanou hlavicku.")

    metadata = parse_csv_metadata(rows[0])
    rigid_bodies = find_rigid_bodies_csv(rows)
    if selected_set:
        available_names = [body.name for body in rigid_bodies]
        rigid_bodies = [body for body in rigid_bodies if body.name in selected_set]
        if not rigid_bodies:
            raise ValueError(
                "Po filtrovani nezustal zadny rigid body. "
                f"Dostupne nazvy: {', '.join(available_names)}"
            )

    frames = []
    for row in rows[7:]:
        if not row or len(row) < 2:
            continue

        frame_value = row[0].strip()
        time_value = row[1].strip()
        if not frame_value and not time_value:
            continue

        bodies = {}
        for body in rigid_bodies:
            x_mm = read_csv_cell(row, body.position_columns["x"]).strip()
            y_mm = read_csv_cell(row, body.position_columns["y"]).strip()
            z_mm = read_csv_cell(row, body.position_columns["z"]).strip()
            if not x_mm or not y_mm or not z_mm:
                continue

            point_meters = (
                float(x_mm) / 1000.0,
                float(y_mm) / 1000.0,
                float(z_mm) / 1000.0,
            )
            bodies[body.name] = transform_position(
                point_meters,
                axis_x=axis_x,
                axis_y=axis_y,
                axis_z=axis_z,
                offset_x=offset_x,
                offset_y=offset_y,
                offset_z=offset_z,
            )

        frames.append(
            OptiTrackFrame(
                frame_number=int(float(frame_value)),
                time_seconds=float(time_value),
                bodies=bodies,
            )
        )

    if not frames:
        raise ValueError("V OptiTrack CSV nejsou zadne datove radky.")

    capture_frame_rate = float(metadata.get("Capture Frame Rate", "0") or 0.0)
    export_frame_rate = float(metadata.get("Export Frame Rate", "0") or 0.0)
    if len(frames) >= 2:
        frame_period_seconds = max(0.0001, frames[1].time_seconds - frames[0].time_seconds)
    elif export_frame_rate > 0:
        frame_period_seconds = 1.0 / export_frame_rate
    elif capture_frame_rate > 0:
        frame_period_seconds = 1.0 / capture_frame_rate
    else:
        frame_period_seconds = 0.1

    return OptiTrackTake(
        path=take_path,
        sheet_name=take_path.name,
        metadata=metadata,
        rigid_bodies=rigid_bodies,
        frames=frames,
        capture_frame_rate=capture_frame_rate,
        export_frame_rate=export_frame_rate,
        frame_period_seconds=frame_period_seconds,
    )


def parse_csv_metadata(row: List[str]) -> Dict[str, str]:
    metadata = {}
    for index in range(0, len(row), 2):
        key = row[index].strip()
        value = row[index + 1].strip() if index + 1 < len(row) else ""
        if key:
            metadata[key] = value
    return metadata


def read_csv_cell(row: List[str], index: int) -> str:
    return row[index] if index < len(row) else ""


def find_rigid_bodies_csv(rows: List[List[str]]) -> List[OptiTrackRigidBody]:
    type_row = rows[2]
    name_row = rows[3]
    id_row = rows[4]
    kind_row = rows[5]
    axis_row = rows[6]

    ordered_names = []
    rigid_bodies_by_name = {}

    for column_index in range(2, len(axis_row)):
        body_type = read_csv_cell(type_row, column_index).strip()
        body_name = read_csv_cell(name_row, column_index).strip()
        body_id = read_csv_cell(id_row, column_index).strip()
        kind = read_csv_cell(kind_row, column_index).strip()
        axis = read_csv_cell(axis_row, column_index).strip().lower()

        if body_type != "Rigid Body" or not body_name:
            continue
        if kind != "Position" or axis not in {"x", "y", "z"}:
            continue

        if body_name not in rigid_bodies_by_name:
            ordered_names.append(body_name)
            rigid_bodies_by_name[body_name] = OptiTrackRigidBody(
                name=body_name,
                source_id=body_id,
                position_columns={},
            )

        rigid_bodies_by_name[body_name].position_columns[axis] = column_index

    rigid_bodies = []
    for body_name in ordered_names:
        body = rigid_bodies_by_name[body_name]
        if {"x", "y", "z"} <= set(body.position_columns):
            rigid_bodies.append(body)

    if not rigid_bodies:
        raise ValueError("V CSV exportu jsem nenasel zadne rigid body s Position X/Y/Z.")
    return rigid_bodies


def compute_bounds(frames: Iterable[OptiTrackFrame]) -> Dict[str, Tuple[float, float]]:
    xs = []
    ys = []
    zs = []
    for frame in frames:
        for x, y, z in frame.bodies.values():
            xs.append(x)
            ys.append(y)
            zs.append(z)

    if not xs:
        raise ValueError("Nelze spocitat bounds: zadny rigid body nema zadnou pozici.")

    return {
        "x": (min(xs), max(xs)),
        "y": (min(ys), max(ys)),
        "z": (min(zs), max(zs)),
    }


def shift_take(take: OptiTrackTake, offset_x: float, offset_y: float, offset_z: float) -> OptiTrackTake:
    """Vrati novy take s aplikovanym translacnim posunem."""
    shifted_frames = []
    for frame in take.frames:
        shifted_bodies = {
            name: (x + offset_x, y + offset_y, z + offset_z)
            for name, (x, y, z) in frame.bodies.items()
        }
        shifted_frames.append(
            OptiTrackFrame(
                frame_number=frame.frame_number,
                time_seconds=frame.time_seconds,
                bodies=shifted_bodies,
            )
        )

    return OptiTrackTake(
        path=take.path,
        sheet_name=take.sheet_name,
        metadata=take.metadata,
        rigid_bodies=take.rigid_bodies,
        frames=shifted_frames,
        capture_frame_rate=take.capture_frame_rate,
        export_frame_rate=take.export_frame_rate,
        frame_period_seconds=take.frame_period_seconds,
    )


def compute_auto_fit_offsets(
    frames: Iterable[OptiTrackFrame],
    *,
    room_size_x: float = 3.0,
    room_size_y: float = 3.0,
    room_margin: float = 0.35,
    floor_z: float = 0.15,
) -> Tuple[float, float, float]:
    bounds = compute_bounds(frames)
    min_x, max_x = bounds["x"]
    min_y, max_y = bounds["y"]
    min_z, _ = bounds["z"]

    span_x = max_x - min_x
    span_y = max_y - min_y
    usable_x = max(0.0, room_size_x - (2.0 * room_margin))
    usable_y = max(0.0, room_size_y - (2.0 * room_margin))

    target_min_x = room_margin
    if span_x < usable_x:
        target_min_x = room_margin + ((usable_x - span_x) / 2.0)

    target_min_y = room_margin
    if span_y < usable_y:
        target_min_y = room_margin + ((usable_y - span_y) / 2.0)

    return (
        target_min_x - min_x,
        target_min_y - min_y,
        max(0.0, floor_z - min_z),
    )
