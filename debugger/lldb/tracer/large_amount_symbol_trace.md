
这个模块是一个辅助模块，目标在于发现断点， 提供给trace系统, 断点用正则匹配
可能有好几万个断点，比如chromium的.*TestBody gtest测试集
这个模块提供一个断点管理
断点量
断点设置进度ui
当前进入哪个符号
出了哪个符号,ret系统指令标识
用时多少
都需要记录的讯息
进入一个目标符号，设置一次性的ret指令断点，这样它实现时就消失了，同时记录其它同符号的ret指令断点，遇到同符号的一个ret其它也被删除掉



设置全局breakpoint callback 方式
run_cmd("script import tracer")
run_cmd(
    "script globals()['libc_breakpoint_callback'] = tracer.libc_hooker.libc_breakpoint_callback"
)
run_cmd(
    "script globals()['libc_return_callback'] = tracer.libc_hooker.libc_return_callback"
)

用notify class通知对symbol trace的开始，及结束


def run_cmd(self, cmd: str) -> output or raise ValueError:
"""执行LLDB命令"""
    pass


SBTarget 
BreakpointDelete(SBTarget self, lldb::break_id_t break_id) → bool

FindFunctions(SBTarget self, char const * name, uint32_t name_type_mask=eFunctionNameTypeAny) → SBSymbolContextList
Find functions by name.

Parameters:
name – The name of the function we are looking for.

name_type_mask – A logical OR of one or more FunctionNameType enum bits that indicate what kind of names should be used when doing the lookup. Bits include fully qualified names, base names, C++ methods, or ObjC selectors. See FunctionNameType for more details.

Returns:
A lldb::SBSymbolContextList that gets filled in with all of the symbol contexts for all the matches.


FindModule(SBTarget self, SBFileSpec file_spec) → 


BreakpointCreateByRegex(SBTarget self, char const * symbol_name_regex, char const * module_name=None) → SBBreakpoint

save symbol info to extra_args

SetScriptCallbackFunction(SBBreakpoint self, char const * callback_function_name, SBStructuredData extra_args) → SBError

on breakpoint,  

read extra_args, get symbol name, 

frame GetSymbol(SBFrame self) → SBSymbol

SBSymbolContextList
class lldb.SBSymbolContextList(*args)
Represents a list of symbol context object. See also SBSymbolContext.

For example (from test/python_api/target/TestTargetAPI.py),

def find_functions(self, exe_name):
    '''Exercise SBTarget.FindFunctions() API.'''
    exe = os.path.join(os.getcwd(), exe_name)

    # Create a target by the debugger.
    target = self.dbg.CreateTarget(exe)
    self.assertTrue(target, VALID_TARGET)

    list = lldb.SBSymbolContextList()
    num = target.FindFunctions('c', lldb.eFunctionNameTypeAuto, False, list)
    self.assertTrue(num == 1 and list.GetSize() == 1)

    for sc in list:
        self.assertTrue(sc.GetModule().GetFileSpec().GetFilename() == exe_name)
        self.assertTrue(sc.GetSymbol().GetName() == 'c')
Attributes Summary

blocks

Returns a list() of lldb.SBBlock objects, one for each block in each SBSymbolContext object in this list.

compile_units

Returns a list() of lldb.SBCompileUnit objects, one for each compile unit in each SBSymbolContext object in this list.

functions

Returns a list() of lldb.SBFunction objects, one for each function in each SBSymbolContext object in this list.

line_entries

Returns a list() of lldb.SBLineEntry objects, one for each line entry in each SBSymbolContext object in this list.

modules

Returns a list() of lldb.SBModule objects, one for each module in each SBSymbolContext object in this list.

symbols

Returns a list() of lldb.SBSymbol objects, one for each symbol in each SBSymbolContext object in this list.
GetInstructions(SBSymbol self, SBTarget target) → SBInstructionList


SBInstruction:
addr

A read only property that returns an lldb object that represents the address (lldb.SBAddress) for this instruction.

comment

A read only property that returns the comment for this instruction as a string.

is_branch

A read only property that returns a boolean value that indicates if this instruction is a branch instruction.

mnemonic

A read only property that returns the mnemonic for this instruction as a string.

operands

A read only property that returns the operands for this instruction as a string.

size

A read only property that returns the size in bytes for this instruction as an integer.

check mnemonic startswith ret, whiching function return

create a breakpoint,   pass symbol extra_args

on this breakpoint callback 
mark symbol as leave

set ret breakpoint  then 

execute notify_class's hook

class NotifyClass
    def symbol_enter(symbol_info):
        pass
    def symbol_leave(symbol_info):
        pass

class 
SymbolTrace(tracer: 'Tracer', notify_class: NotifyClass, symbol_info_cache_file: string)
    target tracer.target
    debugger tracer.debugger
    use tracer.run_cmd
    use log from notify_class
    notify_class.logger
method

def register_symbols(
module,
name_regex, 
):
    find module
    findfunctions

    how many breakpoint found?
    printout  symbol's info
    cache_for_symbol, if program not change
    then:
    BreakpointCreateByName(SBTarget self, char const * symbol_name, char const * module_name=None) → SBBreakpoint
    implement our purpose


SBModule 's mmeber, uuid use for test module change or not 
addr_size

A read only property that returns the size in bytes of an address for this module.

byte_order

A read only property that returns an lldb enumeration value (lldb.eByteOrderLittle, lldb.eByteOrderBig, lldb.eByteOrderInvalid) that represents the byte order for this module.

compile_units

A read only property that returns a list() of lldb.SBCompileUnit objects contained in this module.

file

A read only property that returns an lldb object that represents the file (lldb.SBFileSpec) for this object file for this module as it is represented where it is being debugged.

num_sections

A read only property that returns number of sections in the module as an integer.

num_symbols

A read only property that returns number of symbols in the module symbol table as an integer.

platform_file

A read only property that returns an lldb object that represents the file (lldb.SBFileSpec) for this object file for this module as it is represented on the current host system.

section

A read only property that can be used to access compile units by index ("compile_unit = module.compile_unit[0]"), name ("compile_unit = module.compile_unit['main.cpp']"), or using a regular expression ("compile_unit = module.compile_unit[re.compile(...)]").

sections

A read only property that returns a list() of lldb.SBSection objects contained in this module.

symbol

A read only property that can be used to access symbols by index ("symbol = module.symbol[0]"), name ("symbols = module.symbol['main']"), or using a regular expression ("symbols = module.symbol[re.compile(...)]").

symbols

A read only property that returns a list() of lldb.SBSymbol objects contained in this module.

triple

A read only property that returns the target triple (arch-vendor-os) for this module.

uuid

A read only property that returns a standard python uuid.UUID object that represents the UUID of this module.