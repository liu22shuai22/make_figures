interface BrandMarkProps {
  /** 边长（px），默认 34 */
  size?: number
  className?: string
}

/**
 * 品牌标记：把 E-R 记法本身做成图标——
 * 实体矩形 + 关系菱形 + 属性椭圆，三角构图、斜向连线。
 * 构图要点：三个图形的包围盒要近似以 (16,16) 为光学中心，
 * 矩形内孔 ≥7×4 单位，否则小尺寸下白色描边会糊成实心色块。
 */
export default function BrandMark({ size = 34, className }: BrandMarkProps) {
  return (
    <span
      className={className ? `brand-mark ${className}` : 'brand-mark'}
      style={{
        width: size,
        height: size,
        borderRadius: Math.max(6, Math.round(size * 0.27)),
      }}
      aria-hidden="true"
    >
      <svg viewBox="0 0 32 32" width={size} height={size} fill="none" aria-hidden="true">
        {/* 实体：矩形（左上） */}
        <rect
          x="4.5"
          y="6"
          width="11"
          height="7.5"
          rx="2.2"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
        />
        {/* 实体 — 关系 连线 */}
        <path d="M15.5 9.75h2.7" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        {/* 关系：菱形（右上） */}
        <path
          d="M22.8 5.15 27.4 9.75 22.8 14.35 18.2 9.75Z"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinejoin="round"
        />
        {/* 实体 — 属性 斜向连线 */}
        <path d="M10 13.5 14 20" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        {/* 属性：椭圆（下方居中） */}
        <ellipse cx="16" cy="23.2" rx="5" ry="3.4" fill="none" stroke="currentColor" strokeWidth="1.6" />
      </svg>
    </span>
  )
}
