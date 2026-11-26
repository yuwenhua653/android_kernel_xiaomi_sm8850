/* SPDX-License-Identifier: GPL-2.0-only */
/* Myron/Nezha six-column FOD contract. Calibration bytes are never synthesized. */
#ifndef SC96281_MYRON_DT_H
#define SC96281_MYRON_DT_H

static int sc96281_myron_parse_table(struct device_node *node, const char *prop,
				    fod_params_t *rows, int capacity)
{
	const char *s, *names[3];
	u8 data[3][DEFAULT_FOD_PARAM_LEN * 2];
	u32 uuid;
	int count, i, j, k, ret;

	count = of_property_count_strings(node, prop);
	if (count <= 0 || count % 6 || count / 6 > capacity)
		return -EINVAL;
	for (i = 0; i < count / 6; i++) {
		ret = of_property_read_string_index(node, prop, i * 6, &s);
		if (ret || kstrtou8(s, 10, &rows[i].type) || rows[i].type != 0)
			return -EINVAL;
		ret = of_property_read_string_index(node, prop, i * 6 + 1, &s);
		if (ret || kstrtou8(s, 10, &rows[i].length) ||
		    rows[i].length != DEFAULT_FOD_PARAM_LEN)
			return -EINVAL;
		ret = of_property_read_string_index(node, prop, i * 6 + 2, &s);
		if (ret || kstrtou32(s, 16, &uuid))
			return -EINVAL;
		rows[i].uuid = uuid;
		for (j = 0; j < i; j++)
			if ((u32)rows[j].uuid == uuid)
				return -EINVAL;
		for (j = 0; j < 3; j++) {
			ret = of_property_read_string_index(node, prop, i * 6 + 3 + j, &names[j]);
			if (ret || of_property_count_u8_elems(node, names[j]) != sizeof(data[j]))
				return -EINVAL;
			ret = of_property_read_u8_array(node, names[j], data[j], sizeof(data[j]));
			if (ret)
				return ret;
		}
		/* This board has equal thin/thick magnetic calibration. Do not guess
		 * a case category on Myron. Nezha uses the stock dual-Hall mapping. */
		if (!IS_ENABLED(CONFIG_TARGET_PRODUCT_NEZHA) &&
		    memcmp(data[1], data[2], sizeof(data[1])))
			return -EINVAL;
		for (k = 0; k < DEFAULT_FOD_PARAM_LEN; k++) {
			rows[i].params[k].gain = data[0][2*k];
			rows[i].params[k].offset = data[0][2*k+1];
			rows[i].params_mag[k].gain = data[1][2*k];
			rows[i].params_mag[k].offset = data[1][2*k+1];
			rows[i].params_mag_thick[k].gain = data[2][2*k];
			rows[i].params_mag_thick[k].offset = data[2][2*k+1];
		}
	}
	return count / 6;
}
#endif
