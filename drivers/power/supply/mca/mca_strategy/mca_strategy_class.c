// SPDX-License-Identifier: GPL-2.0
/*
 *mca_strategy_class.c
 *
 * mca strategy class driver
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
#include <linux/mutex.h>
#include <linux/srcu.h>
#include <linux/stat.h>
#include <linux/init.h>
#include <linux/ctype.h>
#include <linux/err.h>
#include <linux/slab.h>
#include <linux/kernel.h>
#include <linux/device.h>
#include <linux/platform_device.h>
#include <mca/strategy/strategy_class.h>

struct mca_strategy_func_data {
	mca_strategy_func func;
	mca_strategy_get_status get_func;
	mca_strategy_set_config set_config;
	void *data;
};

static struct mca_strategy_func_data __rcu *g_mca_stg_func[STRATEGY_FUNC_TYPE_MAX];
static DEFINE_MUTEX(strategy_lock);
DEFINE_STATIC_SRCU(strategy_srcu);

/* Providers publish immutable callbacks/data and unregister before freeing them.
 * Synchronous unregister must not be called from a strategy callback. */
static struct mca_strategy_func_data *mca_strategy_get_func_data(unsigned int type)
{
	return srcu_dereference(g_mca_stg_func[type], &strategy_srcu);
}

int mca_strategy_func_get_status(int type, int status, void *value)
{
	struct mca_strategy_func_data *entry;
	int idx, ret;

	if ((unsigned int)type >= STRATEGY_FUNC_TYPE_MAX || !value)
		return -EINVAL;
	idx = srcu_read_lock(&strategy_srcu);
	entry = mca_strategy_get_func_data(type);
	ret = !entry ? -ENODEV : !entry->get_func ? -EOPNOTSUPP :
		entry->get_func(status, value, entry->data);
	srcu_read_unlock(&strategy_srcu, idx);
	return ret;
}
EXPORT_SYMBOL(mca_strategy_func_get_status);

int mca_strategy_func_process(unsigned int type, int event, int value)
{
	struct mca_strategy_func_data *entry;
	int idx, ret;

	if (type >= STRATEGY_FUNC_TYPE_MAX)
		return -EINVAL;
	idx = srcu_read_lock(&strategy_srcu);
	entry = mca_strategy_get_func_data(type);
	ret = !entry ? -ENODEV : !entry->func ? -EOPNOTSUPP :
		entry->func(event, value, entry->data);
	srcu_read_unlock(&strategy_srcu, idx);
	return ret;
}
EXPORT_SYMBOL(mca_strategy_func_process);

int mca_strategy_func_set_config(int type, int config, int value)
{
	struct mca_strategy_func_data *entry;
	int idx, ret;

	if ((unsigned int)type >= STRATEGY_FUNC_TYPE_MAX)
		return -EINVAL;
	idx = srcu_read_lock(&strategy_srcu);
	entry = mca_strategy_get_func_data(type);
	ret = !entry ? -ENODEV : !entry->set_config ? -EOPNOTSUPP :
		entry->set_config(config, value, entry->data);
	srcu_read_unlock(&strategy_srcu, idx);
	return ret;
}
EXPORT_SYMBOL(mca_strategy_func_set_config);

int mca_strategy_ops_register(unsigned int type, mca_strategy_func func,
	mca_strategy_get_status get_func, mca_strategy_set_config set_config, void *data)
{
	struct mca_strategy_func_data *entry;
	int ret = 0;

	if (type >= STRATEGY_FUNC_TYPE_MAX || !data ||
	    (!func && !get_func && !set_config))
		return -EINVAL;
	entry = kzalloc(sizeof(*entry), GFP_KERNEL);
	if (!entry)
		return -ENOMEM;
	entry->func = func;
	entry->get_func = get_func;
	entry->set_config = set_config;
	entry->data = data;
	mutex_lock(&strategy_lock);
	if (rcu_access_pointer(g_mca_stg_func[type]))
		ret = -EBUSY;
	else
		rcu_assign_pointer(g_mca_stg_func[type], entry);
	mutex_unlock(&strategy_lock);
	if (ret)
		kfree(entry);
	return ret;
}
EXPORT_SYMBOL(mca_strategy_ops_register);

int mca_strategy_ops_unregister(unsigned int type, void *data)
{
	struct mca_strategy_func_data *entry;

	if (type >= STRATEGY_FUNC_TYPE_MAX || !data)
		return -EINVAL;
	mutex_lock(&strategy_lock);
	entry = rcu_access_pointer(g_mca_stg_func[type]);
	if (!entry || entry->data != data) {
		mutex_unlock(&strategy_lock);
		return -ENOENT;
	}
	RCU_INIT_POINTER(g_mca_stg_func[type], NULL);
	mutex_unlock(&strategy_lock);
	synchronize_srcu(&strategy_srcu);
	kfree(entry);
	return 0;
}
EXPORT_SYMBOL(mca_strategy_ops_unregister);

static struct platform_driver mca_strategy_class_driver = {
	.driver	= {
		.name = "mca_strategy_class",
	},
};


static int __init mca_strategy_class_init(void)
{
	return platform_driver_register(&mca_strategy_class_driver);
}

static void __exit mca_strategy_class_exit(void)
{
	struct mca_strategy_func_data *entry;
	int i;

	platform_driver_unregister(&mca_strategy_class_driver);
	/* Dependent provider modules have gone; release any legacy registration. */
	for (i = 0; i < STRATEGY_FUNC_TYPE_MAX; i++) {
		entry = rcu_access_pointer(g_mca_stg_func[i]);
		if (entry)
			mca_strategy_ops_unregister(i, entry->data);
	}
}
module_init(mca_strategy_class_init);
module_exit(mca_strategy_class_exit);


MODULE_DESCRIPTION("mca strategy class");
MODULE_AUTHOR("getian@xiaomi.com");
MODULE_LICENSE("GPL v2");

