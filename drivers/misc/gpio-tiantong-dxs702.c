// SPDX-License-Identifier: GPL-2.0-only
/* Status inputs and supply readback for the DXS702 satellite modem. */
#include <linux/devm-helpers.h>
#include <linux/gpio/consumer.h>
#include <linux/hwmon-sysfs.h>
#include <linux/interrupt.h>
#include <linux/jiffies.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/pm_wakeirq.h>
#include <linux/regulator/consumer.h>

static const char * const dxs702_supplies[] = {
	"ttvddcore0p8", "ttrfavdd1p3", "ttvddsim1p8", "ttlna2p8",
	"ttvddio1p8", "ttvccflash1p8", "ttrf1p8", "ttdcdcpavcc4p6",
};

struct dxs702_input {
	struct device *dev;
	struct gpio_desc *gpio;
	const char *event;
	struct delayed_work work;
	struct mutex lock;
	unsigned long delay;
	unsigned long deadline;
	bool wakeup;
	int sample;
	int irq;
};

struct dxs702 {
	struct dxs702_input inputs[2];
	struct regulator *rails[ARRAY_SIZE(dxs702_supplies)];
};

static ssize_t line_show(struct device *dev, struct device_attribute *attr,
			 char *buf)
{
	struct dxs702 *modem = dev_get_drvdata(dev);
	int i = to_sensor_dev_attr(attr)->index;
	int val = gpiod_get_raw_value_cansleep(modem->inputs[i].gpio);

	return val < 0 ? val : sysfs_emit(buf, "%d\n", val);
}

static ssize_t voltage_show(struct device *dev, struct device_attribute *attr,
			    char *buf)
{
	struct dxs702 *modem = dev_get_drvdata(dev);
	int i = to_sensor_dev_attr(attr)->index;
	int uv = regulator_get_voltage(modem->rails[i]);

	return uv < 0 ? uv : sysfs_emit(buf, "%d\n", uv);
}

static SENSOR_DEVICE_ATTR_RO(bp_sleep_ap, line, 0);
static SENSOR_DEVICE_ATTR_RO(pmic_irq, line, 1);
static SENSOR_DEVICE_ATTR_RO(ldo1_vdd_core_0p8, voltage, 0);
static SENSOR_DEVICE_ATTR_RO(ldo2_rf_avdd_1p3, voltage, 1);
static SENSOR_DEVICE_ATTR_RO(ldo3_vdd_sim_1p8, voltage, 2);
static SENSOR_DEVICE_ATTR_RO(ldo4_lna_2P8, voltage, 3);
static SENSOR_DEVICE_ATTR_RO(ldo5_vdd_io_1p8, voltage, 4);
static SENSOR_DEVICE_ATTR_RO(ldo6_vcc_flash_1p8, voltage, 5);
static SENSOR_DEVICE_ATTR_RO(ldo7_rf_1p8, voltage, 6);
static SENSOR_DEVICE_ATTR_RO(dcdc_pavcc_4p6, voltage, 7);

static struct attribute *dxs702_attrs[] = {
	&sensor_dev_attr_bp_sleep_ap.dev_attr.attr,
	&sensor_dev_attr_pmic_irq.dev_attr.attr,
	&sensor_dev_attr_ldo1_vdd_core_0p8.dev_attr.attr,
	&sensor_dev_attr_ldo2_rf_avdd_1p3.dev_attr.attr,
	&sensor_dev_attr_ldo3_vdd_sim_1p8.dev_attr.attr,
	&sensor_dev_attr_ldo4_lna_2P8.dev_attr.attr,
	&sensor_dev_attr_ldo5_vdd_io_1p8.dev_attr.attr,
	&sensor_dev_attr_ldo6_vcc_flash_1p8.dev_attr.attr,
	&sensor_dev_attr_ldo7_rf_1p8.dev_attr.attr,
	&sensor_dev_attr_dcdc_pavcc_4p6.dev_attr.attr,
	NULL,
};
ATTRIBUTE_GROUPS(dxs702);

static void dxs702_report(struct work_struct *work)
{
	struct dxs702_input *input = container_of(to_delayed_work(work),
						  struct dxs702_input, work);
	char value[24];
	char *env[] = { value, NULL };
	int level;

	guard(mutex)(&input->lock);
	if (time_before(jiffies, input->deadline))
		return;
	level = gpiod_get_raw_value_cansleep(input->gpio);
	if (level >= 0 && level == input->sample) {
		snprintf(value, sizeof(value), "%s=%d", input->event, level);
		kobject_uevent_env(&input->dev->kobj, KOBJ_CHANGE, env);
	}
	input->sample = -ENODATA;
	if (input->wakeup)
		pm_relax(input->dev);
}

