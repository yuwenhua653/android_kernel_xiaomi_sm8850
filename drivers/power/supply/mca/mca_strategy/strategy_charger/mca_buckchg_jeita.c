// SPDX-License-Identifier: GPL-2.0
/*
 *mca_buckchg_jieta.c
 *
 * mca buck charger jeita control driver
 *
 * Copyright (c) 2024-2024 Xiaomi Technologies Co., Ltd.
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
#include <linux/notifier.h>
#include <linux/platform_device.h>
#include <linux/of.h>
#include <linux/power_supply.h>
#include <mca/common/mca_parse_dts.h>
#include <mca/protocol/protocol_class.h>
#include <mca/common/mca_voter.h>
#include <mca/common/mca_event.h>
#include <mca/common/mca_log.h>
#include <mca/strategy/strategy_class.h>
#include <mca/strategy/strategy_fg_class.h>
#include <mca/smartchg/smart_chg_class.h>
#include "inc/mca_buckchg_jeita.h"
#include <mca/platform/platform_loadsw_class.h>
#include <mca/platform/platform_fg_ic_ops.h>
#include <mca/common/mca_hwid.h>
#include "hwid.h"
#include <mca/protocol/protocol_class.h>

#ifndef MCA_LOG_TAG
#define MCA_LOG_TAG "mca_buckchg_jeita"
#endif

#define MCA_DTPT_MOLECULE_SCALE 8
#define MCA_DTPT_DENOM_SCALE 10
#define MCA_BASE_OVER_CURR_COUNT_MAX 4

#define JEITA_COLD_ZONE_INDEX 1

static int mca_buckchg_jeita_get_curr(struct mca_buckchg_jeita_data *jeita_data,
				      int *vbat_index)
{
	int i;
	int ret;
	int vbat = 0;
	int min_cur = jeita_data->max_current;

	*vbat_index = -1;
	ret = strategy_class_fg_ops_get_voltage(&vbat);
	if (ret) {
		mca_log_err("get vbat failed\n");
		return min_cur;
	}

	if (!jeita_data->volt_para.size)
		return min_cur;

	for (i = 0; i < jeita_data->volt_para.size; i++) {
		min_cur = min(min_cur,
			      jeita_data->volt_para.volt_data[i].max_current);
		if (vbat <= jeita_data->volt_para.volt_data[i].voltage) {
			*vbat_index = i;
			return jeita_data->volt_para.volt_data[i].max_current;
		}
	}

	/* can not find para, use min current */
	return min_cur;
}

#define ABNORMAL_BATT_FV_MAX 4200
#define JEITA_HOT_RECHARGE_VBAT_HYS 150

static bool mca_jeita_above_lower_step(const struct mca_buckchg_jeita_data *row,
				      int index, int vbat)
{
	if (index < 0 || index >= row->volt_para.size)
		return false;
	return !index || vbat > row->volt_para.volt_data[index - 1].voltage;
}

static void mca_buckchg_base_jeita_update(struct mca_buckchg_jeita_dev *info)
{
	int temp = 0;
	int i, ret;
	struct mca_buckchg_jeita_data *jeita_data, *cur_jeita_data;
	int fastcharge_mode = 0;
	int now_curr = 0, chg_curr = 0, effective_curr;
	int hys_affect = 0;
	int data_change = 0;
	struct mca_buckchg_jeita_proc_data *proc = &info->base_proc_data;
	static bool runswocp;
	static int base_over_curr_count;
	int vbat_index = -1;
	int vbat = 0;

	if (!info->base_jeita_para.jeita_data || !info->voter_ok) {
		mca_log_err("jeita data not ready\n");
		return;
	}
	effective_curr = mca_get_effective_result(info->fcc_voter);

	ret = platform_fg_ops_get_temp(FG_IC_MASTER, &temp);
	ret |= platform_fg_ops_get_curr(FG_IC_MASTER, &now_curr);
	if (ret) {
		mca_log_err("get battery temp or currfailed\n");
		return;
	}

	temp /= 10;
	fastcharge_mode = strategy_class_fg_get_fastcharge();
	mca_log_err("fastcharge_mode is %d\n", fastcharge_mode);
	platform_fg_ops_get_volt(FG_IC_MASTER, &vbat);
	mca_log_info("vbat is %d\n", vbat);

	if (!fastcharge_mode) {
		for (i = 0; i < info->base_jeita_para.size; i++) {
			cur_jeita_data = info->base_jeita_para.jeita_data + i;
			if (temp < cur_jeita_data->temp_high &&
			    temp >= cur_jeita_data->temp_low)
				break;
		}
		if (i == info->base_jeita_para.size) {
			mca_log_err("can not find flip jeita para\n");
			return;
		}
	} else {
		for (i = 0; i < info->base_jeita_para.fcc_size; i++) {
			cur_jeita_data =
				info->base_jeita_para.jeita_ffc_data + i;
			if (temp < cur_jeita_data->temp_high &&
			    temp >= cur_jeita_data->temp_low)
				break;
		}
		if (i == info->base_jeita_para.fcc_size) {
			mca_log_err("can not find flip jeita fcc para\n");
			return;
		}
	}

	/* select cur jeita_data (temperature hysteresis) */
	if (proc->cur_jeita_index == -1) {
		jeita_data = cur_jeita_data;
		proc->last_chg_curr =
			mca_buckchg_jeita_get_curr(cur_jeita_data, &vbat_index);
	} else {
		if (proc->cur_jeita_index == i ||
		    fastcharge_mode != proc->last_fastcharge_mode)
			jeita_data = cur_jeita_data;
		else {
			if (!fastcharge_mode ||
			    info->base_jeita_para.fcc_size == 0)
				jeita_data = info->base_jeita_para.jeita_data +
					     proc->cur_jeita_index;
			else
				jeita_data =
					info->base_jeita_para.jeita_ffc_data +
					proc->cur_jeita_index;

			mca_log_info("temp_low: %d, temp_high: %d, temp: %d\n",
				     jeita_data->temp_low -
					     jeita_data->low_temp_hys,
				     jeita_data->temp_high +
					     jeita_data->high_temp_hys,
				     temp);
			if (i > proc->cur_jeita_index) {
				if (proc->cur_jeita_index == 0 &&
				    mca_smartchg_is_extreme_cold_enabled())
					jeita_data = cur_jeita_data;
				else if (temp < jeita_data->temp_high +
							 jeita_data->high_temp_hys)
					hys_affect = 1;
				else
					jeita_data = cur_jeita_data;
			} else {
				if (temp > jeita_data->temp_low -
						   jeita_data->low_temp_hys)
					hys_affect = 1;
				else
					jeita_data = cur_jeita_data;
			}
		}
	}
	proc->last_fastcharge_mode = fastcharge_mode;

	proc->max_chg_curr =
		mca_buckchg_jeita_get_curr(jeita_data, &vbat_index);
	if (proc->cur_jeita_index != i && !hys_affect) {
		data_change = 1;
		mca_log_info(
			"jeita_index: cur_jeita_index:%d, i:%d, hys_affect:%d\n",
			proc->cur_jeita_index, i, hys_affect);
		proc->last_chg_curr = proc->max_chg_curr;
	} else if (proc->max_chg_curr > proc->last_chg_curr) {
		if (vbat_index != -1 &&
		    vbat < jeita_data->volt_para.volt_data[vbat_index].voltage -
				   info->base_vbat_low_hyst) {
			data_change = 1;
			mca_log_info(
				"vbat_thre[l->s]: max_chg_curr:%d, last_chg_curr:%d, vbat_index:%d, vbat:%d\n",
				proc->max_chg_curr, proc->last_chg_curr,
				vbat_index, vbat);
			proc->last_chg_curr = proc->max_chg_curr;
		}
	} else if (proc->max_chg_curr < proc->last_chg_curr) {
		if (mca_jeita_above_lower_step(jeita_data, vbat_index, vbat)) {
			data_change = 1;
			mca_log_info(
				"vbat_thre[s->l]: max_chg_curr:%d, last_chg_curr:%d, vbat_index:%d\n",
				proc->max_chg_curr, proc->last_chg_curr,
				vbat_index);
			proc->last_chg_curr = proc->max_chg_curr;
		}
	}

	chg_curr = proc->max_chg_curr;
	mca_log_info(
		"cur index %d/%d max_chg_curr %d chg_curr %d hys_affect %d, now_curr %d, effective_curr %d\n",
		i, proc->cur_jeita_index,
		proc->max_chg_curr, chg_curr, hys_affect,
		now_curr, effective_curr);
	if (data_change && !hys_affect)
		proc->cur_jeita_index = i;

	if (effective_curr != 0 && now_curr / 1000 < -chg_curr)
		base_over_curr_count++;
	else
		base_over_curr_count = 0;

	if (base_over_curr_count >= MCA_BASE_OVER_CURR_COUNT_MAX &&
	    effective_curr != 0) {
		effective_curr -= 100;
		base_over_curr_count = 0;
		mca_vote(info->fcc_voter, "swocp", true, effective_curr);
		runswocp = true;
		mca_log_err("reduce fcc %d by swocp\n", effective_curr);
	}
	if (now_curr / 1000 > -chg_curr + 500 && runswocp) {
		runswocp = false;
		mca_vote(info->fcc_voter, "swocp", false, 0);
		mca_log_err("disable swocp\n");
	}
}

