// mck-pxe machine UI. Talks only to the agent on this machine (127.0.0.1).
'use strict'

const $ = (sel) => document.querySelector(sel)
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c])

let state = null // /api/state
let usb = null // /api/usb
let serverImages = [] // /api/server-images
let flow = null // the open form: { kind: 'deploy' | 'capture' | 'copy', ... }

// Storage modes: same rules as the agent's storage_mismatch()
const STORAGE = { nvme: 'NVMe', ahci: 'AHCI', vmd: 'Intel VMD', 'sata-raid-mode': 'Intel RST (SATA RAID mode)', 'rst-raid': 'Intel RST RAID volume', other: 'Other' }
const DRIVERS = { stornvme: 'standard NVMe', storahci: 'standard AHCI', iaStorVD: 'Intel RST with VMD', iaStorAC: 'Intel RST SATA RAID mode', generic: 'standard (no Intel RST driver)' }

// Server actions need the server and a server account (not the USB's offline one)
const serverOk = () => state.online && !state.user?.offline

function storageLabel(d) {
  if (!d?.storage) return ''
  return (STORAGE[d.storage] || d.storage) + (d.raid_level ? `, ${d.raid_level.toUpperCase()}` : '')
}

// BitLocker recovery keys: 8 groups of 6 digits, each a multiple of 11 (same check as the agent)
function normaliseRecoveryKey(text) {
  const digits = String(text || '').replace(/\D/g, '')
  if (digits.length !== 48) return null
  const groups = digits.match(/.{6}/g)
  return groups.every((g) => +g % 11 === 0) ? groups.join('-') : null
}

function storageMismatch(image, disk) {
  if (!image || !disk || image.os_family !== 'windows') return null
  const a = image.meta?.storage?.boot_driver || (image.kind === 'wim' ? 'generic' : null)
  const b = disk.boot_driver
  if (!a || !b || a === b) return null
  if (!a.startsWith('iaStor') && !b.startsWith('iaStor')) return null
  return `This image was captured with ${DRIVERS[a] || a} storage, but ${disk.path} uses ${DRIVERS[b] || b}. ` +
    'Windows will probably fail to start (INACCESSIBLE_BOOT_DEVICE). Change the BIOS storage setting to match the image, or deploy anyway.'
}

function bytes(n) {
  if (!n) return '—'
  const u = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  while (n >= 1000 && i < u.length - 1) { n /= 1000; i++ }
  return `${n.toFixed(n < 10 && i ? 1 : 0)} ${u[i]}`
}

