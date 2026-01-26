import { useCallback, useMemo, useEffect, useRef } from 'react'
import {
  ReactFlow,
  ReactFlowProvider,
  Node,
  Edge,
  Background,
  Controls,
  MiniMap,
  useReactFlow,
  Panel,
  MarkerType,
  Handle,
  Position,
  useNodesState,
  useEdgesState,
} from 'reactflow'
import 'reactflow/dist/style.css'
import dagre from 'dagre'
import './SemanticGraphViewer.css'

interface GraphNode {
  id: string
  url: string
  semantic_name?: string
  title?: string
  display_header?: string
  description?: string
  headers?: string[]
  primary_entity?: string
  components?: any[]
  active_apis?: string[]
  is_external?: boolean
  domain?: string
}

interface GraphEdge {
  from: string
  to: string
  action?: string
  selector?: string
  link_text?: string
  description?: string
  href?: string
  method?: string
  is_external?: boolean
}

interface SemanticGraph {
  nodes: GraphNode[]
  edges: GraphEdge[]
  api_endpoints?: Record<string, any>
  db_tables?: Record<string, any>
  entrypoints?: Record<string, string>  // persona name -> root node ID
}

interface SemanticGraphViewerProps {
  graph: SemanticGraph
}

// Custom Node Component
function CustomNode({ data }: { data: any }) {
  const { label, nodeColor } = data

  const tooltipSections: string[] = []
  
  if (data.is_external) tooltipSections.push(`🌐 External Link`)
  if (data.title) tooltipSections.push(`📄 ${data.title}`)
  if (data.display_header && data.display_header !== data.title) tooltipSections.push(`📌 ${data.display_header}`)
  if (data.url) tooltipSections.push(`🔗 ${data.url}`)
  if (data.domain && data.is_external) tooltipSections.push(`🌍 Domain: ${data.domain}`)
  if (data.description) {
    const shortDesc = data.description.length > 150 
      ? data.description.substring(0, 150) + '...' 
      : data.description
    tooltipSections.push(`📝 ${shortDesc}`)
  }
  if (data.primary_entity) tooltipSections.push(`🏷️ Entity: ${data.primary_entity}`)
  if (data.headers && data.headers.length > 0) {
    const topHeaders = data.headers.slice(0, 5).join(', ')
    const headerText = data.headers.length > 5 
      ? `${topHeaders}... (+${data.headers.length - 5} more)`
      : topHeaders
    tooltipSections.push(`📋 Headers: ${headerText}`)
  }
  if (data.components && data.components.length > 0) tooltipSections.push(`🧩 Components: ${data.components.length}`)
  if (data.active_apis && data.active_apis.length > 0) tooltipSections.push(`🔌 APIs: ${data.active_apis.length}`)

  return (
    <div className="custom-node-wrapper">
      <div
        className={`custom-node ${data.is_external ? 'external-node' : ''}`}
        style={{
          background: nodeColor,
          border: data.is_external ? '2px dashed #95a5a6' : '2px solid #2c3e50',
          borderRadius: '8px',
          padding: '12px 16px',
          minWidth: '120px',
          maxWidth: '220px',
          boxShadow: data.is_external ? '0 2px 8px rgba(149, 165, 166, 0.2)' : '0 4px 12px rgba(0, 0, 0, 0.15)',
          transition: 'all 0.2s ease',
          position: 'relative',
          opacity: data.is_external ? 0.85 : 1,
        }}
      >
        <Handle
          type="target"
          position={Position.Top}
          style={{ background: '#555', width: 8, height: 8, border: '2px solid #fff' }}
        />
        <div
          style={{
            color: '#ffffff',
            fontSize: '13px',
            fontWeight: '600',
            fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, sans-serif',
            textAlign: 'center',
            wordWrap: 'break-word',
            lineHeight: '1.4',
          }}
        >
          {label}
        </div>
        <Handle
          type="source"
          position={Position.Bottom}
          style={{ background: '#555', width: 8, height: 8, border: '2px solid #fff' }}
        />
      </div>
      <div className="node-tooltip">
        {tooltipSections.map((section, idx) => (
          <div key={idx} className="tooltip-line">{section}</div>
        ))}
      </div>
    </div>
  )
}

