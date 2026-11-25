# Wireless command application and retry

Parent kernel: `9a7946c166d3667c73a4912f97c7d42ed9866ab0`.

The voltage and current providers already return command errors through the
SC96281 and MCA/ADSP interfaces. Two callers incorrectly recorded an attempted
command as successful, allowing a transient failure to persist after the
transport recovered.

## Corrected behavior

- MCA ordinary elections retain the desired aggregate when a callback fails,
  but no longer mark it applied. The next vote recomputes the current aggregate
  and retries it, including an identical request. A newer restrictive vote
  takes precedence; an obsolete high-current request is not replayed. Explicit
  rerun failure also permits a later ordinary retry. Successful duplicates,
  override/force priority and the four election rules are retained. Invalid
  election types release the lock before returning an error.
- Seven wireless adapter profiles update their requested-voltage cache only
  after the required command sequence succeeds. The three ramped EPP profiles
  require a valid voltage sample, stop on failed writes, and clamp the last
  1 V step to the existing 11 V target. The train profile now requests that
  exact final voltage rather than its last loop variable.
- All seven profiles submit the current vote on each valid loop. The voter
  suppresses already-successful duplicates and retries failed applications.
  This is necessary even when the numerical current cache is unchanged: a
  voltage transition can require reapplication of the same current. A failed
  vote cannot update the successful-current cache.
- The EPP-plus high-SOC FCC one-shot flag is set only after both existing FCC
  votes succeed. Both legs are attempted and failures remain retryable.

Temperature thresholds, current/voltage targets, force-6 V and adapter-voltage
caps are retained. No hardware retry thread, emergency-limit bypass or
userspace thermal policy is added. Positive provider acknowledgement is not a
measurement of actual received power. Override activation/deactivation error
semantics and general MCA client lifetime are outside this change.

The companion manifest now pins modules commit
`c8a5bfa8d4d2f2377c411ac9a41f2dc9aa5edff8`, so a sync using this manifest
also retains the already-published CNSS rollback fix. Its former pin omitted
that latest commit. The devicetrees pin is unchanged.

## Validation

`test_mca_vote_retry.py` executes the production election and retry functions
for 271 cases. `test_wireless_profile_apply.py` executes the production profile
functions for 34 cases, including failed reads, each ramp write, cache recovery,
unchanged-current retries, and either FCC leg failing. Both use UBSan and both
reject their respective pre-change production source. The complete 19-script
native host regression suite and six paired CNSS/IPA suites pass.

The complete ARM64 Image and all 354 in-tree modules compile and link;
modpost succeeds with no unresolved-symbol warning. All 354 resulting `.ko`
files have ARM64 ELF headers and the same vermagic. The compiled thermal
provider/load-list checker passes for five QTI drivers, the board-temperature
bridge, and its MCA dependencies. CFI and MODVERSIONS are enabled. This host
Clang 19.1.7 qualification uses LTO_NONE and no Rust/BTF; it is not the
production Android r563880c build. The initial module attempt lacked host
`cpio`; installing the verified tool and rerunning the same target succeeded
without config changes. Full external-module modpost, final partition images
and device tests remain outstanding. Detailed hashes and per-module records
are in `wireless-apply-validation.json`.

Hardware wireless net charging remains open. The user's last device result was
charging indication with falling battery charge. This source change must not
be described as a verified fix for that entire symptom.