async function call(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`)
  return data
}

function toast(text, bad = false) {
  const t = $('#toast')
  t.textContent = text
  t.className = bad ? 'bad' : ''
  t.hidden = false
  clearTimeout(toast.timer)
  toast.timer = setTimeout(() => (t.hidden = true), bad ? 7000 : 3500)
}

function confirmBox({ title, text, ok = 'Continue', danger = false }) {
  return new Promise((resolve) => {
    const m = $('#modal')
    m.innerHTML = `<div class="card"><h2>${esc(title)}</h2><p>${text}</p>
      <div class="row" style="justify-content:flex-end">
        <button class="btn outline" data-r="0">Cancel</button>
        <button class="btn ${danger ? 'danger' : ''}" data-r="1">${esc(ok)}</button></div></div>`
    m.hidden = false
    m.onclick = (e) => {
      const r = e.target.dataset?.r
      if (r === undefined && e.target !== m) return
      m.hidden = true
      resolve(r === '1')
    }
  })
}

// --------------------------------------------------------------------------- rendering

// Only touch the DOM when the content changed: replacing buttons every second
// would swallow clicks that land mid-redraw.
function setHTML(el, html) {
  if (el._html === html) return false
  el.innerHTML = html
  el._html = html
  return true
}

function renderTop() {
  const hw = state.hw || {}
  const online = state.online
  const usbPill = !usb ? '' : usb.ready
    ? `<span class="pill"><span class="dot ok"></span>USB · ${bytes(usb.free)} free</span>`
    : usb.can_create
      ? `<span class="pill"><span class="dot warn"></span>USB · not prepared</span>`
      : ''
  setHTML($('#top'), `
    <img src="logo.svg" alt="" />
    <div><div class="model">${esc(hw.manufacturer)} ${esc(hw.model)}</div>
      <div class="muted mono">${esc(hw.mac)} · ${esc(hw.ip || 'no IP address')}</div></div>
    <span class="spacer"></span>
    ${usbPill}
    <span class="pill" title="${esc(state.status)}"><span class="dot ${online ? 'ok' : 'bad'}"></span>
      ${online ? `Server ${esc(state.server.replace('http://', ''))}` : 'Offline'}</span>
    ${state.user ? `<span class="pill">${esc(state.user.name)}</span>
      <button class="btn sm outline" data-action="sign-out">Sign out</button>` : ''}`)
}

function machineCard() {
  const hw = state.hw || {}
  const disks = (hw.disks || []).map((d) =>
    `<div class="item"><div class="grow"><div class="mono">${esc(d.path)}</div>
      <div class="muted">${bytes(d.size)} ${esc(d.model)}</div></div>
      ${d.bitlocker ? '<span class="tag">BitLocker</span>' : ''}
      ${d.storage ? `<span class="tag">${esc(storageLabel(d))}</span>` : ''}</div>`).join('')
  return `<div class="card"><h3>This machine</h3><dl>
    <dt>Serial</dt><dd>${esc(hw.serial || '—')}</dd>
    <dt>CPU</dt><dd>${esc(hw.cpu)}</dd>
    <dt>Memory</dt><dd>${((hw.ram_mb || 0) / 1024).toFixed(1)} GB</dd>
    <dt>Boot</dt><dd>${esc((hw.boot_mode || '').toUpperCase())}, Secure Boot ${hw.secure_boot ? 'on' : 'off'}</dd>
    </dl><div class="section-title" style="margin-top:16px">Disks</div>
    <div class="list">${disks || '<div class="item muted">No disks found</div>'}</div></div>`
}

function usbCard() {
  if (!usb) return '<div class="card"><h3>USB stick</h3><p class="muted">Checking…</p></div>'
  if (!usb.ready) {
    return `<div class="card"><h3>USB stick</h3>
      ${usb.can_create
        ? `<p>Store images on the boot stick so you can capture and deploy without the server.
           This adds a ${bytes(usb.size)} storage partition in its free space; the stick stays bootable.</p>
           <button class="btn outline" data-action="usb-prepare">Prepare USB storage</button>`
        : `<p class="muted">${esc(usb.reason)}</p>`}</div>`
  }
  const rows = usb.images.map((i, n) => `
    <div class="item"><div class="grow"><div><b>${esc(i.name)}</b></div>
      <div class="muted">${i.kind === 'wim' ? 'WIM' : 'Block'} · ${esc(i.os_family)} · ${bytes(i.size)}
        ${i.drivers ? ` · ${i.drivers} drivers for this model` : ''}</div></div>
      ${serverOk() && !i.on_server ? `<button class="btn sm outline" data-action="usb-upload" data-value="${n}">Upload to server</button>` : ''}
      ${i.on_server ? '<span class="tag">On server</span>' : ''}
    </div>`).join('')
  return `<div class="card"><div class="row" style="margin-bottom:12px"><h3 style="margin:0">Images on the USB stick</h3>
      <span class="spacer"></span><span class="muted">${bytes(usb.free)} free</span>
      ${serverOk() ? '<button class="btn sm outline" data-action="open-copy">Copy from server</button>' : ''}</div>
    <div class="list">${rows || '<div class="item muted">No images yet</div>'}</div></div>`
}

function renderHome() {
  const offline = !state.online
    ? `<div class="banner info" style="margin-bottom:20px">Can't reach the server (${esc(state.status)}). You can still use images on the USB stick.</div>`
    : state.user.offline
      ? `<div class="banner info" style="margin-bottom:20px">You're signed in with the USB stick's offline account, so you can only use images on the stick.
          Sign out and sign in with your server account to use the server.</div>` : ''
  setHTML($('#main'), `${offline}<div class="grid">${machineCard()}<div class="stack">
    <div class="tiles">
      <button class="tile" data-action="open-deploy"><div class="big">Deploy an image</div>
        <div class="muted">Erase a disk and install an image from the server or the USB stick</div></button>
      <button class="tile" data-action="open-capture"><div class="big">Capture this machine</div>
        <div class="muted">Save this machine's disk as a new image on the server or the USB stick</div></button>
    </div>${usbCard()}</div></div>`)
}

