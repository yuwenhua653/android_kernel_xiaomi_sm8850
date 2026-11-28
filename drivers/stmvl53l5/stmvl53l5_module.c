/*******************************************************************************
* Copyright (c) 2022, STMicroelectronics - All Rights Reserved
*
* This file is part of VL53L5 Kernel Driver and is dual licensed,
* either 'STMicroelectronics Proprietary license'
* or 'BSD 3-clause "New" or "Revised" License' , at your option.
*
********************************************************************************
*
* 'STMicroelectronics Proprietary license'
*
********************************************************************************
*
* License terms: STMicroelectronics Proprietary in accordance with licensing
* terms at www.st.com/sla0081
*
* STMicroelectronics confidential
* Reproduction and Communication of this document is strictly prohibited unless
* specifically authorized in writing by STMicroelectronics.
*
*
********************************************************************************
*
* Alternatively, VL53L5 Kernel Driver may be distributed under the terms of
* 'BSD 3-clause "New" or "Revised" License', in which case the following
* provisions apply instead of the ones mentioned above :
*
********************************************************************************
*
* License terms: BSD 3-clause "New" or "Revised" License.
*
* Redistribution and use in source and binary forms, with or without
* modification, are permitted provided that the following conditions are met:
*
* 1. Redistributions of source code must retain the above copyright notice, this
* list of conditions and the following disclaimer.
*
* 2. Redistributions in binary form must reproduce the above copyright notice,
* this list of conditions and the following disclaimer in the documentation
* and/or other materials provided with the distribution.
*
* 3. Neither the name of the copyright holder nor the names of its contributors
* may be used to endorse or promote products derived from this software
* without specific prior written permission.
*
* THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
* AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
* IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
* DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
* FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
* DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
* SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
* CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
* OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
* OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
*
*
*******************************************************************************/

#include <linux/compat.h>
#include <linux/fs.h>
#include <linux/module.h>
#include <linux/property.h>
#include <linux/regulator/consumer.h>
#include <linux/spi/spi.h>
#include <linux/uaccess.h>
#include "stmvl53l5_module_dev.h"
#include "stmvl53l5_ioctl_defs.h"
#include "stmvl53l5_error_codes.h"
#include "stmvl53l5_load_firmware.h"
#include "stmvl53l5_platform.h"
#include "stmvl53l5_power.h"
#include "stmvl53l5_version.h"

static const char * const supply_names[] = { "_3P0_power", "_1P8_power", "_1P2_power" };

static int tof_power_down(struct stmvl53l5_module_t *m)
{
	int i, ret, first = 0;

	m->firmware_loaded = false;
	for (i = ARRAY_SIZE(supply_names) - 1; i >= 0; --i) {
		if (!(m->powered & BIT(i)))
			continue;
		ret = regulator_disable(m->supply[i]);
		if (!ret)
			m->powered &= ~BIT(i);
		else if (!first)
			first = ret;
	}
	return first;
}

static int tof_power_up(struct stmvl53l5_module_t *m)
{
	int i, ret;

	for (i = 0; i < ARRAY_SIZE(supply_names); i++) {
		if (m->powered & BIT(i))
			continue;
		ret = regulator_enable(m->supply[i]);
		if (ret) {
			tof_power_down(m);
			return ret;
		}
		m->powered |= BIT(i);
	}
	return 0;
}

static int tof_identify(struct stmvl53l5_module_t *m)
{
	u8 zero = 0, id[2];
	int ret;

	ret = stmvl53l5_write_multi(&m->stdev, 0x7fff, &zero, 1);
	if (ret)
		return ret;
	ret = stmvl53l5_read_multi(&m->stdev, 0, id, sizeof(id));
	if (ret)
		return ret;
	if (id[0] != 0xf0 || (id[1] != 0x02 && id[1] != 0x0c))
		return -ENODEV;
	m->stdev.host_dev.device_id = id[0];
	m->stdev.host_dev.revision_id = id[1];
	return device_property_read_string(&m->device->dev,
		id[1] == 0x0c ? "stm,l8_firmware_name" : "stm,l5_firmware_name",
		&m->firmware_name);
}

static int tof_load(struct stmvl53l5_module_t *m)
{
	int ret = tof_power_up(m);

	m->firmware_loaded = false;
	if (!ret)
		ret = stmvl53l5_check_rom_firmware_boot(&m->stdev);
	if (!ret)
		ret = stmvl53l5_load_fw_stm(&m->stdev);
	if (!ret)
		ret = stmvl53l5_set_power_mode(&m->stdev, STMVL53L5_AFTERBOOT_POWER_STATE);
	if (ret)
		tof_power_down(m);
	else
		m->firmware_loaded = true;
	return ret;
}

static void tof_worker(struct work_struct *work)
{
	struct stmvl53l5_module_t *m = container_of(work, struct stmvl53l5_module_t, load_work);
	int ret;

	mutex_lock(&m->lock);
	if (!m->stopping && !m->firmware_loaded) {
		ret = tof_load(m);
		if (ret)
			dev_err(&m->device->dev, "firmware initialization failed: %d\n", ret);
	}
	mutex_unlock(&m->lock);
}