static void mca_buckchg_flip_jeita_update(struct mca_buckchg_jeita_dev *info)
{
	int temp = 0;
	int i, ret;
	struct mca_buckchg_jeita_data *jeita_data, *cur_jeita_data;
	int fastcharge_mode = 0;
	int chg_curr = 0;
	int hys_affect = 0;
	int data_change = 0;
	struct mca_buckchg_jeita_proc_data *proc = &info->flip_proc_data;
	int vbat_index = -1;
	int vbat = 0;

	if (!info->flip_jeita_para.jeita_data || !info->voter_ok) {
		mca_log_err("jeita data not ready\n");
		return;
	}

	ret = platform_fg_ops_get_temp(FG_IC_SLAVE, &temp);
	if (ret) {
		mca_log_err("get battery temp failed\n");
		return;
	}

	temp /= 10;
	fastcharge_mode = strategy_class_fg_get_fastcharge();
	mca_log_err("fastcharge_mode is %d\n", fastcharge_mode);
	platform_fg_ops_get_volt(FG_IC_SLAVE, &vbat);
	mca_log_info("vbat is %d\n", vbat);

	if (!fastcharge_mode) {
		for (i = 0; i < info->flip_jeita_para.size; i++) {
			cur_jeita_data = info->flip_jeita_para.jeita_data + i;
			if (temp < cur_jeita_data->temp_high &&
			    temp >= cur_jeita_data->temp_low)
				break;
		}
		if (i == info->flip_jeita_para.size) {
			mca_log_err("can not find flip jeita para\n");
			return;
		}
	} else {
		for (i = 0; i < info->flip_jeita_para.fcc_size; i++) {
			cur_jeita_data =
				info->flip_jeita_para.jeita_ffc_data + i;
			if (temp < cur_jeita_data->temp_high &&
			    temp >= cur_jeita_data->temp_low)
				break;
		}
		if (i == info->flip_jeita_para.fcc_size) {
			mca_log_err("can not find flip jeita fcc para\n");
			return;
		}
	}

	/* select cur jeita_data (temperature hysteresis) */
	if (proc->cur_jeita_index == -1) {
		jeita_data = cur_jeita_data;
		proc->last_chg_curr =
			mca_buckchg_jeita_get_curr(cur_jeita_data, &vbat_index);
	} else {
		if (proc->cur_jeita_index == i ||
		    fastcharge_mode != proc->last_fastcharge_mode)
			jeita_data = cur_jeita_data;
		else {
			if (!fastcharge_mode ||
			    info->flip_jeita_para.fcc_size == 0)
				jeita_data = info->flip_jeita_para.jeita_data +
					     proc->cur_jeita_index;
			else
				jeita_data =
					info->flip_jeita_para.jeita_ffc_data +
					proc->cur_jeita_index;

			mca_log_info("temp_low: %d, temp_high: %d, temp: %d\n",
				     jeita_data->temp_low -
					     jeita_data->low_temp_hys,
				     jeita_data->temp_high +
					     jeita_data->high_temp_hys,
				     temp);
			if (i > proc->cur_jeita_index) {
				if (proc->cur_jeita_index == 0 &&
				    mca_smartchg_is_extreme_cold_enabled())
					jeita_data = cur_jeita_data;
				else if (temp < jeita_data->temp_high +
							 jeita_data->high_temp_hys)
					hys_affect = 1;
				else
					jeita_data = cur_jeita_data;
			} else {
				if (temp > jeita_data->temp_low -
						   jeita_data->low_temp_hys)
					hys_affect = 1;
				else
					jeita_data = cur_jeita_data;
			}
		}
	}
	proc->last_fastcharge_mode = fastcharge_mode;

	proc->max_chg_curr =
		mca_buckchg_jeita_get_curr(jeita_data, &vbat_index);
	if (proc->cur_jeita_index != i && !hys_affect) {
		data_change = 1;
		mca_log_info(
			"jeita_index: cur_jeita_index:%d, i:%d, hys_affect:%d\n",
			proc->cur_jeita_index, i, hys_affect);
		proc->last_chg_curr = proc->max_chg_curr;
	} else if (proc->max_chg_curr > proc->last_chg_curr) {
		if (vbat_index != -1 &&
		    vbat < jeita_data->volt_para.volt_data[vbat_index].voltage -
				   info->flip_vbat_low_hyst) {
			data_change = 1;
			mca_log_info(
				"vbat_thre[l->s]: max_chg_curr:%d, last_chg_curr:%d, vbat_index:%d, vbat:%d\n",
				proc->max_chg_curr, proc->last_chg_curr,
				vbat_index, vbat);
			proc->last_chg_curr = proc->max_chg_curr;
		}
	} else if (proc->max_chg_curr < proc->last_chg_curr) {
		if (mca_jeita_above_lower_step(jeita_data, vbat_index, vbat)) {
			data_change = 1;
			mca_log_info(
				"vbat_thre[s->l]: max_chg_curr:%d, last_chg_curr:%d, vbat_index:%d\n",
				proc->max_chg_curr, proc->last_chg_curr,
				vbat_index);
			proc->last_chg_curr = proc->max_chg_curr;
		}
	}

	chg_curr = proc->max_chg_curr;
	mca_log_info("cur index %d/%d max_chg_curr %d chg_curr %d hys_affect %d\n",
		     i, proc->cur_jeita_index,
		     proc->max_chg_curr, chg_curr, hys_affect);

	if (data_change && !hys_affect) {
		proc->cur_jeita_index = i;
		mca_vote(info->flip_fcc_voter, "jeita", true, chg_curr);
	}
}
/* The China OS4 tables specify the voltage delta and termination current in
 * mV and mA. A wired session with unknown BC1.2 state keeps the weaker limit
 * until the protocol provider can report the negotiated adapter.
 */
