// Generator : SpinalHDL v1.13.0    git head : d9d72474863badf47d8585d187f3e04ae4749c59
// Component : VexRiscv_EmbeddedJtag
// Git hash  : c4b2a55b22f46afb760446cd69f3ca7c36eef778

`timescale 1ns/1ps

module VexRiscv_EmbeddedJtag (
  input  wire [31:0]   externalResetVector,
  input  wire          timerInterrupt,
  input  wire          softwareInterrupt,
  input  wire [31:0]   externalInterruptArray,
  input  wire          jtagInstruction_tdi,
  input  wire          jtagInstruction_enable,
  input  wire          jtagInstruction_capture,
  input  wire          jtagInstruction_shift,
  input  wire          jtagInstruction_update,
  input  wire          jtagInstruction_reset,
  output wire          jtagInstruction_tdo,
  output wire          ndmreset,
  input  wire          reset,
  output reg           stoptime,
  output reg           iBusWishbone_CYC,
  output reg           iBusWishbone_STB,
  input  wire          iBusWishbone_ACK,
  output wire          iBusWishbone_WE,
  output wire [29:0]   iBusWishbone_ADR,
  input  wire [31:0]   iBusWishbone_DAT_MISO,
  output wire [31:0]   iBusWishbone_DAT_MOSI,
  output wire [3:0]    iBusWishbone_SEL,
  input  wire          iBusWishbone_ERR,
  output wire [2:0]    iBusWishbone_CTI,
  output wire [1:0]    iBusWishbone_BTE,
  output wire          dBusWishbone_CYC,
  output wire          dBusWishbone_STB,
  input  wire          dBusWishbone_ACK,
  output wire          dBusWishbone_WE,
  output wire [29:0]   dBusWishbone_ADR,
  input  wire [31:0]   dBusWishbone_DAT_MISO,
  output wire [31:0]   dBusWishbone_DAT_MOSI,
  output wire [3:0]    dBusWishbone_SEL,
  input  wire          dBusWishbone_ERR,
  output wire [2:0]    dBusWishbone_CTI,
  output wire [1:0]    dBusWishbone_BTE,
  input  wire          clk,
  input  wire          debugReset,
  input  wire          jtag_clk
);
  localparam EnvCtrlEnum_NONE = 2'd0;
  localparam EnvCtrlEnum_XRET = 2'd1;
  localparam EnvCtrlEnum_ECALL = 2'd2;
  localparam EnvCtrlEnum_EBREAK = 2'd3;
  localparam BranchCtrlEnum_INC = 2'd0;
  localparam BranchCtrlEnum_B = 2'd1;
  localparam BranchCtrlEnum_JAL = 2'd2;
  localparam BranchCtrlEnum_JALR = 2'd3;
  localparam ShiftCtrlEnum_DISABLE_1 = 2'd0;
  localparam ShiftCtrlEnum_SLL_1 = 2'd1;
  localparam ShiftCtrlEnum_SRL_1 = 2'd2;
  localparam ShiftCtrlEnum_SRA_1 = 2'd3;
  localparam AluBitwiseCtrlEnum_XOR_1 = 2'd0;
  localparam AluBitwiseCtrlEnum_OR_1 = 2'd1;
  localparam AluBitwiseCtrlEnum_AND_1 = 2'd2;
  localparam Src2CtrlEnum_RS = 2'd0;
  localparam Src2CtrlEnum_IMI = 2'd1;
  localparam Src2CtrlEnum_IMS = 2'd2;
  localparam Src2CtrlEnum_PC = 2'd3;
  localparam AluCtrlEnum_ADD_SUB = 2'd0;
  localparam AluCtrlEnum_SLT_SLTU = 2'd1;
  localparam AluCtrlEnum_BITWISE = 2'd2;
  localparam Src1CtrlEnum_RS = 2'd0;
  localparam Src1CtrlEnum_IMU = 2'd1;
  localparam Src1CtrlEnum_PC_INCREMENT = 2'd2;
  localparam Src1CtrlEnum_URS1 = 2'd3;
  localparam DebugDmToHartOp_DATA = 2'd0;
  localparam DebugDmToHartOp_EXECUTE = 2'd1;
  localparam DebugDmToHartOp_REG_WRITE = 2'd2;
  localparam DebugDmToHartOp_REG_READ = 2'd3;
  localparam CsrPlugin_dcsr_stepLogic_BOOT = 2'd0;
  localparam CsrPlugin_dcsr_stepLogic_IDLE = 2'd1;
  localparam CsrPlugin_dcsr_stepLogic_SINGLE = 2'd2;
  localparam CsrPlugin_dcsr_stepLogic_WAIT_1 = 2'd3;

  wire                IBusCachedPlugin_cache_io_flush;
  wire                IBusCachedPlugin_cache_io_cpu_prefetch_isValid;
  wire                IBusCachedPlugin_cache_io_cpu_fetch_isValid;
  wire                IBusCachedPlugin_cache_io_cpu_fetch_isStuck;
  wire                IBusCachedPlugin_cache_io_cpu_decode_isValid;
  wire                IBusCachedPlugin_cache_io_cpu_decode_isStuck;
  wire                IBusCachedPlugin_cache_io_cpu_decode_isUser;
  reg                 IBusCachedPlugin_cache_io_cpu_fill_valid;
  reg        [31:0]   RegFilePlugin_regFile_spinal_port0;
  reg        [31:0]   RegFilePlugin_regFile_spinal_port1;
  wire                IBusCachedPlugin_cache_io_cpu_prefetch_haltIt;
  wire       [31:0]   IBusCachedPlugin_cache_io_cpu_fetch_data;
  wire       [31:0]   IBusCachedPlugin_cache_io_cpu_fetch_physicalAddress;
  wire                IBusCachedPlugin_cache_io_cpu_decode_error;
  wire                IBusCachedPlugin_cache_io_cpu_decode_mmuRefilling;
  wire                IBusCachedPlugin_cache_io_cpu_decode_mmuException;
  wire       [31:0]   IBusCachedPlugin_cache_io_cpu_decode_data;
  wire                IBusCachedPlugin_cache_io_cpu_decode_cacheMiss;
  wire       [31:0]   IBusCachedPlugin_cache_io_cpu_decode_physicalAddress;
  wire                IBusCachedPlugin_cache_io_mem_cmd_valid;
  wire       [31:0]   IBusCachedPlugin_cache_io_mem_cmd_payload_address;
  wire       [2:0]    IBusCachedPlugin_cache_io_mem_cmd_payload_size;
  wire                reset_buffercc_io_dataOut;
  wire                debugModule_1_io_ctrl_cmd_ready;
  wire                debugModule_1_io_ctrl_rsp_valid;
  wire                debugModule_1_io_ctrl_rsp_payload_error;
  wire       [31:0]   debugModule_1_io_ctrl_rsp_payload_data;
  wire                debugModule_1_io_ndmreset;
  wire                debugModule_1_io_harts_0_resume_cmd_valid;
  wire                debugModule_1_io_harts_0_dmToHart_valid;
  wire       [1:0]    debugModule_1_io_harts_0_dmToHart_payload_op;
  wire       [4:0]    debugModule_1_io_harts_0_dmToHart_payload_address;
  wire       [31:0]   debugModule_1_io_harts_0_dmToHart_payload_data;
  wire       [2:0]    debugModule_1_io_harts_0_dmToHart_payload_size;
  wire                debugModule_1_io_harts_0_haltReq;
  wire                debugModule_1_io_harts_0_ackReset;
  wire                debugTransportModuleTunneled_1_io_instruction_tdo;
  wire                debugTransportModuleTunneled_1_io_bus_cmd_valid;
  wire                debugTransportModuleTunneled_1_io_bus_cmd_payload_write;
  wire       [31:0]   debugTransportModuleTunneled_1_io_bus_cmd_payload_data;
  wire       [6:0]    debugTransportModuleTunneled_1_io_bus_cmd_payload_address;
  wire       [31:0]   _zz_decode_LEGAL_INSTRUCTION;
  wire       [31:0]   _zz_decode_LEGAL_INSTRUCTION_1;
  wire       [31:0]   _zz_decode_LEGAL_INSTRUCTION_2;
  wire                _zz_decode_LEGAL_INSTRUCTION_3;
  wire       [0:0]    _zz_decode_LEGAL_INSTRUCTION_4;
  wire       [12:0]   _zz_decode_LEGAL_INSTRUCTION_5;
  wire       [31:0]   _zz_decode_LEGAL_INSTRUCTION_6;
  wire       [31:0]   _zz_decode_LEGAL_INSTRUCTION_7;
  wire       [31:0]   _zz_decode_LEGAL_INSTRUCTION_8;
  wire                _zz_decode_LEGAL_INSTRUCTION_9;
  wire       [0:0]    _zz_decode_LEGAL_INSTRUCTION_10;
  wire       [6:0]    _zz_decode_LEGAL_INSTRUCTION_11;
  wire       [31:0]   _zz_decode_LEGAL_INSTRUCTION_12;
  wire       [31:0]   _zz_decode_LEGAL_INSTRUCTION_13;
  wire       [31:0]   _zz_decode_LEGAL_INSTRUCTION_14;
  wire                _zz_decode_LEGAL_INSTRUCTION_15;
  wire       [0:0]    _zz_decode_LEGAL_INSTRUCTION_16;
  wire       [0:0]    _zz_decode_LEGAL_INSTRUCTION_17;
  wire       [2:0]    _zz__zz_IBusCachedPlugin_jump_pcLoad_payload_1;
  reg        [31:0]   _zz_IBusCachedPlugin_jump_pcLoad_payload_4;
  wire       [1:0]    _zz_IBusCachedPlugin_jump_pcLoad_payload_5;
  wire       [31:0]   _zz_IBusCachedPlugin_fetchPc_pc;
  wire       [2:0]    _zz_IBusCachedPlugin_fetchPc_pc_1;
  wire       [11:0]   _zz__zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch;
  wire       [31:0]   _zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch_2;
  wire       [19:0]   _zz__zz_2;
  wire       [11:0]   _zz__zz_4;
  wire       [31:0]   _zz__zz_6;
  wire       [31:0]   _zz__zz_6_1;
  wire       [19:0]   _zz__zz_IBusCachedPlugin_predictionJumpInterface_payload;
  wire       [11:0]   _zz__zz_IBusCachedPlugin_predictionJumpInterface_payload_2;
  wire                _zz_IBusCachedPlugin_predictionJumpInterface_payload_4;
  wire                _zz_IBusCachedPlugin_predictionJumpInterface_payload_5;
  wire                _zz_IBusCachedPlugin_predictionJumpInterface_payload_6;
  wire       [2:0]    _zz_DBusSimplePlugin_memoryExceptionPort_payload_code;
  wire       [31:0]   _zz__zz_decode_IS_DIV;
  wire       [0:0]    _zz__zz_decode_IS_DIV_1;
  wire       [1:0]    _zz__zz_decode_IS_DIV_2;
  wire       [0:0]    _zz__zz_decode_IS_DIV_3;
  wire                _zz__zz_decode_IS_DIV_4;
  wire       [31:0]   _zz__zz_decode_IS_DIV_5;
  wire       [0:0]    _zz__zz_decode_IS_DIV_6;
  wire                _zz__zz_decode_IS_DIV_7;
  wire                _zz__zz_decode_IS_DIV_8;
  wire       [24:0]   _zz__zz_decode_IS_DIV_9;
  wire       [0:0]    _zz__zz_decode_IS_DIV_10;
  wire       [31:0]   _zz__zz_decode_IS_DIV_11;
  wire       [0:0]    _zz__zz_decode_IS_DIV_12;
  wire       [31:0]   _zz__zz_decode_IS_DIV_13;
  wire       [1:0]    _zz__zz_decode_IS_DIV_14;
  wire       [31:0]   _zz__zz_decode_IS_DIV_15;
  wire       [31:0]   _zz__zz_decode_IS_DIV_16;
  wire                _zz__zz_decode_IS_DIV_17;
  wire       [31:0]   _zz__zz_decode_IS_DIV_18;
  wire       [31:0]   _zz__zz_decode_IS_DIV_19;
  wire       [0:0]    _zz__zz_decode_IS_DIV_20;
  wire                _zz__zz_decode_IS_DIV_21;
  wire       [20:0]   _zz__zz_decode_IS_DIV_22;
  wire       [1:0]    _zz__zz_decode_IS_DIV_23;
  wire       [31:0]   _zz__zz_decode_IS_DIV_24;
  wire       [31:0]   _zz__zz_decode_IS_DIV_25;
  wire                _zz__zz_decode_IS_DIV_26;
  wire       [31:0]   _zz__zz_decode_IS_DIV_27;
  wire       [31:0]   _zz__zz_decode_IS_DIV_28;
  wire       [31:0]   _zz__zz_decode_IS_DIV_29;
  wire       [31:0]   _zz__zz_decode_IS_DIV_30;
  wire       [0:0]    _zz__zz_decode_IS_DIV_31;
  wire       [31:0]   _zz__zz_decode_IS_DIV_32;
  wire       [31:0]   _zz__zz_decode_IS_DIV_33;
  wire       [17:0]   _zz__zz_decode_IS_DIV_34;
  wire       [1:0]    _zz__zz_decode_IS_DIV_35;
  wire       [31:0]   _zz__zz_decode_IS_DIV_36;
  wire       [31:0]   _zz__zz_decode_IS_DIV_37;
  wire                _zz__zz_decode_IS_DIV_38;
  wire       [31:0]   _zz__zz_decode_IS_DIV_39;
  wire       [31:0]   _zz__zz_decode_IS_DIV_40;
  wire       [31:0]   _zz__zz_decode_IS_DIV_41;
  wire       [31:0]   _zz__zz_decode_IS_DIV_42;
  wire       [0:0]    _zz__zz_decode_IS_DIV_43;
  wire                _zz__zz_decode_IS_DIV_44;
  wire       [0:0]    _zz__zz_decode_IS_DIV_45;
  wire       [0:0]    _zz__zz_decode_IS_DIV_46;
  wire       [31:0]   _zz__zz_decode_IS_DIV_47;
  wire       [13:0]   _zz__zz_decode_IS_DIV_48;
  wire                _zz__zz_decode_IS_DIV_49;
  wire       [0:0]    _zz__zz_decode_IS_DIV_50;
  wire       [31:0]   _zz__zz_decode_IS_DIV_51;
  wire                _zz__zz_decode_IS_DIV_52;
  wire       [0:0]    _zz__zz_decode_IS_DIV_53;
  wire       [31:0]   _zz__zz_decode_IS_DIV_54;
  wire       [0:0]    _zz__zz_decode_IS_DIV_55;
  wire       [31:0]   _zz__zz_decode_IS_DIV_56;
  wire       [0:0]    _zz__zz_decode_IS_DIV_57;
  wire       [0:0]    _zz__zz_decode_IS_DIV_58;
  wire       [4:0]    _zz__zz_decode_IS_DIV_59;
  wire       [31:0]   _zz__zz_decode_IS_DIV_60;
  wire       [31:0]   _zz__zz_decode_IS_DIV_61;
  wire                _zz__zz_decode_IS_DIV_62;
  wire       [31:0]   _zz__zz_decode_IS_DIV_63;
  wire       [0:0]    _zz__zz_decode_IS_DIV_64;
  wire       [31:0]   _zz__zz_decode_IS_DIV_65;
  wire       [31:0]   _zz__zz_decode_IS_DIV_66;
  wire       [1:0]    _zz__zz_decode_IS_DIV_67;
  wire                _zz__zz_decode_IS_DIV_68;
  wire                _zz__zz_decode_IS_DIV_69;
  wire       [9:0]    _zz__zz_decode_IS_DIV_70;
  wire       [1:0]    _zz__zz_decode_IS_DIV_71;
  wire       [31:0]   _zz__zz_decode_IS_DIV_72;
  wire       [31:0]   _zz__zz_decode_IS_DIV_73;
  wire                _zz__zz_decode_IS_DIV_74;
  wire                _zz__zz_decode_IS_DIV_75;
  wire       [31:0]   _zz__zz_decode_IS_DIV_76;
  wire       [0:0]    _zz__zz_decode_IS_DIV_77;
  wire       [0:0]    _zz__zz_decode_IS_DIV_78;
  wire       [31:0]   _zz__zz_decode_IS_DIV_79;
  wire       [31:0]   _zz__zz_decode_IS_DIV_80;
  wire       [0:0]    _zz__zz_decode_IS_DIV_81;
  wire       [31:0]   _zz__zz_decode_IS_DIV_82;
  wire       [31:0]   _zz__zz_decode_IS_DIV_83;
  wire       [6:0]    _zz__zz_decode_IS_DIV_84;
  wire       [0:0]    _zz__zz_decode_IS_DIV_85;
  wire       [31:0]   _zz__zz_decode_IS_DIV_86;
  wire       [31:0]   _zz__zz_decode_IS_DIV_87;
  wire                _zz__zz_decode_IS_DIV_88;
  wire       [0:0]    _zz__zz_decode_IS_DIV_89;
  wire       [31:0]   _zz__zz_decode_IS_DIV_90;
  wire       [2:0]    _zz__zz_decode_IS_DIV_91;
  wire                _zz__zz_decode_IS_DIV_92;
  wire                _zz__zz_decode_IS_DIV_93;
  wire       [0:0]    _zz__zz_decode_IS_DIV_94;
  wire       [0:0]    _zz__zz_decode_IS_DIV_95;
  wire       [31:0]   _zz__zz_decode_IS_DIV_96;
  wire       [3:0]    _zz__zz_decode_IS_DIV_97;
  wire                _zz__zz_decode_IS_DIV_98;
  wire                _zz__zz_decode_IS_DIV_99;
  wire       [0:0]    _zz__zz_decode_IS_DIV_100;
  wire       [31:0]   _zz__zz_decode_IS_DIV_101;
  wire       [0:0]    _zz__zz_decode_IS_DIV_102;
  wire       [31:0]   _zz__zz_decode_IS_DIV_103;
  wire       [0:0]    _zz__zz_decode_IS_DIV_104;
  wire       [0:0]    _zz__zz_decode_IS_DIV_105;
  wire       [31:0]   _zz__zz_decode_IS_DIV_106;
  wire       [0:0]    _zz__zz_decode_IS_DIV_107;
  wire       [1:0]    _zz__zz_decode_IS_DIV_108;
  wire       [1:0]    _zz__zz_decode_IS_DIV_109;
  wire       [31:0]   _zz__zz_decode_IS_DIV_110;
  wire       [31:0]   _zz__zz_decode_IS_DIV_111;
  wire       [0:0]    _zz__zz_decode_IS_DIV_112;
  wire       [31:0]   _zz__zz_decode_IS_DIV_113;
  wire                _zz_RegFilePlugin_regFile_port;
  wire                _zz_decode_RegFilePlugin_rs1Data;
  wire                _zz_RegFilePlugin_regFile_port_1;
  wire                _zz_decode_RegFilePlugin_rs2Data;
  wire       [0:0]    _zz__zz_execute_REGFILE_WRITE_DATA;
  wire       [2:0]    _zz__zz_execute_SRC1;
  wire       [4:0]    _zz__zz_execute_SRC1_1;
  wire       [11:0]   _zz__zz_execute_SRC2_2;
  wire       [31:0]   _zz_execute_SrcPlugin_addSub;
  wire       [31:0]   _zz_execute_SrcPlugin_addSub_1;
  wire       [31:0]   _zz_execute_SrcPlugin_addSub_2;
  wire       [31:0]   _zz_execute_SrcPlugin_addSub_3;
  wire       [31:0]   _zz_execute_SrcPlugin_addSub_4;
  wire       [31:0]   _zz__zz_decode_RS2_3;
  wire       [32:0]   _zz__zz_decode_RS2_3_1;
  wire       [19:0]   _zz__zz_execute_BranchPlugin_missAlignedTarget_2;
  wire       [11:0]   _zz__zz_execute_BranchPlugin_missAlignedTarget_4;
  wire       [31:0]   _zz__zz_execute_BranchPlugin_missAlignedTarget_6;
  wire       [31:0]   _zz__zz_execute_BranchPlugin_missAlignedTarget_6_1;
  wire       [31:0]   _zz__zz_execute_BranchPlugin_missAlignedTarget_6_2;
  wire       [19:0]   _zz__zz_execute_BranchPlugin_branch_src2_2;
  wire       [11:0]   _zz__zz_execute_BranchPlugin_branch_src2_4;
  wire       [0:0]    _zz_execute_BranchPlugin_branch_src2_6;
  wire       [7:0]    _zz_execute_BranchPlugin_branch_src2_7;
  wire                _zz_execute_BranchPlugin_branch_src2_8;
  wire       [0:0]    _zz_execute_BranchPlugin_branch_src2_9;
  wire       [0:0]    _zz_execute_BranchPlugin_branch_src2_10;
  wire       [2:0]    _zz_execute_BranchPlugin_branch_src2_11;
  wire       [2:0]    _zz_CsrPlugin_timeout_counter_valueNext;
  wire       [0:0]    _zz_CsrPlugin_timeout_counter_valueNext_1;
  wire       [0:0]    _zz_when;
  wire       [1:0]    _zz_CsrPlugin_trigger_decodeBreak_timeout_counter_valueNext;
  wire       [0:0]    _zz_CsrPlugin_trigger_decodeBreak_timeout_counter_valueNext_1;
  wire       [63:0]   _zz_CsrPlugin_mcycle;
  wire       [0:0]    _zz_CsrPlugin_mcycle_1;
  wire       [1:0]    _zz__zz_CsrPlugin_exceptionPortCtrl_exceptionContext_code_1;
  wire       [1:0]    _zz__zz_CsrPlugin_exceptionPortCtrl_exceptionContext_code_1_1;
  wire       [1:0]    _zz__zz_CsrPlugin_exceptionPortCtrl_exceptionContext_code_3;
  wire       [1:0]    _zz__zz_CsrPlugin_exceptionPortCtrl_exceptionContext_code_3_1;
  wire                _zz_when_1;
  wire                _zz_when_2;
  wire       [5:0]    _zz_memory_MulDivIterativePlugin_mul_counter_valueNext;
  wire       [0:0]    _zz_memory_MulDivIterativePlugin_mul_counter_valueNext_1;
  wire       [33:0]   _zz_memory_MulDivIterativePlugin_accumulator;
  wire       [33:0]   _zz_memory_MulDivIterativePlugin_accumulator_1;
  wire       [32:0]   _zz_memory_MulDivIterativePlugin_accumulator_2;
  wire       [33:0]   _zz_memory_MulDivIterativePlugin_accumulator_3;
  wire       [32:0]   _zz_memory_MulDivIterativePlugin_accumulator_4;
  wire       [32:0]   _zz_memory_MulDivIterativePlugin_accumulator_5;
  wire       [5:0]    _zz_memory_MulDivIterativePlugin_div_counter_valueNext;
  wire       [0:0]    _zz_memory_MulDivIterativePlugin_div_counter_valueNext_1;
  wire       [32:0]   _zz_memory_MulDivIterativePlugin_div_stage_0_remainderMinusDenominator;
  wire       [31:0]   _zz_memory_MulDivIterativePlugin_div_stage_0_outRemainder;
  wire       [31:0]   _zz_memory_MulDivIterativePlugin_div_stage_0_outRemainder_1;
  wire       [32:0]   _zz_memory_MulDivIterativePlugin_div_stage_0_outNumerator;
  wire       [32:0]   _zz_memory_MulDivIterativePlugin_div_result_1;
  wire       [32:0]   _zz_memory_MulDivIterativePlugin_div_result_2;
  wire       [32:0]   _zz_memory_MulDivIterativePlugin_div_result_3;
  wire       [32:0]   _zz_memory_MulDivIterativePlugin_div_result_4;
  wire       [0:0]    _zz_memory_MulDivIterativePlugin_div_result_5;
  wire       [32:0]   _zz_memory_MulDivIterativePlugin_rs1_2;
  wire       [0:0]    _zz_memory_MulDivIterativePlugin_rs1_3;
  wire       [31:0]   _zz_memory_MulDivIterativePlugin_rs2_1;
  wire       [0:0]    _zz_memory_MulDivIterativePlugin_rs2_2;
  reg        [31:0]   _zz__zz_CsrPlugin_csrMapping_readDataInit_6;
  wire       [7:0]    _zz_when_CsrPlugin_l1718;
  wire       [26:0]   _zz_iBusWishbone_ADR_1;
  wire       [31:0]   memory_MEMORY_READ_DATA;
  wire       [31:0]   execute_BRANCH_CALC;
  wire                execute_BRANCH_DO;
  wire       [31:0]   writeBack_REGFILE_WRITE_DATA;
  wire       [31:0]   execute_REGFILE_WRITE_DATA;
  wire       [1:0]    memory_MEMORY_ADDRESS_LOW;
  wire       [1:0]    execute_MEMORY_ADDRESS_LOW;
  wire                decode_CSR_READ_OPCODE;
  wire                decode_CSR_WRITE_OPCODE;
  wire                decode_PREDICTION_HAD_BRANCHED1;
  wire                decode_SRC2_FORCE_ZERO;
  wire                decode_IS_DIV;
  wire                decode_IS_RS2_SIGNED;
  wire                decode_IS_RS1_SIGNED;
  wire                decode_IS_MUL;
  wire       [1:0]    _zz_memory_to_writeBack_ENV_CTRL;
  wire       [1:0]    _zz_memory_to_writeBack_ENV_CTRL_1;
  wire       [1:0]    _zz_execute_to_memory_ENV_CTRL;
  wire       [1:0]    _zz_execute_to_memory_ENV_CTRL_1;
  wire       [1:0]    decode_ENV_CTRL;
  wire       [1:0]    _zz_decode_ENV_CTRL;
  wire       [1:0]    _zz_decode_to_execute_ENV_CTRL;
  wire       [1:0]    _zz_decode_to_execute_ENV_CTRL_1;
  wire                decode_IS_CSR;
  wire       [1:0]    _zz_decode_to_execute_BRANCH_CTRL;
  wire       [1:0]    _zz_decode_to_execute_BRANCH_CTRL_1;
  wire       [1:0]    decode_SHIFT_CTRL;
  wire       [1:0]    _zz_decode_SHIFT_CTRL;
  wire       [1:0]    _zz_decode_to_execute_SHIFT_CTRL;
  wire       [1:0]    _zz_decode_to_execute_SHIFT_CTRL_1;
  wire       [1:0]    decode_ALU_BITWISE_CTRL;
  wire       [1:0]    _zz_decode_ALU_BITWISE_CTRL;
  wire       [1:0]    _zz_decode_to_execute_ALU_BITWISE_CTRL;
  wire       [1:0]    _zz_decode_to_execute_ALU_BITWISE_CTRL_1;
  wire                decode_SRC_LESS_UNSIGNED;
  wire                decode_MEMORY_STORE;
  wire                execute_BYPASSABLE_MEMORY_STAGE;
  wire                decode_BYPASSABLE_MEMORY_STAGE;
  wire                decode_BYPASSABLE_EXECUTE_STAGE;
  wire       [1:0]    decode_SRC2_CTRL;
  wire       [1:0]    _zz_decode_SRC2_CTRL;
  wire       [1:0]    _zz_decode_to_execute_SRC2_CTRL;
  wire       [1:0]    _zz_decode_to_execute_SRC2_CTRL_1;
  wire       [1:0]    decode_ALU_CTRL;
  wire       [1:0]    _zz_decode_ALU_CTRL;
  wire       [1:0]    _zz_decode_to_execute_ALU_CTRL;
  wire       [1:0]    _zz_decode_to_execute_ALU_CTRL_1;
  wire                decode_MEMORY_ENABLE;
  wire       [1:0]    decode_SRC1_CTRL;
  wire       [1:0]    _zz_decode_SRC1_CTRL;
  wire       [1:0]    _zz_decode_to_execute_SRC1_CTRL;
  wire       [1:0]    _zz_decode_to_execute_SRC1_CTRL_1;
  wire       [31:0]   writeBack_FORMAL_PC_NEXT;
  wire       [31:0]   memory_FORMAL_PC_NEXT;
  wire       [31:0]   execute_FORMAL_PC_NEXT;
  wire       [31:0]   decode_FORMAL_PC_NEXT;
  wire       [31:0]   memory_PC;
  wire                execute_IS_RS1_SIGNED;
  wire                execute_IS_DIV;
  wire                execute_IS_MUL;
  wire                execute_IS_RS2_SIGNED;
  wire                memory_IS_DIV;
  wire                memory_IS_MUL;
  wire                execute_CSR_READ_OPCODE;
  wire                execute_CSR_WRITE_OPCODE;
  wire                execute_IS_CSR;
  wire       [1:0]    memory_ENV_CTRL;
  wire       [1:0]    _zz_memory_ENV_CTRL;
  wire       [1:0]    execute_ENV_CTRL;
  wire       [1:0]    _zz_execute_ENV_CTRL;
  wire       [1:0]    writeBack_ENV_CTRL;
  wire       [1:0]    _zz_writeBack_ENV_CTRL;
  reg                 CsrPlugin_running_aheadValue;
  wire       [31:0]   memory_BRANCH_CALC;
  wire                memory_BRANCH_DO;
  wire       [31:0]   execute_PC;
  wire                execute_PREDICTION_HAD_BRANCHED1;
  wire       [31:0]   execute_RS1;
  wire                execute_BRANCH_COND_RESULT;
  wire       [1:0]    execute_BRANCH_CTRL;
  wire       [1:0]    _zz_execute_BRANCH_CTRL;
  wire                decode_RS2_USE;
  wire                decode_RS1_USE;
  wire                execute_REGFILE_WRITE_VALID;
  wire                execute_BYPASSABLE_EXECUTE_STAGE;
  reg        [31:0]   _zz_decode_RS2;
  wire                memory_REGFILE_WRITE_VALID;
  wire       [31:0]   memory_INSTRUCTION;
  wire                memory_BYPASSABLE_MEMORY_STAGE;
  wire                writeBack_REGFILE_WRITE_VALID;
  reg        [31:0]   decode_RS2;
  reg        [31:0]   decode_RS1;
  reg        [31:0]   _zz_decode_RS2_1;
  wire       [1:0]    execute_SHIFT_CTRL;
  wire       [1:0]    _zz_execute_SHIFT_CTRL;
  wire                execute_SRC_LESS_UNSIGNED;
  wire                execute_SRC2_FORCE_ZERO;
  wire                execute_SRC_USE_SUB_LESS;
  wire       [31:0]   _zz_execute_to_memory_PC;
  wire       [1:0]    execute_SRC2_CTRL;
  wire       [1:0]    _zz_execute_SRC2_CTRL;
  wire       [1:0]    execute_SRC1_CTRL;
  wire       [1:0]    _zz_execute_SRC1_CTRL;
  wire                decode_SRC_USE_SUB_LESS;
  wire                decode_SRC_ADD_ZERO;
  wire       [31:0]   execute_SRC_ADD_SUB;
  wire                execute_SRC_LESS;
  wire       [1:0]    execute_ALU_CTRL;
  wire       [1:0]    _zz_execute_ALU_CTRL;
  wire       [31:0]   execute_SRC2;
  wire       [31:0]   execute_SRC1;
  wire       [1:0]    execute_ALU_BITWISE_CTRL;
  wire       [1:0]    _zz_execute_ALU_BITWISE_CTRL;
  wire       [31:0]   _zz_lastStageRegFileWrite_payload_address;
  wire                _zz_lastStageRegFileWrite_valid;
  reg                 _zz_1;
  wire       [31:0]   decode_INSTRUCTION_ANTICIPATED;
  reg                 decode_REGFILE_WRITE_VALID;
  wire                decode_LEGAL_INSTRUCTION;
  wire       [1:0]    _zz_decode_ENV_CTRL_1;
  wire       [1:0]    _zz_decode_BRANCH_CTRL;
  wire       [1:0]    _zz_decode_SHIFT_CTRL_1;
  wire       [1:0]    _zz_decode_ALU_BITWISE_CTRL_1;
  wire       [1:0]    _zz_decode_SRC2_CTRL_1;
  wire       [1:0]    _zz_decode_ALU_CTRL_1;
  wire       [1:0]    _zz_decode_SRC1_CTRL_1;
  reg        [31:0]   _zz_decode_RS2_2;
  wire                writeBack_MEMORY_ENABLE;
  wire       [1:0]    writeBack_MEMORY_ADDRESS_LOW;
  wire       [31:0]   writeBack_MEMORY_READ_DATA;
  wire                memory_ALIGNEMENT_FAULT;
  wire       [31:0]   memory_REGFILE_WRITE_DATA;
  wire                memory_MEMORY_STORE;
  wire                memory_MEMORY_ENABLE;
  wire       [31:0]   execute_SRC_ADD;
  wire       [31:0]   execute_RS2;
  wire       [31:0]   execute_INSTRUCTION;
  wire                execute_MEMORY_STORE;
  wire                execute_MEMORY_ENABLE;
  wire                execute_ALIGNEMENT_FAULT;
  wire                decode_FLUSH_ALL;
  reg                 IBusCachedPlugin_rsp_issueDetected_4;
  reg                 IBusCachedPlugin_rsp_issueDetected_3;
  reg                 IBusCachedPlugin_rsp_issueDetected_2;
  reg                 IBusCachedPlugin_rsp_issueDetected_1;
  wire       [1:0]    decode_BRANCH_CTRL;
  wire       [1:0]    _zz_decode_BRANCH_CTRL_1;
  wire       [31:0]   decode_INSTRUCTION;
  reg        [31:0]   _zz_memory_to_writeBack_FORMAL_PC_NEXT;
  reg        [31:0]   _zz_decode_to_execute_FORMAL_PC_NEXT;
  wire       [31:0]   decode_PC;
  wire       [31:0]   writeBack_PC;
  wire       [31:0]   writeBack_INSTRUCTION;
  reg                 decode_arbitration_haltItself;
  reg                 decode_arbitration_haltByOther;
  reg                 decode_arbitration_removeIt;
  wire                decode_arbitration_flushIt;
  reg                 decode_arbitration_flushNext;
  reg                 decode_arbitration_isValid;
  wire                decode_arbitration_isStuck;
  wire                decode_arbitration_isStuckByOthers;
  wire                decode_arbitration_isFlushed;
  wire                decode_arbitration_isMoving;
  wire                decode_arbitration_isFiring;
  reg                 execute_arbitration_haltItself;
  wire                execute_arbitration_haltByOther;
  reg                 execute_arbitration_removeIt;
  wire                execute_arbitration_flushIt;
  reg                 execute_arbitration_flushNext;
  reg                 execute_arbitration_isValid;
  wire                execute_arbitration_isStuck;
  wire                execute_arbitration_isStuckByOthers;
  wire                execute_arbitration_isFlushed;
  wire                execute_arbitration_isMoving;
  wire                execute_arbitration_isFiring;
  reg                 memory_arbitration_haltItself;
  wire                memory_arbitration_haltByOther;
  reg                 memory_arbitration_removeIt;
  wire                memory_arbitration_flushIt;
  reg                 memory_arbitration_flushNext;
  reg                 memory_arbitration_isValid;
  wire                memory_arbitration_isStuck;
  wire                memory_arbitration_isStuckByOthers;
  wire                memory_arbitration_isFlushed;
  wire                memory_arbitration_isMoving;
  wire                memory_arbitration_isFiring;
  wire                writeBack_arbitration_haltItself;
  wire                writeBack_arbitration_haltByOther;
  reg                 writeBack_arbitration_removeIt;
  reg                 writeBack_arbitration_flushIt;
  reg                 writeBack_arbitration_flushNext;
  reg                 writeBack_arbitration_isValid;
  wire                writeBack_arbitration_isStuck;
  wire                writeBack_arbitration_isStuckByOthers;
  wire                writeBack_arbitration_isFlushed;
  wire                writeBack_arbitration_isMoving;
  wire                writeBack_arbitration_isFiring;
  wire       [31:0]   lastStageInstruction /* verilator public */ ;
  wire       [31:0]   lastStagePc /* verilator public */ ;
  wire                lastStageIsValid /* verilator public */ ;
  wire                lastStageIsFiring /* verilator public */ ;
  reg                 IBusCachedPlugin_fetcherHalt;
  wire                IBusCachedPlugin_forceNoDecodeCond;
  reg                 IBusCachedPlugin_incomingInstruction;
  wire                IBusCachedPlugin_predictionJumpInterface_valid;
  (* keep , syn_keep *) wire       [31:0]   IBusCachedPlugin_predictionJumpInterface_payload /* synthesis syn_keep = 1 */ ;
  reg                 IBusCachedPlugin_decodePrediction_cmd_hadBranch;
  wire                IBusCachedPlugin_decodePrediction_rsp_wasWrong;
  wire                IBusCachedPlugin_pcValids_0;
  wire                IBusCachedPlugin_pcValids_1;
  wire                IBusCachedPlugin_pcValids_2;
  wire                IBusCachedPlugin_pcValids_3;
  reg                 IBusCachedPlugin_decodeExceptionPort_valid;
  reg        [3:0]    IBusCachedPlugin_decodeExceptionPort_payload_code;
  wire       [31:0]   IBusCachedPlugin_decodeExceptionPort_payload_badAddr;
  wire                IBusCachedPlugin_mmuBus_cmd_0_isValid;
  wire                IBusCachedPlugin_mmuBus_cmd_0_isStuck;
  wire       [31:0]   IBusCachedPlugin_mmuBus_cmd_0_virtualAddress;
  wire                IBusCachedPlugin_mmuBus_cmd_0_bypassTranslation;
  wire       [31:0]   IBusCachedPlugin_mmuBus_rsp_physicalAddress;
  wire                IBusCachedPlugin_mmuBus_rsp_isIoAccess;
  wire                IBusCachedPlugin_mmuBus_rsp_isPaging;
  wire                IBusCachedPlugin_mmuBus_rsp_allowRead;
  wire                IBusCachedPlugin_mmuBus_rsp_allowWrite;
  wire                IBusCachedPlugin_mmuBus_rsp_allowExecute;
  wire                IBusCachedPlugin_mmuBus_rsp_exception;
  wire                IBusCachedPlugin_mmuBus_rsp_refilling;
  wire                IBusCachedPlugin_mmuBus_rsp_bypassTranslation;
  wire                IBusCachedPlugin_mmuBus_end;
  wire                IBusCachedPlugin_mmuBus_busy;
  reg                 DBusSimplePlugin_memoryExceptionPort_valid;
  reg        [3:0]    DBusSimplePlugin_memoryExceptionPort_payload_code;
  wire       [31:0]   DBusSimplePlugin_memoryExceptionPort_payload_badAddr;
  wire                decodeExceptionPort_valid;
  wire       [3:0]    decodeExceptionPort_payload_code;
  wire       [31:0]   decodeExceptionPort_payload_badAddr;
  wire                BranchPlugin_jumpInterface_valid;
  wire       [31:0]   BranchPlugin_jumpInterface_payload;
  wire                BranchPlugin_branchExceptionPort_valid;
  wire       [3:0]    BranchPlugin_branchExceptionPort_payload_code;
  wire       [31:0]   BranchPlugin_branchExceptionPort_payload_badAddr;
  reg                 BranchPlugin_inDebugNoFetchFlag;
  wire       [31:0]   CsrPlugin_csrMapping_readDataSignal;
  wire       [31:0]   CsrPlugin_csrMapping_readDataInit;
  wire       [31:0]   CsrPlugin_csrMapping_writeDataSignal;
  reg                 CsrPlugin_csrMapping_allowCsrSignal;
  wire                CsrPlugin_csrMapping_hazardFree;
  wire                CsrPlugin_csrMapping_doForceFailCsr;
  wire                CsrPlugin_inWfi /* verilator public */ ;
  reg                 CsrPlugin_thirdPartyWake;
  reg                 CsrPlugin_jumpInterface_valid;
  reg        [31:0]   CsrPlugin_jumpInterface_payload;
  wire                CsrPlugin_exceptionPendings_0;
  wire                CsrPlugin_exceptionPendings_1;
  wire                CsrPlugin_exceptionPendings_2;
  wire                CsrPlugin_exceptionPendings_3;
  wire                externalInterrupt;
  wire                contextSwitching;
  reg        [1:0]    CsrPlugin_privilege;
  wire                CsrPlugin_forceMachineWire;
  reg                 CsrPlugin_selfException_valid;
  reg        [3:0]    CsrPlugin_selfException_payload_code;
  wire       [31:0]   CsrPlugin_selfException_payload_badAddr;
  reg                 CsrPlugin_allowInterrupts;
  wire                CsrPlugin_allowException;
  wire                CsrPlugin_allowEbreakException;
  reg                 CsrPlugin_xretAwayFromMachine;
  wire                CsrPlugin_injectionPort_valid;
  reg                 CsrPlugin_injectionPort_ready;
  wire       [31:0]   CsrPlugin_injectionPort_payload;
  wire                debugMode;
  wire                debugBus_halted;
  wire                debugBus_running;
  wire                debugBus_unavailable;
  reg                 debugBus_exception;
  wire                debugBus_commit;
  reg                 debugBus_ebreak;
  wire                debugBus_redo;
  wire                debugBus_regSuccess;
  wire                debugBus_ackReset;
  wire                debugBus_haveReset;
  wire                debugBus_resume_cmd_valid;
  reg                 debugBus_resume_rsp_valid;
  wire                debugBus_haltReq;
  wire                debugBus_dmToHart_valid;
  wire       [1:0]    debugBus_dmToHart_payload_op;
  wire       [4:0]    debugBus_dmToHart_payload_address;
  wire       [31:0]   debugBus_dmToHart_payload_data;
  wire       [2:0]    debugBus_dmToHart_payload_size;
  wire                debugBus_hartToDm_valid;
  wire       [3:0]    debugBus_hartToDm_payload_address;
  wire       [31:0]   debugBus_hartToDm_payload_data;
  wire                IBusCachedPlugin_externalFlush;
  wire                IBusCachedPlugin_jump_pcLoad_valid;
  wire       [31:0]   IBusCachedPlugin_jump_pcLoad_payload;
  wire       [2:0]    _zz_IBusCachedPlugin_jump_pcLoad_payload;
  wire       [2:0]    _zz_IBusCachedPlugin_jump_pcLoad_payload_1;
  wire                _zz_IBusCachedPlugin_jump_pcLoad_payload_2;
  wire                _zz_IBusCachedPlugin_jump_pcLoad_payload_3;
  wire                IBusCachedPlugin_fetchPc_output_valid;
  wire                IBusCachedPlugin_fetchPc_output_ready;
  wire       [31:0]   IBusCachedPlugin_fetchPc_output_payload;
  reg        [31:0]   IBusCachedPlugin_fetchPc_pcReg /* verilator public */ ;
  reg                 IBusCachedPlugin_fetchPc_correction;
  reg                 IBusCachedPlugin_fetchPc_correctionReg;
  wire                IBusCachedPlugin_fetchPc_output_fire;
  wire                IBusCachedPlugin_fetchPc_corrected;
  reg                 IBusCachedPlugin_fetchPc_pcRegPropagate;
  reg                 IBusCachedPlugin_fetchPc_booted;
  reg                 IBusCachedPlugin_fetchPc_inc;
  wire                when_Fetcher_l133;
  wire                when_Fetcher_l133_1;
  reg        [31:0]   IBusCachedPlugin_fetchPc_pc;
  wire                IBusCachedPlugin_fetchPc_redo_valid;
  wire       [31:0]   IBusCachedPlugin_fetchPc_redo_payload;
  reg                 IBusCachedPlugin_fetchPc_flushed;
  wire                when_Fetcher_l160;
  reg                 IBusCachedPlugin_iBusRsp_redoFetch;
  wire                IBusCachedPlugin_iBusRsp_stages_0_input_valid;
  wire                IBusCachedPlugin_iBusRsp_stages_0_input_ready;
  wire       [31:0]   IBusCachedPlugin_iBusRsp_stages_0_input_payload;
  wire                IBusCachedPlugin_iBusRsp_stages_0_output_valid;
  wire                IBusCachedPlugin_iBusRsp_stages_0_output_ready;
  wire       [31:0]   IBusCachedPlugin_iBusRsp_stages_0_output_payload;
  reg                 IBusCachedPlugin_iBusRsp_stages_0_halt;
  wire                IBusCachedPlugin_iBusRsp_stages_1_input_valid;
  wire                IBusCachedPlugin_iBusRsp_stages_1_input_ready;
  wire       [31:0]   IBusCachedPlugin_iBusRsp_stages_1_input_payload;
  wire                IBusCachedPlugin_iBusRsp_stages_1_output_valid;
  wire                IBusCachedPlugin_iBusRsp_stages_1_output_ready;
  wire       [31:0]   IBusCachedPlugin_iBusRsp_stages_1_output_payload;
  reg                 IBusCachedPlugin_iBusRsp_stages_1_halt;
  wire                IBusCachedPlugin_iBusRsp_stages_2_input_valid;
  wire                IBusCachedPlugin_iBusRsp_stages_2_input_ready;
  wire       [31:0]   IBusCachedPlugin_iBusRsp_stages_2_input_payload;
  wire                IBusCachedPlugin_iBusRsp_stages_2_output_valid;
  wire                IBusCachedPlugin_iBusRsp_stages_2_output_ready;
  wire       [31:0]   IBusCachedPlugin_iBusRsp_stages_2_output_payload;
  reg                 IBusCachedPlugin_iBusRsp_stages_2_halt;
  wire                _zz_IBusCachedPlugin_iBusRsp_stages_0_input_ready;
  wire                IBusCachedPlugin_iBusRsp_stages_0_input_haltWhen_valid;
  wire                IBusCachedPlugin_iBusRsp_stages_0_input_haltWhen_ready;
  wire       [31:0]   IBusCachedPlugin_iBusRsp_stages_0_input_haltWhen_payload;
  wire                _zz_IBusCachedPlugin_iBusRsp_stages_1_input_ready;
  wire                IBusCachedPlugin_iBusRsp_stages_1_input_haltWhen_valid;
  wire                IBusCachedPlugin_iBusRsp_stages_1_input_haltWhen_ready;
  wire       [31:0]   IBusCachedPlugin_iBusRsp_stages_1_input_haltWhen_payload;
  wire                _zz_IBusCachedPlugin_iBusRsp_stages_2_input_ready;
  wire                IBusCachedPlugin_iBusRsp_stages_2_input_haltWhen_valid;
  wire                IBusCachedPlugin_iBusRsp_stages_2_input_haltWhen_ready;
  wire       [31:0]   IBusCachedPlugin_iBusRsp_stages_2_input_haltWhen_payload;
  wire                IBusCachedPlugin_iBusRsp_flush;
  wire                IBusCachedPlugin_iBusRsp_stages_0_output_toEvent_valid;
  wire                IBusCachedPlugin_iBusRsp_stages_0_output_toEvent_ready;
  wire                IBusCachedPlugin_iBusRsp_stages_0_output_toEvent_m2sPipe_valid;
  wire                IBusCachedPlugin_iBusRsp_stages_0_output_toEvent_m2sPipe_ready;
  reg                 _zz_IBusCachedPlugin_iBusRsp_stages_0_output_toEvent_m2sPipe_valid;
  wire                IBusCachedPlugin_iBusRsp_stages_1_output_m2sPipe_valid;
  wire                IBusCachedPlugin_iBusRsp_stages_1_output_m2sPipe_ready;
  wire       [31:0]   IBusCachedPlugin_iBusRsp_stages_1_output_m2sPipe_payload;
  reg                 _zz_IBusCachedPlugin_iBusRsp_stages_1_output_m2sPipe_valid;
  reg        [31:0]   _zz_IBusCachedPlugin_iBusRsp_stages_1_output_m2sPipe_payload;
  reg                 IBusCachedPlugin_iBusRsp_readyForError;
  wire                IBusCachedPlugin_iBusRsp_output_valid;
  wire                IBusCachedPlugin_iBusRsp_output_ready;
  wire       [31:0]   IBusCachedPlugin_iBusRsp_output_payload_pc;
  wire                IBusCachedPlugin_iBusRsp_output_payload_rsp_error;
  wire       [31:0]   IBusCachedPlugin_iBusRsp_output_payload_rsp_inst;
  wire                IBusCachedPlugin_iBusRsp_output_payload_isRvc;
  wire                when_Fetcher_l242;
  wire                when_Fetcher_l322;
  reg                 IBusCachedPlugin_injector_nextPcCalc_valids_0;
  wire                when_Fetcher_l331;
  reg                 IBusCachedPlugin_injector_nextPcCalc_valids_1;
  wire                when_Fetcher_l331_1;
  reg                 IBusCachedPlugin_injector_nextPcCalc_valids_2;
  wire                when_Fetcher_l331_2;
  reg                 IBusCachedPlugin_injector_nextPcCalc_valids_3;
  wire                when_Fetcher_l331_3;
  reg                 IBusCachedPlugin_injector_nextPcCalc_valids_4;
  wire                when_Fetcher_l331_4;
  wire                _zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch;
  reg        [18:0]   _zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch_1;
  wire                _zz_2;
  reg        [10:0]   _zz_3;
  wire                _zz_4;
  reg        [18:0]   _zz_5;
  reg                 _zz_6;
  wire                _zz_IBusCachedPlugin_predictionJumpInterface_payload;
  reg        [10:0]   _zz_IBusCachedPlugin_predictionJumpInterface_payload_1;
  wire                _zz_IBusCachedPlugin_predictionJumpInterface_payload_2;
  reg        [18:0]   _zz_IBusCachedPlugin_predictionJumpInterface_payload_3;
  wire                iBus_cmd_valid;
  wire                iBus_cmd_ready;
  reg        [31:0]   iBus_cmd_payload_address;
  wire       [2:0]    iBus_cmd_payload_size;
  wire                iBus_rsp_valid;
  wire       [31:0]   iBus_rsp_payload_data;
  wire                iBus_rsp_payload_error;
  reg        [31:0]   IBusCachedPlugin_rspCounter;
  wire                IBusCachedPlugin_s0_tightlyCoupledHit;
  reg                 IBusCachedPlugin_s1_tightlyCoupledHit;
  reg                 IBusCachedPlugin_s2_tightlyCoupledHit;
  wire                IBusCachedPlugin_rsp_iBusRspOutputHalt;
  wire                IBusCachedPlugin_rsp_issueDetected;
  reg                 IBusCachedPlugin_rsp_redoFetch;
  wire                when_IBusCachedPlugin_l245;
  wire                when_IBusCachedPlugin_l250;
  wire                when_IBusCachedPlugin_l256;
  wire                when_IBusCachedPlugin_l262;
  wire                when_IBusCachedPlugin_l273;
  wire                dBus_cmd_valid;
  wire                dBus_cmd_ready;
  wire                dBus_cmd_payload_wr;
  wire       [3:0]    dBus_cmd_payload_mask;
  wire       [31:0]   dBus_cmd_payload_address;
  wire       [31:0]   dBus_cmd_payload_data;
  wire       [1:0]    dBus_cmd_payload_size;
  wire                dBus_rsp_ready;
  wire                dBus_rsp_error;
  wire       [31:0]   dBus_rsp_data;
  wire                _zz_dBus_cmd_valid;
  reg                 execute_DBusSimplePlugin_skipCmd;
  reg        [31:0]   _zz_dBus_cmd_payload_data;
  wire                when_DBusSimplePlugin_l435;
  reg        [3:0]    _zz_execute_DBusSimplePlugin_formalMask;
  wire       [3:0]    execute_DBusSimplePlugin_formalMask;
  wire                when_DBusSimplePlugin_l490;
  wire                when_DBusSimplePlugin_l497;
  wire                when_DBusSimplePlugin_l523;
  reg        [31:0]   writeBack_DBusSimplePlugin_rspShifted;
  wire       [1:0]    switch_Misc_l245;
  wire                _zz_writeBack_DBusSimplePlugin_rspFormated;
  reg        [31:0]   _zz_writeBack_DBusSimplePlugin_rspFormated_1;
  wire                _zz_writeBack_DBusSimplePlugin_rspFormated_2;
  reg        [31:0]   _zz_writeBack_DBusSimplePlugin_rspFormated_3;
  reg        [31:0]   writeBack_DBusSimplePlugin_rspFormated;
  wire                when_DBusSimplePlugin_l566;
  wire       [30:0]   _zz_decode_IS_DIV;
  wire                _zz_decode_IS_DIV_1;
  wire                _zz_decode_IS_DIV_2;
  wire                _zz_decode_IS_DIV_3;
  wire                _zz_decode_IS_DIV_4;
  wire                _zz_decode_IS_DIV_5;
  wire                _zz_decode_IS_DIV_6;
  wire                _zz_decode_IS_DIV_7;
  wire       [1:0]    _zz_decode_SRC1_CTRL_2;
  wire       [1:0]    _zz_decode_ALU_CTRL_2;
  wire       [1:0]    _zz_decode_SRC2_CTRL_2;
  wire       [1:0]    _zz_decode_ALU_BITWISE_CTRL_2;
  wire       [1:0]    _zz_decode_SHIFT_CTRL_2;
  wire       [1:0]    _zz_decode_BRANCH_CTRL_2;
  wire       [1:0]    _zz_decode_ENV_CTRL_2;
  wire                when_RegFilePlugin_l63;
  wire       [4:0]    decode_RegFilePlugin_regFileReadAddress1;
  wire       [4:0]    decode_RegFilePlugin_regFileReadAddress2;
  wire       [31:0]   decode_RegFilePlugin_rs1Data;
  wire       [31:0]   decode_RegFilePlugin_rs2Data;
  reg                 lastStageRegFileWrite_valid /* verilator public */ ;
  reg        [4:0]    lastStageRegFileWrite_payload_address /* verilator public */ ;
  reg        [31:0]   lastStageRegFileWrite_payload_data /* verilator public */ ;
  reg                 _zz_10;
  reg        [31:0]   execute_IntAluPlugin_bitwise;
  reg        [31:0]   _zz_execute_REGFILE_WRITE_DATA;
  reg        [31:0]   _zz_execute_SRC1;
  wire                _zz_execute_SRC2;
  reg        [19:0]   _zz_execute_SRC2_1;
  wire                _zz_execute_SRC2_2;
  reg        [19:0]   _zz_execute_SRC2_3;
  reg        [31:0]   _zz_execute_SRC2_4;
  reg        [31:0]   execute_SrcPlugin_addSub;
  wire                execute_SrcPlugin_less;
  reg                 execute_LightShifterPlugin_isActive;
  wire                execute_LightShifterPlugin_isShift;
  reg        [4:0]    execute_LightShifterPlugin_amplitudeReg;
  wire       [4:0]    execute_LightShifterPlugin_amplitude;
  wire       [31:0]   execute_LightShifterPlugin_shiftInput;
  wire                execute_LightShifterPlugin_done;
  wire                when_ShiftPlugins_l169;
  reg        [31:0]   _zz_decode_RS2_3;
  wire                when_ShiftPlugins_l175;
  wire                when_ShiftPlugins_l184;
  reg                 HazardSimplePlugin_src0Hazard;
  reg                 HazardSimplePlugin_src1Hazard;
  wire                HazardSimplePlugin_writeBackWrites_valid;
  wire       [4:0]    HazardSimplePlugin_writeBackWrites_payload_address;
  wire       [31:0]   HazardSimplePlugin_writeBackWrites_payload_data;
  reg                 HazardSimplePlugin_writeBackBuffer_valid;
  reg        [4:0]    HazardSimplePlugin_writeBackBuffer_payload_address;
  reg        [31:0]   HazardSimplePlugin_writeBackBuffer_payload_data;
  wire                HazardSimplePlugin_addr0Match;
  wire                HazardSimplePlugin_addr1Match;
  wire                when_HazardSimplePlugin_l47;
  wire                when_HazardSimplePlugin_l48;
  wire                when_HazardSimplePlugin_l51;
  wire                when_HazardSimplePlugin_l45;
  wire                when_HazardSimplePlugin_l57;
  wire                when_HazardSimplePlugin_l58;
  wire                when_HazardSimplePlugin_l48_1;
  wire                when_HazardSimplePlugin_l51_1;
  wire                when_HazardSimplePlugin_l45_1;
  wire                when_HazardSimplePlugin_l57_1;
  wire                when_HazardSimplePlugin_l58_1;
  wire                when_HazardSimplePlugin_l48_2;
  wire                when_HazardSimplePlugin_l51_2;
  wire                when_HazardSimplePlugin_l45_2;
  wire                when_HazardSimplePlugin_l57_2;
  wire                when_HazardSimplePlugin_l58_2;
  wire                when_HazardSimplePlugin_l105;
  wire                when_HazardSimplePlugin_l108;
  wire                when_HazardSimplePlugin_l113;
  wire                execute_BranchPlugin_eq;
  wire       [2:0]    switch_Misc_l245_1;
  reg                 _zz_execute_BRANCH_COND_RESULT;
  reg                 _zz_execute_BRANCH_COND_RESULT_1;
  wire                _zz_execute_BranchPlugin_missAlignedTarget;
  reg        [19:0]   _zz_execute_BranchPlugin_missAlignedTarget_1;
  wire                _zz_execute_BranchPlugin_missAlignedTarget_2;
  reg        [10:0]   _zz_execute_BranchPlugin_missAlignedTarget_3;
  wire                _zz_execute_BranchPlugin_missAlignedTarget_4;
  reg        [18:0]   _zz_execute_BranchPlugin_missAlignedTarget_5;
  reg                 _zz_execute_BranchPlugin_missAlignedTarget_6;
  wire                execute_BranchPlugin_missAlignedTarget;
  reg        [31:0]   execute_BranchPlugin_branch_src1;
  reg        [31:0]   execute_BranchPlugin_branch_src2;
  wire                _zz_execute_BranchPlugin_branch_src2;
  reg        [19:0]   _zz_execute_BranchPlugin_branch_src2_1;
  wire                _zz_execute_BranchPlugin_branch_src2_2;
  reg        [10:0]   _zz_execute_BranchPlugin_branch_src2_3;
  wire                _zz_execute_BranchPlugin_branch_src2_4;
  reg        [18:0]   _zz_execute_BranchPlugin_branch_src2_5;
  wire       [31:0]   execute_BranchPlugin_branchAdder;
  reg                 when_CsrPlugin_l818;
  reg        [1:0]    _zz_CsrPlugin_privilege;
  reg                 CsrPlugin_running;
  wire                when_CsrPlugin_l711;
  reg                 CsrPlugin_reseting;
  reg                 _zz_debugBus_haveReset;
  reg                 CsrPlugin_running_aheadValue_regNext;
  wire                CsrPlugin_enterHalt;
  reg                 CsrPlugin_doHalt;
  wire                when_CsrPlugin_l729;
  wire                CsrPlugin_forceResume;
  reg                 _zz_CsrPlugin_doResume;
  wire                CsrPlugin_doResume;
  reg                 CsrPlugin_timeout_state;
  reg                 CsrPlugin_timeout_stateRise;
  wire                CsrPlugin_timeout_counter_willIncrement;
  reg                 CsrPlugin_timeout_counter_willClear;
  reg        [2:0]    CsrPlugin_timeout_counter_valueNext;
  reg        [2:0]    CsrPlugin_timeout_counter_value;
  wire                CsrPlugin_timeout_counter_willOverflowIfInc;
  wire                CsrPlugin_timeout_counter_willOverflow;
  wire                when_CsrPlugin_l735;
  reg                 _zz_debugBus_hartToDm_valid;
  reg        [31:0]   CsrPlugin_dataCsrw_value_0;
  wire                when_CsrPlugin_l750;
  wire                CsrPlugin_inject_cmd_valid;
  wire       [1:0]    CsrPlugin_inject_cmd_payload_op;
  wire       [4:0]    CsrPlugin_inject_cmd_payload_address;
  wire       [31:0]   CsrPlugin_inject_cmd_payload_data;
  wire       [2:0]    CsrPlugin_inject_cmd_payload_size;
  wire                CsrPlugin_inject_cmd_toStream_valid;
  reg                 CsrPlugin_inject_cmd_toStream_ready;
  wire       [1:0]    CsrPlugin_inject_cmd_toStream_payload_op;
  wire       [4:0]    CsrPlugin_inject_cmd_toStream_payload_address;
  wire       [31:0]   CsrPlugin_inject_cmd_toStream_payload_data;
  wire       [2:0]    CsrPlugin_inject_cmd_toStream_payload_size;
  wire                CsrPlugin_inject_buffer_valid;
  wire                CsrPlugin_inject_buffer_ready;
  wire       [1:0]    CsrPlugin_inject_buffer_payload_op;
  wire       [4:0]    CsrPlugin_inject_buffer_payload_address;
  wire       [31:0]   CsrPlugin_inject_buffer_payload_data;
  wire       [2:0]    CsrPlugin_inject_buffer_payload_size;
  reg                 CsrPlugin_inject_cmd_toStream_rValid;
  reg        [1:0]    CsrPlugin_inject_cmd_toStream_rData_op;
  reg        [4:0]    CsrPlugin_inject_cmd_toStream_rData_address;
  reg        [31:0]   CsrPlugin_inject_cmd_toStream_rData_data;
  reg        [2:0]    CsrPlugin_inject_cmd_toStream_rData_size;
  wire                when_Stream_l477;
  wire                CsrPlugin_injectionPort_fire;
  reg                 CsrPlugin_inject_pending;
  wire                when_CsrPlugin_l786;
  wire                when_CsrPlugin_l786_1;
  reg        [31:0]   CsrPlugin_dpc;
  reg        [1:0]    CsrPlugin_dcsr_prv;
  reg                 CsrPlugin_dcsr_step;
  wire                CsrPlugin_dcsr_nmip;
  wire                CsrPlugin_dcsr_mprven;
  reg        [2:0]    CsrPlugin_dcsr_cause;
  reg                 CsrPlugin_dcsr_stoptime;
  reg                 CsrPlugin_dcsr_stopcount;
  reg                 CsrPlugin_dcsr_stepie;
  reg                 CsrPlugin_dcsr_ebreakm;
  wire       [3:0]    CsrPlugin_dcsr_xdebugver;
  wire                CsrPlugin_dcsr_stepLogic_wantExit;
  reg                 CsrPlugin_dcsr_stepLogic_wantStart;
  wire                CsrPlugin_dcsr_stepLogic_wantKill;
  reg        [1:0]    CsrPlugin_dcsr_stepLogic_stateReg;
  reg        [1:0]    CsrPlugin_dcsr_stepLogic_stateNext;
  wire                when_CsrPlugin_l812;
  wire                when_CsrPlugin_l830;
  wire                CsrPlugin_dcsr_stepLogic_onExit_BOOT;
  wire                CsrPlugin_dcsr_stepLogic_onExit_IDLE;
  wire                CsrPlugin_dcsr_stepLogic_onExit_SINGLE;
  wire                CsrPlugin_dcsr_stepLogic_onExit_WAIT_1;
  wire                CsrPlugin_dcsr_stepLogic_onEntry_BOOT;
  wire                CsrPlugin_dcsr_stepLogic_onEntry_IDLE;
  wire                CsrPlugin_dcsr_stepLogic_onEntry_SINGLE;
  wire                CsrPlugin_dcsr_stepLogic_onEntry_WAIT_1;
  wire                when_CsrPlugin_l862;
  reg        [0:0]    CsrPlugin_trigger_tselect_index;
  wire                CsrPlugin_trigger_tselect_outOfRange;
  reg                 CsrPlugin_trigger_decodeBreak_enabled;
  reg                 CsrPlugin_trigger_decodeBreak_timeout_state;
  reg                 CsrPlugin_trigger_decodeBreak_timeout_stateRise;
  wire                CsrPlugin_trigger_decodeBreak_timeout_counter_willIncrement;
  reg                 CsrPlugin_trigger_decodeBreak_timeout_counter_willClear;
  reg        [1:0]    CsrPlugin_trigger_decodeBreak_timeout_counter_valueNext;
  reg        [1:0]    CsrPlugin_trigger_decodeBreak_timeout_counter_value;
  wire                CsrPlugin_trigger_decodeBreak_timeout_counter_willOverflowIfInc;
  wire                CsrPlugin_trigger_decodeBreak_timeout_counter_willOverflow;
  wire                when_Utils_l694;
  wire                CsrPlugin_trigger_slots_0_selected;
  reg        [31:0]   CsrPlugin_trigger_slots_0_tdata1_read;
  wire       [3:0]    CsrPlugin_trigger_slots_0_tdata1_tpe;
  reg                 CsrPlugin_trigger_slots_0_tdata1_dmode;
  reg                 CsrPlugin_trigger_slots_0_tdata1_execute;
  reg                 CsrPlugin_trigger_slots_0_tdata1_m;
  reg                 CsrPlugin_trigger_slots_0_tdata1_s;
  reg                 CsrPlugin_trigger_slots_0_tdata1_u;
  reg        [3:0]    CsrPlugin_trigger_slots_0_tdata1_action;
  reg                 _zz_CsrPlugin_trigger_slots_0_tdata1_privilegeHit;
  wire                CsrPlugin_trigger_slots_0_tdata1_privilegeHit;
  reg        [31:0]   CsrPlugin_trigger_slots_0_tdata2_value;
  wire                CsrPlugin_trigger_slots_0_tdata2_execute_enabled;
  wire                CsrPlugin_trigger_slots_0_tdata2_execute_hit;
  wire                CsrPlugin_trigger_slots_1_selected;
  reg        [31:0]   CsrPlugin_trigger_slots_1_tdata1_read;
  wire       [3:0]    CsrPlugin_trigger_slots_1_tdata1_tpe;
  reg                 CsrPlugin_trigger_slots_1_tdata1_dmode;
  reg                 CsrPlugin_trigger_slots_1_tdata1_execute;
  reg                 CsrPlugin_trigger_slots_1_tdata1_m;
  reg                 CsrPlugin_trigger_slots_1_tdata1_s;
  reg                 CsrPlugin_trigger_slots_1_tdata1_u;
  reg        [3:0]    CsrPlugin_trigger_slots_1_tdata1_action;
  reg                 _zz_CsrPlugin_trigger_slots_1_tdata1_privilegeHit;
  wire                CsrPlugin_trigger_slots_1_tdata1_privilegeHit;
  reg        [31:0]   CsrPlugin_trigger_slots_1_tdata2_value;
  wire                CsrPlugin_trigger_slots_1_tdata2_execute_enabled;
  wire                CsrPlugin_trigger_slots_1_tdata2_execute_hit;
  wire                when_CsrPlugin_l958;
  wire       [1:0]    CsrPlugin_misa_base;
  wire       [25:0]   CsrPlugin_misa_extensions;
  reg        [1:0]    CsrPlugin_mtvec_mode;
  reg        [29:0]   CsrPlugin_mtvec_base;
  reg        [31:0]   CsrPlugin_mepc;
  reg                 CsrPlugin_mstatus_MIE;
  reg                 CsrPlugin_mstatus_MPIE;
  reg        [1:0]    CsrPlugin_mstatus_MPP;
  reg                 CsrPlugin_mip_MEIP;
  reg                 CsrPlugin_mip_MTIP;
  reg                 CsrPlugin_mip_MSIP;
  reg                 CsrPlugin_mie_MEIE;
  reg                 CsrPlugin_mie_MTIE;
  reg                 CsrPlugin_mie_MSIE;
  reg                 CsrPlugin_mcause_interrupt;
  reg        [3:0]    CsrPlugin_mcause_exceptionCode;
  reg        [31:0]   CsrPlugin_mtval;
  reg        [63:0]   CsrPlugin_mcycle;
  reg        [63:0]   CsrPlugin_minstret;
  wire                _zz_when_CsrPlugin_l1302;
  wire                _zz_when_CsrPlugin_l1302_1;
  wire                _zz_when_CsrPlugin_l1302_2;
  reg                 CsrPlugin_exceptionPortCtrl_exceptionValids_decode;
  reg                 CsrPlugin_exceptionPortCtrl_exceptionValids_execute;
  reg                 CsrPlugin_exceptionPortCtrl_exceptionValids_memory;
  reg                 CsrPlugin_exceptionPortCtrl_exceptionValids_writeBack;
  reg                 CsrPlugin_exceptionPortCtrl_exceptionValidsRegs_decode;
  reg                 CsrPlugin_exceptionPortCtrl_exceptionValidsRegs_execute;
  reg                 CsrPlugin_exceptionPortCtrl_exceptionValidsRegs_memory;
  reg                 CsrPlugin_exceptionPortCtrl_exceptionValidsRegs_writeBack;
  reg        [3:0]    CsrPlugin_exceptionPortCtrl_exceptionContext_code;
  reg        [31:0]   CsrPlugin_exceptionPortCtrl_exceptionContext_badAddr;
  wire       [1:0]    CsrPlugin_exceptionPortCtrl_exceptionTargetPrivilegeUncapped;
  wire       [1:0]    CsrPlugin_exceptionPortCtrl_exceptionTargetPrivilege;
  wire       [1:0]    _zz_CsrPlugin_exceptionPortCtrl_exceptionContext_code;
  wire                _zz_CsrPlugin_exceptionPortCtrl_exceptionContext_code_1;
  wire       [1:0]    _zz_CsrPlugin_exceptionPortCtrl_exceptionContext_code_2;
  wire                _zz_CsrPlugin_exceptionPortCtrl_exceptionContext_code_3;
  wire                when_CsrPlugin_l1259;
  wire                when_CsrPlugin_l1259_1;
  wire                when_CsrPlugin_l1259_2;
  wire                when_CsrPlugin_l1259_3;
  wire                when_CsrPlugin_l1272;
  reg                 CsrPlugin_interrupt_valid;
  reg        [3:0]    CsrPlugin_interrupt_code /* verilator public */ ;
  reg        [1:0]    CsrPlugin_interrupt_targetPrivilege;
  wire                when_CsrPlugin_l1296;
  wire                when_CsrPlugin_l1302;
  wire                when_CsrPlugin_l1302_1;
  wire                when_CsrPlugin_l1302_2;
  wire                when_CsrPlugin_l1315;
  wire                CsrPlugin_exception;
  wire                CsrPlugin_lastStageWasWfi;
  reg                 CsrPlugin_pipelineLiberator_pcValids_0;
  reg                 CsrPlugin_pipelineLiberator_pcValids_1;
  reg                 CsrPlugin_pipelineLiberator_pcValids_2;
  wire                CsrPlugin_pipelineLiberator_active;
  wire                when_CsrPlugin_l1335;
  wire                when_CsrPlugin_l1335_1;
  wire                when_CsrPlugin_l1335_2;
  wire                when_CsrPlugin_l1340;
  reg                 CsrPlugin_pipelineLiberator_done;
  wire                when_CsrPlugin_l1346;
  wire                CsrPlugin_interruptJump /* verilator public */ ;
  reg                 CsrPlugin_hadException /* verilator public */ ;
  reg        [1:0]    CsrPlugin_targetPrivilege;
  reg        [3:0]    CsrPlugin_trapCause;
  reg                 CsrPlugin_trapCauseEbreakDebug;
  wire                when_CsrPlugin_l1373;
  wire                when_CsrPlugin_l1375;
  reg        [1:0]    CsrPlugin_xtvec_mode;
  reg        [29:0]   CsrPlugin_xtvec_base;
  reg                 CsrPlugin_trapEnterDebug;
  wire                when_CsrPlugin_l1389;
  wire                when_CsrPlugin_l1390;
  wire                when_CsrPlugin_l1398;
  wire                when_CsrPlugin_l1428;
  wire                when_CsrPlugin_l1456;
  wire       [1:0]    switch_CsrPlugin_l1460;
  wire                when_CsrPlugin_l1468;
  reg                 execute_CsrPlugin_wfiWake;
  wire                when_CsrPlugin_l1527;
  wire                execute_CsrPlugin_blockedBySideEffects;
  reg                 execute_CsrPlugin_illegalAccess;
  reg                 execute_CsrPlugin_illegalInstruction;
  wire                when_CsrPlugin_l1547;
  wire                when_CsrPlugin_l1548;
  wire                when_CsrPlugin_l1555;
  wire                when_CsrPlugin_l1565;
  reg                 execute_CsrPlugin_writeInstruction;
  reg                 execute_CsrPlugin_readInstruction;
  wire                execute_CsrPlugin_writeEnable;
  wire                execute_CsrPlugin_readEnable;
  wire       [31:0]   execute_CsrPlugin_readToWriteData;
  wire                switch_Misc_l245_2;
  reg        [31:0]   _zz_CsrPlugin_csrMapping_writeDataSignal;
  wire                when_CsrPlugin_l1587;
  wire                when_CsrPlugin_l1591;
  wire       [11:0]   execute_CsrPlugin_csrAddress;
  reg        [32:0]   memory_MulDivIterativePlugin_rs1;
  reg        [31:0]   memory_MulDivIterativePlugin_rs2;
  reg        [64:0]   memory_MulDivIterativePlugin_accumulator;
  wire                memory_MulDivIterativePlugin_frontendOk;
  reg                 memory_MulDivIterativePlugin_mul_counter_willIncrement;
  reg                 memory_MulDivIterativePlugin_mul_counter_willClear;
  reg        [5:0]    memory_MulDivIterativePlugin_mul_counter_valueNext;
  reg        [5:0]    memory_MulDivIterativePlugin_mul_counter_value;
  wire                memory_MulDivIterativePlugin_mul_counter_willOverflowIfInc;
  wire                memory_MulDivIterativePlugin_mul_counter_willOverflow;
  wire                when_MulDivIterativePlugin_l96;
  wire                when_MulDivIterativePlugin_l97;
  wire                when_MulDivIterativePlugin_l100;
  wire                when_MulDivIterativePlugin_l110;
  reg                 memory_MulDivIterativePlugin_div_needRevert;
  reg                 memory_MulDivIterativePlugin_div_counter_willIncrement;
  reg                 memory_MulDivIterativePlugin_div_counter_willClear;
  reg        [5:0]    memory_MulDivIterativePlugin_div_counter_valueNext;
  reg        [5:0]    memory_MulDivIterativePlugin_div_counter_value;
  wire                memory_MulDivIterativePlugin_div_counter_willOverflowIfInc;
  wire                memory_MulDivIterativePlugin_div_counter_willOverflow;
  reg                 memory_MulDivIterativePlugin_div_done;
  wire                when_MulDivIterativePlugin_l126;
  wire                when_MulDivIterativePlugin_l126_1;
  reg        [31:0]   memory_MulDivIterativePlugin_div_result;
  wire                when_MulDivIterativePlugin_l128;
  wire                when_MulDivIterativePlugin_l129;
  wire                when_MulDivIterativePlugin_l132;
  wire       [31:0]   _zz_memory_MulDivIterativePlugin_div_stage_0_remainderShifted;
  wire       [32:0]   memory_MulDivIterativePlugin_div_stage_0_remainderShifted;
  wire       [32:0]   memory_MulDivIterativePlugin_div_stage_0_remainderMinusDenominator;
  wire       [31:0]   memory_MulDivIterativePlugin_div_stage_0_outRemainder;
  wire       [31:0]   memory_MulDivIterativePlugin_div_stage_0_outNumerator;
  wire                when_MulDivIterativePlugin_l151;
  wire       [31:0]   _zz_memory_MulDivIterativePlugin_div_result;
  wire                when_MulDivIterativePlugin_l162;
  wire                _zz_memory_MulDivIterativePlugin_rs2;
  wire                _zz_memory_MulDivIterativePlugin_rs1;
  reg        [32:0]   _zz_memory_MulDivIterativePlugin_rs1_1;
  reg        [31:0]   externalInterruptArray_regNext;
  reg        [31:0]   _zz_CsrPlugin_csrMapping_readDataInit;
  wire       [31:0]   _zz_externalInterrupt;
  reg                 io_harts_0_dmToHart_regNext_valid;
  reg        [1:0]    io_harts_0_dmToHart_regNext_payload_op;
  reg        [4:0]    io_harts_0_dmToHart_regNext_payload_address;
  reg        [31:0]   io_harts_0_dmToHart_regNext_payload_data;
  reg        [2:0]    io_harts_0_dmToHart_regNext_payload_size;
  wire                when_Pipeline_l124;
  reg        [31:0]   decode_to_execute_PC;
  wire                when_Pipeline_l124_1;
  reg        [31:0]   execute_to_memory_PC;
  wire                when_Pipeline_l124_2;
  reg        [31:0]   memory_to_writeBack_PC;
  wire                when_Pipeline_l124_3;
  reg        [31:0]   decode_to_execute_INSTRUCTION;
  wire                when_Pipeline_l124_4;
  reg        [31:0]   execute_to_memory_INSTRUCTION;
  wire                when_Pipeline_l124_5;
  reg        [31:0]   memory_to_writeBack_INSTRUCTION;
  wire                when_Pipeline_l124_6;
  reg        [31:0]   decode_to_execute_FORMAL_PC_NEXT;
  wire                when_Pipeline_l124_7;
  reg        [31:0]   execute_to_memory_FORMAL_PC_NEXT;
  wire                when_Pipeline_l124_8;
  reg        [31:0]   memory_to_writeBack_FORMAL_PC_NEXT;
  wire                when_Pipeline_l124_9;
  reg        [1:0]    decode_to_execute_SRC1_CTRL;
  wire                when_Pipeline_l124_10;
  reg                 decode_to_execute_SRC_USE_SUB_LESS;
  wire                when_Pipeline_l124_11;
  reg                 decode_to_execute_MEMORY_ENABLE;
  wire                when_Pipeline_l124_12;
  reg                 execute_to_memory_MEMORY_ENABLE;
  wire                when_Pipeline_l124_13;
  reg                 memory_to_writeBack_MEMORY_ENABLE;
  wire                when_Pipeline_l124_14;
  reg        [1:0]    decode_to_execute_ALU_CTRL;
  wire                when_Pipeline_l124_15;
  reg        [1:0]    decode_to_execute_SRC2_CTRL;
  wire                when_Pipeline_l124_16;
  reg                 decode_to_execute_REGFILE_WRITE_VALID;
  wire                when_Pipeline_l124_17;
  reg                 execute_to_memory_REGFILE_WRITE_VALID;
  wire                when_Pipeline_l124_18;
  reg                 memory_to_writeBack_REGFILE_WRITE_VALID;
  wire                when_Pipeline_l124_19;
  reg                 decode_to_execute_BYPASSABLE_EXECUTE_STAGE;
  wire                when_Pipeline_l124_20;
  reg                 decode_to_execute_BYPASSABLE_MEMORY_STAGE;
  wire                when_Pipeline_l124_21;
  reg                 execute_to_memory_BYPASSABLE_MEMORY_STAGE;
  wire                when_Pipeline_l124_22;
  reg                 decode_to_execute_MEMORY_STORE;
  wire                when_Pipeline_l124_23;
  reg                 execute_to_memory_MEMORY_STORE;
  wire                when_Pipeline_l124_24;
  reg                 decode_to_execute_SRC_LESS_UNSIGNED;
  wire                when_Pipeline_l124_25;
  reg        [1:0]    decode_to_execute_ALU_BITWISE_CTRL;
  wire                when_Pipeline_l124_26;
  reg        [1:0]    decode_to_execute_SHIFT_CTRL;
  wire                when_Pipeline_l124_27;
  reg        [1:0]    decode_to_execute_BRANCH_CTRL;
  wire                when_Pipeline_l124_28;
  reg                 decode_to_execute_IS_CSR;
  wire                when_Pipeline_l124_29;
  reg        [1:0]    decode_to_execute_ENV_CTRL;
  wire                when_Pipeline_l124_30;
  reg        [1:0]    execute_to_memory_ENV_CTRL;
  wire                when_Pipeline_l124_31;
  reg        [1:0]    memory_to_writeBack_ENV_CTRL;
  wire                when_Pipeline_l124_32;
  reg                 decode_to_execute_IS_MUL;
  wire                when_Pipeline_l124_33;
  reg                 execute_to_memory_IS_MUL;
  wire                when_Pipeline_l124_34;
  reg                 decode_to_execute_IS_RS1_SIGNED;
  wire                when_Pipeline_l124_35;
  reg                 decode_to_execute_IS_RS2_SIGNED;
  wire                when_Pipeline_l124_36;
  reg                 decode_to_execute_IS_DIV;
  wire                when_Pipeline_l124_37;
  reg                 execute_to_memory_IS_DIV;
  wire                when_Pipeline_l124_38;
  reg        [31:0]   decode_to_execute_RS1;
  wire                when_Pipeline_l124_39;
  reg        [31:0]   decode_to_execute_RS2;
  wire                when_Pipeline_l124_40;
  reg                 decode_to_execute_SRC2_FORCE_ZERO;
  wire                when_Pipeline_l124_41;
  reg                 decode_to_execute_PREDICTION_HAD_BRANCHED1;
  wire                when_Pipeline_l124_42;
  reg                 decode_to_execute_CSR_WRITE_OPCODE;
  wire                when_Pipeline_l124_43;
  reg                 decode_to_execute_CSR_READ_OPCODE;
  wire                when_Pipeline_l124_44;
  reg                 execute_to_memory_ALIGNEMENT_FAULT;
  wire                when_Pipeline_l124_45;
  reg        [1:0]    execute_to_memory_MEMORY_ADDRESS_LOW;
  wire                when_Pipeline_l124_46;
  reg        [1:0]    memory_to_writeBack_MEMORY_ADDRESS_LOW;
  wire                when_Pipeline_l124_47;
  reg        [31:0]   execute_to_memory_REGFILE_WRITE_DATA;
  wire                when_Pipeline_l124_48;
  reg        [31:0]   memory_to_writeBack_REGFILE_WRITE_DATA;
  wire                when_Pipeline_l124_49;
  reg                 execute_to_memory_BRANCH_DO;
  wire                when_Pipeline_l124_50;
  reg        [31:0]   execute_to_memory_BRANCH_CALC;
  wire                when_Pipeline_l124_51;
  reg        [31:0]   memory_to_writeBack_MEMORY_READ_DATA;
  wire                when_Pipeline_l151;
  wire                when_Pipeline_l154;
  wire                when_Pipeline_l151_1;
  wire                when_Pipeline_l154_1;
  wire                when_Pipeline_l151_2;
  wire                when_Pipeline_l154_2;
  reg        [2:0]    IBusCachedPlugin_injector_port_state;
  wire                when_Fetcher_l391;
  wire                when_CsrPlugin_l1669;
  reg                 execute_CsrPlugin_csr_1972;
  wire                when_CsrPlugin_l1669_1;
  reg                 execute_CsrPlugin_csr_1969;
  wire                when_CsrPlugin_l1669_2;
  reg                 execute_CsrPlugin_csr_1968;
  wire                when_CsrPlugin_l1669_3;
  reg                 execute_CsrPlugin_csr_1952;
  wire                when_CsrPlugin_l1669_4;
  reg                 execute_CsrPlugin_csr_1956;
  wire                when_CsrPlugin_l1669_5;
  reg                 execute_CsrPlugin_csr_1953;
  wire                when_CsrPlugin_l1669_6;
  reg                 execute_CsrPlugin_csr_1954;
  wire                when_CsrPlugin_l1669_7;
  reg                 execute_CsrPlugin_csr_768;
  wire                when_CsrPlugin_l1669_8;
  reg                 execute_CsrPlugin_csr_836;
  wire                when_CsrPlugin_l1669_9;
  reg                 execute_CsrPlugin_csr_772;
  wire                when_CsrPlugin_l1669_10;
  reg                 execute_CsrPlugin_csr_773;
  wire                when_CsrPlugin_l1669_11;
  reg                 execute_CsrPlugin_csr_833;
  wire                when_CsrPlugin_l1669_12;
  reg                 execute_CsrPlugin_csr_834;
  wire                when_CsrPlugin_l1669_13;
  reg                 execute_CsrPlugin_csr_835;
  wire                when_CsrPlugin_l1669_14;
  reg                 execute_CsrPlugin_csr_3008;
  wire                when_CsrPlugin_l1669_15;
  reg                 execute_CsrPlugin_csr_4032;
  reg        [31:0]   _zz_CsrPlugin_csrMapping_readDataInit_1;
  reg        [31:0]   _zz_CsrPlugin_csrMapping_readDataInit_2;
  reg        [31:0]   _zz_CsrPlugin_csrMapping_readDataInit_3;
  reg        [31:0]   _zz_CsrPlugin_csrMapping_readDataInit_4;
  reg        [31:0]   _zz_CsrPlugin_csrMapping_readDataInit_5;
  reg        [31:0]   _zz_CsrPlugin_csrMapping_readDataInit_6;
  wire       [1:0]    switch_CsrPlugin_l1031;
  reg        [31:0]   _zz_CsrPlugin_csrMapping_readDataInit_7;
  reg        [31:0]   _zz_CsrPlugin_csrMapping_readDataInit_8;
  reg        [31:0]   _zz_CsrPlugin_csrMapping_readDataInit_9;
  reg        [31:0]   _zz_CsrPlugin_csrMapping_readDataInit_10;
  reg        [31:0]   _zz_CsrPlugin_csrMapping_readDataInit_11;
  reg        [31:0]   _zz_CsrPlugin_csrMapping_readDataInit_12;
  reg        [31:0]   _zz_CsrPlugin_csrMapping_readDataInit_13;
  reg        [31:0]   _zz_CsrPlugin_csrMapping_readDataInit_14;
  wire                when_CsrPlugin_l1702;
  wire       [11:0]   _zz_when_CsrPlugin_l1709;
  wire                when_CsrPlugin_l1709;
  reg                 when_CsrPlugin_l1719;
  wire                when_CsrPlugin_l1717;
  wire                when_CsrPlugin_l1718;
  wire                when_CsrPlugin_l1725;
  reg        [2:0]    _zz_iBusWishbone_ADR;
  wire                when_InstructionCache_l240;
  wire                when_InstructionCache_l243;
  reg                 _zz_iBus_rsp_valid;
  reg        [31:0]   iBusWishbone_DAT_MISO_regNext;
  reg                 iBusWishbone_ERR_regNext;
  wire                dBus_cmd_halfPipe_valid;
  wire                dBus_cmd_halfPipe_ready;
  wire                dBus_cmd_halfPipe_payload_wr;
  wire       [3:0]    dBus_cmd_halfPipe_payload_mask;
  wire       [31:0]   dBus_cmd_halfPipe_payload_address;
  wire       [31:0]   dBus_cmd_halfPipe_payload_data;
  wire       [1:0]    dBus_cmd_halfPipe_payload_size;
  reg                 dBus_cmd_rValid;
  wire                dBus_cmd_halfPipe_fire;
  reg                 dBus_cmd_rData_wr;
  reg        [3:0]    dBus_cmd_rData_mask;
  reg        [31:0]   dBus_cmd_rData_address;
  reg        [31:0]   dBus_cmd_rData_data;
  reg        [1:0]    dBus_cmd_rData_size;
  reg        [3:0]    _zz_dBusWishbone_SEL;
  `ifndef SYNTHESIS
  reg [47:0] _zz_memory_to_writeBack_ENV_CTRL_string;
  reg [47:0] _zz_memory_to_writeBack_ENV_CTRL_1_string;
  reg [47:0] _zz_execute_to_memory_ENV_CTRL_string;
  reg [47:0] _zz_execute_to_memory_ENV_CTRL_1_string;
  reg [47:0] decode_ENV_CTRL_string;
  reg [47:0] _zz_decode_ENV_CTRL_string;
  reg [47:0] _zz_decode_to_execute_ENV_CTRL_string;
  reg [47:0] _zz_decode_to_execute_ENV_CTRL_1_string;
  reg [31:0] _zz_decode_to_execute_BRANCH_CTRL_string;
  reg [31:0] _zz_decode_to_execute_BRANCH_CTRL_1_string;
  reg [71:0] decode_SHIFT_CTRL_string;
  reg [71:0] _zz_decode_SHIFT_CTRL_string;
  reg [71:0] _zz_decode_to_execute_SHIFT_CTRL_string;
  reg [71:0] _zz_decode_to_execute_SHIFT_CTRL_1_string;
  reg [39:0] decode_ALU_BITWISE_CTRL_string;
  reg [39:0] _zz_decode_ALU_BITWISE_CTRL_string;
  reg [39:0] _zz_decode_to_execute_ALU_BITWISE_CTRL_string;
  reg [39:0] _zz_decode_to_execute_ALU_BITWISE_CTRL_1_string;
  reg [23:0] decode_SRC2_CTRL_string;
  reg [23:0] _zz_decode_SRC2_CTRL_string;
  reg [23:0] _zz_decode_to_execute_SRC2_CTRL_string;
  reg [23:0] _zz_decode_to_execute_SRC2_CTRL_1_string;
  reg [63:0] decode_ALU_CTRL_string;
  reg [63:0] _zz_decode_ALU_CTRL_string;
  reg [63:0] _zz_decode_to_execute_ALU_CTRL_string;
  reg [63:0] _zz_decode_to_execute_ALU_CTRL_1_string;
  reg [95:0] decode_SRC1_CTRL_string;
  reg [95:0] _zz_decode_SRC1_CTRL_string;
  reg [95:0] _zz_decode_to_execute_SRC1_CTRL_string;
  reg [95:0] _zz_decode_to_execute_SRC1_CTRL_1_string;
  reg [47:0] memory_ENV_CTRL_string;
  reg [47:0] _zz_memory_ENV_CTRL_string;
  reg [47:0] execute_ENV_CTRL_string;
  reg [47:0] _zz_execute_ENV_CTRL_string;
  reg [47:0] writeBack_ENV_CTRL_string;
  reg [47:0] _zz_writeBack_ENV_CTRL_string;
  reg [31:0] execute_BRANCH_CTRL_string;
  reg [31:0] _zz_execute_BRANCH_CTRL_string;
  reg [71:0] execute_SHIFT_CTRL_string;
  reg [71:0] _zz_execute_SHIFT_CTRL_string;
  reg [23:0] execute_SRC2_CTRL_string;
  reg [23:0] _zz_execute_SRC2_CTRL_string;
  reg [95:0] execute_SRC1_CTRL_string;
  reg [95:0] _zz_execute_SRC1_CTRL_string;
  reg [63:0] execute_ALU_CTRL_string;
  reg [63:0] _zz_execute_ALU_CTRL_string;
  reg [39:0] execute_ALU_BITWISE_CTRL_string;
  reg [39:0] _zz_execute_ALU_BITWISE_CTRL_string;
  reg [47:0] _zz_decode_ENV_CTRL_1_string;
  reg [31:0] _zz_decode_BRANCH_CTRL_string;
  reg [71:0] _zz_decode_SHIFT_CTRL_1_string;
  reg [39:0] _zz_decode_ALU_BITWISE_CTRL_1_string;
  reg [23:0] _zz_decode_SRC2_CTRL_1_string;
  reg [63:0] _zz_decode_ALU_CTRL_1_string;
  reg [95:0] _zz_decode_SRC1_CTRL_1_string;
  reg [31:0] decode_BRANCH_CTRL_string;
  reg [31:0] _zz_decode_BRANCH_CTRL_1_string;
  reg [71:0] debugBus_dmToHart_payload_op_string;
  reg [95:0] _zz_decode_SRC1_CTRL_2_string;
  reg [63:0] _zz_decode_ALU_CTRL_2_string;
  reg [23:0] _zz_decode_SRC2_CTRL_2_string;
  reg [39:0] _zz_decode_ALU_BITWISE_CTRL_2_string;
  reg [71:0] _zz_decode_SHIFT_CTRL_2_string;
  reg [31:0] _zz_decode_BRANCH_CTRL_2_string;
  reg [47:0] _zz_decode_ENV_CTRL_2_string;
  reg [71:0] CsrPlugin_inject_cmd_payload_op_string;
  reg [71:0] CsrPlugin_inject_cmd_toStream_payload_op_string;
  reg [71:0] CsrPlugin_inject_buffer_payload_op_string;
  reg [71:0] CsrPlugin_inject_cmd_toStream_rData_op_string;
  reg [47:0] CsrPlugin_dcsr_stepLogic_stateReg_string;
  reg [47:0] CsrPlugin_dcsr_stepLogic_stateNext_string;
  reg [71:0] io_harts_0_dmToHart_regNext_payload_op_string;
  reg [95:0] decode_to_execute_SRC1_CTRL_string;
  reg [63:0] decode_to_execute_ALU_CTRL_string;
  reg [23:0] decode_to_execute_SRC2_CTRL_string;
  reg [39:0] decode_to_execute_ALU_BITWISE_CTRL_string;
  reg [71:0] decode_to_execute_SHIFT_CTRL_string;
  reg [31:0] decode_to_execute_BRANCH_CTRL_string;
  reg [47:0] decode_to_execute_ENV_CTRL_string;
  reg [47:0] execute_to_memory_ENV_CTRL_string;
  reg [47:0] memory_to_writeBack_ENV_CTRL_string;
  `endif

  reg [31:0] RegFilePlugin_regFile [0:31] /* verilator public */ ;

  assign _zz_when_1 = (|{decodeExceptionPort_valid,IBusCachedPlugin_decodeExceptionPort_valid});
  assign _zz_when_2 = (|{BranchPlugin_branchExceptionPort_valid,DBusSimplePlugin_memoryExceptionPort_valid});
  assign _zz__zz_IBusCachedPlugin_jump_pcLoad_payload_1 = (_zz_IBusCachedPlugin_jump_pcLoad_payload - 3'b001);
  assign _zz_IBusCachedPlugin_fetchPc_pc_1 = {IBusCachedPlugin_fetchPc_inc,2'b00};
  assign _zz_IBusCachedPlugin_fetchPc_pc = {29'd0, _zz_IBusCachedPlugin_fetchPc_pc_1};
  assign _zz__zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch = {{{decode_INSTRUCTION[31],decode_INSTRUCTION[7]},decode_INSTRUCTION[30 : 25]},decode_INSTRUCTION[11 : 8]};
  assign _zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch_2 = {{_zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch_1,{{{decode_INSTRUCTION[31],decode_INSTRUCTION[7]},decode_INSTRUCTION[30 : 25]},decode_INSTRUCTION[11 : 8]}},1'b0};
  assign _zz__zz_2 = {{{decode_INSTRUCTION[31],decode_INSTRUCTION[19 : 12]},decode_INSTRUCTION[20]},decode_INSTRUCTION[30 : 21]};
  assign _zz__zz_4 = {{{decode_INSTRUCTION[31],decode_INSTRUCTION[7]},decode_INSTRUCTION[30 : 25]},decode_INSTRUCTION[11 : 8]};
  assign _zz__zz_6 = {{_zz_3,{{{decode_INSTRUCTION[31],decode_INSTRUCTION[19 : 12]},decode_INSTRUCTION[20]},decode_INSTRUCTION[30 : 21]}},1'b0};
  assign _zz__zz_6_1 = {{_zz_5,{{{decode_INSTRUCTION[31],decode_INSTRUCTION[7]},decode_INSTRUCTION[30 : 25]},decode_INSTRUCTION[11 : 8]}},1'b0};
  assign _zz__zz_IBusCachedPlugin_predictionJumpInterface_payload = {{{decode_INSTRUCTION[31],decode_INSTRUCTION[19 : 12]},decode_INSTRUCTION[20]},decode_INSTRUCTION[30 : 21]};
  assign _zz__zz_IBusCachedPlugin_predictionJumpInterface_payload_2 = {{{decode_INSTRUCTION[31],decode_INSTRUCTION[7]},decode_INSTRUCTION[30 : 25]},decode_INSTRUCTION[11 : 8]};
  assign _zz_DBusSimplePlugin_memoryExceptionPort_payload_code = (memory_MEMORY_STORE ? 3'b110 : 3'b100);
  assign _zz__zz_execute_REGFILE_WRITE_DATA = execute_SRC_LESS;
  assign _zz__zz_execute_SRC1 = 3'b100;
  assign _zz__zz_execute_SRC1_1 = execute_INSTRUCTION[19 : 15];
  assign _zz__zz_execute_SRC2_2 = {execute_INSTRUCTION[31 : 25],execute_INSTRUCTION[11 : 7]};
  assign _zz_execute_SrcPlugin_addSub = ($signed(_zz_execute_SrcPlugin_addSub_1) + $signed(_zz_execute_SrcPlugin_addSub_4));
  assign _zz_execute_SrcPlugin_addSub_1 = ($signed(_zz_execute_SrcPlugin_addSub_2) + $signed(_zz_execute_SrcPlugin_addSub_3));
  assign _zz_execute_SrcPlugin_addSub_2 = execute_SRC1;
  assign _zz_execute_SrcPlugin_addSub_3 = (execute_SRC_USE_SUB_LESS ? (~ execute_SRC2) : execute_SRC2);
  assign _zz_execute_SrcPlugin_addSub_4 = (execute_SRC_USE_SUB_LESS ? 32'h00000001 : 32'h0);
  assign _zz__zz_decode_RS2_3 = (_zz__zz_decode_RS2_3_1 >>> 1'd1);
  assign _zz__zz_decode_RS2_3_1 = {((execute_SHIFT_CTRL == ShiftCtrlEnum_SRA_1) && execute_LightShifterPlugin_shiftInput[31]),execute_LightShifterPlugin_shiftInput};
  assign _zz__zz_execute_BranchPlugin_missAlignedTarget_2 = {{{execute_INSTRUCTION[31],execute_INSTRUCTION[19 : 12]},execute_INSTRUCTION[20]},execute_INSTRUCTION[30 : 21]};
  assign _zz__zz_execute_BranchPlugin_missAlignedTarget_4 = {{{execute_INSTRUCTION[31],execute_INSTRUCTION[7]},execute_INSTRUCTION[30 : 25]},execute_INSTRUCTION[11 : 8]};
  assign _zz__zz_execute_BranchPlugin_missAlignedTarget_6 = {_zz_execute_BranchPlugin_missAlignedTarget_1,execute_INSTRUCTION[31 : 20]};
  assign _zz__zz_execute_BranchPlugin_missAlignedTarget_6_1 = {{_zz_execute_BranchPlugin_missAlignedTarget_3,{{{execute_INSTRUCTION[31],execute_INSTRUCTION[19 : 12]},execute_INSTRUCTION[20]},execute_INSTRUCTION[30 : 21]}},1'b0};
  assign _zz__zz_execute_BranchPlugin_missAlignedTarget_6_2 = {{_zz_execute_BranchPlugin_missAlignedTarget_5,{{{execute_INSTRUCTION[31],execute_INSTRUCTION[7]},execute_INSTRUCTION[30 : 25]},execute_INSTRUCTION[11 : 8]}},1'b0};
  assign _zz__zz_execute_BranchPlugin_branch_src2_2 = {{{execute_INSTRUCTION[31],execute_INSTRUCTION[19 : 12]},execute_INSTRUCTION[20]},execute_INSTRUCTION[30 : 21]};
  assign _zz__zz_execute_BranchPlugin_branch_src2_4 = {{{execute_INSTRUCTION[31],execute_INSTRUCTION[7]},execute_INSTRUCTION[30 : 25]},execute_INSTRUCTION[11 : 8]};
  assign _zz_execute_BranchPlugin_branch_src2_11 = 3'b100;
  assign _zz_CsrPlugin_timeout_counter_valueNext_1 = CsrPlugin_timeout_counter_willIncrement;
  assign _zz_CsrPlugin_timeout_counter_valueNext = {2'd0, _zz_CsrPlugin_timeout_counter_valueNext_1};
  assign _zz_when = 1'b1;
  assign _zz_CsrPlugin_trigger_decodeBreak_timeout_counter_valueNext_1 = CsrPlugin_trigger_decodeBreak_timeout_counter_willIncrement;
  assign _zz_CsrPlugin_trigger_decodeBreak_timeout_counter_valueNext = {1'd0, _zz_CsrPlugin_trigger_decodeBreak_timeout_counter_valueNext_1};
  assign _zz_CsrPlugin_mcycle_1 = ((! debugMode) || (! CsrPlugin_dcsr_stopcount));
  assign _zz_CsrPlugin_mcycle = {63'd0, _zz_CsrPlugin_mcycle_1};
  assign _zz__zz_CsrPlugin_exceptionPortCtrl_exceptionContext_code_1 = (_zz_CsrPlugin_exceptionPortCtrl_exceptionContext_code & (~ _zz__zz_CsrPlugin_exceptionPortCtrl_exceptionContext_code_1_1));
  assign _zz__zz_CsrPlugin_exceptionPortCtrl_exceptionContext_code_1_1 = (_zz_CsrPlugin_exceptionPortCtrl_exceptionContext_code - 2'b01);
  assign _zz__zz_CsrPlugin_exceptionPortCtrl_exceptionContext_code_3 = (_zz_CsrPlugin_exceptionPortCtrl_exceptionContext_code_2 & (~ _zz__zz_CsrPlugin_exceptionPortCtrl_exceptionContext_code_3_1));
  assign _zz__zz_CsrPlugin_exceptionPortCtrl_exceptionContext_code_3_1 = (_zz_CsrPlugin_exceptionPortCtrl_exceptionContext_code_2 - 2'b01);
  assign _zz_memory_MulDivIterativePlugin_mul_counter_valueNext_1 = memory_MulDivIterativePlugin_mul_counter_willIncrement;
  assign _zz_memory_MulDivIterativePlugin_mul_counter_valueNext = {5'd0, _zz_memory_MulDivIterativePlugin_mul_counter_valueNext_1};
  assign _zz_memory_MulDivIterativePlugin_accumulator = (_zz_memory_MulDivIterativePlugin_accumulator_1 + _zz_memory_MulDivIterativePlugin_accumulator_3);
  assign _zz_memory_MulDivIterativePlugin_accumulator_2 = (memory_MulDivIterativePlugin_rs2[0] ? memory_MulDivIterativePlugin_rs1 : 33'h0);
  assign _zz_memory_MulDivIterativePlugin_accumulator_1 = {{1{_zz_memory_MulDivIterativePlugin_accumulator_2[32]}}, _zz_memory_MulDivIterativePlugin_accumulator_2};
  assign _zz_memory_MulDivIterativePlugin_accumulator_4 = _zz_memory_MulDivIterativePlugin_accumulator_5;
  assign _zz_memory_MulDivIterativePlugin_accumulator_3 = {{1{_zz_memory_MulDivIterativePlugin_accumulator_4[32]}}, _zz_memory_MulDivIterativePlugin_accumulator_4};
  assign _zz_memory_MulDivIterativePlugin_accumulator_5 = (memory_MulDivIterativePlugin_accumulator >>> 6'd32);
  assign _zz_memory_MulDivIterativePlugin_div_counter_valueNext_1 = memory_MulDivIterativePlugin_div_counter_willIncrement;
  assign _zz_memory_MulDivIterativePlugin_div_counter_valueNext = {5'd0, _zz_memory_MulDivIterativePlugin_div_counter_valueNext_1};
  assign _zz_memory_MulDivIterativePlugin_div_stage_0_remainderMinusDenominator = {1'd0, memory_MulDivIterativePlugin_rs2};
  assign _zz_memory_MulDivIterativePlugin_div_stage_0_outRemainder = memory_MulDivIterativePlugin_div_stage_0_remainderMinusDenominator[31:0];
  assign _zz_memory_MulDivIterativePlugin_div_stage_0_outRemainder_1 = memory_MulDivIterativePlugin_div_stage_0_remainderShifted[31:0];
  assign _zz_memory_MulDivIterativePlugin_div_stage_0_outNumerator = {_zz_memory_MulDivIterativePlugin_div_stage_0_remainderShifted,(! memory_MulDivIterativePlugin_div_stage_0_remainderMinusDenominator[32])};
  assign _zz_memory_MulDivIterativePlugin_div_result_1 = _zz_memory_MulDivIterativePlugin_div_result_2;
  assign _zz_memory_MulDivIterativePlugin_div_result_2 = _zz_memory_MulDivIterativePlugin_div_result_3;
  assign _zz_memory_MulDivIterativePlugin_div_result_3 = ({memory_MulDivIterativePlugin_div_needRevert,(memory_MulDivIterativePlugin_div_needRevert ? (~ _zz_memory_MulDivIterativePlugin_div_result) : _zz_memory_MulDivIterativePlugin_div_result)} + _zz_memory_MulDivIterativePlugin_div_result_4);
  assign _zz_memory_MulDivIterativePlugin_div_result_5 = memory_MulDivIterativePlugin_div_needRevert;
  assign _zz_memory_MulDivIterativePlugin_div_result_4 = {32'd0, _zz_memory_MulDivIterativePlugin_div_result_5};
  assign _zz_memory_MulDivIterativePlugin_rs1_3 = _zz_memory_MulDivIterativePlugin_rs1;
  assign _zz_memory_MulDivIterativePlugin_rs1_2 = {32'd0, _zz_memory_MulDivIterativePlugin_rs1_3};
  assign _zz_memory_MulDivIterativePlugin_rs2_2 = _zz_memory_MulDivIterativePlugin_rs2;
  assign _zz_memory_MulDivIterativePlugin_rs2_1 = {31'd0, _zz_memory_MulDivIterativePlugin_rs2_2};
  assign _zz_when_CsrPlugin_l1718 = (execute_CsrPlugin_csrAddress >>> 3'd4);
  assign _zz_iBusWishbone_ADR_1 = (iBus_cmd_payload_address >>> 3'd5);
  assign _zz_decode_RegFilePlugin_rs1Data = 1'b1;
  assign _zz_decode_RegFilePlugin_rs2Data = 1'b1;
  assign _zz_IBusCachedPlugin_jump_pcLoad_payload_5 = {_zz_IBusCachedPlugin_jump_pcLoad_payload_3,_zz_IBusCachedPlugin_jump_pcLoad_payload_2};
  assign _zz_decode_LEGAL_INSTRUCTION = 32'h0000107f;
  assign _zz_decode_LEGAL_INSTRUCTION_1 = (decode_INSTRUCTION & 32'h0000207f);
  assign _zz_decode_LEGAL_INSTRUCTION_2 = 32'h00002073;
  assign _zz_decode_LEGAL_INSTRUCTION_3 = ((decode_INSTRUCTION & 32'h0000407f) == 32'h00004063);
  assign _zz_decode_LEGAL_INSTRUCTION_4 = ((decode_INSTRUCTION & 32'h0000207f) == 32'h00002013);
  assign _zz_decode_LEGAL_INSTRUCTION_5 = {((decode_INSTRUCTION & 32'h0000107f) == 32'h00000013),{((decode_INSTRUCTION & 32'h0000603f) == 32'h00000023),{((decode_INSTRUCTION & _zz_decode_LEGAL_INSTRUCTION_6) == 32'h00000003),{(_zz_decode_LEGAL_INSTRUCTION_7 == _zz_decode_LEGAL_INSTRUCTION_8),{_zz_decode_LEGAL_INSTRUCTION_9,{_zz_decode_LEGAL_INSTRUCTION_10,_zz_decode_LEGAL_INSTRUCTION_11}}}}}};
  assign _zz_decode_LEGAL_INSTRUCTION_6 = 32'h0000207f;
  assign _zz_decode_LEGAL_INSTRUCTION_7 = (decode_INSTRUCTION & 32'h0000505f);
  assign _zz_decode_LEGAL_INSTRUCTION_8 = 32'h00000003;
  assign _zz_decode_LEGAL_INSTRUCTION_9 = ((decode_INSTRUCTION & 32'h0000707b) == 32'h00000063);
  assign _zz_decode_LEGAL_INSTRUCTION_10 = ((decode_INSTRUCTION & 32'h0000607f) == 32'h0000000f);
  assign _zz_decode_LEGAL_INSTRUCTION_11 = {((decode_INSTRUCTION & 32'hfc00007f) == 32'h00000033),{((decode_INSTRUCTION & 32'hbe00705f) == 32'h00005013),{((decode_INSTRUCTION & _zz_decode_LEGAL_INSTRUCTION_12) == 32'h00001013),{(_zz_decode_LEGAL_INSTRUCTION_13 == _zz_decode_LEGAL_INSTRUCTION_14),{_zz_decode_LEGAL_INSTRUCTION_15,{_zz_decode_LEGAL_INSTRUCTION_16,_zz_decode_LEGAL_INSTRUCTION_17}}}}}};
  assign _zz_decode_LEGAL_INSTRUCTION_12 = 32'hfe00305f;
  assign _zz_decode_LEGAL_INSTRUCTION_13 = (decode_INSTRUCTION & 32'hbe00707f);
  assign _zz_decode_LEGAL_INSTRUCTION_14 = 32'h00000033;
  assign _zz_decode_LEGAL_INSTRUCTION_15 = ((decode_INSTRUCTION & 32'hdfffffff) == 32'h10200073);
  assign _zz_decode_LEGAL_INSTRUCTION_16 = ((decode_INSTRUCTION & 32'hffefffff) == 32'h00000073);
  assign _zz_decode_LEGAL_INSTRUCTION_17 = ((decode_INSTRUCTION & 32'hffffffff) == 32'h10500073);
  assign _zz_IBusCachedPlugin_predictionJumpInterface_payload_4 = decode_INSTRUCTION[31];
  assign _zz_IBusCachedPlugin_predictionJumpInterface_payload_5 = decode_INSTRUCTION[31];
  assign _zz_IBusCachedPlugin_predictionJumpInterface_payload_6 = decode_INSTRUCTION[7];
  assign _zz__zz_decode_IS_DIV = 32'h02004064;
  assign _zz__zz_decode_IS_DIV_1 = _zz_decode_IS_DIV_7;
  assign _zz__zz_decode_IS_DIV_2 = {_zz_decode_IS_DIV_5,_zz_decode_IS_DIV_6};
  assign _zz__zz_decode_IS_DIV_3 = ((decode_INSTRUCTION & 32'h02004074) == 32'h02000030);
  assign _zz__zz_decode_IS_DIV_4 = (|((decode_INSTRUCTION & _zz__zz_decode_IS_DIV_5) == 32'h00000050));
  assign _zz__zz_decode_IS_DIV_6 = (|{_zz__zz_decode_IS_DIV_7,_zz__zz_decode_IS_DIV_8});
  assign _zz__zz_decode_IS_DIV_9 = {(|{_zz__zz_decode_IS_DIV_10,_zz__zz_decode_IS_DIV_12}),{(|_zz__zz_decode_IS_DIV_14),{_zz__zz_decode_IS_DIV_17,{_zz__zz_decode_IS_DIV_20,_zz__zz_decode_IS_DIV_22}}}};
  assign _zz__zz_decode_IS_DIV_5 = 32'h10003050;
  assign _zz__zz_decode_IS_DIV_7 = ((decode_INSTRUCTION & 32'h10103050) == 32'h00100050);
  assign _zz__zz_decode_IS_DIV_8 = ((decode_INSTRUCTION & 32'h10403050) == 32'h10000050);
  assign _zz__zz_decode_IS_DIV_10 = ((decode_INSTRUCTION & _zz__zz_decode_IS_DIV_11) == 32'h00001050);
  assign _zz__zz_decode_IS_DIV_12 = ((decode_INSTRUCTION & _zz__zz_decode_IS_DIV_13) == 32'h00002050);
  assign _zz__zz_decode_IS_DIV_14 = {_zz_decode_IS_DIV_4,(_zz__zz_decode_IS_DIV_15 == _zz__zz_decode_IS_DIV_16)};
  assign _zz__zz_decode_IS_DIV_17 = (|(_zz__zz_decode_IS_DIV_18 == _zz__zz_decode_IS_DIV_19));
  assign _zz__zz_decode_IS_DIV_20 = (|_zz__zz_decode_IS_DIV_21);
  assign _zz__zz_decode_IS_DIV_22 = {(|_zz__zz_decode_IS_DIV_23),{_zz__zz_decode_IS_DIV_26,{_zz__zz_decode_IS_DIV_31,_zz__zz_decode_IS_DIV_34}}};
  assign _zz__zz_decode_IS_DIV_11 = 32'h00001050;
  assign _zz__zz_decode_IS_DIV_13 = 32'h00002050;
  assign _zz__zz_decode_IS_DIV_15 = (decode_INSTRUCTION & 32'h0000001c);
  assign _zz__zz_decode_IS_DIV_16 = 32'h00000004;
  assign _zz__zz_decode_IS_DIV_18 = (decode_INSTRUCTION & 32'h00000058);
  assign _zz__zz_decode_IS_DIV_19 = 32'h00000040;
  assign _zz__zz_decode_IS_DIV_21 = ((decode_INSTRUCTION & 32'h02007054) == 32'h00005010);
  assign _zz__zz_decode_IS_DIV_23 = {((decode_INSTRUCTION & _zz__zz_decode_IS_DIV_24) == 32'h40001010),((decode_INSTRUCTION & _zz__zz_decode_IS_DIV_25) == 32'h00001010)};
  assign _zz__zz_decode_IS_DIV_26 = (|{(_zz__zz_decode_IS_DIV_27 == _zz__zz_decode_IS_DIV_28),(_zz__zz_decode_IS_DIV_29 == _zz__zz_decode_IS_DIV_30)});
  assign _zz__zz_decode_IS_DIV_31 = (|(_zz__zz_decode_IS_DIV_32 == _zz__zz_decode_IS_DIV_33));
  assign _zz__zz_decode_IS_DIV_34 = {(|_zz_decode_IS_DIV_5),{(|_zz__zz_decode_IS_DIV_35),{_zz__zz_decode_IS_DIV_38,{_zz__zz_decode_IS_DIV_43,_zz__zz_decode_IS_DIV_48}}}};
  assign _zz__zz_decode_IS_DIV_24 = 32'h40003054;
  assign _zz__zz_decode_IS_DIV_25 = 32'h02007054;
  assign _zz__zz_decode_IS_DIV_27 = (decode_INSTRUCTION & 32'h00000064);
  assign _zz__zz_decode_IS_DIV_28 = 32'h00000024;
  assign _zz__zz_decode_IS_DIV_29 = (decode_INSTRUCTION & 32'h02003054);
  assign _zz__zz_decode_IS_DIV_30 = 32'h00001010;
  assign _zz__zz_decode_IS_DIV_32 = (decode_INSTRUCTION & 32'h00001000);
  assign _zz__zz_decode_IS_DIV_33 = 32'h00001000;
  assign _zz__zz_decode_IS_DIV_35 = {((decode_INSTRUCTION & _zz__zz_decode_IS_DIV_36) == 32'h00002000),((decode_INSTRUCTION & _zz__zz_decode_IS_DIV_37) == 32'h00001000)};
  assign _zz__zz_decode_IS_DIV_38 = (|{(_zz__zz_decode_IS_DIV_39 == _zz__zz_decode_IS_DIV_40),(_zz__zz_decode_IS_DIV_41 == _zz__zz_decode_IS_DIV_42)});
  assign _zz__zz_decode_IS_DIV_43 = (|{_zz__zz_decode_IS_DIV_44,{_zz__zz_decode_IS_DIV_45,_zz__zz_decode_IS_DIV_46}});
  assign _zz__zz_decode_IS_DIV_48 = {(|_zz__zz_decode_IS_DIV_49),{(|_zz__zz_decode_IS_DIV_50),{_zz__zz_decode_IS_DIV_52,{_zz__zz_decode_IS_DIV_57,_zz__zz_decode_IS_DIV_70}}}};
  assign _zz__zz_decode_IS_DIV_36 = 32'h00002010;
  assign _zz__zz_decode_IS_DIV_37 = 32'h00005000;
  assign _zz__zz_decode_IS_DIV_39 = (decode_INSTRUCTION & 32'h00000034);
  assign _zz__zz_decode_IS_DIV_40 = 32'h00000020;
  assign _zz__zz_decode_IS_DIV_41 = (decode_INSTRUCTION & 32'h00000064);
  assign _zz__zz_decode_IS_DIV_42 = 32'h00000020;
  assign _zz__zz_decode_IS_DIV_44 = ((decode_INSTRUCTION & 32'h00000050) == 32'h00000040);
  assign _zz__zz_decode_IS_DIV_45 = _zz_decode_IS_DIV_2;
  assign _zz__zz_decode_IS_DIV_46 = ((decode_INSTRUCTION & _zz__zz_decode_IS_DIV_47) == 32'h00000040);
  assign _zz__zz_decode_IS_DIV_49 = ((decode_INSTRUCTION & 32'h00000020) == 32'h00000020);
  assign _zz__zz_decode_IS_DIV_50 = ((decode_INSTRUCTION & _zz__zz_decode_IS_DIV_51) == 32'h00000010);
  assign _zz__zz_decode_IS_DIV_52 = (|{_zz_decode_IS_DIV_3,{_zz__zz_decode_IS_DIV_53,_zz__zz_decode_IS_DIV_55}});
  assign _zz__zz_decode_IS_DIV_57 = (|{_zz__zz_decode_IS_DIV_58,_zz__zz_decode_IS_DIV_59});
  assign _zz__zz_decode_IS_DIV_70 = {(|_zz__zz_decode_IS_DIV_71),{_zz__zz_decode_IS_DIV_74,{_zz__zz_decode_IS_DIV_77,_zz__zz_decode_IS_DIV_84}}};
  assign _zz__zz_decode_IS_DIV_47 = 32'h00403040;
  assign _zz__zz_decode_IS_DIV_51 = 32'h00000010;
  assign _zz__zz_decode_IS_DIV_53 = ((decode_INSTRUCTION & _zz__zz_decode_IS_DIV_54) == 32'h00000010);
  assign _zz__zz_decode_IS_DIV_55 = ((decode_INSTRUCTION & _zz__zz_decode_IS_DIV_56) == 32'h00000020);
  assign _zz__zz_decode_IS_DIV_58 = _zz_decode_IS_DIV_4;
  assign _zz__zz_decode_IS_DIV_59 = {(_zz__zz_decode_IS_DIV_60 == _zz__zz_decode_IS_DIV_61),{_zz__zz_decode_IS_DIV_62,{_zz__zz_decode_IS_DIV_64,_zz__zz_decode_IS_DIV_67}}};
  assign _zz__zz_decode_IS_DIV_71 = {_zz_decode_IS_DIV_3,(_zz__zz_decode_IS_DIV_72 == _zz__zz_decode_IS_DIV_73)};
  assign _zz__zz_decode_IS_DIV_74 = (|{_zz_decode_IS_DIV_3,_zz__zz_decode_IS_DIV_75});
  assign _zz__zz_decode_IS_DIV_77 = (|{_zz__zz_decode_IS_DIV_78,_zz__zz_decode_IS_DIV_81});
  assign _zz__zz_decode_IS_DIV_84 = {(|_zz__zz_decode_IS_DIV_85),{_zz__zz_decode_IS_DIV_88,{_zz__zz_decode_IS_DIV_94,_zz__zz_decode_IS_DIV_97}}};
  assign _zz__zz_decode_IS_DIV_54 = 32'h00000030;
  assign _zz__zz_decode_IS_DIV_56 = 32'h02000060;
  assign _zz__zz_decode_IS_DIV_60 = (decode_INSTRUCTION & 32'h00001010);
  assign _zz__zz_decode_IS_DIV_61 = 32'h00001010;
  assign _zz__zz_decode_IS_DIV_62 = ((decode_INSTRUCTION & _zz__zz_decode_IS_DIV_63) == 32'h00002010);
  assign _zz__zz_decode_IS_DIV_64 = (_zz__zz_decode_IS_DIV_65 == _zz__zz_decode_IS_DIV_66);
  assign _zz__zz_decode_IS_DIV_67 = {_zz__zz_decode_IS_DIV_68,_zz__zz_decode_IS_DIV_69};
  assign _zz__zz_decode_IS_DIV_72 = (decode_INSTRUCTION & 32'h00000070);
  assign _zz__zz_decode_IS_DIV_73 = 32'h00000020;
  assign _zz__zz_decode_IS_DIV_75 = ((decode_INSTRUCTION & _zz__zz_decode_IS_DIV_76) == 32'h0);
  assign _zz__zz_decode_IS_DIV_78 = (_zz__zz_decode_IS_DIV_79 == _zz__zz_decode_IS_DIV_80);
  assign _zz__zz_decode_IS_DIV_81 = (_zz__zz_decode_IS_DIV_82 == _zz__zz_decode_IS_DIV_83);
  assign _zz__zz_decode_IS_DIV_85 = (_zz__zz_decode_IS_DIV_86 == _zz__zz_decode_IS_DIV_87);
  assign _zz__zz_decode_IS_DIV_88 = (|{_zz__zz_decode_IS_DIV_89,_zz__zz_decode_IS_DIV_91});
  assign _zz__zz_decode_IS_DIV_94 = (|_zz__zz_decode_IS_DIV_95);
  assign _zz__zz_decode_IS_DIV_97 = {_zz__zz_decode_IS_DIV_98,{_zz__zz_decode_IS_DIV_104,_zz__zz_decode_IS_DIV_108}};
  assign _zz__zz_decode_IS_DIV_63 = 32'h00002010;
  assign _zz__zz_decode_IS_DIV_65 = (decode_INSTRUCTION & 32'h00000050);
  assign _zz__zz_decode_IS_DIV_66 = 32'h00000010;
  assign _zz__zz_decode_IS_DIV_68 = ((decode_INSTRUCTION & 32'h0000000c) == 32'h00000004);
  assign _zz__zz_decode_IS_DIV_69 = ((decode_INSTRUCTION & 32'h00000028) == 32'h0);
  assign _zz__zz_decode_IS_DIV_76 = 32'h00000020;
  assign _zz__zz_decode_IS_DIV_79 = (decode_INSTRUCTION & 32'h00006004);
  assign _zz__zz_decode_IS_DIV_80 = 32'h00006000;
  assign _zz__zz_decode_IS_DIV_82 = (decode_INSTRUCTION & 32'h00005014);
  assign _zz__zz_decode_IS_DIV_83 = 32'h00004010;
  assign _zz__zz_decode_IS_DIV_86 = (decode_INSTRUCTION & 32'h00006014);
  assign _zz__zz_decode_IS_DIV_87 = 32'h00002010;
  assign _zz__zz_decode_IS_DIV_89 = ((decode_INSTRUCTION & _zz__zz_decode_IS_DIV_90) == 32'h0);
  assign _zz__zz_decode_IS_DIV_91 = {_zz_decode_IS_DIV_2,{_zz__zz_decode_IS_DIV_92,_zz__zz_decode_IS_DIV_93}};
  assign _zz__zz_decode_IS_DIV_95 = ((decode_INSTRUCTION & _zz__zz_decode_IS_DIV_96) == 32'h0);
  assign _zz__zz_decode_IS_DIV_98 = (|{_zz__zz_decode_IS_DIV_99,{_zz__zz_decode_IS_DIV_100,_zz__zz_decode_IS_DIV_102}});
  assign _zz__zz_decode_IS_DIV_104 = (|{_zz__zz_decode_IS_DIV_105,_zz__zz_decode_IS_DIV_107});
  assign _zz__zz_decode_IS_DIV_108 = {(|_zz__zz_decode_IS_DIV_109),(|_zz__zz_decode_IS_DIV_112)};
  assign _zz__zz_decode_IS_DIV_90 = 32'h00000044;
  assign _zz__zz_decode_IS_DIV_92 = ((decode_INSTRUCTION & 32'h00006004) == 32'h00002000);
  assign _zz__zz_decode_IS_DIV_93 = ((decode_INSTRUCTION & 32'h00005004) == 32'h00001000);
  assign _zz__zz_decode_IS_DIV_96 = 32'h00000058;
  assign _zz__zz_decode_IS_DIV_99 = ((decode_INSTRUCTION & 32'h00000044) == 32'h00000040);
  assign _zz__zz_decode_IS_DIV_100 = ((decode_INSTRUCTION & _zz__zz_decode_IS_DIV_101) == 32'h00002010);
  assign _zz__zz_decode_IS_DIV_102 = ((decode_INSTRUCTION & _zz__zz_decode_IS_DIV_103) == 32'h40000030);
  assign _zz__zz_decode_IS_DIV_105 = ((decode_INSTRUCTION & _zz__zz_decode_IS_DIV_106) == 32'h00000004);
  assign _zz__zz_decode_IS_DIV_107 = _zz_decode_IS_DIV_1;
  assign _zz__zz_decode_IS_DIV_109 = {(_zz__zz_decode_IS_DIV_110 == _zz__zz_decode_IS_DIV_111),_zz_decode_IS_DIV_1};
  assign _zz__zz_decode_IS_DIV_112 = ((decode_INSTRUCTION & _zz__zz_decode_IS_DIV_113) == 32'h00001008);
  assign _zz__zz_decode_IS_DIV_101 = 32'h00002014;
  assign _zz__zz_decode_IS_DIV_103 = 32'h40004034;
  assign _zz__zz_decode_IS_DIV_106 = 32'h00000014;
  assign _zz__zz_decode_IS_DIV_110 = (decode_INSTRUCTION & 32'h00000044);
  assign _zz__zz_decode_IS_DIV_111 = 32'h00000004;
  assign _zz__zz_decode_IS_DIV_113 = 32'h00001048;
  assign _zz_execute_BranchPlugin_branch_src2_6 = execute_INSTRUCTION[31];
  assign _zz_execute_BranchPlugin_branch_src2_7 = execute_INSTRUCTION[19 : 12];
  assign _zz_execute_BranchPlugin_branch_src2_8 = execute_INSTRUCTION[20];
  assign _zz_execute_BranchPlugin_branch_src2_9 = execute_INSTRUCTION[31];
  assign _zz_execute_BranchPlugin_branch_src2_10 = execute_INSTRUCTION[7];
  always @(posedge clk) begin
    if(_zz_decode_RegFilePlugin_rs1Data) begin
      RegFilePlugin_regFile_spinal_port0 <= RegFilePlugin_regFile[decode_RegFilePlugin_regFileReadAddress1];
    end
  end

  always @(posedge clk) begin
    if(_zz_decode_RegFilePlugin_rs2Data) begin
      RegFilePlugin_regFile_spinal_port1 <= RegFilePlugin_regFile[decode_RegFilePlugin_regFileReadAddress2];
    end
  end

  always @(posedge clk) begin
    if(_zz_1) begin
      RegFilePlugin_regFile[lastStageRegFileWrite_payload_address] <= lastStageRegFileWrite_payload_data;
    end
  end

  InstructionCache IBusCachedPlugin_cache (
    .io_flush                              (IBusCachedPlugin_cache_io_flush                           ), //i
    .io_cpu_prefetch_isValid               (IBusCachedPlugin_cache_io_cpu_prefetch_isValid            ), //i
    .io_cpu_prefetch_haltIt                (IBusCachedPlugin_cache_io_cpu_prefetch_haltIt             ), //o
    .io_cpu_prefetch_pc                    (IBusCachedPlugin_iBusRsp_stages_0_input_payload[31:0]     ), //i
    .io_cpu_fetch_isValid                  (IBusCachedPlugin_cache_io_cpu_fetch_isValid               ), //i
    .io_cpu_fetch_isStuck                  (IBusCachedPlugin_cache_io_cpu_fetch_isStuck               ), //i
    .io_cpu_fetch_isRemoved                (                                                          ), //i
    .io_cpu_fetch_pc                       (IBusCachedPlugin_iBusRsp_stages_1_input_payload[31:0]     ), //i
    .io_cpu_fetch_data                     (IBusCachedPlugin_cache_io_cpu_fetch_data[31:0]            ), //o
    .io_cpu_fetch_mmuRsp_physicalAddress   (IBusCachedPlugin_mmuBus_rsp_physicalAddress[31:0]         ), //i
    .io_cpu_fetch_mmuRsp_isIoAccess        (IBusCachedPlugin_mmuBus_rsp_isIoAccess                    ), //i
    .io_cpu_fetch_mmuRsp_isPaging          (IBusCachedPlugin_mmuBus_rsp_isPaging                      ), //i
    .io_cpu_fetch_mmuRsp_allowRead         (IBusCachedPlugin_mmuBus_rsp_allowRead                     ), //i
    .io_cpu_fetch_mmuRsp_allowWrite        (IBusCachedPlugin_mmuBus_rsp_allowWrite                    ), //i
    .io_cpu_fetch_mmuRsp_allowExecute      (IBusCachedPlugin_mmuBus_rsp_allowExecute                  ), //i
    .io_cpu_fetch_mmuRsp_exception         (IBusCachedPlugin_mmuBus_rsp_exception                     ), //i
    .io_cpu_fetch_mmuRsp_refilling         (IBusCachedPlugin_mmuBus_rsp_refilling                     ), //i
    .io_cpu_fetch_mmuRsp_bypassTranslation (IBusCachedPlugin_mmuBus_rsp_bypassTranslation             ), //i
    .io_cpu_fetch_physicalAddress          (IBusCachedPlugin_cache_io_cpu_fetch_physicalAddress[31:0] ), //o
    .io_cpu_decode_isValid                 (IBusCachedPlugin_cache_io_cpu_decode_isValid              ), //i
    .io_cpu_decode_isStuck                 (IBusCachedPlugin_cache_io_cpu_decode_isStuck              ), //i
    .io_cpu_decode_pc                      (IBusCachedPlugin_iBusRsp_stages_2_input_payload[31:0]     ), //i
    .io_cpu_decode_physicalAddress         (IBusCachedPlugin_cache_io_cpu_decode_physicalAddress[31:0]), //o
    .io_cpu_decode_data                    (IBusCachedPlugin_cache_io_cpu_decode_data[31:0]           ), //o
    .io_cpu_decode_cacheMiss               (IBusCachedPlugin_cache_io_cpu_decode_cacheMiss            ), //o
    .io_cpu_decode_error                   (IBusCachedPlugin_cache_io_cpu_decode_error                ), //o
    .io_cpu_decode_mmuRefilling            (IBusCachedPlugin_cache_io_cpu_decode_mmuRefilling         ), //o
    .io_cpu_decode_mmuException            (IBusCachedPlugin_cache_io_cpu_decode_mmuException         ), //o
    .io_cpu_decode_isUser                  (IBusCachedPlugin_cache_io_cpu_decode_isUser               ), //i
    .io_cpu_fill_valid                     (IBusCachedPlugin_cache_io_cpu_fill_valid                  ), //i
    .io_cpu_fill_payload                   (IBusCachedPlugin_cache_io_cpu_decode_physicalAddress[31:0]), //i
    .io_mem_cmd_valid                      (IBusCachedPlugin_cache_io_mem_cmd_valid                   ), //o
    .io_mem_cmd_ready                      (iBus_cmd_ready                                            ), //i
    .io_mem_cmd_payload_address            (IBusCachedPlugin_cache_io_mem_cmd_payload_address[31:0]   ), //o
    .io_mem_cmd_payload_size               (IBusCachedPlugin_cache_io_mem_cmd_payload_size[2:0]       ), //o
    .io_mem_rsp_valid                      (iBus_rsp_valid                                            ), //i
    .io_mem_rsp_payload_data               (iBus_rsp_payload_data[31:0]                               ), //i
    .io_mem_rsp_payload_error              (iBus_rsp_payload_error                                    ), //i
    ._zz_when_Fetcher_l411                 (IBusCachedPlugin_injector_port_state[2:0]                 ), //i
    ._zz_io_cpu_fetch_data_regNextWhen     (CsrPlugin_injectionPort_payload[31:0]                     ), //i
    .clk                                   (clk                                                       ), //i
    .reset                                 (reset                                                     )  //i
  );
  (* keep_hierarchy = "TRUE" *) BufferCC_3 reset_buffercc (
    .io_dataIn  (reset                    ), //i
    .io_dataOut (reset_buffercc_io_dataOut), //o
    .clk        (clk                      ), //i
    .reset      (reset                    )  //i
  );
  DebugModule debugModule_1 (
    .io_ctrl_cmd_valid                   (debugTransportModuleTunneled_1_io_bus_cmd_valid               ), //i
    .io_ctrl_cmd_ready                   (debugModule_1_io_ctrl_cmd_ready                               ), //o
    .io_ctrl_cmd_payload_write           (debugTransportModuleTunneled_1_io_bus_cmd_payload_write       ), //i
    .io_ctrl_cmd_payload_data            (debugTransportModuleTunneled_1_io_bus_cmd_payload_data[31:0]  ), //i
    .io_ctrl_cmd_payload_address         (debugTransportModuleTunneled_1_io_bus_cmd_payload_address[6:0]), //i
    .io_ctrl_rsp_valid                   (debugModule_1_io_ctrl_rsp_valid                               ), //o
    .io_ctrl_rsp_payload_error           (debugModule_1_io_ctrl_rsp_payload_error                       ), //o
    .io_ctrl_rsp_payload_data            (debugModule_1_io_ctrl_rsp_payload_data[31:0]                  ), //o
    .io_ndmreset                         (debugModule_1_io_ndmreset                                     ), //o
    .io_harts_0_halted                   (debugBus_halted                                               ), //i
    .io_harts_0_running                  (debugBus_running                                              ), //i
    .io_harts_0_unavailable              (debugBus_unavailable                                          ), //i
    .io_harts_0_exception                (debugBus_exception                                            ), //i
    .io_harts_0_commit                   (debugBus_commit                                               ), //i
    .io_harts_0_ebreak                   (debugBus_ebreak                                               ), //i
    .io_harts_0_redo                     (debugBus_redo                                                 ), //i
    .io_harts_0_regSuccess               (debugBus_regSuccess                                           ), //i
    .io_harts_0_ackReset                 (debugModule_1_io_harts_0_ackReset                             ), //o
    .io_harts_0_haveReset                (debugBus_haveReset                                            ), //i
    .io_harts_0_resume_cmd_valid         (debugModule_1_io_harts_0_resume_cmd_valid                     ), //o
    .io_harts_0_resume_rsp_valid         (debugBus_resume_rsp_valid                                     ), //i
    .io_harts_0_haltReq                  (debugModule_1_io_harts_0_haltReq                              ), //o
    .io_harts_0_dmToHart_valid           (debugModule_1_io_harts_0_dmToHart_valid                       ), //o
    .io_harts_0_dmToHart_payload_op      (debugModule_1_io_harts_0_dmToHart_payload_op[1:0]             ), //o
    .io_harts_0_dmToHart_payload_address (debugModule_1_io_harts_0_dmToHart_payload_address[4:0]        ), //o
    .io_harts_0_dmToHart_payload_data    (debugModule_1_io_harts_0_dmToHart_payload_data[31:0]          ), //o
    .io_harts_0_dmToHart_payload_size    (debugModule_1_io_harts_0_dmToHart_payload_size[2:0]           ), //o
    .io_harts_0_hartToDm_valid           (debugBus_hartToDm_valid                                       ), //i
    .io_harts_0_hartToDm_payload_address (debugBus_hartToDm_payload_address[3:0]                        ), //i
    .io_harts_0_hartToDm_payload_data    (debugBus_hartToDm_payload_data[31:0]                          ), //i
    .clk                                 (clk                                                           ), //i
    .debugReset                          (debugReset                                                    )  //i
  );
  DebugTransportModuleTunneled debugTransportModuleTunneled_1 (
    .io_instruction_tdi         (jtagInstruction_tdi                                           ), //i
    .io_instruction_enable      (jtagInstruction_enable                                        ), //i
    .io_instruction_capture     (jtagInstruction_capture                                       ), //i
    .io_instruction_shift       (jtagInstruction_shift                                         ), //i
    .io_instruction_update      (jtagInstruction_update                                        ), //i
    .io_instruction_reset       (jtagInstruction_reset                                         ), //i
    .io_instruction_tdo         (debugTransportModuleTunneled_1_io_instruction_tdo             ), //o
    .io_bus_cmd_valid           (debugTransportModuleTunneled_1_io_bus_cmd_valid               ), //o
    .io_bus_cmd_ready           (debugModule_1_io_ctrl_cmd_ready                               ), //i
    .io_bus_cmd_payload_write   (debugTransportModuleTunneled_1_io_bus_cmd_payload_write       ), //o
    .io_bus_cmd_payload_data    (debugTransportModuleTunneled_1_io_bus_cmd_payload_data[31:0]  ), //o
    .io_bus_cmd_payload_address (debugTransportModuleTunneled_1_io_bus_cmd_payload_address[6:0]), //o
    .io_bus_rsp_valid           (debugModule_1_io_ctrl_rsp_valid                               ), //i
    .io_bus_rsp_payload_error   (debugModule_1_io_ctrl_rsp_payload_error                       ), //i
    .io_bus_rsp_payload_data    (debugModule_1_io_ctrl_rsp_payload_data[31:0]                  ), //i
    .jtag_clk                   (jtag_clk                                                      ), //i
    .clk                        (clk                                                           ), //i
    .debugReset                 (debugReset                                                    )  //i
  );
  always @(*) begin
    case(_zz_IBusCachedPlugin_jump_pcLoad_payload_5)
      2'b00 : _zz_IBusCachedPlugin_jump_pcLoad_payload_4 = CsrPlugin_jumpInterface_payload;
      2'b01 : _zz_IBusCachedPlugin_jump_pcLoad_payload_4 = BranchPlugin_jumpInterface_payload;
      default : _zz_IBusCachedPlugin_jump_pcLoad_payload_4 = IBusCachedPlugin_predictionJumpInterface_payload;
    endcase
  end

  always @(*) begin
    case(CsrPlugin_trigger_tselect_index)
      1'b0 : _zz__zz_CsrPlugin_csrMapping_readDataInit_6 = CsrPlugin_trigger_slots_0_tdata1_read;
      default : _zz__zz_CsrPlugin_csrMapping_readDataInit_6 = CsrPlugin_trigger_slots_1_tdata1_read;
    endcase
  end

  `ifndef SYNTHESIS
  always @(*) begin
    case(_zz_memory_to_writeBack_ENV_CTRL)
      EnvCtrlEnum_NONE : _zz_memory_to_writeBack_ENV_CTRL_string = "NONE  ";
      EnvCtrlEnum_XRET : _zz_memory_to_writeBack_ENV_CTRL_string = "XRET  ";
      EnvCtrlEnum_ECALL : _zz_memory_to_writeBack_ENV_CTRL_string = "ECALL ";
      EnvCtrlEnum_EBREAK : _zz_memory_to_writeBack_ENV_CTRL_string = "EBREAK";
      default : _zz_memory_to_writeBack_ENV_CTRL_string = "??????";
    endcase
  end
  always @(*) begin
    case(_zz_memory_to_writeBack_ENV_CTRL_1)
      EnvCtrlEnum_NONE : _zz_memory_to_writeBack_ENV_CTRL_1_string = "NONE  ";
      EnvCtrlEnum_XRET : _zz_memory_to_writeBack_ENV_CTRL_1_string = "XRET  ";
      EnvCtrlEnum_ECALL : _zz_memory_to_writeBack_ENV_CTRL_1_string = "ECALL ";
      EnvCtrlEnum_EBREAK : _zz_memory_to_writeBack_ENV_CTRL_1_string = "EBREAK";
      default : _zz_memory_to_writeBack_ENV_CTRL_1_string = "??????";
    endcase
  end
  always @(*) begin
    case(_zz_execute_to_memory_ENV_CTRL)
      EnvCtrlEnum_NONE : _zz_execute_to_memory_ENV_CTRL_string = "NONE  ";
      EnvCtrlEnum_XRET : _zz_execute_to_memory_ENV_CTRL_string = "XRET  ";
      EnvCtrlEnum_ECALL : _zz_execute_to_memory_ENV_CTRL_string = "ECALL ";
      EnvCtrlEnum_EBREAK : _zz_execute_to_memory_ENV_CTRL_string = "EBREAK";
      default : _zz_execute_to_memory_ENV_CTRL_string = "??????";
    endcase
  end
  always @(*) begin
    case(_zz_execute_to_memory_ENV_CTRL_1)
      EnvCtrlEnum_NONE : _zz_execute_to_memory_ENV_CTRL_1_string = "NONE  ";
      EnvCtrlEnum_XRET : _zz_execute_to_memory_ENV_CTRL_1_string = "XRET  ";
      EnvCtrlEnum_ECALL : _zz_execute_to_memory_ENV_CTRL_1_string = "ECALL ";
      EnvCtrlEnum_EBREAK : _zz_execute_to_memory_ENV_CTRL_1_string = "EBREAK";
      default : _zz_execute_to_memory_ENV_CTRL_1_string = "??????";
    endcase
  end
  always @(*) begin
    case(decode_ENV_CTRL)
      EnvCtrlEnum_NONE : decode_ENV_CTRL_string = "NONE  ";
      EnvCtrlEnum_XRET : decode_ENV_CTRL_string = "XRET  ";
      EnvCtrlEnum_ECALL : decode_ENV_CTRL_string = "ECALL ";
      EnvCtrlEnum_EBREAK : decode_ENV_CTRL_string = "EBREAK";
      default : decode_ENV_CTRL_string = "??????";
    endcase
  end
  always @(*) begin
    case(_zz_decode_ENV_CTRL)
      EnvCtrlEnum_NONE : _zz_decode_ENV_CTRL_string = "NONE  ";
      EnvCtrlEnum_XRET : _zz_decode_ENV_CTRL_string = "XRET  ";
      EnvCtrlEnum_ECALL : _zz_decode_ENV_CTRL_string = "ECALL ";
      EnvCtrlEnum_EBREAK : _zz_decode_ENV_CTRL_string = "EBREAK";
      default : _zz_decode_ENV_CTRL_string = "??????";
    endcase
  end
  always @(*) begin
    case(_zz_decode_to_execute_ENV_CTRL)
      EnvCtrlEnum_NONE : _zz_decode_to_execute_ENV_CTRL_string = "NONE  ";
      EnvCtrlEnum_XRET : _zz_decode_to_execute_ENV_CTRL_string = "XRET  ";
      EnvCtrlEnum_ECALL : _zz_decode_to_execute_ENV_CTRL_string = "ECALL ";
      EnvCtrlEnum_EBREAK : _zz_decode_to_execute_ENV_CTRL_string = "EBREAK";
      default : _zz_decode_to_execute_ENV_CTRL_string = "??????";
    endcase
  end
  always @(*) begin
    case(_zz_decode_to_execute_ENV_CTRL_1)
      EnvCtrlEnum_NONE : _zz_decode_to_execute_ENV_CTRL_1_string = "NONE  ";
      EnvCtrlEnum_XRET : _zz_decode_to_execute_ENV_CTRL_1_string = "XRET  ";
      EnvCtrlEnum_ECALL : _zz_decode_to_execute_ENV_CTRL_1_string = "ECALL ";
      EnvCtrlEnum_EBREAK : _zz_decode_to_execute_ENV_CTRL_1_string = "EBREAK";
      default : _zz_decode_to_execute_ENV_CTRL_1_string = "??????";
    endcase
  end
  always @(*) begin
    case(_zz_decode_to_execute_BRANCH_CTRL)
      BranchCtrlEnum_INC : _zz_decode_to_execute_BRANCH_CTRL_string = "INC ";
      BranchCtrlEnum_B : _zz_decode_to_execute_BRANCH_CTRL_string = "B   ";
      BranchCtrlEnum_JAL : _zz_decode_to_execute_BRANCH_CTRL_string = "JAL ";
      BranchCtrlEnum_JALR : _zz_decode_to_execute_BRANCH_CTRL_string = "JALR";
      default : _zz_decode_to_execute_BRANCH_CTRL_string = "????";
    endcase
  end
  always @(*) begin
    case(_zz_decode_to_execute_BRANCH_CTRL_1)
      BranchCtrlEnum_INC : _zz_decode_to_execute_BRANCH_CTRL_1_string = "INC ";
      BranchCtrlEnum_B : _zz_decode_to_execute_BRANCH_CTRL_1_string = "B   ";
      BranchCtrlEnum_JAL : _zz_decode_to_execute_BRANCH_CTRL_1_string = "JAL ";
      BranchCtrlEnum_JALR : _zz_decode_to_execute_BRANCH_CTRL_1_string = "JALR";
      default : _zz_decode_to_execute_BRANCH_CTRL_1_string = "????";
    endcase
  end
  always @(*) begin
    case(decode_SHIFT_CTRL)
      ShiftCtrlEnum_DISABLE_1 : decode_SHIFT_CTRL_string = "DISABLE_1";
      ShiftCtrlEnum_SLL_1 : decode_SHIFT_CTRL_string = "SLL_1    ";
      ShiftCtrlEnum_SRL_1 : decode_SHIFT_CTRL_string = "SRL_1    ";
      ShiftCtrlEnum_SRA_1 : decode_SHIFT_CTRL_string = "SRA_1    ";
      default : decode_SHIFT_CTRL_string = "?????????";
    endcase
  end
  always @(*) begin
    case(_zz_decode_SHIFT_CTRL)
      ShiftCtrlEnum_DISABLE_1 : _zz_decode_SHIFT_CTRL_string = "DISABLE_1";
      ShiftCtrlEnum_SLL_1 : _zz_decode_SHIFT_CTRL_string = "SLL_1    ";
      ShiftCtrlEnum_SRL_1 : _zz_decode_SHIFT_CTRL_string = "SRL_1    ";
      ShiftCtrlEnum_SRA_1 : _zz_decode_SHIFT_CTRL_string = "SRA_1    ";
      default : _zz_decode_SHIFT_CTRL_string = "?????????";
    endcase
  end
  always @(*) begin
    case(_zz_decode_to_execute_SHIFT_CTRL)
      ShiftCtrlEnum_DISABLE_1 : _zz_decode_to_execute_SHIFT_CTRL_string = "DISABLE_1";
      ShiftCtrlEnum_SLL_1 : _zz_decode_to_execute_SHIFT_CTRL_string = "SLL_1    ";
      ShiftCtrlEnum_SRL_1 : _zz_decode_to_execute_SHIFT_CTRL_string = "SRL_1    ";
      ShiftCtrlEnum_SRA_1 : _zz_decode_to_execute_SHIFT_CTRL_string = "SRA_1    ";
      default : _zz_decode_to_execute_SHIFT_CTRL_string = "?????????";
    endcase
  end
  always @(*) begin
    case(_zz_decode_to_execute_SHIFT_CTRL_1)
      ShiftCtrlEnum_DISABLE_1 : _zz_decode_to_execute_SHIFT_CTRL_1_string = "DISABLE_1";
      ShiftCtrlEnum_SLL_1 : _zz_decode_to_execute_SHIFT_CTRL_1_string = "SLL_1    ";
      ShiftCtrlEnum_SRL_1 : _zz_decode_to_execute_SHIFT_CTRL_1_string = "SRL_1    ";
      ShiftCtrlEnum_SRA_1 : _zz_decode_to_execute_SHIFT_CTRL_1_string = "SRA_1    ";
      default : _zz_decode_to_execute_SHIFT_CTRL_1_string = "?????????";
    endcase
  end
  always @(*) begin
    case(decode_ALU_BITWISE_CTRL)
      AluBitwiseCtrlEnum_XOR_1 : decode_ALU_BITWISE_CTRL_string = "XOR_1";
      AluBitwiseCtrlEnum_OR_1 : decode_ALU_BITWISE_CTRL_string = "OR_1 ";
      AluBitwiseCtrlEnum_AND_1 : decode_ALU_BITWISE_CTRL_string = "AND_1";
      default : decode_ALU_BITWISE_CTRL_string = "?????";
    endcase
  end
  always @(*) begin
    case(_zz_decode_ALU_BITWISE_CTRL)
      AluBitwiseCtrlEnum_XOR_1 : _zz_decode_ALU_BITWISE_CTRL_string = "XOR_1";
      AluBitwiseCtrlEnum_OR_1 : _zz_decode_ALU_BITWISE_CTRL_string = "OR_1 ";
      AluBitwiseCtrlEnum_AND_1 : _zz_decode_ALU_BITWISE_CTRL_string = "AND_1";
      default : _zz_decode_ALU_BITWISE_CTRL_string = "?????";
    endcase
  end
  always @(*) begin
    case(_zz_decode_to_execute_ALU_BITWISE_CTRL)
      AluBitwiseCtrlEnum_XOR_1 : _zz_decode_to_execute_ALU_BITWISE_CTRL_string = "XOR_1";
      AluBitwiseCtrlEnum_OR_1 : _zz_decode_to_execute_ALU_BITWISE_CTRL_string = "OR_1 ";
      AluBitwiseCtrlEnum_AND_1 : _zz_decode_to_execute_ALU_BITWISE_CTRL_string = "AND_1";
      default : _zz_decode_to_execute_ALU_BITWISE_CTRL_string = "?????";
    endcase
  end
  always @(*) begin
    case(_zz_decode_to_execute_ALU_BITWISE_CTRL_1)
      AluBitwiseCtrlEnum_XOR_1 : _zz_decode_to_execute_ALU_BITWISE_CTRL_1_string = "XOR_1";
      AluBitwiseCtrlEnum_OR_1 : _zz_decode_to_execute_ALU_BITWISE_CTRL_1_string = "OR_1 ";
      AluBitwiseCtrlEnum_AND_1 : _zz_decode_to_execute_ALU_BITWISE_CTRL_1_string = "AND_1";
      default : _zz_decode_to_execute_ALU_BITWISE_CTRL_1_string = "?????";
    endcase
  end
  always @(*) begin
    case(decode_SRC2_CTRL)
      Src2CtrlEnum_RS : decode_SRC2_CTRL_string = "RS ";
      Src2CtrlEnum_IMI : decode_SRC2_CTRL_string = "IMI";
      Src2CtrlEnum_IMS : decode_SRC2_CTRL_string = "IMS";
      Src2CtrlEnum_PC : decode_SRC2_CTRL_string = "PC ";
      default : decode_SRC2_CTRL_string = "???";
    endcase
  end
  always @(*) begin
    case(_zz_decode_SRC2_CTRL)
      Src2CtrlEnum_RS : _zz_decode_SRC2_CTRL_string = "RS ";
      Src2CtrlEnum_IMI : _zz_decode_SRC2_CTRL_string = "IMI";
      Src2CtrlEnum_IMS : _zz_decode_SRC2_CTRL_string = "IMS";
      Src2CtrlEnum_PC : _zz_decode_SRC2_CTRL_string = "PC ";
      default : _zz_decode_SRC2_CTRL_string = "???";
    endcase
  end
  always @(*) begin
    case(_zz_decode_to_execute_SRC2_CTRL)
      Src2CtrlEnum_RS : _zz_decode_to_execute_SRC2_CTRL_string = "RS ";
      Src2CtrlEnum_IMI : _zz_decode_to_execute_SRC2_CTRL_string = "IMI";
      Src2CtrlEnum_IMS : _zz_decode_to_execute_SRC2_CTRL_string = "IMS";
      Src2CtrlEnum_PC : _zz_decode_to_execute_SRC2_CTRL_string = "PC ";
      default : _zz_decode_to_execute_SRC2_CTRL_string = "???";
    endcase
  end
  always @(*) begin
    case(_zz_decode_to_execute_SRC2_CTRL_1)
      Src2CtrlEnum_RS : _zz_decode_to_execute_SRC2_CTRL_1_string = "RS ";
      Src2CtrlEnum_IMI : _zz_decode_to_execute_SRC2_CTRL_1_string = "IMI";
      Src2CtrlEnum_IMS : _zz_decode_to_execute_SRC2_CTRL_1_string = "IMS";
      Src2CtrlEnum_PC : _zz_decode_to_execute_SRC2_CTRL_1_string = "PC ";
      default : _zz_decode_to_execute_SRC2_CTRL_1_string = "???";
    endcase
  end
  always @(*) begin
    case(decode_ALU_CTRL)
      AluCtrlEnum_ADD_SUB : decode_ALU_CTRL_string = "ADD_SUB ";
      AluCtrlEnum_SLT_SLTU : decode_ALU_CTRL_string = "SLT_SLTU";
      AluCtrlEnum_BITWISE : decode_ALU_CTRL_string = "BITWISE ";
      default : decode_ALU_CTRL_string = "????????";
    endcase
  end
  always @(*) begin
    case(_zz_decode_ALU_CTRL)
      AluCtrlEnum_ADD_SUB : _zz_decode_ALU_CTRL_string = "ADD_SUB ";
      AluCtrlEnum_SLT_SLTU : _zz_decode_ALU_CTRL_string = "SLT_SLTU";
      AluCtrlEnum_BITWISE : _zz_decode_ALU_CTRL_string = "BITWISE ";
      default : _zz_decode_ALU_CTRL_string = "????????";
    endcase
  end
  always @(*) begin
    case(_zz_decode_to_execute_ALU_CTRL)
      AluCtrlEnum_ADD_SUB : _zz_decode_to_execute_ALU_CTRL_string = "ADD_SUB ";
      AluCtrlEnum_SLT_SLTU : _zz_decode_to_execute_ALU_CTRL_string = "SLT_SLTU";
      AluCtrlEnum_BITWISE : _zz_decode_to_execute_ALU_CTRL_string = "BITWISE ";
      default : _zz_decode_to_execute_ALU_CTRL_string = "????????";
    endcase
  end
  always @(*) begin
    case(_zz_decode_to_execute_ALU_CTRL_1)
      AluCtrlEnum_ADD_SUB : _zz_decode_to_execute_ALU_CTRL_1_string = "ADD_SUB ";
      AluCtrlEnum_SLT_SLTU : _zz_decode_to_execute_ALU_CTRL_1_string = "SLT_SLTU";
      AluCtrlEnum_BITWISE : _zz_decode_to_execute_ALU_CTRL_1_string = "BITWISE ";
      default : _zz_decode_to_execute_ALU_CTRL_1_string = "????????";
    endcase
  end
  always @(*) begin
    case(decode_SRC1_CTRL)
      Src1CtrlEnum_RS : decode_SRC1_CTRL_string = "RS          ";
      Src1CtrlEnum_IMU : decode_SRC1_CTRL_string = "IMU         ";
      Src1CtrlEnum_PC_INCREMENT : decode_SRC1_CTRL_string = "PC_INCREMENT";
      Src1CtrlEnum_URS1 : decode_SRC1_CTRL_string = "URS1        ";
      default : decode_SRC1_CTRL_string = "????????????";
    endcase
  end
  always @(*) begin
    case(_zz_decode_SRC1_CTRL)
      Src1CtrlEnum_RS : _zz_decode_SRC1_CTRL_string = "RS          ";
      Src1CtrlEnum_IMU : _zz_decode_SRC1_CTRL_string = "IMU         ";
      Src1CtrlEnum_PC_INCREMENT : _zz_decode_SRC1_CTRL_string = "PC_INCREMENT";
      Src1CtrlEnum_URS1 : _zz_decode_SRC1_CTRL_string = "URS1        ";
      default : _zz_decode_SRC1_CTRL_string = "????????????";
    endcase
  end
  always @(*) begin
    case(_zz_decode_to_execute_SRC1_CTRL)
      Src1CtrlEnum_RS : _zz_decode_to_execute_SRC1_CTRL_string = "RS          ";
      Src1CtrlEnum_IMU : _zz_decode_to_execute_SRC1_CTRL_string = "IMU         ";
      Src1CtrlEnum_PC_INCREMENT : _zz_decode_to_execute_SRC1_CTRL_string = "PC_INCREMENT";
      Src1CtrlEnum_URS1 : _zz_decode_to_execute_SRC1_CTRL_string = "URS1        ";
      default : _zz_decode_to_execute_SRC1_CTRL_string = "????????????";
    endcase
  end
  always @(*) begin
    case(_zz_decode_to_execute_SRC1_CTRL_1)
      Src1CtrlEnum_RS : _zz_decode_to_execute_SRC1_CTRL_1_string = "RS          ";
      Src1CtrlEnum_IMU : _zz_decode_to_execute_SRC1_CTRL_1_string = "IMU         ";
      Src1CtrlEnum_PC_INCREMENT : _zz_decode_to_execute_SRC1_CTRL_1_string = "PC_INCREMENT";
      Src1CtrlEnum_URS1 : _zz_decode_to_execute_SRC1_CTRL_1_string = "URS1        ";
      default : _zz_decode_to_execute_SRC1_CTRL_1_string = "????????????";
    endcase
  end
  always @(*) begin
    case(memory_ENV_CTRL)
      EnvCtrlEnum_NONE : memory_ENV_CTRL_string = "NONE  ";
      EnvCtrlEnum_XRET : memory_ENV_CTRL_string = "XRET  ";
      EnvCtrlEnum_ECALL : memory_ENV_CTRL_string = "ECALL ";
      EnvCtrlEnum_EBREAK : memory_ENV_CTRL_string = "EBREAK";
      default : memory_ENV_CTRL_string = "??????";
    endcase
  end
  always @(*) begin
    case(_zz_memory_ENV_CTRL)
      EnvCtrlEnum_NONE : _zz_memory_ENV_CTRL_string = "NONE  ";
      EnvCtrlEnum_XRET : _zz_memory_ENV_CTRL_string = "XRET  ";
      EnvCtrlEnum_ECALL : _zz_memory_ENV_CTRL_string = "ECALL ";
      EnvCtrlEnum_EBREAK : _zz_memory_ENV_CTRL_string = "EBREAK";
      default : _zz_memory_ENV_CTRL_string = "??????";
    endcase
  end
  always @(*) begin
    case(execute_ENV_CTRL)
      EnvCtrlEnum_NONE : execute_ENV_CTRL_string = "NONE  ";
      EnvCtrlEnum_XRET : execute_ENV_CTRL_string = "XRET  ";
      EnvCtrlEnum_ECALL : execute_ENV_CTRL_string = "ECALL ";
      EnvCtrlEnum_EBREAK : execute_ENV_CTRL_string = "EBREAK";
      default : execute_ENV_CTRL_string = "??????";
    endcase
  end
  always @(*) begin
    case(_zz_execute_ENV_CTRL)
      EnvCtrlEnum_NONE : _zz_execute_ENV_CTRL_string = "NONE  ";
      EnvCtrlEnum_XRET : _zz_execute_ENV_CTRL_string = "XRET  ";
      EnvCtrlEnum_ECALL : _zz_execute_ENV_CTRL_string = "ECALL ";
      EnvCtrlEnum_EBREAK : _zz_execute_ENV_CTRL_string = "EBREAK";
      default : _zz_execute_ENV_CTRL_string = "??????";
    endcase
  end
  always @(*) begin
    case(writeBack_ENV_CTRL)
      EnvCtrlEnum_NONE : writeBack_ENV_CTRL_string = "NONE  ";
      EnvCtrlEnum_XRET : writeBack_ENV_CTRL_string = "XRET  ";
      EnvCtrlEnum_ECALL : writeBack_ENV_CTRL_string = "ECALL ";
      EnvCtrlEnum_EBREAK : writeBack_ENV_CTRL_string = "EBREAK";
      default : writeBack_ENV_CTRL_string = "??????";
    endcase
  end
  always @(*) begin
    case(_zz_writeBack_ENV_CTRL)
      EnvCtrlEnum_NONE : _zz_writeBack_ENV_CTRL_string = "NONE  ";
      EnvCtrlEnum_XRET : _zz_writeBack_ENV_CTRL_string = "XRET  ";
      EnvCtrlEnum_ECALL : _zz_writeBack_ENV_CTRL_string = "ECALL ";
      EnvCtrlEnum_EBREAK : _zz_writeBack_ENV_CTRL_string = "EBREAK";
      default : _zz_writeBack_ENV_CTRL_string = "??????";
    endcase
  end
  always @(*) begin
    case(execute_BRANCH_CTRL)
      BranchCtrlEnum_INC : execute_BRANCH_CTRL_string = "INC ";
      BranchCtrlEnum_B : execute_BRANCH_CTRL_string = "B   ";
      BranchCtrlEnum_JAL : execute_BRANCH_CTRL_string = "JAL ";
      BranchCtrlEnum_JALR : execute_BRANCH_CTRL_string = "JALR";
      default : execute_BRANCH_CTRL_string = "????";
    endcase
  end
  always @(*) begin
    case(_zz_execute_BRANCH_CTRL)
      BranchCtrlEnum_INC : _zz_execute_BRANCH_CTRL_string = "INC ";
      BranchCtrlEnum_B : _zz_execute_BRANCH_CTRL_string = "B   ";
      BranchCtrlEnum_JAL : _zz_execute_BRANCH_CTRL_string = "JAL ";
      BranchCtrlEnum_JALR : _zz_execute_BRANCH_CTRL_string = "JALR";
      default : _zz_execute_BRANCH_CTRL_string = "????";
    endcase
  end
  always @(*) begin
    case(execute_SHIFT_CTRL)
      ShiftCtrlEnum_DISABLE_1 : execute_SHIFT_CTRL_string = "DISABLE_1";
      ShiftCtrlEnum_SLL_1 : execute_SHIFT_CTRL_string = "SLL_1    ";
      ShiftCtrlEnum_SRL_1 : execute_SHIFT_CTRL_string = "SRL_1    ";
      ShiftCtrlEnum_SRA_1 : execute_SHIFT_CTRL_string = "SRA_1    ";
      default : execute_SHIFT_CTRL_string = "?????????";
    endcase
  end
  always @(*) begin
    case(_zz_execute_SHIFT_CTRL)
      ShiftCtrlEnum_DISABLE_1 : _zz_execute_SHIFT_CTRL_string = "DISABLE_1";
      ShiftCtrlEnum_SLL_1 : _zz_execute_SHIFT_CTRL_string = "SLL_1    ";
      ShiftCtrlEnum_SRL_1 : _zz_execute_SHIFT_CTRL_string = "SRL_1    ";
      ShiftCtrlEnum_SRA_1 : _zz_execute_SHIFT_CTRL_string = "SRA_1    ";
      default : _zz_execute_SHIFT_CTRL_string = "?????????";
    endcase
  end
  always @(*) begin
    case(execute_SRC2_CTRL)
      Src2CtrlEnum_RS : execute_SRC2_CTRL_string = "RS ";
      Src2CtrlEnum_IMI : execute_SRC2_CTRL_string = "IMI";
      Src2CtrlEnum_IMS : execute_SRC2_CTRL_string = "IMS";
      Src2CtrlEnum_PC : execute_SRC2_CTRL_string = "PC ";
      default : execute_SRC2_CTRL_string = "???";
    endcase
  end
  always @(*) begin
    case(_zz_execute_SRC2_CTRL)
      Src2CtrlEnum_RS : _zz_execute_SRC2_CTRL_string = "RS ";
      Src2CtrlEnum_IMI : _zz_execute_SRC2_CTRL_string = "IMI";
      Src2CtrlEnum_IMS : _zz_execute_SRC2_CTRL_string = "IMS";
      Src2CtrlEnum_PC : _zz_execute_SRC2_CTRL_string = "PC ";
      default : _zz_execute_SRC2_CTRL_string = "???";
    endcase
  end
  always @(*) begin
    case(execute_SRC1_CTRL)
      Src1CtrlEnum_RS : execute_SRC1_CTRL_string = "RS          ";
      Src1CtrlEnum_IMU : execute_SRC1_CTRL_string = "IMU         ";
      Src1CtrlEnum_PC_INCREMENT : execute_SRC1_CTRL_string = "PC_INCREMENT";
      Src1CtrlEnum_URS1 : execute_SRC1_CTRL_string = "URS1        ";
      default : execute_SRC1_CTRL_string = "????????????";
    endcase
  end
  always @(*) begin
    case(_zz_execute_SRC1_CTRL)
      Src1CtrlEnum_RS : _zz_execute_SRC1_CTRL_string = "RS          ";
      Src1CtrlEnum_IMU : _zz_execute_SRC1_CTRL_string = "IMU         ";
      Src1CtrlEnum_PC_INCREMENT : _zz_execute_SRC1_CTRL_string = "PC_INCREMENT";
      Src1CtrlEnum_URS1 : _zz_execute_SRC1_CTRL_string = "URS1        ";
      default : _zz_execute_SRC1_CTRL_string = "????????????";
    endcase
  end
  always @(*) begin
    case(execute_ALU_CTRL)
      AluCtrlEnum_ADD_SUB : execute_ALU_CTRL_string = "ADD_SUB ";
      AluCtrlEnum_SLT_SLTU : execute_ALU_CTRL_string = "SLT_SLTU";
      AluCtrlEnum_BITWISE : execute_ALU_CTRL_string = "BITWISE ";
      default : execute_ALU_CTRL_string = "????????";
    endcase
  end
  always @(*) begin
    case(_zz_execute_ALU_CTRL)
      AluCtrlEnum_ADD_SUB : _zz_execute_ALU_CTRL_string = "ADD_SUB ";
      AluCtrlEnum_SLT_SLTU : _zz_execute_ALU_CTRL_string = "SLT_SLTU";
      AluCtrlEnum_BITWISE : _zz_execute_ALU_CTRL_string = "BITWISE ";
      default : _zz_execute_ALU_CTRL_string = "????????";
    endcase
  end
  always @(*) begin
    case(execute_ALU_BITWISE_CTRL)
      AluBitwiseCtrlEnum_XOR_1 : execute_ALU_BITWISE_CTRL_string = "XOR_1";
      AluBitwiseCtrlEnum_OR_1 : execute_ALU_BITWISE_CTRL_string = "OR_1 ";
      AluBitwiseCtrlEnum_AND_1 : execute_ALU_BITWISE_CTRL_string = "AND_1";
      default : execute_ALU_BITWISE_CTRL_string = "?????";
    endcase
  end
  always @(*) begin
    case(_zz_execute_ALU_BITWISE_CTRL)
      AluBitwiseCtrlEnum_XOR_1 : _zz_execute_ALU_BITWISE_CTRL_string = "XOR_1";
      AluBitwiseCtrlEnum_OR_1 : _zz_execute_ALU_BITWISE_CTRL_string = "OR_1 ";
      AluBitwiseCtrlEnum_AND_1 : _zz_execute_ALU_BITWISE_CTRL_string = "AND_1";
      default : _zz_execute_ALU_BITWISE_CTRL_string = "?????";
    endcase
  end
  always @(*) begin
    case(_zz_decode_ENV_CTRL_1)
      EnvCtrlEnum_NONE : _zz_decode_ENV_CTRL_1_string = "NONE  ";
      EnvCtrlEnum_XRET : _zz_decode_ENV_CTRL_1_string = "XRET  ";
      EnvCtrlEnum_ECALL : _zz_decode_ENV_CTRL_1_string = "ECALL ";
      EnvCtrlEnum_EBREAK : _zz_decode_ENV_CTRL_1_string = "EBREAK";
      default : _zz_decode_ENV_CTRL_1_string = "??????";
    endcase
  end
  always @(*) begin
    case(_zz_decode_BRANCH_CTRL)
      BranchCtrlEnum_INC : _zz_decode_BRANCH_CTRL_string = "INC ";
      BranchCtrlEnum_B : _zz_decode_BRANCH_CTRL_string = "B   ";
      BranchCtrlEnum_JAL : _zz_decode_BRANCH_CTRL_string = "JAL ";
      BranchCtrlEnum_JALR : _zz_decode_BRANCH_CTRL_string = "JALR";
      default : _zz_decode_BRANCH_CTRL_string = "????";
    endcase
  end
  always @(*) begin
    case(_zz_decode_SHIFT_CTRL_1)
      ShiftCtrlEnum_DISABLE_1 : _zz_decode_SHIFT_CTRL_1_string = "DISABLE_1";
      ShiftCtrlEnum_SLL_1 : _zz_decode_SHIFT_CTRL_1_string = "SLL_1    ";
      ShiftCtrlEnum_SRL_1 : _zz_decode_SHIFT_CTRL_1_string = "SRL_1    ";
      ShiftCtrlEnum_SRA_1 : _zz_decode_SHIFT_CTRL_1_string = "SRA_1    ";
      default : _zz_decode_SHIFT_CTRL_1_string = "?????????";
    endcase
  end
  always @(*) begin
    case(_zz_decode_ALU_BITWISE_CTRL_1)
      AluBitwiseCtrlEnum_XOR_1 : _zz_decode_ALU_BITWISE_CTRL_1_string = "XOR_1";
      AluBitwiseCtrlEnum_OR_1 : _zz_decode_ALU_BITWISE_CTRL_1_string = "OR_1 ";
      AluBitwiseCtrlEnum_AND_1 : _zz_decode_ALU_BITWISE_CTRL_1_string = "AND_1";
      default : _zz_decode_ALU_BITWISE_CTRL_1_string = "?????";
    endcase
  end
  always @(*) begin
    case(_zz_decode_SRC2_CTRL_1)
      Src2CtrlEnum_RS : _zz_decode_SRC2_CTRL_1_string = "RS ";
      Src2CtrlEnum_IMI : _zz_decode_SRC2_CTRL_1_string = "IMI";
      Src2CtrlEnum_IMS : _zz_decode_SRC2_CTRL_1_string = "IMS";
      Src2CtrlEnum_PC : _zz_decode_SRC2_CTRL_1_string = "PC ";
      default : _zz_decode_SRC2_CTRL_1_string = "???";
    endcase
  end
  always @(*) begin
    case(_zz_decode_ALU_CTRL_1)
      AluCtrlEnum_ADD_SUB : _zz_decode_ALU_CTRL_1_string = "ADD_SUB ";
      AluCtrlEnum_SLT_SLTU : _zz_decode_ALU_CTRL_1_string = "SLT_SLTU";
      AluCtrlEnum_BITWISE : _zz_decode_ALU_CTRL_1_string = "BITWISE ";
      default : _zz_decode_ALU_CTRL_1_string = "????????";
    endcase
  end
  always @(*) begin
    case(_zz_decode_SRC1_CTRL_1)
      Src1CtrlEnum_RS : _zz_decode_SRC1_CTRL_1_string = "RS          ";
      Src1CtrlEnum_IMU : _zz_decode_SRC1_CTRL_1_string = "IMU         ";
      Src1CtrlEnum_PC_INCREMENT : _zz_decode_SRC1_CTRL_1_string = "PC_INCREMENT";
      Src1CtrlEnum_URS1 : _zz_decode_SRC1_CTRL_1_string = "URS1        ";
      default : _zz_decode_SRC1_CTRL_1_string = "????????????";
    endcase
  end
  always @(*) begin
    case(decode_BRANCH_CTRL)
      BranchCtrlEnum_INC : decode_BRANCH_CTRL_string = "INC ";
      BranchCtrlEnum_B : decode_BRANCH_CTRL_string = "B   ";
      BranchCtrlEnum_JAL : decode_BRANCH_CTRL_string = "JAL ";
      BranchCtrlEnum_JALR : decode_BRANCH_CTRL_string = "JALR";
      default : decode_BRANCH_CTRL_string = "????";
    endcase
  end
  always @(*) begin
    case(_zz_decode_BRANCH_CTRL_1)
      BranchCtrlEnum_INC : _zz_decode_BRANCH_CTRL_1_string = "INC ";
      BranchCtrlEnum_B : _zz_decode_BRANCH_CTRL_1_string = "B   ";
      BranchCtrlEnum_JAL : _zz_decode_BRANCH_CTRL_1_string = "JAL ";
      BranchCtrlEnum_JALR : _zz_decode_BRANCH_CTRL_1_string = "JALR";
      default : _zz_decode_BRANCH_CTRL_1_string = "????";
    endcase
  end
  always @(*) begin
    case(debugBus_dmToHart_payload_op)
      DebugDmToHartOp_DATA : debugBus_dmToHart_payload_op_string = "DATA     ";
      DebugDmToHartOp_EXECUTE : debugBus_dmToHart_payload_op_string = "EXECUTE  ";
      DebugDmToHartOp_REG_WRITE : debugBus_dmToHart_payload_op_string = "REG_WRITE";
      DebugDmToHartOp_REG_READ : debugBus_dmToHart_payload_op_string = "REG_READ ";
      default : debugBus_dmToHart_payload_op_string = "?????????";
    endcase
  end
  always @(*) begin
    case(_zz_decode_SRC1_CTRL_2)
      Src1CtrlEnum_RS : _zz_decode_SRC1_CTRL_2_string = "RS          ";
      Src1CtrlEnum_IMU : _zz_decode_SRC1_CTRL_2_string = "IMU         ";
      Src1CtrlEnum_PC_INCREMENT : _zz_decode_SRC1_CTRL_2_string = "PC_INCREMENT";
      Src1CtrlEnum_URS1 : _zz_decode_SRC1_CTRL_2_string = "URS1        ";
      default : _zz_decode_SRC1_CTRL_2_string = "????????????";
    endcase
  end
  always @(*) begin
    case(_zz_decode_ALU_CTRL_2)
      AluCtrlEnum_ADD_SUB : _zz_decode_ALU_CTRL_2_string = "ADD_SUB ";
      AluCtrlEnum_SLT_SLTU : _zz_decode_ALU_CTRL_2_string = "SLT_SLTU";
      AluCtrlEnum_BITWISE : _zz_decode_ALU_CTRL_2_string = "BITWISE ";
      default : _zz_decode_ALU_CTRL_2_string = "????????";
    endcase
  end
  always @(*) begin
    case(_zz_decode_SRC2_CTRL_2)
      Src2CtrlEnum_RS : _zz_decode_SRC2_CTRL_2_string = "RS ";
      Src2CtrlEnum_IMI : _zz_decode_SRC2_CTRL_2_string = "IMI";
      Src2CtrlEnum_IMS : _zz_decode_SRC2_CTRL_2_string = "IMS";
      Src2CtrlEnum_PC : _zz_decode_SRC2_CTRL_2_string = "PC ";
      default : _zz_decode_SRC2_CTRL_2_string = "???";
    endcase
  end
  always @(*) begin
    case(_zz_decode_ALU_BITWISE_CTRL_2)
      AluBitwiseCtrlEnum_XOR_1 : _zz_decode_ALU_BITWISE_CTRL_2_string = "XOR_1";
      AluBitwiseCtrlEnum_OR_1 : _zz_decode_ALU_BITWISE_CTRL_2_string = "OR_1 ";
      AluBitwiseCtrlEnum_AND_1 : _zz_decode_ALU_BITWISE_CTRL_2_string = "AND_1";
      default : _zz_decode_ALU_BITWISE_CTRL_2_string = "?????";
    endcase
  end
  always @(*) begin
    case(_zz_decode_SHIFT_CTRL_2)
      ShiftCtrlEnum_DISABLE_1 : _zz_decode_SHIFT_CTRL_2_string = "DISABLE_1";
      ShiftCtrlEnum_SLL_1 : _zz_decode_SHIFT_CTRL_2_string = "SLL_1    ";
      ShiftCtrlEnum_SRL_1 : _zz_decode_SHIFT_CTRL_2_string = "SRL_1    ";
      ShiftCtrlEnum_SRA_1 : _zz_decode_SHIFT_CTRL_2_string = "SRA_1    ";
      default : _zz_decode_SHIFT_CTRL_2_string = "?????????";
    endcase
  end
  always @(*) begin
    case(_zz_decode_BRANCH_CTRL_2)
      BranchCtrlEnum_INC : _zz_decode_BRANCH_CTRL_2_string = "INC ";
      BranchCtrlEnum_B : _zz_decode_BRANCH_CTRL_2_string = "B   ";
      BranchCtrlEnum_JAL : _zz_decode_BRANCH_CTRL_2_string = "JAL ";
      BranchCtrlEnum_JALR : _zz_decode_BRANCH_CTRL_2_string = "JALR";
      default : _zz_decode_BRANCH_CTRL_2_string = "????";
    endcase
  end
  always @(*) begin
    case(_zz_decode_ENV_CTRL_2)
      EnvCtrlEnum_NONE : _zz_decode_ENV_CTRL_2_string = "NONE  ";
      EnvCtrlEnum_XRET : _zz_decode_ENV_CTRL_2_string = "XRET  ";
      EnvCtrlEnum_ECALL : _zz_decode_ENV_CTRL_2_string = "ECALL ";
      EnvCtrlEnum_EBREAK : _zz_decode_ENV_CTRL_2_string = "EBREAK";
      default : _zz_decode_ENV_CTRL_2_string = "??????";
    endcase
  end
  always @(*) begin
    case(CsrPlugin_inject_cmd_payload_op)
      DebugDmToHartOp_DATA : CsrPlugin_inject_cmd_payload_op_string = "DATA     ";
      DebugDmToHartOp_EXECUTE : CsrPlugin_inject_cmd_payload_op_string = "EXECUTE  ";
      DebugDmToHartOp_REG_WRITE : CsrPlugin_inject_cmd_payload_op_string = "REG_WRITE";
      DebugDmToHartOp_REG_READ : CsrPlugin_inject_cmd_payload_op_string = "REG_READ ";
      default : CsrPlugin_inject_cmd_payload_op_string = "?????????";
    endcase
  end
  always @(*) begin
    case(CsrPlugin_inject_cmd_toStream_payload_op)
      DebugDmToHartOp_DATA : CsrPlugin_inject_cmd_toStream_payload_op_string = "DATA     ";
      DebugDmToHartOp_EXECUTE : CsrPlugin_inject_cmd_toStream_payload_op_string = "EXECUTE  ";
      DebugDmToHartOp_REG_WRITE : CsrPlugin_inject_cmd_toStream_payload_op_string = "REG_WRITE";
      DebugDmToHartOp_REG_READ : CsrPlugin_inject_cmd_toStream_payload_op_string = "REG_READ ";
      default : CsrPlugin_inject_cmd_toStream_payload_op_string = "?????????";
    endcase
  end
  always @(*) begin
    case(CsrPlugin_inject_buffer_payload_op)
      DebugDmToHartOp_DATA : CsrPlugin_inject_buffer_payload_op_string = "DATA     ";
      DebugDmToHartOp_EXECUTE : CsrPlugin_inject_buffer_payload_op_string = "EXECUTE  ";
      DebugDmToHartOp_REG_WRITE : CsrPlugin_inject_buffer_payload_op_string = "REG_WRITE";
      DebugDmToHartOp_REG_READ : CsrPlugin_inject_buffer_payload_op_string = "REG_READ ";
      default : CsrPlugin_inject_buffer_payload_op_string = "?????????";
    endcase
  end
  always @(*) begin
    case(CsrPlugin_inject_cmd_toStream_rData_op)
      DebugDmToHartOp_DATA : CsrPlugin_inject_cmd_toStream_rData_op_string = "DATA     ";
      DebugDmToHartOp_EXECUTE : CsrPlugin_inject_cmd_toStream_rData_op_string = "EXECUTE  ";
      DebugDmToHartOp_REG_WRITE : CsrPlugin_inject_cmd_toStream_rData_op_string = "REG_WRITE";
      DebugDmToHartOp_REG_READ : CsrPlugin_inject_cmd_toStream_rData_op_string = "REG_READ ";
      default : CsrPlugin_inject_cmd_toStream_rData_op_string = "?????????";
    endcase
  end
  always @(*) begin
    case(CsrPlugin_dcsr_stepLogic_stateReg)
      CsrPlugin_dcsr_stepLogic_BOOT : CsrPlugin_dcsr_stepLogic_stateReg_string = "BOOT  ";
      CsrPlugin_dcsr_stepLogic_IDLE : CsrPlugin_dcsr_stepLogic_stateReg_string = "IDLE  ";
      CsrPlugin_dcsr_stepLogic_SINGLE : CsrPlugin_dcsr_stepLogic_stateReg_string = "SINGLE";
      CsrPlugin_dcsr_stepLogic_WAIT_1 : CsrPlugin_dcsr_stepLogic_stateReg_string = "WAIT_1";
      default : CsrPlugin_dcsr_stepLogic_stateReg_string = "??????";
    endcase
  end
  always @(*) begin
    case(CsrPlugin_dcsr_stepLogic_stateNext)
      CsrPlugin_dcsr_stepLogic_BOOT : CsrPlugin_dcsr_stepLogic_stateNext_string = "BOOT  ";
      CsrPlugin_dcsr_stepLogic_IDLE : CsrPlugin_dcsr_stepLogic_stateNext_string = "IDLE  ";
      CsrPlugin_dcsr_stepLogic_SINGLE : CsrPlugin_dcsr_stepLogic_stateNext_string = "SINGLE";
      CsrPlugin_dcsr_stepLogic_WAIT_1 : CsrPlugin_dcsr_stepLogic_stateNext_string = "WAIT_1";
      default : CsrPlugin_dcsr_stepLogic_stateNext_string = "??????";
    endcase
  end
  always @(*) begin
    case(io_harts_0_dmToHart_regNext_payload_op)
      DebugDmToHartOp_DATA : io_harts_0_dmToHart_regNext_payload_op_string = "DATA     ";
      DebugDmToHartOp_EXECUTE : io_harts_0_dmToHart_regNext_payload_op_string = "EXECUTE  ";
      DebugDmToHartOp_REG_WRITE : io_harts_0_dmToHart_regNext_payload_op_string = "REG_WRITE";
      DebugDmToHartOp_REG_READ : io_harts_0_dmToHart_regNext_payload_op_string = "REG_READ ";
      default : io_harts_0_dmToHart_regNext_payload_op_string = "?????????";
    endcase
  end
  always @(*) begin
    case(decode_to_execute_SRC1_CTRL)
      Src1CtrlEnum_RS : decode_to_execute_SRC1_CTRL_string = "RS          ";
      Src1CtrlEnum_IMU : decode_to_execute_SRC1_CTRL_string = "IMU         ";
      Src1CtrlEnum_PC_INCREMENT : decode_to_execute_SRC1_CTRL_string = "PC_INCREMENT";
      Src1CtrlEnum_URS1 : decode_to_execute_SRC1_CTRL_string = "URS1        ";
      default : decode_to_execute_SRC1_CTRL_string = "????????????";
    endcase
  end
  always @(*) begin
    case(decode_to_execute_ALU_CTRL)
      AluCtrlEnum_ADD_SUB : decode_to_execute_ALU_CTRL_string = "ADD_SUB ";
      AluCtrlEnum_SLT_SLTU : decode_to_execute_ALU_CTRL_string = "SLT_SLTU";
      AluCtrlEnum_BITWISE : decode_to_execute_ALU_CTRL_string = "BITWISE ";
      default : decode_to_execute_ALU_CTRL_string = "????????";
    endcase
  end
  always @(*) begin
    case(decode_to_execute_SRC2_CTRL)
      Src2CtrlEnum_RS : decode_to_execute_SRC2_CTRL_string = "RS ";
      Src2CtrlEnum_IMI : decode_to_execute_SRC2_CTRL_string = "IMI";
      Src2CtrlEnum_IMS : decode_to_execute_SRC2_CTRL_string = "IMS";
      Src2CtrlEnum_PC : decode_to_execute_SRC2_CTRL_string = "PC ";
      default : decode_to_execute_SRC2_CTRL_string = "???";
    endcase
  end
  always @(*) begin
    case(decode_to_execute_ALU_BITWISE_CTRL)
      AluBitwiseCtrlEnum_XOR_1 : decode_to_execute_ALU_BITWISE_CTRL_string = "XOR_1";
      AluBitwiseCtrlEnum_OR_1 : decode_to_execute_ALU_BITWISE_CTRL_string = "OR_1 ";
      AluBitwiseCtrlEnum_AND_1 : decode_to_execute_ALU_BITWISE_CTRL_string = "AND_1";
      default : decode_to_execute_ALU_BITWISE_CTRL_string = "?????";
    endcase
  end
  always @(*) begin
    case(decode_to_execute_SHIFT_CTRL)
      ShiftCtrlEnum_DISABLE_1 : decode_to_execute_SHIFT_CTRL_string = "DISABLE_1";
      ShiftCtrlEnum_SLL_1 : decode_to_execute_SHIFT_CTRL_string = "SLL_1    ";
      ShiftCtrlEnum_SRL_1 : decode_to_execute_SHIFT_CTRL_string = "SRL_1    ";
      ShiftCtrlEnum_SRA_1 : decode_to_execute_SHIFT_CTRL_string = "SRA_1    ";
      default : decode_to_execute_SHIFT_CTRL_string = "?????????";
    endcase
  end
  always @(*) begin
    case(decode_to_execute_BRANCH_CTRL)
      BranchCtrlEnum_INC : decode_to_execute_BRANCH_CTRL_string = "INC ";
      BranchCtrlEnum_B : decode_to_execute_BRANCH_CTRL_string = "B   ";
      BranchCtrlEnum_JAL : decode_to_execute_BRANCH_CTRL_string = "JAL ";
      BranchCtrlEnum_JALR : decode_to_execute_BRANCH_CTRL_string = "JALR";
      default : decode_to_execute_BRANCH_CTRL_string = "????";
    endcase
  end
  always @(*) begin
    case(decode_to_execute_ENV_CTRL)
      EnvCtrlEnum_NONE : decode_to_execute_ENV_CTRL_string = "NONE  ";
      EnvCtrlEnum_XRET : decode_to_execute_ENV_CTRL_string = "XRET  ";
      EnvCtrlEnum_ECALL : decode_to_execute_ENV_CTRL_string = "ECALL ";
      EnvCtrlEnum_EBREAK : decode_to_execute_ENV_CTRL_string = "EBREAK";
      default : decode_to_execute_ENV_CTRL_string = "??????";
    endcase
  end
  always @(*) begin
    case(execute_to_memory_ENV_CTRL)
      EnvCtrlEnum_NONE : execute_to_memory_ENV_CTRL_string = "NONE  ";
      EnvCtrlEnum_XRET : execute_to_memory_ENV_CTRL_string = "XRET  ";
      EnvCtrlEnum_ECALL : execute_to_memory_ENV_CTRL_string = "ECALL ";
      EnvCtrlEnum_EBREAK : execute_to_memory_ENV_CTRL_string = "EBREAK";
      default : execute_to_memory_ENV_CTRL_string = "??????";
    endcase
  end
  always @(*) begin
    case(memory_to_writeBack_ENV_CTRL)
      EnvCtrlEnum_NONE : memory_to_writeBack_ENV_CTRL_string = "NONE  ";
      EnvCtrlEnum_XRET : memory_to_writeBack_ENV_CTRL_string = "XRET  ";
      EnvCtrlEnum_ECALL : memory_to_writeBack_ENV_CTRL_string = "ECALL ";
      EnvCtrlEnum_EBREAK : memory_to_writeBack_ENV_CTRL_string = "EBREAK";
      default : memory_to_writeBack_ENV_CTRL_string = "??????";
    endcase
  end
  `endif

  always @(*) begin
    CsrPlugin_running_aheadValue = CsrPlugin_running;
    if(CsrPlugin_trigger_decodeBreak_enabled) begin
      if(CsrPlugin_trigger_decodeBreak_timeout_state) begin
        CsrPlugin_running_aheadValue = 1'b0;
      end
    end
    if(when_CsrPlugin_l1390) begin
      if(!when_CsrPlugin_l1398) begin
        CsrPlugin_running_aheadValue = 1'b0;
      end
    end
    if(CsrPlugin_doResume) begin
      CsrPlugin_running_aheadValue = 1'b1;
    end
  end

  assign memory_MEMORY_READ_DATA = dBus_rsp_data;
  assign execute_BRANCH_CALC = {execute_BranchPlugin_branchAdder[31 : 1],1'b0};
  assign execute_BRANCH_DO = ((execute_PREDICTION_HAD_BRANCHED1 != execute_BRANCH_COND_RESULT) || execute_BranchPlugin_missAlignedTarget);
  assign writeBack_REGFILE_WRITE_DATA = memory_to_writeBack_REGFILE_WRITE_DATA;
  assign execute_REGFILE_WRITE_DATA = _zz_execute_REGFILE_WRITE_DATA;
  assign memory_MEMORY_ADDRESS_LOW = execute_to_memory_MEMORY_ADDRESS_LOW;
  assign execute_MEMORY_ADDRESS_LOW = dBus_cmd_payload_address[1 : 0];
  assign decode_CSR_READ_OPCODE = (decode_INSTRUCTION[13 : 7] != 7'h20);
  assign decode_CSR_WRITE_OPCODE = (! (((decode_INSTRUCTION[14 : 13] == 2'b01) && (decode_INSTRUCTION[19 : 15] == 5'h0)) || ((decode_INSTRUCTION[14 : 13] == 2'b11) && (decode_INSTRUCTION[19 : 15] == 5'h0))));
  assign decode_PREDICTION_HAD_BRANCHED1 = IBusCachedPlugin_decodePrediction_cmd_hadBranch;
  assign decode_SRC2_FORCE_ZERO = (decode_SRC_ADD_ZERO && (! decode_SRC_USE_SUB_LESS));
  assign decode_IS_DIV = _zz_decode_IS_DIV[30];
  assign decode_IS_RS2_SIGNED = _zz_decode_IS_DIV[29];
  assign decode_IS_RS1_SIGNED = _zz_decode_IS_DIV[28];
  assign decode_IS_MUL = _zz_decode_IS_DIV[27];
  assign _zz_memory_to_writeBack_ENV_CTRL = _zz_memory_to_writeBack_ENV_CTRL_1;
  assign _zz_execute_to_memory_ENV_CTRL = _zz_execute_to_memory_ENV_CTRL_1;
  assign decode_ENV_CTRL = _zz_decode_ENV_CTRL;
  assign _zz_decode_to_execute_ENV_CTRL = _zz_decode_to_execute_ENV_CTRL_1;
  assign decode_IS_CSR = _zz_decode_IS_DIV[24];
  assign _zz_decode_to_execute_BRANCH_CTRL = _zz_decode_to_execute_BRANCH_CTRL_1;
  assign decode_SHIFT_CTRL = _zz_decode_SHIFT_CTRL;
  assign _zz_decode_to_execute_SHIFT_CTRL = _zz_decode_to_execute_SHIFT_CTRL_1;
  assign decode_ALU_BITWISE_CTRL = _zz_decode_ALU_BITWISE_CTRL;
  assign _zz_decode_to_execute_ALU_BITWISE_CTRL = _zz_decode_to_execute_ALU_BITWISE_CTRL_1;
  assign decode_SRC_LESS_UNSIGNED = _zz_decode_IS_DIV[16];
  assign decode_MEMORY_STORE = _zz_decode_IS_DIV[13];
  assign execute_BYPASSABLE_MEMORY_STAGE = decode_to_execute_BYPASSABLE_MEMORY_STAGE;
  assign decode_BYPASSABLE_MEMORY_STAGE = _zz_decode_IS_DIV[12];
  assign decode_BYPASSABLE_EXECUTE_STAGE = _zz_decode_IS_DIV[11];
  assign decode_SRC2_CTRL = _zz_decode_SRC2_CTRL;
  assign _zz_decode_to_execute_SRC2_CTRL = _zz_decode_to_execute_SRC2_CTRL_1;
  assign decode_ALU_CTRL = _zz_decode_ALU_CTRL;
  assign _zz_decode_to_execute_ALU_CTRL = _zz_decode_to_execute_ALU_CTRL_1;
  assign decode_MEMORY_ENABLE = _zz_decode_IS_DIV[4];
  assign decode_SRC1_CTRL = _zz_decode_SRC1_CTRL;
  assign _zz_decode_to_execute_SRC1_CTRL = _zz_decode_to_execute_SRC1_CTRL_1;
  assign writeBack_FORMAL_PC_NEXT = memory_to_writeBack_FORMAL_PC_NEXT;
  assign memory_FORMAL_PC_NEXT = execute_to_memory_FORMAL_PC_NEXT;
  assign execute_FORMAL_PC_NEXT = decode_to_execute_FORMAL_PC_NEXT;
  assign decode_FORMAL_PC_NEXT = (decode_PC + 32'h00000004);
  assign memory_PC = execute_to_memory_PC;
  assign execute_IS_RS1_SIGNED = decode_to_execute_IS_RS1_SIGNED;
  assign execute_IS_DIV = decode_to_execute_IS_DIV;
  assign execute_IS_MUL = decode_to_execute_IS_MUL;
  assign execute_IS_RS2_SIGNED = decode_to_execute_IS_RS2_SIGNED;
  assign memory_IS_DIV = execute_to_memory_IS_DIV;
  assign memory_IS_MUL = execute_to_memory_IS_MUL;
  assign execute_CSR_READ_OPCODE = decode_to_execute_CSR_READ_OPCODE;
  assign execute_CSR_WRITE_OPCODE = decode_to_execute_CSR_WRITE_OPCODE;
  assign execute_IS_CSR = decode_to_execute_IS_CSR;
  assign memory_ENV_CTRL = _zz_memory_ENV_CTRL;
  assign execute_ENV_CTRL = _zz_execute_ENV_CTRL;
  assign writeBack_ENV_CTRL = _zz_writeBack_ENV_CTRL;
  assign memory_BRANCH_CALC = execute_to_memory_BRANCH_CALC;
  assign memory_BRANCH_DO = execute_to_memory_BRANCH_DO;
  assign execute_PC = decode_to_execute_PC;
  assign execute_PREDICTION_HAD_BRANCHED1 = decode_to_execute_PREDICTION_HAD_BRANCHED1;
  assign execute_RS1 = decode_to_execute_RS1;
  assign execute_BRANCH_COND_RESULT = _zz_execute_BRANCH_COND_RESULT_1;
  assign execute_BRANCH_CTRL = _zz_execute_BRANCH_CTRL;
  assign decode_RS2_USE = _zz_decode_IS_DIV[15];
  assign decode_RS1_USE = _zz_decode_IS_DIV[5];
  assign execute_REGFILE_WRITE_VALID = decode_to_execute_REGFILE_WRITE_VALID;
  assign execute_BYPASSABLE_EXECUTE_STAGE = decode_to_execute_BYPASSABLE_EXECUTE_STAGE;
  always @(*) begin
    _zz_decode_RS2 = memory_REGFILE_WRITE_DATA;
    if(when_MulDivIterativePlugin_l96) begin
      _zz_decode_RS2 = ((memory_INSTRUCTION[13 : 12] == 2'b00) ? memory_MulDivIterativePlugin_accumulator[31 : 0] : memory_MulDivIterativePlugin_accumulator[63 : 32]);
    end
    if(when_MulDivIterativePlugin_l128) begin
      _zz_decode_RS2 = memory_MulDivIterativePlugin_div_result;
    end
  end

  assign memory_REGFILE_WRITE_VALID = execute_to_memory_REGFILE_WRITE_VALID;
  assign memory_INSTRUCTION = execute_to_memory_INSTRUCTION;
  assign memory_BYPASSABLE_MEMORY_STAGE = execute_to_memory_BYPASSABLE_MEMORY_STAGE;
  assign writeBack_REGFILE_WRITE_VALID = memory_to_writeBack_REGFILE_WRITE_VALID;
  always @(*) begin
    decode_RS2 = decode_RegFilePlugin_rs2Data;
    if(HazardSimplePlugin_writeBackBuffer_valid) begin
      if(HazardSimplePlugin_addr1Match) begin
        decode_RS2 = HazardSimplePlugin_writeBackBuffer_payload_data;
      end
    end
    if(when_HazardSimplePlugin_l45) begin
      if(when_HazardSimplePlugin_l47) begin
        if(when_HazardSimplePlugin_l51) begin
          decode_RS2 = _zz_decode_RS2_2;
        end
      end
    end
    if(when_HazardSimplePlugin_l45_1) begin
      if(memory_BYPASSABLE_MEMORY_STAGE) begin
        if(when_HazardSimplePlugin_l51_1) begin
          decode_RS2 = _zz_decode_RS2;
        end
      end
    end
    if(when_HazardSimplePlugin_l45_2) begin
      if(execute_BYPASSABLE_EXECUTE_STAGE) begin
        if(when_HazardSimplePlugin_l51_2) begin
          decode_RS2 = _zz_decode_RS2_1;
        end
      end
    end
  end

  always @(*) begin
    decode_RS1 = decode_RegFilePlugin_rs1Data;
    if(HazardSimplePlugin_writeBackBuffer_valid) begin
      if(HazardSimplePlugin_addr0Match) begin
        decode_RS1 = HazardSimplePlugin_writeBackBuffer_payload_data;
      end
    end
    if(when_HazardSimplePlugin_l45) begin
      if(when_HazardSimplePlugin_l47) begin
        if(when_HazardSimplePlugin_l48) begin
          decode_RS1 = _zz_decode_RS2_2;
        end
      end
    end
    if(when_HazardSimplePlugin_l45_1) begin
      if(memory_BYPASSABLE_MEMORY_STAGE) begin
        if(when_HazardSimplePlugin_l48_1) begin
          decode_RS1 = _zz_decode_RS2;
        end
      end
    end
    if(when_HazardSimplePlugin_l45_2) begin
      if(execute_BYPASSABLE_EXECUTE_STAGE) begin
        if(when_HazardSimplePlugin_l48_2) begin
          decode_RS1 = _zz_decode_RS2_1;
        end
      end
    end
  end

  always @(*) begin
    _zz_decode_RS2_1 = execute_REGFILE_WRITE_DATA;
    if(when_ShiftPlugins_l169) begin
      _zz_decode_RS2_1 = _zz_decode_RS2_3;
    end
    if(when_CsrPlugin_l1587) begin
      _zz_decode_RS2_1 = CsrPlugin_csrMapping_readDataSignal;
    end
  end

  assign execute_SHIFT_CTRL = _zz_execute_SHIFT_CTRL;
  assign execute_SRC_LESS_UNSIGNED = decode_to_execute_SRC_LESS_UNSIGNED;
  assign execute_SRC2_FORCE_ZERO = decode_to_execute_SRC2_FORCE_ZERO;
  assign execute_SRC_USE_SUB_LESS = decode_to_execute_SRC_USE_SUB_LESS;
  assign _zz_execute_to_memory_PC = execute_PC;
  assign execute_SRC2_CTRL = _zz_execute_SRC2_CTRL;
  assign execute_SRC1_CTRL = _zz_execute_SRC1_CTRL;
  assign decode_SRC_USE_SUB_LESS = _zz_decode_IS_DIV[3];
  assign decode_SRC_ADD_ZERO = _zz_decode_IS_DIV[19];
  assign execute_SRC_ADD_SUB = execute_SrcPlugin_addSub;
  assign execute_SRC_LESS = execute_SrcPlugin_less;
  assign execute_ALU_CTRL = _zz_execute_ALU_CTRL;
  assign execute_SRC2 = _zz_execute_SRC2_4;
  assign execute_SRC1 = _zz_execute_SRC1;
  assign execute_ALU_BITWISE_CTRL = _zz_execute_ALU_BITWISE_CTRL;
  assign _zz_lastStageRegFileWrite_payload_address = writeBack_INSTRUCTION;
  assign _zz_lastStageRegFileWrite_valid = writeBack_REGFILE_WRITE_VALID;
  always @(*) begin
    _zz_1 = 1'b0;
    if(lastStageRegFileWrite_valid) begin
      _zz_1 = 1'b1;
    end
  end

  assign decode_INSTRUCTION_ANTICIPATED = (decode_arbitration_isStuck ? decode_INSTRUCTION : IBusCachedPlugin_cache_io_cpu_fetch_data);
  always @(*) begin
    decode_REGFILE_WRITE_VALID = _zz_decode_IS_DIV[10];
    if(when_RegFilePlugin_l63) begin
      decode_REGFILE_WRITE_VALID = 1'b0;
    end
  end

  assign decode_LEGAL_INSTRUCTION = (|{((decode_INSTRUCTION & 32'h0000005f) == 32'h00000017),{((decode_INSTRUCTION & 32'h0000007f) == 32'h0000006f),{((decode_INSTRUCTION & _zz_decode_LEGAL_INSTRUCTION) == 32'h00001073),{(_zz_decode_LEGAL_INSTRUCTION_1 == _zz_decode_LEGAL_INSTRUCTION_2),{_zz_decode_LEGAL_INSTRUCTION_3,{_zz_decode_LEGAL_INSTRUCTION_4,_zz_decode_LEGAL_INSTRUCTION_5}}}}}});
  always @(*) begin
    _zz_decode_RS2_2 = writeBack_REGFILE_WRITE_DATA;
    if(when_DBusSimplePlugin_l566) begin
      _zz_decode_RS2_2 = writeBack_DBusSimplePlugin_rspFormated;
    end
  end

  assign writeBack_MEMORY_ENABLE = memory_to_writeBack_MEMORY_ENABLE;
  assign writeBack_MEMORY_ADDRESS_LOW = memory_to_writeBack_MEMORY_ADDRESS_LOW;
  assign writeBack_MEMORY_READ_DATA = memory_to_writeBack_MEMORY_READ_DATA;
  assign memory_ALIGNEMENT_FAULT = execute_to_memory_ALIGNEMENT_FAULT;
  assign memory_REGFILE_WRITE_DATA = execute_to_memory_REGFILE_WRITE_DATA;
  assign memory_MEMORY_STORE = execute_to_memory_MEMORY_STORE;
  assign memory_MEMORY_ENABLE = execute_to_memory_MEMORY_ENABLE;
  assign execute_SRC_ADD = execute_SrcPlugin_addSub;
  assign execute_RS2 = decode_to_execute_RS2;
  assign execute_INSTRUCTION = decode_to_execute_INSTRUCTION;
  assign execute_MEMORY_STORE = decode_to_execute_MEMORY_STORE;
  assign execute_MEMORY_ENABLE = decode_to_execute_MEMORY_ENABLE;
  assign execute_ALIGNEMENT_FAULT = (((dBus_cmd_payload_size == 2'b10) && (dBus_cmd_payload_address[1 : 0] != 2'b00)) || ((dBus_cmd_payload_size == 2'b01) && (dBus_cmd_payload_address[0 : 0] != 1'b0)));
  assign decode_FLUSH_ALL = _zz_decode_IS_DIV[0];
  always @(*) begin
    IBusCachedPlugin_rsp_issueDetected_4 = IBusCachedPlugin_rsp_issueDetected_3;
    if(when_IBusCachedPlugin_l262) begin
      IBusCachedPlugin_rsp_issueDetected_4 = 1'b1;
    end
  end

  always @(*) begin
    IBusCachedPlugin_rsp_issueDetected_3 = IBusCachedPlugin_rsp_issueDetected_2;
    if(when_IBusCachedPlugin_l256) begin
      IBusCachedPlugin_rsp_issueDetected_3 = 1'b1;
    end
  end

  always @(*) begin
    IBusCachedPlugin_rsp_issueDetected_2 = IBusCachedPlugin_rsp_issueDetected_1;
    if(when_IBusCachedPlugin_l250) begin
      IBusCachedPlugin_rsp_issueDetected_2 = 1'b1;
    end
  end

  always @(*) begin
    IBusCachedPlugin_rsp_issueDetected_1 = IBusCachedPlugin_rsp_issueDetected;
    if(when_IBusCachedPlugin_l245) begin
      IBusCachedPlugin_rsp_issueDetected_1 = 1'b1;
    end
  end

  assign decode_BRANCH_CTRL = _zz_decode_BRANCH_CTRL_1;
  assign decode_INSTRUCTION = IBusCachedPlugin_iBusRsp_output_payload_rsp_inst;
  always @(*) begin
    _zz_memory_to_writeBack_FORMAL_PC_NEXT = memory_FORMAL_PC_NEXT;
    if(BranchPlugin_jumpInterface_valid) begin
      _zz_memory_to_writeBack_FORMAL_PC_NEXT = BranchPlugin_jumpInterface_payload;
    end
  end

  always @(*) begin
    _zz_decode_to_execute_FORMAL_PC_NEXT = decode_FORMAL_PC_NEXT;
    if(IBusCachedPlugin_predictionJumpInterface_valid) begin
      _zz_decode_to_execute_FORMAL_PC_NEXT = IBusCachedPlugin_predictionJumpInterface_payload;
    end
  end

  assign decode_PC = IBusCachedPlugin_iBusRsp_output_payload_pc;
  assign writeBack_PC = memory_to_writeBack_PC;
  assign writeBack_INSTRUCTION = memory_to_writeBack_INSTRUCTION;
  always @(*) begin
    decode_arbitration_haltItself = 1'b0;
    case(IBusCachedPlugin_injector_port_state)
      3'b010 : begin
        decode_arbitration_haltItself = 1'b1;
      end
      default : begin
      end
    endcase
  end

  always @(*) begin
    decode_arbitration_haltByOther = 1'b0;
    if(when_HazardSimplePlugin_l113) begin
      decode_arbitration_haltByOther = 1'b1;
    end
    case(CsrPlugin_dcsr_stepLogic_stateReg)
      CsrPlugin_dcsr_stepLogic_IDLE : begin
      end
      CsrPlugin_dcsr_stepLogic_SINGLE : begin
      end
      CsrPlugin_dcsr_stepLogic_WAIT_1 : begin
        if(decode_arbitration_isValid) begin
          decode_arbitration_haltByOther = 1'b1;
        end
      end
      default : begin
      end
    endcase
    if(CsrPlugin_trigger_decodeBreak_enabled) begin
      decode_arbitration_haltByOther = 1'b1;
    end
    if(CsrPlugin_pipelineLiberator_active) begin
      decode_arbitration_haltByOther = 1'b1;
    end
    if(when_CsrPlugin_l1527) begin
      decode_arbitration_haltByOther = 1'b1;
    end
  end

  always @(*) begin
    decode_arbitration_removeIt = 1'b0;
    if(CsrPlugin_trigger_decodeBreak_enabled) begin
      if(CsrPlugin_trigger_decodeBreak_timeout_state) begin
        decode_arbitration_removeIt = 1'b1;
      end
    end
    if(_zz_when_1) begin
      decode_arbitration_removeIt = 1'b1;
    end
    if(decode_arbitration_isFlushed) begin
      decode_arbitration_removeIt = 1'b1;
    end
  end

  assign decode_arbitration_flushIt = 1'b0;
  always @(*) begin
    decode_arbitration_flushNext = 1'b0;
    if(IBusCachedPlugin_predictionJumpInterface_valid) begin
      decode_arbitration_flushNext = 1'b1;
    end
    if(CsrPlugin_trigger_decodeBreak_enabled) begin
      if(CsrPlugin_trigger_decodeBreak_timeout_state) begin
        decode_arbitration_flushNext = 1'b1;
      end
    end
    if(_zz_when_1) begin
      decode_arbitration_flushNext = 1'b1;
    end
  end

  always @(*) begin
    execute_arbitration_haltItself = 1'b0;
    if(when_DBusSimplePlugin_l435) begin
      execute_arbitration_haltItself = 1'b1;
    end
    if(when_ShiftPlugins_l169) begin
      if(when_ShiftPlugins_l184) begin
        execute_arbitration_haltItself = 1'b1;
      end
    end
    if(when_CsrPlugin_l1591) begin
      if(execute_CsrPlugin_blockedBySideEffects) begin
        execute_arbitration_haltItself = 1'b1;
      end
    end
  end

  assign execute_arbitration_haltByOther = 1'b0;
  always @(*) begin
    execute_arbitration_removeIt = 1'b0;
    if(CsrPlugin_selfException_valid) begin
      execute_arbitration_removeIt = 1'b1;
    end
    if(execute_arbitration_isFlushed) begin
      execute_arbitration_removeIt = 1'b1;
    end
  end

  assign execute_arbitration_flushIt = 1'b0;
  always @(*) begin
    execute_arbitration_flushNext = 1'b0;
    if(CsrPlugin_selfException_valid) begin
      execute_arbitration_flushNext = 1'b1;
    end
  end

  always @(*) begin
    memory_arbitration_haltItself = 1'b0;
    if(when_DBusSimplePlugin_l490) begin
      memory_arbitration_haltItself = 1'b1;
    end
    if(when_MulDivIterativePlugin_l96) begin
      if(when_MulDivIterativePlugin_l97) begin
        memory_arbitration_haltItself = 1'b1;
      end
      if(when_MulDivIterativePlugin_l100) begin
        memory_arbitration_haltItself = 1'b1;
      end
    end
    if(when_MulDivIterativePlugin_l128) begin
      if(when_MulDivIterativePlugin_l129) begin
        memory_arbitration_haltItself = 1'b1;
      end
    end
  end

  assign memory_arbitration_haltByOther = 1'b0;
  always @(*) begin
    memory_arbitration_removeIt = 1'b0;
    if(_zz_when_2) begin
      memory_arbitration_removeIt = 1'b1;
    end
    if(memory_arbitration_isFlushed) begin
      memory_arbitration_removeIt = 1'b1;
    end
  end

  assign memory_arbitration_flushIt = 1'b0;
  always @(*) begin
    memory_arbitration_flushNext = 1'b0;
    if(BranchPlugin_jumpInterface_valid) begin
      memory_arbitration_flushNext = 1'b1;
    end
    if(_zz_when_2) begin
      memory_arbitration_flushNext = 1'b1;
    end
  end

  assign writeBack_arbitration_haltItself = 1'b0;
  assign writeBack_arbitration_haltByOther = 1'b0;
  always @(*) begin
    writeBack_arbitration_removeIt = 1'b0;
    if(writeBack_arbitration_isFlushed) begin
      writeBack_arbitration_removeIt = 1'b1;
    end
  end

  always @(*) begin
    writeBack_arbitration_flushIt = 1'b0;
    if(CsrPlugin_doResume) begin
      writeBack_arbitration_flushIt = 1'b1;
    end
  end

  always @(*) begin
    writeBack_arbitration_flushNext = 1'b0;
    if(when_CsrPlugin_l1390) begin
      writeBack_arbitration_flushNext = 1'b1;
    end
    if(when_CsrPlugin_l1456) begin
      writeBack_arbitration_flushNext = 1'b1;
    end
  end

  assign lastStageInstruction = writeBack_INSTRUCTION;
  assign lastStagePc = writeBack_PC;
  assign lastStageIsValid = writeBack_arbitration_isValid;
  assign lastStageIsFiring = writeBack_arbitration_isFiring;
  always @(*) begin
    IBusCachedPlugin_fetcherHalt = 1'b0;
    if(when_CsrPlugin_l711) begin
      IBusCachedPlugin_fetcherHalt = 1'b1;
    end
    if(when_CsrPlugin_l1272) begin
      IBusCachedPlugin_fetcherHalt = 1'b1;
    end
    if(when_CsrPlugin_l1390) begin
      IBusCachedPlugin_fetcherHalt = 1'b1;
    end
    if(when_CsrPlugin_l1456) begin
      IBusCachedPlugin_fetcherHalt = 1'b1;
    end
  end

  assign IBusCachedPlugin_forceNoDecodeCond = 1'b0;
  always @(*) begin
    IBusCachedPlugin_incomingInstruction = 1'b0;
    if(when_Fetcher_l242) begin
      IBusCachedPlugin_incomingInstruction = 1'b1;
    end
  end

  always @(*) begin
    BranchPlugin_inDebugNoFetchFlag = 1'b0;
    if(debugMode) begin
      BranchPlugin_inDebugNoFetchFlag = 1'b1;
    end
  end

  always @(*) begin
    CsrPlugin_csrMapping_allowCsrSignal = 1'b0;
    if(when_CsrPlugin_l1702) begin
      CsrPlugin_csrMapping_allowCsrSignal = 1'b1;
    end
    if(when_CsrPlugin_l1709) begin
      CsrPlugin_csrMapping_allowCsrSignal = 1'b1;
    end
  end

  assign CsrPlugin_csrMapping_doForceFailCsr = 1'b0;
  assign CsrPlugin_csrMapping_readDataSignal = CsrPlugin_csrMapping_readDataInit;
  assign CsrPlugin_inWfi = 1'b0;
  always @(*) begin
    CsrPlugin_thirdPartyWake = 1'b0;
    if(when_CsrPlugin_l862) begin
      CsrPlugin_thirdPartyWake = 1'b1;
    end
  end

  always @(*) begin
    CsrPlugin_jumpInterface_valid = 1'b0;
    if(when_CsrPlugin_l1390) begin
      CsrPlugin_jumpInterface_valid = 1'b1;
    end
    if(when_CsrPlugin_l1456) begin
      CsrPlugin_jumpInterface_valid = 1'b1;
    end
    if(CsrPlugin_doResume) begin
      CsrPlugin_jumpInterface_valid = 1'b1;
    end
  end

  always @(*) begin
    CsrPlugin_jumpInterface_payload = 32'bxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx;
    if(when_CsrPlugin_l1390) begin
      CsrPlugin_jumpInterface_payload = {CsrPlugin_xtvec_base,2'b00};
    end
    if(when_CsrPlugin_l1456) begin
      case(switch_CsrPlugin_l1460)
        2'b11 : begin
          CsrPlugin_jumpInterface_payload = CsrPlugin_mepc;
        end
        default : begin
        end
      endcase
    end
    if(CsrPlugin_doResume) begin
      CsrPlugin_jumpInterface_payload = CsrPlugin_dpc;
    end
  end

  assign CsrPlugin_forceMachineWire = 1'b0;
  always @(*) begin
    CsrPlugin_allowInterrupts = 1'b1;
    if(debugMode) begin
      CsrPlugin_allowInterrupts = 1'b0;
    end
  end

  assign CsrPlugin_allowException = 1'b1;
  assign CsrPlugin_allowEbreakException = 1'b1;
  always @(*) begin
    CsrPlugin_xretAwayFromMachine = 1'b0;
    if(when_CsrPlugin_l1456) begin
      case(switch_CsrPlugin_l1460)
        2'b11 : begin
          if(when_CsrPlugin_l1468) begin
            CsrPlugin_xretAwayFromMachine = 1'b1;
          end
        end
        default : begin
        end
      endcase
    end
  end

  assign IBusCachedPlugin_externalFlush = (|{writeBack_arbitration_flushNext,{memory_arbitration_flushNext,{execute_arbitration_flushNext,decode_arbitration_flushNext}}});
  assign IBusCachedPlugin_jump_pcLoad_valid = (|{CsrPlugin_jumpInterface_valid,{BranchPlugin_jumpInterface_valid,IBusCachedPlugin_predictionJumpInterface_valid}});
  assign _zz_IBusCachedPlugin_jump_pcLoad_payload = {IBusCachedPlugin_predictionJumpInterface_valid,{BranchPlugin_jumpInterface_valid,CsrPlugin_jumpInterface_valid}};
  assign _zz_IBusCachedPlugin_jump_pcLoad_payload_1 = (_zz_IBusCachedPlugin_jump_pcLoad_payload & (~ _zz__zz_IBusCachedPlugin_jump_pcLoad_payload_1));
  assign _zz_IBusCachedPlugin_jump_pcLoad_payload_2 = _zz_IBusCachedPlugin_jump_pcLoad_payload_1[1];
  assign _zz_IBusCachedPlugin_jump_pcLoad_payload_3 = _zz_IBusCachedPlugin_jump_pcLoad_payload_1[2];
  assign IBusCachedPlugin_jump_pcLoad_payload = _zz_IBusCachedPlugin_jump_pcLoad_payload_4;
  always @(*) begin
    IBusCachedPlugin_fetchPc_correction = 1'b0;
    if(IBusCachedPlugin_fetchPc_redo_valid) begin
      IBusCachedPlugin_fetchPc_correction = 1'b1;
    end
    if(IBusCachedPlugin_jump_pcLoad_valid) begin
      IBusCachedPlugin_fetchPc_correction = 1'b1;
    end
  end

  assign IBusCachedPlugin_fetchPc_output_fire = (IBusCachedPlugin_fetchPc_output_valid && IBusCachedPlugin_fetchPc_output_ready);
  assign IBusCachedPlugin_fetchPc_corrected = (IBusCachedPlugin_fetchPc_correction || IBusCachedPlugin_fetchPc_correctionReg);
  always @(*) begin
    IBusCachedPlugin_fetchPc_pcRegPropagate = 1'b0;
    if(IBusCachedPlugin_iBusRsp_stages_1_input_ready) begin
      IBusCachedPlugin_fetchPc_pcRegPropagate = 1'b1;
    end
  end

  assign when_Fetcher_l133 = (IBusCachedPlugin_fetchPc_correction || IBusCachedPlugin_fetchPc_pcRegPropagate);
  assign when_Fetcher_l133_1 = ((! IBusCachedPlugin_fetchPc_output_valid) && IBusCachedPlugin_fetchPc_output_ready);
  always @(*) begin
    IBusCachedPlugin_fetchPc_pc = (IBusCachedPlugin_fetchPc_pcReg + _zz_IBusCachedPlugin_fetchPc_pc);
    if(IBusCachedPlugin_fetchPc_redo_valid) begin
      IBusCachedPlugin_fetchPc_pc = IBusCachedPlugin_fetchPc_redo_payload;
    end
    if(IBusCachedPlugin_jump_pcLoad_valid) begin
      IBusCachedPlugin_fetchPc_pc = IBusCachedPlugin_jump_pcLoad_payload;
    end
    IBusCachedPlugin_fetchPc_pc[0] = 1'b0;
    IBusCachedPlugin_fetchPc_pc[1] = 1'b0;
  end

  always @(*) begin
    IBusCachedPlugin_fetchPc_flushed = 1'b0;
    if(IBusCachedPlugin_fetchPc_redo_valid) begin
      IBusCachedPlugin_fetchPc_flushed = 1'b1;
    end
    if(IBusCachedPlugin_jump_pcLoad_valid) begin
      IBusCachedPlugin_fetchPc_flushed = 1'b1;
    end
  end

  assign when_Fetcher_l160 = (IBusCachedPlugin_fetchPc_booted && ((IBusCachedPlugin_fetchPc_output_ready || IBusCachedPlugin_fetchPc_correction) || IBusCachedPlugin_fetchPc_pcRegPropagate));
  assign IBusCachedPlugin_fetchPc_output_valid = ((! IBusCachedPlugin_fetcherHalt) && IBusCachedPlugin_fetchPc_booted);
  assign IBusCachedPlugin_fetchPc_output_payload = IBusCachedPlugin_fetchPc_pc;
  always @(*) begin
    IBusCachedPlugin_iBusRsp_redoFetch = 1'b0;
    if(IBusCachedPlugin_rsp_redoFetch) begin
      IBusCachedPlugin_iBusRsp_redoFetch = 1'b1;
    end
  end

  assign IBusCachedPlugin_iBusRsp_stages_0_input_valid = IBusCachedPlugin_fetchPc_output_valid;
  assign IBusCachedPlugin_fetchPc_output_ready = IBusCachedPlugin_iBusRsp_stages_0_input_ready;
  assign IBusCachedPlugin_iBusRsp_stages_0_input_payload = IBusCachedPlugin_fetchPc_output_payload;
  always @(*) begin
    IBusCachedPlugin_iBusRsp_stages_0_halt = 1'b0;
    if(IBusCachedPlugin_cache_io_cpu_prefetch_haltIt) begin
      IBusCachedPlugin_iBusRsp_stages_0_halt = 1'b1;
    end
  end

  assign _zz_IBusCachedPlugin_iBusRsp_stages_0_input_ready = (! IBusCachedPlugin_iBusRsp_stages_0_halt);
  assign IBusCachedPlugin_iBusRsp_stages_0_input_haltWhen_valid = (IBusCachedPlugin_iBusRsp_stages_0_input_valid && _zz_IBusCachedPlugin_iBusRsp_stages_0_input_ready);
  assign IBusCachedPlugin_iBusRsp_stages_0_input_ready = (IBusCachedPlugin_iBusRsp_stages_0_input_haltWhen_ready && _zz_IBusCachedPlugin_iBusRsp_stages_0_input_ready);
  assign IBusCachedPlugin_iBusRsp_stages_0_input_haltWhen_payload = IBusCachedPlugin_iBusRsp_stages_0_input_payload;
  assign IBusCachedPlugin_iBusRsp_stages_0_output_valid = IBusCachedPlugin_iBusRsp_stages_0_input_haltWhen_valid;
  assign IBusCachedPlugin_iBusRsp_stages_0_input_haltWhen_ready = IBusCachedPlugin_iBusRsp_stages_0_output_ready;
  assign IBusCachedPlugin_iBusRsp_stages_0_output_payload = IBusCachedPlugin_iBusRsp_stages_0_input_haltWhen_payload;
  always @(*) begin
    IBusCachedPlugin_iBusRsp_stages_1_halt = 1'b0;
    if(IBusCachedPlugin_mmuBus_busy) begin
      IBusCachedPlugin_iBusRsp_stages_1_halt = 1'b1;
    end
  end

  assign _zz_IBusCachedPlugin_iBusRsp_stages_1_input_ready = (! IBusCachedPlugin_iBusRsp_stages_1_halt);
  assign IBusCachedPlugin_iBusRsp_stages_1_input_haltWhen_valid = (IBusCachedPlugin_iBusRsp_stages_1_input_valid && _zz_IBusCachedPlugin_iBusRsp_stages_1_input_ready);
  assign IBusCachedPlugin_iBusRsp_stages_1_input_ready = (IBusCachedPlugin_iBusRsp_stages_1_input_haltWhen_ready && _zz_IBusCachedPlugin_iBusRsp_stages_1_input_ready);
  assign IBusCachedPlugin_iBusRsp_stages_1_input_haltWhen_payload = IBusCachedPlugin_iBusRsp_stages_1_input_payload;
  assign IBusCachedPlugin_iBusRsp_stages_1_output_valid = IBusCachedPlugin_iBusRsp_stages_1_input_haltWhen_valid;
  assign IBusCachedPlugin_iBusRsp_stages_1_input_haltWhen_ready = IBusCachedPlugin_iBusRsp_stages_1_output_ready;
  assign IBusCachedPlugin_iBusRsp_stages_1_output_payload = IBusCachedPlugin_iBusRsp_stages_1_input_haltWhen_payload;
  always @(*) begin
    IBusCachedPlugin_iBusRsp_stages_2_halt = 1'b0;
    if(when_IBusCachedPlugin_l273) begin
      IBusCachedPlugin_iBusRsp_stages_2_halt = 1'b1;
    end
  end

  assign _zz_IBusCachedPlugin_iBusRsp_stages_2_input_ready = (! IBusCachedPlugin_iBusRsp_stages_2_halt);
  assign IBusCachedPlugin_iBusRsp_stages_2_input_haltWhen_valid = (IBusCachedPlugin_iBusRsp_stages_2_input_valid && _zz_IBusCachedPlugin_iBusRsp_stages_2_input_ready);
  assign IBusCachedPlugin_iBusRsp_stages_2_input_ready = (IBusCachedPlugin_iBusRsp_stages_2_input_haltWhen_ready && _zz_IBusCachedPlugin_iBusRsp_stages_2_input_ready);
  assign IBusCachedPlugin_iBusRsp_stages_2_input_haltWhen_payload = IBusCachedPlugin_iBusRsp_stages_2_input_payload;
  assign IBusCachedPlugin_iBusRsp_stages_2_output_valid = IBusCachedPlugin_iBusRsp_stages_2_input_haltWhen_valid;
  assign IBusCachedPlugin_iBusRsp_stages_2_input_haltWhen_ready = IBusCachedPlugin_iBusRsp_stages_2_output_ready;
  assign IBusCachedPlugin_iBusRsp_stages_2_output_payload = IBusCachedPlugin_iBusRsp_stages_2_input_haltWhen_payload;
  assign IBusCachedPlugin_fetchPc_redo_valid = IBusCachedPlugin_iBusRsp_redoFetch;
  assign IBusCachedPlugin_fetchPc_redo_payload = IBusCachedPlugin_iBusRsp_stages_2_input_payload;
  assign IBusCachedPlugin_iBusRsp_flush = ((decode_arbitration_removeIt || (decode_arbitration_flushNext && (! decode_arbitration_isStuck))) || IBusCachedPlugin_iBusRsp_redoFetch);
  assign IBusCachedPlugin_iBusRsp_stages_0_output_toEvent_valid = IBusCachedPlugin_iBusRsp_stages_0_output_valid;
  assign IBusCachedPlugin_iBusRsp_stages_0_output_ready = IBusCachedPlugin_iBusRsp_stages_0_output_toEvent_ready;
  assign IBusCachedPlugin_iBusRsp_stages_0_output_toEvent_ready = ((1'b0 && (! IBusCachedPlugin_iBusRsp_stages_0_output_toEvent_m2sPipe_valid)) || IBusCachedPlugin_iBusRsp_stages_0_output_toEvent_m2sPipe_ready);
  assign IBusCachedPlugin_iBusRsp_stages_0_output_toEvent_m2sPipe_valid = _zz_IBusCachedPlugin_iBusRsp_stages_0_output_toEvent_m2sPipe_valid;
  assign IBusCachedPlugin_iBusRsp_stages_1_input_valid = IBusCachedPlugin_iBusRsp_stages_0_output_toEvent_m2sPipe_valid;
  assign IBusCachedPlugin_iBusRsp_stages_0_output_toEvent_m2sPipe_ready = IBusCachedPlugin_iBusRsp_stages_1_input_ready;
  assign IBusCachedPlugin_iBusRsp_stages_1_input_payload = IBusCachedPlugin_fetchPc_pcReg;
  assign IBusCachedPlugin_iBusRsp_stages_1_output_ready = ((1'b0 && (! IBusCachedPlugin_iBusRsp_stages_1_output_m2sPipe_valid)) || IBusCachedPlugin_iBusRsp_stages_1_output_m2sPipe_ready);
  assign IBusCachedPlugin_iBusRsp_stages_1_output_m2sPipe_valid = _zz_IBusCachedPlugin_iBusRsp_stages_1_output_m2sPipe_valid;
  assign IBusCachedPlugin_iBusRsp_stages_1_output_m2sPipe_payload = _zz_IBusCachedPlugin_iBusRsp_stages_1_output_m2sPipe_payload;
  assign IBusCachedPlugin_iBusRsp_stages_2_input_valid = IBusCachedPlugin_iBusRsp_stages_1_output_m2sPipe_valid;
  assign IBusCachedPlugin_iBusRsp_stages_1_output_m2sPipe_ready = IBusCachedPlugin_iBusRsp_stages_2_input_ready;
  assign IBusCachedPlugin_iBusRsp_stages_2_input_payload = IBusCachedPlugin_iBusRsp_stages_1_output_m2sPipe_payload;
  always @(*) begin
    IBusCachedPlugin_iBusRsp_readyForError = 1'b1;
    if(when_Fetcher_l322) begin
      IBusCachedPlugin_iBusRsp_readyForError = 1'b0;
    end
  end

  assign when_Fetcher_l242 = (IBusCachedPlugin_iBusRsp_stages_1_input_valid || IBusCachedPlugin_iBusRsp_stages_2_input_valid);
  assign when_Fetcher_l322 = (! IBusCachedPlugin_pcValids_0);
  assign when_Fetcher_l331 = (! (! IBusCachedPlugin_iBusRsp_stages_1_input_ready));
  assign when_Fetcher_l331_1 = (! (! IBusCachedPlugin_iBusRsp_stages_2_input_ready));
  assign when_Fetcher_l331_2 = (! execute_arbitration_isStuck);
  assign when_Fetcher_l331_3 = (! memory_arbitration_isStuck);
  assign when_Fetcher_l331_4 = (! writeBack_arbitration_isStuck);
  assign IBusCachedPlugin_pcValids_0 = IBusCachedPlugin_injector_nextPcCalc_valids_1;
  assign IBusCachedPlugin_pcValids_1 = IBusCachedPlugin_injector_nextPcCalc_valids_2;
  assign IBusCachedPlugin_pcValids_2 = IBusCachedPlugin_injector_nextPcCalc_valids_3;
  assign IBusCachedPlugin_pcValids_3 = IBusCachedPlugin_injector_nextPcCalc_valids_4;
  assign IBusCachedPlugin_iBusRsp_output_ready = (! decode_arbitration_isStuck);
  always @(*) begin
    decode_arbitration_isValid = IBusCachedPlugin_iBusRsp_output_valid;
    case(IBusCachedPlugin_injector_port_state)
      3'b010 : begin
        decode_arbitration_isValid = 1'b1;
      end
      3'b011 : begin
        decode_arbitration_isValid = 1'b1;
      end
      default : begin
      end
    endcase
    if(IBusCachedPlugin_forceNoDecodeCond) begin
      decode_arbitration_isValid = 1'b0;
    end
  end

  assign _zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch = _zz__zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch[11];
  always @(*) begin
    _zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch_1[18] = _zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch;
    _zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch_1[17] = _zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch;
    _zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch_1[16] = _zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch;
    _zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch_1[15] = _zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch;
    _zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch_1[14] = _zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch;
    _zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch_1[13] = _zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch;
    _zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch_1[12] = _zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch;
    _zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch_1[11] = _zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch;
    _zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch_1[10] = _zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch;
    _zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch_1[9] = _zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch;
    _zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch_1[8] = _zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch;
    _zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch_1[7] = _zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch;
    _zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch_1[6] = _zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch;
    _zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch_1[5] = _zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch;
    _zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch_1[4] = _zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch;
    _zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch_1[3] = _zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch;
    _zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch_1[2] = _zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch;
    _zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch_1[1] = _zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch;
    _zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch_1[0] = _zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch;
  end

  always @(*) begin
    IBusCachedPlugin_decodePrediction_cmd_hadBranch = ((decode_BRANCH_CTRL == BranchCtrlEnum_JAL) || ((decode_BRANCH_CTRL == BranchCtrlEnum_B) && _zz_IBusCachedPlugin_decodePrediction_cmd_hadBranch_2[31]));
    if(_zz_6) begin
      IBusCachedPlugin_decodePrediction_cmd_hadBranch = 1'b0;
    end
  end

  assign _zz_2 = _zz__zz_2[19];
  always @(*) begin
    _zz_3[10] = _zz_2;
    _zz_3[9] = _zz_2;
    _zz_3[8] = _zz_2;
    _zz_3[7] = _zz_2;
    _zz_3[6] = _zz_2;
    _zz_3[5] = _zz_2;
    _zz_3[4] = _zz_2;
    _zz_3[3] = _zz_2;
    _zz_3[2] = _zz_2;
    _zz_3[1] = _zz_2;
    _zz_3[0] = _zz_2;
  end

  assign _zz_4 = _zz__zz_4[11];
  always @(*) begin
    _zz_5[18] = _zz_4;
    _zz_5[17] = _zz_4;
    _zz_5[16] = _zz_4;
    _zz_5[15] = _zz_4;
    _zz_5[14] = _zz_4;
    _zz_5[13] = _zz_4;
    _zz_5[12] = _zz_4;
    _zz_5[11] = _zz_4;
    _zz_5[10] = _zz_4;
    _zz_5[9] = _zz_4;
    _zz_5[8] = _zz_4;
    _zz_5[7] = _zz_4;
    _zz_5[6] = _zz_4;
    _zz_5[5] = _zz_4;
    _zz_5[4] = _zz_4;
    _zz_5[3] = _zz_4;
    _zz_5[2] = _zz_4;
    _zz_5[1] = _zz_4;
    _zz_5[0] = _zz_4;
  end

  always @(*) begin
    case(decode_BRANCH_CTRL)
      BranchCtrlEnum_JAL : begin
        _zz_6 = _zz__zz_6[1];
      end
      default : begin
        _zz_6 = _zz__zz_6_1[1];
      end
    endcase
  end

  assign IBusCachedPlugin_predictionJumpInterface_valid = (decode_arbitration_isValid && IBusCachedPlugin_decodePrediction_cmd_hadBranch);
  assign _zz_IBusCachedPlugin_predictionJumpInterface_payload = _zz__zz_IBusCachedPlugin_predictionJumpInterface_payload[19];
  always @(*) begin
    _zz_IBusCachedPlugin_predictionJumpInterface_payload_1[10] = _zz_IBusCachedPlugin_predictionJumpInterface_payload;
    _zz_IBusCachedPlugin_predictionJumpInterface_payload_1[9] = _zz_IBusCachedPlugin_predictionJumpInterface_payload;
    _zz_IBusCachedPlugin_predictionJumpInterface_payload_1[8] = _zz_IBusCachedPlugin_predictionJumpInterface_payload;
    _zz_IBusCachedPlugin_predictionJumpInterface_payload_1[7] = _zz_IBusCachedPlugin_predictionJumpInterface_payload;
    _zz_IBusCachedPlugin_predictionJumpInterface_payload_1[6] = _zz_IBusCachedPlugin_predictionJumpInterface_payload;
    _zz_IBusCachedPlugin_predictionJumpInterface_payload_1[5] = _zz_IBusCachedPlugin_predictionJumpInterface_payload;
    _zz_IBusCachedPlugin_predictionJumpInterface_payload_1[4] = _zz_IBusCachedPlugin_predictionJumpInterface_payload;
    _zz_IBusCachedPlugin_predictionJumpInterface_payload_1[3] = _zz_IBusCachedPlugin_predictionJumpInterface_payload;
    _zz_IBusCachedPlugin_predictionJumpInterface_payload_1[2] = _zz_IBusCachedPlugin_predictionJumpInterface_payload;
    _zz_IBusCachedPlugin_predictionJumpInterface_payload_1[1] = _zz_IBusCachedPlugin_predictionJumpInterface_payload;
    _zz_IBusCachedPlugin_predictionJumpInterface_payload_1[0] = _zz_IBusCachedPlugin_predictionJumpInterface_payload;
  end

  assign _zz_IBusCachedPlugin_predictionJumpInterface_payload_2 = _zz__zz_IBusCachedPlugin_predictionJumpInterface_payload_2[11];
  always @(*) begin
    _zz_IBusCachedPlugin_predictionJumpInterface_payload_3[18] = _zz_IBusCachedPlugin_predictionJumpInterface_payload_2;
    _zz_IBusCachedPlugin_predictionJumpInterface_payload_3[17] = _zz_IBusCachedPlugin_predictionJumpInterface_payload_2;
    _zz_IBusCachedPlugin_predictionJumpInterface_payload_3[16] = _zz_IBusCachedPlugin_predictionJumpInterface_payload_2;
    _zz_IBusCachedPlugin_predictionJumpInterface_payload_3[15] = _zz_IBusCachedPlugin_predictionJumpInterface_payload_2;
    _zz_IBusCachedPlugin_predictionJumpInterface_payload_3[14] = _zz_IBusCachedPlugin_predictionJumpInterface_payload_2;
    _zz_IBusCachedPlugin_predictionJumpInterface_payload_3[13] = _zz_IBusCachedPlugin_predictionJumpInterface_payload_2;
    _zz_IBusCachedPlugin_predictionJumpInterface_payload_3[12] = _zz_IBusCachedPlugin_predictionJumpInterface_payload_2;
    _zz_IBusCachedPlugin_predictionJumpInterface_payload_3[11] = _zz_IBusCachedPlugin_predictionJumpInterface_payload_2;
    _zz_IBusCachedPlugin_predictionJumpInterface_payload_3[10] = _zz_IBusCachedPlugin_predictionJumpInterface_payload_2;
    _zz_IBusCachedPlugin_predictionJumpInterface_payload_3[9] = _zz_IBusCachedPlugin_predictionJumpInterface_payload_2;
    _zz_IBusCachedPlugin_predictionJumpInterface_payload_3[8] = _zz_IBusCachedPlugin_predictionJumpInterface_payload_2;
    _zz_IBusCachedPlugin_predictionJumpInterface_payload_3[7] = _zz_IBusCachedPlugin_predictionJumpInterface_payload_2;
    _zz_IBusCachedPlugin_predictionJumpInterface_payload_3[6] = _zz_IBusCachedPlugin_predictionJumpInterface_payload_2;
    _zz_IBusCachedPlugin_predictionJumpInterface_payload_3[5] = _zz_IBusCachedPlugin_predictionJumpInterface_payload_2;
    _zz_IBusCachedPlugin_predictionJumpInterface_payload_3[4] = _zz_IBusCachedPlugin_predictionJumpInterface_payload_2;
    _zz_IBusCachedPlugin_predictionJumpInterface_payload_3[3] = _zz_IBusCachedPlugin_predictionJumpInterface_payload_2;
    _zz_IBusCachedPlugin_predictionJumpInterface_payload_3[2] = _zz_IBusCachedPlugin_predictionJumpInterface_payload_2;
    _zz_IBusCachedPlugin_predictionJumpInterface_payload_3[1] = _zz_IBusCachedPlugin_predictionJumpInterface_payload_2;
    _zz_IBusCachedPlugin_predictionJumpInterface_payload_3[0] = _zz_IBusCachedPlugin_predictionJumpInterface_payload_2;
  end

  assign IBusCachedPlugin_predictionJumpInterface_payload = (decode_PC + ((decode_BRANCH_CTRL == BranchCtrlEnum_JAL) ? {{_zz_IBusCachedPlugin_predictionJumpInterface_payload_1,{{{_zz_IBusCachedPlugin_predictionJumpInterface_payload_4,decode_INSTRUCTION[19 : 12]},decode_INSTRUCTION[20]},decode_INSTRUCTION[30 : 21]}},1'b0} : {{_zz_IBusCachedPlugin_predictionJumpInterface_payload_3,{{{_zz_IBusCachedPlugin_predictionJumpInterface_payload_5,_zz_IBusCachedPlugin_predictionJumpInterface_payload_6},decode_INSTRUCTION[30 : 25]},decode_INSTRUCTION[11 : 8]}},1'b0}));
  assign iBus_cmd_valid = IBusCachedPlugin_cache_io_mem_cmd_valid;
  always @(*) begin
    iBus_cmd_payload_address = IBusCachedPlugin_cache_io_mem_cmd_payload_address;
    iBus_cmd_payload_address = IBusCachedPlugin_cache_io_mem_cmd_payload_address;
  end

  assign iBus_cmd_payload_size = IBusCachedPlugin_cache_io_mem_cmd_payload_size;
  assign IBusCachedPlugin_s0_tightlyCoupledHit = 1'b0;
  assign IBusCachedPlugin_cache_io_cpu_prefetch_isValid = (IBusCachedPlugin_iBusRsp_stages_0_input_valid && (! IBusCachedPlugin_s0_tightlyCoupledHit));
  assign IBusCachedPlugin_cache_io_cpu_fetch_isValid = (IBusCachedPlugin_iBusRsp_stages_1_input_valid && (! IBusCachedPlugin_s1_tightlyCoupledHit));
  assign IBusCachedPlugin_cache_io_cpu_fetch_isStuck = (! IBusCachedPlugin_iBusRsp_stages_1_input_ready);
  assign IBusCachedPlugin_mmuBus_cmd_0_isValid = IBusCachedPlugin_cache_io_cpu_fetch_isValid;
  assign IBusCachedPlugin_mmuBus_cmd_0_isStuck = (! IBusCachedPlugin_iBusRsp_stages_1_input_ready);
  assign IBusCachedPlugin_mmuBus_cmd_0_virtualAddress = IBusCachedPlugin_iBusRsp_stages_1_input_payload;
  assign IBusCachedPlugin_mmuBus_cmd_0_bypassTranslation = 1'b0;
  assign IBusCachedPlugin_mmuBus_end = (IBusCachedPlugin_iBusRsp_stages_1_input_ready || IBusCachedPlugin_externalFlush);
  assign IBusCachedPlugin_cache_io_cpu_decode_isValid = (IBusCachedPlugin_iBusRsp_stages_2_input_valid && (! IBusCachedPlugin_s2_tightlyCoupledHit));
  assign IBusCachedPlugin_cache_io_cpu_decode_isStuck = (! IBusCachedPlugin_iBusRsp_stages_2_input_ready);
  assign IBusCachedPlugin_cache_io_cpu_decode_isUser = (CsrPlugin_privilege == 2'b00);
  assign IBusCachedPlugin_rsp_iBusRspOutputHalt = 1'b0;
  assign IBusCachedPlugin_rsp_issueDetected = 1'b0;
  always @(*) begin
    IBusCachedPlugin_rsp_redoFetch = 1'b0;
    if(when_IBusCachedPlugin_l245) begin
      IBusCachedPlugin_rsp_redoFetch = 1'b1;
    end
    if(when_IBusCachedPlugin_l256) begin
      IBusCachedPlugin_rsp_redoFetch = 1'b1;
    end
  end

  always @(*) begin
    IBusCachedPlugin_cache_io_cpu_fill_valid = (IBusCachedPlugin_rsp_redoFetch && (! IBusCachedPlugin_cache_io_cpu_decode_mmuRefilling));
    if(when_IBusCachedPlugin_l256) begin
      IBusCachedPlugin_cache_io_cpu_fill_valid = 1'b1;
    end
  end

  always @(*) begin
    IBusCachedPlugin_decodeExceptionPort_valid = 1'b0;
    if(when_IBusCachedPlugin_l250) begin
      IBusCachedPlugin_decodeExceptionPort_valid = IBusCachedPlugin_iBusRsp_readyForError;
    end
    if(when_IBusCachedPlugin_l262) begin
      IBusCachedPlugin_decodeExceptionPort_valid = IBusCachedPlugin_iBusRsp_readyForError;
    end
  end

  always @(*) begin
    IBusCachedPlugin_decodeExceptionPort_payload_code = 4'bxxxx;
    if(when_IBusCachedPlugin_l250) begin
      IBusCachedPlugin_decodeExceptionPort_payload_code = 4'b1100;
    end
    if(when_IBusCachedPlugin_l262) begin
      IBusCachedPlugin_decodeExceptionPort_payload_code = 4'b0001;
    end
  end

  assign IBusCachedPlugin_decodeExceptionPort_payload_badAddr = {IBusCachedPlugin_iBusRsp_stages_2_input_payload[31 : 2],2'b00};
  assign when_IBusCachedPlugin_l245 = ((IBusCachedPlugin_cache_io_cpu_decode_isValid && IBusCachedPlugin_cache_io_cpu_decode_mmuRefilling) && (! IBusCachedPlugin_rsp_issueDetected));
  assign when_IBusCachedPlugin_l250 = ((IBusCachedPlugin_cache_io_cpu_decode_isValid && IBusCachedPlugin_cache_io_cpu_decode_mmuException) && (! IBusCachedPlugin_rsp_issueDetected_1));
  assign when_IBusCachedPlugin_l256 = ((IBusCachedPlugin_cache_io_cpu_decode_isValid && IBusCachedPlugin_cache_io_cpu_decode_cacheMiss) && (! IBusCachedPlugin_rsp_issueDetected_2));
  assign when_IBusCachedPlugin_l262 = ((IBusCachedPlugin_cache_io_cpu_decode_isValid && IBusCachedPlugin_cache_io_cpu_decode_error) && (! IBusCachedPlugin_rsp_issueDetected_3));
  assign when_IBusCachedPlugin_l273 = (IBusCachedPlugin_rsp_issueDetected_4 || IBusCachedPlugin_rsp_iBusRspOutputHalt);
  assign IBusCachedPlugin_iBusRsp_output_valid = IBusCachedPlugin_iBusRsp_stages_2_output_valid;
  assign IBusCachedPlugin_iBusRsp_stages_2_output_ready = IBusCachedPlugin_iBusRsp_output_ready;
  assign IBusCachedPlugin_iBusRsp_output_payload_rsp_inst = IBusCachedPlugin_cache_io_cpu_decode_data;
  assign IBusCachedPlugin_iBusRsp_output_payload_pc = IBusCachedPlugin_iBusRsp_stages_2_output_payload;
  assign IBusCachedPlugin_cache_io_flush = (decode_arbitration_isValid && decode_FLUSH_ALL);
  assign _zz_dBus_cmd_valid = 1'b0;
  always @(*) begin
    execute_DBusSimplePlugin_skipCmd = 1'b0;
    if(execute_ALIGNEMENT_FAULT) begin
      execute_DBusSimplePlugin_skipCmd = 1'b1;
    end
  end

  assign dBus_cmd_valid = (((((execute_arbitration_isValid && execute_MEMORY_ENABLE) && (! execute_arbitration_isStuckByOthers)) && (! execute_arbitration_isFlushed)) && (! execute_DBusSimplePlugin_skipCmd)) && (! _zz_dBus_cmd_valid));
  assign dBus_cmd_payload_wr = execute_MEMORY_STORE;
  assign dBus_cmd_payload_size = execute_INSTRUCTION[13 : 12];
  always @(*) begin
    case(dBus_cmd_payload_size)
      2'b00 : begin
        _zz_dBus_cmd_payload_data = {{{execute_RS2[7 : 0],execute_RS2[7 : 0]},execute_RS2[7 : 0]},execute_RS2[7 : 0]};
      end
      2'b01 : begin
        _zz_dBus_cmd_payload_data = {execute_RS2[15 : 0],execute_RS2[15 : 0]};
      end
      default : begin
        _zz_dBus_cmd_payload_data = execute_RS2[31 : 0];
      end
    endcase
  end

  assign dBus_cmd_payload_data = _zz_dBus_cmd_payload_data;
  assign when_DBusSimplePlugin_l435 = ((((execute_arbitration_isValid && execute_MEMORY_ENABLE) && (! dBus_cmd_ready)) && (! execute_DBusSimplePlugin_skipCmd)) && (! _zz_dBus_cmd_valid));
  always @(*) begin
    case(dBus_cmd_payload_size)
      2'b00 : begin
        _zz_execute_DBusSimplePlugin_formalMask = 4'b0001;
      end
      2'b01 : begin
        _zz_execute_DBusSimplePlugin_formalMask = 4'b0011;
      end
      default : begin
        _zz_execute_DBusSimplePlugin_formalMask = 4'b1111;
      end
    endcase
  end

  assign execute_DBusSimplePlugin_formalMask = (_zz_execute_DBusSimplePlugin_formalMask <<< dBus_cmd_payload_address[1 : 0]);
  assign dBus_cmd_payload_mask = execute_DBusSimplePlugin_formalMask;
  assign dBus_cmd_payload_address = execute_SRC_ADD;
  assign when_DBusSimplePlugin_l490 = (((memory_arbitration_isValid && memory_MEMORY_ENABLE) && (! memory_MEMORY_STORE)) && ((! dBus_rsp_ready) || 1'b0));
  always @(*) begin
    DBusSimplePlugin_memoryExceptionPort_valid = 1'b0;
    if(when_DBusSimplePlugin_l497) begin
      DBusSimplePlugin_memoryExceptionPort_valid = 1'b1;
    end
    if(memory_ALIGNEMENT_FAULT) begin
      DBusSimplePlugin_memoryExceptionPort_valid = 1'b1;
    end
    if(when_DBusSimplePlugin_l523) begin
      DBusSimplePlugin_memoryExceptionPort_valid = 1'b0;
    end
  end

  always @(*) begin
    DBusSimplePlugin_memoryExceptionPort_payload_code = 4'bxxxx;
    if(when_DBusSimplePlugin_l497) begin
      DBusSimplePlugin_memoryExceptionPort_payload_code = 4'b0101;
    end
    if(memory_ALIGNEMENT_FAULT) begin
      DBusSimplePlugin_memoryExceptionPort_payload_code = {1'd0, _zz_DBusSimplePlugin_memoryExceptionPort_payload_code};
    end
  end

  assign DBusSimplePlugin_memoryExceptionPort_payload_badAddr = memory_REGFILE_WRITE_DATA;
  assign when_DBusSimplePlugin_l497 = ((dBus_rsp_ready && dBus_rsp_error) && (! memory_MEMORY_STORE));
  assign when_DBusSimplePlugin_l523 = (! ((memory_arbitration_isValid && memory_MEMORY_ENABLE) && (1'b1 || (! memory_arbitration_isStuckByOthers))));
  always @(*) begin
    writeBack_DBusSimplePlugin_rspShifted = writeBack_MEMORY_READ_DATA;
    case(writeBack_MEMORY_ADDRESS_LOW)
      2'b01 : begin
        writeBack_DBusSimplePlugin_rspShifted[7 : 0] = writeBack_MEMORY_READ_DATA[15 : 8];
      end
      2'b10 : begin
        writeBack_DBusSimplePlugin_rspShifted[15 : 0] = writeBack_MEMORY_READ_DATA[31 : 16];
      end
      2'b11 : begin
        writeBack_DBusSimplePlugin_rspShifted[7 : 0] = writeBack_MEMORY_READ_DATA[31 : 24];
      end
      default : begin
      end
    endcase
  end

  assign switch_Misc_l245 = writeBack_INSTRUCTION[13 : 12];
  assign _zz_writeBack_DBusSimplePlugin_rspFormated = (writeBack_DBusSimplePlugin_rspShifted[7] && (! writeBack_INSTRUCTION[14]));
  always @(*) begin
    _zz_writeBack_DBusSimplePlugin_rspFormated_1[31] = _zz_writeBack_DBusSimplePlugin_rspFormated;
    _zz_writeBack_DBusSimplePlugin_rspFormated_1[30] = _zz_writeBack_DBusSimplePlugin_rspFormated;
    _zz_writeBack_DBusSimplePlugin_rspFormated_1[29] = _zz_writeBack_DBusSimplePlugin_rspFormated;
    _zz_writeBack_DBusSimplePlugin_rspFormated_1[28] = _zz_writeBack_DBusSimplePlugin_rspFormated;
    _zz_writeBack_DBusSimplePlugin_rspFormated_1[27] = _zz_writeBack_DBusSimplePlugin_rspFormated;
    _zz_writeBack_DBusSimplePlugin_rspFormated_1[26] = _zz_writeBack_DBusSimplePlugin_rspFormated;
    _zz_writeBack_DBusSimplePlugin_rspFormated_1[25] = _zz_writeBack_DBusSimplePlugin_rspFormated;
    _zz_writeBack_DBusSimplePlugin_rspFormated_1[24] = _zz_writeBack_DBusSimplePlugin_rspFormated;
    _zz_writeBack_DBusSimplePlugin_rspFormated_1[23] = _zz_writeBack_DBusSimplePlugin_rspFormated;
    _zz_writeBack_DBusSimplePlugin_rspFormated_1[22] = _zz_writeBack_DBusSimplePlugin_rspFormated;
    _zz_writeBack_DBusSimplePlugin_rspFormated_1[21] = _zz_writeBack_DBusSimplePlugin_rspFormated;
    _zz_writeBack_DBusSimplePlugin_rspFormated_1[20] = _zz_writeBack_DBusSimplePlugin_rspFormated;
    _zz_writeBack_DBusSimplePlugin_rspFormated_1[19] = _zz_writeBack_DBusSimplePlugin_rspFormated;
    _zz_writeBack_DBusSimplePlugin_rspFormated_1[18] = _zz_writeBack_DBusSimplePlugin_rspFormated;
    _zz_writeBack_DBusSimplePlugin_rspFormated_1[17] = _zz_writeBack_DBusSimplePlugin_rspFormated;
    _zz_writeBack_DBusSimplePlugin_rspFormated_1[16] = _zz_writeBack_DBusSimplePlugin_rspFormated;
    _zz_writeBack_DBusSimplePlugin_rspFormated_1[15] = _zz_writeBack_DBusSimplePlugin_rspFormated;
    _zz_writeBack_DBusSimplePlugin_rspFormated_1[14] = _zz_writeBack_DBusSimplePlugin_rspFormated;
    _zz_writeBack_DBusSimplePlugin_rspFormated_1[13] = _zz_writeBack_DBusSimplePlugin_rspFormated;
    _zz_writeBack_DBusSimplePlugin_rspFormated_1[12] = _zz_writeBack_DBusSimplePlugin_rspFormated;
    _zz_writeBack_DBusSimplePlugin_rspFormated_1[11] = _zz_writeBack_DBusSimplePlugin_rspFormated;
    _zz_writeBack_DBusSimplePlugin_rspFormated_1[10] = _zz_writeBack_DBusSimplePlugin_rspFormated;
    _zz_writeBack_DBusSimplePlugin_rspFormated_1[9] = _zz_writeBack_DBusSimplePlugin_rspFormated;
    _zz_writeBack_DBusSimplePlugin_rspFormated_1[8] = _zz_writeBack_DBusSimplePlugin_rspFormated;
    _zz_writeBack_DBusSimplePlugin_rspFormated_1[7 : 0] = writeBack_DBusSimplePlugin_rspShifted[7 : 0];
  end

  assign _zz_writeBack_DBusSimplePlugin_rspFormated_2 = (writeBack_DBusSimplePlugin_rspShifted[15] && (! writeBack_INSTRUCTION[14]));
  always @(*) begin
    _zz_writeBack_DBusSimplePlugin_rspFormated_3[31] = _zz_writeBack_DBusSimplePlugin_rspFormated_2;
    _zz_writeBack_DBusSimplePlugin_rspFormated_3[30] = _zz_writeBack_DBusSimplePlugin_rspFormated_2;
    _zz_writeBack_DBusSimplePlugin_rspFormated_3[29] = _zz_writeBack_DBusSimplePlugin_rspFormated_2;
    _zz_writeBack_DBusSimplePlugin_rspFormated_3[28] = _zz_writeBack_DBusSimplePlugin_rspFormated_2;
    _zz_writeBack_DBusSimplePlugin_rspFormated_3[27] = _zz_writeBack_DBusSimplePlugin_rspFormated_2;
    _zz_writeBack_DBusSimplePlugin_rspFormated_3[26] = _zz_writeBack_DBusSimplePlugin_rspFormated_2;
    _zz_writeBack_DBusSimplePlugin_rspFormated_3[25] = _zz_writeBack_DBusSimplePlugin_rspFormated_2;
    _zz_writeBack_DBusSimplePlugin_rspFormated_3[24] = _zz_writeBack_DBusSimplePlugin_rspFormated_2;
    _zz_writeBack_DBusSimplePlugin_rspFormated_3[23] = _zz_writeBack_DBusSimplePlugin_rspFormated_2;
    _zz_writeBack_DBusSimplePlugin_rspFormated_3[22] = _zz_writeBack_DBusSimplePlugin_rspFormated_2;
    _zz_writeBack_DBusSimplePlugin_rspFormated_3[21] = _zz_writeBack_DBusSimplePlugin_rspFormated_2;
    _zz_writeBack_DBusSimplePlugin_rspFormated_3[20] = _zz_writeBack_DBusSimplePlugin_rspFormated_2;
    _zz_writeBack_DBusSimplePlugin_rspFormated_3[19] = _zz_writeBack_DBusSimplePlugin_rspFormated_2;
    _zz_writeBack_DBusSimplePlugin_rspFormated_3[18] = _zz_writeBack_DBusSimplePlugin_rspFormated_2;
    _zz_writeBack_DBusSimplePlugin_rspFormated_3[17] = _zz_writeBack_DBusSimplePlugin_rspFormated_2;
    _zz_writeBack_DBusSimplePlugin_rspFormated_3[16] = _zz_writeBack_DBusSimplePlugin_rspFormated_2;
    _zz_writeBack_DBusSimplePlugin_rspFormated_3[15 : 0] = writeBack_DBusSimplePlugin_rspShifted[15 : 0];
  end

  always @(*) begin
    case(switch_Misc_l245)
      2'b00 : begin
        writeBack_DBusSimplePlugin_rspFormated = _zz_writeBack_DBusSimplePlugin_rspFormated_1;
      end
      2'b01 : begin
        writeBack_DBusSimplePlugin_rspFormated = _zz_writeBack_DBusSimplePlugin_rspFormated_3;
      end
      default : begin
        writeBack_DBusSimplePlugin_rspFormated = writeBack_DBusSimplePlugin_rspShifted;
      end
    endcase
  end

  assign when_DBusSimplePlugin_l566 = (writeBack_arbitration_isValid && writeBack_MEMORY_ENABLE);
  assign IBusCachedPlugin_mmuBus_rsp_physicalAddress = IBusCachedPlugin_mmuBus_cmd_0_virtualAddress;
  assign IBusCachedPlugin_mmuBus_rsp_allowRead = 1'b1;
  assign IBusCachedPlugin_mmuBus_rsp_allowWrite = 1'b1;
  assign IBusCachedPlugin_mmuBus_rsp_allowExecute = 1'b1;
  assign IBusCachedPlugin_mmuBus_rsp_isIoAccess = IBusCachedPlugin_mmuBus_rsp_physicalAddress[31];
  assign IBusCachedPlugin_mmuBus_rsp_isPaging = 1'b0;
  assign IBusCachedPlugin_mmuBus_rsp_exception = 1'b0;
  assign IBusCachedPlugin_mmuBus_rsp_refilling = 1'b0;
  assign IBusCachedPlugin_mmuBus_busy = 1'b0;
  assign _zz_decode_IS_DIV_1 = ((decode_INSTRUCTION & 32'h00004050) == 32'h00004050);
  assign _zz_decode_IS_DIV_2 = ((decode_INSTRUCTION & 32'h00000018) == 32'h0);
  assign _zz_decode_IS_DIV_3 = ((decode_INSTRUCTION & 32'h00000004) == 32'h00000004);
  assign _zz_decode_IS_DIV_4 = ((decode_INSTRUCTION & 32'h00000048) == 32'h00000048);
  assign _zz_decode_IS_DIV_5 = ((decode_INSTRUCTION & 32'h00003000) == 32'h00002000);
  assign _zz_decode_IS_DIV_6 = ((decode_INSTRUCTION & 32'h00007000) == 32'h00001000);
  assign _zz_decode_IS_DIV_7 = ((decode_INSTRUCTION & 32'h00005000) == 32'h00004000);
  assign _zz_decode_IS_DIV = {(|((decode_INSTRUCTION & _zz__zz_decode_IS_DIV) == 32'h02004020)),{(|{_zz_decode_IS_DIV_7,_zz_decode_IS_DIV_6}),{(|{_zz__zz_decode_IS_DIV_1,_zz__zz_decode_IS_DIV_2}),{(|_zz__zz_decode_IS_DIV_3),{_zz__zz_decode_IS_DIV_4,{_zz__zz_decode_IS_DIV_6,_zz__zz_decode_IS_DIV_9}}}}}};
  assign _zz_decode_SRC1_CTRL_2 = _zz_decode_IS_DIV[2 : 1];
  assign _zz_decode_SRC1_CTRL_1 = _zz_decode_SRC1_CTRL_2;
  assign _zz_decode_ALU_CTRL_2 = _zz_decode_IS_DIV[7 : 6];
  assign _zz_decode_ALU_CTRL_1 = _zz_decode_ALU_CTRL_2;
  assign _zz_decode_SRC2_CTRL_2 = _zz_decode_IS_DIV[9 : 8];
  assign _zz_decode_SRC2_CTRL_1 = _zz_decode_SRC2_CTRL_2;
  assign _zz_decode_ALU_BITWISE_CTRL_2 = _zz_decode_IS_DIV[18 : 17];
  assign _zz_decode_ALU_BITWISE_CTRL_1 = _zz_decode_ALU_BITWISE_CTRL_2;
  assign _zz_decode_SHIFT_CTRL_2 = _zz_decode_IS_DIV[21 : 20];
  assign _zz_decode_SHIFT_CTRL_1 = _zz_decode_SHIFT_CTRL_2;
  assign _zz_decode_BRANCH_CTRL_2 = _zz_decode_IS_DIV[23 : 22];
  assign _zz_decode_BRANCH_CTRL = _zz_decode_BRANCH_CTRL_2;
  assign _zz_decode_ENV_CTRL_2 = _zz_decode_IS_DIV[26 : 25];
  assign _zz_decode_ENV_CTRL_1 = _zz_decode_ENV_CTRL_2;
  assign decodeExceptionPort_valid = (decode_arbitration_isValid && (! decode_LEGAL_INSTRUCTION));
  assign decodeExceptionPort_payload_code = 4'b0010;
  assign decodeExceptionPort_payload_badAddr = decode_INSTRUCTION;
  assign when_RegFilePlugin_l63 = (decode_INSTRUCTION[11 : 7] == 5'h0);
  assign decode_RegFilePlugin_regFileReadAddress1 = decode_INSTRUCTION_ANTICIPATED[19 : 15];
  assign decode_RegFilePlugin_regFileReadAddress2 = decode_INSTRUCTION_ANTICIPATED[24 : 20];
  assign decode_RegFilePlugin_rs1Data = RegFilePlugin_regFile_spinal_port0;
  assign decode_RegFilePlugin_rs2Data = RegFilePlugin_regFile_spinal_port1;
  always @(*) begin
    lastStageRegFileWrite_valid = (_zz_lastStageRegFileWrite_valid && writeBack_arbitration_isFiring);
    if(_zz_10) begin
      lastStageRegFileWrite_valid = 1'b1;
    end
  end

  always @(*) begin
    lastStageRegFileWrite_payload_address = _zz_lastStageRegFileWrite_payload_address[11 : 7];
    if(_zz_10) begin
      lastStageRegFileWrite_payload_address = 5'h0;
    end
  end

  always @(*) begin
    lastStageRegFileWrite_payload_data = _zz_decode_RS2_2;
    if(_zz_10) begin
      lastStageRegFileWrite_payload_data = 32'h0;
    end
  end

  always @(*) begin
    case(execute_ALU_BITWISE_CTRL)
      AluBitwiseCtrlEnum_AND_1 : begin
        execute_IntAluPlugin_bitwise = (execute_SRC1 & execute_SRC2);
      end
      AluBitwiseCtrlEnum_OR_1 : begin
        execute_IntAluPlugin_bitwise = (execute_SRC1 | execute_SRC2);
      end
      default : begin
        execute_IntAluPlugin_bitwise = (execute_SRC1 ^ execute_SRC2);
      end
    endcase
  end

  always @(*) begin
    case(execute_ALU_CTRL)
      AluCtrlEnum_BITWISE : begin
        _zz_execute_REGFILE_WRITE_DATA = execute_IntAluPlugin_bitwise;
      end
      AluCtrlEnum_SLT_SLTU : begin
        _zz_execute_REGFILE_WRITE_DATA = {31'd0, _zz__zz_execute_REGFILE_WRITE_DATA};
      end
      default : begin
        _zz_execute_REGFILE_WRITE_DATA = execute_SRC_ADD_SUB;
      end
    endcase
  end

  always @(*) begin
    case(execute_SRC1_CTRL)
      Src1CtrlEnum_RS : begin
        _zz_execute_SRC1 = execute_RS1;
      end
      Src1CtrlEnum_PC_INCREMENT : begin
        _zz_execute_SRC1 = {29'd0, _zz__zz_execute_SRC1};
      end
      Src1CtrlEnum_IMU : begin
        _zz_execute_SRC1 = {execute_INSTRUCTION[31 : 12],12'h0};
      end
      default : begin
        _zz_execute_SRC1 = {27'd0, _zz__zz_execute_SRC1_1};
      end
    endcase
  end

  assign _zz_execute_SRC2 = execute_INSTRUCTION[31];
  always @(*) begin
    _zz_execute_SRC2_1[19] = _zz_execute_SRC2;
    _zz_execute_SRC2_1[18] = _zz_execute_SRC2;
    _zz_execute_SRC2_1[17] = _zz_execute_SRC2;
    _zz_execute_SRC2_1[16] = _zz_execute_SRC2;
    _zz_execute_SRC2_1[15] = _zz_execute_SRC2;
    _zz_execute_SRC2_1[14] = _zz_execute_SRC2;
    _zz_execute_SRC2_1[13] = _zz_execute_SRC2;
    _zz_execute_SRC2_1[12] = _zz_execute_SRC2;
    _zz_execute_SRC2_1[11] = _zz_execute_SRC2;
    _zz_execute_SRC2_1[10] = _zz_execute_SRC2;
    _zz_execute_SRC2_1[9] = _zz_execute_SRC2;
    _zz_execute_SRC2_1[8] = _zz_execute_SRC2;
    _zz_execute_SRC2_1[7] = _zz_execute_SRC2;
    _zz_execute_SRC2_1[6] = _zz_execute_SRC2;
    _zz_execute_SRC2_1[5] = _zz_execute_SRC2;
    _zz_execute_SRC2_1[4] = _zz_execute_SRC2;
    _zz_execute_SRC2_1[3] = _zz_execute_SRC2;
    _zz_execute_SRC2_1[2] = _zz_execute_SRC2;
    _zz_execute_SRC2_1[1] = _zz_execute_SRC2;
    _zz_execute_SRC2_1[0] = _zz_execute_SRC2;
  end

  assign _zz_execute_SRC2_2 = _zz__zz_execute_SRC2_2[11];
  always @(*) begin
    _zz_execute_SRC2_3[19] = _zz_execute_SRC2_2;
    _zz_execute_SRC2_3[18] = _zz_execute_SRC2_2;
    _zz_execute_SRC2_3[17] = _zz_execute_SRC2_2;
    _zz_execute_SRC2_3[16] = _zz_execute_SRC2_2;
    _zz_execute_SRC2_3[15] = _zz_execute_SRC2_2;
    _zz_execute_SRC2_3[14] = _zz_execute_SRC2_2;
    _zz_execute_SRC2_3[13] = _zz_execute_SRC2_2;
    _zz_execute_SRC2_3[12] = _zz_execute_SRC2_2;
    _zz_execute_SRC2_3[11] = _zz_execute_SRC2_2;
    _zz_execute_SRC2_3[10] = _zz_execute_SRC2_2;
    _zz_execute_SRC2_3[9] = _zz_execute_SRC2_2;
    _zz_execute_SRC2_3[8] = _zz_execute_SRC2_2;
    _zz_execute_SRC2_3[7] = _zz_execute_SRC2_2;
    _zz_execute_SRC2_3[6] = _zz_execute_SRC2_2;
    _zz_execute_SRC2_3[5] = _zz_execute_SRC2_2;
    _zz_execute_SRC2_3[4] = _zz_execute_SRC2_2;
    _zz_execute_SRC2_3[3] = _zz_execute_SRC2_2;
    _zz_execute_SRC2_3[2] = _zz_execute_SRC2_2;
    _zz_execute_SRC2_3[1] = _zz_execute_SRC2_2;
    _zz_execute_SRC2_3[0] = _zz_execute_SRC2_2;
  end

  always @(*) begin
    case(execute_SRC2_CTRL)
      Src2CtrlEnum_RS : begin
        _zz_execute_SRC2_4 = execute_RS2;
      end
      Src2CtrlEnum_IMI : begin
        _zz_execute_SRC2_4 = {_zz_execute_SRC2_1,execute_INSTRUCTION[31 : 20]};
      end
      Src2CtrlEnum_IMS : begin
        _zz_execute_SRC2_4 = {_zz_execute_SRC2_3,{execute_INSTRUCTION[31 : 25],execute_INSTRUCTION[11 : 7]}};
      end
      default : begin
        _zz_execute_SRC2_4 = _zz_execute_to_memory_PC;
      end
    endcase
  end

  always @(*) begin
    execute_SrcPlugin_addSub = _zz_execute_SrcPlugin_addSub;
    if(execute_SRC2_FORCE_ZERO) begin
      execute_SrcPlugin_addSub = execute_SRC1;
    end
  end

  assign execute_SrcPlugin_less = ((execute_SRC1[31] == execute_SRC2[31]) ? execute_SrcPlugin_addSub[31] : (execute_SRC_LESS_UNSIGNED ? execute_SRC2[31] : execute_SRC1[31]));
  assign execute_LightShifterPlugin_isShift = (execute_SHIFT_CTRL != ShiftCtrlEnum_DISABLE_1);
  assign execute_LightShifterPlugin_amplitude = (execute_LightShifterPlugin_isActive ? execute_LightShifterPlugin_amplitudeReg : execute_SRC2[4 : 0]);
  assign execute_LightShifterPlugin_shiftInput = (execute_LightShifterPlugin_isActive ? memory_REGFILE_WRITE_DATA : execute_SRC1);
  assign execute_LightShifterPlugin_done = (execute_LightShifterPlugin_amplitude[4 : 1] == 4'b0000);
  assign when_ShiftPlugins_l169 = ((execute_arbitration_isValid && execute_LightShifterPlugin_isShift) && (execute_SRC2[4 : 0] != 5'h0));
  always @(*) begin
    case(execute_SHIFT_CTRL)
      ShiftCtrlEnum_SLL_1 : begin
        _zz_decode_RS2_3 = (execute_LightShifterPlugin_shiftInput <<< 1);
      end
      default : begin
        _zz_decode_RS2_3 = _zz__zz_decode_RS2_3;
      end
    endcase
  end

  assign when_ShiftPlugins_l175 = (! execute_arbitration_isStuckByOthers);
  assign when_ShiftPlugins_l184 = (! execute_LightShifterPlugin_done);
  always @(*) begin
    HazardSimplePlugin_src0Hazard = 1'b0;
    if(when_HazardSimplePlugin_l57) begin
      if(when_HazardSimplePlugin_l58) begin
        if(when_HazardSimplePlugin_l48) begin
          HazardSimplePlugin_src0Hazard = 1'b1;
        end
      end
    end
    if(when_HazardSimplePlugin_l57_1) begin
      if(when_HazardSimplePlugin_l58_1) begin
        if(when_HazardSimplePlugin_l48_1) begin
          HazardSimplePlugin_src0Hazard = 1'b1;
        end
      end
    end
    if(when_HazardSimplePlugin_l57_2) begin
      if(when_HazardSimplePlugin_l58_2) begin
        if(when_HazardSimplePlugin_l48_2) begin
          HazardSimplePlugin_src0Hazard = 1'b1;
        end
      end
    end
    if(when_HazardSimplePlugin_l105) begin
      HazardSimplePlugin_src0Hazard = 1'b0;
    end
  end

  always @(*) begin
    HazardSimplePlugin_src1Hazard = 1'b0;
    if(when_HazardSimplePlugin_l57) begin
      if(when_HazardSimplePlugin_l58) begin
        if(when_HazardSimplePlugin_l51) begin
          HazardSimplePlugin_src1Hazard = 1'b1;
        end
      end
    end
    if(when_HazardSimplePlugin_l57_1) begin
      if(when_HazardSimplePlugin_l58_1) begin
        if(when_HazardSimplePlugin_l51_1) begin
          HazardSimplePlugin_src1Hazard = 1'b1;
        end
      end
    end
    if(when_HazardSimplePlugin_l57_2) begin
      if(when_HazardSimplePlugin_l58_2) begin
        if(when_HazardSimplePlugin_l51_2) begin
          HazardSimplePlugin_src1Hazard = 1'b1;
        end
      end
    end
    if(when_HazardSimplePlugin_l108) begin
      HazardSimplePlugin_src1Hazard = 1'b0;
    end
  end

  assign HazardSimplePlugin_writeBackWrites_valid = (_zz_lastStageRegFileWrite_valid && writeBack_arbitration_isFiring);
  assign HazardSimplePlugin_writeBackWrites_payload_address = _zz_lastStageRegFileWrite_payload_address[11 : 7];
  assign HazardSimplePlugin_writeBackWrites_payload_data = _zz_decode_RS2_2;
  assign HazardSimplePlugin_addr0Match = (HazardSimplePlugin_writeBackBuffer_payload_address == decode_INSTRUCTION[19 : 15]);
  assign HazardSimplePlugin_addr1Match = (HazardSimplePlugin_writeBackBuffer_payload_address == decode_INSTRUCTION[24 : 20]);
  assign when_HazardSimplePlugin_l47 = 1'b1;
  assign when_HazardSimplePlugin_l48 = (writeBack_INSTRUCTION[11 : 7] == decode_INSTRUCTION[19 : 15]);
  assign when_HazardSimplePlugin_l51 = (writeBack_INSTRUCTION[11 : 7] == decode_INSTRUCTION[24 : 20]);
  assign when_HazardSimplePlugin_l45 = (writeBack_arbitration_isValid && writeBack_REGFILE_WRITE_VALID);
  assign when_HazardSimplePlugin_l57 = (writeBack_arbitration_isValid && writeBack_REGFILE_WRITE_VALID);
  assign when_HazardSimplePlugin_l58 = (1'b0 || (! when_HazardSimplePlugin_l47));
  assign when_HazardSimplePlugin_l48_1 = (memory_INSTRUCTION[11 : 7] == decode_INSTRUCTION[19 : 15]);
  assign when_HazardSimplePlugin_l51_1 = (memory_INSTRUCTION[11 : 7] == decode_INSTRUCTION[24 : 20]);
  assign when_HazardSimplePlugin_l45_1 = (memory_arbitration_isValid && memory_REGFILE_WRITE_VALID);
  assign when_HazardSimplePlugin_l57_1 = (memory_arbitration_isValid && memory_REGFILE_WRITE_VALID);
  assign when_HazardSimplePlugin_l58_1 = (1'b0 || (! memory_BYPASSABLE_MEMORY_STAGE));
  assign when_HazardSimplePlugin_l48_2 = (execute_INSTRUCTION[11 : 7] == decode_INSTRUCTION[19 : 15]);
  assign when_HazardSimplePlugin_l51_2 = (execute_INSTRUCTION[11 : 7] == decode_INSTRUCTION[24 : 20]);
  assign when_HazardSimplePlugin_l45_2 = (execute_arbitration_isValid && execute_REGFILE_WRITE_VALID);
  assign when_HazardSimplePlugin_l57_2 = (execute_arbitration_isValid && execute_REGFILE_WRITE_VALID);
  assign when_HazardSimplePlugin_l58_2 = (1'b0 || (! execute_BYPASSABLE_EXECUTE_STAGE));
  assign when_HazardSimplePlugin_l105 = (! decode_RS1_USE);
  assign when_HazardSimplePlugin_l108 = (! decode_RS2_USE);
  assign when_HazardSimplePlugin_l113 = (decode_arbitration_isValid && (HazardSimplePlugin_src0Hazard || HazardSimplePlugin_src1Hazard));
  assign execute_BranchPlugin_eq = (execute_SRC1 == execute_SRC2);
  assign switch_Misc_l245_1 = execute_INSTRUCTION[14 : 12];
  always @(*) begin
    case(switch_Misc_l245_1)
      3'b000 : begin
        _zz_execute_BRANCH_COND_RESULT = execute_BranchPlugin_eq;
      end
      3'b001 : begin
        _zz_execute_BRANCH_COND_RESULT = (! execute_BranchPlugin_eq);
      end
      3'b101 : begin
        _zz_execute_BRANCH_COND_RESULT = (! execute_SRC_LESS);
      end
      3'b111 : begin
        _zz_execute_BRANCH_COND_RESULT = (! execute_SRC_LESS);
      end
      default : begin
        _zz_execute_BRANCH_COND_RESULT = execute_SRC_LESS;
      end
    endcase
  end

  always @(*) begin
    case(execute_BRANCH_CTRL)
      BranchCtrlEnum_INC : begin
        _zz_execute_BRANCH_COND_RESULT_1 = 1'b0;
      end
      BranchCtrlEnum_JAL : begin
        _zz_execute_BRANCH_COND_RESULT_1 = 1'b1;
      end
      BranchCtrlEnum_JALR : begin
        _zz_execute_BRANCH_COND_RESULT_1 = 1'b1;
      end
      default : begin
        _zz_execute_BRANCH_COND_RESULT_1 = _zz_execute_BRANCH_COND_RESULT;
      end
    endcase
  end

  assign _zz_execute_BranchPlugin_missAlignedTarget = execute_INSTRUCTION[31];
  always @(*) begin
    _zz_execute_BranchPlugin_missAlignedTarget_1[19] = _zz_execute_BranchPlugin_missAlignedTarget;
    _zz_execute_BranchPlugin_missAlignedTarget_1[18] = _zz_execute_BranchPlugin_missAlignedTarget;
    _zz_execute_BranchPlugin_missAlignedTarget_1[17] = _zz_execute_BranchPlugin_missAlignedTarget;
    _zz_execute_BranchPlugin_missAlignedTarget_1[16] = _zz_execute_BranchPlugin_missAlignedTarget;
    _zz_execute_BranchPlugin_missAlignedTarget_1[15] = _zz_execute_BranchPlugin_missAlignedTarget;
    _zz_execute_BranchPlugin_missAlignedTarget_1[14] = _zz_execute_BranchPlugin_missAlignedTarget;
    _zz_execute_BranchPlugin_missAlignedTarget_1[13] = _zz_execute_BranchPlugin_missAlignedTarget;
    _zz_execute_BranchPlugin_missAlignedTarget_1[12] = _zz_execute_BranchPlugin_missAlignedTarget;
    _zz_execute_BranchPlugin_missAlignedTarget_1[11] = _zz_execute_BranchPlugin_missAlignedTarget;
    _zz_execute_BranchPlugin_missAlignedTarget_1[10] = _zz_execute_BranchPlugin_missAlignedTarget;
    _zz_execute_BranchPlugin_missAlignedTarget_1[9] = _zz_execute_BranchPlugin_missAlignedTarget;
    _zz_execute_BranchPlugin_missAlignedTarget_1[8] = _zz_execute_BranchPlugin_missAlignedTarget;
    _zz_execute_BranchPlugin_missAlignedTarget_1[7] = _zz_execute_BranchPlugin_missAlignedTarget;
    _zz_execute_BranchPlugin_missAlignedTarget_1[6] = _zz_execute_BranchPlugin_missAlignedTarget;
    _zz_execute_BranchPlugin_missAlignedTarget_1[5] = _zz_execute_BranchPlugin_missAlignedTarget;
    _zz_execute_BranchPlugin_missAlignedTarget_1[4] = _zz_execute_BranchPlugin_missAlignedTarget;
    _zz_execute_BranchPlugin_missAlignedTarget_1[3] = _zz_execute_BranchPlugin_missAlignedTarget;
    _zz_execute_BranchPlugin_missAlignedTarget_1[2] = _zz_execute_BranchPlugin_missAlignedTarget;
    _zz_execute_BranchPlugin_missAlignedTarget_1[1] = _zz_execute_BranchPlugin_missAlignedTarget;
    _zz_execute_BranchPlugin_missAlignedTarget_1[0] = _zz_execute_BranchPlugin_missAlignedTarget;
  end

  assign _zz_execute_BranchPlugin_missAlignedTarget_2 = _zz__zz_execute_BranchPlugin_missAlignedTarget_2[19];
  always @(*) begin
    _zz_execute_BranchPlugin_missAlignedTarget_3[10] = _zz_execute_BranchPlugin_missAlignedTarget_2;
    _zz_execute_BranchPlugin_missAlignedTarget_3[9] = _zz_execute_BranchPlugin_missAlignedTarget_2;
    _zz_execute_BranchPlugin_missAlignedTarget_3[8] = _zz_execute_BranchPlugin_missAlignedTarget_2;
    _zz_execute_BranchPlugin_missAlignedTarget_3[7] = _zz_execute_BranchPlugin_missAlignedTarget_2;
    _zz_execute_BranchPlugin_missAlignedTarget_3[6] = _zz_execute_BranchPlugin_missAlignedTarget_2;
    _zz_execute_BranchPlugin_missAlignedTarget_3[5] = _zz_execute_BranchPlugin_missAlignedTarget_2;
    _zz_execute_BranchPlugin_missAlignedTarget_3[4] = _zz_execute_BranchPlugin_missAlignedTarget_2;
    _zz_execute_BranchPlugin_missAlignedTarget_3[3] = _zz_execute_BranchPlugin_missAlignedTarget_2;
    _zz_execute_BranchPlugin_missAlignedTarget_3[2] = _zz_execute_BranchPlugin_missAlignedTarget_2;
    _zz_execute_BranchPlugin_missAlignedTarget_3[1] = _zz_execute_BranchPlugin_missAlignedTarget_2;
    _zz_execute_BranchPlugin_missAlignedTarget_3[0] = _zz_execute_BranchPlugin_missAlignedTarget_2;
  end

  assign _zz_execute_BranchPlugin_missAlignedTarget_4 = _zz__zz_execute_BranchPlugin_missAlignedTarget_4[11];
  always @(*) begin
    _zz_execute_BranchPlugin_missAlignedTarget_5[18] = _zz_execute_BranchPlugin_missAlignedTarget_4;
    _zz_execute_BranchPlugin_missAlignedTarget_5[17] = _zz_execute_BranchPlugin_missAlignedTarget_4;
    _zz_execute_BranchPlugin_missAlignedTarget_5[16] = _zz_execute_BranchPlugin_missAlignedTarget_4;
    _zz_execute_BranchPlugin_missAlignedTarget_5[15] = _zz_execute_BranchPlugin_missAlignedTarget_4;
    _zz_execute_BranchPlugin_missAlignedTarget_5[14] = _zz_execute_BranchPlugin_missAlignedTarget_4;
    _zz_execute_BranchPlugin_missAlignedTarget_5[13] = _zz_execute_BranchPlugin_missAlignedTarget_4;
    _zz_execute_BranchPlugin_missAlignedTarget_5[12] = _zz_execute_BranchPlugin_missAlignedTarget_4;
    _zz_execute_BranchPlugin_missAlignedTarget_5[11] = _zz_execute_BranchPlugin_missAlignedTarget_4;
    _zz_execute_BranchPlugin_missAlignedTarget_5[10] = _zz_execute_BranchPlugin_missAlignedTarget_4;
    _zz_execute_BranchPlugin_missAlignedTarget_5[9] = _zz_execute_BranchPlugin_missAlignedTarget_4;
    _zz_execute_BranchPlugin_missAlignedTarget_5[8] = _zz_execute_BranchPlugin_missAlignedTarget_4;
    _zz_execute_BranchPlugin_missAlignedTarget_5[7] = _zz_execute_BranchPlugin_missAlignedTarget_4;
    _zz_execute_BranchPlugin_missAlignedTarget_5[6] = _zz_execute_BranchPlugin_missAlignedTarget_4;
    _zz_execute_BranchPlugin_missAlignedTarget_5[5] = _zz_execute_BranchPlugin_missAlignedTarget_4;
    _zz_execute_BranchPlugin_missAlignedTarget_5[4] = _zz_execute_BranchPlugin_missAlignedTarget_4;
    _zz_execute_BranchPlugin_missAlignedTarget_5[3] = _zz_execute_BranchPlugin_missAlignedTarget_4;
    _zz_execute_BranchPlugin_missAlignedTarget_5[2] = _zz_execute_BranchPlugin_missAlignedTarget_4;
    _zz_execute_BranchPlugin_missAlignedTarget_5[1] = _zz_execute_BranchPlugin_missAlignedTarget_4;
    _zz_execute_BranchPlugin_missAlignedTarget_5[0] = _zz_execute_BranchPlugin_missAlignedTarget_4;
  end

  always @(*) begin
    case(execute_BRANCH_CTRL)
      BranchCtrlEnum_JALR : begin
        _zz_execute_BranchPlugin_missAlignedTarget_6 = (_zz__zz_execute_BranchPlugin_missAlignedTarget_6[1] ^ execute_RS1[1]);
      end
      BranchCtrlEnum_JAL : begin
        _zz_execute_BranchPlugin_missAlignedTarget_6 = _zz__zz_execute_BranchPlugin_missAlignedTarget_6_1[1];
      end
      default : begin
        _zz_execute_BranchPlugin_missAlignedTarget_6 = _zz__zz_execute_BranchPlugin_missAlignedTarget_6_2[1];
      end
    endcase
  end

  assign execute_BranchPlugin_missAlignedTarget = (execute_BRANCH_COND_RESULT && _zz_execute_BranchPlugin_missAlignedTarget_6);
  always @(*) begin
    case(execute_BRANCH_CTRL)
      BranchCtrlEnum_JALR : begin
        execute_BranchPlugin_branch_src1 = execute_RS1;
      end
      default : begin
        execute_BranchPlugin_branch_src1 = execute_PC;
      end
    endcase
  end

  assign _zz_execute_BranchPlugin_branch_src2 = execute_INSTRUCTION[31];
  always @(*) begin
    _zz_execute_BranchPlugin_branch_src2_1[19] = _zz_execute_BranchPlugin_branch_src2;
    _zz_execute_BranchPlugin_branch_src2_1[18] = _zz_execute_BranchPlugin_branch_src2;
    _zz_execute_BranchPlugin_branch_src2_1[17] = _zz_execute_BranchPlugin_branch_src2;
    _zz_execute_BranchPlugin_branch_src2_1[16] = _zz_execute_BranchPlugin_branch_src2;
    _zz_execute_BranchPlugin_branch_src2_1[15] = _zz_execute_BranchPlugin_branch_src2;
    _zz_execute_BranchPlugin_branch_src2_1[14] = _zz_execute_BranchPlugin_branch_src2;
    _zz_execute_BranchPlugin_branch_src2_1[13] = _zz_execute_BranchPlugin_branch_src2;
    _zz_execute_BranchPlugin_branch_src2_1[12] = _zz_execute_BranchPlugin_branch_src2;
    _zz_execute_BranchPlugin_branch_src2_1[11] = _zz_execute_BranchPlugin_branch_src2;
    _zz_execute_BranchPlugin_branch_src2_1[10] = _zz_execute_BranchPlugin_branch_src2;
    _zz_execute_BranchPlugin_branch_src2_1[9] = _zz_execute_BranchPlugin_branch_src2;
    _zz_execute_BranchPlugin_branch_src2_1[8] = _zz_execute_BranchPlugin_branch_src2;
    _zz_execute_BranchPlugin_branch_src2_1[7] = _zz_execute_BranchPlugin_branch_src2;
    _zz_execute_BranchPlugin_branch_src2_1[6] = _zz_execute_BranchPlugin_branch_src2;
    _zz_execute_BranchPlugin_branch_src2_1[5] = _zz_execute_BranchPlugin_branch_src2;
    _zz_execute_BranchPlugin_branch_src2_1[4] = _zz_execute_BranchPlugin_branch_src2;
    _zz_execute_BranchPlugin_branch_src2_1[3] = _zz_execute_BranchPlugin_branch_src2;
    _zz_execute_BranchPlugin_branch_src2_1[2] = _zz_execute_BranchPlugin_branch_src2;
    _zz_execute_BranchPlugin_branch_src2_1[1] = _zz_execute_BranchPlugin_branch_src2;
    _zz_execute_BranchPlugin_branch_src2_1[0] = _zz_execute_BranchPlugin_branch_src2;
  end

  always @(*) begin
    case(execute_BRANCH_CTRL)
      BranchCtrlEnum_JALR : begin
        execute_BranchPlugin_branch_src2 = {_zz_execute_BranchPlugin_branch_src2_1,execute_INSTRUCTION[31 : 20]};
      end
      default : begin
        execute_BranchPlugin_branch_src2 = ((execute_BRANCH_CTRL == BranchCtrlEnum_JAL) ? {{_zz_execute_BranchPlugin_branch_src2_3,{{{_zz_execute_BranchPlugin_branch_src2_6,_zz_execute_BranchPlugin_branch_src2_7},_zz_execute_BranchPlugin_branch_src2_8},execute_INSTRUCTION[30 : 21]}},1'b0} : {{_zz_execute_BranchPlugin_branch_src2_5,{{{_zz_execute_BranchPlugin_branch_src2_9,_zz_execute_BranchPlugin_branch_src2_10},execute_INSTRUCTION[30 : 25]},execute_INSTRUCTION[11 : 8]}},1'b0});
        if(execute_PREDICTION_HAD_BRANCHED1) begin
          execute_BranchPlugin_branch_src2 = {29'd0, _zz_execute_BranchPlugin_branch_src2_11};
        end
      end
    endcase
  end

  assign _zz_execute_BranchPlugin_branch_src2_2 = _zz__zz_execute_BranchPlugin_branch_src2_2[19];
  always @(*) begin
    _zz_execute_BranchPlugin_branch_src2_3[10] = _zz_execute_BranchPlugin_branch_src2_2;
    _zz_execute_BranchPlugin_branch_src2_3[9] = _zz_execute_BranchPlugin_branch_src2_2;
    _zz_execute_BranchPlugin_branch_src2_3[8] = _zz_execute_BranchPlugin_branch_src2_2;
    _zz_execute_BranchPlugin_branch_src2_3[7] = _zz_execute_BranchPlugin_branch_src2_2;
    _zz_execute_BranchPlugin_branch_src2_3[6] = _zz_execute_BranchPlugin_branch_src2_2;
    _zz_execute_BranchPlugin_branch_src2_3[5] = _zz_execute_BranchPlugin_branch_src2_2;
    _zz_execute_BranchPlugin_branch_src2_3[4] = _zz_execute_BranchPlugin_branch_src2_2;
    _zz_execute_BranchPlugin_branch_src2_3[3] = _zz_execute_BranchPlugin_branch_src2_2;
    _zz_execute_BranchPlugin_branch_src2_3[2] = _zz_execute_BranchPlugin_branch_src2_2;
    _zz_execute_BranchPlugin_branch_src2_3[1] = _zz_execute_BranchPlugin_branch_src2_2;
    _zz_execute_BranchPlugin_branch_src2_3[0] = _zz_execute_BranchPlugin_branch_src2_2;
  end

  assign _zz_execute_BranchPlugin_branch_src2_4 = _zz__zz_execute_BranchPlugin_branch_src2_4[11];
  always @(*) begin
    _zz_execute_BranchPlugin_branch_src2_5[18] = _zz_execute_BranchPlugin_branch_src2_4;
    _zz_execute_BranchPlugin_branch_src2_5[17] = _zz_execute_BranchPlugin_branch_src2_4;
    _zz_execute_BranchPlugin_branch_src2_5[16] = _zz_execute_BranchPlugin_branch_src2_4;
    _zz_execute_BranchPlugin_branch_src2_5[15] = _zz_execute_BranchPlugin_branch_src2_4;
    _zz_execute_BranchPlugin_branch_src2_5[14] = _zz_execute_BranchPlugin_branch_src2_4;
    _zz_execute_BranchPlugin_branch_src2_5[13] = _zz_execute_BranchPlugin_branch_src2_4;
    _zz_execute_BranchPlugin_branch_src2_5[12] = _zz_execute_BranchPlugin_branch_src2_4;
    _zz_execute_BranchPlugin_branch_src2_5[11] = _zz_execute_BranchPlugin_branch_src2_4;
    _zz_execute_BranchPlugin_branch_src2_5[10] = _zz_execute_BranchPlugin_branch_src2_4;
    _zz_execute_BranchPlugin_branch_src2_5[9] = _zz_execute_BranchPlugin_branch_src2_4;
    _zz_execute_BranchPlugin_branch_src2_5[8] = _zz_execute_BranchPlugin_branch_src2_4;
    _zz_execute_BranchPlugin_branch_src2_5[7] = _zz_execute_BranchPlugin_branch_src2_4;
    _zz_execute_BranchPlugin_branch_src2_5[6] = _zz_execute_BranchPlugin_branch_src2_4;
    _zz_execute_BranchPlugin_branch_src2_5[5] = _zz_execute_BranchPlugin_branch_src2_4;
    _zz_execute_BranchPlugin_branch_src2_5[4] = _zz_execute_BranchPlugin_branch_src2_4;
    _zz_execute_BranchPlugin_branch_src2_5[3] = _zz_execute_BranchPlugin_branch_src2_4;
    _zz_execute_BranchPlugin_branch_src2_5[2] = _zz_execute_BranchPlugin_branch_src2_4;
    _zz_execute_BranchPlugin_branch_src2_5[1] = _zz_execute_BranchPlugin_branch_src2_4;
    _zz_execute_BranchPlugin_branch_src2_5[0] = _zz_execute_BranchPlugin_branch_src2_4;
  end

  assign execute_BranchPlugin_branchAdder = (execute_BranchPlugin_branch_src1 + execute_BranchPlugin_branch_src2);
  assign BranchPlugin_jumpInterface_valid = ((memory_arbitration_isValid && memory_BRANCH_DO) && (! 1'b0));
  assign BranchPlugin_jumpInterface_payload = memory_BRANCH_CALC;
  assign BranchPlugin_branchExceptionPort_valid = (memory_arbitration_isValid && (memory_BRANCH_DO && memory_BRANCH_CALC[1]));
  assign BranchPlugin_branchExceptionPort_payload_code = 4'b0000;
  assign BranchPlugin_branchExceptionPort_payload_badAddr = memory_BRANCH_CALC;
  assign IBusCachedPlugin_decodePrediction_rsp_wasWrong = BranchPlugin_jumpInterface_valid;
  always @(*) begin
    when_CsrPlugin_l818 = 1'b0;
    if(CsrPlugin_trigger_decodeBreak_enabled) begin
      if(CsrPlugin_trigger_decodeBreak_timeout_state) begin
        when_CsrPlugin_l818 = 1'b1;
      end
    end
    if(when_CsrPlugin_l1390) begin
      when_CsrPlugin_l818 = 1'b1;
    end
  end

  always @(*) begin
    CsrPlugin_privilege = _zz_CsrPlugin_privilege;
    if(CsrPlugin_forceMachineWire) begin
      CsrPlugin_privilege = 2'b11;
    end
  end

  assign debugMode = (! CsrPlugin_running);
  assign when_CsrPlugin_l711 = (! CsrPlugin_running);
  always @(*) begin
    debugBus_resume_rsp_valid = 1'b0;
    if(CsrPlugin_doResume) begin
      debugBus_resume_rsp_valid = 1'b1;
    end
  end

  assign debugBus_running = CsrPlugin_running;
  assign debugBus_halted = (! CsrPlugin_running);
  assign debugBus_unavailable = reset_buffercc_io_dataOut;
  assign debugBus_haveReset = _zz_debugBus_haveReset;
  assign CsrPlugin_enterHalt = ((! CsrPlugin_running_aheadValue) && CsrPlugin_running_aheadValue_regNext);
  assign when_CsrPlugin_l729 = ((debugBus_haltReq && debugBus_running) && (! debugMode));
  assign CsrPlugin_forceResume = 1'b0;
  assign CsrPlugin_doResume = (CsrPlugin_forceResume || _zz_CsrPlugin_doResume);
  always @(*) begin
    CsrPlugin_timeout_stateRise = 1'b0;
    if(CsrPlugin_timeout_counter_willOverflow) begin
      CsrPlugin_timeout_stateRise = (! CsrPlugin_timeout_state);
    end
    if(when_CsrPlugin_l735) begin
      CsrPlugin_timeout_stateRise = 1'b0;
    end
    if(CsrPlugin_inject_cmd_valid) begin
      CsrPlugin_timeout_stateRise = 1'b0;
    end
    case(CsrPlugin_dcsr_stepLogic_stateReg)
      CsrPlugin_dcsr_stepLogic_IDLE : begin
      end
      CsrPlugin_dcsr_stepLogic_SINGLE : begin
        CsrPlugin_timeout_stateRise = 1'b0;
      end
      CsrPlugin_dcsr_stepLogic_WAIT_1 : begin
      end
      default : begin
      end
    endcase
  end

  always @(*) begin
    CsrPlugin_timeout_counter_willClear = 1'b0;
    if(when_CsrPlugin_l735) begin
      CsrPlugin_timeout_counter_willClear = 1'b1;
    end
    if(CsrPlugin_inject_cmd_valid) begin
      CsrPlugin_timeout_counter_willClear = 1'b1;
    end
    case(CsrPlugin_dcsr_stepLogic_stateReg)
      CsrPlugin_dcsr_stepLogic_IDLE : begin
      end
      CsrPlugin_dcsr_stepLogic_SINGLE : begin
        CsrPlugin_timeout_counter_willClear = 1'b1;
      end
      CsrPlugin_dcsr_stepLogic_WAIT_1 : begin
      end
      default : begin
      end
    endcase
  end

  assign CsrPlugin_timeout_counter_willOverflowIfInc = (CsrPlugin_timeout_counter_value == 3'b110);
  assign CsrPlugin_timeout_counter_willOverflow = (CsrPlugin_timeout_counter_willOverflowIfInc && CsrPlugin_timeout_counter_willIncrement);
  always @(*) begin
    if(CsrPlugin_timeout_counter_willOverflow) begin
      CsrPlugin_timeout_counter_valueNext = 3'b000;
    end else begin
      CsrPlugin_timeout_counter_valueNext = (CsrPlugin_timeout_counter_value + _zz_CsrPlugin_timeout_counter_valueNext);
    end
    if(CsrPlugin_timeout_counter_willClear) begin
      CsrPlugin_timeout_counter_valueNext = 3'b000;
    end
  end

  assign CsrPlugin_timeout_counter_willIncrement = 1'b1;
  assign when_CsrPlugin_l735 = (|{writeBack_arbitration_isValid,{memory_arbitration_isValid,execute_arbitration_isValid}});
  always @(*) begin
    _zz_debugBus_hartToDm_valid = 1'b0;
    if(execute_CsrPlugin_csr_1972) begin
      if(execute_CsrPlugin_writeEnable) begin
        _zz_debugBus_hartToDm_valid = 1'b1;
      end
    end
  end

  assign debugBus_hartToDm_valid = _zz_debugBus_hartToDm_valid;
  assign debugBus_hartToDm_payload_address = 4'b0000;
  assign debugBus_hartToDm_payload_data = execute_SRC1;
  assign when_CsrPlugin_l750 = (debugBus_dmToHart_valid && (debugBus_dmToHart_payload_op == DebugDmToHartOp_DATA));
  assign CsrPlugin_inject_cmd_valid = (debugBus_dmToHart_valid && (((debugBus_dmToHart_payload_op == DebugDmToHartOp_EXECUTE) || (debugBus_dmToHart_payload_op == DebugDmToHartOp_REG_READ)) || (debugBus_dmToHart_payload_op == DebugDmToHartOp_REG_WRITE)));
  assign CsrPlugin_inject_cmd_payload_op = debugBus_dmToHart_payload_op;
  assign CsrPlugin_inject_cmd_payload_address = debugBus_dmToHart_payload_address;
  assign CsrPlugin_inject_cmd_payload_data = debugBus_dmToHart_payload_data;
  assign CsrPlugin_inject_cmd_payload_size = debugBus_dmToHart_payload_size;
  assign CsrPlugin_inject_cmd_toStream_valid = CsrPlugin_inject_cmd_valid;
  assign CsrPlugin_inject_cmd_toStream_payload_op = CsrPlugin_inject_cmd_payload_op;
  assign CsrPlugin_inject_cmd_toStream_payload_address = CsrPlugin_inject_cmd_payload_address;
  assign CsrPlugin_inject_cmd_toStream_payload_data = CsrPlugin_inject_cmd_payload_data;
  assign CsrPlugin_inject_cmd_toStream_payload_size = CsrPlugin_inject_cmd_payload_size;
  always @(*) begin
    CsrPlugin_inject_cmd_toStream_ready = CsrPlugin_inject_buffer_ready;
    if(when_Stream_l477) begin
      CsrPlugin_inject_cmd_toStream_ready = 1'b1;
    end
  end

  assign when_Stream_l477 = (! CsrPlugin_inject_buffer_valid);
  assign CsrPlugin_inject_buffer_valid = CsrPlugin_inject_cmd_toStream_rValid;
  assign CsrPlugin_inject_buffer_payload_op = CsrPlugin_inject_cmd_toStream_rData_op;
  assign CsrPlugin_inject_buffer_payload_address = CsrPlugin_inject_cmd_toStream_rData_address;
  assign CsrPlugin_inject_buffer_payload_data = CsrPlugin_inject_cmd_toStream_rData_data;
  assign CsrPlugin_inject_buffer_payload_size = CsrPlugin_inject_cmd_toStream_rData_size;
  assign CsrPlugin_injectionPort_valid = (CsrPlugin_inject_buffer_valid && (CsrPlugin_inject_buffer_payload_op == DebugDmToHartOp_EXECUTE));
  assign CsrPlugin_injectionPort_payload = CsrPlugin_inject_buffer_payload_data;
  assign CsrPlugin_injectionPort_fire = (CsrPlugin_injectionPort_valid && CsrPlugin_injectionPort_ready);
  assign CsrPlugin_inject_buffer_ready = CsrPlugin_injectionPort_fire;
  assign debugBus_regSuccess = 1'b0;
  assign when_CsrPlugin_l786 = (CsrPlugin_inject_cmd_valid && (debugBus_dmToHart_payload_op == DebugDmToHartOp_EXECUTE));
  assign when_CsrPlugin_l786_1 = (((debugBus_exception || debugBus_commit) || debugBus_ebreak) || debugBus_redo);
  assign debugBus_redo = (CsrPlugin_inject_pending && CsrPlugin_timeout_state);
  assign CsrPlugin_dcsr_nmip = 1'b0;
  assign CsrPlugin_dcsr_mprven = 1'b1;
  assign CsrPlugin_dcsr_xdebugver = 4'b0100;
  assign CsrPlugin_dcsr_stepLogic_wantExit = 1'b0;
  always @(*) begin
    CsrPlugin_dcsr_stepLogic_wantStart = 1'b0;
    case(CsrPlugin_dcsr_stepLogic_stateReg)
      CsrPlugin_dcsr_stepLogic_IDLE : begin
      end
      CsrPlugin_dcsr_stepLogic_SINGLE : begin
      end
      CsrPlugin_dcsr_stepLogic_WAIT_1 : begin
      end
      default : begin
        CsrPlugin_dcsr_stepLogic_wantStart = 1'b1;
      end
    endcase
  end

  assign CsrPlugin_dcsr_stepLogic_wantKill = 1'b0;
  always @(*) begin
    CsrPlugin_dcsr_stepLogic_stateNext = CsrPlugin_dcsr_stepLogic_stateReg;
    case(CsrPlugin_dcsr_stepLogic_stateReg)
      CsrPlugin_dcsr_stepLogic_IDLE : begin
        if(when_CsrPlugin_l812) begin
          CsrPlugin_dcsr_stepLogic_stateNext = CsrPlugin_dcsr_stepLogic_SINGLE;
        end
      end
      CsrPlugin_dcsr_stepLogic_SINGLE : begin
        if(when_CsrPlugin_l818) begin
          CsrPlugin_dcsr_stepLogic_stateNext = CsrPlugin_dcsr_stepLogic_WAIT_1;
        end
        if(decode_arbitration_isFiring) begin
          CsrPlugin_dcsr_stepLogic_stateNext = CsrPlugin_dcsr_stepLogic_WAIT_1;
        end
      end
      CsrPlugin_dcsr_stepLogic_WAIT_1 : begin
        if(when_CsrPlugin_l830) begin
          CsrPlugin_dcsr_stepLogic_stateNext = CsrPlugin_dcsr_stepLogic_SINGLE;
        end
      end
      default : begin
      end
    endcase
    if(CsrPlugin_enterHalt) begin
      CsrPlugin_dcsr_stepLogic_stateNext = CsrPlugin_dcsr_stepLogic_IDLE;
    end
    if(CsrPlugin_dcsr_stepLogic_wantStart) begin
      CsrPlugin_dcsr_stepLogic_stateNext = CsrPlugin_dcsr_stepLogic_IDLE;
    end
    if(CsrPlugin_dcsr_stepLogic_wantKill) begin
      CsrPlugin_dcsr_stepLogic_stateNext = CsrPlugin_dcsr_stepLogic_BOOT;
    end
  end

  assign when_CsrPlugin_l812 = (CsrPlugin_dcsr_step && debugBus_resume_rsp_valid);
  assign when_CsrPlugin_l830 = ((! CsrPlugin_doHalt) && CsrPlugin_timeout_state);
  assign CsrPlugin_dcsr_stepLogic_onExit_BOOT = ((CsrPlugin_dcsr_stepLogic_stateNext != CsrPlugin_dcsr_stepLogic_BOOT) && (CsrPlugin_dcsr_stepLogic_stateReg == CsrPlugin_dcsr_stepLogic_BOOT));
  assign CsrPlugin_dcsr_stepLogic_onExit_IDLE = ((CsrPlugin_dcsr_stepLogic_stateNext != CsrPlugin_dcsr_stepLogic_IDLE) && (CsrPlugin_dcsr_stepLogic_stateReg == CsrPlugin_dcsr_stepLogic_IDLE));
  assign CsrPlugin_dcsr_stepLogic_onExit_SINGLE = ((CsrPlugin_dcsr_stepLogic_stateNext != CsrPlugin_dcsr_stepLogic_SINGLE) && (CsrPlugin_dcsr_stepLogic_stateReg == CsrPlugin_dcsr_stepLogic_SINGLE));
  assign CsrPlugin_dcsr_stepLogic_onExit_WAIT_1 = ((CsrPlugin_dcsr_stepLogic_stateNext != CsrPlugin_dcsr_stepLogic_WAIT_1) && (CsrPlugin_dcsr_stepLogic_stateReg == CsrPlugin_dcsr_stepLogic_WAIT_1));
  assign CsrPlugin_dcsr_stepLogic_onEntry_BOOT = ((CsrPlugin_dcsr_stepLogic_stateNext == CsrPlugin_dcsr_stepLogic_BOOT) && (CsrPlugin_dcsr_stepLogic_stateReg != CsrPlugin_dcsr_stepLogic_BOOT));
  assign CsrPlugin_dcsr_stepLogic_onEntry_IDLE = ((CsrPlugin_dcsr_stepLogic_stateNext == CsrPlugin_dcsr_stepLogic_IDLE) && (CsrPlugin_dcsr_stepLogic_stateReg != CsrPlugin_dcsr_stepLogic_IDLE));
  assign CsrPlugin_dcsr_stepLogic_onEntry_SINGLE = ((CsrPlugin_dcsr_stepLogic_stateNext == CsrPlugin_dcsr_stepLogic_SINGLE) && (CsrPlugin_dcsr_stepLogic_stateReg != CsrPlugin_dcsr_stepLogic_SINGLE));
  assign CsrPlugin_dcsr_stepLogic_onEntry_WAIT_1 = ((CsrPlugin_dcsr_stepLogic_stateNext == CsrPlugin_dcsr_stepLogic_WAIT_1) && (CsrPlugin_dcsr_stepLogic_stateReg != CsrPlugin_dcsr_stepLogic_WAIT_1));
  assign when_CsrPlugin_l862 = ((debugMode || CsrPlugin_dcsr_step) || debugBus_haltReq);
  assign CsrPlugin_trigger_tselect_outOfRange = 1'b0;
  always @(*) begin
    CsrPlugin_trigger_decodeBreak_enabled = 1'b0;
    if(CsrPlugin_trigger_slots_0_tdata2_execute_hit) begin
      CsrPlugin_trigger_decodeBreak_enabled = 1'b1;
    end
    if(CsrPlugin_trigger_slots_1_tdata2_execute_hit) begin
      CsrPlugin_trigger_decodeBreak_enabled = 1'b1;
    end
    if(when_CsrPlugin_l958) begin
      CsrPlugin_trigger_decodeBreak_enabled = 1'b0;
    end
  end

  always @(*) begin
    CsrPlugin_trigger_decodeBreak_timeout_stateRise = 1'b0;
    if(CsrPlugin_trigger_decodeBreak_timeout_counter_willOverflow) begin
      CsrPlugin_trigger_decodeBreak_timeout_stateRise = (! CsrPlugin_trigger_decodeBreak_timeout_state);
    end
    if(when_Utils_l694) begin
      CsrPlugin_trigger_decodeBreak_timeout_stateRise = 1'b0;
    end
  end

  always @(*) begin
    CsrPlugin_trigger_decodeBreak_timeout_counter_willClear = 1'b0;
    if(when_Utils_l694) begin
      CsrPlugin_trigger_decodeBreak_timeout_counter_willClear = 1'b1;
    end
  end

  assign CsrPlugin_trigger_decodeBreak_timeout_counter_willOverflowIfInc = (CsrPlugin_trigger_decodeBreak_timeout_counter_value == 2'b10);
  assign CsrPlugin_trigger_decodeBreak_timeout_counter_willOverflow = (CsrPlugin_trigger_decodeBreak_timeout_counter_willOverflowIfInc && CsrPlugin_trigger_decodeBreak_timeout_counter_willIncrement);
  always @(*) begin
    if(CsrPlugin_trigger_decodeBreak_timeout_counter_willOverflow) begin
      CsrPlugin_trigger_decodeBreak_timeout_counter_valueNext = 2'b00;
    end else begin
      CsrPlugin_trigger_decodeBreak_timeout_counter_valueNext = (CsrPlugin_trigger_decodeBreak_timeout_counter_value + _zz_CsrPlugin_trigger_decodeBreak_timeout_counter_valueNext);
    end
    if(CsrPlugin_trigger_decodeBreak_timeout_counter_willClear) begin
      CsrPlugin_trigger_decodeBreak_timeout_counter_valueNext = 2'b00;
    end
  end

  assign CsrPlugin_trigger_decodeBreak_timeout_counter_willIncrement = 1'b1;
  assign when_Utils_l694 = ((! CsrPlugin_trigger_decodeBreak_enabled) || (|{writeBack_arbitration_isValid,{memory_arbitration_isValid,execute_arbitration_isValid}}));
  assign CsrPlugin_trigger_slots_0_selected = (CsrPlugin_trigger_tselect_index == 1'b0);
  always @(*) begin
    CsrPlugin_trigger_slots_0_tdata1_read = 32'h0;
    if(CsrPlugin_trigger_slots_0_selected) begin
      CsrPlugin_trigger_slots_0_tdata1_read[2 : 2] = CsrPlugin_trigger_slots_0_tdata1_execute;
      CsrPlugin_trigger_slots_0_tdata1_read[3 : 3] = CsrPlugin_trigger_slots_0_tdata1_u;
      CsrPlugin_trigger_slots_0_tdata1_read[4 : 4] = CsrPlugin_trigger_slots_0_tdata1_s;
      CsrPlugin_trigger_slots_0_tdata1_read[6 : 6] = CsrPlugin_trigger_slots_0_tdata1_m;
      CsrPlugin_trigger_slots_0_tdata1_read[27 : 27] = CsrPlugin_trigger_slots_0_tdata1_dmode;
      CsrPlugin_trigger_slots_0_tdata1_read[15 : 12] = CsrPlugin_trigger_slots_0_tdata1_action;
    end
    if(CsrPlugin_trigger_slots_0_selected) begin
      CsrPlugin_trigger_slots_0_tdata1_read[31 : 28] = CsrPlugin_trigger_slots_0_tdata1_tpe;
    end
    if(CsrPlugin_trigger_slots_0_selected) begin
      CsrPlugin_trigger_slots_0_tdata1_read[25 : 20] = 6'h1f;
    end
  end

  assign CsrPlugin_trigger_slots_0_tdata1_tpe = 4'b0010;
  always @(*) begin
    case(CsrPlugin_privilege)
      2'b00 : begin
        _zz_CsrPlugin_trigger_slots_0_tdata1_privilegeHit = CsrPlugin_trigger_slots_0_tdata1_u;
      end
      2'b01 : begin
        _zz_CsrPlugin_trigger_slots_0_tdata1_privilegeHit = CsrPlugin_trigger_slots_0_tdata1_s;
      end
      2'b11 : begin
        _zz_CsrPlugin_trigger_slots_0_tdata1_privilegeHit = CsrPlugin_trigger_slots_0_tdata1_m;
      end
      default : begin
        _zz_CsrPlugin_trigger_slots_0_tdata1_privilegeHit = 1'b0;
      end
    endcase
  end

  assign CsrPlugin_trigger_slots_0_tdata1_privilegeHit = ((! debugMode) && _zz_CsrPlugin_trigger_slots_0_tdata1_privilegeHit);
  assign CsrPlugin_trigger_slots_0_tdata2_execute_enabled = ((((! debugMode) && (CsrPlugin_trigger_slots_0_tdata1_action == 4'b0001)) && CsrPlugin_trigger_slots_0_tdata1_execute) && CsrPlugin_trigger_slots_0_tdata1_privilegeHit);
  assign CsrPlugin_trigger_slots_0_tdata2_execute_hit = (CsrPlugin_trigger_slots_0_tdata2_execute_enabled && (CsrPlugin_trigger_slots_0_tdata2_value == decode_PC));
  assign CsrPlugin_trigger_slots_1_selected = (CsrPlugin_trigger_tselect_index == 1'b1);
  always @(*) begin
    CsrPlugin_trigger_slots_1_tdata1_read = 32'h0;
    if(CsrPlugin_trigger_slots_1_selected) begin
      CsrPlugin_trigger_slots_1_tdata1_read[2 : 2] = CsrPlugin_trigger_slots_1_tdata1_execute;
      CsrPlugin_trigger_slots_1_tdata1_read[3 : 3] = CsrPlugin_trigger_slots_1_tdata1_u;
      CsrPlugin_trigger_slots_1_tdata1_read[4 : 4] = CsrPlugin_trigger_slots_1_tdata1_s;
      CsrPlugin_trigger_slots_1_tdata1_read[6 : 6] = CsrPlugin_trigger_slots_1_tdata1_m;
      CsrPlugin_trigger_slots_1_tdata1_read[27 : 27] = CsrPlugin_trigger_slots_1_tdata1_dmode;
      CsrPlugin_trigger_slots_1_tdata1_read[15 : 12] = CsrPlugin_trigger_slots_1_tdata1_action;
    end
    if(CsrPlugin_trigger_slots_1_selected) begin
      CsrPlugin_trigger_slots_1_tdata1_read[31 : 28] = CsrPlugin_trigger_slots_1_tdata1_tpe;
    end
    if(CsrPlugin_trigger_slots_1_selected) begin
      CsrPlugin_trigger_slots_1_tdata1_read[25 : 20] = 6'h1f;
    end
  end

  assign CsrPlugin_trigger_slots_1_tdata1_tpe = 4'b0010;
  always @(*) begin
    case(CsrPlugin_privilege)
      2'b00 : begin
        _zz_CsrPlugin_trigger_slots_1_tdata1_privilegeHit = CsrPlugin_trigger_slots_1_tdata1_u;
      end
      2'b01 : begin
        _zz_CsrPlugin_trigger_slots_1_tdata1_privilegeHit = CsrPlugin_trigger_slots_1_tdata1_s;
      end
      2'b11 : begin
        _zz_CsrPlugin_trigger_slots_1_tdata1_privilegeHit = CsrPlugin_trigger_slots_1_tdata1_m;
      end
      default : begin
        _zz_CsrPlugin_trigger_slots_1_tdata1_privilegeHit = 1'b0;
      end
    endcase
  end

  assign CsrPlugin_trigger_slots_1_tdata1_privilegeHit = ((! debugMode) && _zz_CsrPlugin_trigger_slots_1_tdata1_privilegeHit);
  assign CsrPlugin_trigger_slots_1_tdata2_execute_enabled = ((((! debugMode) && (CsrPlugin_trigger_slots_1_tdata1_action == 4'b0001)) && CsrPlugin_trigger_slots_1_tdata1_execute) && CsrPlugin_trigger_slots_1_tdata1_privilegeHit);
  assign CsrPlugin_trigger_slots_1_tdata2_execute_hit = (CsrPlugin_trigger_slots_1_tdata2_execute_enabled && (CsrPlugin_trigger_slots_1_tdata2_value == decode_PC));
  assign when_CsrPlugin_l958 = (! decode_arbitration_isValid);
  assign CsrPlugin_misa_base = 2'b01;
  assign CsrPlugin_misa_extensions = 26'h0000042;
  assign _zz_when_CsrPlugin_l1302 = (CsrPlugin_mip_MTIP && CsrPlugin_mie_MTIE);
  assign _zz_when_CsrPlugin_l1302_1 = (CsrPlugin_mip_MSIP && CsrPlugin_mie_MSIE);
  assign _zz_when_CsrPlugin_l1302_2 = (CsrPlugin_mip_MEIP && CsrPlugin_mie_MEIE);
  assign CsrPlugin_exceptionPortCtrl_exceptionTargetPrivilegeUncapped = 2'b11;
  assign CsrPlugin_exceptionPortCtrl_exceptionTargetPrivilege = ((CsrPlugin_privilege < CsrPlugin_exceptionPortCtrl_exceptionTargetPrivilegeUncapped) ? CsrPlugin_exceptionPortCtrl_exceptionTargetPrivilegeUncapped : CsrPlugin_privilege);
  assign _zz_CsrPlugin_exceptionPortCtrl_exceptionContext_code = {decodeExceptionPort_valid,IBusCachedPlugin_decodeExceptionPort_valid};
  assign _zz_CsrPlugin_exceptionPortCtrl_exceptionContext_code_1 = _zz__zz_CsrPlugin_exceptionPortCtrl_exceptionContext_code_1[0];
  assign _zz_CsrPlugin_exceptionPortCtrl_exceptionContext_code_2 = {BranchPlugin_branchExceptionPort_valid,DBusSimplePlugin_memoryExceptionPort_valid};
  assign _zz_CsrPlugin_exceptionPortCtrl_exceptionContext_code_3 = _zz__zz_CsrPlugin_exceptionPortCtrl_exceptionContext_code_3[0];
  always @(*) begin
    CsrPlugin_exceptionPortCtrl_exceptionValids_decode = CsrPlugin_exceptionPortCtrl_exceptionValidsRegs_decode;
    if(_zz_when_1) begin
      CsrPlugin_exceptionPortCtrl_exceptionValids_decode = 1'b1;
    end
    if(decode_arbitration_isFlushed) begin
      CsrPlugin_exceptionPortCtrl_exceptionValids_decode = 1'b0;
    end
  end

  always @(*) begin
    CsrPlugin_exceptionPortCtrl_exceptionValids_execute = CsrPlugin_exceptionPortCtrl_exceptionValidsRegs_execute;
    if(CsrPlugin_selfException_valid) begin
      CsrPlugin_exceptionPortCtrl_exceptionValids_execute = 1'b1;
    end
    if(execute_arbitration_isFlushed) begin
      CsrPlugin_exceptionPortCtrl_exceptionValids_execute = 1'b0;
    end
  end

  always @(*) begin
    CsrPlugin_exceptionPortCtrl_exceptionValids_memory = CsrPlugin_exceptionPortCtrl_exceptionValidsRegs_memory;
    if(_zz_when_2) begin
      CsrPlugin_exceptionPortCtrl_exceptionValids_memory = 1'b1;
    end
    if(memory_arbitration_isFlushed) begin
      CsrPlugin_exceptionPortCtrl_exceptionValids_memory = 1'b0;
    end
  end

  always @(*) begin
    CsrPlugin_exceptionPortCtrl_exceptionValids_writeBack = CsrPlugin_exceptionPortCtrl_exceptionValidsRegs_writeBack;
    if(writeBack_arbitration_isFlushed) begin
      CsrPlugin_exceptionPortCtrl_exceptionValids_writeBack = 1'b0;
    end
  end

  assign when_CsrPlugin_l1259 = (! decode_arbitration_isStuck);
  assign when_CsrPlugin_l1259_1 = (! execute_arbitration_isStuck);
  assign when_CsrPlugin_l1259_2 = (! memory_arbitration_isStuck);
  assign when_CsrPlugin_l1259_3 = (! writeBack_arbitration_isStuck);
  assign when_CsrPlugin_l1272 = (|{CsrPlugin_exceptionPortCtrl_exceptionValids_writeBack,{CsrPlugin_exceptionPortCtrl_exceptionValids_memory,{CsrPlugin_exceptionPortCtrl_exceptionValids_execute,CsrPlugin_exceptionPortCtrl_exceptionValids_decode}}});
  assign CsrPlugin_exceptionPendings_0 = CsrPlugin_exceptionPortCtrl_exceptionValidsRegs_decode;
  assign CsrPlugin_exceptionPendings_1 = CsrPlugin_exceptionPortCtrl_exceptionValidsRegs_execute;
  assign CsrPlugin_exceptionPendings_2 = CsrPlugin_exceptionPortCtrl_exceptionValidsRegs_memory;
  assign CsrPlugin_exceptionPendings_3 = CsrPlugin_exceptionPortCtrl_exceptionValidsRegs_writeBack;
  assign when_CsrPlugin_l1296 = (CsrPlugin_mstatus_MIE || (CsrPlugin_privilege < 2'b11));
  assign when_CsrPlugin_l1302 = ((_zz_when_CsrPlugin_l1302 && 1'b1) && (! 1'b0));
  assign when_CsrPlugin_l1302_1 = ((_zz_when_CsrPlugin_l1302_1 && 1'b1) && (! 1'b0));
  assign when_CsrPlugin_l1302_2 = ((_zz_when_CsrPlugin_l1302_2 && 1'b1) && (! 1'b0));
  assign when_CsrPlugin_l1315 = (CsrPlugin_dcsr_step && (! CsrPlugin_dcsr_stepie));
  assign CsrPlugin_exception = (CsrPlugin_exceptionPortCtrl_exceptionValids_writeBack && CsrPlugin_allowException);
  assign CsrPlugin_lastStageWasWfi = 1'b0;
  assign CsrPlugin_pipelineLiberator_active = ((CsrPlugin_interrupt_valid && CsrPlugin_allowInterrupts) && decode_arbitration_isValid);
  assign when_CsrPlugin_l1335 = (! execute_arbitration_isStuck);
  assign when_CsrPlugin_l1335_1 = (! memory_arbitration_isStuck);
  assign when_CsrPlugin_l1335_2 = (! writeBack_arbitration_isStuck);
  assign when_CsrPlugin_l1340 = ((! CsrPlugin_pipelineLiberator_active) || decode_arbitration_removeIt);
  always @(*) begin
    CsrPlugin_pipelineLiberator_done = CsrPlugin_pipelineLiberator_pcValids_2;
    if(when_CsrPlugin_l1346) begin
      CsrPlugin_pipelineLiberator_done = 1'b0;
    end
    if(CsrPlugin_hadException) begin
      CsrPlugin_pipelineLiberator_done = 1'b0;
    end
  end

  assign when_CsrPlugin_l1346 = (|{CsrPlugin_exceptionPortCtrl_exceptionValidsRegs_writeBack,{CsrPlugin_exceptionPortCtrl_exceptionValidsRegs_memory,CsrPlugin_exceptionPortCtrl_exceptionValidsRegs_execute}});
  assign CsrPlugin_interruptJump = ((CsrPlugin_interrupt_valid && CsrPlugin_pipelineLiberator_done) && CsrPlugin_allowInterrupts);
  assign debugBus_commit = (debugMode && writeBack_arbitration_isFiring);
  always @(*) begin
    debugBus_exception = (debugMode && CsrPlugin_hadException);
    if(when_CsrPlugin_l1390) begin
      if(!when_CsrPlugin_l1398) begin
        if(!when_CsrPlugin_l1428) begin
          debugBus_exception = (! CsrPlugin_trapCauseEbreakDebug);
        end
      end
    end
  end

  always @(*) begin
    debugBus_ebreak = 1'b0;
    if(when_CsrPlugin_l1390) begin
      if(!when_CsrPlugin_l1398) begin
        if(!when_CsrPlugin_l1428) begin
          debugBus_ebreak = CsrPlugin_trapCauseEbreakDebug;
        end
      end
    end
  end

  always @(*) begin
    CsrPlugin_targetPrivilege = CsrPlugin_interrupt_targetPrivilege;
    if(CsrPlugin_hadException) begin
      CsrPlugin_targetPrivilege = CsrPlugin_exceptionPortCtrl_exceptionTargetPrivilege;
    end
  end

  always @(*) begin
    CsrPlugin_trapCause = CsrPlugin_interrupt_code;
    if(CsrPlugin_hadException) begin
      CsrPlugin_trapCause = CsrPlugin_exceptionPortCtrl_exceptionContext_code;
    end
  end

  always @(*) begin
    CsrPlugin_trapCauseEbreakDebug = 1'b0;
    if(CsrPlugin_hadException) begin
      if(when_CsrPlugin_l1373) begin
        if(debugMode) begin
          CsrPlugin_trapCauseEbreakDebug = 1'b1;
        end
        if(when_CsrPlugin_l1375) begin
          CsrPlugin_trapCauseEbreakDebug = 1'b1;
        end
      end
    end
  end

  assign when_CsrPlugin_l1373 = (CsrPlugin_exceptionPortCtrl_exceptionContext_code == 4'b0011);
  assign when_CsrPlugin_l1375 = ((CsrPlugin_privilege == 2'b11) && CsrPlugin_dcsr_ebreakm);
  always @(*) begin
    CsrPlugin_xtvec_mode = 2'bxx;
    case(CsrPlugin_targetPrivilege)
      2'b11 : begin
        CsrPlugin_xtvec_mode = CsrPlugin_mtvec_mode;
      end
      default : begin
      end
    endcase
  end

  always @(*) begin
    CsrPlugin_xtvec_base = 30'bxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx;
    case(CsrPlugin_targetPrivilege)
      2'b11 : begin
        CsrPlugin_xtvec_base = CsrPlugin_mtvec_base;
      end
      default : begin
      end
    endcase
  end

  always @(*) begin
    CsrPlugin_trapEnterDebug = 1'b0;
    if(when_CsrPlugin_l1389) begin
      CsrPlugin_trapEnterDebug = 1'b1;
    end
  end

  assign when_CsrPlugin_l1389 = (((CsrPlugin_doHalt || CsrPlugin_trapCauseEbreakDebug) || ((! CsrPlugin_hadException) && CsrPlugin_doHalt)) || (! CsrPlugin_running));
  assign when_CsrPlugin_l1390 = (CsrPlugin_hadException || CsrPlugin_interruptJump);
  assign when_CsrPlugin_l1398 = (! CsrPlugin_trapEnterDebug);
  assign when_CsrPlugin_l1428 = (! debugMode);
  assign when_CsrPlugin_l1456 = (writeBack_arbitration_isValid && (writeBack_ENV_CTRL == EnvCtrlEnum_XRET));
  assign switch_CsrPlugin_l1460 = writeBack_INSTRUCTION[29 : 28];
  assign when_CsrPlugin_l1468 = (CsrPlugin_mstatus_MPP < 2'b11);
  assign contextSwitching = CsrPlugin_jumpInterface_valid;
  assign when_CsrPlugin_l1527 = (|{(writeBack_arbitration_isValid && (writeBack_ENV_CTRL == EnvCtrlEnum_XRET)),{(memory_arbitration_isValid && (memory_ENV_CTRL == EnvCtrlEnum_XRET)),(execute_arbitration_isValid && (execute_ENV_CTRL == EnvCtrlEnum_XRET))}});
  assign execute_CsrPlugin_blockedBySideEffects = ((|{writeBack_arbitration_isValid,memory_arbitration_isValid}) || 1'b0);
  always @(*) begin
    execute_CsrPlugin_illegalAccess = 1'b1;
    if(execute_CsrPlugin_csr_1972) begin
      execute_CsrPlugin_illegalAccess = 1'b0;
    end
    if(execute_CsrPlugin_csr_1969) begin
      execute_CsrPlugin_illegalAccess = 1'b0;
    end
    if(execute_CsrPlugin_csr_1968) begin
      execute_CsrPlugin_illegalAccess = 1'b0;
    end
    if(execute_CsrPlugin_csr_1952) begin
      execute_CsrPlugin_illegalAccess = 1'b0;
    end
    if(execute_CsrPlugin_csr_1956) begin
      if(execute_CSR_READ_OPCODE) begin
        execute_CsrPlugin_illegalAccess = 1'b0;
      end
    end
    if(execute_CsrPlugin_csr_1953) begin
      execute_CsrPlugin_illegalAccess = 1'b0;
    end
    if(execute_CsrPlugin_csr_1954) begin
      if(execute_CSR_WRITE_OPCODE) begin
        execute_CsrPlugin_illegalAccess = 1'b0;
      end
    end
    if(execute_CsrPlugin_csr_768) begin
      execute_CsrPlugin_illegalAccess = 1'b0;
    end
    if(execute_CsrPlugin_csr_836) begin
      execute_CsrPlugin_illegalAccess = 1'b0;
    end
    if(execute_CsrPlugin_csr_772) begin
      execute_CsrPlugin_illegalAccess = 1'b0;
    end
    if(execute_CsrPlugin_csr_773) begin
      if(execute_CSR_WRITE_OPCODE) begin
        execute_CsrPlugin_illegalAccess = 1'b0;
      end
    end
    if(execute_CsrPlugin_csr_833) begin
      execute_CsrPlugin_illegalAccess = 1'b0;
    end
    if(execute_CsrPlugin_csr_834) begin
      if(execute_CSR_READ_OPCODE) begin
        execute_CsrPlugin_illegalAccess = 1'b0;
      end
    end
    if(execute_CsrPlugin_csr_835) begin
      if(execute_CSR_READ_OPCODE) begin
        execute_CsrPlugin_illegalAccess = 1'b0;
      end
    end
    if(execute_CsrPlugin_csr_3008) begin
      execute_CsrPlugin_illegalAccess = 1'b0;
    end
    if(execute_CsrPlugin_csr_4032) begin
      if(execute_CSR_READ_OPCODE) begin
        execute_CsrPlugin_illegalAccess = 1'b0;
      end
    end
    if(CsrPlugin_csrMapping_allowCsrSignal) begin
      execute_CsrPlugin_illegalAccess = 1'b0;
    end
    if(when_CsrPlugin_l1719) begin
      execute_CsrPlugin_illegalAccess = 1'b1;
    end
    if(when_CsrPlugin_l1725) begin
      execute_CsrPlugin_illegalAccess = 1'b0;
    end
  end

  always @(*) begin
    execute_CsrPlugin_illegalInstruction = 1'b0;
    if(when_CsrPlugin_l1547) begin
      if(when_CsrPlugin_l1548) begin
        execute_CsrPlugin_illegalInstruction = 1'b1;
      end
    end
  end

  always @(*) begin
    CsrPlugin_selfException_valid = 1'b0;
    if(when_CsrPlugin_l1555) begin
      CsrPlugin_selfException_valid = 1'b1;
    end
    if(when_CsrPlugin_l1565) begin
      CsrPlugin_selfException_valid = 1'b1;
    end
  end

  always @(*) begin
    CsrPlugin_selfException_payload_code = 4'bxxxx;
    if(when_CsrPlugin_l1555) begin
      case(CsrPlugin_privilege)
        2'b00 : begin
          CsrPlugin_selfException_payload_code = 4'b1000;
        end
        default : begin
          CsrPlugin_selfException_payload_code = 4'b1011;
        end
      endcase
    end
    if(when_CsrPlugin_l1565) begin
      CsrPlugin_selfException_payload_code = 4'b0011;
    end
  end

  assign CsrPlugin_selfException_payload_badAddr = execute_INSTRUCTION;
  assign when_CsrPlugin_l1547 = (execute_arbitration_isValid && (execute_ENV_CTRL == EnvCtrlEnum_XRET));
  assign when_CsrPlugin_l1548 = (CsrPlugin_privilege < execute_INSTRUCTION[29 : 28]);
  assign when_CsrPlugin_l1555 = (execute_arbitration_isValid && (execute_ENV_CTRL == EnvCtrlEnum_ECALL));
  assign when_CsrPlugin_l1565 = ((execute_arbitration_isValid && (execute_ENV_CTRL == EnvCtrlEnum_EBREAK)) && CsrPlugin_allowEbreakException);
  always @(*) begin
    execute_CsrPlugin_writeInstruction = ((execute_arbitration_isValid && execute_IS_CSR) && execute_CSR_WRITE_OPCODE);
    if(when_CsrPlugin_l1719) begin
      execute_CsrPlugin_writeInstruction = 1'b0;
    end
  end

  always @(*) begin
    execute_CsrPlugin_readInstruction = ((execute_arbitration_isValid && execute_IS_CSR) && execute_CSR_READ_OPCODE);
    if(when_CsrPlugin_l1719) begin
      execute_CsrPlugin_readInstruction = 1'b0;
    end
  end

  assign execute_CsrPlugin_writeEnable = (execute_CsrPlugin_writeInstruction && (! execute_arbitration_isStuck));
  assign execute_CsrPlugin_readEnable = (execute_CsrPlugin_readInstruction && (! execute_arbitration_isStuck));
  assign CsrPlugin_csrMapping_hazardFree = (! execute_CsrPlugin_blockedBySideEffects);
  assign execute_CsrPlugin_readToWriteData = CsrPlugin_csrMapping_readDataSignal;
  assign switch_Misc_l245_2 = execute_INSTRUCTION[13];
  always @(*) begin
    case(switch_Misc_l245_2)
      1'b0 : begin
        _zz_CsrPlugin_csrMapping_writeDataSignal = execute_SRC1;
      end
      default : begin
        _zz_CsrPlugin_csrMapping_writeDataSignal = (execute_INSTRUCTION[12] ? (execute_CsrPlugin_readToWriteData & (~ execute_SRC1)) : (execute_CsrPlugin_readToWriteData | execute_SRC1));
      end
    endcase
  end

  assign CsrPlugin_csrMapping_writeDataSignal = _zz_CsrPlugin_csrMapping_writeDataSignal;
  assign when_CsrPlugin_l1587 = (execute_arbitration_isValid && execute_IS_CSR);
  assign when_CsrPlugin_l1591 = (execute_arbitration_isValid && (execute_IS_CSR || 1'b0));
  assign execute_CsrPlugin_csrAddress = execute_INSTRUCTION[31 : 20];
  assign memory_MulDivIterativePlugin_frontendOk = 1'b1;
  always @(*) begin
    memory_MulDivIterativePlugin_mul_counter_willIncrement = 1'b0;
    if(when_MulDivIterativePlugin_l96) begin
      if(when_MulDivIterativePlugin_l100) begin
        memory_MulDivIterativePlugin_mul_counter_willIncrement = 1'b1;
      end
    end
  end

  always @(*) begin
    memory_MulDivIterativePlugin_mul_counter_willClear = 1'b0;
    if(when_MulDivIterativePlugin_l110) begin
      memory_MulDivIterativePlugin_mul_counter_willClear = 1'b1;
    end
  end

  assign memory_MulDivIterativePlugin_mul_counter_willOverflowIfInc = (memory_MulDivIterativePlugin_mul_counter_value == 6'h20);
  assign memory_MulDivIterativePlugin_mul_counter_willOverflow = (memory_MulDivIterativePlugin_mul_counter_willOverflowIfInc && memory_MulDivIterativePlugin_mul_counter_willIncrement);
  always @(*) begin
    if(memory_MulDivIterativePlugin_mul_counter_willOverflow) begin
      memory_MulDivIterativePlugin_mul_counter_valueNext = 6'h0;
    end else begin
      memory_MulDivIterativePlugin_mul_counter_valueNext = (memory_MulDivIterativePlugin_mul_counter_value + _zz_memory_MulDivIterativePlugin_mul_counter_valueNext);
    end
    if(memory_MulDivIterativePlugin_mul_counter_willClear) begin
      memory_MulDivIterativePlugin_mul_counter_valueNext = 6'h0;
    end
  end

  assign when_MulDivIterativePlugin_l96 = (memory_arbitration_isValid && memory_IS_MUL);
  assign when_MulDivIterativePlugin_l97 = ((! memory_MulDivIterativePlugin_frontendOk) || (! memory_MulDivIterativePlugin_mul_counter_willOverflowIfInc));
  assign when_MulDivIterativePlugin_l100 = (memory_MulDivIterativePlugin_frontendOk && (! memory_MulDivIterativePlugin_mul_counter_willOverflowIfInc));
  assign when_MulDivIterativePlugin_l110 = (! memory_arbitration_isStuck);
  always @(*) begin
    memory_MulDivIterativePlugin_div_counter_willIncrement = 1'b0;
    if(when_MulDivIterativePlugin_l128) begin
      if(when_MulDivIterativePlugin_l132) begin
        memory_MulDivIterativePlugin_div_counter_willIncrement = 1'b1;
      end
    end
  end

  always @(*) begin
    memory_MulDivIterativePlugin_div_counter_willClear = 1'b0;
    if(when_MulDivIterativePlugin_l162) begin
      memory_MulDivIterativePlugin_div_counter_willClear = 1'b1;
    end
  end

  assign memory_MulDivIterativePlugin_div_counter_willOverflowIfInc = (memory_MulDivIterativePlugin_div_counter_value == 6'h21);
  assign memory_MulDivIterativePlugin_div_counter_willOverflow = (memory_MulDivIterativePlugin_div_counter_willOverflowIfInc && memory_MulDivIterativePlugin_div_counter_willIncrement);
  always @(*) begin
    if(memory_MulDivIterativePlugin_div_counter_willOverflow) begin
      memory_MulDivIterativePlugin_div_counter_valueNext = 6'h0;
    end else begin
      memory_MulDivIterativePlugin_div_counter_valueNext = (memory_MulDivIterativePlugin_div_counter_value + _zz_memory_MulDivIterativePlugin_div_counter_valueNext);
    end
    if(memory_MulDivIterativePlugin_div_counter_willClear) begin
      memory_MulDivIterativePlugin_div_counter_valueNext = 6'h0;
    end
  end

  assign when_MulDivIterativePlugin_l126 = (memory_MulDivIterativePlugin_div_counter_value == 6'h20);
  assign when_MulDivIterativePlugin_l126_1 = (! memory_arbitration_isStuck);
  assign when_MulDivIterativePlugin_l128 = (memory_arbitration_isValid && memory_IS_DIV);
  assign when_MulDivIterativePlugin_l129 = ((! memory_MulDivIterativePlugin_frontendOk) || (! memory_MulDivIterativePlugin_div_done));
  assign when_MulDivIterativePlugin_l132 = (memory_MulDivIterativePlugin_frontendOk && (! memory_MulDivIterativePlugin_div_done));
  assign _zz_memory_MulDivIterativePlugin_div_stage_0_remainderShifted = memory_MulDivIterativePlugin_rs1[31 : 0];
  assign memory_MulDivIterativePlugin_div_stage_0_remainderShifted = {memory_MulDivIterativePlugin_accumulator[31 : 0],_zz_memory_MulDivIterativePlugin_div_stage_0_remainderShifted[31]};
  assign memory_MulDivIterativePlugin_div_stage_0_remainderMinusDenominator = (memory_MulDivIterativePlugin_div_stage_0_remainderShifted - _zz_memory_MulDivIterativePlugin_div_stage_0_remainderMinusDenominator);
  assign memory_MulDivIterativePlugin_div_stage_0_outRemainder = ((! memory_MulDivIterativePlugin_div_stage_0_remainderMinusDenominator[32]) ? _zz_memory_MulDivIterativePlugin_div_stage_0_outRemainder : _zz_memory_MulDivIterativePlugin_div_stage_0_outRemainder_1);
  assign memory_MulDivIterativePlugin_div_stage_0_outNumerator = _zz_memory_MulDivIterativePlugin_div_stage_0_outNumerator[31:0];
  assign when_MulDivIterativePlugin_l151 = (memory_MulDivIterativePlugin_div_counter_value == 6'h20);
  assign _zz_memory_MulDivIterativePlugin_div_result = (memory_INSTRUCTION[13] ? memory_MulDivIterativePlugin_accumulator[31 : 0] : memory_MulDivIterativePlugin_rs1[31 : 0]);
  assign when_MulDivIterativePlugin_l162 = (! memory_arbitration_isStuck);
  assign _zz_memory_MulDivIterativePlugin_rs2 = (execute_RS2[31] && execute_IS_RS2_SIGNED);
  assign _zz_memory_MulDivIterativePlugin_rs1 = ((execute_IS_MUL && _zz_memory_MulDivIterativePlugin_rs2) || ((execute_IS_DIV && execute_RS1[31]) && execute_IS_RS1_SIGNED));
  always @(*) begin
    _zz_memory_MulDivIterativePlugin_rs1_1[32] = (execute_IS_RS1_SIGNED && execute_RS1[31]);
    _zz_memory_MulDivIterativePlugin_rs1_1[31 : 0] = execute_RS1;
  end

  assign _zz_externalInterrupt = (_zz_CsrPlugin_csrMapping_readDataInit & externalInterruptArray_regNext);
  assign externalInterrupt = (|_zz_externalInterrupt);
  assign ndmreset = debugModule_1_io_ndmreset;
  assign jtagInstruction_tdo = debugTransportModuleTunneled_1_io_instruction_tdo;
  assign debugBus_ackReset = debugModule_1_io_harts_0_ackReset;
  assign debugBus_resume_cmd_valid = debugModule_1_io_harts_0_resume_cmd_valid;
  assign debugBus_haltReq = debugModule_1_io_harts_0_haltReq;
  assign debugBus_dmToHart_valid = io_harts_0_dmToHart_regNext_valid;
  assign debugBus_dmToHart_payload_op = io_harts_0_dmToHart_regNext_payload_op;
  assign debugBus_dmToHart_payload_address = io_harts_0_dmToHart_regNext_payload_address;
  assign debugBus_dmToHart_payload_data = io_harts_0_dmToHart_regNext_payload_data;
  assign debugBus_dmToHart_payload_size = io_harts_0_dmToHart_regNext_payload_size;
  assign when_Pipeline_l124 = (! execute_arbitration_isStuck);
  assign when_Pipeline_l124_1 = (! memory_arbitration_isStuck);
  assign when_Pipeline_l124_2 = ((! writeBack_arbitration_isStuck) && (! CsrPlugin_exceptionPortCtrl_exceptionValids_writeBack));
  assign when_Pipeline_l124_3 = (! execute_arbitration_isStuck);
  assign when_Pipeline_l124_4 = (! memory_arbitration_isStuck);
  assign when_Pipeline_l124_5 = (! writeBack_arbitration_isStuck);
  assign when_Pipeline_l124_6 = (! execute_arbitration_isStuck);
  assign when_Pipeline_l124_7 = (! memory_arbitration_isStuck);
  assign when_Pipeline_l124_8 = (! writeBack_arbitration_isStuck);
  assign _zz_decode_to_execute_SRC1_CTRL_1 = decode_SRC1_CTRL;
  assign _zz_decode_SRC1_CTRL = _zz_decode_SRC1_CTRL_1;
  assign when_Pipeline_l124_9 = (! execute_arbitration_isStuck);
  assign _zz_execute_SRC1_CTRL = decode_to_execute_SRC1_CTRL;
  assign when_Pipeline_l124_10 = (! execute_arbitration_isStuck);
  assign when_Pipeline_l124_11 = (! execute_arbitration_isStuck);
  assign when_Pipeline_l124_12 = (! memory_arbitration_isStuck);
  assign when_Pipeline_l124_13 = (! writeBack_arbitration_isStuck);
  assign _zz_decode_to_execute_ALU_CTRL_1 = decode_ALU_CTRL;
  assign _zz_decode_ALU_CTRL = _zz_decode_ALU_CTRL_1;
  assign when_Pipeline_l124_14 = (! execute_arbitration_isStuck);
  assign _zz_execute_ALU_CTRL = decode_to_execute_ALU_CTRL;
  assign _zz_decode_to_execute_SRC2_CTRL_1 = decode_SRC2_CTRL;
  assign _zz_decode_SRC2_CTRL = _zz_decode_SRC2_CTRL_1;
  assign when_Pipeline_l124_15 = (! execute_arbitration_isStuck);
  assign _zz_execute_SRC2_CTRL = decode_to_execute_SRC2_CTRL;
  assign when_Pipeline_l124_16 = (! execute_arbitration_isStuck);
  assign when_Pipeline_l124_17 = (! memory_arbitration_isStuck);
  assign when_Pipeline_l124_18 = (! writeBack_arbitration_isStuck);
  assign when_Pipeline_l124_19 = (! execute_arbitration_isStuck);
  assign when_Pipeline_l124_20 = (! execute_arbitration_isStuck);
  assign when_Pipeline_l124_21 = (! memory_arbitration_isStuck);
  assign when_Pipeline_l124_22 = (! execute_arbitration_isStuck);
  assign when_Pipeline_l124_23 = (! memory_arbitration_isStuck);
  assign when_Pipeline_l124_24 = (! execute_arbitration_isStuck);
  assign _zz_decode_to_execute_ALU_BITWISE_CTRL_1 = decode_ALU_BITWISE_CTRL;
  assign _zz_decode_ALU_BITWISE_CTRL = _zz_decode_ALU_BITWISE_CTRL_1;
  assign when_Pipeline_l124_25 = (! execute_arbitration_isStuck);
  assign _zz_execute_ALU_BITWISE_CTRL = decode_to_execute_ALU_BITWISE_CTRL;
  assign _zz_decode_to_execute_SHIFT_CTRL_1 = decode_SHIFT_CTRL;
  assign _zz_decode_SHIFT_CTRL = _zz_decode_SHIFT_CTRL_1;
  assign when_Pipeline_l124_26 = (! execute_arbitration_isStuck);
  assign _zz_execute_SHIFT_CTRL = decode_to_execute_SHIFT_CTRL;
  assign _zz_decode_to_execute_BRANCH_CTRL_1 = decode_BRANCH_CTRL;
  assign _zz_decode_BRANCH_CTRL_1 = _zz_decode_BRANCH_CTRL;
  assign when_Pipeline_l124_27 = (! execute_arbitration_isStuck);
  assign _zz_execute_BRANCH_CTRL = decode_to_execute_BRANCH_CTRL;
  assign when_Pipeline_l124_28 = (! execute_arbitration_isStuck);
  assign _zz_decode_to_execute_ENV_CTRL_1 = decode_ENV_CTRL;
  assign _zz_execute_to_memory_ENV_CTRL_1 = execute_ENV_CTRL;
  assign _zz_memory_to_writeBack_ENV_CTRL_1 = memory_ENV_CTRL;
  assign _zz_decode_ENV_CTRL = _zz_decode_ENV_CTRL_1;
  assign when_Pipeline_l124_29 = (! execute_arbitration_isStuck);
  assign _zz_execute_ENV_CTRL = decode_to_execute_ENV_CTRL;
  assign when_Pipeline_l124_30 = (! memory_arbitration_isStuck);
  assign _zz_memory_ENV_CTRL = execute_to_memory_ENV_CTRL;
  assign when_Pipeline_l124_31 = (! writeBack_arbitration_isStuck);
  assign _zz_writeBack_ENV_CTRL = memory_to_writeBack_ENV_CTRL;
  assign when_Pipeline_l124_32 = (! execute_arbitration_isStuck);
  assign when_Pipeline_l124_33 = (! memory_arbitration_isStuck);
  assign when_Pipeline_l124_34 = (! execute_arbitration_isStuck);
  assign when_Pipeline_l124_35 = (! execute_arbitration_isStuck);
  assign when_Pipeline_l124_36 = (! execute_arbitration_isStuck);
  assign when_Pipeline_l124_37 = (! memory_arbitration_isStuck);
  assign when_Pipeline_l124_38 = (! execute_arbitration_isStuck);
  assign when_Pipeline_l124_39 = (! execute_arbitration_isStuck);
  assign when_Pipeline_l124_40 = (! execute_arbitration_isStuck);
  assign when_Pipeline_l124_41 = (! execute_arbitration_isStuck);
  assign when_Pipeline_l124_42 = (! execute_arbitration_isStuck);
  assign when_Pipeline_l124_43 = (! execute_arbitration_isStuck);
  assign when_Pipeline_l124_44 = (! memory_arbitration_isStuck);
  assign when_Pipeline_l124_45 = (! memory_arbitration_isStuck);
  assign when_Pipeline_l124_46 = (! writeBack_arbitration_isStuck);
  assign when_Pipeline_l124_47 = ((! memory_arbitration_isStuck) && (! execute_arbitration_isStuckByOthers));
  assign when_Pipeline_l124_48 = (! writeBack_arbitration_isStuck);
  assign when_Pipeline_l124_49 = (! memory_arbitration_isStuck);
  assign when_Pipeline_l124_50 = (! memory_arbitration_isStuck);
  assign when_Pipeline_l124_51 = (! writeBack_arbitration_isStuck);
  assign decode_arbitration_isFlushed = ((|{writeBack_arbitration_flushNext,{memory_arbitration_flushNext,execute_arbitration_flushNext}}) || (|{writeBack_arbitration_flushIt,{memory_arbitration_flushIt,{execute_arbitration_flushIt,decode_arbitration_flushIt}}}));
  assign execute_arbitration_isFlushed = ((|{writeBack_arbitration_flushNext,memory_arbitration_flushNext}) || (|{writeBack_arbitration_flushIt,{memory_arbitration_flushIt,execute_arbitration_flushIt}}));
  assign memory_arbitration_isFlushed = ((|writeBack_arbitration_flushNext) || (|{writeBack_arbitration_flushIt,memory_arbitration_flushIt}));
  assign writeBack_arbitration_isFlushed = (1'b0 || (|writeBack_arbitration_flushIt));
  assign decode_arbitration_isStuckByOthers = (decode_arbitration_haltByOther || (((1'b0 || execute_arbitration_isStuck) || memory_arbitration_isStuck) || writeBack_arbitration_isStuck));
  assign decode_arbitration_isStuck = (decode_arbitration_haltItself || decode_arbitration_isStuckByOthers);
  assign decode_arbitration_isMoving = ((! decode_arbitration_isStuck) && (! decode_arbitration_removeIt));
  assign decode_arbitration_isFiring = ((decode_arbitration_isValid && (! decode_arbitration_isStuck)) && (! decode_arbitration_removeIt));
  assign execute_arbitration_isStuckByOthers = (execute_arbitration_haltByOther || ((1'b0 || memory_arbitration_isStuck) || writeBack_arbitration_isStuck));
  assign execute_arbitration_isStuck = (execute_arbitration_haltItself || execute_arbitration_isStuckByOthers);
  assign execute_arbitration_isMoving = ((! execute_arbitration_isStuck) && (! execute_arbitration_removeIt));
  assign execute_arbitration_isFiring = ((execute_arbitration_isValid && (! execute_arbitration_isStuck)) && (! execute_arbitration_removeIt));
  assign memory_arbitration_isStuckByOthers = (memory_arbitration_haltByOther || (1'b0 || writeBack_arbitration_isStuck));
  assign memory_arbitration_isStuck = (memory_arbitration_haltItself || memory_arbitration_isStuckByOthers);
  assign memory_arbitration_isMoving = ((! memory_arbitration_isStuck) && (! memory_arbitration_removeIt));
  assign memory_arbitration_isFiring = ((memory_arbitration_isValid && (! memory_arbitration_isStuck)) && (! memory_arbitration_removeIt));
  assign writeBack_arbitration_isStuckByOthers = (writeBack_arbitration_haltByOther || 1'b0);
  assign writeBack_arbitration_isStuck = (writeBack_arbitration_haltItself || writeBack_arbitration_isStuckByOthers);
  assign writeBack_arbitration_isMoving = ((! writeBack_arbitration_isStuck) && (! writeBack_arbitration_removeIt));
  assign writeBack_arbitration_isFiring = ((writeBack_arbitration_isValid && (! writeBack_arbitration_isStuck)) && (! writeBack_arbitration_removeIt));
  assign when_Pipeline_l151 = ((! execute_arbitration_isStuck) || execute_arbitration_removeIt);
  assign when_Pipeline_l154 = ((! decode_arbitration_isStuck) && (! decode_arbitration_removeIt));
  assign when_Pipeline_l151_1 = ((! memory_arbitration_isStuck) || memory_arbitration_removeIt);
  assign when_Pipeline_l154_1 = ((! execute_arbitration_isStuck) && (! execute_arbitration_removeIt));
  assign when_Pipeline_l151_2 = ((! writeBack_arbitration_isStuck) || writeBack_arbitration_removeIt);
  assign when_Pipeline_l154_2 = ((! memory_arbitration_isStuck) && (! memory_arbitration_removeIt));
  always @(*) begin
    CsrPlugin_injectionPort_ready = 1'b0;
    case(IBusCachedPlugin_injector_port_state)
      3'b100 : begin
        CsrPlugin_injectionPort_ready = 1'b1;
      end
      default : begin
      end
    endcase
  end

  assign when_Fetcher_l391 = (! decode_arbitration_isStuck);
  assign when_CsrPlugin_l1669 = (! execute_arbitration_isStuck);
  assign when_CsrPlugin_l1669_1 = (! execute_arbitration_isStuck);
  assign when_CsrPlugin_l1669_2 = (! execute_arbitration_isStuck);
  assign when_CsrPlugin_l1669_3 = (! execute_arbitration_isStuck);
  assign when_CsrPlugin_l1669_4 = (! execute_arbitration_isStuck);
  assign when_CsrPlugin_l1669_5 = (! execute_arbitration_isStuck);
  assign when_CsrPlugin_l1669_6 = (! execute_arbitration_isStuck);
  assign when_CsrPlugin_l1669_7 = (! execute_arbitration_isStuck);
  assign when_CsrPlugin_l1669_8 = (! execute_arbitration_isStuck);
  assign when_CsrPlugin_l1669_9 = (! execute_arbitration_isStuck);
  assign when_CsrPlugin_l1669_10 = (! execute_arbitration_isStuck);
  assign when_CsrPlugin_l1669_11 = (! execute_arbitration_isStuck);
  assign when_CsrPlugin_l1669_12 = (! execute_arbitration_isStuck);
  assign when_CsrPlugin_l1669_13 = (! execute_arbitration_isStuck);
  assign when_CsrPlugin_l1669_14 = (! execute_arbitration_isStuck);
  assign when_CsrPlugin_l1669_15 = (! execute_arbitration_isStuck);
  always @(*) begin
    _zz_CsrPlugin_csrMapping_readDataInit_1 = 32'h0;
    if(execute_CsrPlugin_csr_1972) begin
      _zz_CsrPlugin_csrMapping_readDataInit_1[31 : 0] = CsrPlugin_dataCsrw_value_0;
    end
  end

  always @(*) begin
    _zz_CsrPlugin_csrMapping_readDataInit_2 = 32'h0;
    if(execute_CsrPlugin_csr_1969) begin
      _zz_CsrPlugin_csrMapping_readDataInit_2[31 : 0] = CsrPlugin_dpc;
    end
  end

  always @(*) begin
    _zz_CsrPlugin_csrMapping_readDataInit_3 = 32'h0;
    if(execute_CsrPlugin_csr_1968) begin
      _zz_CsrPlugin_csrMapping_readDataInit_3[3 : 3] = CsrPlugin_dcsr_nmip;
      _zz_CsrPlugin_csrMapping_readDataInit_3[8 : 6] = CsrPlugin_dcsr_cause;
      _zz_CsrPlugin_csrMapping_readDataInit_3[31 : 28] = CsrPlugin_dcsr_xdebugver;
      _zz_CsrPlugin_csrMapping_readDataInit_3[4 : 4] = CsrPlugin_dcsr_mprven;
      _zz_CsrPlugin_csrMapping_readDataInit_3[1 : 0] = CsrPlugin_dcsr_prv;
      _zz_CsrPlugin_csrMapping_readDataInit_3[2 : 2] = CsrPlugin_dcsr_step;
      _zz_CsrPlugin_csrMapping_readDataInit_3[9 : 9] = CsrPlugin_dcsr_stoptime;
      _zz_CsrPlugin_csrMapping_readDataInit_3[10 : 10] = CsrPlugin_dcsr_stopcount;
      _zz_CsrPlugin_csrMapping_readDataInit_3[11 : 11] = CsrPlugin_dcsr_stepie;
      _zz_CsrPlugin_csrMapping_readDataInit_3[15 : 15] = CsrPlugin_dcsr_ebreakm;
    end
  end

  always @(*) begin
    _zz_CsrPlugin_csrMapping_readDataInit_4 = 32'h0;
    if(execute_CsrPlugin_csr_1952) begin
      _zz_CsrPlugin_csrMapping_readDataInit_4[0 : 0] = CsrPlugin_trigger_tselect_index;
    end
  end

  always @(*) begin
    _zz_CsrPlugin_csrMapping_readDataInit_5 = 32'h0;
    if(execute_CsrPlugin_csr_1956) begin
      _zz_CsrPlugin_csrMapping_readDataInit_5[0 : 0] = CsrPlugin_trigger_tselect_outOfRange;
      _zz_CsrPlugin_csrMapping_readDataInit_5[2 : 2] = (! CsrPlugin_trigger_tselect_outOfRange);
    end
  end

  always @(*) begin
    _zz_CsrPlugin_csrMapping_readDataInit_6 = 32'h0;
    if(execute_CsrPlugin_csr_1953) begin
      _zz_CsrPlugin_csrMapping_readDataInit_6[31 : 0] = _zz__zz_CsrPlugin_csrMapping_readDataInit_6;
    end
  end

  assign switch_CsrPlugin_l1031 = CsrPlugin_csrMapping_writeDataSignal[12 : 11];
  always @(*) begin
    _zz_CsrPlugin_csrMapping_readDataInit_7 = 32'h0;
    if(execute_CsrPlugin_csr_768) begin
      _zz_CsrPlugin_csrMapping_readDataInit_7[7 : 7] = CsrPlugin_mstatus_MPIE;
      _zz_CsrPlugin_csrMapping_readDataInit_7[3 : 3] = CsrPlugin_mstatus_MIE;
      _zz_CsrPlugin_csrMapping_readDataInit_7[12 : 11] = CsrPlugin_mstatus_MPP;
    end
  end

  always @(*) begin
    _zz_CsrPlugin_csrMapping_readDataInit_8 = 32'h0;
    if(execute_CsrPlugin_csr_836) begin
      _zz_CsrPlugin_csrMapping_readDataInit_8[11 : 11] = CsrPlugin_mip_MEIP;
      _zz_CsrPlugin_csrMapping_readDataInit_8[7 : 7] = CsrPlugin_mip_MTIP;
      _zz_CsrPlugin_csrMapping_readDataInit_8[3 : 3] = CsrPlugin_mip_MSIP;
    end
  end

  always @(*) begin
    _zz_CsrPlugin_csrMapping_readDataInit_9 = 32'h0;
    if(execute_CsrPlugin_csr_772) begin
      _zz_CsrPlugin_csrMapping_readDataInit_9[11 : 11] = CsrPlugin_mie_MEIE;
      _zz_CsrPlugin_csrMapping_readDataInit_9[7 : 7] = CsrPlugin_mie_MTIE;
      _zz_CsrPlugin_csrMapping_readDataInit_9[3 : 3] = CsrPlugin_mie_MSIE;
    end
  end

  always @(*) begin
    _zz_CsrPlugin_csrMapping_readDataInit_10 = 32'h0;
    if(execute_CsrPlugin_csr_833) begin
      _zz_CsrPlugin_csrMapping_readDataInit_10[31 : 0] = CsrPlugin_mepc;
    end
  end

  always @(*) begin
    _zz_CsrPlugin_csrMapping_readDataInit_11 = 32'h0;
    if(execute_CsrPlugin_csr_834) begin
      _zz_CsrPlugin_csrMapping_readDataInit_11[31 : 31] = CsrPlugin_mcause_interrupt;
      _zz_CsrPlugin_csrMapping_readDataInit_11[3 : 0] = CsrPlugin_mcause_exceptionCode;
    end
  end

  always @(*) begin
    _zz_CsrPlugin_csrMapping_readDataInit_12 = 32'h0;
    if(execute_CsrPlugin_csr_835) begin
      _zz_CsrPlugin_csrMapping_readDataInit_12[31 : 0] = CsrPlugin_mtval;
    end
  end

  always @(*) begin
    _zz_CsrPlugin_csrMapping_readDataInit_13 = 32'h0;
    if(execute_CsrPlugin_csr_3008) begin
      _zz_CsrPlugin_csrMapping_readDataInit_13[31 : 0] = _zz_CsrPlugin_csrMapping_readDataInit;
    end
  end

  always @(*) begin
    _zz_CsrPlugin_csrMapping_readDataInit_14 = 32'h0;
    if(execute_CsrPlugin_csr_4032) begin
      _zz_CsrPlugin_csrMapping_readDataInit_14[31 : 0] = _zz_externalInterrupt;
    end
  end

  assign CsrPlugin_csrMapping_readDataInit = ((((_zz_CsrPlugin_csrMapping_readDataInit_1 | _zz_CsrPlugin_csrMapping_readDataInit_2) | (_zz_CsrPlugin_csrMapping_readDataInit_3 | _zz_CsrPlugin_csrMapping_readDataInit_4)) | ((_zz_CsrPlugin_csrMapping_readDataInit_5 | _zz_CsrPlugin_csrMapping_readDataInit_6) | (_zz_CsrPlugin_csrMapping_readDataInit_7 | _zz_CsrPlugin_csrMapping_readDataInit_8))) | (((_zz_CsrPlugin_csrMapping_readDataInit_9 | _zz_CsrPlugin_csrMapping_readDataInit_10) | (_zz_CsrPlugin_csrMapping_readDataInit_11 | _zz_CsrPlugin_csrMapping_readDataInit_12)) | (_zz_CsrPlugin_csrMapping_readDataInit_13 | _zz_CsrPlugin_csrMapping_readDataInit_14)));
  assign when_CsrPlugin_l1702 = ((execute_arbitration_isValid && execute_IS_CSR) && (({execute_CsrPlugin_csrAddress[11 : 2],2'b00} == 12'h3a0) || ({execute_CsrPlugin_csrAddress[11 : 4],4'b0000} == 12'h3b0)));
  assign _zz_when_CsrPlugin_l1709 = (execute_CsrPlugin_csrAddress & 12'hf60);
  assign when_CsrPlugin_l1709 = (((execute_arbitration_isValid && execute_IS_CSR) && (5'h03 <= execute_CsrPlugin_csrAddress[4 : 0])) && (((_zz_when_CsrPlugin_l1709 == 12'hb00) || (((_zz_when_CsrPlugin_l1709 == 12'hc00) && (! execute_CsrPlugin_writeInstruction)) && (CsrPlugin_privilege == 2'b11))) || ((execute_CsrPlugin_csrAddress & 12'hfe0) == 12'h320)));
  always @(*) begin
    when_CsrPlugin_l1719 = CsrPlugin_csrMapping_doForceFailCsr;
    if(when_CsrPlugin_l1717) begin
      when_CsrPlugin_l1719 = 1'b1;
    end
    if(when_CsrPlugin_l1718) begin
      when_CsrPlugin_l1719 = 1'b1;
    end
  end

  assign when_CsrPlugin_l1717 = (CsrPlugin_privilege < execute_CsrPlugin_csrAddress[9 : 8]);
  assign when_CsrPlugin_l1718 = ((! debugMode) && (_zz_when_CsrPlugin_l1718 == 8'h7b));
  assign when_CsrPlugin_l1725 = ((! execute_arbitration_isValid) || (! execute_IS_CSR));
  assign iBusWishbone_ADR = {_zz_iBusWishbone_ADR_1,_zz_iBusWishbone_ADR};
  assign iBusWishbone_CTI = ((_zz_iBusWishbone_ADR == 3'b111) ? 3'b111 : 3'b010);
  assign iBusWishbone_BTE = 2'b00;
  assign iBusWishbone_SEL = 4'b1111;
  assign iBusWishbone_WE = 1'b0;
  assign iBusWishbone_DAT_MOSI = 32'bxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx;
  always @(*) begin
    iBusWishbone_CYC = 1'b0;
    if(when_InstructionCache_l240) begin
      iBusWishbone_CYC = 1'b1;
    end
  end

  always @(*) begin
    iBusWishbone_STB = 1'b0;
    if(when_InstructionCache_l240) begin
      iBusWishbone_STB = 1'b1;
    end
  end

  assign when_InstructionCache_l240 = (iBus_cmd_valid || (_zz_iBusWishbone_ADR != 3'b000));
  assign when_InstructionCache_l243 = (iBusWishbone_ACK || iBusWishbone_ERR);
  assign iBus_cmd_ready = (iBus_cmd_valid && (iBusWishbone_ACK || iBusWishbone_ERR));
  assign iBus_rsp_valid = _zz_iBus_rsp_valid;
  assign iBus_rsp_payload_data = iBusWishbone_DAT_MISO_regNext;
  assign iBus_rsp_payload_error = iBusWishbone_ERR_regNext;
  assign dBus_cmd_halfPipe_fire = (dBus_cmd_halfPipe_valid && dBus_cmd_halfPipe_ready);
  assign dBus_cmd_ready = (! dBus_cmd_rValid);
  assign dBus_cmd_halfPipe_valid = dBus_cmd_rValid;
  assign dBus_cmd_halfPipe_payload_wr = dBus_cmd_rData_wr;
  assign dBus_cmd_halfPipe_payload_mask = dBus_cmd_rData_mask;
  assign dBus_cmd_halfPipe_payload_address = dBus_cmd_rData_address;
  assign dBus_cmd_halfPipe_payload_data = dBus_cmd_rData_data;
  assign dBus_cmd_halfPipe_payload_size = dBus_cmd_rData_size;
  assign dBusWishbone_ADR = (dBus_cmd_halfPipe_payload_address >>> 2'd2);
  assign dBusWishbone_CTI = 3'b000;
  assign dBusWishbone_BTE = 2'b00;
  always @(*) begin
    case(dBus_cmd_halfPipe_payload_size)
      2'b00 : begin
        _zz_dBusWishbone_SEL = 4'b0001;
      end
      2'b01 : begin
        _zz_dBusWishbone_SEL = 4'b0011;
      end
      default : begin
        _zz_dBusWishbone_SEL = 4'b1111;
      end
    endcase
  end

  assign dBusWishbone_SEL = (_zz_dBusWishbone_SEL <<< dBus_cmd_halfPipe_payload_address[1 : 0]);
  assign dBusWishbone_WE = dBus_cmd_halfPipe_payload_wr;
  assign dBusWishbone_DAT_MOSI = dBus_cmd_halfPipe_payload_data;
  assign dBus_cmd_halfPipe_ready = (dBus_cmd_halfPipe_valid && (dBusWishbone_ACK || dBusWishbone_ERR));
  assign dBusWishbone_CYC = dBus_cmd_halfPipe_valid;
  assign dBusWishbone_STB = dBus_cmd_halfPipe_valid;
  assign dBus_rsp_ready = ((dBus_cmd_halfPipe_valid && (! dBusWishbone_WE)) && (dBusWishbone_ACK || dBusWishbone_ERR));
  assign dBus_rsp_data = dBusWishbone_DAT_MISO;
  assign dBus_rsp_error = dBusWishbone_ERR;
  always @(posedge clk) begin
    if(reset) begin
      IBusCachedPlugin_fetchPc_pcReg <= externalResetVector;
      IBusCachedPlugin_fetchPc_correctionReg <= 1'b0;
      IBusCachedPlugin_fetchPc_booted <= 1'b0;
      IBusCachedPlugin_fetchPc_inc <= 1'b0;
      _zz_IBusCachedPlugin_iBusRsp_stages_0_output_toEvent_m2sPipe_valid <= 1'b0;
      _zz_IBusCachedPlugin_iBusRsp_stages_1_output_m2sPipe_valid <= 1'b0;
      IBusCachedPlugin_injector_nextPcCalc_valids_0 <= 1'b0;
      IBusCachedPlugin_injector_nextPcCalc_valids_1 <= 1'b0;
      IBusCachedPlugin_injector_nextPcCalc_valids_2 <= 1'b0;
      IBusCachedPlugin_injector_nextPcCalc_valids_3 <= 1'b0;
      IBusCachedPlugin_injector_nextPcCalc_valids_4 <= 1'b0;
      IBusCachedPlugin_rspCounter <= 32'h0;
      _zz_10 <= 1'b1;
      execute_LightShifterPlugin_isActive <= 1'b0;
      HazardSimplePlugin_writeBackBuffer_valid <= 1'b0;
      _zz_CsrPlugin_privilege <= 2'b11;
      CsrPlugin_running <= 1'b1;
      CsrPlugin_reseting <= 1'b1;
      _zz_debugBus_haveReset <= 1'b0;
      CsrPlugin_running_aheadValue_regNext <= 1'b0;
      CsrPlugin_doHalt <= 1'b0;
      _zz_CsrPlugin_doResume <= 1'b0;
      CsrPlugin_timeout_state <= 1'b0;
      CsrPlugin_timeout_counter_value <= 3'b000;
      CsrPlugin_inject_cmd_toStream_rValid <= 1'b0;
      CsrPlugin_inject_pending <= 1'b0;
      CsrPlugin_dcsr_prv <= 2'b11;
      CsrPlugin_dcsr_step <= 1'b0;
      CsrPlugin_dcsr_cause <= 3'b000;
      CsrPlugin_dcsr_stoptime <= 1'b0;
      CsrPlugin_dcsr_stopcount <= 1'b0;
      CsrPlugin_dcsr_stepie <= 1'b0;
      CsrPlugin_dcsr_ebreakm <= 1'b0;
      CsrPlugin_dcsr_stepLogic_stateReg <= CsrPlugin_dcsr_stepLogic_BOOT;
      stoptime <= 1'b0;
      CsrPlugin_trigger_decodeBreak_timeout_state <= 1'b0;
      CsrPlugin_trigger_decodeBreak_timeout_counter_value <= 2'b00;
      CsrPlugin_trigger_slots_0_tdata1_dmode <= 1'b0;
      CsrPlugin_trigger_slots_0_tdata1_execute <= 1'b0;
      CsrPlugin_trigger_slots_0_tdata1_m <= 1'b0;
      CsrPlugin_trigger_slots_0_tdata1_s <= 1'b0;
      CsrPlugin_trigger_slots_0_tdata1_u <= 1'b0;
      CsrPlugin_trigger_slots_0_tdata1_action <= 4'b0000;
      CsrPlugin_trigger_slots_1_tdata1_dmode <= 1'b0;
      CsrPlugin_trigger_slots_1_tdata1_execute <= 1'b0;
      CsrPlugin_trigger_slots_1_tdata1_m <= 1'b0;
      CsrPlugin_trigger_slots_1_tdata1_s <= 1'b0;
      CsrPlugin_trigger_slots_1_tdata1_u <= 1'b0;
      CsrPlugin_trigger_slots_1_tdata1_action <= 4'b0000;
      CsrPlugin_mstatus_MIE <= 1'b0;
      CsrPlugin_mstatus_MPIE <= 1'b0;
      CsrPlugin_mstatus_MPP <= 2'b11;
      CsrPlugin_mie_MEIE <= 1'b0;
      CsrPlugin_mie_MTIE <= 1'b0;
      CsrPlugin_mie_MSIE <= 1'b0;
      CsrPlugin_mcycle <= 64'h0;
      CsrPlugin_minstret <= 64'h0;
      CsrPlugin_exceptionPortCtrl_exceptionValidsRegs_decode <= 1'b0;
      CsrPlugin_exceptionPortCtrl_exceptionValidsRegs_execute <= 1'b0;
      CsrPlugin_exceptionPortCtrl_exceptionValidsRegs_memory <= 1'b0;
      CsrPlugin_exceptionPortCtrl_exceptionValidsRegs_writeBack <= 1'b0;
      CsrPlugin_interrupt_valid <= 1'b0;
      CsrPlugin_pipelineLiberator_pcValids_0 <= 1'b0;
      CsrPlugin_pipelineLiberator_pcValids_1 <= 1'b0;
      CsrPlugin_pipelineLiberator_pcValids_2 <= 1'b0;
      CsrPlugin_hadException <= 1'b0;
      execute_CsrPlugin_wfiWake <= 1'b0;
      memory_MulDivIterativePlugin_mul_counter_value <= 6'h0;
      memory_MulDivIterativePlugin_div_counter_value <= 6'h0;
      _zz_CsrPlugin_csrMapping_readDataInit <= 32'h0;
      execute_arbitration_isValid <= 1'b0;
      memory_arbitration_isValid <= 1'b0;
      writeBack_arbitration_isValid <= 1'b0;
      IBusCachedPlugin_injector_port_state <= 3'b000;
      _zz_iBusWishbone_ADR <= 3'b000;
      _zz_iBus_rsp_valid <= 1'b0;
      dBus_cmd_rValid <= 1'b0;
    end else begin
      if(IBusCachedPlugin_fetchPc_correction) begin
        IBusCachedPlugin_fetchPc_correctionReg <= 1'b1;
      end
      if(IBusCachedPlugin_fetchPc_output_fire) begin
        IBusCachedPlugin_fetchPc_correctionReg <= 1'b0;
      end
      IBusCachedPlugin_fetchPc_booted <= 1'b1;
      if(when_Fetcher_l133) begin
        IBusCachedPlugin_fetchPc_inc <= 1'b0;
      end
      if(IBusCachedPlugin_fetchPc_output_fire) begin
        IBusCachedPlugin_fetchPc_inc <= 1'b1;
      end
      if(when_Fetcher_l133_1) begin
        IBusCachedPlugin_fetchPc_inc <= 1'b0;
      end
      if(when_Fetcher_l160) begin
        IBusCachedPlugin_fetchPc_pcReg <= IBusCachedPlugin_fetchPc_pc;
      end
      if(IBusCachedPlugin_iBusRsp_flush) begin
        _zz_IBusCachedPlugin_iBusRsp_stages_0_output_toEvent_m2sPipe_valid <= 1'b0;
      end
      if(IBusCachedPlugin_iBusRsp_stages_0_output_toEvent_ready) begin
        _zz_IBusCachedPlugin_iBusRsp_stages_0_output_toEvent_m2sPipe_valid <= (IBusCachedPlugin_iBusRsp_stages_0_output_toEvent_valid && (! 1'b0));
      end
      if(IBusCachedPlugin_iBusRsp_flush) begin
        _zz_IBusCachedPlugin_iBusRsp_stages_1_output_m2sPipe_valid <= 1'b0;
      end
      if(IBusCachedPlugin_iBusRsp_stages_1_output_ready) begin
        _zz_IBusCachedPlugin_iBusRsp_stages_1_output_m2sPipe_valid <= (IBusCachedPlugin_iBusRsp_stages_1_output_valid && (! IBusCachedPlugin_iBusRsp_flush));
      end
      if(IBusCachedPlugin_fetchPc_flushed) begin
        IBusCachedPlugin_injector_nextPcCalc_valids_0 <= 1'b0;
      end
      if(when_Fetcher_l331) begin
        IBusCachedPlugin_injector_nextPcCalc_valids_0 <= 1'b1;
      end
      if(IBusCachedPlugin_fetchPc_flushed) begin
        IBusCachedPlugin_injector_nextPcCalc_valids_1 <= 1'b0;
      end
      if(when_Fetcher_l331_1) begin
        IBusCachedPlugin_injector_nextPcCalc_valids_1 <= IBusCachedPlugin_injector_nextPcCalc_valids_0;
      end
      if(IBusCachedPlugin_fetchPc_flushed) begin
        IBusCachedPlugin_injector_nextPcCalc_valids_1 <= 1'b0;
      end
      if(IBusCachedPlugin_fetchPc_flushed) begin
        IBusCachedPlugin_injector_nextPcCalc_valids_2 <= 1'b0;
      end
      if(when_Fetcher_l331_2) begin
        IBusCachedPlugin_injector_nextPcCalc_valids_2 <= IBusCachedPlugin_injector_nextPcCalc_valids_1;
      end
      if(IBusCachedPlugin_fetchPc_flushed) begin
        IBusCachedPlugin_injector_nextPcCalc_valids_2 <= 1'b0;
      end
      if(IBusCachedPlugin_fetchPc_flushed) begin
        IBusCachedPlugin_injector_nextPcCalc_valids_3 <= 1'b0;
      end
      if(when_Fetcher_l331_3) begin
        IBusCachedPlugin_injector_nextPcCalc_valids_3 <= IBusCachedPlugin_injector_nextPcCalc_valids_2;
      end
      if(IBusCachedPlugin_fetchPc_flushed) begin
        IBusCachedPlugin_injector_nextPcCalc_valids_3 <= 1'b0;
      end
      if(IBusCachedPlugin_fetchPc_flushed) begin
        IBusCachedPlugin_injector_nextPcCalc_valids_4 <= 1'b0;
      end
      if(when_Fetcher_l331_4) begin
        IBusCachedPlugin_injector_nextPcCalc_valids_4 <= IBusCachedPlugin_injector_nextPcCalc_valids_3;
      end
      if(IBusCachedPlugin_fetchPc_flushed) begin
        IBusCachedPlugin_injector_nextPcCalc_valids_4 <= 1'b0;
      end
      if(iBus_rsp_valid) begin
        IBusCachedPlugin_rspCounter <= (IBusCachedPlugin_rspCounter + 32'h00000001);
      end
      _zz_10 <= 1'b0;
      if(when_ShiftPlugins_l169) begin
        if(when_ShiftPlugins_l175) begin
          execute_LightShifterPlugin_isActive <= 1'b1;
          if(execute_LightShifterPlugin_done) begin
            execute_LightShifterPlugin_isActive <= 1'b0;
          end
        end
      end
      if(execute_arbitration_removeIt) begin
        execute_LightShifterPlugin_isActive <= 1'b0;
      end
      HazardSimplePlugin_writeBackBuffer_valid <= HazardSimplePlugin_writeBackWrites_valid;
      CsrPlugin_reseting <= 1'b0;
      if(CsrPlugin_reseting) begin
        _zz_debugBus_haveReset <= 1'b1;
      end
      if(debugBus_ackReset) begin
        _zz_debugBus_haveReset <= 1'b0;
      end
      CsrPlugin_running_aheadValue_regNext <= CsrPlugin_running_aheadValue;
      if(when_CsrPlugin_l729) begin
        CsrPlugin_doHalt <= 1'b1;
      end
      if(CsrPlugin_enterHalt) begin
        CsrPlugin_doHalt <= 1'b0;
      end
      if(debugBus_resume_cmd_valid) begin
        _zz_CsrPlugin_doResume <= 1'b1;
      end
      if(debugBus_resume_rsp_valid) begin
        _zz_CsrPlugin_doResume <= 1'b0;
      end
      CsrPlugin_timeout_counter_value <= CsrPlugin_timeout_counter_valueNext;
      if(CsrPlugin_timeout_counter_willOverflow) begin
        CsrPlugin_timeout_state <= 1'b1;
      end
      if(when_CsrPlugin_l735) begin
        CsrPlugin_timeout_state <= 1'b0;
      end
      if(CsrPlugin_inject_cmd_toStream_ready) begin
        CsrPlugin_inject_cmd_toStream_rValid <= CsrPlugin_inject_cmd_toStream_valid;
      end
      if(when_CsrPlugin_l786) begin
        CsrPlugin_inject_pending <= 1'b1;
      end
      if(when_CsrPlugin_l786_1) begin
        CsrPlugin_inject_pending <= 1'b0;
      end
      if(CsrPlugin_inject_cmd_valid) begin
        CsrPlugin_timeout_state <= 1'b0;
      end
      CsrPlugin_dcsr_stepLogic_stateReg <= CsrPlugin_dcsr_stepLogic_stateNext;
      case(CsrPlugin_dcsr_stepLogic_stateReg)
        CsrPlugin_dcsr_stepLogic_IDLE : begin
        end
        CsrPlugin_dcsr_stepLogic_SINGLE : begin
          CsrPlugin_timeout_state <= 1'b0;
          if(when_CsrPlugin_l818) begin
            CsrPlugin_doHalt <= 1'b1;
          end
        end
        CsrPlugin_dcsr_stepLogic_WAIT_1 : begin
          if(!when_CsrPlugin_l830) begin
            if(writeBack_arbitration_isFiring) begin
              CsrPlugin_doHalt <= 1'b1;
            end
          end
        end
        default : begin
        end
      endcase
      stoptime <= (debugMode && CsrPlugin_dcsr_stoptime);
      CsrPlugin_trigger_decodeBreak_timeout_counter_value <= CsrPlugin_trigger_decodeBreak_timeout_counter_valueNext;
      if(CsrPlugin_trigger_decodeBreak_timeout_counter_willOverflow) begin
        CsrPlugin_trigger_decodeBreak_timeout_state <= 1'b1;
      end
      if(when_Utils_l694) begin
        CsrPlugin_trigger_decodeBreak_timeout_state <= 1'b0;
      end
      if(CsrPlugin_trigger_decodeBreak_enabled) begin
        if(CsrPlugin_trigger_decodeBreak_timeout_state) begin
          CsrPlugin_dcsr_cause <= 3'b010;
          CsrPlugin_dcsr_prv <= CsrPlugin_privilege;
          _zz_CsrPlugin_privilege <= 2'b11;
        end
      end
      CsrPlugin_mcycle <= (CsrPlugin_mcycle + _zz_CsrPlugin_mcycle);
      if(writeBack_arbitration_isFiring) begin
        CsrPlugin_minstret <= (CsrPlugin_minstret + 64'h0000000000000001);
      end
      if(when_CsrPlugin_l1259) begin
        CsrPlugin_exceptionPortCtrl_exceptionValidsRegs_decode <= 1'b0;
      end else begin
        CsrPlugin_exceptionPortCtrl_exceptionValidsRegs_decode <= CsrPlugin_exceptionPortCtrl_exceptionValids_decode;
      end
      if(when_CsrPlugin_l1259_1) begin
        CsrPlugin_exceptionPortCtrl_exceptionValidsRegs_execute <= (CsrPlugin_exceptionPortCtrl_exceptionValids_decode && (! decode_arbitration_isStuck));
      end else begin
        CsrPlugin_exceptionPortCtrl_exceptionValidsRegs_execute <= CsrPlugin_exceptionPortCtrl_exceptionValids_execute;
      end
      if(when_CsrPlugin_l1259_2) begin
        CsrPlugin_exceptionPortCtrl_exceptionValidsRegs_memory <= (CsrPlugin_exceptionPortCtrl_exceptionValids_execute && (! execute_arbitration_isStuck));
      end else begin
        CsrPlugin_exceptionPortCtrl_exceptionValidsRegs_memory <= CsrPlugin_exceptionPortCtrl_exceptionValids_memory;
      end
      if(when_CsrPlugin_l1259_3) begin
        CsrPlugin_exceptionPortCtrl_exceptionValidsRegs_writeBack <= (CsrPlugin_exceptionPortCtrl_exceptionValids_memory && (! memory_arbitration_isStuck));
      end else begin
        CsrPlugin_exceptionPortCtrl_exceptionValidsRegs_writeBack <= 1'b0;
      end
      CsrPlugin_interrupt_valid <= 1'b0;
      if(when_CsrPlugin_l1296) begin
        if(when_CsrPlugin_l1302) begin
          CsrPlugin_interrupt_valid <= 1'b1;
        end
        if(when_CsrPlugin_l1302_1) begin
          CsrPlugin_interrupt_valid <= 1'b1;
        end
        if(when_CsrPlugin_l1302_2) begin
          CsrPlugin_interrupt_valid <= 1'b1;
        end
      end
      if(when_CsrPlugin_l1315) begin
        CsrPlugin_interrupt_valid <= 1'b0;
      end
      if(CsrPlugin_doHalt) begin
        CsrPlugin_interrupt_valid <= 1'b1;
      end
      if(CsrPlugin_pipelineLiberator_active) begin
        if(when_CsrPlugin_l1335) begin
          CsrPlugin_pipelineLiberator_pcValids_0 <= 1'b1;
        end
        if(when_CsrPlugin_l1335_1) begin
          CsrPlugin_pipelineLiberator_pcValids_1 <= CsrPlugin_pipelineLiberator_pcValids_0;
        end
        if(when_CsrPlugin_l1335_2) begin
          CsrPlugin_pipelineLiberator_pcValids_2 <= CsrPlugin_pipelineLiberator_pcValids_1;
        end
      end
      if(when_CsrPlugin_l1340) begin
        CsrPlugin_pipelineLiberator_pcValids_0 <= 1'b0;
        CsrPlugin_pipelineLiberator_pcValids_1 <= 1'b0;
        CsrPlugin_pipelineLiberator_pcValids_2 <= 1'b0;
      end
      if(CsrPlugin_interruptJump) begin
        CsrPlugin_interrupt_valid <= 1'b0;
      end
      CsrPlugin_hadException <= CsrPlugin_exception;
      if(when_CsrPlugin_l1390) begin
        if(when_CsrPlugin_l1398) begin
          _zz_CsrPlugin_privilege <= CsrPlugin_targetPrivilege;
          case(CsrPlugin_targetPrivilege)
            2'b11 : begin
              CsrPlugin_mstatus_MIE <= 1'b0;
              CsrPlugin_mstatus_MPIE <= CsrPlugin_mstatus_MIE;
              CsrPlugin_mstatus_MPP <= CsrPlugin_privilege;
            end
            default : begin
            end
          endcase
        end else begin
          if(when_CsrPlugin_l1428) begin
            CsrPlugin_dcsr_cause <= 3'b011;
            if(CsrPlugin_dcsr_step) begin
              CsrPlugin_dcsr_cause <= 3'b100;
            end
            if(CsrPlugin_trapCauseEbreakDebug) begin
              CsrPlugin_dcsr_cause <= 3'b001;
            end
            CsrPlugin_dcsr_prv <= CsrPlugin_privilege;
          end
          _zz_CsrPlugin_privilege <= 2'b11;
        end
      end
      if(when_CsrPlugin_l1456) begin
        case(switch_CsrPlugin_l1460)
          2'b11 : begin
            CsrPlugin_mstatus_MPP <= 2'b00;
            CsrPlugin_mstatus_MIE <= CsrPlugin_mstatus_MPIE;
            CsrPlugin_mstatus_MPIE <= 1'b1;
            _zz_CsrPlugin_privilege <= CsrPlugin_mstatus_MPP;
          end
          default : begin
          end
        endcase
      end
      if(CsrPlugin_doResume) begin
        _zz_CsrPlugin_privilege <= CsrPlugin_dcsr_prv;
      end
      execute_CsrPlugin_wfiWake <= ((|{_zz_when_CsrPlugin_l1302_2,{_zz_when_CsrPlugin_l1302_1,_zz_when_CsrPlugin_l1302}}) || CsrPlugin_thirdPartyWake);
      memory_MulDivIterativePlugin_mul_counter_value <= memory_MulDivIterativePlugin_mul_counter_valueNext;
      memory_MulDivIterativePlugin_div_counter_value <= memory_MulDivIterativePlugin_div_counter_valueNext;
      if(when_Pipeline_l151) begin
        execute_arbitration_isValid <= 1'b0;
      end
      if(when_Pipeline_l154) begin
        execute_arbitration_isValid <= decode_arbitration_isValid;
      end
      if(when_Pipeline_l151_1) begin
        memory_arbitration_isValid <= 1'b0;
      end
      if(when_Pipeline_l154_1) begin
        memory_arbitration_isValid <= execute_arbitration_isValid;
      end
      if(when_Pipeline_l151_2) begin
        writeBack_arbitration_isValid <= 1'b0;
      end
      if(when_Pipeline_l154_2) begin
        writeBack_arbitration_isValid <= memory_arbitration_isValid;
      end
      case(IBusCachedPlugin_injector_port_state)
        3'b000 : begin
          if(CsrPlugin_injectionPort_valid) begin
            IBusCachedPlugin_injector_port_state <= 3'b001;
          end
        end
        3'b001 : begin
          IBusCachedPlugin_injector_port_state <= 3'b010;
        end
        3'b010 : begin
          IBusCachedPlugin_injector_port_state <= 3'b011;
        end
        3'b011 : begin
          if(when_Fetcher_l391) begin
            IBusCachedPlugin_injector_port_state <= 3'b100;
          end
        end
        3'b100 : begin
          IBusCachedPlugin_injector_port_state <= 3'b000;
        end
        default : begin
        end
      endcase
      if(execute_CsrPlugin_csr_1968) begin
        if(execute_CsrPlugin_writeEnable) begin
          CsrPlugin_dcsr_prv <= CsrPlugin_csrMapping_writeDataSignal[1 : 0];
          CsrPlugin_dcsr_step <= CsrPlugin_csrMapping_writeDataSignal[2];
          CsrPlugin_dcsr_stoptime <= CsrPlugin_csrMapping_writeDataSignal[9];
          CsrPlugin_dcsr_stopcount <= CsrPlugin_csrMapping_writeDataSignal[10];
          CsrPlugin_dcsr_stepie <= CsrPlugin_csrMapping_writeDataSignal[11];
          CsrPlugin_dcsr_ebreakm <= CsrPlugin_csrMapping_writeDataSignal[15];
        end
      end
      if(execute_CsrPlugin_csr_1953) begin
        if(execute_CsrPlugin_writeEnable) begin
          if(CsrPlugin_trigger_slots_0_selected) begin
            CsrPlugin_trigger_slots_0_tdata1_execute <= CsrPlugin_csrMapping_writeDataSignal[2];
            CsrPlugin_trigger_slots_0_tdata1_u <= CsrPlugin_csrMapping_writeDataSignal[3];
            CsrPlugin_trigger_slots_0_tdata1_s <= CsrPlugin_csrMapping_writeDataSignal[4];
            CsrPlugin_trigger_slots_0_tdata1_m <= CsrPlugin_csrMapping_writeDataSignal[6];
            CsrPlugin_trigger_slots_0_tdata1_dmode <= CsrPlugin_csrMapping_writeDataSignal[27];
            CsrPlugin_trigger_slots_0_tdata1_action <= CsrPlugin_csrMapping_writeDataSignal[15 : 12];
          end
          if(CsrPlugin_trigger_slots_1_selected) begin
            CsrPlugin_trigger_slots_1_tdata1_execute <= CsrPlugin_csrMapping_writeDataSignal[2];
            CsrPlugin_trigger_slots_1_tdata1_u <= CsrPlugin_csrMapping_writeDataSignal[3];
            CsrPlugin_trigger_slots_1_tdata1_s <= CsrPlugin_csrMapping_writeDataSignal[4];
            CsrPlugin_trigger_slots_1_tdata1_m <= CsrPlugin_csrMapping_writeDataSignal[6];
            CsrPlugin_trigger_slots_1_tdata1_dmode <= CsrPlugin_csrMapping_writeDataSignal[27];
            CsrPlugin_trigger_slots_1_tdata1_action <= CsrPlugin_csrMapping_writeDataSignal[15 : 12];
          end
        end
      end
      if(execute_CsrPlugin_csr_768) begin
        if(execute_CsrPlugin_writeEnable) begin
          CsrPlugin_mstatus_MPIE <= CsrPlugin_csrMapping_writeDataSignal[7];
          CsrPlugin_mstatus_MIE <= CsrPlugin_csrMapping_writeDataSignal[3];
          case(switch_CsrPlugin_l1031)
            2'b11 : begin
              CsrPlugin_mstatus_MPP <= 2'b11;
            end
            default : begin
            end
          endcase
        end
      end
      if(execute_CsrPlugin_csr_772) begin
        if(execute_CsrPlugin_writeEnable) begin
          CsrPlugin_mie_MEIE <= CsrPlugin_csrMapping_writeDataSignal[11];
          CsrPlugin_mie_MTIE <= CsrPlugin_csrMapping_writeDataSignal[7];
          CsrPlugin_mie_MSIE <= CsrPlugin_csrMapping_writeDataSignal[3];
        end
      end
      if(execute_CsrPlugin_csr_3008) begin
        if(execute_CsrPlugin_writeEnable) begin
          _zz_CsrPlugin_csrMapping_readDataInit <= CsrPlugin_csrMapping_writeDataSignal[31 : 0];
        end
      end
      if(when_InstructionCache_l240) begin
        if(when_InstructionCache_l243) begin
          _zz_iBusWishbone_ADR <= (_zz_iBusWishbone_ADR + 3'b001);
        end
      end
      _zz_iBus_rsp_valid <= (iBusWishbone_CYC && (iBusWishbone_ACK || iBusWishbone_ERR));
      if(dBus_cmd_valid) begin
        dBus_cmd_rValid <= 1'b1;
      end
      if(dBus_cmd_halfPipe_fire) begin
        dBus_cmd_rValid <= 1'b0;
      end
      CsrPlugin_running <= CsrPlugin_running_aheadValue;
    end
  end

  always @(posedge clk) begin
    if(IBusCachedPlugin_iBusRsp_stages_1_output_ready) begin
      _zz_IBusCachedPlugin_iBusRsp_stages_1_output_m2sPipe_payload <= IBusCachedPlugin_iBusRsp_stages_1_output_payload;
    end
    if(IBusCachedPlugin_iBusRsp_stages_1_input_ready) begin
      IBusCachedPlugin_s1_tightlyCoupledHit <= IBusCachedPlugin_s0_tightlyCoupledHit;
    end
    if(IBusCachedPlugin_iBusRsp_stages_2_input_ready) begin
      IBusCachedPlugin_s2_tightlyCoupledHit <= IBusCachedPlugin_s1_tightlyCoupledHit;
    end
    if(when_ShiftPlugins_l169) begin
      if(when_ShiftPlugins_l175) begin
        execute_LightShifterPlugin_amplitudeReg <= (execute_LightShifterPlugin_amplitude - 5'h01);
      end
    end
    HazardSimplePlugin_writeBackBuffer_payload_address <= HazardSimplePlugin_writeBackWrites_payload_address;
    HazardSimplePlugin_writeBackBuffer_payload_data <= HazardSimplePlugin_writeBackWrites_payload_data;
    if(when_CsrPlugin_l750) begin
      if(_zz_when[0]) begin
        CsrPlugin_dataCsrw_value_0 <= debugBus_dmToHart_payload_data;
      end
    end
    if(CsrPlugin_inject_cmd_toStream_ready) begin
      CsrPlugin_inject_cmd_toStream_rData_op <= CsrPlugin_inject_cmd_toStream_payload_op;
      CsrPlugin_inject_cmd_toStream_rData_address <= CsrPlugin_inject_cmd_toStream_payload_address;
      CsrPlugin_inject_cmd_toStream_rData_data <= CsrPlugin_inject_cmd_toStream_payload_data;
      CsrPlugin_inject_cmd_toStream_rData_size <= CsrPlugin_inject_cmd_toStream_payload_size;
    end
    if(CsrPlugin_trigger_decodeBreak_enabled) begin
      if(CsrPlugin_trigger_decodeBreak_timeout_state) begin
        CsrPlugin_dpc <= decode_PC;
      end
    end
    if(CsrPlugin_trigger_slots_0_selected) begin
      CsrPlugin_trigger_slots_0_tdata2_value[31 : 0] <= CsrPlugin_trigger_slots_0_tdata2_value;
    end
    if(CsrPlugin_trigger_slots_1_selected) begin
      CsrPlugin_trigger_slots_1_tdata2_value[31 : 0] <= CsrPlugin_trigger_slots_1_tdata2_value;
    end
    CsrPlugin_mip_MEIP <= externalInterrupt;
    CsrPlugin_mip_MTIP <= timerInterrupt;
    CsrPlugin_mip_MSIP <= softwareInterrupt;
    if(_zz_when_1) begin
      CsrPlugin_exceptionPortCtrl_exceptionContext_code <= (_zz_CsrPlugin_exceptionPortCtrl_exceptionContext_code_1 ? IBusCachedPlugin_decodeExceptionPort_payload_code : decodeExceptionPort_payload_code);
      CsrPlugin_exceptionPortCtrl_exceptionContext_badAddr <= (_zz_CsrPlugin_exceptionPortCtrl_exceptionContext_code_1 ? IBusCachedPlugin_decodeExceptionPort_payload_badAddr : decodeExceptionPort_payload_badAddr);
    end
    if(CsrPlugin_selfException_valid) begin
      CsrPlugin_exceptionPortCtrl_exceptionContext_code <= CsrPlugin_selfException_payload_code;
      CsrPlugin_exceptionPortCtrl_exceptionContext_badAddr <= CsrPlugin_selfException_payload_badAddr;
    end
    if(_zz_when_2) begin
      CsrPlugin_exceptionPortCtrl_exceptionContext_code <= (_zz_CsrPlugin_exceptionPortCtrl_exceptionContext_code_3 ? DBusSimplePlugin_memoryExceptionPort_payload_code : BranchPlugin_branchExceptionPort_payload_code);
      CsrPlugin_exceptionPortCtrl_exceptionContext_badAddr <= (_zz_CsrPlugin_exceptionPortCtrl_exceptionContext_code_3 ? DBusSimplePlugin_memoryExceptionPort_payload_badAddr : BranchPlugin_branchExceptionPort_payload_badAddr);
    end
    if(when_CsrPlugin_l1296) begin
      if(when_CsrPlugin_l1302) begin
        CsrPlugin_interrupt_code <= 4'b0111;
        CsrPlugin_interrupt_targetPrivilege <= 2'b11;
      end
      if(when_CsrPlugin_l1302_1) begin
        CsrPlugin_interrupt_code <= 4'b0011;
        CsrPlugin_interrupt_targetPrivilege <= 2'b11;
      end
      if(when_CsrPlugin_l1302_2) begin
        CsrPlugin_interrupt_code <= 4'b1011;
        CsrPlugin_interrupt_targetPrivilege <= 2'b11;
      end
    end
    if(when_CsrPlugin_l1390) begin
      if(when_CsrPlugin_l1398) begin
        case(CsrPlugin_targetPrivilege)
          2'b11 : begin
            CsrPlugin_mcause_interrupt <= (! CsrPlugin_hadException);
            CsrPlugin_mcause_exceptionCode <= CsrPlugin_trapCause;
            CsrPlugin_mepc <= writeBack_PC;
            if(CsrPlugin_hadException) begin
              CsrPlugin_mtval <= CsrPlugin_exceptionPortCtrl_exceptionContext_badAddr;
            end
          end
          default : begin
          end
        endcase
      end else begin
        if(when_CsrPlugin_l1428) begin
          CsrPlugin_dpc <= writeBack_PC;
        end
      end
    end
    if(when_MulDivIterativePlugin_l96) begin
      if(when_MulDivIterativePlugin_l100) begin
        memory_MulDivIterativePlugin_rs2 <= (memory_MulDivIterativePlugin_rs2 >>> 1);
        memory_MulDivIterativePlugin_accumulator <= ({_zz_memory_MulDivIterativePlugin_accumulator,memory_MulDivIterativePlugin_accumulator[31 : 0]} >>> 1'd1);
      end
    end
    if(when_MulDivIterativePlugin_l126) begin
      memory_MulDivIterativePlugin_div_done <= 1'b1;
    end
    if(when_MulDivIterativePlugin_l126_1) begin
      memory_MulDivIterativePlugin_div_done <= 1'b0;
    end
    if(when_MulDivIterativePlugin_l128) begin
      if(when_MulDivIterativePlugin_l132) begin
        memory_MulDivIterativePlugin_rs1[31 : 0] <= memory_MulDivIterativePlugin_div_stage_0_outNumerator;
        memory_MulDivIterativePlugin_accumulator[31 : 0] <= memory_MulDivIterativePlugin_div_stage_0_outRemainder;
        if(when_MulDivIterativePlugin_l151) begin
          memory_MulDivIterativePlugin_div_result <= _zz_memory_MulDivIterativePlugin_div_result_1[31:0];
        end
      end
    end
    if(when_MulDivIterativePlugin_l162) begin
      memory_MulDivIterativePlugin_accumulator <= 65'h0;
      memory_MulDivIterativePlugin_rs1 <= ((_zz_memory_MulDivIterativePlugin_rs1 ? (~ _zz_memory_MulDivIterativePlugin_rs1_1) : _zz_memory_MulDivIterativePlugin_rs1_1) + _zz_memory_MulDivIterativePlugin_rs1_2);
      memory_MulDivIterativePlugin_rs2 <= ((_zz_memory_MulDivIterativePlugin_rs2 ? (~ execute_RS2) : execute_RS2) + _zz_memory_MulDivIterativePlugin_rs2_1);
      memory_MulDivIterativePlugin_div_needRevert <= ((_zz_memory_MulDivIterativePlugin_rs1 ^ (_zz_memory_MulDivIterativePlugin_rs2 && (! execute_INSTRUCTION[13]))) && (! (((execute_RS2 == 32'h0) && execute_IS_RS2_SIGNED) && (! execute_INSTRUCTION[13]))));
    end
    externalInterruptArray_regNext <= externalInterruptArray;
    if(when_Pipeline_l124) begin
      decode_to_execute_PC <= decode_PC;
    end
    if(when_Pipeline_l124_1) begin
      execute_to_memory_PC <= _zz_execute_to_memory_PC;
    end
    if(when_Pipeline_l124_2) begin
      memory_to_writeBack_PC <= memory_PC;
    end
    if(when_Pipeline_l124_3) begin
      decode_to_execute_INSTRUCTION <= decode_INSTRUCTION;
    end
    if(when_Pipeline_l124_4) begin
      execute_to_memory_INSTRUCTION <= execute_INSTRUCTION;
    end
    if(when_Pipeline_l124_5) begin
      memory_to_writeBack_INSTRUCTION <= memory_INSTRUCTION;
    end
    if(when_Pipeline_l124_6) begin
      decode_to_execute_FORMAL_PC_NEXT <= _zz_decode_to_execute_FORMAL_PC_NEXT;
    end
    if(when_Pipeline_l124_7) begin
      execute_to_memory_FORMAL_PC_NEXT <= execute_FORMAL_PC_NEXT;
    end
    if(when_Pipeline_l124_8) begin
      memory_to_writeBack_FORMAL_PC_NEXT <= _zz_memory_to_writeBack_FORMAL_PC_NEXT;
    end
    if(when_Pipeline_l124_9) begin
      decode_to_execute_SRC1_CTRL <= _zz_decode_to_execute_SRC1_CTRL;
    end
    if(when_Pipeline_l124_10) begin
      decode_to_execute_SRC_USE_SUB_LESS <= decode_SRC_USE_SUB_LESS;
    end
    if(when_Pipeline_l124_11) begin
      decode_to_execute_MEMORY_ENABLE <= decode_MEMORY_ENABLE;
    end
    if(when_Pipeline_l124_12) begin
      execute_to_memory_MEMORY_ENABLE <= execute_MEMORY_ENABLE;
    end
    if(when_Pipeline_l124_13) begin
      memory_to_writeBack_MEMORY_ENABLE <= memory_MEMORY_ENABLE;
    end
    if(when_Pipeline_l124_14) begin
      decode_to_execute_ALU_CTRL <= _zz_decode_to_execute_ALU_CTRL;
    end
    if(when_Pipeline_l124_15) begin
      decode_to_execute_SRC2_CTRL <= _zz_decode_to_execute_SRC2_CTRL;
    end
    if(when_Pipeline_l124_16) begin
      decode_to_execute_REGFILE_WRITE_VALID <= decode_REGFILE_WRITE_VALID;
    end
    if(when_Pipeline_l124_17) begin
      execute_to_memory_REGFILE_WRITE_VALID <= execute_REGFILE_WRITE_VALID;
    end
    if(when_Pipeline_l124_18) begin
      memory_to_writeBack_REGFILE_WRITE_VALID <= memory_REGFILE_WRITE_VALID;
    end
    if(when_Pipeline_l124_19) begin
      decode_to_execute_BYPASSABLE_EXECUTE_STAGE <= decode_BYPASSABLE_EXECUTE_STAGE;
    end
    if(when_Pipeline_l124_20) begin
      decode_to_execute_BYPASSABLE_MEMORY_STAGE <= decode_BYPASSABLE_MEMORY_STAGE;
    end
    if(when_Pipeline_l124_21) begin
      execute_to_memory_BYPASSABLE_MEMORY_STAGE <= execute_BYPASSABLE_MEMORY_STAGE;
    end
    if(when_Pipeline_l124_22) begin
      decode_to_execute_MEMORY_STORE <= decode_MEMORY_STORE;
    end
    if(when_Pipeline_l124_23) begin
      execute_to_memory_MEMORY_STORE <= execute_MEMORY_STORE;
    end
    if(when_Pipeline_l124_24) begin
      decode_to_execute_SRC_LESS_UNSIGNED <= decode_SRC_LESS_UNSIGNED;
    end
    if(when_Pipeline_l124_25) begin
      decode_to_execute_ALU_BITWISE_CTRL <= _zz_decode_to_execute_ALU_BITWISE_CTRL;
    end
    if(when_Pipeline_l124_26) begin
      decode_to_execute_SHIFT_CTRL <= _zz_decode_to_execute_SHIFT_CTRL;
    end
    if(when_Pipeline_l124_27) begin
      decode_to_execute_BRANCH_CTRL <= _zz_decode_to_execute_BRANCH_CTRL;
    end
    if(when_Pipeline_l124_28) begin
      decode_to_execute_IS_CSR <= decode_IS_CSR;
    end
    if(when_Pipeline_l124_29) begin
      decode_to_execute_ENV_CTRL <= _zz_decode_to_execute_ENV_CTRL;
    end
    if(when_Pipeline_l124_30) begin
      execute_to_memory_ENV_CTRL <= _zz_execute_to_memory_ENV_CTRL;
    end
    if(when_Pipeline_l124_31) begin
      memory_to_writeBack_ENV_CTRL <= _zz_memory_to_writeBack_ENV_CTRL;
    end
    if(when_Pipeline_l124_32) begin
      decode_to_execute_IS_MUL <= decode_IS_MUL;
    end
    if(when_Pipeline_l124_33) begin
      execute_to_memory_IS_MUL <= execute_IS_MUL;
    end
    if(when_Pipeline_l124_34) begin
      decode_to_execute_IS_RS1_SIGNED <= decode_IS_RS1_SIGNED;
    end
    if(when_Pipeline_l124_35) begin
      decode_to_execute_IS_RS2_SIGNED <= decode_IS_RS2_SIGNED;
    end
    if(when_Pipeline_l124_36) begin
      decode_to_execute_IS_DIV <= decode_IS_DIV;
    end
    if(when_Pipeline_l124_37) begin
      execute_to_memory_IS_DIV <= execute_IS_DIV;
    end
    if(when_Pipeline_l124_38) begin
      decode_to_execute_RS1 <= decode_RS1;
    end
    if(when_Pipeline_l124_39) begin
      decode_to_execute_RS2 <= decode_RS2;
    end
    if(when_Pipeline_l124_40) begin
      decode_to_execute_SRC2_FORCE_ZERO <= decode_SRC2_FORCE_ZERO;
    end
    if(when_Pipeline_l124_41) begin
      decode_to_execute_PREDICTION_HAD_BRANCHED1 <= decode_PREDICTION_HAD_BRANCHED1;
    end
    if(when_Pipeline_l124_42) begin
      decode_to_execute_CSR_WRITE_OPCODE <= decode_CSR_WRITE_OPCODE;
    end
    if(when_Pipeline_l124_43) begin
      decode_to_execute_CSR_READ_OPCODE <= decode_CSR_READ_OPCODE;
    end
    if(when_Pipeline_l124_44) begin
      execute_to_memory_ALIGNEMENT_FAULT <= execute_ALIGNEMENT_FAULT;
    end
    if(when_Pipeline_l124_45) begin
      execute_to_memory_MEMORY_ADDRESS_LOW <= execute_MEMORY_ADDRESS_LOW;
    end
    if(when_Pipeline_l124_46) begin
      memory_to_writeBack_MEMORY_ADDRESS_LOW <= memory_MEMORY_ADDRESS_LOW;
    end
    if(when_Pipeline_l124_47) begin
      execute_to_memory_REGFILE_WRITE_DATA <= _zz_decode_RS2_1;
    end
    if(when_Pipeline_l124_48) begin
      memory_to_writeBack_REGFILE_WRITE_DATA <= _zz_decode_RS2;
    end
    if(when_Pipeline_l124_49) begin
      execute_to_memory_BRANCH_DO <= execute_BRANCH_DO;
    end
    if(when_Pipeline_l124_50) begin
      execute_to_memory_BRANCH_CALC <= execute_BRANCH_CALC;
    end
    if(when_Pipeline_l124_51) begin
      memory_to_writeBack_MEMORY_READ_DATA <= memory_MEMORY_READ_DATA;
    end
    if(when_CsrPlugin_l1669) begin
      execute_CsrPlugin_csr_1972 <= (decode_INSTRUCTION[31 : 20] == 12'h7b4);
    end
    if(when_CsrPlugin_l1669_1) begin
      execute_CsrPlugin_csr_1969 <= (decode_INSTRUCTION[31 : 20] == 12'h7b1);
    end
    if(when_CsrPlugin_l1669_2) begin
      execute_CsrPlugin_csr_1968 <= (decode_INSTRUCTION[31 : 20] == 12'h7b0);
    end
    if(when_CsrPlugin_l1669_3) begin
      execute_CsrPlugin_csr_1952 <= (decode_INSTRUCTION[31 : 20] == 12'h7a0);
    end
    if(when_CsrPlugin_l1669_4) begin
      execute_CsrPlugin_csr_1956 <= (decode_INSTRUCTION[31 : 20] == 12'h7a4);
    end
    if(when_CsrPlugin_l1669_5) begin
      execute_CsrPlugin_csr_1953 <= (decode_INSTRUCTION[31 : 20] == 12'h7a1);
    end
    if(when_CsrPlugin_l1669_6) begin
      execute_CsrPlugin_csr_1954 <= (decode_INSTRUCTION[31 : 20] == 12'h7a2);
    end
    if(when_CsrPlugin_l1669_7) begin
      execute_CsrPlugin_csr_768 <= (decode_INSTRUCTION[31 : 20] == 12'h300);
    end
    if(when_CsrPlugin_l1669_8) begin
      execute_CsrPlugin_csr_836 <= (decode_INSTRUCTION[31 : 20] == 12'h344);
    end
    if(when_CsrPlugin_l1669_9) begin
      execute_CsrPlugin_csr_772 <= (decode_INSTRUCTION[31 : 20] == 12'h304);
    end
    if(when_CsrPlugin_l1669_10) begin
      execute_CsrPlugin_csr_773 <= (decode_INSTRUCTION[31 : 20] == 12'h305);
    end
    if(when_CsrPlugin_l1669_11) begin
      execute_CsrPlugin_csr_833 <= (decode_INSTRUCTION[31 : 20] == 12'h341);
    end
    if(when_CsrPlugin_l1669_12) begin
      execute_CsrPlugin_csr_834 <= (decode_INSTRUCTION[31 : 20] == 12'h342);
    end
    if(when_CsrPlugin_l1669_13) begin
      execute_CsrPlugin_csr_835 <= (decode_INSTRUCTION[31 : 20] == 12'h343);
    end
    if(when_CsrPlugin_l1669_14) begin
      execute_CsrPlugin_csr_3008 <= (decode_INSTRUCTION[31 : 20] == 12'hbc0);
    end
    if(when_CsrPlugin_l1669_15) begin
      execute_CsrPlugin_csr_4032 <= (decode_INSTRUCTION[31 : 20] == 12'hfc0);
    end
    if(execute_CsrPlugin_csr_1969) begin
      if(execute_CsrPlugin_writeEnable) begin
        CsrPlugin_dpc <= CsrPlugin_csrMapping_writeDataSignal[31 : 0];
      end
    end
    if(execute_CsrPlugin_csr_1952) begin
      if(execute_CsrPlugin_writeEnable) begin
        CsrPlugin_trigger_tselect_index <= CsrPlugin_csrMapping_writeDataSignal[0 : 0];
      end
    end
    if(execute_CsrPlugin_csr_1954) begin
      if(execute_CsrPlugin_writeEnable) begin
        if(CsrPlugin_trigger_slots_0_selected) begin
          CsrPlugin_trigger_slots_0_tdata2_value <= CsrPlugin_csrMapping_writeDataSignal[31 : 0];
        end
        if(CsrPlugin_trigger_slots_1_selected) begin
          CsrPlugin_trigger_slots_1_tdata2_value <= CsrPlugin_csrMapping_writeDataSignal[31 : 0];
        end
      end
    end
    if(execute_CsrPlugin_csr_836) begin
      if(execute_CsrPlugin_writeEnable) begin
        CsrPlugin_mip_MSIP <= CsrPlugin_csrMapping_writeDataSignal[3];
      end
    end
    if(execute_CsrPlugin_csr_773) begin
      if(execute_CsrPlugin_writeEnable) begin
        CsrPlugin_mtvec_base <= CsrPlugin_csrMapping_writeDataSignal[31 : 2];
      end
    end
    if(execute_CsrPlugin_csr_833) begin
      if(execute_CsrPlugin_writeEnable) begin
        CsrPlugin_mepc <= CsrPlugin_csrMapping_writeDataSignal[31 : 0];
      end
    end
    iBusWishbone_DAT_MISO_regNext <= iBusWishbone_DAT_MISO;
    iBusWishbone_ERR_regNext <= iBusWishbone_ERR;
    if(dBus_cmd_ready) begin
      dBus_cmd_rData_wr <= dBus_cmd_payload_wr;
      dBus_cmd_rData_mask <= dBus_cmd_payload_mask;
      dBus_cmd_rData_address <= dBus_cmd_payload_address;
      dBus_cmd_rData_data <= dBus_cmd_payload_data;
      dBus_cmd_rData_size <= dBus_cmd_payload_size;
    end
  end

  always @(posedge clk) begin
    if(debugReset) begin
      io_harts_0_dmToHart_regNext_valid <= 1'b0;
    end else begin
      io_harts_0_dmToHart_regNext_valid <= debugModule_1_io_harts_0_dmToHart_valid;
    end
  end

  always @(posedge clk) begin
    io_harts_0_dmToHart_regNext_payload_op <= debugModule_1_io_harts_0_dmToHart_payload_op;
    io_harts_0_dmToHart_regNext_payload_address <= debugModule_1_io_harts_0_dmToHart_payload_address;
    io_harts_0_dmToHart_regNext_payload_data <= debugModule_1_io_harts_0_dmToHart_payload_data;
    io_harts_0_dmToHart_regNext_payload_size <= debugModule_1_io_harts_0_dmToHart_payload_size;
  end


endmodule

module DebugTransportModuleTunneled (
  input  wire          io_instruction_tdi,
  input  wire          io_instruction_enable,
  input  wire          io_instruction_capture,
  input  wire          io_instruction_shift,
  input  wire          io_instruction_update,
  input  wire          io_instruction_reset,
  output wire          io_instruction_tdo,
  output wire          io_bus_cmd_valid,
  input  wire          io_bus_cmd_ready,
  output wire          io_bus_cmd_payload_write,
  output wire [31:0]   io_bus_cmd_payload_data,
  output wire [6:0]    io_bus_cmd_payload_address,
  input  wire          io_bus_rsp_valid,
  input  wire          io_bus_rsp_payload_error,
  input  wire [31:0]   io_bus_rsp_payload_data,
  input  wire          jtag_clk,
  input  wire          clk,
  input  wire          debugReset
);
  localparam DebugCaptureOp_SUCCESS = 2'd0;
  localparam DebugCaptureOp_RESERVED = 2'd1;
  localparam DebugCaptureOp_FAILED = 2'd2;
  localparam DebugCaptureOp_OVERRUN = 2'd3;
  localparam DebugUpdateOp_NOP = 2'd0;
  localparam DebugUpdateOp_READ = 2'd1;
  localparam DebugUpdateOp_WRITE = 2'd2;
  localparam DebugUpdateOp_RESERVED = 2'd3;

  wire                logic_jtagLogic_dmiCmd_ccToggle_io_output_valid;
  wire                logic_jtagLogic_dmiCmd_ccToggle_io_output_payload_write;
  wire       [31:0]   logic_jtagLogic_dmiCmd_ccToggle_io_output_payload_data;
  wire       [6:0]    logic_jtagLogic_dmiCmd_ccToggle_io_output_payload_address;
  wire                logic_systemLogic_bus_rsp_ccToggle_io_output_valid;
  wire                logic_systemLogic_bus_rsp_ccToggle_io_output_payload_error;
  wire       [31:0]   logic_systemLogic_bus_rsp_ccToggle_io_output_payload_data;
  reg        [1:0]    logic_jtagLogic_dmiStat_value_aheadValue;
  reg        [13:0]   tap_shiftBuffer;
  reg        [5:0]    tap_instruction;
  reg                 tap_sendCapture;
  reg                 tap_sendShift;
  reg                 tap_sendUpdate;
  wire                when_JtagTunnel_l30;
  reg                 io_instruction_tdi_delay_1;
  reg                 io_instruction_tdi_delay_2;
  reg                 io_instruction_tdi_delay_3;
  reg                 io_instruction_tdi_delay_4;
  reg                 io_instruction_tdi_delay_5;
  reg                 io_instruction_tdi_delay_6;
  reg                 io_instruction_tdi_delay_7;
  reg                 io_instruction_tdi_delay_8;
  reg                 tap_tdiBuffer;
  reg                 tap_tdoBuffer;
  reg                 tap_tdoBuffer_delay_1;
  reg                 tap_tdoBuffer_delay_2;
  reg                 tap_tdoBuffer_delay_3;
  reg                 tap_tdoShifter;
  wire                logic_jtagLogic_dmiCmd_valid;
  wire                logic_jtagLogic_dmiCmd_payload_write;
  wire       [31:0]   logic_jtagLogic_dmiCmd_payload_data;
  wire       [6:0]    logic_jtagLogic_dmiCmd_payload_address;
  wire                logic_jtagLogic_dmiRsp_valid;
  wire                logic_jtagLogic_dmiRsp_payload_error;
  wire       [31:0]   logic_jtagLogic_dmiRsp_payload_data;
  wire       [31:0]   logic_jtagLogic_dtmcs_captureData;
  wire       [31:0]   logic_jtagLogic_dtmcs_updateData;
  wire                logic_jtagLogic_dtmcs_captureValid;
  wire                logic_jtagLogic_dtmcs_updateValid;
  wire                logic_jtagLogic_dtmcs_logic_ctrl_tdi;
  wire                logic_jtagLogic_dtmcs_logic_ctrl_enable;
  wire                logic_jtagLogic_dtmcs_logic_ctrl_capture;
  wire                logic_jtagLogic_dtmcs_logic_ctrl_shift;
  wire                logic_jtagLogic_dtmcs_logic_ctrl_update;
  wire                logic_jtagLogic_dtmcs_logic_ctrl_reset;
  wire                logic_jtagLogic_dtmcs_logic_ctrl_tdo;
  reg        [31:0]   logic_jtagLogic_dtmcs_logic_store;
  wire                when_JtagTunnel_l53;
  wire       [1:0]    logic_jtagLogic_dmi_captureData_op;
  wire       [31:0]   logic_jtagLogic_dmi_captureData_data;
  wire       [6:0]    logic_jtagLogic_dmi_captureData_padding;
  wire       [1:0]    logic_jtagLogic_dmi_updateData_op;
  wire       [31:0]   logic_jtagLogic_dmi_updateData_data;
  wire       [6:0]    logic_jtagLogic_dmi_updateData_address;
  wire                logic_jtagLogic_dmi_captureValid;
  wire                logic_jtagLogic_dmi_updateValid;
  wire                logic_jtagLogic_dmi_logic_ctrl_tdi;
  wire                logic_jtagLogic_dmi_logic_ctrl_enable;
  wire                logic_jtagLogic_dmi_logic_ctrl_capture;
  wire                logic_jtagLogic_dmi_logic_ctrl_shift;
  wire                logic_jtagLogic_dmi_logic_ctrl_update;
  wire                logic_jtagLogic_dmi_logic_ctrl_reset;
  wire                logic_jtagLogic_dmi_logic_ctrl_tdo;
  reg        [40:0]   logic_jtagLogic_dmi_logic_store;
  wire       [1:0]    _zz_logic_jtagLogic_dmi_updateData_op;
  wire                when_JtagTunnel_l53_1;
  reg        [1:0]    logic_jtagLogic_dmiStat_value;
  reg                 logic_jtagLogic_dmiStat_failure;
  reg                 logic_jtagLogic_dmiStat_busy;
  reg                 logic_jtagLogic_dmiStat_clear;
  wire                when_DebugTransportModuleJtag_l36;
  reg                 logic_jtagLogic_pending;
  wire                logic_jtagLogic_trigger_dmiHardReset;
  wire                logic_jtagLogic_trigger_dmiReset;
  reg                 logic_jtagLogic_trigger_dmiCmd;
  reg        [31:0]   logic_jtagLogic_rspLogic_buffer;
  wire                when_DebugTransportModuleJtag_l84;
  wire                logic_systemLogic_bus_cmd_valid;
  wire                logic_systemLogic_bus_cmd_ready;
  wire                logic_systemLogic_bus_cmd_payload_write;
  wire       [31:0]   logic_systemLogic_bus_cmd_payload_data;
  wire       [6:0]    logic_systemLogic_bus_cmd_payload_address;
  wire                logic_systemLogic_bus_rsp_valid;
  wire                logic_systemLogic_bus_rsp_payload_error;
  wire       [31:0]   logic_systemLogic_bus_rsp_payload_data;
  wire                logic_jtagLogic_dmiCmd_ccToggle_io_output_toStream_valid;
  reg                 logic_jtagLogic_dmiCmd_ccToggle_io_output_toStream_ready;
  wire                logic_jtagLogic_dmiCmd_ccToggle_io_output_toStream_payload_write;
  wire       [31:0]   logic_jtagLogic_dmiCmd_ccToggle_io_output_toStream_payload_data;
  wire       [6:0]    logic_jtagLogic_dmiCmd_ccToggle_io_output_toStream_payload_address;
  wire                logic_systemLogic_cmd_valid;
  wire                logic_systemLogic_cmd_ready;
  wire                logic_systemLogic_cmd_payload_write;
  wire       [31:0]   logic_systemLogic_cmd_payload_data;
  wire       [6:0]    logic_systemLogic_cmd_payload_address;
  reg                 logic_jtagLogic_dmiCmd_ccToggle_io_output_toStream_rValid;
  wire                logic_jtagLogic_dmiCmd_ccToggle_io_output_toStream_fire;
  (* async_reg = "true" , altera_attribute = "-name ADV_NETLIST_OPT_ALLOWED NEVER_ALLOW" *) reg                 logic_jtagLogic_dmiCmd_ccToggle_io_output_toStream_rData_write;
  (* async_reg = "true" , altera_attribute = "-name ADV_NETLIST_OPT_ALLOWED NEVER_ALLOW" *) reg        [31:0]   logic_jtagLogic_dmiCmd_ccToggle_io_output_toStream_rData_data;
  (* async_reg = "true" , altera_attribute = "-name ADV_NETLIST_OPT_ALLOWED NEVER_ALLOW" *) reg        [6:0]    logic_jtagLogic_dmiCmd_ccToggle_io_output_toStream_rData_address;
  wire                when_Stream_l477;
  `ifndef SYNTHESIS
  reg [63:0] logic_jtagLogic_dmiStat_value_aheadValue_string;
  reg [63:0] logic_jtagLogic_dmi_captureData_op_string;
  reg [63:0] logic_jtagLogic_dmi_updateData_op_string;
  reg [63:0] _zz_logic_jtagLogic_dmi_updateData_op_string;
  reg [63:0] logic_jtagLogic_dmiStat_value_string;
  `endif


  FlowCCByToggle logic_jtagLogic_dmiCmd_ccToggle (
    .io_input_valid            (logic_jtagLogic_dmiCmd_valid                                  ), //i
    .io_input_payload_write    (logic_jtagLogic_dmiCmd_payload_write                          ), //i
    .io_input_payload_data     (logic_jtagLogic_dmiCmd_payload_data[31:0]                     ), //i
    .io_input_payload_address  (logic_jtagLogic_dmiCmd_payload_address[6:0]                   ), //i
    .io_output_valid           (logic_jtagLogic_dmiCmd_ccToggle_io_output_valid               ), //o
    .io_output_payload_write   (logic_jtagLogic_dmiCmd_ccToggle_io_output_payload_write       ), //o
    .io_output_payload_data    (logic_jtagLogic_dmiCmd_ccToggle_io_output_payload_data[31:0]  ), //o
    .io_output_payload_address (logic_jtagLogic_dmiCmd_ccToggle_io_output_payload_address[6:0]), //o
    .jtag_clk                  (jtag_clk                                                      ), //i
    .clk                       (clk                                                           ), //i
    .debugReset                (debugReset                                                    )  //i
  );
  FlowCCByToggle_1 logic_systemLogic_bus_rsp_ccToggle (
    .io_input_valid          (logic_systemLogic_bus_rsp_valid                                ), //i
    .io_input_payload_error  (logic_systemLogic_bus_rsp_payload_error                        ), //i
    .io_input_payload_data   (logic_systemLogic_bus_rsp_payload_data[31:0]                   ), //i
    .io_output_valid         (logic_systemLogic_bus_rsp_ccToggle_io_output_valid             ), //o
    .io_output_payload_error (logic_systemLogic_bus_rsp_ccToggle_io_output_payload_error     ), //o
    .io_output_payload_data  (logic_systemLogic_bus_rsp_ccToggle_io_output_payload_data[31:0]), //o
    .clk                     (clk                                                            ), //i
    .debugReset              (debugReset                                                     ), //i
    .jtag_clk                (jtag_clk                                                       )  //i
  );
  `ifndef SYNTHESIS
  always @(*) begin
    case(logic_jtagLogic_dmiStat_value_aheadValue)
      DebugCaptureOp_SUCCESS : logic_jtagLogic_dmiStat_value_aheadValue_string = "SUCCESS ";
      DebugCaptureOp_RESERVED : logic_jtagLogic_dmiStat_value_aheadValue_string = "RESERVED";
      DebugCaptureOp_FAILED : logic_jtagLogic_dmiStat_value_aheadValue_string = "FAILED  ";
      DebugCaptureOp_OVERRUN : logic_jtagLogic_dmiStat_value_aheadValue_string = "OVERRUN ";
      default : logic_jtagLogic_dmiStat_value_aheadValue_string = "????????";
    endcase
  end
  always @(*) begin
    case(logic_jtagLogic_dmi_captureData_op)
      DebugCaptureOp_SUCCESS : logic_jtagLogic_dmi_captureData_op_string = "SUCCESS ";
      DebugCaptureOp_RESERVED : logic_jtagLogic_dmi_captureData_op_string = "RESERVED";
      DebugCaptureOp_FAILED : logic_jtagLogic_dmi_captureData_op_string = "FAILED  ";
      DebugCaptureOp_OVERRUN : logic_jtagLogic_dmi_captureData_op_string = "OVERRUN ";
      default : logic_jtagLogic_dmi_captureData_op_string = "????????";
    endcase
  end
  always @(*) begin
    case(logic_jtagLogic_dmi_updateData_op)
      DebugUpdateOp_NOP : logic_jtagLogic_dmi_updateData_op_string = "NOP     ";
      DebugUpdateOp_READ : logic_jtagLogic_dmi_updateData_op_string = "READ    ";
      DebugUpdateOp_WRITE : logic_jtagLogic_dmi_updateData_op_string = "WRITE   ";
      DebugUpdateOp_RESERVED : logic_jtagLogic_dmi_updateData_op_string = "RESERVED";
      default : logic_jtagLogic_dmi_updateData_op_string = "????????";
    endcase
  end
  always @(*) begin
    case(_zz_logic_jtagLogic_dmi_updateData_op)
      DebugUpdateOp_NOP : _zz_logic_jtagLogic_dmi_updateData_op_string = "NOP     ";
      DebugUpdateOp_READ : _zz_logic_jtagLogic_dmi_updateData_op_string = "READ    ";
      DebugUpdateOp_WRITE : _zz_logic_jtagLogic_dmi_updateData_op_string = "WRITE   ";
      DebugUpdateOp_RESERVED : _zz_logic_jtagLogic_dmi_updateData_op_string = "RESERVED";
      default : _zz_logic_jtagLogic_dmi_updateData_op_string = "????????";
    endcase
  end
  always @(*) begin
    case(logic_jtagLogic_dmiStat_value)
      DebugCaptureOp_SUCCESS : logic_jtagLogic_dmiStat_value_string = "SUCCESS ";
      DebugCaptureOp_RESERVED : logic_jtagLogic_dmiStat_value_string = "RESERVED";
      DebugCaptureOp_FAILED : logic_jtagLogic_dmiStat_value_string = "FAILED  ";
      DebugCaptureOp_OVERRUN : logic_jtagLogic_dmiStat_value_string = "OVERRUN ";
      default : logic_jtagLogic_dmiStat_value_string = "????????";
    endcase
  end
  `endif

  always @(*) begin
    logic_jtagLogic_dmiStat_value_aheadValue = logic_jtagLogic_dmiStat_value;
    if(when_DebugTransportModuleJtag_l36) begin
      if(logic_jtagLogic_dmiStat_failure) begin
        logic_jtagLogic_dmiStat_value_aheadValue = DebugCaptureOp_FAILED;
      end
      if(logic_jtagLogic_dmiStat_busy) begin
        logic_jtagLogic_dmiStat_value_aheadValue = DebugCaptureOp_OVERRUN;
      end
    end
    if(logic_jtagLogic_dmiStat_clear) begin
      logic_jtagLogic_dmiStat_value_aheadValue = DebugCaptureOp_SUCCESS;
    end
  end

  always @(*) begin
    tap_sendCapture = 1'b0;
    if(io_instruction_enable) begin
      if(io_instruction_capture) begin
        tap_sendCapture = 1'b1;
      end
    end
  end

  always @(*) begin
    tap_sendShift = 1'b0;
    if(io_instruction_enable) begin
      if(io_instruction_shift) begin
        tap_sendShift = 1'b1;
      end
    end
  end

  always @(*) begin
    tap_sendUpdate = 1'b0;
    if(io_instruction_enable) begin
      if(io_instruction_update) begin
        if(!when_JtagTunnel_l30) begin
          tap_sendUpdate = 1'b1;
        end
      end
    end
  end

  assign when_JtagTunnel_l30 = (! tap_shiftBuffer[13]);
  always @(*) begin
    tap_tdoBuffer = 1'b0;
    if(when_JtagTunnel_l53) begin
      tap_tdoBuffer = logic_jtagLogic_dtmcs_logic_ctrl_tdo;
    end
    if(when_JtagTunnel_l53_1) begin
      tap_tdoBuffer = logic_jtagLogic_dmi_logic_ctrl_tdo;
    end
  end

  assign io_instruction_tdo = tap_tdoShifter;
  assign logic_jtagLogic_dtmcs_captureValid = ((tap_instruction == 6'h10) && tap_sendCapture);
  assign logic_jtagLogic_dtmcs_updateValid = ((tap_instruction == 6'h10) && tap_sendUpdate);
  assign logic_jtagLogic_dtmcs_logic_ctrl_tdo = logic_jtagLogic_dtmcs_logic_store[0];
  assign logic_jtagLogic_dtmcs_updateData = logic_jtagLogic_dtmcs_logic_store;
  assign when_JtagTunnel_l53 = (tap_instruction == 6'h10);
  assign logic_jtagLogic_dtmcs_logic_ctrl_tdi = tap_tdiBuffer;
  assign logic_jtagLogic_dtmcs_logic_ctrl_enable = when_JtagTunnel_l53;
  assign logic_jtagLogic_dtmcs_logic_ctrl_capture = (when_JtagTunnel_l53 && tap_sendCapture);
  assign logic_jtagLogic_dtmcs_logic_ctrl_shift = (when_JtagTunnel_l53 && tap_sendShift);
  assign logic_jtagLogic_dtmcs_logic_ctrl_update = (when_JtagTunnel_l53 && tap_sendUpdate);
  assign logic_jtagLogic_dtmcs_logic_ctrl_reset = io_instruction_reset;
  assign logic_jtagLogic_dmi_captureValid = ((tap_instruction == 6'h11) && tap_sendCapture);
  assign logic_jtagLogic_dmi_updateValid = ((tap_instruction == 6'h11) && tap_sendUpdate);
  assign logic_jtagLogic_dmi_logic_ctrl_tdo = logic_jtagLogic_dmi_logic_store[0];
  assign _zz_logic_jtagLogic_dmi_updateData_op = logic_jtagLogic_dmi_logic_store[1 : 0];
  assign logic_jtagLogic_dmi_updateData_op = _zz_logic_jtagLogic_dmi_updateData_op;
  assign logic_jtagLogic_dmi_updateData_data = logic_jtagLogic_dmi_logic_store[33 : 2];
  assign logic_jtagLogic_dmi_updateData_address = logic_jtagLogic_dmi_logic_store[40 : 34];
  assign when_JtagTunnel_l53_1 = (tap_instruction == 6'h11);
  assign logic_jtagLogic_dmi_logic_ctrl_tdi = tap_tdiBuffer;
  assign logic_jtagLogic_dmi_logic_ctrl_enable = when_JtagTunnel_l53_1;
  assign logic_jtagLogic_dmi_logic_ctrl_capture = (when_JtagTunnel_l53_1 && tap_sendCapture);
  assign logic_jtagLogic_dmi_logic_ctrl_shift = (when_JtagTunnel_l53_1 && tap_sendShift);
  assign logic_jtagLogic_dmi_logic_ctrl_update = (when_JtagTunnel_l53_1 && tap_sendUpdate);
  assign logic_jtagLogic_dmi_logic_ctrl_reset = io_instruction_reset;
  always @(*) begin
    logic_jtagLogic_dmiStat_failure = 1'b0;
    if(logic_jtagLogic_dmi_updateValid) begin
      case(logic_jtagLogic_dmi_updateData_op)
        DebugUpdateOp_NOP : begin
        end
        DebugUpdateOp_READ : begin
        end
        DebugUpdateOp_WRITE : begin
        end
        default : begin
          logic_jtagLogic_dmiStat_failure = 1'b1;
        end
      endcase
    end
    if(logic_jtagLogic_dmiRsp_valid) begin
      if(logic_jtagLogic_dmiRsp_payload_error) begin
        logic_jtagLogic_dmiStat_failure = 1'b1;
      end
    end
  end

  always @(*) begin
    logic_jtagLogic_dmiStat_busy = 1'b0;
    if(when_DebugTransportModuleJtag_l84) begin
      logic_jtagLogic_dmiStat_busy = 1'b1;
    end
  end

  always @(*) begin
    logic_jtagLogic_dmiStat_clear = 1'b0;
    if(logic_jtagLogic_trigger_dmiReset) begin
      logic_jtagLogic_dmiStat_clear = 1'b1;
    end
    if(logic_jtagLogic_trigger_dmiHardReset) begin
      logic_jtagLogic_dmiStat_clear = 1'b1;
    end
  end

  assign when_DebugTransportModuleJtag_l36 = (logic_jtagLogic_dmiStat_value == DebugCaptureOp_SUCCESS);
  assign logic_jtagLogic_trigger_dmiHardReset = ((logic_jtagLogic_dtmcs_updateData[17] && logic_jtagLogic_dtmcs_updateValid) || io_instruction_reset);
  assign logic_jtagLogic_trigger_dmiReset = ((logic_jtagLogic_dtmcs_updateData[16] && logic_jtagLogic_dtmcs_updateValid) || io_instruction_reset);
  always @(*) begin
    logic_jtagLogic_trigger_dmiCmd = 1'b0;
    if(logic_jtagLogic_dmi_updateValid) begin
      case(logic_jtagLogic_dmi_updateData_op)
        DebugUpdateOp_NOP : begin
        end
        DebugUpdateOp_READ : begin
          logic_jtagLogic_trigger_dmiCmd = 1'b1;
        end
        DebugUpdateOp_WRITE : begin
          logic_jtagLogic_trigger_dmiCmd = 1'b1;
        end
        default : begin
        end
      endcase
    end
  end

  assign logic_jtagLogic_dtmcs_captureData = {{{{17'h0,3'b111},logic_jtagLogic_dmiStat_value},6'h07},4'b0001};
  assign logic_jtagLogic_dmiCmd_valid = logic_jtagLogic_trigger_dmiCmd;
  assign logic_jtagLogic_dmiCmd_payload_write = (logic_jtagLogic_dmi_updateData_op == DebugUpdateOp_WRITE);
  assign logic_jtagLogic_dmiCmd_payload_address = logic_jtagLogic_dmi_updateData_address;
  assign logic_jtagLogic_dmiCmd_payload_data = logic_jtagLogic_dmi_updateData_data;
  assign logic_jtagLogic_dmi_captureData_op = logic_jtagLogic_dmiStat_value_aheadValue;
  assign logic_jtagLogic_dmi_captureData_data = logic_jtagLogic_rspLogic_buffer;
  assign logic_jtagLogic_dmi_captureData_padding = 7'h0;
  assign when_DebugTransportModuleJtag_l84 = (logic_jtagLogic_dmi_captureValid && logic_jtagLogic_pending);
  assign logic_jtagLogic_dmiCmd_ccToggle_io_output_toStream_valid = logic_jtagLogic_dmiCmd_ccToggle_io_output_valid;
  assign logic_jtagLogic_dmiCmd_ccToggle_io_output_toStream_payload_write = logic_jtagLogic_dmiCmd_ccToggle_io_output_payload_write;
  assign logic_jtagLogic_dmiCmd_ccToggle_io_output_toStream_payload_data = logic_jtagLogic_dmiCmd_ccToggle_io_output_payload_data;
  assign logic_jtagLogic_dmiCmd_ccToggle_io_output_toStream_payload_address = logic_jtagLogic_dmiCmd_ccToggle_io_output_payload_address;
  assign logic_jtagLogic_dmiCmd_ccToggle_io_output_toStream_fire = (logic_jtagLogic_dmiCmd_ccToggle_io_output_toStream_valid && logic_jtagLogic_dmiCmd_ccToggle_io_output_toStream_ready);
  always @(*) begin
    logic_jtagLogic_dmiCmd_ccToggle_io_output_toStream_ready = logic_systemLogic_cmd_ready;
    if(when_Stream_l477) begin
      logic_jtagLogic_dmiCmd_ccToggle_io_output_toStream_ready = 1'b1;
    end
  end

  assign when_Stream_l477 = (! logic_systemLogic_cmd_valid);
  assign logic_systemLogic_cmd_valid = logic_jtagLogic_dmiCmd_ccToggle_io_output_toStream_rValid;
  assign logic_systemLogic_cmd_payload_write = logic_jtagLogic_dmiCmd_ccToggle_io_output_toStream_rData_write;
  assign logic_systemLogic_cmd_payload_data = logic_jtagLogic_dmiCmd_ccToggle_io_output_toStream_rData_data;
  assign logic_systemLogic_cmd_payload_address = logic_jtagLogic_dmiCmd_ccToggle_io_output_toStream_rData_address;
  assign logic_systemLogic_bus_cmd_valid = logic_systemLogic_cmd_valid;
  assign logic_systemLogic_cmd_ready = logic_systemLogic_bus_cmd_ready;
  assign logic_systemLogic_bus_cmd_payload_write = logic_systemLogic_cmd_payload_write;
  assign logic_systemLogic_bus_cmd_payload_data = logic_systemLogic_cmd_payload_data;
  assign logic_systemLogic_bus_cmd_payload_address = logic_systemLogic_cmd_payload_address;
  assign logic_jtagLogic_dmiRsp_valid = logic_systemLogic_bus_rsp_ccToggle_io_output_valid;
  assign logic_jtagLogic_dmiRsp_payload_error = logic_systemLogic_bus_rsp_ccToggle_io_output_payload_error;
  assign logic_jtagLogic_dmiRsp_payload_data = logic_systemLogic_bus_rsp_ccToggle_io_output_payload_data;
  assign io_bus_cmd_valid = logic_systemLogic_bus_cmd_valid;
  assign logic_systemLogic_bus_cmd_ready = io_bus_cmd_ready;
  assign io_bus_cmd_payload_write = logic_systemLogic_bus_cmd_payload_write;
  assign io_bus_cmd_payload_data = logic_systemLogic_bus_cmd_payload_data;
  assign io_bus_cmd_payload_address = logic_systemLogic_bus_cmd_payload_address;
  assign logic_systemLogic_bus_rsp_valid = io_bus_rsp_valid;
  assign logic_systemLogic_bus_rsp_payload_error = io_bus_rsp_payload_error;
  assign logic_systemLogic_bus_rsp_payload_data = io_bus_rsp_payload_data;
  always @(posedge jtag_clk) begin
    if(io_instruction_reset) begin
      tap_instruction <= 6'h0;
    end
    if(io_instruction_enable) begin
      if(io_instruction_shift) begin
        tap_shiftBuffer <= ({io_instruction_tdi,tap_shiftBuffer} >>> 1'd1);
      end
      if(io_instruction_update) begin
        if(when_JtagTunnel_l30) begin
          tap_instruction <= tap_shiftBuffer[5:0];
        end
      end
    end
    io_instruction_tdi_delay_1 <= io_instruction_tdi;
    io_instruction_tdi_delay_2 <= io_instruction_tdi_delay_1;
    io_instruction_tdi_delay_3 <= io_instruction_tdi_delay_2;
    io_instruction_tdi_delay_4 <= io_instruction_tdi_delay_3;
    io_instruction_tdi_delay_5 <= io_instruction_tdi_delay_4;
    io_instruction_tdi_delay_6 <= io_instruction_tdi_delay_5;
    io_instruction_tdi_delay_7 <= io_instruction_tdi_delay_6;
    io_instruction_tdi_delay_8 <= io_instruction_tdi_delay_7;
    tap_tdiBuffer <= io_instruction_tdi_delay_8;
    tap_tdoBuffer_delay_1 <= tap_tdoBuffer;
    tap_tdoBuffer_delay_2 <= tap_tdoBuffer_delay_1;
    tap_tdoBuffer_delay_3 <= tap_tdoBuffer_delay_2;
    tap_tdoShifter <= tap_tdoBuffer_delay_3;
    if(logic_jtagLogic_dtmcs_logic_ctrl_enable) begin
      if(logic_jtagLogic_dtmcs_logic_ctrl_capture) begin
        logic_jtagLogic_dtmcs_logic_store <= logic_jtagLogic_dtmcs_captureData;
      end
      if(logic_jtagLogic_dtmcs_logic_ctrl_shift) begin
        logic_jtagLogic_dtmcs_logic_store <= ({logic_jtagLogic_dtmcs_logic_ctrl_tdi,logic_jtagLogic_dtmcs_logic_store} >>> 1'd1);
      end
    end
    if(logic_jtagLogic_dmi_logic_ctrl_enable) begin
      if(logic_jtagLogic_dmi_logic_ctrl_capture) begin
        logic_jtagLogic_dmi_logic_store <= {logic_jtagLogic_dmi_captureData_padding,{logic_jtagLogic_dmi_captureData_data,logic_jtagLogic_dmi_captureData_op}};
      end
      if(logic_jtagLogic_dmi_logic_ctrl_shift) begin
        logic_jtagLogic_dmi_logic_store <= ({logic_jtagLogic_dmi_logic_ctrl_tdi,logic_jtagLogic_dmi_logic_store} >>> 1'd1);
      end
    end
    if(logic_jtagLogic_dmiCmd_valid) begin
      logic_jtagLogic_pending <= 1'b1;
    end
    if(logic_jtagLogic_dmiRsp_valid) begin
      logic_jtagLogic_pending <= 1'b0;
    end
    if(logic_jtagLogic_trigger_dmiHardReset) begin
      logic_jtagLogic_pending <= 1'b0;
    end
    if(logic_jtagLogic_dmiRsp_valid) begin
      logic_jtagLogic_rspLogic_buffer <= logic_jtagLogic_dmiRsp_payload_data;
    end
    logic_jtagLogic_dmiStat_value <= logic_jtagLogic_dmiStat_value_aheadValue;
  end

  always @(posedge clk) begin
    if(debugReset) begin
      logic_jtagLogic_dmiCmd_ccToggle_io_output_toStream_rValid <= 1'b0;
    end else begin
      if(logic_jtagLogic_dmiCmd_ccToggle_io_output_toStream_ready) begin
        logic_jtagLogic_dmiCmd_ccToggle_io_output_toStream_rValid <= logic_jtagLogic_dmiCmd_ccToggle_io_output_toStream_valid;
      end
    end
  end

  always @(posedge clk) begin
    if(logic_jtagLogic_dmiCmd_ccToggle_io_output_toStream_fire) begin
      logic_jtagLogic_dmiCmd_ccToggle_io_output_toStream_rData_write <= logic_jtagLogic_dmiCmd_ccToggle_io_output_toStream_payload_write;
      logic_jtagLogic_dmiCmd_ccToggle_io_output_toStream_rData_data <= logic_jtagLogic_dmiCmd_ccToggle_io_output_toStream_payload_data;
      logic_jtagLogic_dmiCmd_ccToggle_io_output_toStream_rData_address <= logic_jtagLogic_dmiCmd_ccToggle_io_output_toStream_payload_address;
    end
  end


endmodule

module DebugModule (
  input  wire          io_ctrl_cmd_valid,
  output wire          io_ctrl_cmd_ready,
  input  wire          io_ctrl_cmd_payload_write,
  input  wire [31:0]   io_ctrl_cmd_payload_data,
  input  wire [6:0]    io_ctrl_cmd_payload_address,
  output wire          io_ctrl_rsp_valid,
  output wire          io_ctrl_rsp_payload_error,
  output wire [31:0]   io_ctrl_rsp_payload_data,
  output wire          io_ndmreset,
  input  wire          io_harts_0_halted,
  input  wire          io_harts_0_running,
  input  wire          io_harts_0_unavailable,
  input  wire          io_harts_0_exception,
  input  wire          io_harts_0_commit,
  input  wire          io_harts_0_ebreak,
  input  wire          io_harts_0_redo,
  input  wire          io_harts_0_regSuccess,
  output wire          io_harts_0_ackReset,
  input  wire          io_harts_0_haveReset,
  output reg           io_harts_0_resume_cmd_valid,
  input  wire          io_harts_0_resume_rsp_valid,
  output wire          io_harts_0_haltReq,
  output wire          io_harts_0_dmToHart_valid,
  output wire [1:0]    io_harts_0_dmToHart_payload_op,
  output wire [4:0]    io_harts_0_dmToHart_payload_address,
  output wire [31:0]   io_harts_0_dmToHart_payload_data,
  output wire [2:0]    io_harts_0_dmToHart_payload_size,
  input  wire          io_harts_0_hartToDm_valid,
  input  wire [3:0]    io_harts_0_hartToDm_payload_address,
  input  wire [31:0]   io_harts_0_hartToDm_payload_data,
  input  wire          clk,
  input  wire          debugReset
);
  localparam DebugDmToHartOp_DATA = 2'd0;
  localparam DebugDmToHartOp_EXECUTE = 2'd1;
  localparam DebugDmToHartOp_REG_WRITE = 2'd2;
  localparam DebugDmToHartOp_REG_READ = 2'd3;
  localparam DebugModuleCmdErr_NONE = 3'd0;
  localparam DebugModuleCmdErr_BUSY = 3'd1;
  localparam DebugModuleCmdErr_NOT_SUPPORTED = 3'd2;
  localparam DebugModuleCmdErr_EXCEPTION = 3'd3;
  localparam DebugModuleCmdErr_HALT_RESUME = 3'd4;
  localparam DebugModuleCmdErr_BUS_1 = 3'd5;
  localparam DebugModuleCmdErr_OTHER = 3'd6;
  localparam logic_command_BOOT = 3'd0;
  localparam logic_command_IDLE = 3'd1;
  localparam logic_command_DECODE = 3'd2;
  localparam logic_command_READ_INT_REG = 3'd3;
  localparam logic_command_WRITE_INT_REG = 3'd4;
  localparam logic_command_WAIT_DONE = 3'd5;
  localparam logic_command_POST_EXEC = 3'd6;
  localparam logic_command_POST_EXEC_WAIT = 3'd7;

  wire       [31:0]   logic_progbufX_mem_spinal_port1;
  wire       [0:0]    _zz_logic_dmcontrol_haltSet;
  wire       [0:0]    _zz_logic_dmcontrol_haltClear;
  wire       [0:0]    _zz_logic_dmcontrol_resumeReq;
  wire       [0:0]    _zz_logic_dmcontrol_ackhavereset;
  wire       [14:0]   _zz_when_DebugModule_l167;
  wire       [0:0]    _zz_logic_progbufX_mem_port;
  wire       [0:0]    _zz_logic_abstractAuto_trigger;
  wire       [2:0]    _zz_logic_command_access_notSupported;
  wire       [1:0]    _zz_logic_command_access_notSupported_1;
  wire       [31:0]   _zz_logic_toHarts_payload_data;
  wire       [19:0]   _zz_logic_toHarts_payload_data_1;
  wire       [31:0]   _zz_logic_toHarts_payload_data_2;
  wire       [11:0]   _zz_logic_toHarts_payload_data_3;
  reg                 _zz_1;
  wire                factory_readErrorFlag;
  wire                factory_writeErrorFlag;
  wire                factory_cmdToRsp_valid;
  reg                 factory_cmdToRsp_payload_error;
  reg        [31:0]   factory_cmdToRsp_payload_data;
  reg                 factory_rspBuffer_valid;
  reg                 factory_rspBuffer_payload_error;
  reg        [31:0]   factory_rspBuffer_payload_data;
  wire                factory_askWrite;
  wire                factory_askRead;
  wire                factory_doWrite;
  wire                factory_doRead;
  wire                io_ctrl_cmd_fire;
  reg                 dmactive;
  reg                 logic_dmcontrol_ndmreset;
  wire       [9:0]    logic_dmcontrol_hartSelLoNew;
  wire       [9:0]    logic_dmcontrol_hartSelHiNew;
  wire       [19:0]   logic_dmcontrol_hartSelNew;
  reg        [9:0]    logic_dmcontrol_hartSelLo;
  reg        [9:0]    logic_dmcontrol_hartSelHi;
  wire       [19:0]   logic_dmcontrol_hartSel;
  reg                 logic_dmcontrol_haltSet;
  reg                 when_BusSlaveFactory_l377;
  wire                when_BusSlaveFactory_l379;
  reg                 logic_dmcontrol_haltClear;
  reg                 when_BusSlaveFactory_l406;
  wire                when_BusSlaveFactory_l408;
  reg                 logic_dmcontrol_resumeReq;
  reg                 when_BusSlaveFactory_l377_1;
  wire                when_BusSlaveFactory_l379_1;
  reg                 logic_dmcontrol_ackhavereset;
  reg                 when_BusSlaveFactory_l377_2;
  wire                when_BusSlaveFactory_l379_2;
  wire       [1:0]    logic_dmcontrol_hartSelAarsizeLimit;
  reg                 logic_dmcontrol_harts_0_haltReq;
  wire                when_DebugModule_l126;
  reg                 logic_toHarts_valid;
  reg        [1:0]    logic_toHarts_payload_op;
  reg        [4:0]    logic_toHarts_payload_address;
  reg        [31:0]   logic_toHarts_payload_data;
  reg        [2:0]    logic_toHarts_payload_size;
  wire                logic_fromHarts_valid;
  wire       [3:0]    logic_fromHarts_payload_address;
  wire       [31:0]   logic_fromHarts_payload_data;
  wire                logic_harts_0_sel;
  reg                 _zz_logic_harts_0_resumeReady;
  reg                 _zz_logic_harts_0_resumeReady_1;
  wire                logic_harts_0_resumeReady;
  wire                logic_toHarts_takeWhen_valid;
  wire       [1:0]    logic_toHarts_takeWhen_payload_op;
  wire       [4:0]    logic_toHarts_takeWhen_payload_address;
  wire       [31:0]   logic_toHarts_takeWhen_payload_data;
  wire       [2:0]    logic_toHarts_takeWhen_payload_size;
  reg                 _zz_io_harts_0_ackReset;
  wire                logic_selected_running;
  wire                logic_selected_halted;
  wire                logic_selected_commit;
  wire                logic_selected_regSuccess;
  wire                logic_selected_exception;
  wire                logic_selected_ebreak;
  wire                logic_selected_redo;
  reg        [31:0]   logic_haltsum_value;
  wire                when_DebugModule_l167;
  wire       [3:0]    logic_dmstatus_version;
  wire                logic_dmstatus_authenticated;
  wire                logic_dmstatus_anyHalted;
  wire                logic_dmstatus_allHalted;
  wire                logic_dmstatus_anyRunning;
  wire                logic_dmstatus_allRunning;
  wire                logic_dmstatus_anyUnavail;
  wire                logic_dmstatus_allUnavail;
  wire                logic_dmstatus_anyNonExistent;
  wire                logic_dmstatus_anyResumeAck;
  wire                logic_dmstatus_allResumeAck;
  wire                logic_dmstatus_anyHaveReset;
  wire                logic_dmstatus_allHaveReset;
  wire                logic_dmstatus_impebreak;
  wire       [3:0]    logic_hartInfo_dataaddr;
  wire       [3:0]    logic_hartInfo_datasize;
  wire                logic_hartInfo_dataaccess;
  wire       [3:0]    logic_hartInfo_nscratch;
  wire                logic_progbufX_trigged;
  reg                 logic_dataX_trigged;
  wire                when_DebugModule_l336;
  wire       [3:0]    logic_abstractcs_dataCount;
  reg        [2:0]    logic_abstractcs_cmdErr;
  reg                 when_BusSlaveFactory_l341;
  wire       [2:0]    _zz_logic_abstractcs_cmdErr;
  reg                 logic_abstractcs_busy;
  wire       [4:0]    logic_abstractcs_progBufSize;
  wire                logic_abstractcs_noError;
  reg        [0:0]    logic_abstractAuto_autoexecdata;
  reg        [1:0]    logic_abstractAuto_autoexecProgbuf;
  wire                logic_abstractAuto_trigger;
  wire                logic_command_wantExit;
  reg                 logic_command_wantStart;
  wire                logic_command_wantKill;
  reg        [0:0]    logic_command_executionCounter;
  reg                 logic_command_commandRequest;
  reg        [31:0]   logic_command_data;
  wire       [15:0]   logic_command_access_args_regno;
  wire                logic_command_access_args_write;
  wire                logic_command_access_args_transfer;
  wire                logic_command_access_args_postExec;
  wire                logic_command_access_args_aarpostincrement;
  wire       [2:0]    logic_command_access_args_aarsize;
  wire       [31:0]   _zz_logic_command_access_args_regno;
  wire                logic_command_access_transferFloat;
  wire                logic_command_access_notSupported;
  wire                logic_command_request;
  wire                when_DebugModule_l391;
  wire                when_DebugModule_l394;
  wire                when_DebugModule_l397;
  reg        [2:0]    logic_command_stateReg;
  reg        [2:0]    logic_command_stateNext;
  wire                when_DebugModule_l406;
  wire                when_DebugModule_l407;
  wire       [7:0]    switch_DebugModule_l418;
  wire                when_DebugModule_l427;
  wire                when_DebugModule_l481;
  wire                when_DebugModule_l497;
  wire                when_DebugModule_l501;
  wire                logic_command_onExit_BOOT;
  wire                logic_command_onExit_IDLE;
  wire                logic_command_onExit_DECODE;
  wire                logic_command_onExit_READ_INT_REG;
  wire                logic_command_onExit_WRITE_INT_REG;
  wire                logic_command_onExit_WAIT_DONE;
  wire                logic_command_onExit_POST_EXEC;
  wire                logic_command_onExit_POST_EXEC_WAIT;
  wire                logic_command_onEntry_BOOT;
  wire                logic_command_onEntry_IDLE;
  wire                logic_command_onEntry_DECODE;
  wire                logic_command_onEntry_READ_INT_REG;
  wire                logic_command_onEntry_WRITE_INT_REG;
  wire                logic_command_onEntry_WAIT_DONE;
  wire                logic_command_onEntry_POST_EXEC;
  wire                logic_command_onEntry_POST_EXEC_WAIT;
  wire       [31:0]   _zz_factory_cmdToRsp_payload_data;
  reg        [31:0]   _zz_factory_cmdToRsp_payload_data_1;
  `ifndef SYNTHESIS
  reg [71:0] io_harts_0_dmToHart_payload_op_string;
  reg [71:0] logic_toHarts_payload_op_string;
  reg [71:0] logic_toHarts_takeWhen_payload_op_string;
  reg [103:0] logic_abstractcs_cmdErr_string;
  reg [103:0] _zz_logic_abstractcs_cmdErr_string;
  reg [111:0] logic_command_stateReg_string;
  reg [111:0] logic_command_stateNext_string;
  `endif

  (* ram_style = "distributed" *) reg [31:0] logic_progbufX_mem [0:1];

  assign _zz_logic_dmcontrol_haltSet = 1'b1;
  assign _zz_logic_dmcontrol_haltClear = 1'b1;
  assign _zz_logic_dmcontrol_resumeReq = 1'b1;
  assign _zz_logic_dmcontrol_ackhavereset = 1'b1;
  assign _zz_when_DebugModule_l167 = (logic_dmcontrol_hartSel >>> 3'd5);
  assign _zz_logic_progbufX_mem_port = io_ctrl_cmd_payload_address[0:0];
  assign _zz_logic_abstractAuto_trigger = io_ctrl_cmd_payload_address[0:0];
  assign _zz_logic_command_access_notSupported_1 = (logic_command_access_transferFloat ? 2'b00 : logic_dmcontrol_hartSelAarsizeLimit);
  assign _zz_logic_command_access_notSupported = {1'd0, _zz_logic_command_access_notSupported_1};
  assign _zz_logic_toHarts_payload_data_1 = ({15'd0,logic_command_access_args_regno[4 : 0]} <<< 4'd15);
  assign _zz_logic_toHarts_payload_data = {12'd0, _zz_logic_toHarts_payload_data_1};
  assign _zz_logic_toHarts_payload_data_3 = ({7'd0,logic_command_access_args_regno[4 : 0]} <<< 3'd7);
  assign _zz_logic_toHarts_payload_data_2 = {20'd0, _zz_logic_toHarts_payload_data_3};
  always @(posedge clk) begin
    if(_zz_1) begin
      logic_progbufX_mem[_zz_logic_progbufX_mem_port] <= io_ctrl_cmd_payload_data;
    end
  end

  assign logic_progbufX_mem_spinal_port1 = logic_progbufX_mem[logic_command_executionCounter];
  `ifndef SYNTHESIS
  always @(*) begin
    case(io_harts_0_dmToHart_payload_op)
      DebugDmToHartOp_DATA : io_harts_0_dmToHart_payload_op_string = "DATA     ";
      DebugDmToHartOp_EXECUTE : io_harts_0_dmToHart_payload_op_string = "EXECUTE  ";
      DebugDmToHartOp_REG_WRITE : io_harts_0_dmToHart_payload_op_string = "REG_WRITE";
      DebugDmToHartOp_REG_READ : io_harts_0_dmToHart_payload_op_string = "REG_READ ";
      default : io_harts_0_dmToHart_payload_op_string = "?????????";
    endcase
  end
  always @(*) begin
    case(logic_toHarts_payload_op)
      DebugDmToHartOp_DATA : logic_toHarts_payload_op_string = "DATA     ";
      DebugDmToHartOp_EXECUTE : logic_toHarts_payload_op_string = "EXECUTE  ";
      DebugDmToHartOp_REG_WRITE : logic_toHarts_payload_op_string = "REG_WRITE";
      DebugDmToHartOp_REG_READ : logic_toHarts_payload_op_string = "REG_READ ";
      default : logic_toHarts_payload_op_string = "?????????";
    endcase
  end
  always @(*) begin
    case(logic_toHarts_takeWhen_payload_op)
      DebugDmToHartOp_DATA : logic_toHarts_takeWhen_payload_op_string = "DATA     ";
      DebugDmToHartOp_EXECUTE : logic_toHarts_takeWhen_payload_op_string = "EXECUTE  ";
      DebugDmToHartOp_REG_WRITE : logic_toHarts_takeWhen_payload_op_string = "REG_WRITE";
      DebugDmToHartOp_REG_READ : logic_toHarts_takeWhen_payload_op_string = "REG_READ ";
      default : logic_toHarts_takeWhen_payload_op_string = "?????????";
    endcase
  end
  always @(*) begin
    case(logic_abstractcs_cmdErr)
      DebugModuleCmdErr_NONE : logic_abstractcs_cmdErr_string = "NONE         ";
      DebugModuleCmdErr_BUSY : logic_abstractcs_cmdErr_string = "BUSY         ";
      DebugModuleCmdErr_NOT_SUPPORTED : logic_abstractcs_cmdErr_string = "NOT_SUPPORTED";
      DebugModuleCmdErr_EXCEPTION : logic_abstractcs_cmdErr_string = "EXCEPTION    ";
      DebugModuleCmdErr_HALT_RESUME : logic_abstractcs_cmdErr_string = "HALT_RESUME  ";
      DebugModuleCmdErr_BUS_1 : logic_abstractcs_cmdErr_string = "BUS_1        ";
      DebugModuleCmdErr_OTHER : logic_abstractcs_cmdErr_string = "OTHER        ";
      default : logic_abstractcs_cmdErr_string = "?????????????";
    endcase
  end
  always @(*) begin
    case(_zz_logic_abstractcs_cmdErr)
      DebugModuleCmdErr_NONE : _zz_logic_abstractcs_cmdErr_string = "NONE         ";
      DebugModuleCmdErr_BUSY : _zz_logic_abstractcs_cmdErr_string = "BUSY         ";
      DebugModuleCmdErr_NOT_SUPPORTED : _zz_logic_abstractcs_cmdErr_string = "NOT_SUPPORTED";
      DebugModuleCmdErr_EXCEPTION : _zz_logic_abstractcs_cmdErr_string = "EXCEPTION    ";
      DebugModuleCmdErr_HALT_RESUME : _zz_logic_abstractcs_cmdErr_string = "HALT_RESUME  ";
      DebugModuleCmdErr_BUS_1 : _zz_logic_abstractcs_cmdErr_string = "BUS_1        ";
      DebugModuleCmdErr_OTHER : _zz_logic_abstractcs_cmdErr_string = "OTHER        ";
      default : _zz_logic_abstractcs_cmdErr_string = "?????????????";
    endcase
  end
  always @(*) begin
    case(logic_command_stateReg)
      logic_command_BOOT : logic_command_stateReg_string = "BOOT          ";
      logic_command_IDLE : logic_command_stateReg_string = "IDLE          ";
      logic_command_DECODE : logic_command_stateReg_string = "DECODE        ";
      logic_command_READ_INT_REG : logic_command_stateReg_string = "READ_INT_REG  ";
      logic_command_WRITE_INT_REG : logic_command_stateReg_string = "WRITE_INT_REG ";
      logic_command_WAIT_DONE : logic_command_stateReg_string = "WAIT_DONE     ";
      logic_command_POST_EXEC : logic_command_stateReg_string = "POST_EXEC     ";
      logic_command_POST_EXEC_WAIT : logic_command_stateReg_string = "POST_EXEC_WAIT";
      default : logic_command_stateReg_string = "??????????????";
    endcase
  end
  always @(*) begin
    case(logic_command_stateNext)
      logic_command_BOOT : logic_command_stateNext_string = "BOOT          ";
      logic_command_IDLE : logic_command_stateNext_string = "IDLE          ";
      logic_command_DECODE : logic_command_stateNext_string = "DECODE        ";
      logic_command_READ_INT_REG : logic_command_stateNext_string = "READ_INT_REG  ";
      logic_command_WRITE_INT_REG : logic_command_stateNext_string = "WRITE_INT_REG ";
      logic_command_WAIT_DONE : logic_command_stateNext_string = "WAIT_DONE     ";
      logic_command_POST_EXEC : logic_command_stateNext_string = "POST_EXEC     ";
      logic_command_POST_EXEC_WAIT : logic_command_stateNext_string = "POST_EXEC_WAIT";
      default : logic_command_stateNext_string = "??????????????";
    endcase
  end
  `endif

  always @(*) begin
    _zz_1 = 1'b0;
    if(logic_progbufX_trigged) begin
      _zz_1 = 1'b1;
    end
  end

  assign factory_readErrorFlag = 1'b0;
  assign factory_writeErrorFlag = 1'b0;
  assign io_ctrl_cmd_ready = 1'b1;
  assign factory_askWrite = (io_ctrl_cmd_valid && io_ctrl_cmd_payload_write);
  assign factory_askRead = (io_ctrl_cmd_valid && (! io_ctrl_cmd_payload_write));
  assign factory_doWrite = (factory_askWrite && io_ctrl_cmd_ready);
  assign factory_doRead = (factory_askRead && io_ctrl_cmd_ready);
  assign io_ctrl_rsp_valid = factory_rspBuffer_valid;
  assign io_ctrl_rsp_payload_error = factory_rspBuffer_payload_error;
  assign io_ctrl_rsp_payload_data = factory_rspBuffer_payload_data;
  assign io_ctrl_cmd_fire = (io_ctrl_cmd_valid && io_ctrl_cmd_ready);
  assign factory_cmdToRsp_valid = io_ctrl_cmd_fire;
  always @(*) begin
    factory_cmdToRsp_payload_error = 1'b0;
    if(logic_progbufX_trigged) begin
      factory_cmdToRsp_payload_error = 1'b0;
    end
    if(when_DebugModule_l336) begin
      factory_cmdToRsp_payload_error = 1'b0;
    end
    case(io_ctrl_cmd_payload_address)
      7'h10 : begin
        factory_cmdToRsp_payload_error = 1'b0;
      end
      7'h40 : begin
        factory_cmdToRsp_payload_error = 1'b0;
      end
      7'h11 : begin
        factory_cmdToRsp_payload_error = 1'b0;
      end
      7'h12 : begin
        factory_cmdToRsp_payload_error = 1'b0;
      end
      7'h16 : begin
        factory_cmdToRsp_payload_error = 1'b0;
      end
      7'h18 : begin
        factory_cmdToRsp_payload_error = 1'b0;
      end
      7'h17 : begin
        factory_cmdToRsp_payload_error = 1'b0;
      end
      default : begin
      end
    endcase
  end

  always @(*) begin
    factory_cmdToRsp_payload_data = 32'h0;
    if(when_DebugModule_l336) begin
      factory_cmdToRsp_payload_data = _zz_factory_cmdToRsp_payload_data;
    end
    case(io_ctrl_cmd_payload_address)
      7'h10 : begin
        factory_cmdToRsp_payload_data[0 : 0] = dmactive;
        factory_cmdToRsp_payload_data[1 : 1] = logic_dmcontrol_ndmreset;
        factory_cmdToRsp_payload_data[25 : 16] = logic_dmcontrol_hartSelLo;
        factory_cmdToRsp_payload_data[15 : 6] = logic_dmcontrol_hartSelHi;
      end
      7'h40 : begin
        factory_cmdToRsp_payload_data[31 : 0] = logic_haltsum_value;
      end
      7'h11 : begin
        factory_cmdToRsp_payload_data[3 : 0] = logic_dmstatus_version;
        factory_cmdToRsp_payload_data[7 : 7] = logic_dmstatus_authenticated;
        factory_cmdToRsp_payload_data[8 : 8] = logic_dmstatus_anyHalted;
        factory_cmdToRsp_payload_data[9 : 9] = logic_dmstatus_allHalted;
        factory_cmdToRsp_payload_data[10 : 10] = logic_dmstatus_anyRunning;
        factory_cmdToRsp_payload_data[11 : 11] = logic_dmstatus_allRunning;
        factory_cmdToRsp_payload_data[12 : 12] = logic_dmstatus_anyUnavail;
        factory_cmdToRsp_payload_data[13 : 13] = logic_dmstatus_allUnavail;
        factory_cmdToRsp_payload_data[14 : 14] = logic_dmstatus_anyNonExistent;
        factory_cmdToRsp_payload_data[15 : 15] = logic_dmstatus_anyNonExistent;
        factory_cmdToRsp_payload_data[16 : 16] = logic_dmstatus_anyResumeAck;
        factory_cmdToRsp_payload_data[17 : 17] = logic_dmstatus_allResumeAck;
        factory_cmdToRsp_payload_data[18 : 18] = logic_dmstatus_anyHaveReset;
        factory_cmdToRsp_payload_data[19 : 19] = logic_dmstatus_allHaveReset;
        factory_cmdToRsp_payload_data[22 : 22] = logic_dmstatus_impebreak;
      end
      7'h12 : begin
        factory_cmdToRsp_payload_data[3 : 0] = logic_hartInfo_dataaddr;
        factory_cmdToRsp_payload_data[15 : 12] = logic_hartInfo_datasize;
        factory_cmdToRsp_payload_data[16 : 16] = logic_hartInfo_dataaccess;
        factory_cmdToRsp_payload_data[23 : 20] = logic_hartInfo_nscratch;
      end
      7'h16 : begin
        factory_cmdToRsp_payload_data[3 : 0] = logic_abstractcs_dataCount;
        factory_cmdToRsp_payload_data[10 : 8] = logic_abstractcs_cmdErr;
        factory_cmdToRsp_payload_data[12 : 12] = logic_abstractcs_busy;
        factory_cmdToRsp_payload_data[28 : 24] = logic_abstractcs_progBufSize;
      end
      7'h18 : begin
        factory_cmdToRsp_payload_data[0 : 0] = logic_abstractAuto_autoexecdata;
        factory_cmdToRsp_payload_data[17 : 16] = logic_abstractAuto_autoexecProgbuf;
      end
      default : begin
      end
    endcase
  end

  assign logic_dmcontrol_hartSelNew = {logic_dmcontrol_hartSelHiNew,logic_dmcontrol_hartSelLoNew};
  assign logic_dmcontrol_hartSel = {logic_dmcontrol_hartSelHi,logic_dmcontrol_hartSelLo};
  always @(*) begin
    logic_dmcontrol_haltSet = 1'b0;
    if(when_BusSlaveFactory_l377) begin
      if(when_BusSlaveFactory_l379) begin
        logic_dmcontrol_haltSet = _zz_logic_dmcontrol_haltSet[0];
      end
    end
  end

  always @(*) begin
    when_BusSlaveFactory_l377 = 1'b0;
    case(io_ctrl_cmd_payload_address)
      7'h10 : begin
        if(factory_doWrite) begin
          when_BusSlaveFactory_l377 = 1'b1;
        end
      end
      default : begin
      end
    endcase
  end

  assign when_BusSlaveFactory_l379 = io_ctrl_cmd_payload_data[31];
  always @(*) begin
    logic_dmcontrol_haltClear = 1'b0;
    if(when_BusSlaveFactory_l406) begin
      if(when_BusSlaveFactory_l408) begin
        logic_dmcontrol_haltClear = _zz_logic_dmcontrol_haltClear[0];
      end
    end
  end

  always @(*) begin
    when_BusSlaveFactory_l406 = 1'b0;
    case(io_ctrl_cmd_payload_address)
      7'h10 : begin
        if(factory_doWrite) begin
          when_BusSlaveFactory_l406 = 1'b1;
        end
      end
      default : begin
      end
    endcase
  end

  assign when_BusSlaveFactory_l408 = (! io_ctrl_cmd_payload_data[31]);
  always @(*) begin
    logic_dmcontrol_resumeReq = 1'b0;
    if(when_BusSlaveFactory_l377_1) begin
      if(when_BusSlaveFactory_l379_1) begin
        logic_dmcontrol_resumeReq = _zz_logic_dmcontrol_resumeReq[0];
      end
    end
    if(logic_dmcontrol_haltSet) begin
      logic_dmcontrol_resumeReq = 1'b0;
    end
  end

  always @(*) begin
    when_BusSlaveFactory_l377_1 = 1'b0;
    case(io_ctrl_cmd_payload_address)
      7'h10 : begin
        if(factory_doWrite) begin
          when_BusSlaveFactory_l377_1 = 1'b1;
        end
      end
      default : begin
      end
    endcase
  end

  assign when_BusSlaveFactory_l379_1 = io_ctrl_cmd_payload_data[30];
  always @(*) begin
    logic_dmcontrol_ackhavereset = 1'b0;
    if(when_BusSlaveFactory_l377_2) begin
      if(when_BusSlaveFactory_l379_2) begin
        logic_dmcontrol_ackhavereset = _zz_logic_dmcontrol_ackhavereset[0];
      end
    end
  end

  always @(*) begin
    when_BusSlaveFactory_l377_2 = 1'b0;
    case(io_ctrl_cmd_payload_address)
      7'h10 : begin
        if(factory_doWrite) begin
          when_BusSlaveFactory_l377_2 = 1'b1;
        end
      end
      default : begin
      end
    endcase
  end

  assign when_BusSlaveFactory_l379_2 = io_ctrl_cmd_payload_data[28];
  assign logic_dmcontrol_hartSelAarsizeLimit = 2'b10;
  assign io_harts_0_haltReq = logic_dmcontrol_harts_0_haltReq;
  always @(*) begin
    io_harts_0_resume_cmd_valid = 1'b0;
    if(when_DebugModule_l126) begin
      io_harts_0_resume_cmd_valid = logic_dmcontrol_resumeReq;
    end
  end

  assign when_DebugModule_l126 = (logic_dmcontrol_hartSelNew == 20'h0);
  assign io_ndmreset = logic_dmcontrol_ndmreset;
  always @(*) begin
    logic_toHarts_valid = 1'b0;
    if(when_DebugModule_l336) begin
      if(io_ctrl_cmd_payload_write) begin
        logic_toHarts_valid = 1'b1;
      end
    end
    if(logic_abstractcs_busy) begin
      logic_toHarts_valid = 1'b0;
    end
    case(logic_command_stateReg)
      logic_command_IDLE : begin
      end
      logic_command_DECODE : begin
      end
      logic_command_READ_INT_REG : begin
        logic_toHarts_valid = 1'b1;
      end
      logic_command_WRITE_INT_REG : begin
        logic_toHarts_valid = 1'b1;
      end
      logic_command_WAIT_DONE : begin
      end
      logic_command_POST_EXEC : begin
        logic_toHarts_valid = 1'b1;
      end
      logic_command_POST_EXEC_WAIT : begin
      end
      default : begin
      end
    endcase
  end

  always @(*) begin
    logic_toHarts_payload_op = (2'bxx);
    if(when_DebugModule_l336) begin
      logic_toHarts_payload_op = DebugDmToHartOp_DATA;
    end
    case(logic_command_stateReg)
      logic_command_IDLE : begin
      end
      logic_command_DECODE : begin
      end
      logic_command_READ_INT_REG : begin
        logic_toHarts_payload_op = DebugDmToHartOp_EXECUTE;
      end
      logic_command_WRITE_INT_REG : begin
        logic_toHarts_payload_op = DebugDmToHartOp_EXECUTE;
      end
      logic_command_WAIT_DONE : begin
      end
      logic_command_POST_EXEC : begin
        logic_toHarts_payload_op = DebugDmToHartOp_EXECUTE;
      end
      logic_command_POST_EXEC_WAIT : begin
      end
      default : begin
      end
    endcase
  end

  always @(*) begin
    logic_toHarts_payload_address = 5'bxxxxx;
    if(when_DebugModule_l336) begin
      logic_toHarts_payload_address = 5'h0;
    end
  end

  always @(*) begin
    logic_toHarts_payload_data = 32'bxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx;
    if(when_DebugModule_l336) begin
      logic_toHarts_payload_data = io_ctrl_cmd_payload_data;
    end
    case(logic_command_stateReg)
      logic_command_IDLE : begin
      end
      logic_command_DECODE : begin
      end
      logic_command_READ_INT_REG : begin
        logic_toHarts_payload_data = (32'h7b401073 | _zz_logic_toHarts_payload_data);
      end
      logic_command_WRITE_INT_REG : begin
        logic_toHarts_payload_data = (32'h7b402073 | _zz_logic_toHarts_payload_data_2);
      end
      logic_command_WAIT_DONE : begin
      end
      logic_command_POST_EXEC : begin
        logic_toHarts_payload_data = logic_progbufX_mem_spinal_port1;
      end
      logic_command_POST_EXEC_WAIT : begin
      end
      default : begin
      end
    endcase
  end

  always @(*) begin
    logic_toHarts_payload_size = 3'bxxx;
    logic_toHarts_payload_size = logic_command_access_args_aarsize;
  end

  assign logic_fromHarts_valid = (|io_harts_0_hartToDm_valid);
  assign logic_fromHarts_payload_address = io_harts_0_hartToDm_payload_address;
  assign logic_fromHarts_payload_data = io_harts_0_hartToDm_payload_data;
  assign logic_harts_0_sel = (logic_dmcontrol_hartSel == 20'h0);
  assign logic_harts_0_resumeReady = ((! _zz_logic_harts_0_resumeReady) && _zz_logic_harts_0_resumeReady_1);
  assign logic_toHarts_takeWhen_valid = (logic_toHarts_valid && (! ((logic_toHarts_payload_op != DebugDmToHartOp_DATA) && (! logic_harts_0_sel))));
  assign logic_toHarts_takeWhen_payload_op = logic_toHarts_payload_op;
  assign logic_toHarts_takeWhen_payload_address = logic_toHarts_payload_address;
  assign logic_toHarts_takeWhen_payload_data = logic_toHarts_payload_data;
  assign logic_toHarts_takeWhen_payload_size = logic_toHarts_payload_size;
  assign io_harts_0_dmToHart_valid = logic_toHarts_takeWhen_valid;
  assign io_harts_0_dmToHart_payload_op = logic_toHarts_takeWhen_payload_op;
  assign io_harts_0_dmToHart_payload_address = logic_toHarts_takeWhen_payload_address;
  assign io_harts_0_dmToHart_payload_data = logic_toHarts_takeWhen_payload_data;
  assign io_harts_0_dmToHart_payload_size = logic_toHarts_takeWhen_payload_size;
  assign io_harts_0_ackReset = _zz_io_harts_0_ackReset;
  assign logic_selected_running = io_harts_0_running;
  assign logic_selected_halted = io_harts_0_halted;
  assign logic_selected_commit = io_harts_0_commit;
  assign logic_selected_regSuccess = io_harts_0_regSuccess;
  assign logic_selected_exception = io_harts_0_exception;
  assign logic_selected_ebreak = io_harts_0_ebreak;
  assign logic_selected_redo = io_harts_0_redo;
  always @(*) begin
    logic_haltsum_value = 32'h0;
    if(when_DebugModule_l167) begin
      logic_haltsum_value[0] = io_harts_0_halted;
    end
  end

  assign when_DebugModule_l167 = (_zz_when_DebugModule_l167 == 15'h0);
  assign logic_dmstatus_version = 4'b0010;
  assign logic_dmstatus_authenticated = 1'b1;
  assign logic_dmstatus_anyHalted = (|(logic_harts_0_sel && io_harts_0_halted));
  assign logic_dmstatus_allHalted = (&((! logic_harts_0_sel) || io_harts_0_halted));
  assign logic_dmstatus_anyRunning = (|(logic_harts_0_sel && io_harts_0_running));
  assign logic_dmstatus_allRunning = (&((! logic_harts_0_sel) || io_harts_0_running));
  assign logic_dmstatus_anyUnavail = (|(logic_harts_0_sel && io_harts_0_unavailable));
  assign logic_dmstatus_allUnavail = (&((! logic_harts_0_sel) || io_harts_0_unavailable));
  assign logic_dmstatus_anyNonExistent = (20'h00001 <= logic_dmcontrol_hartSel);
  assign logic_dmstatus_anyResumeAck = (|(logic_harts_0_sel && logic_harts_0_resumeReady));
  assign logic_dmstatus_allResumeAck = (&((! logic_harts_0_sel) || logic_harts_0_resumeReady));
  assign logic_dmstatus_anyHaveReset = (|(logic_harts_0_sel && io_harts_0_haveReset));
  assign logic_dmstatus_allHaveReset = (&((! logic_harts_0_sel) || io_harts_0_haveReset));
  assign logic_dmstatus_impebreak = 1'b1;
  assign logic_hartInfo_dataaddr = 4'b0000;
  assign logic_hartInfo_datasize = 4'b0000;
  assign logic_hartInfo_dataaccess = 1'b0;
  assign logic_hartInfo_nscratch = 4'b0000;
  assign logic_progbufX_trigged = ((io_ctrl_cmd_valid && io_ctrl_cmd_payload_write) && ((io_ctrl_cmd_payload_address & 7'h70) == 7'h20));
  always @(*) begin
    logic_dataX_trigged = 1'b0;
    if(when_DebugModule_l336) begin
      logic_dataX_trigged = 1'b1;
    end
  end

  assign when_DebugModule_l336 = ((io_ctrl_cmd_valid && (7'h04 <= io_ctrl_cmd_payload_address)) && (io_ctrl_cmd_payload_address < 7'h05));
  assign logic_abstractcs_dataCount = 4'b0001;
  always @(*) begin
    when_BusSlaveFactory_l341 = 1'b0;
    case(io_ctrl_cmd_payload_address)
      7'h16 : begin
        if(factory_doWrite) begin
          when_BusSlaveFactory_l341 = 1'b1;
        end
      end
      default : begin
      end
    endcase
  end

  assign _zz_logic_abstractcs_cmdErr = (logic_abstractcs_cmdErr & (~ io_ctrl_cmd_payload_data[10 : 8]));
  assign logic_abstractcs_progBufSize = 5'h02;
  assign logic_abstractcs_noError = (logic_abstractcs_cmdErr == DebugModuleCmdErr_NONE);
  assign logic_abstractAuto_trigger = ((logic_progbufX_trigged && logic_abstractAuto_autoexecProgbuf[_zz_logic_abstractAuto_trigger]) || (logic_dataX_trigged && logic_abstractAuto_autoexecdata[0]));
  assign logic_command_wantExit = 1'b0;
  always @(*) begin
    logic_command_wantStart = 1'b0;
    case(logic_command_stateReg)
      logic_command_IDLE : begin
      end
      logic_command_DECODE : begin
      end
      logic_command_READ_INT_REG : begin
      end
      logic_command_WRITE_INT_REG : begin
      end
      logic_command_WAIT_DONE : begin
      end
      logic_command_POST_EXEC : begin
      end
      logic_command_POST_EXEC_WAIT : begin
      end
      default : begin
        logic_command_wantStart = 1'b1;
      end
    endcase
  end

  assign logic_command_wantKill = 1'b0;
  always @(*) begin
    logic_command_commandRequest = 1'b0;
    case(io_ctrl_cmd_payload_address)
      7'h17 : begin
        if(factory_doWrite) begin
          logic_command_commandRequest = 1'b1;
        end
      end
      default : begin
      end
    endcase
  end

  assign _zz_logic_command_access_args_regno = logic_command_data;
  assign logic_command_access_args_regno = _zz_logic_command_access_args_regno[15 : 0];
  assign logic_command_access_args_write = _zz_logic_command_access_args_regno[16];
  assign logic_command_access_args_transfer = _zz_logic_command_access_args_regno[17];
  assign logic_command_access_args_postExec = _zz_logic_command_access_args_regno[18];
  assign logic_command_access_args_aarpostincrement = _zz_logic_command_access_args_regno[19];
  assign logic_command_access_args_aarsize = _zz_logic_command_access_args_regno[22 : 20];
  assign logic_command_access_transferFloat = logic_command_access_args_regno[5];
  assign logic_command_access_notSupported = (((_zz_logic_command_access_notSupported < logic_command_access_args_aarsize) || logic_command_access_args_aarpostincrement) || (logic_command_access_args_transfer && (logic_command_access_args_regno[15 : 5] != 11'h080)));
  assign logic_command_request = (logic_command_commandRequest || logic_abstractAuto_trigger);
  assign when_DebugModule_l391 = ((logic_command_request && logic_abstractcs_busy) && logic_abstractcs_noError);
  assign when_DebugModule_l394 = (|io_harts_0_exception);
  assign when_DebugModule_l397 = ((logic_abstractcs_busy && (logic_progbufX_trigged || logic_dataX_trigged)) && logic_abstractcs_noError);
  assign logic_dmcontrol_hartSelLoNew = io_ctrl_cmd_payload_data[25 : 16];
  assign logic_dmcontrol_hartSelHiNew = io_ctrl_cmd_payload_data[15 : 6];
  always @(*) begin
    logic_command_stateNext = logic_command_stateReg;
    case(logic_command_stateReg)
      logic_command_IDLE : begin
        if(when_DebugModule_l406) begin
          if(!when_DebugModule_l407) begin
            logic_command_stateNext = logic_command_DECODE;
          end
        end
      end
      logic_command_DECODE : begin
        logic_command_stateNext = logic_command_IDLE;
        case(switch_DebugModule_l418)
          8'h0 : begin
            if(!logic_command_access_notSupported) begin
              if(logic_command_access_args_postExec) begin
                logic_command_stateNext = logic_command_POST_EXEC;
              end
              if(logic_command_access_args_transfer) begin
                if(when_DebugModule_l427) begin
                  if(logic_command_access_args_write) begin
                    logic_command_stateNext = logic_command_WRITE_INT_REG;
                  end else begin
                    logic_command_stateNext = logic_command_READ_INT_REG;
                  end
                end
              end
            end
          end
          default : begin
          end
        endcase
      end
      logic_command_READ_INT_REG : begin
        logic_command_stateNext = logic_command_WAIT_DONE;
      end
      logic_command_WRITE_INT_REG : begin
        logic_command_stateNext = logic_command_WAIT_DONE;
      end
      logic_command_WAIT_DONE : begin
        if(when_DebugModule_l481) begin
          logic_command_stateNext = logic_command_IDLE;
          if(logic_command_access_args_postExec) begin
            logic_command_stateNext = logic_command_POST_EXEC;
          end
        end
      end
      logic_command_POST_EXEC : begin
        logic_command_stateNext = logic_command_POST_EXEC_WAIT;
      end
      logic_command_POST_EXEC_WAIT : begin
        if(when_DebugModule_l497) begin
          logic_command_stateNext = logic_command_IDLE;
        end
        if(when_DebugModule_l501) begin
          logic_command_stateNext = logic_command_POST_EXEC;
        end
      end
      default : begin
      end
    endcase
    if(logic_command_wantStart) begin
      logic_command_stateNext = logic_command_IDLE;
    end
    if(logic_command_wantKill) begin
      logic_command_stateNext = logic_command_BOOT;
    end
  end

  assign when_DebugModule_l406 = (logic_command_request && logic_abstractcs_noError);
  assign when_DebugModule_l407 = (! io_harts_0_halted);
  assign switch_DebugModule_l418 = logic_command_data[31 : 24];
  assign when_DebugModule_l427 = (! logic_command_access_args_regno[5]);
  assign when_DebugModule_l481 = (logic_selected_commit || logic_selected_regSuccess);
  assign when_DebugModule_l497 = ((logic_selected_ebreak || logic_selected_exception) || logic_selected_commit);
  assign when_DebugModule_l501 = (logic_selected_redo || (logic_selected_commit && (logic_command_executionCounter != 1'b1)));
  assign logic_command_onExit_BOOT = ((logic_command_stateNext != logic_command_BOOT) && (logic_command_stateReg == logic_command_BOOT));
  assign logic_command_onExit_IDLE = ((logic_command_stateNext != logic_command_IDLE) && (logic_command_stateReg == logic_command_IDLE));
  assign logic_command_onExit_DECODE = ((logic_command_stateNext != logic_command_DECODE) && (logic_command_stateReg == logic_command_DECODE));
  assign logic_command_onExit_READ_INT_REG = ((logic_command_stateNext != logic_command_READ_INT_REG) && (logic_command_stateReg == logic_command_READ_INT_REG));
  assign logic_command_onExit_WRITE_INT_REG = ((logic_command_stateNext != logic_command_WRITE_INT_REG) && (logic_command_stateReg == logic_command_WRITE_INT_REG));
  assign logic_command_onExit_WAIT_DONE = ((logic_command_stateNext != logic_command_WAIT_DONE) && (logic_command_stateReg == logic_command_WAIT_DONE));
  assign logic_command_onExit_POST_EXEC = ((logic_command_stateNext != logic_command_POST_EXEC) && (logic_command_stateReg == logic_command_POST_EXEC));
  assign logic_command_onExit_POST_EXEC_WAIT = ((logic_command_stateNext != logic_command_POST_EXEC_WAIT) && (logic_command_stateReg == logic_command_POST_EXEC_WAIT));
  assign logic_command_onEntry_BOOT = ((logic_command_stateNext == logic_command_BOOT) && (logic_command_stateReg != logic_command_BOOT));
  assign logic_command_onEntry_IDLE = ((logic_command_stateNext == logic_command_IDLE) && (logic_command_stateReg != logic_command_IDLE));
  assign logic_command_onEntry_DECODE = ((logic_command_stateNext == logic_command_DECODE) && (logic_command_stateReg != logic_command_DECODE));
  assign logic_command_onEntry_READ_INT_REG = ((logic_command_stateNext == logic_command_READ_INT_REG) && (logic_command_stateReg != logic_command_READ_INT_REG));
  assign logic_command_onEntry_WRITE_INT_REG = ((logic_command_stateNext == logic_command_WRITE_INT_REG) && (logic_command_stateReg != logic_command_WRITE_INT_REG));
  assign logic_command_onEntry_WAIT_DONE = ((logic_command_stateNext == logic_command_WAIT_DONE) && (logic_command_stateReg != logic_command_WAIT_DONE));
  assign logic_command_onEntry_POST_EXEC = ((logic_command_stateNext == logic_command_POST_EXEC) && (logic_command_stateReg != logic_command_POST_EXEC));
  assign logic_command_onEntry_POST_EXEC_WAIT = ((logic_command_stateNext == logic_command_POST_EXEC_WAIT) && (logic_command_stateReg != logic_command_POST_EXEC_WAIT));
  assign _zz_factory_cmdToRsp_payload_data = _zz_factory_cmdToRsp_payload_data_1;
  always @(posedge clk) begin
    if(debugReset) begin
      factory_rspBuffer_valid <= 1'b0;
      dmactive <= 1'b0;
    end else begin
      factory_rspBuffer_valid <= factory_cmdToRsp_valid;
      case(io_ctrl_cmd_payload_address)
        7'h10 : begin
          if(factory_doWrite) begin
            dmactive <= io_ctrl_cmd_payload_data[0];
          end
        end
        default : begin
        end
      endcase
    end
  end

  always @(posedge clk) begin
    factory_rspBuffer_payload_error <= factory_cmdToRsp_payload_error;
    factory_rspBuffer_payload_data <= factory_cmdToRsp_payload_data;
  end

  always @(posedge clk or negedge dmactive) begin
    if(!dmactive) begin
      logic_dmcontrol_ndmreset <= 1'b0;
      logic_dmcontrol_hartSelLo <= 10'h0;
      logic_dmcontrol_hartSelHi <= 10'h0;
      logic_dmcontrol_harts_0_haltReq <= 1'b0;
      _zz_logic_harts_0_resumeReady <= 1'b0;
      _zz_logic_harts_0_resumeReady_1 <= 1'b0;
      logic_abstractcs_cmdErr <= DebugModuleCmdErr_NONE;
      logic_abstractcs_busy <= 1'b0;
      logic_abstractAuto_autoexecdata <= 1'b0;
      logic_abstractAuto_autoexecProgbuf <= 2'b00;
      logic_command_stateReg <= logic_command_BOOT;
    end else begin
      if(when_DebugModule_l126) begin
        logic_dmcontrol_harts_0_haltReq <= ((logic_dmcontrol_harts_0_haltReq || logic_dmcontrol_haltSet) && (! logic_dmcontrol_haltClear));
      end
      if(io_harts_0_resume_cmd_valid) begin
        _zz_logic_harts_0_resumeReady <= 1'b1;
      end
      if(io_harts_0_resume_rsp_valid) begin
        _zz_logic_harts_0_resumeReady <= 1'b0;
      end
      if(io_harts_0_resume_cmd_valid) begin
        _zz_logic_harts_0_resumeReady_1 <= 1'b1;
      end
      if(when_BusSlaveFactory_l341) begin
        logic_abstractcs_cmdErr <= _zz_logic_abstractcs_cmdErr;
      end
      if(when_DebugModule_l391) begin
        logic_abstractcs_cmdErr <= DebugModuleCmdErr_BUSY;
      end
      if(when_DebugModule_l394) begin
        logic_abstractcs_cmdErr <= DebugModuleCmdErr_EXCEPTION;
      end
      if(when_DebugModule_l397) begin
        logic_abstractcs_cmdErr <= DebugModuleCmdErr_BUSY;
      end
      case(io_ctrl_cmd_payload_address)
        7'h10 : begin
          if(factory_doWrite) begin
            logic_dmcontrol_ndmreset <= io_ctrl_cmd_payload_data[1];
            logic_dmcontrol_hartSelLo <= io_ctrl_cmd_payload_data[25 : 16];
            logic_dmcontrol_hartSelHi <= io_ctrl_cmd_payload_data[15 : 6];
          end
        end
        7'h18 : begin
          if(factory_doWrite) begin
            logic_abstractAuto_autoexecdata <= io_ctrl_cmd_payload_data[0 : 0];
            logic_abstractAuto_autoexecProgbuf <= io_ctrl_cmd_payload_data[17 : 16];
          end
        end
        default : begin
        end
      endcase
      logic_command_stateReg <= logic_command_stateNext;
      case(logic_command_stateReg)
        logic_command_IDLE : begin
          if(when_DebugModule_l406) begin
            if(when_DebugModule_l407) begin
              logic_abstractcs_cmdErr <= DebugModuleCmdErr_HALT_RESUME;
            end else begin
              logic_abstractcs_busy <= 1'b1;
            end
          end
        end
        logic_command_DECODE : begin
          case(switch_DebugModule_l418)
            8'h0 : begin
              if(logic_command_access_notSupported) begin
                logic_abstractcs_cmdErr <= DebugModuleCmdErr_NOT_SUPPORTED;
              end
            end
            default : begin
              logic_abstractcs_cmdErr <= DebugModuleCmdErr_NOT_SUPPORTED;
            end
          endcase
        end
        logic_command_READ_INT_REG : begin
        end
        logic_command_WRITE_INT_REG : begin
        end
        logic_command_WAIT_DONE : begin
        end
        logic_command_POST_EXEC : begin
        end
        logic_command_POST_EXEC_WAIT : begin
        end
        default : begin
        end
      endcase
      if(logic_command_onEntry_IDLE) begin
        logic_abstractcs_busy <= 1'b0;
      end
    end
  end

  always @(posedge clk) begin
    _zz_io_harts_0_ackReset <= (logic_harts_0_sel && logic_dmcontrol_ackhavereset);
    case(io_ctrl_cmd_payload_address)
      7'h17 : begin
        if(factory_doWrite) begin
          logic_command_data <= io_ctrl_cmd_payload_data[31 : 0];
        end
      end
      default : begin
      end
    endcase
    case(logic_command_stateReg)
      logic_command_IDLE : begin
        logic_command_executionCounter <= 1'b0;
      end
      logic_command_DECODE : begin
      end
      logic_command_READ_INT_REG : begin
      end
      logic_command_WRITE_INT_REG : begin
      end
      logic_command_WAIT_DONE : begin
      end
      logic_command_POST_EXEC : begin
      end
      logic_command_POST_EXEC_WAIT : begin
        if(when_DebugModule_l497) begin
          logic_command_executionCounter <= (logic_command_executionCounter + 1'b1);
        end
      end
      default : begin
      end
    endcase
    if(logic_fromHarts_valid) begin
      _zz_factory_cmdToRsp_payload_data_1 <= logic_fromHarts_payload_data;
    end
  end


endmodule

module BufferCC_3 (
  input  wire          io_dataIn,
  output wire          io_dataOut,
  input  wire          clk,
  input  wire          reset
);

  (* async_reg = "true" *) reg                 buffers_0;
  (* async_reg = "true" *) reg                 buffers_1;

  assign io_dataOut = buffers_1;
  always @(posedge clk) begin
    buffers_0 <= io_dataIn;
    buffers_1 <= buffers_0;
  end


endmodule

module InstructionCache (
  input  wire          io_flush,
  input  wire          io_cpu_prefetch_isValid,
  output reg           io_cpu_prefetch_haltIt,
  input  wire [31:0]   io_cpu_prefetch_pc,
  input  wire          io_cpu_fetch_isValid,
  input  wire          io_cpu_fetch_isStuck,
  input  wire          io_cpu_fetch_isRemoved,
  input  wire [31:0]   io_cpu_fetch_pc,
  output wire [31:0]   io_cpu_fetch_data,
  input  wire [31:0]   io_cpu_fetch_mmuRsp_physicalAddress,
  input  wire          io_cpu_fetch_mmuRsp_isIoAccess,
  input  wire          io_cpu_fetch_mmuRsp_isPaging,
  input  wire          io_cpu_fetch_mmuRsp_allowRead,
  input  wire          io_cpu_fetch_mmuRsp_allowWrite,
  input  wire          io_cpu_fetch_mmuRsp_allowExecute,
  input  wire          io_cpu_fetch_mmuRsp_exception,
  input  wire          io_cpu_fetch_mmuRsp_refilling,
  input  wire          io_cpu_fetch_mmuRsp_bypassTranslation,
  output wire [31:0]   io_cpu_fetch_physicalAddress,
  input  wire          io_cpu_decode_isValid,
  input  wire          io_cpu_decode_isStuck,
  input  wire [31:0]   io_cpu_decode_pc,
  output wire [31:0]   io_cpu_decode_physicalAddress,
  output wire [31:0]   io_cpu_decode_data,
  output wire          io_cpu_decode_cacheMiss,
  output wire          io_cpu_decode_error,
  output wire          io_cpu_decode_mmuRefilling,
  output wire          io_cpu_decode_mmuException,
  input  wire          io_cpu_decode_isUser,
  input  wire          io_cpu_fill_valid,
  input  wire [31:0]   io_cpu_fill_payload,
  output wire          io_mem_cmd_valid,
  input  wire          io_mem_cmd_ready,
  output wire [31:0]   io_mem_cmd_payload_address,
  output wire [2:0]    io_mem_cmd_payload_size,
  input  wire          io_mem_rsp_valid,
  input  wire [31:0]   io_mem_rsp_payload_data,
  input  wire          io_mem_rsp_payload_error,
  input  wire [2:0]    _zz_when_Fetcher_l411,
  input  wire [31:0]   _zz_io_cpu_fetch_data_regNextWhen,
  input  wire          clk,
  input  wire          reset
);

  reg        [31:0]   banks_0_spinal_port1;
  reg        [22:0]   ways_0_tags_spinal_port1;
  wire       [22:0]   _zz_ways_0_tags_port;
  reg                 _zz_1;
  reg                 _zz_2;
  reg                 lineLoader_fire;
  reg                 lineLoader_valid;
  (* keep , syn_keep *) reg        [31:0]   lineLoader_address /* synthesis syn_keep = 1 */ ;
  reg                 lineLoader_hadError;
  reg                 lineLoader_flushPending;
  reg        [6:0]    lineLoader_flushCounter;
  wire                when_InstructionCache_l339;
  reg                 _zz_when_InstructionCache_l343;
  wire                when_InstructionCache_l343;
  wire                when_InstructionCache_l352;
  reg                 lineLoader_cmdSent;
  wire                io_mem_cmd_fire;
  wire                when_Utils_l593;
  reg                 lineLoader_wayToAllocate_willIncrement;
  wire                lineLoader_wayToAllocate_willClear;
  wire                lineLoader_wayToAllocate_willOverflowIfInc;
  wire                lineLoader_wayToAllocate_willOverflow;
  (* keep , syn_keep *) reg        [2:0]    lineLoader_wordIndex /* synthesis syn_keep = 1 */ ;
  wire                lineLoader_write_tag_0_valid;
  wire       [5:0]    lineLoader_write_tag_0_payload_address;
  wire                lineLoader_write_tag_0_payload_data_valid;
  wire                lineLoader_write_tag_0_payload_data_error;
  wire       [20:0]   lineLoader_write_tag_0_payload_data_address;
  wire                lineLoader_write_data_0_valid;
  wire       [8:0]    lineLoader_write_data_0_payload_address;
  wire       [31:0]   lineLoader_write_data_0_payload_data;
  wire                when_InstructionCache_l402;
  wire       [8:0]    _zz_fetchStage_read_banksValue_0_dataMem;
  wire                _zz_fetchStage_read_banksValue_0_dataMem_1;
  wire       [31:0]   fetchStage_read_banksValue_0_dataMem;
  wire       [31:0]   fetchStage_read_banksValue_0_data;
  wire       [5:0]    _zz_fetchStage_read_waysValues_0_tag_valid;
  wire                _zz_fetchStage_read_waysValues_0_tag_valid_1;
  wire                fetchStage_read_waysValues_0_tag_valid;
  wire                fetchStage_read_waysValues_0_tag_error;
  wire       [20:0]   fetchStage_read_waysValues_0_tag_address;
  wire       [22:0]   _zz_fetchStage_read_waysValues_0_tag_valid_2;
  wire                fetchStage_hit_hits_0;
  wire                fetchStage_hit_valid;
  wire                fetchStage_hit_error;
  wire       [31:0]   fetchStage_hit_data;
  wire       [31:0]   fetchStage_hit_word;
  wire                when_InstructionCache_l436;
  reg        [31:0]   io_cpu_fetch_data_regNextWhen;
  wire                when_InstructionCache_l460;
  reg        [31:0]   decodeStage_mmuRsp_physicalAddress;
  reg                 decodeStage_mmuRsp_isIoAccess;
  reg                 decodeStage_mmuRsp_isPaging;
  reg                 decodeStage_mmuRsp_allowRead;
  reg                 decodeStage_mmuRsp_allowWrite;
  reg                 decodeStage_mmuRsp_allowExecute;
  reg                 decodeStage_mmuRsp_exception;
  reg                 decodeStage_mmuRsp_refilling;
  reg                 decodeStage_mmuRsp_bypassTranslation;
  wire                when_InstructionCache_l460_1;
  reg                 decodeStage_hit_valid;
  wire                when_InstructionCache_l460_2;
  reg                 decodeStage_hit_error;
  wire                when_Fetcher_l411;
  reg [31:0] banks_0 [0:511];
  reg [22:0] ways_0_tags [0:63];

  assign _zz_ways_0_tags_port = {lineLoader_write_tag_0_payload_data_address,{lineLoader_write_tag_0_payload_data_error,lineLoader_write_tag_0_payload_data_valid}};
  always @(posedge clk) begin
    if(_zz_1) begin
      banks_0[lineLoader_write_data_0_payload_address] <= lineLoader_write_data_0_payload_data;
    end
  end

  always @(posedge clk) begin
    if(_zz_fetchStage_read_banksValue_0_dataMem_1) begin
      banks_0_spinal_port1 <= banks_0[_zz_fetchStage_read_banksValue_0_dataMem];
    end
  end

  always @(posedge clk) begin
    if(_zz_2) begin
      ways_0_tags[lineLoader_write_tag_0_payload_address] <= _zz_ways_0_tags_port;
    end
  end

  always @(posedge clk) begin
    if(_zz_fetchStage_read_waysValues_0_tag_valid_1) begin
      ways_0_tags_spinal_port1 <= ways_0_tags[_zz_fetchStage_read_waysValues_0_tag_valid];
    end
  end

  always @(*) begin
    _zz_1 = 1'b0;
    if(lineLoader_write_data_0_valid) begin
      _zz_1 = 1'b1;
    end
  end

  always @(*) begin
    _zz_2 = 1'b0;
    if(lineLoader_write_tag_0_valid) begin
      _zz_2 = 1'b1;
    end
  end

  always @(*) begin
    lineLoader_fire = 1'b0;
    if(io_mem_rsp_valid) begin
      if(when_InstructionCache_l402) begin
        lineLoader_fire = 1'b1;
      end
    end
  end

  always @(*) begin
    io_cpu_prefetch_haltIt = (lineLoader_valid || lineLoader_flushPending);
    if(when_InstructionCache_l339) begin
      io_cpu_prefetch_haltIt = 1'b1;
    end
    if(when_InstructionCache_l343) begin
      io_cpu_prefetch_haltIt = 1'b1;
    end
    if(io_flush) begin
      io_cpu_prefetch_haltIt = 1'b1;
    end
  end

  assign when_InstructionCache_l339 = (! lineLoader_flushCounter[6]);
  assign when_InstructionCache_l343 = (! _zz_when_InstructionCache_l343);
  assign when_InstructionCache_l352 = (lineLoader_flushPending && (! (lineLoader_valid || io_cpu_fetch_isValid)));
  assign io_mem_cmd_fire = (io_mem_cmd_valid && io_mem_cmd_ready);
  assign io_mem_cmd_valid = (lineLoader_valid && (! lineLoader_cmdSent));
  assign io_mem_cmd_payload_address = {lineLoader_address[31 : 5],5'h0};
  assign io_mem_cmd_payload_size = 3'b101;
  assign when_Utils_l593 = (! lineLoader_valid);
  always @(*) begin
    lineLoader_wayToAllocate_willIncrement = 1'b0;
    if(when_Utils_l593) begin
      lineLoader_wayToAllocate_willIncrement = 1'b1;
    end
  end

  assign lineLoader_wayToAllocate_willClear = 1'b0;
  assign lineLoader_wayToAllocate_willOverflowIfInc = 1'b1;
  assign lineLoader_wayToAllocate_willOverflow = (lineLoader_wayToAllocate_willOverflowIfInc && lineLoader_wayToAllocate_willIncrement);
  assign lineLoader_write_tag_0_valid = ((1'b1 && lineLoader_fire) || (! lineLoader_flushCounter[6]));
  assign lineLoader_write_tag_0_payload_address = (lineLoader_flushCounter[6] ? lineLoader_address[10 : 5] : lineLoader_flushCounter[5 : 0]);
  assign lineLoader_write_tag_0_payload_data_valid = lineLoader_flushCounter[6];
  assign lineLoader_write_tag_0_payload_data_error = (lineLoader_hadError || io_mem_rsp_payload_error);
  assign lineLoader_write_tag_0_payload_data_address = lineLoader_address[31 : 11];
  assign lineLoader_write_data_0_valid = (io_mem_rsp_valid && 1'b1);
  assign lineLoader_write_data_0_payload_address = {lineLoader_address[10 : 5],lineLoader_wordIndex};
  assign lineLoader_write_data_0_payload_data = io_mem_rsp_payload_data;
  assign when_InstructionCache_l402 = (lineLoader_wordIndex == 3'b111);
  assign _zz_fetchStage_read_banksValue_0_dataMem = io_cpu_prefetch_pc[10 : 2];
  assign _zz_fetchStage_read_banksValue_0_dataMem_1 = (! io_cpu_fetch_isStuck);
  assign fetchStage_read_banksValue_0_dataMem = banks_0_spinal_port1;
  assign fetchStage_read_banksValue_0_data = fetchStage_read_banksValue_0_dataMem[31 : 0];
  assign _zz_fetchStage_read_waysValues_0_tag_valid = io_cpu_prefetch_pc[10 : 5];
  assign _zz_fetchStage_read_waysValues_0_tag_valid_1 = (! io_cpu_fetch_isStuck);
  assign _zz_fetchStage_read_waysValues_0_tag_valid_2 = ways_0_tags_spinal_port1;
  assign fetchStage_read_waysValues_0_tag_valid = _zz_fetchStage_read_waysValues_0_tag_valid_2[0];
  assign fetchStage_read_waysValues_0_tag_error = _zz_fetchStage_read_waysValues_0_tag_valid_2[1];
  assign fetchStage_read_waysValues_0_tag_address = _zz_fetchStage_read_waysValues_0_tag_valid_2[22 : 2];
  assign fetchStage_hit_hits_0 = (fetchStage_read_waysValues_0_tag_valid && (fetchStage_read_waysValues_0_tag_address == io_cpu_fetch_mmuRsp_physicalAddress[31 : 11]));
  assign fetchStage_hit_valid = (|fetchStage_hit_hits_0);
  assign fetchStage_hit_error = fetchStage_read_waysValues_0_tag_error;
  assign fetchStage_hit_data = fetchStage_read_banksValue_0_data;
  assign fetchStage_hit_word = fetchStage_hit_data;
  assign io_cpu_fetch_data = fetchStage_hit_word;
  assign when_InstructionCache_l436 = (! io_cpu_decode_isStuck);
  assign io_cpu_decode_data = io_cpu_fetch_data_regNextWhen;
  assign io_cpu_fetch_physicalAddress = io_cpu_fetch_mmuRsp_physicalAddress;
  assign when_InstructionCache_l460 = (! io_cpu_decode_isStuck);
  assign when_InstructionCache_l460_1 = (! io_cpu_decode_isStuck);
  assign when_InstructionCache_l460_2 = (! io_cpu_decode_isStuck);
  assign io_cpu_decode_cacheMiss = (! decodeStage_hit_valid);
  assign io_cpu_decode_error = (decodeStage_hit_error || ((! decodeStage_mmuRsp_isPaging) && (decodeStage_mmuRsp_exception || (! decodeStage_mmuRsp_allowExecute))));
  assign io_cpu_decode_mmuRefilling = decodeStage_mmuRsp_refilling;
  assign io_cpu_decode_mmuException = (((! decodeStage_mmuRsp_refilling) && decodeStage_mmuRsp_isPaging) && (decodeStage_mmuRsp_exception || (! decodeStage_mmuRsp_allowExecute)));
  assign io_cpu_decode_physicalAddress = decodeStage_mmuRsp_physicalAddress;
  assign when_Fetcher_l411 = (_zz_when_Fetcher_l411 != 3'b000);
  always @(posedge clk) begin
    if(reset) begin
      lineLoader_valid <= 1'b0;
      lineLoader_hadError <= 1'b0;
      lineLoader_flushPending <= 1'b1;
      lineLoader_cmdSent <= 1'b0;
      lineLoader_wordIndex <= 3'b000;
    end else begin
      if(lineLoader_fire) begin
        lineLoader_valid <= 1'b0;
      end
      if(lineLoader_fire) begin
        lineLoader_hadError <= 1'b0;
      end
      if(io_cpu_fill_valid) begin
        lineLoader_valid <= 1'b1;
      end
      if(io_flush) begin
        lineLoader_flushPending <= 1'b1;
      end
      if(when_InstructionCache_l352) begin
        lineLoader_flushPending <= 1'b0;
      end
      if(io_mem_cmd_fire) begin
        lineLoader_cmdSent <= 1'b1;
      end
      if(lineLoader_fire) begin
        lineLoader_cmdSent <= 1'b0;
      end
      if(io_mem_rsp_valid) begin
        lineLoader_wordIndex <= (lineLoader_wordIndex + 3'b001);
        if(io_mem_rsp_payload_error) begin
          lineLoader_hadError <= 1'b1;
        end
      end
    end
  end

  always @(posedge clk) begin
    if(io_cpu_fill_valid) begin
      lineLoader_address <= io_cpu_fill_payload;
    end
    if(when_InstructionCache_l339) begin
      lineLoader_flushCounter <= (lineLoader_flushCounter + 7'h01);
    end
    _zz_when_InstructionCache_l343 <= lineLoader_flushCounter[6];
    if(when_InstructionCache_l352) begin
      lineLoader_flushCounter <= 7'h0;
    end
    if(when_InstructionCache_l436) begin
      io_cpu_fetch_data_regNextWhen <= io_cpu_fetch_data;
    end
    if(when_InstructionCache_l460) begin
      decodeStage_mmuRsp_physicalAddress <= io_cpu_fetch_mmuRsp_physicalAddress;
      decodeStage_mmuRsp_isIoAccess <= io_cpu_fetch_mmuRsp_isIoAccess;
      decodeStage_mmuRsp_isPaging <= io_cpu_fetch_mmuRsp_isPaging;
      decodeStage_mmuRsp_allowRead <= io_cpu_fetch_mmuRsp_allowRead;
      decodeStage_mmuRsp_allowWrite <= io_cpu_fetch_mmuRsp_allowWrite;
      decodeStage_mmuRsp_allowExecute <= io_cpu_fetch_mmuRsp_allowExecute;
      decodeStage_mmuRsp_exception <= io_cpu_fetch_mmuRsp_exception;
      decodeStage_mmuRsp_refilling <= io_cpu_fetch_mmuRsp_refilling;
      decodeStage_mmuRsp_bypassTranslation <= io_cpu_fetch_mmuRsp_bypassTranslation;
    end
    if(when_InstructionCache_l460_1) begin
      decodeStage_hit_valid <= fetchStage_hit_valid;
    end
    if(when_InstructionCache_l460_2) begin
      decodeStage_hit_error <= fetchStage_hit_error;
    end
    if(when_Fetcher_l411) begin
      io_cpu_fetch_data_regNextWhen <= _zz_io_cpu_fetch_data_regNextWhen;
    end
  end


endmodule

module FlowCCByToggle_1 (
  input  wire          io_input_valid,
  input  wire          io_input_payload_error,
  input  wire [31:0]   io_input_payload_data,
  output wire          io_output_valid,
  output wire          io_output_payload_error,
  output wire [31:0]   io_output_payload_data,
  input  wire          clk,
  input  wire          debugReset,
  input  wire          jtag_clk
);

  wire                debugReset_asyncAssertSyncDeassert_buffercc_io_dataOut;
  wire                inputArea_target_buffercc_io_dataOut;
  wire                debugReset_asyncAssertSyncDeassert;
  wire                debugReset_synchronized;
  (* altera_attribute = "-name ADV_NETLIST_OPT_ALLOWED NEVER_ALLOW" *) reg                 inputArea_target;
  (* altera_attribute = "-name ADV_NETLIST_OPT_ALLOWED NEVER_ALLOW" *) reg                 inputArea_data_error;
  (* altera_attribute = "-name ADV_NETLIST_OPT_ALLOWED NEVER_ALLOW" *) reg        [31:0]   inputArea_data_data;
  wire                outputArea_target;
  (* altera_attribute = "-name ADV_NETLIST_OPT_ALLOWED NEVER_ALLOW" *) reg                 outputArea_hit;
  wire                outputArea_flow_valid;
  wire                outputArea_flow_payload_error;
  wire       [31:0]   outputArea_flow_payload_data;
  (* altera_attribute = "-name ADV_NETLIST_OPT_ALLOWED NEVER_ALLOW" *) reg                 outputArea_flow_m2sPipe_valid;
  (* async_reg = "true" , altera_attribute = "-name ADV_NETLIST_OPT_ALLOWED NEVER_ALLOW" *) reg                 outputArea_flow_m2sPipe_payload_error;
  (* async_reg = "true" , altera_attribute = "-name ADV_NETLIST_OPT_ALLOWED NEVER_ALLOW" *) reg        [31:0]   outputArea_flow_m2sPipe_payload_data;

  (* keep_hierarchy = "TRUE" *) BufferCC_1 debugReset_asyncAssertSyncDeassert_buffercc (
    .io_dataIn  (debugReset_asyncAssertSyncDeassert                    ), //i
    .io_dataOut (debugReset_asyncAssertSyncDeassert_buffercc_io_dataOut), //o
    .jtag_clk   (jtag_clk                                              ), //i
    .debugReset (debugReset                                            )  //i
  );
  (* keep_hierarchy = "TRUE" *) BufferCC_2 inputArea_target_buffercc (
    .io_dataIn               (inputArea_target                    ), //i
    .io_dataOut              (inputArea_target_buffercc_io_dataOut), //o
    .jtag_clk                (jtag_clk                            ), //i
    .debugReset_synchronized (debugReset_synchronized             )  //i
  );
  assign debugReset_asyncAssertSyncDeassert = (1'b0 ^ 1'b0);
  assign debugReset_synchronized = debugReset_asyncAssertSyncDeassert_buffercc_io_dataOut;
  assign outputArea_target = inputArea_target_buffercc_io_dataOut;
  assign outputArea_flow_valid = (outputArea_target != outputArea_hit);
  assign outputArea_flow_payload_error = inputArea_data_error;
  assign outputArea_flow_payload_data = inputArea_data_data;
  assign io_output_valid = outputArea_flow_m2sPipe_valid;
  assign io_output_payload_error = outputArea_flow_m2sPipe_payload_error;
  assign io_output_payload_data = outputArea_flow_m2sPipe_payload_data;
  always @(posedge clk) begin
    if(debugReset) begin
      inputArea_target <= 1'b0;
    end else begin
      if(io_input_valid) begin
        inputArea_target <= (! inputArea_target);
      end
    end
  end

  always @(posedge clk) begin
    if(io_input_valid) begin
      inputArea_data_error <= io_input_payload_error;
      inputArea_data_data <= io_input_payload_data;
    end
  end

  always @(posedge jtag_clk) begin
    if(debugReset_synchronized) begin
      outputArea_flow_m2sPipe_valid <= 1'b0;
      outputArea_hit <= 1'b0;
    end else begin
      outputArea_hit <= outputArea_target;
      outputArea_flow_m2sPipe_valid <= outputArea_flow_valid;
    end
  end

  always @(posedge jtag_clk) begin
    if(outputArea_flow_valid) begin
      outputArea_flow_m2sPipe_payload_error <= outputArea_flow_payload_error;
      outputArea_flow_m2sPipe_payload_data <= outputArea_flow_payload_data;
    end
  end


endmodule

module FlowCCByToggle (
  input  wire          io_input_valid,
  input  wire          io_input_payload_write,
  input  wire [31:0]   io_input_payload_data,
  input  wire [6:0]    io_input_payload_address,
  output wire          io_output_valid,
  output wire          io_output_payload_write,
  output wire [31:0]   io_output_payload_data,
  output wire [6:0]    io_output_payload_address,
  input  wire          jtag_clk,
  input  wire          clk,
  input  wire          debugReset
);

  wire                inputArea_target_buffercc_io_dataOut;
  (* altera_attribute = "-name ADV_NETLIST_OPT_ALLOWED NEVER_ALLOW" *) reg                 inputArea_target;
  (* altera_attribute = "-name ADV_NETLIST_OPT_ALLOWED NEVER_ALLOW" *) reg                 inputArea_data_write;
  (* altera_attribute = "-name ADV_NETLIST_OPT_ALLOWED NEVER_ALLOW" *) reg        [31:0]   inputArea_data_data;
  (* altera_attribute = "-name ADV_NETLIST_OPT_ALLOWED NEVER_ALLOW" *) reg        [6:0]    inputArea_data_address;
  wire                outputArea_target;
  reg                 outputArea_hit;
  wire                outputArea_flow_valid;
  wire                outputArea_flow_payload_write;
  wire       [31:0]   outputArea_flow_payload_data;
  wire       [6:0]    outputArea_flow_payload_address;

  (* keep_hierarchy = "TRUE" *) BufferCC inputArea_target_buffercc (
    .io_dataIn  (inputArea_target                    ), //i
    .io_dataOut (inputArea_target_buffercc_io_dataOut), //o
    .clk        (clk                                 ), //i
    .debugReset (debugReset                          )  //i
  );
  initial begin
  `ifndef SYNTHESIS
    inputArea_target = $urandom;
    outputArea_hit = $urandom;
  `endif
  end

  assign outputArea_target = inputArea_target_buffercc_io_dataOut;
  assign outputArea_flow_valid = (outputArea_target != outputArea_hit);
  assign outputArea_flow_payload_write = inputArea_data_write;
  assign outputArea_flow_payload_data = inputArea_data_data;
  assign outputArea_flow_payload_address = inputArea_data_address;
  assign io_output_valid = outputArea_flow_valid;
  assign io_output_payload_write = outputArea_flow_payload_write;
  assign io_output_payload_data = outputArea_flow_payload_data;
  assign io_output_payload_address = outputArea_flow_payload_address;
  always @(posedge jtag_clk) begin
    if(io_input_valid) begin
      inputArea_target <= (! inputArea_target);
      inputArea_data_write <= io_input_payload_write;
      inputArea_data_data <= io_input_payload_data;
      inputArea_data_address <= io_input_payload_address;
    end
  end

  always @(posedge clk) begin
    outputArea_hit <= outputArea_target;
  end


endmodule

module BufferCC_2 (
  input  wire          io_dataIn,
  output wire          io_dataOut,
  input  wire          jtag_clk,
  input  wire          debugReset_synchronized
);

  (* async_reg = "true" , altera_attribute = "-name ADV_NETLIST_OPT_ALLOWED NEVER_ALLOW" *) reg                 buffers_0;
  (* altera_attribute = "-name ADV_NETLIST_OPT_ALLOWED NEVER_ALLOW" , async_reg = "true" *) reg                 buffers_1;

  assign io_dataOut = buffers_1;
  always @(posedge jtag_clk) begin
    if(debugReset_synchronized) begin
      buffers_0 <= 1'b0;
      buffers_1 <= 1'b0;
    end else begin
      buffers_0 <= io_dataIn;
      buffers_1 <= buffers_0;
    end
  end


endmodule

module BufferCC_1 (
  input  wire          io_dataIn,
  output wire          io_dataOut,
  input  wire          jtag_clk,
  input  wire          debugReset
);

  (* async_reg = "true" *) reg                 buffers_0;
  (* async_reg = "true" *) reg                 buffers_1;

  assign io_dataOut = buffers_1;
  always @(posedge jtag_clk or posedge debugReset) begin
    if(debugReset) begin
      buffers_0 <= 1'b1;
      buffers_1 <= 1'b1;
    end else begin
      buffers_0 <= io_dataIn;
      buffers_1 <= buffers_0;
    end
  end


endmodule

module BufferCC (
  input  wire          io_dataIn,
  output wire          io_dataOut,
  input  wire          clk,
  input  wire          debugReset
);

  (* async_reg = "true" , altera_attribute = "-name ADV_NETLIST_OPT_ALLOWED NEVER_ALLOW" *) reg                 buffers_0;
  (* async_reg = "true" *) reg                 buffers_1;

  initial begin
  `ifndef SYNTHESIS
    buffers_0 = $urandom;
    buffers_1 = $urandom;
  `endif
  end

  assign io_dataOut = buffers_1;
  always @(posedge clk) begin
    buffers_0 <= io_dataIn;
    buffers_1 <= buffers_0;
  end


endmodule
