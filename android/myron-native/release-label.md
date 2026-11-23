# Myron release label

The requested format is the real kernel version, the normal SCM version,
and a final `-yuzuli`, for example `6.12.118-g0123456789ab-yuzuli`.
Annotated version tags can suppress the SCM suffix or add a commit count,
following the existing `scm_version` implementation.

Only `CONFIG_TARGET_PRODUCT_MYRON=y` activates this policy. The persistent
Myron config fragment selects an empty CONFIG_LOCALVERSION and enables
CONFIG_LOCALVERSION_AUTO. scripts/setlocalversion uses its existing
`--no-dirty` helper for Myron, then adds the final owner label. Non-Myron
configurations and `--no-local` keep their existing behavior.

Omitting `dirty` from the displayed release does not make local source clean.
The real Git HEAD is retained; the integration package preserves existing
changes and records original file hashes and the worktree status in backups.
It does not automatically commit, reset or discard user changes.

Do not hard-code KERNELRELEASE in a build wrapper. Clear any old LOCALVERSION
or KERNELRELEASE environment override and use the normal ROM build. Changing
the release changes module vermagic: rebuild boot, vendor_boot, recovery,
system_dlkm and vendor_dlkm as one set, with dependent images and vbmeta.
Old modules must not be mixed with the newly named kernel.

Validation: `python3 android/myron-native/tests/test_release_label.py`
checks actual Git repositories, clean and dirty trees, changing HEAD,
annotated tags, non-Myron configurations and --no-local. This is release
logic validation; it is not a new full-image or device qualification.
