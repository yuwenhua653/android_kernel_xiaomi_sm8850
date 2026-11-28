// SPDX-License-Identifier: GPL-2.0-only
/* Execute libbpf's real distillation and relocation with ambiguous composites. */
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include "btf.h"
#include "libbpf.h"

static void exercise(bool is_union, bool duplicate, bool different_size,
		     bool recursive, bool roundtrip, bool mixed_kind,
		     bool expect_old_failure)
{
	struct btf *base = btf__new_empty(), *split, *distilled, *out;
	const struct btf_type *p, *t;
	const struct btf_member *member;
	const void *raw;
	struct btf *parsed_base, *parsed_split;
	__u32 size;
	int first, second, link = 0, ret;

	assert(base);
	assert(btf__add_int(base, "int", 4, BTF_INT_SIGNED) == 1);
	first = (is_union != mixed_kind) ? btf__add_union(base, "file", 216) : btf__add_struct(base, "file", 216);
	assert(first == 2);
	assert(!btf__add_field(base, "first", 1, 0, 0));
	second = first;
	if (duplicate) {
		second = is_union ? btf__add_union(base, "file", different_size ? 224 : 216) :
			   btf__add_struct(base, "file", different_size ? 224 : 216);
		assert(second == 3);
		if (recursive) {
			assert(!btf__add_field(base, "next", 4, 0, 0));
			link = btf__add_ptr(base, second);
			assert(link == 4);
		} else {
			assert(!btf__add_field(base, "second", 1, is_union ? 0 : 32, 0));
		}
	}
	split = btf__new_empty_split(base);
	assert(split && btf__add_ptr(split, second) > 0);
	assert(!btf__distill_base(split, &distilled, &out));
	if (roundtrip) {
		raw = btf__raw_data(distilled, &size);
		assert(raw);
		parsed_base = btf__new(raw, size);
		assert(parsed_base);
		raw = btf__raw_data(out, &size);
		assert(raw);
		parsed_split = btf__new_split(raw, size, parsed_base);
		assert(parsed_split);
		btf__free(out);
		btf__free(distilled);
		out = parsed_split;
		distilled = parsed_base;
	}
	ret = btf__relocate(out, base);
	if (expect_old_failure && duplicate && !different_size) {
		assert(ret == -EINVAL);
	} else {
		assert(!ret);
		p = btf__type_by_id(out, btf__type_cnt(base));
		assert(p && btf_is_ptr(p));
		t = btf__type_by_id(out, p->type);
		assert(t && btf_kind(t) == (is_union ? BTF_KIND_UNION : BTF_KIND_STRUCT));
		assert(t->size == (different_size ? 224U : 216U));
		assert(!strcmp(btf__name_by_offset(out, t->name_off), "file"));
		assert(btf_vlen(t) == 1);
		member = btf_members(t);
		assert(!strcmp(btf__name_by_offset(out, member->name_off), recursive ? "next" :
			       duplicate ? "second" : "first"));
		if (recursive) {
			t = btf__type_by_id(out, member->type);
			assert(btf_is_ptr(t) && t->type == p->type);
		} else {
			assert(member->offset == (duplicate && !is_union ? 32U : 0U));
			assert(btf_is_int(btf__type_by_id(out, member->type)));
		}
	}
	btf__free(out);
	btf__free(distilled);
	btf__free(split);
	btf__free(base);
}

int main(int argc, char **argv)
{
	bool old = argc == 2 && !strcmp(argv[1], "--expect-old-failure");

	for (int kind = 0; kind < 2; kind++) {
		for (int roundtrip = 0; roundtrip < 2; roundtrip++) {
			exercise(kind, false, false, false, roundtrip, false, old);
			exercise(kind, true, false, false, roundtrip, false, old);
			exercise(kind, true, true, false, roundtrip, false, old);
			exercise(kind, true, false, true, roundtrip, false, old);
			exercise(kind, true, false, false, roundtrip, true, old);
		}
	}
	printf("PASS: 20 real libbpf distill/relocation cases (%s)\n", old ? "baseline reproduction" : "fixed");
}
