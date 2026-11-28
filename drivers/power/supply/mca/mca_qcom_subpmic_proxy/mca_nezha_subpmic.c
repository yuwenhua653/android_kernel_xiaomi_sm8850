// SPDX-License-Identifier: GPL-2.0-only
/* Nezha OS4 sub-PMIC transport. Charging policy belongs to the consumers. */
#include <linux/module.h>
#include <linux/atomic.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/power_supply.h>
#include <linux/workqueue.h>
#include <linux/unaligned.h>
#include <mca/strategy/strategy_class.h>
#include <mca/common/mca_adsp_glink.h>
#include <mca/common/mca_event.h>
#include <mca/common/mca_nezha_psy.h>
#include <mca/platform/platform_bc12_class.h>
#include <mca/platform/platform_buckchg_class.h>
#include <mca/protocol/protocol_pd_class.h>

/* Verified against OS4.0.7.0.XPACNXM mca_qcom_subpmic_proxy.ko.
 * Do not substitute the Myron property enum: offsets differ after 0x200f.
 */
enum nezha_subpmic_property {
	NEZHA_TOO_HOT_LIMIT = 0x0007,
	NEZHA_OVP_THRESHOLD = 0x0008,
	NEZHA_WLS_INPUT_CURRENT = 0x1003,
	NEZHA_WLS_SUSPEND = 0x1004,
	NEZHA_WLS_CURRENT = 0x1007,
	NEZHA_WLS_VDD = 0x100c,
	NEZHA_CHG_STATUS = 0x2001,
	NEZHA_CHG_TYPE = 0x2002,
	NEZHA_CHG_ENABLE = 0x2003,
	NEZHA_BUCK_FREQUENCY = 0x2004,
	NEZHA_CHG_CURRENT = 0x2005,
	NEZHA_TERM_CURRENT = 0x2006,
	NEZHA_TERM_VOLTAGE = 0x2007,
	NEZHA_INPUT_CURRENT = 0x2008,
	NEZHA_INPUT_VOLTAGE = 0x2009,
	NEZHA_PRECHARGE_CURRENT = 0x200a,
	NEZHA_PRECHARGE_VOLTAGE = 0x200b,
	NEZHA_SYSTEM_VOLTAGE = 0x200c,
	NEZHA_OTG_BOOST_STATUS = 0x200d,
	NEZHA_OTG_GATE_STATUS = 0x200e,
	NEZHA_BOOST_ENABLE = 0x200f,
	NEZHA_BOOST_VOLTAGE = 0x2012,
	NEZHA_AICL_ENABLE = 0x2014,
	NEZHA_AICL_RERUN = 0x2015,
	NEZHA_AICL_RESTART = 0x2016,
	NEZHA_AICL_THRESHOLD = 0x2017,
	NEZHA_OPT_FWS = 0x2019,
	NEZHA_ADAPTER_OVERRIDE = 0x201a,
	NEZHA_QC3_VOLTAGE = 0x201b,
	NEZHA_INPUT_SUSPEND = 0x201c,
	NEZHA_LPD_SBU1 = 0x201f,
	NEZHA_LPD_SBU2 = 0x2020,
	NEZHA_LPD_CC1 = 0x2021,
	NEZHA_LPD_CC2 = 0x2022,
	NEZHA_LPD_DP = 0x2023,
	NEZHA_LPD_DM = 0x2024,
	NEZHA_LPD_CONTROL = 0x2025,
	NEZHA_LPD_UART_CONTROL = 0x2026,
	NEZHA_PACK_VOLTAGE = 0x2027,
	NEZHA_PACK_CURRENT = 0x2028,
	NEZHA_EU_MODEL = 0x2029,
	NEZHA_PACK_TEMPERATURE = 0x202b,
	NEZHA_SCREEN_STATUS = 0x202d,
	NEZHA_USB_SWAP = 0x10005,
	NEZHA_WLS_SWAP = 0x10006,
	NEZHA_USB_ONLINE = 0x20001,
	NEZHA_BUS_VOLTAGE = 0x20002,
	NEZHA_USB_SNS_VOLTAGE = 0x20003,
	NEZHA_BUS_CURRENT = 0x20004,
	NEZHA_LPD_ENABLE = 0x20009,
	NEZHA_LPD_STATUS = 0x2000a,
	NEZHA_USB_REAL_TYPE = 0x2000c,
	NEZHA_USBIN_STATUS = 0x2000e,
	NEZHA_AUDIO_STATUS = 0x2102c,
};

