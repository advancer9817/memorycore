"use client"

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { CiCalendarIcon as CiCalendar, GoPackageIcon as GoPackage, HiMiniRectangleStackIcon as HiMiniRectangleStack, PiSwatchesIcon as PiSwatches } from "@/components/shared/react-icons"
import { MoreHorizontal } from "lucide-react"
import { useI18n } from "@/hooks/useI18n"

export function MemoryTableSkeleton() {
  const { messages } = useI18n()
  const loadingRows = Array(5).fill(null)

  return (
    <div className="rounded-md border">
      <Table>
        <TableHeader>
          <TableRow className="bg-zinc-800 hover:bg-zinc-800">
            <TableHead className="w-[50px] pl-4">
              <div className="h-4 w-4 rounded bg-zinc-700/50 animate-pulse" />
            </TableHead>
            <TableHead className="border-zinc-700">
              <div className="flex items-center min-w-[600px]">
                <HiMiniRectangleStack className="mr-1" />
                {messages.memories.memory}
              </div>
            </TableHead>
            <TableHead className="border-zinc-700">
              <div className="flex items-center">
                <PiSwatches className="mr-1" size={15} />
                {messages.memories.categories}
              </div>
            </TableHead>
            <TableHead className="w-[140px] border-zinc-700">
              <div className="flex items-center">
                <GoPackage className="mr-1" />
                {messages.memories.sourceApp}
              </div>
            </TableHead>
            <TableHead className="w-[140px] border-zinc-700">
              <div className="flex items-center w-full justify-center">
                <CiCalendar className="mr-1" size={16} />
                {messages.memories.createdOn}
              </div>
            </TableHead>
            <TableHead className="text-right border-zinc-700 flex justify-center">
              <div className="flex items-center justify-end">
                <MoreHorizontal className="h-4 w-4 mr-2" />
              </div>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {loadingRows.map((_, index) => (
            <TableRow key={index} className="animate-pulse">
              <TableCell className="pl-4">
                <div className="h-4 w-4 rounded bg-zinc-800" />
              </TableCell>
              <TableCell>
                <div className="h-4 w-3/4 bg-zinc-800 rounded" />
              </TableCell>
              <TableCell>
                <div className="flex gap-1">
                  <div className="h-5 w-16 bg-zinc-800 rounded-full" />
                  <div className="h-5 w-16 bg-zinc-800 rounded-full" />
                </div>
              </TableCell>
              <TableCell className="w-[140px]">
                <div className="h-6 w-24 mx-auto bg-zinc-800 rounded" />
              </TableCell>
              <TableCell className="w-[140px]">
                <div className="h-4 w-20 mx-auto bg-zinc-800 rounded" />
              </TableCell>
              <TableCell>
                <div className="h-8 w-8 bg-zinc-800 rounded mx-auto" />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
