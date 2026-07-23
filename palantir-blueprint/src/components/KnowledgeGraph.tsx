import { useRef, useState } from "react";
import { Tag, Intent } from "@blueprintjs/core";

type NodeType = "patient" | "condition" | "medication" | "lab" | "trial" | "relation";

interface GraphNode {
  id: string;
  label: string;
  sublabel?: string;
  type: NodeType;
  x: number;
  y: number;
  nctId?: string;
}

interface GraphEdge {
  from: string;
  to: string;
  label: string;
}

const NODE_COLORS: Record<NodeType, { fill: string; stroke: string; text: string }> = {
  patient:    { fill: "var(--graph-patient-fill)", stroke: "var(--graph-patient-stroke)", text: "var(--graph-patient-text)" },
  condition:  { fill: "var(--graph-condition-fill)", stroke: "var(--graph-condition-stroke)", text: "var(--graph-condition-text)" },
  medication: { fill: "var(--graph-medication-fill)", stroke: "var(--graph-medication-stroke)", text: "var(--graph-medication-text)" },
  lab:        { fill: "var(--graph-lab-fill)", stroke: "var(--graph-lab-stroke)", text: "var(--graph-lab-text)" },
  trial:      { fill: "var(--graph-trial-fill)", stroke: "var(--graph-trial-stroke)", text: "var(--graph-trial-text)" },
  relation:   { fill: "var(--graph-relation-fill)", stroke: "var(--graph-relation-stroke)", text: "var(--graph-relation-text)" },
};

interface KnowledgeGraphProps {
  onTrialClick?: (nctId: string) => void;
  highlightedNct?: string | null;
  // When provided, live data from the query response replaces the static demo graph.
  nodes?: GraphNode[];
  edges?: GraphEdge[];
}

