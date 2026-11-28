# Preserve ambiguous composite BTF definitions

Parent: d0815ed04a4f96571702787561df121f45004f7c (lineage-24.0).

The submitted b5ed8bcc runtime reports two base BTF candidates for `file`,
size 216. This is a distilled-base relocation ambiguity, not evidence of a
module vermagic or symbol ABI failure. The source already excludes Rust from
pahole where supported; do not claim that simply adding that option fixes this.

The host libbpf distiller used by resolve_btfids now indexes named base
structs/unions by name and size. Ambiguous composites and their dependencies
remain complete in the module's split BTF, following the existing anonymous
composite treatment. Unambiguous types keep the previous distilled form.
The relocation validator is unchanged; it must still reject genuinely
ambiguous distilled input. BTF, Rust and CONFIG_MODULE_ALLOW_BTF_MISMATCH are
not disabled or loosened.

Detect the destination by `base_btf == NULL`, as current upstream
[libbpf](https://github.com/libbpf/libbpf/blob/master/src/btf.c) does, rather than
`start_id == 1`: a split BTF can also start at 1 when its distilled base only
contains void. Self-recursive composites exercise this case.

Makefile.modfinal also tracks resolve_btfids and gen-btf.sh as prerequisites
when module BTF is enabled, so an incremental build regenerates module BTF
after host-tool changes. No ROM-wide build rules are modified.

## Validation

- The unmodified library reproduces the same `file`, size 216 ambiguity.
- The corrected production library passes 20 distill/relocation cases: struct,
  union, unique names, same-name different sizes, ambiguous same sizes,
  recursive references with an empty distilled base, mixed struct/union names,
  and raw serialization/reparse before relocation. Members, offsets and
  recursive pointer identities are checked. The harness uses host GCC/UBSan;
  the library itself was built with the normal host flags.
- The actual tools/bpf/resolve_btfids executable builds successfully with
  GCC, libelf and zlib on x86_64.
- test_btf_rebuild.py uses GNU make with the production prerequisite rule to
  check that tool/script timestamps trigger rebuilds only with BTF enabled.
- git diff --check passes. Checkpatch reports no errors or warnings for the
  production diff; style checks retain the existing btf_is_composite pattern
  and the upstream NULL comparison style.

Reproduce on a host with libelf/zlib development packages, from the kernel root:

```sh
mkdir -p /tmp/myron-btf-host
make -C tools/bpf/resolve_btfids OUTPUT=/tmp/myron-btf-host/ -j4
cc -g -O1 -fsanitize=undefined -I tools/lib/bpf -I tools/include/uapi \
  android/myron-native/tests/test_btf_ambiguous.c \
  /tmp/myron-btf-host/libbpf/libbpf.a -lelf -lz -o /tmp/myron-btf-test
/tmp/myron-btf-test
python3 android/myron-native/tests/test_btf_rebuild.py
```

No full ARM64 kernel/module image build or phone test has been performed for
this change. The exact phone BTF objects have not been captured; the regression
reproduces their reported failure class. Rebuild kernel and dependent modules
as a matched set, then confirm the mismatch is absent in the next boot log.
Preserving complete types can increase individual module BTF size; measure
actual output sizes during the full build. This is not a general ABI guarantee.
