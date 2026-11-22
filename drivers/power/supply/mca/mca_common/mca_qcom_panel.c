// SPDX-License-Identifier: GPL-2.0
/*
 * Copyright (c) 2024 Xiaomi Technologies Co., Ltd.
 * Native Myron adaptation of the MCA/Qualcomm panel bridge from vendor
 * commit cba60332e49c0978aa83c8bb77bf157893c14fb6.
 */
#include <drm/drm_panel.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/rcupdate.h>
#include <linux/soc/qcom/panel_event_notifier.h>

#include <mca/common/mca_panel.h>

struct mca_panel_dev {
	/* Serialize duplicate detection and publication across panel events. */
	struct mutex lock;
	int screen_state;
	int hbm_state;
};

/* The primary battery-charger notifier has one owner at a time. */
static struct mca_panel_dev __rcu *active_panel;

int mca_panel_get_screen_state(void)
{
	struct mca_panel_dev *panel;
	int state;

	rcu_read_lock();
	panel = rcu_dereference(active_panel);
	state = panel && READ_ONCE(panel->screen_state) > 0;
	rcu_read_unlock();
	return state;
}
EXPORT_SYMBOL(mca_panel_get_screen_state);

int mca_panel_get_hbm_state(void)
{
	struct mca_panel_dev *panel;
	int state;

	rcu_read_lock();
	panel = rcu_dereference(active_panel);
	state = panel && READ_ONCE(panel->hbm_state) > 0;
	rcu_read_unlock();
	return state;
}
EXPORT_SYMBOL(mca_panel_get_hbm_state);

static void mca_panel_event_notifier_callback(
		enum panel_event_notifier_tag tag,
		struct panel_event_notification *notification, void *data)
{
	struct mca_panel_dev *panel_dev = data;
	int *previous, value;
	unsigned long event;

	if (!notification || tag != PANEL_EVENT_NOTIFICATION_PRIMARY)
		return;
	switch (notification->notif_type) {
	case DRM_PANEL_EVENT_BLANK:
	case DRM_PANEL_EVENT_UNBLANK:
		previous = &panel_dev->screen_state;
		value = notification->notif_type == DRM_PANEL_EVENT_UNBLANK;
		event = MCA_EVENT_PANEL_SCREEN_STATE_CHANGE;
		break;
	case DRM_PANEL_EVENT_HBM_ON:
	case DRM_PANEL_EVENT_HBM_OFF:
		previous = &panel_dev->hbm_state;
		value = notification->notif_type == DRM_PANEL_EVENT_HBM_ON;
		event = MCA_EVENT_PANEL_HBM_STATE_CHANGE;
		break;
	default:
		return;
	}

	/* Early/late notifications can repeat the same state. Publish once. */
	mutex_lock(&panel_dev->lock);
	if (*previous != value) {
		WRITE_ONCE(*previous, value);
		mca_event_block_notify(MCA_EVENT_TYPE_PANEL, event, &value);
	}
	mutex_unlock(&panel_dev->lock);
}

static struct drm_panel *mca_panel_find_active(struct device *dev)
{
	struct device_node *screen, *node;
	struct drm_panel *panel;
	int i, count;
	bool deferred = false;

	/* Myron's charge-screen is a sibling under /soc, not a charger property. */
	screen = of_get_child_by_name(dev->of_node->parent, "charge-screen");
	if (!screen)
		return ERR_PTR(-ENODEV);
	count = of_count_phandle_with_args(screen, "panel", NULL);
	if (count <= 0) {
		of_node_put(screen);
		return ERR_PTR(-EINVAL);
	}
	for (i = 0; i < count; i++) {
		node = of_parse_phandle(screen, "panel", i);
		if (!node) {
			of_node_put(screen);
			return ERR_PTR(-EINVAL);
		}
		panel = of_drm_find_panel(node);
		of_node_put(node);
		if (!IS_ERR(panel)) {
			of_node_put(screen);
			return panel;
		}
		if (PTR_ERR(panel) == -EPROBE_DEFER)
			deferred = true;
	}
	of_node_put(screen);
	return ERR_PTR(deferred ? -EPROBE_DEFER : -ENODEV);
}

static void mca_panel_unregister(void *cookie)
{
	/* The notifier core waits for in-flight callbacks before returning. */
	RCU_INIT_POINTER(active_panel, NULL);
	panel_event_notifier_unregister(cookie);
	synchronize_rcu();
}

static int mca_panel_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct mca_panel_dev *panel_dev;
	struct drm_panel *panel;
	void *cookie;
	int ret;

	panel = mca_panel_find_active(dev);
	if (IS_ERR(panel))
		return dev_err_probe(dev, PTR_ERR(panel), "active charge-screen panel\n");
	panel_dev = devm_kzalloc(dev, sizeof(*panel_dev), GFP_KERNEL);
	if (!panel_dev)
		return -ENOMEM;
	mutex_init(&panel_dev->lock);
	/* Do not invent a state before the first real panel event. */
	panel_dev->screen_state = -1;
	panel_dev->hbm_state = -1;
	cookie = panel_event_notifier_register(
		PANEL_EVENT_NOTIFICATION_PRIMARY,
		PANEL_EVENT_NOTIFIER_CLIENT_BATTERY_CHARGER, panel,
		mca_panel_event_notifier_callback, panel_dev);
	if (IS_ERR_OR_NULL(cookie))
		return dev_err_probe(dev, cookie ? PTR_ERR(cookie) : -EINVAL,
				     "MCA panel notifier registration\n");
	rcu_assign_pointer(active_panel, panel_dev);
	ret = devm_add_action_or_reset(dev, mca_panel_unregister, cookie);
	if (ret)
		return ret;
	dev_info(dev, "MCA screen/HBM event bridge ready\n");
	return 0;
}

static const struct of_device_id mca_panel_match[] = {
	{ .compatible = "mca,mca_panel" },
	{ }
};
MODULE_DEVICE_TABLE(of, mca_panel_match);

static struct platform_driver mca_panel_driver = {
	.probe = mca_panel_probe,
	.driver = {
		.name = "mca_panel",
		.of_match_table = mca_panel_match,
	},
};
module_platform_driver(mca_panel_driver);
MODULE_DESCRIPTION("MCA Qualcomm screen-state event bridge");
MODULE_LICENSE("GPL");
