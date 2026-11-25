// SPDX-License-Identifier: GPL-2.0-only
/*
 * Myron's userspace board-temperature to MCA notification interface.
 * The scalar ABI is documented in android/myron-native/thermal-board-bridge.md.
 * This does not implement Xiaomi's other thermal policy controls.
 */
#include <linux/device.h>
#include <linux/err.h>
#include <linux/kstrtox.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/of.h>
#include <linux/slab.h>
#include <linux/thermal.h>

#include <mca/common/mca_event.h>

struct mi_board_thermal {
	struct mutex lock;
	const char *sensor_name;
	int temperature;
	bool valid;
};

static struct mi_board_thermal board_thermal;
static struct device *thermal_message;

static ssize_t board_sensor_show(struct device *dev,
				struct device_attribute *attr, char *buf)
{
	struct mi_board_thermal *board = dev_get_drvdata(dev);

	return sysfs_emit(buf, "%s\n", board->sensor_name);
}
static DEVICE_ATTR_RO(board_sensor);

static ssize_t board_sensor_temp_show(struct device *dev,
				     struct device_attribute *attr, char *buf)
{
	struct mi_board_thermal *board = dev_get_drvdata(dev);
	ssize_t ret;

	mutex_lock(&board->lock);
	ret = board->valid ? sysfs_emit(buf, "%d\n", board->temperature) :
			     -ENODATA;
	mutex_unlock(&board->lock);
	return ret;
}

static ssize_t board_sensor_temp_store(struct device *dev,
				      struct device_attribute *attr,
				      const char *buf, size_t count)
{
	struct mi_board_thermal *board = dev_get_drvdata(dev);
	int temperature, ret;

	/* Preserve signed milli-Celsius, without scaling or fabricating a sample. */
	ret = kstrtoint(buf, 10, &temperature);
	if (ret)
		return ret;

	/* Serialize updates and their blocking notifications in the same order. */
	mutex_lock(&board->lock);
	board->temperature = temperature;
	board->valid = true;
	mca_event_block_notify(MCA_EVENT_TYPE_THERMAL_TEMP,
			       MCA_EVENT_THERMAL_BOARD_TEMP_CHANGE, &temperature);
	mutex_unlock(&board->lock);
	return count;
}
static DEVICE_ATTR_RW(board_sensor_temp);

static struct attribute *mi_board_thermal_attrs[] = {
	&dev_attr_board_sensor.attr,
	&dev_attr_board_sensor_temp.attr,
	NULL,
};
ATTRIBUTE_GROUPS(mi_board_thermal);

static int __init mi_board_thermal_init(void)
{
	struct device_node *node;
	const char *name;
	int ret;

	/* Enabled only by Myron's native fragment; the node supplies the label. */
	node = of_find_node_by_path("/soc/thermal-message");
	if (!node)
		return -ENODEV;
	if (!of_device_is_available(node)) {
		of_node_put(node);
		return -ENODEV;
	}
	ret = of_property_read_string(node, "board-sensor", &name);
	if (!ret && !*name)
		ret = -EINVAL;
	if (!ret) {
		board_thermal.sensor_name = kstrdup(name, GFP_KERNEL);
		if (!board_thermal.sensor_name)
			ret = -ENOMEM;
	}
	of_node_put(node);
	if (ret)
		return ret;

	mutex_init(&board_thermal.lock);
	thermal_message = thermal_auxiliary_device_create("thermal_message",
							 &board_thermal,
							 mi_board_thermal_groups);
	if (IS_ERR(thermal_message)) {
		ret = PTR_ERR(thermal_message);
		kfree(board_thermal.sensor_name);
		return ret;
	}
	return 0;
}

static void __exit mi_board_thermal_exit(void)
{
	/* Removing sysfs drains active show/store calls before freeing their data. */
	device_unregister(thermal_message);
	kfree(board_thermal.sensor_name);
}
module_init(mi_board_thermal_init);
module_exit(mi_board_thermal_exit);

MODULE_DESCRIPTION("Myron board-temperature notification interface");
MODULE_LICENSE("GPL");
