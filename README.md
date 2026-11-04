# mck-pxe

Network imaging for Windows and Linux machines. Machines PXE boot into a small Linux environment that captures or deploys disk images at network speed. You run it from a web admin UI, or from the console of the PXE-booted machine.

- **Block-level images** use partclone and zstd. Only used blocks are copied, so this is the fastest way to clone identical hardware. Works with NTFS, FAT, ext2/3/4, XFS, Btrfs and exFAT, and copies anything else raw.
- **Windows WIM images** use wimlib. They're hardware independent: upload `install.wim` or `install.esd` from Windows media, or capture a sysprepped reference machine. Every edition in the WIM can be deployed.
- **Automatic driver injection.** Upload vendor driver packs or a general driver library. On each Windows deploy, the machine gets the drivers for its model and hardware IDs.
- **Secure Boot stays on.** UEFI machines boot Microsoft-signed shim, then Debian-signed GRUB and kernel.
- **proxyDHCP**, so your existing DHCP server is left alone.

## How it works

```
PXE client ──DHCP──▶ existing DHCP server          (IP address)
           ──PXE───▶ boot   (dnsmasq proxyDHCP)    (which boot loader)
           ──TFTP──▶ boot                          (shim+GRUB for UEFI / iPXE for BIOS)
           ──HTTP──▶ web:80 /api/boot/…            (per-machine menu)
           ──HTTP──▶ web:80 /boot/…                (kernel, initrd, squashfs)
           ──HTTP──▶ web:80 /api/agent/…           (agent: register, tasks, uploads)
           ──HTTP──▶ web:80 /files/images/…        (image downloads, served by nginx)

Admin ─Pangolin─▶ newt ──▶ mck-pxe:8080 (web) ──▶ api (FastAPI) ──▶ db (PostgreSQL)
```

| Service | What it does |
|---|---|
| `boot` | dnsmasq in proxyDHCP mode with TFTP. Uses host networking. |
| `web` | nginx. Port 80 serves the imaging network. Port 8080 serves the admin UI (Vue + shadcn-vue) and has no host port; it's only reachable from the newt's network. |
| `api` | FastAPI. Handles tasks, the driver library and WIM processing. |
| `db` | PostgreSQL |
| `bootenv/` | Builds the PXE imaging environment: a Debian trixie live system and the `mck-agent` script. |

When a machine has a task queued, its boot menu goes straight into imaging. Otherwise the menu defaults to the local disk after 5 seconds, so it's safe to leave PXE first in the boot order.

## Setup

You need a **Linux** Docker host (Debian recommended) with an address on the imaging network. Docker Desktop on macOS can't do proxyDHCP because it doesn't support host networking on the LAN.

```bash
cp .env.example .env              # set SERVER_IP (an IP, not a hostname), PXE_SUBNET, POSTGRES_PASSWORD, PANGOLIN_NETWORK
./scripts/build-bootenv.sh        # builds data/bootenv/ (about 5 minutes on x86_64)
docker compose up -d --build
```

Then:

1. **Connect the admin UI to Pangolin.** mck-pxe has no login page. Pangolin signs people in with Google and passes their identity in a `Remote-Email` header, which mck-pxe trusts. The admin UI therefore has no host port, and Pangolin's newt reaches it over Docker's network instead:
   1. Find the Docker network of the newt container Pangolin uses on this server:
      ```bash
      docker ps --format '{{.Names}}  {{.Networks}}' | grep -i newt
      ```
   2. Put that network name in `.env` as `PANGOLIN_NETWORK`, then run `docker compose up -d`.
   3. In Pangolin, add a resource on that newt's site with the target `http://mck-pxe:8080`, and turn on SSO.
   4. Optionally set `ADMIN_DOMAIN` or `ADMIN_EMAILS` in `.env` as a second lock on who can get in. Leave `DEV_USER` empty.
