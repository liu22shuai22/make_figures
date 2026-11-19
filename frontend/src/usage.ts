/** 用量数据契约：与 GET /api/usage 的返回保持一致 */

interface Counts {
  input_tokens: number
  output_tokens: number
  calls: number
  unreported_calls: number
}

interface DailyUsage extends Counts {
  day: string
}

export interface UsageModel extends Counts {
  model: string
}

export interface UsageChannel extends Counts {
  id: string
  name: string
  models: UsageModel[]
}

export interface Usage {
  today: DailyUsage
  total: Counts
  daily: DailyUsage[]
  channels?: UsageChannel[]
}

/** 补齐空日期后的单日数据，供图表直接消费 */
export interface UsageDay extends Counts {
  day: string
  /** 轴上标签，如 11/3 */
  label: string
  isToday: boolean
}

const numberFormat = new Intl.NumberFormat('zh-CN')

export const number = (value: number) => numberFormat.format(value)

export const tokens = (counts: Counts) => counts.input_tokens + counts.output_tokens

const EMPTY: Counts = { input_tokens: 0, output_tokens: 0, calls: 0, unreported_calls: 0 }

/** 坐标轴用紧凑写法：1.2 万 / 3.4 亿，避免轴标签过长 */
export function compact(value: number): string {
  if (value >= 1e8) return `${trim(value / 1e8)}亿`
  if (value >= 1e4) return `${trim(value / 1e4)}万`
  return number(value)
}

const trim = (value: number) => value.toFixed(1).replace(/\.0$/, '')

/**
 * 把服务端「只含有记录的日期」补齐成连续 N 天。
 * 锚点用服务端返回的 today.day，避免浏览器与服务器时区不一致时错位。
 */
export function buildSeries(daily: DailyUsage[], endDay: string, days: number): UsageDay[] {
  const byDay = new Map(daily.map((item) => [item.day, item]))
  const end = Date.parse(`${endDay}T00:00:00Z`)
  if (Number.isNaN(end)) return []

  const series: UsageDay[] = []
  for (let offset = days - 1; offset >= 0; offset -= 1) {
    const date = new Date(end - offset * 86_400_000)
    const day = date.toISOString().slice(0, 10)
    series.push({
      day,
      label: `${date.getUTCMonth() + 1}/${date.getUTCDate()}`,
      isToday: offset === 0,
      ...(byDay.get(day) ?? EMPTY),
    })
  }
  return series
}

/** 取一个好看的坐标上界（1/2/5 × 10^n） */
export function niceMax(value: number): number {
  if (!(value > 0)) return 1
  const magnitude = 10 ** Math.floor(Math.log10(value))
  const ratio = value / magnitude
  const step = ratio <= 1 ? 1 : ratio <= 2 ? 2 : ratio <= 5 ? 5 : 10
  return step * magnitude
}

/** 本地时间 HH:mm */
export function clockTime(date: Date): string {
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}