export default function KnowledgeGraph({ onTrialClick, highlightedNct, nodes: propNodes, edges: propEdges }: KnowledgeGraphProps) {
  const liveNodes = propNodes ?? [];
  const liveEdges = propEdges ?? [];

  const svgRef = useRef<SVGSVGElement>(null);
  const [positions, setPositions] = useState<Record<string, { x: number; y: number }>>(
    () => Object.fromEntries(liveNodes.map((n) => [n.id, { x: n.x, y: n.y }]))
  );
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);
  const [hoveredEdge, setHoveredEdge] = useState<number | null>(null);

  // Re-seed positions only when the live node identity set changes (new query result).
  const prevNodeIdsRef = useRef<string>("");
  const nodeIdKey = liveNodes.map((n) => n.id).join(",");
  if (nodeIdKey !== prevNodeIdsRef.current) {
    prevNodeIdsRef.current = nodeIdKey;
    // Merge: preserve existing drag positions, seed new nodes at their suggested coords.
    setPositions((prev) => {
      const next: Record<string, { x: number; y: number }> = {};
      liveNodes.forEach((n) => {
        next[n.id] = prev[n.id] ?? { x: n.x, y: n.y };
      });
      return next;
    });
    setSelectedNode(null);
  }
  const dragRef = useRef<{
    id: string;
    nodeStartX: number;
    nodeStartY: number;
    svgStartX: number;
    svgStartY: number;
    moved: boolean;
  } | null>(null);

  function toSVGCoords(e: React.MouseEvent): { x: number; y: number } {
    if (!svgRef.current) return { x: 0, y: 0 };
    const pt = svgRef.current.createSVGPoint();
    pt.x = e.clientX;
    pt.y = e.clientY;
    const ctm = svgRef.current.getScreenCTM();
    if (!ctm) return { x: 0, y: 0 };
    const r = pt.matrixTransform(ctm.inverse());
    return { x: r.x, y: r.y };
  }

  function getConnected(id: string): Set<string> {
    const s = new Set<string>();
    liveEdges.forEach((e) => {
      if (e.from === id) s.add(e.to);
      if (e.to === id) s.add(e.from);
    });
    return s;
  }

  function isDimmed(nodeId: string): boolean {
    if (!selectedNode) return false;
    return nodeId !== selectedNode && !getConnected(selectedNode).has(nodeId);
  }

  function isEdgeDimmed(edge: GraphEdge): boolean {
    if (!selectedNode) return false;
    return edge.from !== selectedNode && edge.to !== selectedNode;
  }

  function handleNodeMouseDown(e: React.MouseEvent, nodeId: string) {
    e.stopPropagation();
    const svg = toSVGCoords(e);
    dragRef.current = {
      id: nodeId,
      nodeStartX: positions[nodeId].x,
      nodeStartY: positions[nodeId].y,
      svgStartX: svg.x,
      svgStartY: svg.y,
      moved: false,
    };
  }

  function handleSVGMouseMove(e: React.MouseEvent) {
    if (!dragRef.current) return;
    const svg = toSVGCoords(e);
    const dx = svg.x - dragRef.current.svgStartX;
    const dy = svg.y - dragRef.current.svgStartY;
    if (Math.abs(dx) + Math.abs(dy) > 3) dragRef.current.moved = true;
    setPositions((prev) => ({
      ...prev,
      [dragRef.current!.id]: {
        x: dragRef.current!.nodeStartX + dx,
        y: dragRef.current!.nodeStartY + dy,
      },
    }));
  }

  function handleSVGMouseUp() {
    dragRef.current = null;
  }

  function handleNodeClick(e: React.MouseEvent, node: GraphNode) {
    e.stopPropagation();
    if (dragRef.current?.moved) return;
    const next = selectedNode === node.id ? null : node.id;
    setSelectedNode(next);
    if (next && node.nctId) onTrialClick?.(node.nctId);
  }

  const renderedNodes = liveNodes.map((n) => ({ ...n, ...positions[n.id] }));
  const selectedNodeData = selectedNode ? liveNodes.find((n) => n.id === selectedNode) : null;
  const connected = selectedNode ? getConnected(selectedNode) : new Set<string>();

  if (liveNodes.length === 0) {
    return (
      <div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
          <span className="section-label">0 nodes · 0 edges</span>
        </div>
        <div style={{
          height: 435,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "var(--surface-1)",
          borderRadius: 8,
          border: "1px solid var(--border)",
        }}>
          <span style={{ fontFamily: "var(--text-mono)", fontSize: 11, color: "var(--text-dim)" }}>
            Run a query to build the knowledge graph
          </span>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
        <span className="section-label">
          {renderedNodes.length} nodes · {liveEdges.length} edges
        </span>
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          {selectedNode && (
            <Tag minimal intent={Intent.PRIMARY} onRemove={() => setSelectedNode(null)}>
              {selectedNodeData?.label}
            </Tag>
          )}
          <span style={{ fontFamily: "var(--text-mono)", fontSize: 9, color: "var(--text-dim)" }}>
            drag · click to select
          </span>
        </div>
      </div>

      <div style={{ position: "relative" }}>
        <svg
          ref={svgRef}
          viewBox="0 0 460 435"
          style={{
            width: "100%",
            background: "var(--surface-1)",
            borderRadius: 8,
            border: "1px solid var(--border)",
            userSelect: "none",
            display: "block",
          }}
          onMouseMove={handleSVGMouseMove}
          onMouseUp={handleSVGMouseUp}
          onMouseLeave={() => { handleSVGMouseUp(); setHoveredEdge(null); }}
          onClick={() => setSelectedNode(null)}
        >
          {/* Edges */}
          {liveEdges.map((edge, i) => {
            const f = positions[edge.from];
            const t = positions[edge.to];
            if (!f || !t) return null;
            const edgeDimmed = isEdgeDimmed(edge);
            const edgeActive = selectedNode && !edgeDimmed;
            const isHoveredEdge = hoveredEdge === i;
            const mx = (f.x + t.x) / 2;
            const my = (f.y + t.y) / 2;
            return (
              <g key={i} opacity={edgeDimmed ? 0.07 : 1}>
                <line
                  x1={f.x} y1={f.y}
                  x2={t.x} y2={t.y}
                  stroke={edgeActive || isHoveredEdge ? "var(--status-info)" : "var(--graph-edge)"}
                  strokeWidth={edgeActive || isHoveredEdge ? 1.5 : 1}
                />
                {/* Invisible wider hit area for edge hover */}
                <line
                  x1={f.x} y1={f.y}
                  x2={t.x} y2={t.y}
                  stroke="transparent"
                  strokeWidth={12}
                  style={{ cursor: "default" }}
                  onMouseEnter={() => setHoveredEdge(i)}
                  onMouseLeave={() => setHoveredEdge(null)}
                />
                {edge.label && (
                  <text
                    x={mx} y={my - 4}
                    textAnchor="middle"
                    fontSize={8}
                    fill={edgeActive || isHoveredEdge ? "var(--status-info)" : "var(--graph-edge)"}
                    fontFamily="monospace"
                    opacity={isHoveredEdge || (edgeActive ? 1 : 0) ? 1 : 0}
                    style={{
                      pointerEvents: "none",
                      transition: "opacity 0.15s",
                    }}
                  >
                    {edge.label}
                  </text>
                )}
              </g>
            );
          })}

          {/* Nodes */}
          {renderedNodes.map((node) => {
            const c = NODE_COLORS[node.type];
            const isSel = selectedNode === node.id;
            const isHov = hoveredNode === node.id;
            const isHighTrial = node.nctId === highlightedNct;
            const dimmed = isDimmed(node.id);
            return (
              <g
                key={node.id}
                opacity={dimmed ? 0.13 : 1}
                style={{ cursor: "grab" }}
                onMouseDown={(e) => handleNodeMouseDown(e, node.id)}
                onClick={(e) => handleNodeClick(e, node)}
                onMouseEnter={() => setHoveredNode(node.id)}
                onMouseLeave={() => setHoveredNode(null)}
              >
                <circle
                  cx={node.x} cy={node.y}
                  r={isSel ? 12 : isHighTrial ? 10 : 8}
                  fill={c.fill}
                  stroke={isSel || isHov || isHighTrial ? c.stroke : "var(--graph-node-border)"}
                  strokeWidth={isSel || isHighTrial ? 2 : 1}
                />
                {node.sublabel && (
                  <text
                    x={node.x} y={node.y + 2}
                    textAnchor="middle"
                    fontSize={7}
                    fill={c.text}
                    fontFamily="monospace"
                    opacity={0.7}
                    style={{ pointerEvents: "none" }}
                  >
                    {node.sublabel}
                  </text>
                )}
                <text
                  x={node.x} y={node.y + 22}
                  textAnchor="middle"
                  fontSize={9}
                  fill={isSel || isHov ? c.text : "var(--text-dim)"}
                  fontFamily="monospace"
                  style={{ pointerEvents: "none" }}
                >
                  {node.label.length > 14 ? node.label.slice(0, 13) + "…" : node.label}
                </text>
              </g>
            );
          })}
        </svg>

        {/* Legend — compact corner overlay */}
        <div
          style={{
            position: "absolute",
            bottom: 8,
            right: 8,
            display: "flex",
            flexDirection: "column",
            gap: 3,
            padding: "4px 7px",
            background: "var(--surface-1)",
            borderRadius: 6,
            border: "1px solid var(--border)",
            boxShadow: "var(--shadow-xs)",
            pointerEvents: "none",
          }}
        >
          {(["patient", "condition", "medication", "lab", "trial"] as NodeType[]).map((type) => (
            <div key={type} style={{ display: "flex", alignItems: "center", gap: 4 }}>
              <div style={{ width: 5, height: 5, borderRadius: "50%", background: NODE_COLORS[type].stroke, flexShrink: 0 }} />
              <span style={{ fontFamily: "var(--text-mono)", fontSize: 8, color: "var(--text-secondary)" }}>{type}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Node detail panel */}
      {selectedNodeData && (
        <div
          style={{
            marginTop: 8,
            padding: "8px 10px",
            background: "var(--surface-2)",
            border: "1px solid var(--border)",
            borderRadius: 2,
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 5 }}>
            <span style={{ fontFamily: "var(--text-mono)", fontSize: 11, color: "var(--text-primary)" }}>
              {selectedNodeData.label}
            </span>
            <Tag minimal style={{ fontFamily: "var(--text-mono)", fontSize: 9 }}>
              {selectedNodeData.type}
            </Tag>
          </div>
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap", alignItems: "center" }}>
            <span style={{ fontFamily: "var(--text-mono)", fontSize: 9, color: "var(--text-dim)" }}>
              connected:
            </span>
            {Array.from(connected).map((id) => {
              const n = liveNodes.find((x) => x.id === id);
              return n ? <Tag key={id} minimal style={{ fontSize: 9 }}>{n.label}</Tag> : null;
            })}
          </div>
          {selectedNodeData.nctId && (
            <div style={{ marginTop: 6 }}>
              <Tag
                intent={Intent.PRIMARY}
                minimal
                style={{ fontSize: 9, cursor: "pointer" }}
                onClick={() => onTrialClick?.(selectedNodeData.nctId!)}
              >
                jump to trial result →
              </Tag>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