static unsigned int mca_jeita_weak_limits(struct mca_buckchg_jeita_dev *info,
					int *vterm, int *iterm)
{
	unsigned int adapter = XM_CHARGER_TYPE_UNKNOW;

	if (!info->weak_iterm_ma || !READ_ONCE(info->usb_online))
		return adapter;
	if (protocol_class_get_adapter_type(ADAPTER_PROTOCOL_BC12, &adapter))
		adapter = UINT_MAX;

	if ((adapter == UINT_MAX || (adapter >= XM_CHARGER_TYPE_SDP && adapter <= XM_CHARGER_TYPE_FLOAT)) &&
	    *iterm > info->weak_iterm_ma) {
		*vterm -= info->weak_delta_mv;
		*iterm = info->weak_iterm_ma;
	}
	return adapter;
}

static void mca_jeita_vote_termination(struct mca_buckchg_jeita_dev *info, unsigned int adapter,
				      int vterm, int iterm)
{
	int vret = mca_vote(info->vterm_voter, "jeita", true, vterm);
	int iret;

	if (info->support_base_flip || info->base_flip_same)
		return;
	iret = mca_vote(info->iterm_voter, "jeita", true, iterm);
	if (info->weak_iterm_ma) {
		info->weak_vote_retry = vret || iret;
		if (!info->weak_vote_retry)
			info->weak_adapter = adapter;
	}
}

static void mca_buckchg_jeita_update(struct mca_buckchg_jeita_dev *info)
{
	int temp = 0;
	int i, ret;
	struct mca_buckchg_jeita_data *jeita_data, *cur_jeita_data;
	int fastcharge_mode = 0;
	int vterm, iterm, chg_curr = 0;
	unsigned int adapter;
	int hys_affect = 0;
	int data_change = 0;
	int vbat = 0;
	struct mca_buckchg_jeita_proc_data *proc = &info->proc_data;
	int vbat_index = -1;

	if (!info->jeita_para.jeita_data || !info->voter_ok) {
		mca_log_err("jeita data not ready\n");
		return;
	}

	ret = strategy_class_fg_ops_get_temperature(&temp);
	if (ret) {
		mca_log_err("get battery temp failed\n");
		return;
	}

	temp /= 10;
	fastcharge_mode = strategy_class_fg_get_fastcharge();

	ret = strategy_class_fg_ops_get_voltage(&vbat);
	if (ret) {
		mca_log_err("get battery volt failed\n");
		return;
	}

	if (!fastcharge_mode) {
		for (i = 0; i < info->jeita_para.size; i++) {
			cur_jeita_data = info->jeita_para.jeita_data + i;
			if (temp < cur_jeita_data->temp_high &&
			    temp >= cur_jeita_data->temp_low)
				break;
		}
		if (i == info->jeita_para.size) {
			mca_log_err("can not find jeita para\n");
			return;
		}
	} else {
		for (i = 0; i < info->jeita_para.fcc_size; i++) {
			cur_jeita_data = info->jeita_para.jeita_ffc_data + i;
			if (temp < cur_jeita_data->temp_high &&
			    temp >= cur_jeita_data->temp_low)
				break;
		}
		if (i == info->jeita_para.fcc_size) {
			mca_log_err("can not find jeita fcc para\n");
			return;
		}
	}

	/* select cur jeita_data */
	if (proc->cur_jeita_index == -1 || info->baacfg_update) {
		jeita_data = cur_jeita_data;
		proc->last_chg_curr =
			mca_buckchg_jeita_get_curr(cur_jeita_data, &vbat_index);
	} else {
		if (proc->cur_jeita_index == i ||
		    fastcharge_mode != proc->last_fastcharge_mode)
			jeita_data = cur_jeita_data;
		else {
			if (!fastcharge_mode || info->jeita_para.fcc_size == 0)
				jeita_data = info->jeita_para.jeita_data +
					     proc->cur_jeita_index;
			else
				jeita_data = info->jeita_para.jeita_ffc_data +
					     proc->cur_jeita_index;

			mca_log_info("temp_low: %d, temp_high: %d, temp: %d\n",
				     jeita_data->temp_low -
					     jeita_data->low_temp_hys,
				     jeita_data->temp_high +
					     jeita_data->high_temp_hys,
				     temp);
			if (i > proc->cur_jeita_index) {
				if (proc->cur_jeita_index == 0 &&
				    mca_smartchg_is_extreme_cold_enabled())
					jeita_data = cur_jeita_data;
				else if (temp <
					 jeita_data->temp_high +
						 jeita_data->high_temp_hys)
					hys_affect = 1;
				else
					jeita_data = cur_jeita_data;
			} else {
				if (temp > jeita_data->temp_low -
						   jeita_data->low_temp_hys)
					hys_affect = 1;
				else
					jeita_data = cur_jeita_data;
			}
		}
	}

	/* select whether vote */
	proc->max_chg_curr =
		mca_buckchg_jeita_get_curr(jeita_data, &vbat_index);
	if (info->baacfg_update) {
		data_change = 1;
		info->baacfg_update = false;
		mca_log_info("BAA config data update\n");
	} else if (proc->cur_jeita_index != i &&
		   !hys_affect) { //jeita_index change
		data_change = 1;
		mca_log_info(
			"jeita_index: cur_jeita_index:%d, i:%d, hys_affect:%d\n",
			proc->cur_jeita_index, i, hys_affect);
		proc->last_chg_curr = proc->max_chg_curr;
	} else { //jeita_index not change, check vbat_thre
		if (proc->max_chg_curr > proc->last_chg_curr) {
			bool in_cold_zone = (i == 1 || i == 2 ||
					     (i == 3 && hys_affect));
			int low_hyst = in_cold_zone ? info->vbat_low_cold_hyst :
						      info->vbat_low_hyst;

			if (vbat_index != -1 &&
			    vbat < jeita_data->volt_para.volt_data[vbat_index]
						    .voltage -
					    low_hyst) {
				data_change = 1;
				mca_log_info(
					"vbat_thre[l->s]: max_chg_curr:%d, last_chg_curr:%d, vbat_index:%d\n",
					proc->max_chg_curr,
					proc->last_chg_curr, vbat_index);
				proc->last_chg_curr = proc->max_chg_curr;
			}
		} else if (proc->max_chg_curr < proc->last_chg_curr) {
			if (mca_jeita_above_lower_step(jeita_data, vbat_index, vbat)) {
				data_change = 1;
				mca_log_info(
					"vbat_thre[s->l]: max_chg_curr:%d, last_chg_curr:%d, vbat_index:%d\n",
					proc->max_chg_curr,
					proc->last_chg_curr, vbat_index);
				proc->last_chg_curr = proc->max_chg_curr;
			}
		}
	}

	vterm = jeita_data->vterm;
	iterm = jeita_data->iterm;
	adapter = mca_jeita_weak_limits(info, &vterm, &iterm);
	if (adapter != info->weak_adapter || info->weak_vote_retry)
		data_change = 1;

	if (vterm > ABNORMAL_BATT_FV_MAX) {
		vterm -= info->smartchg_data.delta_fv;
		mca_vote(info->en_voter, "jeita-hot", true, 1);
		if (vterm != info->vterm) {
			if (!mca_vote(info->vterm_voter, "jeita", true, vterm))
				info->vterm = vterm;
		}
	} else {
		if (vbat >= vterm - info->jeita_hot_termination_hyst)
			mca_vote(info->en_voter, "jeita-hot", true, 0);
		else if (vbat < vterm - JEITA_HOT_RECHARGE_VBAT_HYS)
			mca_vote(info->en_voter, "jeita-hot", true, 1);
	}

	if (info->dtpt_status)
		chg_curr = proc->max_chg_curr *
			   MCA_DTPT_MOLECULE_SCALE / MCA_DTPT_DENOM_SCALE;
	else
		chg_curr = proc->max_chg_curr;

	mca_log_info(
		"cur index %d/%d last_chg_curr %d chg_curr %d/%d fastcharge %d jeita_vterm %d jeita_iterm %d vterm %d delta_fv %d hys_affect %d\n",
		i, proc->cur_jeita_index, proc->last_chg_curr,
		proc->max_chg_curr, chg_curr, fastcharge_mode,
		jeita_data->vterm, jeita_data->iterm, vterm,
		info->smartchg_data.delta_fv, hys_affect);

	proc->last_fastcharge_mode = fastcharge_mode;
	if (chg_curr)
		mca_vote(info->en_voter, "jeita", true, 1);
	else
		mca_vote(info->en_voter, "jeita", true, 0);

	if (data_change) {
		if (!hys_affect)
			proc->cur_jeita_index = i;
		mca_vote(info->fcc_voter, "jeita", true, chg_curr);
		mca_jeita_vote_termination(info, adapter, vterm, iterm);
	}

	if (!fastcharge_mode && info->base_flip_same) {
		info->cold_zone =
			(proc->cur_jeita_index == JEITA_COLD_ZONE_INDEX);
		mca_log_info(
			"cur index %d/%d last_chg_curr %d cold_zone %d\n", i,
			proc->cur_jeita_index, proc->last_chg_curr,
			info->cold_zone);
	}
}