struct nezha_subpmic {
	struct power_supply *usb;
	struct device *dev;
	struct workqueue_struct *events;
	struct mutex eu_lock;
	atomic_t link_epoch;
	bool eu_model;
	bool eu_requested;
	struct delayed_work update_work;
	int online;
	int real_type;
	unsigned int retries;
	atomic_t generation;
	int seen_generation;
	bool ready;
	bool stopping;
};

#define NEZHA_READ_OP(name, prop) \
static int name(void *data, int *value) \
{ \
	return mca_adsp_glink_read_prop(prop, value, sizeof(*value)); \
}

NEZHA_READ_OP(nezha_get_bus_voltage, NEZHA_BUS_VOLTAGE)
NEZHA_READ_OP(nezha_get_bus_current, NEZHA_BUS_CURRENT)
NEZHA_READ_OP(nezha_get_usb_sns_voltage, NEZHA_USB_SNS_VOLTAGE)
NEZHA_READ_OP(nezha_get_input_current, NEZHA_INPUT_CURRENT)
NEZHA_READ_OP(nezha_get_chg_status, NEZHA_CHG_STATUS)
NEZHA_READ_OP(nezha_get_chg_type, NEZHA_CHG_TYPE)
NEZHA_READ_OP(nezha_get_term_current, NEZHA_TERM_CURRENT)
NEZHA_READ_OP(nezha_get_term_voltage, NEZHA_TERM_VOLTAGE)

static int nezha_get_online(void *data, int *value)
{
	int ret, online;

	ret = mca_adsp_glink_read_prop(NEZHA_USB_ONLINE, &online, sizeof(online));
	if (ret)
		return ret;
	if (online != 0 && online != 1)
		return -EPROTO;
	*value = online;
	return 0;
}

static int nezha_get_real_type(int *value, void *data)
{
	return mca_adsp_glink_read_prop(NEZHA_USB_REAL_TYPE, value, sizeof(*value));
}

static int nezha_is_ready(void *data)
{
	struct nezha_subpmic *sc = data;

	return READ_ONCE(sc->ready) &&
		READ_ONCE(sc->seen_generation) == atomic_read(&sc->generation);
}

/* The stock MCA setters send the consumer's 32-bit value without scaling.
 * These are kernel callbacks, not writable power_supply attributes. No limits,
 * OTG configuration or charger-enable requests are written during probe.
 */
#define NEZHA_WRITE_OP(name, prop) \
static int name(void *data, int value) \
{ \
	if (value < 0) \
		return -EINVAL; \
	return mca_adsp_glink_write_prop(prop, &value, sizeof(value)); \
}

NEZHA_WRITE_OP(nezha_set_input_current, NEZHA_INPUT_CURRENT)
NEZHA_WRITE_OP(nezha_set_input_voltage, NEZHA_INPUT_VOLTAGE)
NEZHA_WRITE_OP(nezha_set_charge_current, NEZHA_CHG_CURRENT)
NEZHA_WRITE_OP(nezha_set_term_current, NEZHA_TERM_CURRENT)
NEZHA_WRITE_OP(nezha_set_term_voltage, NEZHA_TERM_VOLTAGE)

static int nezha_set_suspend(void *data, bool suspend)
{
	u8 value = suspend;

	return mca_adsp_glink_write_prop(NEZHA_INPUT_SUSPEND, &value, sizeof(value));
}

static int nezha_set_charge(void *data, bool enable)
{
	u8 value = enable;

	return mca_adsp_glink_write_prop(NEZHA_CHG_ENABLE, &value, sizeof(value));
}