function renderJob() {
  const j = state.job
  // The frame (title, buttons, result) only changes with the job's state or the
  // countdown; progress and log are updated in place.
  const secs = j.after_at ? Math.max(0, Math.ceil(j.after_at - Date.now() / 1000)) : null
  setHTML($('#main'), jobFrame(j, secs))
  $('#job-bar').style.width = `${Math.min(j.progress || 0, 100)}%`
  $('#job-pct').textContent = `${Math.round(j.progress || 0)}%`
  $('#job-msg').textContent = j.state === 'running' ? j.message : ''
  const log = $('#job-log')
  const text = j.log.join('\n')
  if (log.textContent !== text) {
    const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 30
    log.textContent = text
    if (atBottom) log.scrollTop = log.scrollHeight
  }
}

function jobFrame(j, secs) {
  let result = ''
  if (j.state === 'done' || j.state === 'failed') {
    result = `<div class="banner ${j.state === 'done' ? 'ok' : 'bad'}">${j.state === 'done' ? 'Finished' : 'Failed'}: ${esc(j.message)}</div>
      <div class="row">
        ${j.after ? `<span>${j.after === 'reboot' ? 'Rebooting' : 'Powering off'} in ${secs} s</span>
          <button class="btn outline" data-action="after-cancel">Stay here</button>
          <button class="btn" data-action="power" data-value="${j.after}">${j.after === 'reboot' ? 'Reboot' : 'Power off'} now</button>`
          : `<button class="btn" data-action="dismiss">Done</button>`}
      </div>`
  }
  return `<div class="stack" style="max-width:900px;margin:0 auto">
    <div class="row"><h2>${esc(j.title)}</h2><span class="spacer"></span>
      ${j.state === 'running' ? '<button class="btn outline" data-action="cancel">Cancel</button>' : ''}</div>
    <div class="bar"><div id="job-bar"></div></div>
    <div class="row"><span id="job-msg"></span><span class="spacer"></span><b id="job-pct"></b></div>
    ${result}
    <pre class="log mono" id="job-log"></pre></div>`
}

// --------------------------------------------------------------------------- forms

function diskOptions(selected) {
  return (state.hw.disks || []).map((d) =>
    `<option value="${esc(d.path)}" ${d.path === selected ? 'selected' : ''}>${esc(d.path)} · ${bytes(d.size)} ${esc(d.model)}${d.storage ? ` · ${esc(storageLabel(d))}` : ''}</option>`).join('')
}

function seg(name, value, options) {
  return `<div class="seg">${options.map(([v, label, disabled]) =>
    `<button data-set="${name}" data-value="${v}" class="${v === value ? 'on' : ''}" ${disabled ? 'disabled' : ''}>${esc(label)}</button>`).join('')}</div>`
}

function imageList(images, selected) {
  if (!images.length) return '<div class="list"><div class="item muted">No images available</div></div>'
  return `<div class="list">${images.map((i, n) => `
    <button class="item ${n === selected ? 'selected' : ''}" data-set="image" data-value="${n}">
      <div class="grow"><b>${esc(i.name)}</b><div class="muted">${i.kind === 'wim' ? 'WIM' : 'Block'} · ${esc(i.os_family)}
        ${i.size || i.size_bytes ? ` · ${bytes(i.size || i.size_bytes)}` : ''}${i.drivers ? ` · ${i.drivers} drivers for this model` : ''}</div></div>
    </button>`).join('')}</div>`
}

