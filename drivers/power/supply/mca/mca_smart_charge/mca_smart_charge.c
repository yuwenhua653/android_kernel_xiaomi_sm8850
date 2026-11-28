// SPDX-License-Identifier: GPL-2.0
/*
 * mca_smart_charge.c
 *
 * smart_charge driver
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
#include <linux/mutex.h>
#include <linux/overflow.h>
#include <linux/srcu.h>
#include <linux/string.h>
#include <linux/init.h>
#include <linux/module.h>
#include <linux/slab.h>
#include <linux/of.h>
#include <linux/of_device.h>
#include <linux/workqueue.h>
#include <linux/jiffies.h>
#include <linux/err.h>
#include <linux/platform_device.h>
#include <linux/thermal.h>
#include <mca/protocol/protocol_class.h>
#include <mca/strategy/strategy_class.h>
#include <mca/strategy/strategy_fg_class.h>
#include <mca/strategy/strategy_soc_limit.h>
#include <mca/common/mca_event.h>
#include <mca/common/mca_log.h>
#include <mca/common/mca_parse_dts.h>
#include <mca/common/mca_voter.h>
#include <mca/common/mca_sysfs.h>
#include <mca/common/mca_panel.h>
#include <mca/smartchg/smart_chg_class.h>
#include "inc/mca_smart_charge.h"
#include <mca/common/mca_charge_mievent.h>
#include <mca/common/mca_hwid.h>
#include <mca/shared_memory/charger_partition_class.h>
#include <linux/ktime.h>
#include "hwid.h"

#ifndef MCA_LOG_TAG
#define MCA_LOG_TAG "mca_smart_charge"
#endif
#ifndef BIT
#define BIT(x) (1 << (x))
#endif

#define SMART_CHG_SOCLMT_TRIG_DEFAULT 80
#define SMART_CHG_SOCLMT_CANCEL_DEFAULT 5
#define SMART_CHARGE_DELTA_FV_DEFAULT_VALUE 0
#define SMART_CHARGE_DELTA_ICHG_DEFAULT_VALUE 0
#define SMART_CHARGE_DTPT_DELTA_VALUE 15
#define SMART_CHARGE_FAKE_SCENE_DEFAULT -1

static struct smart_charge_info __rcu *global_smartchg_info;
static DEFINE_MUTEX(smartchg_info_lock);
DEFINE_STATIC_SRCU(smartchg_info_srcu);

static int smart_charge_publish(struct smart_charge_info *info)
{
	int ret = 0;

	mutex_lock(&smartchg_info_lock);
	if (rcu_access_pointer(global_smartchg_info))
		ret = -EBUSY;
	else
		rcu_assign_pointer(global_smartchg_info, info);
	mutex_unlock(&smartchg_info_lock);
	return ret;
}

static void smart_charge_unpublish(struct smart_charge_info *info)
{
	bool removed = false;

	mutex_lock(&smartchg_info_lock);
	if (rcu_access_pointer(global_smartchg_info) == info) {
		RCU_INIT_POINTER(global_smartchg_info, NULL);
		removed = true;
	}
	mutex_unlock(&smartchg_info_lock);
	if (removed)
		synchronize_srcu(&smartchg_info_srcu);
}

static struct mca_smartchg_if_ops __rcu
	*g_mca_smartchg_if_ops[MCA_SMARTCHG_IF_CHG_TYPE_END];
static DEFINE_MUTEX(smartchg_if_lock);
DEFINE_STATIC_SRCU(smartchg_if_srcu);
static void smart_charge_report_scene(struct smart_charge_info *info,
				      int scene);

/* The caller must hold smartchg_if_srcu across the whole callback. */
static struct mca_smartchg_if_ops *mca_smartchg_if_get_ops(unsigned int type)
{
	if (type >= MCA_SMARTCHG_IF_CHG_TYPE_END)
		return NULL;
	return srcu_dereference(g_mca_smartchg_if_ops[type], &smartchg_if_srcu);
}

int mca_smartchg_if_ops_register(struct mca_smartchg_if_ops *ops)
{
	struct mca_smartchg_if_ops *entry;
	int ret = 0;

	if (!ops || (unsigned int)ops->type >= MCA_SMARTCHG_IF_CHG_TYPE_END)
		return -EINVAL;
	entry = kmemdup(ops, sizeof(*entry), GFP_KERNEL);
	if (!entry)
		return -ENOMEM;

	mutex_lock(&smartchg_if_lock);
	if (rcu_access_pointer(g_mca_smartchg_if_ops[entry->type]))
		ret = -EBUSY;
	else
		rcu_assign_pointer(g_mca_smartchg_if_ops[entry->type], entry);
	mutex_unlock(&smartchg_if_lock);
	if (ret)
		kfree(entry);
	return ret;
}
EXPORT_SYMBOL(mca_smartchg_if_ops_register);

int mca_smartchg_if_ops_unregister(unsigned int type, void *data)
{
	struct mca_smartchg_if_ops *entry;

	if (type >= MCA_SMARTCHG_IF_CHG_TYPE_END)
		return -EINVAL;

	/* Serialize replacement with the grace period for the old provider. */
	mutex_lock(&smartchg_if_lock);
	entry = rcu_access_pointer(g_mca_smartchg_if_ops[type]);
	if (!entry || entry->data != data) {
		mutex_unlock(&smartchg_if_lock);
		return -ENOENT;
	}
	RCU_INIT_POINTER(g_mca_smartchg_if_ops[type], NULL);
	synchronize_srcu(&smartchg_if_srcu);
	mutex_unlock(&smartchg_if_lock);
	kfree(entry);
	return 0;
}
EXPORT_SYMBOL(mca_smartchg_if_ops_unregister);

static void mca_smartchg_if_cleanup(void)
{
	struct mca_smartchg_if_ops *entries[MCA_SMARTCHG_IF_CHG_TYPE_END];
	int i;

	mutex_lock(&smartchg_if_lock);
	for (i = 0; i < MCA_SMARTCHG_IF_CHG_TYPE_END; i++) {
		entries[i] = rcu_access_pointer(g_mca_smartchg_if_ops[i]);
		RCU_INIT_POINTER(g_mca_smartchg_if_ops[i], NULL);
	}
	synchronize_srcu(&smartchg_if_srcu);
	mutex_unlock(&smartchg_if_lock);
	for (i = 0; i < MCA_SMARTCHG_IF_CHG_TYPE_END; i++)
		kfree(entries[i]);
}

static ssize_t smart_charge_sysfs_show(struct device *dev,
				       struct device_attribute *attr,
				       char *buf);
static ssize_t smart_charge_sysfs_store(struct device *dev,
					struct device_attribute *attr,
					const char *buf, size_t count);

struct mca_sysfs_attr_info smartchg_sysfs_field_tbl[] = {
	mca_sysfs_attr_rw(smart_charge_sysfs, 0664, MCA_PROP_SMARTCHG,
			  smart_chg),
	mca_sysfs_attr_rw(smart_charge_sysfs, 0664, MCA_PROP_SMARTCHG_FV,
			  smart_fv),
	mca_sysfs_attr_rw(smart_charge_sysfs, 0664, MCA_PROP_SMARTCHG_ICHG,
			  smart_ichg),
	mca_sysfs_attr_rw(smart_charge_sysfs, 0664, MCA_PROP_SMARTBATT,
			  smart_batt),
	mca_sysfs_attr_rw(smart_charge_sysfs, 0664, MCA_PROP_SMARTNIGHT,
			  smart_night),
	mca_sysfs_attr_ro(smart_charge_sysfs, 0440, MCA_PROP_POSTURE, posture),
	mca_sysfs_attr_rw(smart_charge_sysfs, 0664, MCA_PROP_SCENE, scene),
	mca_sysfs_attr_rw(smart_charge_sysfs, 0664, MCA_PROP_BOARD_TEMP,
			  board_temp),
	mca_sysfs_attr_rw(smart_charge_sysfs, 0664, MCA_PROP_SMART_SIC_MODE,
			  smart_sic_mode),
};

#define SMARTCHG_SYSFS_ATTRS_SIZE ARRAY_SIZE(smartchg_sysfs_field_tbl)

static struct attribute *smartchg_sysfs_attrs[SMARTCHG_SYSFS_ATTRS_SIZE + 1];

static const struct attribute_group smartchg_sysfs_attr_group = {
	.attrs = smartchg_sysfs_attrs,
};

