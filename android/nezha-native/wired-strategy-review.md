# Nezha wired charging patch repair — 2026-11-27

Reviewed attachment: `0001-kernel-nezha-enable-wired-charging-strategy-jeita-protection.patch`.
Base: `d4a56a646e5087cffa80081c0d647d99aa9735de` (`nazha`).

The submitted patch had malformed hunk counts, stale contexts, incomplete
provider dependencies and incorrect ownership of a borrowed `usb` supply.
This change adopts a standalone strategy registry selector and fixes concrete
USB, dispatcher, protection sampling and DTPT routing bugs. It does not activate
the proposed wired policy bundle or add its module load entries.

## Validation

Run from the kernel source root with a host C compiler and make:

```sh
python3 tools/test-mca-usb-ownership.py
python3 tools/test-mca-strategy-lifetime.py
python3 tools/test-mca-protection-errors.py
python3 tools/test-mca-dtpt-route.py
python3 tools/test-nezha-jeita-events.py
python3 tools/test-mca-strategy-build.py
```

Tests extract actual C functions. Power-supply/devres/workqueue APIs and SRCU
are host models; the DTPT route models synchronous delivery rather than the real
business queue. C tests use ASan/UBSan, with explicit ownership assertions;
LeakSanitizer is disabled. Makefile tests check registry-only, legacy SERVICES
and COMPLETE selections; they are not a full Kconfig or kernel build.

No full ARM64 build, modpost, image or device qualification was run for this
revision. The previous 463-module report applies to the previous revision.

## Integration boundaries

- `mca_strategy_ops_unregister(type, data)` must run outside callbacks, before
  freeing provider data. The data identity is checked and active readers are
  drained. Existing legacy providers still need explicit unregister/worker
  teardown integration; the FG strategy registry is a separate remaining task.
- A borrowed USB supply retains its owner's properties and callbacks. Reuse
  cannot add the business module's input-current setter to that owner. Nezha
  defers until the owner exists; it does not create a second supply.
- OVP/OCP errors preserve reported faults and request another sample. This is
  not a new hardware shutdown policy for unavailable telemetry. Thresholds,
  units, thermal handoff and buck/CP enforcement require separate qualification.
  IBAT monitoring remains parallel-battery-only. OVP permits the existing single
  FG 1S/2S enum values; no new board topology or voltage threshold is invented.
- Internal DTPT routing uses `MCA_EVENT_BATTERY_DTPT` throughout. Raw OEM 0x37
  must not be injected into this namespace: it is PLATE_SHOCK in the shared
  header. A verified boundary translator is required for raw stock messages.
- Unconditional smart-charge and diagnostic dependencies, FG providers,
  policy/board nodes and calibrated protection parameters remain unresolved.
  Do not enable all policies just to satisfy module-name parity with stock.
