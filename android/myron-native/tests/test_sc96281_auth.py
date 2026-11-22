#!/usr/bin/env python3
"""Exercise production RX authentication reads and the strategy event preamble."""
import argparse
from pathlib import Path
import subprocess
import tempfile
from test_sc96281_commands import function


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--kernel-root', type=Path, required=True)
    a = p.parse_args()
    mca = a.kernel_root / 'drivers/power/supply/mca'
    driver = (mca / 'mca_hardware_ic/wireless_ic/sc96281/sc96281_core.c').read_text()
    strategy = (mca / 'mca_strategy/strategy_wireless/mca_basic_wireless.c').read_text()
    block = strategy.split('case RX_INT_AUTHEN_FINISH:', 1)[1].split(
        'if (info->proc_data.auth_data != AUTH_STATUS_FAILED)', 1)[0]
    pre = r'''
#include <assert.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
typedef uint8_t u8;
typedef uint32_t u32;
#define mca_log_err(...) ((void)0)
#define mca_log_info(...) ((void)0)
#define PROJECT_FLAG_ADAPTER_TYPE (1U << 2)
#define PROJECT_FLAG_UUID (1U << 3)
#define ADAPTER_NONE 0
#define ADAPTER_AUTH_FAILED 1
#define WIRELESS_ROLE_MASTER 0
struct sc96281 {
 struct { bool power_good_flag; int adapter_type; u8 uuid[4]; } proc_data;
};
static uint32_t reads[3];
static int read_count, read_fail, cases;
static int read_field(void *out, size_t size) {
 int i=read_count++;
 if (read_count==read_fail) return -ENXIO;
 assert(i<3); memcpy(out, &reads[i], size); return 0;
}
#define read_cust(chip, field, out) ((void)(chip),read_field(out,sizeof(*(out))))
static int sc96281_read_block(struct sc96281 *chip, uint16_t addr, u8 *out, u8 len) {
 (void)chip; assert(addr==0x01d8 && len==1); return read_field(out,len);
}
'''
    strategy_mocks = r'''
struct strategy_info {
 struct { int auth_data, adapter_type; u8 uuid[4]; u32 uuid_value; } proc_data;
};
static int event_calls, event_fail, decisions;
static u8 event_uuid[4];
static int platform_class_wireless_get_auth_value(int role, int *out) {
 assert(role==0); if (++event_calls==event_fail) return -EIO;
 *out=12; return 0;
}
static int platform_class_wireless_get_tx_uuid(int role, u8 *out) {
 assert(role==0); if (++event_calls==event_fail) return -EIO;
 memcpy(out,event_uuid,4); return 0;
}
static int platform_class_wireless_get_tx_adapter(int role, int *out) {
 assert(role==0); if (++event_calls==event_fail) return -EIO;
 *out=9; return 0;
}
'''
    body = '\n'.join(function(driver, n) for n in
                     ['sc96281_get_auth_value', 'sc96281_get_tx_adapter_by_i2c'])
    body += strategy_mocks + '\nstatic void auth_event(struct strategy_info *info) { int ret=0; (void)ret; do {\n'
    body += block + '\ndecisions++;\n} while(0); }\n'
    post = r'''
int main(void) {
 struct sc96281 sc={.proc_data={.power_good_flag=true,.adapter_type=7,.uuid={1,2,3,4}}};
 int out;
 reads[0]=12; reads[1]=9; reads[2]=0x89abcdef;
 for(int i=1;i<=3;i++) {
  read_count=0; read_fail=i; out=-123;
  assert(sc96281_get_auth_value(&out,&sc)==-ENXIO);
  assert(out==-123 && read_count==i && sc.proc_data.adapter_type==7);
  assert(memcmp(sc.proc_data.uuid,"\1\2\3\4",4)==0); cases++;
 }
 read_fail=0; read_count=0;
 assert(sc96281_get_auth_value(&out,&sc)==0 && out==12);
 assert(sc.proc_data.adapter_type==9);
 assert(memcmp(sc.proc_data.uuid,"\x89\xab\xcd\xef",4)==0); cases++;
 reads[0]=PROJECT_FLAG_ADAPTER_TYPE; reads[1]=ADAPTER_NONE; read_count=0;
 assert(sc96281_get_auth_value(&out,&sc)==0 && read_count==2);
 assert(sc.proc_data.adapter_type==ADAPTER_AUTH_FAILED); cases++;
 reads[0]=0; read_count=0;
 assert(sc96281_get_auth_value(&out,&sc)==0 && read_count==1 && out==0); cases++;
 out=-123; sc.proc_data.adapter_type=7; read_fail=1; read_count=0;
 assert(sc96281_get_tx_adapter_by_i2c(&out,&sc)==-ENXIO);
 assert(out==-123 && sc.proc_data.adapter_type==7); cases++;
 read_fail=0; read_count=0; reads[0]=9;
 assert(sc96281_get_tx_adapter_by_i2c(&out,&sc)==0);
 assert(out==9 && sc.proc_data.adapter_type==9); cases++;
 struct strategy_info info={0};
 for(int i=1;i<=3;i++) {
  event_calls=decisions=0; event_fail=i; auth_event(&info);
  assert(event_calls==i && decisions==0); cases++;
 }
 event_fail=event_calls=decisions=0;
 memset(event_uuid,0xff,4); auth_event(&info);
 assert(decisions==1 && info.proc_data.uuid_value==0xffffffffU); cases++;
 event_calls=0; memcpy(event_uuid,"\x80\x02\x03\x04",4); auth_event(&info);
 assert(decisions==2 && info.proc_data.uuid_value==0x80020304U); cases++;
 printf("PASS: %d production auth cases; read failures; cache; event errors; repeated UUID\n",cases);
}
'''
    with tempfile.TemporaryDirectory() as tmp:
        c, exe = Path(tmp)/'test.c', Path(tmp)/'test'
        c.write_text(pre + body + post)
        subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=undefined', str(c), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    main()
