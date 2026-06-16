"use client";

import dynamic from "next/dynamic";
import { GraphFilterPanel } from "./GraphFilterPanel";
import { GraphNodeList } from "./GraphNodeList";
import { GraphNodeDetail } from "./GraphNodeDetail";
import { GraphTopbar } from "./GraphTopbar";
import { useResizable } from "./useResizable";
import { useGraphPage } from "./useGraphPage";
import { Button } from "@/components/ui/button";

const Graph3D = dynamic(() => import("./Graph3D"), { ssr: false });

export default function GraphPage() {
  const {
    g, data, loading, error, search, searchInput, setSearchInput,
    activeTypes, activeEdgeTypes, activeStatus, setActiveStatus,
    highlightImportant, setHighlightImportant, selectedNode, setSelectedNode,
    fullContent, listCollapsed, setListCollapsed, graphReady, setGraphReady,
    isEditing, setIsEditing, editImportance, setEditImportance, editStatus, setEditStatus,
    dims, filtersOpen, setFiltersOpen, limit, setLimit,
    containerRef, listScrollRef, graph3DHandleRef,
    allTypes, allEdgeTypes, filteredNodes, sortedListNodes, filteredEdges, importantCount,
    rowVirtualizer, linked,
    toggleType, toggleEdgeType, resetAll, handleNodeSelect, handleExportJson, handleSave,
    handleRetry,
  } = useGraphPage();

  // onMount prop pattern: avoids forwardRef + next/dynamic HOC ref-transparency issue
  const listPanel = useResizable(260, 160, 420, "right");
  const detailPanel = useResizable(320, 220, 500, "left");

  return (
    <div className="flex flex-col h-[calc(100vh-56px)] bg-[#020408]">

      {/* ══ Topbar: brand · search(center) · actions ══ */}
      <GraphTopbar
        listCollapsed={listCollapsed}
        setListCollapsed={setListCollapsed}
        searchInput={searchInput}
        setSearchInput={setSearchInput}
        data={data}
        filteredNodesLength={filteredNodes.length}
        filteredEdgesLength={filteredEdges.length}
        highlightImportant={highlightImportant}
        setHighlightImportant={setHighlightImportant}
        importantCount={importantCount}
        resetAll={resetAll}
        limit={limit}
        setLimit={setLimit}
        handleExportJson={handleExportJson}
        messages={g}
      />

      {/* ══ Main area ══ */}
      <div className="flex-1 relative overflow-hidden">

        {/* 3D canvas */}
        <div ref={containerRef} className="absolute inset-0">
          {loading && (
            <div className="absolute inset-0 flex items-center justify-center">
              <span className="font-mono text-xs text-zinc-700 tracking-widest">{g.loading}</span>
            </div>
          )}
          {error && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-red-400 text-sm">
              <span>{error}</span>
              <Button variant="outline" size="sm" className="border-red-800/60 bg-red-950/30 text-red-300 hover:bg-red-900/40" onClick={handleRetry}>
                {g.reset}
              </Button>
            </div>
          )}
          {data && (
            <>
              {!graphReady && (
                <div className="absolute inset-0 flex items-center justify-center z-10" style={{ background: "rgba(2,4,8,0.7)" }}>
                  <div className="flex items-center gap-2 font-mono text-xs text-cyan-700">
                    <span className="w-1 h-1 rounded-full bg-cyan-500 animate-pulse" />
                    {g.computingLayout}
                  </div>
                </div>
              )}
              <Graph3D
                onMount={(h) => { graph3DHandleRef.current = h; }}
                nodes={filteredNodes}
                links={filteredEdges}
                search={search}
                highlightImportant={highlightImportant}
                selectedNodeId={selectedNode?.id ?? null}
                linkedNodeIds={linked}
                width={dims.w}
                height={dims.h}
                onNodeClick={handleNodeSelect}
                onBackgroundClick={() => setSelectedNode(null)}
                onReady={() => setGraphReady(true)}
              />
            </>
          )}
        </div>

        {/* ══ Left panel: filters + list ══ */}
        {!listCollapsed && (
          <div
            className="absolute left-0 top-0 bottom-0 z-20 flex flex-col overflow-hidden"
            style={{ width: listPanel.size, background: "rgba(3,5,10,0.94)", backdropFilter: "blur(16px)", borderRight: "1px solid rgba(255,255,255,0.06)" }}
          >
            <GraphFilterPanel
              allTypes={allTypes} allEdgeTypes={allEdgeTypes}
              activeTypes={activeTypes} activeEdgeTypes={activeEdgeTypes}
              activeStatus={activeStatus} filtersOpen={filtersOpen}
              setFiltersOpen={setFiltersOpen} toggleType={toggleType}
              toggleEdgeType={toggleEdgeType} setActiveStatus={setActiveStatus}
              messages={g}
            />
            <GraphNodeList
              sortedListNodes={sortedListNodes} selectedNode={selectedNode}
              linked={linked} listScrollRef={listScrollRef}
              rowVirtualizer={rowVirtualizer} handleNodeSelect={handleNodeSelect}
              messages={g}
            />
            {/* Resize handle */}
            <div onMouseDown={listPanel.onMouseDown} className="absolute top-0 right-0 bottom-0 w-1 cursor-col-resize hover:bg-cyan-500/20 transition-colors" />
          </div>
        )}

        {/* ══ Right detail panel ══ */}
        {selectedNode && (
          <div className="absolute right-0 top-0 bottom-0 z-20 flex" style={{ width: detailPanel.size }}>
            <div onMouseDown={detailPanel.onMouseDown} className="shrink-0 w-1 cursor-col-resize hover:bg-cyan-500/20 transition-colors" />
            <GraphNodeDetail
              selectedNode={selectedNode} fullContent={fullContent}
              isEditing={isEditing} editImportance={editImportance} editStatus={editStatus}
              setEditImportance={setEditImportance} setEditStatus={setEditStatus}
              setIsEditing={setIsEditing} setSelectedNode={setSelectedNode}
              onSave={handleSave} filteredNodes={filteredNodes} linked={linked}
              handleNodeSelect={handleNodeSelect} messages={g}
            />
          </div>
        )}
      </div>
    </div>
  );
}
