#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise the Nezha IR HAL ABI and ToF firmware parser with a modeled bus.
Optional arguments are unmodified VL53L5/L8 firmware files for metadata validation.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

drivers = Path(__file__).resolve().parents[1] / "drivers"
ir = (drivers / "xiaomi/nezha-ir-spi.c").read_text()
tof = (drivers / "stmvl53l5/stmvl53l5_load_firmware.c").read_text()
header = (drivers / "stmvl53l5/stmvl53l5_module_dev.h").read_text()


def function(text, decl):
    start = text.index(decl)
    return text[start:text.index("\n}", start) + 2] + "\n"


support = r"""
#include <assert.h>
#include <errno.h>
#include <linux/lirc.h>
#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
typedef uint8_t u8;
typedef uint32_t u32;
#define __user
#define get_user(dst, ptr) ((ptr) ? ((dst) = *(ptr), 0) : -EFAULT)
#define IS_ALIGNED(v, a) (!((v) % (a)))
#define KMALLOC_MAX_SIZE 65536
#define IS_ERR(p) ((p) == NULL)
#define PTR_ERR(p) (-EFAULT)
#define mutex_lock(x) ((void)0)
#define mutex_unlock(x) ((void)0)
#define kfree(p) free(p)
struct spi_device { size_t limit; };
struct spi_transfer { unsigned bits_per_word, speed_hz, len; const void *tx_buf; };
struct nezha_ir { struct spi_device *spi; unsigned users; u32 length; };
struct file { void *private_data; };
static int spi_result, writes;
static char last_waveform[16];
static void *memdup_user(const void *src, size_t len) {
    if (!src) return NULL;
    void *copy = malloc(len);
    assert(copy); return memcpy(copy, src, len);
}
static size_t spi_max_message_size(struct spi_device *s) { return s->limit; }
static int spi_sync_transfer(struct spi_device *s, struct spi_transfer *tx, int n) {
    assert(n == 1 && tx->len <= sizeof(last_waveform));
    assert(tx->speed_hz == 1920000 && tx->bits_per_word == 32);
    writes++; memcpy(last_waveform, tx->tx_buf, tx->len); return spi_result;
}
#define U8_MAX UINT8_MAX
#define BYTE_4 4
#define stmvl53l5_trace_print(...) ((void)0)
#define LOG_FUNCTION_START(...) ((void)0)
#define LOG_FUNCTION_END(...) ((void)0)
"""
structs = function(header, "struct stmvl53l5_patch_data_t {").rstrip() + ";\n"
structs += function(header, "struct stmvl53l5_fw_header_t {").rstrip() + ";\n"
fw_support = r"""
struct stmvl53l5_dev_t {
    struct { u8 *p_fw_buff, *p_comms_buff; u32 fw_buff_count, comms_buff_max_count;
             struct stmvl53l5_patch_data_t patch_data; } host_dev;
};
struct stmvl53l5_module_t {
    struct stmvl53l5_dev_t stdev; struct {int dev;} *device;
    const char *firmware_name; u8 *transfer;
};
struct firmware { const u8 *data; size_t size; };
static struct firmware example;
static int acquisitions, releases;
#define container_of(p,t,m) ((t *)((char *)(p) - offsetof(t,m)))
#define STMVL53L5_COMMS_CHUNK_SIZE 256
static int request_firmware(const struct firmware **fw, const char *name, const void *dev) {
    acquisitions++; *fw = &example; return 0;
}
static void release_firmware(const struct firmware *fw) { releases++; }
static u32 get_unaligned_le32(const u8 *p) {
    return (u32)p[0] | ((u32)p[1] << 8) | ((u32)p[2] << 16) | ((u32)p[3] << 24);
}
"""
decode = "".join(function(tof, start) for start in (
    "static unsigned int _stmvl53l5_decode_uint32_t(", "static void _stmvl53l5_decode_patch_struct(",
    "static bool stmvl53l5_valid_segment(", "static bool stmvl53l5_valid_patch("))