static int mca_buckchg_jeita_flip_charge_limit(struct mca_votable *votable,
					       void *data, int effective_result,
					       const char *effective_client)
{
	if (!data)
		return -1;

	mca_log_err("set flip limit current %d\n", effective_result);

	return platform_class_loadsw_set_ibat_limit(LOADSW_ROLE_MASTER,
						    effective_result);
}

static void mca_buckchg_jeita_init_voter(struct mca_buckchg_jeita_dev *info)
{
	info->en_voter = mca_find_votable("chg_enable");
	if (!info->en_voter)
		return;
	info->fcc_voter = mca_find_votable("buck_charge_curr");
	if (!info->fcc_voter)
		return;
	info->vterm_voter = mca_find_votable("term_volt");
	if (!info->vterm_voter)
		return;
	info->iterm_voter = mca_find_votable("term_curr");
	if (!info->iterm_voter)
		return;

	info->voter_ok = 1;
}

static void mca_buckchg_jeita_monitor_work(struct work_struct *work)
{
	int interval = MCA_BUCKCHG_JEITA_UPDATE_NORMAL_INTERVAL;
	struct mca_buckchg_jeita_dev *info = container_of(
		work, struct mca_buckchg_jeita_dev, monitor_work.work);

	if (READ_ONCE(info->stopping))
		return;

	if (!info->voter_ok)
		mca_buckchg_jeita_init_voter(info);

	if (!info->voter_ok) {
		interval = MCA_BUCKCHG_JEITA_INIT_VOTER_INTERVAL;
		mca_log_info("voter not ok\n");
		goto out;
	}

	if (!READ_ONCE(info->online)) {
		mca_log_info("adapter is plugout\n");
		return;
	}
	mca_buckchg_jeita_update(info);
	if (info->support_base_flip) {
		mca_buckchg_base_jeita_update(info);
		mca_buckchg_flip_jeita_update(info);
	}
out:
	if (!READ_ONCE(info->stopping))
		schedule_delayed_work(&info->monitor_work,
				      msecs_to_jiffies(interval));
}

static bool mca_jeita_table_valid(const struct mca_buckchg_jeita_data *table,
	int count)
{
	int i;

	for (i = 0; i < count; i++) {
		const struct mca_buckchg_jeita_data *row = &table[i];

		if (row->temp_low >= row->temp_high || row->low_temp_hys < 0 ||
		    row->high_temp_hys < 0 || row->max_current < 0 ||
		    row->vterm <= 0 || row->iterm < 0 ||
		    (i && row->temp_low != table[i - 1].temp_high))
			return false;
	}
	return count > 0;
}

static int
mca_buckchg_parse_volt_para(struct device *dev, struct device_node *node, const char *name,
			    struct mca_buckchg_jeita_volt_para *volt_para)
{
	struct mca_buckchg_jeita_volt_data *volt_data;
	int array_len, row, col, i;
	const char *tmp_string = NULL;

	if (strcmp(name, "null") == 0) {
		mca_log_info("no need parse volt para\n");
		return 0;
	}
	array_len = mca_parse_dts_count_strings(node, name,
						JEITA_VOLT_DATA_MAX_GROUP,
						BUCKCHG_VOLTAGE_PARA_MAX);
	if (array_len <= 0 || array_len % BUCKCHG_VOLTAGE_PARA_MAX ||
	    array_len > JEITA_VOLT_DATA_MAX_GROUP * BUCKCHG_VOLTAGE_PARA_MAX) {
		mca_log_err("parse %s failed\n", name);
		return -EINVAL;
	}

	volt_para->size = array_len / BUCKCHG_VOLTAGE_PARA_MAX;
	volt_para->volt_data =
		devm_kcalloc(dev, volt_para->size, sizeof(*volt_data), GFP_KERNEL);
	if (!volt_para->volt_data) {
		mca_log_err("volt para no mem\n");
		return -ENOMEM;
	}
	volt_data = volt_para->volt_data;
	for (i = 0; i < array_len; i++) {
		if (mca_parse_dts_string_index(node, name, i, &tmp_string))
			return -EINVAL;

		row = i / BUCKCHG_VOLTAGE_PARA_MAX;
		col = i % BUCKCHG_VOLTAGE_PARA_MAX;

		switch (col) {
		case BUCKCHG_VOLTAGE_TH:
			if (kstrtoint(tmp_string, 10, &volt_data[row].voltage))
				goto error;
			break;
		case BUCKCHG_CURRENT_MAX:
			if (kstrtoint(tmp_string, 10,
				      &volt_data[row].max_current))
				goto error;
			break;
		default:
			break;
		}
	}

	for (i = 0; i < volt_para->size; i++) {
		if (volt_data[i].voltage <= 0 || volt_data[i].max_current < 0 ||
		    (i && volt_data[i].voltage <= volt_data[i - 1].voltage))
			return -EINVAL;
	}
	for (i = 0; i < volt_para->size; i++)
		mca_log_debug("volt_para %d %d\n", volt_data[i].voltage,
			      volt_data[i].max_current);

	return 0;
error:
	return -EINVAL;
}

static int
mca_buckchg_jeita_parse_para(struct device *dev, struct device_node *node, const char *name,
			     struct mca_buckchg_jeita_para *jeita_info)
{
	int array_len, row, col, i;
	const char *tmp_string = NULL;
	char ffc_name[50];
	struct mca_buckchg_jeita_data *jeita_data, *jeita_ffc_data;

	if (!node) {
		mca_log_err("node in null\n");
		return -EINVAL;
	}

	array_len = mca_parse_dts_count_strings(
		node, name, JEITA_DATA_MAX_GROUP, JEITA_TEMP_PARA_MAX);
	if (array_len <= 0 || array_len % JEITA_TEMP_PARA_MAX ||
	    array_len > JEITA_DATA_MAX_GROUP * JEITA_TEMP_PARA_MAX) {
		mca_log_err("parse jeita failed\n");
		return -EINVAL;
	}

