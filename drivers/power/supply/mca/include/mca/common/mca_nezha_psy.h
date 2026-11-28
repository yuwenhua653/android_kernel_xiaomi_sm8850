/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef MCA_NEZHA_PSY_H
#define MCA_NEZHA_PSY_H

#include <linux/of.h>

/* A populated policy device owns both Android supply names. A build can
 * contain the policy module while the board still uses standalone providers.
 */
static inline bool nezha_business_owns_supplies(void)
{
	struct device_node *node;

	if (!IS_ENABLED(CONFIG_MYRON_MCA_COMPLETE_SERVICES))
		return false;
	for_each_compatible_node(node, NULL, "mca,business_charger") {
		if (of_device_is_available(node)) {
			of_node_put(node);
			return true;
		}
	}
	return false;
}

#endif
