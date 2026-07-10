"use client";

import { useRef, useEffect } from "react";
import type { ForceGraph3DInstance, LinkObject, NodeObject } from "3d-force-graph";
import type { BufferGeometry, CanvasTexture, ShaderMaterial, Sprite, SpriteMaterial } from "three";
import { type GraphNode, type GraphEdge, TYPE_COLORS, EDGE_COLORS, GRAPH_SCENE, IMPORTANCE_THRESHOLD } from "./types";

export interface Graph3DHandle {
  focusNode: (id: string) => void;
}

interface Props {
  nodes: GraphNode[];
  links: GraphEdge[];
  search: string;
  highlightImportant: boolean;
  selectedNodeId: string | null;
  linkedNodeIds: Set<string> | null;
  width: number;
  height: number;
  onNodeClick: (node: GraphNode) => void;
  onBackgroundClick: () => void;
  onReady?: () => void;
  onMount?: (handle: Graph3DHandle) => void;
}

// Above this node count the graph is considered "large" and cost-reduction paths kick in.
const LARGE_GRAPH_THRESHOLD = 200;

// Fresnel glow shader — all nodes are spheres for best visual quality.
// On large graphs, pulse animation is skipped for non-important nodes (uTime stays 0).
type ThreeModule = typeof import("three");
type ForceGraphNode = GraphNode & NodeObject;
type ForceGraphLink = GraphEdge & LinkObject<ForceGraphNode>;
type GraphInstance = ForceGraph3DInstance<ForceGraphNode, ForceGraphLink>;
type ForceGraphFactory = () => (element: HTMLElement) => GraphInstance;

function createCoreMaterial(THREE: ThreeModule, color: number, importance: number): ShaderMaterial {
  return new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: true,
    uniforms: {
      uColor:      { value: new THREE.Color(color) },
      uTime:       { value: 0 },
      uImportance: { value: importance },
    },
    vertexShader: `
      varying vec3 vNormal;
      varying vec3 vViewDir;
      void main() {
        vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
        vNormal = normalize(normalMatrix * normal);
        vViewDir = normalize(-mvPosition.xyz);
        gl_Position = projectionMatrix * mvPosition;
      }
    `,
    fragmentShader: `
      uniform vec3 uColor;
      uniform float uTime;
      uniform float uImportance;
      varying vec3 vNormal;
      varying vec3 vViewDir;
      void main() {
        float fresnel = pow(1.0 - max(dot(vNormal, vViewDir), 0.0), 2.0);
        float pulse = 0.70 + 0.30 * sin(uTime * 2.0 + uImportance * 8.0);
        vec3 base = uColor * (0.55 + uImportance * 0.9);
        vec3 glow = uColor * fresnel * (1.8 + uImportance * 2.2) * pulse;
        gl_FragColor = vec4(base + glow, 0.92);
      }
    `,
  });
}

// Cache key: hex color string — glow appearance depends only on color, not radius.
// Radius is applied via Sprite.scale at the call site so a single texture covers all sizes.
type GlowCache = Map<string, { texture: CanvasTexture; material: SpriteMaterial }>;

// Soft radial glow using Sprite + canvas radial gradient — no hard sphere edge.
// CanvasTexture and SpriteMaterial are cached by hex color to avoid redundant GPU uploads.
// Each call creates a new Sprite (cheap) that shares the cached texture+material.
function createGlowSprite(
  THREE: ThreeModule,
  color: number,
  radius: number,
  glowCache: GlowCache,
): Sprite {
  const c = new THREE.Color(color);
  const hex = `#${c.getHexString()}`;

  let cached = glowCache.get(hex);
  if (!cached) {
    const size = 256;
    const canvas = document.createElement("canvas");
    canvas.width = size;
    canvas.height = size;
    const ctx = canvas.getContext("2d")!;
    const grad = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
    grad.addColorStop(0,    hex + "55");  // bright center
    grad.addColorStop(0.35, hex + "33");
    grad.addColorStop(0.7,  hex + "11");
    grad.addColorStop(1,    hex + "00");  // transparent edge
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, size, size);
    const texture = new THREE.CanvasTexture(canvas);
    const material = new THREE.SpriteMaterial({
      map: texture,
      transparent: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    cached = { texture, material };
    glowCache.set(hex, cached);
  }

  // Each Sprite is a distinct scene object; sharing the material is safe for THREE.js.
  const sprite = new THREE.Sprite(cached.material);
  const scale = radius * 5;
  sprite.scale.set(scale, scale, 1);
  return sprite;
}

// Floating label: no background box, just clean text with soft shadow
function createSpriteLabel(THREE: ThreeModule, text: string, color: string, size: number): Sprite {
  const W = 512, H = 48;
  const canvas = document.createElement("canvas");
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext("2d")!;
  ctx.clearRect(0, 0, W, H);
  // Soft text shadow for legibility
  ctx.shadowColor = "rgba(0,0,0,0.9)";
  ctx.shadowBlur = 8;
  ctx.fillStyle = color;
  ctx.font = "600 20px Inter, system-ui, sans-serif";
  ctx.fillText(text.slice(0, 32), 4, 34);
  const tex = new THREE.CanvasTexture(canvas);
  const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false });
  const sprite = new THREE.Sprite(mat);
  sprite.scale.set(52, 5, 1);
  sprite.position.set(0, size * 2.6, 0);
  return sprite;
}