static void smart_charge_set_scene(struct smart_charge_info *info, int scene)
{
	if (!info || !READ_ONCE(info->ready) || READ_ONCE(info->stopping))
		return;
	if (scene >= SMART_CHG_SCENE_NORMAL && scene < SMART_CHG_SCENE_INDEX_MAX) {
		smart_charge_report_scene(info, scene);
		info->scene = scene;
	} else if (scene >= SMART_CHG_SCENE_REDIR_START &&
		   scene < SMART_CHG_SCENE_REDIR_INDEX_MAX) {
		info->fake_scene = scene - SMART_CHG_SCENE_REDIR_START;
	} else if (scene == SMART_CHARGE_FAKE_SCENE_DEFAULT) {
		info->fake_scene = SMART_CHARGE_FAKE_SCENE_DEFAULT;
	}
	cancel_delayed_work_sync(&info->smart_sense_chg_work);
	schedule_delayed_work(&info->smart_sense_chg_work, 0);
}

void mca_smartchg_set_scene(int scene)
{
	struct smart_charge_info *info;
	int idx = srcu_read_lock(&smartchg_info_srcu);

	info = srcu_dereference(global_smartchg_info, &smartchg_info_srcu);
	smart_charge_set_scene(info, scene);
	srcu_read_unlock(&smartchg_info_srcu, idx);
}
EXPORT_SYMBOL(mca_smartchg_set_scene);

int mca_smartchg_get_scene(void)
{
	struct smart_charge_info *info;
	int ret = 0, idx = srcu_read_lock(&smartchg_info_srcu);

	info = srcu_dereference(global_smartchg_info, &smartchg_info_srcu);
	if (info && !READ_ONCE(info->stopping))
		ret = info->fake_scene != SMART_CHARGE_FAKE_SCENE_DEFAULT ?
			info->fake_scene : info->scene;
	srcu_read_unlock(&smartchg_info_srcu, idx);
	return ret;
}
EXPORT_SYMBOL(mca_smartchg_get_scene);

void mca_smartchg_set_board_temp(int board_temp)
{
	struct smart_charge_info *info;
	int idx = srcu_read_lock(&smartchg_info_srcu);

	info = srcu_dereference(global_smartchg_info, &smartchg_info_srcu);
	if (info && !READ_ONCE(info->stopping))
		WRITE_ONCE(info->board_temp, board_temp);
	srcu_read_unlock(&smartchg_info_srcu, idx);
}
EXPORT_SYMBOL(mca_smartchg_set_board_temp);

int mca_smartchg_get_board_temp(void)
{
	struct smart_charge_info *info;
	int ret = 0, idx = srcu_read_lock(&smartchg_info_srcu);

	info = srcu_dereference(global_smartchg_info, &smartchg_info_srcu);
	if (info && !READ_ONCE(info->stopping))
		ret = READ_ONCE(info->board_temp);
	srcu_read_unlock(&smartchg_info_srcu, idx);
	return ret;
}
EXPORT_SYMBOL(mca_smartchg_get_board_temp);

int mca_smartchg_is_extreme_cold_enabled(void)
{
	struct smart_charge_info *info;
	int ret = 0, idx = srcu_read_lock(&smartchg_info_srcu);

	info = srcu_dereference(global_smartchg_info, &smartchg_info_srcu);
	if (info && !READ_ONCE(info->stopping))
		ret = info->smart_chg_data.smart_chgcfg[SMART_CHG_EXTREME_COLD].enable == 1;
	srcu_read_unlock(&smartchg_info_srcu, idx);
	return ret;
}
EXPORT_SYMBOL(mca_smartchg_is_extreme_cold_enabled);

int mca_smartchg_get_limit_soc(void)
{
	struct smart_charge_info *info;
	int ret = 0, idx = srcu_read_lock(&smartchg_info_srcu);

	info = srcu_dereference(global_smartchg_info, &smartchg_info_srcu);
	if (info && !READ_ONCE(info->stopping) && info->soc_limit_enable)
		ret = info->soc_limit;
	srcu_read_unlock(&smartchg_info_srcu, idx);
	return ret;
}
EXPORT_SYMBOL(mca_smartchg_get_limit_soc);

static void smart_charge_report_scene(struct smart_charge_info *info, int scene)
{
	int report_scene = 0;
	int len = 0;
	char event[MCA_EVENT_NOTIFY_SIZE] = { 0 };
	struct mca_event_notify_data event_data = { 0 };

	if (scene != info->scene) {
		switch (scene) {
		case SMART_CHG_SCENE_PHONE:
		case SMART_CHG_SCENE_VIDEO:
		case SMART_CHG_SCENE_VIDEOCHAT:
			report_scene = scene;
			break;
		default:
			report_scene = 0;
			break;
		}

		if (report_scene != info->last_report_scene) {
			mca_log_info("report scene: %d => %d\n",
				     info->last_report_scene, report_scene);
			info->last_report_scene = report_scene;

			len = snprintf(event, MCA_EVENT_NOTIFY_SIZE,
				       "MCA_SMARTCHG_SCENE=%d", report_scene);
			event_data.event = event;
			event_data.event_len = len;
			mca_event_report_uevent(&event_data);
		}
	}
}

static void smart_charge_handle_sense_chg(struct smart_charge_info *info)
{
	int posture_st = SMART_CHG_POSTURE_UNKNOW;
	int scene = SMART_CHG_SCENE_NORMAL;
	int sic_mode = SMART_CHG_SIC_MODE_BALANCED;
	bool active_stat = false;
	int len = 0;
	char event[MCA_EVENT_NOTIFY_SIZE] = { 0 };
	struct mca_event_notify_data event_data = { 0 };

	scene = info->fake_scene != SMART_CHARGE_FAKE_SCENE_DEFAULT ?
			info->fake_scene :
			info->scene;
	posture_st =
		info->smart_chg_data.smart_chgcfg[SMART_CHG_SENSE_CHG]
				.use_fake_value ?
			info->smart_chg_data.smart_chgcfg[SMART_CHG_SENSE_CHG]
				.fake_value :
			info->smart_chg_data.smart_chgcfg[SMART_CHG_SENSE_CHG]
				.func_value;

	if (!info->smart_chg_data.smart_chgcfg[SMART_CHG_SENSE_CHG].enable ||
	    posture_st <= SMART_CHG_POSTURE_UNKNOW ||
	    posture_st >= SMART_CHG_POSTURE_INDEX_MAX)
		return;

	switch (scene) {
	case SMART_CHG_SCENE_PHONE:
		active_stat = true;
		if (posture_st >= SMART_CHG_POSTURE_DESKTOP &&
		    posture_st <= SMART_CHG_POSTURE_HOLDER)
			sic_mode = SMART_CHG_SIC_MODE_SUPERCHG;
		else if (posture_st >= SMART_CHG_POSTURE_ONEHAND &&
			 posture_st <= SMART_CHG_POSTURE_TWOHAND_V)
			sic_mode = SMART_CHG_SIC_MODE_MIDDLE;
		else if (posture_st == SMART_CHG_POSTURE_ANS_CALL)
			sic_mode = SMART_CHG_SIC_MODE_BALANCED;
		break;
	case SMART_CHG_SCENE_VIDEO:
	case SMART_CHG_SCENE_VIDEOCHAT:
	case SMART_CHG_SCENE_PER_VIDEO:
		active_stat = true;
		if (posture_st >= SMART_CHG_POSTURE_DESKTOP &&
		    posture_st <= SMART_CHG_POSTURE_HOLDER)
			sic_mode = SMART_CHG_SIC_MODE_SUPERCHG;
		else if (posture_st >= SMART_CHG_POSTURE_ONEHAND &&
			 posture_st <= SMART_CHG_POSTURE_ANS_CALL)
			sic_mode = SMART_CHG_SIC_MODE_BALANCED;
		break;
	case SMART_CHG_SCENE_CLASS0:
	case SMART_CHG_SCENE_PER_CLASS0:
		if (info->support_sensechg_v2) {
			active_stat = true;
			if (posture_st >= SMART_CHG_POSTURE_DESKTOP &&
			    posture_st <= SMART_CHG_POSTURE_HOLDER)
				sic_mode = SMART_CHG_SIC_MODE_SUPERCHG;
			else if (posture_st >= SMART_CHG_POSTURE_ONEHAND &&
				 posture_st <= SMART_CHG_POSTURE_ANS_CALL)
				sic_mode = SMART_CHG_SIC_MODE_BALANCED;
		} else {
			mca_log_err("unsupport scene: %d\n", info->scene);
			return;
		}
		break;
	default:
		mca_log_err("unsupport scene: %d\n", info->scene);
		return;
	}

	if (info->screen_state == 0)
		sic_mode /= 2;

	mca_log_info(
		"active_stat: %d, online: %d, screen_state: %d, scene: %d, posture: %d, smart_sic_mode: %d -> %d\n",
		active_stat, info->online, info->screen_state, scene,
		posture_st, info->smart_sic_mode, sic_mode);
	if (sic_mode != info->smart_sic_mode) {
		info->smart_sic_mode = sic_mode;
		if (active_stat && info->online) {
			len = snprintf(event, MCA_EVENT_NOTIFY_SIZE,
				       "POWER_SUPPLY_SMART_SIC_MODE=%d",
				       info->smart_sic_mode);
			event_data.event = event;
			event_data.event_len = len;
			mca_event_report_uevent(&event_data);
		}
	}
}

