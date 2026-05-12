# Memory Platform Project Book Frontend Design Brief

## Intent

Create a local, multi-file frontend that makes the OpenMemory + Qdrant multi-agent memory platform project book easy to understand at a glance and useful as a planning artifact.

The output is not a production app. It is a designed explanatory artifact / interactive project briefing that can be opened directly in a browser from local files.

## Audience

- The user as project owner.
- Future AI agents reading the plan.
- A developer deciding what to implement next.

## Content source

Use the project book at:

`/home/advancer/.agent-memory/local-memory-mcp/docs/plans/2026-05-12-openmemory-qdrant-memory-platform-project-book.md`

Do not invent strategic claims beyond that content. You may compress and reorganize it visually.

## Deliverable path

Create a folder:

`/home/advancer/.agent-memory/local-memory-mcp/docs/memory-platform-briefing/`

Required files:

- `index.html`
- `styles.css`
- `app.js`
- `data.js`
- optional `README.md`

No build step. No npm dependencies. No remote dependencies. Must open via `file:///.../index.html`.

## Design posture

Use a clear technical strategy-room aesthetic, not generic SaaS marketing.

Visual language:

- Dark, calm technical canvas.
- Strong information hierarchy.
- One cyan/blue accent plus amber for risk/temporal warnings and green for ready/stable states.
- Dense but readable.
- Diagrams and timelines should be more important than decorative cards.
- Avoid fake metrics and generic icon grids.

Design system:

- CSS variables for color, spacing, radius, shadow.
- Responsive layout.
- Semantic HTML.
- Accessible contrast.
- Keyboard-friendly navigation.
- Respect `prefers-reduced-motion`.

## Page structure

Make one composite page with sticky navigation and multiple sections:

1. Hero / executive summary
   - Explain one-sentence thesis: local-memory-mcp becomes an adapter/governance layer, OpenMemory + Qdrant take over heavy memory capabilities.
   - Show key stack: OpenMemory/mem0, Qdrant, local MCP adapter, SQLite Ops DB, future Graphiti/Zep.

2. Architecture map
   - Visual diagram from Agents → Adapter → OpenMemory/Qdrant/SQLite → future temporal layer.
   - Include short responsibility notes for each layer.

3. Responsibility split
   - “Replace / outsource” vs “Keep in local adapter”.
   - Make it obvious which parts move to mature products and which remain local.

4. Data model explorer
   - Show MemoryRecord fields grouped by identity, governance, temporal, provenance.
   - Include tabs or filters for type/status meanings.

5. Temporal governance
   - Explain time evolution, contradiction handling, and fact expiration as a lifecycle diagram.
   - Include example: old model preference superseded by new active model.

6. Roadmap
   - Seven phases, with milestones and acceptance highlights.
   - Visual timeline or kanban lanes.

7. Migration strategy
   - Show double-write then read-switch then rollback.
   - Include migration order by memory type.

8. Risk matrix
   - Risks, impact, mitigation from the project book.

9. Implementation task board
   - 12 tasks, grouped by milestone.
   - Interactive filter by phase/milestone/status category.

10. Decision summary
   - Final recommended architecture and why.
   - Explicitly state server-memory is fallback/compat, not primary.

## Interactions

Keep interactions useful and local:

- Sticky section navigation.
- Search/filter tasks.
- Toggle between “Architecture”, “Migration”, “Temporal” focus if useful.
- Clickable roadmap phases showing details.
- Data model tabs.
- “Copy config skeleton” button for config YAML.
- Persist selected phase/tabs in localStorage if easy.

## Content data

Put structured content in `data.js` as a single global object, e.g. `window.memoryPlatformData = {...}`.

`app.js` should render repeated sections from this data rather than duplicating everything in HTML.

## Verification requirements

After coding:

1. Check files exist.
2. Run a basic local static check, e.g. Python script or Node syntax check.
3. Open with browser if available and check console errors.

## Final artifact expectation

The page should feel like an internal strategy dashboard / interactive implementation brief, not a blog post. It should make the plan comprehensible in 3 minutes and still useful after 30 minutes.
