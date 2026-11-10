// SPDX-License-Identifier: GPL-2.0-only
/*
 * Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
 *
 * AP sleep-state protocol from the Canoe vendor driver, imported from
 * cba60332e49c0978aa83c8bb77bf157893c14fb6. Keep its bit, SMEM layout and
 * remote wake-event semantics; manage callback lifetimes for native Kbuild.
 */
#include <linux/interrupt.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/pm_wakeup.h>
#include <linux/soc/qcom/smem.h>
#include <linux/soc/qcom/smem_state.h>
#include <linux/suspend.h>
#include <asm/arch_timer.h>

/* Vendor protocol bit, not the phandle argument (Canoe uses argument 0). */
#define AWAKE_BIT BIT(12)
#define QCOM_POWER_STATE_SMEM_ID 512
#define QCOM_POWER_STATE_RESUME 1
#define QCOM_POWER_STATE_SUSPEND 2

struct qcom_power_state {
	__le32 version;
	__le32 subsystem;
	__le32 state;
	__le32 reserve;
	__le64 resume_time;
	__le64 suspend_time;
} __packed;

struct qcom_smp2p_sleepstate_private {
	struct device *dev;
	struct qcom_smem_state *smem_state;
	struct qcom_power_state *power_state;
	struct wakeup_source *notify_ws;
	struct notifier_block pm_nb;
};

static int sleepstate_publish(struct qcom_smp2p_sleepstate_private *priv,
			     bool awake)
{
	struct qcom_power_state *state = priv->power_state;

	if (state) {
		if (awake)
			WRITE_ONCE(state->resume_time,
				   cpu_to_le64(__arch_counter_get_cntvct()));
		else
			WRITE_ONCE(state->suspend_time,
				   cpu_to_le64(__arch_counter_get_cntvct()));
		WRITE_ONCE(state->state, cpu_to_le32(awake ?
			   QCOM_POWER_STATE_RESUME : QCOM_POWER_STATE_SUSPEND));
		/* Publish shared data before notifying the remote via SMP2P. */
		mb();
	}
	return qcom_smem_state_update_bits(priv->smem_state, AWAKE_BIT,
					  awake ? AWAKE_BIT : 0);
}

static int sleepstate_pm_notifier(struct notifier_block *nb,
				 unsigned long event, void *unused)
{
	struct qcom_smp2p_sleepstate_private *priv =
		container_of(nb, struct qcom_smp2p_sleepstate_private, pm_nb);
	int ret;

	switch (event) {
	case PM_SUSPEND_PREPARE:
		ret = sleepstate_publish(priv, false);
		break;
	case PM_POST_SUSPEND:
		ret = sleepstate_publish(priv, true);
		break;
	default:
		return NOTIFY_DONE;
	}
	if (ret)
		dev_err_ratelimited(priv->dev, "sleep-state notification failed: %d\n", ret);
	return NOTIFY_DONE;
}

static irqreturn_t smp2p_sleepstate_handler(int irq, void *data)
{
	struct qcom_smp2p_sleepstate_private *priv = data;

	/* Preserve the vendor's remote wake handling; do not mask the IRQ. */
	__pm_wakeup_event(priv->notify_ws, 200);
	return IRQ_HANDLED;
}

static void sleepstate_unregister_pm(void *data)
{
	struct qcom_smp2p_sleepstate_private *priv = data;

	unregister_pm_notifier(&priv->pm_nb);
}

static void sleepstate_unregister_ws(void *data)
{
	wakeup_source_unregister(data);
}

static int smp2p_sleepstate_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct qcom_smp2p_sleepstate_private *priv;
	const char *label = dev_name(dev);
	char *ws_name;
	unsigned int bit;
	size_t size;
	int irq, ret;

	irq = platform_get_irq_byname(pdev, "smp2p-sleepstate-in");
	if (irq < 0)
		return irq;
	priv = devm_kzalloc(dev, sizeof(*priv), GFP_KERNEL);
	if (!priv)
		return -ENOMEM;
	priv->dev = dev;
	priv->smem_state = devm_qcom_smem_state_get(dev, NULL, &bit);
	if (IS_ERR(priv->smem_state))
		return dev_err_probe(dev, PTR_ERR(priv->smem_state), "sleep-state provider\n");

	of_property_read_string(dev->of_node, "label", &label);
	ws_name = devm_kasprintf(dev, GFP_KERNEL, "%s-smp2p-sleepstate", label);
	if (!ws_name)
		return -ENOMEM;
	priv->notify_ws = wakeup_source_register(dev, ws_name);
	if (!priv->notify_ws)
		return -ENOMEM;
	ret = devm_add_action_or_reset(dev, sleepstate_unregister_ws, priv->notify_ws);
	if (ret)
		return ret;
	ret = devm_request_threaded_irq(dev, irq, NULL, smp2p_sleepstate_handler,
			IRQF_ONESHOT | IRQF_TRIGGER_RISING | IRQF_TRIGGER_FALLING |
			IRQF_NO_SUSPEND, label, priv);
	if (ret)
		return ret;

	/* Optional extended state: the SMP2P notification must work without it. */
	ret = qcom_smem_alloc(QCOM_SMEM_HOST_ANY, QCOM_POWER_STATE_SMEM_ID,
			     sizeof(struct qcom_power_state));
	if (!ret || ret == -EEXIST) {
		priv->power_state = qcom_smem_get(QCOM_SMEM_HOST_ANY,
						QCOM_POWER_STATE_SMEM_ID, &size);
		if (IS_ERR(priv->power_state)) {
			dev_warn(dev, "power-state SMEM unavailable: %ld\n",
				 PTR_ERR(priv->power_state));
			priv->power_state = NULL;
		} else if (size < sizeof(*priv->power_state)) {
			dev_warn(dev, "power-state SMEM too small: %zu\n", size);
			priv->power_state = NULL;
		} else {
			WRITE_ONCE(priv->power_state->version, cpu_to_le32(1));
			WRITE_ONCE(priv->power_state->subsystem, cpu_to_le32(0));
		}
	} else {
		dev_warn(dev, "power-state SMEM allocation failed: %d\n", ret);
	}
	ret = sleepstate_publish(priv, true);
	if (ret)
		return dev_err_probe(dev, ret, "initial awake notification\n");
	priv->pm_nb.notifier_call = sleepstate_pm_notifier;
	priv->pm_nb.priority = INT_MAX;
	ret = register_pm_notifier(&priv->pm_nb);
	if (ret)
		return ret;
	/* Registered last: unregister PM before freeing IRQ, wake source, state. */
	ret = devm_add_action_or_reset(dev, sleepstate_unregister_pm, priv);
	if (ret)
		return ret;
	dev_info(dev, "AP sleep-state notifications ready\n");
	return 0;
}

static const struct of_device_id smp2p_slst_match_table[] = {
	{ .compatible = "qcom,smp2p-sleepstate" },
	{ }
};
MODULE_DEVICE_TABLE(of, smp2p_slst_match_table);

static struct platform_driver smp2p_sleepstate_driver = {
	.probe = smp2p_sleepstate_probe,
	.driver = {
		.name = "smp2p_sleepstate",
		.of_match_table = smp2p_slst_match_table,
	},
};
module_platform_driver(smp2p_sleepstate_driver);
MODULE_DESCRIPTION("Qualcomm SMP2P AP sleep-state notifications");
MODULE_SOFTDEP("pre: smp2p");
MODULE_LICENSE("GPL");
