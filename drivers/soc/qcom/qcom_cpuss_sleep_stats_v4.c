// SPDX-License-Identifier: GPL-2.0-only
/*
 * Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
 */

#include <linux/debugfs.h>
#include <linux/io.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/module.h>
#include <linux/slab.h>
#include <linux/seq_file.h>
#include <soc/qcom/cpuss_telemetry.h>

#define CPUNAME_SZ 6
#define CLUSTERNAME_SZ 10
#define MAX_POSSIBLE_CPUS 8
#define MAX_POSSIBLE_CLUSTERS 2
#define NAME_LENGTH 0x12
#define REGS_MAX 3

#define C2_COUNT_ID_OFFSET 16
#define C4_COUNT_ID_OFFSET 32
#define CL5_COUNT_ID_OFFSET 52
#define SS3_COUNT_ID_OFFSET 60
#define C2_RESIDENCY_ID_OFFSET 17
#define C4_RESIDENCY_ID_OFFSET 33
#define CL5_RESIDENCY_ID_OFFSET 53
#define SS3_RESIDENCY_ID_OFFSET 61

#define QCOM_CORE_SLEEP_STATS_SHOW(name)	\
static int qcom_stats_core_##name##_show(struct seq_file *s, void *d)	\
{									\
	u32 *id = s->private;						\
	s64 val;							\
	val = get_telemetry_counter_value(*id);				\
	if (val < 0)							\
		return val;						\
	seq_printf(s, "%lld\n", val);					\
									\
	return 0;							\
}									\
DEFINE_SHOW_ATTRIBUTE(qcom_stats_core_##name)				\

#define QCOM_SLEEP_STATS_SHOW(name)	\
static int qcom_stats_cluster_cpuss_##name##_show(struct seq_file *s, void *d)	\
{									\
	u32 *id = s->private;						\
	s64 val;							\
	val = get_telemetry_counter_value(*id);				\
	if (val < 0)							\
		return val;						\
	seq_printf(s, "%lld\n", val);					\
									\
	return 0;							\
}									\
DEFINE_SHOW_ATTRIBUTE(qcom_stats_cluster_cpuss_##name)			\

struct regs_config {
	void __iomem *base;
	u32 offset;
	char name[NAME_LENGTH];
	u32 residency_lo_hi_distance;
};

struct stats_config {
	struct regs_config count_regs[REGS_MAX];
	struct regs_config residency_regs[REGS_MAX];
};

struct core_stats_id {
	u32 c2_count_id;
	u32 c2_residency_id;
	u32 c4_count_id;
	u32 c4_residency_id;
};

struct cluster_stats_id {
	u32 cl5_count_id;
	u32 cl5_residency_id;
};

struct cpuss_stats_id {
	u32 ss3_count_id;
	u32 ss3_residency_id;
};

struct qcom_stats_prvdata {
	struct platform_device *pdev;
	int ncpu;
	int ncluster;
	void __iomem *base;
	struct stats_config *offset;
	struct core_stats_id *core_id;
	struct cluster_stats_id *cluster_id;
	struct cpuss_stats_id *cpuss_id;
	struct dentry *rootdir;
	struct dentry *cpu_dir[MAX_POSSIBLE_CPUS];
	struct dentry *cluster_dir[MAX_POSSIBLE_CLUSTERS];
	struct dentry *cpuss_dir;
};

QCOM_CORE_SLEEP_STATS_SHOW(count);
QCOM_CORE_SLEEP_STATS_SHOW(residency);
QCOM_SLEEP_STATS_SHOW(count);
QCOM_SLEEP_STATS_SHOW(residency);

static int qcom_stats_count_show(struct seq_file *s, void *d)
{
	struct regs_config *reg = s->private;
	u32 val;

	val = readl_relaxed(reg->base + reg->offset);
	seq_printf(s, "%u\n", val);

	return 0;
}
DEFINE_SHOW_ATTRIBUTE(qcom_stats_count);

static int qcom_stats_residency_show(struct seq_file *s, void *d)
{
	struct regs_config *reg = s->private;
	u64 val;

	val = (u64)readl_relaxed(reg->base + reg->offset
				+ reg->residency_lo_hi_distance) << 32;
	val += readl_relaxed(reg->base + reg->offset);
	seq_printf(s, "%llu\n", val);

	return 0;
}
DEFINE_SHOW_ATTRIBUTE(qcom_stats_residency);

static void qcom_create_count_file(struct qcom_stats_prvdata *pdata)
{
	int i;

	if (of_device_is_compatible(pdata->pdev->dev.of_node, "qcom,cpuss-sleep-stats-v4")) {
		struct stats_config *config = pdata->offset;
		char reg_name[3] = {0};

		for (i = 0; i < ARRAY_SIZE(config->count_regs); i++) {
			pdata->offset->count_regs[i].base = pdata->base;
			snprintf(reg_name, sizeof(reg_name), "%s", pdata->offset->count_regs[i].name);
			if (!strcmp(reg_name, "CL"))
				debugfs_create_file(pdata->offset->count_regs[i].name, 0400,
				pdata->cluster_dir[i], (void *)&pdata->offset->count_regs[i],
				&qcom_stats_count_fops);
			else if (!strcmp(reg_name, "SS"))
				debugfs_create_file(pdata->offset->count_regs[i].name, 0400,
				pdata->cpuss_dir, (void *)&pdata->offset->count_regs[i],
				&qcom_stats_count_fops);
		}
	}

	if (of_device_is_compatible(pdata->pdev->dev.of_node, "qcom,cpuss-sleep-stats-v6")) {
		for (i = 0; i < pdata->ncluster; i++) {
			pdata->cluster_id[i].cl5_count_id = CL5_COUNT_ID_OFFSET + i * 2;
			debugfs_create_file("CL5_Count", 0400, pdata->cluster_dir[i],
				(void *)&pdata->cluster_id[i].cl5_count_id,
				&qcom_stats_cluster_cpuss_count_fops);
		}

		pdata->cpuss_id->ss3_count_id = SS3_COUNT_ID_OFFSET;
		debugfs_create_file("SS3_Count", 0400, pdata->cpuss_dir,
			(void *)&pdata->cpuss_id->ss3_count_id,
			&qcom_stats_cluster_cpuss_count_fops);

		for (i = 0; i < pdata->ncpu; i++) {
			pdata->core_id[i].c2_count_id = C2_COUNT_ID_OFFSET + i * 2;
			debugfs_create_file("C2_Count", 0400, pdata->cpu_dir[i],
					(void *)&pdata->core_id[i].c2_count_id,
					&qcom_stats_core_count_fops);

			pdata->core_id[i].c4_count_id = C4_COUNT_ID_OFFSET + i * 2;
			debugfs_create_file("C4_Count", 0400, pdata->cpu_dir[i],
					(void *)&pdata->core_id[i].c4_count_id,
					&qcom_stats_core_count_fops);
		}
	}
}

static void qcom_create_resindency_file(struct qcom_stats_prvdata *pdata)
{
	int i;

	if (of_device_is_compatible(pdata->pdev->dev.of_node, "qcom,cpuss-sleep-stats-v4")) {
		struct stats_config *config = pdata->offset;
		char reg_name[3] = {0};

		for (i = 0; i < ARRAY_SIZE(config->residency_regs); i++) {
			pdata->offset->residency_regs[i].base = pdata->base;
			snprintf(reg_name, sizeof(reg_name), "%s", pdata->offset->residency_regs[i].name);
			if (!strcmp(reg_name, "CL"))
				debugfs_create_file(pdata->offset->residency_regs[i].name, 0400,
				pdata->cluster_dir[i], (void *)&pdata->offset->residency_regs[i],
				&qcom_stats_residency_fops);
			else if (!strcmp(reg_name, "SS"))
				debugfs_create_file(pdata->offset->residency_regs[i].name, 0400,
				pdata->cpuss_dir, (void *)&pdata->offset->residency_regs[i],
				&qcom_stats_residency_fops);
		}
	}

	if (of_device_is_compatible(pdata->pdev->dev.of_node, "qcom,cpuss-sleep-stats-v6")) {
		for (i = 0; i < pdata->ncluster; i++) {
			pdata->cluster_id[i].cl5_residency_id = CL5_RESIDENCY_ID_OFFSET + i * 2;
			debugfs_create_file("CL5_Residency", 0400, pdata->cluster_dir[i],
				(void *)&pdata->cluster_id[i].cl5_residency_id,
				&qcom_stats_cluster_cpuss_residency_fops);
		}

		pdata->cpuss_id->ss3_residency_id = SS3_RESIDENCY_ID_OFFSET;
		debugfs_create_file("SS3_Residency", 0400, pdata->cpuss_dir,
			(void *)&pdata->cpuss_id->ss3_residency_id,
			&qcom_stats_cluster_cpuss_residency_fops);

		for (i = 0; i < pdata->ncpu; i++) {
			pdata->core_id[i].c2_residency_id = C2_RESIDENCY_ID_OFFSET + i * 2;
			debugfs_create_file("C2_Residency", 0400, pdata->cpu_dir[i],
					(void *)&pdata->core_id[i].c2_residency_id,
					&qcom_stats_core_residency_fops);

			pdata->core_id[i].c4_residency_id = C4_RESIDENCY_ID_OFFSET + i * 2;
			debugfs_create_file("C4_Residency", 0400, pdata->cpu_dir[i],
					(void *)&pdata->core_id[i].c4_residency_id,
					&qcom_stats_core_residency_fops);
		}
	}
}

static int qcom_create_cpuss_dir(struct qcom_stats_prvdata *pdata)
{
	int i;
	char cpu_name[CPUNAME_SZ] = {0};
	char cluster_name[CLUSTERNAME_SZ] = {0};

	for (i = 0; i < pdata->ncpu; i++) {
		snprintf(cpu_name, sizeof(cpu_name), "pcpu%u", i);
		pdata->cpu_dir[i] = debugfs_create_dir(cpu_name, pdata->rootdir);
		if (IS_ERR_OR_NULL(pdata->cpu_dir[i]))
			return pdata->cpu_dir[i] ? PTR_ERR(pdata->cpu_dir[i]) : -ENOMEM;
	}

	for (i = 0; i < pdata->ncluster; i++) {
		snprintf(cluster_name, sizeof(cluster_name), "cluster%u", i);
		pdata->cluster_dir[i] = debugfs_create_dir(cluster_name, pdata->rootdir);
		if (IS_ERR_OR_NULL(pdata->cluster_dir[i]))
			return pdata->cluster_dir[i] ? PTR_ERR(pdata->cluster_dir[i]) : -ENOMEM;
	}

	pdata->cpuss_dir = debugfs_create_dir("cpuss", pdata->rootdir);
	if (IS_ERR_OR_NULL(pdata->cpuss_dir))
		return pdata->cpuss_dir ? PTR_ERR(pdata->cpuss_dir) : -ENOMEM;
	return 0;
}

static void qcom_cpuss_stats_cleanup(void *data)
{
	struct qcom_stats_prvdata *pdata = data;

	debugfs_remove_recursive(pdata->rootdir);
}

static int qcom_cpuss_sleep_stats_v4_probe(struct platform_device *pdev)
{
	struct qcom_stats_prvdata *pdata;
	u32 clusters;
	int ret;
	bool v6 = of_device_is_compatible(pdev->dev.of_node, "qcom,cpuss-sleep-stats-v6");

	if (v6) {
		s64 ready = get_telemetry_counter_value(SS3_RESIDENCY_ID_OFFSET);

		if (ready == -ENODEV)
			return -EPROBE_DEFER;
		if (ready == -ERANGE)
			return -EINVAL;
	}
	pdata = devm_kzalloc(&pdev->dev, sizeof(*pdata), GFP_KERNEL);
	if (!pdata)
		return -ENOMEM;
	pdata->pdev = pdev;
	if (v6) {
		ret = of_property_read_u32(pdev->dev.of_node, "num-clusters", &clusters);
		if (ret)
			return ret;
		if (!clusters || clusters > MAX_POSSIBLE_CLUSTERS || nr_cpu_ids > MAX_POSSIBLE_CPUS)
			return -EINVAL;
		pdata->ncluster = clusters;
		pdata->ncpu = nr_cpu_ids;
		pdata->core_id = devm_kcalloc(&pdev->dev, pdata->ncpu, sizeof(*pdata->core_id), GFP_KERNEL);
		pdata->cluster_id = devm_kcalloc(&pdev->dev, pdata->ncluster, sizeof(*pdata->cluster_id), GFP_KERNEL);
		pdata->cpuss_id = devm_kzalloc(&pdev->dev, sizeof(*pdata->cpuss_id), GFP_KERNEL);
		if (!pdata->core_id || !pdata->cluster_id || !pdata->cpuss_id)
			return -ENOMEM;
	} else {
		pdata->base = devm_platform_get_and_ioremap_resource(pdev, 0, NULL);
		if (IS_ERR(pdata->base))
			return PTR_ERR(pdata->base);
		pdata->offset = (struct stats_config *)of_device_get_match_data(&pdev->dev);
		if (!pdata->offset)
			return -EINVAL;
		pdata->ncluster = MAX_POSSIBLE_CLUSTERS;
	}
	pdata->rootdir = debugfs_create_dir("qcom_cpuss_sleep_stats", NULL);
	if (IS_ERR_OR_NULL(pdata->rootdir))
		return pdata->rootdir ? PTR_ERR(pdata->rootdir) : -ENOMEM;
	ret = devm_add_action_or_reset(&pdev->dev, qcom_cpuss_stats_cleanup, pdata);
	if (ret)
		return ret;
	ret = qcom_create_cpuss_dir(pdata);
	if (ret)
		return ret;
	qcom_create_count_file(pdata);
	qcom_create_resindency_file(pdata);
	return 0;
}

struct stats_config qcom_cpuss_cntr_offsets = {
	.count_regs = {
		{
			.offset = 0x1220,
			.name = "CL0_CL5_Count",
		},
		{
			.offset = 0x1224,
			.name = "CL1_CL5_Count",
		},
		{
			.offset = 0x1018,
			.name = "SS3_Count",
		},
	},
	.residency_regs = {
		{
			.offset = 0x1320,
			.name = "CL0_CL5_Residency",
			.residency_lo_hi_distance = 0x10,
		},
		{
			.offset = 0x1324,
			.name = "CL1_CL5_Residency",
			.residency_lo_hi_distance = 0x10,
		},
		{
			.offset = 0x1118,
			.name = "SS3_Residency",
			.residency_lo_hi_distance = 0x4,
		},
	},
};

static const struct of_device_id qcom_cpuss_stats_v4_table[] = {
	{ .compatible = "qcom,cpuss-sleep-stats-v4", .data = &qcom_cpuss_cntr_offsets },
	{ .compatible = "qcom,cpuss-sleep-stats-v6" },
	{ },
};

MODULE_DEVICE_TABLE(of, qcom_cpuss_stats_v4_table);

static struct platform_driver qcom_cpuss_sleep_stats_v4 = {
	.probe = qcom_cpuss_sleep_stats_v4_probe,
	.driver	= {
		.name = "qcom_cpuss_sleep_stats_v4",
		.of_match_table	= qcom_cpuss_stats_v4_table,
	},
};

module_platform_driver(qcom_cpuss_sleep_stats_v4);

MODULE_DESCRIPTION("Qualcomm Technologies, Inc. (QTI) CPUSS sleep stats v4 driver");
MODULE_LICENSE("GPL");