static void tof_free(struct kref *ref)
{
	kfree(container_of(ref, struct stmvl53l5_module_t, ref));
}

static int tof_open(struct inode *inode, struct file *file)
{
	struct stmvl53l5_module_t *m = container_of(file->private_data, struct stmvl53l5_module_t, misc);
	int ret = 0;

	mutex_lock(&m->lock);
	if (m->stopping)
		ret = -ENODEV;
	else {
		kref_get(&m->ref);
		file->private_data = m;
		/* First-stage loading can precede the ODM firmware mount. */
		if (!m->firmware_loaded)
			schedule_work(&m->load_work);
	}
	mutex_unlock(&m->lock);
	return ret;
}

static int tof_release(struct inode *inode, struct file *file)
{
	struct stmvl53l5_module_t *m = file->private_data;

	kref_put(&m->ref, tof_free);
	return 0;
}

static int tof_transfer(struct stmvl53l5_module_t *m, void __user *arg, bool write)
{
	struct stmvl53l5_comms_struct_t io;
	void *buf;
	int ret;

	if (!m->firmware_loaded)
		return STMVL53L5_FIRMWARE_NOT_LOADED_ERROR;
#ifdef CONFIG_COMPAT
	if (in_compat_syscall()) {
		struct { u16 len, index; compat_uptr_t buf; } io32;

		if (copy_from_user(&io32, arg, sizeof(io32)))
			return -EFAULT;
		io.len = io32.len;
		io.reg_index = io32.index;
		io.buf = compat_ptr(io32.buf);
	} else
#endif
	if (copy_from_user(&io, arg, sizeof(io)))
		return -EFAULT;
	if (io.reg_index > 0x7fff || io.len > 0x8000 - io.reg_index)
		return -EINVAL;
	if (!io.len)
		return 0;
	if (write) {
		buf = memdup_user(io.buf, io.len);
		if (IS_ERR(buf))
			return PTR_ERR(buf);
		ret = stmvl53l5_write_multi(&m->stdev, io.reg_index, buf, io.len);
	} else {
		buf = kmalloc(io.len, GFP_KERNEL);
		if (!buf)
			return -ENOMEM;
		ret = stmvl53l5_read_multi(&m->stdev, io.reg_index, buf, io.len);
		if (!ret && copy_to_user(io.buf, buf, io.len))
			ret = -EFAULT;
	}
	kfree(buf);
	return ret;
}

static long tof_command(struct stmvl53l5_module_t *m, unsigned int cmd, void __user *arg)
{
	static const u16 version[] = { STMVL53L5_VER_REVISION, STMVL53L5_VER_BUILD,
		STMVL53L5_VER_MINOR, STMVL53L5_VER_MAJOR };
	struct stmvl53l5_boot_struct_t boot = {};
	struct stmvl53l5_power_state_t power;
	u32 speed;
	int ret;

	switch (cmd) {
	case STMVL53L5_IOCTL_READ:
	case STMVL53L5_IOCTL_WRITE:
		return tof_transfer(m, arg, cmd == STMVL53L5_IOCTL_WRITE);
	case STMVL53L5_IOCTL_FW_LOAD:
		return tof_load(m);
	case STMVL53L5_IOCTL_ROM_BOOT:
		if (!m->powered)
			return -EHOSTDOWN;
		ret = stmvl53l5_check_rom_firmware_boot(&m->stdev);
		if (ret)
			return ret;
		boot.revision_id = m->stdev.host_dev.revision_id;
		boot.device_booted = m->stdev.host_dev.device_booted;
		return copy_to_user(arg, &boot, sizeof(boot)) ? -EFAULT : 0;
	case STMVL53L5_IOCTL_POWER:
		if (!m->firmware_loaded)
			return STMVL53L5_FIRMWARE_NOT_LOADED_ERROR;
		if (copy_from_user(&power, arg, sizeof(power)))
			return -EFAULT;
		power.previous = m->stdev.host_dev.power_state;
		ret = stmvl53l5_set_power_mode(&m->stdev, power.request);
		if (ret)
			return ret;
		return copy_to_user(arg, &power, sizeof(power)) ? -EFAULT : 0;
	case STMVL53L5_IOCTL_KERNEL_VERSION:
		return copy_to_user(arg, version, sizeof(version)) ? -EFAULT : 0;
	case STMVL53L5_IOCTL_GET_ERROR:
		return put_user(m->last_driver_error, (int __user *)arg);
	case STMVL53L5_IOCTL_GET_REVID:
		return put_user(m->stdev.host_dev.revision_id, (u8 __user *)arg);
	case STMVL53L5_IOCTL_SET_SPI_TRANSFER_SPEED:
		if (get_user(speed, (u32 __user *)arg))
			return -EFAULT;
		if (!speed || speed > m->device->max_speed_hz)
			return -EINVAL;
		m->transfer_speed_hz = speed;
		return 0;
	case STMVL53L5_IOCTL_KERNEL_INTERRUPT_OWNED:
		return put_user(0, (u8 __user *)arg);
	case STMVL53L5_IOCTL_WAIT_FOR_INTERRUPT:
		/* Neither Nezha board wires a ranging interrupt. */
		return STMVL53L5_ERROR_NO_INTERRUPT_HANDLER;
	default:
		return -EINVAL;
	}
}