//static void smartcharging_handle_soc_limit_process(struct smart_charge_info *info,
//	bool enable, int soc_limit_thre)
//{
//	int curr_soc = 0;
//	static struct mca_smartchg_if_ops *if_ops;

//	if (enable) {
//		curr_soc = strategy_class_fg_ops_get_soc();
//		if (curr_soc >= soc_limit_thre) {
//			mca_log_info("soc_limit_thre = %d\n", soc_limit_thre);
//			info->soc_limit_enable = true;
//			for (int i = 0; i < MCA_SMARTCHG_IF_CHG_TYPE_END; i++) {
//				if_ops = mca_smartchg_if_get_ops(i);
//				if (!if_ops || !if_ops->set_soc_limit_sts)
//					continue;
//				if_ops->set_soc_limit_sts(if_ops->data, info->soc_limit_enable);
//			}
//		} else{
//			cancel_delayed_work_sync(&info->smart_soc_limit_work);
//			schedule_delayed_work(&info->smart_soc_limit_work, msecs_to_jiffies(1000));
//		}
//	} else {
//		mca_log_info("disable soc limit\n");
//		cancel_delayed_work_sync(&info->smart_soc_limit_work);
//		info->soc_limit_enable = true;
//		for (int i = 0; i < MCA_SMARTCHG_IF_CHG_TYPE_END; i++) {
//			if_ops = mca_smartchg_if_get_ops(i);
//			if (!if_ops || !if_ops->set_soc_limit_sts)
//				continue;
//			if_ops->set_soc_limit_sts(if_ops->data, info->soc_limit_enable);
//		}
//	}
//}

static void smart_charge_set_soc_limit(bool enable)
{
	struct mca_smartchg_if_ops *if_ops;
	int idx;

	idx = srcu_read_lock(&smartchg_if_srcu);
	for (int i = 0; i < MCA_SMARTCHG_IF_CHG_TYPE_END; i++) {
		if_ops = mca_smartchg_if_get_ops(i);
		if (!if_ops || !if_ops->set_soc_limit_sts)
			continue;
		if_ops->set_soc_limit_sts(if_ops->data, enable);
	}
	srcu_read_unlock(&smartchg_if_srcu, idx);
}

#define SMART_CHG_SOC_HYS 2
static void smart_charge_soc_limit_workfunc(struct work_struct *work)
{
	struct smart_charge_info *info = container_of(
		work, struct smart_charge_info, smart_soc_limit_work.work);
	int curr_soc = 0;

	if (!READ_ONCE(info->ready) || READ_ONCE(info->stopping))
		return;

	if (!info->online) {
		mca_log_err("adapter is plugout, don't handle soc limit\n");
		return;
	}

	if (info->soc_limit) {
		curr_soc = strategy_class_fg_ops_get_soc();
		mca_log_info("curr_soc = %d, soc_limit_thre = %d\n", curr_soc,
			     info->soc_limit);
		if (curr_soc >= info->soc_limit) {
			if (info->soc_limit_enable == false) {
				info->soc_limit_enable = true;
				smart_charge_set_soc_limit(
					info->soc_limit_enable);
			}

			if (curr_soc >= info->soc_limit + SMART_CHG_SOC_HYS) {
				if (info->smart_chg_data
					    .smart_chgcfg[SMART_CHG_ENDURANCE_PRO]
					    .enable &&
				    !info->ignore_upload.endurance_pro) {
					mca_charge_mievent_report(
						CHARGE_DFX_SMART_ENDURANCE_SOC_ERR,
						&curr_soc, 1);
					info->ignore_upload.endurance_pro =
						true;
				}
				if (info->smart_chg_data
					    .smart_chgcfg[SMART_CHG_NAVIGATION]
					    .enable &&
				    !info->ignore_upload.navigation) {
					mca_charge_mievent_report(
						CHARGE_DFX_SMART_NAVIGATION_SOC_ERR,
						&curr_soc, 1);
					info->ignore_upload.endurance_pro =
						true;
				}
			}

		} else if (curr_soc <=
			   info->soc_limit - SMART_CHG_SOCLMT_CANCEL_DEFAULT) {
			if (info->soc_limit_enable == true) {
				info->soc_limit_enable = false;
				smart_charge_set_soc_limit(
					info->soc_limit_enable);
			}
		}
		schedule_delayed_work(&info->smart_soc_limit_work,
				      msecs_to_jiffies(1000));
	} else {
		mca_log_info("disable soc limit\n");
		info->soc_limit_enable = false;
		smart_charge_set_soc_limit(info->soc_limit_enable);
	}
	mca_log_info("soc_limit_enable = %d\n", info->soc_limit_enable);
}

/*to handle navigation and smart night algorithm conflict*/
static void
smartcharging_handle_algorithm_conflict(struct smart_charge_info *info)
{
	bool smart_night = false;
	bool smart_navigation = false;
	bool smart_endurance_pro = false;
	uint32_t soc_upper_thre = SMART_CHG_SOCLMT_TRIG_DEFAULT;

	smart_night = info->smart_chg_data.smart_chgcfg[SMART_CHG_NIGHT].enable;
	smart_navigation =
		info->smart_chg_data.smart_chgcfg[SMART_CHG_NAVIGATION].enable;
	smart_endurance_pro =
		info->smart_chg_data.smart_chgcfg[SMART_CHG_ENDURANCE_PRO]
			.enable;

	/*endurance protect is prior to all others, then navigation is prior to smart night charge */
	if (smart_endurance_pro) {
		soc_upper_thre = info->smart_chg_data
					 .smart_chgcfg[SMART_CHG_ENDURANCE_PRO]
					 .func_value;
		mca_log_info("smart_endurance %d, soc_upper_thre:%d",
			     smart_endurance_pro, soc_upper_thre);
	} else if (smart_navigation) {
		soc_upper_thre =
			info->smart_chg_data.smart_chgcfg[SMART_CHG_NAVIGATION]
				.func_value;
		mca_log_info("smart_navigation %d, soc_upper_thre:%d",
			     smart_navigation, soc_upper_thre);
	} else if (smart_night) {
		soc_upper_thre =
			info->smart_chg_data.smart_chgcfg[SMART_CHG_NIGHT]
				.func_value;
		mca_log_info("smart_night %d, soc_upper_thre:%d", smart_night,
			     soc_upper_thre);
	} else {
		soc_upper_thre = 0;
	}
	info->soc_limit = soc_upper_thre;
	cancel_delayed_work_sync(&info->smart_soc_limit_work);
	schedule_delayed_work(&info->smart_soc_limit_work, 0);
	//smartcharging_handle_soc_limit_process(info, !!soc_upper_thre, info->soc_limit);
}

static void smartcharging_handle_wls_super(struct smart_charge_info *info)
{
	struct mca_smartchg_if_ops *if_ops;
	int idx;

	idx = srcu_read_lock(&smartchg_if_srcu);
	for (int i = 0; i < MCA_SMARTCHG_IF_CHG_TYPE_END; i++) {
		if_ops = mca_smartchg_if_get_ops(i);
		if (!if_ops || !if_ops->set_wls_super_sts)
			continue;
		if_ops->set_wls_super_sts(
			if_ops->data,
			info->smart_chg_data.smart_chgcfg[SMART_CHG_WLS_SUPER]
				.enable);
	}
	srcu_read_unlock(&smartchg_if_srcu, idx);
}

static void smartcharging_handle_power_boost(struct smart_charge_info *info,
					     int type)
{
	struct mca_smartchg_if_ops *if_ops;
	int idx;

	idx = srcu_read_lock(&smartchg_if_srcu);
	for (int i = 0; i < MCA_SMARTCHG_IF_CHG_TYPE_END; i++) {
		if_ops = mca_smartchg_if_get_ops(i);
		if (!if_ops || !if_ops->set_pwr_boost_sts)
			continue;
		if (type == SMART_CHG_OUTDOOR_PWR_BOOST)
			if_ops->set_pwr_boost_sts(
				if_ops->data,
				info->smart_chg_data
					.smart_chgcfg[SMART_CHG_OUTDOOR]
					.enable);
		else if (type == SMART_CHG_TRAVELWAIT_PWR_BOOST)
			if_ops->set_pwr_boost_sts(
				if_ops->data,
				info->smart_chg_data
					.smart_chgcfg[SMART_CHG_TRAVELWAIT]
					.enable);
	}
	srcu_read_unlock(&smartchg_if_srcu, idx);
}

