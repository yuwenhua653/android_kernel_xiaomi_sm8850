#!/usr/bin/env python3
"""Check production signed temperature, command cache and failed factory samples."""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile
from test_sc96281_commands import function


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--kernel-root', type=Path, required=True)
    p.add_argument('--driver', type=Path)
    a = p.parse_args()
    d = a.kernel_root / 'drivers/power/supply/mca/mca_hardware_ic/wireless_ic/sc96281'
    source = (a.driver or d/'sc96281_core.c').read_text()
    header = (d/'inc/sc96281_reg.h').read_text()
    assert re.search(r'int16_t\s+t_die;', header)
    packet = re.search(r'typedef struct ask_pkt_t \{.*?\} ask_pkt_t;', header, re.S)[0]
    pre = r'''
#include <assert.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#define mca_log_err(...) ((void)0)
#define mca_log_info(...) ((void)0)
#define mutex_lock(p) (++*(p))
#define mutex_unlock(p) (--*(p))
#define PRIVATE_CMD_CTRL_PRI_PKT 1
#define TX_ACTION_NO_REPLY 2
#define TRANS_DATA_LENGTH_1BYTE 0x18
#define TRANS_DATA_LENGTH_2BYTE 0x28
#define TRANS_DATA_LENGTH_3BYTE 0x38
#define TRANS_DATA_LENGTH_5BYTE 0x58
enum {FACTORY_TEST_CMD_RX_IOUT=1,FACTORY_TEST_CMD_RX_VOUT,
 FACTORY_TEST_CMD_RX_FW_ID,FACTORY_TEST_CMD_RX_CHIP_ID,
 FACTORY_TEST_CMD_ADAPTER_TYPE,FACTORY_TEST_CMD_REVERSE_REQ};
'''
    mocks = r'''
struct sc96281 {
 struct { bool power_good_flag; int tx_speed, adapter_type; } proc_data;
 int data_transfer_lock;
 ask_pkt_t sent_pri_packet;
 struct {uint8_t fw_rx_id,fw_tx_id,hw_id_h,hw_id_l;} *wls_fw_data;
};
static int read_result, send_result, sends, sample=0x1234, cases;
static uint16_t raw;
static ask_pkt_t last_sent;
static int read_tdie(void *p) { if(read_result) return read_result; memcpy(p,&raw,2);return 0; }
#define read_cust(sc,field,p) ((void)(sc),read_tdie(p))
static int sc96281_rx_send_ask_pkt(struct sc96281 *sc,ask_pkt_t *ask,bool response) {
 (void)response; assert(sc->data_transfer_lock==1); sends++;last_sent=*ask;return send_result;
}
static int sc96281_get_iout(int *out,void *sc) {
 (void)sc;if(read_result)return read_result;*out=sample;return 0;
}
#define sc96281_get_vout sc96281_get_iout
'''
    funcs = '\n'.join(function(source, n) for n in [
        'sc96281_get_tdie','sc96281_get_temp','sc96281_send_transparent_data',
        'sc96281_send_tx_fan_speed','sc96281_process_factory_cmd'])
    tests = r'''
int main(void) {
 struct sc96281 sc={.proc_data={.power_good_flag=true,.tx_speed=1}};
 int temp;
 for(unsigned int n=0;n<65536;n++) {
  raw=n;temp=12345;
  assert(sc96281_get_temp(&temp,&sc)==0);
  assert(temp==(int)(int16_t)raw/10);cases++;
 }
 read_result=-EIO;temp=12345;
 assert(sc96281_get_temp(&temp,&sc)==-EIO && temp==12345);cases++;
 send_result=-ETIMEDOUT;
 assert(sc96281_send_tx_fan_speed(5,&sc)==-ETIMEDOUT);
 assert(sc.proc_data.tx_speed==1 && sends==1 && sc.data_transfer_lock==0);cases++;
 send_result=0;
 assert(sc96281_send_tx_fan_speed(5,&sc)==0);
 assert(sc.proc_data.tx_speed==5 && sends==2 && sc.data_transfer_lock==0);cases++;
 assert(sc96281_send_tx_fan_speed(5,&sc)==0 && sends==2 && sc.data_transfer_lock==0);cases++;
 uint8_t data[33];memset(data,0xa5,sizeof(data));data[0]=2;
 assert(sc96281_send_transparent_data(data,33,&sc)==0);
 assert(!memcmp(&last_sent,&sc.sent_pri_packet,sizeof(last_sent)));cases++;
 data[1]=0x18;data[2]=0x42;
 assert(sc96281_send_transparent_data(data,3,&sc)==0);
 assert(!memcmp(&last_sent,&sc.sent_pri_packet,sizeof(last_sent)));
 for(unsigned int i=2;i<sizeof(last_sent.buff);i++) assert(sc.sent_pri_packet.buff[i]==0);
 cases++;
 ask_pkt_t saved=sc.sent_pri_packet;
 send_result=-EIO;data[2]=0x99;
 assert(sc96281_send_transparent_data(data,3,&sc)==-EIO);
 assert(!memcmp(&saved,&sc.sent_pri_packet,sizeof(saved)) && sc.data_transfer_lock==0);cases++;
 send_result=0;
 for(int cmd=FACTORY_TEST_CMD_RX_IOUT;cmd<=FACTORY_TEST_CMD_RX_VOUT;cmd++) {
  sends=0;read_result=-EIO;
  assert(sc96281_process_factory_cmd(cmd,&sc)==-EIO && sends==0);cases++;
  read_result=0;
  assert(sc96281_process_factory_cmd(cmd,&sc)==0 && sends==1);
  assert(last_sent.msg[0]==cmd && last_sent.msg[1]==0x34 && last_sent.msg[2]==0x12);cases++;
 }
 printf("PASS: %d production state cases; signed temperature; retry/cache; failed samples\n",cases);
}
'''
    with tempfile.TemporaryDirectory() as tmp:
        c, exe = Path(tmp)/'test.c', Path(tmp)/'test'
        c.write_text(pre+packet+mocks+funcs+tests)
        subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror',
                        '-Wno-sign-compare','-fsanitize=undefined',str(c),'-o',str(exe)],check=True)
        subprocess.run([str(exe)],check=True)


if __name__ == '__main__':
    main()
