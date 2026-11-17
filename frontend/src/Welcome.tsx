import { useEffect, useRef, useState } from 'react'
import ThemeToggle from './components/ThemeToggle'
import LanguageToggle from './components/LanguageToggle'
import BrandMark from './components/BrandMark'
import AccountMenu from './components/AccountMenu'
import SiteFooter from './components/SiteFooter'
import { SAMPLE_JSON, SAMPLE_NAME, sampleStats } from './sample'
import { REPO_URL } from './site'
import { parseSpec } from './spec'
import type { Theme } from './theme'
import { useLocale } from './LocaleContext'

interface WelcomeProps {
  /** 进入工作台并聚焦「描述你的系统」 */
  onStart: () => void
  /** 进入工作台并载入选课样例（自动出图） */
  onSample: () => void
  /** 进入工作台并载入用例图样例 */
  onUseCaseSample: () => void
  /** 直接进入工作台，保留已有草稿 */
  onOpen: () => void
  /** 打开登录页 */
  onLogin: () => void
  /** 退出登录 */
  onLogout: () => void
  /** 当前登录用户名；null 表示未登录 */
  username: string | null
  theme: Theme
  onToggleTheme: () => void
}

/** 演示卡里逐字出现的那一句，和下面导出的选课图是同一份例子 */
const DEMO_SENTENCE = '学生可以选修多门课程，每门课程也可以被多名学生选修，选课时记录成绩。'
const DEMO_MARKS = ['学生', '课程', '选修', '成绩']

/** 用例图页签对应的描述（图书借阅样例） */
const DEMO_UC_SENTENCE = '读者可以借书、还书和查询馆藏；借还时要验证身份，续借可作为借书的扩展。'
const DEMO_UC_MARKS = ['读者', '借书', '还书', '查询馆藏', '验证身份', '续借']

type DemoPlay = 'write' | 'draw' | 'reveal' | 'show'

function prefersStill() {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/** 把句子拆成「要高亮的术语」和其余文字，顺序与原文一致 */
function splitMarks(text: string, marks: string[]) {
  const parts: { text: string; mark: boolean }[] = []
  let i = 0
  while (i < text.length) {
    const mark = marks.find((item) => text.startsWith(item, i))
    if (mark) {
      parts.push({ text: mark, mark: true })
      i += mark.length
    } else {
      parts.push({ text: text[i], mark: false })
      i += 1
    }
  }
  return parts
}

function DemoSentence({
  live,
  text = DEMO_SENTENCE,
  marks = DEMO_MARKS,
}: {
  live: boolean
  text?: string
  marks?: string[]
}) {
  const parts = splitMarks(text, marks)
  let index = 0
  return (
    <p className={'demo-text' + (live ? ' is-live' : '')}>
      {parts.map((part) => {
        const start = index
        index += part.text.length
        const chars = [...part.text].map((ch, offset) => (
          <span
            key={start + offset}
            className={live ? 'demo-char' : undefined}
            style={live ? { animationDelay: `${(start + offset) * 46}ms` } : undefined}
          >
            {ch}
          </span>
        ))
        return part.mark ? (
          <span key={start} className="demo-mark">
            {chars}
          </span>
        ) : (
          <span key={start}>{chars}</span>
        )
      })}
    </p>
  )
}

/** 出图前的一笔线稿：实体、联系、属性和基数都来自选课示例，画完让位给真实导出图 */
function DemoSketch({ drawing, leaving }: { drawing: boolean; leaving: boolean }) {
  const ink = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.6, pathLength: 1 }
  return (
    <svg
      className={'demo-sketch' + (drawing ? ' is-drawing' : '') + (leaving ? ' is-leaving' : '')}
      viewBox="0 0 300 250"
      aria-hidden="true"
    >
      <rect x="110" y="14" width="80" height="36" rx="3" {...ink} />
      <text x="150" y="37" textAnchor="middle">
        课程
      </text>
      <line x1="150" y1="50" x2="150" y2="86" {...ink} />
      <text className="demo-card" x="132" y="74" textAnchor="middle">
        n
      </text>
      <path d="M150 96 186 122 150 148 114 122Z" {...ink} strokeLinejoin="round" />
      <text x="150" y="126" textAnchor="middle">
        选修
      </text>
      <line x1="186" y1="122" x2="222" y2="122" {...ink} />
      <ellipse cx="258" cy="122" rx="36" ry="20" {...ink} />
      <text x="258" y="126" textAnchor="middle">
        成绩
      </text>
      <line x1="150" y1="148" x2="150" y2="190" {...ink} />
      <text className="demo-card" x="132" y="176" textAnchor="middle">
        m
      </text>
      <rect x="110" y="190" width="80" height="36" rx="3" {...ink} />
      <text x="150" y="213" textAnchor="middle">
        学生
      </text>
    </svg>
  )
}

