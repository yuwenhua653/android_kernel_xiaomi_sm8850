// SPDX-License-Identifier: GPL-2.0-only
/*
 * Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
 * Native integration of the Qualcomm CPUSS telemetry shared-memory protocol.
 */
#include <linux/debugfs.h>
#include <linux/io.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/qcom_scmi_vendor.h>
#include <linux/scmi_protocol.h>
#include <linux/seq_file.h>
#include <linux/slab.h>
#include <soc/qcom/cpuss_telemetry.h>

#define SCMI_TELEMETRY_ALGO_STR 0x454c454d45545259ULL
#define TELEMETRY_MAX_COUNTERS 4096
#define TELEMETRY_READ_RETRIES 1024

struct cpuss_telemetry {
	void __iomem *header;
	void __iomem *names;
	void __iomem *values;
	u32 count;
	const struct qcom_scmi_vendor_ops *ops;
	struct scmi_protocol_handle *ph;
	struct dentry *dir;
};

static DEFINE_MUTEX(telemetry_lock);
static struct cpuss_telemetry *active;

/* Never spin forever if firmware leaves its sequence odd or keeps updating. */
static s64 telemetry_read(struct cpuss_telemetry *t, u32 id)
{
	u64 before, after;
	s64 value;
	unsigned int retry;

	if (id >= t->count)
		return -ERANGE;
	for (retry = 0; retry < TELEMETRY_READ_RETRIES; retry++) {
		before = readq(t->header + offsetof(struct telemetry_global_param_t,
						   match_sequence));
		if (before & 1) {
			cpu_relax();
			continue;
		}
		rmb();
		value = readq(t->values + id * sizeof(struct telemetry_counter_attributes_value_t));
		rmb();
		after = readq(t->header + offsetof(struct telemetry_global_param_t,
						  match_sequence));
		if (before == after)
			return value == -1 ? -ENODATA : value;
		cpu_relax();
	}
	return -EAGAIN;
}

s64 get_telemetry_counter_value(u32 id)
{
	s64 value;

	mutex_lock(&telemetry_lock);
	value = active ? telemetry_read(active, id) : -ENODEV;
	mutex_unlock(&telemetry_lock);
	return value;
}
EXPORT_SYMBOL_GPL(get_telemetry_counter_value);

static int counter_info_show(struct seq_file *s, void *unused)
{
	struct cpuss_telemetry *t = s->private;
	char name[MAX_NAME_LENGTH + 1];
	u32 i;

	seq_puts(s, "ID name value\n");
	for (i = 0; i < t->count; i++) {
		s64 value = telemetry_read(t, i);

		memcpy_fromio(name, t->names + i * MAX_NAME_LENGTH, MAX_NAME_LENGTH);
		name[MAX_NAME_LENGTH] = '\0';
		if (value < 0)
			seq_printf(s, "%u %s error=%lld\n", i, name, value);
		else
			seq_printf(s, "%u %s %lld\n", i, name, value);
	}
	return 0;
}
DEFINE_SHOW_ATTRIBUTE(counter_info);

static int telemetry_update(void *data, u64 value)
{
	struct cpuss_telemetry *t = data;

	if (!value)
		return -EINVAL;
	return t->ops->set_param(t->ph, &value, SCMI_TELEMETRY_ALGO_STR,
				SET_PARAM_REQUEST_UPDATE, sizeof(value));
}
DEFINE_DEBUGFS_ATTRIBUTE(update_fops, NULL, telemetry_update, "%llu\n");

static void telemetry_unmap(struct cpuss_telemetry *t)
{
	if (t->values)
		iounmap(t->values);
	if (t->names)
		iounmap(t->names);
	if (t->header)
		iounmap(t->header);
}

static int scmi_cpuss_telemetry_probe(struct scmi_device *sdev)
{
	struct cpuss_telemetry *t;
	u64 address = 0, names, values;
	int ret;

	if (!sdev->handle)
		return -EPROBE_DEFER;
	t = devm_kzalloc(&sdev->dev, sizeof(*t), GFP_KERNEL);
	if (!t)
		return -ENOMEM;
	t->ops = sdev->handle->devm_protocol_get(sdev, sdev->protocol_id, &t->ph);
	if (IS_ERR(t->ops))
		return PTR_ERR(t->ops);
	ret = t->ops->get_param(t->ph, &address, SCMI_TELEMETRY_ALGO_STR,
				0, 0, sizeof(address));
	if (ret)
		return ret;
	if (!address || !IS_ALIGNED(address, sizeof(u64)))
		return -EINVAL;
	t->header = ioremap_cache(address, sizeof(struct telemetry_global_param_t));
	if (!t->header)
		return -ENOMEM;
	t->count = readl(t->header + offsetof(struct telemetry_global_param_t, num_max_counters));
	names = readq(t->header + offsetof(struct telemetry_global_param_t, pname));
	values = readq(t->header + offsetof(struct telemetry_global_param_t, pvalue));
	if (!t->count || t->count > TELEMETRY_MAX_COUNTERS || !names || !values ||
	    !IS_ALIGNED(values, sizeof(u64))) {
		ret = -EINVAL;
		goto unmap;
	}
	/* Map arrays by element size, not by the size of a pointer. */
	t->names = ioremap_cache(names, t->count * sizeof(struct telemetry_counter_attributes_name_t));
	t->values = ioremap_cache(values, t->count * sizeof(struct telemetry_counter_attributes_value_t));
	if (!t->names || !t->values) {
		ret = -ENOMEM;
		goto unmap;
	}
	mutex_lock(&telemetry_lock);
	if (active) {
		ret = -EBUSY;
		mutex_unlock(&telemetry_lock);
		goto unmap;
	}
	t->dir = debugfs_create_dir("cpuss_telemetry", NULL);
	if (IS_ERR_OR_NULL(t->dir)) {
		ret = t->dir ? PTR_ERR(t->dir) : -ENOMEM;
		mutex_unlock(&telemetry_lock);
		goto unmap;
	}
	debugfs_create_file("counter_info", 0400, t->dir, t, &counter_info_fops);
	debugfs_create_file("stat_update", 0200, t->dir, t, &update_fops);
	active = t;
	dev_set_drvdata(&sdev->dev, t);
	mutex_unlock(&telemetry_lock);
	return 0;
unmap:
	telemetry_unmap(t);
	return ret;
}

static void scmi_cpuss_telemetry_remove(struct scmi_device *sdev)
{
	struct cpuss_telemetry *t = dev_get_drvdata(&sdev->dev);

	/* debugfs proxy operations drain before their mapped memory is removed. */
	debugfs_remove_recursive(t->dir);
	mutex_lock(&telemetry_lock);
	if (active == t)
		active = NULL;
	telemetry_unmap(t);
	mutex_unlock(&telemetry_lock);
}

static const struct scmi_device_id scmi_id_table[] = {
	{ QCOM_SCMI_VENDOR_PROTOCOL, "cpuss_telemetry_vendor" },
	{ }
};
MODULE_DEVICE_TABLE(scmi, scmi_id_table);

static struct scmi_driver scmi_cpuss_telemetry_driver = {
	.name = "scmi-cpuss-telemetry-driver",
	.probe = scmi_cpuss_telemetry_probe,
	.remove = scmi_cpuss_telemetry_remove,
	.id_table = scmi_id_table,
};
module_scmi_driver(scmi_cpuss_telemetry_driver);
MODULE_DESCRIPTION("QTI SCMI CPUSS telemetry with bounded reads");
MODULE_LICENSE("GPL");
