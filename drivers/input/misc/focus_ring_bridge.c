// SPDX-License-Identifier: GPL-2.0-only
/* Xiaomi 17 Ultra lens ring events from the ADSP SMP2P endpoint. */
#include <linux/input.h>
#include <linux/interrupt.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/platform_device.h>

static const struct ring_event {
	const char *name;
	int value;
	unsigned int frames;
} ring_events[] = {
	{ "add_one_irq", 1, 1 },
	{ "add_two_irq", 1, 2 },
	{ "add_three_irq", 1, 3 },
	{ "sub_one_irq", -1, 1 },
	{ "sub_two_irq", -1, 2 },
	{ "sub_three_irq", -1, 3 },
	{ "rotation_irq", 60, 1 },
	{ "motion_ping_irq", 6, 1 },
	{ "motion_pang_irq", 6, 1 },
};

struct ring_line {
	struct input_dev *input;
	const struct ring_event *event;
};

static irqreturn_t ring_irq(int irq, void *data)
{
	struct ring_line *line = data;
	unsigned int i;

	for (i = 0; i < line->event->frames; i++) {
		input_report_rel(line->input, REL_WHEEL, line->event->value);
		input_sync(line->input);
	}
	return IRQ_HANDLED;
}

static int ring_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct input_dev *input;
	struct ring_line *lines;
	int irq, ret, i;

	lines = devm_kcalloc(dev, ARRAY_SIZE(ring_events), sizeof(*lines), GFP_KERNEL);
	input = devm_input_allocate_device(dev);
	if (!lines || !input)
		return -ENOMEM;

	input->name = "maxic, focus_ring_bridge";
	input->id.vendor = 0x9120;
	input->id.product = 0x9126;
	input_set_capability(input, EV_REL, REL_WHEEL);
	ret = input_register_device(input);
	if (ret)
		return ret;

	for (i = 0; i < ARRAY_SIZE(ring_events); i++) {
		const struct ring_event *event = &ring_events[i];

		irq = platform_get_irq_byname(pdev, event->name);
		if (irq < 0)
			return irq;
		lines[i].input = input;
		lines[i].event = event;
		ret = devm_request_threaded_irq(dev, irq, NULL, ring_irq,
						IRQF_ONESHOT | IRQF_TRIGGER_RISING,
						event->name, &lines[i]);
		if (ret)
			return dev_err_probe(dev, ret, "requesting %s\n", event->name);
	}
	return 0;
}

static const struct of_device_id ring_match[] = {
	{ .compatible = "xiaomi-focus-ring" },
	{}
};
MODULE_DEVICE_TABLE(of, ring_match);

static struct platform_driver ring_driver = {
	.driver = { .name = "focus_ring_bridge", .of_match_table = ring_match },
	.probe = ring_probe,
};
module_platform_driver(ring_driver);

MODULE_DESCRIPTION("Xiaomi lens ring input bridge");
MODULE_LICENSE("GPL");