function PersonaNode({ data }: { data: any }) {
  const { label } = data
  return (
    <div
      className="persona-node"
      style={{
        background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
        border: '2px solid #fff',
        borderRadius: '20px',
        padding: '8px 16px',
        boxShadow: '0 4px 12px rgba(102, 126, 234, 0.35)',
        position: 'relative',
      }}
    >
      <div
        style={{
          color: '#ffffff',
          fontSize: '11px',
          fontWeight: '600',
          fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, sans-serif',
          textAlign: 'center',
          textTransform: 'uppercase',
          letterSpacing: '0.5px',
        }}
      >
        👤 {label}
      </div>
      <Handle
        type="source"
        position={Position.Bottom}
        style={{ background: '#764ba2', width: 8, height: 8, border: '2px solid #fff' }}
      />
    </div>
  )
}

const nodeTypes = {
  custom: CustomNode,
  persona: PersonaNode,
}

// Layout function 
function getLayoutedElements(nodes: Node[], edges: Edge[]) {
  const dagreGraph = new dagre.graphlib.Graph()
  dagreGraph.setDefaultEdgeLabel(() => ({}))

  dagreGraph.setGraph({ 
    rankdir: 'TB', 
    // Increased horizontal spacing to prevent overlap
    nodesep: 80, 
    // SIGNIFICANTLY Increased vertical spacing to accommodate the stagger offsets
    // If we stagger by up to 140px, we need ranksep > 140px to avoid collision with the next row
    ranksep: 300, 
    align: undefined,
    acyclicer: 'greedy', 
    ranker: 'longest-path' 
  })

  nodes.forEach((node) => {
    const isPersona = node.type === 'persona'
    const label = node.data?.label || ''
    const labelLength = label.length
    
    let nodeWidth = 180
    if (isPersona) {
      nodeWidth = 140
    } else {
      if (labelLength > 40) nodeWidth = 250
      else if (labelLength > 25) nodeWidth = 220
      else if (labelLength > 15) nodeWidth = 200
      else nodeWidth = 180
    }
    
    dagreGraph.setNode(node.id, { 
      width: nodeWidth,
      height: isPersona ? 50 : 80
    })
  })

  edges.forEach((edge) => {
    dagreGraph.setEdge(edge.source, edge.target)
  })

  dagre.layout(dagreGraph)

  // Identify "Level 2" nodes (Children of Home) for staggering
  const personaEdge = edges.find(e => e.source.startsWith('persona-'))
  const homeNodeId = personaEdge?.target
  
  const level2NodeIds = new Set(
    edges
      .filter(e => e.source === homeNodeId)
      .map(e => e.target)
  )

  const layoutedNodes = nodes.map((node) => {
    const nodeWithPosition = dagreGraph.node(node.id)
    
    const isPersona = node.type === 'persona'
    const label = node.data?.label || ''
    let nodeWidth = 180
    if (isPersona) {
      nodeWidth = 140
    } else if (label.length > 40) nodeWidth = 250
    else if (label.length > 25) nodeWidth = 220
    else if (label.length > 15) nodeWidth = 200

    // Staggering Logic
    let yOffset = 0
    if (level2NodeIds.has(node.id)) {
      const level2Array = Array.from(level2NodeIds)
      const index = level2Array.indexOf(node.id)
      // Stagger pattern: 0px -> 70px -> 140px (Reduced step size to be safer)
      yOffset = (index % 3) * 70
    }
    
    return {
      ...node,
      targetPosition: Position.Top,
      sourcePosition: Position.Bottom,
      position: {
        x: nodeWithPosition.x - (nodeWidth / 2),
        y: nodeWithPosition.y - 40 + yOffset,
      },
    }
  })

  return { nodes: layoutedNodes, edges }
}

