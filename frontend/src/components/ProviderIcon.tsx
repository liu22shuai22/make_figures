import anthropic from '../assets/providers/anthropic.svg?raw'
import baichuan from '../assets/providers/baichuan.svg?raw'
import baidu from '../assets/providers/baidu.svg?raw'
import custom from '../assets/providers/custom.svg?raw'
import dashscope from '../assets/providers/dashscope.svg?raw'
import deepseek from '../assets/providers/deepseek.svg?raw'
import doubao from '../assets/providers/doubao.svg?raw'
import fireworks from '../assets/providers/fireworks.svg?raw'
import gemini from '../assets/providers/gemini.svg?raw'
import groq from '../assets/providers/groq.svg?raw'
import hunyuan from '../assets/providers/hunyuan.svg?raw'
import magpie from '../assets/providers/magpie.svg?raw'
import minimax from '../assets/providers/minimax.svg?raw'
import mistral from '../assets/providers/mistral.svg?raw'
import modelscope from '../assets/providers/modelscope.svg?raw'
import moonshot from '../assets/providers/moonshot.svg?raw'
import newapi from '../assets/providers/newapi.svg?raw'
import ollama from '../assets/providers/ollama.svg?raw'
import openai from '../assets/providers/openai.svg?raw'
import openrouter from '../assets/providers/openrouter.svg?raw'
import sensenova from '../assets/providers/sensenova.svg?raw'
import siliconflow from '../assets/providers/siliconflow.svg?raw'
import spark from '../assets/providers/spark.svg?raw'
import stepfun from '../assets/providers/stepfun.svg?raw'
import together from '../assets/providers/together.svg?raw'
import xai from '../assets/providers/xai.svg?raw'
import xiaomi from '../assets/providers/xiaomi.svg?raw'
import yi from '../assets/providers/yi.svg?raw'
import zhipu from '../assets/providers/zhipu.svg?raw'

const ICONS: Record<string, string> = {
  newapi,
  siliconflow,
  deepseek,
  openai,
  anthropic,
  gemini,
  openrouter,
  moonshot,
  dashscope,
  xiaomi,
  hunyuan,
  zhipu,
  doubao,
  qianfan: baidu,
  baidu,
  minimax,
  stepfun,
  baichuan,
  yi,
  spark,
  sensenova,
  modelscope,
  groq,
  mistral,
  xai,
  together,
  fireworks,
  ollama,
  magpie,
  custom,
}

interface Props {
  id?: string | null
  size?: number
  className?: string
  title?: string
}

export function providerIconId(id?: string | null) {
  const key = (id || 'custom').toLowerCase()
  return key in ICONS ? key : 'custom'
}

export default function ProviderIcon({ id, size = 18, className, title }: Props) {
  const key = providerIconId(id)
  const svg = ICONS[key]
  return (
    <span
      className={'provider-icon' + (className ? ` ${className}` : '')}
      style={{ width: size, height: size, fontSize: size }}
      title={title}
      aria-hidden={title ? undefined : true}
      role={title ? 'img' : undefined}
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  )
}