function flowImages() {
  return flow.source === 'usb' ? (usb?.images || []) : serverImages
}

function renderFlow() {
  const f = flow
  const usbOk = usb && (usb.ready || (f.kind === 'capture' && usb.can_create))
  let body = ''
  if (f.kind === 'deploy') {
    const images = flowImages()
    const img = images[f.image]
    const indexes = img ? (img.indexes || img.meta?.indexes || []) : []
    body = `
      <div><div class="section-title">From</div>${seg('source', f.source, [['server', 'Server', !serverOk()], ['usb', 'USB stick', !usb?.ready]])}</div>
      <div><div class="section-title">Image</div>${imageList(images, f.image)}</div>
      ${img && img.kind === 'wim' && indexes.length > 1 ? `<label class="field">Windows edition<select data-field="wim_index">
        ${indexes.map((ix) => `<option value="${ix.index}" ${+f.wim_index === ix.index ? 'selected' : ''}>${ix.index}: ${esc(ix.name)}</option>`).join('')}</select></label>` : ''}
      ${img && img.os_family === 'windows' ? `<label class="check"><input type="checkbox" data-field="inject" ${f.inject ? 'checked' : ''} />
        <span>Inject drivers for this machine${f.source === 'usb' ? (img.drivers ? ` (${img.drivers} on the stick)` : ' (none on the stick for this model)') : ' (matched automatically)'}</span></label>` : ''}`
  } else if (f.kind === 'capture') {
    body = `
      <div><div class="section-title">Save to</div>${seg('source', f.source, [['server', 'Server', !serverOk()], ['usb', 'USB stick', !usbOk]])}</div>
      <label class="field">Image name<input type="text" data-field="name" value="${esc(f.name)}" /></label>
      <div><div class="section-title">Type</div>${seg('ckind', f.ckind, [['block', 'Whole disk (fastest)'], ['wim', 'Windows WIM']])}
        <p class="muted">${f.ckind === 'wim'
          ? 'Hardware independent. Sysprep the machine first.'
          : 'Block-level copy of every partition. Best for identical hardware.'}</p></div>
      <div class="banner info"><b>Before capturing a Windows machine</b>
        <ul style="margin:6px 0 0;padding-left:20px">
          <li><b>BitLocker must be turned off</b> and the drive fully decrypted (in Windows: Settings → Privacy &amp; security →
            Device encryption, or <span class="mono">manage-bde -off C:</span>), <b>or</b> enter the drive's recovery key
            below when asked. Suspending BitLocker isn't enough.</li>
          <li>Windows must have been shut down fully, with Fast Startup and hibernation off.</li>
        </ul></div>`
  } else if (f.kind === 'copy') {
    body = `<p class="muted">The image is copied to the USB stick along with the drivers for this model (${esc(state.hw.model)}).
      Copy it again from other models to add their drivers.</p>
      <div><div class="section-title">Server image</div>${imageList(serverImages, f.image)}</div>`
  }
  const needsDisk = f.kind !== 'copy'
  const mismatch = flowMismatch()
  const after = f.kind === 'deploy' || (f.kind === 'capture' && f.source === 'server')
  const titles = { deploy: 'Deploy an image', capture: 'Capture this machine', copy: 'Copy a server image to the USB stick' }
  setHTML($('#main'), `<div class="form">
    <div class="row"><h2>${titles[f.kind]}</h2></div>
    ${body}
    ${needsDisk ? `<label class="field">${f.kind === 'deploy' ? 'Disk to erase' : 'Disk to capture'}
      <select data-field="disk">${diskOptions(f.disk)}</select></label>` : ''}
    ${f.kind === 'capture' && selectedDisk()?.bitlocker ? `<div class="banner info">
      <b>BitLocker is on for this disk.</b> Enter its 48-digit recovery key to capture it decrypted, or go back and turn
      BitLocker off in Windows first. The key stays on this machine (it isn't sent to the server or saved), and the image
      is saved unencrypted.
      <label class="field" style="margin-top:10px">Recovery key
        <input type="text" class="mono" data-field="bitlocker_key" value="${esc(f.bitlocker_key)}"
          placeholder="123456-123456-123456-123456-123456-123456-123456-123456" autocomplete="off" spellcheck="false" /></label>
    </div>` : ''}
    ${after ? `<label class="field">When finished<select data-field="after">
      ${[['reboot', 'Reboot'], ['poweroff', 'Power off'], ['wait', 'Stay in mck-pxe']].map(([v, l]) =>
        `<option value="${v}" ${f.after === v ? 'selected' : ''}>${l}</option>`).join('')}</select></label>` : ''}
    ${mismatch ? `<div class="banner bad"><b>Storage mode mismatch.</b> ${esc(mismatch)}
      <label class="check" style="margin-top:10px;color:var(--fg)"><input type="checkbox" data-field="allow" ${f.allow ? 'checked' : ''} />
      <span>Deploy anyway</span></label></div>` : ''}
    <div class="row"><button class="btn outline lg" data-action="close">Back</button>
      <button class="btn lg ${f.kind === 'deploy' ? 'danger' : ''}" data-action="submit">
        ${f.kind === 'deploy' ? 'Erase and deploy' : f.kind === 'capture' ? 'Start capture' : 'Copy to USB'}</button></div>
  </div>`)
}

function selectedDisk() {
  return flow && (state.hw.disks || []).find((d) => d.path === flow.disk)
}

function flowMismatch() {
  if (!flow || flow.kind !== 'deploy') return null
  return storageMismatch(flowImages()[flow.image], (state.hw.disks || []).find((d) => d.path === flow.disk))
}

async function openFlow(kind) {
  const disks = state.hw.disks || []
  const defaultDisk = (disks.find((d) => !d.removable) || disks[0] || {}).path
  const source = serverOk() ? 'server' : 'usb'
  flow = { kind, source, image: null, disk: defaultDisk, inject: true, after: kind === 'deploy' ? 'reboot' : 'wait',
    name: `${state.hw.model || 'Image'} ${new Date().toISOString().slice(0, 10)}`, ckind: 'block', allow: false, bitlocker_key: '' }
  if (serverOk() && kind !== 'capture') serverImages = await call('GET', '/api/server-images').catch(() => [])
  renderFlow()
}

async function submitFlow() {
  const f = flow
  const hw = state.hw
  const disk = (hw.disks || []).find((d) => d.path === f.disk)
  const images = f.kind === 'copy' ? serverImages : flowImages()
  const img = images[f.image]
  if (f.kind !== 'capture' && !img) return toast('Choose an image first', true)
  if (f.kind === 'capture' && !f.name.trim()) return toast('Give the image a name', true)
  let bitlockerKey
  if (f.kind === 'capture' && selectedDisk()?.bitlocker) {
    bitlockerKey = normaliseRecoveryKey(f.bitlocker_key)
    if (!bitlockerKey) return toast("That isn't a valid BitLocker recovery key: it's 8 groups of 6 digits. Or turn BitLocker off in Windows.", true)
  }
  if (f.kind !== 'copy' && !disk) return toast('Choose a disk', true)
  const indexes = img ? (img.indexes || img.meta?.indexes || []) : []
  const wimIndex = img?.kind === 'wim' ? +(f.wim_index || indexes[0]?.index || 1) : null
  const allow = !!flowMismatch() && f.allow
  if (flowMismatch() && !allow) return toast('The storage mode doesn’t match. Tick "Deploy anyway" to go ahead.', true)

  if (f.kind === 'deploy' && !(await confirmBox({
    title: 'Erase this disk?', danger: true, ok: 'Erase and deploy',
    text: `Everything on <b>${esc(disk.path)}</b> (${bytes(disk.size)} ${esc(disk.model)}) will be erased and replaced with
      <b>${esc(img.name)}</b>. This can't be undone.`,
  }))) return

  let body
  if (f.kind === 'copy') {
    if (!usb?.ready) await prepareUsb()
    if (!usb?.ready) return
    body = { action: 'usb-copy', image_id: img.id, name: img.name }
  } else if (f.source === 'server') {
    body = { action: 'server-task', type: f.kind, disk: f.disk }
    if (f.kind === 'deploy') Object.assign(body, { image_id: img.id, wim_index: wimIndex, drivers: f.inject ? 'auto' : 'none', allow_storage_mismatch: allow })
    else Object.assign(body, { name: f.name.trim(), kind: f.ckind, bitlocker_key: bitlockerKey })
    body.after = f.after
  } else if (f.kind === 'deploy') {
    body = { action: 'usb-deploy', dir: img.dir, disk: f.disk, wim_index: wimIndex, inject: f.inject, after: f.after, allow_storage_mismatch: allow }
  } else {
    if (!usb?.ready) await prepareUsb()
    if (!usb?.ready) return
    body = { action: 'usb-capture', name: f.name.trim(), kind: f.ckind, disk: f.disk, bitlocker_key: bitlockerKey }
  }
  try {
    const r = await call('POST', '/api/action', body)
    toast(r.message)
    flow = null
    poll()
  } catch (e) {
    toast(e.message, true)
  }
}

async function prepareUsb() {
  if (!usb?.can_create) return toast(usb?.reason || 'No USB stick to prepare', true)
  if (!(await confirmBox({
    title: 'Prepare USB storage?', ok: 'Prepare',
    text: `This adds a ${bytes(usb.size)} partition for images in the free space on the boot stick (${esc(usb.stick)}).
      The stick stays bootable and nothing on it is erased.`,
  }))) return
  try {
    toast((await call('POST', '/api/action', { action: 'usb-prepare' })).message)
    usb = await call('GET', '/api/usb')
  } catch (e) {
    toast(e.message, true)
  }
}

// --------------------------------------------------------------------------- events

document.addEventListener('click', async (e) => {
  const set = e.target.closest('[data-set]')
  if (set && flow) {
    const { set: key, value } = set.dataset
    if (key === 'image') { flow.image = +value; flow.allow = false }
    else if (key === 'source') { flow.source = value; flow.image = null; if (value === 'server' && !serverImages.length) serverImages = await call('GET', '/api/server-images').catch(() => []) }
    else flow[key] = value
    renderFlow()
    return
  }
  const el = e.target.closest('[data-action]')
  if (!el) return
  const { action, value } = el.dataset
  try {
    switch (action) {
      case 'open-deploy': return openFlow('deploy')
      case 'open-capture': return openFlow('capture')
      case 'open-copy': return openFlow('copy')
      case 'close': flow = null; return render()
      case 'submit': return submitFlow()
      case 'usb-prepare': return prepareUsb()
      case 'usb-upload': {
        const img = usb.images[+value]
        if (!(await confirmBox({ title: 'Upload to the server?', text: `<b>${esc(img.name)}</b> (${bytes(img.size)}) will be added to the server's image library.`, ok: 'Upload' }))) return
        toast((await call('POST', '/api/action', { action: 'usb-upload', dir: img.dir })).message)
        return poll()
      }
      case 'cancel':
        if (await confirmBox({ title: 'Cancel?', text: 'A deployment stopped part-way leaves the disk unbootable.', ok: 'Cancel it', danger: true })) await call('POST', '/api/job/cancel')
        return
      case 'dismiss': await call('POST', '/api/job/dismiss'); usb = null; loadUsb(); return poll()
      case 'after-cancel': await call('POST', '/api/after/cancel'); return poll()
      case 'sign-out': return signOut()
      case 'refresh': await call('POST', '/api/refresh'); usb = null; loadUsb(); return toast('Re-scanning hardware')
      case 'text-mode':
        if (await confirmBox({ title: 'Switch to text mode?', text: 'This closes the graphical interface and opens the text menu. Reboot to come back.', ok: 'Switch' })) await call('POST', '/api/ui/text')
        return
      case 'power':
        if (await confirmBox({ title: value === 'reboot' ? 'Reboot?' : 'Power off?', text: 'Anything running will stop.', ok: value === 'reboot' ? 'Reboot' : 'Power off', danger: true })) await call('POST', '/api/power', { action: value })
        return
    }
  } catch (err) {
    toast(err.message, true)
  }
})

document.addEventListener('input', (e) => {
  const field = e.target.dataset?.field
  if (!field || !flow) return
  flow[field] = e.target.type === 'checkbox' ? e.target.checked : e.target.value
  if (field === 'disk') {
    flow.allow = false // a different disk may or may not match the image's storage mode
    renderFlow()
  }
})

// --------------------------------------------------------------------------- signing in

const LOGIN_FORM = `<form class="card login" id="login" autocomplete="off">
  <h2>Sign in</h2>
  <p class="muted" id="login-note">Sign in with your mck-pxe account to deploy or capture.</p>
  <label class="field">Username<input type="text" name="username" autocapitalize="none" spellcheck="false" /></label>
  <label class="field">Password<input type="password" name="password" /></label>
  <div class="banner bad" id="login-error" hidden></div>
  <button class="btn lg" type="submit">Sign in</button>
  <p class="muted" id="login-job"></p>
</form>`

function renderLogin() {
  renderTop()
  if (setHTML($('#main'), LOGIN_FORM)) $('#login [name=username]').focus()
  $('#login-note').textContent = state.online
    ? 'Sign in with your mck-pxe account to deploy or capture.'
    : state.offline_account
      ? "Can't reach the server. Sign in with the USB stick's account to use images on the stick."
      : "Can't reach the server to check your password. Check the network cable and wait a moment."
  const j = state.job
  $('#login-job').textContent = j.state === 'running' ? `Running: ${j.title} (${Math.round(j.progress || 0)}%)` : ''
}

document.addEventListener('submit', async (e) => {
  if (e.target.id !== 'login') return
  e.preventDefault()
  const form = e.target
  const err = $('#login-error')
  err.hidden = true
  const button = form.querySelector('button')
  button.disabled = true
  try {
    await call('POST', '/api/login', { username: form.username.value, password: form.password.value })
    flow = null
    usb = null
    await poll()
    loadUsb()
  } catch (ex) {
    err.textContent = ex.message
    err.hidden = false
    form.password.value = ''
    form.password.focus()
  } finally {
    button.disabled = false
  }
})

async function signOut() {
  await call('POST', '/api/logout').catch(() => {})
  flow = null
  usb = null
  serverImages = []
  poll()
}

// Sign out after a while with nobody using the screen
const IDLE_MINUTES = 15
let lastInput = Date.now()
for (const ev of ['pointerdown', 'keydown', 'wheel']) document.addEventListener(ev, () => (lastInput = Date.now()), true)
setInterval(() => {
  if (state?.user && Date.now() - lastInput > IDLE_MINUTES * 60_000) signOut()
}, 30_000)

// --------------------------------------------------------------------------- polling

function render() {
  if (!state) return
  document.body.classList.toggle('signed-out', !state.user)
  if (!state.user) return renderLogin()
  renderTop()
  if (state.job.state !== 'idle') renderJob()
  else if (flow) { if (!$('.form')) renderFlow() } // don't redraw a form while it's being filled in
  else renderHome()
}

async function loadUsb() {
  if (!state?.user) return
  try { usb = await call('GET', '/api/usb') } catch { usb = { ready: false, can_create: false, reason: "Couldn't check the USB stick" } }
  render()
}

async function poll() {
  try {
    const prev = state?.job?.state
    state = await call('GET', '/api/state')
    if (prev === 'running' && state.job.state !== 'running') loadUsb()
    render()
  } catch {
    setHTML($('#main'), '<p class="muted">Waiting for the mck-pxe agent…</p>')
  }
}

poll()
loadUsb()
setInterval(poll, 1000)
setInterval(() => { if (state?.user && !flow && state.job.state === 'idle') loadUsb() }, 8000)
