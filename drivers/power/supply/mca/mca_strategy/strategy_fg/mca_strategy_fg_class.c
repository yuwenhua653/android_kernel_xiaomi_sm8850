// SPDX-License-Identifier: GPL-2.0
/*
 *mca_strategy_fg_class.c
 *
 * mca fuelgauge strategy class driver
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
#include <linux/module.h>
#include <linux/platform_device.h>
#include <linux/mutex.h>
#include <linux/slab.h>
#include <linux/srcu.h>
#include <mca/strategy/strategy_fg_class.h>

struct mca_fg_entry {
	void *data;
	struct strategy_fg_class_ops ops;
};

static struct mca_fg_entry __rcu *fg_entry;
static DEFINE_MUTEX(fg_lock);
DEFINE_STATIC_SRCU(fg_srcu);

int strategy_class_fg_ops_register(void *data, struct strategy_fg_class_ops *ops)
{
	struct mca_fg_entry *entry;
	int ret = 0;

	if (!data || !ops)
		return -EINVAL;
	entry = kzalloc(sizeof(*entry), GFP_KERNEL);
	if (!entry)
		return -ENOMEM;
	entry->data = data;
	entry->ops = *ops;
	mutex_lock(&fg_lock);
	if (rcu_access_pointer(fg_entry))
		ret = -EBUSY;
	else
		rcu_assign_pointer(fg_entry, entry);
	mutex_unlock(&fg_lock);
	if (ret)
		kfree(entry);
	return ret;
}
EXPORT_SYMBOL(strategy_class_fg_ops_register);

/* Provider must unregister before releasing callback data or code.
 * Do not invoke this from an FG callback: synchronize_srcu() would deadlock.
 */
int strategy_class_fg_ops_unregister(void *data)
{
	struct mca_fg_entry *entry;

	if (!data)
		return -EINVAL;
	mutex_lock(&fg_lock);
	entry = rcu_access_pointer(fg_entry);
	if (!entry || entry->data != data) {
		mutex_unlock(&fg_lock);
		return -ENOENT;
	}
	RCU_INIT_POINTER(fg_entry, NULL);
	mutex_unlock(&fg_lock);
	synchronize_srcu(&fg_srcu);
	kfree(entry);
	return 0;
}
EXPORT_SYMBOL(strategy_class_fg_ops_unregister);

int strategy_class_fg_ops_is_init_ok(void)
{
	struct mca_fg_entry *entry;
	int idx;
	int ret;

	idx = srcu_read_lock(&fg_srcu);
	entry = srcu_dereference(fg_entry, &fg_srcu);
	ret = !entry ? -ENODEV : !entry->ops.strategy_fg_is_init_ok ?
		-EOPNOTSUPP : entry->ops.strategy_fg_is_init_ok(entry->data);
	srcu_read_unlock(&fg_srcu, idx);
	return ret;
}
EXPORT_SYMBOL(strategy_class_fg_ops_is_init_ok);

int strategy_class_fg_ops_get_rsoc(int *rsoc)
{
	struct mca_fg_entry *entry;
	int idx;
	int ret;

	if (!rsoc)
		return -EINVAL;
	idx = srcu_read_lock(&fg_srcu);
	entry = srcu_dereference(fg_entry, &fg_srcu);
	ret = !entry ? -ENODEV : !entry->ops.strategy_fg_get_rsoc ?
		-EOPNOTSUPP : entry->ops.strategy_fg_get_rsoc(entry->data, rsoc);
	srcu_read_unlock(&fg_srcu, idx);
	return ret;
}
EXPORT_SYMBOL(strategy_class_fg_ops_get_rsoc);

int strategy_class_fg_ops_get_soc(void)
{
	struct mca_fg_entry *entry;
	int idx;
	int ret;

	idx = srcu_read_lock(&fg_srcu);
	entry = srcu_dereference(fg_entry, &fg_srcu);
	ret = !entry ? -ENODEV : !entry->ops.strategy_fg_get_soc ?
		-EOPNOTSUPP : entry->ops.strategy_fg_get_soc(entry->data);
	srcu_read_unlock(&fg_srcu, idx);
	return ret;
}
EXPORT_SYMBOL(strategy_class_fg_ops_get_soc);

