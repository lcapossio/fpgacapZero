# PolarFire SoC Discovery Kit example

fpgacapZero on the Microchip **PolarFire SoC Discovery Kit** (MPFS-DISCO-KIT,
MPFS095T-1FCSG325E), reached through the device's UJTAG user TAP over OpenOCD.
The design uses the FPGA fabric only; the MSS (the RISC-V processor subsystem)
is left unconfigured.

| Core | Where | What it sees |
|------|-------|--------------|
| ELA, 8-bit × 1024 | UJTAG USER1 (IR `0x20`) control, USER2 (IR `0x21`) burst data | free-running 8-bit counter on the 50 MHz reference clock |
| EIO, 2 in / 6 out | USER1, register offset `0x8000` | in: SWITCH1 / SWITCH2 pressed; out: LED1..LED6 |

LED7 blinks at about 1.5 Hz once the fabric is configured. Holding SWITCH1
resets the sample domain.

Built with Libero SoC 2025.2: about 1,400 4LUTs + 1,400 DFFs (1.5 %) and one
LSRAM, with timing met at 50 MHz.

## Quick start

1. **Build and program** (Libero SoC, ~3 min build plus ~1.5 min programming):

   ```bash
   python examples/mpfs_disco_kit/build.py --program
   ```

   Libero is found on `PATH`, through `$LIBERO_DIR` / `$ACTEL_SW_DIR`, or in
   the usual install folders; `--libero PATH` overrides that. Synthesis needs
   the Synplify licence. If Synplify reports `synplifypro_actel` as unavailable,
   point it at your licence server, for example
   `SNPSLMD_LICENSE_FILE=1702@localhost`.

   Programming goes through the on-board (embedded) FlashPro5. Nothing else may
   hold its JTAG channel at that moment: while OpenOCD is attached, Libero stops
   with "No programmer is connected".

2. **Start OpenOCD** with the board config:

   ```bash
   openocd -f examples/mpfs_disco_kit/mpfs_disco_kit.cfg
   ```

3. **Capture**:

   ```bash
   fcapz --backend openocd --tap MPFS095T.tap probe
   fcapz --backend openocd --tap MPFS095T.tap capture \
       --pretrigger 8 --posttrigger 23 --trigger-value 0x40 --trigger-mask 0xFF \
       --out ramp.vcd --format vcd
   ```

   A tap name starting with `MPF` selects the PolarFire IR table
   (`OpenOcdTransport.IR_TABLE_POLARFIRE`). In Python:

   ```python
   from fcapz.analyzer import Analyzer, CaptureConfig, TriggerConfig
   from fcapz.eio import EioController
   from fcapz.transport import OpenOcdTransport

   t = OpenOcdTransport(tap="MPFS095T.tap", ir_table=OpenOcdTransport.IR_TABLE_POLARFIRE)
   a = Analyzer(t, chain=1)
   a.connect()
   a.configure(CaptureConfig(pretrigger=8, posttrigger=23, sample_width=8, depth=1024,
                             trigger=TriggerConfig(mode="value_match", value=0x40, mask=0xFF)))
   a.arm()
   print([s & 0xFF for s in a.capture(timeout=10.0).samples])

   eio = EioController(t, chain=1, base_addr=0x8000)
   eio.attach()
   eio.write_outputs(0x15)       # LED1, LED3, LED5
   a.close()
   ```

4. **Hardware tests** (with OpenOCD running):

   ```bash
   python -m pytest examples/mpfs_disco_kit/test_hw_integration.py -v
   ```

## Host access on Windows

`mpfs_disco_kit.cfg` uses OpenOCD's stock `ftdi` driver and
`interface/microchip/embedded_flashpro5.cfg` (OpenOCD 0.12 or later). The
on-board FlashPro5 is an FTDI FT4232H, and JTAG is on its channel A.

- **Linux:** OpenOCD opens channel A directly.
- **Windows:** Microchip's FlashPro driver owns channel A, so OpenOCD's `ftdi`
  driver cannot open it ("unable to open ftdi device"). Replacing the
  channel-A driver with WinUSB (for example with Zadig) lets OpenOCD in, but
  Libero and FlashPro Express then stop seeing the programmer until the
  Microchip driver is restored.

**Validation status:** the RTL, the IR table and the whole host stack were
validated on this board over OpenOCD, through a `remote_bitbang` adapter on
Windows; all 11 hardware tests pass. `mpfs_disco_kit.cfg` itself, the `ftdi`
path, has not yet been run on hardware.

## Things to know about PolarFire

- **One UJTAG per device.** The ELA and EIO cannot each have their own
  wrapper; set `EIO_EN=1` on `fcapz_ela_polarfire` and the EIO shares USER1 at
  offset `0x8000`, as this design does.
- **JTAG pins go to top-level ports.** `fcapz_ela_polarfire` has
  `tck_pad_i` / `tms_pad_i` / `tdi_pad_i` / `trstb_pad_i` / `tdo_pad_o`. Wire
  them to top-level ports named for the pins (`TCK`, `TMS`, `TDI`, `TRSTB`,
  `TDO`). Libero binds them to the dedicated JTAG pins, so the PDC leaves them
  out.
- **User IRs.** UJTAG passes IRs 0x10..0x7F to the fabric. On PolarFire SoC
  the MSS debug module answers at 0x10 / 0x11, so the wrappers default to
  0x20 / 0x21. Microchip's CoreJTAGDebug uses 0x55..0x64. The OpenOCD config
  declares the TAP only, with no RISC-V target, so OpenOCD never scans the MSS
  IRs.
- **eNVM.** Programming this fabric-only design replaces whatever the device
  held before, including MSS firmware in eNVM.
- **Readback speed.** `OpenOcdTransport` reads samples word by word over
  USER1; it does not use the USER2 burst chain yet. Each sample costs one
  register read, so a full 1024-sample window takes far longer than a short
  capture.

## Files

| File | Purpose |
|------|---------|
| `mpfs_disco_kit_top.v` | top level: counter probe, ELA + shared-chain EIO, LEDs, JTAG pins |
| `mpfs_disco_kit_io.pdc` | pins and bank voltages, from Microchip's Discovery Kit reference design |
| `mpfs_disco_kit.sdc` | 50 MHz reference clock, 6 MHz TCK, asynchronous clock groups |
| `build_mpfs_disco_kit.tcl` | Libero batch flow (project under `libero/`, git-ignored) |
| `program_mpfs_disco_kit.tcl` | programs the last build through FlashPro |
| `build.py` | finds Libero and runs the two scripts |
| `mpfs_disco_kit.cfg` | OpenOCD: embedded FlashPro5, MPFS095T TAP only |
| `test_hw_integration.py` | hardware tests (skipped with `FPGACAP_SKIP_HW=1`) |
