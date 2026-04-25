# 4位可加载可加减同步计数器工程

## 1. 设计目标
- 实现一个4位同步计数器，支持异步低有效复位，复位时count=0、overflow=0、underflow=0。
- 支持可加载功能：load=1时，在时钟上升沿将load_value[3:0]装入count，同时清零overflow和underflow。
- 支持加减计数功能：load=0且en=1时，根据up_down信号进行加一或减一操作。
- 加一计数时，从15加一回绕到0，overflow拉高一个时钟周期；减一计数时，从0减一回绕到15，underflow拉高一个时钟周期。
- 当load=0且en=0时，count保持当前值，overflow和underflow清零。
- 不实现任何其他功能，如同步复位、多周期操作、流水线、中断等。

## 2. 语言与工具约束
- RTL语言：Verilog-2001。
- 禁止使用SystemVerilog语法，包括logic、always_ff、always_comb、interface、typedef、enum、struct等。
- 目标工具：Icarus Verilog (iverilog)、ModelSim (vsim)、Vivado 2017.4。
- 时钟统一命名为clk，复位统一命名为rst_n，低有效异步复位。
- 所有RTL文件扩展名为.v。
- 设计必须可综合，不允许只写行为级不可综合模型。

## 3. 顶层模块规范

| 项目 | 内容 |
|---|---|
| 顶层文件 | counter_load_updown_top.v |
| 顶层模块 | counter_load_updown_top |
| 时钟端口 | clk |
| 复位端口 | rst_n |
| 复位类型 | 低有效异步复位 |

顶层端口表：

| 端口名 | 方向 | 位宽 | 说明 |
|---|---|---|---|
| clk | input | 1 | 系统时钟，上升沿触发 |
| rst_n | input | 1 | 异步低有效复位，复位时count=0, overflow=0, underflow=0 |
| en | input | 1 | 计数使能，高有效；load=0且en=1时计数 |
| load | input | 1 | 加载使能，高有效；优先级高于en；load=1时在clk上升沿装入load_value |
| up_down | input | 1 | 计数方向：1=加一，0=减一 |
| load_value | input | 4 | 加载值，当load=1时装入count |
| count | output | 4 | 当前计数值 |
| overflow | output | 1 | 加一溢出标志，从15加一回绕到0时拉高一个时钟周期 |
| underflow | output | 1 | 减一溢出标志，从0减一回绕到15时拉高一个时钟周期 |

## 4. 模块划分

| filename | module_name | 是否顶层 | 功能 | 主要输入 | 主要输出 |
|---|---|---|---|---|---|
| counter_load_updown_top.v | counter_load_updown_top | 是 | 顶层模块，例化核心模块，提供顶层端口 | clk, rst_n, en, load, up_down, load_value[3:0] | count[3:0], overflow, underflow |
| counter_load_updown_core.v | counter_load_updown_core | 否 | 核心计数器逻辑，实现加载、加减计数、溢出标志生成 | clk, rst_n, en, load, up_down, load_value[3:0] | count[3:0], overflow, underflow |

## 5. 模块详细接口

### counter_load_updown_top

| 端口名 | 方向 | 位宽 | 说明 |
|---|---|---|---|
| clk | input | 1 | 系统时钟 |
| rst_n | input | 1 | 异步低有效复位 |
| en | input | 1 | 计数使能 |
| load | input | 1 | 加载使能 |
| up_down | input | 1 | 计数方向 |
| load_value | input | 4 | 加载值 |
| count | output | 4 | 计数值 |
| overflow | output | 1 | 加一溢出标志 |
| underflow | output | 1 | 减一溢出标志 |

- 组合逻辑：无，仅进行模块例化连接。
- 时序逻辑：无，所有时序逻辑在核心模块中实现。
- 复位行为：无，复位由核心模块处理。

### counter_load_updown_core

| 端口名 | 方向 | 位宽 | 说明 |
|---|---|---|---|
| clk | input | 1 | 系统时钟 |
| rst_n | input | 1 | 异步低有效复位 |
| en | input | 1 | 计数使能 |
| load | input | 1 | 加载使能 |
| up_down | input | 1 | 计数方向 |
| load_value | input | 4 | 加载值 |
| count | output | 4 | 计数值 |
| overflow | output | 1 | 加一溢出标志 |
| underflow | output | 1 | 减一溢出标志 |

