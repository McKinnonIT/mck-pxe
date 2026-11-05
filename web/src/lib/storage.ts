// Storage modes and boot drivers, mirroring the agent (bootenv/agent/mck-agent).
import type { Disk, Image } from './types'

export const STORAGE_LABELS: Record<string, string> = {
  nvme: 'NVMe',
  ahci: 'AHCI',
  vmd: 'Intel VMD',
  'sata-raid-mode': 'Intel RST (SATA RAID mode)',
  'rst-raid': 'Intel RST RAID volume',
  other: 'Other',
}

const DRIVER_LABELS: Record<string, string> = {
  stornvme: 'standard NVMe',
  storahci: 'standard AHCI',
  iaStorVD: 'Intel RST with VMD',
  iaStorAC: 'Intel RST SATA RAID mode',
  generic: 'standard (no Intel RST driver)',
}

export function storageLabel(disk: Pick<Disk, 'storage' | 'raid_level'>): string {
  if (!disk.storage) return ''
  const label = STORAGE_LABELS[disk.storage] ?? disk.storage
  return disk.raid_level ? `${label}, ${disk.raid_level.toUpperCase()}` : label
}

export function driverLabel(driver?: string | null): string {
  return driver ? (DRIVER_LABELS[driver] ?? driver) : 'unknown'
}

/** Why a Windows image probably won't boot on this disk's storage mode, or null. */
export function storageMismatch(image: Image | undefined, disk: Disk | undefined): string | null {
  if (!image || !disk || image.os_family !== 'windows') return null
  const a = image.meta.storage?.boot_driver ?? (image.kind === 'wim' ? 'generic' : null)
  const b = disk.boot_driver
  if (!a || !b || a === b) return null
  if (!a.startsWith('iaStor') && !b.startsWith('iaStor')) return null // Windows has both stornvme and storahci
  return `This image was captured with ${driverLabel(a)} storage, but ${disk.path} uses ${driverLabel(b)}. Windows will probably fail to start (INACCESSIBLE_BOOT_DEVICE). Change the BIOS storage setting to match the image, or deploy anyway.`
}
