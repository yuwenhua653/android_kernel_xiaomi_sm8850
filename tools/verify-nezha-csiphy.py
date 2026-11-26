#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compare compiled Nezha CSI PHY baseline tables with OS4.0.7 camera.ko.

Requires pyelftools. Usage: verify-nezha-csiphy.py STOCK_CAMERA_KO CSIPHY_SOC_O
Checks data and relocation targets, not streaming, HAL ABI or OEM AutoEQ retry.
Both structures contain the two AutoEQ choice bytes before bandwidth.
Default choices are checked independently of the upstream backup EQ table.
"""
import argparse
import struct
from elftools.elf.elffile import ELFFile


class Object:
    def __init__(self, path):
        self.file = open(path, 'rb')
        self.elf = ELFFile(self.file)
        if self.elf['e_machine'] != 'EM_AARCH64':
            raise ValueError('expected ARM64 ELF')
        self.symtab = self.elf.get_section_by_name('.symtab')
        self.symbols = {s.name: s for s in self.symtab.iter_symbols()}
        self.relocations = {}
        for section in self.elf.iter_sections():
            if section['sh_type'] == 'SHT_RELA':
                for r in section.iter_relocations():
                    symbol = self.symtab.get_symbol(r['r_info_sym'])
                    self.relocations[section['sh_info'], r['r_offset']] = (
                        symbol['st_shndx'], symbol['st_value'] + r['r_addend'])

    def symbol(self, name):
        s = self.symbols[name]
        return s['st_shndx'], s['st_value']

    def data(self, ptr, size):
        section, offset = ptr
        return self.elf.get_section(section).data()[offset:offset + size]

    def pointer(self, ptr, offset):
        key = ptr[0], ptr[1] + offset
        if key in self.relocations:
            return self.relocations[key]
        if self.data(key, 8) != bytes(8):
            raise ValueError('nonzero pointer without relocation')
        return None

    def rates(self, stock):
        table = self.symbol('data_rate_delta_table_2_4_0_1')
        count, = struct.unpack('<Q', self.data(table, 8))
        array = self.pointer(table, 8)
        stride, prefix = 416, 8
        result = []
        for i in range(count):
            entry = array[0], array[1] + i * stride
            choices, choice = self.data(entry, 2)
            if choices and choice:
                continue
            bw, size, common = struct.unpack_from('<QQQ', self.data(entry, stride), prefix)
            if common:
                raise ValueError('unexpected common-control table')
            slots = []
            for j in range(48):
                p = self.pointer(entry, prefix + 24 + j * 8)
                slots.append(self.data(p, size * 16) if p else None)
            result.append((bw, size, slots))
        return result


def check(stock, source):
    expected, actual = stock.rates(True), source.rates(False)
    if len(expected) != 29 or expected != actual:
        raise ValueError('baseline rate thresholds/registers/PHY variants differ')
    names = ['csiphy_2ph_v2_4_0_1_reg', 'csiphy_2ph_v2_4_0_clk_ln_reg',
             'csiphy_3ph_v2_4_0_reg', 'csiphy_common_reg_2_4_0',
             'csiphy_irq_reg_2_4_0', 'csiphy_reset_enter_reg_2_4_0',
             'csiphy_reset_exit_reg_2_4_0', 'csiphy_lane_en_reg_2_4_0', 'datarate_240_3p0Gsps_1_bp']
    for name in names:
        size = stock.symbols[name]['st_size']
        if source.symbols[name]['st_size'] != size or (
                stock.data(stock.symbol(name), size) != source.data(source.symbol(name), size)):
            raise ValueError('register table mismatch: ' + name)
    for obj in (stock, source):
        ctrl = obj.symbol('ctrl_reg_2_4_0_1')
        for off, name in [(8, names[3]), (16, names[4]), (24, names[5]),
                          (32, names[6]), (40, names[7]), (56, names[0]),
                          (64, names[2]), (72, names[1]),
                          (120, 'data_rate_delta_table_2_4_0_1')]:
            if obj.pointer(ctrl, off) != obj.symbol(name):
                raise ValueError('control table selects wrong register array: ' + name)
    if stock.data(stock.symbol('ctrl_reg_2_4_0_1'), 112)[80:] != source.data(
            source.symbol('ctrl_reg_2_4_0_1'), 112)[80:]:
        raise ValueError('lane offsets differ')
    print('PASS: 29 baseline rates, all PHY/variant pointers, 9 register tables (including backup EQ) and lane offsets')
    print('Not tested: OEM AutoEQ retry, HAL ABI, streaming or hardware')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stock')
    parser.add_argument('object')
    args = parser.parse_args()
    check(Object(args.stock), Object(args.object))