- 组合逻辑：根据当前count和up_down信号计算下一个计数值next_count；根据next_count和up_down信号计算overflow_next和underflow_next。
- 时序逻辑：在clk上升沿，如果rst_n为低，则count<=0, overflow<=0, underflow<=0；否则根据load和en信号更新count、overflow、underflow。
- 复位行为：异步低有效复位，复位时count=0, overflow=0, underflow=0。

## 6. 模块连接关系

- 顶层模块counter_load_updown_top例化核心模块counter_load_updown_core。
- 关键内部信号：顶层模块的输入端口直接连接到核心模块的对应输入端口；核心模块的输出端口直接连接到顶层模块的对应输出端口。
- 数据流方向：输入信号从顶层端口流入核心模块，经过核心模块处理后，输出信号从核心模块流出到顶层端口。
- 控制流方向：load信号控制加载操作，en信号控制计数操作，up_down信号控制计数方向，rst_n信号控制复位操作。

## 7. 功能行为规格

- 复位行为：当rst_n为低电平时，异步复位，count=0, overflow=0, underflow=0。
- 加载行为：当rst_n为高电平且load=1时，在clk上升沿，将load_value[3:0]装入count，同时overflow和underflow清零。
- 计数行为：当rst_n为高电平且load=0且en=1时，在clk上升沿，根据up_down信号进行计数：
  - up_down=1：加一计数。如果当前count为15，则下一个count为0，overflow拉高一个时钟周期；否则count加一，overflow保持为0。
  - up_down=0：减一计数。如果当前count为0，则下一个count为15，underflow拉高一个时钟周期；否则count减一，underflow保持为0。
- 保持行为：当rst_n为高电平且load=0且en=0时，count保持当前值，overflow和underflow清零。
- 优先级：load优先级高于en。当load=1时，无论en为何值，都执行加载操作。
- 溢出标志：overflow和underflow只在溢出发生的那个时钟周期拉高，其他时间保持为0。

## 8. Testbench验收标准

- 测试平台文件固定命名为`tb_top_module.v`。
- 测试平台module名称建议为tb_counter_load_updown_top。
- 测试平台必须例化顶层模块counter_load_updown_top。
- 测试平台必须验证以下场景：
  - 复位测试：验证rst_n为低时，count=0, overflow=0, underflow=0。
  - 加载测试：验证load=1时，count被正确加载为load_value，overflow和underflow清零。
  - 加一计数测试：验证up_down=1时，count从0递增到15，然后回绕到0，overflow在回绕时拉高一个时钟周期。
  - 减一计数测试：验证up_down=0时，count从15递减到0，然后回绕到15，underflow在回绕时拉高一个时钟周期。
  - 保持测试：验证en=0时，count保持，overflow和underflow清零。
  - 加载优先级测试：验证load=1且en=1时，执行加载操作，不执行计数操作。
- 成功时打印SIM_RESULT: PASSED。
- 失败时打印SIM_RESULT: FAILED。
- 仿真结束调用$stop。
- 不允许只跑时钟不检查结果。

## 9. XDC/板卡约束需求

- 顶层端口clk需要物理约束为时钟引脚，并指定时钟周期（例如50MHz对应20ns）。
- 顶层端口rst_n需要物理约束为复位引脚，并指定异步复位。
- 顶层端口en、load、up_down、load_value[3:0]需要物理约束为输入引脚，并指定输入延迟。
- 顶层端口count[3:0]、overflow、underflow需要物理约束为输出引脚，并指定输出延迟。
- 如果使用板卡，需要根据板卡原理图指定具体的引脚位置。

## 10. 代码生成规则

- 每个module必须独立成文件，文件名与module名一致（但顶层文件名为counter_load_updown_top.v）。
- module_name必须和架构表一致。
- 禁止空文件。
- 禁止解释文本混入Verilog。
- 禁止SystemVerilog。
- 循环变量必须声明在module作用域。
- 所有always块必须有明确复位或默认赋值，避免latch。