	jeita_info->size = array_len / JEITA_TEMP_PARA_MAX;
	jeita_info->jeita_data = devm_kcalloc(dev,
		jeita_info->size, sizeof(*jeita_info->jeita_data), GFP_KERNEL);
	if (!jeita_info->jeita_data) {
		mca_log_err("temp para no mem\n");
		return -ENOMEM;
	}
	jeita_data = jeita_info->jeita_data;
	for (i = 0; i < array_len; i++) {
		if (mca_parse_dts_string_index(node, name, i, &tmp_string))
			return -EINVAL;

		row = i / JEITA_TEMP_PARA_MAX;
		col = i % JEITA_TEMP_PARA_MAX;
		switch (col) {
		case JEITA_TEMP_PARA_TEMP_LOW:
			if (kstrtoint(tmp_string, 10,
				      &jeita_data[row].temp_low))
				goto error;
			break;
		case JEITA_TEMP_PARA_TEMP_HIGH:
			if (kstrtoint(tmp_string, 10,
				      &jeita_data[row].temp_high))
				goto error;
			break;
		case JEITA_TEMP_PARA_LOW_TEMP_HYS:
			if (kstrtoint(tmp_string, 10,
				      &jeita_data[row].low_temp_hys))
				goto error;
			break;
		case JEITA_TEMP_PARA_HIGH_TEMP_HYS:
			if (kstrtoint(tmp_string, 10,
				      &jeita_data[row].high_temp_hys))
				goto error;
			break;
		case JEITA_TEMP_PARA_MAX_CURRENT:
			if (kstrtoint(tmp_string, 10,
				      &jeita_data[row].max_current))
				goto error;
			break;
		case JEITA_TEMP_PARA_VTERM:
			if (kstrtoint(tmp_string, 10, &jeita_data[row].vterm))
				goto error;
			break;
		case JEITA_TEMP_PARA_ITERM:
			if (kstrtoint(tmp_string, 10, &jeita_data[row].iterm))
				goto error;
			break;
		case JEITA_TEMP_PARA_VOLT_PARA_NAME:
			if (mca_buckchg_parse_volt_para(
				    dev, node, tmp_string,
				    &jeita_data[row].volt_para))
				goto error;
			break;
		default:
			break;
		}
	}

	if (!mca_jeita_table_valid(jeita_data, jeita_info->size))
		return -EINVAL;

	for (i = 0; i < jeita_info->size; i++)
		mca_log_err("jeita para %d %d %d %d %d %d %d %d\n",
			    jeita_data[i].temp_low, jeita_data[i].temp_high,
			    jeita_data[i].low_temp_hys,
			    jeita_data[i].high_temp_hys,
			    jeita_data[i].max_current, jeita_data[i].vterm,
			    jeita_data[i].iterm, jeita_data[i].volt_para.size);

	snprintf(ffc_name, sizeof(ffc_name), "%s", name);
	snprintf(ffc_name + strlen(ffc_name),
		 sizeof(ffc_name) - strlen(ffc_name), "_ffc");
	mca_log_err("new name:%s\n", ffc_name);
	/* FFC is optional; a present but malformed table is not optional. */
	if (!of_find_property(node, ffc_name, NULL))
		return 0;
	array_len = mca_parse_dts_count_strings(
		node, ffc_name, JEITA_DATA_MAX_GROUP, JEITA_TEMP_PARA_MAX);
	if (array_len <= 0 || array_len % JEITA_TEMP_PARA_MAX ||
	    array_len > JEITA_DATA_MAX_GROUP * JEITA_TEMP_PARA_MAX) {
		mca_log_err("parse jeita para ffc failed\n");
		return -EINVAL;
	}

	jeita_info->fcc_size = array_len / JEITA_TEMP_PARA_MAX;

	jeita_info->jeita_ffc_data =
		devm_kcalloc(dev, jeita_info->fcc_size,
			sizeof(*jeita_info->jeita_ffc_data), GFP_KERNEL);
	if (!jeita_info->jeita_ffc_data) {
		mca_log_err("temp para no mem\n");
		return -ENOMEM;
	}
	jeita_ffc_data = jeita_info->jeita_ffc_data;
	for (i = 0; i < array_len; i++) {
		if (mca_parse_dts_string_index(node, ffc_name, i, &tmp_string))
			return -EINVAL;

		row = i / JEITA_TEMP_PARA_MAX;
		col = i % JEITA_TEMP_PARA_MAX;
		switch (col) {
		case JEITA_TEMP_PARA_TEMP_LOW:
			if (kstrtoint(tmp_string, 10,
				      &jeita_ffc_data[row].temp_low))
				goto error1;
			break;
		case JEITA_TEMP_PARA_TEMP_HIGH:
			if (kstrtoint(tmp_string, 10,
				      &jeita_ffc_data[row].temp_high))
				goto error1;
			break;
		case JEITA_TEMP_PARA_LOW_TEMP_HYS:
			if (kstrtoint(tmp_string, 10,
				      &jeita_ffc_data[row].low_temp_hys))
				goto error1;
			break;
		case JEITA_TEMP_PARA_HIGH_TEMP_HYS:
			if (kstrtoint(tmp_string, 10,
				      &jeita_ffc_data[row].high_temp_hys))
				goto error1;
			break;
		case JEITA_TEMP_PARA_MAX_CURRENT:
			if (kstrtoint(tmp_string, 10,
				      &jeita_ffc_data[row].max_current))
				goto error1;
			break;
		case JEITA_TEMP_PARA_VTERM:
			if (kstrtoint(tmp_string, 10,
				      &jeita_ffc_data[row].vterm))
				goto error1;
			break;
		case JEITA_TEMP_PARA_ITERM:
			if (kstrtoint(tmp_string, 10,
				      &jeita_ffc_data[row].iterm))
				goto error1;
			break;
		case JEITA_TEMP_PARA_VOLT_PARA_NAME:
			if (mca_buckchg_parse_volt_para(
				    dev, node, tmp_string,
				    &jeita_ffc_data[row].volt_para))
				goto error1;
			break;
		default:
			break;
		}
	}
	if (!mca_jeita_table_valid(jeita_ffc_data, jeita_info->fcc_size))
		return -EINVAL;

	for (i = 0; i < jeita_info->fcc_size; i++)
		mca_log_err("jeita ffc para %d %d %d %d %d %d %d %d\n",
			    jeita_ffc_data[i].temp_low,
			    jeita_ffc_data[i].temp_high,
			    jeita_ffc_data[i].low_temp_hys,
			    jeita_ffc_data[i].high_temp_hys,
			    jeita_ffc_data[i].max_current,
			    jeita_ffc_data[i].vterm, jeita_ffc_data[i].iterm,
			    jeita_ffc_data[i].volt_para.size);
	return 0;
error1:
error:
	return -EINVAL;
}

static int mca_jeita_second_cell(struct device_node *node, bool *second)
{
	union power_supply_propval value;
	struct power_supply *psy;
	const char *cell = NULL;
	int ret;

	if (!of_property_present(node, "xiaomi,cell-supply")) {
		ret = platform_fg_ops_get_batt_cell_info(FG_IC_MASTER, &cell);
		if (ret)
			return ret;
		if (!cell)
			return -ENODATA;
		*second = !strcmp(cell, "lwn");
		return 0;
	}
	psy = power_supply_get_by_phandle(node, "xiaomi,cell-supply");
	if (IS_ERR(psy))
		return PTR_ERR(psy);
	if (!psy)
		return -EPROBE_DEFER;
	ret = power_supply_get_property(psy, POWER_SUPPLY_PROP_MANUFACTURER, &value);
	if (!ret) {
		if (value.strval)
			*second = !strcmp(value.strval, "lwn");
		else
			ret = -ENODATA;
	}
	power_supply_put(psy);
	return ret;
}

static bool mca_jeita_delta_valid(const struct mca_buckchg_jeita_data *rows, int count,
				 u32 delta, u32 limit)
{
	int i;

	for (i = 0; i < count; i++)
		if (rows[i].iterm > limit && rows[i].vterm <= delta)
			return false;
	return true;
}

