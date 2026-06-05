"use client";

import { useRef, useEffect, useImperativeHandle, forwardRef } from "react";
import { type GraphNode, type GraphEdge, TYPE_COLORS, EDGE_COLORS, IMPORTANCE_THRESHOLD } from "./types";

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
}

export interface Graph3DHandle {
  focusNode: (id: string) => void;
}

// Fresnel glow shader — all nodes are spheres for best visual quality
function createCoreMaterial(THREE: any, color: number, importance: number): any {
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

// Soft radial glow using Sprite + canvas radial gradient — no hard sphere edge
function createGlowSprite(THREE: any, color: number, radius: number): any {
  const size = 256;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d")!;
  const c = new THREE.Color(color);
  const hex = `#${c.getHexString()}`;
  const grad = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  grad.addColorStop(0,    hex + "55");  // bright center
  grad.addColorStop(0.35, hex + "33");
  grad.addColorStop(0.7,  hex + "11");
  grad.addColorStop(1,    hex + "00");  // transparent edge
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, size, size);
  const tex = new THREE.CanvasTexture(canvas);
  const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false });
  const sprite = new THREE.Sprite(mat);
  const scale = radius * 5;
  sprite.scale.set(scale, scale, 1);
  return sprite;
}

// Floating label: no background box, just clean text with soft shadow
function createSpriteLabel(THREE: any, text: string, color: string, size: number): any {
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

const Graph3DInner = forwardRef<Graph3DHandle, Props>(function Graph3D({
  nodes, links, search, highlightImportant,
  selectedNodeId, linkedNodeIds, width, height,
  onNodeClick, onBackgroundClick, onReady,
}, ref) {
  const containerRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<any>(null);
  // Track animated shader materials for per-frame uTime update
  const animatedMatsRef = useRef<Set<any>>(new Set());

  // Expose focusNode to parent
  useImperativeHandle(ref, () => ({
    focusNode(id: string) {
      const fg = graphRef.current;
      if (!fg) return;
      const graphData = fg.graphData();
      const node = graphData.nodes.find((n: any) => n.id === id);
      if (!node || node.x == null) return;
      const distance = 120;
      const mag = Math.hypot(node.x, node.y, node.z) || 1;
      const distRatio = 1 + distance / mag;
      fg.cameraPosition(
        { x: node.x * distRatio, y: node.y * distRatio, z: node.z * distRatio },
        node,
        800
      );
    },
  }), []);

  useEffect(() => {
    if (!containerRef.current) return;
    let fg: any;
    let rafId = 0;

    Promise.all([
      import("3d-force-graph"),
      import("three"),
    ]).then(([mod, THREE_mod]) => {
      const ForceGraph3D = mod.default;
      const THREE = THREE_mod as any;
      const animatedMats = animatedMatsRef.current;

      // eslint-disable-next-line @typescript-eslint/ban-ts-comment
      // @ts-ignore
      fg = ForceGraph3D()(containerRef.current!)
        .width(width)
        .height(height)
        .backgroundColor("#020408")
        .nodeRelSize(5)
        .nodeVal((n: GraphNode) => Math.max(1, 1 + (n.importance ?? 0.5) * 3))
        // nodeColor is used for fallback; actual color is in ShaderMaterial
        .nodeColor((n: GraphNode) => {
          if (n.importance >= IMPORTANCE_THRESHOLD) return "#FBBF24";
          return TYPE_COLORS[n.type] ?? TYPE_COLORS.unknown;
        })
        .nodeLabel((n: GraphNode) => {
          const color = TYPE_COLORS[n.type] ?? "#888";
          return `<div style="background:rgba(5,7,12,.95);padding:8px 12px;border-radius:6px;font-size:11px;max-width:320px;border:1px solid ${color};font-family:'SF Mono',monospace">
            <b style="color:${color};text-transform:uppercase;letter-spacing:0.08em">${n.type.replace(/_/g, " ")}</b>
            ${n.importance >= IMPORTANCE_THRESHOLD ? ' <span style="color:#FBBF24">★</span>' : ''}
            <br/>${(n.title ?? n.id).slice(0, 140)}
            <br/><span style="color:#475569;font-size:10px">IMP ${(n.importance ?? 0).toFixed(2)} · INJ ${n.injected_count ?? 0}× · 0x${n.id.replace(/-/g,"").slice(0,8).toUpperCase()}</span>
          </div>`;
        })
        .nodeThreeObject((n: GraphNode) => {
          const isImportant = (n.importance ?? 0) >= IMPORTANCE_THRESHOLD;
          const hexColor = isImportant
            ? 0xFBBF24
            : parseInt((TYPE_COLORS[n.type] ?? TYPE_COLORS.unknown).slice(1), 16);
          const typeColor = TYPE_COLORS[n.type] ?? TYPE_COLORS.unknown;
          const size = 2 + (n.importance ?? 0.5) * 3;

          const group = new THREE.Group();

          // Core sphere with Fresnel shader (always sphere — best visual quality)
          const geo = new THREE.SphereGeometry(size, 32, 20);
          const coreMat = createCoreMaterial(THREE, hexColor, n.importance ?? 0.5);
          const core = new THREE.Mesh(geo, coreMat);
          core.userData.coreMaterial = coreMat;
          group.add(core);
          group.userData.core = core;
          group.userData.nodeId = n.id;
          animatedMats.add(coreMat);

          // Soft radial glow Sprite (no hard sphere edge)
          group.add(createGlowSprite(THREE, hexColor, size));

          // Important nodes: extra outer halo Sprite + floating label
          if (isImportant) {
            const haloSprite = createGlowSprite(THREE, hexColor, size * 1.8);
            group.add(haloSprite);
            group.add(createSpriteLabel(THREE, n.title ?? n.id, typeColor, size));
          }

          return group;
        })
        .nodeThreeObjectExtend(false)
        // Edge: color + per-type particle flow
        .linkColor((l: GraphEdge) => EDGE_COLORS[l.relation_type] ?? "#3F3F46")
        .linkOpacity((l: GraphEdge) => l.relation_type === "related_to" ? 0.25 : 0.55)
        .linkWidth((l: GraphEdge) => Math.min(4, 0.8 + (l.weight ?? 1) * 1.2))
        .linkDirectionalParticles((l: GraphEdge) => {
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
        .linkDirectionalParticleColor((l: GraphEdge) => EDGE_COLORS[l.relation_type] ?? "#9ca3af")
        .onNodeClick((n: GraphNode) => onNodeClick(n))
        .onBackgroundClick(() => onBackgroundClick())
        .onEngineStop(() => { onReady?.(); })
        .graphData({
          nodes: nodes.map((n) => ({ ...n })),
          links: links.map((l) => ({ ...l })),
        });

      // Scene: fog + lighting for depth
      const scene = fg.scene();
      const renderer = fg.renderer();
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      scene.fog = new THREE.FogExp2("#020408", 0.0015);
      const ambient = new THREE.AmbientLight(0x06B6D4, 0.5);
      const keyLight = new THREE.PointLight(0x7dd3fc, 2.0, 1000);
      keyLight.position.set(80, 120, 120);
      const fillLight = new THREE.PointLight(0xFBBF24, 0.4, 600);
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
      cancelAnimationFrame(rafId);
      animatedMatsRef.current.clear();
      fg?._destructor?.();
      if (containerRef.current) containerRef.current.innerHTML = "";
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Re-render when filtered data changes
  useEffect(() => {
    const fg = graphRef.current;
    if (!fg) return;
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
        if (n.id === selectedNodeId) return "#60A5FA";
        if (linkedNodeIds?.has(n.id)) {
          if (highlightImportant && (n.importance ?? 0) >= IMPORTANCE_THRESHOLD) return "#FBBF24";
          return TYPE_COLORS[n.type] ?? TYPE_COLORS.unknown;
        }
        return "rgba(30,30,35,0.10)";
      }
      if (hitIds) {
        if (!hitIds.has(n.id)) return "rgba(30,30,35,0.08)";
      }
      if (highlightImportant && (n.importance ?? 0) >= IMPORTANCE_THRESHOLD) return "#FBBF24";
      return TYPE_COLORS[n.type] ?? TYPE_COLORS.unknown;
    });
  }, [search, highlightImportant, selectedNodeId, linkedNodeIds, nodes]);

  return <div ref={containerRef} className="w-full h-full" />;
});

export default Graph3DInner;
