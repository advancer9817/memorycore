'use client'

import { useEffect, useState } from 'react'
import { formatDate } from '@/lib/helpers'

interface RelativeTimeProps {
  timestamp: number | string
}

export function RelativeTime({ timestamp }: RelativeTimeProps) {
  const [label, setLabel] = useState<string>('')

  useEffect(() => {
    setLabel(formatDate(timestamp))
    const timer = setInterval(() => setLabel(formatDate(timestamp)), 60_000)
    return () => clearInterval(timer)
  }, [timestamp])

  return <span suppressHydrationWarning>{label}</span>
}