function SemanticGraphViewerInner({ graph }: SemanticGraphViewerProps) {
  const { setCenter, fitView } = useReactFlow()

  const uniqueNodes = useMemo(() => {
    const seenIds = new Set<string>()
    return graph.nodes.filter((node) => {
      if (seenIds.has(node.id)) return false
      seenIds.add(node.id)
      return true
    })
  }, [graph.nodes])

  const urlToNodeId = useMemo(() => {
    const mapping: Record<string, string> = {}
    uniqueNodes.forEach((node) => {
      mapping[node.url] = node.id
      mapping[node.id] = node.id
    })
    return mapping
  }, [uniqueNodes])

  const personaEntrypoints = useMemo(() => {
    return graph.entrypoints || {}
  }, [graph.entrypoints])

  const rootNodeIds = useMemo(() => {
    return new Set(Object.values(personaEntrypoints))
  }, [personaEntrypoints])

  const reactFlowNodes = useMemo(() => {
    const nodes: Node[] = []

    Object.entries(personaEntrypoints).forEach(([personaName, _rootNodeId]) => {
      nodes.push({
        id: `persona-${personaName}`,
        type: 'persona',
        data: { label: personaName },
        position: { x: 0, y: 0 },
      })
    })

    uniqueNodes.forEach((node) => {
      let isHomePage = false
      try {
        const urlPath = new URL(node.url).pathname
        isHomePage = urlPath === '/' || urlPath === ''
      } catch {
        isHomePage = node.url.endsWith('/') && !node.url.replace(/^https?:\/\//, '').split('/').filter(Boolean).slice(1).length
      }
      const label = isHomePage 
        ? (node.title || node.semantic_name || node.id)
        : (node.display_header || node.semantic_name || node.id)
      
      const displayLabel = (node.is_external ? '🌐 ' : '') + 
        (label.length > 35 ? label.substring(0, 35) + '...' : label)

      let nodeColor = '#4a90e2'
      if (node.is_external) nodeColor = '#95a5a6'
      else if (rootNodeIds.has(node.id)) nodeColor = '#50c878'
      else if (node.primary_entity) nodeColor = '#646cff'
      else if (node.components && node.components.length > 10) nodeColor = '#50c878'
      else if (node.active_apis && node.active_apis.length > 0) nodeColor = '#ff6b6b'

      nodes.push({
        id: node.id,
        type: 'custom',
        data: { label: displayLabel, nodeColor, ...node },
        position: { x: 0, y: 0 },
      })
    })

    return nodes
  }, [uniqueNodes, personaEntrypoints, rootNodeIds])

  const validNodeIds = useMemo(() => {
    const ids = new Set<string>()
    Object.keys(personaEntrypoints).forEach((personaName) => ids.add(`persona-${personaName}`))
    uniqueNodes.forEach((node) => ids.add(node.id))
    return ids
  }, [personaEntrypoints, uniqueNodes])

  const reactFlowEdges = useMemo(() => {
    const edges: Edge[] = []

    Object.entries(personaEntrypoints).forEach(([personaName, rootNodeId]) => {
      if (validNodeIds.has(rootNodeId)) {
        edges.push({
          id: `persona-edge-${personaName}`,
          source: `persona-${personaName}`,
          target: rootNodeId,
          label: 'Entry',
          labelStyle: { fill: '#764ba2', fontWeight: 700, fontSize: 10, fontFamily: 'Inter, sans-serif' },
          labelBgPadding: [8, 4] as [number, number],
          labelBgBorderRadius: 6,
          labelBgStyle: { fill: '#f0e6fa', stroke: '#764ba2', strokeWidth: 1.5 },
          style: { stroke: '#764ba2', strokeWidth: 3, strokeDasharray: '8,4' },
          markerEnd: { type: MarkerType.ArrowClosed, color: '#764ba2', width: 14, height: 14 },
          type: 'default',
          animated: true,
        })
      }
    })

    graph.edges.forEach((edge, index) => {
      const fromId = urlToNodeId[edge.from] || edge.from
      const toId = urlToNodeId[edge.to] || edge.to
      if (!validNodeIds.has(fromId) || !validNodeIds.has(toId)) return

      let label = ''
      // Priority 1: Use selector if available (especially ID-based selectors for stability)
      // This ensures we show stable selectors like "a#legend-link-renewals" instead of dynamic text
      if (edge.selector) {
        // For ID-based selectors (e.g., "a#legend-link-renewals"), show just the ID part for cleaner display
        // For other selectors, show the full selector
        if (edge.selector.startsWith('a#')) {
          label = edge.selector.substring(2) // Remove "a#" prefix, show just "legend-link-renewals"
        } else if (edge.selector.startsWith('#')) {
          label = edge.selector.substring(1) // Remove "#" prefix
        } else {
          label = edge.selector
        }
      } else if (edge.link_text) {
        label = edge.link_text
      } else if (edge.description) {
        label = edge.description
      } else if (edge.href) {
        const path = edge.href.split('/').pop() || edge.href
        label = path.length > 20 ? path.substring(0, 20) + '...' : path
      } else if (edge.action) {
        if (edge.action === 'click_js_nav') label = 'Navigate'
        else if (edge.action === 'navigate') label = 'Navigate'
        else label = edge.action.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase())
      } else label = 'Navigate'

      let edgeColor = '#5a6c7d'
      let strokeDasharray: string | undefined = undefined
      
      if (edge.is_external) {
        edgeColor = '#95a5a6'
        strokeDasharray = '8,4'
        if (!label.startsWith('🌐')) label = '🌐 ' + label
      } else if (edge.action === 'click_js_nav') edgeColor = '#2980b9'
      else if (edge.action === 'navigate') edgeColor = '#7f8c8d'

      edges.push({
        id: `edge-${index}`,
        source: fromId,
        target: toId,
        label,
        labelStyle: { fill: edge.is_external ? '#7f8c8d' : '#1a1a2e', fontWeight: 700, fontSize: 11, fontFamily: 'Inter, sans-serif' },
        labelBgPadding: [10, 6] as [number, number],
        labelBgBorderRadius: 6,
        labelBgStyle: { fill: edge.is_external ? '#ecf0f1' : '#f8f9fa', stroke: edge.is_external ? '#95a5a6' : '#3498db', strokeWidth: 1.5 },
        style: { stroke: edgeColor, strokeWidth: 3, strokeDasharray },
        markerEnd: { type: MarkerType.ArrowClosed, color: edgeColor, width: 16, height: 16 },
        type: 'default',
        animated: false,
      })
    })

    return edges
  }, [graph.edges, urlToNodeId, validNodeIds, personaEntrypoints])

  const initialLayout = useMemo(() => {
    return getLayoutedElements(reactFlowNodes, reactFlowEdges)
  }, [reactFlowNodes, reactFlowEdges])

  const [nodes, setNodes, onNodesChange] = useNodesState(initialLayout.nodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialLayout.edges)
  
  // Store base positions (snapshot when layout is applied or drag ends)
  const basePositionsRef = useRef<Record<string, { x: number; y: number }>>({})
  const draggingNodeRef = useRef<string | null>(null)
  
  // Update base positions when layout changes
  useEffect(() => {
    const positions: Record<string, { x: number; y: number }> = {}
    nodes.forEach(node => {
      positions[node.id] = { x: node.position.x, y: node.position.y }
    })
    basePositionsRef.current = positions
  }, [reactFlowNodes, reactFlowEdges]) // Update when graph data changes
  
  // Find all child nodes recursively (nodes connected via outgoing edges)
  const getChildNodes = useCallback((nodeId: string, visited = new Set<string>()): string[] => {
    if (visited.has(nodeId)) return []
    visited.add(nodeId)
    
    const children: string[] = []
    edges.forEach(edge => {
      if (edge.source === nodeId && !visited.has(edge.target)) {
        children.push(edge.target)
        // Recursively get children of children
        children.push(...getChildNodes(edge.target, visited))
      }
    })
    return children
  }, [edges])
  
  // Custom nodes change handler to track drag start/end
  const handleNodesChange = useCallback((changes: any[]) => {
    // Check if any change is a position change (drag)
    const positionChanges = changes.filter(c => c.type === 'position' && c.dragging !== undefined)
    
    if (positionChanges.length > 0) {
      const dragChange = positionChanges[0]
      
      // Drag started
      if (dragChange.dragging === true && draggingNodeRef.current === null) {
        draggingNodeRef.current = dragChange.id
        // Snapshot current positions as base
        const positions: Record<string, { x: number; y: number }> = {}
        nodes.forEach(node => {
          positions[node.id] = { x: node.position.x, y: node.position.y }
        })
        basePositionsRef.current = positions
      }
      
      // Drag ended
      if (dragChange.dragging === false) {
        draggingNodeRef.current = null
        // Update base positions to new positions
        setNodes((nds) => {
          const newPositions: Record<string, { x: number; y: number }> = {}
          nds.forEach(node => {
            newPositions[node.id] = { x: node.position.x, y: node.position.y }
          })
          basePositionsRef.current = newPositions
          return nds
        })
      }
    }
    
    // Call original handler
    onNodesChange(changes)
  }, [nodes, onNodesChange, setNodes])
  
  // Handle node drag - move child nodes along with parent
  const onNodeDrag = useCallback((_event: React.MouseEvent, node: Node) => {
    if (draggingNodeRef.current !== node.id) return
    
    const childNodeIds = getChildNodes(node.id)
    if (childNodeIds.length === 0) return
    
    // Get base position of dragged node
    const basePos = basePositionsRef.current[node.id]
    if (!basePos) return
    
    // Calculate the offset from base position
    const offsetX = node.position.x - basePos.x
    const offsetY = node.position.y - basePos.y
    
    // Update child node positions maintaining relative positions
    setNodes((nds) =>
      nds.map((n) => {
        if (childNodeIds.includes(n.id)) {
          const childBasePos = basePositionsRef.current[n.id]
          if (childBasePos) {
            return {
              ...n,
              position: {
                x: childBasePos.x + offsetX,
                y: childBasePos.y + offsetY,
              },
            }
          }
        }
        return n
      })
    )
  }, [getChildNodes, setNodes])

  useEffect(() => {
    const result = getLayoutedElements(reactFlowNodes, reactFlowEdges)
    setNodes(result.nodes)
    setEdges(result.edges)
  }, [reactFlowNodes, reactFlowEdges, setNodes, setEdges])

  // Smart Zoom Effect
  useEffect(() => {
    if (nodes.length > 0) {
      const personaNode = nodes.find(n => n.type === 'persona')
      const personaEdge = edges.find(e => e.source === personaNode?.id)
      const homeNode = nodes.find(n => n.id === personaEdge?.target)

      if (personaNode && homeNode) {
        const midX = (personaNode.position.x + homeNode.position.x) / 2
        const midY = (personaNode.position.y + homeNode.position.y) / 2 + 50 

        setTimeout(() => {
          // Reduced zoom level to 0.85 (was 1.1) to show more context and less "in your face"
          setCenter(midX, midY, { zoom: 0.85, duration: 1000 })
        }, 100)
      } else {
        setTimeout(() => {
          fitView({ padding: 0.2, duration: 800, maxZoom: 1.5 })
        }, 100)
      }
    }
  }, [nodes.length, edges.length, setCenter, fitView])

  const onNodeClick = useCallback((_event: React.MouseEvent, node: Node) => {
    console.log('Node clicked:', node)
  }, [])

  if (!graph.nodes.length) {
    return (
      <div className="graph-viewer-empty">
        <p>⚠️ No graph data available</p>
      </div>
    )
  }

  return (
    <div className="graph-viewer-container">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={handleNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeDrag={onNodeDrag}
        nodeTypes={nodeTypes}
        onNodeClick={onNodeClick}
        nodesDraggable={true}
        nodesConnectable={false}
        minZoom={0.05} 
        maxZoom={2}
        defaultEdgeOptions={{
          style: { strokeWidth: 2.5 },
          markerEnd: { type: MarkerType.ArrowClosed },
        }}
      >
        <Background color="#e0e0e0" gap={16} />
        <Controls showInteractive={false} />
        <MiniMap
          nodeColor={(node: Node) => {
            const data = node.data as any
            return data.nodeColor || '#4a90e2'
          }}
          maskColor="rgba(0, 0, 0, 0.1)"
        />
        <Panel position="top-right" className="graph-stats">
          <span>Nodes: {graph.nodes.length}</span>
          <span>Edges: {graph.edges.length}</span>
        </Panel>
      </ReactFlow>
    </div>
  )
}

function SemanticGraphViewer({ graph }: SemanticGraphViewerProps) {
  return (
    <ReactFlowProvider>
      <SemanticGraphViewerInner graph={graph} />
    </ReactFlowProvider>
  )
}

export default SemanticGraphViewer