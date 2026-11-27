// SPDX-License-Identifier: GPL-2.0-only
/* Read-only bridge from the Nezha BQ27Z561 power supply to MCA consumers. */
#include <linux/err.h>
#include <linux/limits.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/power_supply.h>
#include <linux/slab.h>
#include <mca/strategy/strategy_fg_class.h>

struct nezha_fg_psy {
	struct power_supply *psy;
};

static int nezha_fg_read(void *data, enum power_supply_property prop, int *out)
{
	struct nezha_fg_psy *fg = data;
	union power_supply_propval val;
	int ret;

	if (!fg || !out)
		return -EINVAL;
	ret = power_supply_get_property(fg->psy, prop, &val);
	if (ret)
		return ret;
	*out = val.intval;
	return 0;
}

#define NEZHA_FG_READ(name, prop) \
static int name(void *data, int *out) \
{ \
	return nezha_fg_read(data, prop, out); \
}

/* MCA uses deci-C and uAh, as does power_supply. */
NEZHA_FG_READ(nezha_fg_temp, POWER_SUPPLY_PROP_TEMP)
NEZHA_FG_READ(nezha_fg_cycle, POWER_SUPPLY_PROP_CYCLE_COUNT)
NEZHA_FG_READ(nezha_fg_dc, POWER_SUPPLY_PROP_CHARGE_FULL_DESIGN)
NEZHA_FG_READ(nezha_fg_rm, POWER_SUPPLY_PROP_CHARGE_NOW)
NEZHA_FG_READ(nezha_fg_fcc, POWER_SUPPLY_PROP_CHARGE_FULL)
NEZHA_FG_READ(nezha_fg_health, POWER_SUPPLY_PROP_HEALTH)

static int nezha_fg_soc(void *data, int *out)
{
	int val, ret;

	if (!out)
		return -EINVAL;
	ret = nezha_fg_read(data, POWER_SUPPLY_PROP_CAPACITY, &val);
	if (ret)
		return ret;
	if (val < 0 || val > 100)
		return -ERANGE;
	*out = val;
	return 0;
}

static int nezha_fg_get_soc(void *data)
{
	int soc, ret = nezha_fg_soc(data, &soc);

	return ret ? ret : soc;
}

static int nezha_fg_voltage(void *data, int *out)
{
	int uv, ret;

	if (!out)
		return -EINVAL;
	ret = nezha_fg_read(data, POWER_SUPPLY_PROP_VOLTAGE_NOW, &uv);
	if (ret)
		return ret;
	if (uv <= 0)
		return -ERANGE;
	/* MCA voltage consumers use mV. */
	*out = uv / 1000;
	return 0;
}

static int nezha_fg_current(void *data, int *out)
{
	int ua, ret;

	if (!out)
		return -EINVAL;
	ret = nezha_fg_read(data, POWER_SUPPLY_PROP_CURRENT_NOW, &ua);
	if (ret)
		return ret;
	if (ua == INT_MIN)
		return -ERANGE;
	/* BQ power_supply: positive charging. MCA: negative charging, still uA. */
	*out = -ua;
	return 0;
}

static int nezha_fg_ready(void *data)
{
	int present, ret = nezha_fg_read(data, POWER_SUPPLY_PROP_PRESENT, &present);

	return ret ? ret : !!present;
}

static bool nezha_fg_done(void *data)
{
	int status, ret = nezha_fg_read(data, POWER_SUPPLY_PROP_STATUS, &status);

	/* The legacy bool API cannot return errors; unknown must not mean full. */
	return !ret && status == POWER_SUPPLY_STATUS_FULL;
}

static struct strategy_fg_class_ops nezha_fg_ops = {
	.strategy_fg_is_init_ok = nezha_fg_ready,
	.strategy_fg_get_rsoc = nezha_fg_soc,
	.strategy_fg_get_soc = nezha_fg_get_soc,
	.strategy_fg_get_temp = nezha_fg_temp,
	.strategy_fg_get_current = nezha_fg_current,
	.strategy_fg_get_voltage = nezha_fg_voltage,
	.strategy_fg_get_cycle = nezha_fg_cycle,
	.strategy_fg_get_charging_done = nezha_fg_done,
	.strategy_fg_get_dc = nezha_fg_dc,
	.strategy_fg_get_rm = nezha_fg_rm,
	.strategy_fg_get_fcc = nezha_fg_fcc,
	.strategy_fg_get_health = nezha_fg_health,
	/* No emulated authentication, fast-charge control or proprietary telemetry. */
};

static void nezha_fg_unregister(void *data)
{
	strategy_class_fg_ops_unregister(data);
}

static int nezha_fg_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct nezha_fg_psy *fg;
	int ret;

	fg = devm_kzalloc(dev, sizeof(*fg), GFP_KERNEL);
	if (!fg)
		return -ENOMEM;
	fg->psy = devm_power_supply_get_by_phandle(dev, "power-supplies");
	if (IS_ERR(fg->psy))
		return dev_err_probe(dev, PTR_ERR(fg->psy), "battery supplier unavailable\n");
	if (!fg->psy)
		return dev_err_probe(dev, -EPROBE_DEFER, "waiting for battery supplier\n");
	ret = strategy_class_fg_ops_register(fg, &nezha_fg_ops);
	if (ret)
		return dev_err_probe(dev, ret, "cannot register fuel gauge bridge\n");
	/* LIFO: drain callbacks before power_supply_put and freeing fg. */
	return devm_add_action_or_reset(dev, nezha_fg_unregister, fg);
}

static const struct of_device_id nezha_fg_match[] = {
	{ .compatible = "xiaomi,nezha-fg-psy" },
	{ }
};
MODULE_DEVICE_TABLE(of, nezha_fg_match);

static struct platform_driver nezha_fg_driver = {
	.probe = nezha_fg_probe,
	.driver = {
		.name = "mca_nezha_fg_psy",
		.of_match_table = nezha_fg_match,
	},
};
module_platform_driver(nezha_fg_driver);
MODULE_DESCRIPTION("Nezha read-only MCA battery telemetry bridge");
MODULE_LICENSE("GPL");