int strategy_class_fg_ops_get_temperature(int *temp)
{
	struct mca_fg_entry *entry;
	int idx;
	int ret;

	if (!temp)
		return -EINVAL;
	idx = srcu_read_lock(&fg_srcu);
	entry = srcu_dereference(fg_entry, &fg_srcu);
	ret = !entry ? -ENODEV : !entry->ops.strategy_fg_get_temp ?
		-EOPNOTSUPP : entry->ops.strategy_fg_get_temp(entry->data, temp);
	srcu_read_unlock(&fg_srcu, idx);
	return ret;
}
EXPORT_SYMBOL(strategy_class_fg_ops_get_temperature);

int strategy_class_fg_ops_get_current(int *curr)
{
	struct mca_fg_entry *entry;
	int idx;
	int ret;

	if (!curr)
		return -EINVAL;
	idx = srcu_read_lock(&fg_srcu);
	entry = srcu_dereference(fg_entry, &fg_srcu);
	ret = !entry ? -ENODEV : !entry->ops.strategy_fg_get_current ?
		-EOPNOTSUPP : entry->ops.strategy_fg_get_current(entry->data, curr);
	srcu_read_unlock(&fg_srcu, idx);
	return ret;
}
EXPORT_SYMBOL(strategy_class_fg_ops_get_current);

int strategy_class_fg_ops_get_voltage(int *volt)
{
	struct mca_fg_entry *entry;
	int idx;
	int ret;

	if (!volt)
		return -EINVAL;
	idx = srcu_read_lock(&fg_srcu);
	entry = srcu_dereference(fg_entry, &fg_srcu);
	ret = !entry ? -ENODEV : !entry->ops.strategy_fg_get_voltage ?
		-EOPNOTSUPP : entry->ops.strategy_fg_get_voltage(entry->data, volt);
	srcu_read_unlock(&fg_srcu, idx);
	return ret;
}
EXPORT_SYMBOL(strategy_class_fg_ops_get_voltage);

int strategy_class_fg_ops_get_cyclecount(int *cycle)
{
	struct mca_fg_entry *entry;
	int idx;
	int ret;

	if (!cycle)
		return -EINVAL;
	idx = srcu_read_lock(&fg_srcu);
	entry = srcu_dereference(fg_entry, &fg_srcu);
	ret = !entry ? -ENODEV : !entry->ops.strategy_fg_get_cycle ?
		-EOPNOTSUPP : entry->ops.strategy_fg_get_cycle(entry->data, cycle);
	srcu_read_unlock(&fg_srcu, idx);
	return ret;
}
EXPORT_SYMBOL(strategy_class_fg_ops_get_cyclecount);

int strategy_class_fg_get_voltage_mean(int *vol_mean)
{
	struct mca_fg_entry *entry;
	int idx;
	int ret;

	if (!vol_mean)
		return -EINVAL;
	idx = srcu_read_lock(&fg_srcu);
	entry = srcu_dereference(fg_entry, &fg_srcu);
	ret = !entry ? -ENODEV : !entry->ops.strategy_fg_get_voltage_mean ?
		-EOPNOTSUPP : entry->ops.strategy_fg_get_voltage_mean(entry->data, vol_mean);
	srcu_read_unlock(&fg_srcu, idx);
	return ret;
}
EXPORT_SYMBOL(strategy_class_fg_get_voltage_mean);

