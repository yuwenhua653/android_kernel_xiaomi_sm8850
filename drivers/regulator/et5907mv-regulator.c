// SPDX-License-Identifier: GPL-2.0-only
/* Etek ET5907MV satellite LDO bank. */
#include <linux/delay.h>
#include <linux/i2c.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/pinctrl/consumer.h>
#include <linux/regmap.h>
#include <linux/regulator/driver.h>
#include <linux/regulator/machine.h>
#include <linux/regulator/of_regulator.h>

#define ET5907MV_OUTPUTS	7
#define ET5907MV_ENABLE		0x03
#define ET5907MV_LDO1_VSEL	0x04

struct et5907mv_output {
	struct regulator_desc desc;
	struct regulator_config config;
	unsigned int initial_sel;
	bool has_initial_sel;
};

/* VSEL zero reads back the factory default for that individual rail. */
static const int et5907mv_reset_uv[] = {
	1200000, 1200000, 3400000, 1800000, 1800000, 1800000, 2800000,
};

static int et5907mv_get_voltage_sel(struct regulator_dev *rdev)
{
	const struct regulator_desc *desc = rdev->desc;
	int sel = regulator_get_voltage_sel_regmap(rdev);

	if (sel)
		return sel;
	return 1 + (et5907mv_reset_uv[desc->id] - desc->min_uV) / desc->uV_step;
}

static const struct regulator_ops et5907mv_ops = {
	.enable = regulator_enable_regmap,
	.disable = regulator_disable_regmap,
	.is_enabled = regulator_is_enabled_regmap,
	.list_voltage = regulator_list_voltage_linear,
	.map_voltage = regulator_map_voltage_linear,
	.get_voltage_sel = et5907mv_get_voltage_sel,
	.set_voltage_sel = regulator_set_voltage_sel_regmap,
};

static const struct regmap_config et5907mv_regmap = {
	.reg_bits = 8,
	.val_bits = 8,
	.max_register = ET5907MV_LDO1_VSEL + ET5907MV_OUTPUTS - 1,
};

static int et5907mv_parse_output(struct device *dev, struct device_node *child,
				 unsigned int id, struct regmap *map,
				 struct et5907mv_output *out)
{
	struct regulator_desc *desc = &out->desc;
	struct regulator_init_data *init;
	unsigned int base_uv = id < 2 ? 600000 : 1200000;
	unsigned int step_uv = id < 2 ? 6000 : 10000;
	unsigned int uv, sel;
	int ret;

	desc->type = REGULATOR_VOLTAGE;
	desc->owner = THIS_MODULE;
	desc->ops = &et5907mv_ops;
	desc->id = id;
	desc->min_uV = base_uv + step_uv;
	desc->uV_step = step_uv;
	desc->linear_min_sel = 1;
	desc->n_voltages = 256;
	desc->enable_reg = ET5907MV_ENABLE;
	desc->enable_mask = BIT(id);
	desc->vsel_reg = ET5907MV_LDO1_VSEL + id;
	desc->vsel_mask = 0xff;
	ret = of_property_read_string(child, "regulator-name", &desc->name);
	if (ret)
		return ret;

	init = of_get_regulator_init_data(dev, child, desc);
	if (!init)
		return -ENOMEM;
	out->config.dev = dev;
	out->config.init_data = init;
	out->config.regmap = map;
	if (!of_find_property(child, "init-voltage", NULL))
		return 0;
	ret = of_property_read_u32(child, "init-voltage", &uv);
	if (ret || uv < desc->min_uV || uv > base_uv + 255 * step_uv ||
	    uv < init->constraints.min_uV)
		return -EINVAL;
	sel = DIV_ROUND_UP(uv - base_uv, step_uv);
	if (base_uv + sel * step_uv > init->constraints.max_uV)
		return -ERANGE;
	out->has_initial_sel = true;
	out->initial_sel = sel;
	return 0;
}

static int et5907mv_probe(struct i2c_client *client)
{
	struct device *dev = &client->dev;
	struct et5907mv_output *outputs;
	struct pinctrl_state *active, *idle;
	struct pinctrl *pins;
	struct regmap *map;
	unsigned long present = 0;
	unsigned int id_value;
	int i, ret, idle_ret;

	pins = devm_pinctrl_get(dev);
	if (IS_ERR(pins))
		return dev_err_probe(dev, PTR_ERR(pins), "pinctrl\n");
	active = pinctrl_lookup_state(pins, "et5907mv_enable");
	if (IS_ERR(active))
		return dev_err_probe(dev, PTR_ERR(active), "enable pins\n");
	idle = pinctrl_lookup_state(pins, "et5907mv_disable");
	if (IS_ERR(idle))
		return dev_err_probe(dev, PTR_ERR(idle), "idle pins\n");
	map = devm_regmap_init_i2c(client, &et5907mv_regmap);
	if (IS_ERR(map))
		return PTR_ERR(map);
	outputs = devm_kcalloc(dev, ET5907MV_OUTPUTS, sizeof(*outputs), GFP_KERNEL);
	if (!outputs)
		return -ENOMEM;

	for_each_available_child_of_node_scoped(dev->of_node, child) {
		u16 id;

		ret = of_property_read_u16(child, "offset", &id);
		if (ret || id >= ET5907MV_OUTPUTS || test_and_set_bit(id, &present))
			return dev_err_probe(dev, -EINVAL, "%pOF: invalid LDO offset\n", child);
		ret = et5907mv_parse_output(dev, child, id, map, &outputs[id]);
		if (ret)
			return dev_err_probe(dev, ret, "%pOF: invalid LDO data\n", child);
	}
	if (!present)
		return -ENODEV;

	ret = pinctrl_select_state(pins, idle);
	if (ret)
		return ret;
	msleep(25);
	ret = pinctrl_select_state(pins, active);
	if (ret)
		goto idle;
	msleep(25);
	for (i = 0; i < 4; i++) {
		ret = regmap_read(map, 0, &id_value);
		if (!ret)
			break;
		usleep_range(1000, 1500);
	}
	if (ret)
		goto idle;

	for_each_available_child_of_node_scoped(dev->of_node, child) {
		struct et5907mv_output *out;
		struct regulator_dev *rdev;
		u16 id;

		ret = of_property_read_u16(child, "offset", &id);
		if (ret || id >= ET5907MV_OUTPUTS || !test_bit(id, &present)) {
			ret = -EINVAL;
			goto idle;
		}
		out = &outputs[id];
		out->config.of_node = child;

		if (out->has_initial_sel) {
			ret = regmap_write(map, out->desc.vsel_reg, out->initial_sel);
			if (ret)
				goto idle;
		}
		rdev = devm_regulator_register(dev, &out->desc, &out->config);
		if (IS_ERR(rdev)) {
			ret = PTR_ERR(rdev);
			goto idle;
		}
	}
idle:
	/* Hand the shared enable back at the level expected by the satellite. */
	idle_ret = pinctrl_select_state(pins, idle);
	return ret ? ret : idle_ret;
}

static const struct of_device_id et5907mv_match[] = {
	{ .compatible = "etek,et5907mv" },
	{ }
};
MODULE_DEVICE_TABLE(of, et5907mv_match);

static struct i2c_driver et5907mv_driver = {
	.driver = {
		.name = "et5907mv-regulator",
		.of_match_table = et5907mv_match,
	},
	.probe = et5907mv_probe,
};
module_i2c_driver(et5907mv_driver);

MODULE_DESCRIPTION("Etek ET5907MV satellite regulator bank");
MODULE_LICENSE("GPL");