#define NEZHA_WRITE_BOOL(name, prop) \
static int name(void *data, bool enable) \
{ \
	u8 value = enable; \
	return mca_adsp_glink_write_prop(prop, &value, sizeof(value)); \
}

#define NEZHA_READ_BOOL(name, prop) \
static int name(void *data, bool *enabled) \
{ \
	u8 value; \
	int ret = mca_adsp_glink_read_prop(prop, &value, sizeof(value)); \
	if (ret) \
		return ret; \
	if (value > 1) \
		return -EPROTO; \
	*enabled = value; \
	return 0; \
}

NEZHA_WRITE_OP(nezha_set_too_hot_limit, NEZHA_TOO_HOT_LIMIT)
NEZHA_READ_OP(nezha_get_ovp_vth, NEZHA_OVP_THRESHOLD)
NEZHA_WRITE_OP(nezha_set_ovp_vth, NEZHA_OVP_THRESHOLD)
NEZHA_WRITE_OP(nezha_set_wls_input_curr_lmt, NEZHA_WLS_INPUT_CURRENT)
NEZHA_WRITE_BOOL(nezha_set_wls_hiz, NEZHA_WLS_SUSPEND)
NEZHA_READ_OP(nezha_get_wls_curr, NEZHA_WLS_CURRENT)
NEZHA_WRITE_BOOL(nezha_set_wls_vdd_flag, NEZHA_WLS_VDD)
NEZHA_WRITE_OP(nezha_set_buck_fsw, NEZHA_BUCK_FREQUENCY)
NEZHA_WRITE_OP(nezha_set_prechg_curr, NEZHA_PRECHARGE_CURRENT)
NEZHA_WRITE_OP(nezha_set_prechg_volt, NEZHA_PRECHARGE_VOLTAGE)
NEZHA_READ_OP(nezha_get_sys_volt, NEZHA_SYSTEM_VOLTAGE)
NEZHA_READ_OP(nezha_get_otg_boost_enable_status, NEZHA_OTG_BOOST_STATUS)
NEZHA_READ_OP(nezha_get_otg_gate_enable_status, NEZHA_OTG_GATE_STATUS)
NEZHA_WRITE_OP(nezha_set_boost_enable, NEZHA_BOOST_ENABLE)
NEZHA_WRITE_OP(nezha_set_boost_voltage, NEZHA_BOOST_VOLTAGE)
NEZHA_WRITE_BOOL(nezha_set_aicl_enable, NEZHA_AICL_ENABLE)
NEZHA_WRITE_BOOL(nezha_set_rerun_aicl, NEZHA_AICL_RERUN)
NEZHA_WRITE_BOOL(nezha_set_restart_aicl, NEZHA_AICL_RESTART)
NEZHA_READ_OP(nezha_get_usb_aicl_cont_thd, NEZHA_AICL_THRESHOLD)
NEZHA_WRITE_OP(nezha_set_usb_aicl_cont_thd, NEZHA_AICL_THRESHOLD)
NEZHA_WRITE_OP(nezha_set_opt_fws, NEZHA_OPT_FWS)
NEZHA_WRITE_BOOL(nezha_usb_adapter_allow_override, NEZHA_ADAPTER_OVERRIDE)
NEZHA_WRITE_OP(nezha_set_qc3_volt, NEZHA_QC3_VOLTAGE)
NEZHA_READ_OP(nezha_get_lpd_sbu1, NEZHA_LPD_SBU1)
NEZHA_WRITE_OP(nezha_set_lpd_sbu1, NEZHA_LPD_SBU1)
NEZHA_READ_OP(nezha_get_lpd_sbu2, NEZHA_LPD_SBU2)
NEZHA_READ_OP(nezha_get_lpd_cc1, NEZHA_LPD_CC1)
NEZHA_READ_OP(nezha_get_lpd_cc2, NEZHA_LPD_CC2)
NEZHA_READ_OP(nezha_get_lpd_dp, NEZHA_LPD_DP)
NEZHA_READ_OP(nezha_get_lpd_dm, NEZHA_LPD_DM)
NEZHA_READ_OP(nezha_get_lpd_control, NEZHA_LPD_CONTROL)
NEZHA_WRITE_OP(nezha_set_lpd_control, NEZHA_LPD_CONTROL)
NEZHA_READ_OP(nezha_get_lpd_uart_control, NEZHA_LPD_UART_CONTROL)
NEZHA_WRITE_OP(nezha_set_lpd_uart_control, NEZHA_LPD_UART_CONTROL)
NEZHA_READ_OP(nezha_get_pack_vbat, NEZHA_PACK_VOLTAGE)
NEZHA_READ_OP(nezha_get_pack_ibat, NEZHA_PACK_CURRENT)
NEZHA_READ_OP(nezha_get_pack_tbat, NEZHA_PACK_TEMPERATURE)
NEZHA_WRITE_BOOL(nezha_set_screen_status, NEZHA_SCREEN_STATUS)
NEZHA_READ_BOOL(nezha_get_usb_input_swap, NEZHA_USB_SWAP)
NEZHA_READ_BOOL(nezha_get_wls_input_swap, NEZHA_WLS_SWAP)
NEZHA_READ_OP(nezha_get_lpd_enable, NEZHA_LPD_ENABLE)
NEZHA_READ_OP(nezha_get_lpd_status, NEZHA_LPD_STATUS)
NEZHA_WRITE_OP(nezha_set_audio_status, NEZHA_AUDIO_STATUS)

