// SPDX-License-Identifier: GPL-2.0-only
/* Halo HL7603 buck-boost regulator on the Tiantong satellite board. */
#include <linux/bitops.h>
#include <linux/delay.h>
#include <linux/i2c.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/regmap.h>
#include <linux/regulator/driver.h>
#include <linux/regulator/machine.h>
#include <linux/regulator/of_regulator.h>

#define HL7603_CONTROL		0x01
#define HL7603_VOUT		0x02
#define HL7603_ILIM		0x03
#define HL7603_ENABLE		BIT(6)
#define HL7603_MIN_UV		2700000
#define HL7603_STEP_UV		50000
#define HL7603_MAX_SEL		56
#define HL7603_DEFAULT_SEL	38	/* 4.6 V when VOUT reads zero */

static int hl7603_enable(struct regulator_dev *rdev)
{
	int ret;

	/* The satellite PA needs the board's ILIM setting before enable. */
	ret = regmap_write(rdev->regmap, HL7603_ILIM, 0x09);
	if (ret)
		return ret;

	return regulator_enable_regmap(rdev);
}

static int hl7603_get_voltage_sel(struct regulator_dev *rdev)
{
	int sel = regulator_get_voltage_sel_regmap(rdev);

	if (sel > HL7603_MAX_SEL)
		return -ERANGE;
	return sel == 0 ? HL7603_DEFAULT_SEL : sel;
}

static const struct regulator_ops hl7603_ops = {
	.enable = hl7603_enable,
	.disable = regulator_disable_regmap,
	.is_enabled = regulator_is_enabled_regmap,
	.list_voltage = regulator_list_voltage_linear,
	.map_voltage = regulator_map_voltage_linear,
	.get_voltage_sel = hl7603_get_voltage_sel,
	.set_voltage_sel = regulator_set_voltage_sel_regmap,
};

static const struct regulator_desc hl7603_desc = {
	.name = "hl7603-regulator-l1",
	.type = REGULATOR_VOLTAGE,
	.owner = THIS_MODULE,
	.ops = &hl7603_ops,
	.min_uV = HL7603_MIN_UV + HL7603_STEP_UV,
	.uV_step = HL7603_STEP_UV,
	.linear_min_sel = 1,
	.n_voltages = HL7603_MAX_SEL + 1,
	.vsel_reg = HL7603_VOUT,
	.vsel_mask = 0xff,
	.enable_reg = HL7603_CONTROL,
	.enable_mask = HL7603_ENABLE,
};

static const struct regmap_config hl7603_regmap = {
	.reg_bits = 8,
	.val_bits = 8,
	.max_register = 0x05,
};

static int hl7603_probe(struct i2c_client *client)
{
	struct device *dev = &client->dev;
	struct regulator_config config = { .dev = dev };
	struct device_node *child __free(device_node) = NULL;
	struct regulator_init_data *init;
	struct regulator_dev *rdev;
	unsigned int uv, id;
	u16 offset;
	int ret, attempt;

	if (of_get_available_child_count(dev->of_node) != 1)
		return dev_err_probe(dev, -EINVAL, "expected one regulator output\n");
	child = of_get_next_available_child(dev->of_node, NULL);
	ret = of_property_read_u16(child, "offset", &offset);
	if (ret || offset != 6)
		return dev_err_probe(dev, -EINVAL, "invalid output enable bit\n");

	config.regmap = devm_regmap_init_i2c(client, &hl7603_regmap);
	if (IS_ERR(config.regmap))
		return PTR_ERR(config.regmap);
	/* GPIO160 also powers the adjacent LDO. Its owner controls the pin. */
	msleep(25);
	for (attempt = 0; attempt < 4; attempt++) {
		ret = regmap_read(config.regmap, 0, &id);
		if (!ret)
			break;
		usleep_range(1000, 1500);
	}
	if (ret)
		return dev_err_probe(dev, ret, "cannot read regulator ID\n");

	init = of_get_regulator_init_data(dev, child, &hl7603_desc);
	if (!init)
		return -ENOMEM;
	if (of_find_property(child, "init-voltage", NULL)) {
		ret = of_property_read_u32(child, "init-voltage", &uv);
		if (ret || uv < hl7603_desc.min_uV ||
		    uv > HL7603_MIN_UV + HL7603_STEP_UV * HL7603_MAX_SEL ||
		    uv < init->constraints.min_uV || uv > init->constraints.max_uV ||
		    (uv - HL7603_MIN_UV) % HL7603_STEP_UV)
			return dev_err_probe(dev, -EINVAL, "invalid initial voltage\n");
		ret = regmap_write(config.regmap, HL7603_VOUT,
				   (uv - HL7603_MIN_UV) / HL7603_STEP_UV);
		if (ret)
			return dev_err_probe(dev, ret, "cannot set initial voltage\n");
	}

	config.of_node = child;
	config.init_data = init;
	rdev = devm_regulator_register(dev, &hl7603_desc, &config);
	return PTR_ERR_OR_ZERO(rdev);
}

static const struct of_device_id hl7603_of_match[] = {
	{ .compatible = "tiantong,dcdc" },
	{ }
};
MODULE_DEVICE_TABLE(of, hl7603_of_match);

static struct i2c_driver hl7603_driver = {
	.driver = {
		.name = "hl7603-regulator",
		.of_match_table = hl7603_of_match,
	},
	.probe = hl7603_probe,
};
module_i2c_driver(hl7603_driver);

MODULE_DESCRIPTION("HL7603 Tiantong buck-boost regulator");
MODULE_LICENSE("GPL");
