// SPDX-License-Identifier: GPL-2.0-only
/* Xiaomi consumer IR. The OS4 HAL writes a pre-encoded SPI waveform. */
#include <linux/compat.h>
#include <linux/fs.h>
#include <linux/kref.h>
#include <linux/miscdevice.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/slab.h>
#include <linux/spi/spi.h>
#include <linux/uaccess.h>
#include <uapi/linux/lirc.h>

struct nezha_ir {
	struct miscdevice misc;
	struct kref ref;
	struct mutex lock;
	struct spi_device *spi;
	unsigned int users;
	u32 length;
};

static void nezha_ir_free(struct kref *ref)
{
	kfree(container_of(ref, struct nezha_ir, ref));
}

static int nezha_ir_open(struct inode *inode, struct file *file)
{
	struct nezha_ir *ir = container_of(file->private_data, struct nezha_ir, misc);
	int ret = 0;

	mutex_lock(&ir->lock);
	if (!ir->spi) {
		ret = -ENODEV;
	} else {
		kref_get(&ir->ref);
		ir->users++;
		file->private_data = ir;
	}
	mutex_unlock(&ir->lock);
	return ret;
}

static int nezha_ir_release(struct inode *inode, struct file *file)
{
	struct nezha_ir *ir = file->private_data;

	mutex_lock(&ir->lock);
	if (!--ir->users)
		ir->length = 0;
	mutex_unlock(&ir->lock);
	kref_put(&ir->ref, nezha_ir_free);
	return 0;
}

static long nezha_ir_ioctl(struct file *file, unsigned int cmd, unsigned long arg)
{
	struct nezha_ir *ir = file->private_data;
	u32 length;
	int ret = 0;

	if (cmd != LIRC_SET_SEND_MODE)
		return -EINVAL;
	if (get_user(length, (u32 __user *)arg))
		return -EFAULT;
	mutex_lock(&ir->lock);
	if (!ir->spi)
		ret = -ENODEV;
	else if (length != ir->length && ir->users > 1)
		ret = -EPERM;
	else if (length > spi_max_message_size(ir->spi) || length > KMALLOC_MAX_SIZE)
		ret = -EMSGSIZE;
	else
		ir->length = length;
	mutex_unlock(&ir->lock);
	return ret;
}

static ssize_t nezha_ir_write(struct file *file, const char __user *buf,
			      size_t count, loff_t *pos)
{
	struct nezha_ir *ir = file->private_data;
	struct spi_transfer tx = { .bits_per_word = 32, .speed_hz = 1920000 };
	void *data;
	ssize_t ret;

	mutex_lock(&ir->lock);
	if (!ir->spi) {
		ret = -ENODEV;
		goto out;
	}
	if ((ir->length && ir->length != count) || !IS_ALIGNED(count, 4)) {
		ret = -EINVAL;
		goto out;
	}
	if (count > spi_max_message_size(ir->spi) || count > KMALLOC_MAX_SIZE) {
		ret = -EMSGSIZE;
		goto out;
	}
	if (!count) {
		ret = 0;
		goto out;
	}
	data = memdup_user(buf, count);
	if (IS_ERR(data)) {
		ret = PTR_ERR(data);
		goto out;
	}
	tx.tx_buf = data;
	tx.len = count;
	ret = spi_sync_transfer(ir->spi, &tx, 1);
	kfree(data);
	if (!ret)
		ret = count;
out:
	mutex_unlock(&ir->lock);
	return ret;
}

static const struct file_operations nezha_ir_fops = {
	.owner = THIS_MODULE,
	.open = nezha_ir_open,
	.release = nezha_ir_release,
	.write = nezha_ir_write,
	.unlocked_ioctl = nezha_ir_ioctl,
	.compat_ioctl = compat_ptr_ioctl,
	.llseek = noop_llseek,
};

static int nezha_ir_probe(struct spi_device *spi)
{
	struct nezha_ir *ir;
	int ret;

	ir = kzalloc(sizeof(*ir), GFP_KERNEL);
	if (!ir)
		return -ENOMEM;
	kref_init(&ir->ref);
	mutex_init(&ir->lock);
	ir->spi = spi;
	ir->misc.minor = MISC_DYNAMIC_MINOR;
	ir->misc.name = "ir_spi";
	ir->misc.fops = &nezha_ir_fops;
	ir->misc.parent = &spi->dev;
	ir->misc.mode = 0666;
	ret = misc_register(&ir->misc);
	if (ret) {
		kref_put(&ir->ref, nezha_ir_free);
		return ret;
	}
	spi_set_drvdata(spi, ir);
	return 0;
}

static void nezha_ir_shutdown(struct spi_device *spi)
{
	struct nezha_ir *ir = spi_get_drvdata(spi);

	mutex_lock(&ir->lock);
	ir->spi = NULL;
	mutex_unlock(&ir->lock);
}

static void nezha_ir_remove(struct spi_device *spi)
{
	struct nezha_ir *ir = spi_get_drvdata(spi);

	misc_deregister(&ir->misc);
	nezha_ir_shutdown(spi);
	kref_put(&ir->ref, nezha_ir_free);
}

static const struct of_device_id nezha_ir_of_match[] = {
	{ .compatible = "ir-spi" }, {}
};
MODULE_DEVICE_TABLE(of, nezha_ir_of_match);

static const struct spi_device_id nezha_ir_ids[] = {
	{ "ir-spi" }, {}
};
MODULE_DEVICE_TABLE(spi, nezha_ir_ids);

static struct spi_driver nezha_ir_driver = {
	.driver = { .name = "nezha-ir-spi", .of_match_table = nezha_ir_of_match },
	.id_table = nezha_ir_ids,
	.probe = nezha_ir_probe,
	.remove = nezha_ir_remove,
	.shutdown = nezha_ir_shutdown,
};
module_spi_driver(nezha_ir_driver);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Xiaomi Nezha infrared transmitter");