static int nezha_is_charge_done(void *data, bool *done)
{
	int status, ret = nezha_get_chg_status(data, &status);

	if (!ret)
		*done = status == MCA_BATT_CHGR_STATUS_TERMINATION;
	return ret;
}

static int nezha_get_usbin_collapse_rt_sts(void *data, int *collapsed)
{
	u32 value;
	int ret = mca_adsp_glink_read_prop(NEZHA_USBIN_STATUS, &value, sizeof(value));

	if (!ret)
		*collapsed = !!(value & BIT(1));
	return ret;
}

static int nezha_sync_region(struct nezha_subpmic *sc, bool enable)
{
	u8 value = enable;
	int epoch = atomic_read(&sc->link_epoch);
	int ret;

	ret = mca_adsp_glink_write_prop(NEZHA_EU_MODEL, &value, sizeof(value));
	if (!ret && epoch != atomic_read(&sc->link_epoch))
		return -ENOTCONN;
	if (!ret)
		WRITE_ONCE(sc->eu_model, enable);
	return ret;
}

static int nezha_set_eu_model(void *data, bool enable)
{
	struct nezha_subpmic *sc = data;
	int ret;

	guard(mutex)(&sc->eu_lock);
	ret = nezha_sync_region(sc, enable);
	if (!ret)
		sc->eu_requested = enable;
	return ret;
}

