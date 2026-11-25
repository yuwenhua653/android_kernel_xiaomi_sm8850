# Wireless sample validity and thermal decisions

## Corrected defects

The wireless monitor initialized receiver output current to zero and ignored
its provider error. When quick charging was reported inactive, it then voted
`iout + 250` mA: an unsuccessful sample could therefore introduce a 250 mA
input-current vote. A quick-charge status failure was similarly interpreted
as inactive, including advancing the voltage-fallback counter. Neither error
now creates a new vote or advances that fallback. A confirmed active quick
charge still removes this particular SOC current vote. A valid zero-current
sample still follows the original 250 mA rule; thresholds are unchanged.
Negative/overflowing current samples and non-boolean quick-charge results are
not used to make these decisions. Existing other thermal/hardware votes remain.
This is a reproducible source defect, not proof of the whole device power loss.

Battery STATUS and HEALTH lookups acquired a power-supply reference on every
read, overwrote the shared cached pointer and never released these references.
The probe also acquired an unused reference. Reads now acquire/use/release a
local reference, including failed reads; the unused probe acquisition is gone.
The private structure layout is retained. Failed STATUS/HEALTH reads preserve
existing state. Invalid SOC is not sent to the transmitter or used for the
monitor's charging-stage update. Successful HEALTH reads update both hot/cold
flags together, preventing stale flags when switching directly between them.
These health flags describe quick-charge presentation, not the primary
hardware thermal cut-off.

Receiver alarm recovery previously mixed unchecked current with cached
receiver temperature. Now current and temperature are validated independently:
a valid overcurrent or overtemperature can still trigger its existing limit
when the other sample fails. Clearing the temperature vote requires *both*
fresh valid samples and the unchanged hysteresis criteria. Failed samples
retain existing votes and the existing four-second retry. Failed quick-charge
status/current-limit reads cannot be used for a new mitigation value. Negative
current-vote results no longer underflow in subtraction.

The FFC selector used an uninitialized battery temperature after an unsuccessful
fuel-gauge read, and could divide by an invalid battery voltage. It now checks
JEITA data, current votes, receiver voltage, battery temperature/voltage and
fast-charge state before a decision. A failed dependency returns an error
without changing mode. Nonpositive cell voltage is rejected; input-current
power conversion uses a 64-bit intermediate. Existing periodic work provides
the next attempt; no fake temperature/voltage or replacement threshold is used.
This does not promise mitigation of sustained sensor loss: independent hardware
protection and the overall policy still need device qualification.

The train-transmitter and musical-box profiles also treated unsuccessful
battery-temperature reads as zero Celsius. In the musical-box path this could
select the existing 6000 mA cold-profile FCC vote. Both profiles now preserve
their previous settings on read failure. All valid-temperature tables remain
unchanged; the tests exercise their existing boundary behavior.

## Validation

- `test_wireless_samples.py`: **539** monitor, failed/invalid provider, stage,
  health, recovery and balanced-reference cases under UBSan.
- `test_wireless_safety_samples.py`: **874** alarm, hysteresis, partial sensor
  failure, failed FFC dependency, zero/negative cell voltage, arithmetic and
  transmitter-profile cases under UBSan.
- The preceding production monitor, health handler, alarm handler, FFC selector
  and transmitter profiles each fail the respective test when substituted.
- RX/TX queue/session, power-supply reporting, SC96281 command, IRQ,
  authentication and state regression suites pass. Earlier board-temperature,
  thermal-level, UFS and CNSS fixes are retained.
- Final `mca_basic_wireless.o` compiles for ARM64 using Clang 19.1.7 with CFI and
  MODVERSIONS. C checkpatch has zero errors/warnings.

These are source and object qualifications, not a full kernel Image, module
modpost, Android image, flashed device or net-charge measurement. No boot-only
flash or new build request to the owner accompanies this checkpoint.

## Thermal checklist correction

The current supplied mi_thermald executable (SHA-256
`95cad1487b0c9de8a81522392252e8ced4844af4b1cc4e27e357778d47b2df41`)
tries `thermal_message/cpu_limits`, then `ipa_cdev_limits`, then per-CPU
`cpufreq/scaling_max_freq` during CPU-device initialization. These are observed
fallback branches, not evidence of which succeeds on the current ROM.
Therefore absence of `cpu_limits` alone does **not** establish loss of CPU
thermal limiting, and is not by itself a reason to add an unqualified duplicate
CPU control path. Policy selection/screen controls and QTI skin mapping still
need matching configuration/runtime evidence. The opaque vendor thermal
configuration was not altered or assigned invented temperatures.

The board-temperature bridge is source-complete for its two verified attributes;
it is not the full private Xiaomi thermal API. Full duplication is unnecessary,
but all controls actually exercised by Myron policy must work. Keep the current
policy while qualifying those controls. Libperfmgr remains deferred. No shared
EvolutionX/Lineage source, thermal tables, UFS ownership or release label changes
are included.