static int mca_jeita_parse_weak(struct device_node *node, struct mca_buckchg_jeita_dev *info)
{
	const struct mca_buckchg_jeita_para *table = &info->jeita_para;
	u32 enabled, cfg[2];
	int ret;

	if (!IS_ENABLED(CONFIG_TARGET_PRODUCT_NEZHA) ||
	    !of_find_property(node, "support_weak_chg_vterm", NULL))
		return 0;
	ret = of_property_read_u32(node, "support_weak_chg_vterm", &enabled);
	if (ret || !enabled)
		return ret;
	if (of_property_count_u32_elems(node, "weak_chg_vterm_cfg") != ARRAY_SIZE(cfg))
		return -EINVAL;
	ret = of_property_read_u32_array(node, "weak_chg_vterm_cfg", cfg, ARRAY_SIZE(cfg));
	if (ret)
		return ret;
	if (cfg[0] > INT_MAX || !cfg[1] || cfg[1] > INT_MAX ||
	    !mca_jeita_delta_valid(table->jeita_data, table->size, cfg[0], cfg[1]) ||
	    !mca_jeita_delta_valid(table->jeita_ffc_data, table->fcc_size, cfg[0], cfg[1]))
		return -EINVAL;
	info->weak_delta_mv = cfg[0];
	info->weak_iterm_ma = cfg[1];
	return 0;
}

static int mca_buckchg_jeita_parse_dt(struct mca_buckchg_jeita_dev *info)
{
	struct mca_buckchg_jeita_para *jeita_info = &info->jeita_para;
	struct mca_buckchg_jeita_para *base_jeita_info = &info->base_jeita_para;
	struct mca_buckchg_jeita_para *flip_jeita_info = &info->flip_jeita_para;
	struct device_node *node = of_node_get(info->dev->of_node);
	const struct mca_hwid *hwid = mca_get_hwid_info();
	const char *dev_name = NULL;
	int ret;

	mca_parse_dts_u32(node, "vbat_high_hyst", &(info->vbat_high_hyst),
			  MCA_BUCKCHG_JEITA_VBAT_HIGH_HYST);
	mca_parse_dts_u32(node, "vbat_low_hyst", &(info->vbat_low_hyst),
			  MCA_BUCKCHG_JEITA_VBAT_LOW_HYST);
	mca_parse_dts_u32(node, "vbat_low_cold_hyst",
			  &(info->vbat_low_cold_hyst),
			  MCA_BUCKCHG_JEITA_VBAT_LOW_HYST);
	mca_parse_dts_u32(node, "base_vbat_low_hyst",
			  &(info->base_vbat_low_hyst),
			  MCA_BUCKCHG_JEITA_VBAT_LOW_HYST);
	mca_parse_dts_u32(node, "flip_vbat_low_hyst",
			  &(info->flip_vbat_low_hyst),
			  MCA_BUCKCHG_JEITA_VBAT_LOW_HYST);
	mca_parse_dts_u32(node, "jeita_hot_termination_hyst",
			  &(info->jeita_hot_termination_hyst), 0);
	info->has_gbl_batt_para =
		of_property_read_bool(node, "has-global-batt-para");
	if (IS_ENABLED(CONFIG_TARGET_PRODUCT_NEZHA) && info->has_gbl_batt_para &&
	    (!hwid || hwid->country_version > CountryJapan)) {
		ret = -ENODATA;
		goto out;
	}
	if (hwid && info->has_gbl_batt_para &&
	    hwid->country_version != CountryCN) {
		of_node_put(node);
		node = of_find_node_by_name(NULL, "mca_buckchg_jeita_gbl_para");
	}

	if (!node) {
		mca_log_err("node in null\n");
		ret = -EINVAL;
		goto out;
	}

	info->has_tmp_batt_para =
		of_property_read_bool(node, "has-tmp-batt-para");
	if (info->has_tmp_batt_para) {
		platform_fg_ops_get_device_name(FG_IC_MASTER, &dev_name);
		if (!dev_name) {
			mca_log_err("get device name fail, wait for it\n");
			ret = -EPROBE_DEFER;
			goto out;
		}
		mca_log_err("project O9 tmp test: device name: %s\n", dev_name);
		if (!strcmp(dev_name, "2@BP")) {
			of_node_put(node);
			node = of_find_node_by_name(
				NULL, "mca_buckchg_jeita_tmp_para");
			if (!node) {
				mca_log_err("has-tmp-batt-para node in null\n");
				ret = -EINVAL;
				goto out;
			}
		}
	}

	if (of_property_read_bool(node, "has-second-batt-para")) {
		bool second;

		ret = mca_jeita_second_cell(node, &second);
		if (ret) {
			if (ret == -EAGAIN || ret == -EIO || ret == -ETIMEDOUT ||
			    ret == -EREMOTEIO)
				ret = -EPROBE_DEFER;
			goto out;
		}
		if (second) {
			struct device_node *parent = of_get_parent(node);

			of_node_put(node);
			node = of_get_child_by_name(parent, "mca_buckchg_jeita_second_para");
			of_node_put(parent);
			if (!node) {
				ret = -EINVAL;
				goto out;
			}
		}
	}

	ret = mca_buckchg_jeita_parse_para(info->dev, node, "jeita_para", jeita_info);
	if (!ret)
		ret = mca_jeita_parse_weak(node, info);
	if (ret)
		goto out;
	info->support_base_flip =
		of_property_read_bool(node, "support-base-flip");
	info->base_flip_same = of_property_read_bool(node, "base-flip-same");
	if (info->support_base_flip) {
		mca_log_err("support base flip, start config buckchg jeita\n");
		ret = mca_buckchg_jeita_parse_para(info->dev, node, "base_jeita_para",
						   base_jeita_info);
		if (ret)
			goto out;
		ret = mca_buckchg_jeita_parse_para(info->dev, node, "flip_jeita_para",
						   flip_jeita_info);
	}

out:
	of_node_put(node);
	return ret;
}

/* Nezha stock keeps each power source separately: unplugging USB while
 * wireless remains online must not stop battery temperature monitoring. */
static int mca_nezha_jeita_process_event(struct mca_buckchg_jeita_dev *info,
	int event, int value)
{
	bool online, old_usb;

	mutex_lock(&info->event_lock);
	if (READ_ONCE(info->stopping)) {
		mutex_unlock(&info->event_lock);
		return -ENODEV;
	}
	/* This dispatcher receives the shared OSS event enum, not raw OEM IDs.
	 * Stock 0x37 is a different ABI and collides with PLATE_SHOCK here. */
	if (event == MCA_EVENT_BATTERY_DTPT) {
		info->dtpt_status = value;
		goto out;
	}
	old_usb = info->usb_online;
	switch (event) {
	case MCA_EVENT_USB_CONNECT:
		WRITE_ONCE(info->usb_online, true);
		break;
	case MCA_EVENT_USB_DISCONNECT:
		WRITE_ONCE(info->usb_online, false);
		break;
	case MCA_EVENT_WIRELESS_CONNECT:
		info->wireless_online = true;
		break;
	case MCA_EVENT_WIRELESS_DISCONNECT:
		info->wireless_online = false;
		break;
	default:
		goto out;
	}
	online = info->usb_online || info->wireless_online;
	if (online == !!info->online) {
		if (online && info->weak_iterm_ma && old_usb != info->usb_online)
			mod_delayed_work(system_wq, &info->monitor_work, 0);
		goto out;
	}
	WRITE_ONCE(info->online, online);
	cancel_delayed_work_sync(&info->monitor_work);
	if (online) {
		info->proc_data.cur_jeita_index = -1;
		info->proc_data.max_chg_curr = 0;
		schedule_delayed_work(&info->monitor_work, 0);
	} else {
		info->flip_proc_data.cur_jeita_index = 0;
		info->flip_proc_data.temp_hys_en = 0;
		info->flip_proc_data.max_chg_curr = -1;
		info->base_proc_data.cur_jeita_index = 0;
		info->base_proc_data.temp_hys_en = 0;
		info->base_proc_data.max_chg_curr = -1;
	}
out:
	mutex_unlock(&info->event_lock);
	return 0;
}

