# 21 - Broker: several programs on one board

This chapter explains the opt-in broker: when you need it, how to turn it
on, what it guarantees when two programs use the same core, and how to see
and stop it.

Without the broker, every `fcapz` command opens the JTAG cable itself.  Two
programs on the same board then work at the same time: hw_server, OpenOCD
and the other backends keep each scan whole, but nothing stops a second
program from re-arming or reconfiguring a core in the middle of the first
one's capture.  The broker owns the cable for all of them and runs each
operation as a job, one job per core at a time.

The broker is off by default.  Direct mode (no broker) is unchanged.

## Turning it on

Add `--broker` to a command, or set `FCAPZ_BROKER=1` in the environment
(`--no-broker` overrides the variable for one command):

```bash
fcapz --broker capture --out a.vcd --format vcd
export FCAPZ_BROKER=1      # Windows: set FCAPZ_BROKER=1
fcapz eio-read
```

The first command starts the broker, a background process of your own user
account, and later commands reuse it.  It exits on its own 60 seconds after
its last client goes away.

These commands run through the broker: `probe`, `capture`, `eio-probe`,
`eio-read`, `eio-write`, `axi-read`, `axi-write`, `axi-dump`, `axi-fill` and
`axi-load`.  The other commands that open a cable (`arm`, `configure`,
`stream`, `axi-mon`, the UART commands, `openocd-bridge`, ...) refuse to run
with the broker for now (exit code 2), and so does `--program`: program the
FPGA once without the broker, then use it.  Commands that open no cable
(`list-ports`, `axi-decode`, `capture-profile`) run as always.

Run a refused command with `--no-broker`.  On a cable only one program can
open (`ftdi`, `usb_blaster`, `serial`), stop the broker first
(`fcapz broker stop`): it keeps a cable open until it exits.

