# 4位同步计数器FPGA工程

## 1. 设计目标
- 实现一个4位同步二进制计数器，计数范围从0到15。
- 支持同步使能控制，当使能信号有效时，每个时钟上升沿计数加1。
- 支持低有效异步复位，复位时计数器清零。
- 提供计数溢出标志，当计数器从15跳变到0时产生一个时钟周期的高电平脉冲。
- 不实现可加载初始值、可逆计数、多模式选择等复杂功能。
- 不实现任何外部接口协议，仅作为独立计数器模块。

## 2. 语言与工具约束
- RTL语言：Verilog-2001。
- 禁止使用SystemVerilog语法，包括logic类型、always_ff、always_comb、interface、typedef等。
- 目标工具：Icarus Verilog 10.3、ModelSim SE-64 10.6、Vivado 2017.4。
- 时钟统一命名为clk，复位统一命名为rst_n，低有效异步复位。
- 所有端口命名使用小写字母和下划线，避免使用大写字母。

## 3. 顶层模块规范

| 项目 | 内容 |
|---|---|
| 顶层文件 | counter_4bit_top.v |
| 顶层模块 | counter_4bit_top |
| 时钟端口 | clk |
| 复位端口 | rst_n |
| 复位类型 | 低有效异步复位 |

### 顶层端口表
| 端口名 | 方向 | 位宽 | 说明 |
|---|---|---|---|
| clk | input | 1 | 系统时钟，上升沿有效 |
| rst_n | input | 1 | 异步复位，低电平有效 |
| en | input | 1 | 计数使能，高电平有效 |
| count | output | 4 | 4位计数器当前值 |
| overflow | output | 1 | 溢出标志，计数从15到0时产生一个时钟周期高电平 |

## 4. 模块划分

| filename | module_name | 是否顶层 | 功能 | 主要输入 | 主要输出 |
|---|---|---|---|---|---|
| counter_4bit_top.v | counter_4bit_top | 是 | 顶层模块，例化计数器核心模块 | clk, rst_n, en | count, overflow |
| counter_4bit_core.v | counter_4bit_core | 否 | 4位同步计数器核心逻辑 | clk, rst_n, en | count, overflow |

## 5. 模块详细接口

### counter_4bit_top
| 端口名 | 方向 | 位宽 | 说明 |
|---|---|---|---|
| clk | input | 1 | 系统时钟 |
| rst_n | input | 1 | 异步复位 |
| en | input | 1 | 计数使能 |
| count | output | 4 | 计数器值 |
| overflow | output | 1 | 溢出标志 |

- 组合逻辑：无。
- 时序逻辑：无。
- 复位行为：无。
- 说明：该模块仅作为顶层封装，直接例化counter_4bit_core模块，所有端口直通连接。

### counter_4bit_core
| 端口名 | 方向 | 位宽 | 说明 |
|---|---|---|---|
| clk | input | 1 | 系统时钟 |
| rst_n | input | 1 | 异步复位 |
| en | input | 1 | 计数使能 |
| count | output | 4 | 计数器值 |
| overflow | output | 1 | 溢出标志 |

- 组合逻辑：overflow信号的生成。当count当前值为4'b1111且en为1时，overflow为1；否则为0。注意：overflow在下一个时钟周期有效，因为count更新后溢出条件才成立。
- 时序逻辑：count寄存器的更新。在时钟上升沿，如果rst_n为低，count清零；否则如果en为高，count加1。
- 复位行为：异步复位，当rst_n为低时，count立即清零，overflow异步清零。

## 6. 模块连接关系
- counter_4bit_top模块例化counter_4bit_core模块，例化名为u_core。
- 关键内部信号：无，所有信号直接通过端口连接。
- 数据流方向：输入信号clk、rst_n、en从顶层端口进入，经过u_core处理后，count和overflow输出到顶层端口。
- 控制流方向：en信号控制计数是否进行，rst_n控制复位，clk驱动所有时序逻辑。

## 7. 功能行为规格
- 计数器在时钟上升沿更新。
- 当rst_n为低时，count立即变为4'b0000，overflow变为1'b0。
- 当rst_n为高且en为高时，每个时钟上升沿count加1。
- 当rst_n为高且en为低时，count保持不变。
- 计数范围：0到15（4'b0000到4'b1111）。
- 当count从4'b1111加1变为4'b0000时，overflow在下一个时钟周期输出高电平，持续一个时钟周期。
- overflow的生成逻辑：在时钟上升沿，如果当前count值为4'b1111且en为1，则下一个时钟周期overflow为1；否则为0。实现时使用寄存器存储overflow。
- 计数器达到最大值15后，下一个使能时钟周期自动回绕到0，继续计数。

## 8. Testbench验收标准
- 测试平台文件固定命名为`tb_top_module.v`。
- 测试平台module名称为tb_counter_4bit_top。
- 测试平台必须例化counter_4bit_top模块，例化名为dut。
- 测试场景必须包括：
  1. 复位测试：拉低rst_n，验证count为0，overflow为0。
  2. 使能计数测试：释放复位后，使能en，验证count从0递增到15，每个时钟周期加1。
  3. 溢出测试：当count从15跳变到0时，验证overflow输出一个时钟周期的高电平。
  4. 使能暂停测试：在计数过程中拉低en，验证count保持不变。
  5. 异步复位中断测试：在计数过程中拉低rst_n，验证count立即清零。
- 成功时打印SIM_RESULT: PASSED。
- 失败时打印SIM_RESULT: FAILED。
- 仿真结束调用$stop。
- 不允许只跑时钟不检查结果，每个测试场景必须使用$display或$monitor打印关键信号，并使用if语句检查预期值，不匹配时打印错误信息并设置失败标志。

## 9. XDC/板卡约束需求
- 顶层端口clk需要约束为时钟信号，指定时钟周期（例如10ns，对应100MHz）。
- 顶层端口rst_n需要约束为异步复位信号，指定set_false_path或使用set_clock_groups。
- 顶层端口en、count、overflow需要约束为普通IO，指定IO标准（例如LVCMOS33）和驱动强度。
- 如果使用FPGA开发板，需要根据板卡原理图指定引脚分配。
- 不需要约束内部信号，工具会自动优化。

## 10. 代码生成规则
- 每个module必须独立成文件，文件名与module名一致（但顶层文件名为counter_4bit_top.v，模块名为counter_4bit_top）。
- module_name必须和架构表一致。
- 禁止空文件，每个文件必须包含完整的module定义。
- 禁止解释文本混入Verilog，所有注释使用//或/* */，但注释内容必须与代码相关。
- 禁止SystemVerilog，所有代码必须符合Verilog-2001标准。
- 循环变量必须声明在module作用域内，使用integer类型。
- 所有always块必须有明确复位或默认赋值，避免latch。
- 组合逻辑使用always @(*)或assign语句，时序逻辑使用always @(posedge clk or negedge rst_n)。
- 所有输出端口必须在所有条件下赋值，避免产生锁存器。