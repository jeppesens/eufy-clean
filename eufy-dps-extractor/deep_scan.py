#!/usr/bin/env python3
"""
deep_scan.py - Structured extraction of Tuya DPS codes from decompiled Java source.

Scans all .java files for DP-related patterns, deduplicates, and outputs
a structured JSON with all findings.

Usage: python3 deep_scan.py <decompiled_dir> <output_json>
"""

import sys
import os
import re
import json
from collections import defaultdict, OrderedDict

def main():
    if len(sys.argv) < 3:
        print("Usage: deep_scan.py <decompiled_dir> <output_json>", file=sys.stderr)
        sys.exit(1)

    decompiled_dir = sys.argv[1]
    output_file = sys.argv[2]

    # -----------------------------------------------------------------
    # Pattern definitions
    # -----------------------------------------------------------------

    # Direct DP ID assignments: dpId = 103, DpId = "122", etc.
    P_DP_ASSIGN = re.compile(
        r'(?:dp_?[Ii]d|datapoint_?[Ii]d|DpId|dpCode|DATA_POINT_ID)'
        r'\s*[=:]\s*"?(\d{1,3})"?'
    )

    # Constant int fields: static final int DP_CLEANING = 115;
    P_CONST_INT = re.compile(
        r'(?:static\s+)?(?:final\s+)?int\s+(\w+)\s*=\s*(\d{1,3})\s*;'
    )

    # Map.put("103", "cleaning") or put(103, ...)
    P_MAP_PUT = re.compile(
        r'\.put\(\s*(?:Integer\.valueOf\()?"?(\d{1,3})"?\)?\s*,\s*"?([^")\s,]+)"?'
    )

    # Switch case: case 103: or case 122:
    P_CASE = re.compile(r'case\s+(\d{1,3})\s*:')

    # Tuya dpCode strings (standard naming convention)
    KNOWN_DP_CODES = {
        "power", "power_go", "switch_go", "pause", "mode", "status",
        "direction_control", "suction", "seek", "clean_speed",
        "battery_percentage", "battery", "cleaning_area", "cleaning_time",
        "fault", "volume_set", "volume", "reset_edge_brush",
        "reset_roll_brush", "reset_filter", "reset_duster_cloth",
        "reset_map", "break_clean", "switch_charge", "cistern",
        "collection_mode", "dust_collection", "device_timer",
        "disturb_time", "disturb_time_set", "customize_mode",
        "command_trans", "path_data", "voice_switch", "voice_data",
        "work_mode", "work_status", "go_home", "fan_speed",
        "error_code", "boost_iq", "auto_return", "do_not_disturb",
        "small_room", "edge_clean", "mop_mode", "water_level",
        "carpet_boost", "consumable", "side_brush_life",
        "rolling_brush_life", "filter_life", "sensor_life",
        "duster_cloth_life", "request", "language",
        "dust_collection_num", "dust_collection_switch",
        "wake_up", "switch_disturb", "customize_mode_switch",
        "device_info", "clean_area", "clean_time",
        "side_brush", "roll_brush", "filter", "duster_cloth",
        "edge_brush", "rolling_brush", "main_brush",
        "mop", "mop_life", "sensor", "clean_record",
        "map_data", "virtual_wall", "restricted_area",
        "clean_preference", "carpet_clean_preference",
        "y_mop", "water_box", "water_tank",
    }

    P_STRING_LITERAL = re.compile(r'"([a-z][a-z0-9_]{2,40})"')

    # Priority path keywords
    P_PRIORITY = re.compile(
        r'(?i)(robovac|vacuum|clean|sweep|robot|tuya|dp|datapoint|device)',
    )

    # Model number patterns (Eufy uses T2xxx, T8xxx etc.)
    P_MODEL = re.compile(r'["\']?(T[0-9]{4}[A-Z]?)["\']?')

    # -----------------------------------------------------------------
    # Scan
    # -----------------------------------------------------------------
    results = {
        "dp_assignments": [],
        "dp_constants": [],
        "dp_map_entries": [],
        "dp_switch_cases": [],
        "dp_code_strings": [],
        "model_references": [],
        "vacuum_classes": [],
        "tuya_classes": [],
    }

    seen_assignments = set()
    seen_constants = set()
    seen_map_entries = set()
    seen_dp_codes = set()
    seen_models = set()
    seen_cases = defaultdict(set)  # file -> set of case values

    file_count = 0
    for root, dirs, files in os.walk(decompiled_dir):
        for fname in files:
            if not fname.endswith('.java'):
                continue

            filepath = os.path.join(root, fname)
            relpath = os.path.relpath(filepath, decompiled_dir)
            file_count += 1

            try:
                with open(filepath, 'r', errors='replace') as f:
                    content = f.read()
                    lines = content.split('\n')
            except Exception:
                continue

            is_priority = bool(P_PRIORITY.search(relpath))

            # Track vacuum and tuya classes
            if re.search(r'(?i)(robovac|vacuum|clean.?robot|sweep.?robot)', relpath):
                results["vacuum_classes"].append(relpath)
            if re.search(r'(?i)(tuya|tuyasmart|thing)', relpath):
                results["tuya_classes"].append(relpath)

            for i, line in enumerate(lines, 1):
                stripped = line.strip()

                # DP ID assignments
                for m in P_DP_ASSIGN.finditer(stripped):
                    dp_id = int(m.group(1))
                    if 1 <= dp_id <= 255:
                        key = (relpath, dp_id, stripped[:80])
                        if key not in seen_assignments:
                            seen_assignments.add(key)
                            results["dp_assignments"].append({
                                "dp_id": dp_id,
                                "file": relpath,
                                "line": i,
                                "context": stripped[:200],
                                "priority": is_priority,
                            })

                # Constant int definitions
                for m in P_CONST_INT.finditer(stripped):
                    name, val = m.group(1), int(m.group(2))
                    if 1 <= val <= 255 and re.search(r'(?i)(dp|data|point|clean|mode|status|battery|brush|filter|error|speed|volume|mop|suction|seek)', name):
                        key = (name, val)
                        if key not in seen_constants:
                            seen_constants.add(key)
                            results["dp_constants"].append({
                                "name": name,
                                "value": val,
                                "file": relpath,
                                "line": i,
                                "context": stripped[:200],
                            })

                # Map.put entries
                for m in P_MAP_PUT.finditer(stripped):
                    dp_id, value = m.group(1), m.group(2)
                    if dp_id.isdigit() and 1 <= int(dp_id) <= 255:
                        key = (dp_id, value, relpath)
                        if key not in seen_map_entries:
                            seen_map_entries.add(key)
                            results["dp_map_entries"].append({
                                "dp_id": int(dp_id),
                                "value": value,
                                "file": relpath,
                                "line": i,
                                "context": stripped[:200],
                            })

                # Switch cases (in priority files only, to reduce noise)
                if is_priority:
                    for m in P_CASE.finditer(stripped):
                        case_val = int(m.group(1))
                        if 1 <= case_val <= 255:
                            if case_val not in seen_cases[relpath]:
                                seen_cases[relpath].add(case_val)
                                results["dp_switch_cases"].append({
                                    "dp_id": case_val,
                                    "file": relpath,
                                    "line": i,
                                    "context": stripped[:200],
                                })

                # DP code strings
                for m in P_STRING_LITERAL.finditer(stripped):
                    code = m.group(1)
                    if code in KNOWN_DP_CODES:
                        if code not in seen_dp_codes:
                            seen_dp_codes.add(code)
                            results["dp_code_strings"].append({
                                "code": code,
                                "file": relpath,
                                "line": i,
                            })

            # Model references (scan full content)
            for m in P_MODEL.finditer(content):
                model = m.group(1)
                if model not in seen_models:
                    seen_models.add(model)
                    results["model_references"].append({
                        "model": model,
                        "file": relpath,
                    })

    # -----------------------------------------------------------------
    # Post-process: build a unified DP table
    # -----------------------------------------------------------------
    dp_table = OrderedDict()

    for entry in results["dp_assignments"]:
        dp_id = entry["dp_id"]
        if dp_id not in dp_table:
            dp_table[dp_id] = {
                "dp_id": dp_id,
                "names": [],
                "sources": [],
            }
        dp_table[dp_id]["sources"].append({
            "type": "assignment",
            "file": entry["file"],
            "line": entry["line"],
            "context": entry["context"],
        })

    for entry in results["dp_constants"]:
        val = entry["value"]
        if val not in dp_table:
            dp_table[val] = {
                "dp_id": val,
                "names": [],
                "sources": [],
            }
        dp_table[val]["names"].append(entry["name"])
        dp_table[val]["sources"].append({
            "type": "constant",
            "name": entry["name"],
            "file": entry["file"],
            "line": entry["line"],
        })

    for entry in results["dp_map_entries"]:
        dp_id = entry["dp_id"]
        if dp_id not in dp_table:
            dp_table[dp_id] = {
                "dp_id": dp_id,
                "names": [],
                "sources": [],
            }
        dp_table[dp_id]["names"].append(entry["value"])
        dp_table[dp_id]["sources"].append({
            "type": "map_entry",
            "value": entry["value"],
            "file": entry["file"],
            "line": entry["line"],
        })

    # Sort by DP ID
    dp_table_sorted = OrderedDict(sorted(dp_table.items()))

    # -----------------------------------------------------------------
    # Output
    # -----------------------------------------------------------------
    output = {
        "stats": {
            "total_java_files": file_count,
            "dp_assignments_found": len(results["dp_assignments"]),
            "dp_constants_found": len(results["dp_constants"]),
            "dp_map_entries_found": len(results["dp_map_entries"]),
            "dp_switch_cases_found": len(results["dp_switch_cases"]),
            "dp_code_strings_found": len(results["dp_code_strings"]),
            "model_references_found": len(results["model_references"]),
            "vacuum_classes_found": len(results["vacuum_classes"]),
            "tuya_classes_found": len(results["tuya_classes"]),
            "unique_dp_ids": len(dp_table_sorted),
        },
        "dp_table": list(dp_table_sorted.values()),
        "dp_code_strings": results["dp_code_strings"],
        "model_references": results["model_references"],
        "vacuum_classes": results["vacuum_classes"],
        "tuya_classes": results["tuya_classes"][:50],
        "raw": {
            "dp_assignments": results["dp_assignments"],
            "dp_constants": results["dp_constants"],
            "dp_map_entries": results["dp_map_entries"],
            "dp_switch_cases": results["dp_switch_cases"],
        },
    }

    with open(output_file, 'w') as f:
        json.dump(output, f, indent=2)

    # Print summary
    s = output["stats"]
    print(f"  Scanned:           {s['total_java_files']} Java files")
    print(f"  DP assignments:    {s['dp_assignments_found']}")
    print(f"  DP constants:      {s['dp_constants_found']}")
    print(f"  DP map entries:    {s['dp_map_entries_found']}")
    print(f"  DP switch cases:   {s['dp_switch_cases_found']}")
    print(f"  DP code strings:   {s['dp_code_strings_found']}")
    print(f"  Model references:  {s['model_references_found']}")
    print(f"  Vacuum classes:    {s['vacuum_classes_found']}")
    print(f"  Tuya classes:      {s['tuya_classes_found']}")
    print(f"  Unique DP IDs:     {s['unique_dp_ids']}")
    print(f"  Output:            {output_file}")

    # Quick DP table preview
    if dp_table_sorted:
        print(f"\n  --- DP TABLE PREVIEW (top 30) ---")
        for dp_id, info in list(dp_table_sorted.items())[:30]:
            names = ", ".join(set(info["names"])) if info["names"] else "(unnamed)"
            print(f"    DP {dp_id:>3d}: {names}")

    if results["dp_code_strings"]:
        print(f"\n  --- KNOWN DP CODES FOUND ---")
        for entry in sorted(results["dp_code_strings"], key=lambda x: x["code"]):
            print(f"    {entry['code']}")

    if results["model_references"]:
        print(f"\n  --- MODEL NUMBERS FOUND ---")
        models = sorted(set(m["model"] for m in results["model_references"]))
        for m in models:
            print(f"    {m}")


if __name__ == "__main__":
    main()
