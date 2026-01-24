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
  getSemanticGraph: async (persona?: string, projectId?: string): Promise<any> => {
    const params = new URLSearchParams()
    if (persona) params.append('persona', persona)
    if (projectId) params.append('project_id', projectId)
    const queryString = params.toString()
    const url = `/semantic-graph${queryString ? `?${queryString}` : ''}`
    const response = await client.get(url)
    return response.data
  },

  // Projects
  getProjects: async (): Promise<Project[]> => {
    const response = await client.get('/api/projects')
    return response.data
  },

  getProject: async (projectId: string): Promise<Project> => {
    const response = await client.get(`/api/projects/${projectId}`)
    return response.data
  },

  createProject: async (data: ProjectCreate): Promise<Project> => {
    const response = await client.post('/api/projects', data)
    return response.data
  },

  updateProject: async (projectId: string, data: ProjectUpdate): Promise<Project> => {
    const response = await client.put(`/api/projects/${projectId}`, data)
    return response.data
  },

  deleteProject: async (projectId: string): Promise<void> => {
    await client.delete(`/api/projects/${projectId}`)
  },

  getProjectTasks: async (projectId: string): Promise<Task[]> => {
    const response = await client.get(`/api/projects/${projectId}/tasks`)
    return response.data
  },

  regenerateSemanticMaps: async (projectId: string, headless: boolean = true): Promise<{ execution_id: string; message: string; personas: string[] }> => {
    const response = await client.post(`/api/projects/${projectId}/regenerate-semantic-maps`, {
      headless
    })
    return response.data
  },

  // Task CRUD (for future Jira integration)
  createTask: async (data: TaskCreate): Promise<Task> => {
    const response = await client.post('/api/tasks', data)
    return response.data
  },

  updateTask: async (taskId: string, data: TaskUpdate): Promise<Task> => {
    const response = await client.put(`/api/tasks/${taskId}`, data)
    return response.data
  },

  deleteTask: async (taskId: string): Promise<void> => {
    await client.delete(`/api/tasks/${taskId}`)
  },
}

export interface TaskCreate {
  project_id: string
  title: string
  description: string
  pr_link?: string
  file_path?: string
}

export interface TaskUpdate {
  title?: string
  description?: string
  pr_link?: string
  file_path?: string
}

export interface Persona {
  name: string
  gateway_instructions: string
}

export interface Project {
  id: string
  name: string
  description?: string
  ui_url: string
  api_base_url?: string
  openapi_url?: string
  database_url?: string
  backend_path?: string
  personas: Persona[]
  created_at?: string
  updated_at?: string
}

export interface ProjectCreate {
  name: string
  description?: string
  ui_url: string
  api_base_url?: string
  openapi_url?: string
  database_url?: string
  backend_path?: string
  personas?: Persona[]
}

export interface ProjectUpdate {
  name?: string
  description?: string
  ui_url?: string
  api_base_url?: string
  openapi_url?: string
  database_url?: string
  backend_path?: string
  personas?: Persona[]
}

export default client
