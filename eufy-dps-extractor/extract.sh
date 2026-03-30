#!/usr/bin/env bash
#
# extract.sh - Decompile eufy Clean APK and extract all Tuya DPS codes.
# Runs inside Docker. Expects APK in /apk/, writes results to /output/.
#
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

log()  { echo -e "${GREEN}[+]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[x]${NC} $1"; }
hdr()  { echo -e "\n${CYAN}${BOLD}$1${NC}"; }

# =========================================================================
# 1. Find the APK (supports .apk, .apkm, .xapk, .apks)
# =========================================================================

# .apkm / .xapk / .apks are all ZIP bundles containing split APKs.
# The actual code lives in base.apk inside the bundle.
# We extract base.apk (and any split DEX apks) and feed those to jadx.

extract_bundle() {
    local bundle="$1"
    local extract_dir="/work/bundle_extracted"
    rm -rf "$extract_dir"
    mkdir -p "$extract_dir"

    log "Detected bundle format: $(basename "$bundle")" >&2
    log "Extracting base.apk from bundle..." >&2

    unzip -q -o "$bundle" -d "$extract_dir" 2>/dev/null || {
        err "Failed to unzip bundle. File may be corrupted." >&2
        exit 1
    }

    # Show what's inside
    log "Bundle contents:" >&2
    ls -lh "$extract_dir"/ | grep -v '^total' | while read -r line; do
        echo "    $line"
    done >&2

    # Find base.apk (the one with all the code)
    local base=""
    if [[ -f "$extract_dir/base.apk" ]]; then
        base="$extract_dir/base.apk"
    elif [[ -f "$extract_dir/base-master.apk" ]]; then
        base="$extract_dir/base-master.apk"
    else
        # Some bundles just have numbered APKs; find the largest one
        base=$(find "$extract_dir" -name '*.apk' -printf '%s %p\n' | sort -rn | head -1 | cut -d' ' -f2-)
    fi

    if [[ -z "$base" || ! -f "$base" ]]; then
        err "Could not find base.apk inside the bundle." >&2
        err "Contents of bundle:" >&2
        ls -la "$extract_dir"/ >&2
        exit 1
    fi

    log "Using: $(basename "$base") ($(du -h "$base" | cut -f1))" >&2

    # Also collect split APKs that might contain additional DEX files
    # (config splits are just resources/native libs, but some have code)
    SPLIT_APKS=()
    shopt -s nullglob
    for split in "$extract_dir"/split_config.*.apk "$extract_dir"/split_*.apk; do
        if [[ "$split" != "$base" ]]; then
            SPLIT_APKS+=("$split")
        fi
    done
    shopt -u nullglob

    if [[ ${#SPLIT_APKS[@]} -gt 0 ]]; then
        log "Found ${#SPLIT_APKS[@]} split APKs (will scan for additional code)" >&2
    fi

    echo "$base"
}

APK_FILE=""
BUNDLE_NAME=""

# Check if a path was passed as argument
if [[ $# -ge 1 && -f "$1" ]]; then
    APK_FILE="$1"
fi

# Otherwise scan /apk/ for .apk, .apkm, .xapk, .apks
if [[ -z "$APK_FILE" ]]; then
    shopt -s nullglob
    all_files=(/apk/*.apk /apk/*.apkm /apk/*.xapk /apk/*.apks)
    shopt -u nullglob

    if [[ ${#all_files[@]} -eq 0 ]]; then
        err "No APK or bundle found in /apk/."
        echo ""
        echo "Mount your file into the container:"
        echo "  docker run -v /path/to/file.apkm:/apk/eufy.apkm -v ./output:/output eufy-dps-extractor"
        echo ""
        echo "Supported formats: .apk, .apkm, .xapk, .apks"
        echo ""
        echo "Download from:"
        echo "  https://www.apkmirror.com/apk/anker/eufyhome/"
        echo "  Package: com.eufylife.smarthome"
        exit 1
    fi

    APK_FILE="${all_files[0]}"
    if [[ ${#all_files[@]} -gt 1 ]]; then
        warn "Multiple files found, using: $(basename "$APK_FILE")"
        warn "Others: ${all_files[*]:1}"
    fi
fi

SPLIT_APKS=()

# Handle bundle formats (.apkm, .xapk, .apks)
case "$APK_FILE" in
    *.apkm|*.xapk|*.apks)
        BUNDLE_NAME="$(basename "$APK_FILE")"
        # Strip any bundle extension for the output name
        APK_NAME="${BUNDLE_NAME%.*}"
        APK_FILE="$(extract_bundle "$APK_FILE")"
        ;;
    *.apk)
        APK_NAME="$(basename "$APK_FILE" .apk)"
        ;;
    *)
        # Try treating it as a bundle anyway (might be misnamed)
        if file "$APK_FILE" | grep -q 'Zip archive'; then
            warn "Unknown extension but file is a ZIP. Trying as bundle..."
            BUNDLE_NAME="$(basename "$APK_FILE")"
            APK_NAME="${BUNDLE_NAME%.*}"
            APK_FILE="$(extract_bundle "$APK_FILE")"
        else
            APK_NAME="$(basename "$APK_FILE")"
        fi
        ;;
esac

# Re-collect split APKs from the extract dir (the subshell can't propagate arrays)
if [[ -d /work/bundle_extracted ]]; then
    shopt -s nullglob
    for split in /work/bundle_extracted/split_*.apk; do
        SPLIT_APKS+=("$split")
    done
    shopt -u nullglob
fi
DECOMPILED="/work/decompiled"
RESULTS="/output/${APK_NAME}"

mkdir -p "$RESULTS"

hdr "EUFY CLEAN DPS EXTRACTOR"
if [[ -n "${BUNDLE_NAME:-}" ]]; then
    log "Bundle: ${BUNDLE_NAME}"
fi
log "APK:    $(basename "$APK_FILE") ($(du -h "$APK_FILE" | cut -f1))"
log "Output: ${RESULTS}"
echo ""

# =========================================================================
# 2. Decompile with jadx
# =========================================================================
hdr "STEP 1: Decompiling APK with jadx"
log "This takes 1-5 minutes depending on APK size..."

rm -rf "$DECOMPILED"

# Build input file list: base APK + any split APKs that might contain code
JADX_INPUTS=("$APK_FILE")
if [[ ${#SPLIT_APKS[@]} -gt 0 ]]; then
    for split in "${SPLIT_APKS[@]}"; do
        JADX_INPUTS+=("$split")
    done
    log "Feeding ${#JADX_INPUTS[@]} APKs to jadx (base + ${#SPLIT_APKS[@]} splits)"
fi

jadx \
    --no-res \
    --no-debug-info \
    --threads-count "$(nproc)" \
    --output-dir "$DECOMPILED" \
    "${JADX_INPUTS[@]}" \
    2>"${RESULTS}/jadx_warnings.log" || {
        warn "jadx had warnings (normal for obfuscated APKs, see jadx_warnings.log)"
    }

JAVA_COUNT=$(find "$DECOMPILED" -name '*.java' | wc -l)
log "Decompiled ${JAVA_COUNT} Java source files."

# =========================================================================
# 3. Grep passes
# =========================================================================
hdr "STEP 2: Scanning for DPS references (8 passes)"
GREP_DIR="${RESULTS}/grep_results"
mkdir -p "$GREP_DIR"

run_grep() {
    local name="$1"
    local pattern="$2"
    local desc="$3"
    local outfile="${GREP_DIR}/${name}.txt"

    grep -rn --include='*.java' -E "$pattern" "$DECOMPILED" \
        | sed "s|${DECOMPILED}/||g" \
        > "$outfile" 2>/dev/null || true

    local count
    count=$(wc -l < "$outfile" 2>/dev/null || echo 0)
    log "  ${desc}: ${count} hits"
}

# Pass 1: Direct DP ID assignments
run_grep "01_dp_id_assignments" \
    '(dp_?[Ii]d|datapoint_?[Ii]d|DpId|data_point)\s*[=:]\s*[0-9]+' \
    "DP ID assignments"

# Pass 2: DP enum/constant class declarations
run_grep "02_dp_classes" \
    '(enum|class|interface).*(Dp|DP|DataPoint|DpCode|TuyaDp)' \
    "DP enum/constant classes"

# Pass 3: Tuya SDK method calls
run_grep "03_tuya_sdk" \
    '(getDps|sendDps|publishDps|onDpUpdate|TuyaHomeSdk|ITuyaDevice|IThingDevice)' \
    "Tuya SDK references"

# Pass 4: HashMap/Map.put with numeric keys (DP map construction)
run_grep "04_map_puts" \
    '\.(put|set)\(\s*"?[0-9]{1,3}"?\s*,' \
    "Map.put with numeric keys"

# Pass 5: Mode/status/error string enums
run_grep "05_mode_strings" \
    '"(standby|cleaning|completed|sleeping|charging|paused|docking|error|random|smart|wall_follow|mop|spiral|edge|spot|room|auto|manual|boost|quiet|standard|turbo|max|gentle|normal|strong|sweep|vacuum_mop|sweep_only|mop_only)"' \
    "Mode/status strings"

# Pass 6: Vacuum/robovac specific classes
run_grep "06_vacuum_refs" \
    '(robovac|robot.?vac|vacuum|sweep|clean.?robot|robo.?clean|RoboVac|CleanRobot)' \
    "Vacuum/robovac references"

# Pass 7: DpCode string constants (Tuya standard naming)
run_grep "07_dp_codes" \
    '"(power_go|switch_go|pause|mode|status|direction_control|suction|seek|clean_speed|battery_percentage|cleaning_area|cleaning_time|fault|volume_set|reset_edge_brush|reset_roll_brush|reset_filter|reset_duster_cloth|reset_map|break_clean|switch_charge|cistern|collection_mode|dust_collection|device_timer|disturb_time|customize_mode|command_trans|path_data|voice_switch|work_mode|work_status|go_home|fan_speed|error_code|boost_iq|auto_return|do_not_disturb|small_room|edge_clean|mop_mode|water_level|carpet_boost|consumable|side_brush_life|rolling_brush_life|filter_life|sensor_life|duster_cloth_life)"' \
    "Tuya dpCode strings"

# Pass 8: JSON DP schemas (sometimes embedded)
run_grep "08_json_dp_schema" \
    '"dp[Ii]d"\s*:\s*[0-9]+|"code"\s*:\s*"[a-z_]+"' \
    "JSON DP schema fragments"

# =========================================================================
# 4. Find and copy full vacuum-related source files
# =========================================================================
hdr "STEP 3: Extracting vacuum-related source files"
VACUUM_SRC="${RESULTS}/vacuum_sources"
mkdir -p "$VACUUM_SRC"

find "$DECOMPILED" -name '*.java' -print0 | xargs -0 grep -li \
    -E '(RoboVac|robovac|robot.?[Vv]ac|[Vv]acuum[A-Z]|CleanRobot|SweepRobot|TuyaDp|DpId|dpId|DataPointId)' \
    > "${RESULTS}/_vacuum_file_list.txt" 2>/dev/null || true

VACUUM_FILE_COUNT=$(wc -l < "${RESULTS}/_vacuum_file_list.txt" 2>/dev/null || echo 0)
log "Found ${VACUUM_FILE_COUNT} vacuum-related source files."

# Copy them to output for easy browsing
while IFS= read -r src; do
    relpath="${src#${DECOMPILED}/}"
    destdir="${VACUUM_SRC}/$(dirname "$relpath")"
    mkdir -p "$destdir"
    cp "$src" "$destdir/"
done < "${RESULTS}/_vacuum_file_list.txt"

log "Copied to ${VACUUM_SRC}/"

# =========================================================================
# 5. Extract JSON/asset files that might contain DP schemas
# =========================================================================
hdr "STEP 4: Searching for DP schema assets"
ASSETS_DIR="${RESULTS}/assets"
mkdir -p "$ASSETS_DIR"

# Look for JSON files with DP references inside the decompiled resources
find "$DECOMPILED" \( -name '*.json' -o -name '*.cfg' -o -name '*.xml' \) -print0 \
    | xargs -0 grep -li -E '(dpId|dp_id|datapoint|DpCode)' 2>/dev/null \
    | while IFS= read -r f; do
        cp "$f" "$ASSETS_DIR/" 2>/dev/null || true
    done || true

ASSET_COUNT=$(find "$ASSETS_DIR" -type f | wc -l)
log "Found ${ASSET_COUNT} asset files with DP references."

# =========================================================================
# 6. Python deep scan
# =========================================================================
hdr "STEP 5: Python deep-scan for structured extraction"
python3 /usr/local/bin/deep_scan.py "$DECOMPILED" "${RESULTS}/dps_extracted.json"

# =========================================================================
# 7. Generate final report
# =========================================================================
hdr "STEP 6: Generating report"

REPORT="${RESULTS}/REPORT.md"
cat > "$REPORT" <<MDEOF
# Eufy Clean DPS Extraction Report

**APK:** \`$(basename "$APK_FILE")\`
**Date:** $(date -u '+%Y-%m-%d %H:%M UTC')
**Java files decompiled:** ${JAVA_COUNT}
**Vacuum-related files found:** ${VACUUM_FILE_COUNT}

## Grep Results

| File | Hits | Description |
|------|------|-------------|
MDEOF

for f in "${GREP_DIR}"/*.txt; do
    fname=$(basename "$f")
    count=$(wc -l < "$f")
    # Strip number prefix and extension for description
    desc=$(echo "$fname" | sed 's/^[0-9]*_//;s/\.txt$//' | tr '_' ' ')
    echo "| \`${fname}\` | ${count} | ${desc} |" >> "$REPORT"
done

cat >> "$REPORT" <<'MDEOF'

## Key Files to Inspect

The most valuable files are in `vacuum_sources/`. Look for:

1. **Enum classes** with DP ID constants (e.g., `DpCode.java`, `DataPointEnum.java`)
2. **Model config classes** that map model numbers to supported DPs
3. **Command handler classes** that dispatch based on DP ID (switch/case blocks)
4. **JSON schema files** in `assets/` that define DP structure per model

## Structured Extraction

See `dps_extracted.json` for machine-readable results from the Python deep-scan.

```bash
# Pretty-print the structured results
cat dps_extracted.json | python3 -m json.tool | less

# Quick look at found DPs
cat dps_extracted.json | python3 -c "
import json, sys
data = json.load(sys.stdin)
print(f\"DP assignments: {data['stats']['dp_assignments_found']}\")
print(f\"DP code strings: {data['stats']['dp_code_strings_found']}\")
print(f\"Vacuum classes: {data['stats']['vacuum_classes_found']}\")
print()
for dp in data.get('dp_code_strings', []):
    print(f\"  {dp['code']:30s}  ({dp['file']})\")
"
```

## Manual Exploration

```bash
# Browse vacuum source files
ls vacuum_sources/

# Search for a specific DP number
grep -rn '122' vacuum_sources/

# Find all numeric constant definitions in vacuum classes
grep -rn 'static.*final.*int.*=.*[0-9]' vacuum_sources/

# Find model-specific DP configs (replace with your model)
grep -rn 'T2250\|T2262\|T2267\|T2351' vacuum_sources/
```
MDEOF

log "Report written to: ${REPORT}"

# =========================================================================
# 8. Summary
# =========================================================================
hdr "EXTRACTION COMPLETE"
echo ""
echo -e "  ${BOLD}Output directory:${NC} ${RESULTS}"
echo ""
echo "  Contents:"
echo "    REPORT.md                   Summary report"
echo "    dps_extracted.json          Structured DP extraction (JSON)"
echo "    grep_results/               Raw grep output (8 passes)"
echo "    vacuum_sources/             Decompiled vacuum-related .java files"
echo "    assets/                     JSON/config files with DP references"
echo "    jadx_warnings.log           Decompiler warnings"
echo ""
echo -e "  ${YELLOW}Start here:${NC}"
echo "    cat ${RESULTS}/REPORT.md"
echo "    cat ${RESULTS}/dps_extracted.json | python3 -m json.tool"
echo "    ls  ${RESULTS}/vacuum_sources/"
echo ""