static struct platform_class_buckchg_ops nezha_buck_ops = {
	.is_init_ok = nezha_is_ready,
	.get_online = nezha_get_online,
	.get_bus_volt = nezha_get_bus_voltage,
	.get_bus_curr = nezha_get_bus_current,
	.get_usb_sns_volt = nezha_get_usb_sns_voltage,
	.get_input_curr_lmt = nezha_get_input_current,
	.get_chg_status = nezha_get_chg_status,
	.get_chg_type = nezha_get_chg_type,
	.get_term_curr = nezha_get_term_current,
	.get_term_volt = nezha_get_term_voltage,
	.set_hiz = nezha_set_suspend,
	.set_chg = nezha_set_charge,
	.set_input_curr_lmt = nezha_set_input_current,
	.set_input_volt_lmt = nezha_set_input_voltage,
	.set_ichg = nezha_set_charge_current,
	.set_term_curr = nezha_set_term_current,
	.set_term_volt = nezha_set_term_voltage,
	.set_too_hot_limit = nezha_set_too_hot_limit,
	.get_ovp_vth = nezha_get_ovp_vth,
	.set_ovp_vth = nezha_set_ovp_vth,
	.set_wls_input_curr_lmt = nezha_set_wls_input_curr_lmt,
	.set_wls_hiz = nezha_set_wls_hiz,
	.get_wls_curr = nezha_get_wls_curr,
	.set_wls_vdd_flag = nezha_set_wls_vdd_flag,
	.set_buck_fsw = nezha_set_buck_fsw,
	.set_prechg_curr = nezha_set_prechg_curr,
	.set_prechg_volt = nezha_set_prechg_volt,
	.get_sys_volt = nezha_get_sys_volt,
	.get_otg_boost_enable_status = nezha_get_otg_boost_enable_status,
	.get_otg_gate_enable_status = nezha_get_otg_gate_enable_status,
	.set_boost_enable = nezha_set_boost_enable,
	.set_boost_voltage = nezha_set_boost_voltage,
	.set_aicl_enable = nezha_set_aicl_enable,
	.set_rerun_aicl = nezha_set_rerun_aicl,
	.set_restart_aicl = nezha_set_restart_aicl,
	.get_usb_aicl_cont_thd = nezha_get_usb_aicl_cont_thd,
	.set_usb_aicl_cont_thd = nezha_set_usb_aicl_cont_thd,
	.set_opt_fws = nezha_set_opt_fws,
	.usb_adapter_allow_override = nezha_usb_adapter_allow_override,
	.set_qc3_volt = nezha_set_qc3_volt,
	.get_lpd_sbu1 = nezha_get_lpd_sbu1,
	.set_lpd_sbu1 = nezha_set_lpd_sbu1,
	.get_lpd_sbu2 = nezha_get_lpd_sbu2,
	.get_lpd_cc1 = nezha_get_lpd_cc1,
	.get_lpd_cc2 = nezha_get_lpd_cc2,
	.get_lpd_dp = nezha_get_lpd_dp,
	.get_lpd_dm = nezha_get_lpd_dm,
	.get_lpd_control = nezha_get_lpd_control,
	.set_lpd_control = nezha_set_lpd_control,
	.get_lpd_uart_control = nezha_get_lpd_uart_control,
	.set_lpd_uart_control = nezha_set_lpd_uart_control,
	.get_pack_vbat = nezha_get_pack_vbat,
	.get_pack_ibat = nezha_get_pack_ibat,
	.get_pack_tbat = nezha_get_pack_tbat,
	.set_screen_status = nezha_set_screen_status,
	.get_usb_input_swap = nezha_get_usb_input_swap,
	.get_wls_input_swap = nezha_get_wls_input_swap,
	.get_lpd_enable = nezha_get_lpd_enable,
	.get_lpd_status = nezha_get_lpd_status,
	.set_audio_status = nezha_set_audio_status,
	.is_charge_done = nezha_is_charge_done,
	.get_usbin_collapse_rt_sts = nezha_get_usbin_collapse_rt_sts,
	.set_eu_model = nezha_set_eu_model,
};

static struct platform_bc12_class_ops nezha_bc12_ops = {
	.get_charge_type = nezha_get_real_type,
};

static enum power_supply_property nezha_usb_properties[] = {
	POWER_SUPPLY_PROP_ONLINE,
	POWER_SUPPLY_PROP_VOLTAGE_NOW,
	POWER_SUPPLY_PROP_CURRENT_NOW,
};

static int nezha_usb_get_property(struct power_supply *psy,
		enum power_supply_property prop, union power_supply_propval *val)
{
	struct nezha_subpmic *sc = power_supply_get_drvdata(psy);

	switch (prop) {
	case POWER_SUPPLY_PROP_ONLINE:
		return nezha_get_online(sc, &val->intval);
	case POWER_SUPPLY_PROP_VOLTAGE_NOW:
		/* The stock get_bus_volt consumer divides by 1000 for mV. */
		return nezha_get_bus_voltage(sc, &val->intval);
	case POWER_SUPPLY_PROP_CURRENT_NOW:
		/* MCA buck consumers divide this value by 1000 for mA. */
		return nezha_get_bus_current(sc, &val->intval);
	default:
		return -EINVAL;
	}
}