The global transport options (`--backend`, `--host`, `--port`, `--tap`,
`--hardware`, ...) choose the board as usual; the broker opens that board's
cable on first use.  Commands that name the same board share one
connection, however they spell it (`localhost` and `127.0.0.1` are the same
host; hw_server's default port 6666 is its port 3121).  A command that names
the same board with different cable settings (another `--tck-mhz`,
`--no-burst`, ...) is refused, since the cable is already open with the
first settings.  With the `ftdi` and `usb_blaster` backends, one program that
picks the adapter on its own (no `--hardware`) and another that names one
are refused too, because they might be the same adapter.

## What it guarantees

- **One job per core.**  A capture holds its ELA from configuration to
  readout, an EIO access or EJTAG-AXI transfer holds its core while it runs.
  A second command on the same core waits for its turn, in arrival order,
  and says what it waits behind:

  ```text
  waiting: queued behind job 3 (capture, client c1) on this core
  ```

  If its turn does not come within `--broker-wait` seconds (default 30), it
  fails with `CoreBusy` instead of disturbing the first one.
- **Other cores keep running.**  Each slot of an ELA core manager is its own
  core: a capture on slot 1 runs while slot 0 waits for its trigger.  An ELA
  addressed without `--ela-instance` is the manager's first ELA slot, the
  same core as naming that slot (slot 0 when the ELA comes first).
- **A client that goes away loses only its own jobs.**  Ctrl+C on a waiting
  command cancels its job (exit code 130), and a program that crashes has
  its jobs cancelled when its connection drops.  A capture cancelled while
  waiting for its trigger is driven idle before the next job gets the core,
  also one configured with `--startup-arm` (its STARTUP_ARM register is
  cleared, so the reset does not re-arm it).  A capture that fails or times
  out is left as it is, as in direct mode.  Other programs' jobs are not
  touched, and neither is the cable: a command that names a wrong chain or a
  core that is not there fails alone.
- **No silent fallback.**  When the broker cannot start, the command fails
  and shows the end of the broker's log; it never falls back to opening the
  cable itself.  When the broker dies mid-command, the command fails with
  `BrokerConnectionLost`, and the next command starts a new broker.  A
  command that arrives while the broker is stopping waits until it has
  closed its cables, then starts the next one.
- **A lost cable is a new connection.**  When the cable fails (unplugged,
  server gone), the broker reconnects for the next job, after the jobs still
  running on the old connection have ended, and counts a new *image
  generation*.  Python clients that pass the generation they saw get
  `ImageChanged` rather than talking to a core that may have been
  reprogrammed.  A capture that only times out waiting for its trigger
  keeps the connection.

Nothing is retried or re-armed on its own.

## Seeing and stopping it

```bash
fcapz broker status          # the broker, its clients, cores and queues
fcapz broker status --json
fcapz broker stop            # refused while jobs run; --force cancels them
```

Neither command starts a broker.  `status` exits with 1 when none is
running.  `stop` returns when the broker process has exited and its cables
are closed.  See the [CLI reference](10_cli_reference.md#broker).

## From Python

`fcapz.broker.BrokerSession` is the client the CLI uses:

```python
from fcapz import CaptureConfig, TriggerConfig
from fcapz.broker import BrokerSession, TargetSpec

board = TargetSpec(backend="hw_server", port=3121, tap="xc7a100t")
cfg = CaptureConfig(pretrigger=8, posttrigger=56,
                    trigger=TriggerConfig("value_match", 0x1, 0x1))

with BrokerSession.connect(name="my script") as s:
    cap = s.capture(board, cfg, timeout=10, queue_timeout=30)
    print(cap.core, len(cap.result.samples))
    cap.exporter().write_vcd(cap.result, "cap.vcd")
    print(hex(s.eio(board, "read", chain=3)["value"]))
```

`capture()` returns the `CaptureResult` with the core it came from (a
`CoreRef`: target, kind, chain, slot and image generation).  Pass
`expect_gen=cap.core.image_gen` to a later call to fail with `ImageChanged`
if the board was reconnected in between.  `on_event` receives the job's
progress (`accepted`, `queued`, `running`).  `last_capture(board)` returns
the most recent capture any client took on that chain's ELAs;
`last_capture(board, instance=1)` the last one of that slot.

The JSON-RPC server, the desktop GUI, the web interface and the MCP server
do not use the broker yet.

## Where it lives

The broker keeps its files in a per-user directory: `%LOCALAPPDATA%\fcapz\broker`
on Windows, `$XDG_RUNTIME_DIR/fcapz-broker` on Linux, otherwise a private
directory under the system temporary directory.  `FCAPZ_BROKER_DIR` sets
another one (a relative path is taken from the directory the command runs
in).  On Linux and macOS the directory must be your own, not a symbolic
link, and writable by nobody else, and so must `runtime.json`: a command
refuses anything else rather than trust it.  The directory holds:

| File | What it is |
|---|---|
| `runtime.json` | How clients reach the running broker (address, key, process ID); private to your user |
| `runtime.lock` | Ensures one broker per directory |
| `runtime.log` | The broker's log |
| `runtime-stderr.log` | What the broker printed while starting |

Clients and the broker talk over a local named pipe (Windows) or Unix
socket, authenticated with the key in `runtime.json`; nothing listens on
the network.  `FCAPZ_BROKER_IDLE_EXIT` sets how many seconds the broker
stays up after its last client (default 60).

Programs that share a board must use the same broker directory, so run them
as the same user with the same `FCAPZ_BROKER_DIR`.  On Linux the default
depends on `XDG_RUNTIME_DIR` being set: set `FCAPZ_BROKER_DIR` when some of
the programs run without a login session (cron, containers).

A program in direct mode does not go through the broker, and the broker does
not coordinate with it.  hw_server and OpenOCD serve both at once, with no
protection for a core they both use.  A cable that one program opens (`ftdi`,
`usb_blaster`, `serial`) stays the broker's from its first job on it until
the broker exits: a direct-mode command on it fails as busy until then.

The broker keeps what it read from a core while the cable stays connected.
After reprogramming the FPGA with another design, run `fcapz broker stop`
before the next command.

## What's next

- [Chapter 10 - CLI reference](10_cli_reference.md#broker): the broker
  options and subcommands.
- [Chapter 14 - Transports](14_transports.md): the backends the broker
  opens.