static long tof_ioctl(struct file *file, unsigned int cmd, unsigned long arg)
{
	struct stmvl53l5_module_t *m = file->private_data;
	long ret;

	if (IS_ENABLED(CONFIG_COMPAT) && in_compat_syscall() &&
	    _IOC_TYPE(cmd) == STMVL53L5_IOCTL_CHAR && _IOC_SIZE(cmd) == sizeof(u32))
		cmd = _IOC(_IOC_DIR(cmd), _IOC_TYPE(cmd), _IOC_NR(cmd), sizeof(void *));
	mutex_lock(&m->lock);
	ret = m->stopping ? -ENODEV : tof_command(m, cmd, (void __user *)arg);
	if (ret && !m->last_driver_error)
		m->last_driver_error = ret;
	mutex_unlock(&m->lock);
	return ret;
}

static const struct file_operations tof_fops = {
	.owner = THIS_MODULE,
	.open = tof_open,
	.release = tof_release,
	.unlocked_ioctl = tof_ioctl,
	.compat_ioctl = compat_ptr_ioctl,
};

static int tof_probe(struct spi_device *spi)
{
	struct stmvl53l5_module_t *m;
	int i, ret;

	m = kzalloc(sizeof(*m), GFP_KERNEL);
	if (!m)
		return -ENOMEM;
	m->device = spi;
	m->transfer_speed_hz = min_t(u32, spi->max_speed_hz, STMVL53L5_SPI_DEFAULT_TRANSFER_SPEED_HZ);
	m->stdev.host_dev.power_state = STMVL53L5_POWER_STATE_HP_IDLE;
	mutex_init(&m->lock);
	kref_init(&m->ref);
	INIT_WORK(&m->load_work, tof_worker);
	m->address = devm_kmalloc(&spi->dev, 2, GFP_KERNEL);
	m->transfer = devm_kmalloc(&spi->dev, STMVL53L5_COMMS_CHUNK_SIZE, GFP_KERNEL);
	if (!m->address || !m->transfer) {
		ret = -ENOMEM;
		goto fail;
	}
	for (i = 0; i < ARRAY_SIZE(m->supply); i++) {
		m->supply[i] = devm_regulator_get(&spi->dev, supply_names[i]);
		if (IS_ERR(m->supply[i])) {
			ret = PTR_ERR(m->supply[i]);
			goto fail;
		}
		/* All three supplies have fixed Nezha board voltages. */
		ret = regulator_set_load(m->supply[i], 85000);
		if (ret < 0)
			goto fail;
	}
	ret = tof_power_up(m);
	if (ret)
		goto fail;
	ret = tof_identify(m);
	if (ret)
		goto fail;
	m->misc.minor = MISC_DYNAMIC_MINOR;
	m->misc.name = "stmvl53l5";
	m->misc.fops = &tof_fops;
	m->misc.mode = 0444;
	m->misc.parent = &spi->dev;
	ret = misc_register(&m->misc);
	if (ret)
		goto fail;
	spi_set_drvdata(spi, m);
	schedule_work(&m->load_work);
	return 0;
fail:
	tof_power_down(m);
	kref_put(&m->ref, tof_free);
	return dev_err_probe(&spi->dev, ret, "cannot initialize ranging sensor\n");
}

static void tof_shutdown(struct spi_device *spi)
{
	struct stmvl53l5_module_t *m = spi_get_drvdata(spi);

	mutex_lock(&m->lock);
	m->stopping = true;
	if (tof_power_down(m))
		dev_err(&spi->dev, "failed to disable ranging supplies\n");
	mutex_unlock(&m->lock);
	cancel_work_sync(&m->load_work);
}

static void tof_remove(struct spi_device *spi)
{
	struct stmvl53l5_module_t *m = spi_get_drvdata(spi);

	misc_deregister(&m->misc);
	tof_shutdown(spi);
	kref_put(&m->ref, tof_free);
}

static const struct of_device_id tof_of_match[] = {
	{ .compatible = "st,stmvl53l5" }, {}
};
MODULE_DEVICE_TABLE(of, tof_of_match);
static const struct spi_device_id tof_ids[] = {
	{ "stmvl53l5" }, {}
};
MODULE_DEVICE_TABLE(spi, tof_ids);
static struct spi_driver tof_driver = {
	.driver = { .name = STMVL53L5_DRV_NAME, .of_match_table = tof_of_match },
	.id_table = tof_ids,
	.probe = tof_probe,
	.remove = tof_remove,
	.shutdown = tof_shutdown,
};
module_spi_driver(tof_driver);
MODULE_FIRMWARE("stmvl53l5.bin");
MODULE_FIRMWARE("stmvl53l8.bin");
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("ST VL53L5/L8 ranging sensor on Xiaomi Nezha SPI");