/**
 * 欢迎页「体验示例」图种入口。以后加新图种：这里加一项 + 接线 onXxxSample，不必改标题文案。
 */
const TRY_SAMPLES: {
  id: string
  labelKey: 'tryEr' | 'tryUsecase'
  testId: string
  /** 对应 WelcomeProps 里的样例回调 */
  action: 'er' | 'usecase'
}[] = [
  { id: 'er', labelKey: 'tryEr', testId: 'try-sample', action: 'er' },
  { id: 'usecase', labelKey: 'tryUsecase', testId: 'try-usecase-sample', action: 'usecase' },
]

type CapIcon = 'diagram' | 'layers' | 'sliders' | 'download'

const CAP_ICONS: CapIcon[] = ['diagram', 'layers', 'sliders', 'download']

/** 示例规模，给首屏的规格行用 */
const STATS = sampleStats()

/**
 * 演示卡里「规格」页展示的内容：走工作台导入用的同一个解析器，
 * 所以这里看到的就是导入后会出现在表单里的结构，不是另写的一份说明。
 */
const PARSED = parseSpec(SAMPLE_JSON)
const SPEC = PARSED.ok ? PARSED.spec : null

/**
 * 三个可以「照抄」的场景。prompt 是写给模型看的完整描述，
 * 用户复制后直接粘到工作台，就能得到对应的一套图。
 */
/** 场景卡：prompt/实体名仍用中文（给模型与样例一致）；展示名走 locale */
const SCENARIOS: {
  id: string
  entities: string[]
  relations: string[]
  prompt: string
}[] = [
  {
    id: 'library',
    entities: ['读者', '图书', '分类'],
    relations: ['借阅', '属于'],
    prompt:
      '读者可以借阅多本图书，同一本图书也可以被不同读者先后借阅，每次借阅要记录借出日期和归还日期；每本图书属于一个馆藏分类。',
  },
  {
    id: 'shop',
    entities: ['用户', '商品', '订单', '支付'],
    relations: ['下单', '包含', '付款'],
    prompt:
      '用户可以下多个订单，一个订单可以包含多种商品，每件商品要记录购买数量和成交单价；每个订单通过一次支付结清，支付记录支付方式与支付时间。',
  },
  {
    id: 'hr',
    entities: ['员工', '部门', '考勤记录', '请假单'],
    relations: ['属于', '打卡', '申请'],
    prompt:
      '员工隶属于一个部门，每个部门可以有多名员工；员工每天打卡产生考勤记录，记录打卡时间和状态；员工可以提交请假单，请假单记录开始日期、结束日期和审批结果。',
  },
]

/**
 * 演示卡里可切换的图。label/meta/title 在渲染时按 locale 填。
 */
const DEMO_FIGURES = [
  {
    key: 'overview' as const,
    kind: 'er' as const,
    src: '/sample-overview.png',
    width: 547,
    height: 645,
    alt: '选课示例生成的整体 E-R 图：学生与课程经「选修」联系相连，联系带「成绩」属性',
  },
  {
    key: 'student' as const,
    kind: 'er' as const,
    src: '/sample-entity-1.png',
    width: 707,
    height: 528,
    alt: '学生实体的属性图：学号（主键）、姓名、专业三个属性',
  },
  {
    key: 'course' as const,
    kind: 'er' as const,
    src: '/sample-entity-2.png',
    width: 737,
    height: 533,
    alt: '课程实体的属性图：课程编号（主键）、课程名、学分三个属性',
  },
  {
    key: 'usecase' as const,
    kind: 'usecase' as const,
    src: '/sample-usecase.png',
    width: 1005,
    height: 662,
    alt: '图书借阅用例图：读者与管理员关联借书、还书、查询馆藏；借还含验证身份 include',
  },
]

