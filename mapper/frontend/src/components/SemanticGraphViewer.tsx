import { useEffect, useRef } from 'react'
import { Network } from 'vis-network'
import 'vis-network/styles/vis-network.min.css'
import './SemanticGraphViewer.css'

interface Node {
  id: string
  url: string
  semantic_name?: string
  title?: string
  display_header?: string
  primary_entity?: string
  components?: any[]
  active_apis?: string[]
}

interface Edge {
  from: string
  to: string
  action?: string
  selector?: string
}

interface SemanticGraph {
  nodes: Node[]
  edges: Edge[]
  api_endpoints?: Record<string, any>
  db_tables?: Record<string, any>
}

interface SemanticGraphViewerProps {
  graph: SemanticGraph
}

function SemanticGraphViewer({ graph }: SemanticGraphViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const networkRef = useRef<Network | null>(null)

  useEffect(() => {
    if (!containerRef.current || !graph.nodes.length) return

    // Deduplicate nodes by ID (keep first occurrence)
    const seenIds = new Set<string>()
    const uniqueNodes = graph.nodes.filter((node) => {
      if (seenIds.has(node.id)) {
        return false
      }
      seenIds.add(node.id)
      return true
    })

    // Create nodes for vis-network
    const nodes = uniqueNodes.map((node) => {
      // Use display_header if available, otherwise fallback to semantic_name or id
      const label = node.display_header || node.semantic_name || node.id
      const title = [
        `URL: ${node.url}`,
        node.display_header ? `Header: ${node.display_header}` : '',
        node.title ? `Title: ${node.title}` : '',
        node.primary_entity ? `Entity: ${node.primary_entity}` : '',
        node.components ? `Components: ${node.components.length}` : '',
        node.active_apis ? `APIs: ${node.active_apis.length}` : '',
      ]
        .filter(Boolean)
        .join('\n')

      return {
        id: node.id,
        label: label.length > 30 ? label.substring(0, 30) + '...' : label,
        title: title,
        color: {
          background: node.primary_entity ? '#646cff' : '#999',
          border: '#333',
          highlight: {
            background: '#535bf2',
            border: '#333',
          },
        },
        shape: 'box',
        font: {
          size: 14,
          color: '#333',
        },
      }
    })

    // Create edges for vis-network
    // First, create a mapping of URL to node ID (using unique nodes)
    const urlToNodeId: Record<string, string> = {}
    uniqueNodes.forEach((node) => {
      urlToNodeId[node.url] = node.id
      urlToNodeId[node.id] = node.id // Also map ID to itself
    })

    const edges = graph.edges
      .map((edge, index) => {
        // Find source and target node IDs
        const fromId = urlToNodeId[edge.from] || edge.from
        const toId = urlToNodeId[edge.to] || edge.to

        // Only create edge if both nodes exist
        if (!nodes.some((n) => n.id === fromId) || !nodes.some((n) => n.id === toId)) {
          return null
        }

        return {
          id: `edge-${index}`,
          from: fromId,
          to: toId,
          label: edge.action || '',
          arrows: 'to',
          color: {
            color: '#999',
            highlight: '#646cff',
          },
          smooth: {
            type: 'curvedCW',
            roundness: 0.2,
          },
        }
      })
      .filter((e): e is NonNullable<typeof e> => e !== null)

    const data = {
      nodes: nodes,
      edges: edges,
    }

    const options = {
      nodes: {
        shape: 'box',
        margin: 10,
        widthConstraint: {
          maximum: 200,
        },
        heightConstraint: {
          maximum: 100,
        },
      },
      edges: {
        arrows: {
          to: {
            enabled: true,
            scaleFactor: 0.5,
          },
        },
        font: {
          size: 12,
          align: 'middle',
        },
        smooth: {
          type: 'curvedCW',
          roundness: 0.3,
        },
      },
      layout: {
        hierarchical: {
          enabled: true,
          direction: 'LR', // Left to Right
          sortMethod: 'directed', // Use edge direction for sorting
          nodeSpacing: 250, // Horizontal spacing between nodes
          levelSeparation: 180, // Vertical spacing between levels
          treeSpacing: 250, // Spacing between different trees
          blockShifting: true,
          edgeMinimization: false, // Disable edge minimization to allow curves
          parentCentralization: true,
        },
      },
      physics: {
        enabled: false, // Disable physics for hierarchical layout
      },
      interaction: {
        hover: true,
        tooltipDelay: 100,
        zoomView: true,
        dragView: true,
        dragNodes: true, // Allow manual repositioning if needed
      },
    }

    // Create network with error handling
    try {
      const network = new Network(containerRef.current, data, options)
      networkRef.current = network

      // Handle node click to show details
      network.on('click', (params) => {
        if (params.nodes.length > 0) {
          const nodeId = params.nodes[0]
          const node = uniqueNodes.find((n) => n.id === nodeId)
          if (node) {
            console.log('Node clicked:', node)
          }
        }
      })

      return () => {
        if (networkRef.current) {
          networkRef.current.destroy()
          networkRef.current = null
        }
      }
    } catch (error) {
      console.error('Error creating network visualization:', error)
      return () => {}
    }
  }, [graph])

  if (!graph.nodes.length) {
    return (
      <div className="graph-viewer-empty">
        <p>⚠️ No graph data available</p>
        <p className="empty-hint">
          The semantic mapper didn't discover any nodes. Make sure:
          <ul>
            <li>The target app is running at <code>http://localhost:5173</code></li>
            <li>The browser can connect to the app</li>
            <li>Check the execution output for errors</li>
          </ul>
        </p>
      </div>
    )
  }

  return (
    <div className="graph-viewer-container">
      <div className="graph-stats">
        <span>Nodes: {graph.nodes.length}</span>
        <span>Edges: {graph.edges.length}</span>
      </div>
      <div ref={containerRef} className="graph-canvas" />
    </div>
  )
}

export default SemanticGraphViewer
