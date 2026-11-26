#!/system/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Read-only evidence collection. No charging, thermal, idle or module controls.
# Run in a root adb shell for dmesg/debugfs/FDT access; no root is attempted here.
set -u
samples=${1:-60}
interval=${2:-10}
case "$samples:$interval" in
    *[!0-9:]*|:*|*:) echo 'Usage: sh capture-runtime-gaps.sh [samples 1-360] [interval 1-60]' >&2; exit 2 ;;
esac
if [ "$samples" -lt 1 ] || [ "$samples" -gt 360 ] || [ "$interval" -lt 1 ] || [ "$interval" -gt 60 ]; then
    echo 'samples must be 1-360; interval must be 1-60 seconds' >&2
    exit 2
fi
out=$(mktemp -d /data/local/tmp/myron-runtime-gaps-XXXXXXXX) || exit 1
chmod 700 "$out"
trap 'echo "Collection interrupted; partial evidence: $out" >&2; exit 130' INT TERM
read_file() {
    printf '\n[%s]\n' "$1"
    if [ -r "$1" ]; then cat "$1" 2>&1; else echo 'UNAVAILABLE (absent or permission denied)'; fi
}
snapshot() {
    date -u
    read_file /proc/uptime
    for psy in /sys/class/power_supply/*; do
        [ -d "$psy" ] || continue
        for prop in type present online status health capacity charge_counter energy_now voltage_now current_now power_now temp input_current_limit constant_charge_current_max charge_type; do
            [ -e "$psy/$prop" ] && read_file "$psy/$prop"
        done
    done
    for zone in /sys/class/thermal/thermal_zone*; do
        [ -d "$zone" ] || continue
        read_file "$zone/type"
        read_file "$zone/temp"
    done
    for cdev in /sys/class/thermal/cooling_device*; do
        [ -d "$cdev" ] || continue
        read_file "$cdev/type"
        read_file "$cdev/cur_state"
        read_file "$cdev/max_state"
    done
    for prop in board_sensor board_sensor_temp; do
        read_file "/sys/class/thermal/thermal_message/$prop"
    done
}
{
    date -u
    id
    uname -a
    for prop in ro.build.fingerprint ro.vendor.build.fingerprint ro.boot.slot_suffix init.svc.mi_thermald init.svc.vendor.thermal-engine; do
        printf '%s=' "$prop"
        getprop "$prop"
    done
    read_file /proc/modules
    read_file /proc/sys/kernel/random/entropy_avail
    read_file /sys/devices/system/cpu/cpuidle/current_governor_ro
    read_file /sys/kernel/debug/devices_deferred
} > "$out/baseline.txt" 2>&1
if [ -r /sys/firmware/fdt ]; then
    cat /sys/firmware/fdt > "$out/running-fdt.dtb"
else
    echo 'Running flattened DT unavailable; no source DT substituted.' > "$out/running-fdt-unavailable.txt"
fi
dmesg > "$out/dmesg-start.txt" 2>&1
dumpsys thermalservice > "$out/thermalservice-start.txt" 2>&1
dumpsys battery > "$out/battery-start.txt" 2>&1
for phase in start end; do
    if [ "$phase" = end ]; then
        n=1
        while [ "$n" -le "$samples" ]; do
            snapshot > "$out/sample-$(printf '%03d' "$n").txt" 2>&1
            [ "$n" -eq "$samples" ] || sleep "$interval"
            n=$((n + 1))
        done
    fi
    {
        for node in /sys/power/suspend_stats/* /sys/devices/system/cpu/cpu*/cpuidle/state*/name /sys/devices/system/cpu/cpu*/cpuidle/state*/usage /sys/devices/system/cpu/cpu*/cpuidle/state*/time; do
            [ -f "$node" ] && read_file "$node"
        done
        read_file /sys/kernel/debug/wakeup_sources
    } > "$out/idle-$phase.txt" 2>&1
done
dmesg > "$out/dmesg-end.txt" 2>&1
dumpsys thermalservice > "$out/thermalservice-end.txt" 2>&1
dumpsys battery > "$out/battery-end.txt" 2>&1
cat > "$out/README.txt" <<EOF
Read-only collection: $samples samples, interval $interval seconds.
No charging limits, thermal thresholds, module state, or power settings changed.
Missing nodes/permission errors are evidence of unavailable observations, not
proof of a broken driver. Charging current sign must be established per supply;
use charge_counter/energy trends with voltage/current/status, not capacity alone.
Polling itself wakes the device. Idle deltas here cannot measure overnight drain.
No logcat, serial number or account data was requested; review kernel logs and
build identifiers before publicly sharing. Nothing was uploaded by this script.
EOF
archive="$out.tar.gz"
if tar -czf "$archive" -C /data/local/tmp "${out##*/}"; then
    chmod 600 "$archive"
    echo "Capture saved: $archive"
else
    echo "Archive failed; raw evidence retained: $out" >&2
    exit 1
fi
