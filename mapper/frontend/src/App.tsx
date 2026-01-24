import { Routes, Route } from 'react-router-dom'
import Navigation from './components/Navigation'
import ProjectsPage from './pages/ProjectsPage'
import ProjectDetailPage from './pages/ProjectDetailPage'
import TaskDetailPage from './pages/TaskDetailPage'
import ExecutionsPage from './pages/ExecutionsPage'
import GraphViewPage from './pages/GraphViewPage'
import './App.css'

function App() {
  return (
    <div className="app">
      <Navigation />
      <Routes>
        <Route path="/" element={<ProjectsPage />} />
        <Route path="/projects/:projectId" element={<ProjectDetailPage />} />
        <Route path="/projects/:projectId/tasks/:taskId" element={<TaskDetailPage />} />
        <Route path="/executions" element={<ExecutionsPage />} />
        <Route path="/graph" element={<GraphViewPage />} />
      </Routes>
    </div>
  )
}

export default App