int strategy_class_fg_ops_get_soc_decimal(int *soc_decimal, int *rate)
{
	struct mca_fg_entry *entry;
	int idx;
	int ret;

	if (!soc_decimal || !rate)
		return -EINVAL;
	idx = srcu_read_lock(&fg_srcu);
	entry = srcu_dereference(fg_entry, &fg_srcu);
	ret = !entry ? -ENODEV : !entry->ops.strategy_fg_get_soc_decimal_info ?
		-EOPNOTSUPP : entry->ops.strategy_fg_get_soc_decimal_info(entry->data, soc_decimal, rate);
	srcu_read_unlock(&fg_srcu, idx);
	return ret;
}
EXPORT_SYMBOL(strategy_class_fg_ops_get_soc_decimal);

bool strategy_class_fg_ops_get_charging_done(void)
{
	struct mca_fg_entry *entry;
	int idx;
	bool ret;

	idx = srcu_read_lock(&fg_srcu);
	entry = srcu_dereference(fg_entry, &fg_srcu);
	ret = !entry ? false : !entry->ops.strategy_fg_get_charging_done ?
		false : entry->ops.strategy_fg_get_charging_done(entry->data);
	srcu_read_unlock(&fg_srcu, idx);
	return ret;
}
EXPORT_SYMBOL(strategy_class_fg_ops_get_charging_done);

int strategy_class_fg_ops_set_charging_done(bool charging_done)
{
	struct mca_fg_entry *entry;
	int idx;
	int ret;

	idx = srcu_read_lock(&fg_srcu);
	entry = srcu_dereference(fg_entry, &fg_srcu);
	ret = !entry ? -ENODEV : !entry->ops.strategy_fg_set_charging_done ?
		-EOPNOTSUPP : entry->ops.strategy_fg_set_charging_done(entry->data, charging_done);
	srcu_read_unlock(&fg_srcu, idx);
	return ret;
}
EXPORT_SYMBOL(strategy_class_fg_ops_set_charging_done);

int strategy_class_fg_get_model_name(const char **model_name)
{
	struct mca_fg_entry *entry;
	int idx;
	int ret;

	if (!model_name)
		return -EINVAL;
	idx = srcu_read_lock(&fg_srcu);
	entry = srcu_dereference(fg_entry, &fg_srcu);
	ret = !entry ? -ENODEV : !entry->ops.strategy_fg_get_model_name ?
		-EOPNOTSUPP : entry->ops.strategy_fg_get_model_name(entry->data, model_name);
	srcu_read_unlock(&fg_srcu, idx);
	return ret;
}
EXPORT_SYMBOL(strategy_class_fg_get_model_name);

int strategy_class_fg_set_fastcharge(bool en)
{
	struct mca_fg_entry *entry;
	int idx;
	int ret;

	idx = srcu_read_lock(&fg_srcu);
	entry = srcu_dereference(fg_entry, &fg_srcu);
	ret = !entry ? -ENODEV : !entry->ops.strategy_fg_set_fastcharge ?
		-EOPNOTSUPP : entry->ops.strategy_fg_set_fastcharge(entry->data, en);
	srcu_read_unlock(&fg_srcu, idx);
	return ret;
}
EXPORT_SYMBOL(strategy_class_fg_set_fastcharge);

int strategy_class_fg_get_fastcharge(void)
{
	struct mca_fg_entry *entry;
	int idx;
	int ret;

	idx = srcu_read_lock(&fg_srcu);
	entry = srcu_dereference(fg_entry, &fg_srcu);
	ret = !entry ? -ENODEV : !entry->ops.strategy_fg_get_fastcharge ?
		-EOPNOTSUPP : entry->ops.strategy_fg_get_fastcharge(entry->data);
	srcu_read_unlock(&fg_srcu, idx);
	return ret;
}
EXPORT_SYMBOL(strategy_class_fg_get_fastcharge);

int strategy_class_fg_get_authentic(bool *authentic)
{
	struct mca_fg_entry *entry;
	int idx;
	int ret;

	if (!authentic)
		return -EINVAL;
	idx = srcu_read_lock(&fg_srcu);
	entry = srcu_dereference(fg_entry, &fg_srcu);
	ret = !entry ? -ENODEV : !entry->ops.strategy_fg_get_authentic ?
		-EOPNOTSUPP : entry->ops.strategy_fg_get_authentic(entry->data, authentic);
	srcu_read_unlock(&fg_srcu, idx);
	return ret;
}
EXPORT_SYMBOL(strategy_class_fg_get_authentic);

