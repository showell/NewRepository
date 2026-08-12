# Run a compiled CDX under QEMU, bridging this terminal to the guest serial.
#   python3 run_codex.py <kernel.cdx>            interactive (type answers)
#   echo Mars | python3 run_codex.py <kernel.cdx>  piped
import os
import select
import socket
import subprocess
import sys
import time

KERNEL = sys.argv[1]
MEM_MB = 1024
DATA_PORT, CTRL_PORT = 56600, 56601

qemu = subprocess.Popen([
    "qemu-system-x86_64", "-accel", "tcg",
    "-machine", "kernel-irqchip=off", "-kernel", KERNEL,
    "-chardev", f"socket,id=ch0,host=127.0.0.1,port={DATA_PORT},server=on,wait=on,nodelay=on",
    "-chardev", f"socket,id=ch1,host=127.0.0.1,port={CTRL_PORT},server=on,wait=on,nodelay=on",
    "-serial", "chardev:ch0", "-serial", "chardev:ch1",
    "-device", "isa-debug-exit,iobase=0xf4,iosize=0x04",
    "-netdev", "user,id=net0",
    "-device", "ne2k_isa,netdev=net0,irq=9,iobase=0x300,mac=52:54:00:12:34:56",
    "-device", f"loader,addr=0xfe8,data={hex(MEM_MB*1024*1024)},data-len=4",
    "-cpu", "max",
    "-display", "none", "-no-reboot", "-m", str(MEM_MB),
], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def connect(port):
    for _ in range(60):
        if qemu.poll() is not None:
            sys.exit("qemu exited early")
        try:
            return socket.create_connection(("127.0.0.1", port), timeout=1)
        except OSError:
            time.sleep(0.25)
    sys.exit(f"no connection on {port}")

data = connect(DATA_PORT)
ctrl = connect(CTRL_PORT)

try:
    quiet_since = time.time()
    saw_output = False
    while True:
        readable, _, _ = select.select([data, sys.stdin], [], [], 0.5)
        if data in readable:
            chunk = data.recv(4096)
            if not chunk:
                break
            text = chunk.decode(errors="replace")
            kept = "".join(l for l in text.splitlines(keepends=True)
                           if not l.startswith(("WD:", "HEAP:", "STACK:")))
            sys.stdout.write(kept)
            sys.stdout.flush()
            saw_output = True
            quiet_since = time.time()
        if sys.stdin in readable:
            line = sys.stdin.readline()
            if not line:  # EOF on piped input: keep draining output
                if time.time() - quiet_since > 3 and saw_output:
                    break
                continue
            data.sendall(line.encode())
            quiet_since = time.time()
        if qemu.poll() is not None:
            break
        if saw_output and time.time() - quiet_since > 5 and not os.isatty(0):
            break
finally:
    qemu.kill()