model = r"""
static int stmvl53l5_load_firmware(struct stmvl53l5_dev_t *dev) {
    assert(dev->host_dev.fw_buff_count >= 128);
    _stmvl53l5_decode_patch_struct(dev);
    return stmvl53l5_valid_patch(&dev->host_dev.patch_data, dev->host_dev.fw_buff_count) ? 0 : -EINVAL;
}
"""
main = r"""
static int check_fw(u8 *data, size_t size) {
    struct stmvl53l5_module_t module = {};
    typeof(*module.device) device = {};
    module.device = &device;
    example.data=data; example.size=size;
    int ret=stmvl53l5_load_fw_stm(&module.stdev);
    assert(!module.stdev.host_dev.p_fw_buff && acquisitions==releases);
    return ret;
}
static void put_word(u8 *p, u32 v) {
    for (unsigned i=0; i<4; i++) p[i]=(u8)(v >> (8*i));
}
int main(int argc, char **argv) {
    struct spi_device bus={.limit=16}; struct nezha_ir ir={.users=1,.spi=&bus};
    struct file file={&ir}; u32 len=8;
    unsigned long arg=(unsigned long)&len; char wave[]="abcdefgh";
    assert(LIRC_SET_SEND_MODE == 0x40046911U);
    assert(!nezha_ir_ioctl(&file,LIRC_SET_SEND_MODE,arg));
    assert(nezha_ir_write(&file,wave,8,NULL)==8 && !memcmp(wave,last_waveform,8));
    assert(nezha_ir_write(&file,wave,4,NULL)==-EINVAL);
    ir.users=2; assert(!nezha_ir_ioctl(&file,LIRC_SET_SEND_MODE,arg));
    len=4; assert(nezha_ir_ioctl(&file,LIRC_SET_SEND_MODE,arg)==-EPERM);
    ir.users=1; len=17; assert(nezha_ir_ioctl(&file,LIRC_SET_SEND_MODE,arg)==-EMSGSIZE);
    len=0; assert(!nezha_ir_ioctl(&file,LIRC_SET_SEND_MODE,arg));
    assert(nezha_ir_write(&file,wave,6,NULL)==-EINVAL);
    assert(!nezha_ir_write(&file,wave,0,NULL));
    assert(nezha_ir_write(&file,NULL,4,NULL)==-EFAULT);
    spi_result=-EIO; assert(nezha_ir_write(&file,wave,4,NULL)==-EIO && writes==2);
    ir.spi=NULL; assert(nezha_ir_write(&file,wave,4,NULL)==-ENODEV);
    assert(nezha_ir_ioctl(&file,LIRC_SET_SEND_MODE,arg)==-ENODEV);
    u8 image[256]={};
    put_word(image+16,24); put_word(image+20,232);
    u8 *patch=image+24;
    put_word(patch+32,128); put_word(patch+36,64); put_word(patch+40,9);
    assert(check_fw(image,sizeof(image))==0);
    assert(check_fw(image,23)==-EINVAL && check_fw(image,100)==-EINVAL);
    put_word(image+16,UINT32_MAX); assert(check_fw(image,sizeof(image))==-EINVAL);
    put_word(image+16,24); put_word(patch+40,12); assert(check_fw(image,sizeof(image))==-EINVAL);
    put_word(patch+40,11); put_word(patch+44,0x4fc0); assert(!check_fw(image,sizeof(image)));
    put_word(patch+44,0x4fc1); assert(check_fw(image,sizeof(image))==-EINVAL);
    put_word(patch+44,0); put_word(patch+32,UINT32_MAX); assert(check_fw(image,sizeof(image))==-EINVAL);
    assert(!stmvl53l5_valid_segment(0,0x100,256,0x100,0));
    assert(!stmvl53l5_valid_segment(1,UINT32_MAX,256,1,0));
    assert(!stmvl53l5_valid_segment(0,2,256,1,0x7fff));
    for (int i=1; i<argc; i++) {
        FILE *fp=fopen(argv[i],"rb"); assert(fp); assert(!fseek(fp,0,SEEK_END));
        long size=ftell(fp); assert(size>0 && size<16*1024*1024); rewind(fp);
        u8 *data=malloc(size); assert(data && fread(data,1,size,fp)==(size_t)size); fclose(fp);
        assert(!check_fw(data,size)); free(data); printf("PASS firmware metadata %s\n",argv[i]);
    }
    puts("PASS consumer IR ioctl/waveform/error handling and ToF firmware headers/page bounds");
}
"""
program = (support + function(ir, "static long nezha_ir_ioctl(")
           + function(ir, "static ssize_t nezha_ir_write(") + structs + fw_support + decode
           + model + function(tof, "int stmvl53l5_load_fw_stm(") + main)
with tempfile.TemporaryDirectory() as name:
    tmp = Path(name)
    (tmp / "test.c").write_text(program)
    subprocess.run([os.environ.get("CC", "cc"), "-fsanitize=address,undefined", "-g", "-O1",
                    tmp / "test.c", "-o", tmp / "test"], check=True)
    subprocess.run([tmp / "test", *sys.argv[1:]], check=True)
