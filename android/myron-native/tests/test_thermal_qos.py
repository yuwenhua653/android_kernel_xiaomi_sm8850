#!/usr/bin/env python3
"""Check production thermal setters reject invalid states and failed QoS votes."""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile


def function(source, name):
    match = re.search(r'static\s+(?:unsigned int|int)\s+' + name + r'\s*\(', source)
    start = source.index('{', match.end())
    end, depth = start + 1, 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[match.start():end]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel-root', type=Path, required=True)
    args = parser.parse_args()
    root = args.kernel_root / 'drivers/thermal/qcom'
    cpu = (root / 'qti_cpufreq_cdev.c').read_text()
    gpu = (root / 'qti_devfreq_cdev.c').read_text()
    harness = r'''
#include <assert.h>
#include <errno.h>
#include <limits.h>
#include <stdio.h>
struct thermal_cooling_device { void *devdata; const char *type; };
struct cpufreq_cdev_device {
 unsigned long max_state, cur_state; unsigned int *freq_table; int qos_max_freq_req;
};
struct devfreq_cdev_device {
 int max_state, cur_state; unsigned long *freq_table; int qos_max_freq_req; void *dev;
};
static int result, calls;
static unsigned long voted;
static int freq_qos_request_active(int *p) { return *p; }
static int freq_qos_update_request(int *p, unsigned long f) {
 (void)p; calls++; voted = f; return result;
}
#define dev_pm_qos_update_request freq_qos_update_request
#define pr_debug(...) ((void)0)
#define pr_err(...) ((void)0)
#define dev_dbg(...) ((void)0)
#define dev_err(...) ((void)0)
'''
    functions = '\n'.join([function(cpu, 'state_to_cpufreq'),
                            function(cpu, 'cpufreq_cdev_set_state'),
                            function(gpu, 'devfreq_cdev_set_state')])
    cases = r'''
int main(void) {
 unsigned int cf[] = {3000000, 2000000, 1000000};
 unsigned long gf[] = {900000, 600000, 300000};
 struct cpufreq_cdev_device cpu = {2, 0, cf, 1};
 struct devfreq_cdev_device gpu = {2, 0, gf, 1, NULL};
 struct thermal_cooling_device c = {&cpu, "cpu-cluster0"}, g = {&gpu, "gpu"};
 assert(cpufreq_cdev_set_state(&c, 3) == -EINVAL && calls == 0);
 assert(devfreq_cdev_set_state(&g, ULONG_MAX) == -EINVAL && calls == 0);
 result = -EIO;
 assert(cpufreq_cdev_set_state(&c, 1) == -EIO && cpu.cur_state == 0);
 assert(devfreq_cdev_set_state(&g, 1) == -EIO && gpu.cur_state == 0);
 result = 1;
 assert(cpufreq_cdev_set_state(&c, 2) == 0 && cpu.cur_state == 2 && voted == 1000000);
 assert(devfreq_cdev_set_state(&g, 2) == 0 && gpu.cur_state == 2 && voted == 300000);
 calls = 0;
 assert(cpufreq_cdev_set_state(&c, 2) == 0 && calls == 0);
 assert(devfreq_cdev_set_state(&g, 2) == 0 && calls == 0);
 assert(cpufreq_cdev_set_state(&c, 0) == 0 && voted == 3000000);
 assert(devfreq_cdev_set_state(&g, 0) == 0 && voted == 900000);
 cpu.qos_max_freq_req = 0;
 calls = 0;
 assert(cpufreq_cdev_set_state(&c, 1) == -ENODEV && calls == 0 && cpu.cur_state == 0);
 puts("PASS: production CPU/GPU thermal state bounds, failed QoS votes and release");
}
'''
    with tempfile.TemporaryDirectory() as tmp:
        c, exe = Path(tmp) / 'test.c', Path(tmp) / 'test'
        c.write_text(harness + functions + cases)
        subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                        '-Wno-sign-compare', str(c), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    main()
