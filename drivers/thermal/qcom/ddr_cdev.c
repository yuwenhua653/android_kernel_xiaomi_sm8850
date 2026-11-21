// SPDX-License-Identifier: GPL-2.0-only
/*
 * Copyright (c) 2020-2021, The Linux Foundation. All rights reserved.
 * Copyright (c) 2021-2023, Qualcomm Innovation Center, Inc. All rights reserved.
 * Native Canoe integration: referenced frequency table and managed lifetime.
 */
#include <linux/err.h>
#include <linux/interconnect.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/overflow.h>
#include <linux/platform_device.h>
#include <linux/slab.h>
#include <linux/thermal.h>

struct ddr_cdev {
	struct icc_path *path;
	u32 *bandwidth;
	unsigned long cur_state;
	unsigned long max_state;
};

static int ddr_get_max_state(struct thermal_cooling_device *cdev,
			     unsigned long *state)
{
	struct ddr_cdev *ddr = cdev->devdata;

	*state = ddr->max_state;
	return 0;
}

static int ddr_get_cur_state(struct thermal_cooling_device *cdev,
			     unsigned long *state)
{
	struct ddr_cdev *ddr = cdev->devdata;

	*state = ddr->cur_state;
	return 0;
}

static int ddr_set_cur_state(struct thermal_cooling_device *cdev,
			     unsigned long state)
{
	struct ddr_cdev *ddr = cdev->devdata;
	int ret;

	if (state > ddr->max_state)
		return -EINVAL;
	if (state == ddr->cur_state)
		return 0;

	ret = icc_set_bw(ddr->path, 0, ddr->bandwidth[state]);
	if (!ret)
		ddr->cur_state = state;
	return ret;
}

static const struct thermal_cooling_device_ops ddr_cdev_ops = {
	.get_max_state = ddr_get_max_state,
	.get_cur_state = ddr_get_cur_state,
	.set_cur_state = ddr_set_cur_state,
};

static int ddr_read_table(struct device *dev, struct ddr_cdev *ddr)
{
	struct device_node *table;
	u32 width;
	int count, i, ret;

	/* Canoe uses one phandle, not the legacy inline frequency array. */
	if (of_property_count_u32_elems(dev->of_node, "qcom,freq-table") != 1)
		return -EINVAL;
	table = of_parse_phandle(dev->of_node, "qcom,freq-table", 0);
	if (!table)
		return -EINVAL;

	count = of_property_count_u32_elems(table, "qcom,freq-tbl");
	if (count <= 0) {
		ret = count ? count : -EINVAL;
		goto put_table;
	}
	ddr->bandwidth = devm_kcalloc(dev, (size_t)count + 1,
				    sizeof(*ddr->bandwidth), GFP_KERNEL);
	if (!ddr->bandwidth) {
		ret = -ENOMEM;
		goto put_table;
	}
	ret = of_property_read_u32_array(table, "qcom,freq-tbl",
					&ddr->bandwidth[1], count);
put_table:
	of_node_put(table);
	if (ret)
		return ret;

	ret = of_property_read_u32(dev->of_node, "qcom,bus-width", &width);
	if (ret)
		return ret;
	if (!width)
		return -EINVAL;
	for (i = 1; i <= count; i++) {
		if (!ddr->bandwidth[i])
			return -EINVAL;
		if (check_mul_overflow(ddr->bandwidth[i], width,
				       &ddr->bandwidth[i]))
			return -EOVERFLOW;
	}
	/* State 0 has no vote. Other states retain the vendor BW semantics. */
	ddr->max_state = count;
	return 0;
}

static int ddr_cdev_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct thermal_cooling_device *cdev;
	struct ddr_cdev *ddr;
	int ret;

	ddr = devm_kzalloc(dev, sizeof(*ddr), GFP_KERNEL);
	if (!ddr)
		return -ENOMEM;
	ret = ddr_read_table(dev, ddr);
	if (ret)
		return dev_err_probe(dev, ret, "invalid referenced DDR frequency table\n");

	ddr->path = devm_of_icc_get(dev, NULL);
	if (IS_ERR(ddr->path))
		return dev_err_probe(dev, PTR_ERR(ddr->path), "DDR interconnect unavailable\n");
	if (!ddr->path)
		return dev_err_probe(dev, -ENODEV, "DDR interconnect missing\n");
	ret = icc_set_bw(ddr->path, 0, 0);
	if (ret)
		return dev_err_probe(dev, ret, "cannot initialize DDR bandwidth vote\n");

	/* LIFO devres: unregister cooling callbacks before icc_put clears BW. */
	cdev = devm_thermal_of_cooling_device_register(dev, dev->of_node,
						     "ddr-cdev", ddr, &ddr_cdev_ops);
	if (IS_ERR(cdev))
		return dev_err_probe(dev, PTR_ERR(cdev), "DDR cooling registration failed\n");
	dev_info(dev, "native DDR cooling ready: %lu states, initial vote 0\n",
		 ddr->max_state);
	return 0;
}

static const struct of_device_id ddr_cdev_match[] = {
	{ .compatible = "qcom,ddr-cooling-device" },
	{ }
};
MODULE_DEVICE_TABLE(of, ddr_cdev_match);

static struct platform_driver ddr_cdev_driver = {
	.probe = ddr_cdev_probe,
	.driver = {
		.name = "ddr_cdev",
		.of_match_table = ddr_cdev_match,
	},
};
module_platform_driver(ddr_cdev_driver);
MODULE_DESCRIPTION("Canoe DDR cooling device with referenced frequency table");
MODULE_LICENSE("GPL");
