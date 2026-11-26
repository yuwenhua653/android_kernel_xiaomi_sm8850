// SPDX-License-Identifier: GPL-2.0
/*
 * mca_protocol_qc_class.c
 *
 * mca qc protocol class driver
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
#include <linux/stat.h>
#include <linux/init.h>
#include <linux/ctype.h>
#include <linux/err.h>
#include <linux/slab.h>
#include <linux/kernel.h>
#include <linux/device.h>
#include <linux/mutex.h>
#include <linux/srcu.h>
#include <linux/notifier.h>
#include <mca/common/mca_event.h>
#include <mca/common/mca_log.h>
#include <mca/protocol/protocol_qc_class.h>

#ifndef MCA_LOG_TAG
#define MCA_LOG_TAG "protocol_qc_class"
#endif

struct protocol_class_qc_ops_data {
	void *data;
	struct protocol_class_qc_ops *ops;
};

static unsigned int g_cur_port;
static struct protocol_class_qc_ops_data __rcu *g_protocol_qc_data[TYPEC_PORT_MAX];
static DEFINE_MUTEX(g_protocol_qc_lock);
DEFINE_STATIC_SRCU(g_protocol_qc_srcu);

int protocol_class_qc3_check_class_type(unsigned int port_num, int *type)
{
	struct protocol_class_qc_ops_data *entry;
	int idx, ret = -ENODEV;

	if (port_num >= TYPEC_PORT_MAX || !type)
		return -EINVAL;
	idx = srcu_read_lock(&g_protocol_qc_srcu);
	entry = srcu_dereference(g_protocol_qc_data[port_num], &g_protocol_qc_srcu);
	if (entry && entry->ops->protocol_qc3_check_class_type)
		ret = entry->ops->protocol_qc3_check_class_type(type, entry->data);
	srcu_read_unlock(&g_protocol_qc_srcu, idx);
	return ret;
}
EXPORT_SYMBOL(protocol_class_qc3_check_class_type);

int protocol_class_qc_get_qc_type(unsigned int port_num, int *type)
{
	struct protocol_class_qc_ops_data *entry;
	int idx, ret = -ENODEV;

	if (port_num >= TYPEC_PORT_MAX || !type)
		return -EINVAL;
	idx = srcu_read_lock(&g_protocol_qc_srcu);
	entry = srcu_dereference(g_protocol_qc_data[port_num], &g_protocol_qc_srcu);
	if (entry && entry->ops->protocol_qc_get_qc_type)
		ret = entry->ops->protocol_qc_get_qc_type(type, entry->data);
	srcu_read_unlock(&g_protocol_qc_srcu, idx);
	return ret;
}
EXPORT_SYMBOL(protocol_class_qc_get_qc_type);

int protocol_class_qc_set_volt(unsigned int port_num, int volt)
{
	struct protocol_class_qc_ops_data *entry;
	int idx, ret = -ENODEV;

	if (port_num >= TYPEC_PORT_MAX)
		return -EINVAL;
	idx = srcu_read_lock(&g_protocol_qc_srcu);
	entry = srcu_dereference(g_protocol_qc_data[port_num], &g_protocol_qc_srcu);
	if (entry && entry->ops->protocol_qc_set_volt)
		ret = entry->ops->protocol_qc_set_volt(entry->data, volt);
	srcu_read_unlock(&g_protocol_qc_srcu, idx);
	return ret;
}
EXPORT_SYMBOL(protocol_class_qc_set_volt);

int protocol_class_qc_set_volt_cmd(unsigned int port_num, int hvdcp_cmd)
{
	struct protocol_class_qc_ops_data *entry;
	int idx, ret = -ENODEV;

	if (port_num >= TYPEC_PORT_MAX)
		return -EINVAL;
	idx = srcu_read_lock(&g_protocol_qc_srcu);
	entry = srcu_dereference(g_protocol_qc_data[port_num], &g_protocol_qc_srcu);
	if (entry && entry->ops->protocol_qc_set_volt_cmd)
		ret = entry->ops->protocol_qc_set_volt_cmd(entry->data, hvdcp_cmd);
	srcu_read_unlock(&g_protocol_qc_srcu, idx);
	return ret;
}
EXPORT_SYMBOL(protocol_class_qc_set_volt_cmd);

static int protocol_class_qc_get_adapter_type(void *data, int *type)
{
	return protocol_class_qc_get_qc_type(g_cur_port, type);
}

static int protocol_class_qc_set_volt_and_curr(void *data, int volt, int curr)
{
	return protocol_class_qc_set_volt(g_cur_port, volt);
}

int protocol_class_qc_register_ops(unsigned int port_num,
				   struct protocol_class_qc_ops *ops, void *data)
{
	struct protocol_class_qc_ops_data *entry, *old;

	if (port_num >= TYPEC_PORT_MAX || !ops)
		return -EINVAL;
	entry = kmalloc(sizeof(*entry), GFP_KERNEL);
	if (!entry)
		return -ENOMEM;
	entry->ops = ops;
	entry->data = data;
	mutex_lock(&g_protocol_qc_lock);
	old = rcu_replace_pointer(g_protocol_qc_data[port_num], entry,
				  lockdep_is_held(&g_protocol_qc_lock));
	mutex_unlock(&g_protocol_qc_lock);
	synchronize_srcu(&g_protocol_qc_srcu);
	kfree(old);
	return 0;
}
EXPORT_SYMBOL(protocol_class_qc_register_ops);

int protocol_class_qc_unregister_ops(unsigned int port_num,
				     struct protocol_class_qc_ops *ops, void *data)
{
	struct protocol_class_qc_ops_data *old;

	if (port_num >= TYPEC_PORT_MAX || !ops)
		return -EINVAL;
	mutex_lock(&g_protocol_qc_lock);
	old = rcu_dereference_protected(g_protocol_qc_data[port_num],
					lockdep_is_held(&g_protocol_qc_lock));
	if (!old || old->ops != ops || old->data != data) {
		mutex_unlock(&g_protocol_qc_lock);
		synchronize_srcu(&g_protocol_qc_srcu);
		return -ENOENT;
	}
	RCU_INIT_POINTER(g_protocol_qc_data[port_num], NULL);
	mutex_unlock(&g_protocol_qc_lock);
	synchronize_srcu(&g_protocol_qc_srcu);
	kfree(old);
	return 0;
}
EXPORT_SYMBOL_GPL(protocol_class_qc_unregister_ops);

struct adapter_protocol_class_ops g_protocol_qc_ops = {
	.get_adapter_type = protocol_class_qc_get_adapter_type,
	.set_adapter_volt_and_curr = protocol_class_qc_set_volt_and_curr,
};

static int protocol_qc_class_probe(struct platform_device *pdev)
{
	int ret;

	ret = protocol_class_register_ops(ADAPTER_PROTOCOL_QC, &g_protocol_qc_ops, NULL);
	if (ret)
		return ret;

	g_cur_port = TYPEC_PORT_0;

	return ret;
}

static void protocol_qc_class_remove(struct platform_device *pdev)
{
	protocol_class_unregister_ops(ADAPTER_PROTOCOL_QC, &g_protocol_qc_ops, NULL);
}

static void protocol_qc_class_shutdown(struct platform_device *pdev)
{
}

static const struct of_device_id match_table[] = {
	{.compatible = "mca,protocol_qc"},
	{},
};

static struct platform_driver protocol_qc_class_driver = {
	.driver	= {
		.name = "protocol_qc_class",
		.owner = THIS_MODULE,
		.of_match_table = match_table,
	},
	.probe = protocol_qc_class_probe,
	.remove = protocol_qc_class_remove,
	.shutdown = protocol_qc_class_shutdown,
};

static int __init protocol_qc_class_init(void)
{
	return platform_driver_register(&protocol_qc_class_driver);
}
module_init(protocol_qc_class_init);

static void __exit protocol_qc_class_exit(void)
{
	platform_driver_unregister(&protocol_qc_class_driver);
}
module_exit(protocol_qc_class_exit);

MODULE_DESCRIPTION("protocol qc class");
MODULE_AUTHOR("muxinyi1@xiaomi.com");
MODULE_LICENSE("GPL v2");