int strategy_class_fg_get_dc(int *dc)
{
	struct mca_fg_entry *entry;
	int idx;
	int ret;

	if (!dc)
		return -EINVAL;
	idx = srcu_read_lock(&fg_srcu);
	entry = srcu_dereference(fg_entry, &fg_srcu);
	ret = !entry ? -ENODEV : !entry->ops.strategy_fg_get_dc ?
		-EOPNOTSUPP : entry->ops.strategy_fg_get_dc(entry->data, dc);
	srcu_read_unlock(&fg_srcu, idx);
	return ret;
}
EXPORT_SYMBOL(strategy_class_fg_get_dc);

int strategy_class_fg_get_rm(int *rm)
{
	struct mca_fg_entry *entry;
	int idx;
	int ret;

	if (!rm)
		return -EINVAL;
	idx = srcu_read_lock(&fg_srcu);
	entry = srcu_dereference(fg_entry, &fg_srcu);
	ret = !entry ? -ENODEV : !entry->ops.strategy_fg_get_rm ?
		-EOPNOTSUPP : entry->ops.strategy_fg_get_rm(entry->data, rm);
	srcu_read_unlock(&fg_srcu, idx);
	return ret;
}
EXPORT_SYMBOL(strategy_class_fg_get_rm);

int strategy_class_fg_get_fcc(int *fcc)
{
	struct mca_fg_entry *entry;
	int idx;
	int ret;

	if (!fcc)
		return -EINVAL;
	idx = srcu_read_lock(&fg_srcu);
	entry = srcu_dereference(fg_entry, &fg_srcu);
	ret = !entry ? -ENODEV : !entry->ops.strategy_fg_get_fcc ?
		-EOPNOTSUPP : entry->ops.strategy_fg_get_fcc(entry->data, fcc);
	srcu_read_unlock(&fg_srcu, idx);
	return ret;
}
EXPORT_SYMBOL(strategy_class_fg_get_fcc);

int strategy_class_fg_is_chip_ok(void)
{
	struct mca_fg_entry *entry;
	int idx;
	int ret;

	idx = srcu_read_lock(&fg_srcu);
	entry = srcu_dereference(fg_entry, &fg_srcu);
	ret = !entry ? -ENODEV : !entry->ops.strategy_fg_is_chip_ok ?
		-EOPNOTSUPP : entry->ops.strategy_fg_is_chip_ok(entry->data);
	srcu_read_unlock(&fg_srcu, idx);
	return ret;
}
EXPORT_SYMBOL(strategy_class_fg_is_chip_ok);

int strategy_class_fg_get_health(int *health)
{
	struct mca_fg_entry *entry;
	int idx;
	int ret;

	if (!health)
		return -EINVAL;
	idx = srcu_read_lock(&fg_srcu);
	entry = srcu_dereference(fg_entry, &fg_srcu);
	ret = !entry ? -ENODEV : !entry->ops.strategy_fg_get_health ?
		-EOPNOTSUPP : entry->ops.strategy_fg_get_health(entry->data, health);
	srcu_read_unlock(&fg_srcu, idx);
	return ret;
}
EXPORT_SYMBOL(strategy_class_fg_get_health);

int strategy_class_fg_get_first_termination(int *value)
{
	struct mca_fg_entry *entry;
	int idx;
	int ret;

	if (!value)
		return -EINVAL;
	idx = srcu_read_lock(&fg_srcu);
	entry = srcu_dereference(fg_entry, &fg_srcu);
	ret = !entry ? -ENODEV : !entry->ops.strategy_fg_get_first_termination ?
		-EOPNOTSUPP : entry->ops.strategy_fg_get_first_termination(entry->data, value);
	srcu_read_unlock(&fg_srcu, idx);
	return ret;
}
EXPORT_SYMBOL(strategy_class_fg_get_first_termination);