2. For WIM deployments, run `tools/make-generic-bcd.ps1` as Administrator on any Windows PC, then upload the `BCD` file it creates under **Settings**. See [Windows boot files](#windows-boot-files) for why.
3. On the network, make sure PXE broadcasts reach this server: same VLAN, or an IP helper / DHCP relay pointing at `SERVER_IP` as well as your DHCP server.

## Install without Docker (LXC or VM)

`scripts/install-lxc.sh` installs mck-pxe directly on Debian 12 or 13. It sets up PostgreSQL, the API as a systemd service, nginx, dnsmasq and, optionally, newt. This suits an LXC with a network interface on the imaging VLAN: PXE broadcasts reach it directly, with no relay needed.

Suggested LXC: Debian 13, 2–4 cores, 4 GB RAM, about 20 GB for the system, plus a separate mount at `/var/lib/mck-pxe/images` for images. Give it a static IP on the imaging VLAN. An unprivileged container is fine.

```bash
apt-get install -y git
git clone https://github.com/McKinnonIT/mck-pxe.git && cd mck-pxe
./scripts/install-lxc.sh
```

Run it as root. It detects the IP address and subnet, generates a database password, and saves everything in `/etc/mck-pxe/mck-pxe.env`. Edit that file to change anything, then run the script again. To update, `git pull` and run the script again.

**Imaging environment.** Building it needs Docker, so build it on another machine with `scripts/build-bootenv.sh` and copy the three files across:
```bash
scp sysadmin@docker04:~/mck-pxe/data/bootenv/* /var/lib/mck-pxe/bootenv/
```
Alternatively, run the installer with `BOOTENV_SRC=/folder/holding/them`.

**Pangolin.** Create a Newt site for mck-pxe in Pangolin. Add its `PANGOLIN_ENDPOINT`, `NEWT_ID` and `NEWT_SECRET` to `/etc/mck-pxe/mck-pxe.env` and run the script again. Then add a resource on that site with the target `http://127.0.0.1:8080` and turn on SSO. The admin UI only listens on `127.0.0.1`, so newt on the same machine is the only way in.

**Testing before Pangolin is set up.** Set `TEST_MODE=yes` in `/etc/mck-pxe/mck-pxe.env` and run the script again. The admin UI then opens at `http://SERVER_IP:8080/` with no sign-in. Anyone on that network gets full admin access, including wiping machines, so set it back to `no` and run the script again when you're done.

| Service | Logs |
|---|---|
| API | `journalctl -u mck-pxe-api` |
| PXE (proxyDHCP, TFTP) | `journalctl -u dnsmasq` |
| Pangolin tunnel | `journalctl -u mck-pxe-newt` |
| Web and file downloads | `/var/log/nginx/` |

## Using it

**Capturing.** PXE boot the reference machine, choose *mck-pxe imaging environment*, and it appears under **Machines**. Queue a capture there, or press **M** on the machine's console. For Windows, turn off Fast Startup and hibernation first, and suspend BitLocker. For WIM captures, sysprep and shut down first.

**Deploying.** Pick a machine, an image, and for WIMs an edition, then queue it. If the machine is already sitting in mck-pxe, it starts within 5 seconds; otherwise it starts the next time the machine PXE boots. Technicians can also deploy from the machine's console. Set `AGENT_PIN` to require a PIN for that.

**Drivers.** Upload a pack on the **Drivers** page. The supported formats are zip, cab, 7z, tar, and most Dell, HP and Lenovo `.exe` packs.
- If you fill in **Model match** (for example `21K5, ThinkPad E14 Gen 6`, matched against the machine's model and SKU), every driver in the pack goes to those machines.
- If you leave it empty, the pack becomes a **library**: each machine only gets the drivers whose INF hardware IDs match its PCI, USB, HD Audio and ACPI devices.

**Models seen** lists every model that has PXE booted and flags the ones with no drivers assigned. Each machine's page previews exactly what it would get.

Drivers are copied to `C:\Drivers\mck-pxe`. Windows installs them two ways:
- `DevicePath` in the offline registry, so they're picked up during first-boot device setup.
- `pnputil /add-driver … /install` in `SetupComplete.cmd`, as a backstop.

Injection works for both WIM and block-level Windows images.

## Limitations and things to know

- **Not yet tested on real hardware.** The backend, agent logic and UI have tests, but the PXE boot chain and the imaging environment haven't been run against physical machines. Do your first runs on a spare machine.
- **Boot-critical storage drivers**, such as Intel RST/VMD, can't be injected this way because Windows needs them before it can read its own disk. Switch the BIOS from RAID/VMD to AHCI, or use an image that already has the driver.
- **Block-level images** need a target disk big enough for the last partition. Disk sector sizes must also match (512 vs 4K). Partitions aren't resized to fill a larger disk yet.
- **WIM deploys are UEFI only.** They create the GPT layout EFI + MSR + Windows. BIOS machines can still use block-level images.
- **Multicast** isn't implemented yet. Every transfer is unicast HTTP.
- **Secure Boot.** Some "Secured-core" PCs ship with the *Microsoft 3rd-party UEFI CA* disabled. Enable it in firmware so shim can boot.
- `SetupComplete.cmd` doesn't run on Windows activated with an OEM key on some editions. Education and Enterprise volume licensing are fine.

### Windows boot files

Linux can't run `bcdboot`. After applying a WIM, mck-pxe copies the boot files from the image to the EFI partition, then installs the generic BCD you uploaded. That BCD finds `\Windows\system32\winload.efi` on any partition, so one BCD works for every machine and disk.

## Security

- The imaging network (port 80) is unauthenticated, as PXE clients can't log in. Anyone on that network can download images and, without `AGENT_PIN`, start tasks from a machine's console. Keep imaging on a trusted VLAN, and don't bake secrets into images.
- Only port 8080 serves admin endpoints, and it's only reachable on the newt's Docker network. Never publish it as a host port: anyone who can reach it directly could fake the `Remote-Email` header.

## Development

```bash
cd app && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt && cd ..
app/.venv/bin/pytest                         # backend tests (SQLite, no Docker)
app/.venv/bin/ruff check app tests bootenv/agent/mck-agent

# API with a fake admin user, plus the UI with hot reload
cd app && DATABASE_URL=sqlite:///dev.db DATA_DIR=../data DEV_USER=you@example.com .venv/bin/uvicorn mckpxe.main:app --reload
cd web && npm install && npm run dev
```

Tables are created on startup. There are no migrations yet; add Alembic before making the first schema change on a live system.
