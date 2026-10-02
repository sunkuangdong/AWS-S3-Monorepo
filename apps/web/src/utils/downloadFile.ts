/**
 * 让浏览器访问后端提供的临时下载地址。
 * Ask the browser to visit a temporary download URL from the backend.
 *
 * 实际文件名和下载行为由 S3 响应中的 Content-Disposition 决定。
 * The S3 Content-Disposition response header controls the filename and download behavior.
 */
export function downloadFileFromUrl(url: string): void {
  const anchor = document.createElement('a')

  anchor.href = url
  anchor.rel = 'noreferrer'
  document.body.append(anchor)
  anchor.click()
  anchor.remove()
}