function Graph3DInner({
  nodes, links, search, highlightImportant,
  selectedNodeId, linkedNodeIds, width, height,
  onNodeClick, onBackgroundClick, onReady, onMount,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<GraphInstance | null>(null);
  // Keep latest callbacks in refs so the mount-time graph handlers do not go stale.
  const onNodeClickRef = useRef(onNodeClick);
  const onBackgroundClickRef = useRef(onBackgroundClick);
  const onReadyRef = useRef(onReady);
  const onMountRef = useRef(onMount);
  // Shader materials that need per-frame uTime updates (important nodes only on large graphs)
  const animatedMatsRef = useRef<Set<ShaderMaterial>>(new Set());
  // Geometry cache: keyed by Math.round(size * 2) to bucket by size
  const geoCacheRef = useRef<Map<number, BufferGeometry>>(new Map());
  // Glow sprite cache: keyed by hex color — CanvasTexture + SpriteMaterial shared across nodes
  const glowCacheRef = useRef<GlowCache>(new Map());
  // Keep large-graph mode aligned with the latest graphData rebuild.
  const isLargeGraphRef = useRef(false);

  useEffect(() => {
    onNodeClickRef.current = onNodeClick;
    onBackgroundClickRef.current = onBackgroundClick;
    onReadyRef.current = onReady;
    onMountRef.current = onMount;
  }, [onNodeClick, onBackgroundClick, onReady, onMount]);

  useEffect(() => {
    if (!containerRef.current) return;
    let fg: GraphInstance | undefined;
    let rafId = 0;
    let cancelled = false;

    Promise.all([
      import("3d-force-graph"),
      import("three"),
    ]).then(([mod, THREE_mod]) => {
      if (cancelled) return;
      const createForceGraph = mod.default as unknown as ForceGraphFactory;
      const THREE = THREE_mod;
      const animatedMats = animatedMatsRef.current;
      const geoCache = geoCacheRef.current;
      const glowCache = glowCacheRef.current;
      isLargeGraphRef.current = nodes.length >= LARGE_GRAPH_THRESHOLD;

      fg = createForceGraph()(containerRef.current!)
        .width(width)
        .height(height)
        .backgroundColor(GRAPH_SCENE.background)
        .nodeRelSize(5)
        .nodeVal((n: GraphNode) => Math.max(1, 1 + (n.importance ?? 0.5) * 3))
        // nodeColor is used for fallback; actual color is in ShaderMaterial
        .nodeColor((n: GraphNode) => {
          if (n.importance >= IMPORTANCE_THRESHOLD) return GRAPH_SCENE.important;
          return TYPE_COLORS[n.type] ?? TYPE_COLORS.unknown;
        })
        .nodeLabel((n: GraphNode) => {
          const color = TYPE_COLORS[n.type] ?? GRAPH_SCENE.tooltipFallback;
          return `<div style="background:rgba(5,7,12,.95);padding:8px 12px;border-radius:6px;font-size:11px;max-width:320px;border:1px solid ${color};font-family:'SF Mono',monospace">
            <b style="color:${color};text-transform:uppercase;letter-spacing:0.08em">${n.type.replace(/_/g, " ")}</b>
            ${n.importance >= IMPORTANCE_THRESHOLD ? ` <span style="color:${GRAPH_SCENE.important}">★</span>` : ''}
            <br/>${(n.title ?? n.id).slice(0, 140)}
            <br/><span style="color:${GRAPH_SCENE.tooltipMuted};font-size:10px">IMP ${(n.importance ?? 0).toFixed(2)} · INJ ${n.injected_count ?? 0}× · 0x${n.id.replace(/-/g,"").slice(0,8).toUpperCase()}</span>
          </div>`;
        })
        .nodeThreeObject((n: GraphNode) => {
          const isImportant = (n.importance ?? 0) >= IMPORTANCE_THRESHOLD;
          const hexColor = isImportant
            ? Number.parseInt(GRAPH_SCENE.important.slice(1), 16)
            : parseInt((TYPE_COLORS[n.type] ?? TYPE_COLORS.unknown).slice(1), 16);
          const typeColor = TYPE_COLORS[n.type] ?? TYPE_COLORS.unknown;
          const size = 2 + (n.importance ?? 0.5) * 3;

          const group = new THREE.Group();

          // Core sphere with Fresnel shader (always sphere — best visual quality)
          // Geometry cache: bucket by size to avoid creating a new geometry per node
          const geoKey = Math.round(size * 2);
          if (!geoCache.has(geoKey)) {
            geoCache.set(geoKey, new THREE.SphereGeometry(size, 32, 24));
          }
          const geo = geoCache.get(geoKey);
          const coreMat = createCoreMaterial(THREE, hexColor, n.importance ?? 0.5);
          const core = new THREE.Mesh(geo, coreMat);
          core.userData.coreMaterial = coreMat;
          group.add(core);
          group.userData.core = core;
          group.userData.nodeId = n.id;

          // On large graphs only animate important nodes; regular nodes use a frozen pulse.
          // On small graphs animate all nodes as before.
          if (!isLargeGraphRef.current || isImportant) {
            animatedMats.add(coreMat);
          }

          // Soft radial glow Sprite — texture/material cached by hex color
          group.add(createGlowSprite(THREE, hexColor, size, glowCache));

          // Important nodes: extra outer halo Sprite + floating label
          if (isImportant) {
            const haloSprite = createGlowSprite(THREE, hexColor, size * 1.8, glowCache);
            group.add(haloSprite);
            group.add(createSpriteLabel(THREE, n.title ?? n.id, typeColor, size));
          }

          return group;
        })
        .nodeThreeObjectExtend(false)
        // Edge: color + per-type particle flow; reduced on large graphs
        .linkColor((l: GraphEdge) => EDGE_COLORS[l.relation_type] ?? GRAPH_SCENE.fallbackEdge)
        .linkOpacity(((l: GraphEdge) => l.relation_type === "related_to" ? 0.25 : 0.55) as unknown as number)
        .linkWidth((l: GraphEdge) => Math.min(4, 0.8 + (l.weight ?? 1) * 1.2))
        .linkDirectionalParticles((l: GraphEdge) => {
          // Disable particles entirely on large graphs to avoid per-link rAF cost
          if (isLargeGraphRef.current) return 0;
          if (l.relation_type === "contradicts") return 5;
          if (l.relation_type === "supersedes") return 4;
          if (l.relation_type === "supports") return 3;
          if (l.relation_type === "causes") return 2;
          return 1;
        })
        .linkDirectionalParticleWidth((l: GraphEdge) => 1.2 + (l.weight ?? 1) * 0.7)
        .linkDirectionalParticleSpeed((l: GraphEdge) => {
          if (l.relation_type === "contradicts") return 0.012;
          if (l.relation_type === "supersedes") return 0.009;
          if (l.relation_type === "causes") return 0.007;
          return 0.0045;
        })
        .linkDirectionalParticleColor((l: GraphEdge) => EDGE_COLORS[l.relation_type] ?? GRAPH_SCENE.particle)
        .onNodeClick((n: GraphNode) => onNodeClickRef.current(n))
        .onBackgroundClick(() => onBackgroundClickRef.current())
        .onEngineStop(() => { onReadyRef.current?.(); })
        .graphData({
          nodes: nodes.map((n) => ({ ...n })),
          links: links.map((l) => ({ ...l })),
        });

      // Scene: fog + lighting for depth
      const scene = fg.scene();
      const renderer = fg.renderer();
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, GRAPH_SCENE.maxPixelRatio));
      scene.fog = new THREE.FogExp2(GRAPH_SCENE.background, GRAPH_SCENE.fogDensity);
      const ambient = new THREE.AmbientLight(GRAPH_SCENE.ambientLight, 0.5);
      const keyLight = new THREE.PointLight(GRAPH_SCENE.keyLight, 2.0, 1000);
      keyLight.position.set(80, 120, 120);
      const fillLight = new THREE.PointLight(GRAPH_SCENE.fillLight, 0.4, 600);
      fillLight.position.set(-80, -60, 60);
      scene.add(ambient, keyLight, fillLight);

      // Force layout: importance-driven charge + semantic link distances
      fg.d3Force("charge")?.strength((n: GraphNode) => -60 - (n.importance ?? 0.5) * 120);
      fg.d3Force("link")
        ?.distance((l: GraphEdge) => {
          if (l.relation_type === "part_of") return 28;
          if (l.relation_type === "contradicts") return 100;
          if (l.relation_type === "supersedes") return 75;
          return 55 / Math.sqrt(Math.max(0.25, l.weight ?? 1));
        })
        .strength((l: GraphEdge) => {
          if (l.relation_type === "part_of") return 0.9;
          if (l.relation_type === "supports") return 0.55;
          if (l.relation_type === "contradicts") return 0.18;
          return 0.35;
        });
      fg.d3Force("center")?.strength(0.06);
      fg.d3AlphaDecay(0.025);
      fg.d3VelocityDecay(0.28);
      // warmupTicks: run a few ticks before first render for better initial layout
      // cooldownTicks: stop simulation quickly to avoid blocking the main thread
      fg.warmupTicks(30).cooldownTicks(60);

      graphRef.current = fg;

      // Expose focusNode handle to parent via onMount prop
      onMountRef.current?.({
        focusNode(id: string) {
          const fgCurrent = graphRef.current;
          if (!fgCurrent) return;
          const graphData = fgCurrent.graphData();
          const node = graphData.nodes.find((candidate) => candidate.id === id);
          if (!node || node.x == null || node.y == null || node.z == null) return;
          const position = { x: node.x, y: node.y, z: node.z };
          const distance = 120;
          const mag = Math.hypot(position.x, position.y, position.z) || 1;
          const distRatio = 1 + distance / mag;
          fgCurrent.cameraPosition(
            { x: position.x * distRatio, y: position.y * distRatio, z: position.z * distRatio },
            position,
            800
          );
        },
      });

      // Drive ShaderMaterial uTime via rAF (onRenderFramePre not available in this version)
      const tick = () => {
        const t = performance.now() * 0.001;
        for (const mat of animatedMats) {
          if (mat.uniforms?.uTime) mat.uniforms.uTime.value = t;
        }
        rafId = requestAnimationFrame(tick);
      };
      rafId = requestAnimationFrame(tick);
    });

    return () => {
      cancelled = true;
      cancelAnimationFrame(rafId);
      // Dispose all THREE.js GPU resources to prevent WebGL memory leaks
      for (const mat of animatedMatsRef.current) {
        mat.dispose?.();
      }
      animatedMatsRef.current.clear();
      for (const geo of geoCacheRef.current.values()) {
        geo.dispose?.();
      }
      geoCacheRef.current.clear();
      // Dispose cached glow textures and materials (shared across nodes)
      for (const { texture, material } of glowCacheRef.current.values()) {
        texture.dispose?.();
        material.dispose?.();
      }
      glowCacheRef.current.clear();
      fg?._destructor?.();
      if (containerRef.current) containerRef.current.innerHTML = "";
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Re-render when filtered data changes
  useEffect(() => {
    const fg = graphRef.current;
    if (!fg) return;
    // Dispose old shader materials before rebuilding node objects
    for (const mat of animatedMatsRef.current) {
      mat.dispose?.();
    }
    animatedMatsRef.current.clear();
    for (const geo of geoCacheRef.current.values()) {
      geo.dispose?.();
    }
    geoCacheRef.current.clear();
    // Dispose and clear glow cache so new node colors get fresh textures
    for (const { texture, material } of glowCacheRef.current.values()) {
      texture.dispose?.();
      material.dispose?.();
    }
    glowCacheRef.current.clear();
    isLargeGraphRef.current = nodes.length >= LARGE_GRAPH_THRESHOLD;
    fg.graphData({
      nodes: nodes.map((n) => ({ ...n })),
      links: links.map((l) => ({ ...l })),
    });
  }, [nodes, links]);

  // Size
  useEffect(() => {
    graphRef.current?.width(width).height(height);
  }, [width, height]);

  // Selection / search visual state via nodeColor (works alongside ShaderMaterial for fallback)
  useEffect(() => {
    const fg = graphRef.current;
    if (!fg) return;
    const hitIds =
      search.length > 1
        ? new Set(
            nodes
              .filter(
                (n) =>
                  (n.title ?? "").toLowerCase().includes(search.toLowerCase()) ||
                  n.type.toLowerCase().includes(search.toLowerCase())
              )
              .map((n) => n.id)
          )
        : null;

    fg.nodeColor((n: GraphNode) => {
      if (selectedNodeId) {
        if (n.id === selectedNodeId) return GRAPH_SCENE.selected;
        if (linkedNodeIds?.has(n.id)) {
          if (highlightImportant && (n.importance ?? 0) >= IMPORTANCE_THRESHOLD) return GRAPH_SCENE.important;
          return TYPE_COLORS[n.type] ?? TYPE_COLORS.unknown;
        }
        return GRAPH_SCENE.dimNode;
      }
      if (hitIds) {
        if (!hitIds.has(n.id)) return GRAPH_SCENE.hiddenNode;
      }
      if (highlightImportant && (n.importance ?? 0) >= IMPORTANCE_THRESHOLD) return GRAPH_SCENE.important;
      return TYPE_COLORS[n.type] ?? TYPE_COLORS.unknown;
    });
  }, [search, highlightImportant, selectedNodeId, linkedNodeIds, nodes]);

  return <div ref={containerRef} className="w-full h-full" />;
}

export default Graph3DInner;
