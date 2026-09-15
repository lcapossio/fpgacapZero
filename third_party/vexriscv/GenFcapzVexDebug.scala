// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>
//
// Maintainer-only recipe that regenerates the vendored VexRiscv CPU-debug core
// (VexRiscv_EmbeddedJtag.v). Not compiled by clean fcapz builds -- those only
// hash-verify the vendored .v. To regenerate, drop this file into a
// SpinalHDL/VexRiscv checkout at src/main/scala/vexriscv/demo/, then run the
// command in third_party/vexriscv/PROVENANCE.toml ([core.debug.regen]).
// Depends on the upstream VexRiscv/SpinalHDL API (MIT); see ./LICENSE.

package vexriscv.demo

import spinal.core._
import spinal.lib._
import spinal.lib.cpu.riscv.debug.DebugTransportModuleParameter
import vexriscv.ip.InstructionCacheConfig
import vexriscv.plugin.CsrAccess.WRITE_ONLY
import vexriscv.plugin._
import vexriscv.{VexRiscv, VexRiscvConfig, plugin}

import scala.collection.mutable.ArrayBuffer

/**
 * fcapz VexRiscv debug core: same bus/microarch profile as the vendored
 * "Lite" core (iCacheSize=2048, no d$, LightShifter, iterative mul/div,
 * external interrupt array, small CSR, Wishbone iBus/dBus, external reset
 * vector) BUT with the official RISC-V debug (EmbeddedRiscvJtag) instead of
 * the classic SpinalHDL DebugPlugin, in no-TAP tunnel mode so a Xilinx
 * BSCANE2 / Intel sld_virtual_jtag can feed the JTAG DTM.
 *
 * sbt "runMain vexriscv.demo.GenFcapzVexDebug"
 */
object GenFcapzVexDebug extends App {
  val outputFile = "VexRiscv_EmbeddedJtag"

  val spinalConfig = SpinalConfig(
    defaultConfigForClockDomains = ClockDomainConfig(resetKind = spinal.core.SYNC),
    netlistFileName = outputFile + ".v"
  )

  spinalConfig.generateVerilog {
    val plugins = ArrayBuffer[Plugin[VexRiscv]]()

    plugins ++= List(
      new IBusCachedPlugin(
        resetVector = null, // external reset-vector input, like the Lite core
        relaxedPcCalculation = false,
        prediction = STATIC,
        compressedGen = false,
        memoryTranslatorPortConfig = null,
        config = InstructionCacheConfig(
          cacheSize = 2048,
          bytePerLine = 32,
          wayCount = 1,
          addressWidth = 32,
          cpuDataWidth = 32,
          memDataWidth = 32,
          catchIllegalAccess = true,
          catchAccessFault = true,
          asyncTagMemory = false,
          twoCycleRam = false,
          twoCycleCache = true
        )
      ),
      new DBusSimplePlugin(
        catchAddressMisaligned = true,
        catchAccessFault = true,
        withLrSc = false,
        memoryTranslatorPortConfig = null
      ),
      new StaticMemoryTranslatorPlugin(ioRange = _.msb),
      new DecoderSimplePlugin(catchIllegalInstruction = true),
      new RegFilePlugin(regFileReadyKind = plugin.SYNC, zeroBoot = false),
      new IntAluPlugin,
      new SrcPlugin(separatedAddSub = false, executeInsertion = true),
      new LightShifterPlugin, // singleCycleShift=false
      new HazardSimplePlugin(
        bypassExecute = true,
        bypassMemory = true,
        bypassWriteBack = true,
        bypassWriteBackBuffer = true,
        pessimisticUseSrc = false,
        pessimisticWriteRegFile = false,
        pessimisticAddressMatch = false
      ),
      new BranchPlugin(earlyBranch = false, catchAddressMisaligned = true),
      new CsrPlugin(
        CsrPluginConfig.small(mtvecInit = null).copy(
          mtvecAccess = WRITE_ONLY,
          ecallGen = true,
          wfiGenAsNop = true,
          withPrivilegedDebug = true,
          debugTriggers = 2
        )
      ),
      new MulDivIterativePlugin(
        genMul = true,
        genDiv = true,
        mulUnrollFactor = 1,
        divUnrollFactor = 1
      ),
      new ExternalInterruptArrayPlugin(
        machineMaskCsrId = 0xBC0,
        machinePendingsCsrId = 0xFC0,
        supervisorMaskCsrId = 0x9C0,
        supervisorPendingsCsrId = 0xDC0
      ),
      new YamlPlugin(outputFile + ".yaml"),
      new EmbeddedRiscvJtag(
        p = DebugTransportModuleParameter(
          addressWidth = 7,
          version = 1,
          idle = 7
        ),
        debugCd = ClockDomain.current.copy(reset = Bool().setName("debugReset")),
        jtagCd = ClockDomain.external("jtag", withReset = false),
        withTunneling = true,
        withTap = false
      )
    )

    val cpu = new VexRiscv(VexRiscvConfig(plugins.toList))
    cpu.setDefinitionName("VexRiscv_EmbeddedJtag")

    // Wishbone bus wrapper, identical to the Lite core.
    cpu.rework {
      for (p <- cpu.config.plugins) p match {
        case p: IBusCachedPlugin => {
          p.iBus.setAsDirectionLess()
          master(p.iBus.toWishbone()).setName("iBusWishbone")
        }
        case p: DBusSimplePlugin => {
          p.dBus.setAsDirectionLess()
          master(p.dBus.toWishbone()).setName("dBusWishbone")
        }
        case _ =>
      }
    }
    cpu
  }
}
