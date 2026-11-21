// SPDX-License-Identifier: GPL-2.0-only
/*
 * Based on Qualcomm's qti-ocp-notifier.c:
 * Copyright (c) 2022-2023 Qualcomm Innovation Center, Inc. All rights reserved.
 * Native integration: retained regulator references, serialized cache access,
 * and devres ordering that stops IRQ handlers before releasing the cache.
 */
#include <linux/err.h>
#include <linux/idr.h>
#include <linux/interrupt.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/nvmem-consumer.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/regulator/consumer.h>
#include <linux/regulator/driver.h>
#include <linux/slab.h>
#include "internal.h"

#define OCP_ENTRY_SIZE 2
/* The reviewed PMK8850 cells contain three entries; bound malformed data. */
#define OCP_MAX_LOG_BYTES 256

struct ocp_notifier;
struct ocp_log {
	struct ocp_notifier *owner;
	struct nvmem_cell *cell;
	const char *name;
	unsigned long event;
	int irq;
};

struct ocp_notifier {
	struct device *dev;
	struct mutex lock;
	struct idr regulators;
	struct ocp_log logs[2];
};

static int ocp_decode(const u8 *data, size_t len, size_t index,
		      u16 *ppid, u8 *mode)
{
	if (!len || len > OCP_MAX_LOG_BYTES || len % OCP_ENTRY_SIZE ||
	    index >= len / OCP_ENTRY_SIZE)
		return -EINVAL;
	*ppid = ((u16)(data[index * 2] & 0xf0) << 4) | data[index * 2 + 1];
	*mode = data[index * 2] & 0x7;
	return 0;
}

/* Hold consumer handles until all IRQs have been freed; never cache a bare
 * rdev after regulator_put(). This driver casts no enable/voltage/load votes.
 */
static struct regulator *ocp_get_regulator(struct ocp_notifier *ocp, u16 ppid)
{
	struct regulator *reg;
	char supply[16];
	int ret;

	mutex_lock(&ocp->lock);
	reg = idr_find(&ocp->regulators, ppid);
	if (reg)
		goto out;
	snprintf(supply, sizeof(supply), "periph-%03x", ppid);
	reg = regulator_get_optional(ocp->dev, supply);
	if (IS_ERR(reg))
		goto out;
	ret = idr_alloc(&ocp->regulators, reg, ppid, ppid + 1, GFP_KERNEL);
	if (ret < 0) {
		regulator_put(reg);
		reg = ERR_PTR(ret);
	}
out:
	mutex_unlock(&ocp->lock);
	return reg;
}

static int ocp_process_entry(struct ocp_log *log, const u8 *data, size_t len,
			     size_t index, bool notify)
{
	struct ocp_notifier *ocp = log->owner;
	struct regulator *reg;
	u16 ppid;
	u8 mode;
	int ret;

	ret = ocp_decode(data, len, index, &ppid, &mode);
	if (ret || !ppid)
		return ret;
	reg = ocp_get_regulator(ocp, ppid);
	if (IS_ERR(reg)) {
		ret = PTR_ERR(reg);
		/* An unmapped PPID is still a valid event worth recording. */
		if (ret != -ENODEV)
			return ret;
		dev_warn_ratelimited(ocp->dev, "%s %s ppid=0x%03x mode=%u (unmapped)\n",
				     log->name, notify ? "runtime" : "boot", ppid, mode);
		return 0;
	}
	dev_warn_ratelimited(ocp->dev, "%s %s ppid=0x%03x mode=%u\n",
			     log->name, notify ? "runtime" : "boot", ppid, mode);
	if (notify)
		regulator_notifier_call_chain(reg->rdev, log->event, NULL);
	return 0;
}

static int ocp_read_log(struct ocp_log *log, bool notify)
{
	size_t len, i, entries;
	u8 *data;
	int ret = 0;

	data = nvmem_cell_read(log->cell, &len);
	if (IS_ERR(data))
		return PTR_ERR(data);
	if (!len || len > OCP_MAX_LOG_BYTES || len % OCP_ENTRY_SIZE) {
		ret = -EINVAL;
		goto out;
	}
	/* The firmware keeps the latest runtime event in entry zero. */
	entries = notify ? 1 : len / OCP_ENTRY_SIZE;
	for (i = 0; i < entries; i++) {
		ret = ocp_process_entry(log, data, len, i, notify);
		if (ret)
			break;
	}
out:
	kfree(data);
	return ret;
}

