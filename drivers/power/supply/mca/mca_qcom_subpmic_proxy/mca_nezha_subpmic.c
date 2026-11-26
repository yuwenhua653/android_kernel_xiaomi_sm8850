// SPDX-License-Identifier: GPL-2.0-only
/* Nezha OS4 sub-PMIC transport. Charging policy belongs to the consumers. */
#include <linux/module.h>
#include <linux/atomic.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/power_supply.h>
#include <linux/workqueue.h>
#include <mca/common/mca_adsp_glink.h>
#include <mca/common/mca_event.h>
#include <mca/platform/platform_bc12_class.h>
#include <mca/platform/platform_buckchg_class.h>
#include <mca/protocol/protocol_pd_class.h>

/* Verified against OS4.0.7.0.XPACNXM mca_qcom_subpmic_proxy.ko.
 * Do not substitute the Myron property enum: offsets differ after 0x200f.
 */
enum nezha_subpmic_property {
	NEZHA_CHG_STATUS = 0x2001,
	NEZHA_CHG_TYPE = 0x2002,
	NEZHA_CHG_ENABLE = 0x2003,
	NEZHA_CHG_CURRENT = 0x2005,
	NEZHA_TERM_CURRENT = 0x2006,
	NEZHA_TERM_VOLTAGE = 0x2007,
	NEZHA_INPUT_CURRENT = 0x2008,
	NEZHA_INPUT_VOLTAGE = 0x2009,
	NEZHA_INPUT_SUSPEND = 0x201c,
	NEZHA_USB_ONLINE = 0x20001,
	NEZHA_BUS_VOLTAGE = 0x20002,
	NEZHA_USB_SNS_VOLTAGE = 0x20003,
	NEZHA_BUS_CURRENT = 0x20004,
	NEZHA_USB_REAL_TYPE = 0x2000c,
};

struct nezha_subpmic {
	struct power_supply *usb;
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
	ret = nezha_get_online(sc, &online);
	if (!ret)
		ret = nezha_get_real_type(&type, sc);
	if (ret) {
		if (READ_ONCE(sc->ready)) {
			WRITE_ONCE(sc->ready, false);
			power_supply_changed(sc->usb);
		}
		/* Link-up notifications restart discovery; do not poll a dead DSP. */
		if (ret != -ENOTCONN && sc->retries++ < 3 &&
		    !READ_ONCE(sc->stopping))
			mod_delayed_work(system_wq, &sc->update_work, msecs_to_jiffies(500));
		return;
	}
	/* A notification during the two reads invalidates this snapshot. */
	if (generation != atomic_read(&sc->generation)) {
		mod_delayed_work(system_wq, &sc->update_work, 0);
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
	if (changed)
		power_supply_changed(sc->usb);
}

static void nezha_glink_state(void *priv)
{
	struct nezha_subpmic *sc = priv;

	if (!READ_ONCE(sc->stopping)) {
		atomic_inc(&sc->generation);
		mod_delayed_work(system_wq, &sc->update_work, 0);
	}
}

static void nezha_glink_down(void *priv)
{
	struct nezha_subpmic *sc = priv;

	WRITE_ONCE(sc->ready, false);
	nezha_glink_state(priv);
	if (!READ_ONCE(sc->stopping))
		power_supply_changed(sc->usb);
}

static void nezha_glink_notify(u32 prop, void *data, u32 len, void *priv)
{
	/* Re-read state in work context; do not assume Myron notification IDs. */
	nezha_glink_state(priv);
}

static struct mca_adsp_glink_ops nezha_glink_ops = {
	.glink_state_up = nezha_glink_state,
	.glink_state_down = nezha_glink_down,
	.notification = nezha_glink_notify,
};

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
	sc->usb = devm_power_supply_register(&pdev->dev, &nezha_usb_desc, &cfg);
	if (IS_ERR(sc->usb))
		return dev_err_probe(&pdev->dev, PTR_ERR(sc->usb), "register USB supply\n");
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
	mod_delayed_work(system_wq, &sc->update_work, 0);
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
	cancel_delayed_work_sync(&sc->update_work);
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
