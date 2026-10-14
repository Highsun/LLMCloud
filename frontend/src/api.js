const baseUrl = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '')

export async function getHealth() {
  const response = await fetch(`${baseUrl}/health`, { signal: AbortSignal.timeout(5000) })
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  const data = await response.json()
  if (data.status !== 'ok' || typeof data.service !== 'string') {
    throw new Error('健康检查响应格式异常')
  }
  return data
}