static int mca_buckchg_jeita_process_event(int event, int value, void *data)
{
	struct mca_buckchg_jeita_dev *info = data;

	if (!info)
		return -EINVAL;
	if (READ_ONCE(info->stopping))
		return -ENODEV;

	if (IS_ENABLED(CONFIG_TARGET_PRODUCT_NEZHA))
		return mca_nezha_jeita_process_event(info, event, value);

	mca_log_info("receive event %d, value %d\n", event, value);
	switch (event) {
	case MCA_EVENT_USB_CONNECT:
	case MCA_EVENT_WIRELESS_CONNECT:
		info->online = 1;
		info->proc_data.cur_jeita_index = -1;
		info->proc_data.max_chg_curr = 0;
		cancel_delayed_work_sync(&info->monitor_work);
		schedule_delayed_work(&info->monitor_work, 0);
		break;
	case MCA_EVENT_USB_DISCONNECT:
	case MCA_EVENT_WIRELESS_DISCONNECT:
		info->online = 0;
		cancel_delayed_work_sync(&info->monitor_work);
		info->flip_proc_data.cur_jeita_index = 0;
		info->flip_proc_data.temp_hys_en = 0;
		info->flip_proc_data.max_chg_curr = -1;
		info->base_proc_data.cur_jeita_index = 0;
		info->base_proc_data.temp_hys_en = 0;
		info->base_proc_data.max_chg_curr = -1;
		break;
	case MCA_EVENT_BATTERY_DTPT:
		info->dtpt_status = value;
		break;
	default:
		break;
	}

	return 0;
}

static int
mca_strategy_buckchg_jeita_get_normal_vterm(struct mca_buckchg_jeita_dev *info)
{
	int cur_normal_vterm = 0, temp = 0;
	int ret, i;
	struct mca_buckchg_jeita_data *cur_jeita_data;

	ret = strategy_class_fg_ops_get_temperature(&temp);
	if (ret) {
		mca_log_err("get battery temp failed\n");
		return 0;
	}
	temp /= 10;

	for (i = 0; i < info->jeita_para.size; i++) {
		cur_jeita_data = info->jeita_para.jeita_data + i;
		if (temp < cur_jeita_data->temp_high &&
		    temp >= cur_jeita_data->temp_low)
			break;
	}
	if (i == info->jeita_para.size) {
		mca_log_err("can not find jeita para\n");
		return 0;
	}

	cur_normal_vterm = cur_jeita_data->vterm;

	return cur_normal_vterm;
}

static int
mca_strategy_buckchg_jeita_get_ffc_iterm(struct mca_buckchg_jeita_dev *info)
{
	int cur_ffc_itrem = 0, temp = 0;
	int ret, i;
	struct mca_buckchg_jeita_data *cur_jeita_data;

	ret = strategy_class_fg_ops_get_temperature(&temp);
	if (ret) {
		mca_log_err("get battery temp failed\n");
		return 0;
	}
	temp /= 10;

	for (i = 0; i < info->jeita_para.fcc_size; i++) {
		cur_jeita_data = info->jeita_para.jeita_ffc_data + i;
		if (temp < cur_jeita_data->temp_high &&
		    temp >= cur_jeita_data->temp_low)
			break;
	}
	if (i == info->jeita_para.fcc_size) {
		mca_log_err("can not find jeita fcc para\n");
		return 0;
	}

	cur_ffc_itrem = cur_jeita_data->iterm;

	return cur_ffc_itrem;
}

static int
mca_strategy_buckchg_jeita_get_ffc_vterm(struct mca_buckchg_jeita_dev *info)
{
	int cur_ffc_vterm = 0, temp = 0;
	int ret, i;
	struct mca_buckchg_jeita_data *cur_jeita_data;

	ret = strategy_class_fg_ops_get_temperature(&temp);
	if (ret) {
		mca_log_err("get battery temp failed\n");
		return 0;
	}
	temp /= 10;

	for (i = 0; i < info->jeita_para.fcc_size; i++) {
		cur_jeita_data = info->jeita_para.jeita_ffc_data + i;
		if (temp < cur_jeita_data->temp_high &&
		    temp >= cur_jeita_data->temp_low)
			break;
	}
	if (i == info->jeita_para.fcc_size) {
		mca_log_err("can not find jeita fcc para\n");
		return 0;
	}

	cur_ffc_vterm = cur_jeita_data->vterm;

	return cur_ffc_vterm;
}

static int mca_strategy_buckchg_jeita_get_status(int status, void *value,
						 void *data)
{
	struct mca_buckchg_jeita_dev *info =
		(struct mca_buckchg_jeita_dev *)data;
	int *cur_val = (int *)value;

	if (!info || !value)
		return -1;

	if (READ_ONCE(info->stopping))
		return -ENODEV;

	switch (status) {
	case STRATEGY_STATUS_TYPE_JEITA_FFC_ITERM:
		*cur_val = mca_strategy_buckchg_jeita_get_ffc_iterm(info);
		break;
	case STRATEGY_STATUS_TYPE_JEITA_NORMAL_VTERM:
		*cur_val = mca_strategy_buckchg_jeita_get_normal_vterm(info);
		break;
	case STRATEGY_STATUS_TYPE_JEITA_FFC_VTERM:
		*cur_val = mca_strategy_buckchg_jeita_get_ffc_vterm(info);
		break;
	case STRATEGY_STATUS_TYPE_JEITA_COLD_ZONE:
		*cur_val = info->cold_zone;
		break;
	default:
		return -1;
	}

	return 0;
}

static int mca_jeita_smartchg_delta_fv_callback(void *data,
						int effective_result)
{
	struct mca_buckchg_jeita_dev *info =
		(struct mca_buckchg_jeita_dev *)data;

	if (!data)
		return -1;

	if (READ_ONCE(info->stopping))
		return -ENODEV;

	info->smartchg_data.delta_fv = effective_result;
	mca_log_err("effective_result: %d\n", effective_result);

	return 0;
}

static int mca_buckchg_jeita_smartchg_baa_update_jeita_data(
	struct mca_buckchg_jeita_data *jeita_data,
	struct smart_batt_jeita_term_para *para)
{
	int max_volt_idx = jeita_data->volt_para.size - 1;

	mca_log_info(
		"jeita_term_para idx: %d, temp: %d:%d => %d:%d, vterm: %d => %d, iterm: %d => %d\n",
		para->t_range.idx, para->t_range.min, para->t_range.max,
		jeita_data->temp_low, jeita_data->temp_high, jeita_data->vterm,
		para->vterm, jeita_data->iterm, para->iterm);

	jeita_data->vterm = para->vterm;
	jeita_data->iterm = para->iterm;
	if (jeita_data->volt_para.size > 0) {
		mca_log_info(
			"volt_data[%d].voltage: %d => %d\n", max_volt_idx,
			jeita_data->volt_para.volt_data[max_volt_idx].voltage,
			jeita_data->vterm);
		jeita_data->volt_para.volt_data[max_volt_idx].voltage =
			jeita_data->vterm;
	}

	return 0;
}