static irqreturn_t dxs702_irq(int irq, void *data)
{
	struct dxs702_input *input = data;

	guard(mutex)(&input->lock);
	if (input->wakeup && device_may_wakeup(input->dev))
		pm_stay_awake(input->dev);
	input->sample = gpiod_get_raw_value_cansleep(input->gpio);
	input->deadline = jiffies + input->delay;
	mod_delayed_work(system_wq, &input->work, input->delay);
	return IRQ_HANDLED;
}

static int dxs702_add_input(struct device *dev, struct dxs702_input *input,
			    const char *name, const char *event, u32 debounce)
{
	int ret;

	input->dev = dev;
	input->event = event;
	input->delay = msecs_to_jiffies(debounce);
	mutex_init(&input->lock);
	input->gpio = devm_gpiod_get(dev, name, GPIOD_IN);
	if (IS_ERR(input->gpio))
		return dev_err_probe(dev, PTR_ERR(input->gpio), "%s GPIO\n", name);
	input->irq = gpiod_to_irq(input->gpio);
	if (input->irq < 0)
		return dev_err_probe(dev, input->irq, "%s IRQ\n", name);

	/* Register cancellation first so devres frees the IRQ before the work. */
	ret = devm_delayed_work_autocancel(dev, &input->work, dxs702_report);
	if (ret)
		return ret;
	ret = devm_request_threaded_irq(dev, input->irq, NULL, dxs702_irq,
					IRQF_TRIGGER_RISING | IRQF_TRIGGER_FALLING |
					IRQF_ONESHOT, name, input);
	return ret ? dev_err_probe(dev, ret, "%s interrupt\n", name) : 0;
}

static void dxs702_disable_wakeup(void *dev)
{
	device_init_wakeup(dev, false);
}

static void dxs702_clear_wake_irq(void *dev)
{
	dev_pm_clear_wake_irq(dev);
}

static int dxs702_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct dxs702 *modem;
	u32 debounce = 30;
	int i, ret;

	modem = devm_kzalloc(dev, sizeof(*modem), GFP_KERNEL);
	if (!modem)
		return -ENOMEM;
	platform_set_drvdata(pdev, modem);
	for (i = 0; i < ARRAY_SIZE(dxs702_supplies); i++) {
		/* Require real providers, including when one is still probing. */
		modem->rails[i] = devm_regulator_get_optional(dev, dxs702_supplies[i]);
		if (IS_ERR(modem->rails[i]))
			return dev_err_probe(dev, PTR_ERR(modem->rails[i]),
					     "supply %s\n", dxs702_supplies[i]);
	}
	if (device_property_present(dev, "debounce-time")) {
		ret = device_property_read_u32(dev, "debounce-time", &debounce);
		if (ret)
			return ret;
	}
	ret = device_init_wakeup(dev, true);
	if (ret) {
		device_init_wakeup(dev, false);
		return ret;
	}
	ret = devm_add_action_or_reset(dev, dxs702_disable_wakeup, dev);
	if (ret)
		return ret;
	modem->inputs[0].wakeup = true;
	ret = dxs702_add_input(dev, &modem->inputs[0], "bp-sleep-ap", "STATUS", debounce);
	if (ret)
		return ret;
	ret = dxs702_add_input(dev, &modem->inputs[1], "pmic-irq", "PMIC_STATUS", debounce);
	if (ret)
		return ret;
	ret = dev_pm_set_wake_irq(dev, modem->inputs[0].irq);
	if (ret)
		return ret;
	return devm_add_action_or_reset(dev, dxs702_clear_wake_irq, dev);
}

static const struct of_device_id dxs702_match[] = {
	{ .compatible = "mdm,gpio-tiantong-dxs702" },
	{ }
};
MODULE_DEVICE_TABLE(of, dxs702_match);

static struct platform_driver dxs702_driver = {
	.probe = dxs702_probe,
	.driver = {
		.name = "gpio-tiantong-dxs702",
		.of_match_table = dxs702_match,
		.dev_groups = dxs702_groups,
	},
};
module_platform_driver(dxs702_driver);

MODULE_DESCRIPTION("Tiantong DXS702 wake, status and regulator readback");
MODULE_LICENSE("GPL");
