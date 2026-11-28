// SPDX-License-Identifier: GPL-2.0
/*
 * mca_platform_wireless_class.c
 *
 * mca platform wireless class driver
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
#include <linux/kernel.h>
#include <linux/string.h>
#include <linux/srcu.h>
#include <linux/device.h>
#include <linux/module.h>
#include <linux/platform_device.h>
#include <mca/platform/platform_wireless_class.h>
#include <mca/common/mca_log.h>
#include <mca/common/mca_parse_dts.h>
#include <mca/common/mca_sysfs.h>

#ifndef MCA_LOG_TAG
#define MCA_LOG_TAG "wireless_class"
#endif
#define MCA_WIRELESS_MAX_NUM 2
#define STRING_MAX_LEN 200

#define platform_wireless_ops_invalid(data, name) \
	(!data || !data->ops || !data->ops->name)

struct platform_wireless_class_ops_data {
	struct platform_class_wireless_ops *ops;
	void *data;
};

static DEFINE_MUTEX(wireless_provider_lock);
DEFINE_STATIC_SRCU(wireless_provider_srcu);
static struct platform_wireless_class_ops_data __rcu *platform_wireless_data[WIRELESS_ROLE_MAX];

struct platform_wireless_dev {
	struct device *dev;
	int wireless_num;
	const char *wireless_dir_list[MCA_WIRELESS_MAX_NUM];
	struct device *sysfs_dev[MCA_WIRELESS_MAX_NUM];
	int wireless_dev_index[MCA_WIRELESS_MAX_NUM];
};

union platform_wireless_propval {
	unsigned int uintval;
	int intval;
	char strval[STRING_MAX_LEN];
	bool boolval;
	u64 val64bit;
};

enum wireless_attr_list {
	RX_SYSFS_RX_VOUT,
	RX_SYSFS_RX_VRECT,
	RX_SYSFS_RX_IOUT,
	RX_SYSFS_FW_VERSION,
	RX_SYSFS_FW_BIN,
	RX_SYSFS_SLEEP_RX,
	RX_SYSFS_TX_ADAPTER,
	RX_SYSFS_BT_STATE,
	RX_SYSFS_RX_CEP,
	RX_SYSFS_RX_CR,
	RX_SYSFS_TX_MAC,
	RX_SYSFS_WLS_DIE_TEMP,
	RX_SYSFS_WLS_TX_SPEED,
	RX_SYSFS_RX_SS,
	RX_SYSFS_RX_OFFSET,
	RX_SYSFS_RX_SLEEP_MODE,
	RX_SYSFS_TX_UUID,
};

static inline struct platform_wireless_class_ops_data *
platform_wireless_class_get_ic_ops(unsigned int role)
{
	if (role >= WIRELESS_ROLE_MAX)
		return NULL;

	return srcu_dereference(platform_wireless_data[role], &wireless_provider_srcu);
}

int platform_class_wireless_register_ops(
	unsigned int role, void *data, struct platform_class_wireless_ops *ops)
{
	struct platform_wireless_class_ops_data *provider;

	if (role >= WIRELESS_ROLE_MAX || !data || !ops)
		return -EINVAL;
	guard(mutex)(&wireless_provider_lock);
	if (rcu_access_pointer(platform_wireless_data[role]))
		return -EBUSY;
	provider = kmalloc(sizeof(*provider), GFP_KERNEL);
	if (!provider)
		return -ENOMEM;
	provider->data = data;
	provider->ops = ops;
	rcu_assign_pointer(platform_wireless_data[role], provider);
	return 0;
}
EXPORT_SYMBOL(platform_class_wireless_register_ops);

int platform_class_wireless_unregister_ops(
	unsigned int role, void *data, struct platform_class_wireless_ops *ops)
{
	struct platform_wireless_class_ops_data *provider;

	if (role >= WIRELESS_ROLE_MAX)
		return -EINVAL;
	mutex_lock(&wireless_provider_lock);
	provider = rcu_dereference_protected(platform_wireless_data[role],
					     lockdep_is_held(&wireless_provider_lock));
	if (!provider || provider->data != data || provider->ops != ops) {
		mutex_unlock(&wireless_provider_lock);
		return -ENOENT;
	}
	RCU_INIT_POINTER(platform_wireless_data[role], NULL);
	mutex_unlock(&wireless_provider_lock);
	synchronize_srcu(&wireless_provider_srcu);
	kfree(provider);
	return 0;
}
EXPORT_SYMBOL(platform_class_wireless_unregister_ops);

int platform_class_wireless_enable_reverse_chg(unsigned int role, bool enable)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_enable_reverse_chg))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_enable_reverse_chg(enable, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_enable_reverse_chg);

int platform_class_wireless_is_present(unsigned int role, int *present)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_is_present))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_is_present(present, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_is_present);

int platform_class_wireless_get_fw_upgrade_fail_info(unsigned int role,
						     char **info)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data,
					  wls_get_fw_upgrade_fail_info))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_get_fw_upgrade_fail_info(info,
							    temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_get_fw_upgrade_fail_info);

int platform_class_wireless_copy_fw_upgrade_fail_info(unsigned int role, char *buf, size_t size)
{
	struct platform_wireless_class_ops_data *provider;
	char *info = NULL;
	int ret;

	if (!buf || !size)
		return -EINVAL;
	guard(srcu)(&wireless_provider_srcu);
	provider = platform_wireless_class_get_ic_ops(role);
	if (platform_wireless_ops_invalid(provider, wls_get_fw_upgrade_fail_info))
		return -EOPNOTSUPP;
	ret = provider->ops->wls_get_fw_upgrade_fail_info(&info, provider->data);
	if (ret)
		return ret;
	return strscpy(buf, info ?: "Unknown", size) < 0 ? -E2BIG : 0;
}
EXPORT_SYMBOL(platform_class_wireless_copy_fw_upgrade_fail_info);

int platform_class_wireless_get_rsv_eppmode_fail(unsigned int role, int *fail)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_get_rsv_eppmode_fail))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_get_rsv_eppmode_fail(fail, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_get_rsv_eppmode_fail);

int platform_class_wireless_set_vout(unsigned int role, int vout)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_set_vout))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_set_vout(vout, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_set_vout);

int platform_class_wireless_get_vout(unsigned int role, int *vout)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_get_vout))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_get_vout(vout, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_get_vout);

int platform_class_wireless_get_iout(unsigned int role, int *iout)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_get_iout))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_get_iout(iout, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_get_iout);

int platform_class_wireless_get_vrect(unsigned int role, int *vrect)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_get_vrect))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_get_vrect(vrect, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_get_vrect);

int platform_class_wireless_get_tx_adapter(unsigned int role, int *adapter)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_get_tx_adapter))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_get_tx_adapter(adapter, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_get_tx_adapter);

extern int platform_class_wireless_get_tx_adapter_by_i2c(unsigned int role,
							 int *adapter)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_get_tx_adapter_by_i2c))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_get_tx_adapter_by_i2c(adapter,
							 temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_get_tx_adapter_by_i2c);

int platform_class_wireless_get_temp(unsigned int role, int *temp)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_get_temp))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_get_temp(temp, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_get_temp);

int platform_class_wireless_set_enable_mode(unsigned int role, bool enable)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_set_enable_mode))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_set_enable_mode(enable, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_set_enable_mode);

int platform_class_wireless_is_car_adapter(unsigned int role, bool *enable)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_is_car_adapter))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_is_car_adapter(enable, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_is_car_adapter);

int platform_class_wireless_get_fw_version(unsigned int role, char *buf)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_get_fw_version))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_get_fw_version(buf, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_get_fw_version);

int platform_class_wireless_get_rx_rtx_mode(unsigned int role, int *mode)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_get_rx_rtx_mode))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_get_rx_rtx_mode(mode, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_get_rx_rtx_mode);

int platform_class_wireless_set_fw_bin(unsigned int role, const char *buf,
				       int count)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_set_fw_bin))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_set_fw_bin(buf, count, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_set_fw_bin);

int platform_class_wireless_set_input_current_limit(unsigned int role,
						    int value)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data,
					  wls_set_input_current_limit))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_set_input_current_limit(value,
							   temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_set_input_current_limit);

int platform_class_wireless_get_rx_int_flag(unsigned int role, int *int_flag)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_get_rx_int_flag))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_get_rx_int_flag(int_flag, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_get_rx_int_flag);

int platform_class_wireless_get_rx_power_mode(unsigned int role, u8 *power_mode)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_get_rx_power_mode))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_get_rx_power_mode(power_mode,
						     temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_get_rx_power_mode);

int platform_class_wireless_get_tx_max_power(unsigned int role, u8 *max_power)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_get_tx_max_power))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_get_tx_max_power(max_power, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_get_tx_max_power);

int platform_class_wireless_get_auth_value(unsigned int role, int *value)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_get_auth_value))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_get_auth_value(value, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_get_auth_value);

int platform_class_wireless_set_adapter_voltage(unsigned int role, int voltage)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_set_adapter_voltage))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_set_adapter_voltage(voltage,
						       temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_set_adapter_voltage);

int platform_class_wireless_get_tx_uuid(unsigned int role, u8 *uuid)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_get_tx_uuid))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_get_tx_uuid(uuid, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_get_tx_uuid);

int platform_class_wireless_set_fod_params(unsigned int role, int value)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_set_fod_params))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_set_fod_params(value, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_set_fod_params);

int platform_class_wireless_get_rx_fastcharge_status(unsigned int role,
						     u8 *fc_flag)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data,
					  wls_get_rx_fastcharge_status))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_get_rx_fastcharge_status(fc_flag,
							    temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_get_rx_fastcharge_status);

int platform_class_wireless_receive_transparent_data(unsigned int role,
						     u8 *rcv_value,
						     int buff_len, int *rcv_len)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data,
					  wls_receive_transparent_data))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_receive_transparent_data(
		rcv_value, buff_len, rcv_len, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_receive_transparent_data);

int platform_class_wireless_send_transparent_data(unsigned int role,
						  u8 *send_data, u8 length)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_send_transparent_data))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_send_transparent_data(send_data, length,
							 temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_send_transparent_data);

int platform_class_wireless_get_ss_voltage(unsigned int role, int *ss_voltage)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_get_ss_voltage))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_get_ss_voltage(ss_voltage, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_get_ss_voltage);

int platform_class_wireless_do_renego(unsigned int role, u8 max_power)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_do_renego))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_do_renego(max_power, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_do_renego);

int platform_class_wireless_set_parallel_charge(unsigned int role,
						bool parallel)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_set_parallel_charge))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_set_parallel_charge(parallel,
						       temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_set_parallel_charge);

int platform_class_wireless_get_vout_setted(unsigned int role, int *vout_setted)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_get_vout_setted))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_get_vout_setted(vout_setted,
						   temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_get_vout_setted);

int platform_class_wireless_get_poweroff_err_code(unsigned int role,
						  u8 *err_code)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_get_poweroff_err_code))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_get_poweroff_err_code(err_code,
							 temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_get_poweroff_err_code);

int platform_class_wireless_get_rx_err_code(unsigned int role, u8 *err_code)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_get_rx_err_code))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_get_rx_err_code(err_code, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_get_rx_err_code);

int platform_class_wireless_get_tx_err_code(unsigned int role, u8 *err_code)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_get_tx_err_code))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_get_tx_err_code(err_code, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_get_tx_err_code);

int platform_class_wireless_get_project_vendor(unsigned int role,
					       int *project_vendor)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_get_project_vendor))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_get_project_vendor(project_vendor,
						      temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_get_project_vendor);

int platform_class_wireless_check_i2c_is_ok(unsigned int role)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_check_i2c_is_ok))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_check_i2c_is_ok(temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_check_i2c_is_ok);

int platform_class_wireless_enable_rev_fod(unsigned int role, bool enable)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_enable_rev_fod))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_enable_rev_fod(enable, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_enable_rev_fod);

int platform_class_wireless_send_tx_q_value(unsigned int role, u8 value)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_send_tx_q_value))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_send_tx_q_value(value, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_send_tx_q_value);

int platform_class_wireless_set_tx_fan_speed(unsigned int role, int value)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_set_tx_fan_speed))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_set_tx_fan_speed(value, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_set_tx_fan_speed);

int platform_class_wireless_get_tx_fan_speed(unsigned int role, int *value)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_get_tx_fan_speed))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_get_tx_fan_speed(value, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_get_tx_fan_speed);

int platform_class_wireless_set_rx_offset(unsigned int role, int rx_offset)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_set_rx_offset))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_set_rx_offset(rx_offset, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_set_rx_offset);

int platform_class_wireless_get_rx_offset(unsigned int role, int *rx_offset)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_get_rx_offset))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_get_rx_offset(rx_offset, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_get_rx_offset);

int platform_class_wireless_set_rx_sleep_mode(unsigned int role,
					      int sleep_for_dam)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_set_rx_sleep_mode))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_set_rx_sleep_mode(sleep_for_dam,
						     temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_set_rx_sleep_mode);

int platform_class_wireless_download_fw_from_bin(unsigned int role)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_download_fw_from_bin))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_download_fw_from_bin(temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_download_fw_from_bin);

int platform_class_wireless_erase_fw(unsigned int role)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_erase_fw))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_erase_fw(temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_erase_fw);

int platform_class_wireless_get_fw_version_check(unsigned int role,
						 u8 *check_result)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_get_fw_version_check))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_get_fw_version_check(check_result,
							temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_get_fw_version_check);

int platform_class_wireless_download_fw(unsigned int role)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_download_fw))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_download_fw(temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_download_fw);

int platform_class_wireless_set_confirm_data(unsigned int role, u8 confirm_data)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_set_confirm_data))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_set_confirm_data(temp_data->data,
						    confirm_data);
}
EXPORT_SYMBOL(platform_class_wireless_set_confirm_data);

int platform_class_wireless_receive_test_cmd(unsigned int role, u8 *rev_data,
					     int *length)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_receive_test_cmd))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_receive_test_cmd(rev_data, length,
						    temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_receive_test_cmd);

int platform_class_wireless_process_factory_cmd(unsigned int role, u8 cmd)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_process_factory_cmd))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_process_factory_cmd(cmd, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_process_factory_cmd);

int platform_class_wireless_get_hall_gpio_status(unsigned int role,
						 bool *status)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_get_hall_gpio_status))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_get_hall_gpio_status(status,
							temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_get_hall_gpio_status);

int platform_class_wireless_get_magnetic_case_flag(unsigned int role,
						   bool *status)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data,
					  wls_get_magnetic_case_flag))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_get_magnetic_case_flag(status,
							  temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_get_magnetic_case_flag);

int platform_class_wireless_check_firmware_state(unsigned int role,
						 bool *update)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_check_firmware_state))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_check_firmware_state(update,
							temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_check_firmware_state);

int platform_class_wireless_set_debug_fod(unsigned int role, int *args,
					  int count)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_set_debug_fod))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_set_debug_fod(args, count, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_set_debug_fod);

int platform_class_wireless_get_debug_fod_type(unsigned int role,
					       WLS_DEBUG_SET_FOD_TYPE *type)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_get_debug_fod_type))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_get_debug_fod_type(type, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_get_debug_fod_type);

int platform_class_wireless_set_debug_fod_params(unsigned int role)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_set_debug_fod_params))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_set_debug_fod_params(temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_set_debug_fod_params);

int platform_class_wireless_enable_vsys_ctrl(unsigned int role, bool enable)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_enable_vsys_ctrl))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_enable_vsys_ctrl(enable, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_enable_vsys_ctrl);

int platform_class_wireless_get_trx_isense(unsigned int role, int *isense)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_get_trx_isense))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_get_trx_isense(isense, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_get_trx_isense);

int platform_class_wireless_get_trx_vrect(unsigned int role, int *vrect)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_get_trx_vrect))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_get_trx_vrect(vrect, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_get_trx_vrect);

int platform_class_wireless_get_phone_case_category(unsigned int role, int *category)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data = platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_get_phone_case_category))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_get_phone_case_category(category, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_get_phone_case_category);

int platform_class_wireless_set_phone_case_category(unsigned int role, int category)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data = platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_set_phone_case_category))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_set_phone_case_category(category, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_set_phone_case_category);

int platform_class_wireless_switch_bridge(unsigned int role, bool full)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_switch_bridge))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_switch_bridge(full, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_switch_bridge);

int platform_class_wireless_get_pen_hall3(unsigned int role, int *val)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_get_pen_hall3))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_get_pen_hall3(val, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_get_pen_hall3);

int platform_class_wireless_get_pen_hall3_s(unsigned int role, int *val)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_get_pen_hall3_s))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_get_pen_hall3_s(val, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_get_pen_hall3_s);

int platform_class_wireless_get_pen_hall4(unsigned int role, int *val)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_get_pen_hall4))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_get_pen_hall4(val, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_get_pen_hall4);

int platform_class_wireless_get_pen_hall4_s(unsigned int role, int *val)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_get_pen_hall4_s))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_get_pen_hall4_s(val, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_get_pen_hall4_s);

int platform_class_wireless_get_pen_hall_ppe_n(unsigned int role, int *val)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_get_pen_hall_ppe_n))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_get_pen_hall_ppe_n(val, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_get_pen_hall_ppe_n);

int platform_class_wireless_get_pen_hall_ppe_s(unsigned int role, int *val)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_get_pen_hall_ppe_s))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_get_pen_hall_ppe_s(val, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_get_pen_hall_ppe_s);

int platform_class_wireless_get_pen_full_flag(unsigned int role, bool *flag)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_get_pen_full_flag))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_get_pen_full_flag(flag, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_get_pen_full_flag);

int platform_class_wireless_get_pen_place_err(unsigned int role, int *err)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_get_pen_place_err))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_get_pen_place_err(err, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_get_pen_place_err);

int platform_class_wireless_set_pen_place_err(unsigned int role, int err)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_set_pen_place_err))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_set_pen_place_err(err, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_set_pen_place_err);

int platform_class_wireless_get_pen_mac(unsigned int role, u8 *mac)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_get_pen_mac))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_get_pen_mac(mac, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_get_pen_mac);

int platform_class_wireless_get_pen_soc(unsigned int role, int *soc)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_get_pen_soc))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_get_pen_soc(soc, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_get_pen_soc);

int platform_class_wireless_get_reverse_chg_en(unsigned int role, bool *en)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_get_reverse_chg_en))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_get_reverse_chg_en(en, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_get_reverse_chg_en);

int platform_class_wireless_set_hboost_enable(unsigned int role, bool en)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_set_hboost_enable))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_set_hboost_enable(en, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_set_hboost_enable);

int platform_class_wireless_set_charge_type(unsigned int role, int type)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_set_charge_type))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_set_charge_type(type, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_set_charge_type);

int platform_class_wireless_set_external_boost_enable(unsigned int role, bool en)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_set_external_boost_enable))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_set_external_boost_enable(en, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_set_external_boost_enable);

int platform_class_wireless_get_tx_iout(unsigned int role, int *iout)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_get_tx_iout))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_get_tx_iout(iout, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_get_tx_iout);

int platform_class_wireless_get_tx_vout(unsigned int role, int *vout)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_get_tx_vout))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_get_tx_vout(vout, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_get_tx_vout);

int platform_class_wireless_get_rx_brg_status(unsigned int role, int *status)
{
	guard(srcu)(&wireless_provider_srcu);
	struct platform_wireless_class_ops_data *temp_data =
		platform_wireless_class_get_ic_ops(role);

	if (platform_wireless_ops_invalid(temp_data, wls_get_rx_brg_status))
		return -EOPNOTSUPP;

	return temp_data->ops->wls_get_rx_brg_status(status, temp_data->data);
}
EXPORT_SYMBOL(platform_class_wireless_get_rx_brg_status);

static int
platform_wireless_dev_parse_dt(struct platform_wireless_dev *wireless)
{
	struct device_node *node = wireless->dev->of_node;
	int count = 0;
	int ret = 0;
	int i;

	if (!node) {
		mca_log_err("device tree info missing\n");
		return -1;
	}
	ret = mca_parse_dts_u32(node, "wireless-num", &wireless->wireless_num,
				1);
	if (ret) {
		mca_log_err("get wireless-num fail\n");
		return ret;
	}

	count = mca_parse_dts_count_strings(node, "wireless-dir-list",
					    MCA_WIRELESS_MAX_NUM, 1);
	if (count <= 0 || count > MCA_WIRELESS_MAX_NUM || count != wireless->wireless_num)
		return -EINVAL;

	for (i = 0; i < count; i++) {
		ret = mca_parse_dts_string_index(
			node, "wireless-dir-list", i,
			&(wireless->wireless_dir_list[i]));
		if (ret < 0) {
			mca_log_err(
				"Unable to read wireless-dir-list strings[%d]\n",
				i);
			return ret;
		}
	}

	mca_log_info("%s success\n", __func__);
	return ret;
}

static ssize_t wireless_sysfs_show(struct device *dev,
				   struct device_attribute *attr, char *buf);

static ssize_t wireless_sysfs_store(struct device *dev,
				    struct device_attribute *attr,
				    const char *buf, size_t count);

static struct mca_sysfs_attr_info wireless_sysfs_field_tbl[] = {
	mca_sysfs_attr_ro(wireless_sysfs, 0440, RX_SYSFS_RX_VOUT, rx_vout),
	mca_sysfs_attr_ro(wireless_sysfs, 0440, RX_SYSFS_RX_VRECT, rx_vrect),
	mca_sysfs_attr_ro(wireless_sysfs, 0440, RX_SYSFS_RX_IOUT, rx_iout),
	mca_sysfs_attr_rw(wireless_sysfs, 0660, RX_SYSFS_FW_VERSION,
			  fw_version),
	mca_sysfs_attr_wo(wireless_sysfs, 0220, RX_SYSFS_FW_BIN, wls_bin),
	mca_sysfs_attr_rw(wireless_sysfs, 0660, RX_SYSFS_SLEEP_RX, sleep_rx),
	mca_sysfs_attr_rw(wireless_sysfs, 0660, RX_SYSFS_TX_ADAPTER,
			  tx_adapter),
	mca_sysfs_attr_rw(wireless_sysfs, 0660, RX_SYSFS_BT_STATE, bt_state),
	mca_sysfs_attr_rw(wireless_sysfs, 0660, RX_SYSFS_RX_CEP, rx_cep),
	mca_sysfs_attr_rw(wireless_sysfs, 0660, RX_SYSFS_RX_CR, rx_cr),
	mca_sysfs_attr_rw(wireless_sysfs, 0660, RX_SYSFS_TX_MAC, tx_mac),
	mca_sysfs_attr_rw(wireless_sysfs, 0660, RX_SYSFS_WLS_DIE_TEMP,
			  wls_die_temp),
	mca_sysfs_attr_rw(wireless_sysfs, 0660, RX_SYSFS_WLS_TX_SPEED,
			  wls_tx_speed),
	mca_sysfs_attr_rw(wireless_sysfs, 0660, RX_SYSFS_RX_SS, rx_ss),
	mca_sysfs_attr_rw(wireless_sysfs, 0660, RX_SYSFS_RX_OFFSET, rx_offset),
	mca_sysfs_attr_rw(wireless_sysfs, 0660, RX_SYSFS_RX_SLEEP_MODE,
			  rx_sleep_mode),
	mca_sysfs_attr_ro(wireless_sysfs, 0440, RX_SYSFS_TX_UUID, tx_uuid),
};

#define WIRELESS_SYSFS_ATTRS_SIZE ARRAY_SIZE(wireless_sysfs_field_tbl)

static struct attribute *wireless_sysfs_attrs[WIRELESS_SYSFS_ATTRS_SIZE + 1];

static const struct attribute_group wireless_sysfs_attr_group = {
	.attrs = wireless_sysfs_attrs,
};

static ssize_t wireless_sysfs_show(struct device *dev,
				   struct device_attribute *attr, char *buf)
{
	struct mca_sysfs_attr_info *attr_info;
	int *wireless_index;
	union platform_wireless_propval val = {};
	int ret;
	ssize_t count = 0;
	u8 uuid[4] = { 0 };

	attr_info = mca_sysfs_lookup_attr(attr->attr.name,
					  wireless_sysfs_field_tbl,
					  WIRELESS_SYSFS_ATTRS_SIZE);
	if (!attr_info)
		return -ENODEV;

	wireless_index = (int *)dev_get_drvdata(dev);
	if (!wireless_index) {
		mca_log_err("%s dev_driverdata is null\n", __func__);
		return -ENODEV;
	}

	switch (attr_info->sysfs_attr_name) {
	case RX_SYSFS_RX_VOUT:
		ret = platform_class_wireless_get_vout(*wireless_index,
						 &(val.intval));
		if (ret)
			return ret;
		count = scnprintf(buf, PAGE_SIZE, "%d\n", val.intval);
		break;
	case RX_SYSFS_RX_VRECT:
		ret = platform_class_wireless_get_vrect(*wireless_index,
						  &(val.intval));
		if (ret)
			return ret;
		count = scnprintf(buf, PAGE_SIZE, "%d\n", val.intval);
		break;
	case RX_SYSFS_RX_IOUT:
		ret = platform_class_wireless_get_iout(*wireless_index,
						 &(val.intval));
		if (ret)
			return ret;
		count = scnprintf(buf, PAGE_SIZE, "%d\n", val.intval);
		break;
	case RX_SYSFS_FW_VERSION:
		ret = platform_class_wireless_get_fw_version(*wireless_index,
						       val.strval);
		if (ret)
			return ret;
		count = scnprintf(buf, PAGE_SIZE, "%s\n", val.strval);
		break;
	case RX_SYSFS_TX_ADAPTER:
		ret = platform_class_wireless_get_tx_adapter(*wireless_index,
						       &(val.intval));
		if (ret)
			return ret;
		count = scnprintf(buf, PAGE_SIZE, "%d\n", val.intval);
		break;
	case RX_SYSFS_BT_STATE:
	case RX_SYSFS_RX_CEP:
	case RX_SYSFS_RX_CR:
	case RX_SYSFS_TX_MAC:
		return -EOPNOTSUPP;
	case RX_SYSFS_WLS_DIE_TEMP:
		ret = platform_class_wireless_get_temp(*wireless_index,
						 &(val.intval));
		if (ret)
			return ret;
		count = scnprintf(buf, PAGE_SIZE, "%d\n", val.intval);
		break;
	case RX_SYSFS_WLS_TX_SPEED:
		ret = platform_class_wireless_get_tx_fan_speed(*wireless_index,
							 &(val.intval));
		if (ret)
			return ret;
		count = scnprintf(buf, PAGE_SIZE, "%d\n", val.intval);
		break;
	case RX_SYSFS_RX_SS:
		ret = platform_class_wireless_get_ss_voltage(*wireless_index,
						       &(val.intval));
		if (ret)
			return ret;
		count = scnprintf(buf, PAGE_SIZE, "%d\n", val.intval);
		break;
	case RX_SYSFS_RX_OFFSET:
		ret = platform_class_wireless_get_rx_offset(*wireless_index,
						      &(val.intval));
		if (ret)
			return ret;
		count = scnprintf(buf, PAGE_SIZE, "%d\n", val.intval);
		break;
	case RX_SYSFS_TX_UUID:
		ret = platform_class_wireless_get_tx_uuid(*wireless_index, uuid);
		if (ret)
			return ret;
		count = scnprintf(buf, PAGE_SIZE, "%02x.%02x.%02x.%02x\n",
				  uuid[0], uuid[1], uuid[2], uuid[3]);
		break;
	default:
		return -EOPNOTSUPP;
	}

	return count;
}

static ssize_t wireless_sysfs_store(struct device *dev,
				    struct device_attribute *attr,
				    const char *buf, size_t count)
{
	struct mca_sysfs_attr_info *attr_info;
	int *wireless_index;
	union platform_wireless_propval val = {};
	int ret;

	attr_info = mca_sysfs_lookup_attr(attr->attr.name,
					  wireless_sysfs_field_tbl,
					  WIRELESS_SYSFS_ATTRS_SIZE);
	if (!attr_info)
		return -ENODEV;

	wireless_index = (int *)dev_get_drvdata(dev);
	if (!wireless_index) {
		mca_log_err("%s dev_driverdata is null\n", __func__);
		return -ENODEV;
	}

	switch (attr_info->sysfs_attr_name) {
	case RX_SYSFS_FW_VERSION:
		return -EOPNOTSUPP;
	case RX_SYSFS_FW_BIN:
		ret = platform_class_wireless_set_fw_bin(*wireless_index, buf,
						   (int)count);
		if (ret)
			return ret;
		break;
	case RX_SYSFS_SLEEP_RX:
		if (kstrtoint(buf, 10, &val.intval))
			return -EINVAL;
		if (val.intval != 0 && val.intval != 1)
			return -EINVAL;
		ret = platform_class_wireless_set_enable_mode(*wireless_index,
							val.intval);
		if (ret)
			return ret;
		break;
	case RX_SYSFS_WLS_TX_SPEED:
		if (kstrtoint(buf, 10, &val.intval))
			return -EINVAL;
		ret = platform_class_wireless_set_tx_fan_speed(*wireless_index,
							 val.intval);
		if (ret)
			return ret;
		break;
	case RX_SYSFS_RX_OFFSET:
		if (kstrtoint(buf, 10, &val.intval))
			return -EINVAL;
		ret = platform_class_wireless_set_rx_offset(*wireless_index,
						      val.intval);
		if (ret)
			return ret;
		break;
	case RX_SYSFS_RX_SLEEP_MODE:
		if (kstrtoint(buf, 10, &val.intval))
			return -EINVAL;
		ret = platform_class_wireless_set_rx_sleep_mode(*wireless_index,
							  val.intval);
		if (ret)
			return ret;
		break;
	default:
		return -EOPNOTSUPP;
	}

	return count;
}

static const char *const wireless_dev_list[] = {
	[WIRELESS_ROLE_MASTER] = "wireless_master",
	[WIRELESS_ROLE_SLAVE] = "wireless_slave",
};

static void wireless_sysfs_remove_groups(void *data)
{
	struct platform_wireless_dev *wireless = data;
	int i;

	for (i = wireless->wireless_num - 1; i >= 0; i--)
		if (wireless->sysfs_dev[i])
			mca_sysfs_remove_group("xm_power", wireless->sysfs_dev[i],
					       &wireless_sysfs_attr_group);
}

static int platform_wireless_class_probe(struct platform_device *pdev)
{
	struct platform_wireless_dev *wireless;
	unsigned long roles = 0;
	int i, role, ret;

	wireless = devm_kzalloc(&pdev->dev, sizeof(*wireless), GFP_KERNEL);
	if (!wireless)
		return -ENOMEM;
	wireless->dev = &pdev->dev;
	ret = platform_wireless_dev_parse_dt(wireless);
	if (ret)
		return ret;
	for (i = 0; i < wireless->wireless_num; i++) {
		role = match_string(wireless_dev_list, ARRAY_SIZE(wireless_dev_list),
				    wireless->wireless_dir_list[i]);
		if (role < 0 || test_and_set_bit(role, &roles))
			return -EINVAL;
		wireless->wireless_dev_index[i] = role;
	}
	ret = devm_add_action_or_reset(&pdev->dev, wireless_sysfs_remove_groups, wireless);
	if (ret)
		return ret;
	mca_sysfs_init_attrs(wireless_sysfs_attrs, wireless_sysfs_field_tbl,
			     WIRELESS_SYSFS_ATTRS_SIZE);
	for (i = 0; i < wireless->wireless_num; i++) {
		wireless->sysfs_dev[i] = mca_sysfs_create_group("xm_power",
				wireless->wireless_dir_list[i], &wireless_sysfs_attr_group);
		if (!wireless->sysfs_dev[i])
			return -ENODEV;
		dev_set_drvdata(wireless->sysfs_dev[i], &wireless->wireless_dev_index[i]);
	}
	return 0;
}

static const struct of_device_id match_table[] = {
	{ .compatible = "mca,platform_wireless" },
	{},
};

static struct platform_driver platform_wireless_class_driver = {
	.driver	= {
		.name = "platform_wireless_class",
		.of_match_table = match_table,
	},
	.probe = platform_wireless_class_probe,
};

module_platform_driver(platform_wireless_class_driver);
MODULE_DESCRIPTION("platform wireless charge class");
MODULE_AUTHOR("wuliyang@xiaomi.com");
MODULE_LICENSE("GPL v2");
