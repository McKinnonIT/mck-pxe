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
./scripts/build-bootenv.sh        # builds data/bootenv/: Docker if available, else mmdebstrap (as root, on Debian)
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

**Imaging environment.** The installer builds it automatically, without Docker, if it's missing. This takes 5–10 minutes. The build mounts `/proc` and `/sys` inside the image, so an LXC needs **Nesting** turned on (Proxmox: the container's **Options → Features**).
- **After an update that changes `bootenv/`**, such as a change to the agent, rebuild it:
  ```bash
  REBUILD_BOOTENV=yes ./scripts/install-lxc.sh
  ```
- **To skip the build** and use files built elsewhere, run the installer with `BUILD_BOOTENV=no BOOTENV_SRC=/folder/holding/them`.

**Pangolin.** Create a Newt site for mck-pxe in Pangolin. Add its `PANGOLIN_ENDPOINT`, `NEWT_ID` and `NEWT_SECRET` to `/etc/mck-pxe/mck-pxe.env` and run the script again. Then add a resource on that site with the target `http://127.0.0.1:8080` and turn on SSO. The admin UI only listens on `127.0.0.1`, so newt on the same machine is the only way in.

**Testing before Pangolin is set up.** Set `TEST_MODE=yes` in `/etc/mck-pxe/mck-pxe.env` and run the script again. The admin UI then opens at `http://SERVER_IP:8080/` with no sign-in. Anyone on that network gets full admin access, including wiping machines, so set it back to `no` and run the script again when you're done.

| Service | Logs |
|---|---|
| API | `journalctl -u mck-pxe-api` |
| PXE (proxyDHCP, TFTP) | `journalctl -u dnsmasq` |
| Pangolin tunnel | `journalctl -u mck-pxe-newt` |
| Web and file downloads | `/var/log/nginx/` |

## Using it

**The machine's screen.** Machines that boot into mck-pxe, over the network or from the USB stick, show a full-screen web interface: Firefox in kiosk mode, served by the agent on the machine itself. It shows:
- the machine's details and its disks
- whether it's connected to the server
- buttons to deploy, capture, and copy images between the server and the USB stick
- live progress and the log
- a reboot countdown that you can stop

It also works offline, from the USB stick. It only listens on the machine itself (`127.0.0.1`), so nothing else on the network can reach it.

The **text menu** is still there as a backup:
- **Automatically,** if graphics won't start: no graphics device, Firefox fails to load, or it keeps crashing.
- **From the boot menu:** choose *mck-pxe imaging environment (text mode)*. On a BIOS machine booting from the USB stick, type `text` at the `boot:` prompt.
- **From the web interface:** the **Text mode** button.

Alt+F2 gives a root login prompt on another console. Kiosk errors are logged to `/var/log/mck-kiosk.log`.

**Capturing.** PXE boot the reference machine, choose *mck-pxe imaging environment*, and it appears under **Machines**. Queue a capture there, or use the machine's screen (or press **M** in text mode). For Windows, turn off Fast Startup and hibernation first, and suspend BitLocker. For WIM captures, sysprep and shut down first.

**Deploying.** Pick a machine, an image, and for WIMs an edition, then queue it. If the machine is already sitting in mck-pxe, it starts within 5 seconds; otherwise it starts the next time the machine PXE boots. Technicians can also deploy from the machine's console. Set `AGENT_PIN` to require a PIN for that.

**Boot USB.** **Settings → Boot USB** builds `mck-pxe-boot.iso`, the imaging environment on a stick, set up to talk to this server. The machine you boot it on only needs ordinary DHCP and HTTP access to the server, so it's handy for testing connectivity, captures and deployments before PXE or DHCP relay is set up.
- **Writing the stick:** use balenaEtcher, Rufus (DD image mode) or `dd`.
- **Booting:** works on BIOS and UEFI machines, with Secure Boot on.
- **Safety:** the stick is hidden from the agent's disk list, so a deployment can't wipe it.
- **Keeping it current:** rebuild it after you rebuild the imaging environment or change `SERVER_IP`. The card tells you when it's out of date.