static int mca_buckchg_jeita_smartchg_update_baa_para(void *data,
						      char *baa_para,
						      int ffc_size,
						      int normal_size)
{
	struct mca_buckchg_jeita_dev *info =
		(struct mca_buckchg_jeita_dev *)data;
	struct smart_batt_jeita_term_para *jeita_term_para = NULL;
	int offset = 0;
	int index = 0;

	if (!data || !baa_para) {
		mca_log_err("data or baa_para is NULL\n");
		return -1;
	}

	if (READ_ONCE(info->stopping))
		return -ENODEV;

	// update ffc jeita para
	jeita_term_para = (struct smart_batt_jeita_term_para *)baa_para;
	for (int i = 0; i < ffc_size; i++) {
		index = jeita_term_para[i].t_range.idx;
		if (index < 0 || index >= info->jeita_para.fcc_size) {
			mca_log_err(
				"jeita_para.fcc_size: %d, invalid idx: %d\n",
				info->jeita_para.fcc_size, index);
		} else {
			mca_buckchg_jeita_smartchg_baa_update_jeita_data(
				&(info->jeita_para.jeita_ffc_data[index]),
				&(jeita_term_para[i]));
		}
	}

	// update normal jeita para
	offset = ffc_size * sizeof(struct smart_batt_jeita_term_para);
	jeita_term_para =
		(struct smart_batt_jeita_term_para *)(baa_para + offset);
	for (int i = 0; i < normal_size; i++) {
		index = jeita_term_para[i].t_range.idx;
		if (index < 0 || index >= info->jeita_para.size) {
			mca_log_err("jeita_para.size: %d, invalid idx: %d\n",
				    info->jeita_para.size, index);
		} else {
			mca_buckchg_jeita_smartchg_baa_update_jeita_data(
				&(info->jeita_para.jeita_data[index]),
				&(jeita_term_para[i]));
		}
	}

	info->baacfg_update = true;
	return 0;
}

static const struct mca_smartchg_if_ops g_jeita_smartchg_if_ops = {
	.type = MCA_SMARTCHG_IF_CHG_TYPE_JEITA,
	.data = NULL,
	.set_delta_fv = mca_jeita_smartchg_delta_fv_callback,
	.set_delta_ichg = NULL,
	.update_baa_para = mca_buckchg_jeita_smartchg_update_baa_para,
};

static void mca_buckchg_jeita_stop(struct mca_buckchg_jeita_dev *info)
{
	bool had_strategy;
	int ret;

	if (!info || READ_ONCE(info->stopping))
		return;
	WRITE_ONCE(info->stopping, true);
	had_strategy = info->strategy_registered;
	if (info->strategy_registered) {
		mca_strategy_ops_unregister(STRATEGY_FUNC_TYPE_JEITA, info);
		info->strategy_registered = false;
	}
	if (info->smartchg_registered) {
		mca_smartchg_if_ops_unregister(MCA_SMARTCHG_IF_CHG_TYPE_JEITA,
					      info);
		info->smartchg_registered = false;
	}
	/* No dispatcher can enqueue more work after both unregisters return. */
	cancel_delayed_work_sync(&info->monitor_work);
	/* Retain temperature limits and inhibit charging while JEITA is absent.
	 * A later provider must sample temperature before enabling it again.
	 */
	if (had_strategy && info->en_voter) {
		ret = mca_vote(info->en_voter, "jeita", true, 0);
		if (ret)
			mca_log_err("failed to inhibit charging on JEITA stop: %d\n", ret);
	}
	if (info->flip_fcc_voter) {
		mca_detach_owned_votable(info->flip_fcc_voter, info);
		info->flip_fcc_voter = NULL;
	}
}

static int mca_buckchg_jeita_probe(struct platform_device *pdev)
{
	struct mca_buckchg_jeita_dev *info;
	struct mca_smartchg_if_ops smartchg_ops = g_jeita_smartchg_if_ops;
	struct mca_votable *flip;
	int ret;
	int online = 0, wireless_online = 0;

	info = devm_kzalloc(&pdev->dev, sizeof(*info), GFP_KERNEL);
	if (!info)
		return -ENOMEM;

	info->dev = &pdev->dev;
	platform_set_drvdata(pdev, info);
	mutex_init(&info->event_lock);
	INIT_DELAYED_WORK(&info->monitor_work, mca_buckchg_jeita_monitor_work);
	ret = mca_buckchg_jeita_parse_dt(info);
	if (ret)
		return dev_err_probe(&pdev->dev, ret, "invalid/unavailable JEITA parameters\n");

	/* A slab phone must not acquire the foldable-only load-switch voter. */
	if (info->support_base_flip) {
		flip = mca_create_owned_votable("flip_charge_curr", MCA_VOTE_MIN,
			mca_buckchg_jeita_flip_charge_limit,
			MCA_BUCKCHG_JEITA_FLIP_CURRENT_DEFAULT_VALUE, info);
		if (IS_ERR(flip))
			return PTR_ERR(flip);
		info->flip_fcc_voter = flip;
		/* The first temperature-derived vote replays retained constraints. */
	}
	mca_buckchg_jeita_init_voter(info);

	ret = mca_strategy_func_get_status(STRATEGY_FUNC_TYPE_BUCK_CHARGE,
					 STRATEGY_STATUS_TYPE_ONLINE, &online);
	if (ret)
		online = 0;
	ret = mca_strategy_func_get_status(STRATEGY_FUNC_TYPE_BASIC_WIRELESS,
					 STRATEGY_STATUS_TYPE_ONLINE, &wireless_online);
	if (ret)
		wireless_online = 0;
	info->usb_online = !!online;
	info->wireless_online = !!wireless_online;
	info->online = !!online || !!wireless_online;

	ret = mca_strategy_ops_register(STRATEGY_FUNC_TYPE_JEITA,
				       mca_buckchg_jeita_process_event,
				       mca_strategy_buckchg_jeita_get_status,
				       NULL, info);
	if (ret)
		goto fail;
	info->strategy_registered = true;
	smartchg_ops.data = info;
	ret = mca_smartchg_if_ops_register(&smartchg_ops);
	if (ret)
		goto fail;
	info->smartchg_registered = true;

	/* A live Nezha event may already have changed the initial online state. */
	mutex_lock(&info->event_lock);
	if (info->online || !info->voter_ok)
		schedule_delayed_work(&info->monitor_work, info->online ? 0 :
			msecs_to_jiffies(MCA_BUCKCHG_JEITA_INIT_VOTER_INTERVAL));
	mutex_unlock(&info->event_lock);
	return 0;
fail:
	mca_buckchg_jeita_stop(info);
	return ret;
}

static void mca_buckchg_jeita_remove(struct platform_device *pdev)
{
	mca_buckchg_jeita_stop(platform_get_drvdata(pdev));
}

static void mca_buckchg_jeita_shutdown(struct platform_device *pdev)
{
	mca_buckchg_jeita_stop(platform_get_drvdata(pdev));
}

static const struct of_device_id match_table[] = {
	{ .compatible = "mca,buckchg_jeita" },
	{},
};

static struct platform_driver mca_buckchg_jeita_driver = {
	.driver	= {
		.name = "mca_buckchg_jeita",
		.owner = THIS_MODULE,
		.of_match_table = match_table,
	},
	.probe = mca_buckchg_jeita_probe,
	.remove = mca_buckchg_jeita_remove,
	.shutdown = mca_buckchg_jeita_shutdown,
};

static int __init mca_buckchg_jeita_init(void)
{
	return platform_driver_register(&mca_buckchg_jeita_driver);
}
module_init(mca_buckchg_jeita_init);

static void __exit mca_buckchg_jeita_exit(void)
{
	platform_driver_unregister(&mca_buckchg_jeita_driver);
}
module_exit(mca_buckchg_jeita_exit);

MODULE_DESCRIPTION("buckchg jeita");
MODULE_AUTHOR("liyuze1@xiaomi.com");
MODULE_LICENSE("GPL v2");