function CapGlyph({ name }: { name: CapIcon }) {
  const common = {
    width: 18,
    height: 18,
    viewBox: '0 0 20 20',
    fill: 'none',
    'aria-hidden': true as const,
  }
  if (name === 'diagram') {
    return (
      <svg {...common}>
        <rect x="6.4" y="2.2" width="7.2" height="4.2" rx="1.2" stroke="currentColor" strokeWidth="1.5" />
        <path d="M10 6.4v2.4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        <path d="M10 8.8 13.8 12.4 10 16 6.2 12.4Z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
      </svg>
    )
  }
  if (name === 'layers') {
    return (
      <svg {...common}>
        <path d="M10 2.6 2.8 6.4 10 10.2l7.2-3.8L10 2.6Z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
        <path d="M2.8 10.6 10 14.4l7.2-3.8M2.8 14.2 10 18l7.2-3.8" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
      </svg>
    )
  }
  if (name === 'sliders') {
    return (
      <svg {...common}>
        <path d="M3 6h8M14.6 6H17M3 14h3.2M9.8 14H17" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        <circle cx="12.8" cy="6" r="1.9" stroke="currentColor" strokeWidth="1.5" />
        <circle cx="8" cy="14" r="1.9" stroke="currentColor" strokeWidth="1.5" />
      </svg>
    )
  }
  return (
    <svg {...common}>
      <path d="M10 2.8v8.4M6.6 7.9 10 11.3l3.4-3.4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M3.2 13.4v2.2a1.6 1.6 0 0 0 1.6 1.6h10.4a1.6 1.6 0 0 0 1.6-1.6v-2.2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  )
}

type NotationFig =
  | 'entity'
  | 'relation'
  | 'attribute'
  | 'key'
  | 'cardinality'
  | 'actor'
  | 'usecase'
  | 'boundary'
  | 'association'
  | 'include'

function NotationGlyph({ fig }: { fig: NotationFig }) {
  const s = { stroke: 'currentColor', strokeWidth: 1.4, fill: 'none' as const }
  if (fig === 'entity') {
    return (
      <svg width="64" height="34" viewBox="0 0 64 34" aria-hidden="true">
        <rect x="10" y="7" width="44" height="20" rx="2" {...s} />
      </svg>
    )
  }
  if (fig === 'relation') {
    return (
      <svg width="64" height="34" viewBox="0 0 64 34" aria-hidden="true">
        <path d="M32 6 54 17 32 28 10 17Z" {...s} strokeLinejoin="round" />
      </svg>
    )
  }
  if (fig === 'attribute') {
    return (
      <svg width="64" height="34" viewBox="0 0 64 34" aria-hidden="true">
        <ellipse cx="32" cy="17" rx="22" ry="11" {...s} />
      </svg>
    )
  }
  if (fig === 'key') {
    return (
      <svg width="64" height="34" viewBox="0 0 64 34" aria-hidden="true">
        <ellipse cx="32" cy="16" rx="25" ry="12" {...s} />
        <text x="32" y="19" textAnchor="middle" fontSize="9.5" fill="currentColor" stroke="none">
          学号
        </text>
        <path d="M22.5 21.4h19" {...s} strokeWidth={1.2} />
      </svg>
    )
  }
  if (fig === 'cardinality') {
    return (
      <svg width="64" height="34" viewBox="0 0 64 34" aria-hidden="true">
        <rect x="0.5" y="13" width="17" height="12" rx="2" {...s} />
        <rect x="46.5" y="13" width="17" height="12" rx="2" {...s} />
        <path d="M17.5 19h29" {...s} />
        <text x="23" y="12" textAnchor="middle" fontSize="10.5" fill="currentColor" stroke="none">
          1
        </text>
        <text x="41" y="12" textAnchor="middle" fontSize="10.5" fill="currentColor" stroke="none">
          n
        </text>
      </svg>
    )
  }
  if (fig === 'actor') {
    return (
      <svg width="64" height="34" viewBox="0 0 64 34" aria-hidden="true">
        <circle cx="32" cy="7.5" r="3.2" {...s} />
        <path d="M32 10.8v8.2M26.5 14.2h11M32 19l-4.2 7.5M32 19l4.2 7.5" {...s} strokeLinecap="round" />
      </svg>
    )
  }
  if (fig === 'usecase') {
    return (
      <svg width="64" height="34" viewBox="0 0 64 34" aria-hidden="true">
        <ellipse cx="32" cy="17" rx="24" ry="11" {...s} />
        <text x="32" y="20" textAnchor="middle" fontSize="9" fill="currentColor" stroke="none">
          借书
        </text>
      </svg>
    )
  }
  if (fig === 'boundary') {
    return (
      <svg width="64" height="34" viewBox="0 0 64 34" aria-hidden="true">
        <rect x="8" y="4" width="48" height="26" rx="1" {...s} />
        <text x="32" y="13" textAnchor="middle" fontSize="8" fill="currentColor" stroke="none">
          系统
        </text>
        <ellipse cx="32" cy="23" rx="12" ry="5.5" {...s} />
      </svg>
    )
  }
  if (fig === 'association') {
    return (
      <svg width="64" height="34" viewBox="0 0 64 34" aria-hidden="true">
        <circle cx="10" cy="8" r="2.4" {...s} />
        <path d="M10 10.5v6M6.5 13h7M10 16.5 7 22M10 16.5 13 22" {...s} strokeWidth={1.2} strokeLinecap="round" />
        <path d="M14 14h18" {...s} />
        <ellipse cx="48" cy="17" rx="12" ry="7" {...s} />
      </svg>
    )
  }
  return (
    <svg width="64" height="34" viewBox="0 0 64 34" aria-hidden="true">
      <ellipse cx="14" cy="17" rx="10" ry="7" {...s} />
      <path d="M24 17h22" {...s} strokeDasharray="3 2" />
      <path d="M42 13.5 48 17 42 20.5" {...s} strokeLinejoin="round" />
      <ellipse cx="54" cy="17" rx="8" ry="6" {...s} />
      <text x="35" y="12" textAnchor="middle" fontSize="7.5" fill="currentColor" stroke="none">
        «include»
      </text>
    </svg>
  )
}

export default function Welcome({
  onStart,
  onSample,
  onUseCaseSample,
  onOpen,
  onLogin,
  onLogout,
  username,
  theme,
  onToggleTheme,
}: WelcomeProps) {
  const { locale, setLocale, welcome: t } = useLocale()
  const pageRef = useRef<HTMLDivElement>(null)
  const heroRef = useRef<HTMLElement>(null)
  const tiltRef = useRef<HTMLDivElement>(null)
  const [demoIndex, setDemoIndex] = useState(0)
  const [demoView, setDemoView] = useState<'figure' | 'spec'>('figure')
  const [play, setPlay] = useState<DemoPlay>(() => (prefersStill() ? 'show' : 'write'))
  const playTimers = useRef<number[]>([])
  const [copied, setCopied] = useState<string | null>(null)
  const [copyError, setCopyError] = useState<string | null>(null)
  const copyTimer = useRef<number | null>(null)
  const demoFigure = DEMO_FIGURES[demoIndex]
  const demoChrome = (() => {
    if (demoFigure.key === 'overview') {
      return { label: t.demoOverview, meta: t.demoMetaOverview, title: t.demoTitleCourse }
    }
    if (demoFigure.key === 'student') {
      return { label: t.demoStudent, meta: t.demoMetaStudent, title: t.demoTitleCourse }
    }
    if (demoFigure.key === 'course') {
      return { label: t.demoCourse, meta: t.demoMetaCourse, title: t.demoTitleCourse }
    }
    return { label: t.demoUsecase, meta: t.demoMetaUsecase, title: t.demoTitleLibrary }
  })()
  const trySampleRun: Record<(typeof TRY_SAMPLES)[number]['action'], () => void> = {
    er: onSample,
    usecase: onUseCaseSample,
  }
  const notationGroups = [
    { id: 'er', title: t.notationEr, items: t.notationItems.er },
    { id: 'usecase', title: t.notationUc, items: t.notationItems.usecase },
  ]

  useEffect(() => () => {
    if (copyTimer.current) window.clearTimeout(copyTimer.current)
  }, [])

  // 首屏演示自己演一遍：句子写完，线稿画出，再交叉淡入真实导出图。点下方图例会立刻停在结果上。
  useEffect(() => {
    if (prefersStill()) return
    const writeMs = DEMO_SENTENCE.length * 46 + 280
    const drawMs = 1500
    playTimers.current = [
      window.setTimeout(() => setPlay('draw'), writeMs),
      window.setTimeout(() => setPlay('reveal'), writeMs + drawMs),
      window.setTimeout(() => setPlay('show'), writeMs + drawMs + 560),
    ]
    return () => {
      playTimers.current.forEach((id) => window.clearTimeout(id))
    }
  }, [])

  const settlePlay = () => {
    playTimers.current.forEach((id) => window.clearTimeout(id))
    playTimers.current = []
    setPlay('show')
  }

  // 指针视差：只在鼠标 + 桌面 + 未要求减少动效时开启。
  // 倾斜写在外层包裹上，因为 .demo 的入场动画（fill: both）会一直占着 transform。
  useEffect(() => {
    const hero = heroRef.current
    const tilt = tiltRef.current
    if (!hero || !tilt) return
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    if (!window.matchMedia('(pointer: fine)').matches) return

    const onMove = (event: PointerEvent) => {
      if (event.pointerType !== 'mouse') return
      const rect = tilt.getBoundingClientRect()
      const nx = ((event.clientX - rect.left) / rect.width) * 2 - 1
      const ny = ((event.clientY - rect.top) / rect.height) * 2 - 1
      tilt.style.setProperty('--tilt-x', Math.max(-1, Math.min(1, nx)).toFixed(3))
      tilt.style.setProperty('--tilt-y', Math.max(-1, Math.min(1, ny)).toFixed(3))
      const hrect = hero.getBoundingClientRect()
      const hx = ((event.clientX - hrect.left) / hrect.width) * 2 - 1
      const hy = ((event.clientY - hrect.top) / hrect.height) * 2 - 1
      hero.style.setProperty('--px', hx.toFixed(3))
      hero.style.setProperty('--py', hy.toFixed(3))
    }
    const onEnter = (event: PointerEvent) => {
      // 鼠标一进 hero 就停掉常驻摇摆，让位给指针倾斜，避免两个转向打架
      if (event.pointerType === 'mouse') tilt.dataset.interactive = 'on'
    }
    const onLeave = () => {
      tilt.style.setProperty('--tilt-x', '0')
      tilt.style.setProperty('--tilt-y', '0')
      hero.style.setProperty('--px', '0')
      hero.style.setProperty('--py', '0')
      delete tilt.dataset.interactive
    }
    hero.addEventListener('pointerenter', onEnter)
    hero.addEventListener('pointermove', onMove)
    hero.addEventListener('pointerleave', onLeave)
    return () => {
      hero.removeEventListener('pointerenter', onEnter)
      hero.removeEventListener('pointermove', onMove)
      hero.removeEventListener('pointerleave', onLeave)
    }
  }, [])

  const copyPrompt = async (id: string, text: string) => {
    setCopyError(null)
    try {
      await navigator.clipboard.writeText(text)
      setCopied(id)
      if (copyTimer.current) window.clearTimeout(copyTimer.current)
      copyTimer.current = window.setTimeout(() => setCopied(null), 4000)
    } catch {
      setCopyError(t.copyError)
    }
  }

  // 首屏之下的区块进入视口时淡入上浮一次；只在有 JS 且未要求减少动效时启用
  useEffect(() => {
    const root = pageRef.current
    if (!root) return
    if (typeof IntersectionObserver === 'undefined') return
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return

    const nodes = Array.from(root.querySelectorAll<HTMLElement>('[data-reveal]'))
    if (!nodes.length) return

    nodes.forEach((node) => node.classList.add('reveal'))
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return
          entry.target.classList.add('is-in')
          io.unobserve(entry.target)
        })
      },
      { rootMargin: '0px 0px -5% 0px', threshold: 0.04 },
    )
    nodes.forEach((node) => io.observe(node))
    return () => io.disconnect()
  }, [])

  return (
    <div className="welcome" ref={pageRef}>
      {/* 沙画底景：AI×E-R 未来生出的「语义沙」——会自组织成节点与关系的新物质 */}
      <div className="welcome-sand" aria-hidden="true">
        <img className="welcome-sand-art" src="/semantic-sand.jpg" alt="" />
        <div className="welcome-sand-grain" />
        <div className="welcome-sand-veil" />
      </div>
      <header className="welcome-top">
        <div className="brand">
          <BrandMark />
          <div className="brand-text">
            <strong className="welcome-brand">ERFlow</strong>
            <span className="welcome-brand-sub">{t.brandSub}</span>
          </div>
        </div>

        <div className="top-actions">
          <div className="top-tools">
            <LanguageToggle locale={locale} onChange={setLocale} />
            <a
              className="icon-ghost"
              href={REPO_URL}
              target="_blank"
              rel="noreferrer noopener"
              aria-label={t.github}
              title={t.github}
              data-testid="github-link"
            >
              <svg width="17" height="17" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                <path d="M12 .5A11.5 11.5 0 0 0 .5 12a11.5 11.5 0 0 0 7.86 10.92c.58.1.79-.25.79-.55v-2.1c-3.2.7-3.87-1.36-3.87-1.36-.53-1.33-1.29-1.69-1.29-1.69-1.05-.72.08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.7 1.26 3.36.96.1-.75.4-1.26.73-1.55-2.56-.29-5.25-1.28-5.25-5.7 0-1.26.45-2.29 1.19-3.1-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.18 1.18a11 11 0 0 1 5.79 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.59.23 2.76.12 3.05.74.81 1.18 1.84 1.18 3.1 0 4.43-2.69 5.41-5.26 5.7.41.36.78 1.06.78 2.14v3.17c0 .3.21.66.8.55A11.5 11.5 0 0 0 23.5 12A11.5 11.5 0 0 0 12 .5Z" />
              </svg>
            </a>
            <ThemeToggle theme={theme} onToggle={onToggleTheme} />
          </div>
          <div className="top-session">
            {username ? (
              <AccountMenu
                username={username}
                onLogout={onLogout}
                logoutLabel={t.logout}
                signedInLabel={t.signedIn}
              />
            ) : (
              <button type="button" className="btn btn-ghost" onClick={onLogin} data-testid="login-entry">
                {t.login}
              </button>
            )}
            <button type="button" className="btn top-go" onClick={onOpen} data-testid="enter-workbench">
              {t.enterWorkbench}
            </button>
          </div>
        </div>
      </header>

      <main className="hero" ref={heroRef}>
        {/* 景深层：E-R 与用例符号漂在演示卡周围，建立前后景深 */}
        <div className="hero-space" aria-hidden="true">
          <span className="hero-glyph hero-glyph-entity">
            <i />
            {t.glyphEntity}
          </span>
          <span className="hero-glyph hero-glyph-rel">
            <i />
            {t.glyphRelation}
          </span>
          <span className="hero-glyph hero-glyph-attr">
            <i />
            {t.glyphAttr}
          </span>
          <span className="hero-glyph hero-glyph-actor" title={t.glyphActor}>
            <svg width="22" height="28" viewBox="0 0 22 28" fill="none" aria-hidden="true">
              <circle cx="11" cy="5" r="3.2" stroke="currentColor" strokeWidth="1.4" />
              <path
                d="M11 8.4v9M5.5 12h11M11 17.4 6.2 25M11 17.4 15.8 25"
                stroke="currentColor"
                strokeWidth="1.4"
                strokeLinecap="round"
              />
            </svg>
            {t.glyphActor}
          </span>
          <span className="hero-glyph hero-glyph-usecase">{t.glyphUsecase}</span>
          <span className="hero-glyph hero-glyph-card">
            <b />
            <b />
            <b />
          </span>
          <span className="hero-orb hero-orb-a" />
          <span className="hero-orb hero-orb-b" />
        </div>

        <div className="hero-left">
          <section className="hero-copy">
            <h1>
              {t.heroTitleBefore} <span className="hl">{t.heroBrand}</span>
              <span className="hero-dash" aria-hidden="true">
                -
              </span>
              <span className="hero-sgi" title={t.heroSgi}>
                {t.heroSgi}
              </span>
            </h1>
            <p className="hero-sub">
              {t.heroSub}
              <span className="hero-sub-line">{t.heroSubLine}</span>
            </p>
            <div className="hero-actions">
              <button type="button" className="btn btn-primary btn-lg" onClick={onStart} data-testid="start-drawing">
                {t.startDrawing}
              </button>
              <div className="hero-try" role="group" aria-label={t.trySample}>
                <span className="hero-try-label">{t.trySample}</span>
                <div className="hero-try-switch">
                  {TRY_SAMPLES.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      className="hero-try-btn"
                      onClick={trySampleRun[item.action]}
                      data-testid={item.testId}
                    >
                      {t[item.labelKey]}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </section>

          {/* 三步流程：桌面在按钮下方；移动端拆出包裹后排到演示卡之后 */}
          <div className="hero-guide">
            <ol className="hero-steps" aria-label={t.stepsLabel}>
              {t.steps.map((step, i) => (
                <li key={step}>
                  <span className="step-num" aria-hidden="true">
                    {i + 1}
                  </span>
                  {step}
                </li>
              ))}
            </ol>
            <p className="hero-spec" data-testid="hero-spec" title={`${t.heroSpecLabel} · ${SAMPLE_NAME}`}>
              <span className="hero-spec-label">{t.heroSpecLabel}</span>
              <span>
                <b>{STATS.entities}</b> {t.heroSpecEntity}
              </span>
              <span>
                <b>{STATS.relations}</b> {t.heroSpecRelation}
              </span>
              <span>
                <b>{STATS.attrs}</b> {t.heroSpecAttr}
              </span>
              <span>
                {t.heroSpecFigures} <b>3</b>
              </span>
            </p>
            <p className="hero-note">{t.heroNote}</p>
          </div>
        </div>

        <div className="demo-tilt" ref={tiltRef}>
        {/* 台面 + 阴影托住卡片；tilt 建透视 → turn 跟指针 → sway 常驻立姿 */}
        <div className="demo-desk" aria-hidden="true" />
        <div className="demo-floor" aria-hidden="true" />
        <div className="demo-turn">
        <div className="demo-sway">
        <figure className="demo" data-testid="hero-demo">
          <div className="demo-chrome">
            <span className="demo-dots" aria-hidden="true">
              <i />
              <i />
              <i />
            </span>
            <span className="demo-chrome-title">
              {demoView === 'spec' ? t.demoTitleCourse : demoChrome.title}
            </span>
            {/* 窗口栏右侧跟着当前图变：这套图里到底有什么，一眼能读到 */}
            <span className="demo-chrome-meta" data-testid="demo-meta">
              {demoView === 'spec' ? t.demoMetaSpec : demoChrome.meta}
            </span>
          </div>
          <div className="demo-input">
            <DemoSentence
              key={demoView === 'figure' && demoFigure.kind === 'usecase' ? 'uc' : 'er'}
              live={play === 'write' && demoView === 'figure' && demoFigure.kind === 'er'}
              text={
                demoView === 'figure' && demoFigure.kind === 'usecase'
                  ? DEMO_UC_SENTENCE
                  : DEMO_SENTENCE
              }
              marks={
                demoView === 'figure' && demoFigure.kind === 'usecase' ? DEMO_UC_MARKS : DEMO_MARKS
              }
            />
          </div>
          <div className={'demo-arrow' + (play === 'draw' ? ' is-hot' : '')} aria-hidden="true">
            <span className="demo-arrow-icon">
              <svg width="13" height="13" viewBox="0 0 14 14" fill="none">
                <path d="M7 1v11M3 8.5 7 12.5 11 8.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </span>
            <span className="demo-arrow-text">
              {play === 'write' ? t.demoWrite : play === 'draw' ? t.demoDrawing : t.demoGenerate}
            </span>
          </div>
          <div className="demo-output">
            {/* 白底图装进「纸张」容器，深色下才像一张放在桌面上的图，而不是一块白斑 */}
            <div className="demo-paper">
              <div className="demo-stage">
                {demoView === 'spec' && SPEC ? (
                  <div className="demo-spec" data-testid="demo-spec">
                    <div className="spec-head">
                      <strong>{SPEC.title}</strong>
                      <span>
                        {STATS.entities} {t.heroSpecEntity} · {STATS.relations} {t.heroSpecRelation} · {STATS.attrs}{' '}
                        {t.heroSpecAttr}
                      </span>
                    </div>
                    <div className="spec-group">
                      <span className="spec-group-label">{t.heroSpecEntity}</span>
                      <ul className="spec-list">
                        {SPEC.entities.map((entity) => (
                          <li key={entity.id}>
                            <span className="spec-name">{entity.name}</span>
                            <span className="spec-attrs">
                              {entity.attrs.map((attr) => (
                                <span key={attr.id} className={attr.pk ? 'spec-attr is-pk' : 'spec-attr'}>
                                  {attr.name}
                                </span>
                              ))}
                            </span>
                          </li>
                        ))}
                      </ul>
                    </div>
                    <div className="spec-group">
                      <span className="spec-group-label">{t.heroSpecRelation}</span>
                      <ul className="spec-list">
                        {SPEC.relations.map((relation) => (
                          <li key={relation.id}>
                            <span className="spec-name">{relation.name}</span>
                            <span className="spec-ends">
                              {relation.ends.map((end, i) => (
                                <span className="spec-end" key={`${relation.id}-${i}`}>
                                  <b>{end.card}</b>
                                  {SPEC.entities.find((entity) => entity.id === end.entityId)?.name ??
                                    end.missingName ??
                                    '—'}
                                </span>
                              ))}
                            </span>
                            {relation.attrs.length > 0 && (
                              <span className="spec-attrs">
                                {relation.attrs.map((attr) => (
                                  <span key={attr.id} className="spec-attr">
                                    {attr.name}
                                  </span>
                                ))}
                              </span>
                            )}
                          </li>
                        ))}
                      </ul>
                    </div>
                    <div className="spec-group">
                      <span className="spec-group-label">{t.specScale}</span>
                      <ul className="spec-list spec-meters">
                        {[
                          { label: t.heroSpecEntity, value: STATS.entities, max: 15 },
                          { label: t.heroSpecRelation, value: STATS.relations, max: 30 },
                          {
                            label: t.heroSpecAttr,
                            value: Math.max(...SPEC.entities.map((e) => e.attrs.length)),
                            max: 12,
                            hint: t.specPerEntity,
                          },
                        ].map((meter) => (
                          <li key={meter.label}>
                            <span className="spec-meter-label">{meter.label}</span>
                            <span className="spec-meter" aria-hidden="true">
                              <i style={{ width: `${Math.min(100, (meter.value / meter.max) * 100)}%` }} />
                            </span>
                            <span className="spec-meter-num">
                              {meter.value} / {meter.max}
                              {meter.hint && <em>{meter.hint}</em>}
                            </span>
                          </li>
                        ))}
                      </ul>
                    </div>
                    <p className="spec-foot">
                      {t.specFoot} <code>{SAMPLE_NAME}</code>
                      {t.specFootAfter}
                    </p>
                  </div>
                ) : (
                  <img
                    key={demoFigure.key}
                    className={
                      'demo-main' +
                      (demoIndex === 0 && (play === 'write' || play === 'draw') ? ' is-waiting' : '')
                    }
                    src={demoFigure.src}
                    width={demoFigure.width}
                    height={demoFigure.height}
                    alt={demoFigure.alt}
                  />
                )}
                {demoView === 'figure' && demoIndex === 0 && play !== 'show' && (
                  <DemoSketch drawing={play === 'draw'} leaving={play === 'reveal'} />
                )}
              </div>
            </div>
          </div>
          {/* 图索引：E-R 三张 + 用例图；「规格」页仍是选课 E-R 的另一面 */}
          <div className="demo-files" role="group" aria-label={t.demoFilesAria}>
            {DEMO_FIGURES.map((fig, i) => {
              const label =
                fig.key === 'overview'
                  ? t.demoOverview
                  : fig.key === 'student'
                    ? t.demoStudent
                    : fig.key === 'course'
                      ? t.demoCourse
                      : t.demoUsecase
              const meta =
                fig.key === 'overview'
                  ? t.demoMetaOverview
                  : fig.key === 'student'
                    ? t.demoMetaStudent
                    : fig.key === 'course'
                      ? t.demoMetaCourse
                      : t.demoMetaUsecase
              return (
              <button
                type="button"
                key={fig.key}
                className={'demo-file' + (demoView === 'figure' && i === demoIndex ? ' is-current' : '')}
                aria-pressed={demoView === 'figure' && i === demoIndex}
                title={meta}
                onClick={() => {
                  settlePlay()
                  setDemoIndex(i)
                  setDemoView('figure')
                }}
                data-testid={`demo-file-${fig.key}`}
              >
                {label}
              </button>
              )
            })}
            <button
              type="button"
              className={'demo-file demo-file-spec' + (demoView === 'spec' ? ' is-current' : '')}
              aria-pressed={demoView === 'spec'}
              title={t.demoSpecTitle}
              onClick={() => {
                settlePlay()
                setDemoView('spec')
              }}
              data-testid="demo-file-spec"
            >
              {t.demoSpec}
            </button>
          </div>
        </figure>
        </div>
        </div>
        </div>
      </main>

      <section className="caps" aria-labelledby="caps-title" data-reveal>
        <header className="caps-head">
          <h2 id="caps-title">{t.capsTitle}</h2>
          <p className="caps-lead">{t.capsLead}</p>
        </header>
        <ul className="caps-grid">
          {t.caps.map((cap, i) => (
            <li key={cap.title}>
              <span className="cap-icon" aria-hidden="true">
                <CapGlyph name={CAP_ICONS[i] ?? 'diagram'} />
              </span>
              <h3>{cap.title}</h3>
              <p>{cap.desc}</p>
            </li>
          ))}
        </ul>
      </section>

      <section className="scenes" aria-labelledby="scenes-title" data-reveal>
        <header className="section-head">
          <div>
            <h2 id="scenes-title">{t.scenesTitle}</h2>
            <p>{t.scenesLead}</p>
          </div>
        </header>
        <ul className="scene-grid">
          {SCENARIOS.map((scene) => {
            const copy = t.scenes.find((item) => item.id === scene.id)
            return (
            <li key={scene.id} className="scene-card">
              <div className="scene-top">
                <div className="scene-title-row">
                  <span className="scene-kind">E-R</span>
                  <h3>{copy?.name ?? scene.id}</h3>
                </div>
                <span className="scene-count">
                  {scene.entities.length + 1} {t.sceneFigures}
                </span>
              </div>
              <p className="scene-brief">{copy?.brief}</p>
              <dl className="scene-spec">
                <div>
                  <dt>{t.heroSpecEntity}</dt>
                  <dd>
                    {scene.entities.map((entity) => (
                      <span key={entity} className="scene-chip">
                        {entity}
                      </span>
                    ))}
                  </dd>
                </div>
                <div>
                  <dt>{t.heroSpecRelation}</dt>
                  <dd>
                    {scene.relations.map((relation) => (
                      <span key={relation} className="scene-chip is-rel">
                        {relation}
                      </span>
                    ))}
                  </dd>
                </div>
              </dl>
              <div className="scene-actions">
                <button
                  type="button"
                  className={'scene-copy' + (copied === scene.id ? ' is-done' : '')}
                  onClick={() => copyPrompt(scene.id, scene.prompt)}
                  data-testid={`copy-${scene.id}`}
                >
                  {copied === scene.id ? t.sceneCopied : t.sceneCopy}
                </button>
                {copied === scene.id && (
                  <button type="button" className="link-btn" onClick={onStart}>
                    {t.sceneGo}
                  </button>
                )}
              </div>
            </li>
            )
          })}
        </ul>
        {copyError && (
          <p className="scene-error" role="status">
            {copyError}
          </p>
        )}
      </section>

      <section className="notation" aria-labelledby="notation-title" data-reveal>
        <div className="notation-inner">
          <header className="notation-head">
            <h2 id="notation-title">{t.notationTitle}</h2>
            <p>{t.notationLead}</p>
          </header>
          {notationGroups.map((group) => (
            <div key={group.id} className="notation-group">
              <h3 className="notation-group-title">{group.title}</h3>
              <ul className="notation-grid">
                {group.items.map((item) => (
                  <li key={`${group.id}-${item.name}`}>
                    <span className="notation-fig" aria-hidden="true">
                      <NotationGlyph fig={item.fig as NotationFig} />
                    </span>
                    <strong>{item.name}</strong>
                    <span className="notation-desc">{item.desc}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </section>

      <section className="faq" aria-labelledby="faq-title" data-reveal>
        <header className="section-head">
          <div>
            <h2 id="faq-title">{t.faqTitle}</h2>
            <p>{t.faqLead}</p>
          </div>
        </header>
        <ul className="faq-list">
          {t.faq.map((item) => (
            <li key={item.q}>
              <details>
                <summary>
                  {item.q}
                  <span className="faq-mark" aria-hidden="true" />
                </summary>
                <p>{item.a}</p>
              </details>
            </li>
          ))}
        </ul>
      </section>

      <SiteFooter
        onWorkbench={onOpen}
        note={t.footNote}
        badge={t.footBadge}
        tagline={t.footTagline}
        navLabel={t.footNav}
        homeLabel={t.footHome}
        workbenchLabel={t.footWorkbench}
        freeLabel={t.footFree}
        sgiLabel={t.heroSgi}
      />
    </div>
  )
}
