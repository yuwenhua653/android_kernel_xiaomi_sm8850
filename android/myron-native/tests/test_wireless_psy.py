#!/usr/bin/env python3
"""Run the production wireless power_supply getter with failing RX providers."""
import argparse
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel-root', type=Path, required=True)
    args = parser.parse_args()
    source = (args.kernel_root / 'drivers/power/supply/mca/mca_business/'
              'business_charger/mca_charger_wireless_psy.c').read_text()
    getter = source[source.index('static int wireless_psy_get_prop('):
                    source.index('\nstatic int wireless_psy_set_prop(')]
    harness = r'''
#include <assert.h>
#include <errno.h>
#include <stdio.h>
enum power_supply_property { POWER_SUPPLY_PROP_PRESENT,
 POWER_SUPPLY_PROP_ONLINE, POWER_SUPPLY_PROP_VOLTAGE_NOW,
 POWER_SUPPLY_PROP_CURRENT_NOW, POWER_SUPPLY_PROP_TEMP,
 POWER_SUPPLY_PROP_VOLTAGE_MAX, POWER_SUPPLY_PROP_CURRENT_MAX,
 POWER_SUPPLY_PROP_INPUT_CURRENT_LIMIT, POWER_SUPPLY_PROP_CHARGE_CONTROL_LIMIT_MAX };
union power_supply_propval { int intval; };
struct wireless_psy_info { int online; };
struct power_supply { struct wireless_psy_info *info; };
#define power_supply_get_drvdata(p) ((p)->info)
#define WIRELESS_ROLE_MASTER 0
#define STRATEGY_FUNC_TYPE_BASIC_WIRELESS 1
#define STRATEGY_STATUS_TYPE_ONLINE 2
static int result, sample, calls;
static int provider(int role, int *out) {
 assert(role == 0); calls++; *out = sample; return result;
}
#define platform_class_wireless_get_vout provider
#define platform_class_wireless_get_iout provider
#define platform_class_wireless_get_temp provider
static int mca_strategy_func_get_status(int type, int what, int *out) {
 assert(type == 1 && what == 2); return provider(0, out);
}
'''
    cases = r'''
int main(void) {
 struct wireless_psy_info info = { .online = 1 };
 struct power_supply psy = { &info };
 union power_supply_propval value;
 int rc;
 const int props[] = { POWER_SUPPLY_PROP_VOLTAGE_NOW,
   POWER_SUPPLY_PROP_CURRENT_NOW, POWER_SUPPLY_PROP_TEMP };
 const int inputs[] = { 9000, 700, 38 };
 const int expected[] = { 9000000, 700000, 380 };
 for (int i = 0; i < 3; i++) {
   result = 0; sample = inputs[i]; value.intval = -123;
   assert(wireless_psy_get_prop(&psy, props[i], &value) == 0);
   assert(value.intval == expected[i]);
   result = -EIO; sample = 999; value.intval = -123;
   assert(wireless_psy_get_prop(&psy, props[i], &value) == -ENODATA);
   assert(value.intval == -123);
 }
 result = -1; value.intval = -123;
 assert(wireless_psy_get_prop(&psy, POWER_SUPPLY_PROP_PRESENT, &value) == -ENODATA);
 assert(value.intval == -123);
 result = 0; sample = 1;
 assert(wireless_psy_get_prop(&psy, POWER_SUPPLY_PROP_PRESENT, &value) == 0);
 assert(value.intval == 1);
 calls = 0;
 assert(wireless_psy_get_prop(&psy, POWER_SUPPLY_PROP_ONLINE, &value) == 0);
 assert(value.intval == 1 && calls == 0);
 for (int p = POWER_SUPPLY_PROP_VOLTAGE_MAX;
      p <= POWER_SUPPLY_PROP_CHARGE_CONTROL_LIMIT_MAX; p++) {
   value.intval = -123;
   rc = wireless_psy_get_prop(&psy, p, &value);
   assert(rc == -ENODATA && value.intval == -123 && calls == 0);
 }
 assert(wireless_psy_get_prop(&psy, 1000, &value) == -EINVAL);
 puts("PASS: production RX getter; units; provider errors; no stale output; unsupported properties");
}
'''
    with tempfile.TemporaryDirectory() as tmp:
        c = Path(tmp) / 'test.c'
        exe = Path(tmp) / 'test'
        c.write_text(harness + getter + cases)
        subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                        str(c), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    main()
