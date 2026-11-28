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

#include <linux/spi/spi.h>
#include <linux/delay.h>

#include "stmvl53l5_platform.h"
#include "stmvl53l5_logging.h"
#include "stmvl53l5_error_codes.h"

/* The SE14 controller may DMA both transfers. Use instance-owned bounce
 * storage for the register address as well as the data, including stack callers.
 */
static int stmvl53l5_spi_io(struct stmvl53l5_dev_t *dev, u16 index,
			    u8 *data, u32 count, bool write)
{
	struct stmvl53l5_module_t *module = container_of(dev, struct stmvl53l5_module_t, stdev);
	u32 speed = module->transfer_speed_hz;
	size_t max = min_t(size_t, STMVL53L5_COMMS_CHUNK_SIZE, spi_max_transfer_size(module->device));
	size_t message = spi_max_message_size(module->device);
	int ret;

	if (index > 0x7fff || count > 0x8000U - index)
		return -EINVAL;
	if (message <= 2 || max < 2)
		return -EMSGSIZE;
	max = min(max, message - 2);
	if (dev->host_dev.firmware_load || dev->host_dev.revision_id != 0x0c)
		speed = module->device->max_speed_hz;
	while (count) {
		size_t len = min_t(size_t, count, max);
		struct spi_transfer xfer[] = {
			{ .tx_buf = module->address, .len = 2, .speed_hz = speed },
			{ .len = len, .speed_hz = speed },
		};

		module->address[0] = (index >> 8) | (write ? 0x80 : 0);
		module->address[1] = index;
		if (write) {
			memcpy(module->transfer, data, len);
			xfer[1].tx_buf = module->transfer;
		} else {
			xfer[1].rx_buf = module->transfer;
		}
		ret = spi_sync_transfer(module->device, xfer, ARRAY_SIZE(xfer));
		if (ret)
			return ret;
		if (!write)
			memcpy(data, module->transfer, len);
		count -= len;
		data += len;
		index += len;
	}
	return 0;
}

int stmvl53l5_write_multi(struct stmvl53l5_dev_t *dev, u16 index, u8 *data, u32 count)
{
	return stmvl53l5_spi_io(dev, index, data, count, true);
}

int stmvl53l5_read_multi(struct stmvl53l5_dev_t *dev, u16 index, u8 *data, u32 count)
{
	return stmvl53l5_spi_io(dev, index, data, count, false);
}

static unsigned int _calculate_twos_complement_uint32(unsigned int value)
{
	unsigned int twos_complement = 0;

	twos_complement = ~value + 0x01;

	return twos_complement;
}

int stmvl53l5_wait_us(struct stmvl53l5_dev_t *pdev, unsigned int wait_us)
{
	int status = STMVL53L5_ERROR_NONE;

	if (wait_us < 10)
		udelay(wait_us);
	else if (wait_us < 20000)
		usleep_range(wait_us, wait_us + 1);
	else
		msleep(wait_us / 1000);

	return status;
}

int stmvl53l5_wait_ms(struct stmvl53l5_dev_t *pdev, unsigned int wait_ms)
{
	int status = STMVL53L5_ERROR_NONE;

	status = stmvl53l5_wait_us(pdev, wait_ms * 1000);

	return status;
}

int stmvl53l5_get_tick_count(
	struct stmvl53l5_dev_t *pdev, unsigned int *ptime_ms)
{
	*ptime_ms = jiffies_to_msecs(jiffies);
	return 0;
}

int stmvl53l5_check_for_timeout(
	struct stmvl53l5_dev_t *pdev,
	unsigned int start_time_ms,
	unsigned int end_time_ms,
	unsigned int timeout_ms)
{
	int status = STMVL53L5_ERROR_NONE;
	unsigned int time_diff_ms;

	if (start_time_ms <= end_time_ms) {
		time_diff_ms = end_time_ms - start_time_ms;
	} else {
		time_diff_ms = _calculate_twos_complement_uint32(start_time_ms)
			       + end_time_ms;
	}
	if (time_diff_ms > timeout_ms)
		status = STMVL53L5_ERROR_TIME_OUT;

	return status;
}