static void smartcharging_handle_wls_quiet(struct smart_charge_info *info)
{
	struct mca_smartchg_if_ops *if_ops;
	int idx;

	idx = srcu_read_lock(&smartchg_if_srcu);
	for (int i = 0; i < MCA_SMARTCHG_IF_CHG_TYPE_END; i++) {
		if_ops = mca_smartchg_if_get_ops(i);
		if (!if_ops || !if_ops->set_wls_quiet_sts)
			continue;
		if_ops->set_wls_quiet_sts(
			if_ops->data,
			info->smart_chg_data.smart_chgcfg[SMART_CHG_WLS_QUIET]
				.enable);
	}
	srcu_read_unlock(&smartchg_if_srcu, idx);
}

static void smartcharging_handle_controlmessage(struct smart_charge_info *info)
{
	uint32_t smart_header = info->smart_chg_control.AsUINT32;
	int soc = strategy_class_fg_ops_get_soc();

	if (!info || !READ_ONCE(info->ready) || READ_ONCE(info->stopping))
		return;

	smart_header = (smart_header & 0xFFFE);
	smart_header = (smart_header - 1) & smart_header;
	mca_log_info("smart_header: %d", smart_header);
	if (!smart_header) {
		info->smart_chg_data.ret_code = false;
		mca_log_err("input correct\n");
	} else {
		info->smart_chg_data.ret_code = true;
		mca_log_err("error input invalid\n");
		return;
	}

	mca_log_info(
		"smart_chg_control: enable: %d, func_type: 0x%04x, func_value: %d\n",
		info->smart_chg_control.enable,
		info->smart_chg_control.func_type << 1,
		info->smart_chg_control.func_value);

	if (info->smart_chg_control.navigation) {
		info->smart_chg_data.smart_chgcfg[SMART_CHG_NAVIGATION].enable =
			info->smart_chg_control.enable;
		info->smart_chg_data.smart_chgcfg[SMART_CHG_NAVIGATION]
			.func_value = info->smart_chg_control.soc_limit;
		smartcharging_handle_algorithm_conflict(info);
		if (info->smart_chg_control.enable)
			mca_charge_mievent_report(
				CHARGE_DFX_SMART_NAVIGATION_TRIGGERED, &soc, 1);
		else
			mca_charge_mievent_set_state(
				MIEVENT_STATE_END,
				CHARGE_DFX_SMART_NAVIGATION_TRIGGERED);

		info->ignore_upload.navigation =
			soc >= info->smart_chg_control.soc_limit ? true : false;

	} else if (info->smart_chg_control.endurance_pro) {
		info->smart_chg_data.smart_chgcfg[SMART_CHG_ENDURANCE_PRO]
			.enable = info->smart_chg_control.enable;
		info->smart_chg_data.smart_chgcfg[SMART_CHG_ENDURANCE_PRO]
			.func_value = info->smart_chg_control.soc_limit;
		smartcharging_handle_algorithm_conflict(info);
		if (info->smart_chg_control.enable)
			mca_charge_mievent_report(
				CHARGE_DFX_SMART_ENDURANCE_TRIGGERED, &soc, 1);
		else
			mca_charge_mievent_set_state(
				MIEVENT_STATE_END,
				CHARGE_DFX_SMART_ENDURANCE_TRIGGERED);

		info->ignore_upload.endurance_pro =
			soc >= info->smart_chg_control.soc_limit ? true : false;

	} else if (info->smart_chg_control.outdoor) {
		info->smart_chg_data.smart_chgcfg[SMART_CHG_OUTDOOR].enable =
			info->smart_chg_control.enable;
		info->smart_chg_data.smart_chgcfg[SMART_CHG_OUTDOOR].func_value =
			0;
		smartcharging_handle_power_boost(info,
						 SMART_CHG_OUTDOOR_PWR_BOOST);
	} else if (info->smart_chg_control.wls_super_chg) {
		info->smart_chg_data.smart_chgcfg[SMART_CHG_WLS_SUPER].enable =
			info->smart_chg_control.enable;
		info->smart_chg_data.smart_chgcfg[SMART_CHG_WLS_SUPER]
			.func_value = 0;
		smartcharging_handle_wls_super(info);
	} else if (info->smart_chg_control.lowfast) {
		info->smart_chg_data.smart_chgcfg[SMART_CHG_LOWFAST].enable =
			info->smart_chg_control.enable;
		info->smart_chg_data.smart_chgcfg[SMART_CHG_LOWFAST].func_value =
			0;
	} else if (info->smart_chg_control.wls_quiet) {
		info->smart_chg_data.smart_chgcfg[SMART_CHG_WLS_QUIET].enable =
			info->smart_chg_control.enable;
		info->smart_chg_data.smart_chgcfg[SMART_CHG_WLS_QUIET]
			.func_value = 0;
		smartcharging_handle_wls_quiet(info);
	} else if (info->smart_chg_control.sense_chg) {
		info->smart_chg_data.smart_chgcfg[SMART_CHG_SENSE_CHG].enable =
			info->smart_chg_control.enable;
		if (info->smart_chg_control.func_value >
		    SMART_CHG_POSTURE_FAKE_CLEAR) {
			mca_log_info("debug sense charge, set value: %d\n",
				     info->smart_chg_control.func_value);
			info->smart_chg_data.smart_chgcfg[SMART_CHG_SENSE_CHG]
				.use_fake_value = true;
			info->smart_chg_data.smart_chgcfg[SMART_CHG_SENSE_CHG]
				.fake_value =
				info->smart_chg_control.func_value -
				SMART_CHG_POSTURE_FAKE_CLEAR;
		} else if (info->smart_chg_control.func_value ==
			   SMART_CHG_POSTURE_FAKE_CLEAR) {
			mca_log_info(
				"debug sense charge, cancel fake value: %d\n",
				info->smart_chg_control.func_value);
			info->smart_chg_data.smart_chgcfg[SMART_CHG_SENSE_CHG]
				.use_fake_value = false;
			info->smart_chg_data.smart_chgcfg[SMART_CHG_SENSE_CHG]
				.fake_value = 0;
		} else {
			info->smart_chg_data.smart_chgcfg[SMART_CHG_SENSE_CHG]
				.func_value =
				info->smart_chg_control.func_value;
		}
		smart_charge_handle_sense_chg(info);
	} else if (info->smart_chg_control.extreme_cold) {
		info->smart_chg_data.smart_chgcfg[SMART_CHG_EXTREME_COLD]
			.enable = info->smart_chg_control.enable;
		info->smart_chg_data.smart_chgcfg[SMART_CHG_EXTREME_COLD]
			.func_value = 0;
	} else if (info->smart_chg_control.travel_wait) {
		info->smart_chg_data.smart_chgcfg[SMART_CHG_TRAVELWAIT].enable =
			info->smart_chg_control.enable;
		info->smart_chg_data.smart_chgcfg[SMART_CHG_TRAVELWAIT]
			.func_value = 0;
		smartcharging_handle_power_boost(
			info, SMART_CHG_TRAVELWAIT_PWR_BOOST);
	} else if (info->smart_chg_control.smart_bypass) {
		info->bypass_reserved = 0;
		info->bypass_enable = info->smart_chg_control.enable & 1;
	}
}

static int smartcharging_receive_control_message(struct smart_charge_info *info, int val)
{

	info->smart_chg_control.AsUINT32 = val;
	mca_log_info("smart_chg value is %08x\n", val);
	smartcharging_handle_controlmessage(info);
	return 0;
}

static int get_smart_chg_message(struct smart_charge_info *info)
{
	uint32_t control_header = 0;
	int index = 0;

	control_header |= (info->smart_chg_data.ret_code & 0x01);

	for (index = SMART_CHG_NAVIGATION; index < SMART_CHG_MAX; index++) {
		if (info->smart_chg_data.smart_chgcfg[index].enable)
			control_header |= BIT(index);
		else
			control_header &= ~BIT(index);
	}
	mca_log_info("control_header = %d\n", control_header);
	return control_header;
}

static int handle_smart_batt_message(struct smart_charge_info *info, int val)
{
	int vote_value, ret;

	if (check_mul_overflow(val, info->cell_type, &vote_value))
		return -ERANGE;
	ret = mca_vote(info->smartchg_delta_fv_voter, "smart_batt", true, vote_value);
	if (!ret)
		info->smart_batt_val = val;
	return ret;
}

