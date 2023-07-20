import struct
from platform import system
from extra.assembly.assembly import AssemblyCodegen
from tinygrad.ops import BinaryOps, UnaryOps, TernaryOps
from tinygrad.codegen.linearizer import UOps
from tinygrad.helpers import dtypes

def float_to_hex(x): return "%02X%02X%02X%02X" % tuple(struct.pack("f",x)[::-1])

#NOTE: Darwin needs lm functions to start with a "_" 
def get_op(op): return f"bl {'_' if system() == 'Darwin' else ''}{op}"
_type_to_reg = {dtypes.half: 'h', dtypes.float32: 's', dtypes.bool: 'x',dtypes.int8:'w', dtypes.int32: 'w', dtypes.int64: 'x', dtypes.uint8:'w', dtypes.uint32: 'w', dtypes.uint64: 'x'}
class ARMCodegen(AssemblyCodegen):
  def specialize(self, asm):
    ins = [] 
    alu = {BinaryOps.ADD: "add", BinaryOps.SUB: "sub", BinaryOps.MUL: "mul", BinaryOps.DIV: "div", BinaryOps.MAX: "max",
           BinaryOps.MOD: "", BinaryOps.CMPLT: "subs", BinaryOps.CMPEQ: "subs",
           UnaryOps.SIN: get_op('sin'), UnaryOps.LOG2: get_op("log2"), UnaryOps.EXP2: get_op("exp2"), UnaryOps.SQRT: get_op("sqrt"),
           TernaryOps.MULACC: "fmadd", TernaryOps.WHERE: "fcmp"}
    reg_map = {}
    var_size = 0
    buf_to_dtype = {int(arg[4:]):out.dtype for uop,out,_,arg in asm if uop == UOps.DEFINE_GLOBAL}
    all_half = all(dtype == dtypes.half for dtype in buf_to_dtype.values())
    all_int32 = all(dtype == dtypes.int32 for dtype in buf_to_dtype.values())
    all_int8 = all(dtype == dtypes.int8 for dtype in buf_to_dtype.values())
    all_int64 = all(dtype == dtypes.int64 for dtype in buf_to_dtype.values())
    for i, (uop, out, vin, arg) in enumerate(asm):
      if uop == UOps.DEFINE_REGISTER: 
        for i in range(arg[2]):
          var_size += 16
          reg_map[f"%{arg[1]}{i}"] = f"[sp, #{var_size}]"
      elif uop == UOps.DEFINE_GLOBAL:
        #buf_index[arg] = out[1] 
        if arg.startswith('data'):
          if int(arg[4:]) >= 8: ins.append(f"ldr x1, [x19, #{(int(arg[4:]) - 8) * 8}]")
          # if out[1] != dtypes.int32 and arg != "buf0":
          #   for i in range(out.bufsize):
          #     ins.append(f"ldr s0, [x{'1' if int(arg[3:]) >= 8 else arg[3:]}, #{i*4}]")
          #     ins.append("scvtf s0, s0")
          #     ins.append(f"str s0, [x{'1' if int(arg[3:]) >= 8 else arg[3:]}, #{i*4}]")
          # if arg != "buf0":
          #   for i in range(out.bufsize):
          #     ins.append(f"ldr h0, [x{'1' if int(arg[3:]) >= 8 else arg[3:]}, #{i*2}]")
          #     ins.append("fcvt s0, h0")
          #     ins.append(f"str s0, [x{'1' if int(arg[3:]) >= 8 else arg[3:]}, #{i*4}]")
          ins.append(f"str x{'1' if int(arg[4:]) >= 8 else int(arg[4:])}, {reg_map[out.nm]}")
      elif uop == UOps.CONST:
        ins.append(f"mov w0, #{arg & 0xffff if arg > 65535 else arg}" if arg.__class__ is int else f"mov x0, 0x{float_to_hex(arg.value)}")
        if arg.__class__ is int and arg > 65535:
          ins.append(f"movk w0, #{(arg >> 16) & 0xffff}, lsl #16")
          ins.append("sxtw x0, w0")
        elif arg.__class__ is float or dtypes.is_float(out.dtype):
          ins.append("fmov s0, w0")
        ins.append(f"str {'s' if arg.__class__ is float else 'x'}0, {reg_map[out.nm]}")
      elif uop == UOps.CAST:
        if arg == BinaryOps.CMPEQ:
          ins.append("cset w0, eq")
          ins.append("scvtf s0, w0")
        else:
          ins.append(f"ldr w0, {reg_map[vin[0].nm]}")
          ins.append("sxtw x0, w0")
        ins.append(f"str {'s' if dtypes.is_float(out[1]) else 'x'}0, {reg_map[out.nm]}")
      elif uop == UOps.ALU:
        reg = 's' if dtypes.is_float(vin[0][1]) else 'x'
        if all_half and reg == 's':
          ins.append(f"ldr h0, {reg_map[vin[0].nm]}")
          ins.append(f"fcvt s0, h0")
        elif any([all_int32, all_int8, all_int64]) and reg == 's':
          ins.append(f"ldr{'sb' if all_int8 else ''} {'s' if all_int32 else 'x' if all_int64 else 'w'}0, {reg_map[vin[0].nm]}")
          ins.append(f"scvtf s0, {'s' if all_int32 else 'x' if all_int64 else 'w'}0")
        else:
          ins.append(f"ldr {reg}0, {reg_map[vin[0].nm]}")
        if len(vin) >= 2:
          if vin[1].__class__ is int and vin[1] > 65535:
            ins.append(f"mov w2, #{vin[1] & 0xffff}")
            ins.append(f"movk w2, #{(vin[1] >> 16) & 0xffff}, lsl #16")
            ins.append("sxtw x1, w2")
          else:
            if all_half and reg == 's':
              ins.append(f"ldr h1, {reg_map[vin[1].nm]}")
              ins.append(f"fcvt s1, h1")
            elif any([all_int32, all_int8, all_int64]) and reg == 's':
              ins.append(f"ldr{'sb' if all_int8 else ''} {'s' if all_int32 else 'x' if all_int64 else 'w'}1, {reg_map[vin[1].nm]}")
              ins.append(f"scvtf s1, {'s' if all_int32 else 'x' if all_int64 else 'w'}1")
            else:
              ins.append(f"{f'mov {reg}1, #{str(vin[1])}' if vin[1].__class__ is int else f'ldr {reg}1, {reg_map[vin[1].nm]}'}")
        if arg == BinaryOps.MUL and out.dtype == dtypes.bool:
          ins.append("ands x0, x0, x1;")
        elif arg == TernaryOps.MULACC and out == vin[2]:
          if all_half and reg == 's':
              ins.append(f"ldr h2, {reg_map[vin[2].nm]}")
              ins.append(f"fcvt s2, h2")
          elif any([all_int32,all_int8,all_int64]) and reg == 's':
              ins.append(f"ldr{'sb' if all_int8 else ''} {'s' if all_int32 else 'x' if all_int64 else 'w'}2, {reg_map[vin[2].nm]}")
              ins.append(f"scvtf s2, {'s' if all_int32 else 'x' if all_int64 else 'w'}2")
          else:
            ins.append(f"ldr s2, {reg_map[vin[2].nm]}")
          ins.append(f"{alu[arg]} s0, s0, s1, s2")
        elif arg == TernaryOps.WHERE:
          ins.append(f"ldr s2, {reg_map[vin[2].nm]}")
          ins.append(f"fmov s3, #0")
          ins.append(f"{alu[arg]} s0, s3")
          ins.append(f"fcsel s0, s2, s1, eq")

        elif arg in [UnaryOps.LOG2, UnaryOps.SIN, UnaryOps.EXP2, UnaryOps.SQRT]:
          ins.append("stp x29, x30, [sp, #0]!")
          ins.append("mov x29, sp")
          ins.append("fcvt d0, s0")
          ins.append(alu[arg])
          ins.append("fcvt s0, d0")
          ins.append("mov sp, x29")
          ins.append("ldp x29, x30, [sp], #0")
        elif arg in [BinaryOps.CMPEQ, BinaryOps.CMPLT]:
          ins.append(f"{alu[arg]} {reg}0, {reg}0, {reg}1" if reg in 'x' else f"fcmp {reg}0, {reg}1")
        elif arg == BinaryOps.MOD:
          ins.append("udiv x2, x0, x1")
          ins.append("msub x2, x2, x1, x0")
        else:
          ins.append(f"{'f' if reg == 's' else 's' if arg == BinaryOps.DIV else ''}{alu[arg]} {reg}0, {reg}0, {reg}1")
        if all_half and reg == 's':
          ins.append(f"fcvt h0, s0")
          ins.append(f"str h{'2' if arg == BinaryOps.MOD else '0'}, {reg_map[out.nm]}")
        elif any([all_int32,all_int8,all_int64]) and reg == 's':
          ins.append(f"fcvtzs {'x' if all_int64 else 'w'}0, s0")
          ins.append(f"str{'b' if all_int8 else ''} {'x' if all_int64 else 'w'}{'2' if arg == BinaryOps.MOD else '0'}, {reg_map[out.nm]}")
        else:
          ins.append(f"str {reg}{'2' if arg == BinaryOps.MOD else '0'}, {reg_map[out.nm]}")
      elif uop == UOps.LOAD:
        reg = 's0' if dtypes.is_float(out[1]) and not all_int64 else 'x0'
        #reg = _type_to_reg[out[1]] + '0' 
        ins.append(f"ldr x1, {reg_map[vin[0].nm]}")
        if reg == 's0' and arg[0] < -255:
          ins.append(f"mov x2, #{abs(arg[0])}")
          ins.append("sub x1, x1, x2")
          ins.append(f"ldr {reg}0, [x1]")
        else:
          ins.append(f"ldr {reg}, [x1, #{arg[0]}]")
          ins.append(f"str {reg}, {reg_map[out.nm]}")
      elif uop == UOps.STORE: 
        ins.append(f"ldr{'sb' if buf_to_dtype[1] in [dtypes.int8, dtypes.uint8] else ''} {_type_to_reg[buf_to_dtype[1]]}0, {reg_map[vin[1].nm]}")
        if len(buf_to_dtype) == 2 and buf_to_dtype[0] != buf_to_dtype[1]:
          if buf_to_dtype[1] == dtypes.half:
            ins.append(f"fcvt s0,  {_type_to_reg[buf_to_dtype[1]]}0")
            if dtypes.is_int(buf_to_dtype[0]) or dtypes.is_unsigned(buf_to_dtype[0]):
              ins.append(f"fcvtzs {_type_to_reg[buf_to_dtype[0]]}0, s0")
          elif buf_to_dtype[1] == dtypes.float:
            if buf_to_dtype[0] == dtypes.half:
              ins.append(f"fcvt {_type_to_reg[buf_to_dtype[0]]}0,  {_type_to_reg[buf_to_dtype[1]]}0")
            else:
              ins.append(f"fcvtzs {_type_to_reg[buf_to_dtype[0]]}0,  {_type_to_reg[buf_to_dtype[1]]}0")
          elif buf_to_dtype[1] in [dtypes.int8, dtypes.uint8, dtypes.int32, dtypes.int64]:
            if buf_to_dtype[0] == dtypes.float:
              ins.append(f"scvtf {_type_to_reg[buf_to_dtype[0]]}0,  {_type_to_reg[buf_to_dtype[1]]}0")
            elif buf_to_dtype[0] == dtypes.half: 
              ins.append(f"scvtf s0,  {_type_to_reg[buf_to_dtype[1]]}0")
              ins.append(f"fcvt {_type_to_reg[buf_to_dtype[0]]}0, s0")
            elif buf_to_dtype[0] in [dtypes.int64, dtypes.int32]:
              ins.append(f"scvtf s0,  {_type_to_reg[buf_to_dtype[1]]}0")
              ins.append(f"fcvtzs {_type_to_reg[buf_to_dtype[0]]}0, s0")
        ins.append(f"mov x3, #{arg[0]}")
        ins.append(f"ldr x2, {reg_map[vin[0].nm]}")
        ins.append(f"str {_type_to_reg[buf_to_dtype[0]]}0, [x2, x3, lsl {'#3' if buf_to_dtype[0] == dtypes.int64 else '#1' if  buf_to_dtype[0] == dtypes.half else '#2' if buf_to_dtype[0] in [dtypes.int8, dtypes.uint8] else '#0'}]")
      elif uop == UOps.COND_BRANCH:
        ins.append(f"b.{'lt' if arg[1]==True else 'ge'} {arg[0][1:]}")
      elif uop == UOps.LABEL:
        ins.append(f"{arg[1:]}:")
    return "test", "\n".join([".arch armv8-a",".text", ".global _test",".p2align 2", "_test:", "mov x19, sp",f"sub sp, sp, #{var_size}"] + ins  + [f"add sp, sp, #{var_size}","ret;"])
