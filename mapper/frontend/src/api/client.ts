import axios from 'axios'

const API_BASE_URL = import.meta.env.VITE_API_URL || '/api'

const client = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
})

export interface Task {
  id: string
  title: string
  description: string
  pr_link?: string
  file_path: string
  created_at?: string
  updated_at?: string
}

export interface Execution {
  execution_id: string
  task_id: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  started_at: string
  completed_at?: string
  execution_type: 'map' | 'generate-mission' | 'execute'
  result?: any
  error?: string
}

export const api = {
  // Tasks
  getTasks: async (): Promise<Task[]> => {
    const response = await client.get('/tasks')
    return response.data
  },

  getTask: async (taskId: string): Promise<Task> => {
    const response = await client.get(`/tasks/${taskId}`)
    return response.data
  },

  runTaskOperation: async (
    taskId: string,
    operation: 'map' | 'generate-mission' | 'execute',
    options?: Record<string, any>
  ): Promise<Execution> => {
    const response = await client.post(`/tasks/${taskId}/run`, {
      operation,
      options,
    })
    return response.data
  },

  runAutomatedWorkflow: async (taskId: string): Promise<Execution> => {
    const response = await client.post(`/tasks/${taskId}/run-automated`)
    return response.data
  },

  // Executions
  getExecutions: async (taskId?: string): Promise<Execution[]> => {
    const params = taskId ? { task_id: taskId } : {}
    const response = await client.get('/executions', { params })
    return response.data
  },

  getExecution: async (executionId: string): Promise<Execution> => {
    const response = await client.get(`/executions/${executionId}`)
    return response.data
  },

  // Semantic Graph
  getSemanticGraph: async (): Promise<any> => {
    const response = await client.get('/semantic-graph')
    return response.data
  },
}

export default client