static int get_smart_batt_message(struct smart_charge_info *info)
{

	return info->smart_batt_val;
}

static int handle_smart_night_message(struct smart_charge_info *info, int val)
{

	info->smart_night_val = val;
	mca_log_info("smart_night_val is %d\n", !!val);
	if (val)
		strategy_class_fg_ops_get_rsoc(&info->night_enable_rsoc);
	if (!!val == 1 || !!val == 0) {
		info->smart_chg_data.smart_chgcfg[SMART_CHG_NIGHT].enable = val;
		info->smart_chg_data.smart_chgcfg[SMART_CHG_NIGHT].func_value =
			SMART_CHG_SOCLMT_TRIG_DEFAULT;
		smartcharging_handle_algorithm_conflict(info);
	}

	return 0;
}

static int get_smart_night_message(struct smart_charge_info *info)
{

	return info->smart_night_val;
}

static int smart_charge_plugin_or_plugout_reset(struct smart_charge_info *info)
{
	return mca_vote(info->smartchg_delta_ichg_voter, "batt_health",
		       !!info->online, info->smart_delta_ichg);
}

static void smart_charge_csd_send_pulse(struct smart_charge_info *info)
{
	int soc = 0, rsoc = 0;
	int batt_temp = 0;
	bool smart_night = false;

	soc = strategy_class_fg_ops_get_soc();
	strategy_class_fg_ops_get_rsoc(&rsoc);
	(void)strategy_class_fg_ops_get_temperature(&batt_temp);
	batt_temp /= 10;
	smart_night = info->smart_chg_data.smart_chgcfg[SMART_CHG_NIGHT].enable;

	if (!info->pulse_mode) {
		if ((soc >= 50 && soc <= 80) &&
		    (batt_temp >= 20 && batt_temp <= 45)) {
			if (info->plugin_rsoc <= 45 && !info->screen_state &&
			    info->cycle_count > 100 &&
			    (info->cycle_count % 25 == 0) && rsoc == 50) {
				info->pulse_mode = 1;
				mca_event_block_notify(MCA_EVENT_CHARGE_STATUS,
						       MCA_EVENT_CSD_SEND_PULSE,
						       &info->pulse_mode);
			} else if (smart_night == true) {
				if (info->night_enable_rsoc <= 45 &&
				    rsoc == 50) {
					info->pulse_mode = 2;
					mca_event_block_notify(
						MCA_EVENT_CHARGE_STATUS,
						MCA_EVENT_CSD_SEND_PULSE,
						&info->pulse_mode);
				} else if (info->night_enable_rsoc > 45 &&
					   rsoc == 76) {
					info->pulse_mode = 3;
					mca_event_block_notify(
						MCA_EVENT_CHARGE_STATUS,
						MCA_EVENT_CSD_SEND_PULSE,
						&info->pulse_mode);
				}
			}
		}
	} else if ((info->cycle_count % 25 != 0) && smart_night == false) {
		info->pulse_mode = 0;
		mca_event_block_notify(MCA_EVENT_CHARGE_STATUS,
				       MCA_EVENT_CSD_SEND_PULSE,
				       &info->pulse_mode);
	}
	mca_log_info(
		"soc: %d, rsoc: %d, plugin_rsoc: %d, night_enable_rsoc: %d, batt_temp: %d, cycle: %d, night: %d, pulse_mode: %d",
		soc, rsoc, info->plugin_rsoc, info->night_enable_rsoc,
		batt_temp, info->cycle_count, smart_night, info->pulse_mode);
}

static int smart_charge_thermal_notifier_cb(struct notifier_block *nb,
					    unsigned long event, void *val)
{
	struct smart_charge_info *info =
		container_of(nb, struct smart_charge_info, thermal_nb);

	if (!val || !READ_ONCE(info->ready) || READ_ONCE(info->stopping))
		return NOTIFY_DONE;

	switch (event) {
	case MCA_EVENT_THERMAL_BOARD_TEMP_CHANGE:
		info->board_temp = *(int *)val / SMART_CHG_BOARD_TEMP_SCALE;
		break;
	default:
		break;
	}
	return NOTIFY_DONE;
}

static void
update_smart_bypass_temp_section(struct smart_charge_info *info,
				 struct smart_bypass_temp_section *sections,
				 unsigned int count)
{
	int board_temp = info->board_temp;
	int cur = info->bypass_temp_index;
	int report_index;
	int i;

	for (i = 0; i < (int)count; i++) {
		if (board_temp >= sections[i].temp_high ||
		    sections[i].temp_low > board_temp)
			continue;

		report_index = cur;
		if (cur < i) {
			if (board_temp >= sections[cur].temp_high +
						  sections[cur].hyst_high) {
				report_index = i;
				info->bypass_temp_index = i;
			}
		} else if (cur > i &&
			   sections[cur].temp_low - sections[cur].hyst_low >
				   board_temp) {
			report_index = i;
			info->bypass_temp_index = i;
		}

		mca_log_err("for_bypass board_temp:%d, cur_temp_index:%d\n",
			    board_temp, report_index);
		return;
	}

	mca_log_err("temp over range invalid, current:%d\n", -1);
}

static void smart_charge_check_bypass_status(struct smart_charge_info *info)
{
	static bool once_flag;
	bool prev = once_flag;

	if (info->bypass_exit_flag) {
		once_flag = false;
		return;
	}

	if (!once_flag) {
		mca_log_err("for_bypass start time\n");
		info->bypass_start_time = ktime_get_boottime();
	} else {
		if (ktime_get_boottime() >
		    info->bypass_start_time + SMART_BYPASS_DEBOUNCE_NS) {
			mca_log_err("for_bypass exit bypass\n");
			mca_vote(info->smartchg_set_fcc_voter, "smart_bypass",
				 false, 0);
			info->bypass_exit_flag = true;
		} else {
			goto debounce;
		}
	}
	once_flag = prev ^ 1;
debounce:
	mca_log_err("for_bypass Debounce: %lld s\n",
		    (ktime_get_boottime() - info->bypass_start_time) /
			    NSEC_PER_SEC);
}

static const int smart_bypass_med_scenes[] = { 0x08, 0x0b, 0x1c,
					       0x3a, 0x3d, 0x4e };
static const int smart_bypass_high_scenes[] = { 0x12, 0x13, 0x14, 0x19,
						0x4b, 0x1f5, 0x2be, 0x2bc };

static bool smart_bypass_scene_in_set(int scene, const int *set, int n)
{
	for (int i = 0; i < n; i++)
		if (set[i] == scene)
			return true;
	return false;
}

static void smart_charge_handle_bypass_chg(struct smart_charge_info *info)
{
	int fcc = 0;
	uint16_t state;
	int soc;

	if (!info->support_bypass)
		return;

	state = info->bypass_enable;
	if (info->bypass_enable == 0)
		goto report;

	soc = strategy_class_fg_ops_get_soc();
	if (soc < info->bypass_entry_soc || soc > info->bypass_exit_soc) {
		mca_log_err("for_bypass soc not in range, quit bypass mode\n");
		state = 0;
		goto report;
	}
	if (info->wls_online) {
		mca_log_err("for_bypass wlschg online, quit bypass mode\n");
		state = 0;
		goto report;
	}

	if (smart_bypass_scene_in_set(info->scene, smart_bypass_med_scenes,
				      ARRAY_SIZE(smart_bypass_med_scenes))) {
		update_smart_bypass_temp_section(info, info->bypass_med_lmt,
						 info->bypass_med_num);
		info->bypass_active = 1;
		fcc = info->bypass_med_lmt[info->bypass_temp_index].fcc;
	} else if (smart_bypass_scene_in_set(
			   info->scene, smart_bypass_high_scenes,
			   ARRAY_SIZE(smart_bypass_high_scenes))) {
		update_smart_bypass_temp_section(info, info->bypass_high_lmt,
						 info->bypass_high_num);
		info->bypass_active = 1;
		fcc = info->bypass_high_lmt[info->bypass_temp_index].fcc;
	} else {
		info->bypass_active = 0;
		smart_charge_check_bypass_status(info);
	}

	if (fcc != 0 && fcc != info->last_bypass_fcc) {
		mca_vote(info->smartchg_set_fcc_voter, "smart_bypass", true,
			 fcc);
		info->bypass_exit_flag = false;
	}

report:
	mca_log_err("for_bypass [%d->%d] fcc[%d %d]\n", info->last_bypass_state,
		    state, fcc, info->last_bypass_fcc);
	if (info->last_bypass_state != state) {
		info->last_bypass_state = state;
		if (state == 0)
			mca_vote(info->smartchg_set_fcc_voter, "smart_bypass",
				 false, 0);
	}
	if (fcc != info->last_bypass_fcc)
		info->last_bypass_fcc = fcc;
}

