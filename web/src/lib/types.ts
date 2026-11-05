export interface Disk {
  path: string
  size: number
  model: string
  serial?: string
  transport?: string
  removable?: boolean
  storage?: string | null
  boot_driver?: string | null
  raid_level?: string | null
  members?: string[]
}

export interface StorageInfo {
  storage?: string | null
  boot_driver?: string | null
  raid_level?: string | null
}

export interface TaskSummary {
  id: number
  type: 'capture' | 'deploy'
  kind: 'block' | 'wim'
  disk: string
  params: Record<string, any>
  status: string
  progress: number
  message: string
  cancel_requested: boolean
  created_by: string
  created_at: string
  started_at: string | null
  finished_at: string | null
  host: { id: number; name: string; model: string } | null
  image: { id: number; name: string } | null
  log?: string
}

export interface Host {
  id: number
  mac: string
  name: string
  ip: string | null
  manufacturer: string
  model: string
  sku: string
  serial: string
  cpu: string
  ram_mb: number
  boot_mode: string
  secure_boot: boolean
  disks: Disk[]
  hardware_id_count: number
  hardware_ids?: string[]
  notes: string
  first_seen: string
  last_seen: string
  online: boolean
  task?: TaskSummary | null
  tasks?: TaskSummary[]
}

export interface WimIndex {
  index: number
  name: string
  description?: string
  bytes?: number
}

export interface Image {
  id: number
  name: string
  description: string
  kind: 'block' | 'wim'
  os_family: string
  status: string
  error: string
  size_bytes: number
  meta: { indexes?: WimIndex[]; partitions?: any[]; table?: string; required_bytes?: number; storage?: StorageInfo }
  has_unattend: boolean
  unattend?: string
  source: string
  created_by: string
  created_at: string
}

export interface DriverPack {
  id: number
  name: string
  manufacturer: string
  model_match: string
  enabled: boolean
  status: string
  error: string
  filename: string
  size_bytes: number
  driver_count: number
  classes: string[]
  created_by: string
  created_at: string
  drivers?: { id: number; inf_path: string; class_name: string; provider: string; version: string; hardware_id_count: number }[]
}