**Images on the stick.** These options are on the machine's screen (in text mode, press **M**):

| Option | Needs the server? |
|---|---|
| Capture this machine to the USB stick | No |
| Deploy an image from the USB stick | No |
| Copy a server image to the USB stick | Yes |
| Upload a USB image to the server | Yes |

- **Storage:** the first save adds an exFAT `MCKPXE-DATA` partition in the stick's free space, and the stick stays bootable. Use a 32 GB or larger stick. Because it's exFAT, Windows and macOS can read it too. Any other drive labelled `MCKPXE-DATA` works the same way, for example an external SSD for big images.
- **Drivers:** copying an image from the server also copies the drivers for that machine's model. To deploy offline to other models with drivers, boot each model online once and copy the image again; each run adds that model's drivers.
- **Windows WIM images:** copying one also brings the BCD template that offline deploys need.
- **Library:** an image captured offline joins the server's library when you upload it.
- **Older sticks:** sticks written from an ISO built before this feature use a different partition layout. Rebuild the ISO and write the stick again.

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
- **Intel RST storage drivers can't be injected.** Windows needs the right storage driver before it can read its own disk, and driver injection only takes effect once Windows is running. Images have to match the target's storage mode instead; see [Storage modes](#storage-modes-intel-rst-and-vmd).
- **Block-level images** need a target disk big enough for the last partition. Disk sector sizes must also match (512 vs 4K). Partitions aren't resized to fill a larger disk yet.
- **WIM deploys are UEFI only.** They create the GPT layout EFI + MSR + Windows. BIOS machines can still use block-level images.
- **Multicast** isn't implemented yet. Every transfer is unicast HTTP.
- **Secure Boot.** Some "Secured-core" PCs ship with the *Microsoft 3rd-party UEFI CA* disabled. Enable it in firmware so shim can boot.
- `SetupComplete.cmd` doesn't run on Windows activated with an OEM key on some editions. Education and Enterprise volume licensing are fine.

### Storage modes (Intel RST and VMD)

mck-pxe detects how each disk is presented to the operating system, and shows it next to the disk in the admin UI, on the machine's screen and in the text menu:

| Storage mode | What it is | Windows boot driver |
|---|---|---|
| NVMe / AHCI | Standard | `stornvme` / `storahci`, both built into Windows |
| Intel VMD | NVMe behind Intel's Volume Management Device; RST on most recent laptops | `iaStorVD` |
| Intel RST (SATA RAID mode) | Intel SATA controller set to "RAID" in the BIOS, even with one disk | `iaStorAC` |
| Intel RST RAID volume | Several disks combined into one by RST (RAID 0/1/5/10) | as for its member disks |

- **RAID volumes:** the agent assembles them with `mdadm` and treats each one as a single disk. It captures and deploys the volume as a whole, and hides the member disks so they can't be captured on their own by mistake.
  - **Read-only until a deploy:** volumes start read-only (`md_mod.start_ro=1`), so booting mck-pxe never triggers a rebuild.
  - **Marked clean afterwards:** a deploy makes the volume writable, then marks it clean when it finishes, so Windows doesn't start a verify.
  - **Create the volume first:** a deploy writes to an existing volume, so set it up in the target's BIOS RST settings beforehand.
- **Captures record their storage mode.** A Windows deploy to a disk that needs a different Intel RST driver is blocked, because it would fail to start with INACCESSIBLE_BOOT_DEVICE. Either change the target's BIOS storage setting to match, or tick **Deploy anyway**.
- **Stock Windows WIMs don't include the RST driver,** so deploying one to an RST disk shows the same warning. Switch VMD off for the deploy, or use a WIM captured from an RST machine.
- **NVMe and AHCI images mix freely,** because Windows has both drivers built in.
- **Older captures** didn't record their storage mode, so they aren't checked.

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