static const struct power_supply_desc nezha_usb_desc = {
	.name = "usb",
	.type = POWER_SUPPLY_TYPE_USB,
	.properties = nezha_usb_properties,
	.num_properties = ARRAY_SIZE(nezha_usb_properties),
	.get_property = nezha_usb_get_property,
};

static void nezha_update_work(struct work_struct *work)
{
	struct nezha_subpmic *sc = container_of(to_delayed_work(work),
					      struct nezha_subpmic, update_work);
	int online, type, ret, generation;
	bool changed, recovered;

	if (READ_ONCE(sc->stopping))
		return;
	generation = atomic_read(&sc->generation);
	if (generation != sc->seen_generation) {
		WRITE_ONCE(sc->seen_generation, generation);
		sc->retries = 0;
	}
	mutex_lock(&sc->eu_lock);
	ret = sc->eu_requested && !READ_ONCE(sc->eu_model) ? nezha_sync_region(sc, true) : 0;
	mutex_unlock(&sc->eu_lock);
	if (!ret)
		ret = nezha_get_online(sc, &online);
	if (!ret)
		ret = nezha_get_real_type(&type, sc);
	if (ret) {
		if (READ_ONCE(sc->ready)) {
			WRITE_ONCE(sc->ready, false);
			if (sc->usb)
				power_supply_changed(sc->usb);
		}
		/* Link-up notifications restart discovery; do not poll a dead DSP. */
		if (ret != -ENOTCONN && sc->retries++ < 3 &&
		    !READ_ONCE(sc->stopping))
			mod_delayed_work(sc->events, &sc->update_work, msecs_to_jiffies(500));
		return;
	}
	/* A notification during the two reads invalidates this snapshot. */
	if (generation != atomic_read(&sc->generation)) {
		mod_delayed_work(sc->events, &sc->update_work, 0);
		return;
	}
	sc->retries = 0;
	recovered = !READ_ONCE(sc->ready);
	changed = recovered || online != sc->online || type != sc->real_type;
	WRITE_ONCE(sc->ready, true);
	if (recovered || online != sc->online) {
		sc->online = online;
		protocol_class_pd_set_pd_active(0, online);
		mca_event_block_notify(MCA_EVENT_TYPE_CHARGER_CONNECT,
				online ? MCA_EVENT_USB_CONNECT : MCA_EVENT_USB_DISCONNECT, NULL);
	}
	if (recovered || type != sc->real_type) {
		sc->real_type = type;
		mca_event_block_notify(MCA_EVENT_TYPE_CHARGE_TYPE,
				      MCA_EVENT_CHARGE_TYPE_CHANGE, &sc->real_type);
	}
	if (changed && sc->usb)
		power_supply_changed(sc->usb);
}

static void nezha_glink_state(void *priv)
{
	struct nezha_subpmic *sc = priv;

	if (!READ_ONCE(sc->stopping)) {
		atomic_inc(&sc->generation);
		mod_delayed_work(sc->events, &sc->update_work, 0);
	}
}

static void nezha_glink_down(void *priv)
{
	struct nezha_subpmic *sc = priv;

	atomic_inc(&sc->link_epoch);
	WRITE_ONCE(sc->ready, false);
	mutex_lock(&sc->eu_lock);
	WRITE_ONCE(sc->eu_model, false);
	mutex_unlock(&sc->eu_lock);
	nezha_glink_state(priv);
	if (!READ_ONCE(sc->stopping) && sc->usb)
		power_supply_changed(sc->usb);
}

enum nezha_notice {
	NEZHA_NOTIFY_USB = 0,
	NEZHA_NOTIFY_CHARGE_TYPE = 2,
	NEZHA_NOTIFY_LPD = 4,
	NEZHA_NOTIFY_PLATE = 5,
	NEZHA_NOTIFY_CC_SHORT = 6,
	NEZHA_NOTIFY_PPS_PTF = 7,
	NEZHA_NOTIFY_SINK_SUSPEND = 8,
	NEZHA_NOTIFY_CP_REVERT = 9,
};