int strategy_class_fg_get_pack_vendor_id(int *vendor_id)
{
	struct mca_fg_entry *entry;
	int idx;
	int ret;

	if (!vendor_id)
		return -EINVAL;
	idx = srcu_read_lock(&fg_srcu);
	entry = srcu_dereference(fg_entry, &fg_srcu);
	ret = !entry ? -ENODEV : !entry->ops.strategy_fg_get_pack_vendor_id ?
		-EOPNOTSUPP : entry->ops.strategy_fg_get_pack_vendor_id(entry->data, vendor_id);
	srcu_read_unlock(&fg_srcu, idx);
	return ret;
}
EXPORT_SYMBOL(strategy_class_fg_get_pack_vendor_id);

int strategy_class_fg_dual_is_chip_ok(int index)
{
	struct mca_fg_entry *entry;
	int idx;
	int ret;

	idx = srcu_read_lock(&fg_srcu);
	entry = srcu_dereference(fg_entry, &fg_srcu);
	ret = !entry ? -ENODEV : !entry->ops.strategy_fg_dual_is_chip_ok ?
		-EOPNOTSUPP : entry->ops.strategy_fg_dual_is_chip_ok(entry->data, index);
	srcu_read_unlock(&fg_srcu, idx);
	return ret;
}
EXPORT_SYMBOL(strategy_class_fg_dual_is_chip_ok);

int strategy_class_fg_ops_get_thermal_temperature(int *temp)
{
	struct mca_fg_entry *entry;
	int idx;
	int ret;

	if (!temp)
		return -EINVAL;
	idx = srcu_read_lock(&fg_srcu);
	entry = srcu_dereference(fg_entry, &fg_srcu);
	ret = !entry ? -ENODEV : !entry->ops.strategy_fg_get_thermal_temperature ?
		-EOPNOTSUPP : entry->ops.strategy_fg_get_thermal_temperature(entry->data, temp);
	srcu_read_unlock(&fg_srcu, idx);
	return ret;
}
EXPORT_SYMBOL(strategy_class_fg_ops_get_thermal_temperature);

int strategy_class_fg_get_soh(int *soh)
{
	struct mca_fg_entry *entry;
	int idx;
	int ret;

	if (!soh)
		return -EINVAL;
	idx = srcu_read_lock(&fg_srcu);
	entry = srcu_dereference(fg_entry, &fg_srcu);
	ret = !entry ? -ENODEV : !entry->ops.strategy_fg_get_soh ?
		-EOPNOTSUPP : entry->ops.strategy_fg_get_soh(entry->data, soh);
	srcu_read_unlock(&fg_srcu, idx);
	return ret;
}
EXPORT_SYMBOL(strategy_class_fg_get_soh);

int strategy_class_fg_get_temp_offset_flag(int *flag)
{
	struct mca_fg_entry *entry;
	int idx;
	int ret;

	if (!flag)
		return -EINVAL;
	idx = srcu_read_lock(&fg_srcu);
	entry = srcu_dereference(fg_entry, &fg_srcu);
	ret = !entry ? -ENODEV : !entry->ops.strategy_fg_get_temp_offset_flag ?
		-EOPNOTSUPP : entry->ops.strategy_fg_get_temp_offset_flag(entry->data, flag);
	srcu_read_unlock(&fg_srcu, idx);
	return ret;
}
EXPORT_SYMBOL(strategy_class_fg_get_temp_offset_flag);

static int __init strategy_fg_class_init(void)
{
	return 0;
}

static void __exit strategy_fg_class_exit(void)
{
	struct mca_fg_entry *entry = rcu_access_pointer(fg_entry);

	if (entry)
		strategy_class_fg_ops_unregister(entry->data);
}
module_init(strategy_fg_class_init);
module_exit(strategy_fg_class_exit);
MODULE_DESCRIPTION("MCA fuel gauge strategy registry");
MODULE_LICENSE("GPL v2");