static void smart_charge_handle_mishow_config(struct smart_charge_info *info)
{
	const struct mca_hwid *hwid = mca_get_hwid_info();
	bool mishow = false;

	if (!hwid || mca_log_get_charge_boot_mode() == 0)
		return;
	if (!hwid->product_name ||
	    (strcmp(hwid->product_name, "bixi") &&
	     strcmp(hwid->product_name, "luming")))
		return;

	charger_partition_get_mishow(&mishow);
	info->mishow_config = mishow;
	mca_log_info("mishow config is %d\n", info->mishow_config);
	if (info->mishow_config)
		smartcharging_handle_algorithm_conflict(info);
}

static void smart_charge_workfunc(struct work_struct *work)
{
	struct smart_charge_info *info = container_of(
		work, struct smart_charge_info, smart_charge_work.work);
	int delta_ichg = 0;
	const struct mca_hwid *hwid = mca_get_hwid_info();

	if (!READ_ONCE(info->ready) || READ_ONCE(info->stopping))
		return;

	//To-Do
	//Battery status monitoring work_func
	if (!info->online) {
		mca_log_err("adapter is plugout\n");
		return;
	}
	/* Retain the last applied reduction on failed gauge reads or votes. */
	if (info->support_cc_ichg &&
	    !strategy_class_fg_ops_get_cyclecount(&info->cycle_count)) {
		for (int i = 0; i < info->ichg_cc_count; i++) {
			if (info->cycle_count <= info->ichg_cc_table[i].cc_max) {
				delta_ichg = info->ichg_cc_table[i].delta_ichg;
				break;
			}
		}
		/* The voter skips successful unchanged values, but retries a prior
		 * backend failure even when the requested reduction is unchanged.
		 */
		if (!mca_vote(info->smartchg_delta_ichg_voter, "batt_health", true, delta_ichg))
			info->smart_delta_ichg = delta_ichg;
	}
	//csd1.0 feature:check battery swelling
	if (hwid && hwid->country_version == CountryCN && info->support_csd)
		smart_charge_csd_send_pulse(info);

	//smart bypass fcc limiter (mishow)
	smart_charge_handle_bypass_chg(info);
	smart_charge_handle_mishow_config(info);

	schedule_delayed_work(&info->smart_charge_work, msecs_to_jiffies(5000));
}

static void smart_charge_sense_chg_workfunc(struct work_struct *work)
{
	struct smart_charge_info *info = container_of(
		work, struct smart_charge_info, smart_sense_chg_work.work);

	if (!info || !READ_ONCE(info->ready) || READ_ONCE(info->stopping))
		return;

	smart_charge_handle_sense_chg(info);
}

static int mca_smart_charge_process_event(int event, int value, void *data)
{
	struct smart_charge_info *info = data;
	bool was_online;
	int ret;

	if (!info || !READ_ONCE(info->ready) || READ_ONCE(info->stopping))
		return -ENODEV;
	was_online = info->online;
	switch (event) {
	case MCA_EVENT_USB_CONNECT:
		info->usb_online = true;
		break;
	case MCA_EVENT_WIRELESS_CONNECT:
		info->wls_online = true;
		break;
	case MCA_EVENT_USB_DISCONNECT:
		info->usb_online = false;
		break;
	case MCA_EVENT_WIRELESS_DISCONNECT:
		info->wls_online = false;
		break;
	case MCA_EVENT_BATTERY_DTPT:
		return mca_vote(info->smartchg_delta_fv_voter, "dtpt", !!value,
			value ? SMART_CHARGE_DTPT_DELTA_VALUE : 0);
	default:
		return 0;
	}
	info->online = info->usb_online || info->wls_online;
	if (was_online == !!info->online)
		return 0;
	ret = smart_charge_plugin_or_plugout_reset(info);
	if (info->online) {
		strategy_class_fg_ops_get_rsoc(&info->plugin_rsoc);
		cancel_delayed_work_sync(&info->smart_charge_work);
		schedule_delayed_work(&info->smart_charge_work, 0);
		cancel_delayed_work_sync(&info->smart_soc_limit_work);
		schedule_delayed_work(&info->smart_soc_limit_work, 0);
	} else {
		cancel_delayed_work_sync(&info->smart_charge_work);
		cancel_delayed_work_sync(&info->smart_soc_limit_work);
		memset(&info->smart_chg_control, 0, sizeof(info->smart_chg_control));
		info->soc_limit_enable = false;
		info->ignore_upload.AsUINT32 = 0;
		smart_charge_set_soc_limit(false);
	}
	return ret;
}

static int smart_charge_fv_control(struct mca_votable *votable, void *data,
	int effective_result, const char *effective_client)
{
	struct smart_charge_info *info = data;
	struct mca_smartchg_if_ops *if_ops;
	int idx, ret = 0, rc;
	bool handled = false;

	if (!info || !READ_ONCE(info->ready) || READ_ONCE(info->stopping))
		return -ENODEV;
	idx = srcu_read_lock(&smartchg_if_srcu);
	for (int i = 0; i < MCA_SMARTCHG_IF_CHG_TYPE_END; i++) {
		if_ops = mca_smartchg_if_get_ops(i);
		if (!if_ops || !if_ops->set_delta_fv)
			continue;
		handled = true;
		rc = if_ops->set_delta_fv(if_ops->data, effective_result);
		if (rc && !ret)
			ret = rc;
	}
	srcu_read_unlock(&smartchg_if_srcu, idx);
	if (!handled)
		ret = -ENODEV;
	if (!ret)
		info->delta_fv = effective_result;
	return ret;
}

static int smart_charge_ichg_control(struct mca_votable *votable, void *data,
	int effective_result, const char *effective_client)
{
	struct smart_charge_info *info = data;
	struct mca_smartchg_if_ops *if_ops;
	int idx, ret = 0, rc;
	bool handled = false;

	if (!info || !READ_ONCE(info->ready) || READ_ONCE(info->stopping))
		return -ENODEV;
	idx = srcu_read_lock(&smartchg_if_srcu);
	for (int i = 0; i < MCA_SMARTCHG_IF_CHG_TYPE_END; i++) {
		if_ops = mca_smartchg_if_get_ops(i);
		if (!if_ops || !if_ops->set_delta_ichg)
			continue;
		handled = true;
		rc = if_ops->set_delta_ichg(if_ops->data, effective_result);
		if (rc && !ret)
			ret = rc;
	}
	srcu_read_unlock(&smartchg_if_srcu, idx);
	if (!handled)
		ret = -ENODEV;
	if (!ret)
		info->delta_ichg = effective_result;
	return ret;
}

static int smart_charge_set_fcc_control(struct mca_votable *votable, void *data,
	int effective_result, const char *effective_client)
{
	struct smart_charge_info *info = data;
	struct mca_smartchg_if_ops *if_ops;
	int idx, ret = 0, rc;
	bool handled = false;

	if (!info || !READ_ONCE(info->ready) || READ_ONCE(info->stopping))
		return -ENODEV;
	idx = srcu_read_lock(&smartchg_if_srcu);
	for (int i = 0; i < MCA_SMARTCHG_IF_CHG_TYPE_END; i++) {
		if_ops = mca_smartchg_if_get_ops(i);
		if (!if_ops || !if_ops->set_fcc)
			continue;
		handled = true;
		rc = if_ops->set_fcc(if_ops->data, effective_result);
		if (rc && !ret)
			ret = rc;
	}
	srcu_read_unlock(&smartchg_if_srcu, idx);
	if (!handled)
		ret = -ENODEV;
	return ret;
}

static int smart_charge_init_voter(struct smart_charge_info *info)
{
	info->smartchg_delta_fv_voter = mca_create_owned_votable(
		"smartchg_delta_fv", MCA_VOTE_MAX, smart_charge_fv_control,
		SMART_CHARGE_DELTA_FV_DEFAULT_VALUE, info);
	if (IS_ERR(info->smartchg_delta_fv_voter)) {
		mca_log_err("smartchg_delta_fv voteable failed\n");
		return PTR_ERR(info->smartchg_delta_fv_voter);
	}

	info->smartchg_delta_ichg_voter = mca_create_owned_votable(
		"smartchg_delta_ichg", MCA_VOTE_MAX, smart_charge_ichg_control,
		SMART_CHARGE_DELTA_ICHG_DEFAULT_VALUE, info);
	if (IS_ERR(info->smartchg_delta_ichg_voter)) {
		mca_log_err("smartchg_delta_ichg voteable failed\n");
		return PTR_ERR(info->smartchg_delta_ichg_voter);
	}

	info->smartchg_set_fcc_voter = mca_create_owned_votable(
		"smartchg_set_fcc", MCA_VOTE_MIN, smart_charge_set_fcc_control, 0,
		info);
	if (IS_ERR(info->smartchg_set_fcc_voter)) {
		mca_log_err("smartchg_fcc_voter voteable failed\n");
		return PTR_ERR(info->smartchg_set_fcc_voter);
	}

	return 0;
}