struct nezha_notice_work {
	struct work_struct work;
	struct nezha_subpmic *sc;
	u32 id;
	int value;
	int epoch;
};

static void nezha_deliver_notice(struct work_struct *work)
{
	struct nezha_notice_work *notice = container_of(work, struct nezha_notice_work, work);
	struct nezha_subpmic *sc = notice->sc;
	bool suspend = !!notice->value;

	if (READ_ONCE(sc->stopping) || notice->epoch != atomic_read(&sc->link_epoch))
		goto out;
	switch (notice->id) {
	case NEZHA_NOTIFY_CHARGE_TYPE:
		mca_event_block_notify(MCA_EVENT_TYPE_CHARGE_TYPE, MCA_EVENT_CHARGE_CAP_CHANGE, NULL);
		break;
	case NEZHA_NOTIFY_LPD:
		mca_event_block_notify(MCA_EVENT_TYPE_HW_INFO, MCA_EVENT_LPD_STATUS_CHANGE,
				       &notice->value);
		break;
	case NEZHA_NOTIFY_PLATE:
		mca_event_block_notify(MCA_EVENT_TYPE_TYPEC_PORT_STATUS, MCA_EVENT_PLATE_SHOCK, NULL);
		break;
	case NEZHA_NOTIFY_CC_SHORT:
		mca_event_block_notify(MCA_EVENT_TYPE_HW_INFO, MCA_EVENT_CC_SHORT_VBUS, &notice->value);
		break;
	case NEZHA_NOTIFY_PPS_PTF:
		mca_strategy_func_process(STRATEGY_FUNC_TYPE_QUICK_CHARGE, MCA_EVENT_PPS_PTF, notice->value);
		mca_strategy_func_process(STRATEGY_FUNC_TYPE_BUCK_CHARGE, MCA_EVENT_PPS_PTF, notice->value);
		break;
	case NEZHA_NOTIFY_SINK_SUSPEND:
		mca_event_block_notify(MCA_EVENT_TYPE_CHARGE_TYPE, MCA_EVENT_SINK_PWR_SUSPEND_CHANGE, &suspend);
		break;
	case NEZHA_NOTIFY_CP_REVERT:
		mca_event_block_notify(MCA_EVENT_TYPE_HW_INFO, MCA_EVENT_CP_REVERT_CHANGE, &notice->value);
		break;
	}
out:
	kfree(notice);
}

static void nezha_glink_notify(u32 prop, void *data, u32 len, void *priv)
{
	struct nezha_subpmic *sc = priv;
	struct nezha_notice_work *notice;
	int value = 0, epoch = atomic_read(&sc->link_epoch);

	if (READ_ONCE(sc->stopping))
		return;
	switch (prop) {
	case NEZHA_NOTIFY_USB:
		nezha_glink_state(sc);
		return;
	case NEZHA_NOTIFY_SINK_SUSPEND:
		if (!READ_ONCE(sc->eu_model) || !data || !len)
			return;
		value = *(u8 *)data;
		if (value > 1)
			return;
		break;
	case NEZHA_NOTIFY_LPD:
	case NEZHA_NOTIFY_CC_SHORT:
	case NEZHA_NOTIFY_PPS_PTF:
	case NEZHA_NOTIFY_CP_REVERT:
		if (!data || len < sizeof(value))
			return;
		value = get_unaligned_le32(data);
		break;
	case NEZHA_NOTIFY_PLATE:
	case NEZHA_NOTIFY_CHARGE_TYPE:
		break;
	default:
		/* 11/12 are soft CID/CID on Nezha, not the Myron SBU LPD event. */
		return;
	}
	/* The sole GLINK receive worker must stay available for listener replies. */
	notice = kmalloc(sizeof(*notice), GFP_KERNEL);
	if (!notice) {
		dev_err_ratelimited(sc->dev, "cannot queue sub-PMIC notice %u\n", prop);
		return;
	}
	notice->sc = sc;
	notice->id = prop;
	notice->value = value;
	notice->epoch = epoch;
	INIT_WORK(&notice->work, nezha_deliver_notice);
	queue_work(sc->events, &notice->work);
}

