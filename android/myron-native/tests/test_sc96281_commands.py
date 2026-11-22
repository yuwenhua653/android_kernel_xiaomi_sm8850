#!/usr/bin/env python3
"""Fault-inject production SC96281 command sequences; requires a host C compiler."""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile


def function(source, name):
    match = re.search(r'^(?:__maybe_unused )?(?:static )?int ' + name + r'\(',
                      source, re.M)
    if not match:
        raise ValueError(name)
    start = source.index('{', match.end())
    end, depth = start + 1, 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[match.start():end]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--kernel-root', type=Path, required=True)
    p.add_argument('--driver', type=Path)
    a = p.parse_args()
    source = (a.driver or a.kernel_root / 'drivers/power/supply/mca/'
              'mca_hardware_ic/wireless_ic/sc96281/sc96281_core.c').read_text()
    names = ['sc96281_rx_set_Vout', 'sc96281_rx_set_Ilimit',
             'sc96281_rx_set_vout_ovp', 'sc96281_rx_set_vout_ocp',
             'sc96281_rx_set_otp', 'sc96281_rx_send_ept',
             'sc96281_rx_send_ask_pkt', 'sc96281_tx_send_fsk_pkt',
             'sc96281_set_vout']
    body = '\n'.join(function(source, n) for n in names)
    pre = r'''
#include <assert.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <errno.h>
#define __maybe_unused
#define mca_log_err(...) ((void)0)
#define mca_log_info(...) ((void)0)
#define mutex_lock(p) (++*(p))
#define mutex_unlock(p) (--*(p))
#define msleep(n) ((void)(n))
#define ABS(n) ((n) < 0 ? -(n) : (n))
#define ABS_CEP_VALUE 3
#define VOUT_SET_MIN_MV 3500
#define VOUT_SET_DEFAULT_MV 5000
#define VOUT_SET_MAX_MV 20000
typedef int ept_reason_t;
typedef struct { uint8_t header, msg[7]; } ask_pkt_t;
typedef ask_pkt_t fsk_pkt_t;
struct sc96281 {
 struct { bool power_good_flag, parallel_charge; int vout_setted; } proc_data;
 int data_transfer_lock;
};
enum { AP_CMD_RX_VOUT_CHANGE=1, AP_CMD_MAX_I_CHANGE, AP_CMD_OVP_CHANGE,
 AP_CMD_OCP_CHANGE, AP_CMD_OTP_CHANGE, AP_CMD_RX_SEND_EPT,
 CUST_CMD_RX_TP_SEND, AP_CMD_SEND_PPP };
static int write_result, cmd_result, writes, commands, cep_result;
static int last_cmd, cep_value, cases;
static int write_data(void *p) { (void)p; writes++; return write_result; }
#define write_cust(sc, field, p) ((void)(sc), write_data(p))
static int send_cmd(struct sc96281 *sc, int cmd) {
 (void)sc; commands++; last_cmd=cmd; return cmd_result;
}
#define sc96281_rx_set_cmd send_cmd
#define sc96281_rx_set_cust_cmd send_cmd
#define sc96281_tx_set_cmd send_cmd
static int sc96281_rx_get_ce_value(struct sc96281 *sc, int8_t *cep) {
 (void)sc; *cep=cep_value; return cep_result;
}
'''
    calls = [f'{n}(&sc, 9000)' for n in names[:6]] + [
        'sc96281_rx_send_ask_pkt(&sc, &pkt, false)',
        'sc96281_rx_send_ask_pkt(&sc, &pkt, true)',
        'sc96281_tx_send_fsk_pkt(&sc, &pkt)']
    tests = []
    for i, call in enumerate(calls):
        tests.append(f'''
 writes=commands=0; write_result=-EIO; cmd_result=0;
 assert({call} == -EIO && writes==1 && commands==0); cases++;
 writes=commands=0; write_result=0; cmd_result=-ETIMEDOUT;
 assert({call} == -ETIMEDOUT && writes==1 && commands==1); cases++;
 writes=commands=0; cmd_result=0;
 assert({call} == 0 && writes==1 && commands==1); cases++;
 assert(last_cmd == {list(range(1,7))[i] if i < 6 else ('CUST_CMD_RX_TP_SEND' if i == 7 else 'AP_CMD_SEND_PPP')});
''')
    post = r'''
 sc.proc_data.power_good_flag=true;
 sc.proc_data.parallel_charge=true;
 sc.proc_data.vout_setted=5000;
 writes=commands=0; cep_result=-EIO; cep_value=0;
 assert(sc96281_set_vout(9000, &sc)==-EIO);
 assert(!writes && !commands && sc.proc_data.vout_setted==5000);
 assert(sc.data_transfer_lock==0); cases++;
 cep_result=0; cep_value=8;
 assert(sc96281_set_vout(9000, &sc)==0 && !writes && !commands);
 assert(sc.proc_data.vout_setted==5000 && sc.data_transfer_lock==0); cases++;
 cep_value=0; write_result=-EIO;
 assert(sc96281_set_vout(9000, &sc)==-EIO);
 assert(sc.proc_data.vout_setted==5000 && sc.data_transfer_lock==0); cases++;
 write_result=0; cmd_result=-ETIMEDOUT;
 assert(sc96281_set_vout(9000, &sc)==-ETIMEDOUT);
 assert(sc.proc_data.vout_setted==5000 && sc.data_transfer_lock==0); cases++;
 cmd_result=0;
 assert(sc96281_set_vout(9000, &sc)==0);
 assert(sc.proc_data.vout_setted==9000 && sc.data_transfer_lock==0); cases++;
 printf("PASS: %d production command cases; payload errors; trigger errors; CEP; cached voltage\n", cases);
}
'''
    with tempfile.TemporaryDirectory() as tmp:
        c, exe = Path(tmp)/'test.c', Path(tmp)/'test'
        c.write_text(pre + body + '\nint main(void) {\n'
                     'struct sc96281 sc={0}; ask_pkt_t pkt={0};\n'
                     + ''.join(tests) + post)
        subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                        str(c), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    main()
