// SPDX-License-Identifier: GPL-2.0
/*
 * hl7603.c
 *
 * boost bypass ic driver
 *
 * Copyright (c) 2023-2023 Xiaomi Technologies Co., Ltd.
 *
 * This software is licensed under the terms of the GNU General Public
 * License version 2, as published by the Free Software Foundation, and
 * may be copied, distributed, and modified under those terms.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
 * GNU General Public License for more details.
 *
 */
#include <mca/common/mca_log.h>
#include <mca/common/mca_event.h>
#include <mca/common/mca_parse_dts.h>
#include <mca/common/mca_sysfs.h>
#include <mca/common/mca_panel.h>
#include <linux/string.h>
#include <linux/device.h>
#include <linux/kernel.h>
#include <linux/i2c.h>
#include "inc/hl7603.h"

#ifndef MCA_LOG_TAG
#define MCA_LOG_TAG "boost_hl7603"
#endif

#define VOUT_THRSHOLD_DEFAULT 3400

static int hl7603_set_voltage_threshold(struct boost_bypass_dev *info,
					u32 vout_threshold);

static int hl7603_parse_dt(struct boost_bypass_dev *info)
{
	struct device_node *np = info->dev->of_node;

	if (!np) {
		mca_log_err("device tree info missing\n");
		return -EINVAL;
	}
	mca_parse_dts_u32(np, "vout_threshold", &(info->vout_threshold),
			  VOUT_THRSHOLD_DEFAULT);
	info->suport_hbm = of_property_read_bool(np, "support_hbm");
	if (info->suport_hbm)
		mca_parse_dts_u32(np, "hbm_vout_threshold",
				  &(info->hbm_vout_threshold),
				  VOUT_THRSHOLD_DEFAULT);

	return 0;
}

static int hl7603_set_voltage_threshold(struct boost_bypass_dev *info,
					u32 vout_threshold)
{
	int val;
	int ret;

	if ((vout_threshold > VOUT_REG_MAX) || vout_threshold < VOUT_REG_BASE ||
	    (vout_threshold - VOUT_REG_BASE) % VOUT_REG_STEP) {
		mca_log_err("vout_threshold no valid %d", info->vout_threshold);
		return -EINVAL;
	}
	val = (vout_threshold - VOUT_REG_BASE) / VOUT_REG_STEP;

	ret = i2c_smbus_write_byte_data(info->client, VOUT_REG, val);
	if (ret < 0) {
		mca_log_err("i2c write reg 0x%02X failed\n", VOUT_REG);
		return ret;
	}
	val = i2c_smbus_read_byte_data(info->client, VOUT_REG);
	if (val < 0)
		return val;
	mca_log_info("i2c read reg [0x%02X]=[%d]\n", VOUT_REG, val);

	return ret;
}

static int hl7603_panel_notifier_cb(struct notifier_block *nb,
				    unsigned long event, void *val)
{
	struct boost_bypass_dev *info =
		container_of(nb, struct boost_bypass_dev, panel_nb);

	switch (event) {
	case MCA_EVENT_PANEL_HBM_STATE_CHANGE:
		if (info->suport_hbm && val)
			hl7603_set_voltage_threshold(
				info, *(int *)val ? info->hbm_vout_threshold :
						    info->vout_threshold);
		break;
	default:
		break;
	}

	return NOTIFY_DONE;
}

static int hl7603_probe(struct i2c_client *client)
{
	int ret;
	struct boost_bypass_dev *info;

	if (!i2c_check_functionality(client->adapter, I2C_FUNC_SMBUS_BYTE_DATA))
		return -EOPNOTSUPP;

	mca_log_info("%s start probe\n", __func__);
	info = devm_kzalloc(&client->dev, sizeof(*info), GFP_KERNEL);
	if (!info)
		return -ENOMEM;

	info->client = client;
	info->dev = &client->dev;
	i2c_set_clientdata(client, info);
	ret = hl7603_parse_dt(info);
	if (ret)
		return ret;
	ret = hl7603_set_voltage_threshold(info, info->vout_threshold);
	if (ret) {
		mca_log_err("failed to init hl7603\n");
		return ret;
	}

	if (info->suport_hbm) {
		info->panel_nb.notifier_call = hl7603_panel_notifier_cb;
		ret = mca_event_block_notify_register(MCA_EVENT_TYPE_PANEL,
						  &info->panel_nb);
		if (ret)
			return ret == -1 ? -EPROBE_DEFER : ret;
	}

	mca_log_info("probe success\n");
	return 0;
}

static void hl7603_remove(struct i2c_client *client)
{
	struct boost_bypass_dev *info = i2c_get_clientdata(client);

	if (info->suport_hbm)
		mca_event_block_notify_unregister(MCA_EVENT_TYPE_PANEL,
						  &info->panel_nb);
}

static const struct of_device_id hl7603_of_match[] = {
	{ .compatible = "hl7603" },
	{},
};

MODULE_DEVICE_TABLE(of, hl7603_of_match);

static struct i2c_driver hl7603_driver = {
	.driver = {
		.name = "hl7603_boost_bypass",
		.of_match_table = hl7603_of_match,
	},
	.probe = hl7603_probe,
	.remove = hl7603_remove,
};
module_i2c_driver(hl7603_driver);

MODULE_AUTHOR("lvxiaofeng <lvxiaofeng@xiaomi.com>");
MODULE_DESCRIPTION("hl7603 boot_bypass driver");
MODULE_LICENSE("GPL v2");
