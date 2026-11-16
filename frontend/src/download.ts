/** 下载相关的小工具：data URL / 文本 → 浏览器下载 */

function triggerDownload(blob: Blob, filename: string) {
  const href = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = href
  anchor.download = filename
  anchor.rel = 'noopener'
  anchor.style.display = 'none'
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  // 立刻 revoke 会让部分浏览器拿不到数据，延后释放
  window.setTimeout(() => URL.revokeObjectURL(href), 10_000)
}

/** 把 base64 data URL 还原成二进制再下载，避免超长 data URL 直接给 <a download> 的限制 */
export function downloadDataUrl(url: string, filename: string) {
  const comma = url.indexOf(',')
  const header = comma >= 0 ? url.slice(0, comma) : ''
  const body = comma >= 0 ? url.slice(comma + 1) : url
  const mime = /data:([^;,]+)/.exec(header)?.[1] ?? 'application/octet-stream'
  const isBase64 = /;base64/i.test(header)

  let bytes: Uint8Array
  if (isBase64) {
    const binary = atob(body)
    bytes = new Uint8Array(binary.length)
    for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index)
  } else {
    bytes = new TextEncoder().encode(decodeURIComponent(body))
  }
  triggerDownload(new Blob([bytes], { type: mime }), filename)
}

export function downloadText(filename: string, text: string, mime = 'application/json;charset=utf-8') {
  triggerDownload(new Blob([text], { type: mime }), filename)
}

/** 文件名里去掉 Windows/macOS 不接受的字符 */
export function safeFileName(input: string, fallback = 'er-spec'): string {
  const cleaned = input.replace(/[\\/:*?"<>|\r\n\t]+/g, '').trim()
  return cleaned || fallback
}
