function basename(value: string): string {
  const normalized = value.replace(/\\/g, '/')
  return normalized.slice(normalized.lastIndexOf('/') + 1)
}

function safeFilename(value: string): string {
  return basename(value)
    .replace(/[\x00-\x1f\x7f]/g, '')
    .replace(/[<>:"/\\|?*]/g, '')
    .trim()
    .replace(/[. ]+$/g, '')
}

function filenameStar(disposition: string): string | null {
  const match = disposition.match(/(?:^|;)\s*filename\*\s*=\s*(?:"([^"]*)"|([^;]*))/i)
  if (!match) return null

  const encoded = (match[1] ?? match[2] ?? '').trim()
  const extended = encoded.match(/^[^']*'[^']*'(.*)$/)
  return decodeURIComponent(extended?.[1] ?? encoded)
}

function regularFilename(disposition: string): string | null {
  const quoted = disposition.match(/(?:^|;)\s*filename\s*=\s*"([^"]*)"/i)
  if (quoted) return quoted[1]

  const plain = disposition.match(/(?:^|;)\s*filename\s*=\s*([^;]*)/i)
  return plain?.[1]?.trim() || null
}

export function filenameFromDisposition(
  disposition: string | null | undefined,
  fallback: string,
): string {
  if (disposition) {
    try {
      const preferred = filenameStar(disposition)
      const safePreferred = preferred ? safeFilename(preferred) : ''
      if (safePreferred) return safePreferred
    } catch {
      // Invalid RFC 5987 encoding falls back to filename= below.
    }

    const filename = regularFilename(disposition)
    const safeRegular = filename ? safeFilename(filename) : ''
    if (safeRegular) return safeRegular
  }

  return safeFilename(fallback) || 'download'
}

export function saveBlob(blob: Blob, filename: string): void {
  const objectUrl = URL.createObjectURL(blob)
  let anchor: HTMLAnchorElement | null = null

  try {
    anchor = document.createElement('a')
    anchor.href = objectUrl
    anchor.download = filename
    anchor.style.display = 'none'
    document.body.appendChild(anchor)
    anchor.click()
  } finally {
    try {
      anchor?.remove()
    } finally {
      URL.revokeObjectURL(objectUrl)
    }
  }
}