static irqreturn_t ocp_irq(int irq, void *data)
{
	struct ocp_log *log = data;
	int ret = ocp_read_log(log, true);

	if (ret)
		dev_err_ratelimited(log->owner->dev, "%s event read failed: %d\n",
				    log->name, ret);
	return IRQ_HANDLED;
}

static void ocp_release_regulators(void *data)
{
	struct ocp_notifier *ocp = data;
	struct regulator *reg;
	int id;

	/* Registered before IRQ resources, so devres frees/synchronizes every
	 * IRQ first, on both probe failure and driver unbind.
	 */
	idr_for_each_entry(&ocp->regulators, reg, id)
		regulator_put(reg);
	idr_destroy(&ocp->regulators);
}

static int ocp_notifier_probe(struct platform_device *pdev)
{
	static const char * const names[] = { "ocp_log", "alarm_log" };
	static const unsigned long events[] = {
		REGULATOR_EVENT_OVER_CURRENT, REGULATOR_EVENT_UNDER_VOLTAGE,
	};
	struct device *dev = &pdev->dev;
	struct ocp_notifier *ocp;
	int i, ret;

	ocp = devm_kzalloc(dev, sizeof(*ocp), GFP_KERNEL);
	if (!ocp)
		return -ENOMEM;
	ocp->dev = dev;
	mutex_init(&ocp->lock);
	idr_init(&ocp->regulators);
	ret = devm_add_action_or_reset(dev, ocp_release_regulators, ocp);
	if (ret)
		return ret;
	/* Resolve both sources and scan boot logs before enabling either IRQ. */
	for (i = 0; i < ARRAY_SIZE(ocp->logs); i++) {
		struct ocp_log *log = &ocp->logs[i];

		log->owner = ocp;
		log->name = names[i];
		log->event = events[i];
		log->cell = devm_nvmem_cell_get(dev, names[i]);
		if (IS_ERR(log->cell)) {
			ret = PTR_ERR(log->cell);
			/* The alarm is optional only when not described by DT. */
			if (i == 1 && of_property_match_string(dev->of_node,
					"nvmem-cell-names", names[i]) < 0 &&
			    (ret == -ENOENT || ret == -ENODEV)) {
				log->cell = NULL;
				continue;
			}
			return dev_err_probe(dev, ret, "%s unavailable\n", names[i]);
		}
		log->irq = platform_get_irq(pdev, i);
		if (log->irq < 0)
			return log->irq;
		ret = ocp_read_log(log, false);
		if (ret)
			return dev_err_probe(dev, ret, "%s boot log failed\n", names[i]);
	}
	for (i = 0; i < ARRAY_SIZE(ocp->logs); i++) {
		struct ocp_log *log = &ocp->logs[i];

		if (!log->cell)
			continue;
		ret = devm_request_threaded_irq(dev, log->irq, NULL, ocp_irq,
						IRQF_ONESHOT, names[i], log);
		if (ret)
			return dev_err_probe(dev, ret, "%s IRQ failed\n", names[i]);
	}
	dev_info(dev, "native OCP/alarm notifications ready\n");
	return 0;
}

static const struct of_device_id ocp_notifier_match[] = {
	{ .compatible = "qcom,regulator-ocp-notifier" },
	{ }
};
MODULE_DEVICE_TABLE(of, ocp_notifier_match);

static struct platform_driver ocp_notifier_driver = {
	.probe = ocp_notifier_probe,
	.driver = {
		.name = "qti-ocp-notifier",
		.of_match_table = ocp_notifier_match,
	},
};
module_platform_driver(ocp_notifier_driver);
MODULE_DESCRIPTION("QTI OCP/alarm notifier with retained regulator references");
MODULE_LICENSE("GPL");