static struct mca_adsp_glink_ops nezha_glink_ops = {
	.glink_state_up = nezha_glink_state,
	.glink_state_down = nezha_glink_down,
	.notification = nezha_glink_notify,
};

static void nezha_destroy_events(void *data)
{
	destroy_workqueue(data);
}

static int nezha_subpmic_probe(struct platform_device *pdev)
{
	static char *supplied_to[] = { "battery" };
	struct power_supply_config cfg = { .of_node = pdev->dev.of_node };
	struct nezha_subpmic *sc;
	int ret;

	sc = devm_kzalloc(&pdev->dev, sizeof(*sc), GFP_KERNEL);
	if (!sc)
		return -ENOMEM;
	sc->online = -1;
	sc->real_type = -1;
	atomic_set(&sc->generation, 0);
	INIT_DELAYED_WORK(&sc->update_work, nezha_update_work);
	cfg.drv_data = sc;
	cfg.supplied_to = supplied_to;
	cfg.num_supplicants = ARRAY_SIZE(supplied_to);
	sc->dev = &pdev->dev;
	if (!nezha_business_owns_supplies()) {
		sc->usb = devm_power_supply_register(sc->dev, &nezha_usb_desc, &cfg);
		if (IS_ERR(sc->usb))
			return dev_err_probe(sc->dev, PTR_ERR(sc->usb), "register USB supply\n");
	}
	mutex_init(&sc->eu_lock);
	sc->events = alloc_ordered_workqueue("nezha-subpmic", 0);
	if (!sc->events)
		return -ENOMEM;
	ret = devm_add_action_or_reset(&pdev->dev, nezha_destroy_events, sc->events);
	if (ret)
		return ret;
	ret = platform_class_buckchg_ops_register_v2(0, sc, &nezha_buck_ops,
						  sizeof(nezha_buck_ops));
	if (ret)
		return ret;
	ret = platform_bc12_class_ops_register(0, &nezha_bc12_ops, sc);
	if (ret)
		goto unregister_buck;
	ret = mca_adsp_glink_resister_ops(&nezha_glink_ops, sc);
	if (ret)
		goto unregister_bc12;
	platform_set_drvdata(pdev, sc);
	mod_delayed_work(sc->events, &sc->update_work, 0);
	return 0;

unregister_bc12:
	platform_bc12_class_ops_unregister(0, &nezha_bc12_ops, sc);
unregister_buck:
	platform_class_buckchg_ops_unregister(0, sc, &nezha_buck_ops);
	return ret;
}

static void nezha_subpmic_remove(struct platform_device *pdev)
{
	struct nezha_subpmic *sc = platform_get_drvdata(pdev);

	WRITE_ONCE(sc->stopping, true);
	mca_adsp_glink_unregister_ops(&nezha_glink_ops, sc);
	disable_delayed_work_sync(&sc->update_work);
	flush_workqueue(sc->events);
	platform_bc12_class_ops_unregister(0, &nezha_bc12_ops, sc);
	platform_class_buckchg_ops_unregister(0, sc, &nezha_buck_ops);
}

static const struct of_device_id nezha_subpmic_match[] = {
	{ .compatible = "mca,qcom_subpmic" },
	{ }
};
MODULE_DEVICE_TABLE(of, nezha_subpmic_match);

static struct platform_driver nezha_subpmic_driver = {
	.driver = { .name = "nezha_subpmic", .of_match_table = nezha_subpmic_match },
	.probe = nezha_subpmic_probe,
	.remove = nezha_subpmic_remove,
};
module_platform_driver(nezha_subpmic_driver);
MODULE_DESCRIPTION("Nezha OS4 sub-PMIC basic charging provider");
MODULE_LICENSE("GPL");
