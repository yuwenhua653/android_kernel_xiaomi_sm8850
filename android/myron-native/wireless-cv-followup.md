# Wireless constant-voltage and PMIC recovery follow-up

## Corrected source decisions

The periodic basic-wireless monitor previously treated a failed quick-charge
status query as ordinary charging, and consumed an uninitialized PMIC status
when its provider failed. A negative charge-enable vote also counted as true.
Recovery now requires a successful quick-charge status, no input-suspend vote,
a positive charge-enable result and a successful PMIC disabled-state sample.
The enable step follows only a successful disable step; a failed operation is
reported instead of announcing recovery. The normal retry schedule remains.

Starting/stopping software constant-voltage control now uses a freshly read,
positive battery voltage and valid terminal-voltage/charge-enable votes. An
unavailable reading does not turn a stale cached voltage into a new decision.
The already-full-stage stop remains independent of this sample, as before.

Both ordinary and conditional base/flip software CV workers now validate their
voltage/current samples and votes before updating cached values or requesting
current/terminal-voltage changes. A failed pair leaves both cached samples and
existing votes intact, then retries on the existing normal interval. The
base/flip path also checks fast-charge and first-termination providers. This
path is conditional on the board feature; no claim is made that Myron enables
it on the current phone.

Current negation rejects INT_MIN, low current votes cannot produce a negative
FCC decrement, and terminal-voltage compensation uses a 64-bit intermediate
with a positive-int output check before the hardware call. The base/flip
counter saturates at the existing five-step maximum rather than continuing to
increment after the hardware decrement already reached its cap. Normal
charging thresholds, compensation settings, step sizes and valid-sample
behavior remain unchanged.

## Verification

`tests/test_wireless_cv_samples.py --kernel-root <kernel>` executes the three
production C workers with mocked providers and records their hardware/vote
calls. **50 cases** pass under UBSan, including failed/invalid status, failed
PMIC disable/enable steps, fresh-versus-cached voltage, failed current,
missing votes, failed first-termination, zero/negative voltage, signed current
bounds, negative-FCC prevention, oversized compensation, counter saturation,
unchanged valid actions and recovery after an unsuccessful sample.

The preceding monitor and CV functions each fail their corresponding negative
control. The previous **539** sample/reference and **874** alarm/FFC/profile
cases continue to pass. The modified ARM64 object compiles with Clang 19.1.7,
CFI and MODVERSIONS; C checkpatch reports zero errors/warnings.

This is not a full Image/external-module modpost/ROM build or device result.
Successful hardware setters, actual thermal policy behavior and net wireless
charge gain remain unverified. Existing boot, board-temperature and queue
corrections remain included. No charging threshold, DT table, shared ROM source
or libperfmgr integration is changed.

## Corrected interpretation of the older GLINK error

In the current source `MCA_ADSP_GLINK_OWNER` is `0x800A`, i.e. **32778**, and
`mca_adsp_glink_probe()` registers that ID with the QTI PMIC GLINK router.
The router dispatches by exact owner ID. The Myron DT enables the MCA node
under the matching `qcom,qti-pmic-glink` parent, and MCA services select the
module. Consequently the old `No client present for 32778` message must be
correlated with MCA probe/link timing and the message opcode. It is not
sufficient evidence to enable an unrelated ADC/debug driver.

The tree's separate upstream `pmic_pdcharger_ulog` driver also defines 32778
for its own transport/protocol. That reinforces why an owner number by itself
cannot identify the required firmware client. It is not enabled by this patch.
The unused QBG export path references owner `0x8009`, but has no tracked caller
in the MCA tree; no additional client was enabled solely to populate a checklist.

Remaining work still includes matching the actual ROM thermal HAL's skin
sensor mapping and validating active policy controls. Those are separate from
these reproduced source failures; a missing optional module name alone is not
an adaptation defect.