static ssize_t smart_charge_sysfs_show(struct device *dev,
				       struct device_attribute *attr, char *buf)
{
	struct mca_sysfs_attr_info *attr_info;
	ssize_t count = 0;
	struct smart_charge_info *info = dev_get_drvdata(dev);
	int val = 0;

	attr_info = mca_sysfs_lookup_attr(attr->attr.name,
					  smartchg_sysfs_field_tbl,
					  SMARTCHG_SYSFS_ATTRS_SIZE);
	if (!attr_info)
		return -1;

	if (!info || !READ_ONCE(info->ready) || READ_ONCE(info->stopping)) {
		mca_log_err("%s dev_driverdata is null\n", __func__);
		return -1;
	}

	switch (attr_info->sysfs_attr_name) {
	case MCA_PROP_SMARTCHG:
		val = get_smart_chg_message(info);
		count = scnprintf(buf, PAGE_SIZE, "%d\n", val);
		break;
	case MCA_PROP_SMARTBATT:
		val = get_smart_batt_message(info);
		count = scnprintf(buf, PAGE_SIZE, "%d\n", val);
		break;
	case MCA_PROP_SMARTNIGHT:
		val = get_smart_night_message(info);
		count = scnprintf(buf, PAGE_SIZE, "%d\n", val);
		break;
	case MCA_PROP_SMARTCHG_FV:
		val = mca_get_client_vote(info->smartchg_delta_fv_voter,
					  "smart_chg");
		val = val < 0 ? 0 : val;
		count = scnprintf(buf, PAGE_SIZE, "%d\n", val);
		break;
	case MCA_PROP_SMARTCHG_ICHG:
		val = mca_get_client_vote(info->smartchg_delta_ichg_voter,
					  "smart_chg");
		val = val < 0 ? 0 : val;
		count = scnprintf(buf, PAGE_SIZE, "%d\n", val);
		break;
	case MCA_PROP_POSTURE:
		val = info->smart_chg_data.smart_chgcfg[SMART_CHG_SENSE_CHG]
				      .use_fake_value ?
			      info->smart_chg_data
				      .smart_chgcfg[SMART_CHG_SENSE_CHG]
				      .fake_value :
			      info->smart_chg_data
				      .smart_chgcfg[SMART_CHG_SENSE_CHG]
				      .func_value;
		count = scnprintf(buf, PAGE_SIZE, "%d\n", val);
		break;
	case MCA_PROP_SCENE:
		val = info->fake_scene != SMART_CHARGE_FAKE_SCENE_DEFAULT ?
			info->fake_scene : info->scene;
		count = scnprintf(buf, PAGE_SIZE, "%d\n", val);
		break;
	case MCA_PROP_BOARD_TEMP:
		count = scnprintf(buf, PAGE_SIZE, "%d\n", info->board_temp);
		break;
	case MCA_PROP_SMART_SIC_MODE:
		count = scnprintf(buf, PAGE_SIZE, "%d\n", info->smart_sic_mode);
		break;
	default:
		break;
	}

	return count;
}

static ssize_t smart_charge_sysfs_store(struct device *dev,
					struct device_attribute *attr,
					const char *buf, size_t count)
{
	struct mca_sysfs_attr_info *attr_info;
	struct smart_charge_info *info = dev_get_drvdata(dev);
	int val, ret = 0;

	attr_info = mca_sysfs_lookup_attr(attr->attr.name,
					  smartchg_sysfs_field_tbl,
					  SMARTCHG_SYSFS_ATTRS_SIZE);
	if (!attr_info)
		return -1;

	if (!info || !READ_ONCE(info->ready) || READ_ONCE(info->stopping)) {
		mca_log_err("%s dev_driverdata is null\n", __func__);
		return -1;
	}

	if (kstrtoint(buf, 0, &val))
		return -EINVAL;

	switch (attr_info->sysfs_attr_name) {
	case MCA_PROP_SMARTCHG:
		ret = smartcharging_receive_control_message(info, val);
		break;
	case MCA_PROP_SMARTBATT:
		ret = handle_smart_batt_message(info, val);
		break;
	case MCA_PROP_SMARTNIGHT:
		ret = handle_smart_night_message(info, val);
		break;
	case MCA_PROP_SMARTCHG_FV:
		if (check_mul_overflow(val, info->cell_type, &val))
			return -ERANGE;
		ret = mca_vote(info->smartchg_delta_fv_voter, "smart_chg", true, val);
		break;
	case MCA_PROP_SMARTCHG_ICHG:
		ret = mca_vote(info->smartchg_delta_ichg_voter, "smart_chg", true,
			 val);
		break;
	case MCA_PROP_SCENE:
		smart_charge_set_scene(info, val);
		break;
	case MCA_PROP_BOARD_TEMP:
		WRITE_ONCE(info->board_temp, val);
		break;
	default:
		break;
	}

	mca_log_info("set the %d value = %d\n", attr_info->sysfs_attr_name,
		     val);

	if (ret)
		return ret;
	return count;
}

static int smart_charge_sysfs_create_group(struct device *dev)
{
	mca_sysfs_init_attrs(smartchg_sysfs_attrs, smartchg_sysfs_field_tbl,
			     SMARTCHG_SYSFS_ATTRS_SIZE);
	return mca_sysfs_create_link_group("charger", "smart_charge", dev,
					   &smartchg_sysfs_attr_group);
}

static void smart_charge_sysfs_remove_group(struct device *dev)
{
	mca_sysfs_remove_link_group("charger", "smart_charge", dev,
				    &smartchg_sysfs_attr_group);
}

/* No BASP/BAA character device is published. The inferred private blob ABI
 * is not a validated charging interface; use the DT policy and typed APIs.
 */

static int smart_charge_panel_notifier_cb(struct notifier_block *nb,
					  unsigned long event, void *val)
{
	struct smart_charge_info *info =
		container_of(nb, struct smart_charge_info, panel_nb);
	int tmp = 0;

	if (!val || !READ_ONCE(info->ready) || READ_ONCE(info->stopping))
		return NOTIFY_DONE;

	switch (event) {
	case MCA_EVENT_PANEL_SCREEN_STATE_CHANGE:
		tmp = *(int *)val;
		mca_log_info("update screen_state: %d => %d\n",
			     info->screen_state, tmp);
		info->screen_state = tmp;
		cancel_delayed_work_sync(&info->smart_sense_chg_work);
		schedule_delayed_work(&info->smart_sense_chg_work, 0);
		break;
	default:
		break;
	}
	return NOTIFY_DONE;
}

