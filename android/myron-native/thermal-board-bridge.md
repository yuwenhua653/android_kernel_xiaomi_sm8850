# Myron board-temperature bridge

## Source correction

Restore the verified `board_sensor` (read-only) and `board_sensor_temp`
(read/write) attributes under `/sys/class/thermal/thermal_message`.
`board-sensor` comes from the enabled `/soc/thermal-message` DT node, which
already exists in the archived Myron trees. A missing/disabled node or missing
label fails initialization; no physical sensor is substituted.

Each valid signed decimal milli-Celsius sample is delivered synchronously to
`MCA_EVENT_TYPE_THERMAL_TEMP` / `MCA_EVENT_THERMAL_BOARD_TEMP_CHANGE`.
The four existing subscribers are buck charging, fuel gauge, smart charging
and connector protection. The current source enum, not an old numeric event
ID, determines delivery. Negative temperatures retain their sign and units.
Repeated values are delivered too, allowing later subscribers to receive the
next periodic userspace write. There is no replay timer in this module.

Malformed or overflowing writes return an error without changing state or
sending an event. Reads before the first valid write return `-ENODATA`.
Writes and notifications are serialized, so concurrent writes cannot publish
in reverse order. Sysfs removal drains callbacks before the label is freed.
No temperatures, charging currents or protection thresholds are invented.

The module owns an auxiliary device in the existing thermal class. A small,
config-guarded GPL helper in thermal core creates that device through the
normal device API. This avoids copying private class/kernfs structures or
registering a fake thermal zone/cooling device. The helper is an additive
export: existing structure layouts and function signatures are unchanged.
This is not a claim that a complete KMI/signature check has run.

`CONFIG_MI_THERMAL_INTERFACE=m` is selected only in the native Myron fragment.
The device tree's effective Make lists install/load the module in vendor_dlkm
after MCA event infrastructure and the four subscribers. Module ordering is
not proof that all platform probes have completed. MCA's notification API is
void and can drop notifications before its event device is ready; the bridge
cannot acknowledge consumer receipt. Periodic writes can supply later samples.

## Contract evidence

The currently supplied vendor `mi_thermald` executable has an active path that
opens `board_sensor_temp`, formats a sensor result as `%d` followed by newline,
and writes it periodically. This establishes a scalar integer writer, not
merely an unused path string. It does not establish that this thread is alive
on the user's current phone or that all other policy interfaces are available.

The previously uploaded vendor_dlkm reference contains a GPL-labelled
`mi_thermal_interface.ko` built for 6.12.23. Its board-temperature store parses
a decimal integer and passes the value without scaling to MCA. Its paired
connector-protection consumer divides the sample by 1000. Together these
establish the milli-Celsius interface. That old binary sends event `0x38`;
this source tree defines the corresponding event as `0x3c`. The new code uses
the symbolic enum so it matches the current subscribers.

Reference hashes (SHA-256):

| Reference | SHA-256 |
| --- | --- |
| Current vendor mi_thermald | `95cad1487b0c9de8a81522392252e8ced4844af4b1cc4e27e357778d47b2df41` |
| Uploaded historical vendor_dlkm.img | `7d0809c9369f2fa427a72f3667c7fdd72c5ec9c2696a85877d617350280684c8` |
| Historical mi_thermal_interface.ko | `e4ef8eed3d9643e983d004a743496153a5a4dd6e6c1a2ea576ab3d8478fff6a6` |

Historical module Build ID: `55b6eb6f452047b5f5f1c21763a17e7e9d01b5d4`.
Its vermagic is `6.12.23-android16-5-gf79b0b15da3a-mi-4k`; it is a behavior
reference, not a loadable replacement for the current 6.12.118 kernel.
The binaries and disassembly are not included in this commit. This bridge is
new source implementing the verified contract, not an import of another
community driver's full implementation.

## Qualification

- `tests/test_board_thermal_bridge.py --kernel-root <kernel>` executes the
  actual store/show/init/exit functions and actual connector notification
  callback with mocked kernel backends. 29 cases and 2,000 concurrent writes
  pass under UBSan: missing/disabled DT, allocation/device creation failures,
  cleanup, no-data reads, negative and integer-boundary values, invalid writes,
  unchanged rejected state, repeated delivery and ordered concurrency.
- Deliberately using the historical event `0x38` or scaling before publication
  fails the same harness. The tests therefore detect the two contract errors.
- `thermal_core.o` and `mi_thermal_interface.o` compile for ARM64 with
  Clang 19.1.7, CFI and MODVERSIONS in the qualification configuration.
- Device `check_thermal_modules.py` checks the five QTI providers plus the new
  bridge's selection, ARM64 object and effective Make install/load order.
- C checkpatch reports zero errors/warnings. These checks do not replace a
  full kernel/modpost, final partition verification, SELinux policy build or
  device thermal qualification. Existing policy grants mi_thermald access to
  sysfs thermal files; actual labels/access still need runtime verification.

## Remaining scope

This closes the missing board-temperature publisher in source. It is **not**
a complete implementation of Xiaomi's thermal_message ABI. CPU/profile,
screen and other private controls must be justified individually by the
active policy; nonexistent controls are not replaced with successful stubs.
The QTI skin-temperature mapping and live cooling behavior remain open.
Keep mi_thermald until an alternative policy is calibrated and qualified;
there is no need to reproduce all Xiaomi private functionality to use the
standard thermal framework. Libperfmgr remains deferred.

Wireless RX ordering, battery-provider/vote and charging-level boundary fixes
remain present. Net wireless charge gain still needs a new device result;
this board-temperature bridge alone does not establish the cause of the
reported power deficit. Existing UFS boot fixes and yuzuli naming are retained.
