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
  teardown integration. The follow-up below adds the FG registry and bridge.
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
- Unconditional smart-charge and diagnostic dependencies, full FG policy features,
  policy/board nodes and calibrated protection parameters remain unresolved.
  Do not enable all policies just to satisfy module-name parity with stock.

## Follow-up: read-only BQ27Z561 bridge

`CONFIG_XIAOMI_MCA_STRATEGY_CLASS=m` and `CONFIG_XIAOMI_MCA_NEZHA_FG_PSY=m`
now build/load two registries and the read-only bridge. The DT supplier is the
existing `ti,bq27z561` at 0x55, identified by phandle, not a global supply name.
No policy, protection threshold, authentication or charger write is enabled.
The bridge uses Linux BQ current sign/units and the existing MCA consumer units:
positive BQ charging becomes negative MCA uA; voltage uV becomes mV; temperature
remains deci-C and capacity remains uAh. Unsupported properties remain errors.
The legacy charging_done bool API returns false for unknown/error, never true.

`strategy_class_fg_ops_unregister(data)` drains callbacks before freeing data.
Only the new bridge integrates it in this revision. Existing full FG providers
must adopt it before enabling unload/rebind. Do not call unregister inside a
callback. Get-model-name providers must retain the returned string for callers.

Run `python3 tools/test-nezha-fg-psy.py` in addition to the six commands above.
This tests actual dispatch and bridge functions, including supplier absence,
devres unwind, units/sign, unsupported operations and concurrent unregister.
The SRCU/devres/I2C APIs are host models, not a replacement for a kernel build.