static int smart_charge_parse_dt(struct smart_charge_info *info)
{
	struct device_node *node = info->dev->of_node;
	int len = 0;
	int ret = 0;
	int batt_ichg_cfg[CC_ICHG_MAX_GROUP * SMARTCHG_MODE_PARA_MAX];

	if (!node)
		return -EINVAL;
	(void)mca_parse_dts_u32(node, "cell_type", &info->cell_type,
				MCA_CELL_TYPE_1S);
	if (info->cell_type < MCA_CELL_TYPE_1S || info->cell_type >= MCA_CELL_TYPE_MAX)
		return -EINVAL;
	/* The vendor BASP blob layout is unverified; no runtime table override. */
	mca_parse_dts_u32(node, "support_csd", &info->support_csd, 0);
	info->support_sensechg_v2 =
		of_property_read_bool(node, "support_sensechg_v2");
	info->support_cc_ichg = of_property_read_bool(node, "support_cc_ichg");
	if (info->support_cc_ichg) {
		len = mca_parse_dts_u32_count(node, "cc_ichg_cfg",
					      CC_ICHG_MAX_GROUP,
					      SMARTCHG_MODE_PARA_MAX);
		if (len <= 0 || len > ARRAY_SIZE(batt_ichg_cfg) ||
		    len % SMARTCHG_MODE_PARA_MAX)
			return len < 0 ? len : -EINVAL;

		ret = mca_parse_dts_u32_array(
			node, "cc_ichg_cfg", batt_ichg_cfg, len);
		if (ret) {
			mca_log_err(" parse cc_ichg_cfg failed\n");
			return ret;
		}

		for (int row = 0; row < len / SMARTCHG_MODE_PARA_MAX; row++) {
			int col = row * SMARTCHG_MODE_PARA_MAX;

			if (batt_ichg_cfg[col] < 0 || batt_ichg_cfg[col + 1] < 0 ||
			    (row && batt_ichg_cfg[col] <= batt_ichg_cfg[col - SMARTCHG_MODE_PARA_MAX]))
				return -EINVAL;
		}
		info->ichg_cc_count = len / SMARTCHG_MODE_PARA_MAX;
		for (int row = 0; row < info->ichg_cc_count; row++) {
			int col = row * SMARTCHG_MODE_PARA_MAX;

			info->ichg_cc_table[row].cc_max =
				batt_ichg_cfg[col + SMARTCHG_MODE_CYCLECOUNT];
			info->ichg_cc_table[row].delta_ichg =
				batt_ichg_cfg[col + SMARTCHG_MODE_DELTA_ICHG];
			mca_log_err("%d, %d\n", info->ichg_cc_table[row].cc_max,
				    info->ichg_cc_table[row].delta_ichg);
		}
	}

	mca_parse_dts_u32(node, "smart_bypass_support", &info->support_bypass,
			  0);
	if (info->support_bypass) {
		const int elems =
			sizeof(struct smart_bypass_temp_section) / sizeof(u32);

		mca_parse_dts_u32(node, "smart_bypass_entry_soc",
				  &info->bypass_entry_soc, 0);
		mca_parse_dts_u32(node, "smart_bypass_exit_soc",
				  &info->bypass_exit_soc, 0);

		len = mca_parse_dts_u32_count(node, "smart_bypass_high_lmt_cfg",
					      SMART_BYPASS_TEMP_SECTION_MAX,
					      elems);
		if (len < 0) {
			mca_log_err("parse smart_bypass_high_lmt_cfg failed\n");
			return -1;
		}
		info->bypass_high_num = len / elems;
		ret = mca_parse_dts_u32_array(node, "smart_bypass_high_lmt_cfg",
					      (u32 *)info->bypass_high_lmt, len);
		if (ret < 0)
			return -1;

		len = mca_parse_dts_u32_count(node, "smart_bypass_med_lmt_cfg",
					      SMART_BYPASS_TEMP_SECTION_MAX,
					      elems);
		if (len < 0) {
			mca_log_err("parse smart_bypass_med_lmt_cfg failed\n");
			return -1;
		}
		info->bypass_med_num = len / elems;
		ret = mca_parse_dts_u32_array(node, "smart_bypass_med_lmt_cfg",
					      (u32 *)info->bypass_med_lmt, len);
		if (ret < 0)
			return -1;

		len = mca_parse_dts_u32_count(node, "smart_bypass_low_lmt_cfg",
					      SMART_BYPASS_TEMP_SECTION_MAX,
					      elems);
		if (len < 0) {
			mca_log_err("parse smart_bypass_low_lmt_cfg failed\n");
			return -1;
		}
		info->bypass_low_num = len / elems;
		ret = mca_parse_dts_u32_array(node, "smart_bypass_low_lmt_cfg",
					      (u32 *)info->bypass_low_lmt, len);
		if (ret < 0)
			return -1;
	}

	return 0;
}

static void smart_charge_stop(struct smart_charge_info *info)
{
	if (!info || READ_ONCE(info->stopping))
		return;
	WRITE_ONCE(info->stopping, true);
	WRITE_ONCE(info->ready, false);
	smart_charge_unpublish(info);
	if (info->sysfs_created) {
		smart_charge_sysfs_remove_group(info->dev);
		info->sysfs_created = false;
	}
	if (info->panel_registered) {
		mca_event_block_notify_unregister(MCA_EVENT_TYPE_PANEL, &info->panel_nb);
		info->panel_registered = false;
	}
	if (info->thermal_registered) {
		mca_event_block_notify_unregister(MCA_EVENT_TYPE_THERMAL_TEMP, &info->thermal_nb);
		info->thermal_registered = false;
	}
	if (info->strategy_registered) {
		mca_strategy_ops_unregister(STRATEGY_FUNC_TYPE_SMARTCHG, info);
		info->strategy_registered = false;
	}
	if (!IS_ERR_OR_NULL(info->smartchg_delta_fv_voter))
		mca_detach_owned_votable(info->smartchg_delta_fv_voter, info);
	if (!IS_ERR_OR_NULL(info->smartchg_delta_ichg_voter))
		mca_detach_owned_votable(info->smartchg_delta_ichg_voter, info);
	if (!IS_ERR_OR_NULL(info->smartchg_set_fcc_voter))
		mca_detach_owned_votable(info->smartchg_set_fcc_voter, info);
	disable_delayed_work_sync(&info->smart_charge_work);
	disable_delayed_work_sync(&info->smart_sense_chg_work);
	disable_delayed_work_sync(&info->smart_soc_limit_work);
	/* Retain downstream limits until a live provider explicitly updates them. */
}

static int smart_charge_probe(struct platform_device *pdev)
{
	struct smart_charge_info *info;
	int ret, online = 0, wireless_online = 0;

	info = devm_kzalloc(&pdev->dev, sizeof(*info), GFP_KERNEL);
	if (!info)
		return -ENOMEM;
	info->dev = &pdev->dev;
	platform_set_drvdata(pdev, info);
	INIT_DELAYED_WORK(&info->smart_charge_work, smart_charge_workfunc);
	INIT_DELAYED_WORK(&info->smart_sense_chg_work, smart_charge_sense_chg_workfunc);
	INIT_DELAYED_WORK(&info->smart_soc_limit_work, smart_charge_soc_limit_workfunc);
	info->fake_scene = SMART_CHARGE_FAKE_SCENE_DEFAULT;
	ret = smart_charge_parse_dt(info);
	if (ret)
		goto fail;
	ret = smart_charge_init_voter(info);
	if (ret)
		goto fail;
	(void)mca_strategy_func_get_status(STRATEGY_FUNC_TYPE_BUCK_CHARGE,
		STRATEGY_STATUS_TYPE_ONLINE, &online);
	(void)mca_strategy_func_get_status(STRATEGY_FUNC_TYPE_BASIC_WIRELESS,
		STRATEGY_STATUS_TYPE_ONLINE, &wireless_online);
	info->usb_online = online > 0;
	info->wls_online = wireless_online > 0;
	info->online = info->usb_online || info->wls_online;
	WRITE_ONCE(info->ready, true);
	ret = mca_strategy_ops_register(STRATEGY_FUNC_TYPE_SMARTCHG,
		mca_smart_charge_process_event, NULL, NULL, info);
	if (ret)
		goto fail;
	info->strategy_registered = true;
	info->panel_nb.notifier_call = smart_charge_panel_notifier_cb;
	ret = mca_event_block_notify_register(MCA_EVENT_TYPE_PANEL, &info->panel_nb);
	if (ret)
		goto fail;
	info->panel_registered = true;
	info->thermal_nb.notifier_call = smart_charge_thermal_notifier_cb;
	ret = mca_event_block_notify_register(MCA_EVENT_TYPE_THERMAL_TEMP, &info->thermal_nb);
	if (ret)
		goto fail;
	info->thermal_registered = true;
	ret = smart_charge_publish(info);
	if (ret)
		goto fail;
	ret = smart_charge_sysfs_create_group(info->dev);
	if (ret)
		goto fail;
	info->sysfs_created = true;
	if (info->online) {
		schedule_delayed_work(&info->smart_charge_work, 0);
		schedule_delayed_work(&info->smart_soc_limit_work, 0);
	}
	return 0;
fail:
	smart_charge_stop(info);
	return ret;
}

static void smart_charge_remove(struct platform_device *pdev)
{
	smart_charge_stop(platform_get_drvdata(pdev));
}

static void smart_charge_shutdown(struct platform_device *pdev)
{
	smart_charge_stop(platform_get_drvdata(pdev));
}

static const struct of_device_id match_table[] = {
	{ .compatible = "xiaomi,smart_charge" },
	{},
};

static struct platform_driver smart_charge_driver = {
	.driver = {
		.owner = THIS_MODULE,
		.name = "smart_charge",
		.of_match_table = match_table,
	},
	.probe = smart_charge_probe,
	.remove = smart_charge_remove,
	.shutdown = smart_charge_shutdown,
};

static int __init smart_charge_init(void)
{
	return platform_driver_register(&smart_charge_driver);
}
module_init(smart_charge_init);

static void __exit smart_charge_exit(void)
{
	platform_driver_unregister(&smart_charge_driver);
	mca_smartchg_if_cleanup();
}
module_exit(smart_charge_exit);

MODULE_DESCRIPTION("smart charge driver");
MODULE_AUTHOR("liuzhengqing@xiaomi.com");
MODULE_LICENSE("GPL v2");
